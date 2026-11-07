# Diagnóstico da linha de base

## Escopo e método

Este diagnóstico usa a aplicação original, sem alterações de código, esquema ou parâmetros. Durante a linha de base, a API e o PostgreSQL estavam nos limites originais do Compose: API com 0,5 CPU e 256 MiB; banco com 1 CPU e 512 MiB. A API respondeu `{"status":"ok"}` e o banco estava `healthy`. Como as portas locais 3000 e 5432 estavam ocupadas por outros containers, usei temporariamente 3001 (API) e 5434 (banco); esse override ficou fora do repositório.

Foram consultadas as definições e estatísticas do PostgreSQL e executado `EXPLAIN (ANALYZE, BUFFERS, TIMING OFF)` para consultas representativas das sete rotas. Cada consulta teve `statement_timeout=120s`. Os planos foram executados individualmente, sem a carga concorrente, e uma vez por consulta. Os tempos são observações de execução isolada, não medições de CPU nem resultados de antes/depois. Planos paralelos podem consumir CPU em vários workers; por isso, tempo de parede não deve ser interpretado como custo de CPU.

Evidências:

- [estado-postgres.txt](./estado-postgres.txt): índices, estatísticas acumuladas, configurações, conexões, vacuum, JIT, paralelismo e chaves estrangeiras.
- [estado-runtime.txt](./estado-runtime.txt): estado e limites dos containers durante a conferência operacional.
- [planos-consultas.txt](./planos-consultas.txt): planos das consultas representativas.
- [resultados da linha de base](../resultados/): resultados oficiais gerados pelo `medir.sh`.
- [teste-carga.js](../carga/teste-carga.js): perfil, pesos e parâmetros efetivamente usados pelo k6.

## Linha de base observada

As três execuções usaram 20 VUs, duração configurada de 60 s, aquecimento de 15 s e semente 42. As três mantiveram o contrato e registraram zero erros. A tabela abaixo transcreve os arquivos de cada execução. CPU e memória são as médias calculadas pelo `medir.sh` a partir das amostras de `recursos.csv`.

| Execução e evidência | Requisições | Req/s | Duração k6 (s) | p95 geral (ms) | Erros | Banco CPU / memória média | API CPU / memória média |
|---|---:|---:|---:|---:|---:|---:|---:|
| [172817](../resultados/20261107-172817-00-linha-de-base/) | 197 | 2,84 | 69,3 | 23.228,1 | 0% | 91,7% / 390,3 MiB | 9,9% / 31,6 MiB |
| [173048](../resultados/20261107-173048-00-linha-de-base/) | 173 | 2,47 | 70,2 | 26.412,7 | 0% | 90,4% / 374,7 MiB | 8,6% / 30,5 MiB |
| [173256](../resultados/20261107-173256-00-linha-de-base/) | 180 | 2,62 | 68,6 | 24.812,1 | 0% | 86,9% / 377,0 MiB | 9,6% / 31,1 MiB |
| **Mediana das três execuções** | **180** | **2,62** | **69,3** | **24.812,1** | **0%** | **90,4% / 377,0 MiB** | **9,6% / 31,1 MiB** |

As medianas foram calculadas separadamente por coluna, ordenando os três valores e escolhendo o valor central; não foram calculadas a partir de uma execução composta. Os números por execução vêm de `resumo.txt`, `resumo-k6.json` e `recursos.txt` nas pastas ligadas acima.

### Janela de medição e amostras por rota

O `medir.sh` passa `DURACAO=60s` ao cenário k6 `constant-vus`, com `gracefulStop: 30s`. O teste não chama `sleep()` entre requisições: cada VU faz uma requisição e inicia a próxima ao terminar a anterior. Nos `resumo-k6.json`, `state.testRunDurationMs` foi 69.314,5 ms, 70.175,6 ms e 68.577,8 ms. A taxa impressa pelo k6 corresponde a `http_reqs.count / http_reqs.values.rate` (tempo efetivo do teste), não à contagem dividida pelos 60 segundos nominais. As requisições em andamento ao fim do cenário e o encerramento gracioso tornam a janela observada maior; portanto, não se deve inferir a taxa usando apenas a duração configurada.

O perfil de carga usa páginas de pedidos entre 1 e 1000, busca produtos com termos fixos, relatórios de sete dias e `top-produtos?limite=10`. Não varia até 31 dias ou outros limites. As amostras por rota, na ordem das três execuções, foram:

| Rota | Peso configurado | Execução 1 | Execução 2 | Execução 3 | Faixa de amostras |
|---|---:|---:|---:|---:|---:|
| `cliente` | 25% | 51 | 47 | 48 | 47–51 |
| `cliente-por-email` | 15% | 36 | 28 | 31 | 28–36 |
| `pedidos-do-cliente` | 20% | 40 | 37 | 39 | 37–40 |
| `pedidos-por-status` | 15% | 22 | 20 | 21 | 20–22 |
| `busca-produtos` | 15% | 33 | 27 | 28 | 27–33 |
| `vendas-por-dia` | 8% | 13 | 12 | 12 | 12–13 |
| `top-produtos` | 2% | 2 | 2 | 1 | 1–2 |

Os p95 por rota com 1–2 observações (`top-produtos`) não são percentis informativos; mesmo 12–13 observações para vendas dão uma estimativa muito instável da cauda. Trate os percentis por rota da linha de base como indicativos, não como comparação conclusiva. O p95 geral tem mais amostras, mas ainda reflete esta carga fechada de apenas 20 VUs.

Os 90,4% de CPU média do banco contra 9,6% da API são um forte indício de que o PostgreSQL é o principal consumidor de CPU nesta carga. Isso não prova que a latência seja fila nem separa espera de execução. Pela relação de Little, `N/X` estima o tempo médio no sistema num regime estável; com VUs fechados e sem pausa, não permite por si só decompor a resposta entre fila e serviço, nem demonstrar saturação causalmente.

## Achados e hipóteses

### 1. Pedidos do cliente fazem trabalho repetido e sem índices de apoio

Na rota [`GET /clientes/:id/pedidos`](../api/src/rotas.js), o código busca os pedidos, percorre cada pedido para consultar seus itens e, depois, percorre cada item para buscar o produto ([rotas.js, linha 75](../api/src/rotas.js#L75)). Isso produz consultas sequenciais repetidas. Além disso, [`consultar()`](../api/src/db.js) instancia um novo `Client`, conecta, executa uma consulta e fecha a conexão em cada chamada ([db.js, linhas 11–18](../api/src/db.js#L11)).

O banco só tem índices de chave primária. No plano do cliente 7, a busca de pedidos fez `Parallel Seq Scan` em `pedidos` (500 mil linhas) e sort; levou 167,715 ms fora de carga. A consulta de itens do pedido 329786 fez `Parallel Seq Scan` em `itens_pedido` (1,5 milhão de linhas); o plano reportou 499.999 linhas filtradas e levou 102,538 ms. A busca do produto por ID, em contraste, usou a chave primária e levou 0,049 ms.

**Hipótese:** varreduras completas repetidas, mais conexões abertas e fechadas por consulta, contribuem para a latência e o uso de CPU nessa rota, que representa 20% das chamadas. O código e os planos sustentam o mecanismo provável; o ganho de cada correção precisa ser medido isoladamente.

### 2. A busca por e-mail não consegue usar a chave primária nem um índice existente

A consulta aplica `lower()` à coluna `email`; só existe o índice da chave primária de `clientes`. O plano percorreu os 100 mil clientes, descartou 99.999 linhas e levou 127,104 ms isolado.

**Hipótese:** um índice de expressão compatível com `lower(email)` pode evitar a varredura para essa busca. Um índice simples em `email` não corresponde diretamente à expressão usada; isso pode ser verificado com `EXPLAIN` antes de escolher o índice.

### 3. A listagem de pedidos por status varre e ordena a tabela

O endpoint executa um `count(*)` pelo status e consulta a página ordenada por data e ID. Nenhuma combinação de status/data está indexada. Os planos de contagem e página fizeram varreduras paralelas em `pedidos`; a consulta da página também fez sort. Tempos observados isoladamente: 40,814 ms para o `COUNT` e 175,714 ms para a página.

**Hipótese:** um índice composto que corresponda ao filtro e à ordem pode reduzir o trabalho da página. O `COUNT(*)` pode continuar custoso conforme a seletividade e o método de acesso; deve ser avaliado separadamente.

### 4. A busca por substring percorre o catálogo

`ILIKE '%termo%'` não é atendido por índice B-tree convencional. O plano de `cadeira` percorreu os 20 mil produtos e descartou 19 mil; levou 19,717 ms isolado. Os termos reais da carga estão no código do teste, e a frequência desta rota é 15%.

**Hipótese:** `pg_trgm` com índice GIN é uma alternativa a testar para substring. O catálogo é relativamente pequeno e a busca isolada não foi o maior custo encontrado; o benefício precisa ser comparado ao custo de criação, espaço e manutenção do índice.

### 5. Os relatórios fazem agregações e varreduras grandes

- **Vendas por dia:** o plano de uma janela amostral de sete dias percorreu `pedidos` e `itens_pedido`; levou 340,660 ms isolado. O filtro `p.criado_em::date` aplica uma expressão à coluna, e não há índice em data nem em `itens_pedido.pedido_id`.
- **Top produtos:** a consulta agregou os 1,5 milhão de itens após ler pedidos e produtos; levou 2.112,070 ms isolado. O peso da rota é 2%, e a carga executa somente 1–2 observações por rodada.

Uma estimativa exploratória para priorização pode ponderar os tempos de relógio dos planos pelo peso das rotas, mas não representa custo de CPU: alguns planos usam paralelismo, os planos são de uma execução isolada e nem toda execução tem o mesmo número de linhas. Não usar essa estimativa como distribuição medida de CPU ou como substituto de `pg_stat_statements`.

**Hipótese:** o custo do relatório diário decorre da filtragem por data sem acesso seletivo e do join sem índice de apoio nos itens; top produtos tem custo de agregação global. Índices, reescrita do filtro de data e materialização são alternativas, mas precisam de experimentos e análise de atualidade dos dados.

## Evidência de estatísticas e limites

O script de carga insere 100 mil clientes, 20 mil produtos, 500 mil pedidos e cerca de 1,5 milhão de itens, e define chaves estrangeiras de pedidos para clientes e de itens para pedidos e produtos ([02-dados.sql](../banco/02-dados.sql), [01-estrutura.sql](../banco/01-estrutura.sql)). Os contadores `idx_scan` registrados depois da carga são sugestivos de verificações de chaves estrangeiras durante a inserção: há aproximadamente 500 mil buscas de índice em `clientes` e aproximadamente 1,5 milhão em `pedidos` e `produtos`. Mas os contadores também podem incluir consultas posteriores; como `stats_reset` não tem valor, não atribuímos esses totais exclusivamente à geração nem à carga HTTP.

Os contadores acumulados também mostram 1,245 bilhão de linhas lidas sequencialmente em `itens_pedido` e 216,5 milhões em `pedidos`, 105 arquivos temporários e cerca de 1.940 MB gravados. São valores sem timestamp de reset. Os planos capturados não mostram spill: os hashes reportados usam uma batch. A origem dos temporários permanece desconhecida; atribuí-los aos planos, à carga ou à geração dos dados seria especulação.

`pg_stat_statements` está disponível na imagem, mas não instalado/ativado. Habilitá-lo requer alteração de configuração e reinicialização, por isso ficou fora desta captura. Para atribuir custo por query sob uma janela de carga, um próximo diagnóstico pode guardar snapshots de `pg_stat_user_tables` e `pg_stat_database` antes e depois e calcular os deltas; `pg_stat_statements` habilitado seria uma evidência mais direta por consulta.

Configurações efetivas consultadas:

| Parâmetro | Valor observado |
|---|---:|
| `shared_buffers` | 128 MiB |
| `work_mem` | 4 MiB |
| `effective_cache_size` | 4 GiB |
| `max_connections` | 100 |
| `max_parallel_workers_per_gather` | 2 |
| `max_parallel_workers` | 8 |
| `jit` | on |
| `jit_above_cost` | 100000 |

O maior custo estimado nos planos salvos é aproximadamente 57.108, inferior ao `jit_above_cost` observado; nenhum dos planos apresenta bloco de JIT. Isso justifica não priorizar um ajuste de JIT agora, sem afirmar que o recurso nunca possa ajudar em outra consulta. Os planos de `pedidos`, itens, `COUNT`, página, vendas e top produtos usam `Gather`/scans paralelos; as consultas por chave primária e os planos de e-mail e busca de produtos não. Um teste de `max_parallel_workers_per_gather=0`, se feito, deve ser um experimento separado após os índices.

O `effective_cache_size` é uma estimativa usada pelo planner, não memória reservada. A média de memória do banco durante a carga foi 377 MiB, frente ao limite de 512 MiB; isso torna aumentos de memória uma mudança que exige cautela e medição de custo.

`last_vacuum` estava vazio e `last_autovacuum` tinha horário para as quatro tabelas. A coleta não registrou `relallvisible`/visibilidade por página; portanto, não conclui se um index-only scan ajudaria o `COUNT`.

## Próximos experimentos sugeridos

1. Pesquisar e testar índices em grupos isolados, sem reunir índices diferentes num único experimento. A primeira hipótese é `itens_pedido(pedido_id)` (ou `(pedido_id, id)` se o plano/ordenação justificar); medir tamanho com `pg_relation_size`, verificar o contrato e medir as sete rotas, pois o índice também pode afetar os relatórios.
2. Separadamente, testar `pedidos(cliente_id, criado_em DESC, id DESC)` e reavaliar o N+1 de pedidos do cliente. Registrar se as duas mudanças foram isoladas e os efeitos medidos.
3. Só depois comparar o índice de expressão em `lower(email)`, `pedidos(status, criado_em DESC, id DESC)`, `pg_trgm` e alternativas para relatórios, cada qual em experimento próprio.
4. Após observar os planos com índices, decidir se vale testar paralelismo, JIT ou configurações do PostgreSQL; comparar CPU, memória, latência e espaço, além de req/s.
5. Se a atribuição por consulta seguir necessária, planejar uma captura com `pg_stat_statements` em mudança diagnóstica separada e reinício documentado.

Esses itens são hipóteses de trabalho, não resultados de otimização. Nenhuma mudança de performance foi feita nesta etapa.
