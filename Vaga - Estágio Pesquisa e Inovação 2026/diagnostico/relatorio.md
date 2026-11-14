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

As três execuções usaram 20 VUs, duração configurada de 60 s, aquecimento de 15 s e semente 42. As três mantiveram o contrato e registraram zero erros. A tabela abaixo transcreve as métricas HTTP do k6; as de CPU e memória foram recalculadas separadamente dos CSVs e são discutidas na seção de integridade.

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

As primeiras séries, feitas em 07/11 e 12/11, tiveram medianas de 2,62 e 3,93 req/s; seus p95 foram 24.812 e 16.982 ms. A repetição diagnóstica posterior com o índice teve 3,61 req/s e p95 de 23.399 ms. Essas capturas iniciais não são comparáveis de forma causal: datas e janelas diferiram, e a oscilação do p95 entre séries com o índice foi quase tão grande quanto a diferença inicial. Elas permanecem registradas como evidência exploratória; a avaliação principal passa a ser a repetição alternada descrita a seguir.

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

### Série principal intercalada — ordem fixa sem/com índice

Em 12/11, comparei a versão sem o índice (`9b6b69c`) com a versão que o inclui (`59124a7`). A comparação do histórico confirmou que a mudança funcional relevante entre elas é o arquivo SQL do índice; código da API, carga, geração determinística dos dados, estrutura e limites do Compose permaneceram iguais. Cada variante usou um volume de banco recém-gerado com os mesmos dados sintéticos. Antes da série principal, cada banco teve três execuções preliminares, também preservadas em `resultados/`; elas não entram na tabela abaixo. Na série principal, a sequência foi sempre sem índice→com índice em cada par: sem, com, sem, com, sem, com. Portanto, os pares foram intercalados, mas a ordem não foi balanceada nem sorteada. Só um stack do desafio ficou ativo por vez, e os containers externos foram pausados durante as medições.

As três execuções exploratórias com índice em um volume anterior ([1](../resultados/20261112-183330-02-control-on-1/), [2](../resultados/20261112-183902-02-control-on-2/), [3](../resultados/20261112-184416-02-control-on-3/)) também foram preservadas, mas não usadas na comparação principal porque aquele banco tinha idade diferente. Elas registraram 4,40 / 4,80 / 4,83 req/s e p95 de 12.496,0 / 11.037,4 / 10.580,4 ms; são evidência exploratória, não uma extensão da série principal.

Todas as execuções usaram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. Os contratos passaram nos 42 casos e todas as rodadas tiveram zero erros.

| Variante | Req/s por rodada | Mediana req/s | p95 por rodada (ms) | Mediana p95 (ms) |
|---|---|---:|---|---:|
| Sem índice | 2,71 / 2,77 / 2,55 | 2,71 | 23.586,6 / 23.724,1 / 25.501,5 | 23.724,1 |
| Com índice | 4,83 / 4,48 / 4,91 | 4,83 | 12.002,6 / 12.888,6 / 11.382,1 | 12.002,6 |

Pastas sem índice: [rodada 1](../resultados/20261112-185839-02-control-alt-off-1/), [rodada 2](../resultados/20261112-190406-02-control-alt-off-2/), [rodada 3](../resultados/20261112-191019-02-control-alt-off-3/). Pastas com índice: [rodada 1](../resultados/20261112-190132-02-control-alt-on-1/), [rodada 2](../resultados/20261112-190751-02-control-alt-on-2/), [rodada 3](../resultados/20261112-191255-02-control-alt-on-3/).

As faixas observadas foram 2,55–2,77 e 4,48–4,91 req/s; para p95 geral, 23.586,6–25.501,5 e 11.382,1–12.888,6 ms. As razões pareadas foram:

| Par (sem→com índice) | Req/s | Razão de throughput | p95 geral (ms) |
|---|---:|---:|---:|
| 1 | 2,71→4,83 | 1,78× (+78,2%) | 23.586,6→12.002,6 (−49,1%) |
| 2 | 2,77→4,48 | 1,62× (+61,7%) | 23.724,1→12.888,6 (−45,7%) |
| 3 | 2,55→4,91 | 1,93× (+92,5%) | 25.501,5→11.382,1 (−55,4%) |

Na mediana desta série, o throughput foi 78,1% maior e o p95 geral 49,4% menor com o índice. O throughput é a métrica primária; p95 dá contexto de latência, não uma confirmação independente. Os resultados são consistentes com contribuição do índice neste perfil sintético, mas a ordem sempre sem→com deixa deriva temporal confundida com a variante; não atribuo causalmente toda a diferença ao índice. Não demonstram benefício em cargas de escrita nem igual ganho em outros ambientes. O custo de CPU e memória recalculado dos CSVs está na seção de integridade abaixo.

O diagnóstico com a mesma versão e 2 versus 20 VUs está na seção seguinte. Ele mostra throughput quase estável com latência média e p95 muito maiores em 20 VUs, comportamento compatível com contenção/espera, mas não permite concluir que o p95 seja principalmente fila nem que a carga exceda uma capacidade sustentável específica.

**Conclusão provisória:** a série intercalada sustenta uma associação favorável entre o índice, throughput e p95 geral neste workload sintético; a ordem fixa impede tratar a comparação como estimativa causal limpa. A conclusão se limita a este banco, perfil de leitura e máquina e não prova benefício em escrita. O resultado de vendas por rota permanece inconclusivo, e o diagnóstico de VUs não separa execução de espera. Os dados brutos não foram alterados.

## Experimento 02 — índice para pedidos por cliente

**Hipótese:** um B-tree em `pedidos(cliente_id, criado_em DESC, id DESC)` reduziria a varredura e ordenação de `GET /clientes/:id/pedidos`, cuja consulta filtra pelo cliente e ordena pelos outros dois campos. A mudança ficou isolada em `banco/04-indice-pedidos-cliente-criado-em.sql` (commit `64e4fe4`); API, carga, contrato, dados gerados e limites dos containers não mudaram. O baseline já contém o índice de itens `itens_pedido(pedido_id)` do experimento 01; este experimento compara a ausência e a presença apenas do índice novo de pedidos.

O baseline (`91a528e`) e a variante (`64e4fe4`) foram executados em volumes novos com os mesmos dados determinísticos. Houve três execuções preliminares por variante para aquecimento; elas foram preservadas, mas excluídas da comparação principal. Depois, medi três pares intercalados, sempre na ordem sem índice novo→com índice novo; a ordem não foi balanceada nem sorteada. Apenas um stack do desafio ficou ativo e os containers externos ficaram pausados. Todas as medições usaram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. Os 42 casos do contrato passaram e as seis rodadas principais tiveram zero erros.

| Variante | Req/s por rodada | Mediana req/s | p95 geral por rodada (ms) | Mediana p95 geral (ms) | p95 de `pedidos-do-cliente` por rodada (ms) | Mediana p95 da rota (ms) |
|---|---|---:|---|---:|---|---:|
| Sem índice novo (índice de itens presente) | 4,69 / 5,23 / 4,86 | 4,86 | 11.374,7 / 9.983,8 / 12.090,6 | 11.374,7 | 12.305,5 / 11.204,8 / 13.104,1 | 12.305,5 |
| Com índice novo | 5,65 / 5,77 / 5,90 | 5,77 | 10.198,6 / 10.165,1 / 8.899,7 | 10.165,1 | 9.893,3 / 8.551,4 / 8.539,9 | 8.551,4 |

Resultados sem índice novo: [rodada 1](../resultados/20261113-161645-02-pedidos-cliente-alt-off/), [rodada 2](../resultados/20261113-162202-02-pedidos-cliente-alt-off/), [rodada 3](../resultados/20261113-162720-02-pedidos-cliente-alt-off/). Com índice novo: [rodada 1](../resultados/20261113-161925-02-pedidos-cliente-alt-on/), [rodada 2](../resultados/20261113-162441-02-pedidos-cliente-alt-on/), [rodada 3](../resultados/20261113-163002-02-pedidos-cliente-alt-on/).

As faixas foram 4,69–5,23 e 5,65–5,90 req/s; os p95 gerais variaram de 9.983,8–12.090,6 e 8.899,7–10.198,6 ms (faixas sobrepostas); os p95 da rota variaram de 11.204,8–13.104,1 e 8.539,9–9.893,3 ms (sem sobreposição). As razões pareadas:

| Par (sem→com índice novo) | Req/s | Razão de throughput | p95 geral (ms) | p95 da rota (ms) |
|---|---:|---:|---:|---:|
| 1 | 4,69→5,65 | 1,20× (+20,5%) | 11.374,7→10.198,6 (−10,3%) | 12.305,5→9.893,3 (−19,6%) |
| 2 | 5,23→5,77 | 1,10× (+10,3%) | 9.983,8→10.165,1 (+1,8%) | 11.204,8→8.551,4 (−23,7%) |
| 3 | 4,86→5,90 | 1,21× (+21,4%) | 12.090,6→8.899,7 (−26,4%) | 13.104,1→8.539,9 (−34,8%) |

A mediana do throughput geral aumentou 18,7%; o p95 geral caiu 10,6%, e o p95 da rota-alvo caiu 30,5%. O throughput é a métrica primária; os p95 oferecem contexto de latência, não confirmações independentes. O `EXPLAIN ANALYZE` representativo mudou de `Parallel Seq Scan` mais `Sort` para `Index Scan` pelo novo índice, que ocupa 19 MB. A captura confirma o caminho do plano, não uma comparação de latência: os caches diferiam e os tempos absolutos dos planos não devem ser comparados. Os três pares favoreceram o throughput, mas a ordem fixa, seis rodadas e uma máquina não permitem atribuir causalmente toda a diferença nem provar ganho universal.

As preliminares excluídas foram preservadas em [sem índice novo](../resultados/20261113-155959-02-pedidos-cliente-off/), [2](../resultados/20261113-160209-02-pedidos-cliente-off/), [3](../resultados/20261113-160418-02-pedidos-cliente-off/) e [com índice novo](../resultados/20261113-160958-02-pedidos-cliente-fresh-on/), [2](../resultados/20261113-161159-02-pedidos-cliente-fresh-on/), [3](../resultados/20261113-161358-02-pedidos-cliente-fresh-on/). Para transparência, sem índice novo: 3,44 / 2,82 / 3,55 req/s e p95 de 21.686,7 / 21.919,1 / 18.656,2 ms; com índice novo: 4,62 / 4,19 / 3,89 req/s e p95 de 16.885,2 / 25.959,9 / 23.737,9 ms. Por serem execuções de aquecimento/preliminares, não foram combinadas com a série primária.

Uma tentativa anterior, [20261112-193751-02-pedidos-cliente-off](../resultados/20261112-193751-02-pedidos-cliente-off/), também foi excluída: o k6 registrou 223 requisições, 2,65 req/s, p95 de 27.661,5 ms e 3 respostas que falharam no check de status 200 (1,35%). As falhas ocorreram em `pedidos-por-status` (2/30) e `vendas-por-dia` (1/16). A causa não foi confirmada; não atribuo os erros a containers externos nem a uma causa específica. O registro bruto foi preservado, mas não há evidência para incluí-lo na comparação válida.

## Experimento 03 — eliminação do N+1

**Hipótese e mudança:** `GET /clientes/:id/pedidos` fazia consultas repetidas para buscar pedidos, itens e produtos. A rota passou a obter esses dados em um `LEFT JOIN` e reconstruir a resposta, os totais e a ordenação em memória. O pool não foi introduzido nesta etapa; os dois índices anteriores estavam presentes em ambos os braços. A variante A é o commit `888e703`; a B, com a rota alterada, é `786a18d`.

A repetição usou 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42, com a ordem balanceada A→B, B→A, A→B. Worktrees limpos registraram o commit correto e zero arquivos alterados em todos os contextos; o banco permaneceu no mesmo container e volume, e somente a API foi reconstruída entre braços. Os 42 casos do contrato passaram após cada medição. O primeiro par teve um timeout k6 em cada braço; as outras quatro rodadas tiveram zero erros.

| Variante | Req/s por rodada | Mediana req/s | Latência mediana geral por rodada (ms) | p95 geral por rodada (ms) | p95 de `pedidos-do-cliente` por rodada (ms) |
|---|---|---:|---|---|---|
| Sem N+1 (A) | 2,90 / 4,14 / 4,33 | 4,14 (2,90–4,33) | 1.397,0 / 1.199,3 / 1.226,8 | 33.237,9 / 19.636,8 / 15.611,0 | 9.820,5 / 9.225,7 / 11.947,1 |
| N+1 removido (B) | 3,20 / 2,53 / 4,80 | 3,20 (2,53–4,80) | 910,3 / 856,5 / 716,9 | 28.308,2 / 37.188,0 / 20.429,5 | 17.498,4 / 19.177,8 / 4.747,2 |

| Par (ordem executada) | Req/s A→B (variação) | p95 geral A→B (variação) | p95 da rota A→B (variação) |
|---|---:|---:|---:|
| 1 (A→B) | 2,90→3,20 (+10,3%) | 33.237,9→28.308,2 (−14,8%) | 9.820,5→17.498,4 (+78,2%) |
| 2 (B→A) | 4,14→2,53 (−38,9%) | 19.636,8→37.188,0 (+89,4%) | 9.225,7→19.177,8 (+107,9%) |
| 3 (A→B) | 4,33→4,80 (+10,9%) | 15.611,0→20.429,5 (+30,9%) | 11.947,1→4.747,2 (−60,3%) |

Nesta série, a mediana de throughput caiu 22,7% (4,14→3,20 req/s), o p95 geral aumentou 44,2% e o p95 da rota aumentou 78,2%. As faixas de ambos os braços se sobrepõem e os pares divergem; não há evidência estável de ganho. As duas respostas com timeout foram uma chamada de `vendas-por-dia` no braço A e uma de `pedidos-por-status` no B, ambas no primeiro par. A conclusão é inconclusiva; os resultados anteriores, mais favoráveis, são exploratórios e não foram combinados com esta repetição.

Resultados A: [A1](../resultados/20261114-151556-n1-rerun-01-a/), [A2](../resultados/20261114-152435-n1-rerun-02-a/), [A3](../resultados/20261114-152646-n1-rerun-03-a/). Resultados B: [B1](../resultados/20261114-151931-n1-rerun-01-b/), [B2](../resultados/20261114-152153-n1-rerun-02-b/), [B3](../resultados/20261114-152942-n1-rerun-03-b/).

## Experimento 04 — pool de conexões separado

**Hipótese e mudança:** após eliminar o N+1, testei um `Pool` compartilhado limitado a 10 conexões. A rota otimizada permaneceu igual nos dois braços; somente `db.js` e o encerramento do servidor mudaram. O braço A corresponde ao commit `786a18d` (sem pool) e o B ao `518872a` (pool).

Foram usados os mesmos parâmetros e a ordem balanceada A→B, B→A, A→B. Os metadados dos seis resultados registram o commit correspondente e zero arquivos alterados; o contrato passou nos 42 casos após cada medição. O banco permaneceu no mesmo container e volume, somente a API foi reconstruída ao alternar, e os containers externos ficaram parados.

| Variante | Req/s por rodada | Mediana req/s | Latência mediana geral por rodada (ms) | p95 geral por rodada (ms) | p95 de `pedidos-do-cliente` por rodada (ms) |
|---|---|---:|---|---|---|
| Sem pool | 3,32 / 3,63 / 2,94 | 3,32 (2,94–3,63) | 823,9 / 576,8 / 797,5 | 27.642,0 / 35.288,3 / 42.481,9 | 3.808,5 / 3.713,0 / 1.415,5 |
| Com pool | 4,26 / 4,36 / 4,31 | 4,31 (4,26–4,36) | 1.938,4 / 1.573,8 / 2.094,0 | 17.094,6 / 21.597,6 / 15.094,5 | 5.690,5 / 5.631,2 / 7.767,7 |

| Par (ordem executada) | Req/s sem→com (ganho) | p95 geral sem→com (ms) | p95 da rota sem→com (ms) |
|---|---:|---:|---:|
| 1 (A→B) | 3,32→4,26 (+28,3%) | 27.642,0→17.094,6 (−38,2%) | 3.808,5→5.690,5 (+49,4%) |
| 2 (B→A) | 3,63→4,36 (+20,1%) | 35.288,3→21.597,6 (−38,8%) | 3.713,0→5.631,2 (+51,7%) |
| 3 (A→B) | 2,94→4,31 (+46,6%) | 42.481,9→15.094,5 (−64,5%) | 1.415,5→7.767,7 (+448,5%) |

O throughput mediano aumentou 29,8% e o p95 geral caiu 51,6%, em todos os pares. Em contrapartida, a latência mediana geral aumentou 143,1% e o p95 da rota aumentou 53,3%, também nos três pares. Portanto, o pool preserva um trade-off: favorece throughput e cauda geral, mas torna mais lenta a rota-alvo. Não se pode inferir redução geral de recursos nem extrapolar para produção.

Resultados A: [A1](../resultados/20261114-153158-pool-rerun-01-a/), [A2](../resultados/20261114-153949-pool-rerun-02-a/), [A3](../resultados/20261114-154204-pool-rerun-03-a/). Resultados B: [B1](../resultados/20261114-153505-pool-rerun-01-b/), [B2](../resultados/20261114-153711-pool-rerun-02-b/), [B3](../resultados/20261114-154512-pool-rerun-03-b/).

## Execuções excluídas dos experimentos 03 e 04

Duas tentativas iniciais de executar `medir.sh` pelo Git Bash falharam antes de gerar medições: a conversão de caminhos do MSYS fez o k6 procurar `/carga/teste-carga.js` em `C:/Program Files/Git/carga/teste-carga.js`. Não são erros da API e não há métricas válidas a incluir.

Também foram preservadas, mas excluídas, [uma rodada sem N+1](../resultados/20261113-171831-n1-off-par-01-a/) e [uma com N+1](../resultados/20261113-172155-n1-on-par-01-b/); uma [tentativa interrompida](../resultados/20261113-172413-n1-on-par-02-a/) não concluiu o contrato. As séries inicialmente tratadas como válidas em 13/11 permanecem arquivadas, mas não são evidência principal: os `contexto.txt` de braços com mudança registram arquivos sem commit (1 no braço B do N+1 e 1/3 nos braços A/B do pool). A repetição de 14/11 substitui essas comparações sem apagar seus dados. Nela, dois resultados do N+1 tiveram timeout k6 (um em cada braço do primeiro par); os demais não tiveram erros. Todos os 12 contratos passaram nos 42 casos. Worktrees limpos registraram zero arquivos alterados; o identificador do banco ficou constante (`ead6809…`) e os containers externos foram parados. Os arquivos brutos novos estão no commit `4ecae3f`, separado dos commits de código.

## Diagnóstico de concorrência — 2 versus 20 VUs

Em 12/11, rodei três medições com 2 VUs e, em seguida, três com 20 VUs, mantendo a versão com o índice de itens (commit `7412e60`), duração nominal de 60s, aquecimento de 15s e seed 42. Os seis `contexto.txt` registram zero arquivos alterados; todas as execuções mantiveram as 42 respostas do contrato e tiveram 0% de erros. As pastas têm os dados completos: [2 VUs, rodada 1](../resultados/20261112-171024-diag-vus-02/), [rodada 2](../resultados/20261112-171229-diag-vus-02/), [rodada 3](../resultados/20261112-171429-diag-vus-02/); [20 VUs, rodada 1](../resultados/20261112-171643-diag-vus-20/), [rodada 2](../resultados/20261112-171844-diag-vus-20/), [rodada 3](../resultados/20261112-172041-diag-vus-20/).

| Perfil | Req/s, por rodada | Latência média HTTP, por rodada (ms) | `N/X` aprox., por rodada (ms) | Mediana req/s | Mediana latência média (ms) | Mediana `N/X` (ms) | Mediana p95 (ms) |
|---|---|---|---|---:|---:|---:|---:|
| 2 VUs | 3,05 / 3,39 / 3,81 | 653,0 / 589,1 / 524,9 | 654,8 / 590,4 / 525,2 | 3,39 | 589,1 | 590,4 | 1.777,5 |
| 20 VUs | 3,96 / 3,51 / 3,61 | 4.842,0 / 5.500,1 / 5.392,0 | 5.046,6 / 5.704,1 / 5.538,1 | 3,61 | 5.392,0 | 5.538,1 | 23.399,1 |

Com dez vezes mais VUs, o throughput mediano subiu apenas de 3,39 para 3,61 req/s (cerca de 6,5%), enquanto a latência média passou de 589 ms para 5.392 ms e o p95 mediano de 1,78s para 23,40s. O throughput é a evidência principal de um platô para este perfil de rotas; o p95 reforça a sensibilidade à concorrência, mas é mais variável. As latências médias observadas são próximas de `N/X`, conforme esperado para este cenário fechado sem pausa. Isso estima o tempo médio no sistema, não divide esse tempo entre execução e espera; portanto, o platô é compatível com saturação/contenção, mas não prova sua causa.

As rodadas foram feitas em blocos (primeiro todas as de 2 VUs, depois todas as de 20 VUs), não alternadas. Outros containers continuavam ativos. Além disso, o p95 mediano de 20 VUs nesta série foi 23,4s, contra 17,0s na série anterior com o mesmo índice. Portanto, variação temporal e carga externa podem explicar parte da diferença; o diagnóstico não é uma comparação causal nem substitui uma repetição controlada.

### Integridade das métricas de recursos

Recalculei CPU e memória diretamente dos registros de `recursos.csv` com [recalcular-recursos.py](recalcular-recursos.py), sem usar `recursos.txt` e sem alterar [medir.sh](../scripts/medir.sh). O script falha explicitamente em cabeçalhos, linhas ou valores inválidos. Para cada execução, calcula média e máximo numéricos de todos os registros por container; as tabelas abaixo mostram a mediana e a faixa dos três resultados por variante. As rodadas principais têm 35–39 amostras por container, cobrindo 69–77 segundos. Em 11 das 12 rodadas principais, o CSV tem uma amostra por container a mais que o resumo TXT; a origem dessa diferença ainda não foi comprovada. A inspeção somente de leitura do agregador sugere que o pico de CPU pode ser subestimado por comparação textual (por exemplo, em uma execução o TXT apresenta pico de 9,6% para a API, enquanto o CSV contém amostras de até 22,99%). Os percentuais de CPU são os valores do Docker Stats e não foram normalizados pelo limite do container ou pelo throughput; a memória é o valor de uso antes da barra no campo coletado.

| Série e serviço | CPU média por execução (mediana [min–máx], %) | Pico CPU por execução (mediana [min–máx], %) | Memória média por execução (mediana [min–máx], MiB) | Pico de memória por execução (mediana [min–máx], MiB) |
|---|---:|---:|---:|---:|
| Experimento 01 — API, sem→com índice | 9,89 [9,77–10,16]→16,25 [16,14–16,46] | 24,50 [22,99–24,56]→32,41 [31,15–34,23] | 30,25 [29,82–33,20]→34,34 [32,48–34,69] | 39,90 [39,23–41,46]→46,15 [45,00–46,91] |
| Experimento 01 — banco, sem→com índice | 91,16 [91,13–94,02]→91,31 [90,98–91,65] | 117,33 [109,32–118,66]→115,36 [111,03–116,81] | 191,03 [179,13–200,21]→224,99 [202,99–245,63] | 257,10 [227,40–268,10]→301,80 [274,80–333,40] |
| Experimento 02 — API, sem→com índice novo | 16,82 [16,79–17,28]→18,03 [17,44–19,27] | 32,89 [32,34–39,56]→34,88 [31,67–36,91] | 35,99 [34,06–38,01]→36,38 [35,25–37,35] | 46,86 [44,87–51,61]→50,72 [46,53–53,84] |
| Experimento 02 — banco, sem→com índice novo | 90,58 [90,14–91,26]→89,60 [88,16–92,36] | 113,86 [109,21–113,94]→113,18 [107,03–117,17] | 230,34 [229,52–278,66]→225,48 [224,26–226,39] | 342,70 [323,90–383,40]→296,30 [294,90–317,50] |
| Repetição N+1 — API, sem→com | 13,42 [8,70–15,88]→7,57 [6,03–9,96] | 37,67 [32,32–40,33]→33,29 [26,37–49,73] | 47,38 [38,19–53,36]→44,00 [41,73–46,03] | 84,48 [59,89–100,70]→65,62 [57,92–88,29] |
| Repetição N+1 — banco, sem→com | 69,42 [44,39–73,16]→43,36 [34,91–59,64] | 115,72 [113,35–118,41]→112,35 [107,92–113,25] | 381,92 [380,46–384,92]→372,93 [364,11–387,94] | 445,10 [432,50–447,20]→440,30 [436,20–445,70] |
| Repetição pool — API, sem→com | 7,82 [6,34–8,84]→7,58 [7,20–8,12] | 32,22 [30,34–38,11]→32,69 [30,08–34,70] | 47,35 [38,54–50,37]→40,41 [37,73–43,25] | 64,25 [56,46–66,42]→57,08 [52,46–58,06] |
| Repetição pool — banco, sem→com | 45,21 [44,12–49,03]→50,84 [44,78–55,48] | 111,57 [108,65–115,52]→114,20 [113,62–121,67] | 363,89 [359,12–371,83]→373,20 [370,88–395,42] | 435,70 [429,70–440,40]→441,70 [420,00–457,50] |

No experimento 01, o throughput aumentou junto com médias e picos de CPU/memória da API; a média de CPU do banco ficou praticamente estável e sua memória média aumentou. Portanto, estes dados não mostram que o ganho veio sem custo de recursos. No experimento 02, as médias de CPU e memória do banco caíram ligeiramente, enquanto as da API subiram; não há uma redução geral inequívoca. Nenhuma dessas diferenças está normalizada por requisição, e a ordem fixa sem→com deixa possível deriva temporal confundida com a variante.

Na repetição do N+1, as médias de CPU e memória foram menores nos dois serviços, mas o throughput e as latências não mostraram melhora consistente. No pool, a média de CPU ficou próxima na API e aumentou no banco; a memória média diminuiu na API e aumentou no banco. Os picos de CPU calculados a partir dos CSVs ultrapassam 100% em algumas rodadas, apesar do limite configurado, o que reforça a necessidade de tratá-los como observacionais e de não inferir economia. Nenhuma métrica foi normalizada por requisição. As novas rodadas tiveram 36–41 amostras por container; os CSVs e limites estão nas pastas ligadas nas seções dos experimentos 03 e 04.

Incluí também a linha de base de 07/11, antes não coberta pelas conferências anteriores. Nas três execuções, a mediana das médias foi 9,39% CPU e 30,92 MiB para a API, e 88,02% CPU e 375,47 MiB para o banco; as medianas dos picos foram 25,80% e 39,12 MiB para a API, e 108,47% e 455,70 MiB para o banco. As faixas entre execuções foram: médias de CPU 8,37–9,94% (API) e 84,59–91,66% (banco); médias de memória 30,14–31,58 MiB (API) e 372,36–390,29 MiB (banco); picos de CPU 24,38–29,22% e 104,37–112,09%; picos de memória 37,80–40,04 MiB e 443,50–460,30 MiB. Esses valores são recalculados do CSV e não devem ser comparados causalmente às séries posteriores, feitas em outras datas e condições. As inconsistências dos resumos e a janela de amostragem limitam a precisão; as medições servem como descrição observacional, não como custo por requisição ou prova de economia.

## Próximos experimentos sugeridos

1. Se for necessária uma conclusão mais forte sobre concorrência, repetir os perfis de 2 e 20 VUs alternando a ordem, em ambiente estável e sem outras cargas relevantes; manter como diagnóstico, não como resultado oficial antes/depois.
2. N+1 e pool já foram medidos separadamente. O pool permanece na implementação atual por ter elevado throughput em todos os pares e reduzido médias de memória; essa escolha prioriza throughput agregado, não a latência da rota. Antes de finalizar a decisão, repetir a comparação com foco em `pedidos-do-cliente` e avaliar se um limite de pool diferente reduz o p95 sem perder o ganho agregado.
3. Seguir com `lower(email)`, status/paginação, `pg_trgm` e alternativas para relatórios, cada qual isoladamente; priorizar as rotas que seguem com maior latência sob carga.
4. Tratar paralelismo, JIT, `work_mem` e demais parâmetros como experimentos separados das mudanças de consulta. Se necessário, planejar `pg_stat_statements` como mudança diagnóstica própria.

Esses itens são hipóteses futuras. Os experimentos 01 a 04 e seus dados brutos estão registrados nas pastas ligadas acima.
