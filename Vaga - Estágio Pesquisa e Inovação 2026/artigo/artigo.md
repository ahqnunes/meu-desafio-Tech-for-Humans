# Índices B-tree: resultados sob cargas controladas

## 1. Resumo

Em duas séries de três pares, índices B-tree elevaram o throughput mediano sob 20 VUs: 2,71→4,83 req/s para `itens_pedido(pedido_id)` e 4,86→5,77 para `pedidos(cliente_id, criado_em DESC, id DESC)`. O contrato foi mantido e os planos usaram os índices. Como a ordem foi sempre sem→com índice, a deriva temporal não está controlada; os resultados são favoráveis, mas não provam causalidade nem se generalizam.

## 2. Contexto e diagnóstico

A aplicação usa Node.js 20, Express e PostgreSQL 16 em containers. O conjunto sintético contém 100 mil clientes, 20 mil produtos, 500 mil pedidos e aproximadamente 1,5 milhão de itens. O perfil k6 dá maior peso a consultas de cliente, pedidos, e-mail e busca de produtos. A linha de base foi medida três vezes, com 20 VUs, 60 segundos nominais, 15 segundos de aquecimento e seed 42. A taxa mediana foi 2,62 req/s e o p95 geral 24,8 s; cada execução manteve o contrato e registrou zero erros.

Os planos salvos em `diagnostico/planos-consultas.txt` mostraram varredura sequencial da tabela de itens ao buscar os itens de um pedido. A rota `/clientes/:id/pedidos`, em `api/src/rotas.js`, também consulta itens dentro de um loop de pedidos e produtos dentro de outro loop. `api/src/db.js` abre e fecha uma conexão por chamada. São mecanismos plausíveis de trabalho repetido, mas as capturas isoladas não provam quanto cada um contribui para a carga total.

**Hipótese do experimento:** um índice B-tree em `itens_pedido(pedido_id)` reduziria o trabalho para localizar itens de cada pedido. O diagnóstico completo, incluindo parâmetros e limitações dos planos, está em [relatorio.md](../diagnostico/relatorio.md).

## 3. Estado da arte

### Índices e busca

A documentação do PostgreSQL explica que índices podem evitar varreduras completas em buscas seletivas, mas adicionam armazenamento e custo de manutenção em escrita [1]. Índices multicoluna dependem da ordem das colunas, então a escolha deve corresponder aos filtros e à ordenação reais [2]. Para busca por substring, `pg_trgm` oferece suporte indexado a `LIKE` e `ILIKE`; o benefício depende dos trigramas extraídos e da seletividade [3]. O GitLab relatou bons resultados com GIN trigram em seu produto, em troca de índice maior e construção mais lenta [4]. É uma experiência de 2016, em outro conjunto de dados, não uma previsão para este catálogo.

### Consultas da API e pré-computação

Yang et al. estudaram bugs de desempenho em aplicações Rails e descrevem um caso N+1 do Lobsters em que a página passou de 1,10 s para 0,34 s após consolidar consultas [5]. Os ganhos agregados do paper incluem correções de outros tipos e não devem ser atribuídos ao N+1 nem projetados para esta API. A documentação do `node-postgres` recomenda pooling para reutilizar conexões e limitar clientes simultâneos [6]. Para relatórios, a documentação do PostgreSQL diz que views materializadas persistem resultados e podem acelerar leituras, mas exigem refresh e podem servir dados desatualizados [7]. Cada abordagem envolve custos e riscos próprios.

## 4. Alternativas consideradas

| Abordagem | Custo | Desempenho esperado | Risco | Esforço |
|---|---|---|---|---|
| Índices B-tree/expressão | Armazenamento e manutenção na escrita | Menos trabalho em filtros e joins seletivos; medir por rota | Planner pode não usar; mais espaço | Baixo–médio |
| Reescrever N+1 e usar pool | Menos round trips; conexões limitadas em memória | Pode reduzir consultas repetidas e custo de conexão | Alterar ordem/conteúdo ou dimensionar mal o pool | Médio |
| View materializada/cache | Espaço e CPU para refresh/invalidação | Pode baratear leituras repetidas de relatórios | Dado obsoleto e consistência | Médio–alto |
| Ajustar configuração/limites | Mais CPU/RAM custa mais; limites menores arriscam throttling/OOM | Depende de plano, concorrência e carga; medir | Aumentar recurso pode apenas aumentar custo | Baixo–médio |

As opções têm custos e mecanismos diferentes. Índices acrescentam espaço e manutenção de escrita [1]; consolidar consultas e usar pool exigem provar igualdade da resposta [5][6]; materialização envolve atualização e frescor [7]. Limites podem causar throttling/OOM e `work_mem` multiplica consumo por operação e sessão [8][9]. O plano observado favoreceu testar primeiro um índice localizado; as demais alternativas ficaram para experimentos próprios, sem serem descartadas universalmente.

## 5. Solução escolhida e por quê

Comecei pelos dois índices em mudanças SQL isoladas, sem alterar a API. Depois removi o N+1 da rota `/clientes/:id/pedidos` com uma consulta `JOIN`, mantendo a resposta; o pool foi testado em etapa separada. A repetição da remoção do N+1 não confirmou o ganho da série inicial e foi inconclusiva. O pool apresentou um trade-off entre throughput agregado e latência da rota-alvo. Não priorizei `pg_trgm` porque a busca de produtos teve menor custo isolado que os gargalos de pedidos e relatórios; materialização e aumento de recursos ainda exigem justificar custos de atualização e operação.

## 6. Experimento e resultado

| Variante | Req/s por rodada | Mediana req/s | p95 por rodada (ms) | Mediana p95 (ms) |
|---|---|---:|---|---:|
| Sem índice | 2,71 / 2,77 / 2,55 | 2,71 | 23.586,6 / 23.724,1 / 25.501,5 | 23.724,1 |
| Com índice | 4,83 / 4,48 / 4,91 | 4,83 | 12.002,6 / 12.888,6 / 11.382,1 | 12.002,6 |

O contraste entre `9b6b69c` e `59124a7` isolou o arquivo SQL: API, carga e dados determinísticos foram mantidos. Após preliminares, a série usou três pares sempre sem→com índice, volumes novos e containers externos pausados; foram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. O contrato passou e houve zero erros. A ordem fixa permite deriva temporal confundida; as pastas e exclusões estão em [experimentos.md](../experimentos.md).

Na mediana, o throughput aumentou 78,1% e o p95 caiu 49,4%; o índice ocupa 21 MB e aparece no plano posterior. O recálculo direto dos CSVs não indica economia geral: as médias de CPU e memória da API e a memória média do banco aumentaram, enquanto a média de CPU do banco ficou estável. São observações descritivas, sem normalização por requisição. Os detalhes e resultados por rota estão em [experimentos.md](../experimentos.md).

O segundo experimento testou `pedidos(cliente_id, criado_em DESC, id DESC)`. O baseline já continha o índice de itens; a série mediu o índice novo em três pares, sempre sem→com, com os mesmos parâmetros e contrato. O throughput mediano passou de 4,86 para 5,77 req/s; o p95 geral, de 11.374,7 para 10.165,1 ms; o p95 da rota, de 12.305,5 para 8.551,4 ms. Não houve erros nas seis rodadas principais. O plano mudou de `Parallel Seq Scan` com sort para `Index Scan`; o índice ocupa 19 MB. Os caches dos planos diferiam; os dados completos estão em [experimentos.md](../experimentos.md).

Uma repetição posterior da remoção do N+1 usou worktrees limpos e código commitado. O throughput mediano passou de 4,14 para 3,20 req/s (−22,7%), enquanto o p95 geral aumentou 44,2% e o p95 da rota, 78,2%. As faixas se sobrepõem, os pares divergem e houve um timeout em cada braço do primeiro par; portanto, esta repetição é inconclusiva e substitui a série anterior como evidência principal. O contrato passou em todas as rodadas.

O pool de até 10 conexões foi medido separadamente sobre a versão sem N+1. O throughput mediano aumentou 29,8% e o p95 geral caiu 51,6%, mas a latência mediana geral aumentou 143,1% e o p95 de `pedidos-do-cliente` aumentou 53,3%. Os três pares favoreceram throughput e p95 geral e pioraram o p95 da rota-alvo. É um trade-off para este perfil de carga, não uma melhora uniforme; não houve erros k6 e o contrato passou.

## 7. Limites e testes futuros

As séries têm três rodadas por variante, uma máquina e um perfil sintético; não se mediu custo por requisição. A ordem balanceada reduz, mas não elimina, deriva temporal. A repetição do N+1 foi inconclusiva: medianas e pares divergem e há um timeout em cada braço do primeiro par. O pool elevou throughput em 29,8% e reduziu p95 geral em 51,6%, mas aumentou latência mediana geral em 143,1% e p95 da rota em 53,3%. O diagnóstico de 2 versus 20 VUs mostrou throughput quase estável (3,39→3,61 req/s) e latência maior, mas não separa execução de espera. Recursos foram recalculados dos CSVs e são observacionais; `scripts/` permaneceu intacto. Os dados e próximos testes estão em [experimentos.md](../experimentos.md) e [proximos-testes.md](../proximos-testes.md).

## 8. Referências

1. PostgreSQL Global Development Group. [Indexes — Introduction, PostgreSQL 16](https://www.postgresql.org/docs/16/indexes-intro.html). Acesso em 12 nov. 2026.
2. PostgreSQL Global Development Group. [Multicolumn Indexes, PostgreSQL 16](https://www.postgresql.org/docs/16/indexes-multicolumn.html). Acesso em 12 nov. 2026.
3. PostgreSQL Global Development Group. [pg_trgm, PostgreSQL 16](https://www.postgresql.org/docs/16/pgtrgm.html). Acesso em 12 nov. 2026.
4. GitLab. [Fast Search Using PostgreSQL Trigram Text Indexes](https://about.gitlab.com/blog/fast-search-using-postgresql-trigram/). 2016. Acesso em 12 nov. 2026.
5. Yang, J. et al. [How not to structure your database-backed web applications: a study of performance bugs in the wild](https://par.nsf.gov/servlets/purl/10067547). ICSE, 2018, p. 800–810. Acesso em 12 nov. 2026.
6. node-postgres contributors. [Pooling](https://node-postgres.com/features/pooling). Acesso em 12 nov. 2026.
7. PostgreSQL Global Development Group. [Materialized Views, PostgreSQL 16](https://www.postgresql.org/docs/16/rules-materializedviews.html). Acesso em 12 nov. 2026.
8. Docker. [Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/). Acesso em 12 nov. 2026.
9. PostgreSQL Global Development Group. [Resource Consumption, PostgreSQL 16](https://www.postgresql.org/docs/16/runtime-config-resource.html). Acesso em 12 nov. 2026.

## 9. Uso de IA

Usei IA como apoio para organizar hipóteses, revisar cálculos e redigir este artigo. Conferi as fontes citadas, os planos salvos e as métricas nos arquivos JSON e CSV do repositório; as limitações e incertezas foram mantidas explicitamente.
