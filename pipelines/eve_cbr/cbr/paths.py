from __future__ import annotations

"""
Path helpers for the CBR / Suricata EVE large-data pipeline.

Recommended location:
    src/cbr/paths.py

Purpose:
- Keep all input/output path construction in one place.
- Avoid hardcoded paths inside main.py, pipeline.py, or individual phase files.
- Support supervised per-app workflow:
    external archive/storage  -> raw + split app JSONL + archived outputs
    internal working storage  -> current app processing only
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


# ============================================================
# Phase names
# ============================================================

PHASE_DIRS: Dict[int, str] = {
    1: "phase1",
    2: "phase2",
    3: "phase3",
    4: "phase4",
    5: "phase5",
    6: "phase6",
    7: "phase7",
    8: "phase8",
    9: "phase9",
    10: "phase10",
    11: "phase11",
    12: "phase12",
    13: "phase13",
    14: "phase14",
}

PHASE_LABELS: Dict[int, str] = {
    1: "initial_profiling",
    2: "app_validation",
    3: "probing_analysis",
    4: "label_refinement",
    5: "feature_engineering",
    6: "computed_features",
    7: "cleaning",
    8: "export_dataset",
    9: "visualization",
    10: "correlation_leakage",
    11: "modeling_split",
    12: "feature_selection",
    13: "training",
    14: "advanced_evaluation",
}


# ============================================================
# Generic helpers
# ============================================================

def _as_path(value: Any, default: Optional[Path] = None) -> Path:
    if value is None:
        if default is None:
            raise ValueError("Path value is None and no default was provided.")
        return Path(default)
    return Path(value)


def _cfg_path(cfg: Any, *names: str, default: Optional[Path] = None) -> Path:
    """
    Get the first available path-like attribute from cfg.

    This makes paths.py resilient while config.py is still evolving.
    """
    for name in names:
        if hasattr(cfg, name):
            value = getattr(cfg, name)
            if value is not None:
                return _as_path(value)
    if default is not None:
        return Path(default)
    raise AttributeError(f"Config is missing required path attribute. Tried: {names}")


def _cfg_value(cfg: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(cfg, name):
            value = getattr(cfg, name)
            if value is not None:
                return value
    return default


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def normalize_app(app: str) -> str:
    text = str(app).strip().lower()
    if not text:
        raise ValueError("app must not be empty")
    return text


# ============================================================
# Root paths
# ============================================================

def external_root(cfg: Any) -> Path:
    return _cfg_path(
        cfg,
        "external_root",
        "external_archive_root",
        "archive_root",
        default=Path("./archive"),
    )


def internal_work_root(cfg: Any) -> Path:
    return _cfg_path(
        cfg,
        "internal_work_root",
        "work_root",
        "working_root",
        default=Path("./work"),
    )


def raw_dir(cfg: Any) -> Path:
    return _cfg_path(
        cfg,
        "raw_dir",
        "raw_data_dir",
        default=external_root(cfg) / "raw",
    )


def split_app_dir(cfg: Any) -> Path:
    return _cfg_path(
        cfg,
        "split_app_dir",
        "app_split_dir",
        "split_dir",
        default=external_root(cfg) / "split_app",
    )


def prepipeline_dir(cfg: Any) -> Path:
    return _cfg_path(
        cfg,
        "prepipeline_dir",
        "pre_pipeline_dir",
        default=external_root(cfg) / "prepipeline",
    )


def archive_output_dir(cfg: Any) -> Path:
    return _cfg_path(
        cfg,
        "archive_output_dir",
        "external_output_dir",
        "output_archive_dir",
        default=external_root(cfg) / "outputs",
    )


# ============================================================
# App-level paths
# ============================================================

def app_file_name(cfg: Any, app: str) -> str:
    app = normalize_app(app)
    pattern = _cfg_value(cfg, "app_file_pattern", default="eve_{app}.jsonl")
    return str(pattern).format(app=app)


def app_external_jsonl_path(cfg: Any, app: str) -> Path:
    return split_app_dir(cfg) / app_file_name(cfg, app)


def app_work_dir(cfg: Any, app: str) -> Path:
    app = normalize_app(app)
    return internal_work_root(cfg) / "current_app" / app


def app_work_input_path(cfg: Any, app: str) -> Path:
    return app_work_dir(cfg, app) / app_file_name(cfg, app)


def app_work_output_dir(cfg: Any, app: str) -> Path:
    app = normalize_app(app)
    return app_work_dir(cfg, app) / "outputs" / app


def app_archive_output_dir(cfg: Any, app: str) -> Path:
    app = normalize_app(app)
    return archive_output_dir(cfg) / app


def app_log_dir(cfg: Any, app: str) -> Path:
    return app_work_dir(cfg, app) / "logs"


def ensure_app_dirs(cfg: Any, app: str) -> None:
    ensure_dir(app_work_dir(cfg, app))
    ensure_dir(app_work_output_dir(cfg, app))
    ensure_dir(app_log_dir(cfg, app))
    for phase_num in PHASE_DIRS:
        ensure_dir(phase_dir(cfg, app, phase_num))


# ============================================================
# Phase directory helpers
# ============================================================

def phase_dir(cfg: Any, app: str, phase: int | str) -> Path:
    app = normalize_app(app)

    if isinstance(phase, int):
        if phase not in PHASE_DIRS:
            raise ValueError(f"Unknown phase number: {phase}")
        phase_name = PHASE_DIRS[phase]
    else:
        phase_name = str(phase).strip()
        if not phase_name:
            raise ValueError("phase name must not be empty")
        if not phase_name.startswith("phase"):
            phase_name = f"phase{phase_name}"

    return app_work_output_dir(cfg, app) / phase_name


def phase_archive_dir(cfg: Any, app: str, phase: int | str) -> Path:
    app = normalize_app(app)

    if isinstance(phase, int):
        if phase not in PHASE_DIRS:
            raise ValueError(f"Unknown phase number: {phase}")
        phase_name = PHASE_DIRS[phase]
    else:
        phase_name = str(phase).strip()
        if not phase_name:
            raise ValueError("phase name must not be empty")
        if not phase_name.startswith("phase"):
            phase_name = f"phase{phase_name}"

    return app_archive_output_dir(cfg, app) / phase_name


def all_phase_dirs(cfg: Any, app: str) -> Dict[int, Path]:
    return {num: phase_dir(cfg, app, num) for num in PHASE_DIRS}


# ============================================================
# Common phase output files
# ============================================================

def phase1_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 1) / "summary.json"


def phase2_validation_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 2) / "validation_summary.json"


def phase3_probe_features_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 3) / "probe_features.jsonl"


def phase3_alert_ip_index_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 3) / "alert_ip_index.jsonl"


def phase3_suspicious_windows_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 3) / "suspicious_windows.jsonl"


def phase3_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 3) / "summary.json"


def phase4_label_policy_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 4) / "label_policy.json"


def phase4_suspicious_keys_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 4) / "suspicious_keys.jsonl"


def phase4_refined_label_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 4) / "refined_label_summary.json"


def phase4_refinement_audit_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 4) / "refinement_audit.csv"


def phase5_feature_manifest_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 5) / "feature_manifest.json"


def phase5_base_feature_schema_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 5) / "base_feature_schema.json"


def phase5_feature_preview_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 5) / "feature_preview.csv"


def phase5_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 5) / "summary.json"


def phase6_computed_rules_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 6) / "computed_feature_rules.json"


def phase6_computed_schema_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 6) / "computed_feature_schema.json"


def phase6_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 6) / "summary.json"


def phase7_cleaning_policy_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 7) / "cleaning_policy.json"


def phase7_final_schema_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 7) / "final_schema.json"


def phase7_leakage_drop_list_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 7) / "leakage_drop_list.json"


def phase7_training_feature_list_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 7) / "training_feature_list.json"


def phase7_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 7) / "summary.json"


# ============================================================
# Phase 8 output files
# ============================================================

def phase8_train_csv_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "train.csv"


def phase8_test_csv_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "test.csv"


def phase8_export_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "export_summary.json"


def phase8_split_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "split_summary.json"


def phase8_schema_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "schema.json"


def phase8_feature_roles_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "feature_roles.json"


def phase8_label_distribution_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "label_distribution.csv"


def phase8_feature_availability_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "feature_availability.csv"


def phase8_missing_value_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "missing_value_summary.csv"


def phase8_feature_group_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "feature_group_summary.csv"


def phase8_visualization_sample_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "visualization_sample.csv"


def phase8_corr_leak_sample_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 8) / "corr_leak_sample.csv"


# ============================================================
# Phase 9-14 output files
# ============================================================

def phase9_plots_dir(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 9) / "plots"


def phase9_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 9) / "visualization_summary.json"


def phase10_corr_all_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "corr_all.csv"


def phase10_corr_noleak_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "corr_noleak.csv"


def phase10_target_corr_all_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "target_corr_all.csv"


def phase10_target_corr_noleak_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "target_corr_noleak.csv"


def phase10_redundant_pairs_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "redundant_feature_pairs.csv"


def phase10_leakage_candidates_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "leakage_candidates.json"


def phase10_approved_features_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "approved_nonleak_features.json"


def phase10_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 10) / "summary.json"


def phase11_modeling_config_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 11) / "modeling_config.json"


def phase11_feature_columns_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 11) / "feature_columns.json"


def phase11_target_column_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 11) / "target_column.json"


def phase11_validation_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 11) / "train_test_validation_summary.json"


def phase12_mi_scores_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 12) / "mi_scores.csv"


def phase12_rfe_scores_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 12) / "rfe_scores.csv"


def phase12_pca_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 12) / "pca_summary.csv"


def phase12_selected_features_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 12) / "selected_features.json"


def phase12_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 12) / "summary.json"


def phase13_models_dir(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 13) / "models"


def phase13_cv_metrics_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 13) / "cv_metrics.csv"


def phase13_training_metrics_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 13) / "training_metrics.json"


def phase13_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 13) / "summary.json"


def phase14_holdout_metrics_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 14) / "holdout_metrics.csv"


def phase14_confusion_matrix_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 14) / "confusion_matrix.png"


def phase14_roc_auc_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 14) / "roc_auc.png"


def phase14_classification_report_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 14) / "classification_report.json"


def phase14_evaluation_summary_path(cfg: Any, app: str) -> Path:
    return phase_dir(cfg, app, 14) / "evaluation_summary.json"


# ============================================================
# Convenience bundle / manifest
# ============================================================

@dataclass(frozen=True)
class AppPaths:
    app: str
    external_jsonl: Path
    work_dir: Path
    work_input: Path
    work_outputs: Path
    archive_outputs: Path
    logs: Path


def get_app_paths(cfg: Any, app: str) -> AppPaths:
    app = normalize_app(app)
    return AppPaths(
        app=app,
        external_jsonl=app_external_jsonl_path(cfg, app),
        work_dir=app_work_dir(cfg, app),
        work_input=app_work_input_path(cfg, app),
        work_outputs=app_work_output_dir(cfg, app),
        archive_outputs=app_archive_output_dir(cfg, app),
        logs=app_log_dir(cfg, app),
    )


def phase_output_manifest(cfg: Any, app: str) -> Dict[str, Any]:
    app = normalize_app(app)
    return {
        "app": app,
        "input": {
            "external_jsonl": str(app_external_jsonl_path(cfg, app)),
            "work_jsonl": str(app_work_input_path(cfg, app)),
        },
        "phase1": {"summary": str(phase1_summary_path(cfg, app))},
        "phase2": {"validation_summary": str(phase2_validation_summary_path(cfg, app))},
        "phase3": {
            "probe_features": str(phase3_probe_features_path(cfg, app)),
            "alert_ip_index": str(phase3_alert_ip_index_path(cfg, app)),
            "suspicious_windows": str(phase3_suspicious_windows_path(cfg, app)),
            "summary": str(phase3_summary_path(cfg, app)),
        },
        "phase4": {
            "label_policy": str(phase4_label_policy_path(cfg, app)),
            "suspicious_keys": str(phase4_suspicious_keys_path(cfg, app)),
            "refined_label_summary": str(phase4_refined_label_summary_path(cfg, app)),
            "refinement_audit": str(phase4_refinement_audit_path(cfg, app)),
        },
        "phase5": {
            "feature_manifest": str(phase5_feature_manifest_path(cfg, app)),
            "base_feature_schema": str(phase5_base_feature_schema_path(cfg, app)),
            "feature_preview": str(phase5_feature_preview_path(cfg, app)),
            "summary": str(phase5_summary_path(cfg, app)),
        },
        "phase6": {
            "computed_rules": str(phase6_computed_rules_path(cfg, app)),
            "computed_schema": str(phase6_computed_schema_path(cfg, app)),
            "summary": str(phase6_summary_path(cfg, app)),
        },
        "phase7": {
            "cleaning_policy": str(phase7_cleaning_policy_path(cfg, app)),
            "final_schema": str(phase7_final_schema_path(cfg, app)),
            "leakage_drop_list": str(phase7_leakage_drop_list_path(cfg, app)),
            "training_feature_list": str(phase7_training_feature_list_path(cfg, app)),
            "summary": str(phase7_summary_path(cfg, app)),
        },
        "phase8": {
            "train_csv": str(phase8_train_csv_path(cfg, app)),
            "test_csv": str(phase8_test_csv_path(cfg, app)),
            "export_summary": str(phase8_export_summary_path(cfg, app)),
            "split_summary": str(phase8_split_summary_path(cfg, app)),
            "schema": str(phase8_schema_path(cfg, app)),
            "feature_roles": str(phase8_feature_roles_path(cfg, app)),
            "visualization_sample": str(phase8_visualization_sample_path(cfg, app)),
            "corr_leak_sample": str(phase8_corr_leak_sample_path(cfg, app)),
        },
        "phase10": {
            "approved_features": str(phase10_approved_features_path(cfg, app)),
            "leakage_candidates": str(phase10_leakage_candidates_path(cfg, app)),
        },
        "phase11": {
            "modeling_config": str(phase11_modeling_config_path(cfg, app)),
            "feature_columns": str(phase11_feature_columns_path(cfg, app)),
            "target_column": str(phase11_target_column_path(cfg, app)),
        },
        "archive": {
            "app_archive_output_dir": str(app_archive_output_dir(cfg, app)),
        },
    }
