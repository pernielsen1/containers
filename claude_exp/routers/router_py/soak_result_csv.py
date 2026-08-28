"""Shared csv_results/soak_results.csv + soak_summary.csv writer for the resilience soak scripts
(soak_resilience_light.py, soak_resilience_hard.py) - reimplements run_soak.sh's record_result()
in Python so a resilience run's rows land in the exact same files/schema as an ordinary
run_soak.sh perf run (semicolon-separated, comma-decimal, utf-8-sig BOM on first write), just
distinguished by an implementation column that carries the resilience run's own suffix
(e.g. "router_py_fail_pct10", "router_py_before_kill") rather than a bare "router_py" - so a
resilience row is never confused for a clean-run baseline when the two CSVs are read together,
without needing a second set of output files.

record_result(row) takes the same bare row shape stress_run.sh prints to stdout:
"implementation;target_tps;duration_s;sent;received;errors;achieved_tps;p50_ms;p90_ms;p95_ms;
p99_ms;max_ms" - dot-decimal, no timestamp/env yet (those get added here, same as run_soak.sh).
"""
import os
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ROUTERS_ROOT = os.path.dirname(PROJECT_ROOT)
CSV_RESULTS_DIR = os.path.join(ROUTERS_ROOT, "csv_results")
SOAK_RESULTS_CSV = os.path.join(CSV_RESULTS_DIR, "soak_results.csv")
SOAK_SUMMARY_CSV = os.path.join(CSV_RESULTS_DIR, "soak_summary.csv")

ENV_NAME = os.environ.get("ENV_NAME") or os.uname().nodename

_RESULTS_HEADER = (
    "timestamp;env;implementation;target_tps;duration_s;sent;received;errors;achieved_tps;"
    "p50_ms;p90_ms;p95_ms;p99_ms;max_ms\n"
)
_SUMMARY_HEADER = "timestamp;env;implementation;target_tps;duration_s;p50_ms;p90_ms;p99_ms\n"


def _ensure_header(path, header):
    os.makedirs(CSV_RESULTS_DIR, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(header)


def record_result(row: str) -> None:
    _ensure_header(SOAK_RESULTS_CSV, _RESULTS_HEADER)
    _ensure_header(SOAK_SUMMARY_CSV, _SUMMARY_HEADER)

    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    comma_row = row.replace(".", ",")
    with open(SOAK_RESULTS_CSV, "a", encoding="utf-8", newline="") as f:
        f.write(f"{ts};{ENV_NAME};{comma_row}\n")

    fields = row.split(";")
    impl, tps, dur, _sent, _recv, _err, _atps, p50, p90, _p95, p99, _mx = fields
    with open(SOAK_SUMMARY_CSV, "a", encoding="utf-8", newline="") as f:
        f.write(f"{ts};{ENV_NAME};{impl};{tps};{dur};{p50.replace('.', ',')};"
                 f"{p90.replace('.', ',')};{p99.replace('.', ',')}\n")
