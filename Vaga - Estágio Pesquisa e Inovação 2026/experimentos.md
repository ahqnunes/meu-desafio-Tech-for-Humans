# Registro de experimentos

Uma linha por mudança aplicada. Os resultados de carga vêm das pastas geradas por `scripts/medir.sh`; as interpretações e limitações estão detalhadas em [diagnostico/relatorio.md](diagnostico/relatorio.md). Os status seguem o enunciado: “Aplicada e medida” ou “Aplicada, sem ganho”. As ideias pesquisadas e ainda não testadas estão em [proximos-testes.md](proximos-testes.md).

| Mudança | Fonte e hipótese | Status | Antes (mediana de 3) | Depois (mediana de 3) | Pastas de resultados | Conclusão |
|---|---|---|---|---|---|---|
| Índice B-tree em `itens_pedido(pedido_id)` | [Plano baseline](diagnostico/planos-consultas.txt) mostrou `Parallel Seq Scan` para buscar itens do pedido; a documentação do [PostgreSQL 16 sobre índices](https://www.postgresql.org/docs/16/indexes-intro.html) descreve como índices podem evitar varreduras completas. Hipótese: o índice reduziria o trabalho para localizar itens por `pedido_id`. | Aplicada e medida. Três pares intercalados na ordem fixa sem→com índice; contrato mantido nos 42 casos. | Mediana 2,71 req/s (faixa 2,55–2,77); p95 geral 23.724,1 ms (23.586,6–25.501,5). | Mediana 4,83 req/s (faixa 4,48–4,91); p95 geral 12.002,6 ms (11.382,1–12.888,6); índice de 21 MB. | Série principal sem índice: [rodada 1](resultados/20261112-185839-02-control-alt-off-1/), [2](resultados/20261112-190406-02-control-alt-off-2/), [3](resultados/20261112-191019-02-control-alt-off-3/). Com índice: [rodada 1](resultados/20261112-190132-02-control-alt-on-1/), [2](resultados/20261112-190751-02-control-alt-on-2/), [3](resultados/20261112-191255-02-control-alt-on-3/). | Throughput +78,1% e p95 −49,4% nas medianas; ganhos pareados de +78,2%, +61,7% e +92,5%. A ordem fixa permite deriva temporal confundida, então não prova causalidade limpa nem generaliza para outras cargas. |
| Índice B-tree em `pedidos(cliente_id, criado_em DESC, id DESC)` | O [plano baseline](diagnostico/planos-consultas.txt) mostrou varredura sequencial e sort para pedidos de um cliente; a documentação do PostgreSQL sobre [índices multicoluna](https://www.postgresql.org/docs/16/indexes-multicolumn.html) fundamenta alinhar índice a filtros e ordenação. Hipótese: reduzir o trabalho de `GET /clientes/:id/pedidos`. | Aplicada e medida. Três pares intercalados na ordem fixa sem→com índice novo; contrato mantido nos 42 casos. | Sem o índice novo, mas já com o índice de itens: mediana 4,86 req/s (4,69–5,23); p95 geral 11.374,7 ms (9.983,8–12.090,6); p95 da rota 12.305,5 ms (11.204,8–13.104,1). | Mediana 5,77 req/s (5,65–5,90); p95 geral 10.165,1 ms (8.899,7–10.198,6); p95 da rota 8.551,4 ms (8.539,9–9.893,3); índice de 19 MB. | Sem índice novo: [rodada 1](resultados/20261113-161645-02-pedidos-cliente-alt-off/), [2](resultados/20261113-162202-02-pedidos-cliente-alt-off/), [3](resultados/20261113-162720-02-pedidos-cliente-alt-off/). Com índice novo: [rodada 1](resultados/20261113-161925-02-pedidos-cliente-alt-on/), [2](resultados/20261113-162441-02-pedidos-cliente-alt-on/), [3](resultados/20261113-163002-02-pedidos-cliente-alt-on/). | Throughput +18,7%, p95 geral −10,6% e p95 da rota −30,5% nas medianas; ganhos pareados de +20,5%, +10,3% e +21,4%. A ordem fixa limita a atribuição causal e a generalização. |
| Remoção do N+1 em `GET /clientes/:id/pedidos` (um `LEFT JOIN`, sem pool) | Fonte: [Yang et al.](https://par.nsf.gov/servlets/purl/10067547) (caso N+1 do Lobsters) e o [código da rota](api/src/rotas.js), que consulta itens e produtos dentro de loops. Hipótese: consolidar as consultas reduz round trips e o p95 de `pedidos-do-cliente`. | Aplicada, sem ganho (resultado inconclusivo). Três pares balanceados; contrato mantido nos 42 casos. | 4,14 req/s (2,90–4,33); p95 geral 19.636,8 ms; p95 da rota 9.820,5 ms; CPU/resposta 0,200. | 3,20 req/s (2,53–4,80); p95 geral 28.308,2 ms; p95 da rota 17.498,4 ms; CPU/resposta 0,160. | Original, com N+1: [A1](resultados/20261114-151556-n1-rerun-01-a/), [A2](resultados/20261114-152435-n1-rerun-02-a/), [A3](resultados/20261114-152646-n1-rerun-03-a/). N+1 removido: [B1](resultados/20261114-151931-n1-rerun-01-b/), [B2](resultados/20261114-152153-n1-rerun-02-b/), [B3](resultados/20261114-152942-n1-rerun-03-b/). | Nas medianas, o original foi melhor em req/s (−22,7% com a remoção) e em p95 (+44,2% geral e +78,2% da rota); só a CPU por resposta caiu (−21,4%). Nos pares, o throughput variou +10,3%, −38,9% e +10,9%, as faixas se sobrepõem e houve um timeout em cada braço do primeiro par. Explicação provável, não testada: o gargalo está no banco de 1 CPU e na fila de 20 VUs, não nos round trips; a variação entre rodadas é maior que o efeito. |
| Pool de até 10 conexões (`Pool` compartilhado), sobre o N+1 removido | Fonte: [node-postgres, Pooling](https://node-postgres.com/features/pooling) e o [acesso ao banco](api/src/db.js), que abre e fecha um cliente por consulta. Hipótese: reutilizar conexões reduz o custo de conexão e melhora o throughput. | Aplicada e medida (com trade-off). Três pares balanceados; contrato mantido nos 42 casos e 0% de erros. | 3,32 req/s (2,94–3,63); p95 geral 35.288,3 ms; p95 da rota 3.713,0 ms; CPU/resposta 0,160. | 4,31 req/s (4,26–4,36); p95 geral 17.094,6 ms; p95 da rota 5.690,5 ms; CPU/resposta 0,135. | Sem pool: [A1](resultados/20261114-153158-pool-rerun-01-a/), [A2](resultados/20261114-153949-pool-rerun-02-a/), [A3](resultados/20261114-154204-pool-rerun-03-a/). Com pool: [B1](resultados/20261114-153505-pool-rerun-01-b/), [B2](resultados/20261114-153711-pool-rerun-02-b/), [B3](resultados/20261114-154512-pool-rerun-03-b/). | Throughput +29,8% (pares +28,3%, +20,1% e +46,6%) e p95 geral −51,6%; CPU por resposta −21,7%. Em contrapartida, p95 da rota +53,3% (pior nos três pares) e latência mediana geral +143,1%. Escolha provisória de throughput agregado, não de latência da rota. |

## Qual baseline cada mudança usou

- **Índice de `itens_pedido`:** a linha de base original (aplicação como veio).
- **Índice de `pedidos`:** o estado com o índice de itens, antes do commit `64e4fe4`.
- **Remoção do N+1:** o estado com os dois índices (commit `888e703`); a mudança está no commit `786a18d`.
- **Pool:** o estado com o N+1 removido (commit `786a18d`); a mudança está no commit `518872a`.
- **Comparação acumulada:** A = original (`9b6b69c`), B = dois índices (`64e4fe4`) e C = versão final (`518872a`).

## Evidência e procedimento

- Mudança registrada no commit `a630b53`; resultados da série controlada foram registrados no commit `a05825d`.
- A série principal intercalou sem índice/com índice em três pares, sempre nessa ordem fixa, usando 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. As variantes usaram volumes novos com dados determinísticos iguais; os containers externos ficaram pausados e apenas um stack do desafio ficou ativo por vez.
- As seis execuções preliminares do experimento 01 foram preservadas, mas excluídas da comparação principal: sem índice, 2,58 / 2,74 / 2,72 req/s e p95 de 25.494,3 / 24.078,1 / 24.612,6 ms; com índice em banco novo, 3,73 / 3,57 / 3,74 req/s e p95 de 19.106,5 / 17.782,2 / 15.054,2 ms. Pastas: [baseline](resultados/20261112-183041-02-control-off-1/), [2](resultados/20261112-183607-02-control-off-2/), [3](resultados/20261112-184139-02-control-off-3/) e [índice novo](resultados/20261112-185117-02-control-fresh-on-1/), [2](resultados/20261112-185337-02-control-fresh-on-2/), [3](resultados/20261112-185548-02-control-fresh-on-3/).
- Outras três execuções exploratórias com índice usaram um volume anterior ([1](resultados/20261112-183330-02-control-on-1/), [2](resultados/20261112-183902-02-control-on-2/), [3](resultados/20261112-184416-02-control-on-3/)); com 4,40 / 4,80 / 4,83 req/s e p95 de 12.496,0 / 11.037,4 / 10.580,4 ms, foram excluídas porque a idade daquele banco era diferente.
- O contrato foi verificado e as seis execuções principais registraram 0% de erros.
- [Plano antes e depois](diagnostico/experimento-01-plano.txt) confirma a troca de `Parallel Seq Scan` para `Index Scan` na consulta representativa. A captura isolada sustenta o uso do índice, não uma comparação controlada de latência.
- As séries iniciais de 07/11 e 12/11 e a repetição diagnóstica permanecem como evidência exploratória. Médias e picos de recursos foram recalculados diretamente dos CSVs; os valores e limites estão em [diagnostico/relatorio.md](diagnostico/relatorio.md). A ordem fixa das variantes limita ambas as comparações.

## Evidência do segundo experimento

- Mudança: commit `64e4fe4`; resultados brutos: registrados em commit separado.
- Foram usadas três execuções preliminares por variante para aquecimento e, depois, três pares intercalados, sempre sem índice novo→com índice novo. Os bancos partiram de volumes novos com dados determinísticos iguais. As medições usaram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42; containers externos pausados e um stack do desafio por vez.
- As execuções preliminares válidas estão em [sem índice novo](resultados/20261113-155959-02-pedidos-cliente-off/), [2](resultados/20261113-160209-02-pedidos-cliente-off/), [3](resultados/20261113-160418-02-pedidos-cliente-off/) e [com índice novo](resultados/20261113-160958-02-pedidos-cliente-fresh-on/), [2](resultados/20261113-161159-02-pedidos-cliente-fresh-on/), [3](resultados/20261113-161358-02-pedidos-cliente-fresh-on/). Seus valores individuais estão no [relatório](diagnostico/relatorio.md); não foram incluídas na comparação principal.
- Uma tentativa inicial com 1,35% de respostas com erro foi preservada em [20261112-193751-02-pedidos-cliente-off](resultados/20261112-193751-02-pedidos-cliente-off/), mas excluída; a causa não foi confirmada e está detalhada no [relatório](diagnostico/relatorio.md). Todas as seis execuções principais tiveram zero erros e o contrato foi mantido nos 42 casos.
- O plano antes/depois está em [experimento-02-plano.txt](diagnostico/experimento-02-plano.txt); comprova o uso do índice, não tempos de latência comparáveis. Médias e picos de recursos foram recalculados dos CSVs; os valores estão no [relatório](diagnostico/relatorio.md).
- A mudança do segundo experimento está no commit `64e4fe4`; suas 12 execuções válidas foram registradas no commit `530274f` (seis preliminares e seis rodadas principais em ordem fixa sem→com).

O diagnóstico complementar de 2 versus 20 VUs não é uma mudança aplicada e, portanto, não aparece como uma otimização adicional. Seus dados e limites estão registrados na seção de concorrência do [relatório](diagnostico/relatorio.md).

## Eficiência estimada de CPU por resposta bem-sucedida

Uma análise posterior combinou a CPU média de `recursos.csv` com a taxa de respostas bem-sucedidas do k6. A mediana pareada da CPU estimada por resposta caiu em cada comparação incremental; fórmula, dados e limitações estão no [relatório](diagnostico/relatorio.md), e a saída reproduzível está em [cpu-por-requisicao-pares.csv](diagnostico/cpu-por-requisicao-pares.csv), gerada por [recalcular-cpu-por-requisicao.py](diagnostico/recalcular-cpu-por-requisicao.py).

| Mudança incremental | CPU estimada (CPU-s/resposta válida, mediana por variante) | Variação pareada mediana (faixa) | Memória média total (MiB, mediana por variante) |
|---|---:|---:|---:|
| Índice `itens_pedido(pedido_id)` | 0,384→0,223 | −41,9% (−44,6% a −34,5%) | 221,3→259,7 (+17,4%) |
| Índice de pedidos por cliente | 0,221→0,187 | −14,2% (−19,0% a −9,1%) | 266,3→262,8 (−1,3%) |
| Remoção do N+1 | 0,200→0,160 | −21,4% (−27,4% a −13,0%) | 429,3→414,7 (−3,4%) |
| Pool de conexões | 0,160→0,135 | −21,7% (−24,8% a −6,7%) | 409,5→414,1 (+1,1%) |

Esses resultados são estimativas de eficiência, não custo monetário. A janela dos CSVs excede a duração medida pelo k6; além disso, cada comparação incremental tem seu próprio baseline, então as variações não devem ser multiplicadas para inferir o ganho do estado final combinado. A sensibilidade que exclui a primeira amostra manteve as medianas praticamente iguais. CPU por resposta, memória absoluta e latência/throughput devem ser avaliados em conjunto.

## Comparação acumulada dos três estados

Para validar o efeito conjunto, medi o original (A, `9b6b69c`), o estado após o experimento 02 (B, `64e4fe4`) e o estado final com N+1 removido e pool (C, `518872a`) em três blocos balanceados A→B→C, B→C→A e C→A→B. O mesmo container/banco e volume foram mantidos; entre estados, alterei apenas o código da API e a presença dos índices. As nove medições registraram commit correto e contrato mantido nos 42 casos.

| Estado | Req/s (mediana; faixa) | p95 geral (mediana) | p95 da rota (mediana) | CPU estimada (CPU-s/resposta válida) | Memória média total (MiB) |
|---|---:|---:|---:|---:|---:|
| A — original | 2,52 (2,51–2,66) | 26,50 s | 28,52 s | 0,369 | 417,9 |
| B — dois índices | 3,88 (3,73–5,23) | 18,36 s | 10,30 s | 0,189 | 429,4 |
| C — final combinado | 5,91 (4,59–6,29) | 12,65 s | 4,34 s | 0,128 | 431,2 |

Os níveis da tabela são medianas de três rodadas. Os percentuais abaixo são a mediana das razões pareadas A→C, não a razão dessas medianas (que daria +134,5% em req/s e −52,3% no p95 geral). Na comparação pareada, o throughput aumentou 135,8% (82,4–136,6%), o p95 geral caiu 56,1% (42,7–59,4%), o p95 da rota caiu 85,8% (84,8–86,1%) e a CPU estimada por resposta caiu 65,1% (64,4–67,8%); a memória total aumentou 2,4% (1,0–4,9%). B3 teve um timeout (0,35% de erro); não foi descartado, e o contrato passou. A diferença entre o CSV de recursos e a duração k6 teve mediana de 6,04 s (4,38–7,10), portanto CPU por resposta continua sendo uma estimativa, não uma conta monetária. B→C combina remoção de N+1 e pool e não isola seus efeitos. Qualquer mudança nova deixa esta A→C desatualizada e exigiria repetir a comparação acumulada (A→D).

Os CSVs pareados de CPU estão em [cpu-por-requisicao-comparacao-acumulada.csv](diagnostico/cpu-por-requisicao-comparacao-acumulada.csv); o método e os limites completos estão no [relatório](diagnostico/relatorio.md). Dados brutos: A [1](resultados/20261115-153545-final-A-r1/), [2](resultados/20261115-154809-final-A-r2/), [3](resultados/20261115-155354-final-A-r3/); B [1](resultados/20261115-153826-final-B-r1/), [2](resultados/20261115-154327-final-B-r2/), [3](resultados/20261115-155624-final-B-r3/); C [1](resultados/20261115-154050-final-C-r1/), [2](resultados/20261115-154547-final-C-r2/), [3](resultados/20261115-155125-final-C-r3/).

### Valores por rodada e pares

Valores lidos do `resumo-k6.json` e do `recursos.csv` de cada pasta; a CPU por resposta vem de [cpu-por-requisicao-comparacao-acumulada.csv](diagnostico/cpu-por-requisicao-comparacao-acumulada.csv) (respostas válidas). O par k compara a rodada k de dois estados; a ordem dos estados rotacionou entre rodadas (ABC, BCA, CAB).

| Estado | req/s (r1 / r2 / r3) | p95 geral, ms (r1 / r2 / r3) | p95 da rota, ms (r1 / r2 / r3) | CPU/resposta (r1 / r2 / r3) | Memória total, MiB (r1 / r2 / r3) |
|---|---|---|---|---|---|
| A | 2,657 / 2,507 / 2,517 | 25.087,5 / 28.791,5 / 26.498,9 | 27.488,6 / 31.328,4 / 28.516,1 | 0,361 / 0,393 / 0,369 | 417,9 / 427,0 / 413,8 |
| B | 5,234 / 3,880 / 3,729 | 12.651,7 / 18.360,4 / 21.719,8 | 10.304,4 / 13.621,0 / 8.424,7 | 0,187 / 0,191 / 0,189 | 447,3 / 425,1 / 429,4 |
| C | 6,287 / 5,911 / 4,590 | 10.189,6 / 12.646,3 / 15.193,0 | 3.827,4 / 4.461,1 / 4.338,4 | 0,128 / 0,127 / 0,129 | 427,7 / 431,2 / 434,1 |

| Par | req/s | p95 geral | p95 da rota | CPU/resposta | Memória total |
|---|---|---|---|---|---|
| A→B | +97,0% / +54,8% / +48,2% | −49,6% / −36,2% / −18,0% | −62,5% / −56,5% / −70,5% | −48,2% / −51,5% / −48,8% | +7,0% / −0,5% / +3,8% |
| B→C | +20,1% / +52,3% / +23,1% | −19,5% / −31,1% / −30,1% | −62,9% / −67,2% / −48,5% | −31,3% / −33,4% / −31,9% | −4,4% / +1,4% / +1,1% |
| A→C | +136,6% / +135,8% / +82,4% | −59,4% / −56,1% / −42,7% | −86,1% / −85,8% / −84,8% | −64,4% / −67,8% / −65,1% | +2,4% / +1,0% / +4,9% |

## Evidência do terceiro experimento — remoção do N+1

A variante A é o código do commit `888e703`; a B altera somente `api/src/rotas.js`, no commit `786a18d`. A rota consolidou a busca de cliente, pedidos, itens e produtos em um `LEFT JOIN`, reconstruindo a resposta, totais e ordenação em memória. Os dois índices estavam presentes em ambos os braços; não houve pool.

A repetição usou três pares balanceados A→B, B→A, A→B, com 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. Os worktrees estavam limpos, cada `contexto.txt` registra o commit correspondente e zero arquivos alterados. O banco permaneceu no mesmo container e volume durante as 12 medições de N+1 e pool; somente a API foi reconstruída ao trocar de braço. Os containers externos foram parados durante os testes.

| Variante | Req/s por rodada | Mediana req/s | Latência mediana geral por rodada (ms) | p95 geral por rodada (ms) | p95 da rota por rodada (ms) |
|---|---|---:|---|---|---|
| Com N+1 (A, original) | 2,90 / 4,14 / 4,33 | 4,14 (2,90–4,33) | 1.397,0 / 1.199,3 / 1.226,8 | 33.237,9 / 19.636,8 / 15.611,0 | 9.820,5 / 9.225,7 / 11.947,1 |
| N+1 removido (B) | 3,20 / 2,53 / 4,80 | 3,20 (2,53–4,80) | 910,3 / 856,5 / 716,9 | 28.308,2 / 37.188,0 / 20.429,5 | 17.498,4 / 19.177,8 / 4.747,2 |

| Par (ordem executada) | Throughput A→B (variação) | p95 geral A→B (variação) | p95 da rota A→B (variação) | Erros k6 |
|---|---:|---:|---:|---|
| 1 (A→B) | 2,90→3,20 (+10,3%) | 33.237,9→28.308,2 (−14,8%) | 9.820,5→17.498,4 (+78,2%) | 0,47% em cada braço |
| 2 (B→A) | 4,14→2,53 (−38,9%) | 19.636,8→37.188,0 (+89,4%) | 9.225,7→19.177,8 (+107,9%) | 0% |
| 3 (A→B) | 4,33→4,80 (+10,9%) | 15.611,0→20.429,5 (+30,9%) | 11.947,1→4.747,2 (−60,3%) | 0% |

Nesta repetição, o throughput mediano foi 4,14→3,20 req/s (−22,7%), o p95 geral 19.636,8→28.308,2 ms (+44,2%) e o p95 de `pedidos-do-cliente` 9.820,5→17.498,4 ms (+78,2%). As faixas dos dois braços se sobrepõem e os pares divergem; não há evidência estável de ganho nesta execução. O primeiro par teve um timeout em cada variante: uma chamada de `vendas-por-dia` no braço A e uma chamada de `pedidos-por-status` no B. Ambos os contratos passaram nos 42 casos. A leitura é inconclusiva e não apaga a possibilidade de benefício sob outra carga; os resultados anteriores, muito mais favoráveis, são exploratórios e não devem ser combinados com esta série.

Dados brutos A: [A1](resultados/20261114-151556-n1-rerun-01-a/), [A2](resultados/20261114-152435-n1-rerun-02-a/), [A3](resultados/20261114-152646-n1-rerun-03-a/). Dados brutos B: [B1](resultados/20261114-151931-n1-rerun-01-b/), [B2](resultados/20261114-152153-n1-rerun-02-b/), [B3](resultados/20261114-152942-n1-rerun-03-b/).

## Evidência do quarto experimento — pool separado

O braço A usa o commit `786a18d` (N+1 removido, sem pool); o B usa `518872a` e muda apenas a camada de acesso ao banco para um `Pool` compartilhado limitado a 10 conexões, com encerramento gracioso. A série mede o efeito adicional do pool sobre a rota otimizada.

Foram usados os mesmos parâmetros e a ordem balanceada A→B, B→A, A→B. Os metadados dos seis resultados registram o commit correspondente, zero arquivos alterados e contrato mantido nos 42 casos. O banco permaneceu no mesmo container e volume; os containers externos ficaram parados.

| Variante | Req/s por rodada | Mediana req/s | Latência mediana geral por rodada (ms) | p95 geral por rodada (ms) | p95 da rota por rodada (ms) |
|---|---|---:|---|---|---|
| Sem pool (A) | 3,32 / 3,63 / 2,94 | 3,32 (2,94–3,63) | 823,9 / 576,8 / 797,5 | 27.642,0 / 35.288,3 / 42.481,9 | 3.808,5 / 3.713,0 / 1.415,5 |
| Com pool (B) | 4,26 / 4,36 / 4,31 | 4,31 (4,26–4,36) | 1.938,4 / 1.573,8 / 2.094,0 | 17.094,6 / 21.597,6 / 15.094,5 | 5.690,5 / 5.631,2 / 7.767,7 |

| Par (ordem executada) | Throughput A→B (variação) | p95 geral A→B (variação) | p95 da rota A→B (variação) | Erros k6 |
|---|---:|---:|---:|---|
| 1 (A→B) | 3,32→4,26 (+28,3%) | 27.642,0→17.094,6 (−38,2%) | 3.808,5→5.690,5 (+49,4%) | 0% |
| 2 (B→A) | 3,63→4,36 (+20,1%) | 35.288,3→21.597,6 (−38,8%) | 3.713,0→5.631,2 (+51,7%) | 0% |
| 3 (A→B) | 2,94→4,31 (+46,6%) | 42.481,9→15.094,5 (−64,5%) | 1.415,5→7.767,7 (+448,5%) | 0% |

O throughput mediano foi 3,32→4,31 req/s (+29,8%) e o p95 geral 35.288,3→17.094,6 ms (−51,6%). Em contrapartida, a latência mediana geral aumentou 143,1% (797,5→1.938,4 ms) e o p95 da rota aumentou 53,3% (3.713,0→5.690,5 ms). O throughput e o p95 geral favoreceram o pool nos três pares, mas o p95 da rota-alvo piorou nos três. Isso é um trade-off observável, não uma melhora uniforme; recursos e limites de interpretação estão no [relatório](diagnostico/relatorio.md).

### Execuções excluídas e correção do procedimento

Antes da série válida, duas chamadas do Git Bash fizeram o k6 tentar resolver `/carga/teste-carga.js` como `C:/Program Files/Git/carga/teste-carga.js`, por conversão automática de caminhos do MSYS. Não geraram medições completas nem contrato; foram excluídas como falhas de execução do ambiente, não da API.

Também foram preservadas, mas excluídas das comparações: [uma rodada sem N+1](resultados/20261113-171831-n1-off-par-01-a/) (5,80 req/s, p95 geral 9.609,4 ms e p95 da rota 10.290,7 ms) e [uma com N+1](resultados/20261113-172155-n1-on-par-01-b/) (6,83 req/s, p95 geral 12.146,0 ms e p95 da rota 625,6 ms). Ambas tiveram 0% de erros e contrato mantido, mas a troca de worktree recriou o container do banco entre os braços; por isso, não formam um par comparável. A [tentativa interrompida](resultados/20261113-172413-n1-on-par-02-a/) registrou 200 requisições, 6,70 req/s, p95 geral 11.743,7 ms e p95 da rota 1.151,0 ms, mas não concluiu o contrato e também foi excluída.

As séries inicialmente tratadas como válidas em 13/11 também permanecem arquivadas, mas não são a evidência principal: os `contexto.txt` de braços com mudança registram arquivos sem commit (por exemplo, 1 no braço B do N+1 e 1/3 nos braços A/B do pool). A repetição de 14/11 substitui essas comparações sem apagar seus dados.

Na repetição, os arquivos gerados pelo script foram preservados sem edição. Dois resultados do experimento N+1 registraram timeout k6 (0,47% de erros totais em cada braço do primeiro par); os demais tiveram 0%. O contrato, executado após cada rodada, passou nos 42 casos em todas as 12 medições. Os resultados incluem erros e alta dispersão, não foram descartados seletivamente. O identificador do container do banco permaneceu constante (`ead6809…`) durante toda a série; as worktrees limpas alternaram apenas a API. Os dados novos estão no commit `4ecae3f`, separado dos commits de código.
