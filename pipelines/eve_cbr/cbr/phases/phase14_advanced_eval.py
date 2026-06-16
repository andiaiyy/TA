from __future__ import annotations

"""
Phase 14 - Final Evaluation Summary

Purpose:
- Do NOT read raw eve_<app>.jsonl.
- Do NOT read full train.csv/test.csv.
- Do NOT read modeling shards.
- Do NOT retrain models.
- Build final evaluation artifacts from Phase 13 results and previous summaries.

Input:
    phase8/export_summary.json
    phase11/readiness_summary.json
    phase12/selected_features.json
    phase13/results_comparison.csv
    phase13/summary.json

Output:
    phase14_<app>_performance_table.csv
    phase14_<app>_best_model.json
    phase14_<app>_roc_auc_summary.json
    phase14_<app>_final_evaluation_summary.json
    figures/*.png

Generic aliases:
    performance_table.csv
    best_model.json
    roc_auc_summary.json
    final_evaluation_summary.json
    summary.json

Important:
- This phase is intentionally summary-driven.
- True ROC curves and confusion matrices require prediction scores / y_pred.
  If Phase 13 does not save those artifacts, Phase 14 records that limitation
  instead of retraining and duplicating heavy work.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
import csv
import json
import math
import shutil

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

from ..io_utils import now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}
DEFAULT_APPS = ("dns", "http", "tls", "ssh")
DEFAULT_METHODS = ("MI", "RFE", "PCA")
DEFAULT_MODELS = ("DT", "RFC", "LSVC", "XGB")


@dataclass(frozen=True)
class Phase14AdvancedEvalConfig:
    # Kept for compatibility with older pipeline calls.
    modeling_dir: Path = Path("results/modeling")
    phase12_dir: Path = Path("results/phase12_fs")
    phase13_dir: Path = Path("results/phase13_train")
    output_dir: Path = Path("results/phase14_advanced_eval")
    selected_apps: tuple[str, ...] = DEFAULT_APPS

    target_col: str = "Target_refined"
    seed: int = 42
    filename_tag: str = "run"

    methods: tuple[str, ...] = DEFAULT_METHODS
    models_for_roc: tuple[str, ...] = DEFAULT_MODELS

    # Kept only to avoid breaking config construction. Phase 14 no longer uses
    # these values for data loading/training.
    train_rows: Optional[int] = None
    test_rows: Optional[int] = None
    sample_mode: str = "summary_only"
    internal_test_size: float = 0.20
    predict_batch_rows: int = 0

    # Model params retained for backwards-compatible config construction.
    rfc_estimators: int = 100
    rfc_n_jobs: int = 1
    rfc_max_depth: Optional[int] = 16
    rfc_min_samples_leaf: int = 2
    lsvc_c: float = 1.0
    lsvc_max_iter: int = 5000
    lsvc_dual: str = "auto"
    xgb_n_estimators: int = 300
    xgb_max_depth: int = 8
    xgb_learning_rate: float = 0.1
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_lambda: float = 1.0
    xgb_n_jobs: int = 1
    xgb_tree_method: str = "hist"
    xgb_device: str = "cpu"
    xgb_eval_metric: str = "logloss"

    best_metric_preference: tuple[str, ...] = (
        # Primary evaluation: natural-distribution holdout.
        "natural_holdout_f1_attack",
        "natural_holdout_auc",
        "natural_holdout_recall_attack",
        "natural_holdout_precision_attack",
        "natural_holdout_accuracy",

        # Secondary evaluation: balanced holdout, useful for class-separability comparison.
        "balanced_holdout_f1_attack",
        "balanced_holdout_auc",
        "balanced_holdout_recall_attack",
        "balanced_holdout_precision_attack",
        "balanced_holdout_accuracy",

        # Backward-compatible Phase 13 aliases.
        "holdout_f1_attack",
        "holdout_auc",
        "f1_attack",
        "auc",
        "holdout_accuracy",
        "accuracy",
    )

    strict_leakage_guard: bool = True
    write_artifacts: bool = True
    overwrite: bool = True


# ============================================================
# Helpers
# ============================================================

def _normalize_app(app: str) -> str:
    app = str(app).strip().lower()
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app={app!r}. Expected one of {sorted(VALID_APPS)}")
    return app


def _phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _read_optional_json(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _clean_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in path.glob("*"):
        try:
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
        except Exception:
            pass


def _df_from_any(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()

    if isinstance(value, tuple) and value:
        for item in value:
            out = _df_from_any(item)
            if not out.empty:
                return out
        return pd.DataFrame()

    if isinstance(value, list) and value:
        try:
            return pd.DataFrame(value)
        except Exception:
            return pd.DataFrame()

    if isinstance(value, dict):
        for key in ("results_table", "results", "rows", "result_rows"):
            item = value.get(key)
            out = _df_from_any(item)
            if not out.empty:
                return out

        best = (
            value.get("best_by_preferred_metric")
            or value.get("best_by_holdout_f1_attack")
            or value.get("best_by_cv_f1_attack")
            or value.get("best")
        )
        if isinstance(best, dict) and best:
            return pd.DataFrame([best])

    return pd.DataFrame()


def _read_csv_df(path: Optional[Path]) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _candidate_phase13_csv(phase13_dir: Path, app: str, tag: str = "run") -> Optional[Path]:
    candidates = [
        phase13_dir / "results_comparison.csv",
        phase13_dir / f"phase13_{app}_results_comparison.csv",
        phase13_dir / f"results_comparison_{app}_{tag}.csv",
        phase13_dir / f"results_comparison_{app}.csv",
        phase13_dir / f"app={app}" / "results_comparison.csv",
        phase13_dir / f"app={app}" / f"results_comparison_{app}_{tag}.csv",
        phase13_dir / app / "results_comparison.csv",
        phase13_dir / app / f"results_comparison_{app}_{tag}.csv",
    ]

    for p in candidates:
        if p.exists():
            return p

    matches = (
        sorted(phase13_dir.glob("*results_comparison*.csv"))
        + sorted((phase13_dir / f"app={app}").glob("*results_comparison*.csv"))
        + sorted((phase13_dir / app).glob("*results_comparison*.csv"))
    )
    return matches[0] if matches else None


def _candidate_phase13_summary(phase13_dir: Path, app: str, tag: str = "run") -> Optional[Path]:
    candidates = [
        phase13_dir / "summary.json",
        phase13_dir / f"phase13_{app}_summary.json",
        phase13_dir / f"phase13_summary_{app}_{tag}.json",
        phase13_dir / f"app={app}" / "summary.json",
        phase13_dir / f"app={app}" / f"phase13_summary_{app}_{tag}.json",
        phase13_dir / app / "summary.json",
        phase13_dir / app / f"phase13_summary_{app}_{tag}.json",
    ]

    for p in candidates:
        if p.exists():
            return p

    matches = (
        sorted(phase13_dir.glob("*summary*.json"))
        + sorted((phase13_dir / f"app={app}").glob("*summary*.json"))
        + sorted((phase13_dir / app).glob("*summary*.json"))
    )
    return matches[0] if matches else None


def _results_from_sources(
    *,
    phase13_dir: Path,
    app: str,
    tag: str,
    phase13_results: Any = None,
    phase13_summary: Any = None,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    source_info: dict[str, Any] = {}

    df = _df_from_any(phase13_results)
    if not df.empty:
        source_info["results_source"] = "phase13_results_argument"
    else:
        csv_path = _candidate_phase13_csv(phase13_dir, app, tag)
        df = _read_csv_df(csv_path)
        source_info["results_source"] = str(csv_path) if csv_path else None

    summary = {}
    if isinstance(phase13_summary, dict):
        summary = phase13_summary
        source_info["summary_source"] = "phase13_summary_argument"
    else:
        summary_path = _candidate_phase13_summary(phase13_dir, app, tag)
        summary = _read_optional_json(summary_path)
        source_info["summary_source"] = str(summary_path) if summary_path else None

    if df.empty and summary:
        df = _df_from_any(summary)
        if not df.empty:
            source_info["results_source"] = "phase13_summary_json_embedded_table"

    return df, summary, source_info


def _normalize_results(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    rename_map = {
        "method": "Method",
        "model": "Model",
        "app": "App",
    }
    for old, new in rename_map.items():
        if old in out.columns and new not in out.columns:
            out[new] = out[old]

    for required in ("App", "Method", "Model"):
        if required not in out.columns:
            out[required] = ""

    metric_cols = [
        # Cross-validation metrics
        "accuracy",
        "precision_attack",
        "recall_attack",
        "f1_attack",
        "auc",

        # Backward-compatible primary holdout aliases
        "holdout_accuracy",
        "holdout_precision_attack",
        "holdout_recall_attack",
        "holdout_f1_attack",
        "holdout_auc",

        # Phase 13 v2: primary natural-distribution holdout
        "natural_holdout_accuracy",
        "natural_holdout_precision_attack",
        "natural_holdout_recall_attack",
        "natural_holdout_f1_attack",
        "natural_holdout_auc",

        # Phase 13 v2: secondary balanced holdout
        "balanced_holdout_accuracy",
        "balanced_holdout_precision_attack",
        "balanced_holdout_recall_attack",
        "balanced_holdout_f1_attack",
        "balanced_holdout_auc",

        "train_rows",
        "test_rows",
        "natural_test_rows",
        "balanced_test_rows",
        "train_features",
        "elapsed_seconds",
    ]
    for col in metric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def _select_best(df: pd.DataFrame, preference: Sequence[str]) -> dict[str, Any] | None:
    if df.empty:
        return None

    for metric in preference:
        if metric not in df.columns:
            continue

        values = pd.to_numeric(df[metric], errors="coerce")
        if values.notna().sum() <= 0:
            continue

        idx = values.idxmax()
        row = df.loc[idx].replace({np.nan: None}).to_dict()
        row["best_metric"] = metric
        row["best_metric_value"] = _safe_float(row.get(metric), 0.0)
        return {str(k): _json_safe(v) for k, v in row.items()}

    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return None if not math.isfinite(x) else x
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    return value


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    safe = df.replace([np.inf, -np.inf], np.nan)
    records = []
    for row in safe.to_dict(orient="records"):
        records.append({str(k): _json_safe(v) for k, v in row.items()})
    return records


def _fieldnames_from_records(records: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in records:
        for k in row:
            if k not in out:
                out.append(k)
    return out


def _metric_available(df: pd.DataFrame, metrics: Sequence[str]) -> list[str]:
    return [m for m in metrics if m in df.columns and pd.to_numeric(df[m], errors="coerce").notna().any()]


CV_METRICS = [
    "accuracy",
    "precision_attack",
    "recall_attack",
    "f1_attack",
    "auc",
]

LEGACY_HOLDOUT_METRICS = [
    "holdout_accuracy",
    "holdout_precision_attack",
    "holdout_recall_attack",
    "holdout_f1_attack",
    "holdout_auc",
]

NATURAL_HOLDOUT_METRICS = [
    "natural_holdout_accuracy",
    "natural_holdout_precision_attack",
    "natural_holdout_recall_attack",
    "natural_holdout_f1_attack",
    "natural_holdout_auc",
]

BALANCED_HOLDOUT_METRICS = [
    "balanced_holdout_accuracy",
    "balanced_holdout_precision_attack",
    "balanced_holdout_recall_attack",
    "balanced_holdout_f1_attack",
    "balanced_holdout_auc",
]


def _coalesce_metric(row: Any, *names: str) -> Any:
    """Return the first non-null metric value from a Series/dict-like row."""
    for name in names:
        try:
            if name in row:
                val = row.get(name)
                if val is not None and val != "" and not (isinstance(val, float) and not math.isfinite(val)):
                    return val
        except Exception:
            continue
    return None


def _evaluation_metric_groups(df: pd.DataFrame) -> dict[str, list[str]]:
    return {
        "cv": _metric_available(df, CV_METRICS),
        "natural_holdout": _metric_available(df, NATURAL_HOLDOUT_METRICS),
        "balanced_holdout": _metric_available(df, BALANCED_HOLDOUT_METRICS),
        "legacy_holdout": _metric_available(df, LEGACY_HOLDOUT_METRICS),
    }


def _preferred_heat_metric(df: pd.DataFrame) -> Optional[str]:
    for candidate in (
        "natural_holdout_f1_attack",
        "natural_holdout_auc",
        "balanced_holdout_f1_attack",
        "balanced_holdout_auc",
        "holdout_f1_attack",
        "holdout_auc",
        "f1_attack",
        "auc",
        "accuracy",
    ):
        if candidate in df.columns and pd.to_numeric(df[candidate], errors="coerce").notna().any():
            return candidate
    return None


def _make_evaluation_table(df: pd.DataFrame, *, prefix: str, label: str) -> list[dict[str, Any]]:
    """Create compact evaluation-specific rows for natural/balanced/legacy holdout tables."""
    if df.empty:
        return []

    metric_map = {
        "accuracy": f"{prefix}_accuracy",
        "precision_attack": f"{prefix}_precision_attack",
        "recall_attack": f"{prefix}_recall_attack",
        "f1_attack": f"{prefix}_f1_attack",
        "auc": f"{prefix}_auc",
    }
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        out = {
            "App": row.get("App"),
            "Method": row.get("Method"),
            "Model": row.get("Model"),
            "evaluation": label,
        }
        has_metric = False
        for short_name, col in metric_map.items():
            val = row.get(col) if col in df.columns else None
            out[short_name] = _json_safe(val)
            if val is not None and not pd.isna(val):
                has_metric = True
        rows_key = "test_rows"
        if prefix.startswith("natural_holdout"):
            rows_key = "natural_test_rows"
        elif prefix.startswith("balanced_holdout"):
            rows_key = "balanced_test_rows"
        out["test_rows"] = _json_safe(row.get(rows_key)) if rows_key in df.columns else _json_safe(row.get("test_rows"))
        if has_metric:
            rows.append(out)
    return rows


# ============================================================
# Plotting
# ============================================================

def _empty_plot(path: Path, title: str, message: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True, fontsize=11)
    ax.axis("off")
    ax.set_title(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)
    return {"path": str(path), "status": "empty", "message": message}


def _bar_metric_plot(df: pd.DataFrame, path: Path, *, metrics: list[str], title: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)

    if df.empty or not metrics:
        return _empty_plot(path, title, "No metric table available.")

    labels = []
    for _, row in df.iterrows():
        labels.append(f"{row.get('Method', '')}/{row.get('Model', '')}")

    x = np.arange(len(labels))
    width = 0.8 / max(1, len(metrics))

    fig, ax = plt.subplots(figsize=(max(12, len(labels) * 0.65), 6.5))
    for i, metric in enumerate(metrics):
        values = pd.to_numeric(df[metric], errors="coerce").fillna(0).to_numpy(dtype=float)
        ax.bar(x + (i - (len(metrics) - 1) / 2) * width, values, width=width, label=metric)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)

    return {"path": str(path), "status": "completed", "metrics": metrics, "rows": int(len(df))}


def _heatmap_plot(df: pd.DataFrame, path: Path, *, metric: str, title: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)

    if df.empty or metric not in df.columns or "Method" not in df.columns or "Model" not in df.columns:
        return _empty_plot(path, title, "Heatmap cannot be generated because Method/Model/metric columns are missing.")

    tmp = df.copy()
    tmp[metric] = pd.to_numeric(tmp[metric], errors="coerce")
    pivot = tmp.pivot_table(values=metric, index="Method", columns="Model", aggfunc="mean")

    if pivot.empty:
        return _empty_plot(path, title, "No valid values for heatmap.")

    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(pivot.values, aspect="auto", vmin=0, vmax=1)
    fig.colorbar(im, ax=ax, label=metric)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    for (i, j), val in np.ndenumerate(pivot.values):
        if math.isfinite(float(val)):
            ax.text(j, i, f"{float(val):.4f}", ha="center", va="center", fontsize=9)

    plt.tight_layout()
    plt.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)

    return {"path": str(path), "status": "completed", "metric": metric}


def _best_model_card(path: Path, best: Optional[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not best:
        return _empty_plot(path, "Best Model Summary", "No best model could be selected.")

    lines = [
        f"Application: {summary.get('app', '').upper()}",
        "",
        "Best model selection",
        f"  Method : {best.get('Method')}",
        f"  Model  : {best.get('Model')}",
        f"  Metric : {best.get('best_metric')}",
        f"  Value  : {_safe_float(best.get('best_metric_value'), 0.0):.4f}",
        "",
        "Rows",
        f"  Phase 8 train rows : {summary.get('phase8_train_rows', 'N/A')}",
        f"  Phase 8 test rows  : {summary.get('phase8_test_rows', 'N/A')}",
        f"  Phase 13 train used: {best.get('train_rows', 'N/A')}",
        f"  Phase 13 test used : {best.get('test_rows', 'N/A')}",
        "",
        "Interpretation",
        "  Phase 14 summarizes Phase 13 results.",
        "  It does not retrain models.",
        "  It does not reread full datasets.",
    ]

    fig, ax = plt.subplots(figsize=(10.5, 7))
    ax.axis("off")
    ax.text(0.03, 0.97, "\n".join(lines), ha="left", va="top", fontsize=12, family="monospace")
    ax.set_title("Phase 14 - Best Model Summary", fontsize=16, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)

    return {"path": str(path), "status": "completed"}


def _placeholder_artifact(path: Path, *, title: str, reason: str) -> dict[str, Any]:
    return _empty_plot(path, title, reason)


# ============================================================
# Summary builders
# ============================================================

def _roc_auc_summary_from_results(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "source": "phase13_results",
            "status": "empty",
            "note": "No Phase 13 result rows were available.",
            "items": {},
        }

    items: dict[str, Any] = {}
    for _, row in df.iterrows():
        method = str(row.get("Method", "unknown"))
        model = str(row.get("Model", "unknown"))
        items.setdefault(method, {})
        items[method][model] = {
            "cv_auc": _json_safe(row.get("auc")) if "auc" in df.columns else None,
            "natural_holdout_auc": (
                _json_safe(row.get("natural_holdout_auc"))
                if "natural_holdout_auc" in df.columns else None
            ),
            "balanced_holdout_auc": (
                _json_safe(row.get("balanced_holdout_auc"))
                if "balanced_holdout_auc" in df.columns else None
            ),
            "legacy_holdout_auc": (
                _json_safe(row.get("holdout_auc"))
                if "holdout_auc" in df.columns else None
            ),
        }

    return {
        "source": "phase13_results_table",
        "status": "metric_summary_only",
        "primary_evaluation": "natural_holdout",
        "secondary_evaluation": "balanced_holdout",
        "items": items,
        "note": (
            "This is an AUC metric summary from Phase 13, not a reconstructed ROC curve. "
            "Natural holdout is treated as the primary evaluation when available; "
            "balanced holdout is retained as a secondary class-separability evaluation. "
            "True ROC curves require prediction score vectors."
        ),
    }

def _warnings(
    *,
    df: pd.DataFrame,
    phase13_summary: dict[str, Any],
    best: Optional[dict[str, Any]],
) -> list[str]:
    out: list[str] = []

    if df.empty:
        out.append("Phase 13 results are missing or empty.")

    if not best:
        out.append("Best model could not be selected.")

    if phase13_summary.get("training_quality_warnings"):
        for w in phase13_summary.get("training_quality_warnings") or []:
            out.append(str(w))

    groups = _evaluation_metric_groups(df)
    if not groups.get("natural_holdout") and groups.get("balanced_holdout"):
        out.append(
            "Natural holdout metrics are unavailable; Phase 14 selected/visualized from balanced or legacy metrics where needed."
        )
    if not groups.get("balanced_holdout") and groups.get("natural_holdout"):
        out.append("Balanced holdout metrics are unavailable; secondary balanced evaluation is missing.")

    # Near perfect metric warning. Check natural first, then balanced, legacy, and CV.
    for metric in (
        "natural_holdout_f1_attack",
        "natural_holdout_auc",
        "balanced_holdout_f1_attack",
        "balanced_holdout_auc",
        "holdout_f1_attack",
        "holdout_auc",
        "f1_attack",
        "auc",
        "accuracy",
    ):
        if metric in df.columns:
            vals = pd.to_numeric(df[metric], errors="coerce")
            if vals.notna().any() and float(vals.max()) >= 0.999:
                out.append(
                    f"Near-perfect {metric} detected in Phase 13 results. "
                    "Treat as leakage/split-review signal before making final claims."
                )
                break

    return out

def _phase8_counts(export_summary: dict[str, Any], split_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "train_rows": _safe_int(export_summary.get("train_rows"), _safe_int(split_summary.get("train_rows"), 0)),
        "test_rows": _safe_int(export_summary.get("test_rows"), _safe_int(split_summary.get("test_rows"), 0)),
        "rows_written": _safe_int(export_summary.get("rows_written"), _safe_int(split_summary.get("total_rows"), 0)),
        "target_counts": export_summary.get("target_counts", {}),
        "train_target_counts": export_summary.get("train_target_counts") or split_summary.get("train_target_counts", {}),
        "test_target_counts": export_summary.get("test_target_counts") or split_summary.get("test_target_counts", {}),
        "file_class_summary": export_summary.get("file_class_summary") or split_summary.get("file_class_summary", {}),
        "dataset_total_class_summary": export_summary.get("dataset_total_class_summary", {}),
        "train_file_class_summary": export_summary.get("train_file_class_summary", {}),
        "test_file_class_summary": export_summary.get("test_file_class_summary", {}),
        "label_source_counts": export_summary.get("label_source_counts", {}),
    }


def _load_upstream_summaries_from_dirs(
    *,
    phase8_dir: Path,
    phase11_dir: Path,
    phase12_dir: Path,
) -> dict[str, Any]:
    return {
        "phase8_export_summary": _read_optional_json(phase8_dir / "export_summary.json"),
        "phase8_split_summary": _read_optional_json(phase8_dir / "split_summary.json"),
        "phase11_readiness_summary": _read_optional_json(phase11_dir / "readiness_summary.json"),
        "phase11_modeling_manifest": _read_optional_json(phase11_dir / "modeling_manifest.json"),
        "phase12_summary": _read_optional_json(phase12_dir / "summary.json"),
        "phase12_selected_features": _read_optional_json(phase12_dir / "selected_features.json"),
    }


# ============================================================
# Core runner
# ============================================================

def _run_phase14_core(
    *,
    app: str,
    output_dir: Path,
    phase8_dir: Path,
    phase11_dir: Path,
    phase12_dir: Path,
    phase13_dir: Path,
    cfg: Any = None,
    phase13_results: Any = None,
    phase13_summary_arg: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    app = _normalize_app(app)
    output_dir = Path(output_dir)

    overwrite = bool(getattr(cfg, "overwrite", True)) if cfg is not None else True
    if overwrite:
        _clean_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    tag = str(getattr(cfg, "filename_tag", "run") if cfg is not None else "run")
    preference = tuple(getattr(cfg, "best_metric_preference", (
        "natural_holdout_f1_attack",
        "natural_holdout_auc",
        "natural_holdout_recall_attack",
        "natural_holdout_precision_attack",
        "natural_holdout_accuracy",
        "balanced_holdout_f1_attack",
        "balanced_holdout_auc",
        "holdout_f1_attack",
        "holdout_auc",
        "f1_attack",
        "auc",
        "holdout_accuracy",
        "accuracy",
    )))

    print("\n" + "=" * 72)
    print("Phase 14 - Final Evaluation Summary")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {phase13_dir}")
    print("Mode        : summary-driven, no retraining")
    print("=" * 72)

    upstream = _load_upstream_summaries_from_dirs(
        phase8_dir=phase8_dir,
        phase11_dir=phase11_dir,
        phase12_dir=phase12_dir,
    )

    results_df, phase13_summary, source_info = _results_from_sources(
        phase13_dir=phase13_dir,
        app=app,
        tag=tag,
        phase13_results=phase13_results,
        phase13_summary=phase13_summary_arg,
    )

    results_df = _normalize_results(results_df)
    metric_groups = _evaluation_metric_groups(results_df)
    best = _select_best(results_df, preference)

    natural_records = _make_evaluation_table(
        results_df,
        prefix="natural_holdout",
        label="natural_holdout_primary",
    )
    balanced_records = _make_evaluation_table(
        results_df,
        prefix="balanced_holdout",
        label="balanced_holdout_secondary",
    )
    legacy_records = _make_evaluation_table(
        results_df,
        prefix="holdout",
        label="legacy_holdout_alias",
    )

    phase8_counts = _phase8_counts(
        upstream.get("phase8_export_summary", {}),
        upstream.get("phase8_split_summary", {}),
    )

    prefix = f"phase14_{app}"

    performance_table_path = output_dir / f"{prefix}_performance_table.csv"
    natural_holdout_table_path = output_dir / f"{prefix}_natural_holdout_table.csv"
    balanced_holdout_table_path = output_dir / f"{prefix}_balanced_holdout_table.csv"
    legacy_holdout_table_path = output_dir / f"{prefix}_legacy_holdout_table.csv"
    best_model_path = output_dir / f"{prefix}_best_model.json"
    roc_auc_path = output_dir / f"{prefix}_roc_auc_summary.json"
    summary_path = output_dir / f"{prefix}_final_evaluation_summary.json"

    performance_table_alias = output_dir / "performance_table.csv"
    natural_holdout_table_alias = output_dir / "natural_holdout_table.csv"
    balanced_holdout_table_alias = output_dir / "balanced_holdout_table.csv"
    legacy_holdout_table_alias = output_dir / "legacy_holdout_table.csv"
    best_model_alias = output_dir / "best_model.json"
    roc_auc_alias = output_dir / "roc_auc_summary.json"
    final_summary_alias = output_dir / "final_evaluation_summary.json"
    summary_alias = output_dir / "summary.json"

    records = _df_to_records(results_df)
    fieldnames = _fieldnames_from_records(records)
    if not fieldnames:
        fieldnames = ["App", "Method", "Model"]

    _write_csv(performance_table_path, records, fieldnames)
    _write_csv(performance_table_alias, records, fieldnames)

    eval_fieldnames = ["App", "Method", "Model", "evaluation", "accuracy", "precision_attack", "recall_attack", "f1_attack", "auc", "test_rows"]
    _write_csv(natural_holdout_table_path, natural_records, eval_fieldnames)
    _write_csv(natural_holdout_table_alias, natural_records, eval_fieldnames)
    _write_csv(balanced_holdout_table_path, balanced_records, eval_fieldnames)
    _write_csv(balanced_holdout_table_alias, balanced_records, eval_fieldnames)
    _write_csv(legacy_holdout_table_path, legacy_records, eval_fieldnames)
    _write_csv(legacy_holdout_table_alias, legacy_records, eval_fieldnames)

    best_payload = {
        "phase": 14,
        "app": app,
        "created_at": now_iso(),
        "selection_policy": list(preference),
        "primary_evaluation": "natural_holdout",
        "secondary_evaluation": "balanced_holdout",
        "best_model": best,
        "source": source_info.get("results_source"),
    }
    write_json(best_payload, best_model_path)
    write_json(best_payload, best_model_alias)

    roc_auc_summary = _roc_auc_summary_from_results(results_df)
    write_json(roc_auc_summary, roc_auc_path)
    write_json(roc_auc_summary, roc_auc_alias)

    natural_holdout_metrics = metric_groups.get("natural_holdout", [])
    balanced_holdout_metrics = metric_groups.get("balanced_holdout", [])
    legacy_holdout_metrics = metric_groups.get("legacy_holdout", [])
    cv_metrics = metric_groups.get("cv", [])

    heat_metric = _preferred_heat_metric(results_df)

    figures = {
        "natural_holdout_metrics": _bar_metric_plot(
            results_df,
            figures_dir / f"{prefix}_natural_holdout_metrics.png",
            metrics=natural_holdout_metrics,
            title=f"{app.upper()} - Natural Holdout Metrics from Phase 13",
        ),
        "balanced_holdout_metrics": _bar_metric_plot(
            results_df,
            figures_dir / f"{prefix}_balanced_holdout_metrics.png",
            metrics=balanced_holdout_metrics,
            title=f"{app.upper()} - Balanced Holdout Metrics from Phase 13",
        ),
        "legacy_holdout_metrics": _bar_metric_plot(
            results_df,
            figures_dir / f"{prefix}_legacy_holdout_metrics.png",
            metrics=legacy_holdout_metrics,
            title=f"{app.upper()} - Legacy Holdout Alias Metrics from Phase 13",
        ),
        "cv_metrics": _bar_metric_plot(
            results_df,
            figures_dir / f"{prefix}_cv_metrics.png",
            metrics=cv_metrics,
            title=f"{app.upper()} - CV Metrics from Phase 13",
        ),
        "performance_heatmap": _heatmap_plot(
            results_df,
            figures_dir / f"{prefix}_performance_heatmap.png",
            metric=heat_metric or "f1_attack",
            title=f"{app.upper()} - Method × Model Performance Heatmap",
        ),
        "best_model_card": _best_model_card(
            figures_dir / f"{prefix}_best_model_card.png",
            best=best,
            summary={
                "app": app,
                "phase8_train_rows": phase8_counts["train_rows"],
                "phase8_test_rows": phase8_counts["test_rows"],
            },
        ),
        "roc_curves_placeholder": _placeholder_artifact(
            figures_dir / f"{prefix}_roc_curves_not_generated.png",
            title=f"{app.upper()} - ROC Curves Not Regenerated",
            reason=(
                "Phase 14 is summary-driven and does not retrain. "
                "True ROC curves require saved prediction scores from Phase 13. "
                "Use Phase 13 natural/balanced AUC metrics for comparison or patch Phase 13 to save prediction scores."
            ),
        ),
        "confusion_matrix_placeholder": _placeholder_artifact(
            figures_dir / f"{prefix}_confusion_matrix_not_generated.png",
            title=f"{app.upper()} - Confusion Matrix Not Regenerated",
            reason=(
                "Phase 14 does not reread train/test or retrain models. "
                "A confusion matrix requires y_true and y_pred from Phase 13. "
                "Patch Phase 13 to save a small prediction summary if an exact confusion matrix is required."
            ),
        ),
    }

    # Top-level compatibility aliases for old report generators. Prefer natural holdout when available.
    preferred_perf = figures_dir / f"{prefix}_natural_holdout_metrics.png"
    if not preferred_perf.exists() or not natural_holdout_metrics:
        preferred_perf = figures_dir / f"{prefix}_balanced_holdout_metrics.png"
    if not preferred_perf.exists() or (not natural_holdout_metrics and not balanced_holdout_metrics):
        preferred_perf = figures_dir / f"{prefix}_legacy_holdout_metrics.png"
    _copy_file(preferred_perf, output_dir / "model_performance_comparison.png")
    _copy_file(figures_dir / f"{prefix}_roc_curves_not_generated.png", output_dir / "roc_curves.png")
    _copy_file(figures_dir / f"{prefix}_confusion_matrix_not_generated.png", output_dir / "confusion_matrix_best_model.png")

    warnings = _warnings(df=results_df, phase13_summary=phase13_summary, best=best)

    summary = {
        "phase": 14,
        "title": "Final Evaluation Summary",
        "status": "completed" if not results_df.empty else "completed_with_warning",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),
        "mode": "summary_driven_no_retraining",
        "evaluation_policy": {
            "primary": "natural_holdout",
            "secondary": "balanced_holdout",
            "best_model_selection": "natural holdout metrics are preferred; balanced holdout is used as fallback/comparison",
            "metric_groups_available": metric_groups,
        },

        "read_policy": {
            "raw_jsonl_reread": False,
            "train_test_full_reread": False,
            "model_retraining": False,
            "dataset_output_created": False,
            "source": "Phase 13 metrics + Phase 8/11/12 summaries",
        },

        "input": {
            "phase8_dir": str(phase8_dir),
            "phase11_dir": str(phase11_dir),
            "phase12_dir": str(phase12_dir),
            "phase13_dir": str(phase13_dir),
            "phase13_results_source": source_info.get("results_source"),
            "phase13_summary_source": source_info.get("summary_source"),
        },

        "phase8": phase8_counts,
        "phase11": {
            "train_rows": upstream.get("phase11_readiness_summary", {}).get("train_rows"),
            "test_rows": upstream.get("phase11_readiness_summary", {}).get("test_rows"),
            "modeling_feature_count": upstream.get("phase11_readiness_summary", {}).get("modeling_feature_count"),
            "warnings": upstream.get("phase11_readiness_summary", {}).get("warnings", []),
        },
        "phase12": {
            "mi_selected_n": upstream.get("phase12_summary", {}).get("mi_selected_n"),
            "rfe_selected_n": upstream.get("phase12_summary", {}).get("rfe_selected_n"),
            "pca_n_components": upstream.get("phase12_summary", {}).get("pca_n_components"),
            "numeric_features_used": upstream.get("phase12_summary", {}).get("numeric_features_used"),
        },
        "phase13": {
            "results_rows": int(len(results_df)),
            "train_rows_loaded": phase13_summary.get("train_rows_loaded"),
            "test_rows_loaded": phase13_summary.get("test_rows_loaded"),
            "natural_test_rows_loaded": phase13_summary.get("natural_test_rows_loaded"),
            "balanced_test_rows_loaded": phase13_summary.get("balanced_test_rows_loaded"),
            "cv_folds": phase13_summary.get("cv_folds"),
            "train_sample_info": phase13_summary.get("train_sample_info", {}),
            "test_sample_info": phase13_summary.get("test_sample_info", {}),
            "natural_test_sample_info": phase13_summary.get("natural_test_sample_info", {}),
            "balanced_test_sample_info": phase13_summary.get("balanced_test_sample_info", {}),
            "holdout_available": phase13_summary.get("holdout_available"),
            "natural_holdout_available": phase13_summary.get("natural_holdout_available"),
            "balanced_holdout_available": phase13_summary.get("balanced_holdout_available"),
            "training_quality_warnings": phase13_summary.get("training_quality_warnings", []),
        },

        "best_model": best,
        "results_table": records,
        "natural_holdout_table": natural_records,
        "balanced_holdout_table": balanced_records,
        "legacy_holdout_table": legacy_records,
        "roc_auc_summary": roc_auc_summary,
        "roc_curve_status": {
            "status": "not_regenerated",
            "reason": "Phase 14 is summary-driven. True ROC curves require saved prediction score vectors from Phase 13.",
        },
        "confusion_matrix_status": {
            "status": "not_regenerated",
            "reason": "Phase 14 is summary-driven. Confusion matrix requires saved y_true/y_pred counts from Phase 13.",
        },

        "figures": figures,
        "warnings": warnings,

        "output": {
            "performance_table": str(performance_table_path),
            "natural_holdout_table": str(natural_holdout_table_path),
            "balanced_holdout_table": str(balanced_holdout_table_path),
            "legacy_holdout_table": str(legacy_holdout_table_path),
            "best_model": str(best_model_path),
            "roc_auc_summary": str(roc_auc_path),
            "summary": str(summary_path),
            "figures_dir": str(figures_dir),
        },

        "note": (
            "Phase 14 summarizes final model evaluation without repeating heavy training/evaluation. "
            "Natural holdout metrics are treated as primary because they preserve the original test distribution; "
            "balanced holdout metrics are reported as secondary comparison. "
            "For exact ROC curves or confusion matrices, save prediction-score artifacts in Phase 13."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, final_summary_alias)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 14 - Final Evaluation Summary")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Results Rows: {len(results_df):,}")
    if best:
        print(f"Best        : {best.get('Method')}/{best.get('Model')} by {best.get('best_metric')}={_safe_float(best.get('best_metric_value'), 0.0):.4f}")
    else:
        print("Best        : N/A")
    print(f"Output      : {summary_path}")
    if warnings:
        print(f"Warnings    : {len(warnings)}")
    print("=" * 72 + "\n")

    return {"summary": summary, "best": best, "figures": figures}, summary


# ============================================================
# Public APIs
# ============================================================

def run_phase14(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    phase13_results: Any = None,
    phase13_summary: Optional[dict[str, Any]] = None,
    **_: Any,
) -> dict[str, Any]:
    """New per-app pipeline API."""
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)

    _result, summary = _run_phase14_core(
        app=app,
        output_dir=phase_dir,
        phase8_dir=_phase_dir(phase_dir, "phase8"),
        phase11_dir=_phase_dir(phase_dir, "phase11"),
        phase12_dir=_phase_dir(phase_dir, "phase12"),
        phase13_dir=_phase_dir(phase_dir, "phase13"),
        cfg=cfg,
        phase13_results=phase13_results,
        phase13_summary_arg=phase13_summary,
    )
    return summary


def phase14_advanced_eval_ram(
    df_train: Any = None,
    df_test: Any = None,
    *,
    app: str,
    phase12_result: Optional[dict[str, Any]] = None,
    phase13_results: Any = None,
    phase13_summary: Optional[dict[str, Any]] = None,
    cfg: Optional[Phase14AdvancedEvalConfig] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Backward-compatible RAM-mode API.

    The df_train/df_test arguments are accepted for old pipeline compatibility,
    but this patched Phase 14 intentionally does not use them. Evaluation is
    summary-driven from Phase 13 outputs.
    """
    app = _normalize_app(app)
    cfg = cfg or Phase14AdvancedEvalConfig(selected_apps=(app,))

    output_dir = Path(cfg.output_dir) / f"app={app}"
    phase13_dir = Path(cfg.phase13_dir)
    phase12_dir = Path(cfg.phase12_dir)

    # Old pipeline usually stores Phase 8/11 elsewhere. If unavailable, these
    # remain harmless empty inputs.
    phase8_dir = Path(getattr(cfg, "phase8_dir", Path(cfg.output_dir).parent / "phase8"))
    phase11_dir = Path(getattr(cfg, "phase11_dir", Path(cfg.output_dir).parent / "phase11"))

    return _run_phase14_core(
        app=app,
        output_dir=output_dir,
        phase8_dir=phase8_dir,
        phase11_dir=phase11_dir,
        phase12_dir=phase12_dir,
        phase13_dir=phase13_dir,
        cfg=cfg,
        phase13_results=phase13_results,
        phase13_summary_arg=phase13_summary,
    )


def phase14_advanced_eval(
    *,
    cfg: Phase14AdvancedEvalConfig,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Compatibility batch API."""
    results: dict[str, dict[str, Any]] = {}
    summaries: dict[str, Any] = {}

    for app in cfg.selected_apps:
        result, summary = phase14_advanced_eval_ram(app=app, cfg=cfg)
        results[str(app).lower()] = result
        summaries[str(app).lower()] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, summary in summaries.items():
        best = summary.get("best_model") or {}
        rows.append({
            "app": app,
            "status": summary.get("status"),
            "results_rows": summary.get("phase13", {}).get("results_rows"),
            "best_method": best.get("Method"),
            "best_model": best.get("Model"),
            "best_metric": best.get("best_metric"),
            "best_metric_value": best.get("best_metric_value"),
            "warnings_count": len(summary.get("warnings", []) or []),
            "summary_json": summary.get("output", {}).get("summary"),
        })

    _write_csv(
        metrics_dir / "phase14_advanced_eval_summary_by_app.csv",
        rows,
        ["app", "status", "results_rows", "best_method", "best_model", "best_metric", "best_metric_value", "warnings_count", "summary_json"],
    )

    summary_all = {
        "phase": 14,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "apps": summaries,
        "output_dir": str(cfg.output_dir),
        "generated_at": now_iso(),
        "note": "Batch compatibility wrapper for summary-driven Phase 14.",
    }
    write_json(summary_all, metrics_dir / "phase14_advanced_eval_summary_all.json")
    return results, summary_all


# Compatibility aliases.
phase14_run = run_phase14
phase14_advanced_evaluation = phase14_advanced_eval
phase14_advanced_eval_in_memory = phase14_advanced_eval_ram
phase14_advanced_evaluation_ram = phase14_advanced_eval_ram
run_phase14_advanced_eval_ram = phase14_advanced_eval_ram
build_phase14_advanced_eval_ram = phase14_advanced_eval_ram
build_phase14_advanced_eval = phase14_advanced_eval
