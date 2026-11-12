# Registro de experimentos

Uma linha por mudança aplicada. Os resultados de carga vêm das pastas geradas por `scripts/medir.sh`; as interpretações e limitações estão detalhadas em [diagnostico/relatorio.md](diagnostico/relatorio.md).

| Mudança | Fonte e hipótese | Status | Antes (mediana de 3) | Depois (mediana de 3) | Pastas de resultados | Conclusão |
|---|---|---|---|---|---|---|
| Índice B-tree em `itens_pedido(pedido_id)` | [Plano baseline](diagnostico/planos-consultas.txt) mostrou `Parallel Seq Scan` para buscar itens do pedido; a documentação do [PostgreSQL 16 sobre índices](https://www.postgresql.org/docs/16/indexes-intro.html) descreve como índices podem evitar varreduras completas. Hipótese: o índice reduziria o trabalho para localizar itens por `pedido_id`. | Aplicada e medida; atribuição causal inconclusiva. Contrato mantido nos 42 casos. | 2,62 req/s; p95 geral 24.812,1 ms. CPU/memória: não reportadas como comparação confiável devido às inconsistências descritas na auditoria de recursos. | 3,93 req/s; p95 geral 16.981,7 ms. CPU/memória: não reportadas como comparação confiável. Índice: 21 MB. | Antes: [172817](resultados/20261107-172817-00-linha-de-base/), [173048](resultados/20261107-173048-00-linha-de-base/), [173256](resultados/20261107-173256-00-linha-de-base/). Depois: [161707](resultados/20261112-161707-01-indice-itens-pedido/), [161931](resultados/20261112-161931-01-indice-itens-pedido/), [162145](resultados/20261112-162145-01-indice-itens-pedido/). | O plano posterior usa o índice, mas as medições de carga não são pareadas: foram feitas em datas diferentes e uma janela efetiva chegou a 80,7 s. Uma série posterior com o mesmo índice teve 3,61 req/s e p95 de 23.399,1 ms. Assim, a diferença inicial é descritiva, não prova que o índice causou o ganho; o p95 de vendas por rota também é inconclusivo. |

## Evidência e procedimento

- Mudança registrada no commit `a630b53`; resultados da mudança registrados separadamente no commit `7cb4cad`.
- As três execuções antes e as três depois usaram 20 VUs, 60 s nominais, 15 s de aquecimento e seed 42. A duração efetiva está nos JSONs de cada execução.
- O contrato foi verificado antes da carga e após a mudança; as seis execuções registraram 0% de erros.
- [Plano antes e depois](diagnostico/experimento-01-plano.txt) confirma a troca de `Parallel Seq Scan` para `Index Scan` na consulta representativa. A captura isolada sustenta o uso do índice, não uma comparação controlada de latência.
- A auditoria em [diagnostico/relatorio.md](diagnostico/relatorio.md) identificou divergências entre `recursos.csv` e `recursos.txt`; por isso CPU e memória ficam pendentes de reconciliação, não são tratadas como zero nem como melhora.

O diagnóstico complementar de 2 versus 20 VUs não é uma mudança aplicada e, portanto, não aparece como uma segunda linha de otimização. Seus dados e limites estão registrados na seção de concorrência do [relatório](diagnostico/relatorio.md).
