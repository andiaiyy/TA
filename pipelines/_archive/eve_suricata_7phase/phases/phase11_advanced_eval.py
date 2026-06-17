# src/cbr/phases/phase11_advanced_eval.py
from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message=r"`sklearn\.utils\.parallel\.delayed` should be used with `sklearn\.utils\.parallel\.Parallel`.*",
    category=UserWarning,
)

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Iterable
from contextlib import nullcontext

import json
import math
import os
import sys
import time
import threading
import traceback

try:
    import psutil  # optional
except Exception:
    psutil = None

import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import LinearSVC
from sklearn.metrics import roc_curve, auc, confusion_matrix

try:
    from xgboost import XGBClassifier
except Exception:
    XGBClassifier = None

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.ioff()

try:
    import seaborn as sns  # optional
    _HAS_SNS = True
except Exception:
    _HAS_SNS = False

try:
    from threadpoolctl import threadpool_limits  # type: ignore
except Exception:
    threadpool_limits = None


# -------------------------------------------------------------------------
# CPU / Thread Safety Defaults
# -------------------------------------------------------------------------
_DEFAULT_THREAD_LIMIT = 4
os.environ.setdefault("OMP_NUM_THREADS", str(_DEFAULT_THREAD_LIMIT))
os.environ.setdefault("OPENBLAS_NUM_THREADS", str(_DEFAULT_THREAD_LIMIT))
os.environ.setdefault("MKL_NUM_THREADS", str(_DEFAULT_THREAD_LIMIT))
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", str(_DEFAULT_THREAD_LIMIT))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(_DEFAULT_THREAD_LIMIT))


# =============================================================================
# SMALL HELPERS
# =============================================================================
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fmt_elapsed(seconds: float) -> str:
    try:
        s = int(round(float(seconds)))
    except Exception:
        s = 0
    if s < 0:
        s = 0
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


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


# =============================================================================
# LIVE STATUS + REALTIME FILE LOG
# =============================================================================
class _LiveStatus:
    """
    Single-line live console status + realtime file logger.
    - Console: always overwrite the same line
    - Log file: append every event/status snapshot in realtime
    - Warnings/errors also replace the same console line (no newline spam)
    """

    def __init__(
        self,
        *,
        enabled: bool,
        every_s: float,
        stall_s: float = 600.0,
        stream=None,
    ):
        self.enabled = bool(enabled)
        self.every_s = float(every_s) if every_s and every_s > 0 else 5.0
        self.stall_s = float(stall_s) if stall_s and stall_s > 0 else 600.0
        self.stream = stream or sys.stderr

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stopped = False

        self.stage = "init"
        self.extra = ""
        self.level = "INFO"
        self.start_t = time.perf_counter()
        self.last_update_t = time.perf_counter()

        self.log_path: Optional[Path] = None
        self._last_render_len = 0

    def start(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._append_log_line(f"[{_ts()}] [INFO] Phase11 live status started.")
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run, name="phase11-live-status", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._clear_line()
        self._append_log_line(f"[{_ts()}] [INFO] Phase11 live status stopped.")

    def update(self, stage: str, extra: str = "", *, level: str = "INFO", log: bool = True) -> None:
        with self._lock:
            self.stage = str(stage)
            self.extra = str(extra)
            self.level = str(level).upper()
            self.last_update_t = time.perf_counter()

        self._render_once()
        if log:
            self._append_log_line(self._snapshot_line())

    def info(self, msg: str) -> None:
        self.update("info", msg, level="INFO", log=True)

    def warn(self, msg: str) -> None:
        self.update("warning", msg, level="WARN", log=True)

    def error(self, msg: str) -> None:
        self.update("error", msg, level="ERROR", log=True)

    def _term_width(self) -> int:
        try:
            import shutil
            w = shutil.get_terminal_size(fallback=(140, 20)).columns
            return max(60, int(w))
        except Exception:
            return 140

    def _clear_line(self) -> None:
        try:
            w = self._term_width()
            self.stream.write("\r" + (" " * w) + "\r")
            self.stream.flush()
            self._last_render_len = 0
        except Exception:
            pass

    def _emit_overwrite(self, s: str) -> None:
        try:
            w = self._term_width()
            s2 = s
            if len(s2) > w - 1:
                s2 = s2[: max(0, w - 1)]
            pad_len = max(0, self._last_render_len - len(s2))
            self.stream.write("\r" + s2 + (" " * pad_len))
            self.stream.flush()
            self._last_render_len = len(s2)
        except Exception:
            pass

    def _append_log_line(self, s: str) -> None:
        if self.log_path is None:
            return
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(s + "\n")
                f.flush()
        except Exception:
            pass

    def _snapshot_line(self) -> str:
        with self._lock:
            stage = self.stage
            extra = self.extra
            level = self.level
            start_t = self.start_t
            last_update_t = self.last_update_t

        now = time.perf_counter()
        elapsed = now - start_t
        since = now - last_update_t

        stall_txt = ""
        if since >= self.stall_s:
            stall_txt = f" | STALLED for={_fmt_elapsed(since)}"

        cpu_txt = ""
        mem_txt = ""
        if psutil is not None:
            try:
                cpu = psutil.cpu_percent(interval=None)
                vm = psutil.virtual_memory()
                cpu_txt = f" | cpu={cpu:.0f}%"
                mem_txt = f" | ram={vm.percent:.0f}% ({_fmt_bytes(vm.used)}/{_fmt_bytes(vm.total)})"
            except Exception:
                pass

        line = f"[{_ts()}] [{level}] Phase11 | elapsed={_fmt_elapsed(elapsed)} | stage={stage}"
        if extra:
            line += f" | {extra}"
        line += f" | since_update={_fmt_elapsed(since)}{stall_txt}{cpu_txt}{mem_txt}"
        return line

    def _render_once(self) -> None:
        if not self.enabled:
            return
        self._emit_overwrite(self._snapshot_line())

    def _run(self) -> None:
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

        while not self._stop.is_set():
            time.sleep(self.every_s)
            line = self._snapshot_line()
            if self.enabled:
                self._emit_overwrite(line)
            self._append_log_line(line)


# =============================================================================
# CONFIG
# =============================================================================
@dataclass(frozen=True)
class Phase11Config:
    out_dir: Path
    filename_tag: str

    target_col: str = "Target"
    seed: int = 42

    # evaluation preference:
    # - if df_test provided and valid -> use as holdout
    # - else -> do internal split on df_train
    internal_test_size: float = 0.2

    # core model params
    knn_k: int = 5
    rfc_estimators: int = 100
    rfc_n_jobs: int = 4
    blas_thread_limit: int = 1

    # LSVC params
    lsvc_c: float = 1.0
    lsvc_max_iter: int = 5000

    # XGBoost params
    xgb_n_estimators: int = 300
    xgb_max_depth: int = 8
    xgb_learning_rate: float = 0.1
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_lambda: float = 1.0
    xgb_n_jobs: int = 4
    xgb_tree_method: str = "hist"
    xgb_device: str = "cuda"
    xgb_eval_metric: str = "logloss"

    # PCA default if feature_sets doesn't specify
    pca_default_n_components: int = 20

    # drop id-ish/categorical columns
    drop_cols: Tuple[str, ...] = (
        "timestamp", "src_ip", "dest_ip", "src_port", "dest_port",
        "proto", "event_type", "alert_category",
    )

    # Which models to evaluate in ROC stage.
    # Keep order consistent with Phase 10.
    models_for_roc: Tuple[str, ...] = ("DT", "RFC", "LSVC", "XGB", "KNN")
    enable_knn_if_small: bool = True

    # Raised caps so KNN is only skipped when the eval set is truly too large.
    knn_max_train_rows: int = 3_000_000
    knn_max_test_rows: int = 1_500_000

    # KNN parallelism
    knn_n_jobs: int = -1

    # Prediction batching
    predict_batch_rows: int = 200_000

    # Progress / logging
    progress_enabled: bool = True
    progress_every_seconds: float = 5.0
    progress_stall_seconds: float = 600.0
    write_run_log: bool = True

    # which metric to select "best model" for confusion matrix
    best_metric_preference: Tuple[str, ...] = (
        "holdout_f1_attack", "f1_attack", "holdout_auc", "auc", "holdout_accuracy", "accuracy"
    )

    write_artifacts: bool = True


# =============================================================================
# NUMERIC COERCION
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


def _prepare_numeric_Xy(df: pd.DataFrame, target_col: str, drop_cols: Tuple[str, ...]) -> Tuple[pd.DataFrame, pd.Series]:
    if target_col not in df.columns:
        raise RuntimeError(f"Missing target column '{target_col}'.")

    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    vc = y.value_counts()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class: {vc.to_dict()}")

    cols_to_drop = [target_col]
    for c in drop_cols:
        if c in df.columns:
            cols_to_drop.append(c)

    X_all = df.drop(cols_to_drop, axis=1, errors="ignore").copy()
    if X_all.empty:
        raise RuntimeError("No feature columns left after dropping target/drop_cols.")

    kept_cols: list[str] = []
    X_num = pd.DataFrame(index=X_all.index)

    for c in X_all.columns:
        s_num = _series_to_numeric_like(X_all[c])
        if s_num.notna().sum() > 0:
            X_num[c] = s_num.replace([np.inf, -np.inf], np.nan).fillna(0)
            kept_cols.append(c)

    if not kept_cols:
        raise RuntimeError("No numeric/numeric-like columns available after coercion.")

    return X_num[kept_cols], y


def _align_test_to_train(X_test_all: pd.DataFrame, train_cols: list[str]) -> pd.DataFrame:
    out = X_test_all.copy()
    for c in train_cols:
        if c not in out.columns:
            out[c] = 0
    out = out[train_cols].copy()
    for c in out.columns:
        out[c] = _series_to_numeric_like(out[c]).replace([np.inf, -np.inf], np.nan).fillna(0)
    return out


# =============================================================================
# MODEL HELPERS
# =============================================================================
def _safe_score_vector(estimator, X: pd.DataFrame) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        p = estimator.predict_proba(X)
        p = np.asarray(p)
        if p.ndim == 2 and p.shape[1] >= 2:
            return p[:, 1]
        return p.ravel()

    if hasattr(estimator, "decision_function"):
        s = estimator.decision_function(X)
        return np.asarray(s).ravel()

    return estimator.predict(X).astype(float)


def _build_models(cfg: Phase11Config) -> Dict[str, Any]:
    models: Dict[str, Any] = {
        "DT": DecisionTreeClassifier(random_state=cfg.seed),
        "RFC": RandomForestClassifier(
            n_estimators=cfg.rfc_estimators,
            random_state=cfg.seed,
            n_jobs=int(cfg.rfc_n_jobs) if int(cfg.rfc_n_jobs) != 0 else None,
        ),
        "LSVC": LinearSVC(
            C=float(cfg.lsvc_c),
            max_iter=int(cfg.lsvc_max_iter),
            random_state=cfg.seed,
        ),
        "KNN": KNeighborsClassifier(
            n_neighbors=cfg.knn_k,
            n_jobs=int(cfg.knn_n_jobs) if int(cfg.knn_n_jobs) != 0 else None,
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


def _build_estimator(method: str, model_name: str, models: Dict[str, Any], n_components: int, seed: int) -> Any:
    if model_name not in models:
        raise RuntimeError(f"Requested model '{model_name}' is not available in Phase 11.")

    base = clone(models[model_name])

    needs_scaler = model_name in {"KNN", "LSVC"}
    is_tree_boost = model_name in {"DT", "RFC", "XGB"}

    if method in ("MI", "RFE"):
        if needs_scaler:
            return Pipeline([("scaler", StandardScaler()), ("model", base)])
        return base

    steps = []
    if not is_tree_boost:
        steps.append(("scaler", StandardScaler()))
    steps.append(("pca", PCA(n_components=n_components, random_state=seed)))
    steps.append(("model", base))
    return Pipeline(steps)


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
# BATCH HELPERS
# =============================================================================
def _iter_df_batches(X: pd.DataFrame, batch_rows: int) -> Iterable[tuple[int, int, pd.DataFrame]]:
    n = len(X)
    if batch_rows <= 0 or batch_rows >= n:
        yield (0, n, X)
        return

    for start in range(0, n, batch_rows):
        end = min(n, start + batch_rows)
        yield (start, end, X.iloc[start:end])


def _scores_batched(
    estimator,
    X: pd.DataFrame,
    *,
    batch_rows: int,
    live: Optional[_LiveStatus],
    stage_prefix: str,
) -> np.ndarray:
    n = len(X)
    out = np.empty(n, dtype=np.float32)
    nb = max(1, int(math.ceil(n / max(1, batch_rows))))
    b = 0

    for start, end, Xb in _iter_df_batches(X, batch_rows):
        b += 1
        if live is not None:
            live.update(stage_prefix, f"batch {b}/{nb} rows={start:,}-{end:,}/{n:,}", log=True)

        out[start:end] = _safe_score_vector(estimator, Xb).astype(np.float32, copy=False)

    if live is not None:
        live.update(stage_prefix, f"done batches={nb}", log=True)

    return out.astype(float)


def _predict_batched(
    estimator,
    X: pd.DataFrame,
    *,
    batch_rows: int,
    live: Optional[_LiveStatus],
    stage_prefix: str,
) -> np.ndarray:
    n = len(X)
    out = np.empty(n, dtype=np.int64)
    nb = max(1, int(math.ceil(n / max(1, batch_rows))))
    b = 0

    for start, end, Xb in _iter_df_batches(X, batch_rows):
        b += 1
        if live is not None:
            live.update(stage_prefix, f"batch {b}/{nb} rows={start:,}-{end:,}/{n:,}", log=True)

        out[start:end] = np.asarray(estimator.predict(Xb), dtype=np.int64)

    if live is not None:
        live.update(stage_prefix, f"done batches={nb}", log=True)

    return out


# =============================================================================
# MAIN
# =============================================================================
def phase11_advanced_evaluation(
    df_train: pd.DataFrame,
    feature_sets: dict,
    results_df: pd.DataFrame,
    cfg: Phase11Config,
    df_test: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Phase 11: ROC/AUC plots + model comparison plots + confusion matrix.

    Notes:
    - This phase uses df_train / df_test provided by pipeline.
    - If pipeline passes only Phase8 RAM samples, Phase11 visualizations reflect that sample,
      not necessarily the exact disk-loaded dataset used in Phase10.
    """
    t0_wall = time.perf_counter()
    _ensure_dir(cfg.out_dir)

    run_log_path = cfg.out_dir / "run_log_phase11.txt"
    live = _LiveStatus(
        enabled=bool(cfg.progress_enabled),
        every_s=max(2.0, float(cfg.progress_every_seconds)),
        stall_s=float(cfg.progress_stall_seconds),
    )
    live.start(run_log_path)
    live.update("start", f"tag={cfg.filename_tag} log={run_log_path.name}", log=True)

    # filenames
    roc_png = cfg.out_dir / f"roc_curves_{cfg.filename_tag}.png"
    perf_png = cfg.out_dir / f"model_performance_comparison_{cfg.filename_tag}.png"
    cm_png = cfg.out_dir / f"confusion_matrix_best_model_{cfg.filename_tag}.png"
    auc_json = cfg.out_dir / f"roc_auc_summary_{cfg.filename_tag}.json"
    meta_json = cfg.out_dir / f"phase11_summary_{cfg.filename_tag}.json"

    try:
        # -----------------------------------------------------------------
        # PREP TRAIN
        # -----------------------------------------------------------------
        live.update("prepare_train", f"rows={len(df_train):,}", log=True)
        X_train_num, y_train = _prepare_numeric_Xy(df_train, cfg.target_col, cfg.drop_cols)

        # -----------------------------------------------------------------
        # PREP TEST / INTERNAL SPLIT
        # -----------------------------------------------------------------
        use_holdout = False
        X_test_num: Optional[pd.DataFrame] = None
        y_test: Optional[pd.Series] = None

        if df_test is not None:
            live.update("prepare_test", f"rows={len(df_test):,}", log=True)
            try:
                X_test_all, y_test = _prepare_numeric_Xy(df_test, cfg.target_col, cfg.drop_cols)
                live.update("align_test_to_train", f"train_cols={len(X_train_num.columns)}", log=True)
                X_test_num = _align_test_to_train(X_test_all, X_train_num.columns.tolist())
                use_holdout = True
            except Exception as e:
                use_holdout = False
                X_test_num = None
                y_test = None
                live.warn(f"holdout test unusable; fallback to internal split | {e!r}")

        if not use_holdout:
            from sklearn.model_selection import train_test_split

            live.update("internal_split", f"test_size={cfg.internal_test_size}", log=True)
            X_train_num, X_test_num, y_train, y_test = train_test_split(
                X_train_num,
                y_train,
                test_size=cfg.internal_test_size,
                random_state=cfg.seed,
                stratify=y_train,
            )

        assert X_test_num is not None and y_test is not None

        train_dist = pd.Series(y_train).value_counts().to_dict()
        test_dist = pd.Series(y_test).value_counts().to_dict()

        # -----------------------------------------------------------------
        # PCA CONFIG
        # -----------------------------------------------------------------
        live.update("pca_config", "reading PCA config", log=True)
        n_comp = cfg.pca_default_n_components
        pca_cfg = feature_sets.get("PCA", {})
        if isinstance(pca_cfg, dict) and "n_components" in pca_cfg:
            try:
                n_comp = int(pca_cfg["n_components"])
            except Exception:
                n_comp = cfg.pca_default_n_components
        n_comp = max(2, min(n_comp, X_train_num.shape[1]))

        models = _build_models(cfg)

        # Decide models for ROC
        models_for_roc = [m for m in cfg.models_for_roc if m in models]
        missing_models = [m for m in cfg.models_for_roc if m not in models]
        if missing_models:
            live.warn(f"ROC models unavailable and skipped: {missing_models}")
        too_big_for_knn = (len(y_train) > cfg.knn_max_train_rows) or (len(y_test) > cfg.knn_max_test_rows)

        if "KNN" in models_for_roc and too_big_for_knn:
            models_for_roc = [x for x in models_for_roc if x != "KNN"]
            live.warn(
                f"KNN skipped for ROC (too large): train={len(y_train):,} test={len(y_test):,} "
                f"limits train<= {cfg.knn_max_train_rows:,}, test<= {cfg.knn_max_test_rows:,}"
            )

        if cfg.enable_knn_if_small and not too_big_for_knn and "KNN" not in models_for_roc:
            models_for_roc.append("KNN")

        live.update(
            "eval_ready",
            f"train={len(y_train):,} test={len(y_test):,} mode={'holdout' if use_holdout else 'internal_split'} "
            f"roc_models={models_for_roc}",
            log=True,
        )

        # -----------------------------------------------------------------
        # 1) ROC CURVES
        # -----------------------------------------------------------------
        live.update("roc_setup", "building ROC panels", log=True)

        roc_results_full: Dict[str, Dict[str, Dict[str, Any]]] = {}
        auc_only: Dict[str, Dict[str, Dict[str, float]]] = {}

        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        fig.suptitle("ROC Curves: MI, RFE, PCA", fontsize=14, fontweight="bold")

        methods_list = ["MI", "RFE", "PCA"]
        total_models = max(1, len(methods_list) * max(1, len(models_for_roc)))
        done_models = 0

        for i, method in enumerate(methods_list):
            ax = axes[i]
            roc_results_full[method] = {}
            auc_only[method] = {}

            if method in ("MI", "RFE"):
                feats = feature_sets.get(method, [])
                feats = feats if isinstance(feats, list) else []
                feats = [f for f in feats if f in X_train_num.columns]

                if not feats:
                    ax.set_title(f"{method} (no usable features)")
                    ax.axis("off")
                    for mdl in models_for_roc:
                        auc_only[method][mdl] = {"auc": 0.5}
                        roc_results_full[method][mdl] = {"fpr": [0, 1], "tpr": [0, 1], "auc": 0.5}
                    done_models += len(models_for_roc)
                    live.warn(f"{method} has no usable features; ROC panel skipped")
                    continue

                X_tr_m = X_train_num[feats]
                X_te_m = X_test_num[feats]
            else:
                X_tr_m = X_train_num
                X_te_m = X_test_num

            for model_name in models_for_roc:
                done_models += 1
                live.update(
                    "roc_fit",
                    f"{method}/{model_name} ({done_models}/{total_models}) train={len(X_tr_m):,} test={len(X_te_m):,}",
                    log=True,
                )

                est = _build_estimator(method, model_name, models, n_comp, cfg.seed)

                try:
                    with _limit_threads(cfg.blas_thread_limit):
                        est.fit(X_tr_m, y_train)

                    live.update(
                        "roc_score",
                        f"{method}/{model_name} ({done_models}/{total_models}) scoring",
                        log=True,
                    )
                    scores = _scores_batched(
                        est,
                        X_te_m,
                        batch_rows=int(cfg.predict_batch_rows),
                        live=live,
                        stage_prefix="roc_score",
                    )

                    fpr, tpr, _ = roc_curve(y_test, scores)
                    roc_auc = auc(fpr, tpr)

                    roc_results_full[method][model_name] = {
                        "fpr": fpr.tolist(),
                        "tpr": tpr.tolist(),
                        "auc": float(roc_auc),
                    }
                    auc_only[method][model_name] = {"auc": float(roc_auc)}
                    ax.plot(fpr, tpr, linewidth=2.0, label=f"{model_name} (AUC={roc_auc:.4f})")

                    live.update(
                        "roc_done",
                        f"{method}/{model_name} auc={roc_auc:.4f}",
                        log=True,
                    )

                except Exception as e:
                    live.warn(f"ROC failed | {method}/{model_name} | {e!r}")
                    roc_results_full[method][model_name] = {"fpr": [0, 1], "tpr": [0, 1], "auc": 0.5}
                    auc_only[method][model_name] = {"auc": 0.5}

            ax.plot([0, 1], [0, 1], "k--", linewidth=1.0, label="Random")
            ax.set_xlabel("False Positive Rate", fontweight="bold")
            ax.set_ylabel("True Positive Rate", fontweight="bold")
            ax.set_title(f"{method}", fontweight="bold")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="lower right", fontsize=9)

        plt.tight_layout()
        live.update("roc_save", "saving ROC figure", log=True)
        if cfg.write_artifacts:
            plt.savefig(roc_png, dpi=250, bbox_inches="tight")
        plt.close(fig)

        if cfg.write_artifacts:
            auc_json.write_text(json.dumps(auc_only, indent=2), encoding="utf-8")

        # -----------------------------------------------------------------
        # 2) PERFORMANCE COMPARISON PLOT
        # -----------------------------------------------------------------
        live.update("perf_plot", "building Phase10 performance plot", log=True)

        def _pick_col(primary: str, fallback: str) -> str:
            if primary in results_df.columns:
                return primary
            if fallback in results_df.columns:
                return fallback
            raise RuntimeError(f"Phase10 results_df missing both '{primary}' and '{fallback}'")

        acc_col = _pick_col("accuracy", "acc")
        f1_col = _pick_col("f1_attack", "f1")
        auc_col = _pick_col("auc", "roc_auc")

        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(f"Model Performance Comparison (tag={cfg.filename_tag})", fontsize=14, fontweight="bold")

        methods = results_df["Method"].unique().tolist()

        ax = axes[0, 0]
        for m in methods:
            d = results_df[results_df["Method"] == m]
            ax.plot(d["Model"].values, d[acc_col].values, marker="o", linewidth=2.0, label=m)
        ax.set_ylabel("Accuracy", fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title("Accuracy")

        ax = axes[0, 1]
        for m in methods:
            d = results_df[results_df["Method"] == m]
            ax.plot(d["Model"].values, d[f1_col].values, marker="s", linewidth=2.0, label=m)
        ax.set_ylabel("F1 (Attack)", fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title("F1 (Attack)")

        ax = axes[1, 0]
        for m in methods:
            d = results_df[results_df["Method"] == m]
            ax.plot(d["Model"].values, d[auc_col].values, marker="^", linewidth=2.0, label=m)
        ax.set_ylabel("AUC-ROC", fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend()
        ax.set_title("AUC-ROC")

        ax = axes[1, 1]
        heat = results_df.pivot_table(values=acc_col, index="Method", columns="Model", aggfunc="mean")
        if _HAS_SNS:
            sns.heatmap(heat, annot=True, fmt=".4f", ax=ax, cbar_kws={"label": "Accuracy"})
        else:
            im = ax.imshow(heat.values)
            ax.set_xticks(range(len(heat.columns)))
            ax.set_xticklabels(heat.columns)
            ax.set_yticks(range(len(heat.index)))
            ax.set_yticklabels(heat.index)
            fig.colorbar(im, ax=ax, label="Accuracy")
            for (ii, jj), val in np.ndenumerate(heat.values):
                ax.text(jj, ii, f"{val:.4f}", ha="center", va="center", fontsize=9)
        ax.set_title("Accuracy Heatmap")

        plt.tight_layout()
        if cfg.write_artifacts:
            plt.savefig(perf_png, dpi=250, bbox_inches="tight")
        plt.close(fig)

        # -----------------------------------------------------------------
        # 3) CONFUSION MATRIX FOR BEST MODEL
        # -----------------------------------------------------------------
        live.update("cm_pick", "selecting best model from Phase10 results", log=True)

        best = _pick_best_row(results_df, cfg.best_metric_preference)
        if best is not None and "Method" in best and "Model" in best:
            best_method = str(best["Method"])
            best_model = str(best["Model"])
        else:
            best_method = "PCA"
            best_model = "RFC"

        if best_model == "KNN" and (len(y_train) > cfg.knn_max_train_rows or len(y_test) > cfg.knn_max_test_rows):
            live.warn("best model is KNN but eval set is huge; using RFC for confusion matrix")
            best_model = "RFC"

        if best_method in ("MI", "RFE"):
            feats = feature_sets.get(best_method, [])
            feats = feats if isinstance(feats, list) else []
            feats = [f for f in feats if f in X_train_num.columns]
            if feats:
                X_tr_best = X_train_num[feats]
                X_te_best = X_test_num[feats]
            else:
                X_tr_best = X_train_num
                X_te_best = X_test_num
                live.warn(f"{best_method} best features not usable; fallback to all train-aligned features")
        else:
            X_tr_best = X_train_num
            X_te_best = X_test_num

        live.update("cm_fit", f"{best_method}/{best_model}", log=True)
        est_best = _build_estimator(best_method, best_model, models, n_comp, cfg.seed)

        with _limit_threads(cfg.blas_thread_limit):
            est_best.fit(X_tr_best, y_train)

        live.update("cm_predict", f"{best_method}/{best_model} test={len(X_te_best):,}", log=True)
        y_pred = _predict_batched(
            est_best,
            X_te_best,
            batch_rows=int(cfg.predict_batch_rows),
            live=live,
            stage_prefix="cm_predict",
        )

        cm = confusion_matrix(y_test, y_pred, labels=[0, 1])

        fig, ax = plt.subplots(figsize=(8, 6))
        if _HAS_SNS:
            sns.heatmap(
                cm,
                annot=True,
                fmt="d",
                ax=ax,
                xticklabels=["Benign", "Attack"],
                yticklabels=["Benign", "Attack"],
                cbar_kws={"label": "Count"},
            )
        else:
            im = ax.imshow(cm)
            fig.colorbar(im, ax=ax, label="Count")
            for (ii, jj), val in np.ndenumerate(cm):
                ax.text(jj, ii, str(val), ha="center", va="center", fontsize=12)
            ax.set_xticks([0, 1])
            ax.set_xticklabels(["Benign", "Attack"])
            ax.set_yticks([0, 1])
            ax.set_yticklabels(["Benign", "Attack"])

        ax.set_ylabel("True Label", fontweight="bold")
        ax.set_xlabel("Predicted Label", fontweight="bold")
        ax.set_title(f"Confusion Matrix: {best_model} ({best_method})", fontweight="bold")

        plt.tight_layout()
        live.update("cm_save", "saving confusion matrix figure", log=True)
        if cfg.write_artifacts:
            plt.savefig(cm_png, dpi=250, bbox_inches="tight")
        plt.close(fig)

        # -----------------------------------------------------------------
        # SUMMARY JSON
        # -----------------------------------------------------------------
        elapsed_s = time.perf_counter() - t0_wall
        live.update("summary", "writing summary JSON", log=True)

        summary = {
            "phase": 11,
            "generated_at": datetime.now().isoformat(),
            "elapsed_seconds": float(elapsed_s),
            "elapsed_human": _fmt_elapsed(elapsed_s),
            "eval_mode": "holdout_df_test" if use_holdout else "internal_split_from_train",
            "train_rows": int(len(y_train)),
            "test_rows": int(len(y_test)),
            "train_dist": train_dist,
            "test_dist": test_dist,
            "best_method": best_method,
            "best_model": best_model,
            "models_for_roc": models_for_roc,
            "rfc_n_jobs": int(cfg.rfc_n_jobs),
            "knn_n_jobs": int(cfg.knn_n_jobs),
            "lsvc_c": float(cfg.lsvc_c),
            "lsvc_max_iter": int(cfg.lsvc_max_iter),
            "xgb_enabled": bool("XGB" in models),
            "xgb_device": str(cfg.xgb_device),
            "xgb_tree_method": str(cfg.xgb_tree_method),
            "predict_batch_rows": int(cfg.predict_batch_rows),
            "note": (
                "Phase11 evaluates the df_train/df_test provided by pipeline. "
                "If pipeline passes RAM samples instead of the exact Phase10 disk-loaded dataset, "
                "these plots are visualization-oriented and may not perfectly reproduce Phase10."
            ),
            "paths": {
                "roc_curves_png": str(roc_png),
                "perf_comparison_png": str(perf_png),
                "confusion_matrix_png": str(cm_png),
                "roc_auc_summary_json": str(auc_json),
                "summary_json": str(meta_json),
                "run_log": str(run_log_path),
            },
            "roc_auc_summary": auc_only,
        }

        if cfg.write_artifacts:
            meta_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        live.update("done", f"elapsed={_fmt_elapsed(elapsed_s)}", log=True)
        live.stop()

        print(f"✅ PHASE 11 DONE | total_elapsed={_fmt_elapsed(elapsed_s)}")
        print(f"   eval_mode        : {'holdout_df_test' if use_holdout else 'internal_split_from_train'}")
        print(f"   train_rows       : {len(y_train):,} | dist={train_dist}")
        print(f"   test_rows        : {len(y_test):,} | dist={test_dist}")
        print(f"   best             : {best_method}/{best_model}")
        print(f"   roc_models       : {models_for_roc}")
        print(f"   roc_png          : {roc_png}")
        print(f"   perf_png         : {perf_png}")
        print(f"   cm_png           : {cm_png}")
        print(f"   auc_json         : {auc_json}")
        print(f"   summary_json     : {meta_json}")
        print(f"   run_log          : {run_log_path}")

        return {
            "roc_results_full": roc_results_full,
            "roc_auc_summary": auc_only,
            "best": {"method": best_method, "model": best_model},
            "paths": {
                "roc_curves_png": roc_png,
                "perf_comparison_png": perf_png,
                "confusion_matrix_png": cm_png,
                "roc_auc_summary_json": auc_json,
                "summary_json": meta_json,
                "run_log": run_log_path,
            },
            "summary": summary,
        }

    except Exception as e:
        tb = traceback.format_exc()
        live.error(repr(e))
        if cfg.write_run_log:
            try:
                with run_log_path.open("a", encoding="utf-8") as f:
                    f.write(tb + "\n")
                    f.flush()
            except Exception:
                pass
        live.stop()
        raise

    finally:
        if not live._stopped:
            live.stop()