"""Progress & Status page (main dashboard) — live progress of all in-flight
experiments on top, then the history table (AgGrid) below with a pop-up (dialog)
detail view built from the shared result components."""
from datetime import datetime, timezone
import time

import streamlit as st
import pandas as pd

from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from orchestrator.result_service import (
    list_all_experiments, get_full_experiment, get_experiment_metrics,
)
from orchestrator.experiment_service import (
    rerun_experiment, cancel_experiment, get_experiment_status,
)
from ui.views._artifact_browser import (
    render_file_browser, make_json_loader, make_text_loader, make_bytes_reader,
)
from ui.components.result_views import normalize_result_payload, render_results
from ui.components.dashboard import (
    select_running, progress_view, elapsed_seconds, format_elapsed,
)


# ─── Time helpers ──────────────────────────────────────────────────────────

def _parse_iso(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _relative_time(iso_str):
    dt = _parse_iso(iso_str)
    if dt is None:
        return "-"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    days = secs / 86400
    if days < 30:
        return f"{int(days)}d ago"
    if days < 365:
        return f"{int(days // 30)}mo ago"
    return f"{int(days // 365)}y ago"


def _epoch(iso_str):
    dt = _parse_iso(iso_str)
    return dt.timestamp() if dt else 0.0


def _duration(start, end):
    s, e = _parse_iso(start), _parse_iso(end)
    if s is None or e is None:
        return "-"
    secs = (e - s).total_seconds()
    if secs < 0:
        return "-"
    if secs < 60:
        return f"{secs:.0f}s"
    return f"{secs / 60:.1f}min"


def _build_artifact_files(experiment_id: str) -> dict:
    """Read storage/artifacts/{experiment_id}/ dynamically and map each file
    to a viewer spec. Path-guarded to the experiment's artifact directory."""
    from pathlib import Path
    from config.settings import ARTIFACTS_DIR

    base = Path(ARTIFACTS_DIR).resolve()
    art_dir = (base / experiment_id).resolve()
    files: dict = {}
    if not art_dir.is_relative_to(base) or not art_dir.exists():
        return files

    for entry in sorted(art_dir.iterdir()):
        if not entry.is_file():
            continue
        rp = entry.resolve()
        if not rp.is_relative_to(art_dir):
            continue  # defensive: skip anything resolving outside the dir
        name = entry.name
        rel = f"storage/artifacts/{experiment_id}/{name}"
        ext = entry.suffix.lower()
        if ext == ".json":
            files[name] = {"icon": "", "language": "json", "full_path": rel,
                           "download_name": name, "loader": make_json_loader(rp)}
        elif ext in (".log", ".txt"):
            files[name] = {"icon": "", "language": "text", "full_path": rel,
                           "download_name": name, "tail": ext == ".log",
                           "loader": make_text_loader(rp)}
        elif ext in (".pkl", ".joblib", ".bin"):
            files[name] = {"icon": "", "binary": True, "full_path": rel,
                           "size": rp.stat().st_size, "download_name": name,
                           "read_bytes": make_bytes_reader(rp)}
        else:
            files[name] = {"icon": "", "binary": True, "full_path": rel,
                           "size": rp.stat().st_size, "download_name": name,
                           "read_bytes": make_bytes_reader(rp)}
    return files


@st.cache_data(show_spinner=False)
def _roc_auc(experiment_id, completed_at):
    """Load roc_auc from metrics.json. Cache key includes completed_at so it
    invalidates only when the experiment actually finishes/changes."""
    metrics = get_experiment_metrics(experiment_id)
    if metrics and isinstance(metrics.get("roc_auc"), (int, float)):
        return float(metrics["roc_auc"])
    return None


# ─── Grid data ─────────────────────────────────────────────────────────────

def _dataset_basename(path) -> str:
    """Extract basename from a path that may use either '/' or '\\' separator.

    Robust to mixed-environment history: rows written from Docker store
    '/app/storage/datasets/foo.csv'; rows written from Windows host store
    'D:\\Program\\TA\\storage\\datasets\\foo.csv'. ``Path(...).name`` on Linux
    fails for the Windows form because backslash is not a separator there, so
    we split on both. Returns "-" for empty/None.
    """
    if not path:
        return "-"
    import re
    parts = re.split(r"[\\/]", str(path))
    return parts[-1] or "-"


def _build_grid_df(experiments: list[dict]) -> pd.DataFrame:
    rows = []
    for e in experiments:
        finished = e.get("status") == "FINISHED"
        roc = _roc_auc(e["id"], e.get("completed_at")) if finished else None
        rows.append({
            "ID": e["id"][:8],
            "_full_id": e["id"],
            "Start Time": _relative_time(e.get("created_at")),
            "_created_epoch": _epoch(e.get("created_at")),
            "_created_abs": (e.get("created_at") or "-")[:19],
            "Duration": _duration(e.get("started_at"), e.get("completed_at")),
            "Pipeline": e.get("pipeline_id", "-"),
            "Dataset": e.get("dataset_type", "-"),
            "File": _dataset_basename(e.get("dataset_path")),
            # Informasi saja — TIDAK dipakai untuk menyaring apa pun. Record
            # tanpa pemilik (dijalankan tanpa login, termasuk seluruh record
            # lama sebelum autentikasi ada) tampil sebagai "sistem".
            "Pemilik": e.get("owner") or "sistem",
            "Status": e.get("status", "-"),
            "Accuracy": e.get("accuracy"),
            "Precision": e.get("precision_score"),
            "Recall": e.get("recall"),
            "F1-score": e.get("f1_score"),
            "ROC-AUC": roc,
            "random_state": "42",
            "test_split": "0.20",
            "Hash": (e.get("dataset_hash") or "-")[:8],
        })
    df = pd.DataFrame(rows)

    # Per-column max flags for highlighting (ignores None/NaN robustly).
    for col, flag in [
        ("Accuracy", "_hi_accuracy"), ("Precision", "_hi_precision"),
        ("Recall", "_hi_recall"), ("F1-score", "_hi_f1"), ("ROC-AUC", "_hi_roc"),
    ]:
        numeric = pd.to_numeric(df[col], errors="coerce")
        col_max = numeric.max()
        if pd.notna(col_max):
            df[flag] = [bool(pd.notna(v) and v == col_max) for v in numeric]
        else:
            df[flag] = False
    return df


_METRIC_FORMATTER = JsCode(
    "function(p){ if(p.value===null||p.value===undefined||isNaN(p.value)){return '-';} "
    "return Number(p.value).toFixed(4); }"
)

_START_COMPARATOR = JsCode(
    "function(a,b,nodeA,nodeB){ const x=(nodeA.data&&nodeA.data._created_epoch)||0; "
    "const y=(nodeB.data&&nodeB.data._created_epoch)||0; return x-y; }"
)

_STATUS_STYLE = JsCode("""
function(params){
    const colors = {
        'FINISHED':'#d4edda','RUNNING':'#cce5ff','FAILED':'#f8d7da',
        'CANCELLED':'#e2e3e5','QUEUED':'#fff3cd','PENDING':'#fff3cd'
    };
    const bg = colors[params.value];
    if (bg) { return {'backgroundColor': bg, 'fontWeight': '600'}; }
    return null;
}
""")


def _hi_style(flag_field: str) -> JsCode:
    return JsCode(
        f"function(params){{ if(params.data && params.data.{flag_field}){{ "
        f"return {{'backgroundColor':'#cce5ff','fontWeight':'600'}}; }} return null; }}"
    )


def _metric_col(header, field, hi_flag, group_open):
    col = {
        "headerName": header, "field": field, "width": 110,
        "type": "numericColumn",
        "valueFormatter": _METRIC_FORMATTER,
        "cellStyle": _hi_style(hi_flag),
    }
    if group_open:
        col["columnGroupShow"] = "open"
    return col


def _build_grid_options(df: pd.DataFrame) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, resizable=True, filterable=False)
    gb.configure_selection(selection_mode="single", use_checkbox=False)
    options = gb.build()

    options["columnDefs"] = [
        {"headerName": "Info", "children": [
            {"headerName": "ID", "field": "ID", "width": 110, "pinned": "left"},
            {"headerName": "Start Time", "field": "Start Time", "width": 120,
             "tooltipField": "_created_abs", "comparator": _START_COMPARATOR,
             "sort": "desc"},
            {"headerName": "Duration", "field": "Duration", "width": 100},
            {"headerName": "Pipeline", "field": "Pipeline", "width": 210},
            {"headerName": "Dataset", "field": "Dataset", "width": 130},
            {"headerName": "File", "field": "File", "width": 200,
             "tooltipField": "File"},
            {"headerName": "Pemilik", "field": "Pemilik", "width": 120},
            {"headerName": "Status", "field": "Status", "width": 120,
             "cellStyle": _STATUS_STYLE},
        ]},
        {"headerName": "Metrics", "children": [
            # F1-score has no columnGroupShow → always visible (the column that
            # survives when the Metrics group is collapsed). The rest are "open".
            _metric_col("F1-score", "F1-score", "_hi_f1", group_open=False),
            _metric_col("Accuracy", "Accuracy", "_hi_accuracy", group_open=True),
            _metric_col("Precision", "Precision", "_hi_precision", group_open=True),
            _metric_col("Recall", "Recall", "_hi_recall", group_open=True),
            _metric_col("ROC-AUC", "ROC-AUC", "_hi_roc", group_open=True),
        ]},
        {"headerName": "Config", "children": [
            # Hash stays visible when Config collapses; the rest are "open".
            {"headerName": "Hash", "field": "Hash", "width": 110},
            {"headerName": "random_state", "field": "random_state", "width": 120,
             "columnGroupShow": "open"},
            {"headerName": "test_split", "field": "test_split", "width": 110,
             "columnGroupShow": "open"},
        ]},
    ]

    options["suppressHorizontalScroll"] = False
    options["enableBrowserTooltips"] = True
    if len(df) > 20:
        options["pagination"] = True
        options["paginationPageSize"] = 20
    return options


# ─── Page ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=4, show_spinner=False)
def _dash_health(nonce: int) -> dict:
    """Cache infra health briefly so the running dashboard does not probe the
    broker on every rerun. Never raises."""
    try:
        from orchestrator.health_service import check_execution_health
        return check_execution_health()
    except Exception:
        return {"mode": "async", "broker_ok": False, "worker_ok": False,
                "can_run": False, "message": ""}


def _render_running_section(experiments) -> tuple:
    """Dashboard of ALL in-flight (RUNNING/QUEUED) experiments — one card each
    with progress bar + running stage + cancel. Returns (running, auto, interval).

    Progress is read cross-session via get_experiment_status (task_id → Celery
    AsyncResult); when granular data is unavailable (QUEUED, or broker down) the
    card shows status + elapsed only — never a fabricated percentage."""
    running = select_running(experiments)

    head = st.columns([3, 1, 1])
    head[0].subheader("Sedang Berjalan")
    if hasattr(head[1], "toggle"):
        auto = head[1].toggle("Auto-refresh", value=True, key="_dash_auto")
    else:
        auto = head[1].checkbox("Auto-refresh", value=True, key="_dash_auto")
    if head[2].button("Perbarui", use_container_width=True, key="_dash_refresh"):
        st.session_state["_dash_nonce"] = st.session_state.get("_dash_nonce", 0) + 1
        st.rerun()

    if not running:
        st.info("Tidak ada eksperimen yang sedang berjalan. "
                "Buka **Run Experiment** dari menu di sidebar untuk memulai.")
        return running, bool(auto), 6

    health = _dash_health(st.session_state.get("_dash_nonce", 0))
    async_mode = health.get("mode") == "async"
    can_read_progress = (not async_mode) or bool(health.get("broker_ok"))
    if async_mode and not health.get("broker_ok", True):
        st.warning("Broker (Redis) tidak tersambung — progres granular tidak tersedia; "
                   "menampilkan status & elapsed saja.")

    for e in running:
        eid = e["id"]
        status_data = None
        if can_read_progress:
            try:
                status_data = get_experiment_status(eid)
            except Exception:
                status_data = None
        status_data = status_data or e
        pv = progress_view(status_data)
        el = elapsed_seconds(e.get("started_at") or e.get("created_at"))
        cur_status = status_data.get("status", e.get("status", "-"))

        with st.container(border=True):
            top = st.columns([3, 1])
            top[0].markdown(f"**{e.get('pipeline_id', '?')}** · {e.get('dataset_type', '?')}")
            top[1].markdown(f"`{cur_status}`")
            st.caption(f"Mulai {(e.get('started_at') or e.get('created_at') or '-')[:19]} · "
                       f"Elapsed {format_elapsed(el)}")
            if pv["overall_percent"] is not None:
                st.progress(min(max(pv["overall_percent"], 0), 100) / 100.0,
                            text=f"Progres keseluruhan: {pv['overall_percent']}%")
            if pv["stage_label"]:
                st.markdown(f"**{pv['stage_label']}**")
            elif e.get("status") == "QUEUED":
                st.caption("Menunggu worker mengambil tugas…")
            else:
                st.caption("Progres granular tidak tersedia untuk eksperimen ini.")
            if st.button("Batalkan", key=f"dash_cancel_{eid}"):
                r = cancel_experiment(eid)
                if r.get("success"):
                    st.warning("Eksperimen dibatalkan.")
                else:
                    st.error(r.get("message", "Gagal membatalkan."))
                st.rerun()

    return running, bool(auto), 6


def _pdf_download_button(exp: dict, metrics: dict, metadata: dict, key: str) -> None:
    """PDF download for a FINISHED experiment (unchanged generator path)."""
    try:
        from utils.report_generator import generate_report
        from orchestrator.execution_service import get_pipeline_info
        pdf_bytes = generate_report(
            experiment_id=exp["id"],
            dataset_type=exp["dataset_type"],
            dataset_path=exp["dataset_path"],
            dataset_hash=exp.get("dataset_hash", "N/A"),
            pipeline_id=exp["pipeline_id"],
            pipeline_info=get_pipeline_info(exp["pipeline_id"]) or {},
            metrics=metrics,
            metadata=metadata,
            label_mapping=(metadata or {}).get("label_mapping"),
            feature_names=(metadata or {}).get("feature_names"),
        )
        st.download_button(
            "Download PDF Report", data=pdf_bytes,
            file_name=f"experiment_report_{exp['id'][:8]}.pdf",
            mime="application/pdf", key=key,
        )
    except Exception as e:  # never break the dialog on a PDF failure
        st.caption(f"PDF tidak dapat dibuat: {type(e).__name__}")


@st.dialog("Detail Eksperimen", width="large")
def _detail_dialog(experiment_id: str) -> None:
    """Pop-up detail view. Renders the SHARED interactive result component
    (zero duplication): confusion matrix, feature importance, ROC, learning
    curve / dual-holdout, static-figures expander — all defensive cases
    preserved for HIKARI and EVE-cbr."""
    full = get_full_experiment(experiment_id)
    if not full:
        st.error("Eksperimen tidak ditemukan.")
        if st.button("Tutup", key=f"dlg_close_missing_{experiment_id}"):
            st.session_state.pop("_detail_id", None)
            st.rerun()
        return

    exp = full["experiment"]
    metrics = full.get("metrics")
    metadata = full.get("metadata")

    st.markdown(f"**{exp['pipeline_id']}** · {exp['dataset_type']} · `{exp['status']}`")
    st.caption(f"ID `{exp['id']}` · Created {(exp.get('created_at') or '-')[:19]} · "
               f"Completed {(exp.get('completed_at') or '-')[:19]}")
    # Ketertelusuran pipeline TERUNGGAH: versi + SHA-256 berkasnya. Pipeline
    # bawaan tidak menampilkan apa-apa di sini — definisinya ada di git.
    if exp.get("pipeline_version") or exp.get("pipeline_hash"):
        st.caption(
            f"Pipeline terunggah · versi {exp.get('pipeline_version') or '-'} · "
            f"SHA-256 `{(exp.get('pipeline_hash') or '-')[:16]}…` · "
            f"dataset SHA-256 `{(exp.get('dataset_hash') or '-')[:16]}…`"
        )

    if exp["status"] == "FINISHED" and metrics:
        payload = normalize_result_payload(
            experiment_id=exp["id"], metrics=metrics, metadata=metadata,
            pipeline_id=exp.get("pipeline_id"), dataset_type=exp.get("dataset_type"),
        )
        render_results(payload, key=f"dlg_{exp['id']}", pipeline_id=exp.get("pipeline_id", ""))
        _pdf_download_button(exp, metrics, metadata, key=f"dlgpdf_{exp['id']}")
        with st.expander("Artifact Viewer", expanded=False):
            files = _build_artifact_files(exp["id"])
            if files:
                render_file_browser(files, state_key=f"dlg_artifacts_{exp['id']}")
            else:
                st.info("Artefak belum tersedia atau direktori artefak kosong.")
    elif exp["status"] == "FAILED":
        em = exp.get("error_message", "Unknown")
        if em == "Cancelled by user":
            st.warning("Eksperimen dibatalkan oleh pengguna.")
        else:
            st.error(f"Gagal: {em}")
    else:
        st.info(f"Eksperimen berstatus {exp['status']}. Hasil belum tersedia.")

    st.markdown("---")
    act = st.columns(3)
    if exp["status"] in ("QUEUED", "RUNNING"):
        if act[0].button("Batalkan", key=f"dlg_cancel_{exp['id']}"):
            cancel_experiment(exp["id"])
            st.session_state.pop("_detail_id", None)
            st.rerun()
    if act[1].button("Re-run", key=f"dlg_rerun_{exp['id']}"):
        r = rerun_experiment(exp["id"])
        if r.get("success"):
            st.success(f"Baru: `{r['experiment_id'][:8]}…` — tutup dan segarkan.")
        else:
            st.error(r.get("error", "Gagal."))
    if act[2].button("Tutup", key=f"dlg_close_{exp['id']}"):
        st.session_state.pop("_detail_id", None)
        st.rerun()


def _render_selected_actions(selected_id: str) -> None:
    """Compact action bar for the row selected in the history table."""
    full = get_full_experiment(selected_id)
    if not full:
        st.session_state.pop("selected_experiment_id", None)
        return
    exp = full["experiment"]
    st.markdown(f"**Terpilih:** `{exp['id'][:8]}` — {exp['pipeline_id']} · `{exp['status']}`")
    cols = st.columns(3)
    if cols[0].button("Lihat detail", key=f"open_{selected_id}", type="primary",
                      use_container_width=True):
        st.session_state["_detail_id"] = selected_id
        st.rerun()
    if cols[1].button("Re-run", key=f"rerun_{selected_id}", use_container_width=True):
        r = rerun_experiment(selected_id)
        if r.get("success"):
            st.success(f"Baru: `{r['experiment_id'][:8]}…` — segarkan tabel.")
        else:
            st.error(r.get("error", "Gagal."))
    if exp["status"] in ("QUEUED", "RUNNING"):
        if cols[2].button("Batalkan", key=f"cancel_{selected_id}", use_container_width=True):
            cancel_experiment(selected_id)
            st.rerun()


def render():
    st.title("Progress & Status")

    experiments = list_all_experiments()

    # ── Sedang Berjalan (live dashboard of ALL in-flight experiments) ──
    running, auto, interval = _render_running_section(experiments)

    st.markdown("---")
    st.subheader("Riwayat Eksperimen")

    if not experiments:
        st.info("Belum ada eksperimen. Buka halaman 'Run Experiment' untuk membuat satu.")
        st.session_state.pop("selected_experiment_id", None)
    else:
        st.caption(
            f"{len(experiments)} eksperimen. Pilih satu baris lalu klik "
            "**Lihat detail** untuk membuka hasil sebagai pop-up. Grup Metrics/Config "
            "dapat di-collapse lewat ikon header grup."
        )
        df = _build_grid_df(experiments)
        grid_options = _build_grid_options(df)
        grid_response = AgGrid(
            df,
            gridOptions=grid_options,
            allow_unsafe_jscode=True,
            theme="streamlit",
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=False,
            height=440,
            key="experiment_history_grid",
        )

        selected_id = None
        sel = grid_response.get("selected_rows")
        if isinstance(sel, pd.DataFrame):
            if not sel.empty and "_full_id" in sel.columns:
                selected_id = sel.iloc[0]["_full_id"]
        elif isinstance(sel, list) and sel:
            selected_id = sel[0].get("_full_id")

        if selected_id:
            st.session_state["selected_experiment_id"] = selected_id
        selected_id = st.session_state.get("selected_experiment_id")

        if selected_id:
            _render_selected_actions(selected_id)
        else:
            st.info("Pilih satu eksperimen pada tabel untuk aksi & detail.")

    # ── Detail pop-up (flag pattern so interactive controls inside work) ──
    if st.session_state.get("_detail_id"):
        _detail_dialog(st.session_state["_detail_id"])

    # ── Auto-refresh the running dashboard (adaptive; paused while a detail
    #    dialog is open so the pop-up is not disrupted). Broker is not probed
    #    on every rerun — health is cached. No forced parallel execution. ──
    if running and auto and not st.session_state.get("_detail_id"):
        time.sleep(interval)
        st.rerun()
