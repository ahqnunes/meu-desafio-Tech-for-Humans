# Pesquisa: perguntas, fontes e achados

Registro de pesquisa para fundamentar os experimentos e o artigo. Fontes listadas em “Fontes abertas e verificadas” foram abertas e conferidas em 2026-11-11. Não usar os achados como prova de ganho nesta aplicação: cada hipótese precisa de experimento próprio.

## Lista do que precisa ser pesquisado

- [x] **Índices B-tree:** quando ajudam em filtros e joins; custo de escrita/manutenção; por que o planner pode preferir uma varredura sequencial.
- [x] **Composição e ordem de índices:** utilidade de índice multicoluna, regra das colunas à esquerda e trade-off entre `(pedido_id)` e `(pedido_id, id)`.
- [x] **Índice de expressão para e-mail:** compatibilidade com `lower(email)` e custo de manutenção da expressão.
- [x] **Busca por substring:** suporte de `pg_trgm` a `LIKE`/`ILIKE`, tipos GIN/GiST e fatores que afetam a seletividade.
- [x] **Chaves estrangeiras:** se o PostgreSQL cria automaticamente índice na tabela que referencia a chave.
- [x] **Consultas repetidas e conexões:** fundamento e custos de N+1; pooling em `node-postgres`.
- [~] **Paginação e relatório:** OFFSET/keyset, sort, agregações e index-only scan pesquisados; falta medir o custo e fechar a decisão para este contrato.
- [x] **Atribuição de custo por consulta:** requisitos e dados que `pg_stat_statements` oferece.
- [x] **Evidência acadêmica/técnica sobre N+1:** paper integral conferido, com os resultados do exemplo e limites de validade.
- [x] **Paginação keyset vs. OFFSET:** fonte técnica primária lida; custo crescente de páginas profundas e cursor incompatível com a API de página numerada.
- [x] **Pré-computação:** documentação oficial de materialized views e refresh, incluindo atualização e atualidade dos dados.
- [x] **Recursos/configuração:** documentação de Docker sobre CPU quota, throttling, hard memory limit/OOM e documentação PostgreSQL sobre `shared_buffers` e `work_mem`.
- [x] **Casos de mercado:** GitLab, Zenn e Azure abertos; resultados e ressalvas contextualizados.
- [ ] **Custos medidos no desafio:** obter, por experimento, tempo, CPU, memória, tamanho de cada índice, efeito nas outras rotas e contrato. A documentação não substitui esses resultados.
- [x] **Fontes do artigo:** shortlist de oito fontes de abordagens diferentes selecionada; manter as demais como referências de apoio no registro.

## Pesquisa — 2026-11-11

### Índices e custo de manutenção

A documentação do PostgreSQL explica que índices podem evitar varreduras completas em buscas seletivas e ajudar em condições de `WHERE` e `JOIN`, mas são mantidos junto com as alterações da tabela. A documentação também alerta que índices aumentam o overhead de manipulação de dados e podem impedir HOT updates. Portanto, a hipótese de indexar `itens_pedido.pedido_id` é coerente com a consulta por pedido e com joins, mas precisa ser avaliada junto ao tamanho do índice e ao custo de escrita.

Para B-tree multicoluna, as colunas líderes são importantes: condições de igualdade nas colunas mais à esquerda delimitam a faixa mais eficientemente. Assim, `(pedido_id, id)` é compatível com filtro por `pedido_id` e pode corresponder à ordenação por `id`; a documentação, porém, não demonstra que adicionar `id` seja melhor que o índice simples no banco deste desafio. Esse detalhe deve ser decidido com `EXPLAIN`, tamanho e medições, não assumido.

### Índice em `lower(email)`

A documentação oficial mostra diretamente que uma consulta por `lower(coluna)` pode usar índice construído sobre a expressão `lower(coluna)`. Também registra o custo de recalcular e manter a expressão em inserções e updates não-HOT. Isso dá suporte à hipótese de um índice funcional, sem afirmar ainda o ganho de ponta a ponta.

### Busca de produto com substring

Na documentação PostgreSQL 16, `pg_trgm` oferece classes de operadores GIN e GiST que suportam buscas indexadas `LIKE` e `ILIKE`, inclusive padrões sem âncora à esquerda. A busca extrai trigramas do padrão; mais trigramas extraíveis tendem a tornar o acesso mais eficaz. Isso fundamenta testar a alternativa para `ILIKE '%termo%'`, mas não prova que o índice será escolhido ou que o ganho compensará armazenamento e manutenção no catálogo de 20 mil produtos. A comparação GIN vs. GiST continua pendente de estudo e experimento específico.

### Índice nas colunas que referenciam FKs

A documentação oficial afirma que a chave referenciada tem índice por ser chave primária/única, mas o PostgreSQL não cria automaticamente índice nas colunas da tabela que referencia a chave. Ela recomenda considerar esses índices porque exclusões/alterações na tabela referenciada podem precisar procurar linhas correspondentes. No desafio, isso explica por que as FKs não substituem os índices necessários às consultas de pedidos e itens; a motivação da otimização, contudo, vem dos `EXPLAIN` das rotas de leitura.

### N+1 e pool de conexões

O código do desafio consulta itens dentro do loop de pedidos e produtos dentro do loop de itens. Esse padrão é evidência direta de consultas repetidas. O estudo acadêmico abaixo fornece contexto e dados de outro ecossistema, mas não permite prever o ganho nesta API.

A documentação de `node-postgres` recomenda pooling para aplicações com consultas frequentes. Ela explica que abrir uma conexão envolve handshake, autenticação/configuração, e que o servidor tem limite de clientes; sugere um pool reutilizável e limitado, geralmente um por aplicação. Os tempos citados nessa documentação não são medição deste ambiente e não devem ser usados como ganho esperado. A melhoria de pool deve ser um experimento separado do índice.

O paper integral foi baixado do NSF PAR e conferido, não apenas o abstract. Em 12 aplicações Rails, N+1 foi identificado em 15 ações problemáticas e nove issues. No exemplo de lazy loading do Lobsters, 50 objetos `mods` eram recuperados e uma consulta adicional buscava cada `story`; a mudança reduziu o carregamento da página de 1,10 s para 0,34 s (PDF p. 7; anais pp. 806–807). Os números gerais não são números de N+1: entre as 64 correções em 39 ações, a mediana do speed-up foi ~2× e o máximo ~39× veio da remoção de uma funcionalidade desnecessária; as 40 correções que não mudaram a interface nem a funcionalidade tiveram speed-up médio de 2,2× e máximo de 9,2× (PDF p. 9; anais p. 808). O estudo também diz que falta de índice, embora comum nos relatos históricos, apareceu em apenas 3 das 40 ações problemáticas nas versões atuais analisadas (PDF p. 8; anais p. 807). O escopo principal é Rails/ORM; para a análise de escalabilidade, os autores ampliaram bases sintéticas até 20 mil registros. Há ainda uma amostra exploratória de 45 issues Django de três aplicações. Esta API usa `pg` e SQL explícito, então os achados contextualizam o padrão, mas não predizem seu ganho.

### OFFSET, sort, agregações e `COUNT(*)`

A documentação de índices multicoluna e bitmap explica que combinar índices pode perder a ordem e exigir sort, e que o planner escolhe planos conforme os custos. Para pedidos, isso reforça verificar se um índice composto atende filtro e `ORDER BY`; o efeito dos índices sobre esta paginação ainda precisa ser medido sob o contrato atual.

Um index-only scan só evita buscar a linha no heap quando a consulta pode obter os dados do índice e a visibility map indica que a página é toda visível. Logo, não presumir que um índice acelera o `COUNT(*)`; verificar plano e visibilidade depois da mudança.

Use The Index, Luke explica que OFFSET precisa localizar e descartar as linhas anteriores, portanto o trabalho cresce para páginas profundas. Keyset/seek usa os valores da última linha como cursor e permite avançar por uma faixa indexável, mas não navega diretamente para uma página arbitrária e exige passar o cursor entre cliente e API. Como a rota atual recebe `pagina`, trocar para cursor alteraria a interface/contrato; keyset fica como alternativa pesquisada, mas não elegível para a otimização sob o contrato atual. O plano já mostrou paginação de até página 1000 no teste, mas a carga não testa além disso.

### Views materializadas e cache

A documentação oficial do PostgreSQL diz que uma materialized view persiste o resultado e que consultas podem ler esses dados como uma tabela, frequentemente mais rápido que recalcular a consulta original. O dado pode ficar desatualizado; o refresh executa novamente a consulta definidora. `REFRESH MATERIALIZED VIEW CONCURRENTLY` permite leituras simultâneas, mas exige view já populada e índice UNIQUE apropriado; refresh ainda substitui o conteúdo da view. Para os relatórios, isso implica custo de armazenamento e refresh/atualidade, e não é automaticamente adequado ao contrato que compara resultados exatos. Cache de aplicação/CDN pode reduzir chamadas repetidas, mas depende de taxa de repetição e política correta de expiração/invalidação; o perfil aleatório desta carga talvez limite reuso de URLs.

### Recursos e configuração

Docker documenta CPU quota como teto: ao consumir a cota do período, o container é throttled. Limites rígidos de memória evitam consumo acima do teto, mas falta de memória pode provocar OOM e matar processos; aumentar limites pode melhorar folga, mas custa recurso e não prova menor custo. A documentação PostgreSQL 16 diz que `shared_buffers` só muda na inicialização; 25% é referência para servidor dedicado com pelo menos 1 GB, e sistemas com menos de 1 GB devem começar com percentual menor. `work_mem` é limite por operação de sort/hash e várias operações/sessões podem multiplicar o consumo. Para este banco, com limite de 512 MiB, a média de 377 MiB reportada pela instrumentação da baseline não é evidência confiável: a auditoria em [diagnostico/relatorio.md](diagnostico/relatorio.md) encontrou inconsistências entre `recursos.csv` e `recursos.txt`. Portanto, uso de memória e CPU permanecem sem conclusão; aumentar `work_mem` ou limites é uma hipótese de risco, não uma recomendação inicial.

### Casos de engenharia e fornecedor

- **GitLab (2016):** relata adoção de GIN trigram para buscas `ILIKE`; o artigo diz que GIN deu melhores tempos que GiST no cenário deles, ao custo de índice maior e construção mais lenta. Um exemplo local passa de ~160 ms para ~0,167 ms com GIN, em outra aplicação e distribuição. É experiência antiga e não previsão para o catálogo de 20 mil produtos deste desafio.
- **Zenn (2025):** relata combinação de cache CDN para buscas populares e índices PostgreSQL. O artigo mostra latência média diária de busca de 0,42 s para 0,07 s e p95 de 0,85 s para 0,20 s entre datas, mas as melhorias incluem CDN e `pg_trgm`; o autor atribui a queda observada em parte ao trigram, sem experimento controlado que separe cada efeito. O relato também observa fallback/full scan para termos de até dois caracteres com `pg_trgm`. No teste deste desafio os termos fixos são `cadeira`, `mesa`, `lumin`, `teclado`, `monitor`, `ergo`, `sem fio`, `portatil`, `modelo 12`, `slim`, `reforcada`, `webcam`: todos têm pelo menos três caracteres.
- **Microsoft Azure (2024):** é um caso de fornecedor com tabela de teste de 80 milhões de linhas. Importante distinguir as técnicas: a melhoria de ~1,9 s para ~27 ms no artigo foi para prefixo `LIKE 'testp123%'` com B-tree `text_pattern_ops`, não com trigram. Para padrão sem prefixo, GIN `pg_trgm` reduziu um `LIKE '%testp123'` de ~2,6 s para ~1,08 s. O resultado depende de outra distribuição, hardware gerenciado e consultas de teste; serve como exemplo de mecanismo e não como projeção para este projeto.

## Comparação preliminar de alternativas

O custo/desempenho abaixo combina documentação e evidência externa; não são resultados medidos nesta API. A coluna “Desempenho a verificar” registra o mecanismo esperado e a medição necessária, sem prometer ganho.

| Abordagem | Custo | Desempenho a verificar | Risco | Esforço |
|---|---|---|---|---|
| Índices B-tree/expressão por rota | Espaço adicional; manutenção nas escritas e updates; custo de build/recriação do banco. | Acesso seletivo para e-mail, cliente/itens e pedidos ordenados; medir `EXPLAIN`, tamanho, todas as rotas e uso de CPU. | Mais índices aumentam custo de escrita e podem não ser escolhidos pelo planner; índice composto pode ocupar mais espaço que o simples. | Baixo–médio: SQL novo e rebuild; cada grupo deve ter experimento separado. |
| Reescrita da API (remover N+1, pooling) | Baixo custo de armazenamento; pool mantém conexões abertas e limitadas; exige escolher limite adequado. | Menos round trips/conexões e menor latência em pedidos do cliente; medir p95, req/s, CPU e concorrência. | Mudança de ordem/valores quebra contrato; pool ilimitado ou dimensionado incorretamente pode sobrecarregar o DB. | Médio: código, testes de contrato e controle de pool. |
| Pré-computação/cache de relatórios | Armazenamento da view/cache e CPU de refresh/invalidação; cache externo ainda pode exigir serviço. | Leituras repetidas de agregações podem ficar mais baratas; medir hit rate, latência e custo de atualizar os dados. | Dado obsoleto, invalidação complexa e refresh caro; o contrato espera valores exatos. | Médio–alto: política de frescor, refresh/expiração e testes de consistência. |
| Configuração/limites de recursos | Aumentar CPU/RAM aumenta consumo/custo; reduzir limites poupa recursos se a carga continuar atendida. | `shared_buffers`, paralelismo, `work_mem` ou limites podem alterar plano, throughput e throttling; exigir medições antes/depois de CPU/memória e latência. | OOM/throttling, regressão ou efeito confundido com paralelismo/contenção; `work_mem` multiplica por operação/sessão. | Baixo–médio: parâmetros e reinício/Compose; experimentos independentes e reversíveis. |

Esta tabela é um rascunho para a seção de alternativas do artigo. A ordem experimental inicial continua sendo índice de `itens_pedido(pedido_id)` isolado; API, cache e configuração não devem entrar no mesmo commit/medição.

### Shortlist para a seção de alternativas do artigo

Para cumprir o limite de 6–8 referências e evitar concentração em um único site, a seleção inicial é:

1. **Índices B-tree e custo:** documentação PostgreSQL 16, [Indexes — Introduction](https://www.postgresql.org/docs/16/indexes-intro.html).
2. **Busca por substring:** documentação PostgreSQL 16, [pg_trgm](https://www.postgresql.org/docs/16/pgtrgm.html).
3. **Caso de mercado para trigram:** GitLab, [Fast Search Using PostgreSQL Trigram Text Indexes](https://about.gitlab.com/blog/fast-search-using-postgresql-trigram/).
4. **N+1:** Yang et al., [paper ICSE 2018 integral](https://par.nsf.gov/servlets/purl/10067547).
5. **Pool da API:** node-postgres, [Pooling](https://node-postgres.com/features/pooling).
6. **Pré-computação:** documentação PostgreSQL 16, [Materialized Views](https://www.postgresql.org/docs/16/rules-materializedviews.html).
7. **Configuração do banco:** documentação PostgreSQL 16, [Resource Consumption](https://www.postgresql.org/docs/16/runtime-config-resource.html).
8. **Limites do container:** Docker, [Resource constraints](https://docs.docker.com/engine/containers/resource_constraints/).

Esta shortlist contém **8 fontes** para eventual citação na seção curta do artigo. A bibliografia numerada abaixo contém **21 referências consultadas** como inventário de pesquisa; não significa que todas serão citadas no texto final. As fontes de refresh concorrente, paginação, Zenn e Azure permanecem como material de apoio, mas não precisam entrar na seção curta, a menos que esses temas sejam escolhidos para a comparação final.

### Instrumentação

`pg_stat_statements` coleta estatísticas de planejamento e execução por consulta normalizada, incluindo chamadas, tempo total e blocos compartilhados. Para ativá-lo é preciso adicioná-lo a `shared_preload_libraries`, reiniciar o servidor e criar a extensão no banco. É uma mudança operacional separada, não necessária para iniciar o primeiro experimento.

## Fontes abertas e verificadas

1. PostgreSQL Global Development Group. **Indexes — Introduction**, PostgreSQL 16. Explica varredura sequencial vs. índice, uso em filtros/joins, manutenção e overhead de índices. [https://www.postgresql.org/docs/16/indexes-intro.html](https://www.postgresql.org/docs/16/indexes-intro.html)
2. PostgreSQL Global Development Group. **Indexes on Expressions**, PostgreSQL 16. Exemplo de índice em `lower()` e custo de manutenção. [https://www.postgresql.org/docs/16/indexes-expressional.html](https://www.postgresql.org/docs/16/indexes-expressional.html)
3. PostgreSQL Global Development Group. **Multicolumn Indexes**, PostgreSQL 16. Regras de índice multicoluna e colunas líderes. [https://www.postgresql.org/docs/16/indexes-multicolumn.html](https://www.postgresql.org/docs/16/indexes-multicolumn.html)
4. PostgreSQL Global Development Group. **pg_trgm — support for similarity of text using trigram matching**, PostgreSQL 16. Classes GIN/GiST e suporte a `LIKE`/`ILIKE`. [https://www.postgresql.org/docs/16/pgtrgm.html](https://www.postgresql.org/docs/16/pgtrgm.html)
5. PostgreSQL Global Development Group. **Constraints**, PostgreSQL 16, seção sobre chaves estrangeiras. Índices não são criados automaticamente nas colunas que referenciam uma FK. [https://www.postgresql.org/docs/16/ddl-constraints.html](https://www.postgresql.org/docs/16/ddl-constraints.html)
6. PostgreSQL Global Development Group. **CREATE INDEX**, PostgreSQL 16. Expressões, `INCLUDE`, construção concorrente e considerações de tamanho/manutenção. [https://www.postgresql.org/docs/16/sql-createindex.html](https://www.postgresql.org/docs/16/sql-createindex.html)
7. PostgreSQL Global Development Group. **Combining Multiple Indexes**, PostgreSQL 16. Bitmap scans, composição de índices e perda de ordem que pode exigir sort. [https://www.postgresql.org/docs/16/indexes-bitmap-scans.html](https://www.postgresql.org/docs/16/indexes-bitmap-scans.html)
8. PostgreSQL Global Development Group. **Index-Only Scans and Covering Indexes**, PostgreSQL 16. Requisitos de colunas e visibility map. [https://www.postgresql.org/docs/16/indexes-index-only-scans.html](https://www.postgresql.org/docs/16/indexes-index-only-scans.html)
9. PostgreSQL Global Development Group. **pg_stat_statements — track statistics of SQL planning and execution**, PostgreSQL 16. Requisito de preload/reinício e estatísticas coletadas. [https://www.postgresql.org/docs/16/pgstatstatements.html](https://www.postgresql.org/docs/16/pgstatstatements.html)
10. node-postgres contributors. **Pooling**. Documentação técnica do driver. Motivos e uso de pool limitado/reutilizável. [https://node-postgres.com/features/pooling](https://node-postgres.com/features/pooling)
11. Yang, J.; Subramaniam, P.; Lu, S.; Yan, C.; Cheung, A. **How not to structure your database-backed web applications: a study of performance bugs in the wild**. ICSE 2018, pp. 800–810. Texto integral lido no PDF do NSF PAR; exemplo N+1 na p. 806 (PDF p. 7), resultados gerais na p. 808 (PDF p. 9). [https://par.nsf.gov/servlets/purl/10067547](https://par.nsf.gov/servlets/purl/10067547)
12. PostgreSQL Global Development Group. **Materialized Views**, PostgreSQL 16. Persistência, frescor e refresh. [https://www.postgresql.org/docs/16/rules-materializedviews.html](https://www.postgresql.org/docs/16/rules-materializedviews.html)
13. PostgreSQL Global Development Group. **REFRESH MATERIALIZED VIEW**, PostgreSQL 16. Refresh normal/concurrent e pré-condições. [https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html](https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html)
14. PostgreSQL Global Development Group. **Resource Consumption**, PostgreSQL 16. Semântica de `shared_buffers`, `work_mem` e outros parâmetros de recursos. [https://www.postgresql.org/docs/16/runtime-config-resource.html](https://www.postgresql.org/docs/16/runtime-config-resource.html)
15. Docker. **Resource constraints**. Efeitos de CPU quota/throttling, limite de memória e OOM. [https://docs.docker.com/engine/containers/resource_constraints/](https://docs.docker.com/engine/containers/resource_constraints/)
16. Winand, M. **Pagination with OFFSET / No OFFSET**. Custo de descartar linhas, páginas profundas e limitações do keyset. [https://use-the-index-luke.com/no-offset](https://use-the-index-luke.com/no-offset)
17. Winand, M. **Fetching the Next Page**. OFFSET versus seek, ordenação determinística e uso de chave de continuação. [https://use-the-index-luke.com/sql/partial-results/fetch-next-page](https://use-the-index-luke.com/sql/partial-results/fetch-next-page)
18. Peterse, Y. **Fast Search Using PostgreSQL Trigram Text Indexes**. GitLab, 2016-03-18. Caso de GIN trigram, trade-off de tamanho/build e exemplo de query. [https://about.gitlab.com/blog/fast-search-using-postgresql-trigram/](https://about.gitlab.com/blog/fast-search-using-postgresql-trigram/)
19. Yoshikawa, D. **Zenn Search Tuning Story**. Zenn, 2025. Experiência de CDN cache e índices PostgreSQL; métricas agregadas e limitações de termos curtos. [https://zenn.dev/team_zenn/articles/zenn-search-tuning-story?locale=en](https://zenn.dev/team_zenn/articles/zenn-search-tuning-story?locale=en)
20. Microsoft Azure Database for PostgreSQL. **Tips for tuning Postgres LIKE/ILIKE queries via pg_trgm on Azure**. Microsoft TechCommunity, 2024. Caso de fornecedor com teste grande; distingue B-tree prefixo de GIN trigram para padrões sem prefixo. [https://techcommunity.microsoft.com/blog/adforpostgresql/tips-for-tuning-postgres-like--ilike-queries-via-pg-trgm-on-azure/4069179](https://techcommunity.microsoft.com/blog/adforpostgresql/tips-for-tuning-postgres-like--ilike-queries-via-pg-trgm-on-azure/4069179)
21. PostgreSQL Global Development Group. **When Can Parallel Query Be Used?**, PostgreSQL 16. Condições para planejamento paralelo e limitações de workers. [https://www.postgresql.org/docs/16/when-can-parallel-query-be-used.html](https://www.postgresql.org/docs/16/when-can-parallel-query-be-used.html)

As fontes foram consultadas em 2026-11-11. A lista contém documentação primária PostgreSQL e `node-postgres`, paper acadêmico lido integralmente, documentação Docker, material técnico de paginação e relatos de engenharia/fornecedor. Para o artigo, selecionar 6–8 fontes agrupadas por abordagem; não listar todas as referências deste inventário se não forem citadas.
