"""
Run Experiment page — supports both sync and async execution.
"""
import logging
import time
from datetime import datetime, timezone
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
from ui.views._artifact_browser import render_file_browser, format_size
from streamlit_option_menu import option_menu
from contracts.dataset_schemas import get_schema

# Accent color shared with the sidebar (kept in sync intentionally).
_ACCENT = "#2563eb"

_EXT_MAP: dict[str, tuple[str, ...]] = {
    "EVE_SURICATA": (".json", ".jsonl", ".ndjson"),
}

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


# Default within-stage time estimates used only to animate the progress bar.
# These are cosmetic defaults; they do NOT influence pipeline computation, metrics,
# runtime recording, or anything persisted. They control only how fast the bar
# creeps within a single stage when no stage transition has occurred yet.
_PB_TRAINING_ESTIMATE_SEC = 600.0   # for stages whose text contains "Training" or "Computing learning curve"
_PB_DEFAULT_ESTIMATE_SEC = 30.0     # for short stages (Preprocessing, Scaling, Evaluating, ...)


def _compute_progress_state(status_data: dict, stages: list, session_state, experiment_id: str) -> dict:
    """Compute UI-only progress bar state.

    Strictly cosmetic. The returned fraction/elapsed/hint are for st.progress
    + caption only. They are NEVER written to metrics.json, metadata.json,
    experiments.db, the runtime field, or any artifact. Reproducibility is
    untouched; the underlying data (celery_stage, started_at) is read-only.

    Args:
        status_data: dict from get_experiment_status (DB row + optional celery_stage)
        stages:      ordered list of stage strings for this pipeline_id (from registry)
        session_state: Streamlit session state (used to track stage entry time)
        experiment_id: scoping key so multiple experiments don't collide in state

    Returns:
        dict with keys: fraction (0.0..1.0), label, elapsed_text, hint
    """
    status = status_data.get("status", "")
    celery_stage = status_data.get("celery_stage") or ""
    started_at = status_data.get("started_at")
    total = len(stages)

    # Real elapsed time from the DB-recorded started_at — honest display.
    # This is purely for the caption; it does NOT replace any runtime field.
    elapsed_text = ""
    try:
        if started_at:
            t0 = datetime.fromisoformat(started_at)
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            elapsed_sec = max(0.0, (datetime.now(timezone.utc) - t0).total_seconds())
            m, s = divmod(int(elapsed_sec), 60)
            h, m = divmod(m, 60)
            elapsed_text = f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"
    except Exception:
        pass

    # Terminal / pre-run states first
    if status == "QUEUED":
        return {"fraction": 0.0, "label": "Queued — waiting for worker", "elapsed_text": elapsed_text, "hint": ""}
    if status == "FAILED":
        return {"fraction": 0.0, "label": "Failed", "elapsed_text": elapsed_text, "hint": ""}
    if status == "FINISHED":
        return {"fraction": 1.0, "label": "Complete", "elapsed_text": elapsed_text, "hint": ""}

    # Worker-injected wrapper stages (celery_worker._safe_update_state calls)
    if celery_stage == "Executing pipeline...":
        return {"fraction": 0.02, "label": "Starting pipeline...", "elapsed_text": elapsed_text, "hint": ""}
    if celery_stage == "Saving results...":
        # Pin at 98% — bar must NOT hit 100% until status is truly FINISHED in DB
        return {"fraction": 0.98, "label": "Saving results...", "elapsed_text": elapsed_text, "hint": ""}

    if total == 0:
        return {"fraction": 0.05, "label": celery_stage or "Running...", "elapsed_text": elapsed_text, "hint": ""}

    try:
        idx = stages.index(celery_stage)
    except ValueError:
        # Unknown stage — never fabricate a position
        return {"fraction": 0.05, "label": celery_stage or "Running...", "elapsed_text": elapsed_text, "hint": ""}

    # Track stage entry time in session_state — cosmetic, never persisted.
    start_key = f"_pb_stage_start_{experiment_id}"
    prev_key = f"_pb_prev_stage_{experiment_id}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if session_state.get(prev_key) != celery_stage:
        session_state[start_key] = now_ts
        session_state[prev_key] = celery_stage
    in_stage_sec = max(0.0, now_ts - session_state.get(start_key, now_ts))

    base = idx / total
    is_training = ("Training" in celery_stage) or ("Computing learning curve" in celery_stage)
    estimate_sec = _PB_TRAINING_ESTIMATE_SEC if is_training else _PB_DEFAULT_ESTIMATE_SEC
    within = min(in_stage_sec / estimate_sec, 0.95)
    # Hard cap at 95% of the slot allocated to this stage. The bar advances to
    # the next stage's floor only when celery_stage actually transitions.
    fraction = min(base + within / total, (idx + 0.95) / total)

    label = f"Step {idx + 1}/{total}: {celery_stage}"
    hint = "training step — within-step % is estimated" if is_training and in_stage_sec > 3 else ""
    return {"fraction": fraction, "label": label, "elapsed_text": elapsed_text, "hint": hint}


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
    "HIKARI2021":   {"icon": "", "desc": "Network traffic · 88 features · CSV"},
    "EVE_SURICATA": {"icon": "", "desc": "Suricata IDS logs · EVE JSON"},
}


def _list_dataset_files(dataset_type: str) -> list[str]:
    d = Path(DATASETS_DIR)
    if not d.exists():
        return []
    exts = _EXT_MAP.get(dataset_type, (".csv",))
    if isinstance(exts, str):  # legacy/defensive
        exts = (exts,)
    found: set[str] = set()
    for ext in exts:
        for f in d.glob(f"*{ext}"):
            if f.is_file():
                found.add(str(f))
    return sorted(found)


def _type_icon(dtype: str) -> str:
    """Pick a Bootstrap icon for the type tab from the schema's file format.
    Schema-derived to stay consistent if a JSON-format type is added later."""
    s = get_schema(dtype) or {}
    if s.get("file_format") in ("json", "json_or_csv") or s.get("expected_top_level_keys"):
        return "braces"
    return "table"


def _render_type_characteristics(dtype: str) -> None:
    """Show type characteristics from contracts/dataset_schemas.py.
    Uses _TYPE_META only for the human-readable one-liner; everything else
    is read from the schema so this stays accurate if schemas change."""
    schema = get_schema(dtype) or {}
    meta = _TYPE_META.get(dtype, {})

    fmt_raw = schema.get("file_format")
    if fmt_raw == "json_or_csv":
        fmt = "NDJSON / CSV"
    elif fmt_raw == "json":
        fmt = "NDJSON"
    else:
        fmt = "CSV"

    label_col = schema.get("label_column", "(tidak ada)")
    expected_cols = schema.get("expected_columns") or []
    n_cols = len(expected_cols)
    n_cols_text = str(n_cols) if n_cols > 0 else "(diturunkan oleh pipeline)"

    c1, c2, c3 = st.columns(3)
    c1.metric("Format", fmt)
    c2.metric("Label column", label_col)
    c3.metric("Feature columns", n_cols_text)

    if meta.get("desc"):
        st.caption(meta["desc"])

    top_keys = schema.get("expected_top_level_keys") or []
    if top_keys:
        st.caption("Kunci NDJSON yang diharapkan: " + ", ".join(f"`{k}`" for k in top_keys))


def _render_file_picker(dtype: str) -> None:
    """List files of this type from storage/datasets/, let the user pick one,
    and confirm via a Use button that hands off to the existing flow.

    Mapping mechanism: file extension only, via _EXT_MAP — identical to the
    pre-existing _list_dataset_files behaviour. CSV files appear under
    HIKARI2021; NDJSON / JSON files appear under EVE_SURICATA. Platform does
    not discriminate by content at list time; schema validation runs later on
    the chosen file.
    """
    exts = _EXT_MAP.get(dtype, (".csv",))
    if isinstance(exts, str):
        exts = (exts,)
    ext_display = ", ".join(f"*{e}" for e in exts)
    try:
        files = _list_dataset_files(dtype)
    except Exception as e:
        st.error(f"Gagal memindai folder `storage/datasets/`: {e}")
        return

    if not files:
        st.info(
            f"Belum ada berkas dataset bertype **{dtype}** (`{ext_display}`) di "
            f"`storage/datasets/`. Tambahkan berkas ke folder tersebut untuk memulai."
        )
        return

    # Build labels with size; skip any file whose stat fails so a single bad
    # file does not break the whole picker.
    options: list[str] = []
    labels: dict[str, str] = {}
    for f in files:
        try:
            size = format_size(Path(f).stat().st_size)
        except Exception:
            size = "ukuran tidak diketahui"
        options.append(f)
        labels[f] = f"{Path(f).name}  ({size})"

    radio_key = f"selected_dataset_file__{dtype}"
    # Default the radio to the previously-chosen file for this type, if any.
    default_idx = 0
    prior = st.session_state.get(radio_key)
    if prior in options:
        default_idx = options.index(prior)

    chosen = st.radio(
        f"Berkas yang cocok di `storage/datasets/` (filter: `{ext_display}`):",
        options=options,
        format_func=lambda p: labels[p],
        index=default_idx,
        key=radio_key,
    )

    if st.button("Use this dataset", type="primary", use_container_width=False):
        st.session_state["dataset_type"] = dtype
        st.session_state["dataset_path"] = chosen
        # Clear downstream state so a stale validation/result does not bleed
        # through after the user picks a fresh file.
        for key in ("validation", "last_result", "polling_experiment_id"):
            st.session_state.pop(key, None)
        st.rerun()


def _pipeline_dataset_confirmation(dataset_type: str) -> str | None:
    """Dynamic, dataset_type-derived note about the input the selected pipeline
    expects. Informational only — it does NOT replace the dataset validation
    performed elsewhere. ``dataset_type`` comes from the selected pipeline's
    registry entry and the label column from the schema, so there is no brittle
    pipeline->dataset hardcoding here."""
    schema = get_schema(dataset_type) or {}
    label_col = schema.get("label_column") or "label"
    if dataset_type == "HIKARI2021":
        return (
            f"**Pipeline ini menerima dataset:** HIKARI2021 (varian ALLFLOWMETER) berformat "
            f"**CSV**, dengan kolom label `{label_col}` (0 = benign, 1 = malicious) dan "
            f"puluhan kolom fitur numerik berbasis *flow*."
        )
    if dataset_type == "EVE_SURICATA":
        return (
            f"**Pipeline ini menerima dataset:** EVE Suricata berformat **NDJSON** (satu objek "
            f"JSON per baris). Pipeline cbr memfokuskan analisis pada **trafik TLS** dan "
            f"menurunkan label dari **alert Suricata** (disempurnakan secara konservatif); "
            f"berkas mentah tidak perlu memiliki kolom `{label_col}`/label eksplisit."
        )
    # Unknown/future dataset type: stay honest and generic, still derived.
    return f"**Pipeline ini menerima dataset bertipe:** {dataset_type} (kolom label `{label_col}`)."


def _all_dataset_options() -> list[tuple[str, str]]:
    """[(path, dataset_type)] for every dataset file in storage/datasets/.

    dataset_type is derived by the SAME extension mapping the former type tabs
    used (``_list_dataset_files`` per registered type), so the dataset_path and
    dataset_type that flow to execution stay identical to before.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for dtype in get_available_datasets():
        for p in _list_dataset_files(dtype):
            if p not in seen:
                out.append((p, dtype))
                seen.add(p)
    return sorted(out, key=lambda t: Path(t[0]).name.lower())


def _dataset_preview(path: str, dataset_type: str, n: int = 5):
    """Memory-safe preview: read ONLY the first ``n`` rows. Never loads the whole
    file (datasets can be ~568 MB → OOM on a fragile host). Returns a DataFrame
    or None. Display-only — not used for validation, parsing, or execution."""
    import json as _json

    ext = Path(path).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, nrows=n)
    # NDJSON / JSON-lines: stream only the first n valid objects.
    records: list[dict] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                records.append(obj)
            if len(records) >= n:
                break
    if not records:
        return None
    return pd.json_normalize(records, max_level=1)


def render():
    st.title("Run Experiment")

    # ── Dataset Selection ──────────────────────────────────────────────
    st.header("Dataset Selection")

    # Single dropdown over every dataset file in storage/datasets/. Each option
    # carries its dataset_type (derived exactly as the former type tabs did), so
    # the dataset_path + dataset_type flowing to execution are unchanged.
    _ds_options = _all_dataset_options()
    if not _ds_options:
        st.info(
            "Belum ada berkas dataset di `storage/datasets/`. Tambahkan berkas CSV "
            "(HIKARI2021) atau NDJSON (EVE Suricata) untuk memulai."
        )
        return

    _path_to_type = {p: t for p, t in _ds_options}
    _paths = [p for p, _ in _ds_options]

    def _ds_label(p: str) -> str:
        try:
            size = format_size(Path(p).stat().st_size)
        except Exception:
            size = "ukuran tidak diketahui"
        return f"{Path(p).name}  ·  {_path_to_type.get(p, '?')}  ({size})"

    dataset_path = st.selectbox(
        "Pilih dataset", _paths, index=None,
        placeholder="Pilih berkas dataset…",
        format_func=_ds_label, key="dataset_select",
    )

    if not dataset_path:
        st.caption(
            "Pilih satu berkas dataset untuk melihat preview, hasil validasi, dan "
            "pipeline yang kompatibel."
        )
        return

    dataset_type = _path_to_type.get(dataset_path, "")
    # Persist for downstream readers (PDF/report read session dataset_path/type).
    st.session_state["dataset_path"] = dataset_path
    st.session_state["dataset_type"] = dataset_type

    # Validate once per selected path — identical logic to the former "Validate
    # Dataset" button (validate_dataset_for_ui), guarded so the parse/hash runs
    # once per selection (not every rerun). A new selection re-validates and
    # drops stale result/polling/pipeline state.
    if st.session_state.get("_validated_path") != dataset_path:
        with st.spinner("Memvalidasi dataset…"):
            st.session_state["validation"] = validate_dataset_for_ui(dataset_type, dataset_path)
        st.session_state["_validated_path"] = dataset_path
        for _k in ("last_result", "polling_experiment_id", "pipeline_select", "selected_pipeline"):
            st.session_state.pop(_k, None)

    v = st.session_state.get("validation") or {}

    # Detail dataset — memory-safe preview (first rows only) + existing validation info.
    with st.expander("Detail dataset (preview & validasi)", expanded=True):
        st.markdown("**Preview (beberapa baris pertama):**")
        try:
            _preview = _dataset_preview(dataset_path, dataset_type, n=5)
            if _preview is not None and not _preview.empty:
                st.dataframe(_preview, use_container_width=True)
            else:
                st.caption("Preview tidak tersedia untuk berkas ini.")
        except Exception as _e:
            st.caption(f"Preview tidak tersedia: {_e}")

        st.markdown("---")
        if not v.get("success"):
            st.error(v.get("error", "Validasi dataset gagal."))
        else:
            st.success("Dataset is valid!")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Type", dataset_type)
            c2.metric("Rows", f"{v['row_count']:,}" if isinstance(v.get("row_count"), int) else "-")
            c3.metric("Columns", v.get("column_count", "-"))
            # EVE-style datasets have no labels in the raw file — Phase 1
            # synthesizes them. Show a placeholder instead of a meaningless count.
            if v.get("unique_labels"):
                c4.metric("Classes", len(v["unique_labels"]))
            else:
                c4.metric("Classes", "pipeline-generated")
            if v.get("dataset_hash"):
                st.code(f"SHA-256: {v['dataset_hash']}", language=None)
            if v.get("unique_labels"):
                st.markdown(f"**Labels:** {', '.join(str(lbl) for lbl in v['unique_labels'])}")

    if not v.get("success"):
        return

    # ── Pipeline Selection ─────────────────────────────────────────────
    st.header("Pipeline Selection")
    pipelines = v.get("compatible_pipelines", {})
    if not pipelines:
        st.warning("Tidak ada pipeline yang kompatibel untuk dataset ini.")
        return

    pipeline_opts = {pid: info["name"] for pid, info in pipelines.items()}
    selected = st.selectbox(
        "Pilih pipeline", list(pipeline_opts.keys()), index=None,
        placeholder="Pilih pipeline…",
        format_func=lambda x: pipeline_opts[x], key="pipeline_select",
    )
    st.session_state["selected_pipeline"] = selected

    if selected:
        # Dynamic, per-pipeline dataset confirmation — a SEPARATE element from
        # the read-only Pipeline Detail / Config Viewer below. Derived from the
        # selected pipeline's dataset_type in the registry; informational only,
        # it does NOT replace the dataset validation already performed above.
        _pdtype = pipelines.get(selected, {}).get("dataset_type")
        _confirm = _pipeline_dataset_confirmation(_pdtype) if _pdtype else None
        if _confirm:
            st.info(_confirm)

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

    # ── Execute (conditional — only after a pipeline is selected) ───────
    # Async polling view takes over while an experiment is in flight.
    if "polling_experiment_id" in st.session_state:
        _poll_experiment(st.session_state["polling_experiment_id"])
        return

    if selected:
        st.header("Execute")
        if st.button("Run Experiment", type="primary"):
            _run_with_status(dataset_type, dataset_path, selected)

    # Results (sync path)
    if "last_result" in st.session_state and st.session_state["last_result"].get("success"):
        _display_results(st.session_state["last_result"])


# Tahapan besar pipeline EVE cbr (14 fase, dikelompokkan agar jelas & jujur).
# Hanya ditampilkan untuk pipeline EVE (eve_cbr.*) — bukan HIKARI.
_EVE_PHASE_LINES = [
    "Memisahkan trafik TLS dari dataset EVE",
    "Profiling & analisis probing",
    "Refinement label konservatif (cap konversi baris)",
    "Konstruksi & pembersihan fitur",
    "Screening korelasi & leakage",
    "Feature selection (MI / RFE / PCA, train-only)",
    "Pelatihan & evaluasi dual-holdout (natural + balanced)",
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
    # The EVE phase checklist describes the cbr (EVE) pipeline stages, so show
    # it only for EVE pipelines. HIKARI pipelines get a generic line instead —
    # never the EVE phase names.
    is_eve = (dataset_type == "EVE_SURICATA") or (pipeline_id or "").startswith("eve_cbr")
    with st.status("Running pipeline...", expanded=True) as status_box:
        st.write("Initializing experiment...")
        st.write("Parsing and validating dataset...")
        st.write("")
        phase_placeholder = None
        if is_eve:
            st.write("**Tahapan pipeline cbr (EVE) akan dijalankan berurutan:**")
            phase_placeholder = st.empty()
            phase_placeholder.markdown(_phase_checklist("[ ]"))
            st.write("")
        else:
            st.write("Pipeline dijalankan; metrik dan artefak muncul setelah selesai.")
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
        if phase_placeholder is not None:
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
        # Progress bar (UI-cosmetic only; nothing computed here is persisted).
        # Stages list comes from config.pipeline_registry — UI may import config/.
        from config.pipeline_registry import get_pipeline as _get_pipeline_entry
        _reg_entry = _get_pipeline_entry(status_data.get("pipeline_id", "")) or {}
        _stages_list = _reg_entry.get("stages", []) or []
        _pb = _compute_progress_state(status_data, _stages_list, st.session_state, experiment_id)
        st.progress(_pb["fraction"])
        st.markdown(f"**{_pb['label']}**")
        _bottom_parts = []
        if _pb["elapsed_text"]:
            _bottom_parts.append(f"Elapsed: {_pb['elapsed_text']}")
        if _pb["hint"]:
            _bottom_parts.append(_pb["hint"])
        if _bottom_parts:
            st.caption(" — ".join(_bottom_parts))

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

    Wrapped inside an expander (default closed) so the long dict dump does
    not dominate the main view during polling. Information is preserved
    in full; only the visual default changed.
    """
    import os

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

    st.markdown("---")
    with st.expander("Detail diagnostik", expanded=False):
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

    # Confusion Matrix + Feature Importance side by side to save vertical
    # space and prevent the feature-importance chart from sprawling.
    has_cm = "confusion_matrix" in m
    has_fi = bool(full.get("feature_importance"))
    if has_cm or has_fi:
        st.subheader("Confusion Matrix & Feature Importance")
        col_cm, col_fi = st.columns(2)
        if has_cm:
            with col_cm:
                cm = np.array(m["confusion_matrix"])
                lm = result.get("label_mapping", {})
                labels = sorted(lm.keys(), key=lambda k: lm[k]) if lm else []
                fig, ax = plt.subplots(figsize=(5, 4))
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
        if has_fi:
            with col_fi:
                fi_full = full["feature_importance"]
                n_total = len(fi_full)
                top_n = 20
                fi = fi_full[:top_n]
                fig, ax = plt.subplots(figsize=(5, max(4, len(fi) * 0.3)))
                ax.barh(
                    [x["feature"] for x in reversed(fi)],
                    [x["importance"] for x in reversed(fi)],
                    color="#2563EB",
                )
                ax.set_xlabel("Importance")
                title = f"Top {len(fi)} Feature Importance"
                if n_total > len(fi):
                    title += f" (of {n_total} total)"
                ax.set_title(title, fontsize=11)
                fig.tight_layout()
                st.pyplot(fig)
                plt.close(fig)
        elif has_cm:
            with col_fi:
                st.caption("Feature importance tidak tersedia untuk algoritma ini.")

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

    # (Feature Importance moved into the Confusion Matrix block above to
    # share a two-column row; this avoids duplicate rendering here.)

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
