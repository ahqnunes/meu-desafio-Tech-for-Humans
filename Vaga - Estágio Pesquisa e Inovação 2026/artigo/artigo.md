# Índices B-tree: resultados sob cargas controladas

## 1. Resumo

Em duas séries de três pares, índices B-tree elevaram o throughput mediano sob 20 VUs: 2,71→4,83 req/s para `itens_pedido(pedido_id)` e 4,86→5,77 para `pedidos(cliente_id, criado_em DESC, id DESC)`. Uma normalização posterior estima menor CPU por resposta em cada etapa, mas não prova economia monetária ou o efeito do conjunto final. A ordem fixa sem→com índice também deixa deriva temporal confundida.

## 2. Contexto e diagnóstico

A API usa Node.js 20, Express e PostgreSQL 16; os dados sintéticos têm 100 mil clientes, 20 mil produtos, 500 mil pedidos e 1,5 milhão de itens. A linha de base (20 VUs, 60 s nominais, 15 s de aquecimento, seed 42) teve mediana de 2,62 req/s e p95 de 24,8 s; as três rodadas mantiveram o contrato e não tiveram erros.

Os planos mostraram varreduras sequenciais em itens e pedidos; `/clientes/:id/pedidos` também consultava itens e produtos dentro de loops. São hipóteses de trabalho repetido, não medidas da contribuição de cada mecanismo para a carga total.

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

Índices acrescentam espaço e manutenção de escrita [1]; consultas consolidadas e pooling exigem preservar a resposta [5][6]; materialização envolve frescor [7]. Limites podem causar throttling/OOM, e `work_mem` pode multiplicar consumo por operação [8][9]. O primeiro teste priorizou a evidência local, sem descartar alternativas.

## 5. Solução escolhida e por quê

Testei os dois índices em mudanças SQL isoladas, depois a remoção do N+1 e, separadamente, o pool. A repetição do N+1 foi inconclusiva; o pool trocou melhor throughput agregado por pior p95 da rota-alvo. `pg_trgm`, materialização e aumento de recursos ficaram para depois, pois seus custos ainda precisam ser justificados localmente.

## 6. Experimento e resultado

Cada valor HTTP é a mediana de três rodadas por variante. Os p95 de rota são apresentados quando relevantes. Recursos são a mediana das médias por rodada, recalculadas de `recursos.csv`; CPU e memória estão na ordem API; banco.

| Mudança | Req/s (antes→depois) | p95 geral (ms; antes→depois) | p95 da rota-alvo (ms; antes→depois) | Recursos médios (antes→depois) | Resultados antes → depois | Conclusão |
|---|---:|---:|---:|---|---|---|
| Índice `itens_pedido(pedido_id)` | 2,71→4,83 | 23.724,1→12.002,6 | — | API 9,89% / 30,25 MiB→16,25% / 34,34 MiB; banco 91,16% / 191,03 MiB→91,31% / 224,99 MiB | [1](../resultados/20261112-185839-02-control-alt-off-1/), [2](../resultados/20261112-190406-02-control-alt-off-2/), [3](../resultados/20261112-191019-02-control-alt-off-3/) → [1](../resultados/20261112-190132-02-control-alt-on-1/), [2](../resultados/20261112-190751-02-control-alt-on-2/), [3](../resultados/20261112-191255-02-control-alt-on-3/) | Throughput +78,1% e p95 −49,4%; ordem fixa sem→com e recursos não provam causalidade nem redução de custo. |
| Índice `pedidos(cliente_id, criado_em DESC, id DESC)` | 4,86→5,77 | 11.374,7→10.165,1 | 12.305,5→8.551,4 | API 16,82% / 35,99 MiB→18,03% / 36,38 MiB; banco 90,58% / 230,34 MiB→89,60% / 225,48 MiB | [1](../resultados/20261113-161645-02-pedidos-cliente-alt-off/), [2](../resultados/20261113-162202-02-pedidos-cliente-alt-off/), [3](../resultados/20261113-162720-02-pedidos-cliente-alt-off/) → [1](../resultados/20261113-161925-02-pedidos-cliente-alt-on/), [2](../resultados/20261113-162441-02-pedidos-cliente-alt-on/), [3](../resultados/20261113-163002-02-pedidos-cliente-alt-on/) | Throughput +18,7%; p95 geral −10,6% e da rota −30,5%. Ordem fixa; índice de 19 MB; sem prova de economia geral. |
| Remoção do N+1, sem pool | 4,14→3,20 | 19.636,8→28.308,2 | 9.820,5→17.498,4 | API 13,42% / 47,38 MiB→7,57% / 44,00 MiB; banco 69,42% / 381,92 MiB→43,36% / 372,93 MiB | [A1](../resultados/20261114-151556-n1-rerun-01-a/), [A2](../resultados/20261114-152435-n1-rerun-02-a/), [A3](../resultados/20261114-152646-n1-rerun-03-a/) → [B1](../resultados/20261114-151931-n1-rerun-01-b/), [B2](../resultados/20261114-152153-n1-rerun-02-b/), [B3](../resultados/20261114-152942-n1-rerun-03-b/) | Inconclusivo: faixas se sobrepõem, pares divergem e houve um timeout em cada braço do primeiro par. |
| Pool de até 10 conexões | 3,32→4,31 | 35.288,3→17.094,6 | 3.713,0→5.690,5 | API 7,82% / 47,35 MiB→7,58% / 40,41 MiB; banco 45,21% / 363,89 MiB→50,84% / 373,20 MiB | [A1](../resultados/20261114-153158-pool-rerun-01-a/), [A2](../resultados/20261114-153949-pool-rerun-02-a/), [A3](../resultados/20261114-154204-pool-rerun-03-a/) → [B1](../resultados/20261114-153505-pool-rerun-01-b/), [B2](../resultados/20261114-153711-pool-rerun-02-b/), [B3](../resultados/20261114-154512-pool-rerun-03-b/) | Trade-off: throughput +29,8% e p95 geral −51,6%; latência mediana geral +143,1% e p95 da rota +53,3%. |

As medições usaram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. As ordens dos índices foram sempre sem→com; N+1 e pool usaram pares balanceados A→B, B→A, A→B. O contrato passou nos 42 casos de todas as medições principais; o pool teve zero erros k6, enquanto os dois timeouts do N+1 foram mantidos nos dados e na análise. Os planos confirmam o uso dos índices.

Uma comparação acumulada e balanceada, na mesma base, mediu A→C: throughput +135,8%, p95 geral −56,1%, p95 da rota −85,8% e CPU estimada por resposta válida −65,1%; a memória total aumentou 2,4% na mediana pareada. A janela de recursos excedeu a duração k6 em mediana 6,0 s, então CPU/resposta é um proxy, não economia monetária. B3 teve 0,35% de erro; o contrato passou. C combina N+1 e pool e não isola seus efeitos. Dados e método estão no [relatório](../diagnostico/relatorio.md).

## 7. Limites e testes futuros

As séries têm três rodadas por variante, uma máquina e um perfil sintético; a ordem balanceada reduz, mas não elimina, deriva temporal. O N+1 isolado foi inconclusivo; o pool isolado trocou melhor throughput agregado por pior p95 da rota. A comparação acumulada favoreceu o estado final, mas não separa o efeito de N+1 e pool e mediu pequeno aumento de memória. A estimativa de CPU por resposta é limitada pela janela de coleta. Os próximos testes estão em [experimentos.md](../experimentos.md) e [proximos-testes.md](../proximos-testes.md).

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
10. Docker. [docker container stats](https://docs.docker.com/reference/cli/docker/container/stats/). Acesso em 15 nov. 2026.
11. Grafana k6. [Built-in metrics](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/). Acesso em 15 nov. 2026.

## 9. Uso de IA

Usei IA como apoio para organizar hipóteses, revisar cálculos e redigir este artigo. Conferi as fontes citadas, os planos salvos e as métricas nos arquivos JSON e CSV do repositório; as limitações e incertezas foram mantidas explicitamente.
