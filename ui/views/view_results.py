"""Progress & Status page (main dashboard) — live progress of all in-flight
experiments on top, then the history table (AgGrid) below with a pop-up (dialog)
detail view built from the shared result components."""
from datetime import date, datetime, timezone
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
from orchestrator import run_mode as rm
from ui.components import experiment_table as et
from ui.components import dialogs as dlg


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


@st.cache_data(show_spinner=False)
def _pipeline_params() -> dict:
    """{pipeline_id: {param: nilai}} dari get_info() setiap pipeline terdaftar.

    Ini adalah CADANGAN, bukan sumber utama: eksperimen yang dijalankan sejak
    mode eksekusi ada membawa ``params_used`` sendiri, dan ``et.build_rows``
    memakainya lebih dulu. Fungsi ini hanya mengisi baris lama yang memang
    belum pernah mencatat parameternya. Nilainya bersifat DEFINISI — nilai pada
    kode saat ini — karena itu asal-usulnya selalu dinyatakan di UI
    (lihat ``et.PARAM_PROVENANCE``).
    Di-cache karena membangun instance pipeline tidak gratis.
    """
    out: dict[str, dict] = {}
    try:
        from config.pipeline_registry import PIPELINE_REGISTRY
    except Exception:                       # pragma: no cover - defensif
        return out
    for pid, meta in PIPELINE_REGISTRY.items():
        try:
            info = meta["class"]().get_info() or {}
        except Exception:                   # pipeline rusak != tabel rusak
            continue
        params = info.get("fixed_params")
        out[pid] = dict(params) if isinstance(params, dict) else {}
    return out


def _build_rows(experiments: list[dict]) -> list[dict]:
    """Baris tabel — memakai penyusun MURNI, pembaca artefak disuntikkan."""
    finished = {e.get("id"): e.get("completed_at") for e in experiments
                if e.get("status") == "FINISHED"}

    def _roc(eid):
        if eid not in finished:
            return None
        return _roc_auc(eid, finished[eid])

    rows = et.build_rows(experiments, roc_reader=_roc,
                         params_reader=_pipeline_params)
    return et.mark_best_within_family(rows)


_METRIC_FORMATTER = JsCode(
    "function(p){ if(p.value===null||p.value===undefined||isNaN(p.value)){return '-';} "
    "return Number(p.value).toFixed(4); }"
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
    """Sorot nilai terbaik. Flagnya dihitung PER KELUARGA pipeline di
    ``et.mark_best_within_family`` — bukan juara lintas keluarga."""
    return JsCode(
        f"function(params){{ if(params.data && params.data.{flag_field}){{ "
        f"return {{'backgroundColor':'#cce5ff','fontWeight':'600'}}; }} return null; }}"
    )


def _grid_dataframe(rows: list[dict], columns: list[dict]) -> pd.DataFrame:
    """DataFrame untuk AgGrid: metrik tetap numerik (agar pengurutan & format
    benar), sisanya teks siap-tampil."""
    data = []
    for row in rows:
        rec = {"_full_id": row["_id"]}
        for col in columns:
            if col["kind"] == et.KIND_METRIC:
                flag = et.best_flag_key(col["key"])
                rec[col["label"]] = row.get(col["key"])
                rec[flag] = bool(row.get(flag))
            else:
                rec[col["label"]] = et.cell_text(row, col)
        data.append(rec)
    return pd.DataFrame(data)


_COLUMN_WIDTHS = {"Pipeline": 210, "Berkas": 200, "Waktu": 150,
                  "Hash dataset": 130, "Dataset": 130, "Pemilik": 120}


def _build_grid_options(df: pd.DataFrame, columns: list[dict]) -> dict:
    """Header BERGRUP Identitas | Parameter | Metrik + centang multi-pilih."""
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(sortable=True, resizable=True, filterable=False)
    gb.configure_selection(selection_mode="multiple", use_checkbox=True)
    options = gb.build()

    grouped = et.columns_by_group(columns)
    col_defs, first_column = [], True
    for group in et.GROUP_ORDER:
        cols = grouped.get(group) or []
        if not cols:
            continue
        children = []
        for col in cols:
            spec = {"headerName": col["label"], "field": col["label"],
                    "width": _COLUMN_WIDTHS.get(col["label"], 120)}
            if col["kind"] == et.KIND_METRIC:
                spec.update({"type": "numericColumn",
                             "valueFormatter": _METRIC_FORMATTER,
                             "cellStyle": _hi_style(et.best_flag_key(col["key"]))})
            elif col["label"] == "Status":
                spec["cellStyle"] = _STATUS_STYLE
            if first_column:
                # Centang menempel pada kolom pertama yang tampil dan dipin ke
                # kiri agar tetap terlihat saat tabel digeser mendatar.
                spec.update({"checkboxSelection": True, "pinned": "left"})
                first_column = False
            children.append(spec)
        col_defs.append({"headerName": group, "children": children})

    options["columnDefs"] = col_defs
    options["suppressHorizontalScroll"] = False
    options["enableBrowserTooltips"] = True
    if len(df) > 20:
        options["pagination"] = True
        options["paginationPageSize"] = 20
    return options


# --- Kontrol riwayat: filter, pemilih kolom, ekspor ------------------------

_FILTER_KEY = "_hist_filters"
_COLUMNS_KEY = "_hist_columns"
_COMPARE_KEY = dlg.COMPARE_KEY


def _selected_columns(all_columns: list[dict]) -> list[str]:
    """Pilihan kolom pengguna, bertahan lewat session_state."""
    valid = {c["key"] for c in all_columns}
    chosen = st.session_state.get(_COLUMNS_KEY)
    if not isinstance(chosen, list):
        chosen = list(et.DEFAULT_COLUMNS)
    chosen = [k for k in chosen if k in valid]
    return chosen or [k for k in et.DEFAULT_COLUMNS if k in valid]


def _render_column_picker(all_columns: list[dict]) -> list[str]:
    """Pemilih kolom per grup. Pilihan disimpan sehingga tidak kembali ke
    default setiap kali pengguna berinteraksi dengan halaman."""
    current = _selected_columns(all_columns)
    grouped = et.columns_by_group(all_columns)

    with st.popover("Kolom", use_container_width=False):
        st.caption("Pilih kolom yang ditampilkan.")
        picked: list[str] = []
        for group in et.GROUP_ORDER:
            cols = grouped.get(group) or []
            if not cols:
                continue
            labels = {c["label"]: c["key"] for c in cols}
            default = [c["label"] for c in cols if c["key"] in current]
            chosen = st.multiselect(group, list(labels), default=default,
                                    key=f"_hist_cols_{group}")
            picked += [labels[label] for label in chosen]
        st.caption(et.PARAM_PROVENANCE)
        if st.button("Kembalikan ke set inti", key="_hist_cols_reset"):
            for group in et.GROUP_ORDER:
                st.session_state.pop(f"_hist_cols_{group}", None)
            st.session_state[_COLUMNS_KEY] = list(et.DEFAULT_COLUMNS)
            st.rerun()

    if picked:
        st.session_state[_COLUMNS_KEY] = picked
    return picked or current


def _render_filters(rows: list[dict]) -> dict:
    """Filter pipeline/dataset/status/rentang waktu. Menyaring data yang SUDAH
    dibaca — tidak ada kueri ulang ke basis data."""
    options = et.filter_options(rows)
    saved = st.session_state.get(_FILTER_KEY) or {}

    with st.popover("Filter", use_container_width=False):
        pipelines = st.multiselect("Pipeline", options["pipelines"],
                                   default=saved.get("pipelines") or [],
                                   key="_hist_f_pipeline")
        datasets = st.multiselect("Dataset", options["datasets"],
                                  default=saved.get("datasets") or [],
                                  key="_hist_f_dataset")
        statuses = st.multiselect("Status", options["statuses"],
                                  default=saved.get("statuses") or [],
                                  key="_hist_f_status")
        # Kosong = SEMUA mode. Run eksplorasi tidak pernah disembunyikan secara
        # bawaan — penyaringan mode adalah pilihan pengguna.
        modes = st.multiselect(
            "Mode eksekusi", options["modes"],
            default=saved.get("modes") or [],
            format_func=lambda m: et.MODE_FILTER_LABELS.get(m, m),
            key="_hist_f_mode",
            help=et.MODE_FILTER_DEFAULT_NOTE,
        )
        cols = st.columns(2)
        start = cols[0].date_input("Dari tanggal", value=saved.get("start"),
                                   key="_hist_f_start", format="YYYY-MM-DD")
        end = cols[1].date_input("Sampai tanggal", value=saved.get("end"),
                                 key="_hist_f_end", format="YYYY-MM-DD")
        if st.button("Bersihkan filter", key="_hist_f_clear"):
            for key in ("_hist_f_pipeline", "_hist_f_dataset", "_hist_f_status",
                        "_hist_f_mode", "_hist_f_start", "_hist_f_end"):
                st.session_state.pop(key, None)
            st.session_state.pop(_FILTER_KEY, None)
            st.rerun()

    filters = {"pipelines": pipelines, "datasets": datasets,
               "statuses": statuses, "modes": modes,
               "start": start if isinstance(start, date) else None,
               "end": end if isinstance(end, date) else None}
    st.session_state[_FILTER_KEY] = filters
    return filters


def _render_expression_search(rows: list[dict]) -> list[dict]:
    """Pencarian ekspresi sederhana pada metrik. Parser TERBATAS — tanpa
    eval/exec; ekspresi tak dikenal memberi pesan, bukan crash."""
    text = st.text_input("Cari metrik", value="", key="_hist_expr",
                         placeholder="mis. f1 > 0.8 and accuracy >= 0.9",
                         help=et.EXPR_HELP, label_visibility="collapsed")
    if not (text or "").strip():
        return rows
    try:
        terms = et.parse_expression(text)
    except et.ExpressionError as e:
        st.warning(str(e))
        return rows
    return et.apply_expression(rows, terms)


# --- Perbandingan berdampingan --------------------------------------------

def _comparison_body(rows: list[dict], param_keys: list[str]) -> None:
    data = et.build_comparison(rows, param_keys)

    # Peringatan WAJIB lebih dulu — sebelum satu angka pun terbaca.
    for warning in data["warnings"]:
        st.warning(warning)
    if data["note"]:
        st.caption(data["note"])

    header = "| Field | " + " | ".join(f"`{h}`" for h in data["headers"]) + " |"
    divider = "| --- " * (len(data["headers"]) + 1) + "|"
    for section in data["sections"]:
        st.markdown(f"**{section['group']}**")
        lines = [header, divider]
        for field in section["fields"]:
            # Baris yang BERBEDA ditebalkan + ditandai agar langsung terlihat.
            mark = "**" if field["differs"] else ""
            cells = " | ".join(f"{mark}{v}{mark}" for v in field["values"])
            label = ("Δ " if field["differs"] else "") + field["label"]
            lines.append(f"| {label} | {cells} |")
        st.markdown(chr(10).join(lines))
    # SATU baris penutup untuk seluruh tabel perbandingan: asal parameter +
    # arti penanda Δ. Sebelumnya asal parameter diulang di tiap bagian.
    st.caption(
        "Baris bertanda Δ berbeda antar eksperimen; tidak ada peringkat "
        "otomatis — penilaian mana yang lebih baik tetap milik pembaca. "
        + et.PARAM_PROVENANCE
    )

    if st.button("Tutup", key="_hist_cmp_close"):
        dlg.close_dialog(_COMPARE_KEY)
        st.rerun()


if hasattr(st, "dialog"):
    _comparison_dialog = dlg.dialog_decorator(
        "Bandingkan Eksperimen", _COMPARE_KEY, width="large")(_comparison_body)
else:                                       # pragma: no cover - Streamlit lama
    def _comparison_dialog(rows, param_keys):
        with st.expander("Bandingkan Eksperimen", expanded=True):
            _comparison_body(rows, param_keys)


def _maybe_render_comparison(rows: list[dict], param_keys: list[str]) -> None:
    """Dipanggil dari ALUR UTAMA render() — pola flag yang sama dengan dialog
    detail, sehingga kontrol di dalamnya bekerja."""
    ids = dlg.dialog_state(_COMPARE_KEY)
    if not ids:
        return
    chosen = [r for r in rows if r["_id"] in set(ids)]
    if len(chosen) < 2:                     # data berubah sejak tombol ditekan
        dlg.close_dialog(_COMPARE_KEY)
        return
    _comparison_dialog(chosen, param_keys)


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


@st.cache_data(show_spinner=False)
def _cached_pdf(experiment_id: str, completed_at, _payload: dict) -> bytes:
    """Bangun PDF SEKALI per eksperimen selesai.

    Sebelumnya laporan dibuat ulang pada setiap rerun modal, jadi menekan apa
    pun di dalamnya (tab, expander, tombol) menunggu satu render PDF penuh —
    itulah rasa tersendatnya. Eksperimen yang sudah FINISHED bersifat tetap,
    sehingga hasilnya aman di-cache; kuncinya menyertakan completed_at supaya
    re-run menghasilkan berkas baru. Jalur generatornya sendiri tidak diubah.
    """
    from utils.report_generator import generate_report
    return generate_report(**_payload)


def _pdf_download_button(exp: dict, metrics: dict, metadata: dict, key: str) -> None:
    """PDF download for a FINISHED experiment (unchanged generator path)."""
    try:
        from orchestrator.execution_service import get_pipeline_info
        pdf_bytes = _cached_pdf(exp["id"], exp.get("completed_at"), dict(
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
        ))
        st.download_button(
            "Download PDF Report", data=pdf_bytes,
            file_name=f"experiment_report_{exp['id'][:8]}.pdf",
            mime="application/pdf", key=key,
        )
    except Exception as e:  # never break the dialog on a PDF failure
        st.caption(f"PDF tidak dapat dibuat: {type(e).__name__}")


def _detail_payload(experiment_id: str) -> dict | None:
    """Baca eksperimen SEKALI lalu simpan untuk selama modal terbuka.

    Tanpa ini, `get_full_experiment` (DB + artefak) dibaca ulang pada setiap
    interaksi di dalam modal. Payload dibuang saat modal ditutup, jadi membuka
    eksperimen lain selalu membaca yang baru.
    """
    cached = dlg.payload(dlg.DETAIL_KEY)
    if isinstance(cached, dict) and cached.get("_id") == experiment_id:
        return cached.get("full")
    full = get_full_experiment(experiment_id)
    dlg.store_payload(dlg.DETAIL_KEY, {"_id": experiment_id, "full": full})
    return full


def _render_mode_details(exp: dict) -> None:
    """Mode + parameter yang dipakai + mana yang berbeda dari bawaan.

    Sumbernya berbeda tergantung usia record, dan perbedaan itu DINYATAKAN:
    eksperimen yang mencatat ``params_used`` menampilkan angka yang benar-benar
    dipakai saat itu; record lama menampilkan definisi pipeline pada kode saat
    ini, dengan keterangan bahwa parameternya memang belum pernah dicatat.
    """
    mode = rm.mode_of(exp)
    used = rm.params_of(exp)
    locked = rm.locked_params(exp.get("pipeline_id") or "")

    if rm.is_exploration(mode):
        st.warning(rm.EXPLORATION_WARNING)

    if not used:
        if locked:
            st.caption(
                "Parameter (definisi pipeline saat ini — eksperimen ini "
                f"dijalankan sebelum parameter dicatat per run): "
                f"{rm.format_params(locked)}"
            )
        return

    changed = rm.changed_keys(used, locked)
    st.caption("Parameter yang dipakai (direkam saat run): "
               + rm.format_params(used, locked))
    if changed:
        st.caption(f"Berbeda dari bawaan: {', '.join(f'`{k}`' for k in sorted(changed))}.")
    else:
        st.caption("Seluruh parameter sama dengan nilai terkunci pipeline.")


def _detail_dialog_body(experiment_id: str) -> None:
    """Pop-up detail view. Renders the SHARED interactive result component
    (zero duplication): confusion matrix, feature importance, ROC, learning
    curve / dual-holdout, static-figures expander — all defensive cases
    preserved for HIKARI and EVE-cbr."""
    full = _detail_payload(experiment_id)
    if not full:
        st.error("Eksperimen tidak ditemukan.")
        if st.button("Tutup", key=f"dlg_close_missing_{experiment_id}"):
            dlg.close_dialog(dlg.DETAIL_KEY)
            dlg.clear_payload(dlg.DETAIL_KEY)
            st.rerun()
        return

    exp = full["experiment"]
    metrics = full.get("metrics")
    metadata = full.get("metadata")

    st.markdown(f"**{exp['pipeline_id']}** · {exp['dataset_type']} · "
                f"`{exp['status']}` · {rm.run_mode_badge(exp.get('run_mode'))}")
    _render_mode_details(exp)
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
            dlg.close_dialog(dlg.DETAIL_KEY)
            dlg.clear_payload(dlg.DETAIL_KEY)
            st.rerun()
    if act[1].button("Re-run", key=f"dlg_rerun_{exp['id']}"):
        r = rerun_experiment(exp["id"])
        if r.get("success"):
            st.success(f"Baru: `{r['experiment_id'][:8]}…` — tutup dan segarkan.")
        else:
            st.error(r.get("error", "Gagal."))
    if act[2].button("Tutup", key=f"dlg_close_{exp['id']}"):
        dlg.close_dialog(dlg.DETAIL_KEY)
        dlg.clear_payload(dlg.DETAIL_KEY)
        st.rerun()


# Didekorasi lewat util supaya on_dismiss (tombol X / Esc / klik di luar) selalu
# terpasang — tanpa itu flagnya tetap hidup dan modal terbuka lagi tiap rerun.
_detail_dialog = dlg.dialog_decorator(
    "Detail Eksperimen", dlg.DETAIL_KEY, width="large")(_detail_dialog_body)


def _render_selected_actions(selected_id: str) -> None:
    """Compact action bar for the row selected in the history table."""
    full = get_full_experiment(selected_id)
    if not full:
        st.session_state.pop("selected_experiment_id", None)
        return
    exp = full["experiment"]
    # Mode ikut pada baris ringkas ini juga: tidak boleh ada tempat di mana
    # sebuah run eksplorasi terlihat seperti run resmi.
    st.markdown(f"**Terpilih:** `{exp['id'][:8]}` — {exp['pipeline_id']} · "
                f"`{exp['status']}` · {rm.run_mode_badge(exp.get('run_mode'))}")
    cols = st.columns(3)
    if cols[0].button("Lihat detail", key=f"open_{selected_id}", type="primary",
                      use_container_width=True):
        dlg.open_dialog(dlg.DETAIL_KEY, selected_id)
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


def _render_history(experiments: list[dict]) -> None:
    """Riwayat eksperimen: filter -> kolom bergrup -> bandingkan -> ekspor.

    Seluruh penyaringan berjalan pada data yang SUDAH dibaca sekali di
    ``render()``; tidak ada kueri tambahan ke basis data per interaksi.
    """
    all_rows = _build_rows(experiments)
    params_map = _pipeline_params()
    param_keys = et.parameter_keys(lambda: params_map)
    all_columns = et.build_columns(param_keys)

    bar = st.columns([1, 1, 3, 2])
    with bar[0]:
        filters = _render_filters(all_rows)
    with bar[1]:
        selected_keys = _render_column_picker(all_columns)
    with bar[2]:
        rows = _render_expression_search(all_rows)

    rows = et.apply_filters(rows, **filters)
    columns = et.visible_columns(all_columns, selected_keys)

    with bar[3]:
        st.download_button(
            "Unduh CSV", data=et.to_csv(rows, columns).encode("utf-8"),
            file_name=et.csv_filename(), mime="text/csv",
            use_container_width=True, key="_hist_csv",
            help="Mengikuti kolom & filter yang sedang aktif, lengkap dengan "
                 "keterangan semantik metrik per baris.",
        )

    st.caption(et.result_summary(len(rows), len(all_rows)))
    note = et.semantics_note(rows)
    if note:
        st.caption(note)

    if not rows:
        st.info("Tidak ada eksperimen yang cocok dengan filter. Bersihkan "
                "filter lewat tombol **Filter**.")
        st.session_state.pop("selected_experiment_id", None)
        return
    if not columns:
        st.warning("Tidak ada kolom yang dipilih. Pilih kolom lewat tombol "
                   "**Kolom**.")
        return

    df = _grid_dataframe(rows, columns)
    grid_response = AgGrid(
        df,
        gridOptions=_build_grid_options(df, columns),
        allow_unsafe_jscode=True,
        theme="streamlit",
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        fit_columns_on_grid_load=False,
        height=440,
        key="experiment_history_grid",
    )
    st.caption(et.BEST_MARK_NOTE)

    selected_ids = _selected_ids(grid_response)

    # Satu baris terpilih -> panel aksi lama (detail / re-run / batalkan).
    # Dua sampai lima -> perbandingan berdampingan.
    if len(selected_ids) == 1:
        st.session_state["selected_experiment_id"] = selected_ids[0]
    remembered = st.session_state.get("selected_experiment_id")

    cmp_cols = st.columns([2, 5])
    problem = et.compare_selection_error(selected_ids)
    if cmp_cols[0].button(f"Bandingkan terpilih ({len(selected_ids)})",
                          key="_hist_compare", use_container_width=True,
                          disabled=bool(problem)):
        dlg.open_dialog(_COMPARE_KEY, selected_ids)
        st.rerun()
    if problem and selected_ids:
        cmp_cols[1].caption(problem)
    elif not selected_ids:
        cmp_cols[1].caption(
            f"Centang 2-{et.MAX_COMPARE} eksperimen untuk membandingkannya, "
            f"atau satu baris untuk membuka detail & aksinya.")

    if len(selected_ids) <= 1 and remembered:
        _render_selected_actions(remembered)


def _selected_ids(grid_response) -> list[str]:
    """ID eksperimen yang dicentang. Bentuk kembalian AgGrid berbeda antar
    versi (DataFrame atau list), jadi keduanya ditangani."""
    sel = grid_response.get("selected_rows")
    if isinstance(sel, pd.DataFrame):
        if sel.empty or "_full_id" not in sel.columns:
            return []
        return [str(v) for v in sel["_full_id"].tolist()]
    if isinstance(sel, list):
        return [r.get("_full_id") for r in sel if r.get("_full_id")]
    return []


def render():
    st.title("Progress & Status")

    experiments = list_all_experiments()

    # -- Sedang Berjalan (live dashboard of ALL in-flight experiments) --
    running, auto, interval = _render_running_section(experiments)

    st.markdown("---")
    st.subheader("Riwayat Eksperimen")

    if not experiments:
        st.info("Belum ada eksperimen. Buka halaman 'Run Experiment' untuk membuat satu.")
        st.session_state.pop("selected_experiment_id", None)
    else:
        _render_history(experiments)

    # -- Pop-up detail & perbandingan (pola flag, dipanggil dari alur utama
    #    supaya kontrol interaktif di dalamnya bekerja) --
    if dlg.is_open(dlg.DETAIL_KEY):
        _detail_dialog(dlg.dialog_state(dlg.DETAIL_KEY))
    if experiments and dlg.is_open(_COMPARE_KEY):
        _maybe_render_comparison(_build_rows(experiments),
                                 et.parameter_keys(_pipeline_params))

    # -- Auto-refresh the running dashboard (adaptive; paused while a pop-up is
    #    open so it is not disrupted). Broker is not probed on every rerun --
    if (running and auto and not dlg.is_open(dlg.DETAIL_KEY)
            and not dlg.is_open(_COMPARE_KEY)):
        time.sleep(interval)
        st.rerun()
