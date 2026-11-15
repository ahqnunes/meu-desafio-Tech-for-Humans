import argparse
import csv
import json
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
CONTAINERS = ("api", "banco")


def decimal_value(value, label, path, line_number=None):
    location = "{}:{}".format(path, line_number) if line_number else str(path)
    try:
        number = Decimal(str(value).strip().rstrip("%").strip())
    except InvalidOperation as error:
        raise ValueError("{}: valor inválido para {}: {!r}".format(
            location, label, value
        )) from error
    if not number.is_finite() or number < 0:
        raise ValueError("{}: valor inválido para {}: {!r}".format(
            location, label, value
        ))
    return number


def memory_mib(value, path, line_number):
    match = MEMORY_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("{}:{}: formato de memória inválido: {!r}".format(
            path, line_number, value
        ))
    amount = decimal_value(match.group(1), "memória", path, line_number)
    return amount * MIB_MULTIPLIERS[match.group(2)]


def container_role(name):
    if re.search(r"api-\d+$", name):
        return "api"
    if re.search(r"banco-\d+$", name):
        return "banco"
    return None


def csv_duration(times, path):
    if not times:
        raise ValueError("{}: nenhuma amostra de tempo".format(path))
    seconds = []
    for value in times:
        parts = value.split(":")
        if len(parts) != 3:
            raise ValueError("{}: horário inválido: {!r}".format(path, value))
        try:
            hour, minute, second = [int(part) for part in parts]
        except ValueError as error:
            raise ValueError(
                "{}: horário inválido: {!r}".format(path, value)
            ) from error
        if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
            raise ValueError("{}: horário inválido: {!r}".format(path, value))
        seconds.append(hour * 3600 + minute * 60 + second)
    duration = seconds[-1] - seconds[0]
    return duration + 24 * 3600 if duration < 0 else duration


def read_resources(result_dir):
    path = result_dir / "recursos.csv"
    if not path.is_file():
        raise FileNotFoundError("CSV não encontrado: {}".format(path))
    grouped = defaultdict(lambda: {"cpu": [], "memory": [], "times": []})
    required = {"momento", "container", "cpu_percentual", "memoria"}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("{}: cabeçalhos ausentes: {}".format(
                path, ", ".join(sorted(missing))
            ))
        for line_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            if None in row or any(row.get(field) is None for field in required):
                raise ValueError("{}:{}: linha incompleta".format(
                    path, line_number
                ))
            role = container_role(row["container"].strip())
            if role is None:
                continue
            values = grouped[role]
            values["cpu"].append(decimal_value(
                row["cpu_percentual"], "CPU", path, line_number
            ))
            values["memory"].append(memory_mib(
                row["memoria"], path, line_number
            ))
            values["times"].append(row["momento"].strip())

    missing_roles = set(CONTAINERS).difference(grouped)
    if missing_roles:
        raise ValueError("{}: containers ausentes: {}".format(
            path, ", ".join(sorted(missing_roles))
        ))
    for role, values in grouped.items():
        if not values["cpu"]:
            raise ValueError("{}: nenhuma amostra para {}".format(path, role))
        values["window_seconds"] = csv_duration(values["times"], path)
    return grouped


def read_k6(result_dir):
    path = result_dir / "resumo-k6.json"
    if not path.is_file():
        raise FileNotFoundError("Resumo k6 não encontrado: {}".format(path))
    with path.open("r", encoding="utf-8") as source:
        data = json.load(source)
    metrics = data.get("metrics", {})
    requests = metrics.get("http_reqs", {}).get("values", {})
    failures = metrics.get("http_req_failed", {}).get("values", {})
    if "rate" not in requests or "rate" not in failures:
        raise ValueError("{}: métricas http_reqs/http_req_failed ausentes".format(
            path
        ))
    request_rate = decimal_value(requests["rate"], "req/s", path)
    failure_rate = decimal_value(failures["rate"], "taxa de erro", path)
    if failure_rate > 1:
        raise ValueError("{}: taxa de erro fora de 0–1".format(path))
    success_rate = request_rate * (Decimal(1) - failure_rate)
    if success_rate == 0:
        raise ValueError(
            "{}: nenhuma requisição bem-sucedida para normalizar CPU".format(
                path
            )
        )
    duration_ms = data.get("state", {}).get("testRunDurationMs")
    if duration_ms is None:
        raise ValueError("{}: duração do teste ausente".format(path))
    return {
        "request_rate": request_rate,
        "failure_rate": failure_rate,
        "success_rate": success_rate,
        "duration_seconds": decimal_value(
            duration_ms, "duração k6", path
        ) / 1000,
    }


def mean(values):
    return sum(values) / len(values)


def mean_without_first(values):
    return mean(values[1:]) if len(values) > 1 else mean(values)


def resource_metrics(values, successful_rate):
    cpu = values["cpu"]
    memory = values["memory"]
    cpu_mean = mean(cpu)
    cpu_without_first = mean_without_first(cpu)
    return {
        "cpu_mean_pct": cpu_mean,
        "cpu_seconds_per_success": cpu_mean / 100 / successful_rate,
        "cpu_seconds_per_success_without_first": (
            cpu_without_first / 100 / successful_rate
        ),
        "memory_mean_mib": mean(memory),
        "samples": len(cpu),
        "window_seconds": values["window_seconds"],
    }


def percent_change(before, after):
    if before == 0:
        return Decimal(0) if after == 0 else None
    return (after / before - 1) * 100


def format_decimal(value):
    if value is None:
        return ""
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def write_rows(output, rows):
    writer = csv.DictWriter(
        output, fieldnames=list(rows[0]), lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: format_decimal(value) if isinstance(value, Decimal) else value
            for key, value in row.items()
        })


def result_data(path):
    path = Path(path)
    if not path.is_dir():
        raise FileNotFoundError("Pasta de resultado não encontrada: {}".format(
            path
        ))
    return path, read_k6(path), read_resources(path)


def pair_rows(pair, before_path, after_path):
    before_path, before_k6, before_resources = result_data(before_path)
    after_path, after_k6, after_resources = result_data(after_path)
    rows = []
    for role in (*CONTAINERS, "total"):
        if role == "total":
            before_times = before_resources["api"]["times"]
            after_times = after_resources["api"]["times"]
            before = {
                "cpu": sum(
                    mean(before_resources[container]["cpu"])
                    for container in CONTAINERS
                ),
                "cpu_without_first": sum(
                    mean_without_first(before_resources[container]["cpu"])
                    for container in CONTAINERS
                ),
                "memory": sum(
                    mean(before_resources[container]["memory"])
                    for container in CONTAINERS
                ),
                "samples": min(
                    len(before_resources[container]["cpu"])
                    for container in CONTAINERS
                ),
                "window_seconds": csv_duration(before_times, before_path),
            }
            after = {
                "cpu": sum(
                    mean(after_resources[container]["cpu"])
                    for container in CONTAINERS
                ),
                "cpu_without_first": sum(
                    mean_without_first(after_resources[container]["cpu"])
                    for container in CONTAINERS
                ),
                "memory": sum(
                    mean(after_resources[container]["memory"])
                    for container in CONTAINERS
                ),
                "samples": min(
                    len(after_resources[container]["cpu"])
                    for container in CONTAINERS
                ),
                "window_seconds": csv_duration(after_times, after_path),
            }
        else:
            before_values = before_resources[role]
            after_values = after_resources[role]
            before = {
                "cpu": mean(before_values["cpu"]),
                "cpu_without_first": mean_without_first(before_values["cpu"]),
                "memory": mean(before_values["memory"]),
                "samples": len(before_values["cpu"]),
                "window_seconds": before_values["window_seconds"],
            }
            after = {
                "cpu": mean(after_values["cpu"]),
                "cpu_without_first": mean_without_first(after_values["cpu"]),
                "memory": mean(after_values["memory"]),
                "samples": len(after_values["cpu"]),
                "window_seconds": after_values["window_seconds"],
            }

        before_cost = before["cpu"] / 100 / before_k6["success_rate"]
        after_cost = after["cpu"] / 100 / after_k6["success_rate"]
        before_sensitivity = (
            before["cpu_without_first"] / 100 / before_k6["success_rate"]
        )
        after_sensitivity = (
            after["cpu_without_first"] / 100 / after_k6["success_rate"]
        )
        rows.append({
            "pair": pair,
            "resource": role,
            "before_result": before_path.name,
            "after_result": after_path.name,
            "before_req_s": before_k6["request_rate"],
            "after_req_s": after_k6["request_rate"],
            "before_error_pct": before_k6["failure_rate"] * 100,
            "after_error_pct": after_k6["failure_rate"] * 100,
            "before_cpu_mean_pct": before["cpu"],
            "after_cpu_mean_pct": after["cpu"],
            "before_cpu_seconds_per_success": before_cost,
            "after_cpu_seconds_per_success": after_cost,
            "cpu_cost_change_pct": percent_change(before_cost, after_cost),
            "before_cpu_per_success_without_first": before_sensitivity,
            "after_cpu_per_success_without_first": after_sensitivity,
            "sensitivity_change_pct": percent_change(
                before_sensitivity, after_sensitivity
            ),
            "before_memory_mean_mib": before["memory"],
            "after_memory_mean_mib": after["memory"],
            "before_samples": before["samples"],
            "after_samples": after["samples"],
            "before_csv_window_s": before["window_seconds"],
            "after_csv_window_s": after["window_seconds"],
            "before_k6_duration_s": before_k6["duration_seconds"],
            "after_k6_duration_s": after_k6["duration_seconds"],
        })
    return rows


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Estima CPU-segundos por requisição bem-sucedida para pares de "
            "medições, usando recursos.csv e resumo-k6.json."
        )
    )
    parser.add_argument(
        "--pair",
        nargs=3,
        action="append",
        required=True,
        metavar=("PAR", "ANTES", "DEPOIS"),
        help="Par e caminhos das pastas de resultados; pode ser repetido.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Arquivo CSV de saída (padrão: stdout).",
    )
    args = parser.parse_args()
    rows = []
    try:
        for pair, before_path, after_path in args.pair:
            rows.extend(pair_rows(pair, before_path, after_path))
        if args.output:
            with args.output.open(
                "w", encoding="utf-8", newline=""
            ) as output:
                write_rows(output, rows)
        else:
            write_rows(sys.stdout, rows)
    except (OSError, ValueError, csv.Error) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
