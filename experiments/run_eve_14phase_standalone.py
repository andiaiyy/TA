"""EVE Suricata 14-phase pipeline — STANDALONE end-to-end runner.

DIAGNOSTIC / TAHAP 1 only. Does NOT touch experiments.db, storage/artifacts/,
the platform registry, or any production pipeline. Produces all output under
storage/eve_v2_work/results/phaseN_.../ so the artifact tree is fully isolated
and inspectable.

Why this script exists
----------------------
The 14 v2 phase modules under pipelines/eve_suricata/phases_v2/ were extracted
from a notebook and have never been wired into the platform's orchestrator. We
need to prove the chain runs end-to-end before we attempt integration. This
script is the proof.

What it does
------------
1. Reads storage/datasets/eve_100k_fixed.json (NDJSON, 100k records).
2. Calls phase1 ... phase14 sequentially, each with explicit input/output
   directories pinned under storage/eve_v2_work/results/.
3. Forces parquet_engine="pyarrow" everywhere (fastparquet is NOT installed
   in the venv; Phase 11/12/13 default to fastparquet and would crash).
4. Times each phase, captures success/failure, prints a per-phase status line.
5. At the end, loads phase13's results_comparison_*.csv per app and phase14's
   summary, prints best (model, method, app) by F1, and writes a JSON summary
   to storage/eve_v2_work/run_summary.json.

If any phase fails, the runner halts, prints which phase + traceback, and exits
non-zero. No cleanup is done — partial outputs stay on disk for forensic look.
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback

# Phase scripts print Unicode emoji (e.g. 🔵). Force UTF-8 stdout/stderr so the
# default cp1252 console on Windows doesn't crash on the first print.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Project root on sys.path so phase imports work without installing
_HERE = Path(__file__).resolve().parent
_PROJ = _HERE.parent
if str(_PROJ) not in sys.path:
    sys.path.insert(0, str(_PROJ))

from pipelines.eve_suricata.phases_v2.phase1 import (
    Phase1DiskConfig, phase1_initial_parsing_label_evidence,
)
from pipelines.eve_suricata.phases_v2.phase2_app_filter import (
    Phase2AppFilterConfig, phase2_filter_applications,
)
from pipelines.eve_suricata.phases_v2.phase3_probing_analysis import (
    Phase3ProbingConfig, phase3_probing_analysis,
)
from pipelines.eve_suricata.phases_v2.phase4_label_refinement import (
    Phase4LabelRefinementConfig, phase4_refine_labels,
)
from pipelines.eve_suricata.phases_v2.phase5_feature_engineering import (
    Phase5FeatureEngineeringConfig, phase5_feature_engineering,
)
from pipelines.eve_suricata.phases_v2.phase6_computed_features import (
    Phase6ComputedFeaturesConfig, phase6_computed_features,
)
from pipelines.eve_suricata.phases_v2.phase7_cleaning import (
    Phase7CleaningConfig, phase7_cleaning,
)
from pipelines.eve_suricata.phases_v2.phase8_export_dataset import (
    Phase8ExportConfig, phase8_export_dataset,
)
from pipelines.eve_suricata.phases_v2.phase9_visualization import (
    Phase9VisualizationConfig, phase9_visualization,
)
from pipelines.eve_suricata.phases_v2.phase10_correlation_leakage import (
    Phase10CorrelationLeakageConfig, phase10_correlation_leakage,
)
from pipelines.eve_suricata.phases_v2.phase11_modeling_split import (
    Phase11ModelingSplitConfig, phase11_modeling_split,
)
from pipelines.eve_suricata.phases_v2.phase12_fs import (
    Phase12FSConfig, phase12_fs,
)
from pipelines.eve_suricata.phases_v2.phase13_train import (
    Phase13TrainConfig, phase13_train,
)
from pipelines.eve_suricata.phases_v2.phase14_advanced_eval import (
    Phase14AdvancedEvalConfig, phase14_advanced_eval,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
INPUT_FILE = _PROJ / "storage" / "datasets" / "eve_100k_fixed.json"
WORK_DIR = _PROJ / "storage" / "eve_v2_work"
RESULTS = WORK_DIR / "results"

PHASE_DIRS = {
    1:  RESULTS / "phase1_dataset",
    2:  RESULTS / "phase2_app_dataset",
    3:  RESULTS / "phase3_probing",
    4:  RESULTS / "phase4_labeled_dataset",
    5:  RESULTS / "phase5_feature_engineered_dataset",
    6:  RESULTS / "phase6_computed_features_dataset",
    7:  RESULTS / "phase7_clean_dataset",
    8:  RESULTS / "phase8_export_dataset",
    9:  RESULTS / "phase9_visualization",
    10: RESULTS / "phase10_correlation_leakage",
    11: RESULTS / "modeling",
    12: RESULTS / "phase12_fs",
    13: RESULTS / "phase13_train",
    14: RESULTS / "phase14_advanced_eval",
}

PARQUET_ENGINE = "pyarrow"  # fastparquet NOT installed in venv


# ---------------------------------------------------------------------------
# Runner harness
# ---------------------------------------------------------------------------
def _hdr(n: int, name: str) -> None:
    print("\n" + "=" * 78)
    print(f"  PHASE {n:>2}: {name}")
    print("=" * 78)


def _run(label: str, fn, *args, **kwargs) -> Tuple[bool, float, Any, str]:
    t0 = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        print(f"\n[OK]  {label}  elapsed={elapsed:.1f}s")
        return True, elapsed, out, ""
    except Exception:
        elapsed = time.perf_counter() - t0
        tb = traceback.format_exc()
        print(f"\n[FAIL] {label}  elapsed={elapsed:.1f}s")
        print(tb)
        return False, elapsed, None, tb


def main() -> int:
    print(f"INPUT_FILE = {INPUT_FILE}")
    print(f"WORK_DIR   = {WORK_DIR}")
    print(f"PARQUET_ENGINE = {PARQUET_ENGINE}")
    if not INPUT_FILE.exists():
        print(f"\nERROR: input file not found at {INPUT_FILE}")
        return 2
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    timings: List[Dict[str, Any]] = []
    status: Dict[int, str] = {}

    # -- PHASE 1 -----------------------------------------------------------
    _hdr(1, "Initial parsing + label evidence (NDJSON -> staging parquet)")
    ok, t, out, tb = _run(
        "phase1",
        phase1_initial_parsing_label_evidence,
        INPUT_FILE,
        max_lines=None,
        disk=Phase1DiskConfig(
            output_dir=PHASE_DIRS[1],
            write_format="parquet",
            batch_size=200_000,
            return_df_sample=10_000,
            save_sample_file=True,
            parquet_engine=PARQUET_ENGINE,
            parquet_compression="snappy",
        ),
    )
    timings.append({"phase": 1, "elapsed_sec": t, "ok": ok})
    status[1] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 2 -----------------------------------------------------------
    _hdr(2, "App filter (split into dns/http/tls/ssh shards)")
    ok, t, out, tb = _run(
        "phase2",
        phase2_filter_applications,
        cfg=Phase2AppFilterConfig(
            input_dir=PHASE_DIRS[1],
            output_dir=PHASE_DIRS[2],
        ),
    )
    timings.append({"phase": 2, "elapsed_sec": t, "ok": ok})
    status[2] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 3 -----------------------------------------------------------
    _hdr(3, "Probing analysis (src_ip window features per app)")
    ok, t, out, tb = _run(
        "phase3",
        phase3_probing_analysis,
        cfg=Phase3ProbingConfig(
            input_dir=PHASE_DIRS[2],
            output_dir=PHASE_DIRS[3],
        ),
    )
    timings.append({"phase": 3, "elapsed_sec": t, "ok": ok})
    status[3] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 4 -----------------------------------------------------------
    _hdr(4, "Label refinement (no-alert != benign; merge probing evidence -> Target)")
    ok, t, out, tb = _run(
        "phase4",
        phase4_refine_labels,
        cfg=Phase4LabelRefinementConfig(
            phase2_input_dir=PHASE_DIRS[2],
            phase3_input_dir=PHASE_DIRS[3],
            output_dir=PHASE_DIRS[4],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 4, "elapsed_sec": t, "ok": ok})
    status[4] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 5 -----------------------------------------------------------
    _hdr(5, "Feature engineering")
    ok, t, out, tb = _run(
        "phase5",
        phase5_feature_engineering,
        cfg=Phase5FeatureEngineeringConfig(
            input_dir=PHASE_DIRS[4],
            output_dir=PHASE_DIRS[5],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 5, "elapsed_sec": t, "ok": ok})
    status[5] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 6 -----------------------------------------------------------
    _hdr(6, "Computed features")
    ok, t, out, tb = _run(
        "phase6",
        phase6_computed_features,
        cfg=Phase6ComputedFeaturesConfig(
            input_dir=PHASE_DIRS[5],
            output_dir=PHASE_DIRS[6],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 6, "elapsed_sec": t, "ok": ok})
    status[6] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 7 -----------------------------------------------------------
    _hdr(7, "Cleaning (NaN/Inf removal, constant-column drop)")
    ok, t, out, tb = _run(
        "phase7",
        phase7_cleaning,
        cfg=Phase7CleaningConfig(
            input_dir=PHASE_DIRS[6],
            output_dir=PHASE_DIRS[7],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 7, "elapsed_sec": t, "ok": ok})
    status[7] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 8 (export CSV; no downstream) -------------------------------
    _hdr(8, "Export dataset (final CSV record)")
    ok, t, out, tb = _run(
        "phase8",
        phase8_export_dataset,
        cfg=Phase8ExportConfig(
            input_dir=PHASE_DIRS[7],
            output_dir=PHASE_DIRS[8],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 8, "elapsed_sec": t, "ok": ok})
    status[8] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 9 (visualization; no downstream) ----------------------------
    _hdr(9, "Visualization")
    ok, t, out, tb = _run(
        "phase9",
        phase9_visualization,
        cfg=Phase9VisualizationConfig(
            input_dir=PHASE_DIRS[7],
            output_dir=PHASE_DIRS[9],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 9, "elapsed_sec": t, "ok": ok})
    status[9] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 10 ----------------------------------------------------------
    _hdr(10, "Correlation + leakage detection (features_to_drop per app)")
    ok, t, out, tb = _run(
        "phase10",
        phase10_correlation_leakage,
        cfg=Phase10CorrelationLeakageConfig(
            input_dir=PHASE_DIRS[7],
            output_dir=PHASE_DIRS[10],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 10, "elapsed_sec": t, "ok": ok})
    status[10] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 11 ----------------------------------------------------------
    _hdr(11, "Modeling split (train/test per app, stratified random)")
    ok, t, out, tb = _run(
        "phase11",
        phase11_modeling_split,
        cfg=Phase11ModelingSplitConfig(
            input_dir=PHASE_DIRS[7],
            phase10_dir=PHASE_DIRS[10],
            output_dir=PHASE_DIRS[11],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 11, "elapsed_sec": t, "ok": ok})
    status[11] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 12 ----------------------------------------------------------
    _hdr(12, "Feature selection (MI / RFE / PCA)")
    ok, t, out, tb = _run(
        "phase12",
        phase12_fs,
        cfg=Phase12FSConfig(
            modeling_dir=PHASE_DIRS[11],
            output_dir=PHASE_DIRS[12],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 12, "elapsed_sec": t, "ok": ok})
    status[12] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 13 ----------------------------------------------------------
    _hdr(13, "Train (4 models x 3 methods x 4 apps = 48 combos)")
    ok, t, out, tb = _run(
        "phase13",
        phase13_train,
        cfg=Phase13TrainConfig(
            modeling_dir=PHASE_DIRS[11],
            phase12_dir=PHASE_DIRS[12],
            output_dir=PHASE_DIRS[13],
            parquet_engine=PARQUET_ENGINE,
            save_fitted_models=True,
        ),
    )
    timings.append({"phase": 13, "elapsed_sec": t, "ok": ok})
    status[13] = "ok" if ok else "fail"
    if not ok:
        return _finalize(timings, status, tb)

    # -- PHASE 14 ----------------------------------------------------------
    _hdr(14, "Advanced evaluation (ROC curves, confusion matrices, best-combo)")
    ok, t, out, tb = _run(
        "phase14",
        phase14_advanced_eval,
        cfg=Phase14AdvancedEvalConfig(
            modeling_dir=PHASE_DIRS[11],
            phase12_dir=PHASE_DIRS[12],
            phase13_dir=PHASE_DIRS[13],
            output_dir=PHASE_DIRS[14],
            parquet_engine=PARQUET_ENGINE,
        ),
    )
    timings.append({"phase": 14, "elapsed_sec": t, "ok": ok})
    status[14] = "ok" if ok else "fail"

    return _finalize(timings, status, tb if not ok else "")


def _finalize(timings: List[Dict[str, Any]], status: Dict[int, str], tb: str) -> int:
    print("\n" + "=" * 78)
    print("  SUMMARY")
    print("=" * 78)
    total = sum(t["elapsed_sec"] for t in timings)
    for t in timings:
        mark = "OK  " if t["ok"] else "FAIL"
        print(f"  Phase {t['phase']:>2}  [{mark}]  {t['elapsed_sec']:>8.1f}s")
    print(f"  {'TOTAL':<10}             {total:>8.1f}s = {total/60:.1f} min")

    summary = {
        "input_file": str(INPUT_FILE),
        "work_dir": str(WORK_DIR),
        "parquet_engine": PARQUET_ENGINE,
        "timings": timings,
        "status_per_phase": {k: v for k, v in status.items()},
        "total_sec": total,
        "all_ok": all(t["ok"] for t in timings),
        "failed_at_phase": next((t["phase"] for t in timings if not t["ok"]), None),
        "traceback": tb if tb else None,
    }

    # Try to surface phase14 bundle samples if phase13 + phase14 ran
    if status.get(13) == "ok":
        bundle = _collect_phase13_results()
        summary["phase13_results_bundle"] = bundle[:60]  # cap for sanity
        if bundle:
            best = max(bundle, key=lambda r: r.get("f1", -1.0))
            summary["best_combo"] = best
            print("\n  Best (model, method, app) by F1 from phase13:")
            print(f"    app={best.get('app')}  model={best.get('model')}  method={best.get('method')}")
            print(f"    f1={best.get('f1')}  accuracy={best.get('accuracy')}  auc={best.get('auc')}")

    summary_path = WORK_DIR / "run_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n  Wrote run summary: {summary_path}")

    return 0 if summary["all_ok"] else 1


def _collect_phase13_results() -> List[Dict[str, Any]]:
    """Scan results/phase13_train/app=*/results_comparison_*.csv and return rows."""
    import pandas as pd

    out: List[Dict[str, Any]] = []
    base = PHASE_DIRS[13]
    if not base.exists():
        return out
    for app_dir in sorted(base.glob("app=*")):
        app = app_dir.name.split("=", 1)[1]
        for csv_path in sorted(app_dir.glob("results_comparison_*.csv")):
            try:
                df = pd.read_csv(csv_path)
                df["app"] = app
                for rec in df.to_dict(orient="records"):
                    out.append({k: rec.get(k) for k in (
                        "app", "model", "method", "accuracy", "precision", "recall",
                        "f1", "auc", "holdout_accuracy", "holdout_f1_attack",
                        "holdout_auc",
                    )})
            except Exception:
                pass
    return out


if __name__ == "__main__":
    raise SystemExit(main())
