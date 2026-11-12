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

As três execuções usaram 20 VUs, duração configurada de 60 s, aquecimento de 15 s e semente 42. As três mantiveram o contrato e registraram zero erros. A tabela abaixo transcreve as métricas HTTP do k6. CPU e memória não são incluídas porque a auditoria encontrou inconsistências entre `recursos.csv` e `recursos.txt` (detalhes na seção de integridade das métricas).

| Execução e evidência | Requisições | Req/s | Duração k6 (s) | Latência média (ms) | p95 geral (ms) | Erros |
|---|---:|---:|---:|---:|---:|---:|
| [172817](../resultados/20261107-172817-00-linha-de-base/) | 197 | 2,84 | 69,3 | 6.653,5 | 23.228,1 | 0% |
| [173048](../resultados/20261107-173048-00-linha-de-base/) | 173 | 2,47 | 70,2 | 7.559,6 | 26.412,7 | 0% |
| [173256](../resultados/20261107-173256-00-linha-de-base/) | 180 | 2,62 | 68,6 | 7.202,5 | 24.812,1 | 0% |
| **Mediana das três execuções** | **180** | **2,62** | **69,3** | **7.202,5** | **24.812,1** | **0%** |

As medianas foram calculadas separadamente por coluna, ordenando os três valores e escolhendo o valor central; não foram calculadas a partir de uma execução composta. Os números por execução vêm de `resumo.txt` e `resumo-k6.json` nas pastas ligadas acima.

### Janela de medição e amostras por rota

O `medir.sh` passa `DURACAO=60s` ao cenário k6 `constant-vus`, com `gracefulStop: 30s`. O teste não chama `sleep()` entre requisições: cada VU faz uma requisição e inicia a próxima ao terminar a anterior. Nos `resumo-k6.json`, `state.testRunDurationMs` foi 69.314,5 ms, 70.175,6 ms e 68.577,8 ms. A taxa impressa pelo k6 corresponde a `http_reqs.count / http_reqs.values.rate` (tempo efetivo do teste), não à contagem dividida pelos 60 segundos nominais. As requisições em andamento ao fim do cenário e o encerramento gracioso tornam a janela observada maior; portanto, não se deve inferir a taxa usando apenas a duração configurada.

O perfil de carga escolhe páginas de pedidos entre 1 e 1000; busca produtos com os termos `cadeira`, `mesa`, `lumin`, `teclado`, `monitor`, `ergo`, `sem fio`, `portatil`, `modelo 12`, `slim`, `reforcada` e `webcam` (todos com pelo menos três caracteres); gera relatórios com janela móvel de sete dias; e chama `top-produtos?limite=10`. Não varia buscas com termos menores, relatórios até 31 dias ou outros limites de top produtos. O cenário é `constant-vus`, com 20 VUs, sem `sleep()` entre requisições e `gracefulStop=30s`. As amostras por rota, na ordem das três execuções, foram:

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

No modelo fechado e sem pausa, a relação de Little permite comparar a latência média observada com `N/X` (VUs divididos pela taxa de conclusão) num regime estável. Essa relação estima o tempo médio no sistema, mas não o decompõe entre fila e serviço nem prova, isoladamente, que a capacidade foi excedida. O diagnóstico de 2 versus 20 VUs, adicionado adiante, explora essa sensibilidade sem atribuir todo o p95 à fila.

## Achados e hipóteses

### 1. Pedidos do cliente fazem trabalho repetido e sem índices de apoio

Na rota [`GET /clientes/:id/pedidos`](../api/src/rotas.js), o código busca os pedidos, percorre cada pedido para consultar seus itens e, depois, percorre cada item para buscar o produto ([rotas.js, linha 75](../api/src/rotas.js#L75)). Isso produz consultas sequenciais repetidas. Além disso, [`consultar()`](../api/src/db.js) instancia um novo `Client`, conecta, executa uma consulta e fecha a conexão em cada chamada ([db.js, linhas 11–18](../api/src/db.js#L11)).

O banco só tem índices de chave primária. No plano do cliente 7, a busca de pedidos fez `Parallel Seq Scan` em `pedidos` (500 mil linhas) e sort; levou 167,715 ms fora de carga. A consulta de itens do pedido 329786 fez `Parallel Seq Scan` em `itens_pedido` (1,5 milhão de linhas); o plano reportou 499.999 linhas filtradas e levou 102,538 ms. A busca do produto por ID, em contraste, usou a chave primária e levou 0,049 ms.

**Hipótese:** varreduras completas repetidas, mais conexões abertas e fechadas por consulta, contribuem para a latência e o trabalho do banco nessa rota, que representa 20% das chamadas. O código e os planos sustentam o mecanismo provável; o ganho de cada correção precisa ser medido isoladamente.

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

O `effective_cache_size` é uma estimativa usada pelo planner, não memória reservada. Como as métricas observadas de uso de memória não passaram na verificação de integridade descrita adiante, este relatório não usa esses valores para inferir pressão de memória nem justificar mudanças de configuração.

`last_vacuum` estava vazio e `last_autovacuum` tinha horário para as quatro tabelas. A coleta não registrou `relallvisible`/visibilidade por página; portanto, não conclui se um index-only scan ajudaria o `COUNT`.

## Experimento 01 — índice em `itens_pedido(pedido_id)`

**Hipótese:** um índice B-tree simples em `itens_pedido(pedido_id)` evita varrer a tabela inteira para localizar os itens de cada pedido. Foi a única mudança de performance: [03-indice-itens-pedido.sql](../banco/03-indice-itens-pedido.sql). O contrato foi mantido nos 42 casos antes da carga e em cada uma das três medições.

O índice ocupa **21 MB** (`pg_size_pretty`). O plano capturado antes da mudança, já salvo em [planos-consultas.txt](./planos-consultas.txt), mostra `Parallel Seq Scan`; o plano posterior mostra `Index Scan` no índice novo, ainda seguido de sort por `id`. Ambos foram capturados e estão transcritos em [experimento-01-plano.txt](./experimento-01-plano.txt). São evidência de que o planner escolheu o índice nesta consulta, não uma comparação controlada de latência: o plano de baseline teve buffers reportados como hits, o plano posterior registrou quatro buffers lidos e tempo de planejamento bem maior. Nos relatórios, o plano isolado de vendas passou de `Parallel Hash Join` com varredura sequencial dos itens para `Nested Loop` com o índice (155,877 ms nesta captura, contra 340,660 ms no plano original); top produtos continuou com `Parallel Seq Scan` dos itens (2.046,655 ms, contra 2.112,070 ms). As capturas não foram pareadas sob as mesmas condições de cache, portanto seus tempos não provam melhora ou piora de latência; planos posteriores em [experimento-01-planos-relatorios.txt](./experimento-01-planos-relatorios.txt).

### Medições

As três execuções usaram commit `e3771f3`, 20 VUs, 60s nominais, aquecimento de 15s e seed 42; cada `contexto.txt` registra zero arquivos alterados. Foram executadas em 12/11, cinco dias depois da baseline de 07/11. No Git Bash do Windows, foi necessário definir `MSYS_NO_PATHCONV=1` para impedir que o argumento `/carga/teste-carga.js` fosse reescrito como caminho local; a tentativa inicial sem a variável falhou antes de executar o k6 e foi excluída. As pastas completas têm todos os arquivos, inclusive resultados por rota, contrato e recursos.

| Execução | Janela efetiva (s) | Requisições | Req/s | Latência média (ms) | p95 geral (ms) | Erros |
|---|---:|---:|---:|---:|---:|---:|
| [161707](../resultados/20261112-161707-01-indice-itens-pedido/) | 65,7 | 281 | 4,28 | 4.540,1 | 16.257,3 | 0% |
| [161931](../resultados/20261112-161931-01-indice-itens-pedido/) | 66,2 | 260 | 3,93 | 4.864,9 | 16.981,7 | 0% |
| [162145](../resultados/20261112-162145-01-indice-itens-pedido/) | 80,7 | 269 | 3,33 | 5.224,9 | 18.388,5 | 0% |
| **Mediana do experimento** | **66,2** | **269** | **3,93** | **4.864,9** | **16.981,7** | **0%** |

Como indicador principal de desempenho, a mediana de throughput foi 2,62 req/s na baseline e 3,93 req/s na primeira série com índice (+50%, descritivo). Uma repetição posterior com o mesmo índice teve 3,61 req/s de mediana em 20 VUs (+38% contra a baseline), mostrando que o throughput variou menos que o p95 entre as séries com índice. A mediana do p95 foi 24.812 ms na baseline, 16.982 ms na primeira série com índice e 23.399 ms na repetição diagnóstica do mesmo índice. A queda inicial de 7,83s quase se iguala à subida posterior de 6,42s; por isso, o p95 não deve ser apresentado como uma melhoria independente nem como evidência causal. A rota diretamente relacionada, `pedidos-do-cliente`, teve mediana dos p95 por execução de 29.966 ms para 15.737 ms, mas as amostras por execução (37–40 na baseline e 54–59 no experimento) e as condições entre séries também limitam a inferência. A baseline e a primeira série com índice ocorreram com cinco dias de diferença e outros containers ativos durante a série nova; uma janela efetiva foi 80,7s. As comparações entre séries permanecem descritivas, não causais.

| Rota | p95 mediano baseline (ms) | p95 mediano com índice (ms) | Amostras por execução: baseline → experimento |
|---|---:|---:|---:|
| `cliente` | 660,2 | 671,4 | 47–51 → 63–68 |
| `cliente-por-email` | 3.718,2 | 4.798,1 | 28–36 → 42–45 |
| `pedidos-do-cliente` | 29.966,0 | 15.737,0 | 37–40 → 54–59 |
| `pedidos-por-status` | 15.433,6 | 18.934,4 | 20–22 → 36–38 |
| `busca-produtos` | 1.778,6 | 950,7 | 27–33 → 44–50 |
| `vendas-por-dia` | 14.557,6 | 46.518,2 | 12–13 → 16–20 |
| `top-produtos` | 16.200,0 | 32.524,4 | 1–2 → 3–4 |

As amostras por rota são pequenas, sobretudo para relatórios; esses p95 não são estimativas robustas de cauda. O p95 de vendas subiu nas amostras da carga apesar da mudança de plano isolado; com 12–20 observações por execução e condições não pareadas, o resultado é **inconclusivo**: não explica nem descarta regressão ou ruído. Top produtos teve só 1–4 amostras por execução e continuou varrendo itens no plano; seu p95 não é interpretável.

O diagnóstico com a mesma versão e 2 versus 20 VUs está na seção seguinte. Ele mostra throughput quase estável com latência média e p95 muito maiores em 20 VUs, comportamento compatível com contenção/espera, mas não permite concluir que o p95 seja principalmente fila nem que a carga exceda uma capacidade sustentável específica.

**Conclusão provisória:** o índice é usado no plano e é plausível mantê-lo para o próximo teste, mas a diferença de throughput entre baseline e índice ainda não é causalmente atribuível a ele. O throughput é o indicador principal nesta comparação; o p95 variou muito inclusive entre séries com o mesmo índice. O resultado de vendas por rota é inconclusivo, e o diagnóstico de VUs não separa espera de execução. Os dados brutos não foram alterados.

## Diagnóstico de concorrência — 2 versus 20 VUs

Em 12/11, rodei três medições com 2 VUs e, em seguida, três com 20 VUs, mantendo a versão com o índice (commit `7412e60`), duração nominal de 60s, aquecimento de 15s e seed 42. Os seis `contexto.txt` registram zero arquivos alterados; todas as execuções mantiveram as 42 respostas do contrato e tiveram 0% de erros. As pastas têm os dados completos: [2 VUs, rodada 1](../resultados/20261112-171024-diag-vus-02/), [rodada 2](../resultados/20261112-171229-diag-vus-02/), [rodada 3](../resultados/20261112-171429-diag-vus-02/); [20 VUs, rodada 1](../resultados/20261112-171643-diag-vus-20/), [rodada 2](../resultados/20261112-171844-diag-vus-20/), [rodada 3](../resultados/20261112-172041-diag-vus-20/).

| Perfil | Req/s, por rodada | Latência média HTTP, por rodada (ms) | `N/X` aprox., por rodada (ms) | Mediana req/s | Mediana latência média (ms) | Mediana `N/X` (ms) | Mediana p95 (ms) |
|---|---|---|---|---:|---:|---:|---:|
| 2 VUs | 3,05 / 3,39 / 3,81 | 653,0 / 589,1 / 524,9 | 654,8 / 590,4 / 525,2 | 3,39 | 589,1 | 590,4 | 1.777,5 |
| 20 VUs | 3,96 / 3,51 / 3,61 | 4.842,0 / 5.500,1 / 5.392,0 | 5.046,6 / 5.704,1 / 5.538,1 | 3,61 | 5.392,0 | 5.538,1 | 23.399,1 |

Com dez vezes mais VUs, o throughput mediano subiu apenas de 3,39 para 3,61 req/s (cerca de 6,5%), enquanto a latência média passou de 589 ms para 5.392 ms e o p95 mediano de 1,78s para 23,40s. O throughput é a evidência principal de um platô para este perfil de rotas; o p95 reforça a sensibilidade à concorrência, mas é mais variável. As latências médias observadas são próximas de `N/X`, conforme esperado para este cenário fechado sem pausa. Isso estima o tempo médio no sistema, não divide esse tempo entre execução e espera; portanto, o platô é compatível com saturação/contenção, mas não prova sua causa.

As rodadas foram feitas em blocos (primeiro todas as de 2 VUs, depois todas as de 20 VUs), não alternadas. Outros containers continuavam ativos. Além disso, o p95 mediano de 20 VUs nesta série foi 23,4s, contra 17,0s na série anterior com o mesmo índice. Portanto, variação temporal e carga externa podem explicar parte da diferença; o diagnóstico não é uma comparação causal nem substitui uma repetição controlada.

### Integridade das métricas de recursos

Na conferência dos arquivos, incluí também as três rodadas de baseline de 07/11. Em duas delas, `recursos.csv` tinha uma amostra por container a mais que `recursos.txt`; isso também ocorreu nas três rodadas do experimento 01 e em cinco das seis rodadas do diagnóstico de concorrência. No conjunto, 10 de 12 rodadas têm uma amostra extra no CSV. Além disso, os máximos de CPU em `recursos.txt` são menores que amostras correspondentes no CSV; por exemplo, a API da primeira baseline tem pico de 24,38% no CSV contra máximo reportado de 9,4%, e a primeira rodada do experimento 01 tem 30,48% contra 9,5%. Não alterei os arquivos gerados. Até reconciliar a agregação de [medir.sh](../scripts/medir.sh), este relatório não usa CPU ou memória como evidência ou argumento de comparação, nem trata os agregados de `recursos.txt` como resumo exato de todos os registros do CSV.

## Próximos experimentos sugeridos

1. Se for necessária uma conclusão mais forte sobre concorrência, repetir os perfis de 2 e 20 VUs alternando a ordem, em ambiente estável e sem outras cargas relevantes; manter como diagnóstico, não como resultado oficial antes/depois.
2. Se a atribuição do ganho ao índice for necessária, medir baseline sem índice e versão com índice nas mesmas condições e no mesmo período, com três repetições por versão.
3. Reconciliar a agregação dos dados de recursos sem editar os resultados já gravados nem a régua protegida; até lá, limitar as conclusões a HTTP/k6 e aos planos.
4. Depois, em experimento separado, testar `pedidos(cliente_id, criado_em DESC, id DESC)` preservando o índice atual; verificar contrato, plano, custo em espaço e efeitos em todas as rotas.
5. Separadamente, comparar N+1 e pooling na API; depois testar `lower(email)`, status/paginação, `pg_trgm` e alternativas para relatórios, cada qual isoladamente.
6. Após observar esses planos, decidir se vale testar paralelismo, JIT ou configuração do PostgreSQL; se necessário, planejar ativação de `pg_stat_statements` como mudança diagnóstica separada.

Esses itens são hipóteses futuras. O experimento 01 foi concluído e seus resultados completos estão nas pastas ligadas acima.
