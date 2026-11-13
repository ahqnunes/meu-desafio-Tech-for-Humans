# Índices B-tree: resultados sob cargas controladas

## 1. Resumo

Em duas comparações alternadas, índices B-tree elevaram o throughput mediano sob 20 usuários virtuais. Para `itens_pedido(pedido_id)`, passou de 2,71 para 4,83 req/s (+78,1%); para `pedidos(cliente_id, criado_em DESC, id DESC)`, de 4,86 para 5,77 req/s (+18,7%). O contrato foi mantido e os planos usaram os índices. Os resultados apoiam benefício neste workload sintético, mas não o garantem em outras cargas ou ambientes. CPU e memória seguem inconclusivas por inconsistências no agregador.

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

Essas opções não são intercambiáveis. Índices são uma mudança localizada no banco e têm custo persistente de espaço e escrita [1]. A consolidação de consultas e o pool atacam viagens e conexões da API, mas exigem testes que provem igualdade exata da resposta [5][6]. Materialização desloca trabalho para atualização e traz uma decisão explícita sobre frescor [7]. Alterar limites de container pode provocar throttling ou OOM, e parâmetros PostgreSQL como `work_mem` multiplicam o consumo por operações e sessões [8][9]. Por isso, a tabela separa mecanismos de risco; o desempenho esperado é hipótese a medir, não uma promessa. O experimento inicial escolheu a opção de menor escopo que correspondia diretamente ao plano observado. Nenhuma alternativa foi rejeitada como universalmente ruim: ficaram para depois por custo, incerteza ou necessidade de preservar a semântica atual.

## 5. Solução escolhida e por quê

Comecei pelo índice em `itens_pedido(pedido_id)`: o plano mostrava uma varredura de 1,5 milhão de linhas para buscar itens de um pedido. Em seguida, o plano de `/clientes/:id/pedidos` motivou o índice composto em `pedidos(cliente_id, criado_em DESC, id DESC)`. Ambos puderam ser adicionados em arquivos SQL isolados, sem alterar a API. N+1 e pooling ficaram para mudanças separadas. Não priorizei `pg_trgm` porque a busca de produtos teve menor custo isolado que os gargalos de pedidos e relatórios; materialização e aumento de recursos ainda exigem justificar custos de atualização e operação.

## 6. Experimento e resultado

| Variante | Req/s por rodada | Mediana req/s | p95 por rodada (ms) | Mediana p95 (ms) |
|---|---|---:|---|---:|
| Sem índice | 2,71 / 2,77 / 2,55 | 2,71 | 23.586,6 / 23.724,1 / 25.501,5 | 23.724,1 |
| Com índice | 4,83 / 4,48 / 4,91 | 4,83 | 12.002,6 / 12.888,6 / 11.382,1 | 12.002,6 |

O contraste entre `9b6b69c` e `59124a7` isolou o arquivo SQL do índice: API, carga e dados sintéticos determinísticos foram mantidos. Após execuções preliminares, a série principal alternou as variantes por três pares, com volumes novos, containers externos pausados, 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. O contrato de 42 casos passou e houve zero erros. As seis pastas primárias e as limitações das séries exploratórias estão em [experimentos.md](../experimentos.md).

Na mediana, o throughput aumentou 78,1% e o p95 caiu 49,4%. O índice ocupa 21 MB e aparece no plano posterior. Esses dados são mais fortes que as capturas iniciais, feitas em datas diferentes, que permanecem exploratórias. A comparação controlada sustenta uma contribuição do índice para este perfil sintético; não estabelece redução de recursos ou benefício em escrita. CPU e memória não foram usadas porque o agregador permanece sob auditoria. Os detalhes e resultados por rota estão em [experimentos.md](../experimentos.md).

Um segundo experimento testou `pedidos(cliente_id, criado_em DESC, id DESC)`, com três rodadas preliminares por variante e depois três pares alternados em volumes novos. Parâmetros e contrato foram iguais ao primeiro teste. O throughput mediano passou de 4,86 para 5,77 req/s; o p95 geral, de 11.374,7 para 10.165,1 ms; e o p95 da rota `pedidos-do-cliente`, de 12.305,5 para 8.551,4 ms. As seis execuções não tiveram erros. O plano mudou de `Parallel Seq Scan` com sort para `Index Scan`; o índice ocupa 19 MB. Os tempos do `EXPLAIN ANALYZE` não foram comparados, pois os estados de cache diferiam. Dados brutos e os dois planos estão em [experimentos.md](../experimentos.md) e [experimento-02-plano.txt](../diagnostico/experimento-02-plano.txt).

## 7. Limites e testes futuros

As comparações alternadas reduzem o risco de deriva temporal, mas têm apenas três rodadas por variante em uma máquina e um perfil sintético; não estabelecem capacidade universal, impacto em escrita ou custo total. O teste separado de 2 versus 20 VUs mostrou throughput quase estável (3,39 para 3,61 req/s) e latência maior sob 20 VUs, mas foi feito em blocos e não separa execução de espera. A amostragem por rota é pequena para estimar p95, especialmente nos relatórios.

O agregador de recursos aparenta comparar picos de CPU como texto e, em uma execução, sumarizar 36 amostras enquanto o CSV contém 37. Não alterei `scripts/`, protegido pelo desafio; por isso, não afirmo economia de CPU/memória. Os próximos testes — incluindo N+1, pool, outros índices e relatórios — estão em [proximos-testes.md](../proximos-testes.md).

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
