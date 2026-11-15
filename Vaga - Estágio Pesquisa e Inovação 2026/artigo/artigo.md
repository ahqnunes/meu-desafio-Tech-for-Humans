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

Cada valor HTTP é a mediana de três rodadas por variante. Os p95 de rota são apresentados quando relevantes. Recursos são a mediana das médias por rodada, recalculadas de `recursos.csv`; CPU e memória estão na ordem API; banco.

| Mudança | Req/s (antes→depois) | p95 geral (ms; antes→depois) | p95 da rota-alvo (ms; antes→depois) | Recursos médios (antes→depois) | Resultados antes → depois | Conclusão |
|---|---:|---:|---:|---|---|---|
| Índice `itens_pedido(pedido_id)` | 2,71→4,83 | 23.724,1→12.002,6 | — | API 9,89% / 30,25 MiB→16,25% / 34,34 MiB; banco 91,16% / 191,03 MiB→91,31% / 224,99 MiB | [1](../resultados/20261112-185839-02-control-alt-off-1/), [2](../resultados/20261112-190406-02-control-alt-off-2/), [3](../resultados/20261112-191019-02-control-alt-off-3/) → [1](../resultados/20261112-190132-02-control-alt-on-1/), [2](../resultados/20261112-190751-02-control-alt-on-2/), [3](../resultados/20261112-191255-02-control-alt-on-3/) | Throughput +78,1% e p95 −49,4%; ordem fixa sem→com e recursos não provam causalidade nem redução de custo. |
| Índice `pedidos(cliente_id, criado_em DESC, id DESC)` | 4,86→5,77 | 11.374,7→10.165,1 | 12.305,5→8.551,4 | API 16,82% / 35,99 MiB→18,03% / 36,38 MiB; banco 90,58% / 230,34 MiB→89,60% / 225,48 MiB | [1](../resultados/20261113-161645-02-pedidos-cliente-alt-off/), [2](../resultados/20261113-162202-02-pedidos-cliente-alt-off/), [3](../resultados/20261113-162720-02-pedidos-cliente-alt-off/) → [1](../resultados/20261113-161925-02-pedidos-cliente-alt-on/), [2](../resultados/20261113-162441-02-pedidos-cliente-alt-on/), [3](../resultados/20261113-163002-02-pedidos-cliente-alt-on/) | Throughput +18,7%; p95 geral −10,6% e da rota −30,5%. Ordem fixa; índice de 19 MB; sem prova de economia geral. |
| Remoção do N+1, sem pool | 4,14→3,20 | 19.636,8→28.308,2 | 9.820,5→17.498,4 | API 13,42% / 47,38 MiB→7,57% / 44,00 MiB; banco 69,42% / 381,92 MiB→43,36% / 372,93 MiB | [A1](../resultados/20261114-151556-n1-rerun-01-a/), [A2](../resultados/20261114-152435-n1-rerun-02-a/), [A3](../resultados/20261114-152646-n1-rerun-03-a/) → [B1](../resultados/20261114-151931-n1-rerun-01-b/), [B2](../resultados/20261114-152153-n1-rerun-02-b/), [B3](../resultados/20261114-152942-n1-rerun-03-b/) | Inconclusivo: faixas se sobrepõem, pares divergem e houve um timeout em cada braço do primeiro par. |
| Pool de até 10 conexões | 3,32→4,31 | 35.288,3→17.094,6 | 3.713,0→5.690,5 | API 7,82% / 47,35 MiB→7,58% / 40,41 MiB; banco 45,21% / 363,89 MiB→50,84% / 373,20 MiB | [A1](../resultados/20261114-153158-pool-rerun-01-a/), [A2](../resultados/20261114-153949-pool-rerun-02-a/), [A3](../resultados/20261114-154204-pool-rerun-03-a/) → [B1](../resultados/20261114-153505-pool-rerun-01-b/), [B2](../resultados/20261114-153711-pool-rerun-02-b/), [B3](../resultados/20261114-154512-pool-rerun-03-b/) | Trade-off: throughput +29,8% e p95 geral −51,6%; latência mediana geral +143,1% e p95 da rota +53,3%. |

As medições usaram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. As ordens dos índices foram sempre sem→com; N+1 e pool usaram pares balanceados A→B, B→A, A→B. O contrato passou nos 42 casos de todas as medições principais; o pool teve zero erros k6, enquanto os dois timeouts do N+1 foram mantidos nos dados e na análise. Os planos confirmam o uso dos índices. CPU e memória são observações descritivas, não normalizadas por requisição; portanto, não há evidência suficiente para afirmar que as mudanças reduziram o custo total. Os detalhes metodológicos, exclusões e limitações estão em [experimentos.md](../experimentos.md) e [relatorio.md](../diagnostico/relatorio.md).

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
