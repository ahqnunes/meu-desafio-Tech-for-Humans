
import csv
import json
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = Path(__file__).resolve().parent / "tabela-final.txt"
BRACOS = "ABC"
COMPARACOES = [("A", "C"), ("B", "C"), ("A", "B")]
ROTA_ALVO = "pedidos-do-cliente"

# chave, rótulo, casas decimais
METRICAS = [
    ("rps", "req/s", 3),
    ("p95", "p95 geral (ms)", 1),
    ("rota", f"p95 {ROTA_ALVO} (ms)", 1),
    ("err", "erros (%)", 2),
    ("cpu", "CPU-s/resposta (integral)", 4),
    ("cpu_proxy", "CPU-s/resposta (proxy: media%/req/s)", 4),
    ("mem", "memoria total media (MiB)", 1),
]

linhas = []


def say(texto=""):
    print(texto)
    linhas.append(texto)


def para_mib(texto):
    valor, unidade = re.match(r"\s*([\d.]+)\s*([KMG]?i?B)", texto).groups()
    fator = {"B": 1 / 1048576, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[unidade]
    return float(valor) * fator


def rodada(pasta):
    k6 = json.loads((pasta / "resumo-k6.json").read_text(encoding="utf-8"))["metrics"]
    n = k6["http_reqs"]["values"]["count"]
    rps = k6["http_reqs"]["values"]["rate"]

    amostras = {}  # container -> [(instante, cpu%, mem MiB)]
    with open(pasta / "recursos.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            amostras.setdefault(r["container"], []).append((
                datetime.strptime(r["momento"], "%H:%M:%S"),
                float(r["cpu_percentual"].strip().rstrip("%")),
                para_mib(r["memoria"].split("/")[0]),
            ))

    # CPU-segundos consumidos (integral trapezoidal; 100% = 1 CPU)
    cpu_s = 0.0
    for lista in amostras.values():
        for (t0, c0, _), (t1, c1, _) in zip(lista, lista[1:]):
            cpu_s += (c0 + c1) / 200 * ((t1 - t0).total_seconds() % 86400)

    cpu_medio_total = sum(sum(c for _, c, _ in l) / len(l) for l in amostras.values())
    mem_total = sum(sum(m for _, _, m in l) / len(l) for l in amostras.values())

    return {
        "rps": rps,
        "p95": k6["http_req_duration"]["values"]["p(95)"],
        "rota": k6[f"http_req_duration{{rota:{ROTA_ALVO}}}"]["values"]["p(95)"],
        "err": k6["http_req_failed"]["values"]["rate"] * 100,
        "cpu": cpu_s / n,
        "cpu_proxy": cpu_medio_total / 100 / rps,
        "mem": mem_total,
    }


# ---------- carregar as nove rodadas ----------
pastas = {}
dados = {}
for a in BRACOS:
    achadas = {}
    for p in (RAIZ / "resultados").glob(f"*-final-{a}-r*"):
        m = re.search(r"-r(\d+)$", p.name)
        if m:
            achadas[int(m.group(1))] = p
    if not achadas:
        raise SystemExit(f"Nenhuma pasta final-{a}-r* em {RAIZ / 'resultados'}")
    pastas[a] = [achadas[k] for k in sorted(achadas)]
    dados[a] = [rodada(p) for p in pastas[a]]

numeros = {a: sorted(int(re.search(r"-r(\d+)$", p.name).group(1)) for p in pastas[a]) for a in BRACOS}
if len({tuple(v) for v in numeros.values()}) != 1:
    raise SystemExit(f"Os braços têm rodadas diferentes: {numeros}")

say("PASTAS")
for a in BRACOS:
    for p in pastas[a]:
        say(f"  {a}: {p.name}")

# ---------- por braço ----------
say("\nPOR BRACO (valores por rodada; mediana; faixa)")
for a in BRACOS:
    say(f"\n[{a}]")
    for chave, rotulo, casas in METRICAS:
        v = [r[chave] for r in dados[a]]
        say(f"  {rotulo}: {[round(x, casas) for x in v]}  mediana {round(st.median(v), casas)}  "
            f"faixa {round(min(v), casas)}-{round(max(v), casas)}")

# ---------- pares ----------
say("\nPARES (rodada k contra rodada k)")
for x, y in COMPARACOES:
    say(f"\n{x}->{y}")
    for chave, rotulo, casas in METRICAS:
        if chave == "err":  # base pode ser 0%: diferença em pontos percentuais
            d = [b[chave] - a[chave] for a, b in zip(dados[x], dados[y])]
            say(f"  {rotulo}: diferenca em p.p. {[round(v, 2) for v in d]}")
            continue
        ps = [(b[chave] / a[chave] - 1) * 100 for a, b in zip(dados[x], dados[y])]
        say(f"  {rotulo}: pares {[f'{p:+.1f}%' for p in ps]}  mediana {st.median(ps):+.1f}%")
    razoes = [(b["rps"] > a["rps"]) for a, b in zip(dados[x], dados[y])]
    say(f"  pares com req/s maior no segundo braço: {sum(razoes)} de {len(razoes)}")

# ---------- linha pronta para a tabela (niveis = mediana por braço) ----------
def med(a, k):
    return st.median(r[k] for r in dados[a])

say("\nNIVEIS PARA A TABELA (mediana de 3 rodadas; p95 em segundos)")
for x, y in COMPARACOES:
    say(f"  {x}->{y}: req/s {med(x,'rps'):.2f}->{med(y,'rps'):.2f} | "
        f"p95 geral {med(x,'p95')/1000:.2f}->{med(y,'p95')/1000:.2f} s | "
        f"p95 {ROTA_ALVO} {med(x,'rota')/1000:.2f}->{med(y,'rota')/1000:.2f} s | "
        f"CPU/resp (integral) {med(x,'cpu'):.3f}->{med(y,'cpu'):.3f} | "
        f"CPU/resp (proxy) {med(x,'cpu_proxy'):.3f}->{med(y,'cpu_proxy'):.3f} | "
        f"mem {med(x,'mem'):.1f}->{med(y,'mem'):.1f} MiB")

SAIDA.write_text("\n".join(linhas) + "\n", encoding="utf-8")
print(f"\nSalvo em {SAIDA}")