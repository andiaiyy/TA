"""Post-run summary for the EVE v2 14-phase standalone run.

Reads artifacts that are already on disk under storage/eve_v2_work/ and produces
a JSON summary at storage/eve_v2_work/run_summary.json. Does not re-execute any
phase.

Why this exists separately from run_eve_14phase_standalone.py: that runner's
inline finalize block used the wrong column names from phase13's CSV ("f1"
instead of "f1_attack") and crashed on `max(...)` over Nones. This script
fixes the column naming and is None-safe.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

_HERE = Path(__file__).resolve().parent
_PROJ = _HERE.parent
WORK_DIR = _PROJ / "storage" / "eve_v2_work"
PHASE13_DIR = WORK_DIR / "results" / "phase13_train"
PHASE14_DIR = WORK_DIR / "results" / "phase14_advanced_eval"

# Phase 13 CSV column names (binary task → metric_attack suffix)
CV_METRIC_COLS = (
    "accuracy", "accuracy_std",
    "precision_attack", "recall_attack", "f1_attack", "auc",
)
HOLDOUT_METRIC_COLS = (
    "holdout_accuracy",
    "holdout_precision_attack", "holdout_recall_attack",
    "holdout_f1_attack", "holdout_auc",
)


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        f = float(x)
    except Exception:
        return None
    if f != f:  # NaN
        return None
    return f


def _collect_phase13_bundle() -> List[Dict[str, Any]]:
    """Return list of per-(app, method, model) records from phase 13 result CSVs."""
    if not PHASE13_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for app_dir in sorted(PHASE13_DIR.glob("app=*")):
        app = app_dir.name.split("=", 1)[1]
        for csv_path in sorted(app_dir.glob("results_comparison_*.csv")):
            df = pd.read_csv(csv_path)
            df["app"] = app
            for rec in df.to_dict(orient="records"):
                row = {
                    "app": app,
                    "method": rec.get("Method") or rec.get("method"),
                    "model": rec.get("Model") or rec.get("model"),
                    "train_rows": rec.get("train_rows"),
                    "test_rows": rec.get("test_rows"),
                    "train_features": rec.get("train_features"),
                    "cv_folds": rec.get("cv_folds"),
                }
                for col in CV_METRIC_COLS + HOLDOUT_METRIC_COLS:
                    row[col] = _safe_float(rec.get(col))
                out.append(row)
    return out


def _best_combo(bundle: List[Dict[str, Any]], metric: str) -> Optional[Dict[str, Any]]:
    eligible = [r for r in bundle if _safe_float(r.get(metric)) is not None]
    if not eligible:
        return None
    return max(eligible, key=lambda r: r[metric])


def _suspicious_rows(bundle: List[Dict[str, Any]], threshold: float = 0.999) -> int:
    return sum(1 for r in bundle if (_safe_float(r.get("f1_attack")) or 0.0) >= threshold)


def _collect_phase14_summary() -> Dict[str, Any]:
    """Pick up phase14's per-app summary JSON if present."""
    info: Dict[str, Any] = {}
    if not PHASE14_DIR.exists():
        return info
    for app_dir in sorted(PHASE14_DIR.glob("app=*")):
        app = app_dir.name.split("=", 1)[1]
        for js in sorted(app_dir.glob("*summary*.json")):
            try:
                info[app] = json.loads(js.read_text(encoding="utf-8"))
                break
            except Exception:
                pass
    return info


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    bundle = _collect_phase13_bundle()
    print(f"phase13 bundle: {len(bundle)} records (expected 48 = 4 apps x 3 methods x 4 models)")

    best_cv = _best_combo(bundle, "f1_attack")
    best_holdout = _best_combo(bundle, "holdout_f1_attack")
    susp = _suspicious_rows(bundle, 0.999)

    if best_cv:
        print(f"\nBest by CV F1_attack:")
        print(f"  app={best_cv['app']}  method={best_cv['method']}  model={best_cv['model']}")
        print(f"  f1_attack={best_cv['f1_attack']}  auc={best_cv['auc']}  accuracy={best_cv['accuracy']}")

    if best_holdout:
        print(f"\nBest by holdout F1_attack:")
        print(f"  app={best_holdout['app']}  method={best_holdout['method']}  model={best_holdout['model']}")
        print(f"  holdout_f1_attack={best_holdout['holdout_f1_attack']}")
        print(f"  holdout_auc={best_holdout['holdout_auc']}")
        print(f"  holdout_accuracy={best_holdout['holdout_accuracy']}")

    print(f"\nSuspicious rows (f1_attack >= 0.999): {susp}/{len(bundle)}")

    # Sample 5 records for quick eyeball
    if bundle:
        print(f"\nSample of bundle (first 5 of {len(bundle)}):")
        for r in bundle[:5]:
            print(f"  app={r['app']:>4} method={r['method']:>3} model={r['model']:>4}  "
                  f"f1={r['f1_attack']}  auc={r['auc']}  train={r['train_rows']}  test={r['test_rows']}")

    phase14 = _collect_phase14_summary()
    apps_with_phase14 = sorted(phase14.keys())
    print(f"\nphase14 summary present for apps: {apps_with_phase14}")

    summary = {
        "n_records": len(bundle),
        "best_by_cv_f1_attack": best_cv,
        "best_by_holdout_f1_attack": best_holdout,
        "n_suspicious_at_0.999": susp,
        "phase14_apps_summarized": apps_with_phase14,
        "bundle": bundle,
    }
    out_path = WORK_DIR / "run_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote summary: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
