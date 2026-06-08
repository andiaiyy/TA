"""Run 4 EVE 7-phase pipelines synchronously on host venv. Writes metrics to
the shared experiments.db (same DB as Docker UI sees via volume mount).
"""
import os
os.environ["USE_ASYNC"] = "false"  # force sync; bypass Celery

import io
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_HERE = Path(__file__).resolve().parent
_PROJ = _HERE.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

from orchestrator.experiment_service import create_and_run_experiment

DATASET_PATH = str(_PROJ / "storage" / "datasets" / "eve_100k_fixed.json")
PIPELINES = [
    ("eve_suricata.rfc", "RFC"),
    ("eve_suricata.dt",  "DT"),
    ("eve_suricata.knn", "KNN"),
    ("eve_suricata.xgb", "XGB"),
]
HISTORICAL = {
    "eve_suricata.rfc": (0.9720, 0.9767, 0.9720, 0.9731),
    "eve_suricata.dt":  (0.9706, 0.9747, 0.9706, 0.9717),
    "eve_suricata.knn": (0.9696, 0.9748, 0.9696, 0.9709),
    "eve_suricata.xgb": (0.9707, 0.9760, 0.9707, 0.9720),
}


def _cmp(now, then):
    if now is None: return "n/a"
    d = now - then
    return "==" if abs(d) < 1e-6 else f"Δ={d:+.4f}"


def main() -> int:
    print(f"DATASET: {DATASET_PATH}")
    print(f"USE_ASYNC: {os.environ['USE_ASYNC']}\n")

    results = {}
    t_start = time.time()
    for pid, label in PIPELINES:
        print(f"--- {label} ({pid}) ---", flush=True)
        t0 = time.time()
        r = create_and_run_experiment("EVE_SURICATA", DATASET_PATH, pid)
        elapsed = time.time() - t0
        if not r.get("success"):
            print(f"  FAIL: {r.get('error')}")
            results[pid] = {"status": "FAILED", "error": r.get("error")}
            continue
        m = r.get("metrics") or {}
        results[pid] = {
            "status": "FINISHED",
            "experiment_id": r["experiment_id"],
            "elapsed": elapsed,
            "accuracy": m.get("accuracy"),
            "precision": m.get("precision"),
            "recall": m.get("recall"),
            "f1_score": m.get("f1_score"),
            "roc_auc": m.get("roc_auc"),
        }
        print(f"  OK   elapsed={elapsed:.1f}s  acc={m.get('accuracy'):.4f}  f1={m.get('f1_score'):.4f}")

    total = time.time() - t_start
    print(f"\nTotal: {total:.1f}s = {total/60:.1f} min\n")

    print("=" * 88)
    print(f"{'Pipeline':<22} {'Status':<10} {'acc':>7} {'prec':>7} {'rec':>7} {'f1':>7}   vs May 30")
    print("=" * 88)
    for pid, label in PIPELINES:
        r = results.get(pid, {})
        s = r.get("status", "?")
        if s != "FINISHED":
            print(f"{pid:<22} {s:<10}   error={r.get('error', '')[:50]}")
            continue
        a, p, rc, f1 = r["accuracy"], r["precision"], r["recall"], r["f1_score"]
        h = HISTORICAL[pid]
        cmp_str = f"  acc {_cmp(a, h[0])}, f1 {_cmp(f1, h[3])}"
        print(f"{pid:<22} {s:<10} {a:>7.4f} {p:>7.4f} {rc:>7.4f} {f1:>7.4f}{cmp_str}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
