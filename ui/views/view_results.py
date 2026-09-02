"""Progress & Status page (main dashboard) — live progress of all in-flight
experiments on top, then the history table (AgGrid) below with a pop-up (dialog)
detail view built from the shared result components."""
from datetime import date, datetime, timezone
from html import escape
import time

import streamlit as st

from ui.i18n import t
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
from ui.components.sections import prose
from ui.components.page_flags import wait_before_refresh

# Nama halaman ini di menu ui/app.py. Dipakai mengikat pembaruan
# berkala pada halamannya: begitu pengguna pindah, penggambaran
# ulang berhenti (eksperimennya sendiri tidak disentuh).
PAGE_NAME = 'Progress & Status'
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


def _build_rows(experiments: list[dict], *, with_roc: bool = True) -> list[dict]:
    """Baris tabel — memakai penyusun MURNI, pembaca artefak disuntikkan.

    ``with_roc=False`` MELEWATI pembacaan artefak sepenuhnya. ROC-AUC adalah
    satu-satunya nilai di tabel ini yang tidak ada di basis data: mengisinya
    berarti membuka `metrics.json` satu per satu untuk SETIAP eksperimen yang
    selesai. Kolomnya tidak termasuk set bawaan, jadi pada tampilan biasa
    puluhan pembacaan itu dilakukan untuk kolom yang tidak seorang pun lihat.
    """
    finished = ({e.get("id"): e.get("completed_at") for e in experiments
                 if e.get("status") == "FINISHED"} if with_roc else {})

    def _roc(eid):
        if eid not in finished:
            return None
        return _roc_auc(eid, finished[eid])

    rows = et.build_rows(experiments, roc_reader=_roc if with_roc else None,
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


_COLUMN_WIDTHS = {"pipeline": 210, "berkas": 200, "waktu": 150,
                  "dataset_hash": 130, "dataset": 130, "pemilik": 120}


def _build_grid_options(df: pd.DataFrame, columns: list[dict],
                        metric_tooltip: str = "") -> dict:
    """Header BERGRUP Identitas | Parameter | Metrik + centang multi-pilih.

    ``metric_tooltip`` menempel pada header SETIAP kolom metrik. Di situlah
    keterangan semantik metrik tinggal sekarang: menjelaskan angka tepat di
    kolom yang menampilkannya, bukan sebagai paragraf di bawah tabel.
    """
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
                    "width": _COLUMN_WIDTHS.get(col["key"], 120)}
            if col["kind"] == et.KIND_METRIC:
                spec.update({"type": "numericColumn",
                             "valueFormatter": _METRIC_FORMATTER,
                             "cellStyle": _hi_style(et.best_flag_key(col["key"]))})
                if metric_tooltip:
                    spec["headerTooltip"] = metric_tooltip
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

    with st.popover(t("ps.dlg_columns"), use_container_width=False):
        picked: list[str] = []
        for group in et.GROUP_ORDER:
            cols = grouped.get(group) or []
            if not cols:
                continue
            labels = {c["label"]: c["key"] for c in cols}
            default = [c["label"] for c in cols if c["key"] in current]
            chosen = st.multiselect(
                # Judul kelompok ikut bahasa; `key` tetap memakai PENGENAL
                # kelompok, jadi pilihan pengguna tidak hilang saat bahasa
                # diganti.
                et.group_label(group), list(labels), default=default,
                key=f"_hist_cols_{group}",
                # Asal-usul parameter menempel pada grup yang dijelaskannya,
                # bukan sebagai baris keterangan terpisah.
                help=(t(et.PARAM_PROVENANCE_KEY)
                      if group == et.GROUP_PARAM else None),
            )
            picked += [labels[label] for label in chosen]
        if st.button(t("ps.btn_core_columns"), key="_hist_cols_reset"):
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

    with st.popover(t("ps.dlg_filter"), use_container_width=False):
        pipelines = st.multiselect(t("ps.f_pipeline"), options["pipelines"],
                                   default=saved.get("pipelines") or [],
                                   key="_hist_f_pipeline")
        datasets = st.multiselect(t("ps.f_dataset"), options["datasets"],
                                  default=saved.get("datasets") or [],
                                  key="_hist_f_dataset")
        statuses = st.multiselect(t("ps.f_status"), options["statuses"],
                                  default=saved.get("statuses") or [],
                                  key="_hist_f_status")
        # Kosong = SEMUA mode. Run eksplorasi tidak pernah disembunyikan secara
        # bawaan — penyaringan mode adalah pilihan pengguna.
        modes = st.multiselect(
            t("ps.f_run_mode"), options["modes"],
            default=saved.get("modes") or [],
            format_func=lambda m: et.MODE_FILTER_LABELS.get(m, m),
            key="_hist_f_mode",
            help=t(et.MODE_FILTER_DEFAULT_NOTE_KEY),
        )
        cols = st.columns(2)
        start = cols[0].date_input(t("ps.f_date_from"), value=saved.get("start"),
                                   key="_hist_f_start", format="YYYY-MM-DD")
        end = cols[1].date_input(t("ps.f_date_to"), value=saved.get("end"),
                                 key="_hist_f_end", format="YYYY-MM-DD")
        if st.button(t("ps.btn_clear_filter"), key="_hist_f_clear"):
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
    text = st.text_input(t("ps.f_metric_search"), value="", key="_hist_expr",
                         placeholder=t("ps.f_metric_hint"),
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
#
# Tiga hal yang menentukan bentuk bagian ini:
#
# * **Hitung SEKALI.** Baris yang dibandingkan disimpan sebagai payload modal
#   saat modal DIBUKA. Setiap interaksi di dalamnya (mencentang "hanya yang
#   berbeda", membuang satu eksperimen) hanya menyusun ulang tabel dari data
#   yang sudah ada di memori — tidak ada pembacaan basis data atau artefak.
# * **Tabel selaras.** Dirender sebagai SATU tabel HTML dengan lebar kolom
#   seragam (`table-layout: fixed`), label rata kiri, angka rata kanan. Satu
#   tabel untuk semua kelompok, bukan satu tabel per kelompok — hanya dengan
#   begitu lebar kolomnya benar-benar sama di seluruh bagian.
# * **Peringatan tetap di atas.** Semantik metrik & campuran mode dirender
#   sebelum satu angka pun terbaca.

_CMP_ONLY_DIFF_KEY = "_hist_cmp_only_diff"

# Lebar kolom pertama (nama baris). SATU angka yang dipakai dua kali: oleh CSS
# tabel DAN oleh bobot `st.columns` baris aksi, sehingga tombol setiap
# eksperimen jatuh tepat di bawah kolomnya sendiri.
CMP_LABEL_WIDTH = 0.32

_CMP_CSS = """
<style>
/* SATU mekanisme untuk seluruh tabel di dialog ini: elemen tabel berkelas
   "ids-cmp".
   Lebar kolom, tinggi baris, padding, dan garis pemisah didefinisikan sekali
   di sini supaya tabel utama dan tabel aksi tidak mungkin tampil berbeda. */
.ids-cmp { width: 100%; border-collapse: collapse; table-layout: fixed;
           font-size: 0.9rem; }
.ids-cmp col.ids-cmp-labelcol { width: 32%; }
/* Tinggi baris & padding SERAGAM untuk th maupun td. */
.ids-cmp th, .ids-cmp td {
    padding: .38rem .5rem; line-height: 1.45; height: 2.2rem;
    vertical-align: middle;
    /* Nama panjang dipendekkan; nilai penuh ada di tooltip (atribut title). */
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    /* SATU gaya garis pemisah di seluruh tabel — tipis dan sama. */
    border-bottom: 1px solid rgba(127,127,127,.22);
}
.ids-cmp thead th { font-weight: 600; text-align: right; }
.ids-cmp .ids-cmp-label { text-align: left; }
/* Angka rata KANAN dengan angka lebar-tetap supaya digitnya sejajar. */
.ids-cmp td.ids-cmp-r { text-align: right;
    font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
.ids-cmp td.ids-cmp-l { text-align: left; }
/* Pemisah kelompok: dibedakan lewat latar & huruf kecil-besar, BUKAN lewat
   garis yang lebih tebal — supaya tidak ada campuran garis tebal & tipis. */
.ids-cmp tr.ids-cmp-group td {
    font-weight: 600; font-size: .8rem; letter-spacing: .03em;
    text-transform: uppercase; opacity: .72;
    background: rgba(127,127,127,.07);
}
/* Baris yang BERBEDA disorot; yang sama dibiarkan tenang. */
.ids-cmp tr.ids-cmp-diff td { background: rgba(127,127,127,.13);
           font-weight: 600; }
.ids-cmp tr.ids-cmp-diff td.ids-cmp-label::before {
           content: "\0394\00a0"; opacity: .65; }
</style>
"""


def _comparison_payload(ids: list[str], rows: list[dict],
                        param_keys: list[str]) -> dict:
    """Baris + kunci parameter untuk modal, DISUSUN SEKALI saat modal dibuka.

    Payload dibuang saat modal ditutup, jadi membuka perbandingan lain selalu
    menyusun yang baru. Selama modal terbuka, isinya tidak pernah disusun ulang
    — mencentang "hanya yang berbeda" atau membuang satu eksperimen bekerja atas
    data yang sudah ada di memori.
    """
    cached = dlg.payload(_COMPARE_KEY)
    if isinstance(cached, dict) and cached.get("_ids") == list(ids):
        return cached
    chosen = [r for r in rows if r["_id"] in set(ids)]
    fresh = {"_ids": list(ids), "rows": chosen, "param_keys": list(param_keys)}
    dlg.store_payload(_COMPARE_KEY, fresh)
    return fresh


def _drop_from_comparison(experiment_id: str) -> None:
    """Buang satu eksperimen dari perbandingan — tanpa membaca ulang apa pun.

    Flag dan payload diperbarui bersama: flag menjaga modal tetap terbuka,
    payload menyediakan barisnya. Bila tinggal satu, modal ditutup dan flagnya
    dibersihkan — membandingkan satu eksperimen tidak ada artinya.
    """
    payload = dlg.payload(_COMPARE_KEY) or {}
    rows = et.drop_from_comparison(payload.get("rows") or [], experiment_id)
    if len(rows) < 2:
        dlg.close_dialog(_COMPARE_KEY)
        dlg.clear_payload(_COMPARE_KEY)
        return
    ids = [r["_id"] for r in rows]
    st.session_state[_COMPARE_KEY] = ids
    dlg.store_payload(_COMPARE_KEY,
                      {"_ids": ids, "rows": rows,
                       "param_keys": payload.get("param_keys") or []})


def _close_comparison() -> None:
    """Bersihkan flag + payload perbandingan. Dipakai semua jalur keluar."""
    dlg.close_dialog(_COMPARE_KEY)
    dlg.clear_payload(_COMPARE_KEY)


def _cell_html(value, css_class: str, *, tag: str = "td") -> str:
    """Satu sel: dipendekkan bila panjang, nilai penuh selalu di tooltip.

    Elipsis dilakukan CSS (`text-overflow`), sementara `title` membawa teks
    lengkapnya — jadi kolom yang sempit tidak pernah menghilangkan informasi.
    """
    text = str(value)
    return (f'<{tag} class="{css_class}" title="{escape(text)}">'
            f'{escape(text)}</{tag}>')


def comparison_table_html(data: dict) -> str:
    """Tabel perbandingan sebagai SATU blok HTML yang selaras."""
    headers = data["headers"]
    cols = ('<colgroup><col class="ids-cmp-labelcol" />'
            + '<col />' * len(headers) + '</colgroup>')
    head = ('<thead><tr>'
            + _cell_html("Field", "ids-cmp-label", tag="th")
            + "".join(_cell_html(h, "", tag="th") for h in headers)
            + "</tr></thead>")

    body: list[str] = []
    for section in data["sections"]:
        body.append(
            f'<tr class="ids-cmp-group"><td colspan="{len(headers) + 1}">'
            f'{escape(str(section.get("group_label") or section["group"]))}'
            f'</td></tr>')
        for field in section["fields"]:
            row_class = "ids-cmp-diff" if field["differs"] else ""
            align = "ids-cmp-r" if field["align"] == et.ALIGN_RIGHT else "ids-cmp-l"
            cells = "".join(_cell_html(v, align) for v in field["values"])
            body.append(
                f'<tr class="{row_class}">'
                + _cell_html(field["label"], "ids-cmp-label")
                + f'{cells}</tr>')

    return (f'<div class="ids-cmp-scroll"><table class="ids-cmp">{cols}{head}'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def comparison_column_weights(count: int) -> list[float]:
    """Bobot `st.columns` yang SEJAJAR dengan kolom tabel di atasnya.

    Diturunkan dari :data:`CMP_LABEL_WIDTH` yang sama dengan yang dipakai CSS,
    jadi baris aksi tidak mungkin melenceng dari tabelnya.
    """
    count = max(int(count), 1)
    return [CMP_LABEL_WIDTH] + [(1.0 - CMP_LABEL_WIDTH) / count] * count


def comparison_actions_html(rows) -> str:
    """Baris identitas eksperimen — tabel yang SAMA mekanismenya.

    Sebelumnya bagian ini memakai `st.columns` + markdown per baris, sehingga
    lebar kolom, tinggi baris, dan garisnya tidak pernah cocok dengan tabel
    utama. Sekarang ia tabel `ids-cmp` juga; hanya tombolnya yang tetap widget
    Streamlit (HTML tidak bisa memuat tombol), dan tombol itu memakai bobot
    kolom yang sama sehingga jatuh tepat di bawah kolomnya.
    """
    headers = [r.get("id", "—") for r in rows]
    cols = ('<colgroup><col class="ids-cmp-labelcol" />'
            + '<col />' * len(headers) + '</colgroup>')
    body = []
    for label, key in ((t("ps.cmp_row_pipeline"), "pipeline"),
                       (t("ps.cmp_row_mode"), "mode")):
        body.append(
            "<tr>" + _cell_html(label, "ids-cmp-label")
            + "".join(_cell_html(r.get(key, "—"), "ids-cmp-l") for r in rows)
            + "</tr>")
    head = ('<thead><tr>'
            + _cell_html(t("ps.cmp_col_experiment"), "ids-cmp-label",
                         tag="th")
            + "".join(_cell_html(h, "", tag="th") for h in headers)
            + "</tr></thead>")
    return (f'<div class="ids-cmp-scroll"><table class="ids-cmp">{cols}{head}'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _comparison_body(ids: list[str], rows: list[dict],
                     param_keys: list[str]) -> None:
    payload = _comparison_payload(ids, rows, param_keys)
    chosen = payload["rows"]

    # Peringatan WAJIB lebih dulu — sebelum satu angka pun terbaca.
    for warning in et.comparison_warnings(chosen):
        st.warning(warning)
    note = et.semantics_note(chosen)
    if note:
        st.markdown(note)

    only_diff = st.checkbox(t(et.ONLY_DIFF_LABEL_KEY), key=_CMP_ONLY_DIFF_KEY,
                            help=t("ps.cmp_hide_same"))
    data = et.build_comparison(chosen, payload["param_keys"],
                               only_differences=only_diff)

    if not data["sections"]:
        st.info(t(et.ALL_SAME_NOTE_KEY))
    else:
        st.html(_CMP_CSS + comparison_table_html(data))

    prose(t("ps.cmp_reading", diff=data["diff_count"],
              total=data["total_count"])
          + " " + t(et.PARAM_PROVENANCE_KEY),
          key="cmp_reading")

    # Aksi per eksperimen. Identitasnya memakai tabel yang SAMA dengan di atas,
    # dan tombolnya memakai bobot kolom yang sama sehingga sejajar dengannya.
    st.divider()
    st.markdown(t("ps.cmp_manage"))
    st.html(_CMP_CSS + comparison_actions_html(chosen))

    weights = comparison_column_weights(len(chosen))
    detail_cols = st.columns(weights)
    detail_cols[0].markdown(t("ps.btn_open_detail"))
    for index, row in enumerate(chosen, start=1):
        if detail_cols[index].button(
                t("ps.btn_open_short"), key=f"_cmp_open_{row['_id']}",
                use_container_width=True,
                help=t("ps.help_open_detail", id=row["id"])):
            # Perbandingan ditutup lebih dulu supaya ia tidak terbuka kembali
            # di belakang modal detail pada rerun berikutnya.
            _close_comparison()
            dlg.open_dialog(dlg.DETAIL_KEY, row["_id"])
            st.rerun()

    too_few = len(chosen) <= 2
    drop_cols = st.columns(weights)
    drop_cols[0].markdown(t("ps.btn_drop_compare"))
    for index, row in enumerate(chosen, start=1):
        if drop_cols[index].button(
                t("ps.btn_drop_short"), key=f"_cmp_drop_{row['_id']}",
                use_container_width=True,
                help=(t("ps.help_drop_too_few") if too_few
                      else t("ps.help_drop", id=row["id"]))):
            _drop_from_comparison(row["_id"])
            st.rerun()

    if st.button("Tutup", key="_hist_cmp_close"):
        _close_comparison()
        st.rerun()


def _comparison_dialog(ids, rows, param_keys):
    """Modal perbandingan, judulnya disusun pada bahasa yang sedang aktif."""
    if hasattr(st, "dialog"):
        dlg.dialog_decorator(t("ps.dlg_compare"), _COMPARE_KEY,
                             width="large")(_comparison_body)(
            ids, rows, param_keys)
        return
    with st.expander(t("ps.dlg_compare"), expanded=True):  # pragma: no cover
        _comparison_body(ids, rows, param_keys)


def _maybe_render_comparison(rows: list[dict], param_keys: list[str]) -> None:
    """Dipanggil dari ALUR UTAMA render() — pola flag yang sama dengan dialog
    detail, sehingga kontrol di dalamnya bekerja."""
    ids = dlg.dialog_state(_COMPARE_KEY)
    if not ids:
        # Flag sudah bersih: payload ikut dibuang supaya perbandingan berikutnya
        # tidak pernah memakai baris lama.
        dlg.clear_payload(_COMPARE_KEY)
        return
    if len([r for r in rows if r["_id"] in set(ids)]) < 2:
        dlg.close_dialog(_COMPARE_KEY)      # data berubah sejak tombol ditekan
        dlg.clear_payload(_COMPARE_KEY)
        return
    _comparison_dialog(list(ids), rows, param_keys)


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
    head[0].subheader(t("ps.running_title"))
    if hasattr(head[1], "toggle"):
        auto = head[1].toggle("Auto-refresh", value=True, key="_dash_auto")
    else:
        auto = head[1].checkbox("Auto-refresh", value=True, key="_dash_auto")
    if head[2].button(t("ps.btn_refresh_now"), use_container_width=True, key="_dash_refresh"):
        st.session_state["_dash_nonce"] = st.session_state.get("_dash_nonce", 0) + 1
        st.rerun()

    if not running:
        st.info(t("ps.empty_running"))
        return running, bool(auto), 6

    health = _dash_health(st.session_state.get("_dash_nonce", 0))
    async_mode = health.get("mode") == "async"
    can_read_progress = (not async_mode) or bool(health.get("broker_ok"))
    if async_mode and not health.get("broker_ok", True):
        st.warning(t("ps.msg_broker_down"))

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
            _mulai = (e.get("started_at") or e.get("created_at") or "-")[:19]
            top[0].markdown(
                f"**{e.get('pipeline_id', '?')}** · {e.get('dataset_type', '?')} · "
                f"mulai {_mulai} · elapsed {format_elapsed(el)}")
            top[1].markdown(f"`{cur_status}`")
            if pv["overall_percent"] is not None:
                st.progress(min(max(pv["overall_percent"], 0), 100) / 100.0,
                            text=f"Progres keseluruhan: {pv['overall_percent']}%")
            if pv["stage_label"]:
                st.markdown(f"**{pv['stage_label']}**")
            elif e.get("status") == "QUEUED":
                st.markdown(t("ps.msg_waiting_worker"))
            else:
                st.markdown(t("ps.msg_no_granular"))
            if st.button(t("ps.btn_cancel_short"), key=f"dash_cancel_{eid}"):
                r = cancel_experiment(eid)
                if r.get("success"):
                    st.warning(t("ps.msg_cancelled"))
                else:
                    st.error(r.get("message") or t("ps.msg_cancel_failed"))
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
            t("ps.btn_pdf"), data=pdf_bytes,
            file_name=f"experiment_report_{exp['id'][:8]}.pdf",
            mime="application/pdf", key=key,
        )
    except Exception as e:  # never break the dialog on a PDF failure
        st.caption(t("ps.msg_pdf_failed_kind", kind=type(e).__name__))


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
    # Daftar berkas artefak disiapkan DI SINI juga. Sebelumnya ia disusun di
    # dalam badan modal, sehingga direktori artefak ditelusuri ulang (plus
    # `stat` per berkas) pada SETIAP interaksi di dalam modal — padahal isinya
    # tidak berubah selama modal terbuka.
    dlg.store_payload(dlg.DETAIL_KEY, {
        "_id": experiment_id, "full": full,
        "files": _build_artifact_files(experiment_id) if full else {},
    })
    return full


def _detail_artifact_files(experiment_id: str) -> dict:
    """Berkas artefak yang sudah disiapkan saat modal dibuka."""
    cached = dlg.payload(dlg.DETAIL_KEY)
    if isinstance(cached, dict) and cached.get("_id") == experiment_id:
        return cached.get("files") or {}
    return {}


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
            st.caption(t("ps.params_legacy_line",
                          params=rm.format_params(locked)))
        return

    changed = rm.changed_keys(used, locked)
    st.caption(t("ps.params_used_line",
                 params=rm.format_params(used, locked)))
    if changed:
        st.caption(t("ps.params_differs_line",
                     keys=", ".join(f"`{k}`" for k in sorted(changed))))
    else:
        st.caption(t("ps.params_locked"))


def _detail_dialog_body(experiment_id: str) -> None:
    """Pop-up detail view. Renders the SHARED interactive result component
    (zero duplication): confusion matrix, feature importance, ROC, learning
    curve / dual-holdout, static-figures expander — all defensive cases
    preserved for HIKARI and EVE-cbr."""
    full = _detail_payload(experiment_id)
    if not full:
        st.error(t("ps.msg_not_found"))
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
    st.caption(t("ps.detail_identity", id=exp["id"],
                 created=(exp.get("created_at") or "-")[:19],
                 completed=(exp.get("completed_at") or "-")[:19]))
    # Ketertelusuran pipeline TERUNGGAH: versi + SHA-256 berkasnya. Pipeline
    # bawaan tidak menampilkan apa-apa di sini — definisinya ada di git.
    if exp.get("pipeline_version") or exp.get("pipeline_hash"):
        st.caption(t(
            "ps.detail_traceability",
            version=exp.get("pipeline_version") or "-",
            pipeline_hash=(exp.get("pipeline_hash") or "-")[:16],
            dataset_hash=(exp.get("dataset_hash") or "-")[:16]))

    if exp["status"] == "FINISHED" and metrics:
        payload = normalize_result_payload(
            experiment_id=exp["id"], metrics=metrics, metadata=metadata,
            pipeline_id=exp.get("pipeline_id"), dataset_type=exp.get("dataset_type"),
        )
        render_results(payload, key=f"dlg_{exp['id']}", pipeline_id=exp.get("pipeline_id", ""))
        _pdf_download_button(exp, metrics, metadata, key=f"dlgpdf_{exp['id']}")
        with st.expander(t("ps.exp_artifact_viewer"), expanded=False):
            files = _detail_artifact_files(exp["id"])
            if files:
                render_file_browser(files, state_key=f"dlg_artifacts_{exp['id']}")
            else:
                st.info(t("ps.empty_artifacts"))
    elif exp["status"] == "FAILED":
        em = exp.get("error_message", "Unknown")
        if em == "Cancelled by user":
            st.warning(t("ps.msg_cancelled_by_user"))
        else:
            st.error(t("ps.msg_failed_with", error=em))
    else:
        st.info(t("ps.msg_status_no_result", status=exp["status"]))

    st.markdown("---")
    act = st.columns(3)
    if exp["status"] in ("QUEUED", "RUNNING"):
        if act[0].button(t("ps.btn_cancel_short"),
                         key=f"dlg_cancel_{exp['id']}"):
            cancel_experiment(exp["id"])
            dlg.close_dialog(dlg.DETAIL_KEY)
            dlg.clear_payload(dlg.DETAIL_KEY)
            st.rerun()
    if act[1].button(t("ps.btn_rerun"), key=f"dlg_rerun_{exp['id']}"):
        r = rerun_experiment(exp["id"])
        if r.get("success"):
            st.success(t("ps.msg_rerun_started",
                         id=r["experiment_id"][:8]))
        else:
            st.error(r.get("error") or t("ps.msg_failed_short"))
    if act[2].button("Tutup", key=f"dlg_close_{exp['id']}"):
        dlg.close_dialog(dlg.DETAIL_KEY)
        dlg.clear_payload(dlg.DETAIL_KEY)
        st.rerun()


# Didekorasi lewat util supaya on_dismiss (tombol X / Esc / klik di luar) selalu
# terpasang — tanpa itu flagnya tetap hidup dan modal terbuka lagi tiap rerun.
# Didekorasi SAAT DIPANGGIL: judul yang disusun di tingkat modul akan membeku
# pada bahasa yang kebetulan aktif ketika modul ini diimpor.
def _detail_dialog(experiment_id):
    """Modal detail, judulnya disusun pada bahasa yang sedang aktif."""
    dlg.dialog_decorator(t("ps.dlg_detail_title"), dlg.DETAIL_KEY,
                         width="large")(_detail_dialog_body)(experiment_id)


def _render_selected_actions(selected_id: str) -> None:
    """Compact action bar for the row selected in the history table."""
    full = get_full_experiment(selected_id)
    if not full:
        st.session_state.pop("selected_experiment_id", None)
        return
    exp = full["experiment"]
    # Mode ikut pada baris ringkas ini juga: tidak boleh ada tempat di mana
    # sebuah run eksplorasi terlihat seperti run resmi.
    st.markdown(t("ps.detail_selected_line", id=exp["id"][:8],
                  pipeline=exp["pipeline_id"], status=exp["status"],
                  badge=rm.run_mode_badge(exp.get("run_mode"))))
    cols = st.columns(3)
    if cols[0].button(t("ps.btn_detail"), key=f"open_{selected_id}", type="primary",
                      use_container_width=True):
        dlg.open_dialog(dlg.DETAIL_KEY, selected_id)
        st.rerun()
    if cols[1].button(t("ps.btn_rerun"), key=f"rerun_{selected_id}", use_container_width=True):
        r = rerun_experiment(selected_id)
        if r.get("success"):
            st.success(t("ps.msg_rerun_refresh",
                         id=r["experiment_id"][:8]))
        else:
            st.error(r.get("error") or t("ps.msg_failed_short"))
    if exp["status"] in ("QUEUED", "RUNNING"):
        if cols[2].button(t("ps.btn_cancel_short"), key=f"cancel_{selected_id}",
                          use_container_width=True):
            cancel_experiment(selected_id)
            st.rerun()


def _roc_column_visible() -> bool:
    """Apakah kolom ROC-AUC termasuk yang sedang ditampilkan?

    Dibaca dari pilihan kolom yang tersimpan, SEBELUM baris disusun — sehingga
    artefak hanya dibuka bila nilainya memang akan terlihat.
    """
    chosen = st.session_state.get(_COLUMNS_KEY)
    return "auc" in (chosen if chosen is not None else et.DEFAULT_COLUMNS)


def _render_history(experiments: list[dict], all_rows: list[dict]) -> None:
    """Riwayat eksperimen: filter -> kolom bergrup -> bandingkan -> ekspor.

    Seluruh penyaringan berjalan pada data yang SUDAH dibaca sekali di
    ``render()``; tidak ada kueri tambahan ke basis data per interaksi.
    ``all_rows`` disusun pemanggil supaya penyusunannya tidak terjadi dua kali.
    """
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
            t("ps.btn_csv"), data=et.to_csv(rows, columns).encode("utf-8"),
            file_name=et.csv_filename(), mime="text/csv",
            use_container_width=True, key="_hist_csv",
            # Jumlah baris yang sedang tampil menempel di sini karena tombol
            # ini mengikuti filter yang persis sama.
            help=t("ps.help_csv_summary",
                   summary=et.result_summary(len(rows), len(all_rows))),
        )

    # Tidak ada lagi baris ringkasan di bawah kontrol. Semantik metrik (WAJIB)
    # dan arti sorotan pindah ke tooltip header kolom metrik — menjelaskan
    # angkanya di tempat angka itu dibaca.
    metric_tooltip = " ".join(part for part in
                              (et.semantics_note(rows),
                               t(et.BEST_MARK_NOTE_KEY))
                              if part)

    if not rows:
        st.info(t("ps.empty_filtered"))
        st.session_state.pop("selected_experiment_id", None)
        return
    if not columns:
        st.warning(t("ps.empty_columns"))
        return

    df = _grid_dataframe(rows, columns)
    grid_response = AgGrid(
        df,
        gridOptions=_build_grid_options(df, columns, metric_tooltip),
        allow_unsafe_jscode=True,
        theme="streamlit",
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        fit_columns_on_grid_load=False,
        height=440,
        key="experiment_history_grid",
    )
    selected_ids = _selected_ids(grid_response)

    # Satu baris terpilih -> panel aksi lama (detail / re-run / batalkan).
    # Dua sampai lima -> perbandingan berdampingan.
    if len(selected_ids) == 1:
        st.session_state["selected_experiment_id"] = selected_ids[0]
    remembered = st.session_state.get("selected_experiment_id")

    cmp_cols = st.columns([2, 5])
    problem = et.compare_selection_error(selected_ids)
    # Sebab tombol tidak aktif (WAJIB tetap tersampaikan) menempel pada tombol
    # itu sendiri, bukan sebagai baris keterangan di sebelahnya.
    if cmp_cols[0].button(
            t("ps.btn_compare_selected", count=len(selected_ids)),
            key="_hist_compare", use_container_width=True,
            disabled=bool(problem),
            help=problem or t("ps.help_compare_hint", max=et.MAX_COMPARE)):
        dlg.open_dialog(_COMPARE_KEY, selected_ids)
        st.rerun()

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
    st.title(t("page.progress"))

    experiments = list_all_experiments()

    # -- Sedang Berjalan (live dashboard of ALL in-flight experiments) --
    running, auto, interval = _render_running_section(experiments)

    st.markdown("---")
    st.subheader(t("ps.history_title"))

    if not experiments:
        st.info(t("ps.empty_history_alt"))
        st.session_state.pop("selected_experiment_id", None)
        all_rows = []
    else:
        # Baris disusun SEKALI di sini lalu dipakai ulang oleh riwayat dan
        # dialog perbandingan. Sebelumnya keduanya memanggil `_build_rows`
        # sendiri-sendiri, jadi seluruh pekerjaannya dikerjakan dua kali setiap
        # kali dialog terbuka.
        all_rows = _build_rows(experiments, with_roc=_roc_column_visible())
        _render_history(experiments, all_rows)

    # -- Pop-up detail & perbandingan (pola flag, dipanggil dari alur utama
    #    supaya kontrol interaktif di dalamnya bekerja) --
    if dlg.is_open(dlg.DETAIL_KEY):
        _detail_dialog(dlg.dialog_state(dlg.DETAIL_KEY))
    if experiments and dlg.is_open(_COMPARE_KEY):
        _maybe_render_comparison(all_rows, et.parameter_keys(_pipeline_params))

    # -- Auto-refresh the running dashboard (adaptive; paused while a pop-up is
    #    open so it is not disrupted). Broker is not probed on every rerun --
    if (running and auto and not dlg.is_open(dlg.DETAIL_KEY)
            and not dlg.is_open(_COMPARE_KEY)):
        # Sama seperti pemantauan di halaman Run Experiment: jeda yang dapat
        # disela dan terikat pada halaman ini, sehingga berpindah halaman tidak
        # menahan klik pengguna dan tidak meninggalkan sisa gambar.
        if wait_before_refresh(interval, page=PAGE_NAME):
            st.rerun()
