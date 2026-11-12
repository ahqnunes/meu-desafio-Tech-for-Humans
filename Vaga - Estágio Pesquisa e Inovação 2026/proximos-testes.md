# Próximos testes

As ideias abaixo foram pesquisadas, mas ainda não foram testadas nesta aplicação. Benefícios são hipóteses; não há resultados de desempenho a reportar para estes próximos experimentos. A comparação controlada do índice já foi concluída e está registrada em [experimentos.md](experimentos.md). Cada mudança futura deve ser isolada, registrada antes da medição, aprovada pelo contrato e medida três vezes com os mesmos parâmetros. Não alterar `carga/`, `scripts/` nem os arquivos protegidos do contrato e da geração de dados.

## Otimizações ainda não testadas

### Índice de pedidos por cliente e ordenação

- **Fonte/evidência:** [planos baseline](diagnostico/planos-consultas.txt) e [documentação PostgreSQL sobre índices multicoluna](https://www.postgresql.org/docs/16/indexes-multicolumn.html).
- **Hipótese:** um B-tree em `pedidos(cliente_id, criado_em DESC, id DESC)` pode reduzir a varredura e o sort ao listar pedidos do cliente.
- **Como testar:** criar um arquivo SQL novo; verificar o plano e o tamanho do índice; rodar o contrato e três medições, avaliando todas as rotas porque o índice também pode afetar relatórios.
- **Necessário/limites:** preservar a ordem e os campos da resposta; separar este índice dos testes de reescrita da API.

### Consulta de pedidos sem N+1 e pool de conexões

- **Fonte/evidência:** [código da rota](api/src/rotas.js), [acesso ao banco](api/src/db.js), estudo de [Yang et al.](https://par.nsf.gov/servlets/purl/10067547) sobre bugs de performance e [documentação de pooling do node-postgres](https://node-postgres.com/features/pooling).
- **Hipótese:** consolidar a busca de pedidos e itens pode reduzir round trips; reutilizar conexões por pool pode reduzir o custo de abrir/fechar um cliente por consulta.
- **Como testar:** primeiro eliminar o N+1 em uma mudança isolada; em outro commit, introduzir um pool limitado. Em cada caso, conferir precisamente a ordem e o conteúdo das respostas e medir três vezes.
- **Necessário/limites:** contrato preservado, limite explícito do pool e teste de carga com o banco; não combinar as duas alterações num experimento.

### Índice funcional para busca por e-mail

- **Fonte/evidência:** plano da busca em [diagnostico/planos-consultas.txt](diagnostico/planos-consultas.txt) e [documentação PostgreSQL sobre índices de expressão](https://www.postgresql.org/docs/16/indexes-expressional.html).
- **Hipótese:** um índice em `lower(email)` pode apoiar a expressão aplicada pela consulta e evitar a varredura de clientes.
- **Como testar:** adicionar índice em SQL versionado, comparar o plano, tamanho e medições das sete rotas antes/depois; validar o contrato.
- **Necessário/limites:** considerar espaço e custo de escrita/manutenção; um índice B-tree simples em `email` não é substituto presumido para a expressão `lower(email)`.

### Índice para pedidos por status e paginação

- **Fonte/evidência:** planos de `COUNT` e página em [diagnostico/planos-consultas.txt](diagnostico/planos-consultas.txt) e documentação PostgreSQL sobre [índices multicoluna](https://www.postgresql.org/docs/16/indexes-multicolumn.html).
- **Hipótese:** um índice alinhado ao filtro por `status` e à ordenação pode reduzir o custo da página; o `COUNT(*)` pode continuar custoso.
- **Como testar:** testar o índice composto em mudança isolada, examinar separadamente plano de página e `COUNT`, medir todas as rotas e preservar a semântica de `pagina`.
- **Necessário/limites:** a carga atual usa páginas de 1 a 1000; não extrapolar para páginas mais profundas não testadas. Keyset pagination não entra como otimização elegível enquanto exigir alterar o contrato de página numerada.

### Índice GIN com `pg_trgm` para busca de produtos

- **Fonte/evidência:** [documentação PostgreSQL 16 de `pg_trgm`](https://www.postgresql.org/docs/16/pgtrgm.html), com contexto de mercado no levantamento [pesquisa.md](pesquisa.md).
- **Hipótese:** o índice pode apoiar `ILIKE '%termo%'` e reduzir o trabalho de busca no catálogo.
- **Como testar:** habilitar a extensão e criar o índice em SQL versionado; verificar `EXPLAIN`, tamanho e efeito em todas as rotas; executar contrato e três medições.
- **Necessário/limites:** os termos atuais da carga têm pelo menos três caracteres. O catálogo tem 20 mil produtos e a consulta isolada não foi o maior custo; benefício e custo de armazenamento/manutenção precisam ser medidos localmente.

### Relatórios: filtro de data e pré-computação

- **Fonte/evidência:** planos dos relatórios em [diagnostico/experimento-01-planos-relatorios.txt](diagnostico/experimento-01-planos-relatorios.txt), documentação de [views materializadas](https://www.postgresql.org/docs/16/rules-materializedviews.html) e de [refresh](https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html).
- **Hipótese:** um filtro por faixa de timestamp compatível com índice pode reduzir trabalho em vendas por dia; pré-computar um agregado pode ajudar leituras repetidas de relatórios.
- **Como testar:** testar separadamente a reescrita do filtro/índice e, em outro experimento, uma view materializada; comparar resposta e frescor dos dados além de latência e custo de armazenamento/refresh.
- **Necessário/limites:** esclarecer a exigência de atualidade antes de escolher materialização; medir todas as rotas. A carga atual cobre janela móvel de sete dias e top produtos com limite 10, não toda a faixa permitida pela API.

### Corrigir e validar a leitura de recursos

- **Fonte/evidência:** inspeção somente de leitura do agregador em [scripts/medir.sh](scripts/medir.sh) e auditoria em [diagnostico/relatorio.md](diagnostico/relatorio.md); contexto técnico: [documentação PostgreSQL 16 de recursos](https://www.postgresql.org/docs/16/runtime-config-resource.html) e [limites de recursos do Docker](https://docs.docker.com/engine/containers/resource_constraints/).
- **Hipótese:** ajustes de paralelismo, `work_mem` ou limites podem alterar throughput e custo, mas não se presume melhora.
- **Como testar:** o código atual sugere comparação textual no cálculo do pico e possível corrida ao terminar a coleta. Como `scripts/` é régua protegida pelo desafio, não editar o arquivo. Primeiro obter autorização ou um procedimento de validação permitido; então comparar agregados com amostras brutas e testar o encerramento do coletor. Só depois fazer experimentos separados de parâmetros e limites, três medições por variante.
- **Necessário/limites:** `work_mem` pode multiplicar por operação e sessão; limites de CPU podem causar throttling e memória pode causar OOM. Não atribuir resultados a CPU/memória enquanto agregados não forem confiáveis e não alterar os arquivos protegidos.
