"""Dispatch fresh re-runs for the 4 EVE 7-phase pipelines via Celery, then
poll the DB until all FINISHED. Reports new metrics next to historical ones.

USE_ASYNC forced to true so dispatch goes to ids_worker (Docker Celery worker)
rather than running sync in this venv process.

Reads experiments.db to fetch results; does NOT write to it or to artifacts
itself — the orchestrator owns persistence.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

# Force async BEFORE importing config.celery_config (it reads env at import)
os.environ["USE_ASYNC"] = "true"
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/0"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_HERE = Path(__file__).resolve().parent
_PROJ = _HERE.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

from orchestrator.experiment_service import create_and_run_experiment, get_experiment_status

# Use bare basename — the orchestrator's Fix A fallback in worker will resolve
# this to /app/storage/datasets/eve_100k_fixed.json inside the Docker container.
# Avoids the bug where Linux Path() can't parse Windows backslash paths.
DATASET_PATH = "eve_100k_fixed.json"
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


def main() -> int:
    print(f"DATASET: {DATASET_PATH}")
    print(f"USE_ASYNC: {os.environ.get('USE_ASYNC')}")
    print()

    submissions = {}
    for pid, label in PIPELINES:
        print(f"[dispatch] {label:4s}  pid={pid}", flush=True)
        r = create_and_run_experiment("EVE_SURICATA", DATASET_PATH, pid)
        if not r.get("success"):
            print(f"  ERROR: {r.get('error')}")
            return 1
        exp_id = r["experiment_id"]
        submissions[pid] = {"label": label, "experiment_id": exp_id, "status": "QUEUED"}
        print(f"  experiment_id={exp_id}  async_mode={r.get('async_mode')}")
    print()

    print("Polling until all FINISHED/FAILED...")
    poll_interval = 8
    started = time.time()
    deadline = started + 1200  # 20 min safety cap
    last_status = {}
    while time.time() < deadline:
        all_done = True
        any_change = False
        for pid, info in submissions.items():
            if info["status"] in ("FINISHED", "FAILED"):
                continue
            status = get_experiment_status(info["experiment_id"]) or {}
            cur = status.get("status", "?")
            stage = status.get("celery_stage") or ""
            if last_status.get(pid) != (cur, stage):
                elapsed = int(time.time() - started)
                print(f"  [{elapsed:>3}s] {info['label']:4s}  {cur:8s}  stage={stage[:60]}")
                last_status[pid] = (cur, stage)
                any_change = True
            info["status"] = cur
            if cur not in ("FINISHED", "FAILED"):
                all_done = False
        if all_done:
            break
        time.sleep(poll_interval)

    elapsed_total = int(time.time() - started)
    print(f"\nAll done in {elapsed_total}s ({elapsed_total/60:.1f} min)\n")

    print("=" * 88)
    print(f"{'Pipeline':<22} {'Status':<10} {'acc':>7} {'prec':>7} {'rec':>7} {'f1':>7}  vs May 30")
    print("=" * 88)
    for pid, info in submissions.items():
        st = get_experiment_status(info["experiment_id"]) or {}
        s = st.get("status", "?")
        acc = st.get("accuracy")
        prec = st.get("precision_score")
        rec = st.get("recall")
        f1 = st.get("f1_score")
        hist = HISTORICAL[pid]
        # Compare each metric
        def _cmp(now, then):
            if now is None: return "n/a"
            d = now - then
            return "==" if abs(d) < 1e-6 else f"Δ={d:+.4f}"
        if acc is not None:
            cmp_str = f"  acc {_cmp(acc, hist[0])}, f1 {_cmp(f1, hist[3])}"
            print(f"{pid:<22} {s:<10} {acc:>7.4f} {prec:>7.4f} {rec:>7.4f} {f1:>7.4f}{cmp_str}")
        else:
            err = st.get("error_message", "")
            print(f"{pid:<22} {s:<10}   (no metrics) err={(err or '')[:50]}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
