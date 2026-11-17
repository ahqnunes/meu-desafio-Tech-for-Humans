# Índices e ajustes na API mais que dobraram o throughput nos mesmos limites de recurso

## 1. Resumo

A API de uma loja fictícia (Node.js e PostgreSQL) ficava lenta sob carga: 2,5 req/s e p95 de 26 s com 20 usuários virtuais. Nos mesmos limites de CPU e memória, adicionei dois índices, removi consultas repetidas (N+1) e limitei conexões com um pool. Em pares de rodadas, a versão final teve throughput +136% (2,52→5,91 req/s), p95 −56%, CPU por resposta −65% e memória +2,4%. O efeito isolado de N+1 e pool não ficou provado. Custo em dinheiro não foi medido.

## 2. Contexto e diagnóstico

A API usa Node.js 20, Express e PostgreSQL 16 em dois containers, com 100 mil clientes, 20 mil produtos, 500 mil pedidos e 1,5 milhão de itens sintéticos. Os limites do Compose são 0,5 CPU e 256 MB na API e 1 CPU e 512 MB no banco; valem em todas as comparações e ficam registrados no `contexto.txt` de cada medição. A carga usa 20 usuários virtuais (VUs) simultâneos, 60 s nominais, 15 s de aquecimento e semente 42. A linha de base teve 2,62 req/s e p95 de 24,8 s (o p95 é o tempo abaixo do qual ficam 95% das respostas), com contrato mantido e sem erros.

O diagnóstico está em [relatorio.md](../diagnostico/relatorio.md), com os planos em [planos-consultas.txt](../diagnostico/planos-consultas.txt), [experimento-01-plano.txt](../diagnostico/experimento-01-plano.txt) e [experimento-01-planos-relatorios.txt](../diagnostico/experimento-01-planos-relatorios.txt). Hipóteses de causa:

- Itens e pedidos sem índices levam a varreduras sequenciais ao buscar os itens de um pedido e os pedidos de um cliente.
- `/clientes/:id/pedidos` consulta itens e produtos dentro de loops (N+1, em [rotas.js](../api/src/rotas.js)), o que multiplica consultas por requisição.
- Cada consulta abre e fecha sua própria conexão ([db.js](../api/src/db.js)), o que acrescenta custo de conexão.

O diagnóstico também apontou a busca por e-mail com `lower(email)` e relatórios com agregações grandes; esses pontos ficaram em `proximos-testes.md`. Os planos são evidência de trabalho repetido, não da contribuição de cada mecanismo para a carga total. Os percentuais de CPU deste artigo vêm de médias recalculadas de `recursos.csv`, não de `recursos.txt`.

## 3. Estado da arte

### Índices e busca

A documentação do PostgreSQL explica que índices podem evitar varreduras completas em buscas seletivas, mas acrescentam custo de manutenção a cada escrita [1]. Em índices multicoluna, a ordem das colunas importa: o índice é mais eficiente com restrições nas colunas à esquerda [2], e pode entregar linhas já ordenadas, evitando uma etapa de ordenação [12]. Para busca por substring, `pg_trgm` oferece suporte indexado a `LIKE` e `ILIKE`; o benefício depende dos trigramas extraídos e da seletividade [3]. O GitLab relatou bons resultados com GIN trigram em seu produto, em troca de índice maior e construção mais lenta [4]. É uma experiência de 2016, em outro conjunto de dados, não uma previsão para este catálogo.

### Consultas da API e pré-computação

Yang et al. estudaram bugs de desempenho em aplicações Rails; em um caso de N+1 do Lobsters, consolidar as consultas reduziu o carregamento da página de 1,10 s para 0,34 s [5]. O estudo trata de aplicações com ORM; esta API usa SQL direto com `pg`, então os resultados do paper dão contexto, não previsão. A documentação do `node-postgres` recomenda pooling para reutilizar conexões e limitar clientes simultâneos [6]. Para relatórios, a documentação do PostgreSQL diz que views materializadas persistem resultados e podem acelerar leituras, mas exigem refresh e podem servir dados desatualizados [7]. Cada abordagem envolve custos e riscos próprios.

### Limites de recursos e configuração

A documentação do Docker descreve limites de CPU e memória por container, com restrição de CPU e encerramento por falta de memória [8]. No PostgreSQL, `work_mem` pode ser usada várias vezes por consulta e por sessão [9].

## 4. Alternativas consideradas

| Abordagem | Custo | Desempenho esperado | Risco | Esforço |
|---|---|---|---|---|
| Índices B-tree/expressão | Armazenamento e manutenção na escrita | Menos trabalho em filtros e joins seletivos; medir por rota | Planner pode não usar; mais espaço | Baixo–médio |
| Reescrever N+1 e usar pool | Menos round trips; conexões limitadas em memória | Pode reduzir consultas repetidas e custo de conexão | Alterar ordem/conteúdo ou dimensionar mal o pool | Médio |
| View materializada/cache | Espaço e CPU para refresh/invalidação | Pode baratear leituras repetidas de relatórios | Dado obsoleto e consistência | Médio–alto |
| Ajustar configuração/limites | Mais CPU/RAM custa mais; limites menores arriscam throttling/OOM | Depende de plano, concorrência e carga; medir | Aumentar recurso pode apenas aumentar custo | Baixo–médio |

Índices acrescentam manutenção de escrita [1] e ocupam espaço (21 MB e 19 MB neste banco); consultas consolidadas e pooling exigem preservar a resposta e dimensionar o pool [5][6]; materialização envolve frescor dos dados [7]. Limites menores podem causar throttling ou OOM, e `work_mem` pode multiplicar o consumo por operação e por sessão [8][9]. Avaliei as abordagens pela evidência local: os planos mostravam varreduras sequenciais e consultas repetidas, o que favorecia índices e a reescrita de consultas, de menor esforço e sem alterar o contrato. Índices e reescrita de consultas vieram primeiro por serem fáceis de reverter e de medir isoladamente. Materialização e ajustes de configuração ficaram de fora por exigirem decisões sobre frescor e recursos que o enunciado trata como custo.

## 5. Solução escolhida e por quê

Priorizei índices alinhados aos planos e, depois, a reescrita do N+1 e o pool, cada um medido isolado. Não aumentei limites: o enunciado compara nos tetos atuais e trata recurso extra como custo. “Mais barata” é definição minha: mesmos tetos de CPU e memória, menos CPU por resposta válida e memória sem disparar. Mantive a versão final (C) porque, em pares da mesma sessão, ela superou a versão só com índices (B): req/s +20,1%, +52,3% e +23,1%; CPU por resposta −31,3%, −33,4% e −31,9%. Os pares não separam N+1 de pool; isolados, o N+1 foi inconclusivo e o pool piorou o p95 de `pedidos-do-cliente`. `pg_trgm`, materialização e ajustes de configuração ficaram de fora.

## 6. Experimento e resultado

| Mudança | Hipótese | p95 geral (rota-alvo), antes → depois | req/s antes → depois | CPU/memória | Pastas de resultados | Conclusão |
|---|---|---|---|---|---|---|
| 1. Índice `itens_pedido(pedido_id)` | Evita a varredura sequencial ao buscar os itens de um pedido | 23,72 s → 12,00 s | 2,71 → 4,83 | CPU/resposta 0,384 → 0,223 (−41,9%); memória 221,3 → 259,7 MiB | [1](../resultados/20261112-185839-02-control-alt-off-1/), [2](../resultados/20261112-190406-02-control-alt-off-2/), [3](../resultados/20261112-191019-02-control-alt-off-3/) → [1](../resultados/20261112-190132-02-control-alt-on-1/), [2](../resultados/20261112-190751-02-control-alt-on-2/), [3](../resultados/20261112-191255-02-control-alt-on-3/) | req/s +78,1%, p95 −49,4%, CPU/resposta −41,9% (−44,6% a −34,5%). Ordem fixa sem→com; não prova causalidade. |
| 2. Índice `pedidos(cliente_id, criado_em DESC, id DESC)` | Evita varredura e ordenação nos pedidos de um cliente | 11,37 s (12,31 s) → 10,17 s (8,55 s) | 4,86 → 5,77 | CPU/resposta 0,221 → 0,187 (−14,2%); memória 266,3 → 262,8 MiB | [1](../resultados/20261113-161645-02-pedidos-cliente-alt-off/), [2](../resultados/20261113-162202-02-pedidos-cliente-alt-off/), [3](../resultados/20261113-162720-02-pedidos-cliente-alt-off/) → [1](../resultados/20261113-161925-02-pedidos-cliente-alt-on/), [2](../resultados/20261113-162441-02-pedidos-cliente-alt-on/), [3](../resultados/20261113-163002-02-pedidos-cliente-alt-on/) | req/s +18,7%, p95 geral −10,6%, da rota −30,5%. Ordem fixa; índice de 19 MB. |
| 3. Remoção do N+1, sem pool | Um JOIN no lugar de uma consulta por pedido reduz round trips | 19,64 s (9,82 s) → 28,31 s (17,50 s) | 4,14 → 3,20 | CPU/resposta 0,200 → 0,160 (−21,4%); memória 429,3 → 414,7 MiB | [A1](../resultados/20261114-151556-n1-rerun-01-a/), [A2](../resultados/20261114-152435-n1-rerun-02-a/), [A3](../resultados/20261114-152646-n1-rerun-03-a/) → [B1](../resultados/20261114-151931-n1-rerun-01-b/), [B2](../resultados/20261114-152153-n1-rerun-02-b/), [B3](../resultados/20261114-152942-n1-rerun-03-b/) | Inconclusivo: faixas se sobrepõem, pares divergem e houve um timeout em cada braço do primeiro par. |
| 4. Pool de até 10 conexões | Reutilizar conexões reduz o custo de abrir uma por consulta | 35,29 s (3,71 s) → 17,09 s (5,69 s) | 3,32 → 4,31 | CPU/resposta 0,160 → 0,135 (−21,7%); memória 409,5 → 414,1 MiB | [A1](../resultados/20261114-153158-pool-rerun-01-a/), [A2](../resultados/20261114-153949-pool-rerun-02-a/), [A3](../resultados/20261114-154204-pool-rerun-03-a/) → [B1](../resultados/20261114-153505-pool-rerun-01-b/), [B2](../resultados/20261114-153711-pool-rerun-02-b/), [B3](../resultados/20261114-154512-pool-rerun-03-b/) | Trade-off: req/s +29,8%, p95 geral −51,6%; latência mediana geral +143,1% e p95 da rota +53,3%. |
| 5. Série final, A→B: só os dois índices | Os dois índices juntos | 26,50 s (28,52 s) → 18,36 s (10,30 s) | 2,52 → 3,88 | CPU/resposta 0,369 → 0,189; memória 417,9 → 429,4 MiB | [A1](../resultados/20261115-153545-final-A-r1/), [A2](../resultados/20261115-154809-final-A-r2/), [A3](../resultados/20261115-155354-final-A-r3/) → [B1](../resultados/20261115-153826-final-B-r1/), [B2](../resultados/20261115-154327-final-B-r2/), [B3](../resultados/20261115-155624-final-B-r3/) | Pares: req/s +97,0%, +54,8%, +48,2%; CPU/resposta −48,2%, −51,5%, −48,8%. |
| 6. Série final, B→C: N+1 e pool sobre os índices | Menos round trips e conexões reutilizadas | 18,36 s (10,30 s) → 12,65 s (4,34 s) | 3,88 → 5,91 | CPU/resposta 0,189 → 0,128; memória 429,4 → 431,2 MiB | [B1](../resultados/20261115-153826-final-B-r1/), [B2](../resultados/20261115-154327-final-B-r2/), [B3](../resultados/20261115-155624-final-B-r3/) → [C1](../resultados/20261115-154050-final-C-r1/), [C2](../resultados/20261115-154547-final-C-r2/), [C3](../resultados/20261115-155125-final-C-r3/) | Pares: req/s +20,1%, +52,3%, +23,1%; p95 −19,5%, −31,1%, −30,1%; CPU/resposta −31,3%, −33,4%, −31,9%. Não separa N+1 de pool. |
| 7. Série final, A→C: acumulada | Soma das mudanças | 26,50 s (28,52 s) → 12,65 s (4,34 s) | 2,52 → 5,91 | CPU/resposta 0,369 → 0,128; memória 417,9 → 431,2 MiB | [A1](../resultados/20261115-153545-final-A-r1/), [A2](../resultados/20261115-154809-final-A-r2/), [A3](../resultados/20261115-155354-final-A-r3/) → [C1](../resultados/20261115-154050-final-C-r1/), [C2](../resultados/20261115-154547-final-C-r2/), [C3](../resultados/20261115-155125-final-C-r3/) | Pares: req/s +136,6%, +135,8%, +82,4%; p95 −59,4%, −56,1%, −42,7%; CPU/resposta −64,4%, −67,8%, −65,1%; memória +1,0% a +4,9% (mediana +2,4%). |

Níveis são a mediana de três rodadas; nas linhas 1–4, cada experimento tem seu próprio baseline. O p95 da rota-alvo (`pedidos-do-cliente`) aparece entre parênteses quando medido. A coluna CPU/memória traz a CPU estimada por resposta válida (CPU média de API e banco, do `recursos.csv`, dividida por req/s, medida com `docker stats` [10] e k6 [11]) e a memória total média. É um proxy, não preço; valores em [cpu-por-requisicao-pares.csv](../diagnostico/cpu-por-requisicao-pares.csv) e [cpu-por-requisicao-comparacao-acumulada.csv](../diagnostico/cpu-por-requisicao-comparacao-acumulada.csv).

Na série final, A é a versão original, B tem só os dois índices e C é a versão final. O par k compara a rodada k de dois braços, com a ordem dos braços rotacionada entre rodadas. Todas as medições usaram os mesmos parâmetros de carga, com contrato mantido nos 42 casos e os mesmos limites de CPU e memória. Nos índices, a ordem foi sempre sem→com. O erro de B3 (0,35%) foi uma requisição de `/pedidos?status=` de ~60 s, compatível com timeout. Em B→C o p95 da rota-alvo melhorou em todos os pares, embora N+1 e pool isolados a tivessem piorado; não investiguei essa interação. Método e dados no [relatório](../diagnostico/relatorio.md).

## 7. Limites e testes futuros

Os resultados vêm de três rodadas por variante, uma máquina e um perfil sintético só de leitura. Mesmo com a ordem rotacionada, o throughput de B e C caiu ao longo da sessão final (B: 5,23→3,73 req/s; C: 6,29→4,59) e o p95 geral subiu, enquanto A ficou estável; não investiguei a causa. A CPU por resposta variou pouco (C: 0,127–0,129). Os níveis absolutos também não se comparam entre sessões: o estado “N+1 removido, sem pool” teve p95 de 17,50 s na rota-alvo no experimento 3 e de 3,71 s no 4. Não medi custo monetário, carga com escrita (os índices têm custo de manutenção) nem outros perfis. Não reescrevi o filtro de data dos relatórios (as datas saem em UTC e os 42 casos podem não cobrir o limite do dia), e o tamanho do pool (10 vs 4) não foi variado.

**O que mudaria a conclusão:** (a) em outra sessão, C não superar A em req/s ou CPU por resposta; (b) com limites 25% menores, C não manter ao menos o throughput de A; (c) uma carga com escrita anular o ganho de leitura. Defini esses critérios antes de qualquer novo teste. Detalhes em [experimentos.md](../experimentos.md) e [proximos-testes.md](../proximos-testes.md).

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
12. PostgreSQL Global Development Group. [Indexes and ORDER BY, PostgreSQL 16](https://www.postgresql.org/docs/16/indexes-ordering.html). Acesso em 16 nov. 2026.

## 9. Uso de IA

Usei IA como apoio para organizar hipóteses, revisar cálculos e redigir este artigo. Conferi as fontes citadas, os planos salvos e as métricas nos arquivos JSON e CSV do repositório; as limitações e incertezas foram mantidas explicitamente.
