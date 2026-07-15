"""
Adapter: cbr EVE/Suricata pipeline  ->  platform BasePipeline contract.

This module wraps the *vendored, unmodified* cbr core (pipelines/eve_cbr/cbr/)
behind the platform's BasePipeline interface. The cbr core logic is NOT changed;
we only:
  - build a RunConfig with Docker-safe resource caps + Fix 1 (row-level
    conversion cap) + a single requested algorithm,
  - run the per-app TLS split (pre-pipeline step cbr expects),
  - call cbr.run_pipeline(cfg) in a per-run temp directory,
  - read cbr's on-disk Phase 13/14 artifacts and map the *natural-holdout*
    metrics, confusion matrix, and feature importance into a PipelineResult.

Honesty policy: natural-holdout (original class distribution) is reported as the
PRIMARY metric. Balanced-holdout is surfaced in extra_info only as a secondary
class-separability comparison.

One pipeline_id == one algorithm (DT/RFC/LSVC/XGB). Each subclass sets cbr
modeling.models = [its algorithm] so Phase 13 trains only that model
(× MI/RFE/PCA feature methods), keeping cost bounded.
"""
from __future__ import annotations

import csv
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from contracts.pipeline_contracts import PipelineInput, PipelineResult
from pipelines.base import BasePipeline, ProgressCallback
from config.research_attribution import research_paper_credit

logger = logging.getLogger(__name__)

_APP = "tls"
_TARGET_COLUMN = "Target_refined"
_LABEL_MAPPING = {0: "Benign", 1: "Attack"}

# Vendored split script + ports file.
_SPLIT_DIR = Path(__file__).resolve().parent / "split"
_PORTS_FILE = _SPLIT_DIR / "ports.txt"

# Docker-safe resource caps (validated empirically, RAM cap ~3.53 GB).
# Default cbr config uses 10M rows -> OOM. These mirror src/_validation/run_validation.py.
_RES = dict(
    fs_sample_rows=50_000,
    fs_per_class_rows=25_000,
    mi_max_rows=20_000,
    rfe_max_rows=30_000,
    pca_max_rows=40_000,
    modeling_train_rows=150_000,
    modeling_train_per_class_rows=75_000,
    modeling_natural_test_min_rows=1_000,
    modeling_natural_test_max_rows=1_000_000,
    modeling_balanced_test_rows=40_000,
    modeling_balanced_test_per_class_rows=20_000,
    n_jobs=2,
    cv_folds=2,
    # Phase 8 reservoir caps (viz_sampler/corr_sampler in phase8_export_dataset.py
    # each hold a full dict-copy per sampled row). cbr core defaults are
    # 300_000/1_000_000, which on production-scale apps (>=1.3M rows) fill
    # completely and measured ~2.7-3.7 GB peak RSS -- over the worker's 3.5 GB
    # cap. These caps mirror the modeling caps above to keep Phase 8 bounded.
    visualization_sample_rows=50_000,
    corr_leak_sample_rows=100_000,
)

# Feature methods preferred for the reported result. MI/RFE map importances to
# real feature names; PCA mixes features, so it is only a last resort.
_METHOD_PREFERENCE = ("MI", "RFE", "PCA")
_METRIC_BASES = ("accuracy", "precision_attack", "recall_attack", "f1_attack", "auc")

# ── Progress stages (Jenkins-style) ───────────────────────────────────────
# The 14 internal cbr phases grouped into 7 conceptual stages, bracketed by the
# adapter's own pre-split and metric-collection steps. This is the SINGLE SOURCE
# OF TRUTH for the eve_cbr stage list; config/pipeline_registry.py imports
# EVE_CBR_STAGES so the worker can resolve stage_index/stage_total. Progress is
# pure observation — these strings never affect computation.
_STAGE_SPLIT = "Splitting TLS from EVE dataset"
_STAGE_COLLECT = "Collecting natural-holdout metrics"
_STAGE_P12 = "Ingestion & validation (fase 1–2)"
_STAGE_P34 = "Probing & label refinement (fase 3–4)"
_STAGE_P56 = "Feature engineering (fase 5–6)"
_STAGE_P7 = "Cleaning policy (fase 7)"
_STAGE_P8 = "Export & train/test split (fase 8)"
_STAGE_P910 = "Visualization & leakage analysis (fase 9–10)"
_STAGE_P1114 = "Modeling & evaluation (fase 11–14)"

EVE_CBR_STAGES = [
    _STAGE_SPLIT,
    _STAGE_P12, _STAGE_P34, _STAGE_P56, _STAGE_P7, _STAGE_P8, _STAGE_P910, _STAGE_P1114,
    _STAGE_COLLECT,
]

# cbr phase number (1..14) -> conceptual stage label.
_PHASE_STAGE = {
    1: _STAGE_P12, 2: _STAGE_P12,
    3: _STAGE_P34, 4: _STAGE_P34,
    5: _STAGE_P56, 6: _STAGE_P56,
    7: _STAGE_P7,
    8: _STAGE_P8,
    9: _STAGE_P910, 10: _STAGE_P910,
    11: _STAGE_P1114, 12: _STAGE_P1114, 13: _STAGE_P1114, 14: _STAGE_P1114,
}


def phase_to_stage(phase: int) -> str:
    """Map a cbr phase number to its conceptual progress stage label."""
    return _PHASE_STAGE.get(int(phase), _STAGE_P1114)


# ============================================================
# Config building
# ============================================================

def build_run_config(*, algo: str, split_dir: Path, work_dir: Path, archive_dir: Path,
                     summary_path: Path, random_state: int):
    """Build a cbr RunConfig for a single algorithm on TLS with Docker-safe caps.

    cbr core is untouched; we only set resource params + Fix 1 + models=[algo]
    + save_fitted_models=True (so the adapter can read importances back).
    """
    from pipelines.eve_cbr.cbr.config import (
        RunConfig, PhaseToggles, StorageConfig, SplitConfig, ExportConfig,
        ProbingConfig, ModelingConfig,
    )

    storage = StorageConfig(
        project_root=Path(work_dir),
        external_archive_root=Path(work_dir),
        split_app_dir=Path(split_dir),
        archive_output_dir=Path(archive_dir),
        internal_work_root=Path(work_dir) / "work",
        app_file_template="eve_{app}.jsonl",
        cleanup_internal_after_app=False,
        archive_app_outputs_after_app=False,
    )

    modeling = ModelingConfig(
        methods=["MI", "RFE", "PCA"],
        models=[algo],                              # <-- one algorithm only
        fs_sample_rows=_RES["fs_sample_rows"],
        fs_sampling_strategy="balanced",
        fs_per_class_rows=_RES["fs_per_class_rows"],
        fs_top_k=30,
        mi_max_rows=_RES["mi_max_rows"],
        rfe_max_rows=_RES["rfe_max_rows"],
        pca_max_rows=_RES["pca_max_rows"],
        read_chunksize=100_000,
        seed=random_state,
        allow_modeling_subset=True,
        modeling_train_rows=_RES["modeling_train_rows"],
        modeling_train_sampling_strategy="balanced",
        modeling_train_per_class_rows=_RES["modeling_train_per_class_rows"],
        modeling_test_rows=_RES["modeling_balanced_test_rows"],
        modeling_sampling_strategy="balanced",
        modeling_natural_test_min_rows=_RES["modeling_natural_test_min_rows"],
        modeling_natural_test_max_rows=_RES["modeling_natural_test_max_rows"],
        modeling_balanced_test_rows=_RES["modeling_balanced_test_rows"],
        modeling_balanced_test_per_class_rows=_RES["modeling_balanced_test_per_class_rows"],
        create_temporary_training_cache=False,
        cleanup_training_cache_after_run=True,
        evaluation_chunk_rows=250_000,
        cv_folds=_RES["cv_folds"],
        blas_thread_limit=1,
        save_fitted_models=True,                    # <-- needed for feature importance
        pca_default_n_components=10,
        rfc_estimators=100,
        rfc_n_jobs=_RES["n_jobs"],
        rfc_max_depth=16,
        rfc_min_samples_leaf=2,
        lsvc_c=1.0,
        lsvc_max_iter=5_000,
        xgb_n_estimators=150,
        xgb_max_depth=6,
        xgb_learning_rate=0.1,
        xgb_subsample=0.8,
        xgb_colsample_bytree=0.8,
        xgb_reg_lambda=1.0,
        xgb_n_jobs=_RES["n_jobs"],
        xgb_tree_method="hist",
        xgb_device="cpu",
        xgb_eval_metric="logloss",
    )

    return RunConfig(
        run_mode="large_disk_supervised",
        selected_apps=[_APP],
        phases=PhaseToggles(),  # all phases on
        storage=storage,
        split=SplitConfig(
            target_column=_TARGET_COLUMN,
            strategy="group_hash",
            train_ratio=0.8,
            test_ratio=0.2,
            random_seed=random_state,
            group_key_columns=["app", "window_start", "src_ip"],
            export_train_test_in_phase8=True,
            export_full_feature_ready=False,
        ),
        export=ExportConfig(
            format="csv",
            compression=None,
            visualization_sample_rows=_RES["visualization_sample_rows"],
            corr_leak_sample_rows=_RES["corr_leak_sample_rows"],
        ),
        probing=ProbingConfig(
            window_minutes=5,
            ip_only_relabeling_enabled=False,
            max_benign_conversion_pct=5.0,
            stop_if_conversion_exceeds_limit=True,
            extreme_probe_changes_target=False,
            enforce_row_level_conversion_cap=True,   # <-- Fix 1 (mandatory)
        ),
        modeling=modeling,
        use_prepipeline_summary_for_phase1=True,
        use_prepipeline_summary_for_phase2=True,
        prepipeline_summary_path=Path(summary_path),
        copy_app_to_internal_before_run=False,
        require_app_input_exists=True,
        verbose=True,
        phase_progress_every=100_000,
        feature_preview_rows=200,
    )


# ============================================================
# Split (STAGE 3) — deterministic TLS split from full EVE JSONL
# ============================================================

def split_tls(*, dataset_path: str, out_dir: Path) -> dict:
    """Run the vendored pre-pipeline split for TLS only. Deterministic.

    Returns the cbr split app-summary dict for TLS (written_rows, label_counts...).
    """
    from pipelines.eve_cbr.split.split_eve_by_app import split_selected_apps

    out_dir.mkdir(parents=True, exist_ok=True)
    result = split_selected_apps(
        input_file=Path(dataset_path),
        output_dir=out_dir,
        app_targets=["tls"],
        ports_file=_PORTS_FILE,
        max_rows_per_app=0,         # no cap — full deterministic split
        write_malformed=False,
        progress_every=0,           # quiet
        label_mode="event_type_or_valid_alert",
    )
    return result.get("apps", {}).get("tls", {})


# ============================================================
# Result collection from cbr on-disk artifacts
# ============================================================

def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Could not read cbr artifact %s", path, exc_info=True)
    return {}


def _read_results_rows(phase13_dir: Path) -> list[dict]:
    path = phase13_dir / "results_comparison.csv"
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(dict(row))
    except Exception:
        logger.warning("Could not read %s", path, exc_info=True)
    return rows


def _fnum(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _metric(row: dict, base: str) -> tuple[Optional[float], Optional[str]]:
    """Return (value, holdout_source) preferring natural > balanced > legacy > cv."""
    for prefix, label in (("natural_holdout_", "natural"),
                          ("balanced_holdout_", "balanced"),
                          ("holdout_", "legacy"),
                          ("", "cv")):
        v = _fnum(row.get(f"{prefix}{base}"))
        if v is not None:
            return v, label
    return None, None


def _select_row(rows: list[dict], algo: str) -> Optional[dict]:
    """Pick the row for this algorithm: prefer MI/RFE (real-feature importance),
    rank by natural-holdout F1_attack (fallback balanced/legacy/cv)."""
    algo_rows = [r for r in rows if str(r.get("Model", "")).upper() == algo]
    if not algo_rows:
        return None

    def score(r: dict) -> tuple[int, float]:
        method = str(r.get("Method", "")).upper()
        method_rank = _METHOD_PREFERENCE.index(method) if method in _METHOD_PREFERENCE else 99
        f1, _ = _metric(r, "f1_attack")
        # prefer earlier method (lower rank) then higher f1
        return (-method_rank, f1 if f1 is not None else -1.0)

    return sorted(algo_rows, key=score, reverse=True)[0]


def _confusion_matrix(phase13_dir: Path, *, method: str, algo: str) -> tuple[list[list[int]], Optional[dict], str]:
    """Read confusion matrix + roc points for (method, algo) from the
    holdout_prediction_summary.json, preferring the natural holdout."""
    payload = _read_json(phase13_dir / "holdout_prediction_summary.json")
    items = payload.get("items", []) if isinstance(payload, dict) else []
    by_kind = {}
    for it in items:
        if str(it.get("Method", "")).upper() == method and str(it.get("Model", "")).upper() == algo:
            by_kind[str(it.get("holdout_kind", ""))] = it
    for kind in ("natural", "balanced"):
        it = by_kind.get(kind)
        if it and it.get("confusion_matrix"):
            cm = [[int(x) for x in row] for row in it["confusion_matrix"]]
            return cm, it.get("roc_points"), kind
    return [], None, ""


def _feature_importance(phase13_dir: Path, *, method: str, algo: str) -> tuple[list[dict], list[str], object]:
    """Load the saved fitted estimator and extract feature importance.

    Returns (importance_list, feature_names, model_object). Importance maps to
    real feature names for MI/RFE; empty for PCA (importances live in PCA space).
    """
    model_path = phase13_dir / "models" / f"{_APP}_{method}_{algo}.joblib"
    if not model_path.exists():
        return [], [], None
    try:
        import joblib
        import numpy as np
        est = joblib.load(model_path)
    except Exception:
        logger.warning("Could not load fitted model %s", model_path, exc_info=True)
        return [], [], None

    _fn = getattr(est, "feature_names_in_", None)
    names = list(_fn) if _fn is not None else []

    # Unwrap sklearn Pipeline to the final estimator for importances/coef.
    final = est
    try:
        from sklearn.pipeline import Pipeline
        if isinstance(est, Pipeline):
            if "pca" in dict(est.named_steps):   # PCA: importances not in original space
                return [], names, est
            final = est[-1]
    except Exception:
        pass

    values = None
    if hasattr(final, "feature_importances_"):
        values = final.feature_importances_
    elif hasattr(final, "coef_"):
        import numpy as np
        values = np.abs(np.asarray(final.coef_)).ravel()

    importance: list[dict] = []
    if values is not None and names and len(values) == len(names):
        importance = sorted(
            [{"feature": n, "importance": round(float(v), 6)} for n, v in zip(names, values)],
            key=lambda d: d["importance"], reverse=True,
        )
    return importance, names, est


def collect_result(*, cfg, algo: str, split_summary_tls: dict) -> PipelineResult:
    """Map cbr on-disk Phase 13/14 artifacts -> platform PipelineResult."""
    phase13_dir = Path(cfg.storage.phase_dir(_APP, "phase13"))
    phase14_dir = Path(cfg.storage.phase_dir(_APP, "phase14"))
    phase8_dir = Path(cfg.storage.phase_dir(_APP, "phase8"))

    rows = _read_results_rows(phase13_dir)
    row = _select_row(rows, algo)
    if row is None:
        raise RuntimeError(
            f"cbr produced no Phase 13 result row for algorithm {algo!r}. "
            f"Check {phase13_dir/'summary.json'} for skip_reason."
        )

    method = str(row.get("Method", "")).upper()

    acc, acc_src = _metric(row, "accuracy")
    prec, _ = _metric(row, "precision_attack")
    rec, _ = _metric(row, "recall_attack")
    f1, f1_src = _metric(row, "f1_attack")
    auc, _ = _metric(row, "auc")

    cm, roc_points, cm_kind = _confusion_matrix(phase13_dir, method=method, algo=algo)
    importance, feat_names, model = _feature_importance(phase13_dir, method=method, algo=algo)

    phase14_summary = _read_json(phase14_dir / "summary.json")
    phase8_export = _read_json(phase8_dir / "export_summary.json")

    # Final refined-Target counts after Fix 1 (Phase 8 export).
    target_counts = phase8_export.get("target_counts") or {}
    train_tc = phase8_export.get("train_target_counts") or {}
    test_tc = phase8_export.get("test_target_counts") or {}

    extra_info: dict[str, Any] = {
        "evaluation": {
            "primary": "natural_holdout",
            "primary_metric_source": f1_src,
            "reported_holdout_kind": cm_kind or f1_src,
        },
        "selected_combo": {"app": _APP, "method": method, "model": algo},
        "natural_holdout": {b: _fnum(row.get(f"natural_holdout_{b}")) for b in _METRIC_BASES},
        "balanced_holdout": {b: _fnum(row.get(f"balanced_holdout_{b}")) for b in _METRIC_BASES},
        "cv": {b: _fnum(row.get(b)) for b in _METRIC_BASES},
        "feature_importance": importance,
        "feature_importance_note": (
            "Importance maps to real features (MI/RFE)."
            if importance else
            "Feature importance unavailable (PCA feature method or model has no "
            "importances/coef)."
        ),
        "anti_leakage": {
            "group_split": "group_hash on [app, window_start, src_ip]",
            "pipeline_scaling": "StandardScaler inside CV/holdout pipeline (no test leakage)",
            "dual_holdout": "natural (primary) + balanced (secondary)",
            "fix1_row_level_conversion_cap": True,
            "forbidden_feature_guard": "alert_/label_/evidence_ prefixes + Target* blocked",
        },
        "fix1_enforce_row_level_conversion_cap": True,
        "final_target_counts_phase8": target_counts,
        "train_target_counts_phase8": train_tc,
        "test_target_counts_phase8": test_tc,
        "split_tls": {
            "written_rows": split_summary_tls.get("written_rows"),
            "initial_label_counts": split_summary_tls.get("label_counts"),
            "ports_used": split_summary_tls.get("ports_used"),
            "note": "initial split labels are pre-Phase-4; final attack count is the "
                    "Phase-8 refined Target above.",
        },
        "cbr_best_model": phase14_summary.get("best_model"),
        "cbr_natural_holdout_table": phase14_summary.get("natural_holdout_table"),
        "cbr_phase13_results_rows": len(rows),
    }
    if auc is not None:
        extra_info["roc_auc"] = auc
    if roc_points and isinstance(roc_points, dict):
        extra_info["roc_curve"] = {"fpr": roc_points.get("fpr", []), "tpr": roc_points.get("tpr", [])}

    if not cm:
        # platform expects a 2x2 list; keep shape stable if prediction summary missing.
        cm = [[0, 0], [0, 0]]

    return PipelineResult(
        accuracy=float(acc) if acc is not None else 0.0,
        precision=float(prec) if prec is not None else 0.0,
        recall=float(rec) if rec is not None else 0.0,
        f1_score=float(f1) if f1 is not None else 0.0,
        confusion_matrix=cm,
        model=model,
        feature_names=feat_names,
        label_mapping=_LABEL_MAPPING,
        extra_info=extra_info,
    )


# ============================================================
# Base pipeline
# ============================================================

class BaseCbrEvePipeline(BasePipeline):
    """Shared cbr EVE/TLS adapter. Subclasses set ALGORITHM (DT/RFC/LSVC/XGB)."""

    ALGORITHM: str = ""          # cbr internal model name
    ALGORITHM_LABEL: str = ""    # human-readable

    def run(self, pipeline_input: PipelineInput,
            progress: Optional[ProgressCallback] = None) -> PipelineResult:
        if not pipeline_input.dataset_path:
            raise ValueError(
                "EVE cbr pipelines require dataset_path in PipelineInput "
                "(path to the full EVE NDJSON/JSONL file)."
            )
        algo = self.ALGORITHM
        rs = pipeline_input.random_state

        work_root = Path(tempfile.mkdtemp(prefix=f"cbr_eve_{algo.lower()}_"))
        split_dir = work_root / "data_split"
        work_dir = work_root / "cbr_work"
        archive_dir = work_root / "cbr_outputs"
        summary_path = split_dir / "split_summary.json"

        try:
            from pipelines.eve_cbr.cbr.pipeline import run_pipeline

            self._emit_progress(progress, _STAGE_SPLIT)
            split_summary_tls = split_tls(dataset_path=pipeline_input.dataset_path, out_dir=split_dir)

            cfg = build_run_config(
                algo=algo, split_dir=split_dir, work_dir=work_dir,
                archive_dir=archive_dir, summary_path=summary_path, random_state=rs,
            )

            # Bridge cbr's per-phase hook (1..14) to the 7 conceptual stages,
            # emitting only when the stage changes so the UI advances cleanly.
            # Pure observation — no effect on the cbr run.
            _last = {"stage": None}

            def _phase_bridge(phase_no: int, _phase_name: str) -> None:
                stage = phase_to_stage(phase_no)
                if stage != _last["stage"]:
                    _last["stage"] = stage
                    self._emit_progress(progress, stage)

            run_pipeline(cfg, progress=_phase_bridge)

            self._emit_progress(progress, _STAGE_COLLECT)
            result = collect_result(cfg=cfg, algo=algo, split_summary_tls=split_summary_tls)
            return result
        finally:
            shutil.rmtree(work_root, ignore_errors=True)

    def get_info(self) -> dict:
        return {
            "paper": research_paper_credit("EVE_SURICATA"),
            "algorithm": self.ALGORITHM_LABEL,
            "app": "TLS",
            "dataset": "EVE/Suricata (eve_sample_1000000.jsonl), TLS split by port/app_proto/event_type",
            "preprocessing_steps": [
                "Pre-split: deterministic TLS extraction (app_proto -> event_type -> ports 443/8443)",
                "P1-2: ingestion + pre-split app validation",
                "P3-4: probing analysis + conservative label refinement (Target_refined)",
                "P5-7: feature engineering, computed features, cleaning policy",
                "P8: streaming train/test export with Fix 1 row-level conversion cap",
                "P9-10: visualization + correlation/leakage analysis",
                "P11-12: modeling split prep + feature selection (MI/RFE/PCA)",
                "P13: balanced-train training + dual natural/balanced holdout evaluation",
                "P14: summary-driven final evaluation (no retraining)",
            ],
            "feature_selection": "MI / RFE / PCA (reported result prefers MI/RFE)",
            "anti_leakage": [
                "group_hash split on [app, window_start, src_ip]",
                "pipeline-internal scaling (no test leakage)",
                "dual holdout: natural (primary, honest) + balanced (secondary)",
                "Fix 1: enforce_row_level_conversion_cap=True",
                "forbidden-feature leakage guard (alert_/label_/evidence_/Target*)",
            ],
            "metrics_policy": "natural-holdout attack metrics reported as PRIMARY (honest)",
            "fixed_params": {
                "models": [self.ALGORITHM],
                "fs_sample_rows": _RES["fs_sample_rows"],
                "modeling_train_rows": _RES["modeling_train_rows"],
                "visualization_sample_rows": _RES["visualization_sample_rows"],
                "corr_leak_sample_rows": _RES["corr_leak_sample_rows"],
                "n_jobs": _RES["n_jobs"],
                "cv_folds": _RES["cv_folds"],
                "enforce_row_level_conversion_cap": True,
            },
            "train_test_split": {"method": "cbr Phase 8 group_hash split", "target": _TARGET_COLUMN},
        }
