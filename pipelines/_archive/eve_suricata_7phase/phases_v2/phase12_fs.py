# src/cbr/phases/phase12_fs.py
from __future__ import annotations

import gc
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import RFE, mutual_info_classif
from sklearn.preprocessing import StandardScaler


# =============================================================================
# PHASE 12: FEATURE SELECTION (APP-AWARE, SHARDED-SAFE)
# =============================================================================
# Purpose:
#   Run feature selection per application after Phase 11 modeling split.
#
# Input:
#   results/modeling/app={app}/train/part-*.parquet
#
# Output:
#   results/phase12_fs/app={app}/
#     phase12_mi_ranking_{app}_{tag}.csv
#     phase12_rfe_ranking_{app}_{tag}.csv
#     phase12_feature_sets_{app}_{tag}.json
#     phase12_pca_meta_{app}_{tag}.json
#     phase12_meta_{app}_{tag}.json
#     phase12_pca_scaler_{app}_{tag}.joblib   optional when joblib is installed
#
#   results/phase12_fs/metrics/
#     phase12_fs_summary_{app}.json
#     phase12_fs_summary_all.json
#     phase12_fs_summary_by_app.csv
#
# Important:
#   - This phase no longer receives one df_train in memory.
#   - This phase reads bounded samples from app train shards.
#   - Output is per application.
# =============================================================================


DEFAULT_APPS: Tuple[str, ...] = ("dns", "http", "tls", "ssh")

DEFAULT_DROP_COLS: Tuple[str, ...] = (
    "Target",
    "timestamp",
    "src_ip",
    "dest_ip",
    "src_port",
    "dest_port",
    "proto",
    "event_type",
    "event_type_raw",
    "app_proto",
    "app_proto_raw",
    "application",
    "application_raw",
    "community_id",
)

# Conservative AIRC/leakage-aware fallback guard. Phase 11 should already
# remove these fields, but Phase 12 must not select them even if one slips
# through the modeling split.
DEFAULT_AIRC_EXTRA_DROP_COLS: Tuple[str, ...] = (
    # Preliminary/final label and explanation columns
    "Target_prelim",
    "is_malicious",
    "label_status",
    "label_status_h",
    "label_status_final",
    "label_status_final_h",
    "label_source",
    "label_source_h",
    "label_reason",
    "label_reason_h",
    "label_confidence",

    # Alert-derived shortcuts
    "has_alert",
    "alert_category",
    "alert_category_h",
    "alert_severity",
    "alert_signature",
    "alert_signature_h",
    "alert_signature_id",
    "alert_count_window",
    "target_prelim_malicious_count",

    # Evidence/probe-direct shortcuts
    "evidence_alert",
    "evidence_compromised_ip",
    "evidence_probe",
    "probe_score",
    "probe_reason",
    "probe_reason_h",
    "is_possible_probe",
    "is_probe_suspicious",
    "window_start",
    "window_start_h",
)

DEFAULT_LABEL_PREFIXES: Tuple[str, ...] = ("label_", "evidence_")
DEFAULT_ALERT_PREFIXES: Tuple[str, ...] = ("alert_",)
DEFAULT_PROBE_PREFIXES: Tuple[str, ...] = ("probe_",)


@dataclass(frozen=True)
class Phase12FSConfig:
    modeling_dir: Path = Path("results/modeling")
    output_dir: Path = Path("results/phase12_fs")
    selected_apps: Tuple[str, ...] = DEFAULT_APPS

    target_col: str = "Target"
    seed: int = 42

    # Sampling caps from train shards.
    fs_sample_n: int = 5_000_000
    fs_sample_mode: str = "stratified_proportional"  # "stratified_proportional" | "stratified_balanced" | "random"

    # Per-method row caps.
    mi_max_rows: int = 1_000_000
    rfe_max_rows: int = 1_500_000
    pca_max_rows: int = 3_000_000

    top_k: int = 25

    # Optional drop guard. Phase 11 should already have removed most leakage,
    # but these are safe if still present.
    drop_cols: Tuple[str, ...] = DEFAULT_DROP_COLS

    # AIRC/leakage-aware guard. These flags make Phase 12 a final safety gate
    # so MI/RFE/PCA cannot select alert-, label-, or direct-probe shortcuts.
    strict_leakage_guard: bool = True
    drop_probe_direct_features: bool = True
    drop_label_explanation_features: bool = True
    drop_alert_derived_features: bool = True
    extra_drop_cols: Tuple[str, ...] = DEFAULT_AIRC_EXTRA_DROP_COLS

    # Optional pattern extensions if pipeline.py wants to pass stricter guards.
    forbidden_feature_prefixes: Tuple[str, ...] = ()
    forbidden_feature_suffixes: Tuple[str, ...] = ("_raw",)

    # IO
    filename_tag: str = "run"
    parquet_engine: Optional[str] = "fastparquet"

    write_artifacts: bool = True
    write_sample_csv: bool = False
    save_pca_scaler_joblib: bool = True

    overwrite: bool = True
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


def _list_train_shards(modeling_dir: Path, app: str) -> List[Path]:
    app = str(app).strip().lower()
    dirs = [
        Path(modeling_dir) / f"app={app}" / "train",
        Path(modeling_dir) / app / "train",
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
    x = x.replace([np.inf, -np.inf], np.nan).fillna(0)
    return x


def _target_series(df: pd.DataFrame, target_col: str) -> pd.Series:
    if target_col not in df.columns:
        raise RuntimeError(f"Target column missing: {target_col}")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    return (y == 1).astype(np.int8)


def _to_numeric_frame(X: pd.DataFrame) -> pd.DataFrame:
    Xn = X.select_dtypes(include=[np.number]).copy()
    if Xn.shape[1] == 0:
        return Xn

    for c in Xn.columns:
        Xn[c] = pd.to_numeric(Xn[c], errors="coerce")
        Xn[c] = Xn[c].replace([np.inf, -np.inf], np.nan).fillna(0)

    return Xn


def _safe_mutual_info(X: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    try:
        return mutual_info_classif(X, y, random_state=seed, n_jobs=-1)
    except TypeError:
        return mutual_info_classif(X, y, random_state=seed)


# =============================================================================
# Streaming sample from train shards
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


def _scan_train_counts(
    shard_files: List[Path],
    *,
    cfg: Phase12FSConfig,
    app: str,
) -> Dict[str, Any]:
    rows_seen = 0
    bytes_seen = 0
    target_counter: Counter = Counter()
    schema_cols: Optional[List[str]] = None

    for fp in tqdm(shard_files, desc=f"PHASE 12 scan app={app}", unit="shard", dynamic_ncols=True):
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


def _sample_plan(target_counts: Counter, n_take: int, mode: str) -> Dict[int, int]:
    total = int(sum(target_counts.values()))
    n_take = min(max(0, int(n_take)), total)
    if total <= 0 or n_take <= 0:
        return {}

    mode = str(mode or "stratified_proportional").lower().strip()

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


def _collect_fs_sample(
    shard_files: List[Path],
    *,
    cfg: Phase12FSConfig,
    app: str,
    target_counts: Counter,
) -> pd.DataFrame:
    n_take = max(0, int(cfg.fs_sample_n))
    if n_take <= 0:
        return pd.DataFrame()

    mode = str(cfg.fs_sample_mode or "stratified_proportional").lower().strip()

    if mode == "random":
        sampler = _ReservoirSampler(n_take, seed=int(cfg.seed) + abs(hash(app)) % 10_000)
        for fp in tqdm(shard_files, desc=f"PHASE 12 sample app={app}", unit="shard", dynamic_ncols=True):
            df = _read_shard(fp, parquet_engine=cfg.parquet_engine)
            if df is None or df.empty:
                continue
            sampler.add(df)
            if cfg.gc_each_shard:
                del df
                gc.collect()
        return sampler.dataframe()

    plan = _sample_plan(target_counts, n_take, mode)
    samplers = {
        int(k): _ReservoirSampler(v, seed=int(cfg.seed) + int(k) * 29 + abs(hash(app)) % 10_000)
        for k, v in plan.items()
    }

    for fp in tqdm(shard_files, desc=f"PHASE 12 sample app={app}", unit="shard", dynamic_ncols=True):
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
        out = out.sample(n=n_take, random_state=cfg.seed).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=cfg.seed).reset_index(drop=True)

    return out


# =============================================================================
# Feature selection core
# =============================================================================

def _unique_preserve_order(values: Sequence[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for x in values:
        val = str(x).strip()
        if not val or val in seen:
            continue
        out.append(val)
        seen.add(val)
    return out


def _effective_drop_cols(cfg: Phase12FSConfig) -> List[str]:
    drops: List[str] = [cfg.target_col, *list(cfg.drop_cols)]

    if bool(getattr(cfg, "strict_leakage_guard", True)):
        drops.extend(list(getattr(cfg, "extra_drop_cols", ())))

    if bool(getattr(cfg, "drop_label_explanation_features", True)):
        drops.extend([
            "label_status", "label_status_h", "label_status_final", "label_status_final_h",
            "label_source", "label_source_h", "label_reason", "label_reason_h",
            "label_confidence", "evidence_alert", "evidence_compromised_ip", "evidence_probe",
        ])

    if bool(getattr(cfg, "drop_alert_derived_features", True)):
        drops.extend([
            "has_alert", "Target_prelim", "alert_category", "alert_category_h", "alert_severity",
            "alert_signature", "alert_signature_h", "alert_signature_id", "alert_count_window",
            "target_prelim_malicious_count",
        ])

    if bool(getattr(cfg, "drop_probe_direct_features", True)):
        drops.extend([
            "probe_score", "probe_reason", "probe_reason_h", "is_possible_probe",
            "is_probe_suspicious", "window_start", "window_start_h",
        ])

    return _unique_preserve_order(drops)


def _is_forbidden_feature(feature: Any, cfg: Phase12FSConfig) -> bool:
    name = str(feature).strip()
    if not name or name == cfg.target_col:
        return False

    low = name.lower()
    exact = {str(x).strip().lower() for x in _effective_drop_cols(cfg)}
    if low in exact:
        return True

    prefixes: List[str] = list(getattr(cfg, "forbidden_feature_prefixes", ()) or ())
    suffixes: List[str] = list(getattr(cfg, "forbidden_feature_suffixes", ()) or ())

    if bool(getattr(cfg, "drop_label_explanation_features", True)):
        prefixes.extend(DEFAULT_LABEL_PREFIXES)
    if bool(getattr(cfg, "drop_alert_derived_features", True)):
        prefixes.extend(DEFAULT_ALERT_PREFIXES)
    if bool(getattr(cfg, "drop_probe_direct_features", True)):
        prefixes.extend(DEFAULT_PROBE_PREFIXES)
        # These do not start with probe_ but are direct probe/window indicators.
        if low in {"is_possible_probe", "is_probe_suspicious", "window_start", "window_start_h"}:
            return True

    for pref in prefixes:
        pref = str(pref).strip().lower()
        if pref and low.startswith(pref):
            return True

    for suf in suffixes:
        suf = str(suf).strip().lower()
        if suf and low.endswith(suf):
            return True

    return False


def _filter_feature_list(features: Sequence[Any], cfg: Phase12FSConfig) -> Tuple[List[str], List[str]]:
    kept: List[str] = []
    removed: List[str] = []
    for f in features:
        fs = str(f)
        if _is_forbidden_feature(fs, cfg):
            removed.append(fs)
        else:
            kept.append(fs)
    return kept, removed


def _prepare_X_y(df_fs: pd.DataFrame, cfg: Phase12FSConfig) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
    if cfg.target_col not in df_fs.columns:
        raise RuntimeError(f"Missing target_col={cfg.target_col} in FS sample.")

    y = _target_series(df_fs, cfg.target_col)
    vc = y.value_counts().to_dict()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class in FS sample: {vc}")

    effective_drop_cols = _effective_drop_cols(cfg)
    guard_drop_present = [c for c in df_fs.columns if _is_forbidden_feature(c, cfg)]
    drop_cols = _unique_preserve_order([cfg.target_col, *effective_drop_cols, *guard_drop_present])

    X_raw = df_fs.drop(columns=drop_cols, errors="ignore")
    X = _to_numeric_frame(X_raw)

    non_numeric_dropped = [c for c in X_raw.columns if c not in set(X.columns)]
    forbidden_after_numeric = [c for c in X.columns if _is_forbidden_feature(c, cfg)]
    if forbidden_after_numeric:
        X = X.drop(columns=forbidden_after_numeric, errors="ignore")

    if X.shape[1] == 0:
        raise RuntimeError(
            "No numeric leakage-safe features found for Phase 12. "
            "Check Phase 11 output schema and strict drop/coercion rules."
        )

    prep_info = {
        "df_fs_columns": int(len(df_fs.columns)),
        "X_raw_columns": int(X_raw.shape[1]),
        "numeric_features_total": int(X.shape[1]),
        "non_numeric_dropped": non_numeric_dropped,
        "drop_cols_attempted": list(drop_cols),
        "guard_drop_present": _unique_preserve_order(guard_drop_present),
        "forbidden_after_numeric_removed": _unique_preserve_order(forbidden_after_numeric),
        "target_dist_sample": {str(k): int(v) for k, v in vc.items()},
        "leakage_guard": {
            "strict_leakage_guard": bool(getattr(cfg, "strict_leakage_guard", True)),
            "drop_probe_direct_features": bool(getattr(cfg, "drop_probe_direct_features", True)),
            "drop_label_explanation_features": bool(getattr(cfg, "drop_label_explanation_features", True)),
            "drop_alert_derived_features": bool(getattr(cfg, "drop_alert_derived_features", True)),
            "extra_drop_cols_count": int(len(getattr(cfg, "extra_drop_cols", ()) or ())),
        },
    }

    return X, y, prep_info

def _fit_mi(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    cfg: Phase12FSConfig,
    n_select: int,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    n_mi = int(min(cfg.mi_max_rows, len(X)))
    if len(X) > n_mi:
        idx = np.random.RandomState(cfg.seed).choice(len(X), n_mi, replace=False)
        X_mi = X.iloc[idx].values
        y_mi = y.iloc[idx].values
    else:
        X_mi = X.values
        y_mi = y.values

    try:
        mi_scores = _safe_mutual_info(X_mi, y_mi, cfg.seed)
        mi_df = (
            pd.DataFrame({"Feature": X.columns, "MI_Score": mi_scores})
            .sort_values("MI_Score", ascending=False)
            .reset_index(drop=True)
        )
        mi_selected = mi_df.head(n_select)["Feature"].tolist()
        info = {"method": "mutual_information", "status": "ok", "rows_used": int(len(X_mi))}
    except Exception as e:
        var = X.var().sort_values(ascending=False)
        mi_df = pd.DataFrame({"Feature": var.index, "MI_Score": var.values}).reset_index(drop=True)
        mi_selected = var.head(n_select).index.tolist()
        info = {"method": "variance_fallback", "status": "fallback", "error": repr(e), "rows_used": int(len(X))}

    return mi_df, mi_selected, info


def _fit_rfe(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    cfg: Phase12FSConfig,
    n_select: int,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    n_rfe = int(min(cfg.rfe_max_rows, len(X)))
    if len(X) > n_rfe:
        idx = np.random.RandomState(cfg.seed).choice(len(X), n_rfe, replace=False)
        X_rfe = X.iloc[idx].reset_index(drop=True)
        y_rfe = y.iloc[idx].reset_index(drop=True)
    else:
        X_rfe = X.reset_index(drop=True)
        y_rfe = y.reset_index(drop=True)

    try:
        base_rf = RandomForestClassifier(
            n_estimators=80,
            random_state=cfg.seed,
            n_jobs=-1,
            class_weight=None,
        )
        step = max(1, min(5, X.shape[1] // 10))
        rfe = RFE(estimator=base_rf, n_features_to_select=n_select, step=step)
        rfe.fit(X_rfe, y_rfe)

        rfe_selected = X.columns[rfe.support_].tolist()
        rfe_df = (
            pd.DataFrame({
                "Feature": X.columns,
                "RFE_Ranking": rfe.ranking_,
                "Selected": rfe.support_.astype(bool),
            })
            .sort_values(["RFE_Ranking", "Feature"], ascending=[True, True])
            .reset_index(drop=True)
        )
        info = {
            "method": "rfe_random_forest",
            "status": "ok",
            "rows_used": int(len(X_rfe)),
            "step": int(step),
            "n_estimators": 80,
        }
    except Exception as e:
        # Fallback to RandomForest feature importance.
        rf = RandomForestClassifier(n_estimators=120, random_state=cfg.seed, n_jobs=-1)
        take = min(20_000, len(X_rfe))
        rf.fit(X_rfe.head(take), y_rfe.head(take))
        imp = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
        rfe_selected = imp.head(n_select).index.tolist()
        rfe_df = pd.DataFrame({"Feature": imp.index, "Importance": imp.values}).reset_index(drop=True)
        info = {
            "method": "rf_importance_fallback",
            "status": "fallback",
            "error": repr(e),
            "rows_used": int(take),
            "n_estimators": 120,
        }

    return rfe_df, rfe_selected, info


def _fit_pca(
    X: pd.DataFrame,
    *,
    cfg: Phase12FSConfig,
    n_components: int,
) -> Tuple[PCA, StandardScaler, Dict[str, Any]]:
    n_pca = int(min(cfg.pca_max_rows, len(X)))
    if len(X) > n_pca:
        idx = np.random.RandomState(cfg.seed).choice(len(X), n_pca, replace=False)
        X_pca_fit = X.iloc[idx].reset_index(drop=True)
    else:
        X_pca_fit = X.reset_index(drop=True)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_pca_fit.values)

    pca = PCA(n_components=int(n_components), random_state=cfg.seed)
    pca.fit(X_scaled)

    cumsum = np.cumsum(pca.explained_variance_ratio_)
    pca_meta = {
        "n_components": int(n_components),
        "fit_rows": int(len(X_pca_fit)),
        "feature_columns": [str(c) for c in X.columns],
        "cumulative_variance": float(cumsum[-1]) if len(cumsum) else 0.0,
        "explained_variance_ratio": [float(v) for v in pca.explained_variance_ratio_],
    }

    return pca, scaler, pca_meta


# =============================================================================
# Public API
# =============================================================================

def phase12_fs_for_app(
    app: str,
    *,
    cfg: Phase12FSConfig,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    app = str(app).strip().lower()
    tag = cfg.filename_tag.strip() or "run"
    t0 = datetime.now()

    shard_files = _list_train_shards(cfg.modeling_dir, app)
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    if not shard_files:
        summary = {
            "phase": 12,
            "app": app,
            "status": "skipped_no_train_shards",
            "modeling_dir": str(cfg.modeling_dir),
            "output_dir": str(out_app_dir),
            "seconds": 0.0,
        }
        _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")
        return {}, summary

    print(f"\n🔬 PHASE 12: Feature selection for app={app}")
    print(f"   Train shards: {len(shard_files):,}")
    print(f"   Output      : {out_app_dir}")

    scan = _scan_train_counts(shard_files, cfg=cfg, app=app)

    if int(scan["rows_seen"]) <= 0:
        summary = {
            "phase": 12,
            "app": app,
            "status": "skipped_empty_train",
            "modeling_dir": str(cfg.modeling_dir),
            "output_dir": str(out_app_dir),
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")
        return {}, summary

    df_fs = _collect_fs_sample(
        shard_files,
        cfg=cfg,
        app=app,
        target_counts=scan["target_counts"],
    )

    if df_fs.empty:
        summary = {
            "phase": 12,
            "app": app,
            "status": "skipped_empty_fs_sample",
            "modeling_dir": str(cfg.modeling_dir),
            "output_dir": str(out_app_dir),
            "rows_seen": int(scan["rows_seen"]),
            "seconds": float((datetime.now() - t0).total_seconds()),
        }
        _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")
        return {}, summary

    X, y, prep_info = _prepare_X_y(df_fs, cfg)
    n_select = int(min(cfg.top_k, X.shape[1]))

    print(f"   FS sample rows : {len(df_fs):,}")
    print(f"   Numeric feats  : {X.shape[1]:,}")
    print(f"   top_k          : {n_select:,}")
    print(f"   Target sample  : {prep_info['target_dist_sample']}")

    if cfg.write_sample_csv:
        sample_path = out_app_dir / f"phase12_train_sample_{app}_{tag}_n{len(df_fs)}.csv"
        df_fs.to_csv(sample_path, index=False)
    else:
        sample_path = None

    print("   Method 1: Mutual Information")
    mi_df, mi_selected, mi_info = _fit_mi(X, y, cfg=cfg, n_select=n_select)
    mi_selected, mi_removed_by_guard = _filter_feature_list(mi_selected, cfg)

    print("   Method 2: RFE / RF fallback")
    rfe_df, rfe_selected, rfe_info = _fit_rfe(X, y, cfg=cfg, n_select=n_select)
    rfe_selected, rfe_removed_by_guard = _filter_feature_list(rfe_selected, cfg)

    print("   Method 3: PCA")
    n_components = int(min(n_select, X.shape[1]))
    pca, scaler, pca_meta = _fit_pca(X, cfg=cfg, n_components=n_components)

    pca_feature_columns, pca_removed_by_guard = _filter_feature_list([str(c) for c in X.columns], cfg)
    feature_sets = {
        "MI": [str(x) for x in mi_selected],
        "RFE": [str(x) for x in rfe_selected],
        "PCA": {
            "n_components": int(n_components),
            "feature_columns": pca_feature_columns,
        },
    }

    paths: Dict[str, Optional[str]] = {
        "mi_ranking_csv": None,
        "rfe_ranking_csv": None,
        "feature_sets_json": None,
        "meta_json": None,
        "pca_meta_json": None,
        "pca_scaler_joblib": None,
        "sample_csv": str(sample_path) if sample_path else None,
    }

    elapsed = (datetime.now() - t0).total_seconds()

    summary = {
        "phase": 12,
        "app": app,
        "status": "completed",
        "mode": "app_aware_sharded_sample",
        "generated_at": datetime.now().isoformat(),
        "modeling_dir": str(cfg.modeling_dir),
        "output_dir": str(out_app_dir),
        "rows_seen_train": int(scan["rows_seen"]),
        "input_bytes": int(scan["bytes_seen"]),
        "input_size": _human_bytes(scan["bytes_seen"]),
        "target_counts_train": {str(k): int(v) for k, v in scan["target_counts"].items()},
        "fs_sample_rows": int(len(df_fs)),
        "fs_sample_mode": str(cfg.fs_sample_mode),
        "target_dist_sample": prep_info["target_dist_sample"],
        "numeric_features_total": int(X.shape[1]),
        "top_k": int(n_select),
        "mi_selected_n": int(len(mi_selected)),
        "rfe_selected_n": int(len(rfe_selected)),
        "pca_n_components": int(n_components),
        "pca_cumvar": float(pca_meta["cumulative_variance"]),
        "prep_info": prep_info,
        "leakage_guard": prep_info.get("leakage_guard", {}),
        "mi_removed_by_guard": mi_removed_by_guard,
        "rfe_removed_by_guard": rfe_removed_by_guard,
        "pca_removed_by_guard": pca_removed_by_guard,
        "mi_info": mi_info,
        "rfe_info": rfe_info,
        "pca_meta": pca_meta,
        "feature_sets": feature_sets,
        "seed": int(cfg.seed),
        "paths": paths,
        "seconds": float(elapsed),
        "note": (
            "Phase 12 runs feature selection per application using train shards from Phase 11. "
            "Returned objects are for in-process use only; persistent artifacts are written per app. "
            "AIRC leakage guard prevents alert/label/direct-probe shortcut features from being selected."
        ),
    }

    if cfg.write_artifacts:
        mi_path = out_app_dir / f"phase12_mi_ranking_{app}_{tag}.csv"
        rfe_path = out_app_dir / f"phase12_rfe_ranking_{app}_{tag}.csv"
        fs_path = out_app_dir / f"phase12_feature_sets_{app}_{tag}.json"
        meta_path = out_app_dir / f"phase12_meta_{app}_{tag}.json"
        pca_meta_path = out_app_dir / f"phase12_pca_meta_{app}_{tag}.json"

        mi_df.to_csv(mi_path, index=False)
        rfe_df.to_csv(rfe_path, index=False)
        _json_dump({"feature_sets": feature_sets}, fs_path)
        _json_dump(pca_meta, pca_meta_path)

        paths.update({
            "mi_ranking_csv": str(mi_path),
            "rfe_ranking_csv": str(rfe_path),
            "feature_sets_json": str(fs_path),
            "meta_json": str(meta_path),
            "pca_meta_json": str(pca_meta_path),
        })

        if cfg.save_pca_scaler_joblib:
            try:
                import joblib  # type: ignore
                joblib_path = out_app_dir / f"phase12_pca_scaler_{app}_{tag}.joblib"
                joblib.dump(
                    {
                        "pca": pca,
                        "scaler": scaler,
                        "feature_columns": [str(c) for c in X.columns],
                        "pca_meta": pca_meta,
                    },
                    joblib_path,
                )
                paths["pca_scaler_joblib"] = str(joblib_path)
            except Exception as e:
                summary["pca_scaler_joblib_error"] = repr(e)

        summary["paths"] = paths
        _json_dump(summary, meta_path)

    _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")

    result = {
        "feature_sets": feature_sets,
        "mi_df": mi_df,
        "rfe_df": rfe_df,
        "pca": pca,
        "scaler": scaler,
        "pca_meta": pca_meta,
        "summary": summary,
        "paths": paths,
    }

    print(f"✅ Phase 12 complete app={app}")
    print(f"   FS sample : {len(df_fs):,}")
    print(f"   Features  : {X.shape[1]:,}")
    print(f"   MI/RFE/PCA: {len(mi_selected):,}/{len(rfe_selected):,}/{n_components:,}")
    print(f"   PCA cumvar: {pca_meta['cumulative_variance']*100:.2f}%")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    return result, summary


def phase12_fs(
    *,
    cfg: Phase12FSConfig,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    print("\n" + "🔬 " + "=" * 76)
    print("PHASE 12: FEATURE SELECTION (APP-AWARE)")
    print("🔬 " + "=" * 76)

    t0 = datetime.now()

    results_by_app: Dict[str, Dict[str, Any]] = {}
    summaries: Dict[str, Any] = {}

    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        result, summary = phase12_fs_for_app(app_norm, cfg=cfg)
        results_by_app[app_norm] = result
        summaries[app_norm] = summary

    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for app, s in summaries.items():
        rows.append({
            "app": app,
            "status": s.get("status"),
            "rows_seen_train": int(s.get("rows_seen_train", 0)),
            "fs_sample_rows": int(s.get("fs_sample_rows", 0)),
            "numeric_features_total": int(s.get("numeric_features_total", 0)),
            "top_k": int(s.get("top_k", 0)),
            "mi_selected_n": int(s.get("mi_selected_n", 0)),
            "rfe_selected_n": int(s.get("rfe_selected_n", 0)),
            "pca_n_components": int(s.get("pca_n_components", 0)),
            "pca_cumvar": float(s.get("pca_cumvar", 0.0)),
            "feature_sets_json": (s.get("paths") or {}).get("feature_sets_json"),
            "meta_json": (s.get("paths") or {}).get("meta_json"),
            "seconds": float(s.get("seconds", 0.0)),
        })

    summary_df = pd.DataFrame(rows)
    if not summary_df.empty:
        summary_df.to_csv(metrics_dir / "phase12_fs_summary_by_app.csv", index=False)

    elapsed = (datetime.now() - t0).total_seconds()

    summary_all = {
        "phase": 12,
        "status": "completed",
        "selected_apps": list(cfg.selected_apps),
        "modeling_dir": str(cfg.modeling_dir),
        "output_dir": str(cfg.output_dir),
        "apps": summaries,
        "seconds": float(elapsed),
        "note": (
            "Phase 12 is app-aware and reads Phase 11 train shards. "
            "It writes per-app feature selection artifacts for Phase 13 training."
        ),
    }

    _json_dump(summary_all, metrics_dir / "phase12_fs_summary_all.json")

    print("\n✅ PHASE 12 COMPLETE")
    print(f"   Output dir: {cfg.output_dir}")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    return results_by_app, summary_all




# =============================================================================
# RAM MODE API (small-data / per-app pipeline)
# =============================================================================

def _sample_df_for_fs_ram(
    df: pd.DataFrame,
    *,
    target_col: str,
    n_take: int,
    mode: str,
    seed: int,
) -> pd.DataFrame:
    """Sample an already in-memory training DataFrame for Phase 12."""
    if df is None or df.empty:
        return pd.DataFrame()

    n_take = max(0, int(n_take))
    if n_take <= 0 or len(df) <= n_take:
        return df.copy().reset_index(drop=True)

    mode = str(mode or "stratified_proportional").lower().strip()
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
        if sub.empty or take <= 0:
            continue
        take = min(int(take), len(sub))
        picked = sub.sample(n=take, random_state=int(seed) + int(cls) * 101)
        parts.append(picked)

    if not parts:
        idx = rng.choice(len(df), size=n_take, replace=False)
        return df.iloc[idx].copy().reset_index(drop=True)

    out = pd.concat(parts, ignore_index=True)
    if len(out) > n_take:
        out = out.sample(n=n_take, random_state=int(seed)).reset_index(drop=True)
    else:
        out = out.sample(frac=1.0, random_state=int(seed)).reset_index(drop=True)
    return out


def phase12_fs_ram(
    df_train: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase12FSConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    RAM-mode Phase 12 for one active application.

    Input:
      df_train : train DataFrame returned by Phase 11 RAM mode.
      app      : active app name, e.g. http/tls/dns/ssh.

    Output:
      result   : feature_sets + ranking DataFrames + PCA metadata.
      summary  : JSON-serializable per-app summary.

    This function does not read train shards. It may write small artifacts
    (rankings, feature_sets JSON, metadata) when cfg.write_artifacts=True.
    """
    app = str(app).strip().lower()
    t0 = datetime.now()

    if cfg is None:
        cfg = Phase12FSConfig(selected_apps=(app,))

    tag = cfg.filename_tag.strip() or "run"
    out_app_dir = Path(cfg.output_dir) / f"app={app}"
    metrics_dir = Path(cfg.output_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if cfg.overwrite and cfg.write_artifacts:
        _clean_dir(out_app_dir)
    out_app_dir.mkdir(parents=True, exist_ok=True)

    if df_train is None or df_train.empty:
        elapsed = (datetime.now() - t0).total_seconds()
        summary = {
            "phase": 12,
            "app": app,
            "status": "skipped_empty_train",
            "mode": "ram",
            "rows_seen_train": 0,
            "fs_sample_rows": 0,
            "seconds": float(elapsed),
            "note": "RAM-mode Phase 12 received an empty train DataFrame.",
        }
        if cfg.write_artifacts:
            _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")
        return {}, summary

    if cfg.target_col not in df_train.columns:
        raise RuntimeError(f"Phase 12 RAM requires target_col={cfg.target_col!r} in df_train.")

    y_all = _target_series(df_train, cfg.target_col)
    train_target_counts = Counter(y_all.astype(int).tolist())

    df_fs = _sample_df_for_fs_ram(
        df_train,
        target_col=cfg.target_col,
        n_take=int(cfg.fs_sample_n),
        mode=str(cfg.fs_sample_mode),
        seed=int(cfg.seed) + abs(hash(app)) % 100_000,
    )

    if df_fs.empty:
        elapsed = (datetime.now() - t0).total_seconds()
        summary = {
            "phase": 12,
            "app": app,
            "status": "skipped_empty_fs_sample",
            "mode": "ram",
            "rows_seen_train": int(len(df_train)),
            "target_counts_train": {str(k): int(v) for k, v in train_target_counts.items()},
            "seconds": float(elapsed),
        }
        if cfg.write_artifacts:
            _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")
        return {}, summary

    X, y, prep_info = _prepare_X_y(df_fs, cfg)
    n_select = int(min(cfg.top_k, X.shape[1]))

    print(f"\n🔬 PHASE 12 RAM: Feature selection for app={app}")
    print(f"   Train rows   : {len(df_train):,}")
    print(f"   FS sample    : {len(df_fs):,}")
    print(f"   Numeric feats: {X.shape[1]:,}")
    print(f"   top_k        : {n_select:,}")
    print(f"   Target sample: {prep_info['target_dist_sample']}")

    print("   Method 1: Mutual Information")
    mi_df, mi_selected, mi_info = _fit_mi(X, y, cfg=cfg, n_select=n_select)
    mi_selected, mi_removed_by_guard = _filter_feature_list(mi_selected, cfg)

    print("   Method 2: RFE / RF fallback")
    rfe_df, rfe_selected, rfe_info = _fit_rfe(X, y, cfg=cfg, n_select=n_select)
    rfe_selected, rfe_removed_by_guard = _filter_feature_list(rfe_selected, cfg)

    print("   Method 3: PCA")
    n_components = int(min(n_select, X.shape[1]))
    pca, scaler, pca_meta = _fit_pca(X, cfg=cfg, n_components=n_components)

    pca_feature_columns, pca_removed_by_guard = _filter_feature_list([str(c) for c in X.columns], cfg)
    feature_sets = {
        "MI": [str(x) for x in mi_selected],
        "RFE": [str(x) for x in rfe_selected],
        "PCA": {
            "n_components": int(n_components),
            "feature_columns": pca_feature_columns,
        },
    }

    paths: Dict[str, Optional[str]] = {
        "mi_ranking_csv": None,
        "rfe_ranking_csv": None,
        "feature_sets_json": None,
        "meta_json": None,
        "pca_meta_json": None,
        "pca_scaler_joblib": None,
        "sample_csv": None,
    }

    elapsed = (datetime.now() - t0).total_seconds()
    summary = {
        "phase": 12,
        "app": app,
        "status": "completed",
        "mode": "ram",
        "generated_at": datetime.now().isoformat(),
        "output_dir": str(out_app_dir),
        "rows_seen_train": int(len(df_train)),
        "target_counts_train": {str(k): int(v) for k, v in train_target_counts.items()},
        "fs_sample_rows": int(len(df_fs)),
        "fs_sample_mode": str(cfg.fs_sample_mode),
        "target_dist_sample": prep_info["target_dist_sample"],
        "numeric_features_total": int(X.shape[1]),
        "top_k": int(n_select),
        "mi_selected_n": int(len(mi_selected)),
        "rfe_selected_n": int(len(rfe_selected)),
        "pca_n_components": int(n_components),
        "pca_cumvar": float(pca_meta["cumulative_variance"]),
        "prep_info": prep_info,
        "leakage_guard": prep_info.get("leakage_guard", {}),
        "mi_removed_by_guard": mi_removed_by_guard,
        "rfe_removed_by_guard": rfe_removed_by_guard,
        "pca_removed_by_guard": pca_removed_by_guard,
        "mi_info": mi_info,
        "rfe_info": rfe_info,
        "pca_meta": pca_meta,
        "feature_sets": feature_sets,
        "seed": int(cfg.seed),
        "paths": paths,
        "write_output": bool(cfg.write_artifacts),
        "seconds": float(elapsed),
        "note": (
            "RAM-mode Phase 12 runs feature selection directly from df_train returned by Phase 11. "
            "It does not read modeling shards or dataset checkpoints. "
            "AIRC leakage guard prevents alert/label/direct-probe shortcut features from being selected."
        ),
    }

    if cfg.write_sample_csv:
        sample_path = out_app_dir / f"phase12_train_sample_{app}_{tag}_n{len(df_fs)}.csv"
        df_fs.to_csv(sample_path, index=False)
        paths["sample_csv"] = str(sample_path)

    if cfg.write_artifacts:
        mi_path = out_app_dir / f"phase12_mi_ranking_{app}_{tag}.csv"
        rfe_path = out_app_dir / f"phase12_rfe_ranking_{app}_{tag}.csv"
        fs_path = out_app_dir / f"phase12_feature_sets_{app}_{tag}.json"
        meta_path = out_app_dir / f"phase12_meta_{app}_{tag}.json"
        pca_meta_path = out_app_dir / f"phase12_pca_meta_{app}_{tag}.json"

        mi_df.to_csv(mi_path, index=False)
        rfe_df.to_csv(rfe_path, index=False)
        _json_dump({"feature_sets": feature_sets}, fs_path)
        _json_dump(pca_meta, pca_meta_path)

        paths.update({
            "mi_ranking_csv": str(mi_path),
            "rfe_ranking_csv": str(rfe_path),
            "feature_sets_json": str(fs_path),
            "meta_json": str(meta_path),
            "pca_meta_json": str(pca_meta_path),
        })

        if cfg.save_pca_scaler_joblib:
            try:
                import joblib  # type: ignore
                joblib_path = out_app_dir / f"phase12_pca_scaler_{app}_{tag}.joblib"
                joblib.dump(
                    {
                        "pca": pca,
                        "scaler": scaler,
                        "feature_columns": [str(c) for c in X.columns],
                        "pca_meta": pca_meta,
                    },
                    joblib_path,
                )
                paths["pca_scaler_joblib"] = str(joblib_path)
            except Exception as e:
                summary["pca_scaler_joblib_error"] = repr(e)

        summary["paths"] = paths
        _json_dump(summary, meta_path)
        _json_dump(summary, metrics_dir / f"phase12_fs_summary_{app}.json")

    result = {
        "feature_sets": feature_sets,
        "mi_df": mi_df,
        "rfe_df": rfe_df,
        "pca": pca,
        "scaler": scaler,
        "pca_meta": pca_meta,
        "summary": summary,
        "paths": paths,
    }

    print(f"✅ Phase 12 RAM complete app={app}")
    print(f"   FS sample : {len(df_fs):,}")
    print(f"   Features  : {X.shape[1]:,}")
    print(f"   MI/RFE/PCA: {len(mi_selected):,}/{len(rfe_selected):,}/{n_components:,}")
    print(f"   PCA cumvar: {pca_meta['cumulative_variance']*100:.2f}%")
    print(f"   Time      : {elapsed/60:.2f} minutes")

    gc.collect()
    return result, summary


# RAM-mode aliases for pipeline integration.
def phase12_feature_selection_ram(
    df_train: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase12FSConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return phase12_fs_ram(df_train, app=app, cfg=cfg)


def run_phase12_fs_ram(
    df_train: pd.DataFrame,
    *,
    app: str,
    cfg: Optional[Phase12FSConfig] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return phase12_fs_ram(df_train, app=app, cfg=cfg)


# Compatibility aliases.
def phase12_feature_selection(
    *,
    cfg: Phase12FSConfig,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    return phase12_fs(cfg=cfg)


def build_phase12_fs(
    *,
    cfg: Phase12FSConfig,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    return phase12_fs(cfg=cfg)


if __name__ == "__main__":
    results, summary = phase12_fs(
        cfg=Phase12FSConfig(
            modeling_dir=Path("results/modeling"),
            output_dir=Path("results/phase12_fs"),
            selected_apps=("dns", "http", "tls", "ssh"),
            target_col="Target",
            fs_sample_n=5_000_000,
            mi_max_rows=1_000_000,
            rfe_max_rows=1_500_000,
            pca_max_rows=3_000_000,
            top_k=25,
            filename_tag="run",
            parquet_engine="fastparquet",
            overwrite=True,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
