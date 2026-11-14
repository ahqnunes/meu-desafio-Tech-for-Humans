# Próximos testes

As ideias abaixo ainda não foram testadas nesta aplicação; benefícios são hipóteses. Os experimentos de índices, a remoção do N+1 e o pool já foram medidos e estão registrados em [experimentos.md](experimentos.md) e [diagnostico/relatorio.md](diagnostico/relatorio.md). Cada mudança futura deve ser isolada, registrada antes da medição, aprovada pelo contrato e medida três vezes com os mesmos parâmetros; balancear ou sortear a ordem dos braços por par. Não alterar `carga/`, `scripts/` nem os arquivos protegidos do contrato e da geração de dados.

A auditoria de recursos foi feita por recálculo direto dos CSVs usando [diagnostico/recalcular-recursos.py](diagnostico/recalcular-recursos.py); médias, picos e limitações estão em [diagnostico/relatorio.md](diagnostico/relatorio.md). A coleta ainda tem divergências de contagem, portanto futuras medições devem manter os CSVs e registrar as métricas como observacionais, não como custo por requisição.

## Experimentos concluídos nesta etapa

### Remoção do N+1 em pedidos por cliente

- **Implementação:** uma consulta com `LEFT JOIN` e montagem da mesma resposta em memória; sem pooling.
- **Repetição commitada:** três pares balanceados em worktrees limpos; throughput mediano 4,14→3,20 req/s (−22,7%), p95 geral +44,2% e p95 de `pedidos-do-cliente` +78,2%.
- **Conclusão:** inconclusiva. As faixas se sobrepõem, os pares divergem e houve um timeout em cada braço do primeiro par. A repetição substitui a série anterior como evidência principal; não se deve manter a conclusão anterior de ganho medido.
- **Integridade:** contrato mantido nos 42 casos em todas as rodadas; resultados e recursos detalhados em [experimentos.md](experimentos.md) e [diagnostico/relatorio.md](diagnostico/relatorio.md).
- **Próximo passo:** se a decisão de manter a alteração depender de benefício demonstrado, repetir com uma medição focada na rota-alvo, mesma base e warm-up documentado; não combinar com teste de pool ou ajuste de configuração.

### Pool de conexões, testado separadamente

- **Implementação testada:** pool PostgreSQL limitado a 10 conexões sobre a variante sem N+1; encerramento gracioso e registro de erros de conexões ociosas.
- **Repetição commitada:** throughput mediano +29,8% e p95 geral −51,6%; em contrapartida, latência mediana geral +143,1% e p95 da rota-alvo +53,3%. Os três pares favoreceram throughput e p95 geral, mas pioraram o p95 da rota.
- **Decisão/limite:** o pool permanece no código como decisão provisória de trade-off, não por economia comprovada de recursos. A repetição mostrou média de CPU maior no banco e memória média maior no banco, embora ambos os valores fossem menores na API. Se latência de rota ou custo por requisição for prioritário, medir esses objetivos explicitamente e comparar limites de pool em experimento separado e controlado.
- **Integridade:** contrato mantido nos 42 casos e 0% de erros; CSVs e medições individuais estão registrados nas referências acima.

## Otimizações ainda não testadas

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

## Experimentos de configuração (separados das mudanças de consulta)

Depois das mudanças de consulta, pode-se avaliar paralelismo, `work_mem` ou limites, cada um em experimento próprio. Consultar a [documentação PostgreSQL 16 de recursos](https://www.postgresql.org/docs/16/runtime-config-resource.html) e os [limites de recursos do Docker](https://docs.docker.com/engine/containers/resource_constraints/); definir uma hipótese mensurável, manter o contrato e repetir três vezes por variante.

`work_mem` pode multiplicar o consumo por operação e sessão; limites de CPU podem causar throttling e memória pode causar OOM. Não combinar knobs entre si ou com mudanças de consulta, não alterar `scripts/` e registrar CPU/memória recalculadas dos CSVs junto do throughput e latência.
