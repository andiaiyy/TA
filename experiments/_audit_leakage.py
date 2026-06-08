"""Investigation only. Loads phase13 fitted models + feature_sets and
reports feature_importances_ / coefficients per (app, method, model).

Read-only. Does not modify anything.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import joblib

_HERE = Path(__file__).resolve().parent
_PROJ = _HERE.parent
P13 = _PROJ / "storage" / "eve_v2_work" / "results" / "phase13_train"
P12 = _PROJ / "storage" / "eve_v2_work" / "results" / "phase12_fs"


def _load_feature_list(app: str, method: str) -> List[str]:
    p = P12 / f"app={app}" / f"phase12_feature_sets_{app}_run.json"
    fs = json.loads(p.read_text(encoding="utf-8"))["feature_sets"][method]
    if isinstance(fs, dict):  # PCA
        # For PCA, we don't get original feature names — the transformer produces PCs
        return [f"PC{i}" for i in range(fs.get("n_components", 0))]
    return list(fs)


def _model_importances(obj: Any, feat_names: List[str]) -> List[tuple]:
    """Return list of (feature, importance) sorted desc by absolute value."""
    # Pipeline -> get last step
    inner = obj
    if hasattr(obj, "steps"):
        inner = obj.steps[-1][1]
    # Tree-based / XGB
    if hasattr(inner, "feature_importances_"):
        imp = np.asarray(inner.feature_importances_, dtype=float)
        pairs = list(zip(feat_names[:len(imp)], imp))
        return sorted(pairs, key=lambda x: abs(x[1]), reverse=True)
    # LSVC
    if hasattr(inner, "coef_"):
        coef = np.asarray(inner.coef_, dtype=float).ravel()
        pairs = list(zip(feat_names[:len(coef)], coef))
        return sorted(pairs, key=lambda x: abs(x[1]), reverse=True)
    return []


def main() -> int:
    apps = ["dns", "http", "tls", "ssh"]
    methods = ["MI", "RFE", "PCA"]
    models = ["DT", "RFC", "LSVC", "XGB"]

    summary: Dict[str, Any] = {}

    for app in apps:
        print("\n" + "=" * 78)
        print(f"  APP={app}")
        print("=" * 78)
        app_block: Dict[str, Any] = {}
        for method in methods:
            try:
                feats = _load_feature_list(app, method)
            except Exception as e:
                print(f"  [{method}] feature list load failed: {e}")
                continue
            for model_name in models:
                ck = P13 / f"app={app}" / "checkpoints" / method / model_name / "final_model.joblib"
                if not ck.exists():
                    continue
                try:
                    obj = joblib.load(ck)
                except Exception as e:
                    print(f"  [{method}/{model_name}] load failed: {e}")
                    continue

                imps = _model_importances(obj, feats)
                rr = json.loads((ck.parent / "result_row.json").read_text(encoding="utf-8"))
                f1 = rr.get("f1_attack")
                n_train = rr.get("train_rows")
                n_test = rr.get("test_rows")

                top = imps[:5]
                if imps:
                    top_share = abs(imps[0][1]) / (sum(abs(p[1]) for p in imps) + 1e-12)
                else:
                    top_share = 0.0

                line = f"  [{method}/{model_name:<4}]  f1={f1}  train={n_train}/{n_test}  top1_share={top_share:.3f}"
                print(line)
                if top:
                    for name, val in top:
                        print(f"      {name:<25s}  {val:>+.4f}")
                app_block.setdefault(method, {})[model_name] = {
                    "f1_attack": f1,
                    "n_train": n_train,
                    "n_test": n_test,
                    "top5": [(n, float(v)) for n, v in top],
                    "top1_share": float(top_share),
                }
        summary[app] = app_block

    out = _PROJ / "storage" / "eve_v2_work" / "audit_leakage_importances.json"
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
