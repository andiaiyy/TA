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

from orchestrator.experiment_service import (
    validate_dataset_for_ui, create_and_run_experiment, get_experiment_status,
    cancel_experiment,
    get_diag,  # [DIAG] dispatch diagnostic accessor
)
from orchestrator.execution_service import get_pipeline_info
from orchestrator.validation_service import get_available_datasets
from orchestrator.result_service import get_experiment_metrics, get_full_experiment, get_experiment_metadata
from config.settings import DATASETS_DIR
from config.research_attribution import get_research_display_name, get_research_attribution
from ui.views._artifact_browser import render_file_browser, format_size
from ui.components.result_views import normalize_result_payload, render_results
from streamlit_option_menu import option_menu
from contracts.dataset_schemas import get_schema
# Helper murni untuk penyajian diagnosa (aturan format per dataset_type +
# pembersih nilai mentah). `diagnose_all` sendiri tetap diimpor secara lazy di
# dalam fungsi ber-cache.
from orchestrator.dataset_diagnostics import required_format, sanitize_display_value

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
    payload = status_data.get("celery_progress") or {}
    started_at = status_data.get("started_at")
    total = len(stages)

    def _base(fraction, label, *, stage_index=None, hint="", stage_percent=0):
        return {
            "fraction": fraction, "label": label, "elapsed_text": elapsed_text,
            "hint": hint, "stage_index": stage_index, "stage_total": total,
            "stage_percent": stage_percent,
        }

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
        return _base(0.0, "Queued — waiting for worker", stage_index=0)
    if status == "FAILED":
        return _base(0.0, "Failed", stage_index=None)
    if status == "FINISHED":
        return _base(1.0, "Complete", stage_index=total)

    # Worker-injected wrapper stages (celery_worker._safe_update_state calls)
    if celery_stage == "Executing pipeline...":
        return _base(0.02, "Starting pipeline...", stage_index=0)
    if celery_stage == "Saving results...":
        # Pin at 98% — bar must NOT hit 100% until status is truly FINISHED in DB
        return _base(0.98, "Saving results...", stage_index=total)

    if total == 0:
        return _base(0.05, celery_stage or "Running...", stage_index=None)

    # Resolve the current 0-based stage index: prefer the granular payload's
    # stage_index (authoritative), fall back to matching the stage string.
    idx = None
    p_idx = payload.get("stage_index")
    if isinstance(p_idx, int) and 1 <= p_idx <= total:
        idx = p_idx - 1
    else:
        try:
            idx = stages.index(celery_stage)
        except ValueError:
            idx = None
    if idx is None:
        # Unknown stage — never fabricate a position
        return _base(0.05, celery_stage or "Running...", stage_index=None)

    stage_name = payload.get("stage_name") or celery_stage or (stages[idx] if idx < total else "")

    # Track stage entry time in session_state — cosmetic, never persisted.
    start_key = f"_pb_stage_start_{experiment_id}"
    prev_key = f"_pb_prev_stage_{experiment_id}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if session_state.get(prev_key) != stage_name:
        session_state[start_key] = now_ts
        session_state[prev_key] = stage_name
    in_stage_sec = max(0.0, now_ts - session_state.get(start_key, now_ts))

    # Global bar floor: use the worker's monotonic overall_percent when present,
    # else the completed-stage floor idx/total. Within-stage time creep animates
    # on top, capped just below the next stage so the bar never jumps ahead.
    p_overall = payload.get("overall_percent")
    base = (p_overall / 100.0) if isinstance(p_overall, (int, float)) else (idx / total)
    base = max(base, idx / total)
    is_training = ("Training" in stage_name) or ("Computing learning curve" in stage_name) or ("Modeling" in stage_name)
    estimate_sec = _PB_TRAINING_ESTIMATE_SEC if is_training else _PB_DEFAULT_ESTIMATE_SEC
    within = min(in_stage_sec / estimate_sec, 0.95)
    fraction = min(base + within / total, (idx + 0.95) / total)

    label = f"Fase {idx + 1}/{total} — {stage_name}"
    hint = "estimasi progres dalam-fase (berbasis waktu)" if is_training and in_stage_sec > 3 else ""
    return _base(fraction, label, stage_index=idx + 1, hint=hint,
                 stage_percent=int(round(within * 100)))


_STAGE_PALETTE = {
    # state: (background, foreground, icon, label)
    "done":    ("#dcfce7", "#166534", "✅", "selesai"),
    "running": ("#dbeafe", "#1e40af", "▶️", "berjalan"),
    "waiting": ("#f1f5f9", "#64748b", "⏳", "menunggu"),
}


def _render_stage_columns(stages: list, view: list, running_percent: int = 0) -> None:
    """Jenkins-style HORIZONTAL stage view: all stages laid out in a SINGLE row
    inside a flex container that scrolls horizontally when they don't all fit.
    Each card shows number + name, colored status (green=done, blue=running with
    a small progress bar + %, grey=waiting), and duration. Display only — never
    persisted.

    ``view`` is the list from workers.progress_util.build_stage_view (one entry
    per stage, in order). ``running_percent`` is the in-stage % for the running
    card (time-estimated by the UI). Stage names are HTML-escaped.
    """
    import html
    from workers.progress_util import format_duration

    if not stages:
        return
    n = len(stages)
    rp = int(min(max(running_percent, 0), 100))
    # Fit-vs-scroll: when the pipeline has few stages let the cards stretch to
    # fill the row; when many, fix each card's width and scroll horizontally so
    # long stage titles remain readable (Jenkins Stage View pattern).
    grow_shrink = "1 1 160px" if n <= 6 else "0 0 180px"

    cards: list[str] = []
    for i in range(n):
        name = stages[i]
        v = view[i] if i < len(view) else {"state": "waiting", "duration_sec": None}
        state = v.get("state", "waiting")
        bg, fg, icon, label = _STAGE_PALETTE.get(state, _STAGE_PALETTE["waiting"])
        dur = format_duration(v.get("duration_sec"))
        safe_name = html.escape(str(name))
        safe_dur = html.escape(str(dur))
        title_attr = html.escape(f"{i + 1}. {name}", quote=True)

        if state == "running":
            status_line = (
                f"<div style='font-size:0.70rem; margin-top:6px;'>{icon} {label} {rp}%</div>"
                f"<div style='height:4px; margin-top:4px; border-radius:2px; "
                f"background:{fg}22; overflow:hidden;'>"
                f"<div style='width:{rp}%; height:100%; background:{fg};'></div>"
                f"</div>"
            )
        else:
            status_line = (
                f"<div style='font-size:0.70rem; margin-top:6px;'>{icon} {label}</div>"
            )

        cards.append(
            f"<div style='flex:{grow_shrink}; min-width:160px; "
            f"border-radius:8px; overflow:hidden; border:1px solid {fg}33; "
            f"background:{bg}; color:{fg};'>"
            f"<div style='padding:8px 8px 10px 8px; min-height:92px; "
            f"display:flex; flex-direction:column;'>"
            f"<div title='{title_attr}' style='font-size:0.72rem; font-weight:600; "
            f"line-height:1.15; min-height:2.3em;'>{i + 1}. {safe_name}</div>"
            f"{status_line}"
            f"<div style='font-size:0.70rem; opacity:0.85; margin-top:auto; "
            f"padding-top:4px;'>⏱ {safe_dur}</div>"
            f"</div></div>"
        )

    st.markdown(
        "<div style='display:flex; flex-wrap:nowrap; gap:8px; overflow-x:auto; "
        "padding:2px 2px 8px 2px; margin-bottom:6px;'>"
        + "".join(cards)
        + "</div>",
        unsafe_allow_html=True,
    )


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


def _dataset_info_lines(dataset_type: str) -> list[str]:
    """Structured dataset facts shown inside the 'Tentang Research Pipeline'
    expander (previously a separate blue st.info box, now consolidated here).

    Derived from the schema (label column, file format) plus a single curated
    description per dataset_type — kept in ONE place so the information does not
    get scattered across the UI. ``dataset_type`` comes from the selected
    pipeline's registry entry, so there is no brittle pipeline->dataset
    hardcoding. Informational only; it does NOT replace dataset validation and
    does not touch any computation. Returns a list of markdown bullet strings."""
    schema = get_schema(dataset_type) or {}
    label_col = schema.get("label_column") or "label"
    if dataset_type == "HIKARI2021":
        return [
            "**Format berkas:** CSV (varian ALLFLOWMETER)",
            f"**Kolom label:** `{label_col}` — 0 = benign, 1 = malicious",
            "**Sifat fitur:** puluhan kolom fitur numerik berbasis *flow* "
            "(statistik payload, hitungan header/paket, atribut koneksi).",
        ]
    if dataset_type == "EVE_SURICATA":
        return [
            "**Format berkas:** NDJSON (satu objek JSON per baris)",
            f"**Kolom label:** `{label_col}` — diturunkan dari **alert Suricata** "
            "(disempurnakan secara konservatif); berkas mentah tidak perlu kolom "
            "label eksplisit.",
            "**Sifat fitur:** fitur aliran (*flow*) hasil pipeline cbr 14 fase; "
            "analisis difokuskan pada **trafik TLS**.",
        ]
    # Unknown/future dataset type: stay honest and generic, still derived.
    return [f"**Tipe dataset:** {dataset_type} (kolom label `{label_col}`)."]


# ── "Persyaratan Dataset" (read-only sub-bagian di dalam expander) ─────────
# SATU dict terpusat untuk kalimat yang TIDAK bisa diturunkan dari sumber
# terstruktur (satuan baris, sifat fitur, nilai ILUSTRATIF pada contoh). Semua
# yang bisa diturunkan dibaca langsung dari sumbernya saat render:
#   - ekstensi berkas          -> _EXT_MAP (mekanisme yang dipakai file picker)
#   - kolom label & daftar kolom -> contracts/dataset_schemas.py (get_schema)
#   - kolom non-fitur HIKARI   -> pipelines/hikari2021/_common.py (_DROP_COLS)
#   - nama kelas 0/1           -> _LABEL_NAMES / _LABEL_MAPPING milik pipeline
#   - kolom target EVE final   -> pipelines/eve_cbr/cbr_adapter.py
# Jadi NAMA KOLOM pada contoh struktur tidak pernah dikarang. Panel ini murni
# informatif: tidak ada input, tidak ada validasi berkas, tidak ada efek ke
# komputasi/metrik.
_DATASET_REQUIREMENTS: dict[str, dict] = {
    "HIKARI2021": {
        "row_unit": "satu baris per **flow** jaringan",
        "feature_nature": (
            "Kolom **numerik berbasis flow** — durasi, hitungan paket/header, "
            "statistik payload & inter-arrival time."
        ),
        # Kolom yang ditampilkan pada contoh struktur. NAMA kolom di sini wajib
        # ada di expected_columns skema — divalidasi saat render, dan yang tidak
        # ditemukan otomatis dibuang (fallback: kolom fitur pertama dari skema).
        # Hanya NILAI-nya yang ilustratif.
        "sample_columns": {"flow_duration": "0.523", "fwd_pkts_tot": "142",
                           "bwd_pkts_tot": "98"},
        # Ringkasan satu baris untuk kotak uji kecocokan (sifat fitur saja —
        # format & kolom label disusun dari _EXT_MAP + skema saat render).
        "summary_line": "fitur numerik berbasis flow",
    },
    "EVE_SURICATA": {
        "row_unit": "satu objek JSON per baris (satu **event**)",
        "feature_nature": (
            "Field mentah **Suricata EVE log**. Pipeline memfilter **event TLS** "
            "lalu merekayasa & menyeleksi fiturnya sendiri — berkas tidak perlu "
            "berisi kolom fitur siap pakai."
        ),
        # Nilai ilustratif; nama field-nya diambil dari expected_top_level_keys.
        "sample_values": {
            "timestamp": "2021-01-05T10:12:44.123456+0700",
            "flow_id": 1234567890123456,
            "event_type": "tls",
            "src_ip": "10.0.0.5",
            "src_port": 51514,
            "dest_ip": "93.184.216.34",
            "dest_port": 443,
            "proto": "TCP",
            "app_proto": "tls",
        },
        "summary_line": "field EVE mentah, fokus event TLS (label dari alert)",
        "class_hint": "dua kelas setelah pelabelan dari alert",
    },
}


def _dataset_extensions(dataset_type: str) -> tuple[str, ...]:
    """Ekstensi berkas yang diterima untuk sebuah dataset_type — dibaca dari
    _EXT_MAP, mekanisme yang SAMA dengan file picker, jadi panel persyaratan
    tidak pernah berbeda dari daftar berkas yang benar-benar tampil."""
    exts = _EXT_MAP.get(dataset_type, (".csv",))
    return (exts,) if isinstance(exts, str) else tuple(exts)


def _hikari_column_facts() -> tuple[list[str], list[str], list[str]]:
    """(kolom_fitur, kolom_non_fitur, nama_kelas) untuk HIKARI2021.

    Seluruhnya dibaca dari sumber nyata: ``expected_columns`` pada skema,
    ``_DROP_COLS`` dan ``_LABEL_NAMES`` milik preprocessing HIKARI. Defensif —
    bila impor pipeline gagal, kembalikan daftar kosong agar UI tidak pernah
    crash (panel hanya menyembunyikan bagian yang tidak bisa diturunkan)."""
    schema = get_schema("HIKARI2021") or {}
    cols = list(schema.get("expected_columns") or [])
    label_col = schema.get("label_column") or "Label"
    try:
        from pipelines.hikari2021._common import _DROP_COLS, _LABEL_NAMES
        drops, names = list(_DROP_COLS), list(_LABEL_NAMES)
    except Exception:  # pragma: no cover - defensive
        logger.debug("HIKARI _common tidak dapat diimpor untuk panel persyaratan",
                     exc_info=True)
        drops, names = [], []
    features = [c for c in cols if c not in drops and c != label_col]
    return features, drops, names


def _eve_label_facts() -> tuple[str, list[str]]:
    """(kolom target final, nama_kelas) untuk EVE — dibaca dari cbr_adapter.
    Defensif: ("", []) bila modul tidak dapat diimpor."""
    try:
        from pipelines.eve_cbr.cbr_adapter import _TARGET_COLUMN, _LABEL_MAPPING
        return str(_TARGET_COLUMN), [str(_LABEL_MAPPING.get(0, "")),
                                     str(_LABEL_MAPPING.get(1, ""))]
    except Exception:  # pragma: no cover - defensive
        logger.debug("cbr_adapter tidak dapat diimpor untuk panel persyaratan",
                     exc_info=True)
        return "", []


def _render_dataset_requirements(dataset_type: str) -> None:
    """Sub-bagian read-only "Persyaratan Dataset" di dalam expander "Tentang
    Research Pipeline". Lima elemen: format berkas, kolom label, sifat fitur,
    contoh struktur, dan checklist kecocokan.

    Isinya mengikuti ``dataset_type`` (BUKAN algoritma) — RF/DT/KNN dst. berbagi
    persyaratan dataset yang sama. Murni tampilan: tidak memvalidasi berkas apa
    pun dan tidak menyentuh jalur komputasi."""
    import json as _json

    schema = get_schema(dataset_type) or {}
    req = _DATASET_REQUIREMENTS.get(dataset_type, {})
    label_col = schema.get("label_column") or "label"
    exts = _dataset_extensions(dataset_type)
    ext_text = " / ".join(f"`{e}`" for e in exts)

    st.markdown("---")
    st.markdown("**Persyaratan Dataset**")
    st.caption(
        "Cocokkan dataset Anda dengan poin-poin di bawah sebelum menjalankan "
        "eksperimen. Informasi ini mengikuti *research pipeline* (tipe dataset) "
        "yang dipilih, bukan algoritmanya."
    )

    if not req:
        # Tipe dataset baru/tak dikenal: tetap jujur, tetap diturunkan.
        st.markdown(
            f"- **Format berkas:** {ext_text}\n"
            f"- **Kolom label (target):** `{label_col}`"
        )
        return

    # ── 1-3. Format, kolom label, sifat fitur (tabel ringkas) ─────────────
    if dataset_type == "HIKARI2021":
        features, drops, class_names = _hikari_column_facts()
        benign = class_names[0] if len(class_names) > 1 else "benign"
        malicious = class_names[1] if len(class_names) > 1 else "malicious"
        label_text = f"`{label_col}` — `0` = {benign}, `1` = {malicious}"
        feature_text = req["feature_nature"]
        if features:
            feature_text += f" Skema mencatat **{len(features)} kolom fitur**."
    else:
        target_final, class_names = _eve_label_facts()
        benign = class_names[0] if len(class_names) > 1 else "benign"
        attack = class_names[1] if len(class_names) > 1 else "attack"
        label_text = (
            f"`{label_col}` — dibentuk **oleh pipeline dari alert Suricata** "
            f"(`event_type` = `alert` atau alert valid)"
        )
        if target_final:
            label_text += f", lalu disempurnakan menjadi `{target_final}`"
        label_text += (
            f"; `0` = {benign}, `1` = {attack}. Bukan anotasi *ground-truth* "
            f"eksternal — berkas mentah tidak perlu kolom label."
        )
        features, drops = [], []
        feature_text = req["feature_nature"]

    st.markdown(
        "| Aspek | Persyaratan |\n"
        "| --- | --- |\n"
        f"| **Format berkas** | {ext_text} — {req['row_unit']} |\n"
        f"| **Kolom label (target)** | {label_text} |\n"
        f"| **Fitur yang diharapkan** | {feature_text} |"
    )

    if dataset_type == "HIKARI2021" and drops:
        st.caption(
            "Kolom non-fitur berikut dibuang otomatis oleh preprocessing "
            "(boleh ada, boleh tidak — akan diabaikan): "
            + ", ".join(f"`{c}`" for c in drops)
            + ". Kolom non-numerik lain juga otomatis dibuang."
        )

    # ── 4. Contoh struktur (nama kolom/field NYATA, nilai ilustratif) ─────
    st.markdown("**Contoh struktur**")
    if dataset_type == "HIKARI2021":
        # Hanya kolom yang BENAR-BENAR ada di skema yang ditampilkan; bila tidak
        # satu pun cocok, pakai kolom fitur pertama dari skema apa adanya.
        pairs = [(c, v) for c, v in req["sample_columns"].items() if c in features]
        if not pairs:
            pairs = [(c, "…") for c in features[:3]]
        if pairs:
            header = "…," + ",".join(c for c, _ in pairs) + f",…,{label_col}"
            values = "…," + ",".join(v for _, v in pairs) + ",…,0"
            st.code(f"{header}\n{values}", language="text")
            st.caption(
                "Nama kolom diambil dari `contracts/dataset_schemas.py`; nilainya "
                "ilustratif. `…` = kolom lain — ini **bukan** daftar kolom lengkap."
            )
    else:
        keys = list(schema.get("expected_top_level_keys") or [])
        vals = req["sample_values"]
        ordered = {k: vals[k] for k in keys if k in vals}
        ordered.update({k: v for k, v in vals.items() if k not in ordered})
        if ordered:
            st.code(_json.dumps(ordered, ensure_ascii=False), language="json")
            st.caption(
                "Nama field diambil dari `expected_top_level_keys` pada "
                "`contracts/dataset_schemas.py`; nilainya ilustratif. Contoh "
                "disederhanakan — event lain (mis. `event_type` = `alert` dengan "
                "objek `alert`) tetap diperlukan karena dipakai untuk membentuk "
                "label."
            )

    # ── 5. Checklist kecocokan (diturunkan, read-only) ────────────────────
    st.markdown("**Dataset Anda cocok jika…**")
    checks = [
        f"Format berkasnya {ext_text} — {req['row_unit']}.",
    ]
    if dataset_type == "HIKARI2021":
        checks += [
            f"Ada kolom label bernama persis `{label_col}` berisi `0`/`1`.",
            "Kolom fiturnya **numerik** (kolom non-numerik & non-fitur di atas "
            "otomatis diabaikan).",
            f"Berisi **dua kelas**: `0` = {benign} dan `1` = {malicious}.",
        ]
    else:
        checks += [
            "Berisi **event TLS** (`app_proto` / `event_type` = `tls`, atau port "
            "443/8443) — pipeline yang memisahkannya.",
            f"Tidak perlu kolom label: `{label_col}` dibentuk pipeline dari alert "
            "Suricata pada berkas yang sama.",
            f"Berisi **dua kelas** setelah pelabelan — ada event `alert` sehingga "
            f"kelas {attack} tidak kosong.",
        ]
    st.markdown("\n".join(f"- ✔ {c}" for c in checks))


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


# ── Diagnosa kecocokan dataset (otomatis, hemat memori) ───────────────────

@st.cache_data(show_spinner=False)
def _cached_diagnosis(dataset_path: str, mtime: float, size: int) -> dict:
    """Diagnosa kecocokan berkas terhadap SEMUA research pipeline.

    Kunci cache = (path, mtime, ukuran) → diagnosa hanya dihitung ulang bila
    berkas yang dipilih berganti atau berubah di disk; rerun Streamlit biasa
    memakai hasil cache dan TIDAK menyentuh berkas sama sekali.

    Berkas dibaca SATU KALI dan dicuplik (lihat SAMPLE_ROWS di
    orchestrator/dataset_diagnostics.py); dataset besar tidak pernah dimuat
    seluruhnya, tidak ada pipeline/model yang dijalankan. Tidak pernah raise —
    kegagalan dikembalikan sebagai pesan agar UI tetap bisa dipakai."""
    try:
        from orchestrator.dataset_diagnostics import diagnose_all
        return diagnose_all(dataset_path)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Diagnosa dataset gagal untuk %s", dataset_path, exc_info=True)
        return {"path": dataset_path, "rows_read": 0, "sampled": False,
                "detected_format": "unknown", "malformed_lines": 0,
                "error": f"Diagnosa tidak dapat dijalankan: {e}",
                "results": {}, "compatible_types": []}


def _diagnose_selected(dataset_path: str) -> dict:
    """Diagnosa untuk berkas terpilih, ber-cache berdasarkan mtime+ukuran."""
    try:
        stat = Path(dataset_path).stat()
        return _cached_diagnosis(dataset_path, stat.st_mtime, stat.st_size)
    except OSError as e:
        return {"path": dataset_path, "rows_read": 0, "sampled": False,
                "detected_format": "unknown", "malformed_lines": 0,
                "error": f"Berkas tidak dapat dibaca: {e}",
                "results": {}, "compatible_types": []}


_STATUS_ICON = {"pass": "✔", "warn": "⚠", "fail": "✖", "skip": "–"}

# ── Penyajian bertingkat: verdict → penyebab → tindakan ───────────────────
# Semua di bawah ini murni PENYAJIAN atas hasil diagnose_all(); tidak ada satu
# pun nilai `compatible`/`status` yang dihitung ulang atau diubah di sini.

VERDICT_OK, VERDICT_NEAR, VERDICT_NO = "ok", "near", "no"

_VERDICT_LABEL = {
    VERDICT_OK: "Cocok",
    VERDICT_NEAR: "Hampir cocok",
    VERDICT_NO: "Tidak cocok",
}
# Urutan tampil: yang paling dekat cocok lebih dulu.
_VERDICT_RANK = {VERDICT_OK: 0, VERDICT_NEAR: 1, VERDICT_NO: 2}

# Urutan kepentingan cek — kegagalan pertama pada urutan ini yang dijadikan
# "penyebab utama"; sisanya biasanya akibat lanjutan dari yang pertama.
_FAILURE_PRIORITY = ("format", "label", "features", "classes", "dtype")

# SATU tempat untuk kalimat tindakan "Agar cocok…", dipetakan dari jenis
# kegagalan (kunci cek) × dataset_type. Jangan sebar kalimat ini ke tempat lain.
_ACTION_HINTS: dict[str, dict[str, str]] = {
    "format": {
        "HIKARI2021": "sediakan berkas `.csv` hasil ekstraksi ALLFLOWMETER pada "
                      "dataset HIKARI2021.",
        "EVE_SURICATA": "sediakan berkas `.ndjson`/`.jsonl` keluaran Suricata "
                        "(EVE log) yang memuat event TLS.",
    },
    "label": {
        "HIKARI2021": "pastikan berkas memiliki kolom label `Label` berisi 0/1.",
        "EVE_SURICATA": "gunakan EVE log yang memuat event `alert` Suricata — "
                        "label diturunkan dari alert tersebut, bukan dari kolom "
                        "label di berkas.",
    },
    "features": {
        "HIKARI2021": "gunakan dataset hasil ekstraksi ALLFLOWMETER pada "
                      "HIKARI2021, atau samakan kolom fiturnya dengan skema "
                      "tersebut.",
        "EVE_SURICATA": "gunakan EVE log Suricata yang utuh (memuat kunci dasar "
                        "seperti `timestamp`, `flow_id`, `event_type`) dan "
                        "berisi event TLS.",
    },
    "classes": {
        "HIKARI2021": "pastikan dataset memuat dua kelas (benign & attack), "
                      "bukan hanya satu.",
        "EVE_SURICATA": "pastikan EVE log memuat trafik TLS normal sekaligus "
                        "event `alert`, agar dua kelas dapat terbentuk.",
    },
}


def _checks_by_key(result: dict) -> dict:
    return {c["key"]: c for c in result.get("checks", [])}


def _primary_failure(result: dict) -> dict | None:
    """Kegagalan paling menentukan (satu saja), menurut _FAILURE_PRIORITY."""
    by_key = _checks_by_key(result)
    for key in _FAILURE_PRIORITY:
        c = by_key.get(key)
        if c and c["status"] == "fail":
            return c
    return None


def _verdict(result: dict) -> str:
    """Tiga tingkat, bukan biner.

    - Cocok        : diagnosa lolos (compatible).
    - Hampir cocok : format & kolom label sudah benar, hanya struktur kolom /
                     distribusi kelas yang belum — masih bisa diperbaiki
                     pengguna tanpa berganti jenis berkas.
    - Tidak cocok  : yang gagal bersifat fundamental (format berkas / kolom
                     label), jadi berkas ini memang bukan untuk pipeline itu.
    """
    if result.get("compatible"):
        return VERDICT_OK
    by_key = _checks_by_key(result)
    fundamental_ok = all(
        (by_key.get(k) or {}).get("status") in ("pass", "warn")
        for k in ("format", "label")
    )
    failing = {k for k, c in by_key.items() if c["status"] == "fail"}
    if fundamental_ok and failing and failing <= {"features", "classes"}:
        return VERDICT_NEAR
    return VERDICT_NO


def _cause_sentence(diag: dict, dataset_type: str, result: dict) -> str:
    """Penyebab utama dalam SATU kalimat — ringkas, tanpa menumpahkan daftar
    kolom (jumlahnya saja; nama-nama contoh ada di rincian)."""
    failure = _primary_failure(result)
    if failure is None:
        warns = [c for c in result.get("checks", []) if c["status"] == "warn"]
        if warns:
            return (f"Seluruh pemeriksaan wajib lulus, dengan {len(warns)} "
                    f"catatan pada rincian.")
        return "Seluruh pemeriksaan lulus."

    key, count = failure["key"], failure.get("count", 0)
    if key == "format":
        names = {"csv": "CSV", "ndjson": "NDJSON", "unknown": "tidak dikenali"}
        want = names.get(required_format(dataset_type), "?")
        got = names.get(diag.get("detected_format", "unknown"), "tidak dikenali")
        return (f"Pipeline ini butuh berkas {want}, sedangkan dataset Anda {got}; "
                f"pemeriksaan lain dilewati.")
    if key == "label":
        return failure["message"]
    if key == "features":
        if count:
            unit = "kunci JSON" if required_format(dataset_type) == "ndjson" else "kolom"
            return (f"Struktur {unit} berbeda dari skema ({count} {unit} tidak "
                    f"ditemukan); format & kolom label sudah benar.")
        return failure["message"]
    if key == "classes":
        return ("Hanya satu kelas yang terdeteksi, padahal pipeline butuh dua "
                "kelas (benign & attack).")
    return failure["message"]


def _action_sentence(dataset_type: str, result: dict) -> str:
    """Kalimat "Agar cocok…" untuk kegagalan utama; "" bila tidak ada kegagalan."""
    failure = _primary_failure(result)
    if failure is None:
        return ""
    hint = (_ACTION_HINTS.get(failure["key"]) or {}).get(dataset_type)
    return f"**Agar cocok:** {hint}" if hint else ""


def _sample_note(diag: dict) -> str:
    """Catatan kecil bahwa angka berasal dari sampel, bukan seluruh berkas."""
    if not diag.get("rows_read"):
        return ""
    n = f"{diag['rows_read']:,}"
    return (f"Berdasarkan **{n} baris pertama** (sampel; berkas tidak dimuat "
            f"seluruhnya)." if diag.get("sampled")
            else f"Berdasarkan seluruh {n} baris berkas ini.")


# ── Penyaji BERSAMA untuk "kolom/kunci yang hilang" ───────────────────────
# Dipakai di DUA tempat — rincian dialog uji kecocokan dan ringkasan validasi
# di halaman — supaya gayanya persis sama: JUMLAH dulu, beberapa contoh, lalu
# "… (+N lainnya)". Daftar penuh 80+ kolom tidak pernah tampil secara default.

# Maksimal nama yang disebut sebelum "… (+N lainnya)". Disamakan dengan
# _MAX_LISTED di orchestrator/dataset_diagnostics.py agar jumlah contoh di
# rincian dialog dan di ringkasan validasi persis sama.
_MISSING_PREVIEW = 5

# Baris error validator yang isinya dump daftar mentah — diganti oleh penyaji
# ini, jadi tidak pernah ditampilkan apa adanya. (Sumber literalnya:
# orchestrator/validator.py; hanya dicocokkan, tidak diubah.)
_RAW_LIST_ERROR_PREFIXES = ("Missing required columns", "Missing expected JSON keys")


def _missing_items_summary(count: int, examples: list[str], dataset_type: str,
                           *, unit: str = "kolom") -> str:
    """Satu kalimat: jumlah + contoh terbatas. TIDAK pernah mendaftar semuanya."""
    shown = [sanitize_display_value(e) for e in examples[:_MISSING_PREVIEW]]
    text = (f"Dataset ini kekurangan **{count} {unit}** yang diminta skema "
            f"`{dataset_type}`.")
    if shown:
        rest = count - len(shown)
        contoh = ", ".join(f"`{n}`" for n in shown)
        text += f" Contoh: {contoh}"
        text += f", … (+{rest} lainnya)." if rest > 0 else "."
    return text


def _render_check_list(result: dict, dataset_type: str = "") -> None:
    """Rincian kelima pemeriksaan. Status `skip` ditandai jelas sebagai
    *dilewati* agar tidak terbaca seperti kegagalan."""
    checks = result.get("checks", [])

    # Cek yang dilewati dengan ALASAN yang sama (mis. keempatnya menunggu format
    # berkas benar) diruntuhkan jadi SATU baris — empat kalimat identik tidak
    # menambah informasi apa pun. Skip yang berdiri sendiri (mis. "tidak berlaku
    # untuk pipeline ini") tetap punya barisnya sendiri.
    skip_groups: dict[str, list[str]] = {}
    for c in checks:
        if c["status"] == "skip":
            skip_groups.setdefault(c["message"], []).append(c["title"])
    collapsed_shown: set[str] = set()

    for c in checks:
        icon = _STATUS_ICON.get(c["status"], "·")
        if c["status"] == "skip":
            group = skip_groups.get(c["message"], [])
            if len(group) > 1:
                if c["message"] in collapsed_shown:
                    continue
                collapsed_shown.add(c["message"])
                names = ", ".join(group)
                st.markdown(
                    f"- {icon} _Pemeriksaan lain ({names}) dilewati: "
                    f"{sanitize_display_value(c['message'])}_"
                )
            else:
                st.markdown(f"- {icon} **{c['title']}** — "
                            f"_dilewati: {sanitize_display_value(c['message'])}_")
            continue

        # Kolom/kunci yang hilang memakai penyaji BERSAMA (jumlah + contoh
        # terbatas), gaya yang sama dengan ringkasan validasi dataset.
        if c["key"] == "features" and c["status"] == "fail" and c.get("count"):
            unit = "kunci JSON" if c["message"].find("kunci JSON") >= 0 else "kolom"
            st.markdown(f"- {icon} **{c['title']}** — "
                        + _missing_items_summary(c["count"], c.get("examples") or [],
                                                 dataset_type, unit=unit))
            continue

        st.markdown(f"- {icon} **{c['title']}** — {c['message']}")


def _render_validation_failure(v: dict, dataset_type: str) -> None:
    """Ringkasan kegagalan validasi — pengganti dump "Missing required columns:
    [80+ kolom]".

    Dibaca dari ``validation_result`` (ValidationResult) yang MEMANG sudah
    dikembalikan validation_service, jadi tidak ada logika validasi yang
    diubah — hanya cara menampilkannya: jumlah + beberapa contoh + daftar penuh
    di dalam expander yang tertutup secara default.
    """
    vr = v.get("validation_result")
    missing = list(getattr(vr, "missing_columns", None) or [])
    errors = list(getattr(vr, "errors", None) or [])

    schema = get_schema(dataset_type) or {}
    is_json = bool(schema.get("expected_top_level_keys"))
    unit = "kunci JSON" if is_json else "kolom"

    # Pesan validator yang isinya daftar mentah TIDAK ditampilkan apa adanya;
    # digantikan ringkasan di bawah. Error lain (mis. "DataFrame is empty")
    # tetap ditampilkan utuh karena pendek dan informatif.
    other = [e for e in errors
             if not any(e.startswith(p) for p in _RAW_LIST_ERROR_PREFIXES)]

    if missing:
        st.error(_missing_items_summary(len(missing), missing, dataset_type, unit=unit))
        st.markdown(
            f"Sepertinya berkas ini **bukan** dataset `{dataset_type}`. Jalankan "
            f"**Uji kecocokan** pada kotak di bawah untuk melihat research "
            f"pipeline yang sesuai beserta langkah perbaikannya."
        )
        with st.expander(f"Lihat semua {len(missing)} {unit} yang diminta skema",
                         expanded=False):
            st.code("\n".join(str(c) for c in missing), language=None)
    for e in other:
        st.error(e)
    if not missing and not other:
        st.error(v.get("error") or "Validasi dataset gagal.")


def _sorted_results(diag: dict) -> list[tuple[str, dict]]:
    """(dataset_type, result) diurutkan: Cocok → Hampir cocok → Tidak cocok."""
    items = list((diag.get("results") or {}).items())
    return sorted(items, key=lambda kv: (_VERDICT_RANK[_verdict(kv[1])], kv[0]))


def _any_compatible(diag: dict) -> bool:
    """Apakah ADA research pipeline yang cocok otomatis dengan berkas ini?

    Dibaca dari hasil ``diagnose_all`` yang sudah ber-cache — tidak ada
    pembacaan berkas tambahan. Ini penentu alur: true → alur normal tanpa kotak,
    false → kotak uji kecocokan.
    """
    return bool(diag.get("compatible_types"))


def _compatible_names(diag: dict) -> list[str]:
    """Nama tampilan research pipeline yang cocok (untuk indikator ringkas)."""
    return [get_research_display_name(dt) for dt in (diag.get("compatible_types") or [])]


def _requirement_summary(dataset_type: str) -> str:
    """Syarat dataset dalam SATU baris untuk kotak pipeline: format · kolom
    label · sifat fitur. Diturunkan dari _EXT_MAP + skema + dict persyaratan
    terpusat yang sama dengan panel "Persyaratan Dataset"."""
    schema = get_schema(dataset_type) or {}
    req = _DATASET_REQUIREMENTS.get(dataset_type, {})
    exts = " / ".join(f"`{e}`" for e in _dataset_extensions(dataset_type))
    label = f"kolom label `{schema.get('label_column', '?')}`"
    return f"{exts} · {label} · {req.get('summary_line', '—')}"


def _compat_dialog_body(diag: dict, dataset_type: str, *, collapsible: bool = True) -> None:
    """Isi hasil uji kecocokan untuk SATU research pipeline.

    Tiga lapis: verdict → penyebab utama (satu kalimat) → tindakan, dengan
    kelima pemeriksaan dilipat di "Rincian pemeriksaan". Hanya membaca hasil
    diagnosa ber-cache — tidak ada pipeline/model yang dijalankan dan tidak ada
    pembacaan berkas baru di sini.

    ``collapsible=False`` dipakai pada jalur cadangan (Streamlit tanpa
    ``st.dialog``), karena isinya sudah berada di dalam sebuah expander dan
    Streamlit melarang expander bersarang.
    """
    result = (diag.get("results") or {}).get(dataset_type) or {}
    st.markdown(f"**{get_research_display_name(dataset_type)}**  ·  `{dataset_type}`")

    if not result:
        st.warning(diag.get("error") or "Hasil diagnosa tidak tersedia.")
    else:
        verdict = _verdict(result)
        headline = (f"**{_VERDICT_LABEL[verdict]}** — "
                    f"{_cause_sentence(diag, dataset_type, result)}")
        if verdict == VERDICT_OK:
            st.success(headline)
        elif verdict == VERDICT_NEAR:
            st.warning(headline)
        else:
            st.error(headline)

        action = _action_sentence(dataset_type, result)
        if action:
            st.markdown(action)

        if collapsible:
            with st.expander("Rincian pemeriksaan", expanded=False):
                _render_check_list(result, dataset_type)
        else:
            st.markdown("**Rincian pemeriksaan**")
            _render_check_list(result, dataset_type)

        note = _sample_note(diag)
        if note:
            st.caption(note)
        st.caption(
            "Uji ini hanya membaca cuplikan berkas (tidak memuat seluruh "
            "dataset) dan tidak menjalankan pipeline apa pun."
        )

    if st.button("Tutup", key=f"compat_close_{dataset_type}"):
        _close_compat_dialog()


# `st.dialog` HANYA ada di modul `st` — bukan pada DeltaGenerator hasil
# st.columns()/st.container(), jadi jangan pernah memanggil `col.dialog(...)`.
# Dekorasi dilakukan sekali di tingkat modul (pola yang sama dengan
# `_detail_dialog` di ui/views/view_results.py). Pada Streamlit lama yang belum
# punya st.dialog, jalur cadangannya adalah st.expander — bukan atribut .dialog
# pada container.
_HAS_ST_DIALOG = hasattr(st, "dialog")

if _HAS_ST_DIALOG:
    _compat_dialog = st.dialog("Uji Kecocokan Dataset", width="large")(_compat_dialog_body)
else:  # pragma: no cover - hanya untuk Streamlit < 1.37
    def _compat_dialog(diag: dict, dataset_type: str) -> None:
        with st.expander("Uji Kecocokan Dataset", expanded=True):
            _compat_dialog_body(diag, dataset_type, collapsible=False)


def _request_compat_check(dataset_type: str) -> None:
    """Tombol HANYA menyimpan pilihan; dialog TIDAK dipanggil dari sini.

    Dipanggil dari dalam kotak (kolom/container) — konteks yang tidak sah untuk
    membuka dialog. Fungsi ber-@st.dialog baru dipanggil dari ALUR UTAMA script
    di `_maybe_render_compat_dialog`, sesudah blok kotak dirender.
    """
    st.session_state["_compat_check_type"] = dataset_type


def _close_compat_dialog() -> None:
    """Bersihkan flag lalu rerun agar dialog tidak terbuka lagi."""
    st.session_state.pop("_compat_check_type", None)
    st.rerun()


def _maybe_render_compat_dialog(diag: dict) -> None:
    """Panggil dialog dari ALUR UTAMA script bila ada flag uji kecocokan.

    Ini satu-satunya tempat fungsi ber-@st.dialog dipanggil: bukan dari
    on_click callback, bukan dari dalam kolom/container.
    """
    dtype = st.session_state.get("_compat_check_type")
    if not dtype:
        return
    if dtype not in (diag.get("results") or {}):
        # Dataset berganti sejak tombol ditekan — jangan tampilkan hasil basi.
        st.session_state.pop("_compat_check_type", None)
        return
    _compat_dialog(diag, dtype)


def _render_compat_boxes(diag: dict) -> None:
    """Kotak per RESEARCH PIPELINE (dataset_type) — bukan per algoritma.

    Hanya dipanggil saat tidak ada satu pun pipeline yang cocok otomatis.
    Tiap kotak: nama + atribusi, ringkasan syarat satu baris, dan tombol "Uji
    kecocokan" yang membuka dialog hasil untuk pipeline itu saja.
    """
    results = diag.get("results") or {}
    if not results:
        st.warning(diag.get("error") or "Diagnosa kecocokan tidak tersedia.")
        return

    st.warning(
        "Dataset belum otomatis cocok dengan pipeline mana pun. "
        "Pilih salah satu untuk menjalankan uji kecocokan."
    )
    ordered = _sorted_results(diag)          # yang paling dekat cocok lebih dulu
    cols = st.columns(len(ordered))
    for col, (dtype, _result) in zip(cols, ordered):
        # Gaya pemanggilan lewat objek kolom/container (seperti `cols[0].button`
        # di ui/views/view_results.py) — tidak masuk ke dalam context manager,
        # sehingga tombol tidak pernah menjalankan apa pun dari konteks bersarang.
        box = col.container(border=True)
        box.markdown(f"**{get_research_display_name(dtype)}**")
        box.caption(f"`{dtype}`")
        box.caption(_requirement_summary(dtype))
        if box.button("Uji kecocokan", key=f"compat_test_{dtype}",
                      use_container_width=True):
            # Hanya set flag. Dialog dibuka di alur utama (setelah blok ini)
            # pada run yang SAMA — tidak perlu st.rerun() dari dalam kotak.
            _request_compat_check(dtype)
    if diag.get("malformed_lines"):
        st.caption(f"{diag['malformed_lines']:,} baris pada sampel gagal diparse "
                   f"dan diabaikan.")


# ── Execution-status panel (async-only UI; mode shown, never toggled) ──────

@st.cache_data(ttl=5, show_spinner=False)
def _cached_health(nonce: int) -> dict:
    """Cache the infra health for a few seconds (and per manual re-check nonce)
    so the broker is not probed on every Streamlit rerun. Never raises."""
    try:
        from orchestrator.health_service import check_execution_health
        return check_execution_health()
    except Exception:
        return {"mode": "async", "broker_ok": False, "worker_ok": False,
                "worker_count": 0, "queue_depth": None, "can_run": False,
                "message": "Pemeriksaan kesehatan gagal."}


def _render_execution_status_panel() -> dict:
    """Read-only status panel: execution mode + broker/worker/queue indicators +
    a manual 'Periksa ulang' button. Returns the health dict so the caller can
    guard the Run button. This panel NEVER changes USE_ASYNC — mode is shown as
    information, not as a control."""
    nonce = st.session_state.get("_health_nonce", 0)
    health = _cached_health(nonce)

    with st.container(border=True):
        top = st.columns([2, 1])
        top[0].markdown("**Status Eksekusi**")
        if top[1].button("Periksa ulang", key="recheck_health", use_container_width=True):
            st.session_state["_health_nonce"] = nonce + 1
            st.rerun()

        if health.get("mode") == "sync":
            cols = st.columns(2)
            cols[0].metric("Mode", "Sinkron")
            cols[1].success("Local worker (in-process)")
            st.caption("Broker/worker tidak diperlukan pada mode sinkron.")
            return health

        cols = st.columns(4)
        cols[0].metric("Mode", "Asinkron")
        if health.get("broker_ok"):
            cols[1].success("Broker: tersambung")
        else:
            cols[1].error("Broker: terputus")
        if health.get("worker_ok"):
            cols[2].success(f"Worker: {health.get('worker_count', 0)} aktif")
        else:
            cols[2].error("Worker: tidak terdeteksi")
        qd = health.get("queue_depth")
        cols[3].metric("Antrian", qd if qd is not None else "—")
    return health


def render():
    st.title("Run Experiment")

    # Unggah & validasi script pipeline TIDAK lagi di halaman ini — seluruh
    # alurnya pindah ke halaman "Add Pipeline & Dataset" (ui/views/contribute.py)
    # agar hanya ada SATU pintu masuk kontribusi. Halaman ini kembali fokus
    # pada menjalankan eksperimen.

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
        for _k in ("last_result", "polling_experiment_id", "research_select", "algorithm_select", "selected_pipeline"):
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
            # Ringkasannya dirender DI LUAR expander ini (lihat di bawah), karena
            # daftar lengkap kolom butuh expander sendiri dan Streamlit melarang
            # expander bersarang.
            st.error("Dataset tidak lolos validasi skema — ringkasannya ada di "
                     "bawah panel ini.")
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

    # Ringkasan kegagalan validasi (jumlah + contoh + "lihat semua" tertutup).
    # Di luar expander di atas supaya expander daftar-lengkapnya sah.
    if not v.get("success"):
        _render_validation_failure(v, dataset_type)

    # Kecocokan dataset — ON-DEMAND. Yang berjalan otomatis di sini HANYA
    # pertanyaan "apakah ada research pipeline yang cocok?" (dari diagnose_all
    # yang sudah ber-cache: satu kali baca tercuplik untuk seluruh pipeline).
    #   ada yang cocok  → alur normal, tanpa kotak (indikator ringkas saja)
    #   tidak ada       → kotak per research pipeline; rincian baru dihitung/
    #                     ditampilkan saat pengguna menekan "Uji kecocokan"
    # Ditempatkan SEBELUM early-return validasi supaya berkas yang tidak cocok
    # di mana pun tetap punya jalan untuk diperiksa per pipeline.
    with st.spinner("Memeriksa kecocokan dataset…"):
        _diag = _diagnose_selected(dataset_path)

    if _any_compatible(_diag):
        st.caption("Dataset cocok untuk: " + ", ".join(_compatible_names(_diag)) + ".")
    else:
        _render_compat_boxes(_diag)
    _maybe_render_compat_dialog(_diag)

    if not v.get("success"):
        return

    # ── Pipeline Selection ─────────────────────────────────────────────
    st.header("Pipeline Selection")
    pipelines = v.get("compatible_pipelines", {})
    if not pipelines:
        st.warning("Tidak ada pipeline yang kompatibel untuk dataset ini.")
        return

    # Two-level selection (DISPLAY/grouping only): research pipeline → algorithm.
    # Group key = dataset_type (robust, 1:1 with a research); the research display
    # label comes from the SINGLE structured attribution source
    # (config/research_attribution.py) so the reproduced-study credit lives in one
    # place; the algorithm name comes from the registry `algorithm` field. Each
    # (research, algorithm) resolves back to a REAL registered pipeline_id,
    # dispatched exactly as before. compatible_pipelines is already filtered by the
    # selected dataset's dataset_type, so the research filter is preserved — just
    # applied one level up.
    research_groups: dict[str, dict[str, str]] = {}
    research_display: dict[str, str] = {}
    for pid, info in pipelines.items():
        dt = info.get("dataset_type", "") or pid
        algo = info.get("algorithm") or info.get("name", pid)
        research_groups.setdefault(dt, {})[algo] = pid
        if dt not in research_display:
            research_display[dt] = get_research_display_name(dt)

    research_keys = list(research_groups.keys())
    research = st.selectbox(
        "Pilih research pipeline", research_keys,
        index=0 if len(research_keys) == 1 else None,
        placeholder="Pilih research pipeline…",
        format_func=lambda k: research_display.get(k, k),
        key="research_select",
    )

    selected = None
    _research_compatible = True
    if research:
        algo_to_pid = research_groups[research]
        _rep_pid = next(iter(algo_to_pid.values()))  # representative for shared info
        _pdtype = pipelines.get(_rep_pid, {}).get("dataset_type")

        # Kecocokan research pipeline yang SEDANG dipilih — dibaca dari hasil
        # diagnosa yang sudah di-cache (tanpa pembacaan berkas tambahan). Hanya
        # dipakai untuk mengunci tombol Run di bawah; rinciannya tidak dirender
        # otomatis, pengguna membukanya lewat "Uji kecocokan".
        if _pdtype:
            _sel_result = (_diag.get("results") or {}).get(_pdtype) or {}
            _research_compatible = bool(_sel_result.get("compatible", True))

        # Research-level info consolidated in ONE read-only expander (the former
        # separate blue st.info dataset box is merged in here). All fields are
        # derived from structured sources: registry (name/dataset_type/paper),
        # get_info() (feature_selection/app/anti_leakage/metrics_policy), and the
        # dataset schema (via _dataset_info_lines). Nothing here is editable and
        # nothing affects computation.
        rep_info = get_pipeline_info(_rep_pid) or {}
        with st.expander("Tentang Research Pipeline (Read-Only)", expanded=True):
            st.markdown(f"**Research:** {research_display.get(research, research)}")
            st.markdown(f"**Dataset type:** `{research}`")

            # ── Atribusi penelitian sumber (read-only, terstruktur) ─────────
            # Dibaca dari config/research_attribution.py (sumber tunggal), agar
            # kredit penelitian tidak tersebar. Membedakan sumber PIPELINE dari
            # sumber DATASET (khusus HIKARI). Tidak ada nilai yang bisa diubah di
            # sini dan tidak memengaruhi komputasi.
            _attr = get_research_attribution(research)
            _psrc = _attr.get("pipeline_source") or {}
            if _psrc:
                st.markdown("**Penelitian sumber (pipeline):**")
                if _psrc.get("type"):
                    st.markdown(f"  - **Jenis:** {_psrc['type']}")
                if _psrc.get("authors"):
                    st.markdown(f"  - **Penulis:** {_psrc['authors']}")
                if _psrc.get("title"):
                    st.markdown(f"  - **Judul:** \"{_psrc['title']}\"")
                if _psrc.get("institution"):
                    st.markdown(f"  - **Institusi:** {_psrc['institution']}")
                # Tahun tidak pernah dikarang: tampilkan tahun terkonfirmasi, atau
                # catatan "belum dikonfirmasi" secara eksplisit bila year=None.
                if _psrc.get("year"):
                    st.markdown(f"  - **Tahun:** {_psrc['year']}")
                elif _psrc.get("year_note"):
                    st.markdown(f"  - **Tahun:** _{_psrc['year_note']}_")
            _dsrc = _attr.get("dataset_source") or {}
            if _dsrc:
                st.markdown("**Sumber dataset:**")
                _dline = _dsrc.get("name", "")
                if _dsrc.get("attribution"):
                    _dline = f"{_dline} — {_dsrc['attribution']}" if _dline else _dsrc["attribution"]
                if _dline:
                    st.markdown(f"  - {_dline}")
                if _dsrc.get("note"):
                    st.markdown(f"  - _{_dsrc['note']}_")
            if _attr.get("scope"):
                st.markdown(f"**Cakupan penelitian sumber:** {_attr['scope']}")

            if rep_info.get("paper"):
                st.markdown(f"**Paper:** {rep_info['paper']}")

            # Dataset info (moved out of the old blue box).
            if _pdtype:
                st.markdown("**Dataset:**")
                for _line in _dataset_info_lines(_pdtype):
                    st.markdown(f"- {_line}")

            # Extra descriptive fields from the structured get_info(), when present.
            if rep_info.get("feature_selection"):
                st.markdown(f"**Feature selection:** {rep_info['feature_selection']}")
            if rep_info.get("app"):
                st.markdown(f"**Fokus aplikasi/trafik:** {rep_info['app']}")
            if rep_info.get("anti_leakage"):
                st.markdown("**Anti-leakage:**")
                for a in rep_info["anti_leakage"]:
                    st.markdown(f"  - {a}")
            if rep_info.get("metrics_policy"):
                st.markdown(f"**Metrics policy:** {rep_info['metrics_policy']}")

            # Sub-bagian read-only "Persyaratan Dataset" — agar pengguna dapat
            # mencocokkan datasetnya sendiri sebelum menjalankan eksperimen.
            # Mengikuti dataset_type (bukan algoritma), diturunkan dari skema +
            # konstanta pipeline. Tidak memvalidasi berkas apa pun.
            if _pdtype:
                _render_dataset_requirements(_pdtype)

            st.caption(
                "Pilih algoritma di bawah untuk melihat preprocessing & "
                "hyperparameter spesifik algoritma tersebut."
            )

        # Algorithm selector within the chosen research (algorithm names only —
        # the research name is already clear from the level above). Horizontal
        # segmented buttons; fall back to a horizontal radio on older Streamlit
        # without st.segmented_control. Both return the selected algorithm name
        # (or None when nothing is picked), so the pipeline_id resolution below
        # is identical either way and the Execute button stays conditional.
        _algo_names = list(algo_to_pid.keys())
        if hasattr(st, "segmented_control"):
            algorithm = st.segmented_control(
                "Pilih algoritma", _algo_names,
                selection_mode="single", default=None,
                key="algorithm_select",
            )
        else:
            algorithm = st.radio(
                "Pilih algoritma", _algo_names,
                index=None, horizontal=True,
                key="algorithm_select",
            )
        selected = algo_to_pid.get(algorithm) if algorithm else None

    st.session_state["selected_pipeline"] = selected

    if selected:
        # Algorithm-specific detail (full per-pipeline get_info) + config viewer.
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
        health = _render_execution_status_panel()
        can_run = health.get("can_run", True)
        # Gate tambahan: dataset yang tidak lolos diagnosa untuk research
        # pipeline TERPILIH tidak bisa dijalankan (eksperimen pasti gagal di
        # worker). Ini hanya mengunci tombol Run — pemilihan research/algoritma
        # lain tetap bebas, sehingga pengguna bisa berpindah ke pipeline yang cocok.
        if not _research_compatible:
            can_run = False
            st.error(
                "**Dataset belum cocok untuk pipeline ini.** Jalankan uji "
                "kecocokan untuk melihat penyebab dan saran perbaikannya, atau "
                "pilih research pipeline lain."
            )
            # Tombol ini berada SESUDAH titik pemanggilan dialog di alur utama,
            # jadi flag baru terbaca pada run berikutnya — rerun dari sini sah
            # karena berada di alur utama render(), bukan di dalam kolom.
            if st.button("Uji kecocokan", key="compat_test_from_run"):
                _request_compat_check(dataset_type)
                st.rerun()
        if not health.get("can_run", True):
            st.error(
                "**Eksekusi asinkron belum siap.** "
                + (health.get("message") or "Broker/worker tidak tersedia.")
                + " Jika eksperimen tetap dijalankan, ia akan tertahan di antrian dan "
                "berpotensi ditandai **FAILED (stale)** setelah 120 menit. "
                "Pastikan service **ids_worker** dan **ids_redis** berjalan, lalu klik "
                "**Periksa ulang**."
            )
        if st.button("Run Experiment", type="primary", disabled=not can_run):
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

        # Owner = username bila ada yang masuk, None bila mode pengunjung.
        # Murni metadata pencatatan: tidak diteruskan ke worker/pipeline dan
        # tidak pernah dipakai untuk menyaring tampilan.
        from ui.views.login import current_user as _current_user
        _user = _current_user()
        result = create_and_run_experiment(
            dataset_type, dataset_path, pipeline_id,
            owner=(_user or {}).get("username"),
        )

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
        # Single GLOBAL progress bar (monotonic 0→100, never reset per stage).
        _pct = int(round(_pb["fraction"] * 100))
        st.progress(_pb["fraction"], text=f"Progres keseluruhan: {_pct}%")
        # Summary line: "Fase i/N — name · Elapsed 2m 14s".
        _summary = f"**{_pb['label']}**"
        if _pb["elapsed_text"]:
            _summary += f" · Elapsed {_pb['elapsed_text']}"
        st.markdown(_summary)
        if _pb["hint"]:
            st.caption(_pb["hint"])

        # Jenkins-style HORIZONTAL stage view (columns): done / running / waiting
        # with per-stage duration. Per-stage start timestamps live in
        # session_state so durations survive Streamlit reruns during polling.
        if _stages_list:
            from workers.progress_util import build_stage_view
            _starts_key = f"_stage_starts_{experiment_id}"
            _starts = st.session_state.setdefault(_starts_key, {})
            _now = datetime.now(timezone.utc).timestamp()
            _ci = _pb.get("stage_index")
            if isinstance(_ci, int) and _ci >= 1:
                _starts.setdefault(_ci, _now)  # first time we observe this stage
            _view = build_stage_view(len(_stages_list), _ci, status, _starts, _now)
            st.markdown("**Tahapan pipeline**")
            _render_stage_columns(_stages_list, _view, _pb.get("stage_percent", 0))

        with st.status(f"Experiment {status.lower()}...", expanded=False):
            st.write(f"**Experiment ID:** `{experiment_id[:8]}...`")
            st.write(f"**Status:** {status}")
            if status == "QUEUED":
                st.write("Waiting for worker to pick up the task...")
            else:
                # Show the last reported stage message if the worker sent one.
                # Suppress internal [DIAG] scaffolding strings from the UI.
                _cp = status_data.get("celery_progress") or {}
                _msg = _cp.get("message") or status_data.get("celery_stage")
                if _msg and str(_msg).startswith("[DIAG]"):
                    _msg = "Menyiapkan eksekusi…"
                if _msg:
                    st.write(f"**Current step:** {_msg}")
                else:
                    st.write("Pipeline is executing. This may take several minutes...")
            _iv = _get_poll_interval(status_data.get("pipeline_id", ""))
            st.write(f"This page auto-refreshes about every {_iv} seconds.")
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
    """Render all metrics and charts via the shared interactive result view."""
    st.header("Results")
    eid = result["experiment_id"]

    # Unify this page's in-memory PipelineResult with the persisted metrics.json,
    # then render through the SAME shared component the History page uses.
    metrics = get_experiment_metrics(eid) or result.get("metrics") or {}
    payload = normalize_result_payload(
        experiment_id=eid,
        metrics=metrics,
        label_mapping=result.get("label_mapping"),
        feature_names=result.get("feature_names"),
        pipeline_id=st.session_state.get("selected_pipeline"),
        dataset_type=st.session_state.get("dataset_type"),
    )
    render_results(payload, key=eid, pipeline_id=st.session_state.get("selected_pipeline", ""))

    full = metrics  # PDF/download section below reads the same unified metrics

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
