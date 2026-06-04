"""SVC HIKARI timing diagnostic — DIAGNOSTIC ONLY, NOT a real experiment.

Runs the EXACT SVC config from pipelines/hikari2021/svc_pipeline.py on
progressively larger stratified subsamples of HIKARI2021, and records
training wall-clock time + process-CPU time per size.

DOES NOT touch:
  - experiments.db
  - storage/artifacts/
  - orchestrator/experiment_service
  - Celery / Redis

Output: storage/diagnostics/svc_timing.json (incremental write per size).

Run from project root:
    .\\venv\\Scripts\\python.exe experiments\\svc_timing_diagnostic.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.svm import SVC
from sklearn.model_selection import train_test_split

# Allow imports from project root when launched as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.dataset_parser import parse_dataset
from pipelines.hikari2021._common import common_preprocess

DATA_PATH = "storage/datasets/ALLFLOWMETER_HIKARI2021.csv"
OUT_FILE = Path("storage/diagnostics/svc_timing.json")
RANDOM_STATE = 42

# Sizes are the TOTAL stratified subsample drawn from X, before the 70/30 split.
# Pipeline uses test_size=0.3 stratified, so n_train = round(0.7 * n_total).
# We keep this proportion identical to the production pipeline.
SIZES = [3_000, 6_000, 10_000, 20_000, 35_000]


def main() -> int:
    print("=" * 64)
    print("SVC TIMING DIAGNOSTIC — runs identical SVC config on subsamples")
    print("DOES NOT write to experiments.db or storage/artifacts/")
    print("=" * 64)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[1/4] Loading dataset: {DATA_PATH}")
    t0 = time.perf_counter()
    df = parse_dataset(DATA_PATH)
    print(f"      Loaded {len(df):,} rows in {time.perf_counter() - t0:.1f}s")

    print(f"\n[2/4] common_preprocess (drop artifact cols + non-numeric + NaN rows)")
    X, y, feat, _ = common_preprocess(df, label_col="Label")
    print(f"      X.shape = {X.shape}; class balance: 0={int((y==0).sum()):,}, 1={int((y==1).sum()):,}")
    n_full = len(X)
    full_train = int(round(0.7 * n_full))
    print(f"      Full dataset size = {n_full:,}; pipeline would use n_train={full_train:,} after 70/30")

    results = []

    print(f"\n[3/4] Timing SVC fits on progressive subsamples")
    print(f"      Config: SVC(probability=True, random_state=42)  [== production svc_pipeline.py]")
    print(f"      No scaling applied (same as production pipeline)\n")
    print(f"{'n_total':>8} {'n_train':>8} {'wall_s':>10} {'cpu_s':>10} {'cpu_pct':>8} {'cpu_pct_2cores':>14}")
    print("-" * 64)

    for n in SIZES:
        if n > n_full:
            print(f"      [skip] requested n={n:,} > available n_full={n_full:,}")
            continue

        # Stratified subsample to size n
        Xs, _, ys, _ = train_test_split(
            X, y, train_size=n, random_state=RANDOM_STATE, stratify=y
        )
        # 70/30 split identical to pipeline
        Xt, _, yt, _ = train_test_split(
            Xs, ys, test_size=0.3, random_state=RANDOM_STATE, stratify=ys
        )

        clf = SVC(probability=True, random_state=RANDOM_STATE)
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        clf.fit(Xt, yt)
        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
        cpu_pct = (cpu / wall) * 100.0 if wall > 0 else 0.0

        row = {
            "n_total": int(n),
            "n_train": int(len(Xt)),
            "wall_sec": round(wall, 3),
            "cpu_sec": round(cpu, 3),
            "cpu_pct_of_one_core": round(cpu_pct, 1),
        }
        results.append(row)

        print(
            f"{n:>8,} {len(Xt):>8,} {wall:>10.2f} {cpu:>10.2f}"
            f" {cpu_pct:>7.1f}% {(cpu_pct/2):>13.1f}%"
        )

        OUT_FILE.write_text(json.dumps({"results": results}, indent=2))

    if len(results) < 2:
        print("\n[4/4] Not enough data points to extrapolate (need ≥ 2).")
        return 0

    print(f"\n[4/4] Power-law extrapolation: wall_sec = a * n_train^b")
    n_arr = np.array([r["n_train"] for r in results], dtype=float)
    t_arr = np.array([r["wall_sec"] for r in results], dtype=float)
    log_n = np.log(n_arr)
    log_t = np.log(t_arr)
    b, log_a = np.polyfit(log_n, log_t, 1)
    a = float(np.exp(log_a))
    print(f"      Fit: wall_sec = {a:.6g} * n_train^{b:.3f}")
    print(f"      (For RBF SVC, b ≈ 2 is normal; b > 2 means kernel evals dominate.)")

    extrap_n = full_train
    t_full_fit = float(a * (extrap_n ** b))
    print(f"\n      Extrapolation to n_train = {extrap_n:,} (production scenario):")
    print(f"        Main SVC fit alone   : ~{t_full_fit:>10.0f} s   = {t_full_fit/60:>6.1f} min   = {t_full_fit/3600:>5.2f} h")

    # learning_curve cost: cv=3, train_sizes=[0.2,0.4,0.6,0.8,1.0] on full X_train.
    # For each size frac s, each of 3 folds trains on (2/3)*s*n_train rows.
    # Cost per fit ~ a * ((2/3)*s*n_train)^b. Total = 3 × Σ_s cost(s).
    fractions = [0.2, 0.4, 0.6, 0.8, 1.0]
    lc_cost = 0.0
    for s in fractions:
        per_fold_n = (2.0 / 3.0) * s * extrap_n
        per_fold_cost = a * (per_fold_n ** b)
        lc_cost += 3.0 * per_fold_cost
    # learning_curve runs estimators with n_jobs=2 → parallel speedup ~ /2 (capped by available cores)
    lc_cost_parallel = lc_cost / 2.0
    print(f"        Learning curve (~15 sub-fits, n_jobs=2 parallel): ~{lc_cost_parallel:.0f} s = {lc_cost_parallel/60:.1f} min")

    total = t_full_fit + lc_cost_parallel
    print(f"        TOTAL (fit + learning_curve)                  : ~{total:.0f} s = {total/60:.1f} min = {total/3600:.2f} h")

    summary = {
        "config": {
            "kernel": "rbf (default)",
            "probability": True,
            "scaling": False,
            "random_state": RANDOM_STATE,
            "max_iter": -1,
        },
        "results": results,
        "power_law": {"a": a, "b": b, "form": "wall_sec = a * n_train ** b"},
        "extrapolation_to_production": {
            "n_train": int(extrap_n),
            "main_fit_sec": t_full_fit,
            "learning_curve_sec": lc_cost_parallel,
            "total_sec": total,
            "total_hours": total / 3600,
        },
        "notes": [
            "Diagnostic only — DOES NOT modify experiments.db or storage/artifacts/",
            "Extrapolation assumes pure power-law scaling; libsvm SMO often shows super-quadratic behavior on harder convergence regions, so real time may exceed the estimate.",
            "cpu_pct = process CPU time / wall time. ~100% on one core = single-threaded busy work (libsvm SMO is single-threaded for fit), ~200% means n_jobs spread across two cores.",
        ],
    }
    OUT_FILE.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote diagnostic summary: {OUT_FILE.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
