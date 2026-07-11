from __future__ import annotations

"""
Pipeline orchestrator for the CBR / Suricata EVE workflow.

This file is intentionally an orchestrator only.
It should not contain heavy feature-engineering, probing, cleaning, export,
training, or evaluation logic.

Current design:
- Pre-pipeline split is done outside main.py / pipeline.py.
- Pipeline receives pre-split app files:
    eve_http.jsonl, eve_tls.jsonl, eve_dns.jsonl, eve_ssh.jsonl
- Pipeline runs one app at a time.
- Raw/split/archive data can live on external SSD.
- Current app is copied to internal working storage before processing.
- Phase 3 and Phase 8 are the only phases expected to scan full app JSONL.
- Phase 5/6/7 should output rules/schema/policy, not full datasets.
- Phase 8 should generate train/test CSV + summaries/samples.
- Phase 11 validates/prepares split; it should not split the full data again.
"""

import gc
import importlib
import inspect
import os
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional


def _configure_console_encoding() -> None:
    """Avoid UnicodeEncodeError on Windows consoles when status icons are printed."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_console_encoding()

from .config import RunConfig
from .io_utils import (
    archive_app_outputs,
    cleanup_dir,
    copy_file,
    ensure_dir,
    file_size_gib,
    require_file,
    summarize_files,
    write_json,
)


# ============================================================
# Phase registry
# ============================================================

PHASE_MODULES: Dict[int, str] = {
    1: ".phases.phase1",
    2: ".phases.phase2_app_filter",
    3: ".phases.phase3_probing_analysis",
    4: ".phases.phase4_label_refinement",
    5: ".phases.phase5_feature_engineering",
    6: ".phases.phase6_computed_features",
    7: ".phases.phase7_cleaning",
    8: ".phases.phase8_export_dataset",
    9: ".phases.phase9_visualization",
    10: ".phases.phase10_correlation_leakage",
    11: ".phases.phase11_modeling_split",
    12: ".phases.phase12_fs",
    13: ".phases.phase13_train",
    14: ".phases.phase14_advanced_eval",
}

PHASE_NAMES: Dict[int, str] = {
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

# Preferred new API:
#   def run_phaseX(cfg: RunConfig, app: str, app_input_path: Path, phase_dir: Path, app_output_dir: Path) -> dict
#
# Fallback names are included so each phase can be patched gradually.
PHASE_RUNNER_CANDIDATES: Dict[int, tuple[str, ...]] = {
    1: ("run_phase1", "phase1_run", "phase1_initial_profiling"),
    2: ("run_phase2", "phase2_run", "phase2_validate_app"),
    3: ("run_phase3", "phase3_run", "phase3_probing_analysis"),
    4: ("run_phase4", "phase4_run", "phase4_label_refinement"),
    5: ("run_phase5", "phase5_run", "phase5_build_feature_manifest"),
    6: ("run_phase6", "phase6_run", "phase6_build_computed_rules"),
    7: ("run_phase7", "phase7_run", "phase7_build_cleaning_policy"),
    8: ("run_phase8", "phase8_run", "phase8_export_dataset"),
    9: ("run_phase9", "phase9_run", "phase9_visualization"),
    10: ("run_phase10", "phase10_run", "phase10_correlation_leakage"),
    11: ("run_phase11", "phase11_run", "phase11_modeling_preparation"),
    12: ("run_phase12", "phase12_run", "phase12_feature_selection"),
    13: ("run_phase13", "phase13_run", "phase13_train"),
    14: ("run_phase14", "phase14_run", "phase14_advanced_eval"),
}


# ============================================================
# Path helpers
# ============================================================

def _phase_enabled(cfg: RunConfig, phase: int) -> bool:
    return bool(cfg.enabled_phases().get(f"phase{int(phase)}", False))


def _phase_dir(cfg: RunConfig, app: str, phase: int) -> Path:
    return cfg.storage.phase_dir(app, PHASE_NAMES[int(phase)])


def _app_context_path(cfg: RunConfig, app: str) -> Path:
    return cfg.storage.app_output_dir(app) / "app_context.json"


def _app_status_path(cfg: RunConfig, app: str) -> Path:
    return cfg.storage.app_output_dir(app) / "app_status.json"


def _run_log_dir(cfg: RunConfig) -> Path:
    return cfg.storage.archive_output_dir / "_run_logs"


def _pipeline_summary_path(cfg: RunConfig) -> Path:
    return _run_log_dir(cfg) / "pipeline_summary.json"


def _pipeline_failed_path(cfg: RunConfig) -> Path:
    return _run_log_dir(cfg) / "pipeline_failed.json"


def _pipeline_pdf_status_path(cfg: RunConfig) -> Path:
    return _run_log_dir(cfg) / "pdf_report_status.json"


def _generated_file_line_counts_from_summary(summary: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Extract file line-count metadata from a phase summary without scanning large files."""
    if not isinstance(summary, dict):
        return {}

    direct = summary.get("generated_file_line_counts")
    if isinstance(direct, dict) and direct:
        return direct

    # Phase 8 fallback for older summaries. Data rows are known from counters;
    # CSV physical lines include one header row, JSONL physical lines do not.
    if int(summary.get("phase", 0) or 0) == 8:
        export_format = str(summary.get("output_format") or "csv").lower()
        has_header = export_format == "csv"
        out: dict[str, Any] = {}

        def add(name: str, path_key: str, rows_key: str, size_key: str) -> None:
            rows = int(summary.get(rows_key, 0) or 0)
            path = summary.get(path_key)
            if not path and rows <= 0:
                return
            out[name] = {
                "path": str(path) if path else None,
                "data_rows": rows,
                "physical_lines": rows + (1 if has_header and path else 0),
                "line_count_method": "pipeline_phase8_counter_fallback",
                "size_bytes": int(summary.get(size_key, 0) or 0),
            }

        add("train", "train_path", "train_rows", "train_size_bytes")
        add("test", "test_path", "test_rows", "test_size_bytes")

        sample_files = summary.get("summary_files") if isinstance(summary.get("summary_files"), dict) else {}
        for key, rows_key in (
            ("visualization_sample", "visualization_sample_rows"),
            ("corr_leak_sample", "corr_leak_sample_rows"),
        ):
            rows = int(summary.get(rows_key, 0) or 0)
            path = sample_files.get(key)
            if path or rows:
                out[key] = {
                    "path": str(path) if path else None,
                    "data_rows": rows,
                    "physical_lines": rows + (1 if path else 0),
                    "line_count_method": "pipeline_phase8_sample_counter_fallback",
                    "size_bytes": 0,
                }
        return out

    return {}


def _collect_generated_line_counts_from_phase_statuses(phase_statuses: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase_key, payload in sorted((phase_statuses or {}).items()):
        if not isinstance(payload, dict):
            continue
        counts = payload.get("generated_file_line_counts")
        if not isinstance(counts, dict) or not counts:
            counts = _generated_file_line_counts_from_summary(payload.get("summary"))
        if counts:
            out[str(phase_key)] = counts
    return out


def _json_scalar(value: Any) -> Any:
    """Return a compact JSON-safe scalar."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    try:
        # numpy/pandas scalars expose item(); keep this dependency-free.
        item = value.item()  # type: ignore[attr-defined]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
    except Exception:
        pass
    return str(value)


def _compact_value(value: Any, *, max_depth: int = 2, max_list: int = 25, max_dict: int = 80) -> Any:
    """Compact arbitrary phase outputs before duplicating them in pipeline summaries.

    Detailed phase artifacts remain in each phase directory. Pipeline-level JSON
    should be an index/overview, not another full copy of every phase result.
    """
    if max_depth <= 0:
        if isinstance(value, dict):
            return {"_type": "dict", "_keys": len(value)}
        if isinstance(value, (list, tuple, set)):
            return {"_type": type(value).__name__, "_len": len(value)}
        return _json_scalar(value)

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= max_dict:
                out["_truncated"] = True
                out["_original_key_count"] = len(value)
                break
            out[str(k)] = _compact_value(v, max_depth=max_depth - 1, max_list=max_list, max_dict=max_dict)
        return out

    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [
            _compact_value(v, max_depth=max_depth - 1, max_list=max_list, max_dict=max_dict)
            for v in seq[:max_list]
        ]
        if len(seq) > max_list:
            out.append({"_truncated": True, "_original_len": len(seq)})
        return out

    return _json_scalar(value)


def _pick_existing(d: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {k: _compact_value(d[k], max_depth=2) for k in keys if k in d}


def _compact_phase_summary(summary: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Keep only report/index fields in pipeline/app status files.

    The original phase functions still write their detailed `summary.json`, CSV,
    figure, and model artifacts in the phase folders. This compact copy prevents
    `pipeline_summary.json` from growing to hundreds of thousands of lines.
    """
    if not isinstance(summary, dict) or not summary:
        return {}

    keep_common = (
        "phase", "title", "status", "current_run", "app", "generated_at", "mode",
        "rows_seen", "rows_written", "total_rows", "train_rows", "test_rows",
        "train_rows_loaded", "test_rows_loaded", "natural_test_rows_loaded",
        "balanced_test_rows_loaded", "results_rows", "feature_count",
        "numeric_features_used", "modeling_feature_count", "target_column",
        "output_format", "compression", "train_path", "test_path",
        "train_size_bytes", "test_size_bytes", "fs_sample_rows",
        "fs_sample_rows_requested", "fs_per_class_rows_requested", "fs_sampling_strategy",
        "mi_selected_n", "rfe_selected_n", "pca_n_components", "pca_cumulative_variance",
        "top_k", "cv_folds", "best_model", "recommended_default",
        "dataset_generation_note", "note", "skip_reason", "root_cause_hint",
        "visualization_source", "visualization_aggregates_path",
    )
    out = _pick_existing(summary, keep_common)

    # Compact, but preserve count/policy blocks used by PDF and diagnostics.
    nested_keep = (
        "target_counts", "target_alert_counts", "label_source_counts",
        "target_counts_by_split", "target_alert_counts_by_split", "label_source_counts_by_split",
        "train_target_counts", "test_target_counts", "file_class_summary",
        "dataset_total_class_summary", "train_file_class_summary", "test_file_class_summary",
        "split_class_coverage", "alert_policy_counts", "phase8_label_diagnostics",
        "sample_info", "sample_class_summary", "fs_sampling_policy", "prep_info",
        "mi_info", "rfe_info", "removed_by_final_guard",
        "evaluation_policy", "natural_holdout_table", "balanced_holdout_table",
        "legacy_holdout_table", "roc_auc_summary", "roc_curve_status",
        "confusion_matrix_status", "generated_file_line_counts",
        "summary_files", "output", "figures", "input",
    )
    for key in nested_keep:
        if key in summary:
            out[key] = _compact_value(summary[key], max_depth=3, max_list=30, max_dict=120)

    # Result tables can be very large. Store dimensions/columns only; detailed
    # rows remain in phase13/results_comparison.csv and phase14/performance_table.csv.
    for key in ("results_table", "natural_holdout_table_rows", "balanced_holdout_table_rows"):
        val = summary.get(key)
        if isinstance(val, list):
            out[f"{key}_meta"] = {
                "rows": len(val),
                "columns": list(val[0].keys()) if val and isinstance(val[0], dict) else [],
            }
        elif isinstance(val, dict):
            out[key] = _compact_value(val, max_depth=2)

    for key in ("warnings", "split_warnings", "training_quality_warnings"):
        val = summary.get(key)
        if isinstance(val, list):
            out[key] = [str(x) for x in val[:20]]
            if len(val) > 20:
                out[f"{key}_truncated"] = len(val) - 20

    return out


def _compact_phase_status(payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    out = {
        "app": payload.get("app"),
        "phase": payload.get("phase"),
        "phase_name": payload.get("phase_name"),
        "status": payload.get("status"),
        "seconds": payload.get("seconds"),
        "updated_at": payload.get("updated_at"),
    }
    if payload.get("error"):
        out["error"] = payload.get("error")
    if payload.get("traceback"):
        tb = str(payload.get("traceback"))
        out["traceback_tail"] = tb[-4000:]
    counts = payload.get("generated_file_line_counts")
    if isinstance(counts, dict) and counts:
        out["generated_file_line_counts"] = _compact_value(counts, max_depth=3, max_dict=120)
    out["summary"] = _compact_phase_summary(payload.get("summary"))
    return out


def _compact_phase_statuses(phase_statuses: dict[str, Any]) -> dict[str, Any]:
    return {str(k): _compact_phase_status(v) for k, v in (phase_statuses or {}).items()}


def _compact_app_summary(app_summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(app_summary, dict):
        return {}
    return {
        "app": app_summary.get("app"),
        "status": app_summary.get("status"),
        "error": app_summary.get("error"),
        "started_at": app_summary.get("started_at"),
        "finished_at": app_summary.get("finished_at"),
        "elapsed_seconds": app_summary.get("elapsed_seconds"),
        "elapsed_minutes": app_summary.get("elapsed_minutes"),
        "context": _compact_value(app_summary.get("context", {}), max_depth=2, max_dict=80),
        "phase_statuses": _compact_phase_statuses(app_summary.get("phase_statuses", {})),
        "generated_file_line_counts": _compact_value(app_summary.get("generated_file_line_counts", {}), max_depth=3, max_dict=120),
        "archived_to": app_summary.get("archived_to"),
        "files": _compact_value(app_summary.get("files", {}), max_depth=2, max_dict=80),
        "summary_mode": "compact; detailed per-phase summaries remain under <app>/phase*/summary.json",
    }


def _pipeline_apps_overview(app_results: dict[str, Any]) -> dict[str, Any]:
    overview: dict[str, Any] = {}
    for app, payload in (app_results or {}).items():
        if not isinstance(payload, dict):
            continue
        phases = payload.get("phase_statuses", {}) if isinstance(payload.get("phase_statuses"), dict) else {}
        overview[str(app)] = {
            "status": payload.get("status"),
            "elapsed_minutes": payload.get("elapsed_minutes"),
            "phase_status_counts": dict(Counter(str(v.get("status", "unknown")) for v in phases.values() if isinstance(v, dict))),
            "phase_seconds": {k: v.get("seconds") for k, v in phases.items() if isinstance(v, dict)},
            "app_status_path": _app_status_path_cached(payload),
        }
    return overview


def _app_status_path_cached(app_summary: dict[str, Any]) -> Optional[str]:
    # app_summary does not store cfg, but the written file path is inferable from
    # the context block and useful for humans inspecting pipeline_summary.json.
    ctx = app_summary.get("context") if isinstance(app_summary.get("context"), dict) else {}
    app_out = ctx.get("app_output_dir")
    return str(Path(str(app_out)) / "app_status.json") if app_out else None


def _should_generate_pdf_after_pipeline(cfg: RunConfig) -> bool:
    if os.environ.get("CBR_DISABLE_AUTO_PDF", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        return False

    # Default is ON because the current workflow wants the final report produced
    # immediately after a successful pipeline run. These optional config fields
    # are read only if they exist, so config.py does not need to be patched.
    enabled = bool(getattr(cfg, "generate_pdf_after_pipeline", True))
    for attr in ("report", "pdf_report", "reporting"):
        obj = getattr(cfg, attr, None)
        if obj is None:
            continue
        if hasattr(obj, "generate_pdf_after_pipeline"):
            enabled = bool(getattr(obj, "generate_pdf_after_pipeline"))
        if hasattr(obj, "auto_generate_after_pipeline"):
            enabled = bool(getattr(obj, "auto_generate_after_pipeline"))
    return enabled


def _find_generate_pdf_script(cfg: RunConfig) -> Optional[Path]:
    explicit = getattr(cfg, "generate_pdf_script", None) or getattr(cfg, "pdf_report_script", None)
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(str(explicit)))

    here = Path(__file__).resolve()
    # Expected layout: src/cbr/pipeline.py and src/scripts/generate_pdf/generate_pdf.py
    candidates.extend([
        here.parents[1] / "scripts" / "generate_pdf" / "generate_pdf.py",
        here.parents[2] / "src" / "scripts" / "generate_pdf" / "generate_pdf.py",
        Path.cwd() / "src" / "scripts" / "generate_pdf" / "generate_pdf.py",
        Path.cwd() / "scripts" / "generate_pdf" / "generate_pdf.py",
        Path.cwd() / "generate_pdf" / "generate_pdf.py",
    ])

    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return p.resolve()
        except Exception:
            continue
    return None


def _run_pdf_report_after_success(cfg: RunConfig, *, run_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    status: dict[str, Any] = {
        "enabled": _should_generate_pdf_after_pipeline(cfg),
        "started_at": datetime.now().isoformat(),
        "status": "skipped",
    }

    if not status["enabled"]:
        status["reason"] = "disabled"
        write_json(status, _pipeline_pdf_status_path(cfg))
        return status

    script = _find_generate_pdf_script(cfg)
    if script is None:
        status.update({
            "status": "skipped",
            "reason": "generate_pdf.py not found",
        })
        write_json(status, _pipeline_pdf_status_path(cfg))
        return status

    reports_dir = cfg.storage.archive_output_dir / "reports"
    ensure_dir(reports_dir)
    out_pdf = reports_dir / f"pipeline_report_{run_id}.pdf"

    cmd = [
        sys.executable,
        str(script),
        "--artifacts",
        str(cfg.storage.archive_output_dir),
        "--out",
        str(out_pdf),
        "--run-id",
        str(run_id),
    ]

    print("🧾 Generate final PDF report...")
    print(f"   Script : {script}")
    print(f"   Output : {out_pdf}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(script.parent),
            text=True,
            capture_output=True,
            check=False,
        )
        status.update({
            "status": "completed" if proc.returncode == 0 and out_pdf.exists() else "failed",
            "script": str(script),
            "output_pdf": str(out_pdf),
            "returncode": int(proc.returncode),
            "stdout_tail": proc.stdout[-4000:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-4000:] if proc.stderr else "",
            "seconds": float(time.perf_counter() - started),
            "size_bytes": int(out_pdf.stat().st_size) if out_pdf.exists() else 0,
        })
    except Exception as exc:
        status.update({
            "status": "failed",
            "script": str(script),
            "output_pdf": str(out_pdf),
            "error": repr(exc),
            "seconds": float(time.perf_counter() - started),
        })

    write_json(status, _pipeline_pdf_status_path(cfg))
    if status.get("status") == "completed":
        print(f"✅ PDF report generated: {out_pdf}")
    else:
        print(f"⚠️ PDF report was not generated successfully. See: {_pipeline_pdf_status_path(cfg)}")
    return status


def _external_app_input(cfg: RunConfig, app: str) -> Path:
    return cfg.storage.app_external_input(app)


def _internal_app_input(cfg: RunConfig, app: str) -> Path:
    return cfg.storage.app_work_input(app)


def _selected_apps(cfg: RunConfig) -> list[str]:
    out: list[str] = []
    for app in cfg.selected_apps:
        app_norm = str(app).strip().lower()
        if app_norm and app_norm not in out:
            out.append(app_norm)
    return out


# ============================================================
# Setup / validation
# ============================================================

def _ensure_base_dirs(cfg: RunConfig) -> None:
    cfg.ensure_base_dirs()
    ensure_dir(_run_log_dir(cfg))


def _ensure_app_dirs(cfg: RunConfig, app: str) -> None:
    cfg.ensure_app_dirs(app)
    ensure_dir(cfg.storage.app_output_dir(app))
    ensure_dir(cfg.storage.app_archive_dir(app))
    for phase in range(1, 15):
        ensure_dir(_phase_dir(cfg, app, phase))


def _validate_app_inputs(cfg: RunConfig, apps: Iterable[str]) -> None:
    missing: list[str] = []
    for app in apps:
        p = _external_app_input(cfg, app)
        if not p.exists():
            missing.append(str(p))

    if missing and cfg.require_app_input_exists:
        lines = [
            "Missing pre-split app input file(s).",
            "Run the pre-pipeline split script first, or fix --split-app-dir.",
            "",
            *[f" - {x}" for x in missing],
        ]
        raise FileNotFoundError("\n".join(lines))


def _prepare_app_input(cfg: RunConfig, app: str) -> Path:
    """
    Return the app input path that phases should read.

    Default workflow:
    external split_app/eve_<app>.jsonl -> internal work/apps/<app>/eve_<app>.jsonl

    The copy avoids running heavy phases directly from external SSD.
    """
    external_path = require_file(_external_app_input(cfg, app), label=f"{app} external app JSONL")

    if not cfg.copy_app_to_internal_before_run:
        return external_path

    internal_path = _internal_app_input(cfg, app)
    print(f"📥 Copy app input to internal SSD: {external_path} -> {internal_path}")
    copied = copy_file(external_path, internal_path, overwrite=True, label=f"{app} app input")
    size_gib = file_size_gib(copied)
    print(f"✅ Input ready: {copied} ({size_gib:.2f} GiB)")
    return copied


def _write_app_context(
    cfg: RunConfig,
    app: str,
    *,
    app_input_path: Path,
    started_at: datetime,
) -> dict[str, Any]:
    context = {
        "app": app,
        "run_mode": cfg.run_mode,
        "started_at": started_at.isoformat(),
        "external_app_input": str(_external_app_input(cfg, app)),
        "active_app_input": str(app_input_path),
        "app_work_dir": str(cfg.storage.app_work_dir(app)),
        "app_output_dir": str(cfg.storage.app_output_dir(app)),
        "app_archive_dir": str(cfg.storage.app_archive_dir(app)),
        "prepipeline_summary_path": str(cfg.prepipeline_summary_path) if cfg.prepipeline_summary_path else None,
        "target_column": cfg.split.target_column,
        "split_strategy": cfg.split.strategy,
        "phase8_exports_train_test": bool(cfg.split.export_train_test_in_phase8),
        "modeling_subset_enabled": bool(cfg.modeling.allow_modeling_subset),
        "enabled_phases": cfg.enabled_phases(),
    }
    write_json(context, _app_context_path(cfg, app))
    return context


# ============================================================
# Phase calling
# ============================================================

def _load_phase_runner(phase: int) -> Callable[..., Any]:
    module_name = PHASE_MODULES[int(phase)]
    module = importlib.import_module(module_name, package=__package__)

    names = PHASE_RUNNER_CANDIDATES.get(int(phase), ())
    generic_names = (f"run_phase{int(phase)}", "run")
    for name in (*names, *generic_names):
        runner = getattr(module, name, None)
        if callable(runner):
            return runner

    expected = ", ".join(dict.fromkeys((*names, *generic_names)))
    raise AttributeError(
        f"No compatible runner found for Phase {phase} in {module_name}. "
        f"Expected one of: {expected}. "
        f"Patch the phase file to expose run_phase{phase}(...)."
    )


def _call_runner(
    runner: Callable[..., Any],
    *,
    cfg: RunConfig,
    app: str,
    phase: int,
    app_input_path: Path,
) -> Any:
    """
    Call phase runner flexibly so phase files can be patched one by one.

    Preferred function signature:
        run_phaseX(
            cfg: RunConfig,
            app: str,
            app_input_path: Path,
            phase_dir: Path,
            app_output_dir: Path,
        ) -> dict
    """
    phase_output_dir = _phase_dir(cfg, app, phase)
    app_output_dir = cfg.storage.app_output_dir(app)

    common_kwargs: dict[str, Any] = {
        "cfg": cfg,
        "config": cfg,
        "run_config": cfg,
        "app": app,
        "target_app": app,
        "app_input_path": app_input_path,
        "input_path": app_input_path,
        "app_file": app_input_path,
        "phase_dir": phase_output_dir,
        "output_dir": phase_output_dir,
        "app_output_dir": app_output_dir,
        "prepipeline_summary_path": cfg.prepipeline_summary_path,
    }

    try:
        sig = inspect.signature(runner)
    except Exception:
        return runner(cfg, app)

    params = sig.parameters
    has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    if has_var_kwargs:
        return runner(**common_kwargs)

    kwargs = {name: value for name, value in common_kwargs.items() if name in params}

    if kwargs:
        return runner(**kwargs)

    # Fallback for simple positional APIs.
    try:
        return runner(cfg, app)
    except TypeError:
        return runner()


def _summary_from_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}

    if isinstance(result, dict):
        return result

    if isinstance(result, tuple):
        # Common legacy pattern: (data, summary)
        for item in reversed(result):
            if isinstance(item, dict):
                return item

    # Avoid trying to serialize large DataFrames or model objects.
    return {
        "result_type": type(result).__name__,
        "note": "Phase returned a non-dict result. Only type was captured by pipeline.",
    }


def _write_phase_status(
    cfg: RunConfig,
    app: str,
    phase: int,
    *,
    status: str,
    seconds: float = 0.0,
    summary: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    payload = {
        "app": app,
        "phase": int(phase),
        "phase_name": PHASE_NAMES[int(phase)],
        "status": status,
        "seconds": float(seconds),
        "updated_at": datetime.now().isoformat(),
        "summary": _compact_phase_summary(summary),
        "summary_mode": "compact; detailed phase summary is stored in the phase artifact directory when produced by the phase",
    }
    generated_counts = _generated_file_line_counts_from_summary(summary)
    if generated_counts:
        payload["generated_file_line_counts"] = generated_counts

    if error:
        payload["error"] = error

    write_json(payload, _phase_dir(cfg, app, phase) / "pipeline_status.json")
    return payload


def _run_phase(
    cfg: RunConfig,
    app: str,
    phase: int,
    *,
    app_input_path: Path,
) -> dict[str, Any]:
    if not _phase_enabled(cfg, phase):
        print(f"⏭️  {app.upper()} P{phase}: skipped")
        return _write_phase_status(
            cfg,
            app,
            phase,
            status="skipped",
            summary={"reason": "disabled_by_config"},
        )

    print(f"\n▶️  {app.upper()} P{phase}: {PHASE_NAMES[phase]}")
    t0 = time.perf_counter()

    try:
        runner = _load_phase_runner(phase)
        result = _call_runner(
            runner,
            cfg=cfg,
            app=app,
            phase=phase,
            app_input_path=app_input_path,
        )
        seconds = time.perf_counter() - t0
        summary = _summary_from_result(result)

        status = "completed"
        if isinstance(summary, dict) and summary.get("status"):
            status = str(summary.get("status"))

        phase_status = _write_phase_status(
            cfg,
            app,
            phase,
            status=status,
            seconds=seconds,
            summary=summary,
        )

        print(f"✅ {app.upper()} P{phase} done in {seconds/60:.2f} min")
        return phase_status

    except Exception as exc:
        seconds = time.perf_counter() - t0
        error_payload = {
            "app": app,
            "phase": int(phase),
            "phase_name": PHASE_NAMES[int(phase)],
            "status": "failed",
            "seconds": float(seconds),
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "updated_at": datetime.now().isoformat(),
        }
        write_json(error_payload, _phase_dir(cfg, app, phase) / "pipeline_status.json")
        write_json(error_payload, cfg.storage.app_output_dir(app) / f"failed_phase{phase}.json")
        print(f"❌ {app.upper()} P{phase} failed: {exc!r}")
        raise


# ============================================================
# Archive / cleanup
# ============================================================

def _archive_app_if_requested(cfg: RunConfig, app: str) -> Optional[Path]:
    if not cfg.storage.archive_app_outputs_after_app:
        return None

    src = cfg.storage.app_output_dir(app)
    dst = cfg.storage.app_archive_dir(app)

    print(f"📦 Archive app outputs: {src} -> {dst}")
    archived = archive_app_outputs(src, dst, overwrite=True)
    print(f"✅ Archived: {archived}")
    return archived


def _cleanup_app_if_requested(cfg: RunConfig, app: str, *, archived: bool) -> None:
    if not cfg.storage.cleanup_internal_after_app:
        return

    if not archived:
        print(
            f"⚠️ Cleanup requested for {app.upper()}, but archive-after-app is OFF. "
            "Skipping cleanup to avoid losing outputs."
        )
        return

    work_dir = cfg.storage.app_work_dir(app)
    print(f"🧹 Cleanup internal app workdir: {work_dir}")
    cleanup_dir(work_dir, keep_dir=False)
    print("✅ Cleanup complete")


# ============================================================
# Per-app and full pipeline
# ============================================================

def run_app_pipeline(cfg: RunConfig, app: str, progress: Optional[Callable[[int, str], None]] = None) -> dict[str, Any]:
    app = str(app).strip().lower()
    started_at = datetime.now()
    t0 = time.perf_counter()

    print("\n" + "=" * 88)
    print(f"🚀 START APP: {app.upper()}")
    print("=" * 88)

    _ensure_app_dirs(cfg, app)
    app_input_path = _prepare_app_input(cfg, app)
    context = _write_app_context(cfg, app, app_input_path=app_input_path, started_at=started_at)

    phase_statuses: dict[str, Any] = {}
    status = "completed"
    error: Optional[str] = None
    archived_path: Optional[Path] = None

    try:
        for phase in range(1, 15):
            # Observation-only progress hook fired BEFORE the phase runs. Wrapped
            # so a broken reporter can never perturb the pipeline or its result.
            if progress is not None:
                try:
                    progress(phase, PHASE_NAMES.get(phase, f"phase{phase}"))
                except Exception:
                    pass
            phase_statuses[f"phase{phase}"] = _run_phase(
                cfg,
                app,
                phase,
                app_input_path=app_input_path,
            )

        archived_path = _archive_app_if_requested(cfg, app)

    except Exception as exc:
        status = "failed"
        error = repr(exc)
        failure = {
            "app": app,
            "status": status,
            "error": error,
            "traceback": traceback.format_exc(),
            "updated_at": datetime.now().isoformat(),
        }
        write_json(failure, cfg.storage.app_output_dir(app) / "app_failed.json")
        print(f"❌ APP FAILED: {app.upper()} | {error}")
        raise

    finally:
        elapsed = time.perf_counter() - t0
        finished_at = datetime.now()

        files_summary = summarize_files(
            {
                "external_input": _external_app_input(cfg, app),
                "active_input": app_input_path,
                "app_context": _app_context_path(cfg, app),
            }
        )

        generated_file_line_counts = _collect_generated_line_counts_from_phase_statuses(phase_statuses)

        app_summary_full = {
            "app": app,
            "status": status,
            "error": error,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_seconds": float(elapsed),
            "elapsed_minutes": float(elapsed / 60.0),
            "context": context,
            "phase_statuses": phase_statuses,
            "generated_file_line_counts": generated_file_line_counts,
            "archived_to": str(archived_path) if archived_path else None,
            "files": files_summary,
        }
        app_summary = _compact_app_summary(app_summary_full)

        write_json(app_summary, _app_status_path(cfg, app))

        _cleanup_app_if_requested(cfg, app, archived=archived_path is not None and status == "completed")

        gc.collect()

    print("\n" + "=" * 88)
    print(f"✅ FINISHED APP: {app.upper()} | status={status} | elapsed={app_summary['elapsed_minutes']:.2f} min")
    print("=" * 88 + "\n")

    return app_summary


def run_pipeline(cfg: RunConfig, progress: Optional[Callable[[int, str], None]] = None) -> dict[str, Any]:
    """
    Run the configured CBR pipeline.

    Expected precondition:
        pre-pipeline split has already produced eve_<app>.jsonl files.

    ``progress`` is an OPTIONAL observation-only hook ``progress(phase_no, phase_name)``
    fired just before each of the 14 phases. It defaults to None (byte-identical
    behaviour to before) and must never influence computation, ordering, or seeds.
    """
    _ensure_base_dirs(cfg)

    apps = _selected_apps(cfg)
    _validate_app_inputs(cfg, apps)

    started_at = datetime.now()
    t0 = time.perf_counter()

    print("\n" + "=" * 88)
    print("🚀 CBR / SURICATA EVE PIPELINE")
    print("=" * 88)
    print(f"Started              : {started_at:%Y-%m-%d %H:%M:%S}")
    print(f"Run mode             : {cfg.run_mode}")
    print(f"Selected apps        : {', '.join(apps)}")
    print(f"Split app dir        : {cfg.storage.split_app_dir}")
    print(f"Internal work root   : {cfg.storage.internal_work_root}")
    print(f"Archive output dir   : {cfg.storage.archive_output_dir}")
    print(f"Copy app to internal : {cfg.copy_app_to_internal_before_run}")
    print(f"Archive after app    : {cfg.storage.archive_app_outputs_after_app}")
    print(f"Cleanup after app    : {cfg.storage.cleanup_internal_after_app}")
    print(f"Target column        : {cfg.split.target_column}")
    print(f"Enabled phases       : {cfg.enabled_phases()}")
    print("=" * 88 + "\n")

    app_results: dict[str, Any] = {}
    status = "completed"
    error: Optional[str] = None

    try:
        for app in apps:
            app_results[app] = run_app_pipeline(cfg, app, progress=progress)

    except Exception as exc:
        status = "failed"
        error = repr(exc)
        failure = {
            "status": status,
            "error": error,
            "traceback": traceback.format_exc(),
            "updated_at": datetime.now().isoformat(),
            "apps_completed": list(app_results.keys()),
        }
        write_json(failure, _pipeline_failed_path(cfg))
        raise

    finally:
        finished_at = datetime.now()
        elapsed = time.perf_counter() - t0

        generated_file_line_counts_by_app = {
            app_name: app_payload.get("generated_file_line_counts", {})
            for app_name, app_payload in app_results.items()
            if isinstance(app_payload, dict) and app_payload.get("generated_file_line_counts")
        }

        summary = {
            "status": status,
            "error": error,
            "run_mode": cfg.run_mode,
            "selected_apps": apps,
            "enabled_phases": cfg.enabled_phases(),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "elapsed_seconds": float(elapsed),
            "elapsed_minutes": float(elapsed / 60.0),
            "storage": {
                "external_archive_root": str(cfg.storage.external_archive_root),
                "split_app_dir": str(cfg.storage.split_app_dir),
                "archive_output_dir": str(cfg.storage.archive_output_dir),
                "internal_work_root": str(cfg.storage.internal_work_root),
            },
            "split": {
                "target_column": cfg.split.target_column,
                "strategy": cfg.split.strategy,
                "train_ratio": cfg.split.train_ratio,
                "test_ratio": cfg.split.test_ratio,
                "export_train_test_in_phase8": cfg.split.export_train_test_in_phase8,
            },
            "export": {
                "format": cfg.export.format,
                "compression": cfg.export.compression,
                "visualization_sample_rows": cfg.export.visualization_sample_rows,
                "corr_leak_sample_rows": cfg.export.corr_leak_sample_rows,
            },
            "modeling": {
                "allow_modeling_subset": cfg.modeling.allow_modeling_subset,
                "modeling_train_rows": cfg.modeling.modeling_train_rows,
                "modeling_test_rows": cfg.modeling.modeling_test_rows,
                "temporary_training_cache": cfg.modeling.create_temporary_training_cache,
            },
            "generated_file_line_counts_by_app": generated_file_line_counts_by_app,
            "apps_overview": _pipeline_apps_overview(app_results),
            "apps": {app_name: _compact_app_summary(app_payload) for app_name, app_payload in app_results.items()},
            "summary_mode": (
                "compact pipeline summary; detailed per-app and per-phase artifacts remain under "
                "archive_output_dir/<app>/phase*/"
            ),
        }

        # Write once before report generation so generate_pdf.py can read the
        # latest successful pipeline summary, then write again with PDF status.
        write_json(summary, _pipeline_summary_path(cfg))
        if status == "completed" and error is None:
            run_id = started_at.strftime("%Y%m%d_%H%M%S")
            summary["pdf_report"] = _run_pdf_report_after_success(cfg, run_id=run_id)
            write_json(summary, _pipeline_summary_path(cfg))

    print("\n" + "=" * 88)
    print(f"✅ PIPELINE FINISHED | status={status} | elapsed={summary['elapsed_minutes']:.2f} min")
    print(f"Summary: {_pipeline_summary_path(cfg)}")
    print("=" * 88 + "\n")

    return summary
