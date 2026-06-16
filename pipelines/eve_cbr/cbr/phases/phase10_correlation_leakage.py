from __future__ import annotations

"""
Phase 10 - Correlation and Leakage Analysis

Purpose:
- Do NOT read raw eve_<app>.jsonl.
- Do NOT read full train.csv/test.csv.
- Do NOT read Phase 7/8 full dataset shards.
- Read the bounded Phase 8 corr_leak_sample.csv.
- Use Phase 7 leakage_drop_list.json as the baseline no-leak policy.
- Produce two correlation tables:
    1. ALL features, including leakage/audit columns
    2. NO-LEAK features, after leakage/drop policy is applied

Input:
    phase8/corr_leak_sample.csv
    phase7/leakage_drop_list.json
    phase7/training_feature_list.json
    phase8/schema.json optional
    phase8/export_summary.json optional

Output:
    phase10_<app>_corr_ALL.csv
    phase10_<app>_corr_NOLEAK.csv
    phase10_<app>_features_to_drop.json
    phase10_<app>_features_for_modeling.json
    phase10_<app>_nan_issues.json
    phase10_<app>_top_corr_ALL.png
    phase10_<app>_top_corr_NOLEAK.png
    phase10_<app>_summary.json

Generic aliases:
    corr_ALL.csv
    corr_NOLEAK.csv
    features_to_drop.json
    features_for_modeling.json
    nan_issues.json
    summary.json
"""

from collections import Counter
from pathlib import Path
from typing import Any, Optional, Sequence
import json
import math

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

from ..io_utils import now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Leakage policy
# ============================================================

DEFAULT_LEAKAGE_COLUMNS = {
    # Target / labels
    "Target",
    "Target_alert",
    "Target_refined",
    "Target_prelim",

    # Alert-derived / IDS label evidence
    "has_alert",
    "alert_category",
    "alert_category_h",
    "alert_severity",
    "alert_signature",
    "alert_signature_h",
    "alert_signature_id",
    "alert_gid",
    "alert_rev",
    "alert_action",
    "alert_metadata",

    # Label explanation / audit
    "label_source",
    "label_source_h",
    "label_reason",
    "label_reason_h",
    "label_status",
    "label_status_h",
    "label_status_final",
    "label_status_final_h",
    "label_confidence",
    "refinement_reason",
    "suspicious_by_probe",

    # Probe evidence used directly in refinement/audit
    "probe_score_with_alert",
    "probe_level",
    "probe_reason",
    "probe_reason_h",
    "is_suspicious_window",
    "fanout_high",
    "same_alert_window",
    "near_alert_window",
    "matched_alert_window",
    "minutes_to_alert_window",

    # Alert-window shortcut features
    "alert_count_window",
    "valid_alert_count_window",

    # Identifiers / split/audit keys
    "timestamp",
    "window_start",
    "src_ip",
    "dest_ip",
    "first_seen",
    "last_seen",

    # High-risk categorical proxy
    "event_type",
    "event_type_h",
    "event_type_raw",
}

DROP_PREFIXES = (
    "alert_",
    "label_",
    "evidence_",
)

DROP_SUBSTRINGS = (
    "_raw",
)

# These can be behavioral but should be reviewed. For conservative thesis
# modeling, direct refinement-score columns are excluded by default.
MEDIUM_RISK_COLUMNS = {
    "probe_score_no_alert",
    "event_count_window",
    "unique_dest_ip_window",
    "unique_dest_port_window",
    "total_bytes_window",
    "total_pkts_window",
    "no_alert_count_window",
}


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


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _target_col_from_df(df: pd.DataFrame, preferred: str = "Target_refined") -> str:
    for candidate in [preferred, "Target_refined", "Target", "Target_alert"]:
        if candidate in df.columns:
            return candidate
    raise RuntimeError("No target column found. Expected Target_refined or Target.")


def _load_corr_sample(path: Path, *, max_rows: Optional[int] = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if max_rows is not None and int(max_rows) > 0:
        return pd.read_csv(path, nrows=int(max_rows))
    return pd.read_csv(path)


def _to_numeric_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() <= 0:
            continue
        out[col] = s.replace([np.inf, -np.inf], np.nan).fillna(0)
    return out


def _load_phase7_drop_columns(leakage_drop: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    cols = leakage_drop.get("drop_columns", [])
    if isinstance(cols, list):
        out.update(str(c) for c in cols if str(c).strip())
    return out


def _policy_drop_reason(col: str, phase7_drop_cols: set[str], target_col: str) -> str:
    c = str(col)
    cl = c.lower()

    if c == target_col:
        return "target_column"

    if c in phase7_drop_cols:
        return "phase7_leakage_drop_list"

    if c in DEFAULT_LEAKAGE_COLUMNS:
        return "default_leakage_policy"

    if cl in {x.lower() for x in DEFAULT_LEAKAGE_COLUMNS}:
        return "default_leakage_policy_case_insensitive"

    if any(cl.startswith(prefix) for prefix in DROP_PREFIXES):
        return "leakage_prefix"

    if any(substr in cl for substr in DROP_SUBSTRINGS):
        return "raw_or_audit_column"

    return ""


def _build_features_to_drop(
    *,
    df: pd.DataFrame,
    phase7_drop_cols: set[str],
    target_col: str,
) -> dict[str, Any]:
    reasons: dict[str, str] = {}

    for col in df.columns:
        reason = _policy_drop_reason(col, phase7_drop_cols, target_col)
        if reason:
            reasons[str(col)] = reason

    # Keep policy columns even if absent from sample, so later phases can guard
    # against them when reading train/test.
    for col in sorted(DEFAULT_LEAKAGE_COLUMNS | phase7_drop_cols):
        if col != target_col:
            reasons.setdefault(str(col), "guard_policy_absent_from_sample")

    return {
        "phase": 10,
        "title": "Features to Drop for Modeling",
        "created_at": now_iso(),
        "target_column": target_col,
        "drop_columns": sorted(reasons),
        "drop_reasons": {k: reasons[k] for k in sorted(reasons)},
        "drop_prefixes": list(DROP_PREFIXES),
        "drop_substrings": list(DROP_SUBSTRINGS),
        "medium_risk_columns": sorted(MEDIUM_RISK_COLUMNS),
        "note": (
            "This combines Phase 7 leakage policy, default alert/label/probe leakage guards, "
            "and pattern-based safeguards."
        ),
    }


def _compute_corr_table(
    df: pd.DataFrame,
    *,
    target_col: str,
    candidate_cols: Sequence[str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []

    if target_col not in df.columns:
        raise RuntimeError(f"Target column missing: {target_col}")

    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(float)
    if y.nunique(dropna=True) <= 1:
        return pd.DataFrame(columns=["Feature", "Correlation", "Abs_Corr", "N", "Unique"]), [
            {
                "Feature": target_col,
                "Issue": "TARGET_CONSTANT",
                "Unique_Values": int(y.nunique(dropna=True)),
            }
        ]

    rows: list[dict[str, Any]] = []

    for col in candidate_cols:
        if col == target_col or col not in df.columns:
            continue

        x_raw = pd.to_numeric(df[col], errors="coerce")
        null_count = int(x_raw.isna().sum())
        x = x_raw.replace([np.inf, -np.inf], np.nan).fillna(0).astype(float)

        unique_count = int(x.nunique(dropna=True))
        std = float(x.std(ddof=1)) if len(x) > 1 else 0.0

        if unique_count <= 1 or std == 0.0 or not math.isfinite(std):
            issues.append({
                "Feature": str(col),
                "Issue": "CONSTANT_OR_SINGLE_VALUE",
                "Null_Count": null_count,
                "Unique_Values": unique_count,
                "Std_Dev": std,
            })
            continue

        try:
            corr = float(x.corr(y))
        except Exception:
            corr = float("nan")

        if not math.isfinite(corr):
            issues.append({
                "Feature": str(col),
                "Issue": "CORRELATION_NAN",
                "Null_Count": null_count,
                "Unique_Values": unique_count,
                "Std_Dev": std,
            })
            continue

        rows.append({
            "Feature": str(col),
            "Correlation": corr,
            "Abs_Corr": abs(corr),
            "N": int(len(x)),
            "Unique": unique_count,
        })

    if not rows:
        return pd.DataFrame(columns=["Feature", "Correlation", "Abs_Corr", "N", "Unique"]), issues

    corr_df = pd.DataFrame(rows).sort_values("Abs_Corr", ascending=False).reset_index(drop=True)
    return corr_df, issues


def _plot_top_corr(corr_df: pd.DataFrame, path: Path, *, title: str, top_k: int) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)

    if corr_df.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(0.5, 0.5, "No valid correlation features", ha="center", va="center")
        ax.axis("off")
        ax.set_title(title, fontsize=14, fontweight="bold")
        plt.tight_layout()
        plt.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return {"path": str(path), "status": "empty"}

    top = corr_df.head(int(top_k)).copy()
    top = top.sort_values("Correlation", ascending=True)

    fig, ax = plt.subplots(figsize=(12, max(6, len(top) * 0.42)))
    ax.barh(top["Feature"], top["Correlation"])
    ax.axvline(0, linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Pearson correlation with target")
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return {"path": str(path), "status": "completed", "features": top["Feature"].tolist()}


def _feature_modeling_list(
    *,
    numeric_cols: list[str],
    features_to_drop: dict[str, Any],
    corr_noleak: pd.DataFrame,
) -> dict[str, Any]:
    drop_cols = set(features_to_drop.get("drop_columns", []))
    approved = [c for c in numeric_cols if c not in drop_cols]

    return {
        "phase": 10,
        "title": "Features for Modeling Candidate List",
        "created_at": now_iso(),
        "approved_numeric_features": sorted(set(approved)),
        "approved_feature_count": int(len(set(approved))),
        "ranked_by_abs_correlation_noleak": corr_noleak["Feature"].head(200).astype(str).tolist() if not corr_noleak.empty else [],
        "note": (
            "This is still a candidate list. Phase 11/12 may further restrict it before training."
        ),
    }


# ============================================================
# Runner
# ============================================================

def run_phase10(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    export_cfg = getattr(cfg, "export", None)
    split_cfg = getattr(cfg, "split", None)

    top_k = int(getattr(export_cfg, "corr_top_k", 15) or 15)
    max_rows = int(getattr(export_cfg, "corr_leak_sample_rows", 1_000_000) or 1_000_000)
    preferred_target = str(getattr(split_cfg, "target_column", "Target_refined") or "Target_refined")

    phase8_dir = _phase_dir(phase_dir, "phase8")
    phase7_dir = _phase_dir(phase_dir, "phase7")

    corr_sample_path = phase8_dir / "corr_leak_sample.csv"
    export_summary_path = phase8_dir / "export_summary.json"
    phase7_drop_path = phase7_dir / "leakage_drop_list.json"
    phase7_training_path = phase7_dir / "training_feature_list.json"

    export_summary = _read_optional_json(export_summary_path)
    phase7_drop = _read_optional_json(phase7_drop_path)
    phase7_training = _read_optional_json(phase7_training_path)

    print("\n" + "=" * 72)
    print("Phase 10 - Correlation and Leakage Analysis")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {corr_sample_path}")
    print("Mode        : Phase 8 sample only, no raw/full dataset reread")
    print("=" * 72)

    df = _load_corr_sample(corr_sample_path, max_rows=max_rows)

    prefix = f"phase10_{app}"

    corr_all_path = phase_dir / f"{prefix}_corr_ALL.csv"
    corr_noleak_path = phase_dir / f"{prefix}_corr_NOLEAK.csv"
    drop_path = phase_dir / f"{prefix}_features_to_drop.json"
    modeling_path = phase_dir / f"{prefix}_features_for_modeling.json"
    issues_path = phase_dir / f"{prefix}_nan_issues.json"
    top_all_path = phase_dir / f"{prefix}_top_corr_ALL.png"
    top_noleak_path = phase_dir / f"{prefix}_top_corr_NOLEAK.png"
    summary_path = phase_dir / f"{prefix}_summary.json"

    corr_all_alias = phase_dir / "corr_ALL.csv"
    corr_noleak_alias = phase_dir / "corr_NOLEAK.csv"
    drop_alias = phase_dir / "features_to_drop.json"
    modeling_alias = phase_dir / "features_for_modeling.json"
    issues_alias = phase_dir / "nan_issues.json"
    summary_alias = phase_dir / "summary.json"

    if df.empty:
        summary = {
            "phase": 10,
            "title": "Correlation and Leakage Analysis",
            "status": "completed_with_warning",
            "app": app,
            "current_run": app.upper(),
            "generated_at": now_iso(),
            "mode": "phase8_sample_only",
            "warning": "Phase 8 corr_leak_sample.csv was missing or empty.",
            "input": {
                "corr_leak_sample": str(corr_sample_path),
                "phase8_export_summary": str(export_summary_path),
                "phase7_leakage_drop_list": str(phase7_drop_path),
            },
        }
        write_json(summary, summary_path)
        write_json(summary, summary_alias)
        pd.DataFrame().to_csv(corr_all_path, index=False)
        pd.DataFrame().to_csv(corr_noleak_path, index=False)
        pd.DataFrame().to_csv(corr_all_alias, index=False)
        pd.DataFrame().to_csv(corr_noleak_alias, index=False)
        write_json([], issues_path)
        write_json([], issues_alias)
        write_json({"drop_columns": []}, drop_path)
        write_json({"drop_columns": []}, drop_alias)
        write_json({"approved_numeric_features": []}, modeling_path)
        write_json({"approved_numeric_features": []}, modeling_alias)
        return summary

    target_col = _target_col_from_df(df, preferred=preferred_target)

    # Normalize target to binary numeric for correlation.
    df[target_col] = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    df[target_col] = (df[target_col] == 1).astype(np.int8)

    target_counts = {str(k): int(v) for k, v in df[target_col].value_counts(dropna=False).sort_index().to_dict().items()}

    numeric_df = _to_numeric_frame(df)
    if target_col not in numeric_df.columns:
        numeric_df[target_col] = df[target_col].astype(np.int8)

    numeric_cols = [c for c in numeric_df.columns if c != target_col]

    phase7_drop_cols = _load_phase7_drop_columns(phase7_drop)
    features_to_drop = _build_features_to_drop(
        df=df,
        phase7_drop_cols=phase7_drop_cols,
        target_col=target_col,
    )
    drop_cols = set(features_to_drop.get("drop_columns", []))

    noleak_cols = [c for c in numeric_cols if c not in drop_cols]

    corr_all, issues_all = _compute_corr_table(
        numeric_df,
        target_col=target_col,
        candidate_cols=numeric_cols,
    )

    corr_noleak, issues_noleak = _compute_corr_table(
        numeric_df,
        target_col=target_col,
        candidate_cols=noleak_cols,
    )

    issues = {
        "ALL": issues_all,
        "NOLEAK": issues_noleak,
    }

    features_for_modeling = _feature_modeling_list(
        numeric_cols=numeric_cols,
        features_to_drop=features_to_drop,
        corr_noleak=corr_noleak,
    )

    corr_all.to_csv(corr_all_path, index=False)
    corr_noleak.to_csv(corr_noleak_path, index=False)
    corr_all.to_csv(corr_all_alias, index=False)
    corr_noleak.to_csv(corr_noleak_alias, index=False)

    write_json(features_to_drop, drop_path)
    write_json(features_to_drop, drop_alias)

    write_json(features_for_modeling, modeling_path)
    write_json(features_for_modeling, modeling_alias)

    write_json(issues, issues_path)
    write_json(issues, issues_alias)

    top_all_info = _plot_top_corr(
        corr_all,
        top_all_path,
        title=f"{app.upper()} - Top {top_k} Correlation with Target (ALL)",
        top_k=top_k,
    )
    top_noleak_info = _plot_top_corr(
        corr_noleak,
        top_noleak_path,
        title=f"{app.upper()} - Top {top_k} Correlation with Target (NO-LEAK)",
        top_k=top_k,
    )

    # Redundant correlation among no-leak numeric features, sample-bounded.
    redundant_pairs: list[dict[str, Any]] = []
    try:
        keep = corr_noleak["Feature"].head(80).astype(str).tolist() if not corr_noleak.empty else []
        keep = [c for c in keep if c in numeric_df.columns]
        if len(keep) >= 2:
            cmat = numeric_df[keep].corr(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0)
            seen = set()
            for a in keep:
                for b in keep:
                    if a == b:
                        continue
                    key = tuple(sorted((a, b)))
                    if key in seen:
                        continue
                    seen.add(key)
                    val = _safe_float(cmat.loc[a, b], 0.0)
                    if abs(val) >= 0.95:
                        redundant_pairs.append({
                            "feature_a": a,
                            "feature_b": b,
                            "correlation": val,
                            "abs_correlation": abs(val),
                        })
            redundant_pairs = sorted(redundant_pairs, key=lambda x: x["abs_correlation"], reverse=True)[:200]
    except Exception:
        redundant_pairs = []

    redundant_pairs_path = phase_dir / f"{prefix}_redundant_pairs.json"
    redundant_pairs_alias = phase_dir / "redundant_pairs.json"
    write_json(redundant_pairs, redundant_pairs_path)
    write_json(redundant_pairs, redundant_pairs_alias)

    summary = {
        "phase": 10,
        "title": "Correlation and Leakage Analysis",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),
        "mode": "phase8_sample_only_no_full_reread",

        "input": {
            "corr_leak_sample": str(corr_sample_path),
            "phase8_export_summary": str(export_summary_path),
            "phase7_leakage_drop_list": str(phase7_drop_path),
            "phase7_training_feature_list": str(phase7_training_path),
            "phase8_rows_written": export_summary.get("rows_written"),
            "phase8_train_rows": export_summary.get("train_rows"),
            "phase8_test_rows": export_summary.get("test_rows"),
        },

        "sample_rows": int(len(df)),
        "target_column": target_col,
        "target_counts_sample": target_counts,

        "feature_counts": {
            "all_columns_in_sample": int(df.shape[1]),
            "numeric_features_all": int(len(numeric_cols)),
            "numeric_features_noleak": int(len(noleak_cols)),
            "corr_valid_all": int(len(corr_all)),
            "corr_valid_noleak": int(len(corr_noleak)),
            "drop_columns_count": int(len(features_to_drop.get("drop_columns", []))),
            "approved_numeric_features_count": int(len(features_for_modeling.get("approved_numeric_features", []))),
        },

        "top_k": int(top_k),
        "topk_all": corr_all.head(top_k).to_dict(orient="records"),
        "topk_noleak": corr_noleak.head(top_k).to_dict(orient="records"),
        "redundant_pairs_top": redundant_pairs[:25],

        "outputs": {
            "corr_all": str(corr_all_path),
            "corr_noleak": str(corr_noleak_path),
            "features_to_drop": str(drop_path),
            "features_for_modeling": str(modeling_path),
            "nan_issues": str(issues_path),
            "redundant_pairs": str(redundant_pairs_path),
            "top_all_png": str(top_all_path),
            "top_noleak_png": str(top_noleak_path),
            "summary": str(summary_path),
        },

        "figures": {
            "top_all": top_all_info,
            "top_noleak": top_noleak_info,
        },

        "policy_note": (
            "The ALL table is for diagnosis only. The NO-LEAK table excludes target, alert-derived, "
            "label-explanation, probe-refinement evidence, identifiers, raw strings, and Phase 7 drop columns."
        ),
        "read_policy": {
            "raw_jsonl_reread": False,
            "train_test_full_reread": False,
            "source": "phase8_corr_leak_sample",
        },
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 10 - Correlation and Leakage Analysis")
    print("=" * 72)
    print(f"Current Run        : {app.upper()}")
    print(f"Sample Rows        : {len(df):,}")
    print(f"Numeric ALL        : {len(numeric_cols):,}")
    print(f"Numeric NO-LEAK    : {len(noleak_cols):,}")
    print(f"Drop Columns       : {len(features_to_drop.get('drop_columns', [])):,}")
    print(f"Top ALL Output     : {corr_all_path}")
    print(f"Top NO-LEAK Output : {corr_noleak_path}")
    print(f"Output             : {summary_path}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase10_run = run_phase10
phase10_correlation_leakage = run_phase10
phase10_correlation_ram = run_phase10
