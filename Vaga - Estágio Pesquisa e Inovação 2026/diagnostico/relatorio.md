# Diagnóstico da linha de base

## Escopo e método

Este diagnóstico usa a aplicação original, sem alterações de código, esquema ou parâmetros. A API e o PostgreSQL estavam saudáveis. As portas locais são 3001 (API) e 5434 (banco), por conflito com serviços de outro projeto; o Compose temporário usado para isso fica fora do repositório.

Foram consultadas as definições e estatísticas do PostgreSQL e executado `EXPLAIN (ANALYZE, BUFFERS, TIMING OFF)` para as consultas que implementam as sete rotas. Cada plano tem timeout de 120 segundos. As consultas de diagnóstico não rodaram com a carga concorrente; seus tempos servem para localizar trabalho feito pelo banco, não para substituir as medições oficiais de carga.

Evidências brutas:

- [estado-postgres.txt](./estado-postgres.txt): índices, estatísticas acumuladas, parâmetros, conexões e extensões.
- [planos-consultas.txt](./planos-consultas.txt): planos das consultas representativas das rotas.
- [resultados da linha de base](../resultados/): medições oficiais do script de carga.

## Linha de base observada

As três medições usaram 20 VUs, 60 segundos de carga, 15 segundos de aquecimento e semente 42; as três mantiveram o contrato. As medianas calculadas a partir de `resultados/` são:

| Métrica | Mediana |
|---|---:|
| Requisições por segundo | 2,62 |
| p95 geral | 24.812,1 ms |
| CPU média do PostgreSQL | 90,4% |
| Memória média do PostgreSQL | 377,0 MiB |
| CPU média da API | 9,6% |

O banco é o recurso mais ocupado durante a carga. Os tempos por rota também apontam para pedidos do cliente, listagem por status e relatório de vendas, mas a quantidade de amostras de algumas rotas é pequena; esses percentis são indícios, não comparações conclusivas por rota.

## Achados e hipóteses

### 1. Pedidos do cliente fazem trabalho repetido e sem índices de apoio

`GET /clientes/:id/pedidos` primeiro busca os pedidos do cliente; depois, para cada pedido, consulta os itens; e, para cada item, busca o produto. `consultar()` abre e fecha uma conexão PostgreSQL em cada chamada. Esse padrão multiplica consultas, conexões e varreduras na rota com peso de 20% da carga.

O banco só tem índices de chave primária. No plano do cliente 7, a busca de pedidos fez `Parallel Seq Scan` em `pedidos` (500 mil linhas) e sort; levou 167,715 ms fora de carga. A consulta de itens do pedido 329786 fez `Parallel Seq Scan` em `itens_pedido` (1,5 milhão de linhas), descartou 499.999 linhas por worker e levou 102,538 ms. A busca do produto por ID, em contraste, usou a chave primária e levou 0,049 ms.

**Hipótese:** as varreduras completas repetidas, somadas às conexões novas por consulta, explicam boa parte da latência e do consumo do banco nessa rota. O plano e o código sustentam a causa; o ganho de cada correção ainda precisa ser medido isoladamente.

### 2. A busca por e-mail não consegue usar a chave primária nem um índice existente

A consulta compara `lower(email)` com `lower($1)`, mas só existe o índice da chave primária de `clientes`. O plano percorreu os 100 mil clientes, descartou 99.999 linhas e levou 127,104 ms em execução isolada.

**Hipótese:** um índice de expressão compatível com `lower(email)` pode evitar a varredura para essa busca. Um índice simples em `email` não corresponde diretamente à expressão usada pela consulta.

### 3. A listagem de pedidos por status varre e ordena a tabela

O endpoint executa duas consultas: `count(*)` pelo status e a página ordenada por data e ID. Nenhuma combinação de status/data está indexada. Os planos fizeram varreduras paralelas em `pedidos`; a consulta da página também fez sort. Tempos isolados: 40,814 ms para o `COUNT` e 175,714 ms para a página.

**Hipótese:** índices que atendam ao filtro e à ordem podem reduzir o trabalho; o `COUNT(*)` pode continuar custoso dependendo da seletividade e precisa ser avaliado separadamente.

### 4. A busca por substring percorre o catálogo

`ILIKE '%termo%'` não é atendido por índice B-tree convencional. O plano varreu os 20 mil produtos e descartou 19 mil para `cadeira`; levou 19,717 ms isolado.

**Hipótese:** `pg_trgm` com índice GIN é uma alternativa a testar para substring. Como o catálogo tem 20 mil linhas e essa rota representa 15% da carga, a prioridade deve ser comparada com os problemas de `pedidos` e `itens_pedido`, não presumida.

### 5. Os relatórios fazem agregações e varreduras grandes

- Vendas por dia: o plano percorreu `pedidos` e `itens_pedido` para retornar um intervalo de sete dias; levou 340,660 ms isolado. O filtro `p.criado_em::date` envolve a coluna em uma expressão, e não há índice em data nem em `itens_pedido.pedido_id`.
- Top produtos: agrega os 1,5 milhão de itens após ler pedidos e produtos; levou 2.112,070 ms isolado. A rota tem apenas 2% do peso da carga.

**Hipótese:** o custo do relatório diário decorre da filtragem por data sem acesso seletivo e do join sem índice de apoio nos itens; o relatório de top produtos tem custo inerente à agregação global. Índices, reescrita do filtro de data e materialização são alternativas, mas exigem experimentos e análise de atualidade dos dados.

## Evidência de estatísticas e limites

As estatísticas do banco mostram 1,245 bilhão de linhas lidas sequencialmente em `itens_pedido` e 216,5 milhões em `pedidos`, além de 105 arquivos temporários e cerca de 1.940 MB gravados. São contadores acumulados, sem timestamp de reset disponível; portanto, não atribuímos esses totais a uma rota ou execução específica. Os planos isolados de top produtos não mostram spill do hash (`Batches: 1`), então a origem dos temporários permanece em aberto.

`pg_stat_statements` está disponível na imagem, mas não instalado/ativado. Não foi habilitado porque requer ajuste de configuração e reinicialização do PostgreSQL; sem ele, ainda falta uma classificação acumulada e confiável das consultas mais caras sob carga.

O contêiner do banco tem limite de 512 MiB. A configuração observada inclui `shared_buffers=128MB`, `work_mem=4MB`, `max_connections=100` e `effective_cache_size=4GB`. `effective_cache_size` é uma estimativa do planner, não memória alocada; ainda assim, a diferença para o limite merece um experimento de configuração, não uma alteração presumida como melhoria.

## Próximos experimentos sugeridos

1. Criar índices secundários correspondentes às consultas frequentes — em particular `lower(email)`, pedidos por cliente/data/ID, itens por pedido/ID e pedidos por status/data/ID — em um único arquivo SQL novo, medir três vezes e verificar o contrato.
2. Em um experimento separado, eliminar o N+1 de pedidos do cliente com consulta(s) em lote, preservando exatamente a ordem, os valores e o formato do contrato.
3. Só depois comparar `pg_trgm` para busca textual e alternativas para os relatórios, medindo custo de CPU, memória e espaço, além da latência.
4. Se a atribuição por consulta ainda for necessária, planejar uma mudança diagnóstica separada para habilitar `pg_stat_statements`, documentar a configuração temporária e não misturar essa alteração com uma otimização medida.

Esses itens são hipóteses de trabalho, não resultados de otimização. Nenhuma mudança de performance foi feita nesta etapa.
