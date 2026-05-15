# src/cbr/phases/phase7_corr.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from datetime import datetime
import json

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()


@dataclass(frozen=True)
class Phase7Config:
    target_col: str = "Target"

    # sample size
    n_sample: int = 1_000_000
    top_k: int = 15

    force_rebuild: bool = False
    filename_tag: str = ""
    out_dir: Path = Path("results/phase7")

    # UPDATED: leakage denylist (target leakage / label-proxy)
    # event_type/event_type_h is commonly a proxy for "alert" vs non-alert
    leakage_cols: tuple[str, ...] = (
        "event_type",
        "event_type_h",
        "has_alert",
        "alert_category",
        "alert_severity",
    )

    # sampling control
    sample_seed: int = 42
    sample_mode: str = "stratified_balanced"  # "stratified_balanced" | "random"


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


def _save_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _sample_df(
    df: pd.DataFrame,
    target_col: str,
    n_take: int,
    seed: int,
    mode: str = "stratified_balanced",
) -> pd.DataFrame:
    """
    Return a sampled dataframe (copy) of size n_take.
    - stratified_balanced: tries 50/50 class balance
    - random: pure random sample
    Ensures sample isn't single-class when both classes exist in df.
    """
    rng = np.random.default_rng(seed)

    if n_take >= len(df):
        return df.copy()

    if mode == "random":
        return df.sample(n=n_take, random_state=seed).copy()

    if target_col not in df.columns:
        return df.sample(n=n_take, random_state=seed).copy()

    y = _to_numeric_safe(df[target_col]).astype(int)
    uniq = y.nunique(dropna=True)
    if uniq <= 1:
        return df.sample(n=n_take, random_state=seed).copy()

    pos_idx = y.index[y == 1].to_numpy()
    neg_idx = y.index[y == 0].to_numpy()

    if len(pos_idx) == 0 or len(neg_idx) == 0:
        return df.sample(n=n_take, random_state=seed).copy()

    n_pos_target = n_take // 2
    n_neg_target = n_take - n_pos_target

    n_pos = min(len(pos_idx), n_pos_target)
    n_neg = min(len(neg_idx), n_neg_target)

    remaining = n_take - (n_pos + n_neg)
    if remaining > 0:
        if n_pos < n_pos_target:
            add_neg = min(remaining, len(neg_idx) - n_neg)
            n_neg += add_neg
            remaining -= add_neg
        if remaining > 0 and n_neg < n_neg_target:
            add_pos = min(remaining, len(pos_idx) - n_pos)
            n_pos += add_pos
            remaining -= add_pos

    if n_pos + n_neg < n_take:
        return df.sample(n=n_take, random_state=seed).copy()

    pick_pos = rng.choice(pos_idx, size=n_pos, replace=False)
    pick_neg = rng.choice(neg_idx, size=n_neg, replace=False)
    pick = np.concatenate([pick_pos, pick_neg])
    rng.shuffle(pick)

    return df.loc[pick].copy()


def _compute_corr_table(df_in: pd.DataFrame, target_col: str, cols: list[str]) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """
    Compute correlation table for given cols.
    Returns:
      corr_df: Feature, Correlation, Abs_Corr
      nan_issues: list of issue dicts
      valid_cols: list of columns successfully correlated
    """
    nan_issues: list[dict] = []
    valid_cols: list[str] = []

    target_data = df_in[target_col].astype(float).replace([np.inf, -np.inf], 0).fillna(0)

    for col in cols:
        col_data = _to_numeric_safe(df_in[col])

        raw_num = pd.to_numeric(df_in[col], errors="coerce")
        nulls = int(raw_num.isna().sum())
        infs = int(np.isinf(raw_num.fillna(0)).sum())
        uniq = int(col_data.nunique(dropna=True))
        const = float(col_data.std()) == 0.0

        try:
            corr_val = col_data.corr(target_data)
            is_nan = pd.isna(corr_val)
        except Exception:
            corr_val = None
            is_nan = True

        if is_nan:
            if nulls == len(df_in):
                issue = "ALL_NULL"
            elif const or uniq <= 1:
                issue = "CONSTANT_OR_SINGLE"
            elif infs > 0:
                issue = "INFINITY_VALUES"
            elif nulls > len(df_in) * 0.5:
                issue = "MOSTLY_NULL"
            else:
                issue = "UNKNOWN"

            nan_issues.append({
                "Feature": col,
                "Issue": issue,
                "Null_Count": nulls,
                "Inf_Count": infs,
                "Unique_Values": uniq,
                "Std_Dev": float(col_data.std()),
                "Min": float(col_data.min()),
                "Max": float(col_data.max()),
            })
        else:
            valid_cols.append(col)

    correlations = []
    nan_count = 0
    for col in valid_cols:
        try:
            col_data = _to_numeric_safe(df_in[col]).astype(float)
            corr_val = col_data.corr(target_data)
            if pd.isna(corr_val):
                nan_count += 1
                corr_val = 0.0
            correlations.append({
                "Feature": col,
                "Correlation": float(corr_val),
                "Abs_Corr": float(abs(corr_val)),
            })
        except Exception:
            correlations.append({"Feature": col, "Correlation": 0.0, "Abs_Corr": 0.0})

    if len(correlations) == 0:
        corr_df = pd.DataFrame(columns=["Feature", "Correlation", "Abs_Corr"])
    else:
        corr_df = pd.DataFrame(correlations).sort_values("Abs_Corr", ascending=False)

    return corr_df, nan_issues, valid_cols


def _plot_topk(corr_df: pd.DataFrame, top_k: int, out_path: Path, title: str) -> None:
    if corr_df is None or len(corr_df) == 0:
        return
    top = corr_df.head(top_k)
    if len(top) == 0:
        return

    fig, ax = plt.subplots(figsize=(12, 8))
    top_plot = top.sort_values("Correlation")
    ax.barh(range(len(top_plot)), top_plot["Correlation"].values)
    ax.set_yticks(range(len(top_plot)))
    ax.set_yticklabels(top_plot["Feature"].values, fontsize=9)
    ax.axvline(0, linewidth=1)
    ax.set_title(title)
    ax.set_xlabel("Correlation")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def phase7_correlation_analysis(df_clean: pd.DataFrame, cfg: Phase7Config) -> dict[str, Any]:
    """
    Phase 7:
    - input: df_clean (Phase 4)
    - sample: stratified/random sample
    - outputs:
        corr_df_ALL csv + plot  (includes leakage columns; for leakage detection)
        corr_df_NOLEAK csv + plot (excludes leakage columns; for normal insight)
        issues json, drop json, meta json, feature inventory
    """
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tag = cfg.filename_tag.strip() or "run"

    corr_all_csv   = out_dir / f"corr_df_ALL_{tag}.csv"
    corr_nl_csv    = out_dir / f"corr_df_NOLEAK_{tag}.csv"
    issues_json    = out_dir / f"nan_issues_{tag}.json"
    drop_json      = out_dir / f"features_to_drop_{tag}.json"
    meta_json      = out_dir / f"phase7_meta_{tag}.json"
    top_all_png    = out_dir / f"top_features_correlation_ALL_{tag}.png"
    top_nl_png     = out_dir / f"top_features_correlation_NOLEAK_{tag}.png"
    feat_txt       = out_dir / f"features_phase7_{tag}.txt"
    feat_json      = out_dir / f"features_phase7_{tag}.json"

    # small-cache (artifacts only)
    if (not cfg.force_rebuild) and corr_all_csv.exists() and meta_json.exists():
        print(f"✅ Phase 7 cached results found:\n   - {corr_all_csv}\n   - {meta_json}\n")
        corr_df = pd.read_csv(corr_all_csv)
        top_corr_df = corr_df.head(cfg.top_k)
        return {
            "skipped": True,
            "phase": 7,
            "out_dir": str(out_dir),
            "corr_all_csv": str(corr_all_csv),
            "corr_noleak_csv": str(corr_nl_csv) if corr_nl_csv.exists() else None,
            "meta_json": str(meta_json),
            "issues_json": str(issues_json) if issues_json.exists() else None,
            "drop_json": str(drop_json) if drop_json.exists() else None,
            "top_all_png": str(top_all_png) if top_all_png.exists() else None,
            "top_noleak_png": str(top_nl_png) if top_nl_png.exists() else None,
            "top_k": int(cfg.top_k),
            "top15_all": top_corr_df.to_dict(orient="records"),
        }

    phase7_start = datetime.now()

    if cfg.target_col not in df_clean.columns:
        raise RuntimeError(
            f"Target column missing in df input: '{cfg.target_col}'. "
            f"Fix upstream phases. DO NOT synthesize Target."
        )

    # sample-based input
    n_take = min(cfg.n_sample, len(df_clean))
    df_in = _sample_df(
        df=df_clean,
        target_col=cfg.target_col,
        n_take=n_take,
        seed=cfg.sample_seed,
        mode=cfg.sample_mode,
    )

    # Ensure Target numeric
    df_in[cfg.target_col] = _to_numeric_safe(df_in[cfg.target_col]).astype(int)

    if df_in[cfg.target_col].nunique(dropna=True) <= 1:
        dist = df_in[cfg.target_col].value_counts(dropna=False).to_dict()
        raise RuntimeError(
            f"Phase 7 sample has CONSTANT Target -> correlation undefined. "
            f"Target dist in sample: {dist}. Fix sampling strategy."
        )

    print("\n" + "⚪ " + "="*76)
    print("PHASE 7: STATISTICAL ANALYSIS & CORRELATION DIAGNOSTICS")
    print("⚪ " + "="*76 + "\n")
    print(f"🔍 Input rows (sample): {len(df_in):,}  (mode={cfg.sample_mode}, seed={cfg.sample_seed})")
    print(f"🎯 Target dist (sample): {df_in[cfg.target_col].value_counts(dropna=False).to_dict()}")

    # leakage presence (DO NOT DROP HERE; only flag)
    leakage_present = [c for c in cfg.leakage_cols if c in df_in.columns and c != cfg.target_col]
    print(f"🧨 Leakage present     : {len(leakage_present)} -> {leakage_present if leakage_present else '-'}")

    # numeric features
    numeric_features = df_in.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    if cfg.target_col in numeric_features:
        numeric_features.remove(cfg.target_col)

    print(f"🔍 Numeric features (all): {len(numeric_features)}\n")

    # --- Compute correlations ALL (includes leakage) ---
    corr_all, nan_issues, valid_cols = _compute_corr_table(df_in, cfg.target_col, numeric_features)

    # --- Compute correlations NO-LEAK (excludes leakage) ---
    numeric_noleak = [c for c in numeric_features if c not in set(leakage_present)]
    corr_noleak, _, valid_noleak = _compute_corr_table(df_in, cfg.target_col, numeric_noleak)

    # Build features_to_drop (for downstream modeling)
    features_to_drop = [x["Feature"] for x in nan_issues]
    for c in leakage_present:
        if c not in features_to_drop:
            features_to_drop.insert(0, c)

    print(f"   ✓ Valid features (all)   : {len(valid_cols)}")
    print(f"   ✓ Valid features (noleak): {len(valid_noleak)}")
    print(f"   ✗ features_to_drop       : {len(features_to_drop)} (leakage + invalid corr)")

    # Save artifacts
    corr_all.to_csv(corr_all_csv, index=False)
    corr_noleak.to_csv(corr_nl_csv, index=False)
    _save_json(nan_issues, issues_json)
    _save_json(features_to_drop, drop_json)

    # Plots
    _plot_topk(
        corr_all, cfg.top_k, top_all_png,
        title=f"Top {cfg.top_k} Correlation with Target (INCLUDING leakage)"
    )
    _plot_topk(
        corr_noleak, cfg.top_k, top_nl_png,
        title=f"Top {cfg.top_k} Correlation with Target (NO leakage cols)"
    )

    # Feature inventory (NO DROP — inventory of sampled df)
    all_features = [str(c) for c in df_in.columns.tolist()]
    numeric_cols = df_in.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    non_numeric_cols = [c for c in all_features if c not in set(numeric_cols)]

    feat_txt.write_text("\n".join(all_features), encoding="utf-8")
    _save_json(
        {
            "total_columns": len(all_features),
            "numeric_columns": len(numeric_cols),
            "non_numeric_columns": len(non_numeric_cols),
            "features": all_features,
            "leakage_present": leakage_present,
            "features_to_drop_for_modeling": features_to_drop,
        },
        feat_json,
    )

    meta = {
        "phase": 7,
        "input_rows": int(len(df_in)),
        "sample_mode": cfg.sample_mode,
        "sample_seed": int(cfg.sample_seed),

        "numeric_features_total_all": int(len(numeric_features)),
        "numeric_features_total_noleak": int(len(numeric_noleak)),

        "valid_features_all": int(len(valid_cols)),
        "valid_features_noleak": int(len(valid_noleak)),

        "leakage_present": leakage_present,
        "features_to_drop_for_modeling": features_to_drop,

        "top_k": int(cfg.top_k),
        "topk_all": corr_all.head(cfg.top_k).to_dict(orient="records"),
        "topk_noleak": corr_noleak.head(cfg.top_k).to_dict(orient="records"),

        "generated_at": datetime.now().isoformat(),
        "corr_all_csv": str(corr_all_csv),
        "corr_noleak_csv": str(corr_nl_csv),
        "issues_json": str(issues_json),
        "drop_json": str(drop_json),
        "top_all_png": str(top_all_png) if top_all_png.exists() else None,
        "top_noleak_png": str(top_nl_png) if top_nl_png.exists() else None,
        "features_txt": str(feat_txt),
        "features_json": str(feat_json),
    }
    _save_json(meta, meta_json)

    phase7_time = (datetime.now() - phase7_start).total_seconds()
    print(f"\n✅ PHASE 7 COMPLETE - {phase7_time:.2f}s ({phase7_time/60:.2f} min)")
    print(f"💾 Saved:")
    print(f"   - {corr_all_csv}")
    print(f"   - {corr_nl_csv}")
    print(f"   - {issues_json}")
    print(f"   - {drop_json}")
    if top_all_png.exists():
        print(f"   - {top_all_png}")
    if top_nl_png.exists():
        print(f"   - {top_nl_png}")
    print(f"   - {meta_json}")
    print(f"   - {feat_txt}")
    print(f"   - {feat_json}\n")

    return {
        "skipped": False,
        **meta,
    }