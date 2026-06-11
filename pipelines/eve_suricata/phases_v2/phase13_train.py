# src/cbr/phases/phase13_train.py
from __future__ import annotations

import gc
import json
import os
import shutil
import time
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

# -------------------------------------------------------------------------
# CPU / Thread defaults
# -------------------------------------------------------------------------
_LOGICAL_CPU = max(1, os.cpu_count() or 8)
_RESERVED_THREADS = 2 if _LOGICAL_CPU >= 8 else 1
_WORKER_THREADS = max(1, _LOGICAL_CPU - _RESERVED_THREADS)
_INNER_MATH_THREADS = 1

os.environ.setdefault("OMP_NUM_THREADS", str(_INNER_MATH_THREADS))
os.environ.setdefault("OPENBLAS_NUM_THREADS", str(_INNER_MATH_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(_INNER_MATH_THREADS))
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", str(_INNER_MATH_THREADS))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(_INNER_MATH_THREADS))

from sklearn.base import clone
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier

try:
    from xgboost import XGBClassifier  # type: ignore
except Exception:
    XGBClassifier = None

try:
    import joblib  # type: ignore
except Exception:
    joblib = None

try:
    from threadpoolctl import threadpool_limits  # type: ignore
except Exception:
    threadpool_limits = None


# =============================================================================
# PHASE 13: TRAINING (APP-AWARE, DISK-BACKED INPUT, BOUNDED RAM)
# =============================================================================
# Purpose:
#   Train/evaluate models per application after Phase 11 split and Phase 12 FS.
#
# Input:
#   results/modeling/app={app}/train/part-*.parquet
#   results/modeling/app={app}/test/part-*.parquet
#   results/phase12_fs/app={app}/phase12_feature_sets_{app}_{tag}.json
#
# Output:
#   results/phase13_train/app={app}/
#     results_comparison_{app}_{tag}.csv
#     phase13_summary_{app}_{tag}.json
#     phase13_<idx><MODEL>_summary_{app}_{tag}.json
#     checkpoints/...
#
#   results/phase13_train/metrics/
#     phase13_train_summary_{app}.json
#     phase13_train_summary_all.json
#     phase13_train_summary_by_app.csv
#
# Important:
#   - This phase no longer receives df_train/df_test as required input.
#   - This phase reads bounded train/test samples from per-app shards.
#   - KNN is intentionally disabled by default because it is impractical for
#     large-scale data in this project.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")
DEFAULT_MODELS: Tuple[str, ...] = ("DT", "RFC", "LSVC", "XGB")
DEFAULT_METHODS: Tuple[str, ...] = ("MI", "RFE", "PCA")

# Final training-time guard for AIRC / leakage-aware reporting.
# Phase 10-12 should already remove these, but Phase 13 must fail safe.
DEFAULT_TRAINING_FORBIDDEN_COLS: Tuple[str, ...] = (
    "has_alert",
    "is_malicious",
    "event_type",
    "event_type_h",
    "event_type_raw",
    "Target_prelim",
    "target_prelim_malicious_count",
    "label_status",
    "label_status_h",
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
    "probe_score",
    "is_possible_probe",
    "is_probe_suspicious",
    "probe_reason",
    "probe_reason_h",
    "alert_count_window",
    "window_start",
    "window_start_h",
    "src_ip",
    "dest_ip",
    "timestamp",
    "flow_id",
    "community_id",
)

DEFAULT_TRAINING_FORBIDDEN_PREFIXES: Tuple[str, ...] = (
    "event_type",
    "alert_",
    "label_",
    "evidence_",
    "probe_",
    "target_prelim",
)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Phase13TrainConfig:
    modeling_dir: Path = Path("results/modeling")
    phase12_dir: Path = Path("results/phase12_fs")
    output_dir: Path = Path("results/phase13_train")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    target_col: str = "Target"
    seed: int = 42
    filename_tag: str = "run"

    methods: Tuple[str, ...] = DEFAULT_METHODS
    models: Tuple[str, ...] = DEFAULT_MODELS

    # CV / holdout
    default_n_splits: int = 2
    do_holdout_eval: bool = True

    # Bounded RAM samples from Phase 11 shards.
    # 0 or None means load all rows from shards. Use carefully.
    train_rows: Optional[int] = 800_000
    test_rows: Optional[int] = 200_000
    sample_mode: str = "stratified_proportional"  # "stratified_balanced" | "stratified_proportional" | "random"

    # AIRC leakage-aware final guard.
    # This is intentionally duplicated from Phase 10-12 because Phase 13 is the
    # final boundary before model fitting.
    strict_leakage_guard: bool = True
    forbidden_feature_cols: Tuple[str, ...] = DEFAULT_TRAINING_FORBIDDEN_COLS
    forbidden_feature_prefixes: Tuple[str, ...] = DEFAULT_TRAINING_FORBIDDEN_PREFIXES

    # Reporting / model selection. "holdout_first" uses holdout_f1_attack then
    # holdout_auc when available; otherwise it falls back to CV F1.
    best_model_policy: str = "holdout_first"
    suspicious_score_threshold: float = 0.999

    # Model knobs
    rfc_estimators: int = 100
    rfc_n_jobs: int = _WORKER_THREADS
    rfc_max_depth: Optional[int] = 16
    rfc_min_samples_leaf: int = 2

    lsvc_c: float = 1.0
    lsvc_max_iter: int = 5_000
    lsvc_dual: str = "auto"

    xgb_n_estimators: int = 300
    xgb_max_depth: int = 8
    xgb_learning_rate: float = 0.1
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_lambda: float = 1.0
    xgb_n_jobs: int = _WORKER_THREADS
    xgb_tree_method: str = "hist"
    xgb_device: str = "cpu"
    xgb_eval_metric: str = "logloss"

    pca_default_n_components: int = 20

    # Stability / artifacts
    blas_thread_limit: int = _INNER_MATH_THREADS
    cooldown_seconds: float = 0.0
    gc_each_fold: bool = True

    write_artifacts: bool = True
    save_fitted_models: bool = False
    resume_enabled: bool = True
    checkpoint_each_fold: bool = True

    parquet_engine: Optional[str] = "fastparquet"
    overwrite: bool = False


# =============================================================================
# Helpers
# =============================================================================

def _json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)


def _json_load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(max(0, int(n)))
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{x:.2f} B"


def _fmt_elapsed(seconds: float) -> str:
    s = int(round(float(seconds)))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _clean_dir(path: Path) -> None:
    if not path.exists():
        return
    for fp in path.glob("*"):
        try:
            if fp.is_file():
                fp.unlink()
            elif fp.is_dir():
                shutil.rmtree(fp)
        except Exception:
            pass


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.replace([np.inf, -np.inf], np.nan).fillna(0)


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        raise RuntimeError(f"Missing target column: {target_col}")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


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


def _list_split_shards(modeling_dir: Path, app: str, split: str) -> List[Path]:
    app = str(app).strip().lower()
    split = str(split).strip().lower()
    dirs = [
        Path(modeling_dir) / f"app={app}" / split,
        Path(modeling_dir) / app / split,
    ]

    files: List[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for pat in ("part-*.parquet", "part-*.csv.gz", "part-*.csv", "*.parquet", "*.csv.gz", "*.csv"):
            files.extend(sorted(d.glob(pat)))
    return sorted(set(files))


def _counter_to_str_dict(c: Counter) -> Dict[str, int]:
    return {str(k): int(v) for k, v in c.items()}


def _limit_threads(limit: int | None):
    if threadpool_limits is None:
        return nullcontext()
    if limit is None:
        return nullcontext()
    try:
        lim = int(limit)
    except Exception:
        return nullcontext()
    if lim <= 0:
        return nullcontext()
    return threadpool_limits(limits=lim)


def _cooldown_sleep(seconds: float) -> None:
    try:
        s = float(seconds)
    except Exception:
        s = 0.0
    if s > 0:
        time.sleep(s)


# =============================================================================
# Feature sets
# =============================================================================

def _find_phase12_feature_sets(cfg: Phase13TrainConfig, app: str) -> Optional[Path]:
    app = str(app).strip().lower()
    tag = cfg.filename_tag.strip() or "run"

    app_dirs = [
        Path(cfg.phase12_dir) / f"app={app}",
        Path(cfg.phase12_dir) / app,
    ]

    candidates = [
        f"phase12_feature_sets_{app}_{tag}.json",
        f"phase12_feature_sets_{app}.json",
        f"phase12_feature_sets_{tag}.json",
        "phase12_feature_sets.json",
        "feature_sets.json",
    ]

    for d in app_dirs:
        for name in candidates:
            p = d / name
            if p.exists():
                return p

        matches = sorted(d.glob("*feature_sets*.json"))
        if matches:
            return matches[0]

    return None


def _load_feature_sets(cfg: Phase13TrainConfig, app: str) -> Tuple[Dict[str, Any], Optional[Path]]:
    path = _find_phase12_feature_sets(cfg, app)
    if path is None:
        raise RuntimeError(f"Phase 12 feature_sets JSON not found for app={app} in {cfg.phase12_dir}")

    obj = _json_load(path)
    if isinstance(obj, dict) and "feature_sets" in obj:
        fs = obj["feature_sets"]
    else:
        fs = obj

    if not isinstance(fs, dict):
        raise RuntimeError(f"Invalid feature_sets JSON for app={app}: {path}")

    return fs, path


# =============================================================================
# Streaming sample from split shards
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


def _scan_split_counts(
    shard_files: List[Path],
    *,
    cfg: Phase13TrainConfig,
    app: str,
    split: str,
) -> Dict[str, Any]:
    rows_seen = 0
    bytes_seen = 0
    target_counter: Counter = Counter()
    schema_cols: Optional[List[str]] = None

    for fp in tqdm(shard_files, desc=f"PHASE 13 scan {app}/{split}", unit="shard", dynamic_ncols=True):
        try:
            bytes_seen += int(fp.stat().st_size)
        except Exception:
            pass

        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        rows_seen += int(len(df))
        if schema_cols is None:
            schema_cols = list(df.columns)

        y = _target_series(df, cfg.target_col)
        target_counter.update(y.astype(int).tolist())

        del df
        gc.collect()

    return {
        "rows_seen": int(rows_seen),
        "bytes_seen": int(bytes_seen),
        "target_counts": target_counter,
        "schema_cols": schema_cols or [],
    }


def _sample_plan(target_counts: Counter, n_take: int, mode: str) -> Dict[int, int]:
    total = int(sum(target_counts.values()))
    n_take = min(max(0, int(n_take)), total)
    if total <= 0 or n_take <= 0:
        return {}

    mode = str(mode or "stratified_balanced").lower().strip()
    n0 = int(target_counts.get(0, 0))
    n1 = int(target_counts.get(1, 0))

    if mode == "stratified_balanced" and n0 > 0 and n1 > 0:
        per = n_take // 2
        take0 = min(per, n0)
        take1 = min(n_take - take0, n1)

        rem = n_take - (take0 + take1)
        if rem > 0:
            add0 = min(rem, n0 - take0)
            take0 += add0
            rem -= add0
        if rem > 0:
            add1 = min(rem, n1 - take1)
            take1 += add1

        return {0: int(take0), 1: int(take1)}

    # proportional default
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
        if plan.get(kk, 0) < int(target_counts[kk]):
            plan[kk] = plan.get(kk, 0) + 1
            remaining -= 1

    while sum(plan.values()) > n_take:
        kmax = max(plan, key=lambda kk: plan[kk])
        plan[kmax] -= 1
        if plan[kmax] <= 0:
            del plan[kmax]

    return {int(k): int(v) for k, v in plan.items() if int(v) > 0}


def _load_split_sample(
    shard_files: List[Path],
    *,
    cfg: Phase13TrainConfig,
    app: str,
    split: str,
    n_rows: Optional[int],
    target_counts: Counter,
) -> pd.DataFrame:
    total = int(sum(target_counts.values()))
    if n_rows is None or int(n_rows) <= 0:
        # Full load. Use carefully.
        parts: List[pd.DataFrame] = []
        for fp in tqdm(shard_files, desc=f"PHASE 13 load full {app}/{split}", unit="shard", dynamic_ncols=True):
            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is not None and not df.empty:
                parts.append(df)
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    n_take = min(int(n_rows), total)
    if n_take <= 0:
        return pd.DataFrame()

    mode = str(cfg.sample_mode or "stratified_balanced").lower().strip()

    if mode == "random":
        sampler = _ReservoirSampler(n_take, seed=int(cfg.seed) + abs(hash((app, split))) % 100_000)
        for fp in tqdm(shard_files, desc=f"PHASE 13 sample {app}/{split}", unit="shard", dynamic_ncols=True):
            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is None or df.empty:
                continue
            sampler.add(df)
            del df
            gc.collect()
        return sampler.dataframe()

    plan = _sample_plan(target_counts, n_take, mode)
    samplers = {
        int(k): _ReservoirSampler(v, seed=int(cfg.seed) + int(k) * 37 + abs(hash((app, split))) % 100_000)
        for k, v in plan.items()
    }

    for fp in tqdm(shard_files, desc=f"PHASE 13 sample {app}/{split}", unit="shard", dynamic_ncols=True):
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        y = _target_series(df, cfg.target_col)
        for cls, sampler in samplers.items():
            sub = df[y == int(cls)]
            if not sub.empty:
                sampler.add(sub)

        del df
        gc.collect()

    parts = [s.dataframe() for s in samplers.values() if not s.dataframe().empty]
    if not parts:
        return pd.DataFrame()

    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=cfg.seed).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=cfg.seed).reset_index(drop=True)

    return out


# =============================================================================
# Numeric prep / metrics
# =============================================================================

_BOOL_STR_MAP = {
    "true": 1,
    "false": 0,
    "yes": 1,
    "no": 0,
    "y": 1,
    "n": 0,
    "t": 1,
    "f": 0,
    "on": 1,
    "off": 0,
}


def _series_to_numeric_like(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.astype("Int8")

    if pd.api.types.is_numeric_dtype(s):
        return s

    s_str = s.astype("string").str.strip()
    s_low = s_str.str.lower()
    mapped = s_low.map(_BOOL_STR_MAP)
    coerced_bool = mapped.astype("float64")
    coerced_num = pd.to_numeric(s_str, errors="coerce")

    out = coerced_num.copy()
    mask = out.isna() & coerced_bool.notna()
    if mask.any():
        out.loc[mask] = coerced_bool.loc[mask]
    return out


def _is_forbidden_training_feature(col: str, cfg: Phase13TrainConfig) -> bool:
    if not bool(getattr(cfg, "strict_leakage_guard", True)):
        return False

    c = str(col).strip()
    c_low = c.lower()

    forbidden_exact = {str(x).strip().lower() for x in getattr(cfg, "forbidden_feature_cols", ()) if str(x).strip()}
    if c_low in forbidden_exact:
        return True

    prefixes = tuple(str(x).strip().lower() for x in getattr(cfg, "forbidden_feature_prefixes", ()) if str(x).strip())
    return bool(prefixes and c_low.startswith(prefixes))


def _forbidden_features_in_columns(cols: Sequence[str], cfg: Phase13TrainConfig) -> List[str]:
    return [str(c) for c in cols if _is_forbidden_training_feature(str(c), cfg)]


def _drop_forbidden_training_features(df: pd.DataFrame, cfg: Phase13TrainConfig) -> Tuple[pd.DataFrame, List[str]]:
    if df is None or df.empty or not bool(getattr(cfg, "strict_leakage_guard", True)):
        return df.copy() if df is not None else pd.DataFrame(), []
    forbidden = _forbidden_features_in_columns(list(df.columns), cfg)
    if not forbidden:
        return df.copy(), []
    return df.drop(columns=forbidden, errors="ignore"), forbidden


def _select_best_results(results_df: pd.DataFrame, cfg: Phase13TrainConfig) -> Dict[str, Any]:
    if results_df is None or results_df.empty:
        return {"best_cv": None, "best_holdout": None, "best_preferred": None, "policy": getattr(cfg, "best_model_policy", "holdout_first")}

    def _best_by(sort_cols: List[str]) -> Optional[Dict[str, Any]]:
        cols = [c for c in sort_cols if c in results_df.columns]
        if not cols:
            return None
        tmp = results_df.copy()
        for c in cols:
            tmp[c] = pd.to_numeric(tmp[c], errors="coerce")
        tmp = tmp.dropna(subset=[cols[0]])
        if tmp.empty:
            return None
        tmp = tmp.sort_values(cols, ascending=[False] * len(cols), kind="mergesort")
        return tmp.iloc[0].to_dict()

    best_cv = _best_by(["f1_attack", "auc", "accuracy"])
    best_holdout = _best_by(["holdout_f1_attack", "holdout_auc", "f1_attack", "auc"])

    policy = str(getattr(cfg, "best_model_policy", "holdout_first") or "holdout_first").lower().strip()
    if policy in {"holdout", "holdout_first", "holdout_f1"} and best_holdout is not None:
        preferred = best_holdout
    else:
        preferred = best_cv or best_holdout

    return {
        "best_cv": best_cv,
        "best_holdout": best_holdout,
        "best_preferred": preferred,
        "policy": policy,
    }


def _results_table_for_report(results_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Embed the full Method × Model table into Phase 13 summaries.

    The PDF generator can read results_comparison_*.csv when the full artifacts
    directory is present. However, copied metrics folders often contain only the
    JSON summaries. Keeping this small table in JSON makes the analytical PDF
    reproducible from metrics alone.
    """
    if results_df is None or results_df.empty:
        return []

    safe = results_df.copy()
    safe = safe.replace([np.inf, -np.inf], np.nan)
    safe = safe.where(pd.notnull(safe), None)

    preferred_cols = [
        "App",
        "Method",
        "Model",
        "accuracy",
        "accuracy_std",
        "precision_attack",
        "recall_attack",
        "f1_attack",
        "auc",
        "cv_folds",
        "train_rows",
        "train_features",
        "holdout_accuracy",
        "holdout_precision_attack",
        "holdout_recall_attack",
        "holdout_f1_attack",
        "holdout_auc",
        "test_rows",
        "elapsed_seconds",
    ]
    cols = [c for c in preferred_cols if c in safe.columns]
    extra = [c for c in safe.columns if c not in cols and c != "model_checkpoint"]
    safe = safe[cols + extra]

    out: List[Dict[str, Any]] = []
    for row in safe.to_dict(orient="records"):
        cleaned: Dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                cleaned[str(k)] = int(v)
            elif isinstance(v, (np.floating, float)):
                fv = float(v)
                cleaned[str(k)] = None if (np.isnan(fv) or np.isinf(fv)) else fv
            else:
                cleaned[str(k)] = v
        out.append(cleaned)
    return out


def _training_quality_warnings(
    results_df: pd.DataFrame,
    *,
    cfg: Phase13TrainConfig,
    do_holdout: bool,
    forbidden_after_prep: Sequence[str],
    train_target_counts: Dict[str, int],
    test_target_counts: Dict[str, int],
) -> List[str]:
    warnings: List[str] = []
    threshold = float(getattr(cfg, "suspicious_score_threshold", 0.999))

    if forbidden_after_prep:
        warnings.append(
            "Forbidden leakage/shortcut features were still present after numeric preparation: "
            + ", ".join(str(x) for x in forbidden_after_prep[:20])
        )

    if not do_holdout:
        warnings.append("Holdout evaluation was disabled or invalid; interpret CV metrics as preliminary only.")

    if isinstance(train_target_counts, dict) and len([v for v in train_target_counts.values() if int(v) > 0]) < 2:
        warnings.append("Training sample contains only one target class.")
    if do_holdout and isinstance(test_target_counts, dict) and len([v for v in test_target_counts.values() if int(v) > 0]) < 2:
        warnings.append("Holdout sample contains only one target class.")

    if results_df is not None and not results_df.empty:
        metric_cols = [c for c in ("f1_attack", "auc", "holdout_f1_attack", "holdout_auc") if c in results_df.columns]
        suspicious_rows = []
        for _, row in results_df.iterrows():
            hit_metrics = []
            for c in metric_cols:
                try:
                    v = float(row.get(c))
                except Exception:
                    continue
                if v >= threshold:
                    hit_metrics.append(f"{c}={v:.4f}")
            if hit_metrics:
                suspicious_rows.append(f"{row.get('Method')}/{row.get('Model')} ({', '.join(hit_metrics)})")

        if suspicious_rows:
            warnings.append(
                "Near-perfect scores detected; treat as possible shortcut/leakage or overly easy split until validated: "
                + "; ".join(suspicious_rows[:10])
            )

    return warnings


def _prepare_numeric_Xy(df: pd.DataFrame, cfg: Phase13TrainConfig) -> Tuple[pd.DataFrame, pd.Series]:
    if cfg.target_col not in df.columns:
        raise RuntimeError(f"Missing target column '{cfg.target_col}' in input df.")

    y = _target_series(df, cfg.target_col)
    vc = y.value_counts()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class: {vc.to_dict()}")

    X_all = df.drop(columns=[cfg.target_col], errors="ignore").copy()
    X_all, _forbidden_dropped = _drop_forbidden_training_features(X_all, cfg)
    if X_all.empty:
        raise RuntimeError("No feature columns left after dropping target and leakage/shortcut features.")

    kept_cols: List[str] = []
    X_num = pd.DataFrame(index=X_all.index)

    for c in X_all.columns:
        s_num = _series_to_numeric_like(X_all[c])
        if s_num.notna().sum() > 0:
            X_num[c] = s_num.replace([np.inf, -np.inf], np.nan).fillna(0)
            kept_cols.append(c)

    if not kept_cols:
        raise RuntimeError("No numeric/numeric-like columns available for training after coercion.")

    return X_num[kept_cols], y


def _align_test_to_train(X_test_all: pd.DataFrame, train_numeric_cols: Sequence[str]) -> pd.DataFrame:
    out = X_test_all.copy()
    for c in train_numeric_cols:
        if c not in out.columns:
            out[c] = 0
    out = out[list(train_numeric_cols)].copy()
    for c in out.columns:
        out[c] = _series_to_numeric_like(out[c]).replace([np.inf, -np.inf], np.nan).fillna(0)
    return out


def _safe_score_vector(estimator, X) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        p = estimator.predict_proba(X)
        if isinstance(p, np.ndarray) and p.ndim == 2 and p.shape[1] >= 2:
            return p[:, 1]
        return np.asarray(p).ravel()

    if hasattr(estimator, "decision_function"):
        s = estimator.decision_function(X)
        return np.asarray(s).ravel()

    return np.asarray(estimator.predict(X)).astype(float)


def _eval_once(
    estimator,
    X_tr,
    y_tr,
    X_te,
    y_te,
    *,
    thread_limit: int | None = None,
) -> Dict[str, float]:
    y_tr = np.asarray(y_tr).ravel()
    y_te = np.asarray(y_te).ravel().astype(np.int64, copy=False)

    with _limit_threads(thread_limit):
        estimator.fit(X_tr, y_tr)
        y_pred = estimator.predict(X_te)

        try:
            scores = _safe_score_vector(estimator, X_te)
        except Exception:
            scores = np.asarray(y_pred).astype(float, copy=False)

        acc = accuracy_score(y_te, y_pred)
        prec = precision_score(y_te, y_pred, average="binary", pos_label=1, zero_division=0)
        rec = recall_score(y_te, y_pred, average="binary", pos_label=1, zero_division=0)
        f1 = f1_score(y_te, y_pred, average="binary", pos_label=1, zero_division=0)

        try:
            auc = roc_auc_score(y_te, scores)
        except Exception:
            auc = 0.5

    return {
        "accuracy": float(acc),
        "precision_attack": float(prec),
        "recall_attack": float(rec),
        "f1_attack": float(f1),
        "auc": float(auc),
    }


# =============================================================================
# Models / estimators
# =============================================================================

def _build_models(cfg: Phase13TrainConfig) -> Dict[str, Any]:
    models: Dict[str, Any] = {
        "DT": DecisionTreeClassifier(random_state=cfg.seed),
        "RFC": RandomForestClassifier(
            n_estimators=cfg.rfc_estimators,
            max_depth=cfg.rfc_max_depth,
            min_samples_leaf=cfg.rfc_min_samples_leaf,
            random_state=cfg.seed,
            n_jobs=cfg.rfc_n_jobs,
        ),
        "LSVC": LinearSVC(
            C=cfg.lsvc_c,
            max_iter=cfg.lsvc_max_iter,
            dual=cfg.lsvc_dual,
            random_state=cfg.seed,
        ),
    }

    if XGBClassifier is not None:
        models["XGB"] = XGBClassifier(
            n_estimators=cfg.xgb_n_estimators,
            max_depth=cfg.xgb_max_depth,
            learning_rate=cfg.xgb_learning_rate,
            subsample=cfg.xgb_subsample,
            colsample_bytree=cfg.xgb_colsample_bytree,
            reg_lambda=cfg.xgb_reg_lambda,
            n_jobs=cfg.xgb_n_jobs,
            tree_method=cfg.xgb_tree_method,
            device=cfg.xgb_device,
            random_state=cfg.seed,
            eval_metric=cfg.xgb_eval_metric,
        )

    return models


def _make_estimator(
    method: str,
    model_name: str,
    base_models: Dict[str, Any],
    n_components: int,
    cfg: Phase13TrainConfig,
):
    m = clone(base_models[model_name])

    method = method.upper()

    if method in {"MI", "RFE"}:
        if model_name == "LSVC":
            return Pipeline([("scaler", StandardScaler()), ("model", m)])
        return m

    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=int(n_components), random_state=cfg.seed)),
        ("model", m),
    ])


def _get_method_features(
    method: str,
    feature_sets: Dict[str, Any],
    train_cols: Sequence[str],
    n_pca_default: int,
) -> Tuple[Optional[List[str]], int]:
    method = str(method).upper()
    train_cols_set = set(str(c) for c in train_cols)

    if method in {"MI", "RFE"}:
        feats = feature_sets.get(method, [])
        if not isinstance(feats, list):
            return [], n_pca_default
        found = [str(f) for f in feats if str(f) in train_cols_set]
        return found, n_pca_default

    pca_cfg = feature_sets.get("PCA", {})
    n_comp = n_pca_default
    if isinstance(pca_cfg, dict):
        try:
            n_comp = int(pca_cfg.get("n_components", n_pca_default))
        except Exception:
            n_comp = n_pca_default

    n_comp = max(2, min(int(n_comp), len(train_cols)))
    return None, n_comp


# =============================================================================
# Checkpoints
# =============================================================================

def _checkpoint_root(out_app_dir: Path) -> Path:
    return Path(out_app_dir) / "checkpoints"


def _job_key(method: str, model_name: str) -> str:
    return f"{str(method).upper()}__{str(model_name).upper()}"


def _job_dir(out_app_dir: Path, method: str, model_name: str) -> Path:
    return _checkpoint_root(out_app_dir) / str(method).upper() / str(model_name).upper()


def _job_state_path(out_app_dir: Path, method: str, model_name: str) -> Path:
    return _job_dir(out_app_dir, method, model_name) / "job_state.json"


def _job_row_path(out_app_dir: Path, method: str, model_name: str) -> Path:
    return _job_dir(out_app_dir, method, model_name) / "result_row.json"


def _load_json_or_none(path: Path) -> Optional[dict]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _load_completed_row(out_app_dir: Path, method: str, model_name: str) -> Optional[dict]:
    state = _load_json_or_none(_job_state_path(out_app_dir, method, model_name))
    if not state or str(state.get("status", "")).lower() != "completed":
        return None

    row = _load_json_or_none(_job_row_path(out_app_dir, method, model_name))
    if row:
        return row

    row2 = state.get("result_row")
    return row2 if isinstance(row2, dict) else None


def _save_job_state(out_app_dir: Path, method: str, model_name: str, state: dict) -> None:
    p = _job_state_path(out_app_dir, method, model_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    _json_dump(state, p)


def _save_job_row(out_app_dir: Path, method: str, model_name: str, row: dict) -> None:
    p = _job_row_path(out_app_dir, method, model_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    _json_dump(row, p)


def _save_model_if_needed(out_app_dir: Path, method: str, model_name: str, estimator, cfg: Phase13TrainConfig) -> Optional[str]:
    if not cfg.save_fitted_models or joblib is None or estimator is None:
        return None

    p = _job_dir(out_app_dir, method, model_name) / "final_model.joblib"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        joblib.dump(estimator, p)
        return str(p)
    except Exception:
        return None


# =============================================================================
# Public API
# =============================================================================

def phase13_train_for_app(
    app: str,
    *,
    cfg: Phase13TrainConfig,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    app = str(app).strip().lower()
    tag = cfg.filename_tag.strip() or "run"
    t0 = time.perf_counter()

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)
    _checkpoint_root(out_app_dir).mkdir(parents=True, exist_ok=True)

    train_shards = _list_split_shards(cfg.modeling_dir, app, "train")
    test_shards = _list_split_shards(cfg.modeling_dir, app, "test")

    if not train_shards:
        summary = {
            "phase": 13,
            "app": app,
            "status": "skipped_no_train_shards",
            "modeling_dir": str(cfg.modeling_dir),
            "output_dir": str(out_app_dir),
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase13_train_summary_{app}.json")
        return pd.DataFrame(), summary

    print(f"\nPHASE 13: Training for app={app}")
    print(f"   Train shards : {len(train_shards):,}")
    print(f"   Test shards  : {len(test_shards):,}")
    print(f"   Output       : {out_app_dir}")

    feature_sets, feature_sets_path = _load_feature_sets(cfg, app)

    train_scan = _scan_split_counts(train_shards, cfg=cfg, app=app, split="train")
    test_scan = _scan_split_counts(test_shards, cfg=cfg, app=app, split="test") if test_shards else {
        "rows_seen": 0,
        "bytes_seen": 0,
        "target_counts": Counter(),
        "schema_cols": [],
    }

    df_train = _load_split_sample(
        train_shards,
        cfg=cfg,
        app=app,
        split="train",
        n_rows=cfg.train_rows,
        target_counts=train_scan["target_counts"],
    )

    if df_train.empty:
        raise RuntimeError(f"Phase 13 train sample is empty for app={app}.")

    df_test = pd.DataFrame()
    if cfg.do_holdout_eval and test_shards:
        df_test = _load_split_sample(
            test_shards,
            cfg=cfg,
            app=app,
            split="test",
            n_rows=cfg.test_rows,
            target_counts=test_scan["target_counts"],
        )

    X_train_numeric, y_train = _prepare_numeric_Xy(df_train, cfg)

    do_holdout = bool(cfg.do_holdout_eval and df_test is not None and not df_test.empty)
    X_test_numeric = None
    y_test = None

    if do_holdout:
        try:
            X_test_all, y_test = _prepare_numeric_Xy(df_test, cfg)
            X_test_numeric = _align_test_to_train(X_test_all, X_train_numeric.columns.tolist())
            if y_test.nunique(dropna=True) < 2:
                do_holdout = False
                X_test_numeric = None
                y_test = None
        except Exception as e:
            print(f"   ⚠️ Holdout disabled for app={app}: {e!r}")
            do_holdout = False
            X_test_numeric = None
            y_test = None

    min_class = int(pd.Series(y_train).value_counts().min())
    n_splits = min(int(cfg.default_n_splits), min_class)
    if n_splits < 2:
        raise RuntimeError(f"Not enough samples per class for CV. app={app}, min_class={min_class}")

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=cfg.seed)
    base_models = _build_models(cfg)

    methods = [str(m).upper() for m in cfg.methods]
    model_order = [str(m).upper() for m in cfg.models]
    model_order = [m for m in model_order if m in base_models]

    if "XGB" in cfg.models and XGBClassifier is None:
        print("   ⚠️ XGB requested but xgboost is not installed; skipped.")

    results_map: Dict[str, dict] = {}

    if cfg.resume_enabled:
        for method in methods:
            for model_name in model_order:
                row = _load_completed_row(out_app_dir, method, model_name)
                if row:
                    results_map[_job_key(method, model_name)] = row

    for method in methods:
        feature_list, n_comp = _get_method_features(
            method,
            feature_sets,
            X_train_numeric.columns.tolist(),
            cfg.pca_default_n_components,
        )

        if method in {"MI", "RFE"}:
            if not feature_list:
                print(f"   ⚠️ {app}/{method} skipped: no selected features found in train columns.")
                continue
            X_method_train = X_train_numeric[feature_list].copy()
            X_method_test = X_test_numeric[feature_list].copy() if do_holdout and X_test_numeric is not None else None
        elif method == "PCA":
            X_method_train = X_train_numeric.copy()
            X_method_test = X_test_numeric.copy() if do_holdout and X_test_numeric is not None else None
        else:
            print(f"   ⚠️ Unknown method skipped: {method}")
            continue

        print(f"   Method={method} | train_features={X_method_train.shape[1]} | pca_n={n_comp if method == 'PCA' else '-'}")

        for model_name in model_order:
            job_key = _job_key(method, model_name)
            if cfg.resume_enabled and job_key in results_map:
                print(f"      ↪ resume skip {method}/{model_name}")
                continue

            print(f"      ▶ {method}/{model_name}")
            t_job = time.perf_counter()

            _save_job_state(
                out_app_dir,
                method,
                model_name,
                {
                    "method": method,
                    "model_name": model_name,
                    "status": "running",
                    "updated_at": datetime.now().isoformat(),
                    "fold_metrics": {},
                    "holdout_metrics": None,
                },
            )

            accs: List[float] = []
            precs: List[float] = []
            recs: List[float] = []
            f1s: List[float] = []
            aucs: List[float] = []
            fold_metrics: Dict[str, Dict[str, float]] = {}

            for fold_idx, (tr_idx, te_idx) in enumerate(cv.split(X_method_train, y_train), start=1):
                X_tr = X_method_train.iloc[tr_idx]
                X_te = X_method_train.iloc[te_idx]
                y_tr = y_train.iloc[tr_idx]
                y_te = y_train.iloc[te_idx]

                est = _make_estimator(method, model_name, base_models, n_comp, cfg)
                m = _eval_once(
                    est,
                    X_tr,
                    y_tr,
                    X_te,
                    y_te,
                    thread_limit=cfg.blas_thread_limit,
                )

                accs.append(float(m["accuracy"]))
                precs.append(float(m["precision_attack"]))
                recs.append(float(m["recall_attack"]))
                f1s.append(float(m["f1_attack"]))
                aucs.append(float(m["auc"]))
                fold_metrics[str(fold_idx)] = m

                if cfg.checkpoint_each_fold:
                    _save_job_state(
                        out_app_dir,
                        method,
                        model_name,
                        {
                            "method": method,
                            "model_name": model_name,
                            "status": "running",
                            "updated_at": datetime.now().isoformat(),
                            "fold_metrics": fold_metrics,
                            "holdout_metrics": None,
                        },
                    )

                print(
                    f"        fold {fold_idx}/{n_splits}: "
                    f"acc={m['accuracy']:.4f} f1={m['f1_attack']:.4f} auc={m['auc']:.4f}"
                )

                if cfg.gc_each_fold:
                    del est, X_tr, X_te, y_tr, y_te
                    gc.collect()

                _cooldown_sleep(cfg.cooldown_seconds)

            row: Dict[str, Any] = {
                "App": app,
                "Method": method,
                "Model": model_name,
                "accuracy": float(np.mean(accs)),
                "accuracy_std": float(np.std(accs)),
                "precision_attack": float(np.mean(precs)),
                "recall_attack": float(np.mean(recs)),
                "f1_attack": float(np.mean(f1s)),
                "auc": float(np.mean(aucs)),
                "cv_folds": int(n_splits),
                "train_rows": int(len(X_method_train)),
                "train_features": int(X_method_train.shape[1]),
            }

            holdout_metrics = None
            est_final = None

            if do_holdout and X_method_test is not None and y_test is not None:
                est_final = _make_estimator(method, model_name, base_models, n_comp, cfg)
                holdout_metrics = _eval_once(
                    est_final,
                    X_method_train,
                    y_train,
                    X_method_test,
                    y_test,
                    thread_limit=cfg.blas_thread_limit,
                )

                row.update({
                    "holdout_accuracy": float(holdout_metrics["accuracy"]),
                    "holdout_precision_attack": float(holdout_metrics["precision_attack"]),
                    "holdout_recall_attack": float(holdout_metrics["recall_attack"]),
                    "holdout_f1_attack": float(holdout_metrics["f1_attack"]),
                    "holdout_auc": float(holdout_metrics["auc"]),
                    "test_rows": int(len(X_method_test)),
                })

            model_path = _save_model_if_needed(out_app_dir, method, model_name, est_final, cfg)
            if model_path:
                row["model_checkpoint"] = model_path

            row["elapsed_seconds"] = float(time.perf_counter() - t_job)

            results_map[job_key] = row
            _save_job_row(out_app_dir, method, model_name, row)
            _save_job_state(
                out_app_dir,
                method,
                model_name,
                {
                    "method": method,
                    "model_name": model_name,
                    "status": "completed",
                    "updated_at": datetime.now().isoformat(),
                    "fold_metrics": fold_metrics,
                    "holdout_metrics": holdout_metrics,
                    "result_row": row,
                },
            )

            print(
                f"        ✓ cv_f1={row['f1_attack']:.4f} cv_auc={row['auc']:.4f}"
                + (f" holdout_auc={row.get('holdout_auc', 0):.4f}" if do_holdout else "")
            )

            if cfg.gc_each_fold and est_final is not None:
                del est_final
                gc.collect()

    # Ordered results
    rows: List[dict] = []
    for method in methods:
        for model_name in model_order:
            row = results_map.get(_job_key(method, model_name))
            if row:
                rows.append(row)

    results_df = pd.DataFrame(rows)

    results_csv_path = out_app_dir / f"results_comparison_{app}_{tag}.csv"
    summary_path = out_app_dir / f"phase13_summary_{app}_{tag}.json"

    if cfg.write_artifacts:
        results_df.to_csv(results_csv_path, index=False)

    best_pack = _select_best_results(results_df, cfg)
    best_row = best_pack.get("best_cv")
    best_holdout_row = best_pack.get("best_holdout")
    best_preferred_row = best_pack.get("best_preferred")

    forbidden_after_prep = _forbidden_features_in_columns(X_train_numeric.columns.tolist(), cfg)
    train_counts_loaded_for_warning = {str(k): int(v) for k, v in y_train.value_counts().to_dict().items()}
    test_counts_loaded_for_warning = (
        {str(k): int(v) for k, v in y_test.value_counts().to_dict().items()}
        if y_test is not None else {}
    )
    quality_warnings = _training_quality_warnings(
        results_df,
        cfg=cfg,
        do_holdout=bool(do_holdout),
        forbidden_after_prep=forbidden_after_prep,
        train_target_counts=train_counts_loaded_for_warning,
        test_target_counts=test_counts_loaded_for_warning,
    )

    # Per-model summary files for report compatibility.
    model_summary_paths: Dict[str, str] = {}
    if cfg.write_artifacts and not results_df.empty:
        for idx, model_name in enumerate(model_order, start=1):
            df_model = results_df[results_df["Model"].astype(str) == model_name].copy()
            if df_model.empty:
                continue

            p = out_app_dir / f"phase13_{idx}{model_name}_summary_{app}_{tag}.json"
            payload = {
                "phase": 13,
                "app": app,
                "generated_at": datetime.now().isoformat(),
                "model_name": model_name,
                "model_order_index": idx,
                "results_rows": int(len(df_model)),
                "results": df_model.to_dict(orient="records"),
                "best_by_cv_f1_attack": (
                    df_model.loc[df_model["f1_attack"].astype(float).idxmax()].to_dict()
                    if "f1_attack" in df_model.columns else None
                ),
            }
            _json_dump(payload, p)
            model_summary_paths[model_name] = str(p)

    elapsed = time.perf_counter() - t0

    summary = {
        "phase": 13,
        "app": app,
        "status": "completed",
        "generated_at": datetime.now().isoformat(),
        "modeling_dir": str(cfg.modeling_dir),
        "phase12_dir": str(cfg.phase12_dir),
        "output_dir": str(out_app_dir),
        "feature_sets_json": str(feature_sets_path) if feature_sets_path else None,
        "train_rows_seen": int(train_scan["rows_seen"]),
        "test_rows_seen": int(test_scan["rows_seen"]),
        "train_rows_loaded": int(len(df_train)),
        "test_rows_loaded": int(len(df_test)) if df_test is not None else 0,
        "train_target_counts_seen": _counter_to_str_dict(train_scan["target_counts"]),
        "test_target_counts_seen": _counter_to_str_dict(test_scan["target_counts"]),
        "train_target_counts_loaded": {str(k): int(v) for k, v in y_train.value_counts().to_dict().items()},
        "test_target_counts_loaded": (
            {str(k): int(v) for k, v in y_test.value_counts().to_dict().items()}
            if y_test is not None else {}
        ),
        "do_holdout_eval": bool(do_holdout),
        "cv_folds": int(n_splits),
        "methods": methods,
        "models": model_order,
        "results_rows": int(len(results_df)),
        "results_columns": [str(c) for c in results_df.columns],
        "results_table": _results_table_for_report(results_df),
        "best_by_cv_f1_attack": best_row,
        "best_by_holdout_f1_attack": best_holdout_row,
        "best_by_preferred_metric": best_preferred_row,
        "best_selection_policy": best_pack.get("policy"),
        "training_quality_warnings": quality_warnings,
        "airc_leakage_aware": True,
        "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
        "forbidden_features_after_prep": forbidden_after_prep,
        "logical_cpu": int(_LOGICAL_CPU),
        "worker_threads": int(_WORKER_THREADS),
        "inner_math_threads": int(_INNER_MATH_THREADS),
        "rfc_n_jobs": int(cfg.rfc_n_jobs),
        "lsvc_max_iter": int(cfg.lsvc_max_iter),
        "xgb_available": bool(XGBClassifier is not None),
        "xgb_device": str(cfg.xgb_device),
        "xgb_tree_method": str(cfg.xgb_tree_method),
        "paths": {
            "results_csv": str(results_csv_path) if cfg.write_artifacts else None,
            "summary_json": str(summary_path) if cfg.write_artifacts else None,
            "checkpoint_root": str(_checkpoint_root(out_app_dir)),
            "model_summaries": model_summary_paths,
        },
        "seconds": float(elapsed),
        "elapsed_human": _fmt_elapsed(elapsed),
        "note": (
            "Phase 13 trains models per application using Phase 11 train/test shards and Phase 12 feature sets. "
            "KNN is intentionally not part of the default model list."
        ),
    }

    if cfg.write_artifacts:
        _json_dump(summary, summary_path)
        _json_dump(summary, metrics_dir / f"phase13_train_summary_{app}.json")

    print(f"✅ Phase 13 complete app={app}")
    print(f"   Results rows : {len(results_df):,}")
    print(f"   Best         : {best_row}")
    print(f"   Output       : {out_app_dir}")
    print(f"   Time         : {_fmt_elapsed(elapsed)}")

    return results_df, summary


def phase13_train(
    *,
    cfg: Phase13TrainConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    print("\n" + "=" * 78)
    print("PHASE 13: TRAINING (APP-AWARE)")
    print("=" * 78)

    t0 = time.perf_counter()

    results_by_app: Dict[str, pd.DataFrame] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        try:
            results_df, summary = phase13_train_for_app(app_norm, cfg=cfg)
        except Exception as e:
            results_df = pd.DataFrame()
            summary = {
                "phase": 13,
                "app": app_norm,
                "status": "failed",
                "error": repr(e),
                "seconds": 0.0,
            }
            metrics_dir = Path(cfg.output_dir) / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            _json_dump(summary, metrics_dir / f"phase13_train_summary_{app_norm}.json")
            print(f"❌ Phase 13 failed app={app_norm}: {e!r}")

        results_by_app[app_norm] = results_df
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        best = s.get("best_by_preferred_metric") or s.get("best_by_holdout_f1_attack") or s.get("best_by_cv_f1_attack") or {}
        rows.append({
            "app": app,
            "status": s.get("status"),
            "results_rows": int(s.get("results_rows", 0)),
            "train_rows_loaded": int(s.get("train_rows_loaded", 0)),
            "test_rows_loaded": int(s.get("test_rows_loaded", 0)),
            "cv_folds": int(s.get("cv_folds", 0)),
            "best_method": best.get("Method"),
            "best_model": best.get("Model"),
            "best_f1_attack": best.get("f1_attack"),
            "best_auc": best.get("auc"),
            "best_holdout_auc": best.get("holdout_auc"),
            "results_csv": (s.get("paths") or {}).get("results_csv"),
            "summary_json": (s.get("paths") or {}).get("summary_json"),
            "seconds": float(s.get("seconds", 0.0)),
            "error": s.get("error"),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase13_train_summary_by_app.csv", index=False)

    elapsed = time.perf_counter() - t0

    summary_all = {
        "phase": 13,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "modeling_dir": str(cfg.modeling_dir),
        "phase12_dir": str(cfg.phase12_dir),
        "output_dir": str(cfg.output_dir),
        "apps": summaries,
        "seconds": float(elapsed),
        "elapsed_human": _fmt_elapsed(elapsed),
        "note": (
            "Phase 13 is app-aware and reads Phase 11 modeling shards plus Phase 12 feature sets."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase13_train_summary_all.json")

    print("\n✅ PHASE 13 COMPLETE")
    print(f"   Output dir: {cfg.output_dir}")
    print(f"   Time      : {_fmt_elapsed(elapsed)}")

    return results_by_app, summary_all



# =============================================================================
# RAM MODE API (small-data / per-app pipeline)
# =============================================================================

def _extract_feature_sets_ram(
    feature_sets: Optional[Dict[str, Any]] = None,
    phase12_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    fs: Any = feature_sets
    if fs is None and isinstance(phase12_result, dict):
        fs = phase12_result.get("feature_sets")
        if fs is None and isinstance(phase12_result.get("summary"), dict):
            fs = phase12_result["summary"].get("feature_sets")
    if isinstance(fs, dict) and "feature_sets" in fs and isinstance(fs.get("feature_sets"), dict):
        fs = fs["feature_sets"]
    if not isinstance(fs, dict):
        raise RuntimeError("Phase 13 RAM requires feature_sets from Phase 12. Pass phase12_result or feature_sets.")
    return fs


def _sample_df_for_train_ram(
    df: pd.DataFrame,
    *,
    target_col: str,
    n_rows: Optional[int],
    mode: str,
    seed: int,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if n_rows is None or int(n_rows) <= 0 or len(df) <= int(n_rows):
        return df.copy().reset_index(drop=True)
    n_take = int(n_rows)
    mode = str(mode or "stratified_balanced").lower().strip()
    rng = np.random.default_rng(int(seed))
    if mode == "random" or target_col not in df.columns:
        idx = rng.choice(len(df), size=n_take, replace=False)
        return df.iloc[idx].copy().reset_index(drop=True)
    y = _target_series(df, target_col)
    counts = Counter(y.astype(int).tolist())
    plan = _sample_plan(counts, n_take, mode)
    parts: List[pd.DataFrame] = []
    for cls, take in plan.items():
        sub = df.loc[y == int(cls)]
        if sub.empty or int(take) <= 0:
            continue
        take = min(int(take), len(sub))
        parts.append(sub.sample(n=take, random_state=int(seed) + int(cls) * 103))
    if not parts:
        idx = rng.choice(len(df), size=n_take, replace=False)
        return df.iloc[idx].copy().reset_index(drop=True)
    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=int(seed)).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=int(seed)).reset_index(drop=True)
    return out


def phase13_train_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase13TrainConfig] = None,
    phase12_result: Optional[Dict[str, Any]] = None,
    feature_sets: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Train Phase 13 directly from RAM DataFrames produced by Phase 11."""
    app = str(app).strip().lower()
    if cfg is None:
        cfg = Phase13TrainConfig(selected_apps=(app,))
    tag = cfg.filename_tag.strip() or "run"
    t0 = time.perf_counter()

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)
    _checkpoint_root(out_app_dir).mkdir(parents=True, exist_ok=True)

    if df_train is None or df_train.empty:
        summary = {
            "phase": 13,
            "app": app,
            "status": "skipped_empty_train",
            "mode": "ram",
            "output_dir": str(out_app_dir),
            "seconds": 0.0,
        }
        if cfg.write_artifacts:
            _json_dump(summary, metrics_dir / f"phase13_train_summary_{app}.json")
        return pd.DataFrame(), summary

    fs = _extract_feature_sets_ram(feature_sets=feature_sets, phase12_result=phase12_result)

    df_train_loaded = _sample_df_for_train_ram(
        df_train,
        target_col=cfg.target_col,
        n_rows=cfg.train_rows,
        mode=cfg.sample_mode,
        seed=int(cfg.seed) + abs(hash((app, "train"))) % 100_000,
    )
    df_test_loaded = pd.DataFrame()
    if df_test is not None and isinstance(df_test, pd.DataFrame) and not df_test.empty:
        df_test_loaded = _sample_df_for_train_ram(
            df_test,
            target_col=cfg.target_col,
            n_rows=cfg.test_rows,
            mode=cfg.sample_mode,
            seed=int(cfg.seed) + abs(hash((app, "test"))) % 100_000,
        )

    if df_train_loaded.empty:
        raise RuntimeError(f"Phase 13 RAM train sample is empty for app={app}.")

    print(f"\nPHASE 13 RAM: Training for app={app}")
    print(f"   Train rows : {len(df_train_loaded):,} / source {len(df_train):,}")
    print(f"   Test rows  : {len(df_test_loaded):,} / source {0 if df_test is None else len(df_test):,}")
    print(f"   Output     : {out_app_dir}")

    X_train_numeric, y_train = _prepare_numeric_Xy(df_train_loaded, cfg)
    forbidden_after_prep = _forbidden_features_in_columns(X_train_numeric.columns.tolist(), cfg)

    do_holdout = bool(cfg.do_holdout_eval and df_test_loaded is not None and not df_test_loaded.empty)
    X_test_numeric = None
    y_test = None
    if do_holdout:
        try:
            X_test_all, y_test = _prepare_numeric_Xy(df_test_loaded, cfg)
            X_test_numeric = _align_test_to_train(X_test_all, X_train_numeric.columns.tolist())
            if y_test.nunique(dropna=True) < 2:
                do_holdout = False
                X_test_numeric = None
                y_test = None
        except Exception as e:
            print(f"   ⚠️ Holdout disabled for app={app}: {e!r}")
            do_holdout = False
            X_test_numeric = None
            y_test = None

    min_class = int(pd.Series(y_train).value_counts().min())
    n_splits = min(int(cfg.default_n_splits), min_class)
    if n_splits < 2:
        raise RuntimeError(f"Not enough samples per class for CV. app={app}, min_class={min_class}")

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=cfg.seed)
    base_models = _build_models(cfg)
    methods = [str(m).upper() for m in cfg.methods]
    model_order = [str(m).upper() for m in cfg.models]
    model_order = [m for m in model_order if m in base_models]
    if "XGB" in [str(m).upper() for m in cfg.models] and XGBClassifier is None:
        print("   ⚠️ XGB requested but xgboost is not installed; skipped.")

    results_map: Dict[str, dict] = {}
    if cfg.resume_enabled:
        for method in methods:
            for model_name in model_order:
                row = _load_completed_row(out_app_dir, method, model_name)
                if row:
                    results_map[_job_key(method, model_name)] = row

    for method in methods:
        feature_list, n_comp = _get_method_features(
            method,
            fs,
            X_train_numeric.columns.tolist(),
            cfg.pca_default_n_components,
        )
        if method in {"MI", "RFE"}:
            if not feature_list:
                print(f"   ⚠️ {app}/{method} skipped: no selected features found in train columns.")
                continue
            X_method_train = X_train_numeric[feature_list].copy()
            X_method_test = X_test_numeric[feature_list].copy() if do_holdout and X_test_numeric is not None else None
        elif method == "PCA":
            X_method_train = X_train_numeric.copy()
            X_method_test = X_test_numeric.copy() if do_holdout and X_test_numeric is not None else None
            n_comp = max(2, min(int(n_comp), X_method_train.shape[1], max(2, len(X_method_train) - 1)))
        else:
            print(f"   ⚠️ Unknown method skipped: {method}")
            continue

        print(f"   Method={method} | train_features={X_method_train.shape[1]} | pca_n={n_comp if method == 'PCA' else '-'}")
        for model_name in model_order:
            job_key = _job_key(method, model_name)
            if cfg.resume_enabled and job_key in results_map:
                print(f"      ↪ resume skip {method}/{model_name}")
                continue
            print(f"      ▶ {method}/{model_name}")
            t_job = time.perf_counter()
            _save_job_state(out_app_dir, method, model_name, {
                "method": method,
                "model_name": model_name,
                "status": "running",
                "updated_at": datetime.now().isoformat(),
                "fold_metrics": {},
                "holdout_metrics": None,
                "mode": "ram",
            })

            accs: List[float] = []
            precs: List[float] = []
            recs: List[float] = []
            f1s: List[float] = []
            aucs: List[float] = []
            fold_metrics: Dict[str, Dict[str, float]] = {}
            for fold_idx, (tr_idx, te_idx) in enumerate(cv.split(X_method_train, y_train), start=1):
                X_tr = X_method_train.iloc[tr_idx]
                X_te = X_method_train.iloc[te_idx]
                y_tr = y_train.iloc[tr_idx]
                y_te = y_train.iloc[te_idx]
                est = _make_estimator(method, model_name, base_models, n_comp, cfg)
                m = _eval_once(est, X_tr, y_tr, X_te, y_te, thread_limit=cfg.blas_thread_limit)
                accs.append(float(m["accuracy"]))
                precs.append(float(m["precision_attack"]))
                recs.append(float(m["recall_attack"]))
                f1s.append(float(m["f1_attack"]))
                aucs.append(float(m["auc"]))
                fold_metrics[str(fold_idx)] = m
                if cfg.checkpoint_each_fold:
                    _save_job_state(out_app_dir, method, model_name, {
                        "method": method,
                        "model_name": model_name,
                        "status": "running",
                        "updated_at": datetime.now().isoformat(),
                        "fold_metrics": fold_metrics,
                        "holdout_metrics": None,
                        "mode": "ram",
                    })
                print(f"        fold {fold_idx}/{n_splits}: acc={m['accuracy']:.4f} f1={m['f1_attack']:.4f} auc={m['auc']:.4f}")
                if cfg.gc_each_fold:
                    del est, X_tr, X_te, y_tr, y_te
                    gc.collect()
                _cooldown_sleep(cfg.cooldown_seconds)

            row: Dict[str, Any] = {
                "App": app,
                "Method": method,
                "Model": model_name,
                "accuracy": float(np.mean(accs)),
                "accuracy_std": float(np.std(accs)),
                "precision_attack": float(np.mean(precs)),
                "recall_attack": float(np.mean(recs)),
                "f1_attack": float(np.mean(f1s)),
                "auc": float(np.mean(aucs)),
                "cv_folds": int(n_splits),
                "train_rows": int(len(X_method_train)),
                "train_features": int(X_method_train.shape[1]),
            }

            holdout_metrics = None
            est_final = None
            if do_holdout and X_method_test is not None and y_test is not None:
                est_final = _make_estimator(method, model_name, base_models, n_comp, cfg)
                holdout_metrics = _eval_once(est_final, X_method_train, y_train, X_method_test, y_test, thread_limit=cfg.blas_thread_limit)
                row.update({
                    "holdout_accuracy": float(holdout_metrics["accuracy"]),
                    "holdout_precision_attack": float(holdout_metrics["precision_attack"]),
                    "holdout_recall_attack": float(holdout_metrics["recall_attack"]),
                    "holdout_f1_attack": float(holdout_metrics["f1_attack"]),
                    "holdout_auc": float(holdout_metrics["auc"]),
                    "test_rows": int(len(X_method_test)),
                })

            model_path = _save_model_if_needed(out_app_dir, method, model_name, est_final, cfg)
            if model_path:
                row["model_checkpoint"] = model_path
            row["elapsed_seconds"] = float(time.perf_counter() - t_job)
            results_map[job_key] = row
            _save_job_row(out_app_dir, method, model_name, row)
            _save_job_state(out_app_dir, method, model_name, {
                "method": method,
                "model_name": model_name,
                "status": "completed",
                "updated_at": datetime.now().isoformat(),
                "fold_metrics": fold_metrics,
                "holdout_metrics": holdout_metrics,
                "result_row": row,
                "mode": "ram",
            })
            print(f"        ✓ cv_f1={row['f1_attack']:.4f} cv_auc={row['auc']:.4f}" + (f" holdout_auc={row.get('holdout_auc', 0):.4f}" if do_holdout else ""))
            if cfg.gc_each_fold and est_final is not None:
                del est_final
                gc.collect()

    rows: List[dict] = []
    for method in methods:
        for model_name in model_order:
            row = results_map.get(_job_key(method, model_name))
            if row:
                rows.append(row)
    results_df = pd.DataFrame(rows)

    results_csv_path = out_app_dir / f"results_comparison_{app}_{tag}.csv"
    summary_path = out_app_dir / f"phase13_summary_{app}_{tag}.json"
    if cfg.write_artifacts:
        results_df.to_csv(results_csv_path, index=False)

    best_pack = _select_best_results(results_df, cfg)
    best_row = best_pack.get("best_cv")
    best_holdout_row = best_pack.get("best_holdout")
    best_preferred_row = best_pack.get("best_preferred")

    train_target_counts_loaded = {str(k): int(v) for k, v in y_train.value_counts().to_dict().items()}
    test_target_counts_loaded = ({str(k): int(v) for k, v in y_test.value_counts().to_dict().items()} if y_test is not None else {})
    quality_warnings = _training_quality_warnings(
        results_df,
        cfg=cfg,
        do_holdout=bool(do_holdout),
        forbidden_after_prep=forbidden_after_prep,
        train_target_counts=train_target_counts_loaded,
        test_target_counts=test_target_counts_loaded,
    )

    model_summary_paths: Dict[str, str] = {}
    if cfg.write_artifacts and not results_df.empty:
        for idx, model_name in enumerate(model_order, start=1):
            df_model = results_df[results_df["Model"].astype(str) == model_name].copy()
            if df_model.empty:
                continue
            p = out_app_dir / f"phase13_{idx}{model_name}_summary_{app}_{tag}.json"
            payload = {
                "phase": 13,
                "app": app,
                "mode": "ram",
                "generated_at": datetime.now().isoformat(),
                "model_name": model_name,
                "model_order_index": idx,
                "results_rows": int(len(df_model)),
                "results": df_model.to_dict(orient="records"),
                "best_by_cv_f1_attack": (df_model.loc[df_model["f1_attack"].astype(float).idxmax()].to_dict() if "f1_attack" in df_model.columns else None),
            }
            _json_dump(payload, p)
            model_summary_paths[model_name] = str(p)

    elapsed = time.perf_counter() - t0
    summary = {
        "phase": 13,
        "app": app,
        "status": "completed",
        "mode": "ram",
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(out_app_dir),
        "train_rows_seen": int(len(df_train)),
        "test_rows_seen": int(0 if df_test is None else len(df_test)),
        "train_rows_loaded": int(len(df_train_loaded)),
        "test_rows_loaded": int(len(df_test_loaded)) if df_test_loaded is not None else 0,
        "train_target_counts_loaded": train_target_counts_loaded,
        "test_target_counts_loaded": test_target_counts_loaded,
        "do_holdout_eval": bool(do_holdout),
        "cv_folds": int(n_splits),
        "methods": methods,
        "models": model_order,
        "results_rows": int(len(results_df)),
        "results_columns": [str(c) for c in results_df.columns],
        "results_table": _results_table_for_report(results_df),
        "best_by_cv_f1_attack": best_row,
        "best_by_holdout_f1_attack": best_holdout_row,
        "best_by_preferred_metric": best_preferred_row,
        "best_selection_policy": best_pack.get("policy"),
        "training_quality_warnings": quality_warnings,
        "airc_leakage_aware": True,
        "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
        "forbidden_features_after_prep": forbidden_after_prep,
        "logical_cpu": int(_LOGICAL_CPU),
        "worker_threads": int(_WORKER_THREADS),
        "inner_math_threads": int(_INNER_MATH_THREADS),
        "rfc_n_jobs": int(cfg.rfc_n_jobs),
        "lsvc_max_iter": int(cfg.lsvc_max_iter),
        "xgb_available": bool(XGBClassifier is not None),
        "xgb_device": str(cfg.xgb_device),
        "xgb_tree_method": str(cfg.xgb_tree_method),
        "paths": {
            "results_csv": str(results_csv_path) if cfg.write_artifacts else None,
            "summary_json": str(summary_path) if cfg.write_artifacts else None,
            "checkpoint_root": str(_checkpoint_root(out_app_dir)),
            "model_summaries": model_summary_paths,
        },
        "write_output": bool(cfg.write_artifacts),
        "seconds": float(elapsed),
        "elapsed_human": _fmt_elapsed(elapsed),
        "note": (
            "RAM-mode Phase 13 trains models directly from df_train/df_test returned by Phase 11. "
            "It applies a final leakage/shortcut feature guard before fitting. KNN is intentionally excluded."
        ),
    }
    if cfg.write_artifacts:
        _json_dump(summary, summary_path)
        _json_dump(summary, metrics_dir / f"phase13_train_summary_{app}.json")

    print(f"✅ Phase 13 RAM complete app={app}")
    print(f"   Results rows : {len(results_df):,}")
    print(f"   Best preferred: {best_preferred_row}")
    if quality_warnings:
        print("   ⚠️ Warnings   : " + " | ".join(quality_warnings[:2]))
    print(f"   Output       : {out_app_dir}")
    print(f"   Time         : {_fmt_elapsed(elapsed)}")
    gc.collect()
    return results_df, summary


# RAM-mode aliases for pipeline integration.
def phase13_train_and_evaluate_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase13TrainConfig] = None,
    phase12_result: Optional[Dict[str, Any]] = None,
    feature_sets: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase13_train_ram(df_train, df_test, app=app, cfg=cfg, phase12_result=phase12_result, feature_sets=feature_sets)


def run_phase13_train_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str,
    cfg: Optional[Phase13TrainConfig] = None,
    phase12_result: Optional[Dict[str, Any]] = None,
    feature_sets: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    return phase13_train_ram(df_train, df_test, app=app, cfg=cfg, phase12_result=phase12_result, feature_sets=feature_sets)


# Compatibility aliases.
def phase13_train_and_evaluate(
    *,
    cfg: Phase13TrainConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase13_train(cfg=cfg)


def build_phase13_train(
    *,
    cfg: Phase13TrainConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    return phase13_train(cfg=cfg)


if __name__ == "__main__":
    results, summary = phase13_train(
        cfg=Phase13TrainConfig(
            modeling_dir=Path("results/modeling"),
            phase12_dir=Path("results/phase12_fs"),
            output_dir=Path("results/phase13_train"),
            selected_apps=("dns", "http", "tls", "ssh"),
            target_col="Target",
            filename_tag="run",
            methods=("MI", "RFE", "PCA"),
            models=("DT", "RFC", "LSVC", "XGB"),
            train_rows=800_000,
            test_rows=200_000,
            sample_mode="stratified_balanced",
            default_n_splits=2,
            do_holdout_eval=True,
            parquet_engine="fastparquet",
            overwrite=False,
        )
    )
    print(json.dumps(summary, indent=2, default=str))