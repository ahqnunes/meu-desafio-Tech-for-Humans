import argparse
import csv
import re
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


MEMORY_PATTERN = re.compile(
    r"^\s*([\d.]+)\s*(B|KiB|MiB|GiB|TiB)\s*/\s*([\d.]+)\s*(B|KiB|MiB|GiB|TiB)\s*$"
)
MIB_MULTIPLIERS = {
    "B": Decimal(1) / (1024 * 1024),
    "KiB": Decimal(1) / 1024,
    "MiB": Decimal(1),
    "GiB": Decimal(1024),
    "TiB": Decimal(1024 * 1024),
}


def parse_decimal(value, label, csv_path, line_number):
    cleaned = value.strip().rstrip("%").strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(
            "{}:{}: valor inválido para {}: {!r}".format(
                csv_path, line_number, label, value
            )
        ) from error
    if not number.is_finite() or number < 0:
        raise ValueError(
            "{}:{}: valor inválido para {}: {!r}".format(
                csv_path, line_number, label, value
            )
        )
    return number


def parse_memory(value, csv_path, line_number):
    match = MEMORY_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(
            "{}:{}: formato de memória inválido: {!r}".format(
                csv_path, line_number, value
            )
        )
    amount = parse_decimal(match.group(1), "memória", csv_path, line_number)
    return amount * MIB_MULTIPLIERS[match.group(2)]


def read_result(path):
    csv_path = path / "recursos.csv" if path.is_dir() else path
    if not csv_path.is_file():
        raise FileNotFoundError("CSV não encontrado: {}".format(csv_path))

    grouped = defaultdict(lambda: {"cpu": [], "memory": [], "times": []})
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"momento", "container", "cpu_percentual", "memoria"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "{}: cabeçalhos ausentes: {}".format(
                    csv_path, ", ".join(sorted(missing))
                )
            )
        for line_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            if None in row:
                raise ValueError(
                    "{}:{}: quantidade de colunas excedente".format(
                        csv_path, line_number
                    )
                )
            if any(row.get(field) is None for field in required):
                raise ValueError(
                    "{}:{}: linha incompleta".format(csv_path, line_number)
                )
            if not row["momento"].strip():
                raise ValueError(
                    "{}:{}: momento vazio".format(csv_path, line_number)
                )
            container = row["container"].strip()
            if not container:
                raise ValueError(
                    "{}:{}: container vazio".format(csv_path, line_number)
                )
            values = grouped[container]
            values["cpu"].append(
                parse_decimal(
                    row["cpu_percentual"], "CPU", csv_path, line_number
                )
            )
            values["memory"].append(
                parse_memory(row["memoria"], csv_path, line_number)
            )
            values["times"].append(row["momento"].strip())

    if not grouped:
        raise ValueError("{}: nenhum registro de recurso".format(csv_path))
    return csv_path, grouped


def format_decimal(value):
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Recalcula médias e máximos de CPU e memória a partir de "
            "recursos.csv, sem usar recursos.txt."
        )
    )
    parser.add_argument(
        "resultados",
        nargs="+",
        type=Path,
        help="Pastas de resultados ou caminhos para recursos.csv",
    )
    args = parser.parse_args()

    output = []
    try:
        for path in args.resultados:
            csv_path, grouped = read_result(path)
            for container, values in sorted(grouped.items()):
                cpu = values["cpu"]
                memory = values["memory"]
                output.append(
                    [
                        csv_path.parent.name,
                        container,
                        len(cpu),
                        format_decimal(sum(cpu) / len(cpu)),
                        format_decimal(max(cpu)),
                        format_decimal(sum(memory) / len(memory)),
                        format_decimal(max(memory)),
                        values["times"][0],
                        values["times"][-1],
                    ]
                )
    except (FileNotFoundError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "resultado",
            "container",
            "amostras",
            "cpu_media_pct",
            "cpu_max_pct",
            "memoria_media_mib",
            "memoria_max_mib",
            "primeira_amostra",
            "ultima_amostra",
        ]
    )
    writer.writerows(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
