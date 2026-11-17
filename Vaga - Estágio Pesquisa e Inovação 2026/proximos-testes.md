# Próximos testes

Cada ficha abaixo tem o status **Pesquisada, teste futuro**: a ideia apareceu na pesquisa ([pesquisa.md](pesquisa.md)) e ainda não foi testada nesta aplicação. Os benefícios são hipóteses, não resultados. O que já foi aplicado e medido (dois índices, remoção do N+1, pool e a comparação acumulada A, B e C) está em [experimentos.md](experimentos.md) e em [diagnostico/relatorio.md](diagnostico/relatorio.md).

**Regras para qualquer teste futuro:** uma mudança por commit, registrada antes da medição; contrato mantido nos 42 casos; três rodadas por variante com os mesmos parâmetros; ordem dos estados balanceada ou sorteada por par; CPU e memória recalculadas dos CSVs (ver [diagnostico/relatorio.md](diagnostico/relatorio.md)). Não alterar `carga/`, `scripts/` nem os arquivos protegidos do contrato e da geração de dados. Qualquer mudança que entre no estado final deixa a comparação A→C desatualizada e exige refazê-la (A→D).

## 1. Limites de CPU e memória 25% menores

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [Docker, Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/) (CPU quota com throttling; limite de memória e OOM) e [PostgreSQL 16, Resource Consumption](https://www.postgresql.org/docs/16/runtime-config-resource.html).
- **Ganho esperado (hipótese):** o estado final (C) gastou ~65% menos CPU por resposta que o original (A) e a memória total ficou quase igual. Se há folga real, C deve manter ao menos o throughput de A com tetos 25% menores: API 0,375 CPU e 192 MB; banco 0,75 CPU e 384 MB.
- **Como testar:** alterar só `cpus` e `memory` no `docker-compose.yml`, em um commit isolado; comparar A (limites originais) com C (limites reduzidos) em três pares balanceados; registrar req/s, p95, CPU, memória, erros e sinais de throttling ou OOM.
- **Critério definido antes do teste:** a conclusão do artigo cai se C com limites reduzidos não mantiver o throughput mediano de A (2,52 req/s), se perder contrato ou se tiver OOM ou erros.
- **Necessário/limites:** o banco usou, em média, de 375 a 398 MiB por rodada (CSV); um teto de 384 MB pode forçar reclaim de cache ou OOM. Reduzir recursos só vale como evidência de “mais barato” se o contrato e o throughput se mantiverem.

## 2. Tamanho do pool (10 contra 4)

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [node-postgres, Pooling](https://node-postgres.com/features/pooling) (teto de clientes e reutilização) e o resultado do pool de 10 conexões em [experimentos.md](experimentos.md): throughput e p95 geral melhoraram, mas o p95 de `pedidos-do-cliente` piorou nos três pares.
- **Ganho esperado (hipótese):** com o banco limitado a 1 CPU, um teto menor (4) reduz a contenção e devolve latência à rota, possivelmente com perda parcial de throughput.
- **Como testar:** mudar só o parâmetro `max` do pool, com índices e N+1 fixos; pares balanceados; contrato e três rodadas; medir também `pedidos-do-cliente` isoladamente.
- **Necessário/limites:** invalida A→C até refazer a acumulada. Conferir na documentação do node-postgres se há orientação de dimensionamento antes de escolher os valores. Não misturar com índice novo.

## 3. Repetição da comparação acumulada em outra sessão ou máquina

- **Status:** Pesquisada, teste futuro.
- **Fonte:** o enunciado (“os números podem variar mais de 30%” entre execuções) e os resultados de [experimentos.md](experimentos.md): o mesmo estado teve níveis diferentes em sessões diferentes (por exemplo, 5,77 req/s no experimento 2 e 4,14 no início do 3).
- **Ganho esperado (hipótese):** C continua acima de A em req/s e em CPU por resposta fora da sessão original.
- **Como testar:** repetir A, B e C com a ordem sorteada, em outra sessão ou máquina, com os mesmos parâmetros.
- **Critério definido antes do teste:** a conclusão cai se a diferença entre A e C ficar dentro da variação entre rodadas de uma mesma versão.
- **Necessário/limites:** tempo de máquina; a mesma régua (`medir.sh`).

## 4. Carga com escrita

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [PostgreSQL 16, Indexes — Introduction](https://www.postgresql.org/docs/16/indexes-intro.html): índices aumentam o custo de manipulação de dados.
- **Ganho esperado (hipótese):** o oposto de um ganho: com escritas, o custo de manter os dois índices reduz a vantagem medida em leitura.
- **Como testar:** a carga atual só lê e `carga/` não pode ser alterada. Seria um perfil exploratório fora do `medir.sh`, declarado como tal, comparando inserções ou atualizações em A e em B.
- **Necessário/limites:** escrever esse perfil; não vale como medição oficial do desafio.

## 5. Índice por status e paginação em `GET /pedidos`

- **Status:** Pesquisada, teste futuro.
- **Fonte:** planos de `COUNT` e página em [diagnostico/planos-consultas.txt](diagnostico/planos-consultas.txt); [Multicolumn Indexes](https://www.postgresql.org/docs/16/indexes-multicolumn.html), [Indexes and ORDER BY](https://www.postgresql.org/docs/16/indexes-ordering.html) e [Index-Only Scans](https://www.postgresql.org/docs/16/indexes-index-only-scans.html).
- **Ganho esperado (hipótese, página):** um índice alinhado a `status` e à ordenação (`criado_em DESC, id DESC`) reduz o trabalho da página de 20 linhas.
- **Hipótese (COUNT):** o `COUNT(*)` do total não melhora necessariamente: um index-only scan só compensa se boa parte das páginas estiver marcada como visível no visibility map.
- **Como testar:** uma mudança SQL isolada; plano da página e do `COUNT` em separado; medir as sete rotas; preservar a semântica de `pagina`.
- **Necessário/limites:** a carga usa páginas de 1 a 1000. O timeout do braço B3 da série final foi nesta rota.

## 6. Índice funcional para busca por e-mail

- **Status:** Pesquisada, teste futuro.
- **Fonte:** plano da busca em [diagnostico/planos-consultas.txt](diagnostico/planos-consultas.txt) e [PostgreSQL 16, Indexes on Expressions](https://www.postgresql.org/docs/16/indexes-expressional.html).
- **Ganho esperado (hipótese):** um índice em `lower(email)` evita a varredura de 100 mil clientes em `GET /clientes?email=`.
- **Como testar:** índice em SQL versionado; comparar plano, tamanho e as sete rotas antes e depois; validar o contrato.
- **Necessário/limites:** espaço e manutenção na escrita; um B-tree simples em `email` não substitui a expressão `lower(email)`.

## 7. Relatórios: filtro de data

- **Status:** Pesquisada, teste futuro.
- **Fonte:** planos em [diagnostico/experimento-01-planos-relatorios.txt](diagnostico/experimento-01-planos-relatorios.txt) (varredura sequencial com filtro em `(criado_em)::date`) e [Multicolumn Indexes](https://www.postgresql.org/docs/16/indexes-multicolumn.html).
- **Ganho esperado (hipótese):** um filtro por faixa de timestamp, compatível com índice, reduz o trabalho de `vendas-por-dia`.
- **Como testar:** reescrever o filtro e criar o índice em uma mudança isolada; comparar respostas além de latência.
- **Necessário/limites:** a API devolve datas em UTC; reescrever `(criado_em)::date` como faixa exige raciocínio de fuso, e os 42 casos do contrato podem não cobrir o limite do dia.

## 8. Relatórios: view materializada

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [Materialized Views](https://www.postgresql.org/docs/16/rules-materializedviews.html) e [REFRESH MATERIALIZED VIEW](https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html).
- **Ganho esperado (hipótese):** leituras repetidas de agregados ficam mais baratas, ao custo de espaço, refresh e dado possivelmente desatualizado.
- **Como testar:** experimento separado do item 7; comparar resposta, frescor, armazenamento e custo de refresh.
- **Necessário/limites:** esclarecer a exigência de atualidade antes; o contrato compara resultados exatos. A carga cobre uma janela móvel de sete dias e `top-produtos` com limite 10.

## 9. Índice GIN com `pg_trgm` na busca de produtos

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [PostgreSQL 16, pg_trgm](https://www.postgresql.org/docs/16/pgtrgm.html); casos em [pesquisa.md](pesquisa.md): [GitLab (2016)](https://about.gitlab.com/blog/fast-search-using-postgresql-trigram/), [Zenn (2025)](https://zenn.dev/team_zenn/articles/zenn-search-tuning-story?locale=en) e [Microsoft Azure (2024)](https://techcommunity.microsoft.com/blog/adforpostgresql/tips-for-tuning-postgres-like--ilike-queries-via-pg-trgm-on-azure/4069179).
- **Ganho esperado (hipótese):** o índice apoia `ILIKE '%termo%'`. O caso do Azure distingue esse padrão sem prefixo (onde o trigram ajuda) do `LIKE` por prefixo (onde um B-tree resolve).
- **Como testar:** habilitar a extensão e criar o índice em SQL versionado; `EXPLAIN`, tamanho e as sete rotas; contrato e três rodadas.
- **Necessário/limites:** os termos da carga têm pelo menos três caracteres; o catálogo tem 20 mil produtos e a busca não foi o maior custo. Os casos externos usam outras bases e não preveem este catálogo.

## 10. Índice composto `(pedido_id, id)` em `itens_pedido`

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [Multicolumn Indexes](https://www.postgresql.org/docs/16/indexes-multicolumn.html), [Indexes and ORDER BY](https://www.postgresql.org/docs/16/indexes-ordering.html) e o plano em [diagnostico/experimento-01-plano.txt](diagnostico/experimento-01-plano.txt), que ainda ordena os itens por `id` depois do `Index Scan`.
- **Ganho esperado (hipótese):** eliminar a etapa de ordenação; o ganho tende a ser pequeno, porque cada pedido tem poucos itens.
- **Como testar:** trocar o índice simples pelo composto em uma mudança isolada; plano, tamanho e as sete rotas.
- **Necessário/limites:** índice maior que o simples; decidir por `EXPLAIN` e medição, não por suposição.

## 11. Parâmetros do PostgreSQL (paralelismo, `work_mem`, `shared_buffers`)

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [Resource Consumption](https://www.postgresql.org/docs/16/runtime-config-resource.html) e [When Can Parallel Query Be Used?](https://www.postgresql.org/docs/16/when-can-parallel-query-be-used.html). Os planos de relatórios mostram `Workers Planned: 2` em um banco limitado a 1 CPU.
- **Ganho esperado (hipótese):** menos workers paralelos podem reduzir a contenção de CPU no banco; mexer em `work_mem` ou `shared_buffers` pode alterar planos e consumo de memória. Não há ganho presumido.
- **Como testar:** um parâmetro por experimento, com `-c` no `command` do serviço `banco`; contrato e três rodadas por variante.
- **Necessário/limites:** `work_mem` pode multiplicar o consumo por operação e sessão; não combinar parâmetros entre si nem com mudanças de consulta.

## 12. Paginação por keyset (cursor)

- **Status:** Pesquisada, teste futuro (não elegível sob o contrato atual).
- **Fonte:** Winand, [Pagination with OFFSET / No OFFSET](https://use-the-index-luke.com/no-offset) e [Fetching the Next Page](https://use-the-index-luke.com/sql/partial-results/fetch-next-page).
- **Ganho esperado (hipótese):** custo estável em páginas profundas, porque o OFFSET precisa descartar as linhas anteriores.
- **Como testar:** só se o contrato aceitar um cursor; hoje a rota recebe `pagina` e trocar isso alteraria a interface.
- **Necessário/limites:** a carga só vai até a página 1000, então o ganho em páginas profundas não seria medido.

## 13. Instrumentação com `pg_stat_statements`

- **Status:** Pesquisada, teste futuro.
- **Fonte:** [PostgreSQL 16, pg_stat_statements](https://www.postgresql.org/docs/16/pgstatstatements.html).
- **Ganho esperado (hipótese):** atribuir tempo e blocos a cada consulta normalizada e orientar o próximo índice. Não é uma otimização.
- **Como testar:** adicionar a `shared_preload_libraries`, reiniciar o banco e criar a extensão, como mudança operacional separada.
- **Necessário/limites:** reinício do banco; não misturar com outro experimento.
