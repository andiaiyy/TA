"""
Run Experiment page — supports both sync and async execution.
"""
import logging
import time
from pathlib import Path
import streamlit as st

logger = logging.getLogger(__name__)
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

from orchestrator.experiment_service import (
    validate_dataset_for_ui, create_and_run_experiment, get_experiment_status,
    cancel_experiment,
    get_diag,  # [DIAG] dispatch diagnostic accessor
)
from orchestrator.execution_service import get_pipeline_info
from orchestrator.validation_service import get_available_datasets
from orchestrator.result_service import get_experiment_metrics, get_full_experiment, get_experiment_metadata
from config.settings import DATASETS_DIR
from ui.views._artifact_browser import render_file_browser

_EXT_MAP = {"EVE_SURICATA": ".json"}

_POLL_INTERVALS = {
    "svc": 30,
    "knn": 15,
    "lr":  10,
    "rfc": 10,
    "rfe": 10,
    "dt":  5,
    "nb":  5,
}
_DEFAULT_POLL_INTERVAL = 8


def _get_poll_interval(pipeline_id: str) -> int:
    pid_lower = (pipeline_id or "").lower()
    for key, seconds in _POLL_INTERVALS.items():
        if key in pid_lower:
            return seconds
    return _DEFAULT_POLL_INTERVAL


# ── Pipeline Config Viewer support ─────────────────────────────────────────

def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s.strip() != s or any(c in s for c in (":", "#", "\n", '"')):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _dict_to_yaml(obj, indent: int = 0) -> str:
    """Minimal YAML renderer for get_info() output. Avoids a PyYAML
    dependency; handles the nested dict/list/scalar shapes get_info returns.
    Display-only, not intended to round-trip through a YAML parser."""
    pad = "  " * indent
    out = []
    if isinstance(obj, dict):
        for k, val in obj.items():
            if isinstance(val, (dict, list)) and val:
                out.append(f"{pad}{k}:")
                out.append(_dict_to_yaml(val, indent + 1))
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(val)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}-")
                out.append(_dict_to_yaml(item, indent + 1))
            else:
                out.append(f"{pad}- {_yaml_scalar(item)}")
    else:
        return f"{pad}{_yaml_scalar(obj)}"
    return "\n".join(out)


def _type_name(t) -> str:
    if isinstance(t, str):
        return t
    return getattr(t, "__name__", str(t))


def _build_pipeline_config_files(pipeline_id: str) -> dict:
    """Build the four virtual files for the Pipeline Config Viewer.

    Each value is a lazy loader so only the selected file is materialized.
    Source reading is path-guarded to the pipelines/ directory; no user
    input reaches the filesystem (selection is from the registry only)."""
    import inspect
    import json
    import dataclasses
    from config.pipeline_registry import get_pipeline
    from config.settings import BASE_DIR
    from contracts.pipeline_contracts import PipelineInput, PipelineResult

    entry = get_pipeline(pipeline_id)
    if entry is None:
        return {}
    cls = entry.get("class")

    def _load_info() -> str:
        info = get_pipeline_info(pipeline_id) or {}
        return _dict_to_yaml(info)

    def _load_source() -> str:
        if cls is None:
            return "Source code tidak tersedia untuk pipeline ini."
        try:
            src_file = inspect.getsourcefile(cls)
            if src_file:
                p = Path(src_file).resolve()
                pipelines_root = (Path(BASE_DIR) / "pipelines").resolve()
                if not p.is_relative_to(pipelines_root):
                    return "Source code tidak tersedia (berkas di luar direktori pipelines/)."
                return p.read_text(encoding="utf-8")
            return inspect.getsource(cls)
        except Exception:
            try:
                return inspect.getsource(cls)
            except Exception:
                return "Source code tidak tersedia untuk pipeline ini."

    def _source_path() -> str:
        try:
            src_file = inspect.getsourcefile(cls)
            if src_file:
                return str(Path(src_file).resolve().relative_to(Path(BASE_DIR).resolve()))
        except Exception:
            pass
        return f"pipelines/<{pipeline_id}>.py"

    def _load_registry() -> str:
        e = {"pipeline_id": pipeline_id}
        for k, val in entry.items():
            e[k] = val.__name__ if (k == "class" and hasattr(val, "__name__")) else val
        return json.dumps(e, indent=2, default=str)

    def _load_contract() -> str:
        lines = ["# Kontrak data antara orchestrator dan pipeline", "",
                 "PipelineInput (orchestrator -> pipeline):"]
        for f in dataclasses.fields(PipelineInput):
            lines.append(f"    {f.name}: {_type_name(f.type)}")
        lines += ["", "PipelineResult (pipeline -> orchestrator):"]
        for f in dataclasses.fields(PipelineResult):
            lines.append(f"    {f.name}: {_type_name(f.type)}")
        return "\n".join(lines)

    return {
        "info.yaml": {
            "icon": "", "language": "yaml", "loader": _load_info,
            "full_path": f"<virtual>/{pipeline_id}/info.yaml",
            "download_name": "info.yaml",
        },
        "pipeline_source.py": {
            "icon": "", "language": "python", "loader": _load_source,
            "full_path": _source_path(), "download_name": "pipeline_source.py",
        },
        "registry_entry.json": {
            "icon": "", "language": "json", "loader": _load_registry,
            "full_path": "config/pipeline_registry.py (entry)",
            "download_name": "registry_entry.json",
        },
        "contract.txt": {
            "icon": "", "language": "text", "loader": _load_contract,
            "full_path": "contracts/pipeline_contracts.py (summary)",
            "download_name": "contract.txt",
        },
    }

_TYPE_META = {
    "CICIDS2017":   {"icon": "", "desc": "Network traffic · 78 features · CSV"},
    "HIKARI2021":   {"icon": "", "desc": "Network traffic · 88 features · CSV"},
    "EVE_SURICATA": {"icon": "", "desc": "Suricata IDS logs · EVE JSON"},
}


def _list_dataset_files(dataset_type: str) -> list[str]:
    d = Path(DATASETS_DIR)
    if not d.exists():
        return []
    ext = _EXT_MAP.get(dataset_type, ".csv")
    return sorted(str(f) for f in d.glob(f"*{ext}") if f.is_file())


@st.dialog("Select Dataset File")
def _file_dialog(dataset_type: str):
    meta = _TYPE_META.get(dataset_type, {})
    st.markdown(f"### {dataset_type}")
    st.caption(meta.get("desc", ""))
    st.markdown("---")

    files = _list_dataset_files(dataset_type)
    ext = _EXT_MAP.get(dataset_type, ".csv")

    if files:
        selected_file = st.selectbox(
            f"Available `{ext}` files in `storage/datasets/`",
            options=files,
            format_func=lambda p: Path(p).name,
        )
    else:
        st.warning(
            f"No `{ext}` files found in `storage/datasets/`.\n\n"
            "Place your dataset file there and try again."
        )
        selected_file = None

    st.markdown("")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirm", type="primary", disabled=(selected_file is None), use_container_width=True):
            st.session_state["dataset_type"] = dataset_type
            st.session_state["dataset_path"] = selected_file
            st.session_state.pop("pending_dtype", None)
            for key in ("validation", "last_result", "polling_experiment_id"):
                st.session_state.pop(key, None)
            st.rerun()
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.pop("pending_dtype", None)
            st.rerun()


def render():
    st.title("Run Experiment")

    # Open file dialog if a type card was just clicked
    pending = st.session_state.get("pending_dtype")
    if pending:
        _file_dialog(pending)

    # === SECTION 1: Dataset Selection ===
    st.header("1. Dataset Selection")

    dataset_path = st.session_state.get("dataset_path")
    dataset_type = st.session_state.get("dataset_type", "")

    if dataset_path:
        # Show confirmed selection with a Change button
        c1, c2, c3 = st.columns([3, 4, 1])
        with c1:
            meta = _TYPE_META.get(dataset_type, {})
            st.markdown(f"**Type:** `{dataset_type}`")
        with c2:
            st.markdown(f"**File:** `{Path(dataset_path).name}`")
        with c3:
            if st.button("Change"):
                # Clear current selection — type cards re-appear
                for key in ("dataset_type", "dataset_path", "validation", "last_result", "polling_experiment_id"):
                    st.session_state.pop(key, None)
                st.rerun()
    else:
        # Show dataset type tiles — clicking one opens the file dialog
        st.markdown("Select a dataset type to get started:")
        cols = st.columns(len(get_available_datasets()))
        for col, dtype in zip(cols, get_available_datasets()):
            meta = _TYPE_META.get(dtype, {})
            with col:
                if st.button(
                    f"**{dtype}**\n\n{meta.get('desc', '')}",
                    use_container_width=True,
                    key=f"dtype_btn_{dtype}",
                ):
                    st.session_state["pending_dtype"] = dtype
                    st.rerun()
        return  # nothing else to render until a dataset is selected

    # Validate button
    if st.button("Validate Dataset", type="primary"):
        with st.spinner("Validating..."):
            st.session_state["validation"] = validate_dataset_for_ui(dataset_type, dataset_path)
            st.session_state.pop("last_result", None)
            st.session_state.pop("polling_experiment_id", None)

    if "validation" not in st.session_state:
        return

    v = st.session_state["validation"]
    if not v["success"]:
        st.error(f"{v['error']}")
        return

    st.success("Dataset is valid!")
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", f"{v['row_count']:,}")
    c2.metric("Columns", v["column_count"])
    # EVE-style datasets have no labels in the raw file — Phase 1 synthesizes
    # them. Show a placeholder instead of a meaningless count.
    if v["unique_labels"]:
        c3.metric("Classes", len(v["unique_labels"]))
    else:
        c3.metric("Classes", "pipeline-generated")
    if v.get("dataset_hash"):
        st.code(f"SHA-256: {v['dataset_hash']}", language=None)
    if v["unique_labels"]:
        st.markdown(f"**Labels:** {', '.join(str(lbl) for lbl in v['unique_labels'])}")

    # === SECTION 2: Pipeline Selection ===
    st.header("2. Pipeline Selection")
    pipelines = v.get("compatible_pipelines", {})
    if not pipelines:
        st.warning("No compatible pipelines.")
        return

    pipeline_opts = {pid: info["name"] for pid, info in pipelines.items()}
    selected = st.selectbox("Select Pipeline", list(pipeline_opts.keys()), format_func=lambda x: pipeline_opts[x])
    st.session_state["selected_pipeline"] = selected

    if selected:
        info = get_pipeline_info(selected)
        if info:
            with st.expander("Pipeline Detail (Read-Only)"):
                st.markdown(f"**Paper:** {info.get('paper')}")
                st.markdown(f"**Algorithm:** {info.get('algorithm')}")
                if info.get("preprocessing_steps"):
                    st.markdown("**Preprocessing:**")
                    for i, s in enumerate(info["preprocessing_steps"], 1):
                        st.markdown(f"  {i}. {s}")
                if info.get("feature_selection"):
                    st.markdown(f"**Feature Selection:** {info['feature_selection']}")
                if info.get("fixed_params"):
                    st.markdown("**Fixed Params:**")
                    st.json(info["fixed_params"])
                if info.get("runtime_warning"):
                    st.warning(info["runtime_warning"])
                st.info("All parameters locked per paper.")

        with st.expander("Pipeline Config Viewer (info.yaml · source · registry · contract)"):
            render_file_browser(
                _build_pipeline_config_files(selected),
                state_key="selected_file_pipeline_view",
            )

    # === SECTION 3: Execute ===
    st.header("3. Execute")

    if "polling_experiment_id" in st.session_state:
        _poll_experiment(st.session_state["polling_experiment_id"])
        return

    if st.button("Run Experiment", type="primary"):
        _run_with_status(dataset_type, dataset_path, selected)

    # === SECTION 4: Results (sync path) ===
    if "last_result" in st.session_state and st.session_state["last_result"].get("success"):
        _display_results(st.session_state["last_result"])


_EVE_PHASE_LINES = [
    "Phase 1 — Load & Label",
    "Phase 2 — Feature Engineering",
    "Phase 3 — Computed Features",
    "Phase 4 — Aggressive Cleaning",
    "Phase 7 — Correlation Analysis",
    "Phase 8 — Train/Test Split",
    "Phase 9 — Feature Selection (MI + RFE + PCA)",
    "Phase 10 — Model Training & Evaluation",
]


def _phase_checklist(icon: str) -> str:
    return "\n".join(f"- {icon} {p}" for p in _EVE_PHASE_LINES)


def _run_with_status(dataset_type: str, dataset_path: str, pipeline_id: str) -> None:
    """Dispatch the experiment with a live status block.

    Sync mode (USE_ASYNC=false): create_and_run_experiment blocks until the
    pipeline finishes, so the checklist sits on during the run and flips
    to when the call returns.

    Async mode: the call returns immediately after dispatching the Celery
    task. We transition to the polling view, which handles its own UI.
    """
    with st.status("Running pipeline...", expanded=True) as status_box:
        st.write("Initializing experiment...")
        st.write("Parsing and validating dataset...")
        st.write("")
        st.write("**Phases will execute in sequence:**")
        phase_placeholder = st.empty()
        phase_placeholder.markdown(_phase_checklist("[ ]"))
        st.write("")
        st.info("Full process log will appear in results after completion.")

        result = create_and_run_experiment(dataset_type, dataset_path, pipeline_id)

        if not result["success"]:
            status_box.update(label="Pipeline failed", state="error")
            st.error(f"{result['error']}")
            return

        if result.get("async_mode"):
            status_box.update(label="Dispatched to worker", state="running")
            st.session_state["polling_experiment_id"] = result["experiment_id"]
            st.info(f"Experiment queued: `{result['experiment_id'][:8]}...`")
            st.rerun()
            return

        # Sync path completed successfully
        phase_placeholder.markdown(_phase_checklist("[x]"))
        status_box.update(label="Pipeline complete!", state="complete")
        st.session_state["last_result"] = result
        st.rerun()


def _poll_experiment(experiment_id: str):
    """Poll experiment status until FINISHED or FAILED, then trigger rerun."""
    status_data = get_experiment_status(experiment_id)
    logger.info("[DIAG] poll tick status_data=%r", status_data)

    if status_data is None:
        st.error("Experiment not found.")
        st.session_state.pop("polling_experiment_id", None)
        return

    status = status_data["status"]

    if status in ("QUEUED", "RUNNING"):
        with st.status(f"Experiment {status.lower()}...", expanded=True):
            st.write(f"**Experiment ID:** `{experiment_id[:8]}...`")
            st.write(f"**Status:** {status}")
            if status == "QUEUED":
                st.write("Waiting for worker to pick up the task...")
            else:
                # Show coarse celery stage if the worker reported one;
                # fall back to the existing static text otherwise.
                celery_stage = status_data.get("celery_stage")
                if celery_stage:
                    st.write(f"**Current step:** {celery_stage}")
                else:
                    st.write("Pipeline is executing. This may take several minutes...")
            st.write("This page auto-refreshes every 5 seconds.")
        if st.button("Cancel Experiment", key=f"cancel_poll_{experiment_id}"):
            r = cancel_experiment(experiment_id)
            if r["success"]:
                st.session_state.pop("polling_experiment_id", None)
                st.warning("Experiment cancelled.")
            else:
                st.error(r["message"])
            st.rerun()

        # [DIAG] Diagnostic block — visible on every poll tick. Removable
        # in one grep pass (search for "[DIAG]"). No expander, no collapse.
        _render_diag_block(experiment_id, status_data)

        pipeline_id = status_data.get("pipeline_id", "")
        interval = _get_poll_interval(pipeline_id)
        st.caption(f"Refreshing in {interval}s...")
        time.sleep(interval)
        st.rerun()

    elif status == "FINISHED":
        st.session_state.pop("polling_experiment_id", None)
        full = get_full_experiment(experiment_id)
        if full:
            st.session_state["last_result"] = {
                "success": True,
                "experiment_id": experiment_id,
                "metrics": full.get("metrics", {}),
                "feature_names": (full.get("metadata") or {}).get("feature_names"),
                "label_mapping": (full.get("metadata") or {}).get("label_mapping"),
            }
        st.rerun()

    elif status == "FAILED":
        st.session_state.pop("polling_experiment_id", None)
        error_msg = status_data.get("error_message", "Unknown error")
        if error_msg == "Cancelled by user":
            st.warning("Experiment was cancelled.")
        else:
            st.error(f"Experiment failed: {error_msg}")


def _render_diag_block(experiment_id: str, status_data: dict) -> None:
    """[DIAG] Render the diagnostic block on the Run Experiment page.

    Shows everything needed to identify which link in the dispatch chain
    is broken: env-var, orchestrator branch, task_id, DB status, worker
    entered marker, raw AsyncResult.
    """
    import os
    st.markdown("---")
    st.write("### [DIAG] Diagnostic block")

    # 1. What the Streamlit process sees in its own environment, RIGHT NOW.
    env_use_async = os.environ.get("USE_ASYNC")

    # 2. What config.celery_config bound at import time (frozen for life of process).
    try:
        from config.celery_config import USE_ASYNC as cfg_use_async
    except Exception as e:  # defensive — should never fail
        cfg_use_async = f"<import error: {e}>"

    # 3. What the orchestrator stashed at dispatch.
    diag = get_diag(experiment_id)
    branch = diag.get("branch")
    task_id = diag.get("task_id")
    diag_use_async = diag.get("USE_ASYNC")

    # 4. Raw AsyncResult — proves whether the worker has actually entered
    # the task body. The `[DIAG] worker task entered` marker is written
    # as the literal first statement of run_pipeline_task.
    raw_state = None
    raw_info = None
    worker_entered = False
    if task_id:
        try:
            from workers.celery_worker import app as celery_app
            ar = celery_app.AsyncResult(task_id)
            raw_state = ar.state
            raw_info = ar.info
            if isinstance(raw_info, dict):
                stage = raw_info.get("stage", "")
                # Any PROGRESS state at all proves the worker ran the
                # first statement of the task body.
                if "worker task entered" in str(stage) or raw_state == "PROGRESS":
                    worker_entered = True
            elif raw_state in ("STARTED", "SUCCESS", "PROGRESS"):
                worker_entered = True
        except Exception as e:
            raw_info = f"<AsyncResult error: {e}>"

    st.write(f"**os.environ.get('USE_ASYNC')** (Streamlit process env): `{env_use_async!r}`")
    st.write(f"**config.celery_config.USE_ASYNC** (frozen at import): `{cfg_use_async!r}`")
    st.write(f"**Dispatched branch** (from orchestrator stash): `{branch!r}`")
    st.write(f"**Dispatch-time USE_ASYNC** (from orchestrator stash): `{diag_use_async!r}`")
    st.write(f"**task_id**: `{task_id!r}`")
    st.write(f"**DB status**: `{status_data.get('status')!r}`")
    st.write(f"**worker task started**: `{'yes' if worker_entered else 'no'}`")
    st.write(f"**raw AsyncResult.state**: `{raw_state!r}`")
    st.write("**raw AsyncResult.info**:")
    st.code(repr(raw_info), language="python")
    st.write("**status_data** (full dict from get_experiment_status):")
    st.json(status_data)


def _display_results(result: dict):
    """Render all metrics and charts."""
    st.header("4. Results")
    m = result["metrics"]
    eid = result["experiment_id"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accuracy", f"{m.get('accuracy', 0):.4f}")
    c2.metric("Precision", f"{m.get('precision', 0):.4f}")
    c3.metric("Recall", f"{m.get('recall', 0):.4f}")
    c4.metric("F1-Score", f"{m.get('f1_score', 0):.4f}")

    full = get_experiment_metrics(eid) or m

    # Confusion Matrix
    if "confusion_matrix" in m:
        st.subheader("Confusion Matrix")
        cm = np.array(m["confusion_matrix"])
        lm = result.get("label_mapping", {})
        labels = sorted(lm.keys(), key=lambda k: lm[k]) if lm else []
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(cm, cmap='Blues')
        plt.colorbar(im, ax=ax)
        if labels:
            ax.set_xticks(range(len(labels)))
            ax.set_yticks(range(len(labels)))
            ax.set_xticklabels([str(l) for l in labels], rotation=45, ha='right')
            ax.set_yticklabels([str(l) for l in labels])
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, format(cm[i, j], 'd'), ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "black")
        ax.set_ylabel("Actual")
        ax.set_xlabel("Predicted")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # ROC Curve
    if "roc_auc" in full:
        st.subheader("ROC Curve")
        col1, col2 = st.columns([3, 1])
        with col1:
            fig, ax = plt.subplots(figsize=(6, 5))
            if "roc_curve" in full:
                fpr = full["roc_curve"]["fpr"]
                tpr = full["roc_curve"]["tpr"]
                if isinstance(fpr, list):
                    ax.plot(fpr, tpr, label=f"AUC = {full['roc_auc']:.4f}", linewidth=2)
                elif isinstance(fpr, dict):
                    for cls in fpr:
                        ax.plot(fpr[cls], tpr[cls], label=cls, linewidth=1.5)
            elif "roc_curves_per_class" in full:
                for cls, curve in full["roc_curves_per_class"].items():
                    ax.plot(curve["fpr"], curve["tpr"], label=str(cls), linewidth=1.5)
            ax.plot([0, 1], [0, 1], 'k--', alpha=0.5)
            ax.set_xlabel("FPR")
            ax.set_ylabel("TPR")
            ax.legend(loc="lower right")
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)
        with col2:
            st.metric("ROC-AUC", f"{full['roc_auc']:.4f}")

    # Feature Importance
    if "feature_importance" in full and full["feature_importance"]:
        st.subheader("Feature Importance")
        fi = full["feature_importance"]
        fig, ax = plt.subplots(figsize=(8, max(3, len(fi) * 0.3)))
        ax.barh([x["feature"] for x in reversed(fi[:20])],
                [x["importance"] for x in reversed(fi[:20])], color="#2563EB")
        ax.set_xlabel("Importance")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # Per-Class Report
    if "classification_report" in full:
        st.subheader("Per-Class Report")
        report = full["classification_report"]
        class_rows = {k: v for k, v in report.items() if isinstance(v, dict)}
        if class_rows:
            df = pd.DataFrame(class_rows).T.round(4)
            if "support" in df.columns:
                df["support"] = df["support"].astype(int)
            st.dataframe(df, use_container_width=True)

    # Learning Curve
    if "learning_curve" in full and "error" not in full.get("learning_curve", {}):
        st.subheader("Learning Curve")
        lc = full["learning_curve"]
        tr_std = lc.get("train_scores_std", [0] * len(lc["train_sizes"]))
        val_mean = lc.get("val_scores_mean", [])
        val_std = lc.get("val_scores_std", [0] * len(lc["train_sizes"]))
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.fill_between(
            lc["train_sizes"],
            [m - s for m, s in zip(lc["train_scores_mean"], tr_std)],
            [m + s for m, s in zip(lc["train_scores_mean"], tr_std)],
            alpha=0.1, color="blue",
        )
        if val_mean:
            ax.fill_between(
                lc["train_sizes"],
                [mv - s for mv, s in zip(val_mean, val_std)],
                [mv + s for mv, s in zip(val_mean, val_std)],
                alpha=0.1, color="orange",
            )
        ax.plot(lc["train_sizes"], lc["train_scores_mean"], 'o-', color="blue", label="Train", linewidth=2)
        if val_mean:
            ax.plot(lc["train_sizes"], val_mean, 'o-', color="orange", label="Validation", linewidth=2)
        ax.set_xlabel("Training Size")
        ax.set_ylabel("F1 (Weighted)")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

    # Process Log (captured stdout from local_worker / Celery worker)
    if "process_log" in full and full["process_log"]:
        with st.expander("Process Log", expanded=False):
            st.code(full["process_log"], language=None)

    # PDF Download
    st.markdown("---")
    st.subheader("Download Report")
    try:
        from utils.report_generator import generate_report
        pipe_info = get_pipeline_info(st.session_state.get("selected_pipeline", "")) or {}
        exp_metadata = get_experiment_metadata(eid) or {}

        pdf_bytes = generate_report(
            experiment_id=eid,
            dataset_type=st.session_state.get("dataset_type", "Unknown"),
            dataset_path=st.session_state.get("dataset_path", "Unknown"),
            dataset_hash=exp_metadata.get("dataset_hash", full.get("dataset_hash", "N/A")),
            pipeline_id=st.session_state.get("selected_pipeline", "Unknown"),
            pipeline_info=pipe_info,
            metrics=full,
            metadata=exp_metadata,
            label_mapping=result.get("label_mapping"),
            feature_names=result.get("feature_names"),
        )
        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name=f"experiment_report_{eid[:8]}.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        st.warning(f"PDF generation failed: {e}")

    st.caption(f"Experiment ID: `{eid}`")
