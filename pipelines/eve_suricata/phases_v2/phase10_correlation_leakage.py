# src/cbr/phases/phase10_correlation_leakage.py
from __future__ import annotations

import gc
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

from tqdm import tqdm


# =============================================================================
# PHASE 10: CORRELATION + LEAKAGE ANALYSIS (APP-AWARE, SHARDED-SAFE)
# =============================================================================
# Purpose:
#   Diagnose target correlation and leakage after Phase 7 clean dataset.
#
# Input:
#   results/phase7_clean_dataset/app={app}/part-*.parquet
#
# Output:
#   results/phase10_correlation_leakage/app={app}/
#     corr_df_ALL_{app}_{tag}.csv
#     corr_df_NOLEAK_{app}_{tag}.csv
#     nan_issues_{app}_{tag}.json
#     features_to_drop_{app}_{tag}.json
#     phase10_meta_{app}_{tag}.json
#     features_phase10_{app}_{tag}.txt
#     features_phase10_{app}_{tag}.json
#     top_features_correlation_ALL_{app}_{tag}.png
#     top_features_correlation_NOLEAK_{app}_{tag}.png
#
# Important:
#   - This phase no longer receives one in-memory df_clean.
#   - This phase no longer assumes global attacks/benign folders.
#   - It samples from app shards to avoid loading very large data into RAM.
#   - It writes per-app features_to_drop for Phase 11 modeling split.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")


DEFAULT_LEAKAGE_COLS: Tuple[str, ...] = (
    # Original alert-derived leakage / label proxy
    "event_type",
    "event_type_h",
    "event_type_raw",
    "has_alert",
    "alert_category",
    "alert_category_h",
    "alert_severity",
    "alert_signature",
    "alert_signature_h",
    "alert_signature_id",

    # Phase 1 preliminary/staging label evidence
    "Target_prelim",
    "label_status",
    "label_status_h",

    # Phase 4 final label explanation/evidence
    "label_status_final",
    "label_status_final_h",
    "label_source",
    "label_source_h",
    "label_reason",
    "label_reason_h",
    "label_confidence",
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",

    # Probing evidence used for label refinement
    "probe_score",
    "is_possible_probe",
    "is_probe_suspicious",
    "probe_reason",
    "probe_reason_h",

    # Probing/window shortcuts. In alert_only mode the aggregate window features
    # may still be behavioral features, but this phase keeps them available in
    # features_to_drop when the pipeline supplies strict leakage settings.
    "alert_count_window",
    "target_prelim_malicious_count",

    # Join/helper column used in probing
    "window_start",
    "window_start_h",
)


@dataclass(frozen=True)
class Phase10CorrelationLeakageConfig:
    input_dir: Path = Path("results/phase7_clean_dataset")
    output_dir: Path = Path("results/phase10_correlation_leakage")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    target_col: str = "Target"
    n_sample: int = 1_000_000
    top_k: int = 15

    sample_seed: int = 42
    sample_mode: str = "stratified_balanced"  # "stratified_balanced" | "random"

    leakage_cols: Tuple[str, ...] = DEFAULT_LEAKAGE_COLS

    # Extra compatibility fields for the leakage-aware AIRC/PPT pipeline.
    # The current pipeline mostly passes leakage_cols directly, but these flags
    # make the phase safe if called with a newer config later.
    strict_leakage_guard: bool = True
    drop_probe_direct_features: bool = True
    drop_label_explanation_features: bool = True
    drop_alert_derived_features: bool = True
    extra_drop_cols: Tuple[str, ...] = ()

    force_rebuild: bool = False
    filename_tag: str = "run"

    parquet_engine: Optional[str] = "fastparquet"
    gc_each_shard: bool = True


# =============================================================================
# Helpers
# =============================================================================

def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(max(0, int(n)))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} B"


def _file_size_bytes(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


def _read_shard(path: Path, *, parquet_engine: Optional[str] = None) -> pd.DataFrame:
    suffixes = "".join(path.suffixes).lower()
    if path.suffix.lower() == ".parquet":
        kwargs: Dict[str, Any] = {}
        if parquet_engine:
            kwargs["engine"] = parquet_engine
        return pd.read_parquet(path, **kwargs)
    if suffixes.endswith(".csv.gz"):
        return pd.read_csv(path, compression="gzip")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported shard format: {path}")


def _list_app_shards(input_dir: Path, app: str) -> List[Path]:
    app = str(app).strip().lower()
    dirs = [
        Path(input_dir) / f"app={app}",
        Path(input_dir) / app,
    ]

    files: List[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for pat in ("part-*.parquet", "part-*.csv.gz", "part-*.csv", "*.parquet", "*.csv.gz", "*.csv"):
            files.extend(sorted(d.glob(pat)))

    return sorted(set(files))


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        raise RuntimeError(f"Target column missing: {target_col}")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


def _counter_to_str_dict(c: Counter) -> Dict[str, int]:
    return {str(k): int(v) for k, v in c.items()}


def _plot_topk(corr_df: pd.DataFrame, top_k: int, out_path: Path, title: str) -> None:
    if corr_df is None or corr_df.empty:
        return

    top = corr_df.head(int(top_k))
    if top.empty:
        return

    fig, ax = plt.subplots(figsize=(12, 8))
    top_plot = top.sort_values("Correlation")
    ax.barh(range(len(top_plot)), top_plot["Correlation"].values)
    ax.set_yticks(range(len(top_plot)))
    ax.set_yticklabels(top_plot["Feature"].values, fontsize=9)
    ax.axvline(0, linewidth=1)
    ax.set_title(title)
    ax.set_xlabel("Correlation with Target")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# Sampling from shards
# =============================================================================

class _ReservoirSampler:
    def __init__(self, k: int, seed: int):
        self.k = max(0, int(k))
        self.rng = np.random.default_rng(int(seed))
        self.n_seen = 0
        self.df: Optional[pd.DataFrame] = None

    def add(self, df: pd.DataFrame) -> None:
        if self.k <= 0 or df is None or df.empty:
            return

        if self.df is None:
            if len(df) <= self.k:
                self.df = df.copy().reset_index(drop=True)
                self.n_seen += len(df)
                return
            idx = self.rng.choice(len(df), size=self.k, replace=False)
            self.df = df.iloc[idx].copy().reset_index(drop=True)
            self.n_seen += len(df)
            return

        for i in range(len(df)):
            self.n_seen += 1
            j = int(self.rng.integers(0, max(1, self.n_seen)))
            if j < self.k:
                self.df.iloc[j] = df.iloc[i]

    def dataframe(self) -> pd.DataFrame:
        if self.df is None:
            return pd.DataFrame()
        return self.df.reset_index(drop=True)


def _sample_plan_balanced(target_counts: Counter, n_take: int) -> Dict[int, int]:
    total = int(sum(target_counts.values()))
    n_take = min(max(0, int(n_take)), total)
    if total <= 0 or n_take <= 0:
        return {}

    n_pos_avail = int(target_counts.get(1, 0))
    n_neg_avail = int(target_counts.get(0, 0))

    if n_pos_avail <= 0 or n_neg_avail <= 0:
        # Single class fallback.
        key = 1 if n_pos_avail > 0 else 0
        return {key: min(n_take, int(target_counts.get(key, 0)))}

    n_pos = min(n_take // 2, n_pos_avail)
    n_neg = min(n_take - n_pos, n_neg_avail)

    remaining = n_take - (n_pos + n_neg)
    if remaining > 0:
        neg_left = n_neg_avail - n_neg
        pos_left = n_pos_avail - n_pos

        add_neg = min(remaining, neg_left)
        n_neg += add_neg
        remaining -= add_neg

        if remaining > 0:
            add_pos = min(remaining, pos_left)
            n_pos += add_pos

    return {0: int(n_neg), 1: int(n_pos)}


def _sample_plan_proportional(target_counts: Counter, n_take: int) -> Dict[int, int]:
    total = int(sum(target_counts.values()))
    n_take = min(max(0, int(n_take)), total)
    if total <= 0 or n_take <= 0:
        return {}

    plan: Dict[int, int] = {}
    for k, v in target_counts.items():
        kk = int(k)
        plan[kk] = int((int(v) / max(1, total)) * n_take)

    for k, v in target_counts.items():
        kk = int(k)
        if int(v) > 0 and plan.get(kk, 0) == 0 and sum(plan.values()) < n_take:
            plan[kk] = 1

    remaining = n_take - sum(plan.values())
    for k, _v in sorted(target_counts.items(), key=lambda kv: int(kv[1]), reverse=True):
        if remaining <= 0:
            break
        kk = int(k)
        plan[kk] = plan.get(kk, 0) + 1
        remaining -= 1

    while sum(plan.values()) > n_take:
        kmax = max(plan, key=lambda kk: plan[kk])
        plan[kmax] -= 1
        if plan[kmax] <= 0:
            del plan[kmax]

    return {int(k): int(v) for k, v in plan.items() if int(v) > 0}


def _scan_shards_for_counts(
    shard_files: List[Path],
    *,
    cfg: Phase10CorrelationLeakageConfig,
    app: str,
) -> Dict[str, Any]:
    rows_seen = 0
    bytes_seen = 0
    target_counter: Counter = Counter()
    schema_cols: Optional[List[str]] = None

    for fp in tqdm(shard_files, desc=f"PHASE 10 scan app={app}", unit="shard", dynamic_ncols=True):
        bytes_seen += _file_size_bytes(fp)
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        rows_seen += int(len(df))
        if schema_cols is None:
            schema_cols = list(df.columns)

        y = _target_series(df, cfg.target_col)
        target_counter.update(y.astype(int).tolist())

        if cfg.gc_each_shard:
            del df
            gc.collect()

    return {
        "rows_seen": int(rows_seen),
        "bytes_seen": int(bytes_seen),
        "target_counts": target_counter,
        "schema_cols": schema_cols or [],
    }


def _collect_sample_from_shards(
    shard_files: List[Path],
    *,
    cfg: Phase10CorrelationLeakageConfig,
    app: str,
    target_counts: Counter,
) -> pd.DataFrame:
    n_take = max(0, int(cfg.n_sample))
    if n_take <= 0:
        return pd.DataFrame()

    if cfg.sample_mode == "random":
        sampler = _ReservoirSampler(n_take, seed=int(cfg.sample_seed) + abs(hash(app)) % 10_000)
        for fp in tqdm(shard_files, desc=f"PHASE 10 sample app={app}", unit="shard", dynamic_ncols=True):
            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is None or df.empty:
                continue
            sampler.add(df)
            if cfg.gc_each_shard:
                del df
                gc.collect()
        return sampler.dataframe()

    # Default: balanced by Target.
    if cfg.sample_mode == "stratified_proportional":
        plan = _sample_plan_proportional(target_counts, n_take)
    else:
        plan = _sample_plan_balanced(target_counts, n_take)

    samplers = {
        int(k): _ReservoirSampler(v, seed=int(cfg.sample_seed) + int(k) * 31 + abs(hash(app)) % 10_000)
        for k, v in plan.items()
    }

    for fp in tqdm(shard_files, desc=f"PHASE 10 sample app={app}", unit="shard", dynamic_ncols=True):
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        y = _target_series(df, cfg.target_col)
        for cls, sampler in samplers.items():
            sub = df[y == int(cls)]
            if not sub.empty:
                sampler.add(sub)

        if cfg.gc_each_shard:
            del df
            gc.collect()

    parts = [s.dataframe() for s in samplers.values() if not s.dataframe().empty]
    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=cfg.sample_seed).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=cfg.sample_seed).reset_index(drop=True)

    return out


# =============================================================================
# Correlation/leakage logic
# =============================================================================

def _safe_corr_numeric(x: pd.Series, y: pd.Series) -> float:
    """
    Compute Pearson correlation without emitting numpy RuntimeWarning when a
    column is constant/single-valued. Returns NaN when correlation is undefined.
    """
    x = _to_numeric_safe(x).astype(float)
    y = _to_numeric_safe(y).astype(float)

    if len(x) == 0 or len(y) == 0:
        return float("nan")
    if x.nunique(dropna=True) <= 1 or y.nunique(dropna=True) <= 1:
        return float("nan")

    sx = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    sy = float(y.std(ddof=1)) if len(y) > 1 else 0.0
    if sx == 0.0 or sy == 0.0 or not np.isfinite(sx) or not np.isfinite(sy):
        return float("nan")

    with np.errstate(divide="ignore", invalid="ignore"):
        val = x.corr(y)
    return float(val) if pd.notna(val) and np.isfinite(val) else float("nan")


def _compute_corr_table(
    df_in: pd.DataFrame,
    target_col: str,
    cols: List[str],
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], List[str]]:
    nan_issues: List[Dict[str, Any]] = []
    valid_cols: List[str] = []

    target_data = _to_numeric_safe(df_in[target_col]).astype(float)
    target_const = target_data.nunique(dropna=True) <= 1

    for col in cols:
        if col not in df_in.columns:
            continue

        col_data = _to_numeric_safe(df_in[col]).astype(float)

        raw_num = pd.to_numeric(df_in[col], errors="coerce")
        nulls = int(raw_num.isna().sum())
        try:
            infs = int(np.isinf(raw_num.fillna(0)).sum())
        except Exception:
            infs = 0
        uniq = int(col_data.nunique(dropna=True))
        std_val = float(col_data.std()) if len(col_data) else 0.0
        const = std_val == 0.0 or uniq <= 1

        # Avoid pandas/numpy corr() when correlation is mathematically undefined.
        if target_const:
            issue = "TARGET_CONSTANT"
            is_nan = True
        elif nulls == len(df_in):
            issue = "ALL_NULL"
            is_nan = True
        elif const:
            issue = "CONSTANT_OR_SINGLE"
            is_nan = True
        elif infs > 0:
            issue = "INFINITY_VALUES"
            is_nan = True
        elif nulls > len(df_in) * 0.5:
            issue = "MOSTLY_NULL"
            is_nan = True
        else:
            corr_val = _safe_corr_numeric(col_data, target_data)
            is_nan = pd.isna(corr_val)
            issue = "UNKNOWN" if is_nan else ""

        if is_nan:
            nan_issues.append({
                "Feature": str(col),
                "Issue": issue,
                "Null_Count": int(nulls),
                "Inf_Count": int(infs),
                "Unique_Values": int(uniq),
                "Std_Dev": float(std_val),
                "Min": float(col_data.min()) if len(col_data) else 0.0,
                "Max": float(col_data.max()) if len(col_data) else 0.0,
            })
        else:
            valid_cols.append(str(col))

    correlations: List[Dict[str, Any]] = []
    for col in valid_cols:
        try:
            col_data = _to_numeric_safe(df_in[col]).astype(float)
            corr_val = _safe_corr_numeric(col_data, target_data)
            if pd.isna(corr_val):
                corr_val = 0.0
            correlations.append({
                "Feature": str(col),
                "Correlation": float(corr_val),
                "Abs_Corr": float(abs(corr_val)),
            })
        except Exception:
            correlations.append({
                "Feature": str(col),
                "Correlation": 0.0,
                "Abs_Corr": 0.0,
            })

    if not correlations:
        corr_df = pd.DataFrame(columns=["Feature", "Correlation", "Abs_Corr"])
    else:
        corr_df = pd.DataFrame(correlations).sort_values("Abs_Corr", ascending=False)

    return corr_df, nan_issues, valid_cols

def _detect_leakage_cols(df: pd.DataFrame, leakage_cols: Sequence[str], target_col: str) -> List[str]:
    present = []
    for c in leakage_cols:
        if c in df.columns and c != target_col:
            present.append(c)

    # Pattern-based guard for newly-added label/evidence fields.
    prefixes = (
        "alert_",
        "label_",
        "evidence_",
        "probe_",
    )
    exact = {
        "event_type",
        "event_type_h",
        "event_type_raw",
        "has_alert",
        "is_possible_probe",
        "is_probe_suspicious",
        "Target_prelim",
        "target_prelim_malicious_count",
        "window_start",
        "window_start_h",
    }

    for c in df.columns:
        if c == target_col:
            continue
        cs = str(c)
        if cs in exact or cs.startswith(prefixes):
            if cs not in present:
                present.append(cs)

    return present


def _effective_leakage_cols(cfg: Phase10CorrelationLeakageConfig) -> Tuple[str, ...]:
    """
    Build the leakage/drop column list used by both disk and RAM mode.

    Important: pipeline.py may pass a custom leakage_cols tuple. We still union
    it with DEFAULT_LEAKAGE_COLS so old baseline leakage fields such as
    event_type/has_alert/alert_* are not accidentally lost.
    """
    out: List[str] = []

    def add_many(values: Sequence[str]) -> None:
        for v in values or ():
            x = str(v).strip()
            if x and x not in out:
                out.append(x)

    add_many(DEFAULT_LEAKAGE_COLS)
    add_many(getattr(cfg, "leakage_cols", ()) or ())
    add_many(getattr(cfg, "extra_drop_cols", ()) or ())

    if bool(getattr(cfg, "strict_leakage_guard", True)):
        if bool(getattr(cfg, "drop_alert_derived_features", True)):
            add_many((
                "has_alert", "alert_category", "alert_category_h", "alert_severity",
                "alert_signature", "alert_signature_h", "alert_signature_id",
                "alert_count_window", "target_prelim_malicious_count",
            ))
        if bool(getattr(cfg, "drop_label_explanation_features", True)):
            add_many((
                "Target_prelim", "label_status", "label_status_h",
                "label_status_final", "label_status_final_h", "label_source",
                "label_source_h", "label_reason", "label_reason_h",
                "label_confidence", "evidence_alert", "evidence_compromised_ip",
                "evidence_probe",
            ))
        if bool(getattr(cfg, "drop_probe_direct_features", True)):
            add_many((
                "probe_score", "is_possible_probe", "is_probe_suspicious",
                "probe_reason", "probe_reason_h", "window_start", "window_start_h",
            ))

    return tuple(out)


# =============================================================================
# Public API
# =============================================================================

def phase10_correlation_leakage_for_app(
    app: str,
    *,
    cfg: Phase10CorrelationLeakageConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    app = str(app).strip().lower()
    tag = cfg.filename_tag.strip() or "run"
    t0 = datetime.now()

    shard_files = _list_app_shards(cfg.input_dir, app)
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    corr_all_csv = out_app_dir / f"corr_df_ALL_{app}_{tag}.csv"
    corr_noleak_csv = out_app_dir / f"corr_df_NOLEAK_{app}_{tag}.csv"
    issues_json = out_app_dir / f"nan_issues_{app}_{tag}.json"
    drop_json = out_app_dir / f"features_to_drop_{app}_{tag}.json"
    meta_json = out_app_dir / f"phase10_meta_{app}_{tag}.json"
    top_all_png = out_app_dir / f"top_features_correlation_ALL_{app}_{tag}.png"
    top_noleak_png = out_app_dir / f"top_features_correlation_NOLEAK_{app}_{tag}.png"
    feat_txt = out_app_dir / f"features_phase10_{app}_{tag}.txt"
    feat_json = out_app_dir / f"features_phase10_{app}_{tag}.json"

    if not shard_files:
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_no_input_shards",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": 0,
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return pd.DataFrame(), summary

    if (not cfg.force_rebuild) and corr_all_csv.exists() and meta_json.exists():
        try:
            corr_df = pd.read_csv(corr_all_csv)
        except Exception:
            corr_df = pd.DataFrame()
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_existing_outputs",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "corr_all_csv": str(corr_all_csv),
            "corr_noleak_csv": str(corr_noleak_csv) if corr_noleak_csv.exists() else None,
            "meta_json": str(meta_json),
            "drop_json": str(drop_json) if drop_json.exists() else None,
            "top_k": int(cfg.top_k),
            "topk_all": corr_df.head(cfg.top_k).to_dict(orient="records") if not corr_df.empty else [],
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return corr_df, summary

    print(f"\n⚪ PHASE 10: Correlation + leakage analysis for app={app}")
    print(f"   Input shards : {len(shard_files):,}")
    print(f"   Output       : {out_app_dir}")

    scan = _scan_shards_for_counts(shard_files, cfg=cfg, app=app)

    if int(scan["rows_seen"]) <= 0:
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_empty_input",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": 0,
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return pd.DataFrame(), summary

    df_in = _collect_sample_from_shards(
        shard_files,
        cfg=cfg,
        app=app,
        target_counts=scan["target_counts"],
    )

    if df_in.empty:
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_empty_sample",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": int(scan["rows_seen"]),
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return df_in, summary

    if cfg.target_col not in df_in.columns:
        raise RuntimeError(f"Target column missing in Phase 10 sample for app={app}: {cfg.target_col}")

    df_in[cfg.target_col] = _target_series(df_in, cfg.target_col)

    target_dist_sample = {
        str(k): int(v)
        for k, v in df_in[cfg.target_col].value_counts(dropna=False).to_dict().items()
    }

    if df_in[cfg.target_col].nunique(dropna=True) <= 1:
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_constant_target_sample",
            "input_dir": str(cfg.input_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": int(scan["rows_seen"]),
            "sample_rows": int(len(df_in)),
            "target_counts_input": _counter_to_str_dict(scan["target_counts"]),
            "target_counts_sample": target_dist_sample,
            "note": "Correlation with Target is undefined because sampled Target has one class only.",
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, out_app_dir / f"phase10_meta_{app}_{tag}.json")
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return df_in, summary

    leakage_present = _detect_leakage_cols(df_in, _effective_leakage_cols(cfg), cfg.target_col)

    numeric_features = df_in.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    if cfg.target_col in numeric_features:
        numeric_features.remove(cfg.target_col)

    corr_all, nan_issues, valid_cols = _compute_corr_table(df_in, cfg.target_col, numeric_features)

    numeric_noleak = [c for c in numeric_features if c not in set(leakage_present)]
    corr_noleak, nan_issues_noleak, valid_noleak = _compute_corr_table(df_in, cfg.target_col, numeric_noleak)

    # Features to drop = explicit leakage + invalid correlation features.
    features_to_drop: List[str] = []

    for c in leakage_present:
        if c not in features_to_drop:
            features_to_drop.append(c)

    for issue in nan_issues:
        feat = str(issue.get("Feature", ""))
        if feat and feat not in features_to_drop:
            features_to_drop.append(feat)

    corr_all.to_csv(corr_all_csv, index=False)
    corr_noleak.to_csv(corr_noleak_csv, index=False)
    _json_dump(nan_issues, issues_json)
    _json_dump(features_to_drop, drop_json)

    _plot_topk(
        corr_all,
        cfg.top_k,
        top_all_png,
        title=f"{app.upper()} - Top {cfg.top_k} Correlation with Target (INCLUDING leakage)",
    )
    _plot_topk(
        corr_noleak,
        cfg.top_k,
        top_noleak_png,
        title=f"{app.upper()} - Top {cfg.top_k} Correlation with Target (NO leakage cols)",
    )

    all_features = [str(c) for c in df_in.columns.tolist()]
    numeric_cols = df_in.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    non_numeric_cols = [c for c in all_features if c not in set(numeric_cols)]

    feat_txt.write_text("\n".join(all_features), encoding="utf-8")
    _json_dump(
        {
            "app": app,
            "total_columns": int(len(all_features)),
            "numeric_columns": int(len(numeric_cols)),
            "non_numeric_columns": int(len(non_numeric_cols)),
            "features": all_features,
            "numeric_features": numeric_cols,
            "non_numeric_features": non_numeric_cols,
            "leakage_present": leakage_present,
            "features_to_drop_for_modeling": features_to_drop,
        },
        feat_json,
    )

    elapsed = (datetime.now() - t0).total_seconds()

    meta = {
        "phase": 10,
        "app": app,
        "status": "completed",
        "input_dir": str(cfg.input_dir),
        "output_dir": str(out_app_dir),
        "rows_seen": int(scan["rows_seen"]),
        "input_bytes": int(scan["bytes_seen"]),
        "input_size": _human_bytes(scan["bytes_seen"]),
        "sample_rows": int(len(df_in)),
        "sample_mode": cfg.sample_mode,
        "sample_seed": int(cfg.sample_seed),
        "target_counts_input": _counter_to_str_dict(scan["target_counts"]),
        "target_counts_sample": target_dist_sample,
        "numeric_features_total_all": int(len(numeric_features)),
        "numeric_features_total_noleak": int(len(numeric_noleak)),
        "valid_features_all": int(len(valid_cols)),
        "valid_features_noleak": int(len(valid_noleak)),
        "nan_issues_count": int(len(nan_issues)),
        "leakage_present": leakage_present,
        "leakage_present_count": int(len(leakage_present)),
        "features_to_drop_for_modeling": features_to_drop,
        "features_to_drop_count": int(len(features_to_drop)),
        "leakage_policy": {
            "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
            "drop_probe_direct_features": bool(getattr(cfg, "drop_probe_direct_features", True)),
            "drop_label_explanation_features": bool(getattr(cfg, "drop_label_explanation_features", True)),
            "drop_alert_derived_features": bool(getattr(cfg, "drop_alert_derived_features", True)),
            "effective_leakage_cols_count": int(len(_effective_leakage_cols(cfg))),
        },
        "top_k": int(cfg.top_k),
        "topk_all": corr_all.head(cfg.top_k).to_dict(orient="records"),
        "topk_noleak": corr_noleak.head(cfg.top_k).to_dict(orient="records"),
        "corr_all_csv": str(corr_all_csv),
        "corr_noleak_csv": str(corr_noleak_csv),
        "issues_json": str(issues_json),
        "drop_json": str(drop_json),
        "top_all_png": str(top_all_png) if top_all_png.exists() else None,
        "top_noleak_png": str(top_noleak_png) if top_noleak_png.exists() else None,
        "features_txt": str(feat_txt),
        "features_json": str(feat_json),
        "generated_at": datetime.now().isoformat(),
        "seconds": float(elapsed),
        "note": (
            "Phase 10 diagnoses correlation and leakage per application. "
            "features_to_drop should be used by Phase 11/12 before modeling."
        ),
    }

    _json_dump(meta, meta_json)
    _json_dump(meta, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")

    print(f"✅ Phase 10 complete app={app}")
    print(f"   Sample rows       : {len(df_in):,}")
    print(f"   Target sample     : {target_dist_sample}")
    print(f"   Leakage present   : {len(leakage_present):,}")
    print(f"   Features to drop  : {len(features_to_drop):,}")
    print(f"   corr ALL          : {corr_all_csv}")
    print(f"   corr NOLEAK       : {corr_noleak_csv}")
    print(f"   Time              : {elapsed/60:.2f} minutes")

    return corr_all, meta


def phase10_correlation_leakage(
    *,
    cfg: Phase10CorrelationLeakageConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    print("\n" + "⚪ " + "=" * 76)
    print("PHASE 10: CORRELATION + LEAKAGE ANALYSIS (APP-AWARE)")
    print("⚪ " + "=" * 76)

    t0 = datetime.now()

    corr_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        corr_df, summary = phase10_correlation_leakage_for_app(app_norm, cfg=cfg)
        corr_by_app[app_norm] = corr_df
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        rows.append({
            "app": app,
            "status": s.get("status"),
            "rows_seen": int(s.get("rows_seen", 0)),
            "sample_rows": int(s.get("sample_rows", 0)),
            "numeric_features_total_all": int(s.get("numeric_features_total_all", 0)),
            "numeric_features_total_noleak": int(s.get("numeric_features_total_noleak", 0)),
            "valid_features_all": int(s.get("valid_features_all", 0)),
            "valid_features_noleak": int(s.get("valid_features_noleak", 0)),
            "leakage_present_count": int(s.get("leakage_present_count", 0)),
            "features_to_drop_count": int(s.get("features_to_drop_count", 0)),
            "corr_all_csv": s.get("corr_all_csv"),
            "corr_noleak_csv": s.get("corr_noleak_csv"),
            "drop_json": s.get("drop_json"),
            "seconds": float(s.get("seconds", 0.0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase10_correlation_leakage_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()
    total_rows_seen = int(sum(int(s.get("rows_seen", 0)) for s in summaries.values()))

    summary_all = {
        "phase": 10,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "input_dir": str(cfg.input_dir),
        "output_dir": str(cfg.output_dir),
        "total_rows_seen": total_rows_seen,
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Phase 10 is app-aware and reads Phase 7 clean app partitions. "
            "Its features_to_drop artifacts are intended for Phase 11 modeling split."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase10_correlation_leakage_summary_all.json")

    print("\n✅ PHASE 10 COMPLETE")
    print(f"   Total rows seen: {total_rows_seen:,}")
    print(f"   Output dir     : {cfg.output_dir}")
    print(f"   Time           : {elapsed/60:.2f} minutes")

    return corr_by_app, summary_all



# =============================================================================
# RAM MODE API (SMALL DATASET / PER-APP PIPELINE)
# =============================================================================

def _sample_df_for_phase10_ram(
    df: pd.DataFrame,
    *,
    target_col: str,
    n_sample: int,
    sample_mode: str,
    seed: int,
) -> pd.DataFrame:
    """Bounded in-RAM sample for correlation/leakage analysis."""
    if df is None or df.empty:
        return pd.DataFrame()

    n_take = max(0, int(n_sample))
    if n_take <= 0 or len(df) <= n_take:
        return df.copy().reset_index(drop=True)

    rng = np.random.default_rng(int(seed))
    y = _target_series(df, target_col)
    counts = Counter(y.astype(int).tolist())

    mode = str(sample_mode or "stratified_balanced").strip().lower()
    if mode == "random" or len(counts) <= 1:
        idx = rng.choice(len(df), size=n_take, replace=False)
        return df.iloc[idx].copy().reset_index(drop=True)

    if mode == "stratified_proportional":
        plan = _sample_plan_proportional(counts, n_take)
    else:
        plan = _sample_plan_balanced(counts, n_take)

    parts: List[pd.DataFrame] = []
    for cls, need in plan.items():
        sub = df.loc[y == int(cls)]
        if sub.empty or int(need) <= 0:
            continue
        take = min(int(need), len(sub))
        parts.append(sub.sample(n=take, random_state=int(rng.integers(0, 2_147_483_647))).copy())

    if not parts:
        idx = rng.choice(len(df), size=n_take, replace=False)
        return df.iloc[idx].copy().reset_index(drop=True)

    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=int(seed)).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=int(seed)).reset_index(drop=True)
    return out


def phase10_correlation_leakage_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase10CorrelationLeakageConfig] = None,
    output_dir: Optional[Path] = None,
    target_col: Optional[str] = None,
    n_sample: Optional[int] = None,
    top_k: Optional[int] = None,
    sample_mode: Optional[str] = None,
    sample_seed: Optional[int] = None,
    leakage_cols: Optional[Sequence[str]] = None,
    filename_tag: Optional[str] = None,
    progress_desc: str = "PHASE 10",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    RAM-mode Phase 10 for one active application.

    Input:
      df_clean from Phase 7 RAM mode.

    Output:
      corr_all DataFrame and metadata summary. Small artifacts are still written
      because Phase 11/modeling/report need features_to_drop and correlation tables,
      but this function does not read or write Parquet dataset checkpoints.
    """
    t0 = datetime.now()
    app = str(app).strip().lower()

    if cfg is None:
        cfg = Phase10CorrelationLeakageConfig(selected_apps=(app,))

    target_col = str(target_col or cfg.target_col)
    n_sample = int(n_sample if n_sample is not None else cfg.n_sample)
    top_k = int(top_k if top_k is not None else cfg.top_k)
    sample_mode = str(sample_mode or cfg.sample_mode)
    sample_seed = int(sample_seed if sample_seed is not None else cfg.sample_seed)
    if leakage_cols is None:
        leakage_cols = _effective_leakage_cols(cfg)
    else:
        # Do not let a caller override away DEFAULT_LEAKAGE_COLS by accident.
        _tmp: List[str] = []
        for _v in list(DEFAULT_LEAKAGE_COLS) + list(leakage_cols):
            _x = str(_v).strip()
            if _x and _x not in _tmp:
                _tmp.append(_x)
        leakage_cols = tuple(_tmp)
    tag = str(filename_tag or cfg.filename_tag or "run").strip() or "run"
    out_base = Path(output_dir) if output_dir is not None else Path(cfg.output_dir)

    out_app_dir = out_base / f"app={app}"
    metrics_dir = out_base / "metrics"
    out_app_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    corr_all_csv = out_app_dir / f"corr_df_ALL_{app}_{tag}.csv"
    corr_noleak_csv = out_app_dir / f"corr_df_NOLEAK_{app}_{tag}.csv"
    issues_json = out_app_dir / f"nan_issues_{app}_{tag}.json"
    drop_json = out_app_dir / f"features_to_drop_{app}_{tag}.json"
    meta_json = out_app_dir / f"phase10_meta_{app}_{tag}.json"
    top_all_png = out_app_dir / f"top_features_correlation_ALL_{app}_{tag}.png"
    top_noleak_png = out_app_dir / f"top_features_correlation_NOLEAK_{app}_{tag}.png"
    feat_txt = out_app_dir / f"features_phase10_{app}_{tag}.txt"
    feat_json = out_app_dir / f"features_phase10_{app}_{tag}.json"

    print(f"\n⚪ {progress_desc}: CORRELATION + LEAKAGE RAM MODE app={app}")

    if df_clean is None or df_clean.empty:
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_empty_input",
            "mode": "ram_per_app",
            "rows_seen": 0,
            "sample_rows": 0,
            "features_to_drop_for_modeling": [],
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return pd.DataFrame(), summary

    if target_col not in df_clean.columns:
        raise RuntimeError(f"Target column missing in Phase 10 RAM input for app={app}: {target_col}")

    rows_seen = int(len(df_clean))
    input_memory_bytes = int(df_clean.memory_usage(deep=True).sum())
    y_full = _target_series(df_clean, target_col)
    target_counts_input = Counter(y_full.astype(int).tolist())

    df_in = _sample_df_for_phase10_ram(
        df_clean,
        target_col=target_col,
        n_sample=n_sample,
        sample_mode=sample_mode,
        seed=sample_seed + abs(hash(app)) % 100_000,
    )

    if df_in.empty:
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_empty_sample",
            "mode": "ram_per_app",
            "rows_seen": rows_seen,
            "sample_rows": 0,
            "target_counts_input": _counter_to_str_dict(target_counts_input),
            "features_to_drop_for_modeling": [],
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return df_in, summary

    df_in = df_in.copy()
    df_in[target_col] = _target_series(df_in, target_col)
    target_dist_sample = {str(k): int(v) for k, v in df_in[target_col].value_counts(dropna=False).to_dict().items()}

    leakage_present = _detect_leakage_cols(df_in, leakage_cols, target_col)
    numeric_features = df_in.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    if target_col in numeric_features:
        numeric_features.remove(target_col)

    if df_in[target_col].nunique(dropna=True) <= 1:
        features_to_drop = list(dict.fromkeys(leakage_present))
        _json_dump(features_to_drop, drop_json)
        summary = {
            "phase": 10,
            "app": app,
            "status": "skipped_constant_target_sample",
            "mode": "ram_per_app",
            "output_dir": str(out_app_dir),
            "rows_seen": rows_seen,
            "sample_rows": int(len(df_in)),
            "target_counts_input": _counter_to_str_dict(target_counts_input),
            "target_counts_sample": target_dist_sample,
            "leakage_present": leakage_present,
            "features_to_drop_for_modeling": features_to_drop,
            "features_to_drop_count": int(len(features_to_drop)),
            "drop_json": str(drop_json),
            "note": "Correlation with Target is undefined because sampled Target has one class only.",
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, meta_json)
        _json_dump(summary, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")
        return df_in, summary

    corr_all, nan_issues, valid_cols = _compute_corr_table(df_in, target_col, numeric_features)
    numeric_noleak = [c for c in numeric_features if c not in set(leakage_present)]
    corr_noleak, nan_issues_noleak, valid_noleak = _compute_corr_table(df_in, target_col, numeric_noleak)

    features_to_drop: List[str] = []
    for c in leakage_present:
        if c not in features_to_drop:
            features_to_drop.append(c)
    for issue in nan_issues:
        feat = str(issue.get("Feature", ""))
        if feat and feat not in features_to_drop:
            features_to_drop.append(feat)

    corr_all.to_csv(corr_all_csv, index=False)
    corr_noleak.to_csv(corr_noleak_csv, index=False)
    _json_dump(nan_issues, issues_json)
    _json_dump(features_to_drop, drop_json)

    _plot_topk(corr_all, top_k, top_all_png, title=f"{app.upper()} - Top {top_k} Correlation with Target (INCLUDING leakage)")
    _plot_topk(corr_noleak, top_k, top_noleak_png, title=f"{app.upper()} - Top {top_k} Correlation with Target (NO leakage cols)")

    all_features = [str(c) for c in df_in.columns.tolist()]
    numeric_cols = df_in.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    non_numeric_cols = [c for c in all_features if c not in set(numeric_cols)]
    feat_txt.write_text("\n".join(all_features), encoding="utf-8")
    _json_dump(
        {
            "app": app,
            "total_columns": int(len(all_features)),
            "numeric_columns": int(len(numeric_cols)),
            "non_numeric_columns": int(len(non_numeric_cols)),
            "features": all_features,
            "numeric_features": numeric_cols,
            "non_numeric_features": non_numeric_cols,
            "leakage_present": leakage_present,
            "features_to_drop_for_modeling": features_to_drop,
        },
        feat_json,
    )

    elapsed = (datetime.now() - t0).total_seconds()
    meta = {
        "phase": 10,
        "app": app,
        "status": "completed",
        "mode": "ram_per_app",
        "output_dir": str(out_app_dir),
        "rows_seen": rows_seen,
        "input_memory_bytes": int(input_memory_bytes),
        "input_memory_mib": float(input_memory_bytes / (1024.0 ** 2)),
        "sample_rows": int(len(df_in)),
        "sample_mode": sample_mode,
        "sample_seed": int(sample_seed),
        "target_counts_input": _counter_to_str_dict(target_counts_input),
        "target_counts_sample": target_dist_sample,
        "numeric_features_total_all": int(len(numeric_features)),
        "numeric_features_total_noleak": int(len(numeric_noleak)),
        "valid_features_all": int(len(valid_cols)),
        "valid_features_noleak": int(len(valid_noleak)),
        "nan_issues_count": int(len(nan_issues)),
        "leakage_present": leakage_present,
        "leakage_present_count": int(len(leakage_present)),
        "features_to_drop_for_modeling": features_to_drop,
        "features_to_drop_count": int(len(features_to_drop)),
        "leakage_policy": {
            "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
            "drop_probe_direct_features": bool(getattr(cfg, "drop_probe_direct_features", True)),
            "drop_label_explanation_features": bool(getattr(cfg, "drop_label_explanation_features", True)),
            "drop_alert_derived_features": bool(getattr(cfg, "drop_alert_derived_features", True)),
            "effective_leakage_cols_count": int(len(leakage_cols)),
        },
        "top_k": int(top_k),
        "topk_all": corr_all.head(top_k).to_dict(orient="records"),
        "topk_noleak": corr_noleak.head(top_k).to_dict(orient="records"),
        "corr_all_csv": str(corr_all_csv),
        "corr_noleak_csv": str(corr_noleak_csv),
        "issues_json": str(issues_json),
        "drop_json": str(drop_json),
        "top_all_png": str(top_all_png) if top_all_png.exists() else None,
        "top_noleak_png": str(top_noleak_png) if top_noleak_png.exists() else None,
        "features_txt": str(feat_txt),
        "features_json": str(feat_json),
        "generated_at": datetime.now().isoformat(),
        "seconds": float(elapsed),
        "note": (
            "RAM-mode Phase 10 diagnoses correlation/leakage directly from df_clean. "
            "Only small artifacts are written; no parquet dataset checkpoint is read or written."
        ),
    }

    _json_dump(meta, meta_json)
    _json_dump(meta, metrics_dir / f"phase10_correlation_leakage_summary_{app}.json")

    print(f"✅ Phase 10 RAM complete app={app}")
    print(f"   Rows/sample      : {rows_seen:,} / {len(df_in):,}")
    print(f"   Target sample    : {target_dist_sample}")
    print(f"   Leakage present  : {len(leakage_present):,}")
    print(f"   Features to drop : {len(features_to_drop):,}")
    print(f"   Time             : {elapsed/60:.2f} minutes")

    gc.collect()
    return corr_all, meta


# RAM-mode aliases for pipeline compatibility.
def phase10_correlation_leakage_in_memory(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase10CorrelationLeakageConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase10_correlation_leakage_ram(df_clean, app=app, cfg=cfg, **kwargs)


def phase10_correlation_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase10CorrelationLeakageConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase10_correlation_leakage_ram(df_clean, app=app, cfg=cfg, **kwargs)


def run_phase10_correlation_leakage_ram(
    df_clean: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase10CorrelationLeakageConfig] = None,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase10_correlation_leakage_ram(df_clean, app=app, cfg=cfg, **kwargs)

# Compatibility alias.
def build_phase10_correlation_leakage(
    *,
    cfg: Phase10CorrelationLeakageConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase10_correlation_leakage(cfg=cfg)


if __name__ == "__main__":
    corr, summary = phase10_correlation_leakage(
        cfg=Phase10CorrelationLeakageConfig(
            input_dir=Path("results/phase7_clean_dataset"),
            output_dir=Path("results/phase10_correlation_leakage"),
            selected_apps=("dns", "http", "tls", "ssh"),
            target_col="Target",
            n_sample=1_000_000,
            top_k=15,
            sample_mode="stratified_balanced",
            sample_seed=42,
            filename_tag="run",
            force_rebuild=False,
            parquet_engine="fastparquet",
        )
    )
    print(json.dumps(summary, indent=2, default=str))
