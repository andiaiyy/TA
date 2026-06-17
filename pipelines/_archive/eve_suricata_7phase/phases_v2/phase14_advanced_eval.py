# src/cbr/phases/phase14_advanced_eval.py
from __future__ import annotations

import gc
import json
import math
import os
import shutil
import time
import traceback
from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

from sklearn.base import clone
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import auc, confusion_matrix, roc_curve
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier

try:
    from xgboost import XGBClassifier  # type: ignore
except Exception:
    XGBClassifier = None

try:
    from threadpoolctl import threadpool_limits  # type: ignore
except Exception:
    threadpool_limits = None


# -------------------------------------------------------------------------
# CPU / thread defaults
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


# =============================================================================
# PHASE 14: ADVANCED EVALUATION (APP-AWARE, SHARDED-SAFE)
# =============================================================================
# Purpose:
#   Generate per-application advanced evaluation artifacts after Phase 13:
#     - ROC curves by feature-selection method
#     - ROC/AUC summary JSON
#     - model performance comparison plot from Phase 13 results
#     - confusion matrix for best model
#
# Input:
#   results/modeling/app={app}/train/part-*.parquet
#   results/modeling/app={app}/test/part-*.parquet
#   results/phase12_fs/app={app}/phase12_feature_sets_{app}_{tag}.json
#   results/phase13_train/app={app}/results_comparison_{app}_{tag}.csv
#
# Output:
#   results/phase14_advanced_eval/app={app}/
#     roc_curves_{app}_{tag}.png
#     model_performance_comparison_{app}_{tag}.png
#     confusion_matrix_best_model_{app}_{tag}.png
#     roc_auc_summary_{app}_{tag}.json
#     phase14_summary_{app}_{tag}.json
#
#   results/phase14_advanced_eval/metrics/
#     phase14_advanced_eval_summary_{app}.json
#     phase14_advanced_eval_summary_all.json
#     phase14_advanced_eval_summary_by_app.csv
#
# Notes:
#   - This phase retrains bounded evaluation models because Phase 13 does not
#     necessarily save fitted model objects.
#   - This phase is visualization/evaluation-oriented and should use bounded
#     samples from Phase 11 train/test shards.
#   - KNN is intentionally excluded from default models because it is impractical
#     for this large-scale pipeline.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")
DEFAULT_METHODS: Tuple[str, ...] = ("MI", "RFE", "PCA")
DEFAULT_MODELS: Tuple[str, ...] = ("DT", "RFC", "LSVC", "XGB")


# Extra guard for AIRC / leakage-aware reporting.
# These columns may be useful for audit/visualization, but they must not be used
# as direct model inputs because they encode labels, alert presence, probing
# decisions, or identifiers that can create shortcut learning.
DEFAULT_AIRC_EXTRA_DROP_COLS: Tuple[str, ...] = (
    # Target / staging labels
    "Target_prelim",
    "is_malicious",

    # Raw identifiers / grouping fields
    "timestamp",
    "src_ip",
    "dest_ip",
    "flow_id",
    "community_id",
    "pkt_src",
    "tx_id",
    "window_start",
    "window_start_h",
    "first_seen",
    "last_seen",
    "src_subnet24_h",
    "dest_subnet24_h",

    # Event / alert-derived shortcuts
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
    "alert_count_window",

    # Phase 1/4 label explanation / evidence fields
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

    # Probing direct shortcuts
    "probe_score",
    "probe_reason",
    "probe_reason_h",
    "is_possible_probe",
    "is_probe_suspicious",
    "target_prelim_malicious_count",
)


# =============================================================================
# Config
# =============================================================================

@dataclass(frozen=True)
class Phase14AdvancedEvalConfig:
    modeling_dir: Path = Path("results/modeling")
    phase12_dir: Path = Path("results/phase12_fs")
    phase13_dir: Path = Path("results/phase13_train")
    output_dir: Path = Path("results/phase14_advanced_eval")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    target_col: str = "Target"
    seed: int = 42
    filename_tag: str = "run"

    methods: Tuple[str, ...] = DEFAULT_METHODS
    models_for_roc: Tuple[str, ...] = DEFAULT_MODELS

    # Bounded evaluation samples.
    train_rows: Optional[int] = 500_000
    test_rows: Optional[int] = 200_000
    sample_mode: str = "stratified_balanced"  # "stratified_balanced" | "stratified_proportional" | "random"

    # If no test shards exist or test sample invalid, create internal split from train sample.
    internal_test_size: float = 0.20

    # Model params
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

    # Best model selection based on Phase 13 results.
    best_metric_preference: Tuple[str, ...] = (
        "holdout_f1_attack",
        "f1_attack",
        "holdout_auc",
        "auc",
        "holdout_accuracy",
        "accuracy",
    )

    # AIRC / leakage-aware safety guard. Phase 11 and 12 should already remove
    # these, but Phase 14 retrains evaluation models, so it applies one final
    # defensive drop before ROC/confusion-matrix generation.
    strict_leakage_guard: bool = True
    drop_probe_direct_features: bool = True
    drop_label_explanation_features: bool = True
    drop_alert_derived_features: bool = True

    # In alert_only mode, probing window aggregates can remain as behavioral
    # features. They only become forbidden shortcuts when probing is also used
    # to construct Target.
    use_probing_as_label: bool = False
    drop_probe_window_features_when_labelled: bool = True

    extra_drop_cols: Tuple[str, ...] = DEFAULT_AIRC_EXTRA_DROP_COLS

    # Evaluation-quality warnings. These do not stop the run; they make the
    # summary/report more honest when scores look too perfect.
    perfect_score_warning_threshold: float = 0.999
    warn_on_internal_split: bool = True

    # Prediction batching avoids memory spikes for large test samples.
    predict_batch_rows: int = 200_000

    # IO
    parquet_engine: Optional[str] = "fastparquet"
    write_artifacts: bool = True
    overwrite: bool = True

    # Stability
    blas_thread_limit: int = _INNER_MATH_THREADS
    gc_each_model: bool = True


# =============================================================================
# General helpers
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


def _file_size_bytes(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


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


def _to_numeric_safe(s: pd.Series) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    return x.replace([np.inf, -np.inf], np.nan).fillna(0)


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        raise RuntimeError(f"Missing target column: {target_col}")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


def _counter_to_str_dict(c: Counter) -> Dict[str, int]:
    return {str(k): int(v) for k, v in c.items()}


# =============================================================================
# Feature set / results loaders
# =============================================================================

def _find_phase12_feature_sets(cfg: Phase14AdvancedEvalConfig, app: str) -> Optional[Path]:
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


def _load_feature_sets(cfg: Phase14AdvancedEvalConfig, app: str) -> Tuple[Dict[str, Any], Optional[Path]]:
    path = _find_phase12_feature_sets(cfg, app)
    if path is None:
        raise RuntimeError(f"Phase 12 feature_sets JSON not found for app={app} in {cfg.phase12_dir}")

    obj = _json_load(path)
    fs = obj.get("feature_sets", obj) if isinstance(obj, dict) else obj
    if not isinstance(fs, dict):
        raise RuntimeError(f"Invalid Phase 12 feature_sets JSON for app={app}: {path}")

    return fs, path


def _find_phase13_results_csv(cfg: Phase14AdvancedEvalConfig, app: str) -> Optional[Path]:
    app = str(app).strip().lower()
    tag = cfg.filename_tag.strip() or "run"

    app_dirs = [
        Path(cfg.phase13_dir) / f"app={app}",
        Path(cfg.phase13_dir) / app,
    ]

    candidates = [
        f"results_comparison_{app}_{tag}.csv",
        f"results_comparison_{app}.csv",
        f"results_comparison_{tag}.csv",
        "results_comparison.csv",
    ]

    for d in app_dirs:
        for name in candidates:
            p = d / name
            if p.exists():
                return p
        matches = sorted(d.glob("results_comparison*.csv"))
        if matches:
            return matches[0]

    return None


def _load_phase13_results(cfg: Phase14AdvancedEvalConfig, app: str) -> Tuple[pd.DataFrame, Optional[Path]]:
    path = _find_phase13_results_csv(cfg, app)
    if path is None:
        return pd.DataFrame(), None

    try:
        return pd.read_csv(path), path
    except Exception:
        return pd.DataFrame(), path


# =============================================================================
# Streaming sample from train/test shards
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
    cfg: Phase14AdvancedEvalConfig,
    app: str,
    split: str,
) -> Dict[str, Any]:
    rows_seen = 0
    bytes_seen = 0
    target_counter: Counter = Counter()

    for fp in tqdm(shard_files, desc=f"PHASE 14 scan {app}/{split}", unit="shard", dynamic_ncols=True):
        bytes_seen += _file_size_bytes(fp)
        df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
        if df is None or df.empty:
            continue

        rows_seen += int(len(df))
        y = _target_series(df, cfg.target_col)
        target_counter.update(y.astype(int).tolist())

        del df
        gc.collect()

    return {
        "rows_seen": int(rows_seen),
        "bytes_seen": int(bytes_seen),
        "target_counts": target_counter,
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

        remaining = n_take - (take0 + take1)
        if remaining > 0:
            add0 = min(remaining, n0 - take0)
            take0 += add0
            remaining -= add0
        if remaining > 0:
            add1 = min(remaining, n1 - take1)
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
    cfg: Phase14AdvancedEvalConfig,
    app: str,
    split: str,
    n_rows: Optional[int],
    target_counts: Counter,
) -> pd.DataFrame:
    total = int(sum(target_counts.values()))
    if n_rows is None or int(n_rows) <= 0:
        parts: List[pd.DataFrame] = []
        for fp in tqdm(shard_files, desc=f"PHASE 14 load full {app}/{split}", unit="shard", dynamic_ncols=True):
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
        for fp in tqdm(shard_files, desc=f"PHASE 14 sample {app}/{split}", unit="shard", dynamic_ncols=True):
            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is None or df.empty:
                continue
            sampler.add(df)
            del df
            gc.collect()
        return sampler.dataframe()

    plan = _sample_plan(target_counts, n_take, mode)
    samplers = {
        int(k): _ReservoirSampler(v, seed=int(cfg.seed) + int(k) * 41 + abs(hash((app, split))) % 100_000)
        for k, v in plan.items()
    }

    for fp in tqdm(shard_files, desc=f"PHASE 14 sample {app}/{split}", unit="shard", dynamic_ncols=True):
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
# Leakage-aware feature guard
# =============================================================================

def _forbidden_feature_cols(cols: Sequence[str], cfg: Phase14AdvancedEvalConfig) -> List[str]:
    """Return model-input columns that should not be used in leakage-aware evaluation."""
    target_col = str(getattr(cfg, "target_col", "Target"))
    strict = bool(getattr(cfg, "strict_leakage_guard", True))
    drop_probe = bool(getattr(cfg, "drop_probe_direct_features", True))
    drop_label = bool(getattr(cfg, "drop_label_explanation_features", True))
    drop_alert = bool(getattr(cfg, "drop_alert_derived_features", True))
    extra = {str(c) for c in getattr(cfg, "extra_drop_cols", DEFAULT_AIRC_EXTRA_DROP_COLS) if str(c).strip()}
    extra_low = {c.lower() for c in extra}

    out: List[str] = []
    for col in cols:
        c = str(col)
        cl = c.lower()
        if c == target_col:
            continue

        forbidden = False
        if strict and (c in extra or cl in extra_low or c.endswith("_raw")):
            forbidden = True

        if drop_alert:
            forbidden = forbidden or cl == "has_alert" or cl.startswith("alert_") or cl in {
                "event_type", "event_type_h", "event_type_raw", "target_prelim", "target_prelim_malicious_count",
                "alert_count_window",
            }

        if drop_label:
            forbidden = forbidden or cl.startswith("label_") or cl.startswith("evidence_") or cl in {
                "label_status", "label_status_h", "label_status_final", "label_source", "label_confidence",
            }

        if drop_probe:
            # Direct probe decisions/scores are shortcuts. Window aggregates are
            # handled separately below so they can remain behavioral features in
            # alert_only mode.
            forbidden = forbidden or cl.startswith("probe_") or cl in {
                "is_possible_probe", "is_probe_suspicious", "window_start", "window_start_h",
            }

        if (
            strict
            and bool(getattr(cfg, "use_probing_as_label", False))
            and bool(getattr(cfg, "drop_probe_window_features_when_labelled", True))
        ):
            forbidden = forbidden or cl in {
                "event_count_window", "unique_dest_ip_window", "unique_dest_port_window",
                "total_bytes_window", "total_pkts_window", "bytes_per_event_window", "pkts_per_event_window",
                "first_seen", "last_seen",
            }

        if forbidden and c not in out:
            out.append(c)

    return out


def _drop_forbidden_features(df: pd.DataFrame, cfg: Phase14AdvancedEvalConfig) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if df is None or df.empty:
        return pd.DataFrame(), {"dropped_forbidden_features": [], "dropped_forbidden_count": 0}

    forbidden = _forbidden_feature_cols(df.columns.tolist(), cfg)
    out = df.drop(columns=[c for c in forbidden if c in df.columns], errors="ignore").copy()
    info = {
        "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
        "drop_probe_direct_features": bool(getattr(cfg, "drop_probe_direct_features", True)),
        "drop_label_explanation_features": bool(getattr(cfg, "drop_label_explanation_features", True)),
        "drop_alert_derived_features": bool(getattr(cfg, "drop_alert_derived_features", True)),
        "dropped_forbidden_features": forbidden,
        "dropped_forbidden_count": int(len(forbidden)),
    }
    return out, info


def _max_auc_from_auc_summary(auc_only: Dict[str, Dict[str, Dict[str, float]]]) -> float:
    best = 0.0
    try:
        for method_data in (auc_only or {}).values():
            if not isinstance(method_data, dict):
                continue
            for item in method_data.values():
                if isinstance(item, dict):
                    best = max(best, float(item.get("auc", 0.0) or 0.0))
    except Exception:
        return best
    return float(best)


def _phase14_quality_warnings(
    *,
    use_holdout: bool,
    auc_only: Dict[str, Dict[str, Dict[str, float]]],
    cm_info: Dict[str, Any],
    forbidden_features_after_prep: Sequence[str],
    results_df: pd.DataFrame,
    cfg: Phase14AdvancedEvalConfig,
) -> List[str]:
    warnings: List[str] = []
    threshold = float(getattr(cfg, "perfect_score_warning_threshold", 0.999))

    if bool(getattr(cfg, "warn_on_internal_split", True)) and not use_holdout:
        warnings.append(
            "Phase 14 used an internal split from the training sample because the holdout/test sample was unavailable or unusable. "
            "Treat the evaluation as diagnostic, not final generalization evidence."
        )

    if forbidden_features_after_prep:
        warnings.append(
            "Forbidden leakage-prone features were still present after numeric preparation and should be reviewed: "
            + ", ".join(map(str, forbidden_features_after_prep[:20]))
        )

    max_auc = _max_auc_from_auc_summary(auc_only)
    if max_auc >= threshold:
        warnings.append(
            f"At least one ROC AUC is >= {threshold:.3f}. This can be valid, but in this project it should trigger leakage/split review before being claimed as final."
        )

    if isinstance(cm_info, dict) and cm_info.get("status") == "completed":
        try:
            fp = int(cm_info.get("fp", 0))
            fn = int(cm_info.get("fn", 0))
            total = int(cm_info.get("tn", 0)) + fp + fn + int(cm_info.get("tp", 0))
            if total > 0 and fp == 0 and fn == 0:
                warnings.append(
                    "The confusion matrix is perfect (FP=0 and FN=0). Verify that alert/label/probe-derived shortcuts and source/time overlap were removed."
                )
        except Exception:
            pass

    if isinstance(results_df, pd.DataFrame) and not results_df.empty:
        for col in ("holdout_f1_attack", "f1_attack", "holdout_auc", "auc", "accuracy"):
            if col in results_df.columns:
                vals = pd.to_numeric(results_df[col], errors="coerce")
                if vals.notna().any() and float(vals.max()) >= threshold:
                    warnings.append(
                        f"Phase 13 result column '{col}' contains values >= {threshold:.3f}; report this as leakage-aware diagnostic output unless stricter validation is passed."
                    )
                    break

    return warnings

# =============================================================================
# Numeric prep
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


def _prepare_numeric_Xy(df: pd.DataFrame, cfg: Phase14AdvancedEvalConfig) -> Tuple[pd.DataFrame, pd.Series]:
    if cfg.target_col not in df.columns:
        raise RuntimeError(f"Missing target column '{cfg.target_col}'.")

    y = _target_series(df, cfg.target_col)
    vc = y.value_counts()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class: {vc.to_dict()}")

    X_all = df.drop(columns=[cfg.target_col], errors="ignore").copy()
    if X_all.empty:
        raise RuntimeError("No feature columns left after dropping target.")

    X_all, leakage_guard_info = _drop_forbidden_features(X_all, cfg)
    if X_all.empty:
        raise RuntimeError("No feature columns left after leakage-aware feature guard.")

    kept_cols: List[str] = []
    X_num = pd.DataFrame(index=X_all.index)

    for c in X_all.columns:
        s_num = _series_to_numeric_like(X_all[c])
        if s_num.notna().sum() > 0:
            X_num[c] = s_num.replace([np.inf, -np.inf], np.nan).fillna(0)
            kept_cols.append(c)

    if not kept_cols:
        raise RuntimeError("No numeric/numeric-like columns available after coercion.")

    X_out = X_num[kept_cols]
    X_out.attrs["leakage_guard"] = leakage_guard_info
    X_out.attrs["forbidden_features_after_prep"] = _forbidden_feature_cols(X_out.columns.tolist(), cfg)
    return X_out, y


def _align_test_to_train(X_test_all: pd.DataFrame, train_cols: Sequence[str]) -> pd.DataFrame:
    out = X_test_all.copy()
    for c in train_cols:
        if c not in out.columns:
            out[c] = 0
    out = out[list(train_cols)].copy()
    for c in out.columns:
        out[c] = _series_to_numeric_like(out[c]).replace([np.inf, -np.inf], np.nan).fillna(0)
    return out


# =============================================================================
# Model / prediction helpers
# =============================================================================

def _safe_score_vector(estimator, X: pd.DataFrame) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        p = np.asarray(estimator.predict_proba(X))
        if p.ndim == 2 and p.shape[1] >= 2:
            return p[:, 1]
        return p.ravel()

    if hasattr(estimator, "decision_function"):
        return np.asarray(estimator.decision_function(X)).ravel()

    return np.asarray(estimator.predict(X)).astype(float)


def _iter_df_batches(X: pd.DataFrame, batch_rows: int) -> Iterable[Tuple[int, int, pd.DataFrame]]:
    n = len(X)
    if batch_rows <= 0 or batch_rows >= n:
        yield (0, n, X)
        return

    for start in range(0, n, batch_rows):
        end = min(n, start + batch_rows)
        yield (start, end, X.iloc[start:end])


def _scores_batched(estimator, X: pd.DataFrame, *, batch_rows: int) -> np.ndarray:
    n = len(X)
    out = np.empty(n, dtype=np.float32)
    for start, end, Xb in _iter_df_batches(X, batch_rows):
        out[start:end] = _safe_score_vector(estimator, Xb).astype(np.float32, copy=False)
    return out.astype(float)


def _predict_batched(estimator, X: pd.DataFrame, *, batch_rows: int) -> np.ndarray:
    n = len(X)
    out = np.empty(n, dtype=np.int64)
    for start, end, Xb in _iter_df_batches(X, batch_rows):
        out[start:end] = np.asarray(estimator.predict(Xb), dtype=np.int64)
    return out


def _build_models(cfg: Phase14AdvancedEvalConfig) -> Dict[str, Any]:
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
            C=float(cfg.lsvc_c),
            max_iter=int(cfg.lsvc_max_iter),
            dual=cfg.lsvc_dual,
            random_state=cfg.seed,
        ),
    }

    if XGBClassifier is not None:
        models["XGB"] = XGBClassifier(
            n_estimators=int(cfg.xgb_n_estimators),
            max_depth=int(cfg.xgb_max_depth),
            learning_rate=float(cfg.xgb_learning_rate),
            subsample=float(cfg.xgb_subsample),
            colsample_bytree=float(cfg.xgb_colsample_bytree),
            reg_lambda=float(cfg.xgb_reg_lambda),
            n_jobs=int(cfg.xgb_n_jobs),
            tree_method=str(cfg.xgb_tree_method),
            device=str(cfg.xgb_device),
            eval_metric=str(cfg.xgb_eval_metric),
            random_state=cfg.seed,
        )

    return models


def _build_estimator(
    method: str,
    model_name: str,
    models: Dict[str, Any],
    n_components: int,
    cfg: Phase14AdvancedEvalConfig,
):
    if model_name not in models:
        raise RuntimeError(f"Requested model '{model_name}' is not available.")

    base = clone(models[model_name])
    method = str(method).upper()

    if method in {"MI", "RFE"}:
        if model_name == "LSVC":
            return Pipeline([("scaler", StandardScaler()), ("model", base)])
        return base

    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=int(n_components), random_state=cfg.seed)),
        ("model", base),
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


def _pick_best_row(results_df: pd.DataFrame, prefer: Tuple[str, ...]) -> Optional[pd.Series]:
    if results_df is None or results_df.empty:
        return None

    metric = None
    for m in prefer:
        if m in results_df.columns:
            metric = m
            break

    if metric is None:
        return None

    s = pd.to_numeric(results_df[metric], errors="coerce")
    if s.isna().all():
        return None

    idx = s.idxmax()
    return results_df.loc[idx]


# =============================================================================
# Plot helpers
# =============================================================================

def _plot_performance_comparison(
    results_df: pd.DataFrame,
    *,
    app: str,
    tag: str,
    out_path: Path,
) -> Dict[str, Any]:
    if results_df is None or results_df.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "Phase 13 results are unavailable", ha="center", va="center")
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(out_path, dpi=250, bbox_inches="tight")
        plt.close(fig)
        return {"status": "empty_results_df"}

    def pick_col(primary: str, fallback: str) -> Optional[str]:
        if primary in results_df.columns:
            return primary
        if fallback in results_df.columns:
            return fallback
        return None

    acc_col = pick_col("accuracy", "acc")
    f1_col = pick_col("f1_attack", "f1")
    auc_col = pick_col("auc", "roc_auc")

    if not acc_col and not f1_col and not auc_col:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No supported metric columns in Phase 13 results", ha="center", va="center")
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(out_path, dpi=250, bbox_inches="tight")
        plt.close(fig)
        return {"status": "no_metric_columns"}

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Model Performance Comparison - {app.upper()} ({tag})", fontsize=14, fontweight="bold")

    methods = results_df["Method"].dropna().astype(str).unique().tolist() if "Method" in results_df.columns else []

    ax = axes[0, 0]
    if acc_col and methods:
        for m in methods:
            d = results_df[results_df["Method"].astype(str) == str(m)]
            ax.plot(d["Model"].astype(str).values, pd.to_numeric(d[acc_col], errors="coerce").values, marker="o", linewidth=2.0, label=m)
        ax.set_ylabel("Accuracy", fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title("Accuracy")
    else:
        ax.text(0.5, 0.5, "Accuracy unavailable", ha="center", va="center")
        ax.axis("off")

    ax = axes[0, 1]
    if f1_col and methods:
        for m in methods:
            d = results_df[results_df["Method"].astype(str) == str(m)]
            ax.plot(d["Model"].astype(str).values, pd.to_numeric(d[f1_col], errors="coerce").values, marker="s", linewidth=2.0, label=m)
        ax.set_ylabel("F1 (Attack)", fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title("F1 (Attack)")
    else:
        ax.text(0.5, 0.5, "F1 unavailable", ha="center", va="center")
        ax.axis("off")

    ax = axes[1, 0]
    if auc_col and methods:
        for m in methods:
            d = results_df[results_df["Method"].astype(str) == str(m)]
            ax.plot(d["Model"].astype(str).values, pd.to_numeric(d[auc_col], errors="coerce").values, marker="^", linewidth=2.0, label=m)
        ax.set_ylabel("AUC-ROC", fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title("AUC-ROC")
    else:
        ax.text(0.5, 0.5, "AUC unavailable", ha="center", va="center")
        ax.axis("off")

    ax = axes[1, 1]
    heat_col = acc_col or f1_col or auc_col
    if heat_col and "Method" in results_df.columns and "Model" in results_df.columns:
        heat = results_df.pivot_table(values=heat_col, index="Method", columns="Model", aggfunc="mean")
        im = ax.imshow(heat.values, aspect="auto")
        fig.colorbar(im, ax=ax, label=heat_col)
        ax.set_xticks(range(len(heat.columns)))
        ax.set_xticklabels(heat.columns)
        ax.set_yticks(range(len(heat.index)))
        ax.set_yticklabels(heat.index)
        for (ii, jj), val in np.ndenumerate(heat.values):
            ax.text(jj, ii, f"{val:.4f}", ha="center", va="center", fontsize=9)
        ax.set_title(f"{heat_col} Heatmap")
    else:
        ax.text(0.5, 0.5, "Heatmap unavailable", ha="center", va="center")
        ax.axis("off")

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=250, bbox_inches="tight")
    plt.close(fig)

    return {
        "status": "completed",
        "metric_columns": {
            "accuracy": acc_col,
            "f1_attack": f1_col,
            "auc": auc_col,
        },
    }


def _plot_confusion_matrix(
    cm: np.ndarray,
    *,
    title: str,
    out_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cm)
    fig.colorbar(im, ax=ax, label="Count")

    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Benign", "Attack"])
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Benign", "Attack"])

    for (ii, jj), val in np.ndenumerate(cm):
        ax.text(jj, ii, str(int(val)), ha="center", va="center", fontsize=12)

    ax.set_ylabel("True Label", fontweight="bold")
    ax.set_xlabel("Predicted Label", fontweight="bold")
    ax.set_title(title, fontweight="bold")

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=250, bbox_inches="tight")
    plt.close(fig)


# =============================================================================
# Public API
# =============================================================================

def phase14_advanced_eval_for_app(
    app: str,
    *,
    cfg: Phase14AdvancedEvalConfig,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    app = str(app).strip().lower()
    tag = cfg.filename_tag.strip() or "run"
    t0 = time.perf_counter()

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    roc_png = out_app_dir / f"roc_curves_{app}_{tag}.png"
    perf_png = out_app_dir / f"model_performance_comparison_{app}_{tag}.png"
    cm_png = out_app_dir / f"confusion_matrix_best_model_{app}_{tag}.png"
    auc_json = out_app_dir / f"roc_auc_summary_{app}_{tag}.json"
    meta_json = out_app_dir / f"phase14_summary_{app}_{tag}.json"

    train_shards = _list_split_shards(cfg.modeling_dir, app, "train")
    test_shards = _list_split_shards(cfg.modeling_dir, app, "test")

    if not train_shards:
        summary = {
            "phase": 14,
            "app": app,
            "status": "skipped_no_train_shards",
            "modeling_dir": str(cfg.modeling_dir),
            "output_dir": str(out_app_dir),
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase14_advanced_eval_summary_{app}.json")
        return {}, summary

    print(f"\n📈 PHASE 14: Advanced evaluation for app={app}")
    print(f"   Train shards : {len(train_shards):,}")
    print(f"   Test shards  : {len(test_shards):,}")
    print(f"   Output       : {out_app_dir}")

    feature_sets, feature_sets_path = _load_feature_sets(cfg, app)
    results_df, results_csv_path = _load_phase13_results(cfg, app)

    train_scan = _scan_split_counts(train_shards, cfg=cfg, app=app, split="train")
    test_scan = _scan_split_counts(test_shards, cfg=cfg, app=app, split="test") if test_shards else {
        "rows_seen": 0,
        "bytes_seen": 0,
        "target_counts": Counter(),
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
        raise RuntimeError(f"Phase 14 train sample is empty for app={app}.")

    df_test = pd.DataFrame()
    use_holdout = False

    if test_shards:
        df_test = _load_split_sample(
            test_shards,
            cfg=cfg,
            app=app,
            split="test",
            n_rows=cfg.test_rows,
            target_counts=test_scan["target_counts"],
        )

    X_train_num, y_train = _prepare_numeric_Xy(df_train, cfg)
    train_leakage_guard = X_train_num.attrs.get("leakage_guard", {})
    forbidden_features_after_prep = X_train_num.attrs.get("forbidden_features_after_prep", _forbidden_feature_cols(X_train_num.columns.tolist(), cfg))

    if not df_test.empty:
        try:
            X_test_all, y_test = _prepare_numeric_Xy(df_test, cfg)
            X_test_num = _align_test_to_train(X_test_all, X_train_num.columns.tolist())
            use_holdout = bool(y_test.nunique(dropna=True) >= 2)
            if not use_holdout:
                raise RuntimeError("test sample has one class")
        except Exception as e:
            print(f"   ⚠️ Holdout sample unusable for app={app}; internal split fallback: {e!r}")
            use_holdout = False
            X_test_num = None
            y_test = None
    else:
        X_test_num = None
        y_test = None

    if not use_holdout:
        X_train_num, X_test_num, y_train, y_test = train_test_split(
            X_train_num,
            y_train,
            test_size=float(cfg.internal_test_size),
            random_state=int(cfg.seed),
            stratify=y_train,
        )

    assert X_test_num is not None and y_test is not None

    train_dist = {str(k): int(v) for k, v in pd.Series(y_train).value_counts().to_dict().items()}
    test_dist = {str(k): int(v) for k, v in pd.Series(y_test).value_counts().to_dict().items()}

    models = _build_models(cfg)
    models_for_roc = [str(m).upper() for m in cfg.models_for_roc if str(m).upper() in models]
    missing_models = [str(m).upper() for m in cfg.models_for_roc if str(m).upper() not in models]

    if missing_models:
        print(f"   ⚠️ Models unavailable and skipped: {missing_models}")

    methods = [str(m).upper() for m in cfg.methods]
    total_jobs = max(1, len(methods) * max(1, len(models_for_roc)))

    roc_results_full: Dict[str, Dict[str, Dict[str, Any]]] = {}
    auc_only: Dict[str, Dict[str, Dict[str, float]]] = {}

    fig, axes = plt.subplots(1, len(methods), figsize=(6 * len(methods), 5))
    if len(methods) == 1:
        axes = [axes]
    fig.suptitle(f"ROC Curves - {app.upper()} ({tag})", fontsize=14, fontweight="bold")

    done = 0
    failed_jobs: List[Dict[str, Any]] = []

    for i, method in enumerate(methods):
        ax = axes[i]
        roc_results_full[method] = {}
        auc_only[method] = {}

        feature_list, n_comp = _get_method_features(
            method,
            feature_sets,
            X_train_num.columns.tolist(),
            cfg.pca_default_n_components,
        )

        if method in {"MI", "RFE"}:
            if not feature_list:
                ax.set_title(f"{method} (no usable features)")
                ax.axis("off")
                for model_name in models_for_roc:
                    auc_only[method][model_name] = {"auc": 0.5}
                    roc_results_full[method][model_name] = {"fpr": [0.0, 1.0], "tpr": [0.0, 1.0], "auc": 0.5}
                continue

            X_tr_m = X_train_num[feature_list].copy()
            X_te_m = X_test_num[feature_list].copy()
        elif method == "PCA":
            X_tr_m = X_train_num.copy()
            X_te_m = X_test_num.copy()
            n_comp = max(1, min(int(n_comp), int(X_tr_m.shape[1]), max(1, int(len(X_tr_m)) - 1)))
        else:
            ax.set_title(f"{method} (unknown)")
            ax.axis("off")
            continue

        for model_name in models_for_roc:
            done += 1
            print(f"   ROC {done}/{total_jobs}: {method}/{model_name}")

            try:
                est = _build_estimator(method, model_name, models, n_comp, cfg)

                with _limit_threads(cfg.blas_thread_limit):
                    est.fit(X_tr_m, y_train)

                scores = _scores_batched(
                    est,
                    X_te_m,
                    batch_rows=int(cfg.predict_batch_rows),
                )

                fpr, tpr, _ = roc_curve(y_test, scores)
                roc_auc = auc(fpr, tpr)

                roc_results_full[method][model_name] = {
                    "fpr": [float(x) for x in fpr],
                    "tpr": [float(x) for x in tpr],
                    "auc": float(roc_auc),
                }
                auc_only[method][model_name] = {"auc": float(roc_auc)}

                ax.plot(fpr, tpr, linewidth=2.0, label=f"{model_name} (AUC={roc_auc:.4f})")

                if cfg.gc_each_model:
                    del est
                    gc.collect()

            except Exception as e:
                failed_jobs.append({
                    "method": method,
                    "model": model_name,
                    "error": repr(e),
                })
                roc_results_full[method][model_name] = {"fpr": [0.0, 1.0], "tpr": [0.0, 1.0], "auc": 0.5}
                auc_only[method][model_name] = {"auc": 0.5}
                print(f"      ⚠️ failed {method}/{model_name}: {e!r}")

        ax.plot([0, 1], [0, 1], "k--", linewidth=1.0, label="Random")
        ax.set_xlabel("False Positive Rate", fontweight="bold")
        ax.set_ylabel("True Positive Rate", fontweight="bold")
        ax.set_title(method, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)

    plt.tight_layout()
    if cfg.write_artifacts:
        plt.savefig(roc_png, dpi=250, bbox_inches="tight")
    plt.close(fig)

    # Performance comparison from Phase 13.
    perf_info = _plot_performance_comparison(
        results_df,
        app=app,
        tag=tag,
        out_path=perf_png,
    )

    # Best model for confusion matrix.
    best = _pick_best_row(results_df, cfg.best_metric_preference)
    if best is not None and "Method" in best and "Model" in best:
        best_method = str(best["Method"]).upper()
        best_model = str(best["Model"]).upper()
    else:
        # Fallback: choose highest ROC AUC from Phase 14 results.
        best_method = "PCA"
        best_model = "RFC"
        best_auc = -1.0
        for method, d in auc_only.items():
            for model_name, item in d.items():
                val = float(item.get("auc", 0.5))
                if val > best_auc:
                    best_auc = val
                    best_method = str(method).upper()
                    best_model = str(model_name).upper()

    if best_model not in models:
        best_model = "RFC" if "RFC" in models else next(iter(models.keys()))

    feature_list, n_comp = _get_method_features(
        best_method,
        feature_sets,
        X_train_num.columns.tolist(),
        cfg.pca_default_n_components,
    )

    if best_method in {"MI", "RFE"} and feature_list:
        X_tr_best = X_train_num[feature_list].copy()
        X_te_best = X_test_num[feature_list].copy()
    else:
        X_tr_best = X_train_num.copy()
        X_te_best = X_test_num.copy()
        n_comp = max(1, min(int(n_comp), int(X_tr_best.shape[1]), max(1, int(len(X_tr_best)) - 1)))

    cm_info: Dict[str, Any] = {}
    try:
        est_best = _build_estimator(best_method, best_model, models, n_comp, cfg)
        with _limit_threads(cfg.blas_thread_limit):
            est_best.fit(X_tr_best, y_train)

        y_pred = _predict_batched(
            est_best,
            X_te_best,
            batch_rows=int(cfg.predict_batch_rows),
        )

        cm = confusion_matrix(y_test, y_pred, labels=[0, 1])

        _plot_confusion_matrix(
            cm,
            title=f"Confusion Matrix - {app.upper()} - {best_model} ({best_method})",
            out_path=cm_png,
        )

        cm_info = {
            "status": "completed",
            "best_method": best_method,
            "best_model": best_model,
            "confusion_matrix": cm.astype(int).tolist(),
            "tn": int(cm[0, 0]),
            "fp": int(cm[0, 1]),
            "fn": int(cm[1, 0]),
            "tp": int(cm[1, 1]),
        }
    except Exception as e:
        cm_info = {
            "status": "failed",
            "best_method": best_method,
            "best_model": best_model,
            "error": repr(e),
        }
        print(f"   ⚠️ Confusion matrix failed: {e!r}")

    eval_quality_warnings = _phase14_quality_warnings(
        use_holdout=bool(use_holdout),
        auc_only=auc_only,
        cm_info=cm_info,
        forbidden_features_after_prep=forbidden_features_after_prep,
        results_df=results_df,
        cfg=cfg,
    )

    elapsed = time.perf_counter() - t0

    summary = {
        "phase": 14,
        "app": app,
        "status": "completed",
        "airc_leakage_aware": True,
        "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
        "leakage_guard": train_leakage_guard,
        "forbidden_features_after_prep": list(forbidden_features_after_prep),
        "evaluation_quality_warnings": eval_quality_warnings,
        "generated_at": datetime.now().isoformat(),
        "eval_mode": "holdout_test_shards" if use_holdout else "internal_split_from_train_sample",
        "modeling_dir": str(cfg.modeling_dir),
        "phase12_dir": str(cfg.phase12_dir),
        "phase13_dir": str(cfg.phase13_dir),
        "output_dir": str(out_app_dir),
        "feature_sets_json": str(feature_sets_path) if feature_sets_path else None,
        "phase13_results_csv": str(results_csv_path) if results_csv_path else None,
        "train_rows_seen": int(train_scan["rows_seen"]),
        "test_rows_seen": int(test_scan["rows_seen"]),
        "train_rows_loaded_initial": int(len(df_train)),
        "test_rows_loaded_initial": int(len(df_test)) if df_test is not None else 0,
        "train_rows_eval": int(len(y_train)),
        "test_rows_eval": int(len(y_test)),
        "train_dist_eval": train_dist,
        "test_dist_eval": test_dist,
        "methods": methods,
        "models_for_roc": models_for_roc,
        "missing_models": missing_models,
        "failed_jobs": failed_jobs,
        "roc_auc_summary": auc_only,
        "confusion_matrix": cm_info,
        "performance_plot": perf_info,
        "logical_cpu": int(_LOGICAL_CPU),
        "worker_threads": int(_WORKER_THREADS),
        "inner_math_threads": int(_INNER_MATH_THREADS),
        "xgb_available": bool(XGBClassifier is not None),
        "xgb_device": str(cfg.xgb_device),
        "xgb_tree_method": str(cfg.xgb_tree_method),
        "predict_batch_rows": int(cfg.predict_batch_rows),
        "paths": {
            "roc_curves_png": str(roc_png) if cfg.write_artifacts else None,
            "perf_comparison_png": str(perf_png) if cfg.write_artifacts else None,
            "confusion_matrix_png": str(cm_png) if cfg.write_artifacts else None,
            "roc_auc_summary_json": str(auc_json) if cfg.write_artifacts else None,
            "summary_json": str(meta_json) if cfg.write_artifacts else None,
        },
        "seconds": float(elapsed),
        "elapsed_human": _fmt_elapsed(elapsed),
        "note": (
            "Phase 14 performs app-aware advanced evaluation using bounded train/test samples. "
            "If Phase 13 did not save fitted models, this phase retrains evaluation models for ROC/confusion matrix artifacts."
        ),
    }

    if cfg.write_artifacts:
        _json_dump(auc_only, auc_json)
        _json_dump(summary, meta_json)
        _json_dump(summary, metrics_dir / f"phase14_advanced_eval_summary_{app}.json")

    print(f"✅ Phase 14 complete app={app}")
    print(f"   eval_mode : {summary['eval_mode']}")
    print(f"   train/test: {len(y_train):,}/{len(y_test):,}")
    print(f"   best      : {best_method}/{best_model}")
    print(f"   ROC       : {roc_png}")
    print(f"   CM        : {cm_png}")
    print(f"   Time      : {_fmt_elapsed(elapsed)}")

    result = {
        "roc_results_full": roc_results_full,
        "roc_auc_summary": auc_only,
        "best": {"method": best_method, "model": best_model},
        "paths": summary["paths"],
        "summary": summary,
    }

    return result, summary


def phase14_advanced_eval(
    *,
    cfg: Phase14AdvancedEvalConfig,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    print("\n" + "📈 " + "=" * 76)
    print("PHASE 14: ADVANCED EVALUATION (APP-AWARE)")
    print("📈 " + "=" * 76)

    t0 = time.perf_counter()

    results_by_app: Dict[str, Dict[str, Any]] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        try:
            result, summary = phase14_advanced_eval_for_app(app_norm, cfg=cfg)
        except Exception as e:
            result = {}
            summary = {
                "phase": 14,
                "app": app_norm,
                "status": "failed",
                "error": repr(e),
                "traceback": traceback.format_exc(),
                "seconds": 0.0,
            }
            metrics_dir = Path(cfg.output_dir) / "metrics"
            metrics_dir.mkdir(parents=True, exist_ok=True)
            _json_dump(summary, metrics_dir / f"phase14_advanced_eval_summary_{app_norm}.json")
            print(f"❌ Phase 14 failed app={app_norm}: {e!r}")

        results_by_app[app_norm] = result
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        cm = s.get("confusion_matrix") or {}
        paths = s.get("paths") or {}
        rows.append({
            "app": app,
            "status": s.get("status"),
            "eval_mode": s.get("eval_mode"),
            "train_rows_eval": int(s.get("train_rows_eval", 0)),
            "test_rows_eval": int(s.get("test_rows_eval", 0)),
            "best_method": cm.get("best_method"),
            "best_model": cm.get("best_model"),
            "cm_status": cm.get("status"),
            "warnings_count": int(len(s.get("evaluation_quality_warnings", []) or [])),
            "roc_curves_png": paths.get("roc_curves_png"),
            "perf_comparison_png": paths.get("perf_comparison_png"),
            "confusion_matrix_png": paths.get("confusion_matrix_png"),
            "roc_auc_summary_json": paths.get("roc_auc_summary_json"),
            "summary_json": paths.get("summary_json"),
            "seconds": float(s.get("seconds", 0.0)),
            "error": s.get("error"),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase14_advanced_eval_summary_by_app.csv", index=False)

    elapsed = time.perf_counter() - t0

    summary_all = {
        "phase": 14,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "modeling_dir": str(cfg.modeling_dir),
        "phase12_dir": str(cfg.phase12_dir),
        "phase13_dir": str(cfg.phase13_dir),
        "output_dir": str(cfg.output_dir),
        "apps": summaries,
        "seconds": float(elapsed),
        "elapsed_human": _fmt_elapsed(elapsed),
        "note": (
            "Phase 14 is app-aware and leakage-aware. It reads Phase 11 modeling shards, Phase 12 feature sets, and Phase 13 result summaries."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase14_advanced_eval_summary_all.json")

    print("\n✅ PHASE 14 COMPLETE")
    print(f"   Output dir: {cfg.output_dir}")
    print(f"   Time      : {_fmt_elapsed(elapsed)}")

    return results_by_app, summary_all


# Compatibility aliases.
def phase14_advanced_evaluation(
    *,
    cfg: Phase14AdvancedEvalConfig,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    return phase14_advanced_eval(cfg=cfg)


def build_phase14_advanced_eval(
    *,
    cfg: Phase14AdvancedEvalConfig,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    return phase14_advanced_eval(cfg=cfg)




# =============================================================================
# RAM MODE API (SMALL DATASET / PER-APP PIPELINE)
# =============================================================================

def _extract_feature_sets_from_phase12_result(phase12_result: Any) -> Dict[str, Any]:
    """Extract feature_sets from Phase 12 RAM/disk result payloads."""
    if phase12_result is None:
        return {}

    # Common tuple shape: (result, summary)
    if isinstance(phase12_result, tuple) and phase12_result:
        return _extract_feature_sets_from_phase12_result(phase12_result[0])

    if not isinstance(phase12_result, dict):
        return {}

    obj = phase12_result

    # Phase 12 result usually has {"feature_sets": {...}}
    fs = obj.get("feature_sets")
    if isinstance(fs, dict):
        # Sometimes wrapped as {"feature_sets": {"MI":..., "RFE":..., "PCA":...}}
        if "feature_sets" in fs and isinstance(fs.get("feature_sets"), dict):
            return fs.get("feature_sets", {})
        return fs

    # Some callers may pass the Phase 12 summary.
    summary = obj.get("summary")
    if isinstance(summary, dict):
        fs = summary.get("feature_sets")
        if isinstance(fs, dict):
            return fs

    # If the dict itself looks like a feature-set object.
    if any(k in obj for k in ("MI", "RFE", "PCA")):
        return obj

    return {}


def _results_to_dataframe_from_phase13(phase13_results: Any = None, phase13_summary: Any = None) -> pd.DataFrame:
    """Normalize Phase 13 RAM/disk result payload into a results DataFrame."""
    if isinstance(phase13_results, pd.DataFrame):
        return phase13_results.copy()

    if isinstance(phase13_results, tuple) and phase13_results:
        # Common shape: (results_df, summary)
        if isinstance(phase13_results[0], pd.DataFrame):
            return phase13_results[0].copy()
        if len(phase13_results) > 1:
            return _results_to_dataframe_from_phase13(phase13_results[0], phase13_results[1])

    candidates: List[Any] = []
    if isinstance(phase13_results, dict):
        candidates.extend([
            phase13_results.get("results_df"),
            phase13_results.get("results"),
            phase13_results.get("rows"),
            phase13_results.get("result_rows"),
        ])
    if isinstance(phase13_summary, dict):
        candidates.extend([
            phase13_summary.get("results"),
            phase13_summary.get("rows"),
            phase13_summary.get("result_rows"),
        ])

    for item in candidates:
        if isinstance(item, pd.DataFrame):
            return item.copy()
        if isinstance(item, list) and item:
            try:
                return pd.DataFrame(item)
            except Exception:
                pass

    # Last fallback: single best row. Useful for selecting confusion matrix model.
    # Prefer the leakage-aware / holdout-first fields produced by patched
    # Phase 13 before falling back to legacy CV-only output.
    if isinstance(phase13_summary, dict):
        best = (
            phase13_summary.get("best_by_preferred_metric")
            or phase13_summary.get("best_by_holdout_f1_attack")
            or phase13_summary.get("best_by_cv_f1_attack")
            or phase13_summary.get("best")
        )
        if isinstance(best, dict) and best:
            return pd.DataFrame([best])

    return pd.DataFrame()


def _sample_df_ram_for_eval(
    df: pd.DataFrame,
    *,
    target_col: str,
    n_rows: Optional[int],
    mode: str,
    seed: int,
) -> pd.DataFrame:
    """Bound a RAM DataFrame using random/stratified sampling without disk I/O."""
    if df is None or df.empty:
        return pd.DataFrame()

    if n_rows is None or int(n_rows) <= 0 or int(n_rows) >= len(df):
        return df.reset_index(drop=True).copy()

    n_take = int(n_rows)
    mode = str(mode or "stratified_balanced").lower().strip()
    rng = np.random.default_rng(int(seed))

    if target_col not in df.columns or mode == "random":
        return df.sample(n=n_take, random_state=int(seed)).reset_index(drop=True)

    y = _target_series(df, target_col)
    counts = Counter(y.astype(int).tolist())
    plan = _sample_plan(counts, n_take, mode)

    parts: List[pd.DataFrame] = []
    for cls, take in plan.items():
        sub = df[y == int(cls)]
        if sub.empty or int(take) <= 0:
            continue
        take = min(int(take), len(sub))
        parts.append(sub.sample(n=take, random_state=int(rng.integers(0, 2_147_483_647))).copy())

    if not parts:
        return df.sample(n=n_take, random_state=int(seed)).reset_index(drop=True)

    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=int(seed)).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=int(seed)).reset_index(drop=True)
    return out


def phase14_advanced_eval_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str = "unknown",
    phase12_result: Optional[Dict[str, Any]] = None,
    phase13_results: Any = None,
    phase13_summary: Optional[Dict[str, Any]] = None,
    cfg: Optional[Phase14AdvancedEvalConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    RAM-mode Phase 14 for the small-data / seminar pipeline.

    Input:
      df_train        : train DataFrame returned by Phase 11 RAM mode.
      df_test         : optional test DataFrame returned by Phase 11 RAM mode.
      phase12_result  : Phase 12 RAM result containing feature_sets.
      phase13_results : Phase 13 RAM results DataFrame or compatible payload.

    Output:
      result, summary

    This function does not read train/test Parquet shards. It may write only small
    evaluation artifacts: ROC plot, performance comparison plot, confusion matrix,
    and JSON summaries.
    """
    app = str(app).strip().lower() or "unknown"
    cfg = cfg or Phase14AdvancedEvalConfig(selected_apps=(app,))
    tag = cfg.filename_tag.strip() or "run"
    t0 = time.perf_counter()

    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    roc_png = out_app_dir / f"roc_curves_{app}_{tag}.png"
    perf_png = out_app_dir / f"model_performance_comparison_{app}_{tag}.png"
    cm_png = out_app_dir / f"confusion_matrix_best_model_{app}_{tag}.png"
    auc_json = out_app_dir / f"roc_auc_summary_{app}_{tag}.json"
    meta_json = out_app_dir / f"phase14_summary_{app}_{tag}.json"

    if df_train is None or df_train.empty:
        elapsed = time.perf_counter() - t0
        summary = {
            "phase": 14,
            "phase_name": "advanced_eval",
            "mode": "ram",
            "app": app,
            "status": "skipped_empty_train",
            "rows_train_in": 0,
            "rows_test_in": 0 if df_test is None else int(len(df_test)),
            "seconds": float(elapsed),
        }
        _json_dump(summary, metrics_dir / f"phase14_advanced_eval_summary_{app}.json")
        return {}, summary

    feature_sets = _extract_feature_sets_from_phase12_result(phase12_result)
    if not feature_sets:
        # Small-artifact fallback only, if pipeline did not pass Phase 12 result.
        try:
            feature_sets, _feature_sets_path = _load_feature_sets(cfg, app)
        except Exception:
            feature_sets = {}

    if not feature_sets:
        raise RuntimeError(
            f"Phase 14 RAM requires feature_sets from Phase 12 for app={app}. "
            "Pass phase12_result from phase12_fs_ram(...)."
        )

    results_df = _results_to_dataframe_from_phase13(phase13_results, phase13_summary)
    if results_df.empty:
        # Small-artifact fallback only, if Phase 13 wrote results CSV.
        try:
            results_df, _ = _load_phase13_results(cfg, app)
        except Exception:
            results_df = pd.DataFrame()

    rows_train_in = int(len(df_train))
    rows_test_in = 0 if df_test is None else int(len(df_test))

    df_train_eval = _sample_df_ram_for_eval(
        df_train,
        target_col=cfg.target_col,
        n_rows=cfg.train_rows,
        mode=cfg.sample_mode,
        seed=int(cfg.seed),
    )

    df_test_eval = _sample_df_ram_for_eval(
        df_test if df_test is not None else pd.DataFrame(),
        target_col=cfg.target_col,
        n_rows=cfg.test_rows,
        mode=cfg.sample_mode,
        seed=int(cfg.seed) + 17,
    )

    if df_train_eval.empty:
        raise RuntimeError(f"Phase 14 RAM train sample is empty for app={app}.")

    X_train_num, y_train = _prepare_numeric_Xy(df_train_eval, cfg)
    train_leakage_guard = X_train_num.attrs.get("leakage_guard", {})
    forbidden_features_after_prep = X_train_num.attrs.get("forbidden_features_after_prep", _forbidden_feature_cols(X_train_num.columns.tolist(), cfg))

    use_holdout = False
    X_test_num = None
    y_test = None

    if not df_test_eval.empty:
        try:
            X_test_all, y_test_tmp = _prepare_numeric_Xy(df_test_eval, cfg)
            X_test_tmp = _align_test_to_train(X_test_all, X_train_num.columns.tolist())
            if y_test_tmp.nunique(dropna=True) >= 2:
                X_test_num = X_test_tmp
                y_test = y_test_tmp
                use_holdout = True
        except Exception as e:
            print(f"   ⚠️ Phase 14 RAM holdout unusable for app={app}; internal split fallback: {e!r}")

    if not use_holdout:
        X_train_num, X_test_num, y_train, y_test = train_test_split(
            X_train_num,
            y_train,
            test_size=float(cfg.internal_test_size),
            random_state=int(cfg.seed),
            stratify=y_train,
        )

    assert X_test_num is not None and y_test is not None

    train_dist = {str(k): int(v) for k, v in pd.Series(y_train).value_counts().to_dict().items()}
    test_dist = {str(k): int(v) for k, v in pd.Series(y_test).value_counts().to_dict().items()}

    models = _build_models(cfg)
    models_for_roc = [str(m).upper() for m in cfg.models_for_roc if str(m).upper() in models]
    missing_models = [str(m).upper() for m in cfg.models_for_roc if str(m).upper() not in models]
    methods = [str(m).upper() for m in cfg.methods]

    if missing_models:
        print(f"   ⚠️ Models unavailable and skipped: {missing_models}")

    roc_results_full: Dict[str, Dict[str, Dict[str, Any]]] = {}
    auc_only: Dict[str, Dict[str, Dict[str, float]]] = {}
    failed_jobs: List[Dict[str, Any]] = []

    fig, axes = plt.subplots(1, max(1, len(methods)), figsize=(6 * max(1, len(methods)), 5))
    if len(methods) == 1:
        axes = [axes]
    fig.suptitle(f"ROC Curves - {app.upper()} ({tag})", fontsize=14, fontweight="bold")

    total_jobs = max(1, len(methods) * max(1, len(models_for_roc)))
    done = 0

    for i, method in enumerate(methods):
        ax = axes[i]
        roc_results_full[method] = {}
        auc_only[method] = {}

        feature_list, n_comp = _get_method_features(
            method,
            feature_sets,
            X_train_num.columns.tolist(),
            cfg.pca_default_n_components,
        )

        if method in {"MI", "RFE"}:
            if not feature_list:
                ax.set_title(f"{method} (no usable features)")
                ax.axis("off")
                for model_name in models_for_roc:
                    auc_only[method][model_name] = {"auc": 0.5}
                    roc_results_full[method][model_name] = {"fpr": [0.0, 1.0], "tpr": [0.0, 1.0], "auc": 0.5}
                continue
            X_tr_m = X_train_num[feature_list].copy()
            X_te_m = X_test_num[feature_list].copy()
        elif method == "PCA":
            X_tr_m = X_train_num.copy()
            X_te_m = X_test_num.copy()
            n_comp = max(1, min(int(n_comp), int(X_tr_m.shape[1]), max(1, int(len(X_tr_m)) - 1)))
        else:
            ax.set_title(f"{method} (unknown)")
            ax.axis("off")
            continue

        for model_name in models_for_roc:
            done += 1
            print(f"   ROC RAM {done}/{total_jobs}: {method}/{model_name}")
            try:
                est = _build_estimator(method, model_name, models, n_comp, cfg)
                with _limit_threads(cfg.blas_thread_limit):
                    est.fit(X_tr_m, y_train)

                scores = _scores_batched(est, X_te_m, batch_rows=int(cfg.predict_batch_rows))
                fpr, tpr, _ = roc_curve(y_test, scores)
                roc_auc = auc(fpr, tpr)

                roc_results_full[method][model_name] = {
                    "fpr": [float(x) for x in fpr],
                    "tpr": [float(x) for x in tpr],
                    "auc": float(roc_auc),
                }
                auc_only[method][model_name] = {"auc": float(roc_auc)}
                ax.plot(fpr, tpr, linewidth=2.0, label=f"{model_name} (AUC={roc_auc:.4f})")

                if cfg.gc_each_model:
                    del est
                    gc.collect()

            except Exception as e:
                failed_jobs.append({"method": method, "model": model_name, "error": repr(e)})
                roc_results_full[method][model_name] = {"fpr": [0.0, 1.0], "tpr": [0.0, 1.0], "auc": 0.5}
                auc_only[method][model_name] = {"auc": 0.5}
                print(f"      ⚠️ failed {method}/{model_name}: {e!r}")

        ax.plot([0, 1], [0, 1], "k--", linewidth=1.0, label="Random")
        ax.set_xlabel("False Positive Rate", fontweight="bold")
        ax.set_ylabel("True Positive Rate", fontweight="bold")
        ax.set_title(method, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="lower right", fontsize=9)

    plt.tight_layout()
    if cfg.write_artifacts:
        plt.savefig(roc_png, dpi=250, bbox_inches="tight")
    plt.close(fig)

    if cfg.write_artifacts:
        perf_info = _plot_performance_comparison(results_df, app=app, tag=tag, out_path=perf_png)
    else:
        perf_info = {"status": "skipped_write_artifacts_false"}

    best = _pick_best_row(results_df, cfg.best_metric_preference)
    if best is not None and "Method" in best and "Model" in best:
        best_method = str(best["Method"]).upper()
        best_model = str(best["Model"]).upper()
    else:
        best_method = "PCA"
        best_model = "RFC"
        best_auc = -1.0
        for method, d in auc_only.items():
            for model_name, item in d.items():
                val = float(item.get("auc", 0.5))
                if val > best_auc:
                    best_auc = val
                    best_method = str(method).upper()
                    best_model = str(model_name).upper()

    if best_model not in models:
        best_model = "RFC" if "RFC" in models else next(iter(models.keys()))

    feature_list, n_comp = _get_method_features(
        best_method,
        feature_sets,
        X_train_num.columns.tolist(),
        cfg.pca_default_n_components,
    )

    if best_method in {"MI", "RFE"} and feature_list:
        X_tr_best = X_train_num[feature_list].copy()
        X_te_best = X_test_num[feature_list].copy()
    else:
        X_tr_best = X_train_num.copy()
        X_te_best = X_test_num.copy()
        n_comp = max(1, min(int(n_comp), int(X_tr_best.shape[1]), max(1, int(len(X_tr_best)) - 1)))

    cm_info: Dict[str, Any]
    try:
        est_best = _build_estimator(best_method, best_model, models, n_comp, cfg)
        with _limit_threads(cfg.blas_thread_limit):
            est_best.fit(X_tr_best, y_train)
        y_pred = _predict_batched(est_best, X_te_best, batch_rows=int(cfg.predict_batch_rows))
        cm = confusion_matrix(y_test, y_pred, labels=[0, 1])

        if cfg.write_artifacts:
            _plot_confusion_matrix(
                cm,
                title=f"Confusion Matrix - {app.upper()} - {best_model} ({best_method})",
                out_path=cm_png,
            )

        cm_info = {
            "status": "completed",
            "best_method": best_method,
            "best_model": best_model,
            "confusion_matrix": cm.astype(int).tolist(),
            "tn": int(cm[0, 0]),
            "fp": int(cm[0, 1]),
            "fn": int(cm[1, 0]),
            "tp": int(cm[1, 1]),
        }
    except Exception as e:
        cm_info = {"status": "failed", "best_method": best_method, "best_model": best_model, "error": repr(e)}
        print(f"   ⚠️ Confusion matrix failed: {e!r}")

    eval_quality_warnings = _phase14_quality_warnings(
        use_holdout=bool(use_holdout),
        auc_only=auc_only,
        cm_info=cm_info,
        forbidden_features_after_prep=forbidden_features_after_prep,
        results_df=results_df,
        cfg=cfg,
    )

    elapsed = time.perf_counter() - t0
    summary = {
        "phase": 14,
        "phase_name": "advanced_eval",
        "mode": "ram",
        "app": app,
        "status": "completed",
        "airc_leakage_aware": True,
        "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
        "leakage_guard": train_leakage_guard,
        "forbidden_features_after_prep": list(forbidden_features_after_prep),
        "evaluation_quality_warnings": eval_quality_warnings,
        "generated_at": datetime.now().isoformat(),
        "eval_mode": "holdout_df_test" if use_holdout else "internal_split_from_train_df",
        "output_dir": str(out_app_dir),
        "rows_train_in": int(rows_train_in),
        "rows_test_in": int(rows_test_in),
        "train_rows_loaded_initial": int(len(df_train_eval)),
        "test_rows_loaded_initial": int(len(df_test_eval)),
        "train_rows_eval": int(len(y_train)),
        "test_rows_eval": int(len(y_test)),
        "train_dist_eval": train_dist,
        "test_dist_eval": test_dist,
        "methods": methods,
        "models_for_roc": models_for_roc,
        "missing_models": missing_models,
        "failed_jobs": failed_jobs,
        "roc_auc_summary": auc_only,
        "confusion_matrix": cm_info,
        "performance_plot": perf_info,
        "phase13_results_rows": int(len(results_df)),
        "logical_cpu": int(_LOGICAL_CPU),
        "worker_threads": int(_WORKER_THREADS),
        "inner_math_threads": int(_INNER_MATH_THREADS),
        "xgb_available": bool(XGBClassifier is not None),
        "xgb_device": str(cfg.xgb_device),
        "xgb_tree_method": str(cfg.xgb_tree_method),
        "predict_batch_rows": int(cfg.predict_batch_rows),
        "paths": {
            "roc_curves_png": str(roc_png) if cfg.write_artifacts else None,
            "perf_comparison_png": str(perf_png) if cfg.write_artifacts else None,
            "confusion_matrix_png": str(cm_png) if cfg.write_artifacts else None,
            "roc_auc_summary_json": str(auc_json) if cfg.write_artifacts else None,
            "summary_json": str(meta_json) if cfg.write_artifacts else None,
        },
        "seconds": float(elapsed),
        "elapsed_human": _fmt_elapsed(elapsed),
        "note": (
            "RAM-mode Phase 14 evaluates one active application from in-memory train/test DataFrames. "
            "It does not read modeling shards or write dataset checkpoints."
        ),
    }

    if cfg.write_artifacts:
        _json_dump(auc_only, auc_json)
        _json_dump(summary, meta_json)
        _json_dump(summary, metrics_dir / f"phase14_advanced_eval_summary_{app}.json")

    print(f"✅ Phase 14 RAM complete app={app}")
    print(f"   eval_mode : {summary['eval_mode']}")
    print(f"   train/test: {len(y_train):,}/{len(y_test):,}")
    print(f"   best      : {best_method}/{best_model}")
    print(f"   Time      : {_fmt_elapsed(elapsed)}")

    result = {
        "roc_results_full": roc_results_full,
        "roc_auc_summary": auc_only,
        "best": {"method": best_method, "model": best_model},
        "paths": summary["paths"],
        "summary": summary,
    }

    gc.collect()
    return result, summary


# RAM-mode aliases for pipeline integration.
def phase14_advanced_eval_in_memory(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str = "unknown",
    phase12_result: Optional[Dict[str, Any]] = None,
    phase13_results: Any = None,
    phase13_summary: Optional[Dict[str, Any]] = None,
    cfg: Optional[Phase14AdvancedEvalConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return phase14_advanced_eval_ram(
        df_train,
        df_test,
        app=app,
        phase12_result=phase12_result,
        phase13_results=phase13_results,
        phase13_summary=phase13_summary,
        cfg=cfg,
    )


def phase14_advanced_evaluation_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str = "unknown",
    phase12_result: Optional[Dict[str, Any]] = None,
    phase13_results: Any = None,
    phase13_summary: Optional[Dict[str, Any]] = None,
    cfg: Optional[Phase14AdvancedEvalConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return phase14_advanced_eval_ram(
        df_train,
        df_test,
        app=app,
        phase12_result=phase12_result,
        phase13_results=phase13_results,
        phase13_summary=phase13_summary,
        cfg=cfg,
    )


def run_phase14_advanced_eval_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str = "unknown",
    phase12_result: Optional[Dict[str, Any]] = None,
    phase13_results: Any = None,
    phase13_summary: Optional[Dict[str, Any]] = None,
    cfg: Optional[Phase14AdvancedEvalConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return phase14_advanced_eval_ram(
        df_train,
        df_test,
        app=app,
        phase12_result=phase12_result,
        phase13_results=phase13_results,
        phase13_summary=phase13_summary,
        cfg=cfg,
    )


def build_phase14_advanced_eval_ram(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame] = None,
    *,
    app: str = "unknown",
    phase12_result: Optional[Dict[str, Any]] = None,
    phase13_results: Any = None,
    phase13_summary: Optional[Dict[str, Any]] = None,
    cfg: Optional[Phase14AdvancedEvalConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return phase14_advanced_eval_ram(
        df_train,
        df_test,
        app=app,
        phase12_result=phase12_result,
        phase13_results=phase13_results,
        phase13_summary=phase13_summary,
        cfg=cfg,
    )

if __name__ == "__main__":
    results, summary = phase14_advanced_eval(
        cfg=Phase14AdvancedEvalConfig(
            modeling_dir=Path("results/modeling"),
            phase12_dir=Path("results/phase12_fs"),
            phase13_dir=Path("results/phase13_train"),
            output_dir=Path("results/phase14_advanced_eval"),
            selected_apps=("dns", "http", "tls", "ssh"),
            target_col="Target",
            filename_tag="run",
            methods=("MI", "RFE", "PCA"),
            models_for_roc=("DT", "RFC", "LSVC", "XGB"),
            train_rows=500_000,
            test_rows=200_000,
            sample_mode="stratified_balanced",
            parquet_engine="fastparquet",
            overwrite=True,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
