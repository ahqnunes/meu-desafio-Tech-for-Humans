# Pesquisa: perguntas, fontes e achados

Registro de pesquisa para fundamentar os experimentos e o artigo. Fontes listadas em “Fontes abertas e verificadas” foram abertas e conferidas em 2026-11-11. Não usar os achados como prova de ganho nesta aplicação: cada hipótese precisa de experimento próprio.

## Lista do que precisa ser pesquisado

- [x] **Índices B-tree:** quando ajudam em filtros e joins; custo de escrita/manutenção; por que o planner pode preferir uma varredura sequencial.
- [x] **Composição e ordem de índices:** utilidade de índice multicoluna, regra das colunas à esquerda e trade-off entre `(pedido_id)` e `(pedido_id, id)`.
- [x] **Índice de expressão para e-mail:** compatibilidade com `lower(email)` e custo de manutenção da expressão.
- [x] **Busca por substring:** suporte de `pg_trgm` a `LIKE`/`ILIKE`, tipos GIN/GiST e fatores que afetam a seletividade.
- [x] **Chaves estrangeiras:** se o PostgreSQL cria automaticamente índice na tabela que referencia a chave.
- [x] **Consultas repetidas e conexões:** fundamento e custos de N+1; pooling em `node-postgres`.
- [x] **Paginação e relatório:** implicações de OFFSET, sort, agregações e index-only scan para o `COUNT(*)`.
- [x] **Atribuição de custo por consulta:** requisitos e dados que `pg_stat_statements` oferece.
- [x] **Evidência acadêmica/técnica sobre N+1:** localizar um estudo primário e conferir a população e os resultados descritos no registro/abstract; delimitar sua aplicabilidade à API com SQL direto.
- [ ] **Paginação keyset vs. OFFSET:** fonte técnica primária, custo com páginas profundas e incompatibilidade potencial com o contrato atual de `pagina=`.
- [ ] **Custos medidos no desafio:** obter, por experimento, tempo, CPU, memória, tamanho de cada índice, efeito nas outras rotas e contrato. A documentação não substitui esses resultados.
- [ ] **Casos de mercado:** localizar e abrir ao menos um caso de engenharia de empresa ou provedor confiável que seja diretamente relevante; só incluir no artigo se trouxer evidência aplicável.
- [ ] **Fontes oficiais complementares:** confirmar documentação da versão 16 para qualquer tema que entre no artigo e registrar data de acesso. Não reutilizar sem conferência os links de versões antigas.

## Primeira rodada de pesquisa — 2026-11-11

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

Yang et al. analisaram 12 aplicações ORM reais, derivaram nove anti-patterns de mais de 200 issues e corrigiram manualmente 64 problemas; o abstract reporta speed-up mediano de 2× e máximo de 39×. O próprio estudo delimita o contexto a aplicações com ORM, enquanto esta API usa `pg` e SQL explícito. Portanto, a publicação dá contexto técnico ao anti-pattern, mas os números não são previsão nem evidência de ganho para este repositório. O registro aberto confirma título, autores, publicação ICSE 2018 e resumo; a página do editor ACM retornou 403 nesta sessão, então a análise integral do paper ainda está pendente.

### OFFSET, sort, agregações e `COUNT(*)`

A documentação de índices multicoluna e bitmap explica que combinar índices pode perder a ordem e exigir sort, e que o planner escolhe planos conforme os custos. Para pedidos, isso reforça verificar se um índice composto atende filtro e `ORDER BY`; para páginas profundas, o comportamento de OFFSET/keyset continua na lista de pesquisa pendente porque o contrato atual recebe número de página e precisa ser preservado.

Um index-only scan só evita buscar a linha no heap quando a consulta pode obter os dados do índice e a visibility map indica que a página é toda visível. Logo, não presumir que um índice acelera o `COUNT(*)`; verificar plano e visibilidade depois da mudança.

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
11. Yang, J.; Subramaniam, P.; Lu, S.; Yan, C.; Cheung, A. **How not to structure your database-backed web applications: a study of performance bugs in the wild**. ICSE 2018, pp. 800–810. Registro e abstract no NSF Public Access Repository; abstract lido, texto integral não verificado nesta rodada. [https://par.nsf.gov/biblio/10067547-how-not-structure-your-database-backed-web-applications-study-performance-bugs-wild](https://par.nsf.gov/biblio/10067547-how-not-structure-your-database-backed-web-applications-study-performance-bugs-wild)

As fontes 1–9 são documentação técnica primária do projeto PostgreSQL; a fonte 10 é documentação primária do driver `node-postgres`; a fonte 11 é um estudo acadêmico primário, consultado pelo registro e abstract do NSF PAR. A leitura integral do paper e fontes de casos de mercado continuam pendentes.
