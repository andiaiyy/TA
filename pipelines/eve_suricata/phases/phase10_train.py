
from __future__ import annotations

import threading
import json
import os
import gc
import time
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from contextlib import nullcontext

try:
    import psutil  # optional
except Exception:
    psutil = None

try:
    import joblib  # optional
except Exception:
    joblib = None

# -------------------------------------------------------------------------
# CPU / Thread Defaults (machine-aware)
# - Parallelism utama datang dari estimator n_jobs
# - Inner BLAS / OpenMP sengaja kecil agar tidak nested oversubscription
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

import numpy as np
import pandas as pd

from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import LinearSVC
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
)

try:
    from xgboost import XGBClassifier  # type: ignore
except Exception:
    XGBClassifier = None

try:
    from threadpoolctl import threadpool_limits  # type: ignore
except Exception:
    threadpool_limits = None


# =============================================================================
# CONFIG
# =============================================================================
@dataclass(frozen=True)
class Phase10Config:
    # IO / naming
    out_dir: Path
    filename_tag: str

    # core
    target_col: str = "Target"
    seed: int = 42

    # evaluation
    default_n_splits: int = 2
    do_holdout_eval: bool = True

    # features
    drop_cols: Tuple[str, ...] = (
        "timestamp", "src_ip", "dest_ip", "src_port", "dest_port",
        "proto", "event_type", "alert_category",
    )

    # PCA default
    pca_default_n_components: int = 20

    # model hyperparams
    knn_k: int = 5

    # RFC knobs
    rfc_estimators: int = 100
    rfc_estimators_importance: int = 200
    rfc_n_jobs: int = _WORKER_THREADS
    rfc_max_depth: Optional[int] = 16
    rfc_min_samples_leaf: int = 2

    # Linear SVM (practical SVM for large datasets)
    lsvc_c: float = 1.0
    lsvc_max_iter: int = 5_000
    lsvc_dual: str = "auto"

    # XGBoost (GPU-capable)
    xgb_n_estimators: int = 300
    xgb_max_depth: int = 8
    xgb_learning_rate: float = 0.1
    xgb_subsample: float = 0.8
    xgb_colsample_bytree: float = 0.8
    xgb_reg_lambda: float = 1.0
    xgb_n_jobs: int = _WORKER_THREADS
    xgb_tree_method: str = "hist"
    xgb_device: str = "cuda"
    xgb_eval_metric: str = "logloss"

    # KNN parallelism / behavior
    knn_n_jobs: int = _WORKER_THREADS
    knn_algorithm: str = "auto"
    knn_force_float32: bool = True
    knn_predict_batch_size: int = 250_000
    knn_methods: Tuple[str, ...] = ("MI", "RFE", "PCA")

    # CPU throttling / stability
    blas_thread_limit: int = _INNER_MATH_THREADS
    cooldown_seconds: float = 0.0
    gc_each_fold: bool = False

    # artifact controls
    write_artifacts: bool = True
    print_fold_metrics: bool = False

    # checkpoint / resume
    resume_enabled: bool = True
    checkpoint_each_fold: bool = True
    save_fitted_models: bool = False

    # ---------------------------------------------------------------------
    # DISK INPUTS
    # ---------------------------------------------------------------------
    prefer_disk_inputs: bool = False
    phase8_meta_json: Optional[Path] = None
    prefer_phase8_medium_inputs: bool = True
    phase8_medium_train_path: Optional[Path] = None
    phase8_medium_test_path: Optional[Path] = None

    train_attack_path: Optional[Path] = None
    train_benign_path: Optional[Path] = None
    test_attack_path: Optional[Path] = None
    test_benign_path: Optional[Path] = None

    # Rows to load into RAM:
    # - if >0: load sample
    # - if ==0: load FULL file(s) (⚠️ heavy)
    disk_train_rows: int = 200_000
    disk_test_rows: int = 200_000

    # Sampling strategy:
    disk_train_strategy: str = "balanced"
    disk_test_strategy: str = "balanced"
    disk_test_target_dist: Optional[Dict[int, int]] = None

    # Disk read knobs
    disk_chunksize: int = 500_000
    disk_shuffle_after_load: bool = True

    # ---------------------------------------------------------------------
    # PROGRESS / STATUS OUTPUT
    # ---------------------------------------------------------------------
    progress_enabled: bool = True
    progress_every_seconds: float = 5.0
    progress_print_fit_steps: bool = False
    progress_print_disk_steps: bool = True
    progress_print_prepare_steps: bool = True


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


def _dist_attack_benign(y: pd.Series | np.ndarray) -> dict[str, int]:
    ys = pd.Series(y)
    vc = ys.value_counts().to_dict()
    return {
        "attack": int(vc.get(1, 0)),
        "benign": int(vc.get(0, 0)),
    }


def _print_phase10_start_banner(*, cfg: Phase10Config, phase10_t0: float) -> None:
    print("\n" + "=" * 80)
    print("🤖 PHASE 10: ML MODEL TRAINING & EVALUATION (CPU-SAFE, LEAKAGE-SAFE)")
    print("=" * 80)
    print(f"📌 Phase10 start     : {_ts()}")
    print(f"📌 Prefer disk input : {cfg.prefer_disk_inputs}")
    print(f"📌 Prefer P8 medium  : {cfg.prefer_phase8_medium_inputs}")
    print(f"📌 Resume enabled    : {cfg.resume_enabled}")
    print(f"📌 disk_train_rows   : {cfg.disk_train_rows:,} (0=FULL)")
    print(f"📌 disk_test_rows    : {cfg.disk_test_rows:,} (0=FULL)")
    print(f"📌 Logical CPU       : {_LOGICAL_CPU}")
    print(f"📌 Worker threads    : {_WORKER_THREADS} (reserved={_RESERVED_THREADS})")
    print(f"📌 RFC n_jobs        : {cfg.rfc_n_jobs}")
    print(f"📌 LSVC max_iter     : {cfg.lsvc_max_iter}")
    print(f"📌 XGB device        : {cfg.xgb_device}")
    print(f"📌 XGB tree_method   : {cfg.xgb_tree_method}")
    print(f"📌 KNN n_jobs        : {cfg.knn_n_jobs}")
    print(f"📌 KNN algorithm     : {cfg.knn_algorithm}")
    print(f"📌 KNN methods       : {cfg.knn_methods}")
    print(f"📌 KNN batch predict : {cfg.knn_predict_batch_size:,}")
    print(f"📌 BLAS thread limit : {cfg.blas_thread_limit}")
    print(f"📌 Out dir           : {cfg.out_dir}")
    print(f"⏱️  Phase10 elapsed so far: {_fmt_elapsed(time.perf_counter() - phase10_t0)}")
    print("=" * 80)


def _print_phase10_input_summary(
    *,
    phase10_t0: float,
    cfg: Phase10Config,
    disk_dbg: dict,
    df_train: pd.DataFrame,
    y_train: pd.Series,
    df_test: Optional[pd.DataFrame],
    y_test: Optional[pd.Series],
    do_holdout: bool,
    n_splits: int,
) -> dict[str, dict | int]:
    vc_train = y_train.value_counts().to_dict()
    train_ab = _dist_attack_benign(y_train)

    if do_holdout and y_test is not None:
        vc_test = y_test.value_counts().to_dict()
        test_ab = _dist_attack_benign(y_test)
    else:
        vc_test = None
        test_ab = {"attack": 0, "benign": 0}

    print("\n" + "=" * 80)
    print("📦 PHASE 10 INPUT SUMMARY")
    print("=" * 80)

    if disk_dbg.get("disk_used"):
        print("📌 INPUT MODE: DISK (Phase 8 exports)")
        if disk_dbg.get("disk_source"):
            print(f"   source          : {disk_dbg.get('disk_source')}")
        print(f"   disk_train_rows={cfg.disk_train_rows:,} (0=FULL) | disk_test_rows={cfg.disk_test_rows:,} (0=FULL)")
        if disk_dbg.get("train"):
            print(f"   TRAIN load mode : {disk_dbg['train'].get('mode')}")
        if disk_dbg.get("test"):
            print(f"   TEST  load mode : {disk_dbg['test'].get('mode')}")
        if disk_dbg.get("test_load_failed"):
            print(f"   ⚠️ Test disk load failed: {disk_dbg.get('test_load_failed')}")
    else:
        print("📌 INPUT MODE: RAM (Phase 8 return samples)")
        if disk_dbg.get("disk_reason"):
            print(f"   ⚠️ Disk not used: {disk_dbg.get('disk_reason')}")

    print(f"📌 TRAIN rows={len(df_train):,} | dist={vc_train}")
    print(f"   Train Rows: Attack: {train_ab['attack']:,} | Benign: {train_ab['benign']:,}")

    if do_holdout and df_test is not None and y_test is not None and vc_test is not None:
        print(f"📌 TEST  rows={len(df_test):,} | dist={vc_test}")
        print(f"   Test Rows : Attack: {test_ab['attack']:,} | Benign: {test_ab['benign']:,}")
    else:
        print("📌 TEST  : (skipped)")
        print("   Test Rows : skipped")

    print(f"📌 CV folds          : {n_splits}")
    print(f"📌 Logical CPU       : {_LOGICAL_CPU}")
    print(f"📌 Worker threads    : {_WORKER_THREADS} (reserved={_RESERVED_THREADS})")
    print(f"📌 RFC n_jobs        : {cfg.rfc_n_jobs}")
    print(f"📌 LSVC max_iter     : {cfg.lsvc_max_iter}")
    print(f"📌 XGB device        : {cfg.xgb_device}")
    print(f"📌 XGB tree_method   : {cfg.xgb_tree_method}")
    print(f"📌 KNN n_jobs        : {cfg.knn_n_jobs}")
    print(f"📌 KNN algorithm     : {cfg.knn_algorithm}")
    print(f"📌 KNN methods       : {cfg.knn_methods}")
    print(f"📌 KNN batch predict : {cfg.knn_predict_batch_size:,}")
    print(f"📌 BLAS thread limit : {cfg.blas_thread_limit}")
    print(f"📌 Cooldown per fold : {cfg.cooldown_seconds:.1f}s | GC each fold: {cfg.gc_each_fold}")
    print(f"📌 Out dir           : {cfg.out_dir}")
    print(f"⏱️  Phase10 elapsed so far: {_fmt_elapsed(time.perf_counter() - phase10_t0)}")
    print("=" * 80)

    return {
        "train_vc": vc_train,
        "train_ab": train_ab,
        "test_ab": test_ab,
    }


class _ProgressThrottle:
    def __init__(self, enabled: bool, every_seconds: float):
        self.enabled = bool(enabled)
        try:
            self.every = float(every_seconds)
        except Exception:
            self.every = 5.0
        if self.every <= 0:
            self.every = 1.0
        self._last = 0.0

    def should_print(self) -> bool:
        if not self.enabled:
            return False
        now = time.time()
        if (now - self._last) >= self.every:
            self._last = now
            return True
        return False

    def force(self) -> None:
        self._last = 0.0


class _LiveStatus:
    """
    Single-line live console status + realtime file logger.
    - Console: always overwrite the same line
    - Log file: append every event/status snapshot in realtime
    - Stores structured progress state: fs/model/fold
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

        self.fs_method = "pending"
        self.model_name = "pending"
        self.fold_text = "0/0"

        self.log_path: Optional[Path] = None
        self._last_render_len = 0

    def start(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._append_log_line(f"[{_ts()}] [INFO] Phase10 live status started.")
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run, name="phase10-live-status", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._clear_line()
        self._append_log_line(f"[{_ts()}] [INFO] Phase10 live status stopped.")

    def update(
        self,
        stage: str,
        extra: str = "",
        *,
        level: str = "INFO",
        log: bool = True,
        fs_method: Optional[str] = None,
        model_name: Optional[str] = None,
        fold_text: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.stage = str(stage)
            self.extra = str(extra)
            self.level = str(level).upper()
            self.last_update_t = time.perf_counter()

            if fs_method is not None:
                self.fs_method = str(fs_method)
            if model_name is not None:
                self.model_name = str(model_name)
            if fold_text is not None:
                self.fold_text = str(fold_text)

        self._render_once()
        if log:
            self._append_log_line(self._snapshot_line())

    def warn(
        self,
        msg: str,
        *,
        fs_method: Optional[str] = None,
        model_name: Optional[str] = None,
        fold_text: Optional[str] = None,
    ) -> None:
        self.update(
            "warning",
            msg,
            level="WARN",
            log=True,
            fs_method=fs_method,
            model_name=model_name,
            fold_text=fold_text,
        )

    def info(
        self,
        msg: str,
        *,
        fs_method: Optional[str] = None,
        model_name: Optional[str] = None,
        fold_text: Optional[str] = None,
    ) -> None:
        self.update(
            "info",
            msg,
            level="INFO",
            log=True,
            fs_method=fs_method,
            model_name=model_name,
            fold_text=fold_text,
        )

    def _term_width(self) -> int:
        try:
            import shutil
            w = shutil.get_terminal_size(fallback=(180, 20)).columns
            return max(80, int(w))
        except Exception:
            return 180

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
            fs_method = self.fs_method
            model_name = self.model_name
            fold_text = self.fold_text

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

        line = (
            f"[{_ts()}] [{level}] Phase10"
            f" | elapsed={_fmt_elapsed(elapsed)}"
            f" | stage={stage}"
            f" | fs={fs_method}"
            f" | model={model_name}"
            f" | fold={fold_text}"
        )
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


def _cooldown_sleep(seconds: float) -> None:
    try:
        s = float(seconds)
    except Exception:
        s = 0.0
    if s <= 0:
        return
    time.sleep(s)


# =============================================================================
# CHECKPOINT / RESUME HELPERS
# =============================================================================
def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _checkpoint_root(cfg: Phase10Config) -> Path:
    return Path(cfg.out_dir) / "checkpoints"


def _partial_results_path(cfg: Phase10Config) -> Path:
    return _checkpoint_root(cfg) / f"partial_results_{cfg.filename_tag}.csv"


def _job_key(method: str, model_name: str) -> str:
    return f"{str(method).upper()}__{str(model_name).upper()}"


def _job_dir(cfg: Phase10Config, method: str, model_name: str) -> Path:
    return _checkpoint_root(cfg) / str(method).upper() / str(model_name).upper()


def _job_state_path(cfg: Phase10Config, method: str, model_name: str) -> Path:
    return _job_dir(cfg, method, model_name) / "job_state.json"


def _job_row_path(cfg: Phase10Config, method: str, model_name: str) -> Path:
    return _job_dir(cfg, method, model_name) / "result_row.json"


def _job_model_path(cfg: Phase10Config, method: str, model_name: str) -> Path:
    return _job_dir(cfg, method, model_name) / "final_model.joblib"


def _load_json_or_none(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_job_state(cfg: Phase10Config, method: str, model_name: str) -> dict:
    p = _job_state_path(cfg, method, model_name)
    obj = _load_json_or_none(p)
    return obj if isinstance(obj, dict) else {}


def _save_job_state(cfg: Phase10Config, method: str, model_name: str, state: dict) -> None:
    p = _job_state_path(cfg, method, model_name)
    _ensure_dir(p.parent)
    p.write_text(json.dumps(_json_safe(state), indent=2), encoding="utf-8")


def _save_job_row(cfg: Phase10Config, method: str, model_name: str, row: dict) -> None:
    p = _job_row_path(cfg, method, model_name)
    _ensure_dir(p.parent)
    p.write_text(json.dumps(_json_safe(row), indent=2), encoding="utf-8")


def _load_job_row(cfg: Phase10Config, method: str, model_name: str) -> Optional[dict]:
    p = _job_row_path(cfg, method, model_name)
    obj = _load_json_or_none(p)
    return obj if isinstance(obj, dict) else None


def _job_completed_row(cfg: Phase10Config, method: str, model_name: str) -> Optional[dict]:
    state = _load_job_state(cfg, method, model_name)
    if str(state.get("status", "")).lower() != "completed":
        return None
    row = _load_job_row(cfg, method, model_name)
    if isinstance(row, dict) and row:
        return row
    row2 = state.get("result_row")
    return row2 if isinstance(row2, dict) else None


def _save_estimator_checkpoint(cfg: Phase10Config, method: str, model_name: str, estimator) -> Optional[Path]:
    if not cfg.save_fitted_models or joblib is None or estimator is None:
        return None
    p = _job_model_path(cfg, method, model_name)
    _ensure_dir(p.parent)
    try:
        joblib.dump(estimator, p)
        return p
    except Exception:
        return None


def _ordered_results_df(
    results_map: dict[str, dict],
    methods: list[str] | tuple[str, ...],
    model_order: list[str] | tuple[str, ...],
) -> pd.DataFrame:
    rows: list[dict] = []
    for method in methods:
        for model_name in model_order:
            row = results_map.get(_job_key(method, model_name))
            if isinstance(row, dict) and row:
                rows.append(row)
    return pd.DataFrame(rows)


def _save_partial_results(
    results_map: dict[str, dict],
    cfg: Phase10Config,
    methods: list[str] | tuple[str, ...],
    model_order: list[str] | tuple[str, ...],
) -> Optional[Path]:
    if not cfg.write_artifacts:
        return None
    p = _partial_results_path(cfg)
    _ensure_dir(p.parent)
    df = _ordered_results_df(results_map, methods, model_order)
    df.to_csv(p, index=False)
    return p


def _default_model_order() -> list[str]:
    return ["DT", "RFC", "LSVC", "XGB"]


def _model_summary_path(cfg: Phase10Config, model_name: str, index_1based: int) -> Path:
    return Path(cfg.out_dir) / f"phase10_{index_1based}{model_name}_summary_{cfg.filename_tag}.json"


def _save_model_summaries(
    results_df: pd.DataFrame,
    cfg: Phase10Config,
    *,
    generated_at: str,
    common_info: dict,
) -> dict[str, str]:
    if not cfg.write_artifacts or results_df is None or results_df.empty:
        return {}

    paths: dict[str, str] = {}
    model_order = _default_model_order()
    for idx, model_name in enumerate(model_order, start=1):
        df_model = results_df[results_df["Model"].astype(str) == model_name].copy()
        if df_model.empty:
            continue

        best_row = None
        if "f1_attack" in df_model.columns:
            try:
                best_idx = df_model["f1_attack"].astype(float).idxmax()
                best_row = df_model.loc[best_idx].to_dict()
            except Exception:
                best_row = None

        payload = {
            "phase": 10,
            "generated_at": generated_at,
            "model_name": model_name,
            "model_order_index": idx,
            "results_rows": int(len(df_model)),
            "results": _json_safe(df_model.to_dict(orient="records")),
            "best_by_cv_f1_attack": _json_safe(best_row),
            **_json_safe(common_info),
        }
        p = _model_summary_path(cfg, model_name, idx)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        paths[model_name] = str(p)
    return paths


# =============================================================================
# NUMERIC / FEATURE PREP
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


# =============================================================================
# CORE METRICS
# =============================================================================
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


def _final_estimator(estimator):
    if isinstance(estimator, Pipeline):
        try:
            return estimator.steps[-1][1]
        except Exception:
            return estimator
    return estimator


def _is_knn_estimator(estimator) -> bool:
    try:
        return isinstance(_final_estimator(estimator), KNeighborsClassifier)
    except Exception:
        return False


def _slice_rows(X, start: int, end: int):
    if hasattr(X, "iloc"):
        return X.iloc[start:end]
    return X[start:end]


def _knn_to_numpy_X(X, force_float32: bool):
    dtype = np.float32 if force_float32 else None
    arr = np.asarray(X, dtype=dtype)
    return np.ascontiguousarray(arr)


def _to_numpy_1d(y):
    arr = np.asarray(y)
    if arr.ndim > 1:
        arr = arr.ravel()
    return arr


def _normalize_knn_methods(knn_methods: Tuple[str, ...] | list[str] | None) -> set[str]:
    if not knn_methods:
        return set()
    out: set[str] = set()
    for m in knn_methods:
        try:
            s = str(m).strip().upper()
        except Exception:
            s = ""
        if s:
            out.add(s)
    return out


def _predict_with_scores_knn_batched(
    estimator,
    X_te,
    *,
    batch_size: int,
    live: Optional[_LiveStatus] = None,
    label: str = "",
) -> tuple[np.ndarray, np.ndarray]:
    n_total = len(X_te)
    if n_total <= 0:
        return np.asarray([], dtype=np.int64), np.asarray([], dtype=np.float32)

    try:
        batch_size = int(batch_size)
    except Exception:
        batch_size = 0

    if batch_size <= 0 or batch_size >= n_total:
        if live is not None:
            live.update("predict", f"{label} predict_proba rows={n_total:,}")
        proba = np.asarray(estimator.predict_proba(X_te))
        if proba.ndim == 2 and proba.shape[1] >= 2:
            classes = getattr(estimator, "classes_", None)
            if classes is None:
                classes = getattr(_final_estimator(estimator), "classes_", None)
            if classes is not None:
                classes = np.asarray(classes)
                y_pred = classes[np.argmax(proba, axis=1)].astype(np.int64, copy=False)
                pos_idx = int(np.where(classes == 1)[0][0]) if np.any(classes == 1) else min(1, proba.shape[1] - 1)
            else:
                y_pred = np.argmax(proba, axis=1).astype(np.int64, copy=False)
                pos_idx = min(1, proba.shape[1] - 1)
            scores = np.asarray(proba[:, pos_idx], dtype=np.float32).ravel()
            return y_pred, scores

        y_pred = np.asarray(estimator.predict(X_te)).astype(np.int64, copy=False)
        return y_pred, y_pred.astype(np.float32, copy=False)

    pred_parts: list[np.ndarray] = []
    score_parts: list[np.ndarray] = []
    classes = getattr(estimator, "classes_", None)
    if classes is None:
        classes = getattr(_final_estimator(estimator), "classes_", None)
    classes = np.asarray(classes) if classes is not None else None

    n_batches = (n_total + batch_size - 1) // batch_size
    for batch_i, start in enumerate(range(0, n_total, batch_size), start=1):
        end = min(start + batch_size, n_total)
        xb = _slice_rows(X_te, start, end)

        if live is not None:
            live.update(
                "predict",
                f"{label} predict_proba batch={batch_i}/{n_batches} rows={end:,}/{n_total:,}",
            )

        proba = np.asarray(estimator.predict_proba(xb))
        if proba.ndim == 2 and proba.shape[1] >= 2:
            if classes is not None:
                y_pred_b = classes[np.argmax(proba, axis=1)].astype(np.int64, copy=False)
                pos_idx = int(np.where(classes == 1)[0][0]) if np.any(classes == 1) else min(1, proba.shape[1] - 1)
            else:
                y_pred_b = np.argmax(proba, axis=1).astype(np.int64, copy=False)
                pos_idx = min(1, proba.shape[1] - 1)
            scores_b = np.asarray(proba[:, pos_idx], dtype=np.float32).ravel()
        else:
            y_pred_b = np.asarray(estimator.predict(xb)).astype(np.int64, copy=False)
            scores_b = y_pred_b.astype(np.float32, copy=False)

        pred_parts.append(y_pred_b)
        score_parts.append(scores_b)

    return np.concatenate(pred_parts), np.concatenate(score_parts)


def _eval_once(
    estimator,
    X_tr,
    y_tr,
    X_te,
    y_te,
    *,
    thread_limit: int | None = None,
    live: Optional[_LiveStatus] = None,
    label: str = "",
    knn_force_float32: bool = False,
    knn_predict_batch_size: int = 0,
) -> Dict[str, float]:
    is_knn = _is_knn_estimator(estimator)

    if is_knn:
        X_tr = _knn_to_numpy_X(X_tr, knn_force_float32)
        X_te = _knn_to_numpy_X(X_te, knn_force_float32)

    y_tr = _to_numpy_1d(y_tr)
    y_te = _to_numpy_1d(y_te).astype(np.int64, copy=False)

    with _limit_threads(thread_limit):
        if live is not None:
            live.update("fit", f"{label} fit()")

        estimator.fit(X_tr, y_tr)

        if is_knn and hasattr(estimator, "predict_proba"):
            y_pred, scores = _predict_with_scores_knn_batched(
                estimator,
                X_te,
                batch_size=int(knn_predict_batch_size),
                live=live,
                label=label,
            )
        else:
            if live is not None:
                live.update("predict", f"{label} predict()")
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
            if live is not None:
                live.update("auc", f"{label} roc_auc")
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


def _prepare_numeric_Xy(df: pd.DataFrame, cfg: Phase10Config) -> Tuple[pd.DataFrame, pd.Series]:
    if cfg.target_col not in df.columns:
        raise RuntimeError(f"Missing target column '{cfg.target_col}' in input df.")

    y = pd.to_numeric(df[cfg.target_col], errors="coerce").fillna(0).astype(int)
    vc = y.value_counts()
    if len(vc) < 2:
        raise RuntimeError(f"Target has only one class: {vc.to_dict()}")

    cols_to_drop = [cfg.target_col]
    for c in cfg.drop_cols:
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
        raise RuntimeError("No numeric/numeric-like columns available for training after coercion.")

    return X_num[kept_cols], y


def _align_test_to_train(X_test_all: pd.DataFrame, train_numeric_cols: list[str]) -> pd.DataFrame:
    out = X_test_all.copy()
    for c in train_numeric_cols:
        if c not in out.columns:
            out[c] = 0
    out = out[train_numeric_cols].copy()
    for c in out.columns:
        out[c] = _series_to_numeric_like(out[c]).replace([np.inf, -np.inf], np.nan).fillna(0)
    return out


def _build_models(cfg: Phase10Config) -> Dict[str, Any]:
    if XGBClassifier is None:
        raise RuntimeError(
            "xgboost is not installed. Install it first, for example: pip install xgboost"
        )

    return {
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
        "XGB": XGBClassifier(
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
        ),
        "KNN": KNeighborsClassifier(
            n_neighbors=cfg.knn_k,
            algorithm=cfg.knn_algorithm,
            n_jobs=cfg.knn_n_jobs,
        ),
    }


def _make_estimator(
    method: str,
    model_name: str,
    base_models: Dict[str, Any],
    n_components: int,
    cfg: Phase10Config,
):
    m = clone(base_models[model_name])

    if method in ("MI", "RFE"):
        if model_name in ("KNN", "LSVC"):
            return Pipeline([("scaler", StandardScaler()), ("model", m)])
        return m

    return Pipeline([
        ("scaler", StandardScaler()),
        ("pca", PCA(n_components=n_components, random_state=cfg.seed)),
        ("model", m),
    ])


# =============================================================================
# DISK LOADING
# =============================================================================
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _path_if_exists(v: Any) -> Optional[Path]:
    try:
        if v is None:
            return None
        p = Path(v)
        return p if p.exists() else None
    except Exception:
        return None


def _load_full_table(
    path: Path,
    *,
    chunksize: int,
    target_col: str,
    prog: _ProgressThrottle,
    label: str,
    live: Optional[_LiveStatus] = None,
) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        if live is not None:
            live.update("disk_load", f"{label} parquet read {path.name}", log=True)
        df = pd.read_parquet(path)
        df = _ensure_target_binary(df, target_col)
        if live is not None:
            live.update("disk_load_done", f"{label} rows={len(df):,}", log=True)
        return df
    return _load_full_csv(
        path,
        chunksize=chunksize,
        target_col=target_col,
        prog=prog,
        label=label,
        live=live,
    )


def _load_phase8_medium_direct(
    *,
    train_path: Path,
    test_path: Optional[Path],
    cfg: Phase10Config,
    live: Optional[_LiveStatus] = None,
) -> tuple[pd.DataFrame, Optional[pd.DataFrame], dict]:
    prog = _ProgressThrottle(cfg.progress_enabled and cfg.progress_print_disk_steps, cfg.progress_every_seconds)
    dbg: dict = {
        "mode": "phase8_medium_full",
        "train_path": str(train_path),
        "test_path": str(test_path) if test_path is not None else None,
    }

    df_train = _load_full_table(
        train_path,
        chunksize=int(cfg.disk_chunksize),
        target_col=cfg.target_col,
        prog=prog,
        label="TRAIN-MEDIUM",
        live=live,
    )

    df_test = None
    if cfg.do_holdout_eval and test_path is not None and Path(test_path).exists():
        df_test = _load_full_table(
            test_path,
            chunksize=int(cfg.disk_chunksize),
            target_col=cfg.target_col,
            prog=prog,
            label="TEST-MEDIUM",
            live=live,
        )
    elif cfg.do_holdout_eval:
        dbg["test_missing"] = True

    return df_train, df_test, dbg


def _infer_benign_path(attack_path: Path) -> Path:
    name = attack_path.name
    if "__train_ATTACK" in name:
        return attack_path.with_name(name.replace("__train_ATTACK", "__train_BENIGN"))
    if "__testFAIR_ATTACK" in name:
        return attack_path.with_name(name.replace("__testFAIR_ATTACK", "__testFAIR_BENIGN"))
    if "__train" in name and "__train_BENIGN" not in name:
        return attack_path.with_name(name.replace("__train", "__train_BENIGN"))
    if "__testFAIR" in name and "__testFAIR_BENIGN" not in name:
        return attack_path.with_name(name.replace("__testFAIR", "__testFAIR_BENIGN"))
    if "__test" in name and "__test_BENIGN" not in name:
        return attack_path.with_name(name.replace("__test", "__test_BENIGN"))
    return attack_path.with_name(name + "_BENIGN")


def _resolve_paths_from_phase8_meta(cfg: Phase10Config) -> dict:
    if cfg.phase8_meta_json is None:
        return {}

    p = Path(cfg.phase8_meta_json)
    if not p.exists():
        return {}

    meta = _read_json(p)
    out: dict = {}

    paths_extra = meta.get("paths_extra") or {}
    if isinstance(paths_extra, dict):
        out["train_attack_path"] = paths_extra.get("train_attack_csv")
        out["train_benign_path"] = paths_extra.get("train_benign_csv")
        out["test_attack_path"] = paths_extra.get("test_attack_csv")
        out["test_benign_path"] = paths_extra.get("test_benign_csv")

    paths = meta.get("paths") or {}
    if isinstance(paths, dict):
        out["train_combined_path"] = paths.get("train_csv")
        out["test_combined_path"] = paths.get("test_fair_csv") or paths.get("test_csv")

    medium = meta.get("paths_medium_for_phase10") or {}
    if isinstance(medium, dict):
        out["phase8_medium_format"] = medium.get("format")
        out["phase8_medium_dir"] = medium.get("dir")
        out["phase8_medium_train_path"] = medium.get("train_parquet") or medium.get("train_csv")
        out["phase8_medium_test_path"] = medium.get("test_parquet") or medium.get("test_csv")

    dist = meta.get("dist_test_fair_target") or meta.get("dist_test_fair") or None
    if isinstance(dist, dict):
        try:
            out["disk_test_target_dist"] = {int(k): int(v) for k, v in dist.items()}
        except Exception:
            pass

    return out


def _pick_class_counts(strategy: str, n_total: int, target_dist: Optional[Dict[int, int]] = None) -> tuple[int, int]:
    if n_total <= 0:
        return (0, 0)

    s = (strategy or "balanced").lower().strip()

    if s == "proportional" and target_dist:
        a = int(target_dist.get(1, 0))
        b = int(target_dist.get(0, 0))
        den = a + b
        if den > 0:
            n_attack = int(round(n_total * (a / den)))
            n_attack = max(1, min(n_attack, n_total))
            n_ben = n_total - n_attack
            return (n_ben, n_attack)

    n_attack = max(1, n_total // 2)
    n_ben = n_total - n_attack
    return (n_ben, n_attack)


def _ensure_target_binary(df: pd.DataFrame, target_col: str) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return df
    if target_col not in df.columns:
        raise RuntimeError(f"Missing target column '{target_col}' in disk data.")
    y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).astype(int)
    df = df.copy()
    df[target_col] = (y == 1).astype(int)
    return df


def _load_full_csv(
    path: Path,
    *,
    chunksize: int,
    target_col: str,
    prog: _ProgressThrottle,
    label: str,
    live: Optional[_LiveStatus] = None,
) -> pd.DataFrame:
    dfs: list[pd.DataFrame] = []
    total_rows = 0
    chunk_i = 0

    for chunk in pd.read_csv(path, chunksize=chunksize):
        chunk_i += 1
        chunk = _ensure_target_binary(chunk, target_col)
        dfs.append(chunk)
        total_rows += len(chunk)

        if prog.should_print() and live is not None:
            live.update("disk_load", f"{label} chunks={chunk_i:,} rows={total_rows:,}", log=True)

    if not dfs:
        return pd.DataFrame()

    if live is not None:
        live.update("disk_load_done", f"{label} rows={total_rows:,}", log=True)

    return pd.concat(dfs, ignore_index=True)


def _reservoir_update_class(
    reservoir: Optional[pd.DataFrame],
    seen: int,
    new_df: pd.DataFrame,
    k: int,
    rng: np.random.Generator,
) -> tuple[Optional[pd.DataFrame], int]:
    if k <= 0 or new_df is None or len(new_df) == 0:
        return reservoir, seen

    if reservoir is None:
        reservoir = new_df.iloc[:0].copy()

    need = k - len(reservoir)
    if need > 0:
        take = min(need, len(new_df))
        if take > 0:
            reservoir = pd.concat([reservoir, new_df.iloc[:take].copy()], ignore_index=True)
            new_df = new_df.iloc[take:]
            seen += take

    m = len(new_df)
    if m <= 0:
        return reservoir, seen

    i = seen + np.arange(1, m + 1, dtype=np.int64)
    j = (rng.random(m) * i).astype(np.int64)
    mask = j < k
    if mask.any():
        pos = j[mask].tolist()
        src = np.where(mask)[0].tolist()
        for ppos, sidx in zip(pos, src):
            reservoir.iloc[ppos] = new_df.iloc[sidx].values  # type: ignore[index]

    seen += m
    return reservoir, seen


def _load_stratified_sample_from_single_file(
    path: Path,
    *,
    n_total: int,
    strategy: str,
    target_dist: Optional[Dict[int, int]],
    seed: int,
    target_col: str,
    chunksize: int,
    prog: _ProgressThrottle,
    label: str,
    live: Optional[_LiveStatus] = None,
) -> pd.DataFrame:
    n_ben, n_atk = _pick_class_counts(strategy, n_total, target_dist=target_dist)

    rng = np.random.default_rng(seed)
    res0: Optional[pd.DataFrame] = None
    res1: Optional[pd.DataFrame] = None
    seen0 = 0
    seen1 = 0

    chunk_i = 0
    rows_total = 0

    for chunk in pd.read_csv(path, chunksize=chunksize):
        chunk_i += 1
        chunk = _ensure_target_binary(chunk, target_col)
        if len(chunk) == 0:
            continue

        rows_total += len(chunk)
        ben = chunk[chunk[target_col] == 0]
        atk = chunk[chunk[target_col] == 1]

        if n_ben > 0:
            res0, seen0 = _reservoir_update_class(res0, seen0, ben, n_ben, rng)
        if n_atk > 0:
            res1, seen1 = _reservoir_update_class(res1, seen1, atk, n_atk, rng)

        if prog.should_print() and live is not None:
            r0 = 0 if res0 is None else len(res0)
            r1 = 0 if res1 is None else len(res1)
            live.update(
                "disk_sample",
                f"{label} chunks={chunk_i:,} rows_seen={rows_total:,} | ben={r0:,}/{n_ben:,} atk={r1:,}/{n_atk:,}",
                log=True,
            )

    parts = []
    if res0 is not None and len(res0):
        parts.append(res0)
    if res1 is not None and len(res1):
        parts.append(res1)

    if not parts:
        return pd.DataFrame()

    df = pd.concat(parts, ignore_index=True)

    if live is not None:
        live.update(
            "disk_sample_done",
            f"{label} sampled_rows={len(df):,} | ben={0 if res0 is None else len(res0):,} atk={0 if res1 is None else len(res1):,}",
            log=True,
        )
    return df


def _load_sample_from_single_class_file(
    path: Path,
    *,
    n_rows: int,
    expected_label: int,
    seed: int,
    target_col: str,
    chunksize: int,
    prog: _ProgressThrottle,
    label: str,
    live: Optional[_LiveStatus] = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    res: Optional[pd.DataFrame] = None
    seen = 0
    chunk_i = 0
    rows_total = 0

    for chunk in pd.read_csv(path, chunksize=chunksize):
        chunk_i += 1
        chunk = _ensure_target_binary(chunk, target_col)
        if len(chunk) == 0:
            continue

        if target_col in chunk.columns:
            chunk = chunk[chunk[target_col] == expected_label]
        if len(chunk) == 0:
            continue

        rows_total += len(chunk)
        res, seen = _reservoir_update_class(res, seen, chunk, n_rows, rng)

        if prog.should_print() and live is not None:
            r = 0 if res is None else len(res)
            live.update(
                "disk_sample",
                f"{label} chunks={chunk_i:,} rows_seen={rows_total:,} | kept={r:,}/{n_rows:,}",
                log=True,
            )

    if res is None:
        return pd.DataFrame()

    if live is not None:
        live.update(
            "disk_sample_done",
            f"{label} sampled_rows={len(res):,}",
            log=True,
        )
    return res


def _load_disk_two_files(
    attack_path: Path,
    benign_path: Optional[Path],
    *,
    n_total: int,
    strategy: str,
    target_dist: Optional[Dict[int, int]],
    seed: int,
    target_col: str,
    chunksize: int,
    prog: _ProgressThrottle,
    label: str,
    live: Optional[_LiveStatus] = None,
) -> pd.DataFrame:
    attack_path = Path(attack_path)
    if not attack_path.exists():
        raise RuntimeError(f"Disk load: attack_path not found: {attack_path}")

    if benign_path is None:
        inferred = _infer_benign_path(attack_path)
        if inferred.exists():
            benign_path = inferred
    if benign_path is not None:
        benign_path = Path(benign_path)
        if not benign_path.exists():
            benign_path = None

    if n_total == 0:
        if live is not None:
            live.update("disk_load", f"{label} full attack+benign chunked load", log=True)
        df_a = _load_full_csv(
            attack_path,
            chunksize=chunksize,
            target_col=target_col,
            prog=prog,
            label=f"{label}/ATTACK",
            live=live,
        )
        df_b = (
            _load_full_csv(
                benign_path,
                chunksize=chunksize,
                target_col=target_col,
                prog=prog,
                label=f"{label}/BENIGN",
                live=live,
            )
            if benign_path
            else pd.DataFrame()
        )
        return pd.concat([df_a, df_b], ignore_index=True) if (len(df_a) or len(df_b)) else pd.DataFrame()

    n_ben, n_atk = _pick_class_counts(strategy, n_total, target_dist=target_dist)
    if live is not None:
        live.update("disk_sample", f"{label} target sample -> atk={n_atk:,}, ben={n_ben:,}", log=True)

    df_a = (
        _load_sample_from_single_class_file(
            attack_path,
            n_rows=n_atk,
            expected_label=1,
            seed=seed,
            target_col=target_col,
            chunksize=chunksize,
            prog=prog,
            label=f"{label}/ATTACK",
            live=live,
        )
        if n_atk > 0
        else pd.DataFrame()
    )

    df_b = (
        _load_sample_from_single_class_file(
            benign_path,
            n_rows=n_ben,
            expected_label=0,
            seed=seed + 1,
            target_col=target_col,
            chunksize=chunksize,
            prog=prog,
            label=f"{label}/BENIGN",
            live=live,
        )
        if (benign_path is not None and n_ben > 0)
        else pd.DataFrame()
    )

    df = pd.concat([df_a, df_b], ignore_index=True) if (len(df_a) or len(df_b)) else pd.DataFrame()
    return _ensure_target_binary(df, target_col)


def _load_disk_auto(
    *,
    train_or_test: str,
    attack_path: Optional[Path],
    benign_path: Optional[Path],
    combined_path: Optional[Path],
    n_rows: int,
    strategy: str,
    target_dist: Optional[Dict[int, int]],
    seed: int,
    target_col: str,
    chunksize: int,
    cfg: Phase10Config,
    live: Optional[_LiveStatus] = None,
) -> tuple[pd.DataFrame, dict]:
    dbg: dict = {"mode": None}
    prog = _ProgressThrottle(cfg.progress_enabled and cfg.progress_print_disk_steps, cfg.progress_every_seconds)
    label = f"{train_or_test.upper()}-DISK"

    if attack_path is not None:
        ap = Path(attack_path)
        bp = None
        if benign_path is not None:
            bp = Path(benign_path)
            if not bp.exists():
                bp = None
        if bp is None:
            inf = _infer_benign_path(ap)
            if inf.exists():
                bp = inf

        if bp is not None and ap.exists():
            dbg["mode"] = "two_files"
            dbg["attack_path"] = str(ap)
            dbg["benign_path"] = str(bp)
            df = _load_disk_two_files(
                ap,
                bp,
                n_total=n_rows,
                strategy=strategy,
                target_dist=target_dist,
                seed=seed,
                target_col=target_col,
                chunksize=chunksize,
                prog=prog,
                label=label,
                live=live,
            )
            return df, dbg

    if combined_path is None:
        raise RuntimeError(f"Disk load ({train_or_test}): no usable path (two-files not found, combined missing).")

    cp = Path(combined_path)
    if not cp.exists():
        raise RuntimeError(f"Disk load ({train_or_test}): combined_path not found: {cp}")

    dbg["combined_path"] = str(cp)

    if n_rows == 0:
        dbg["mode"] = "combined_full"
        if live is not None:
            live.update("disk_load", f"{label} full combined load", log=True)
        df = _load_full_csv(
            cp,
            chunksize=chunksize,
            target_col=target_col,
            prog=prog,
            label=label,
            live=live,
        )
        return df, dbg

    dbg["mode"] = "combined_stratified_sample"
    if live is not None:
        live.update("disk_sample", f"{label} combined stratified sample n_rows={n_rows:,}", log=True)
    df = _load_stratified_sample_from_single_file(
        cp,
        n_total=n_rows,
        strategy=strategy,
        target_dist=target_dist,
        seed=seed,
        target_col=target_col,
        chunksize=chunksize,
        prog=prog,
        label=label,
        live=live,
    )
    return df, dbg


def _maybe_load_train_test_from_disk(
    df_train: pd.DataFrame,
    df_test: Optional[pd.DataFrame],
    cfg: Phase10Config,
    live: Optional[_LiveStatus] = None,
) -> tuple[pd.DataFrame, Optional[pd.DataFrame], dict]:
    dbg: dict = {"disk_used": False}

    if not cfg.prefer_disk_inputs:
        return df_train, df_test, dbg

    resolved = _resolve_paths_from_phase8_meta(cfg)

    medium_train_path = (
        _path_if_exists(resolved.get("phase8_medium_train_path"))
        or _path_if_exists(cfg.phase8_medium_train_path)
    )
    medium_test_path = (
        _path_if_exists(resolved.get("phase8_medium_test_path"))
        or _path_if_exists(cfg.phase8_medium_test_path)
    )

    if cfg.prefer_phase8_medium_inputs and medium_train_path is not None:
        try:
            if live is not None:
                live.update("disk_load_medium", f"Phase8 medium full load: {medium_train_path.name}", log=True)

            df_train2, df_test2, dbg_medium = _load_phase8_medium_direct(
                train_path=medium_train_path,
                test_path=medium_test_path,
                cfg=cfg,
                live=live,
            )

            if len(df_train2) > 0:
                if cfg.disk_shuffle_after_load:
                    rs = int(np.random.default_rng(cfg.seed).integers(0, 2**31 - 1))
                    df_train2 = df_train2.sample(frac=1.0, random_state=rs).reset_index(drop=True)
                if df_test2 is not None and len(df_test2) > 0:
                    rs = int(np.random.default_rng(cfg.seed + 1).integers(0, 2**31 - 1))
                    df_test2 = df_test2.sample(frac=1.0, random_state=rs).reset_index(drop=True)

                df_train = df_train2
                if df_test2 is not None and len(df_test2) > 0:
                    df_test = df_test2

                dbg["disk_used"] = True
                dbg["disk_source"] = "phase8_medium"
                dbg["train"] = dbg_medium
                if df_test2 is not None and len(df_test2) > 0:
                    dbg["test"] = {
                        "mode": "phase8_medium_full",
                        "test_path": str(medium_test_path) if medium_test_path is not None else None,
                    }
                elif cfg.do_holdout_eval:
                    dbg["test_load_empty"] = True

                if live is not None:
                    live.update(
                        "disk_load_medium_done",
                        f"train_rows={len(df_train):,} test_rows={0 if df_test is None else len(df_test):,}",
                        log=True,
                    )
                return df_train, df_test, dbg

            dbg["medium_reason"] = "phase8 medium train load returned empty"
            if live is not None:
                live.warn("phase8 medium train load returned empty; fallback to regular disk paths")

        except Exception as e:
            dbg["medium_load_failed"] = repr(e)
            if live is not None:
                live.warn(f"phase8 medium load failed; fallback to regular disk paths | {e!r}")

    train_attack_path = _path_if_exists(resolved.get("train_attack_path")) or _path_if_exists(cfg.train_attack_path)
    train_benign_path = _path_if_exists(resolved.get("train_benign_path")) or _path_if_exists(cfg.train_benign_path)
    test_attack_path = _path_if_exists(resolved.get("test_attack_path")) or _path_if_exists(cfg.test_attack_path)
    test_benign_path = _path_if_exists(resolved.get("test_benign_path")) or _path_if_exists(cfg.test_benign_path)

    train_combined_path = _path_if_exists(resolved.get("train_combined_path"))
    test_combined_path = _path_if_exists(resolved.get("test_combined_path"))

    disk_test_target_dist = cfg.disk_test_target_dist
    if resolved.get("disk_test_target_dist") and isinstance(resolved["disk_test_target_dist"], dict):
        disk_test_target_dist = resolved["disk_test_target_dist"]

    try:
        if live is not None:
            live.update("disk_load_train", f"prefer_disk train_rows={cfg.disk_train_rows:,}", log=True)

        df_train2, dbg_train = _load_disk_auto(
            train_or_test="train",
            attack_path=train_attack_path,
            benign_path=train_benign_path,
            combined_path=train_combined_path,
            n_rows=int(cfg.disk_train_rows),
            strategy=str(cfg.disk_train_strategy),
            target_dist=None,
            seed=int(cfg.seed),
            target_col=cfg.target_col,
            chunksize=int(cfg.disk_chunksize),
            cfg=cfg,
            live=live,
        )

        if len(df_train2) > 0:
            if cfg.disk_shuffle_after_load:
                rs = int(np.random.default_rng(cfg.seed).integers(0, 2**31 - 1))
                df_train2 = df_train2.sample(frac=1.0, random_state=rs).reset_index(drop=True)
            df_train = df_train2
            dbg["disk_used"] = True
            dbg["disk_source"] = "regular_phase8_exports"
            dbg["train"] = dbg_train
            if live is not None:
                live.update("disk_load_train_done", f"rows={len(df_train):,}", log=True)
        else:
            dbg["disk_used"] = False
            dbg["disk_reason"] = "train disk load returned empty"
            if live is not None:
                live.warn("train disk load returned empty; fallback to RAM sample")
            return df_train, df_test, dbg

    except Exception as e:
        dbg["disk_used"] = False
        dbg["disk_reason"] = f"train disk load failed: {e!r}"
        if live is not None:
            live.warn(f"train disk load failed; fallback to RAM | {e!r}")
        return df_train, df_test, dbg

    if cfg.do_holdout_eval:
        try:
            if live is not None:
                live.update("disk_load_test", f"prefer_disk test_rows={cfg.disk_test_rows:,}", log=True)

            df_test2, dbg_test = _load_disk_auto(
                train_or_test="test",
                attack_path=test_attack_path,
                benign_path=test_benign_path,
                combined_path=test_combined_path,
                n_rows=int(cfg.disk_test_rows),
                strategy=str(cfg.disk_test_strategy),
                target_dist=disk_test_target_dist if str(cfg.disk_test_strategy).lower().strip() == "proportional" else None,
                seed=int(cfg.seed) + 1,
                target_col=cfg.target_col,
                chunksize=int(cfg.disk_chunksize),
                cfg=cfg,
                live=live,
            )
            if len(df_test2) > 0:
                if cfg.disk_shuffle_after_load:
                    rs = int(np.random.default_rng(cfg.seed + 1).integers(0, 2**31 - 1))
                    df_test2 = df_test2.sample(frac=1.0, random_state=rs).reset_index(drop=True)
                df_test = df_test2
                dbg["test"] = dbg_test
                if live is not None:
                    live.update("disk_load_test_done", f"rows={len(df_test):,}", log=True)
            else:
                dbg["test_load_empty"] = True
                if live is not None:
                    live.warn("test disk load returned empty; holdout may be skipped")

        except Exception as e:
            dbg["test_load_failed"] = repr(e)
            if live is not None:
                live.warn(f"test disk load failed | {e!r}")

    return df_train, df_test, dbg


# =============================================================================
# MAIN
# =============================================================================
def phase10_train_and_evaluate(
    df_train: pd.DataFrame,
    feature_sets: dict,
    cfg: Phase10Config,
    df_test: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    phase10_t0 = time.perf_counter()
    _ensure_dir(cfg.out_dir)
    _ensure_dir(_checkpoint_root(cfg))

    run_log_path = Path(cfg.out_dir) / "run_log_phase_10.txt"
    live = _LiveStatus(
        enabled=bool(cfg.progress_enabled),
        every_s=max(2.0, float(cfg.progress_every_seconds)),
        stall_s=600.0,
    )
    live.start(run_log_path)
    live.update("start", f"log={run_log_path.name}", log=True)

    try:
        live._clear_line()
        _print_phase10_start_banner(cfg=cfg, phase10_t0=phase10_t0)

        live.update(
            "disk_load_begin",
            f"prefer_disk={cfg.prefer_disk_inputs} train_rows={cfg.disk_train_rows:,} test_rows={cfg.disk_test_rows:,}",
            log=True,
        )
        t_disk0 = time.perf_counter()
        df_train, df_test, disk_dbg = _maybe_load_train_test_from_disk(df_train, df_test, cfg, live=live)
        t_disk = time.perf_counter() - t_disk0

        live.update("prepare_train_Xy", f"rows={len(df_train):,}", log=True)
        X_train_numeric, y_train = _prepare_numeric_Xy(df_train, cfg)

        do_holdout = bool(cfg.do_holdout_eval and df_test is not None)
        X_test_numeric = None
        y_test = None

        if do_holdout:
            live.update("prepare_test_Xy", f"rows={len(df_test):,}", log=True)
            X_test_all, y_test = _prepare_numeric_Xy(df_test, cfg)
            live.update("align_test_to_train", f"train_cols={len(X_train_numeric.columns)}", log=True)
            X_test_numeric = _align_test_to_train(X_test_all, X_train_numeric.columns.tolist())

            if len(y_test.value_counts()) < 2:
                do_holdout = False
                X_test_numeric = None
                y_test = None
                live.warn("holdout test became single-class; holdout disabled")

        min_class = int(pd.Series(y_train).value_counts().min())
        n_splits = min(int(cfg.default_n_splits), min_class)
        if n_splits < 2:
            raise RuntimeError(f"Not enough samples per class for CV. min_class={min_class}")

        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=cfg.seed)
        base_models = _build_models(cfg)

        pca_cfg = feature_sets.get("PCA", {})
        n_comp = cfg.pca_default_n_components
        if isinstance(pca_cfg, dict) and "n_components" in pca_cfg:
            try:
                n_comp = int(pca_cfg["n_components"])
            except Exception:
                n_comp = cfg.pca_default_n_components
        n_comp = max(2, min(n_comp, X_train_numeric.shape[1]))

        live._clear_line()
        summary_info = _print_phase10_input_summary(
            phase10_t0=phase10_t0,
            cfg=cfg,
            disk_dbg=disk_dbg,
            df_train=df_train,
            y_train=y_train,
            df_test=df_test,
            y_test=y_test,
            do_holdout=do_holdout,
            n_splits=n_splits,
        )
        train_vc = summary_info["train_vc"]
        train_ab = summary_info["train_ab"]
        test_ab = summary_info["test_ab"]

        methods = ["MI", "RFE", "PCA"]
        model_order = _default_model_order()
        knn_methods = _normalize_knn_methods(cfg.knn_methods)

        # Preload completed rows from checkpoints
        results_map: dict[str, dict] = {}
        for method in methods:
            for model_name in model_order:
                row = _job_completed_row(cfg, method, model_name) if cfg.resume_enabled else None
                if isinstance(row, dict) and row:
                    results_map[_job_key(method, model_name)] = row

        if results_map and cfg.write_artifacts:
            _save_partial_results(results_map, cfg, methods, model_order)

        live.update(
            "cv_start",
            f"methods={len(methods)} folds={n_splits}",
            log=True,
            fs_method="pending",
            model_name="pending",
            fold_text=f"0/{n_splits}",
        )

        for method in methods:
            if method not in feature_sets:
                live.warn(f"feature_sets missing '{method}', skipped")
                continue

            if method in ("MI", "RFE"):
                feats = feature_sets.get(method, [])
                if not isinstance(feats, list) or len(feats) == 0:
                    live.warn(f"method '{method}' has empty feature list, skipped")
                    continue
                feats = [f for f in feats if f in X_train_numeric.columns]
                if len(feats) == 0:
                    live.warn(f"method '{method}' features not found in train numeric columns, skipped")
                    continue

                X_method_train = X_train_numeric[feats].copy()
                X_method_test = None
                if do_holdout and X_test_numeric is not None:
                    X_method_test = X_test_numeric[feats].copy()
            else:
                X_method_train = X_train_numeric.copy()
                X_method_test = X_test_numeric.copy() if (do_holdout and X_test_numeric is not None) else None

            live.update(
                "method_prepare",
                f"{method} train_feats={X_method_train.shape[1]}{' pca_n_comp='+str(n_comp) if method=='PCA' else ''}",
                log=True,
                fs_method=method,
                model_name="pending",
                fold_text=f"0/{n_splits}",
            )

            for model_name in model_order:
                if model_name not in base_models:
                    continue

                if model_name == "KNN" and method.upper() not in knn_methods:
                    live.info(
                        f"skip {method}/KNN (cfg.knn_methods={cfg.knn_methods})",
                        fs_method=method,
                        model_name=model_name,
                        fold_text=f"0/{n_splits}",
                    )
                    continue

                job_key = _job_key(method, model_name)
                if cfg.resume_enabled and job_key in results_map:
                    live.info(
                        f"resume skip completed {method}/{model_name}",
                        fs_method=method,
                        model_name=model_name,
                        fold_text=f"{n_splits}/{n_splits}",
                    )
                    continue

                if model_name == "KNN":
                    X_method_train_use = _knn_to_numpy_X(X_method_train, cfg.knn_force_float32)
                    y_train_use = np.asarray(y_train, dtype=np.int64)
                    X_method_test_use = (
                        _knn_to_numpy_X(X_method_test, cfg.knn_force_float32)
                        if (do_holdout and X_method_test is not None)
                        else None
                    )
                else:
                    X_method_train_use = X_method_train
                    y_train_use = y_train
                    X_method_test_use = X_method_test

                state = _load_job_state(cfg, method, model_name) if cfg.resume_enabled else {}
                fold_metrics_cached = state.get("fold_metrics", {}) if isinstance(state.get("fold_metrics"), dict) else {}
                holdout_cached = state.get("holdout_metrics") if isinstance(state.get("holdout_metrics"), dict) else None

                live.update(
                    "model_start",
                    f"{method}/{model_name}",
                    log=True,
                    fs_method=method,
                    model_name=model_name,
                    fold_text=f"0/{n_splits}",
                )

                state_base = {
                    "method": method,
                    "model_name": model_name,
                    "status": "running",
                    "updated_at": datetime.now().isoformat(),
                    "fold_metrics": fold_metrics_cached,
                    "holdout_metrics": holdout_cached,
                }
                if cfg.resume_enabled:
                    _save_job_state(cfg, method, model_name, state_base)

                accs, precs, recs, f1s, aucs = [], [], [], [], []

                fold_idx = 1
                for tr_idx, te_idx in cv.split(X_method_train_use, y_train_use):
                    cached_fold = fold_metrics_cached.get(str(fold_idx)) if cfg.resume_enabled else None
                    if isinstance(cached_fold, dict):
                        m = cached_fold
                        live.info(
                            f"resume use cached {method}/{model_name}/fold={fold_idx}/{n_splits}",
                            fs_method=method,
                            model_name=model_name,
                            fold_text=f"{fold_idx}/{n_splits}",
                        )
                    else:
                        label = f"{method}/{model_name}/fold={fold_idx}/{n_splits}"
                        live.update(
                            "fold_begin",
                            label,
                            log=True,
                            fs_method=method,
                            model_name=model_name,
                            fold_text=f"{fold_idx}/{n_splits}",
                        )

                        if model_name == "KNN":
                            X_tr = X_method_train_use[tr_idx]
                            X_te = X_method_train_use[te_idx]
                            y_tr = y_train_use[tr_idx]
                            y_te = y_train_use[te_idx]
                        else:
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
                            live=live,
                            label=label,
                            knn_force_float32=cfg.knn_force_float32,
                            knn_predict_batch_size=cfg.knn_predict_batch_size,
                        )
                        live.update(
                            "fold_done",
                            f"{label} | acc={m['accuracy']:.4f} f1={m['f1_attack']:.4f} auc={m['auc']:.4f}",
                            log=True,
                            fs_method=method,
                            model_name=model_name,
                            fold_text=f"{fold_idx}/{n_splits}",
                        )

                        if cfg.checkpoint_each_fold:
                            fold_metrics_cached[str(fold_idx)] = m
                            state_fold = {
                                "method": method,
                                "model_name": model_name,
                                "status": "running",
                                "updated_at": datetime.now().isoformat(),
                                "fold_metrics": fold_metrics_cached,
                                "holdout_metrics": holdout_cached,
                            }
                            _save_job_state(cfg, method, model_name, state_fold)

                        if cfg.gc_each_fold:
                            del est, X_tr, X_te, y_tr, y_te
                            gc.collect()

                        if cfg.cooldown_seconds and cfg.cooldown_seconds > 0:
                            _cooldown_sleep(cfg.cooldown_seconds)

                    accs.append(float(m["accuracy"]))
                    precs.append(float(m["precision_attack"]))
                    recs.append(float(m["recall_attack"]))
                    f1s.append(float(m["f1_attack"]))
                    aucs.append(float(m["auc"]))
                    fold_idx += 1

                row = {
                    "Method": method,
                    "Model": model_name,
                    "accuracy": float(np.mean(accs)),
                    "accuracy_std": float(np.std(accs)),
                    "precision_attack": float(np.mean(precs)),
                    "recall_attack": float(np.mean(recs)),
                    "f1_attack": float(np.mean(f1s)),
                    "auc": float(np.mean(aucs)),
                }

                est_final = None
                if do_holdout and X_method_test_use is not None and y_test is not None:
                    if isinstance(holdout_cached, dict):
                        hold = holdout_cached
                        live.info(
                            f"resume use cached holdout {method}/{model_name}",
                            fs_method=method,
                            model_name=model_name,
                            fold_text="holdout",
                        )
                    else:
                        live.update(
                            "holdout_fit",
                            f"{method}/{model_name}",
                            log=True,
                            fs_method=method,
                            model_name=model_name,
                            fold_text="holdout",
                        )

                        est_final = _make_estimator(method, model_name, base_models, n_comp, cfg)
                        hold = _eval_once(
                            est_final,
                            X_method_train_use,
                            y_train_use,
                            X_method_test_use,
                            y_test,
                            thread_limit=cfg.blas_thread_limit,
                            live=live,
                            label=f"{method}/{model_name}/holdout",
                            knn_force_float32=cfg.knn_force_float32,
                            knn_predict_batch_size=cfg.knn_predict_batch_size,
                        )
                        live.update(
                            "holdout_done",
                            f"{method}/{model_name} | holdout_f1={hold['f1_attack']:.4f} holdout_auc={hold['auc']:.4f}",
                            log=True,
                            fs_method=method,
                            model_name=model_name,
                            fold_text="holdout",
                        )
                        holdout_cached = hold
                        state_hold = {
                            "method": method,
                            "model_name": model_name,
                            "status": "running",
                            "updated_at": datetime.now().isoformat(),
                            "fold_metrics": fold_metrics_cached,
                            "holdout_metrics": holdout_cached,
                        }
                        _save_job_state(cfg, method, model_name, state_hold)

                    row.update({
                        "holdout_accuracy": float(hold["accuracy"]),
                        "holdout_precision_attack": float(hold["precision_attack"]),
                        "holdout_recall_attack": float(hold["recall_attack"]),
                        "holdout_f1_attack": float(hold["f1_attack"]),
                        "holdout_auc": float(hold["auc"]),
                    })

                model_ckpt_path = _save_estimator_checkpoint(cfg, method, model_name, est_final)
                if model_ckpt_path is not None:
                    row["model_checkpoint"] = str(model_ckpt_path)

                results_map[job_key] = row
                _save_job_row(cfg, method, model_name, row)
                _save_job_state(
                    cfg,
                    method,
                    model_name,
                    {
                        "method": method,
                        "model_name": model_name,
                        "status": "completed",
                        "updated_at": datetime.now().isoformat(),
                        "fold_metrics": fold_metrics_cached,
                        "holdout_metrics": holdout_cached,
                        "result_row": row,
                    },
                )
                _save_partial_results(results_map, cfg, methods, model_order)

                live.update(
                    "model_done",
                    f"{method}/{model_name} | cv_f1={row['f1_attack']:.4f} cv_auc={row['auc']:.4f}",
                    log=True,
                    fs_method=method,
                    model_name=model_name,
                    fold_text=f"{n_splits}/{n_splits}",
                )

                if cfg.gc_each_fold and est_final is not None:
                    del est_final
                    gc.collect()

        results_df = _ordered_results_df(results_map, methods, model_order)

        results_csv_path = None
        summary_path = None
        model_summary_paths: dict[str, str] = {}
        partial_results_ckpt = _partial_results_path(cfg)

        if cfg.write_artifacts:
            live.update("save_artifacts", "writing CSV + summary JSON", log=True)

            results_csv_path = Path(cfg.out_dir) / f"results_comparison_{cfg.filename_tag}.csv"
            results_df.to_csv(results_csv_path, index=False)

            best_row = None
            if not results_df.empty and "f1_attack" in results_df.columns:
                best_idx = results_df["f1_attack"].astype(float).idxmax()
                best_row = results_df.loc[best_idx].to_dict()

            summary = {
                "phase": 10,
                "generated_at": datetime.now().isoformat(),
                "input_mode": "disk" if disk_dbg.get("disk_used") else "ram",
                "disk_debug": disk_dbg,
                "train_rows": int(len(df_train)),
                "train_target_dist": train_vc,
                "train_attack_rows": int(train_ab["attack"]),
                "train_benign_rows": int(train_ab["benign"]),
                "do_holdout_eval": bool(do_holdout),
                "test_attack_rows": int(test_ab["attack"]) if do_holdout else 0,
                "test_benign_rows": int(test_ab["benign"]) if do_holdout else 0,
                "cv_folds": int(n_splits),
                "logical_cpu": int(_LOGICAL_CPU),
                "worker_threads": int(_WORKER_THREADS),
                "inner_math_threads": int(_INNER_MATH_THREADS),
                "rfc_n_jobs": int(cfg.rfc_n_jobs),
                "lsvc_c": float(cfg.lsvc_c),
                "lsvc_max_iter": int(cfg.lsvc_max_iter),
                "xgb_n_estimators": int(cfg.xgb_n_estimators),
                "xgb_max_depth": int(cfg.xgb_max_depth),
                "xgb_learning_rate": float(cfg.xgb_learning_rate),
                "xgb_subsample": float(cfg.xgb_subsample),
                "xgb_colsample_bytree": float(cfg.xgb_colsample_bytree),
                "xgb_reg_lambda": float(cfg.xgb_reg_lambda),
                "xgb_n_jobs": int(cfg.xgb_n_jobs),
                "xgb_tree_method": str(cfg.xgb_tree_method),
                "xgb_device": str(cfg.xgb_device),
                "xgb_eval_metric": str(cfg.xgb_eval_metric),
                "knn_n_jobs": int(cfg.knn_n_jobs),
                "knn_algorithm": str(cfg.knn_algorithm),
                "knn_methods": list(cfg.knn_methods),
                "prefer_phase8_medium_inputs": bool(cfg.prefer_phase8_medium_inputs),
                "knn_predict_batch_size": int(cfg.knn_predict_batch_size),
                "blas_thread_limit": int(cfg.blas_thread_limit),
                "resume_enabled": bool(cfg.resume_enabled),
                "checkpoint_each_fold": bool(cfg.checkpoint_each_fold),
                "save_fitted_models": bool(cfg.save_fitted_models),
                "methods_seen": sorted(list(set(results_df["Method"].tolist()))) if not results_df.empty else [],
                "best_by_cv_f1_attack": best_row,
                "elapsed_seconds": float(time.perf_counter() - phase10_t0),
                "paths": {
                    "results_csv": str(results_csv_path) if results_csv_path else None,
                    "partial_results_csv": str(partial_results_ckpt),
                    "run_log": str(run_log_path),
                    "checkpoint_root": str(_checkpoint_root(cfg)),
                },
            }
            summary_path = Path(cfg.out_dir) / f"phase10_summary_{cfg.filename_tag}.json"
            summary_path.write_text(json.dumps(_json_safe(summary), indent=2), encoding="utf-8")

            model_summary_common = {
                "input_mode": summary["input_mode"],
                "disk_debug": summary["disk_debug"],
                "train_rows": summary["train_rows"],
                "train_target_dist": summary["train_target_dist"],
                "train_attack_rows": summary["train_attack_rows"],
                "train_benign_rows": summary["train_benign_rows"],
                "do_holdout_eval": summary["do_holdout_eval"],
                "test_attack_rows": summary["test_attack_rows"],
                "test_benign_rows": summary["test_benign_rows"],
                "cv_folds": summary["cv_folds"],
                "logical_cpu": summary["logical_cpu"],
                "worker_threads": summary["worker_threads"],
                "inner_math_threads": summary["inner_math_threads"],
                "rfc_n_jobs": summary["rfc_n_jobs"],
                "lsvc_c": summary["lsvc_c"],
                "lsvc_max_iter": summary["lsvc_max_iter"],
                "xgb_n_estimators": summary["xgb_n_estimators"],
                "xgb_max_depth": summary["xgb_max_depth"],
                "xgb_learning_rate": summary["xgb_learning_rate"],
                "xgb_subsample": summary["xgb_subsample"],
                "xgb_colsample_bytree": summary["xgb_colsample_bytree"],
                "xgb_reg_lambda": summary["xgb_reg_lambda"],
                "xgb_n_jobs": summary["xgb_n_jobs"],
                "xgb_tree_method": summary["xgb_tree_method"],
                "xgb_device": summary["xgb_device"],
                "xgb_eval_metric": summary["xgb_eval_metric"],
                "knn_n_jobs": summary["knn_n_jobs"],
                "knn_algorithm": summary["knn_algorithm"],
                "knn_methods": summary["knn_methods"],
                "prefer_phase8_medium_inputs": summary["prefer_phase8_medium_inputs"],
                "knn_predict_batch_size": summary["knn_predict_batch_size"],
                "blas_thread_limit": summary["blas_thread_limit"],
                "resume_enabled": summary["resume_enabled"],
                "checkpoint_each_fold": summary["checkpoint_each_fold"],
                "save_fitted_models": summary["save_fitted_models"],
                "elapsed_seconds_total_phase10": summary["elapsed_seconds"],
                "paths": summary["paths"],
            }
            model_summary_paths = _save_model_summaries(
                results_df,
                cfg,
                generated_at=summary["generated_at"],
                common_info=model_summary_common,
            )
            summary["paths"]["model_summaries"] = model_summary_paths
            summary_path.write_text(json.dumps(_json_safe(summary), indent=2), encoding="utf-8")

        elapsed = time.perf_counter() - phase10_t0
        live.update("done", f"elapsed={_fmt_elapsed(elapsed)} rows={len(results_df):,}", log=True)
        live.stop()

        print("\n" + "=" * 80)
        print(f"✅ PHASE 10 DONE | total_elapsed={_fmt_elapsed(elapsed)}")
        print(f"📌 input_mode     : {'disk' if disk_dbg.get('disk_used') else 'ram'}")
        print(f"📌 disk_load_time : {_fmt_elapsed(t_disk)}")
        print(f"📌 checkpoints    : {_checkpoint_root(cfg)}")
        print(f"📌 partial CSV    : {partial_results_ckpt}")
        if results_csv_path:
            print(f"💾 Results CSV : {results_csv_path}")
        if summary_path:
            print(f"💾 Summary JSON: {summary_path}")
        print(f"📌 Model summaries: {Path(cfg.out_dir)} / phase10_<idx><MODEL>_summary_{cfg.filename_tag}.json")
        print("=" * 80)

        return {
            "results_df": results_df,
            "summary": {
                "elapsed_seconds": float(elapsed),
                "elapsed_human": _fmt_elapsed(elapsed),
                "results_rows": int(len(results_df)),
                "input_mode": "disk" if disk_dbg.get("disk_used") else "ram",
                "disk_debug": disk_dbg,
                "paths": {
                    "results_csv": str(results_csv_path) if results_csv_path else None,
                    "summary_json": str(summary_path) if summary_path else None,
                    "partial_results_csv": str(partial_results_ckpt),
                    "run_log": str(run_log_path),
                    "checkpoint_root": str(_checkpoint_root(cfg)),
                },
            },
            "paths": {
                "results_csv": results_csv_path,
                "summary_json": summary_path,
                "partial_results_csv": partial_results_ckpt,
                "run_log": run_log_path,
                "checkpoint_root": _checkpoint_root(cfg),
            },
        }

    except Exception as e:
        live.update("error", repr(e), level="ERROR", log=True)
        live.stop()
        raise

    finally:
        if not live._stopped:
            live.stop()
