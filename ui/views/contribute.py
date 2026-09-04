"""
Halaman "Add Pipeline & Dataset".

Dua jalur kontribusi, dipilih lewat dua kartu di tampilan awal:

  • **Unggah Pipeline** — instruksi persyaratan → unggah beberapa berkas `.py`
    → penjelasan per berkas + metadata → validasi statis seluruh paket →
    laporan rinci → (bila valid) unduh + cuplikan entri registry + panduan
    aktivasi manual.
  • **Unggah Dataset** — persyaratan dataset → unggah berkas → simpan ke
    `storage/datasets/` (nama disanitasi, menimpa ditolak) → diagnosa
    kecocokan yang SUDAH ADA (sampling + cache) terhadap tiap research pipeline.

⚠️ SECURITY (lanjutan Tahap 1–3, tidak dilemahkan):
  - Berkas `.py` yang diunggah TIDAK PERNAH diimpor/`exec`/dijalankan. Seluruh
    pemeriksaan statis lewat `orchestrator/pipeline_validator.py` (`ast.parse`).
  - SETIAP berkas dalam paket divalidasi penuh, bukan hanya entry point-nya —
    berkas pendukung ikut dieksekusi saat pipeline berjalan nanti, jadi
    kegagalan keamanan di berkas mana pun menggagalkan seluruh paket.
  - Registry tetap STATIS. Tidak ada tombol aktivasi, tidak ada penulisan ke
    `config/pipeline_registry.py` maupun ke `pipelines/`.

Logika yang dipakai ulang (tanpa duplikasi): `ui/components/pipeline_upload.py`
untuk validasi paket/cuplikan registry, `orchestrator/dataset_diagnostics.py`
untuk diagnosa dataset, dan penyaji persyaratan/verdict dataset milik halaman
Run Experiment.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import streamlit as st

from ui.i18n import t

from config.research_attribution import get_research_short_label
from config.settings import DATASETS_DIR, STORAGE_DIR
from contracts.dataset_schemas import supported_datasets
from database.models import (
    ALL_ROLES, KIND_DATASET, KIND_PIPELINE, ROLE_CONTRIBUTOR,
    ROLE_RESEARCH_ADMIN, STATUS_ACTIVE, STATUS_DISABLED, STATUS_PENDING,
    SUBMISSION_PENDING, role_label,
)
from orchestrator.auth_service import (
    AuthError, PermissionDenied, can_approve, can_manage_users, can_upload,
    create_user_as, list_users, require_upload, set_user_role, set_user_status,
)
from config.settings import DATASETS_DIR
from database import trials as trial_db
from orchestrator import trial_service
from orchestrator.trial_service import DATASET_TYPE_UNREGISTERED
from ui.i18n import CATALOG
from orchestrator.submission_service import (
    approve_submission, list_submissions, read_submission_sources,
    reject_submission, submit_dataset, submit_pipeline,
)
# Konstanta kontrak & keamanan dibaca LANGSUNG dari validator supaya panduan di
# halaman ini tidak pernah menyimpang dari aturan yang benar-benar ditegakkan.
from orchestrator.pipeline_validator import (
    ALLOWED_MODULES, BASE_CLASS_NAME, EXPECTED_INFO_KEYS, FORBIDDEN_CALLS,
    FORBIDDEN_MODULES, REQUIRED_METHODS, RUN_FIRST_PARAM, RUN_PROGRESS_PARAM,
)
from ui.components.pipeline_upload import (
    GROUP_SECURITY, GROUP_STRUCTURE, MAX_UPLOAD_BYTES, ROLE_ENTRY,
    ROLE_SUPPORT,
    extract_registry_metadata,
    review_package, safe_staging_name, save_to_staging,
)
from ui.components.instructions import (
    render_dataset_instructions, render_pipeline_instructions,
)
from ui.components import submission_review as sr
from ui.components.contribute_context import render_page_context
from ui.components import tables as tbl
from ui.components.validator_messages import (
    check_message, error_message,
)
from ui.components.sections import prose, render_facts, render_section
from utils.timestamps import now_iso
from ui.components.upload_cards import render_upload_cards
from ui.views._artifact_browser import format_size
from ui.views.login import current_user, render_login_prompt

logger = logging.getLogger(__name__)

_MODE_KEY = "_contrib_mode"
_RESULT_KEY = "_contrib_pkg_result"
_FORM_KEY = "_contrib_pkg_form"

# Batas unggah peramban. Harus SEJALAN dengan server.maxUploadSize di
# .streamlit/config.toml (dalam MB) — Streamlit menolak lebih dulu di sisi
# server bila nilainya lebih kecil.
MAX_DATASET_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024        # 5 GB

# Potongan awal berkas yang ditulis ke berkas sementara untuk didiagnosa.
# Diagnosa hanya mencuplik 50.000 baris (± 27–30 MB pada dataset di repo ini),
# jadi menyalin SELURUH unggahan 5 GB ke disk hanya untuk diperiksa itu sia-sia.
# Prefix dipotong pada newline terakhir supaya tidak ada baris terpenggal.
DIAGNOSIS_PREFIX_BYTES = 96 * 1024 * 1024                # 96 MB
_COPY_CHUNK_BYTES = 4 * 1024 * 1024                      # 4 MB per tulis

# Berkas sementara untuk diagnosa. DI DALAM proyek (agar lolos path-safety
# resolve_dataset_path) tetapi BUKAN storage/datasets/ — isinya selalu dihapus
# setelah diagnosa selesai.
UPLOAD_TMP_DIR = Path(STORAGE_DIR) / "_upload_tmp"

_DS_DIAG_KEY = "_contrib_ds_diag"

_STATUS_ICON = {"pass": "✔", "warn": "⚠", "fail": "✖"}


#: Penanda "pembacaan ini GAGAL" — dibedakan dari nilai kosong yang sah.
#: `None` sudah berarti "tidak ada uji terakhir", jadi memakainya untuk
#: kegagalan akan menampilkan "belum pernah diuji" pada keadaan yang
#: sebenarnya "tidak dapat dibaca" — dua hal yang tindakannya berbeda.
_UNREADABLE = object()


def _safe_read(what: str, fn, *args, default=None, **kwargs):
    """Bacaan yang TIDAK BOLEH menjatuhkan halaman.

    Jalur uji coba membaca basis data dan disk di beberapa titik yang bukan
    aksi pengguna — riwayat uji terakhir, gerbang persetujuan. Sebuah
    ``sqlite3.OperationalError`` di sana tidak tertangkap penangan mana pun,
    sehingga Streamlit menampilkan jejak teknis mentah kepada peninjau.

    Di sini pembacaan seperti itu diberi satu bentuk: nilai cadangan yang
    dinyatakan pemanggil, dan rincian LENGKAP ke log pengembang. Pemanggil
    memutuskan sendiri apa arti nilai cadangan itu — untuk gerbang, artinya
    fail-closed (lihat pemakaiannya).
    """
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("Pembacaan gagal pada alur peninjauan: %s", what)
        return default


# ── Tampilan awal: dua kartu kontribusi ───────────────────────────────────

def _render_choice_boxes() -> None:
    user = current_user()

    # Konteks lebih dulu: keadaan platform → status & hak pengguna → apa yang
    # terjadi setelah mengunggah. Panel ini juga yang menampilkan ajakan masuk
    # bagi pengunjung, jadi tidak ada dua ajakan berturut-turut di sini.
    render_page_context(user)
    st.divider()

    # Empat kartu seragam: dua jalur unggah + dua jalur pengelolaan. Ketiga
    # bendera di sini HANYA menghidupkan/mematikan tombol — izin sebenarnya
    # tetap ditegakkan `require_upload`/`require_approve`/`require_manage_users`
    # di fungsi aksinya, jadi tombol yang hidup pun tidak melewati pemeriksaan.
    mode = render_upload_cards(
        may_upload=bool(can_upload(user)),
        may_approve=bool(can_approve(user)),
        may_manage_users=bool(can_manage_users(user)),
        signed_in=bool(user),
        counts=_admin_queue_notes(user),
    )
    if mode:
        st.session_state[_MODE_KEY] = mode
        st.rerun()

    _render_my_submissions()


def _admin_queue_notes(user: dict | None) -> dict:
    """Baris jumlah antrean pada kartu admin — hanya dibaca bila memang berhak.

    Dipisah dari perenderan supaya kartu tetap bebas dari pembacaan basis data,
    dan supaya pengguna tanpa hak tidak memicu kueri apa pun.
    """
    notes: dict[str, str] = {}
    if can_approve(user):
        try:
            n = len(list_submissions(status=SUBMISSION_PENDING))
            notes["review"] = t("ap.review_pending_count", count=n)
        except Exception:                   # pragma: no cover - defensive
            pass
    return notes


# ── Pengajuan: milik sendiri & peninjauan ─────────────────────────────────

# Status pengajuan adalah PENGENAL di basis data; hanya labelnya dipetakan.
# Kuncinya sudah ada — dipakai bersama `render_submission_counts`.
_STATUS_LABEL_KEYS = {
    SUBMISSION_PENDING: "ap.sub_pending",
    "approved": "ap.sub_approved",
    "rejected": "ap.sub_rejected",
}


def _status_label(status: str) -> str:
    """Label status pengajuan pada bahasa aktif."""
    key = _STATUS_LABEL_KEYS.get(status)
    return t(key) if key else status


def _my_submission_columns():
    """Kolom "Pengajuan saya" — jenis kolom yang sama dengan tabel lain.

    FUNGSI, bukan konstanta: konstanta modul dievaluasi sekali saat impor, jadi
    judul kolomnya akan terkunci pada bahasa yang kebetulan aktif saat itu dan
    tidak pernah ikut berganti. Pola yang sama dipakai `sidebar_progress`.
    """
    return (
        tbl.column("#", "id", kind=tbl.KIND_MARK, width="4.5rem"),
        tbl.column(t("ap.col_file"), "filename", kind=tbl.KIND_NAME),
        tbl.column(t("ap.col_kind"), "kind", kind=tbl.KIND_STATUS),
        tbl.column(t("ap.col_status"), "status", kind=tbl.KIND_STATUS),
        tbl.column(t("ap.col_time"), "when", kind=tbl.KIND_TIME),
        tbl.column(t("ap.lbl_review_note"), "note"),
    )


def _render_my_submissions() -> None:
    """Status pengajuan milik pengguna yang sedang masuk."""
    user = current_user()
    if not can_upload(user):
        return
    try:
        mine = list_submissions(submitted_by=user["username"])
    except Exception as e:                  # pragma: no cover - defensive
        st.warning(f"Daftar pengajuan tidak dapat dibaca: {e}")
        return
    if not mine:
        return

    st.divider()
    st.markdown("Pengajuan saya")
    # Tabel yang SAMA dengan tabel lain di halaman ini. Dulu satu baris markdown
    # per pengajuan, dipotong diam-diam pada 10 — pembaca tidak pernah tahu ada
    # berapa seluruhnya. `limit` kini menyebutkan totalnya.
    rows = [{
        "id": f"#{item['id']}",
        "filename": item["original_filename"],
        "kind": item["kind"],
        "status": _status_label(item["status"]),
        "when": item.get("submitted_at") or "",
        "note": item.get("review_note") or "",
    } for item in mine]
    tbl.render_table(_my_submission_columns(), rows, limit=10,
                     empty=t("ap.my_submissions_empty"))


# ── Penanda daftar peninjauan ─────────────────────────────────────────────
# Semuanya berawalan `_contrib`, jadi ``page_flags.VIEW_STATE_PREFIXES`` sudah
# membuangnya saat pengguna berpindah halaman — tidak perlu mekanisme baru,
# dan tidak ada daftar nama kedua yang bisa ketinggalan.
_OPEN_KEY = "_contrib_review_open"       # id pengajuan yang sedang dibuka
_QUERY_KEY = "_contrib_review_query"
_SORT_KEY = "_contrib_review_sort"
_PAGE_KEY = "_contrib_review_page"


def _open_submission(submission_id: int) -> None:
    """Buka satu pengajuan. Dipanggil dari CALLBACK tombol/pemilih."""
    st.session_state[_OPEN_KEY] = submission_id


def _close_submission() -> None:
    """Kembali ke daftar. Penyaring & halaman SENGAJA tidak disentuh, supaya
    peninjau kembali ke tempat yang sama dengan saat ia membuka."""
    st.session_state.pop(_OPEN_KEY, None)


def _render_pending_list(pending: list, user: dict) -> None:
    """Daftar antrean: cari, urutkan, penggal, lalu buka satu.

    Urutan langkahnya menentukan biayanya. Menyaring dan memenggal dikerjakan
    atas kolom baris pengajuan APA ADANYA; pemeriksaan statis — yang membaca
    seluruh berkas sebuah paket — baru dijalankan untuk baris yang benar-benar
    tampil di halaman ini. Jadi yang dibayar satu render mengikuti ukuran
    halaman, bukan panjang antrean.
    """
    render_section(t("ap.sec_pending", count=len(pending)),
                   help=t("ap.help_only_pipelines_reviewed"))

    controls = st.columns([3, 2])
    query = controls[0].text_input(t("ap.lbl_search_queue"), key=_QUERY_KEY,
                                   placeholder=t("ap.ph_search_queue"))
    sort_labels = {sr.SORT_OLDEST: t("ap.sort_oldest"),
                   sr.SORT_NEWEST: t("ap.sort_newest")}
    sort = controls[1].selectbox(
        t("ap.lbl_sort_queue"), list(sort_labels), key=_SORT_KEY,
        format_func=lambda value: sort_labels[value])

    matched = sr.order_pending(sr.filter_pending(pending, query), sort)
    last_page = sr.page_count(len(matched))
    page = min(int(st.session_state.get(_PAGE_KEY, 1) or 1), last_page)
    visible = sr.page_slice(matched, page)

    # Pemeriksaan statis HANYA untuk baris yang tampil.
    def _reviewed(item):
        return _reviewed_package(item["id"], item.get("file_hash") or "", item)

    tbl.render_table(sr.PENDING_COLUMNS, sr.pending_table_rows(visible, _reviewed),
                     empty=t(sr.EMPTY_STATE_KEY))

    # Jumlah hasil DINYATAKAN: penyaring tidak boleh menyembunyikan antrean
    # tanpa disadari.
    shown, total = sr.result_note(len(visible), len(pending))
    st.caption(t("ap.queue_count", shown=shown, total=total))

    if last_page > 1:
        nav = st.columns([1, 2, 1])
        nav[0].button(t("ap.btn_prev_page"), key="review_prev",
                      disabled=page <= 1, use_container_width=True,
                      on_click=lambda: st.session_state.update(
                          {_PAGE_KEY: page - 1}))
        nav[1].markdown(t("ap.page_of", page=page, total=last_page))
        nav[2].button(t("ap.btn_next_page"), key="review_next",
                      disabled=page >= last_page, use_container_width=True,
                      on_click=lambda: st.session_state.update(
                          {_PAGE_KEY: page + 1}))

    if not visible:
        return

    # MEMBUKA satu pengajuan. Tabel di atas digambar sebagai HTML supaya gaya,
    # kolom, dan terjemahannya tetap satu dengan tabel lain di aplikasi ini —
    # dan HTML tidak dapat memuat widget, jadi pemilihannya diletakkan di
    # sini sebagai satu kontrol, bukan satu tombol per baris.
    labels = {row["id"]: sr.summary_line(row)
              for row in sr.pending_table_rows(visible, _reviewed)}
    chosen = st.selectbox(
        t("ap.lbl_open_submission"), list(labels), index=None,
        placeholder=t("ap.ph_open_submission"),
        format_func=lambda sid: labels[sid], key="review_pick")
    if chosen is not None:
        _open_submission(chosen)
        st.rerun()


def _render_pending_section(pending: list, user: dict) -> None:
    """Bagian "Menunggu tinjauan" — daftar antrean, atau SATU pengajuan.

    Judul bagiannya memakai pola baku yang sama dengan "Aktif" dan "Riwayat
    versi", jadi ketiganya terbaca sebagai bagian yang setara.

    Bentuknya master-detail: daftar dan detail TIDAK PERNAH tergambar
    bersamaan. Itu bukan soal selera tata letak — expander Streamlit selalu
    merender isinya dan tidak mengekspos status terbuka, sehingga satu kartu
    per pengajuan berarti setiap pengajuan membaca berkas paketnya pada SETIAP
    penggambaran ulang, sepanjang apa pun antreannya. Dengan detail yang
    menggantikan daftar, yang dibaca hanya pengajuan yang benar-benar dibuka.
    """
    from ui.views import manage_pipelines as mp

    # Dua kejujuran WAJIB, satu baris — dipakai apa adanya dari modul penyaji.
    # Ditulis SEKALI, di atas percabangan, sehingga ia tampil pada daftar
    # MAUPUN detail. Di detail-lah keputusan setujui/tolak benar-benar diambil,
    # jadi justru di sana peringatan "pemeriksaannya statis, keputusannya
    # manusia" paling perlu terbaca.
    prose(f"{t(mp.STATIC_CHECK_NOTE_KEY)} {t(mp.NEW_VERSION_NOTE_KEY)}",
          key="review_notes")

    open_id = st.session_state.get(_OPEN_KEY)
    item = next((s for s in pending if s["id"] == open_id), None)
    if open_id is not None and item is None:
        # Sudah tidak di antrean (baru saja diputuskan, atau antreannya
        # berubah). Kembali ke daftar alih-alih menggambar halaman kosong.
        _close_submission()

    if item is None:
        _render_pending_list(pending, user)
        return

    # ── Detail satu pengajuan ────────────────────────────────────────────
    st.button(t("ap.btn_back_to_queue"), key="review_back",
              on_click=_close_submission)

    # Uji terakhirnya dibaca untuk SATU pengajuan — bukan untuk seluruh
    # antrean, dan bukan sekali per kartu seperti sebelumnya.
    trials = _safe_read("uji terakhir pengajuan", trial_db.latest_trials_for,
                        [item["id"]], default=None)
    latest = _UNREADABLE if trials is None else trials.get(item["id"])
    _render_submission_review_card(item, user, latest)


def _render_review_flow() -> None:
    """Peninjauan pengajuan + pengelolaan pipeline kontribusi.

    Sub-tampilan ini memuat TIGA bagian: **Menunggu tinjauan**, **Aktif**, dan
    **Riwayat versi**. Dua yang terakhir beserta penyunting dan perbandingan
    versinya disajikan modul ``ui/views/manage_pipelines``; fungsinya DIPANGGIL,
    bukan disalin ke sini.

    Ketiganya dipisahkan segmented control di atas — SATU bagian tampil pada
    satu waktu (alasannya ditulis di ``manage_pipelines``). Keadaan tiap bagian
    hidup di ``session_state`` dan tidak dibuang oleh perpindahan.

    Pembagian isinya mengikuti apa yang dibicarakan, bukan urutan kemunculan:

    * **Menunggu tinjauan** — segalanya tentang PENGAJUAN: antrean pipeline,
      sisa pengajuan dataset lama, dan riwayat pengajuan yang sudah diputuskan.
    * **Aktif** dan **Riwayat versi** — tentang PIPELINE TERDAFTAR.

    Sampai perbaikan ini, klaim "satu bagian pada satu waktu" hanya berlaku
    untuk dua bagian terakhir: jalur "Menunggu tinjauan" tidak berhenti setelah
    antreannya, melainkan menggambar Aktif dan Riwayat versi sekali lagi di
    bawahnya, sehingga bagian itu memuat semuanya sekaligus.

    Izin diperiksa DI SINI dan sekali lagi di dalam ``approve_submission`` /
    ``reject_submission`` / ``save_new_version``, jadi menyembunyikan tombol
    tidak pernah menjadi satu-satunya penghalang.
    """
    from ui.views import manage_pipelines as mp
    user = current_user()
    st.subheader(t("ap.sec_review"))
    if not can_approve(user):
        st.error(t("ap.denied_review"))
        return

    try:
        waiting = list_submissions(status=SUBMISSION_PENDING)
    except Exception as e:                  # pragma: no cover - defensive
        st.error(f"Gagal membaca antrean: {e}")
        return

    # Hanya PIPELINE yang ditinjau: isinya kode yang akan dieksekusi. Dataset
    # tersimpan langsung, jadi tidak pernah masuk antrean ini lagi.
    # TERLAMA MENUNGGU LEBIH DULU — antrean tinjauan, bukan tumpukan.
    pending = sr.sort_pending([s for s in waiting if s["kind"] == KIND_PIPELINE])
    active_count = len(mp.active_rows())
    section = mp.render_section_switch(len(pending), active_count)

    if section == mp.SECTION_ACTIVE:
        mp.render_active(user)
        return
    if section == mp.SECTION_HISTORY:
        mp.render_history()
        return

    # Mulai di sini SELURUHNYA milik bagian "Menunggu tinjauan". Ketiga bagian
    # berbicara tentang dua hal yang berbeda, dan pembagiannya mengikuti itu:
    #
    #   Menunggu tinjauan  → tentang PENGAJUAN (antrean, sisa dataset lama,
    #                        dan riwayat pengajuan yang sudah diputuskan)
    #   Aktif & Riwayat versi → tentang PIPELINE TERDAFTAR
    #
    # Sebelumnya bagian ini juga menggambar Aktif dan Riwayat versi di
    # bawahnya, sehingga satu-satunya bagian yang benar-benar "satu bagian
    # pada satu waktu" adalah dua bagian lainnya.
    _render_pending_section(pending, user)

    # Data lama: pengajuan dataset yang terlanjur menunggu sebelum aturan ini
    # berubah. Tidak dibuang — disetujui lewat jalur yang sudah ada, sehingga
    # berkasnya pindah ke storage/datasets/ dan tidak ada yang hilang.
    legacy = [s for s in waiting if s["kind"] == KIND_DATASET]
    if legacy:
        st.divider()
        prose(
            t("ap.msg_legacy_dataset_submission"), key="legacy_dataset")
        for item in legacy:
            cols = st.columns([5, 2])
            cols[0].markdown(f"`#{item['id']}` **{item['original_filename']}**")
            if cols[1].button(t("ap.btn_finish"), key=f"legacy_ds_{item['id']}",
                              use_container_width=True):
                try:
                    approve_submission(item["id"], actor=user,
                                       note="Diselesaikan: dataset tidak lagi "
                                            "memerlukan persetujuan.")
                except Exception as e:
                    st.error(f"Gagal menyelesaikan: {e}")
                else:
                    st.success(f"#{item['id']} selesai — berkas masuk ke "
                               f"storage/datasets/.")
                    st.rerun()

    st.divider()
    history = [s for s in list_submissions() if s["status"] != SUBMISSION_PENDING]
    st.markdown(t("ap.review_history_heading")
                + ("" if history else t("ap.review_history_empty")))
    for item in history[:15]:
        # SATU baris per pengajuan yang sudah ditinjau (sebelumnya 4 caption).
        note = f" · {item['review_note']}" if item.get("review_note") else ""
        st.markdown(
            f"`#{item['id']}` **{item['original_filename']}** — {item['kind']} · "
            f"{_status_label(item['status'])} · "
            f"oleh {item.get('reviewed_by') or '-'}{note}")


@st.cache_data(ttl=60, show_spinner=False)
def _reviewed_package(submission_id: int, file_hash: str, _item: dict) -> dict:
    """Pemeriksaan STATIS berkas tersimpan, dihitung sekali per pengajuan.

    Kuncinya (id, hash titik masuk) tidak berubah selama pengajuan itu belum
    diputuskan, jadi membuka/menutup kartu tidak memicu validasi ulang. Tidak
    ada kode pengajuan yang di-import maupun dijalankan di sini.
    """
    return sr.review_stored_package(_item)


def _render_check_groups(entry: dict) -> None:
    """Rincian pemeriksaan satu berkas, dikelompokkan Struktur & Keamanan."""
    groups = entry.get("groups") or {}
    _render_group(GROUP_STRUCTURE, groups.get(GROUP_STRUCTURE) or [])
    _render_group(GROUP_SECURITY, groups.get(GROUP_SECURITY) or [])


# ── Langkah UJI COBA (sebelum keputusan) ──────────────────────────────────

def _trial_dataset_options() -> list[tuple[str, str]]:
    """[(path, dataset_type)] dataset yang tersedia di platform.

    Urutan pasangannya PENTING dan sengaja disebut di sini: pembacanya
    mengembalikan (jalur, jenis), dan membongkarnya terbalik membuat daftar
    pilihan mengirimkan JENIS sebagai jalur berkas — cacat yang tidak terlihat
    sampai uji coba benar-benar dijalankan. Sebuah test mengunci urutan ini.
    """
    from ui.views.run_experiment import _dataset_options_cached

    try:
        options, _sizes = _dataset_options_cached(0, str(DATASETS_DIR))
    except Exception:                        # pragma: no cover - defensif
        logger.exception("Daftar dataset uji tidak terbaca")
        return []
    return [(path, dtype) for path, dtype in options]


def _render_trial_compatibility(dataset_type: str, dataset_path: str) -> None:
    """Ringkasan kecocokan dataset — memakai diagnosa yang SUDAH ADA.

    Tujuannya mencegah uji coba yang gagal hanya karena datasetnya jelas tidak
    cocok: kegagalan seperti itu tidak mengatakan apa pun tentang pipelinenya.
    """
    from orchestrator.dataset_diagnostics import diagnose_dataset
    from ui.components.validator_messages import diagnostic_message, diagnostic_title

    st.markdown(f"**{t('trial.compat_heading')}**")
    try:
        report = diagnose_dataset(dataset_path, dataset_type)
    except Exception:
        st.caption(t("trial.compat_unavailable"))
        return
    # `diagnose_dataset` mengembalikan DICT (ramah cache/JSON), bukan objek.
    checks = (report or {}).get("checks") or []
    if not checks:
        st.caption(t("trial.compat_unavailable"))
        return
    mark = {"pass": "✔", "warn": "⚠", "fail": "✖"}
    lines = []
    for check in checks:
        status = (check or {}).get("status") or ""
        lines.append(f"- {mark.get(status, '·')} **{diagnostic_title(check)}** "
                     f"— {diagnostic_message(check)}")
    st.markdown("\n".join(lines))


def _render_trial_outcome(trial: dict) -> None:
    """Hasil satu uji coba, apa adanya.

    Kegagalan dilaporkan LENGKAP: tahap, jenis, dan pesannya. Itulah yang
    dicari peninjau — "uji gagal" saja tidak menolong siapa pun.
    """
    st.caption(t("trial.tested_by", who=trial["started_by"],
                 when=(trial.get("started_at") or "")[:19],
                 dataset=trial.get("dataset_type") or "—"))
    if trial["status"] == trial_db.STATUS_PASSED:
        st.success(t("trial.result_passed",
                     rows=trial.get("rows_used") or "—",
                     seconds=trial.get("duration_s") or "—"))
        metrics = trial.get("metrics") or {}
        if metrics:
            render_facts([(name, f"{value:.4f}"
                           if isinstance(value, float) else str(value))
                          for name, value in metrics.items()])
        else:
            st.caption(t("trial.no_metrics"))
        return
    # Tahap & pesan diterjemahkan lebih dulu. Menyisipkannya mentah membuat
    # satu kalimat memuat dua bahasa — cacat yang sama dengan catatan kaki
    # metrik pada laporan PDF.
    from ui.components.validator_messages import (
        trial_failure_message, trial_stage,
    )

    st.error(t("trial.result_failed",
               stage=trial_stage(trial.get("error_stage")) or "—"))
    st.markdown(t("trial.failure_detail",
                  kind=trial.get("error_kind") or "—",
                  message=trial_failure_message(
                      trial.get("error_kind"),
                      trial.get("error_message")) or "—"))


def _render_trial_step(item: dict, user: dict | None,
                       latest=_UNREADABLE) -> None:
    """Pilih dataset → lihat kecocokan → jalankan uji → baca hasilnya.

    ``latest`` OPSIONAL: uji terakhir pengajuan ini yang sudah diambil bersama
    seluruh antrean dalam satu kueri. Bila tidak diberikan, ia dibaca di sini
    seperti sebelumnya.
    """
    st.markdown(f"**{t('trial.heading')}**")
    limits = trial_service.TRIAL_LIMITS
    st.caption(t("trial.intro", rows=f"{limits['max_rows']:,}".replace(",", "."),
                 seconds=limits["max_seconds"]))

    blocker = trial_service.trial_blocker(item)
    if blocker:
        st.info(t(blocker))
        return

    # Jenis yang dimiliki pengajuan ini SENDIRI — tanpa berkas platform.
    # Ditentukan SEKALI di sini lalu dipakai ulang: ia menjawab dua pertanyaan
    # yang selama ini ditanyakan terpisah (adakah kekurangan yang perlu
    # ditulis, dan jenis apa yang dipakai lampiran), dan tanpa berkas terpilih
    # ia juga jawaban yang sama dengan yang dipakai gerbang. Sebelumnya
    # keduanya memicu pembacaan berkas paket masing-masing.
    intrinsic_type = trial_service.resolve_dataset_type(
        item, trial_service.SOURCE_ATTACHED, None)

    # Ketiadaan dataset target dinyatakan sebagai KEKURANGAN, bukan dibiarkan
    # ditemukan sendiri saat tombol ditekan.
    if not intrinsic_type:
        st.caption(t("td.missing_dataset_type"))

    from orchestrator.trial_dataset_service import attachment_of, human_size

    attachment = attachment_of(item)

    # Sumber dataset. Lampiran hanya ditawarkan bila memang ada — pengajuan
    # tanpa lampiran tetap dapat diuji lewat dataset platform (Tahap 1).
    sources = [trial_service.SOURCE_PLATFORM]
    if attachment:
        sources.append(trial_service.SOURCE_ATTACHED)
    source_labels = {
        trial_service.SOURCE_PLATFORM: t("td.source_platform"),
        trial_service.SOURCE_ATTACHED: t("td.source_attached"),
    }
    source = st.radio(
        t("td.lbl_source"), sources, horizontal=True,
        format_func=lambda value: source_labels[value],
        key=f"trial_src_{item['id']}")
    if not attachment:
        st.caption(t("td.no_attachment_hint"))

    picked = None
    if source == trial_service.SOURCE_ATTACHED:
        # Keterangan lampiran ditampilkan SEBELUM dijalankan, supaya peninjau
        # tahu berkas apa yang akan dipakai.
        st.markdown(t("td.attachment_facts",
                      filename=attachment.get("filename") or "—",
                      size=human_size(attachment.get("size") or 0),
                      when=(attachment.get("uploaded_at") or "")[:19]))
        if attachment.get("note"):
            st.caption(t("td.contributor_note", note=attachment["note"]))
        st.caption(t("td.sample_caveat"))
        # Jenis untuk lampiran datang dari PENENTU yang sama — lampiran tidak
        # punya jenis sendiri, ia memakai jenis pipeline yang sedang diuji.
        # Itu PERSIS pertanyaan yang sudah dijawab `intrinsic_type` di atas
        # (sumber lampiran, tanpa jalur berkas), jadi dipakai ulang.
        attached_type = intrinsic_type
        if attached_type:
            _render_trial_compatibility(attached_type,
                                        attachment.get("stored_path") or "")
        resolved_type = attached_type
        ready = True
    else:
        options = _trial_dataset_options()
        if not options:
            st.info(t("trial.compat_unavailable"))
            return
        # Nilai pilihan adalah JALUR berkas; labelnya nama berkas yang terbaca
        # manusia. Jenisnya TIDAK dipakai sebagai nilai pilihan — ia ditentukan
        # `resolve_dataset_type`, satu-satunya penentu.
        names = {path: Path(path).name for path, _dtype in options}
        picked = st.selectbox(
            t("trial.lbl_dataset"), list(names),
            index=None, placeholder=t("trial.ph_dataset"),
            format_func=lambda path: names.get(path, path),
            key=f"trial_ds_{item['id']}")
        if picked:
            # Hanya DI SINI penentuan ulang benar-benar diperlukan: berkas yang
            # dipilih adalah sumber paling berwenang, dan ia baru diketahui
            # sekarang. Tanpa berkas terpilih, jawabannya sama dengan
            # `intrinsic_type` — langkah (i) tidak menghasilkan apa pun.
            resolved_type = trial_service.resolve_dataset_type(
                item, source, picked)
            if resolved_type:
                _render_trial_compatibility(resolved_type, picked)
        else:
            resolved_type = intrinsic_type
        ready = bool(picked)

    # Gerbang jenis dataset — berlaku pada KEDUA jalur. Tombol yang pasti
    # gagal tidak boleh aktif, dan alasannya selalu dinyatakan. Kunci pesannya
    # tetap diputuskan penentu, bukan di sini — yang disodorkan hanya hasil
    # penentuan yang sudah dilakukan di atas.
    type_blocker = trial_service.dataset_type_blocker(
        item, source, picked, resolved=resolved_type)
    if type_blocker:
        st.warning(t(type_blocker))

    blocked = bool(type_blocker) or not ready
    if st.button(t("trial.btn_run"), key=f"trial_run_{item['id']}",
                 disabled=blocked, use_container_width=True,
                 help=t(type_blocker) if type_blocker else None):
        with st.spinner(t("trial.running")):
            try:
                trial_service.run_trial(
                    item["id"], dataset_path=picked, actor=user,
                    source=source)
            except (AuthError, trial_service.TrialError) as e:
                # Kesalahan yang MEMANG dikenali alur: pesannya sudah layak
                # ditampilkan apa adanya.
                st.error(error_message(e))
            except Exception as e:
                # Apa pun sisanya — termasuk kesalahan basis data — tidak boleh
                # sampai ke pengguna sebagai jejak teknis. Rinciannya LENGKAP
                # di log pengembang; yang tampil adalah kalimat yang dapat
                # dipahami.
                logger.exception(
                    "Uji coba pengajuan #%s gagal tak terduga "
                    "(source=%s, dataset_path=%r)",
                    item["id"], source, picked)
                st.error(t("td.err_trial_failed", kind=type(e).__name__))
            else:
                st.rerun()

    # Riwayat uji terakhir. Bila pemanggil sudah mengambilnya bersama seluruh
    # antrean, nilai itu dipakai; kalau tidak, dibaca di sini seperti dulu.
    # Kegagalan membacanya tidak boleh menjatuhkan seluruh kartu peninjauan —
    # bagian lain kartu ini masih berguna, jadi yang hilang hanya bagian
    # riwayatnya, dan itu dikatakan.
    if latest is _UNREADABLE:
        latest = _safe_read("riwayat uji terakhir", trial_db.latest_trial,
                            item["id"], default=_UNREADABLE)
    if latest is _UNREADABLE:
        st.caption(t("trial.err_history_unreadable"))
    elif latest:
        _render_trial_outcome(latest)
        # Uji yang sudah tidak berlaku dikatakan APA ADANYA di sebelah
        # hasilnya, supaya hasil "BERHASIL" yang basi tidak terbaca sebagai
        # izin untuk menyetujui.
        fingerprint = _safe_read("sidik jari paket",
                                 trial_service.submission_fingerprint, item,
                                 default=None)
        if (latest["status"] == trial_db.STATUS_PASSED
                and fingerprint is not None
                and latest["package_hash"] != fingerprint):
            st.warning(t("trial.gate_stale"))


def _render_file_review(row: dict) -> None:
    """Satu berkas paket: peran, ukuran, penjelasan pengunggah, temuan, kode."""
    entry = row["entry"]
    mark = "✔" if row["ok"] else "✖"
    size = f" · {format_size(row['size'])}" if row.get("size") else ""
    header = f"{mark} {row['filename']} · {row['role']}{size}"

    with st.expander(header, expanded=not row["ok"]):
        # Penjelasan PENGUNGGAH — konteks yang paling membantu peninjau, dan
        # selama ini hanya ada di dalam blob JSON.
        if row["description"]:
            st.markdown(f"Penjelasan pengunggah: {row['description']}")

        if not entry.get("ok"):
            st.error(entry.get("error") or "Berkas tidak dapat diperiksa.")
            return

        if row["role"] == ROLE_SUPPORT:
            st.markdown(t("ap.note_support_file"))

        _render_check_groups(entry)

        lines = sr.finding_lines(entry)
        if lines:
            st.markdown("Temuan ada di baris: "
                        + ", ".join(f"**{n}**" for n in lines)
                        + " — nomornya tercetak di sisi kiri kode.")

        # Kode dengan NOMOR BARIS, dalam wadah yang dapat digulir sehingga
        # berkas panjang tidak mendominasi layar.
        source = entry.get("source") or ""
        with st.container(height=320, border=True):
            st.code(sr.numbered_source(source), language="python")
        st.download_button(
            t("ap.btn_download_file"), data=source.encode("utf-8"),
            file_name=row["filename"], mime="text/x-python",
            key=f"review_dl_{row['filename']}_{id(entry)}",
            help=t("ap.help_open_outside"))


def _render_submission_review_card(item: dict, user: dict,
                                   latest=_UNREADABLE) -> None:
    """Satu pengajuan: identitas, berkas, pemeriksaan, kode, keputusan.

    Seluruh isinya berasal dari pengajuan yang TERSIMPAN. Kode hanya
    ditampilkan sebagai teks — tidak pernah di-import maupun dijalankan.

    ``latest`` OPSIONAL: uji terakhir pengajuan ini, sudah diambil pemanggil
    (lihat ``database.trials.latest_trials_for``). Tanpa itu, kartu ini membaca
    sendiri.

    Dipanggil untuk pengajuan yang BENAR-BENAR DIBUKA saja — satu pada satu
    waktu. Wadahnya tetap expander, tetapi kini terbuka sejak awal: peninjau
    sudah memilih pengajuan ini, jadi menyuruhnya mengklik sekali lagi untuk
    melihat isinya tidak menambah apa pun.
    """
    reviewed = _reviewed_package(item["id"], item.get("file_hash") or "", item)
    row = sr.summary_row(item, reviewed)

    with st.expander(sr.summary_line(row), expanded=True):
        # 1. Identitas & metadata — pasangan label–nilai ringkas.
        render_facts(sr.metadata_rows(item))

        # 2 & 3. Berkas paket: SELURUHNYA, titik masuk lebih dulu.
        files = sr.file_rows(item, reviewed)
        st.markdown(f"**Berkas paket** — {len(files)}, "
                    f"{row['verdict_text']}.")
        for file_row in files:
            _render_file_review(file_row)

        warnings = sr.warning_checks(reviewed)
        if warnings:
            st.warning(t(sr.WARNING_REMINDER_KEY))

        # 4. Uji coba — SEBELUM keputusan, karena ia syarat persetujuan.
        st.divider()
        _render_trial_step(item, user, latest)

        # 5. Keputusan.
        st.divider()
        options = list(supported_datasets())
        meta_type = (item.get("metadata") or {}).get("dataset_type")
        chosen_type = st.selectbox(
            t("ap.lbl_target_dataset"), options,
            index=options.index(meta_type) if meta_type in options else None,
            format_func=_dataset_label, placeholder=t("ap.ph_target_dataset"),
            key=f"review_dtype_{item['id']}",
            help=t("ap.help_dataset_type"),
        )
        note = st.text_input(
            t("ap.lbl_review_note"), key=f"review_note_{item['id']}",
            placeholder=t("ap.ph_review_note"))
        st.markdown(t(sr.APPROVAL_CONSEQUENCE_KEY))

        # Alasan tombol nonaktif SELALU dinyatakan — tombol mati tanpa
        # keterangan membuat peninjau menebak apa yang kurang.
        # Gerbang persetujuan membaca basis data DAN disk. Bila pembacaannya
        # gagal, jawabannya adalah MENUTUP gerbang, bukan membukanya: "tidak
        # tahu apakah sudah diuji" tidak boleh berarti "boleh disetujui".
        # Pola fail-closed yang sama dipakai di seluruh platform.
        # Uji terakhir yang sudah diambil di atas ikut disodorkan, supaya
        # gerbang tidak menanyakannya ke basis data untuk kedua kalinya.
        # Aturannya tidak berubah, dan sidik jari paket tetap dihitung ulang
        # di dalam gerbang — yang dihemat hanya pembacaan.
        gate = _safe_read(
            "gerbang persetujuan", trial_service.approval_blocker, item,
            default="ap.err_gate_unreadable",
            **({} if latest is _UNREADABLE else {"trial": latest}))
        cols = st.columns(2)
        if cols[0].button(t("action.approve"),
                          key=f"review_approve_{item['id']}",
                          type="primary", use_container_width=True,
                          disabled=bool(gate), help=t(gate) if gate else None):
            try:
                approve_submission(item["id"], actor=user, note=note,
                                   dataset_type=chosen_type)
            except AuthError as e:
                st.error(error_message(e))
            except Exception as e:
                # Menyetujui memindahkan berkas, menulis basis data, DAN
                # mendaftarkan pipeline — jadi OSError, kesalahan basis data,
                # maupun DynamicRegistryError semuanya mungkin di sini, dan
                # tidak satu pun turunan AuthError. Sebelumnya semuanya lolos
                # sebagai jejak teknis ke peninjau.
                logger.exception(
                    "Persetujuan pengajuan #%s gagal tak terduga "
                    "(dataset_type=%r)", item["id"], chosen_type)
                st.error(t("ap.err_unexpected", kind=type(e).__name__))
            else:
                registered = _latest_registration(item)
                st.success(
                    f"Disetujui. {registered}"
                    f" Ditinjau {user['username']} pada "
                    f"{now_iso()[:19]}."
                    + (f" Catatan: {note}" if note.strip() else ""))
                st.rerun()
        # Menolak TANPA alasan tidak dijalankan sama sekali — berkasnya tetap
        # ada, hanya statusnya yang berubah.
        if cols[1].button("Tolak", key=f"review_reject_{item['id']}",
                          use_container_width=True,
                          help=t("ap.help_reject_reason")):
            if not note.strip():
                st.error(t("ap.msg_need_reject_reason"))
            else:
                try:
                    reject_submission(item["id"], actor=user, note=note)
                except AuthError as e:
                    st.error(error_message(e))
                except Exception as e:
                    # Menolak memindahkan berkas & menulis basis data: OSError
                    # dan kesalahan basis data mungkin terjadi, keduanya bukan
                    # AuthError.
                    logger.exception(
                        "Penolakan pengajuan #%s gagal tak terduga",
                        item["id"])
                    st.error(t("ap.err_unexpected", kind=type(e).__name__))
                else:
                    st.rerun()


def _latest_registration(item: dict) -> str:
    """Kalimat konfirmasi: identitas & hash versi yang barusan terdaftar."""
    try:
        from orchestrator.dynamic_registry import list_registered
        rows = [r for r in list_registered()
                if r.get("submission_id") == item["id"]]
    except Exception:                       # pragma: no cover - defensif
        rows = []
    if not rows:
        return "Pipeline terdaftar dan langsung dapat dijalankan."
    newest = max(rows, key=lambda r: r["version"])
    return (f"`{newest['pipeline_id']}` aktif sebagai versi {newest['version']} "
            f"(hash `{(newest['file_hash'] or '')[:12]}…`).")


# ── Kelola pengguna (Research Admin) ──────────────────────────────────────

def _render_users_flow() -> None:
    """Bagian kelola pengguna. Ditempatkan di halaman ini sebagai jalur ketiga
    (bukan halaman navigasi baru) supaya menu tetap tiga halaman.

    Izinnya diperiksa DI SINI dan sekali lagi di dalam fungsi aksinya
    (`create_user_as` / `set_user_active`), sehingga menyembunyikan menu saja
    tidak pernah menjadi satu-satunya penghalang."""
    user = current_user()
    st.subheader(t("ap.sec_users"))
    if not can_manage_users(user):
        st.error(t("ap.denied_users"))
        return

    # Tidak ada lagi antrean persetujuan AKUN: pendaftaran langsung aktif.
    # Menonaktifkan / mengaktifkan kembali tetap tersedia di daftar pengguna di
    # bawah, karena itu keputusan sadar seorang Research Admin — bukan antrean.
    st.markdown("Buat akun baru")
    with st.form("contrib_create_user"):
        cols = st.columns(3)
        new_username = cols[0].text_input("Username", key="contrib_new_username")
        new_password = cols[1].text_input("Password", type="password",
                                          key="contrib_new_password")
        new_role = cols[2].selectbox(t("ap.lbl_role"), ALL_ROLES, index=ALL_ROLES.index(ROLE_CONTRIBUTOR),
                                     format_func=role_label, key="contrib_new_role")
        created = st.form_submit_button(t("ap.btn_create_account"), type="primary")
    if created:
        try:
            created_user = create_user_as(user, new_username, new_password, new_role)
        except AuthError as e:            # termasuk PermissionDenied
            st.error(error_message(e))
        else:
            st.success(f"Akun `{created_user['username']}` dibuat "
                       f"({created_user['role_label']}).")

    st.divider()
    st.markdown(t("ap.note_user_list"))
    try:
        users = list_users()
    except Exception as e:                # pragma: no cover - defensive
        st.error(f"Gagal membaca daftar pengguna: {e}")
        return
    if not users:
        st.markdown(t("ap.empty_no_accounts"))
        return

    for row in users:
        with st.container(border=True):
            cols = st.columns([3, 2, 2, 2])
            # Peran + status akun (status WAJIB tetap tampil) menyatu dengan
            # baris identitasnya, bukan sebagai keterangan di bawahnya.
            is_self = row["username"] == (user or {}).get("username")
            cols[0].markdown(
                f"`{row['username']}` · {row['role_label']} · "
                f"{row['status_label']}" + (" · **akun Anda**" if is_self else ""))
            if is_self:
                continue

            active = row["status"] == STATUS_ACTIVE
            label = "Nonaktifkan" if active else "Aktifkan"
            if cols[2].button(label, key=f"contrib_toggle_{row['username']}",
                              use_container_width=True):
                try:
                    set_user_status(row["username"],
                                    STATUS_DISABLED if active else STATUS_ACTIVE,
                                    actor=user)
                except AuthError as e:
                    st.error(error_message(e))
                else:
                    st.rerun()
            # Peran Research Admin HANYA diberikan dari sini — tidak pernah
            # lewat pendaftaran mandiri.
            promote = row["role"] != ROLE_RESEARCH_ADMIN
            role_label_btn = "Jadikan Admin" if promote else "Jadikan Kontributor"
            if cols[3].button(role_label_btn, key=f"contrib_role_{row['username']}",
                              use_container_width=True):
                try:
                    set_user_role(row["username"],
                                  ROLE_RESEARCH_ADMIN if promote else ROLE_CONTRIBUTOR,
                                  actor=user)
                except AuthError as e:
                    st.error(error_message(e))
                else:
                    st.rerun()



def _render_upload_gate(kind: str) -> bool:
    """True bila pengguna saat ini boleh mengunggah; selain itu tampilkan
    keterangan + arahan masuk dan kembalikan False.

    SATU tempat yang menentukan status kontrol unggah di kedua jalur, sehingga
    tampilan tidak pernah menyimpang dari izin yang ditegakkan lapis aksi.
    Halaman & persyaratannya sendiri tidak pernah disembunyikan — hanya
    kontrolnya yang dimatikan.
    """
    user = current_user()
    if can_upload(user):
        return True

    label = "dataset" if kind == "dataset" else "pipeline"
    render_login_prompt(
        f"Kontrol unggah dinonaktifkan sampai Anda masuk. Masuk sebagai "
        f"Kontributor untuk mengunggah {label}. Persyaratan di atas tetap "
        f"dapat dibaca tanpa masuk; melihat hasil dan menjalankan eksperimen "
        f"juga tidak memerlukan akun.",
        key=f"contrib_login_gate_{kind}",
    )
    return False


# ── Jalur pipeline: instruksi persyaratan (dari konstanta validator) ──────

def _render_pipeline_requirements() -> None:
    """Persyaratan pipeline sebagai diagram alur + tabel kontrak + chip modul.

    Isinya sama persis dengan sebelumnya (dan tetap dibaca dari konstanta
    validator), hanya disajikan padat; rinciannya ada di expander.
    """
    render_pipeline_instructions()


# ── Jalur pipeline: laporan ───────────────────────────────────────────────

def _render_group(title: str, checks: list[dict]) -> None:
    if not checks:
        return
    st.markdown(f"**{title}**")
    for c in checks:
        icon = _STATUS_ICON.get(c["status"], "·")
        line = f" _(baris {c['line']})_" if c.get("line") else ""
        st.markdown(f"- {icon} **{c['name']}** — {check_message(c)}{line}")


def _render_package_report(result: dict, form: dict) -> None:
    st.subheader(t("ap.sec_validation"))
    n_files = len(result["files"])
    if result["valid"]:
        st.success(f"Valid — {n_files} berkas lolos, entry point "
                   f"`{result['entry_points'][0]}`.")
    else:
        st.error(result["summary"])
        if result["cause"]:
            st.markdown(result["cause"])

    for item in result["files"]:
        ok = item["package_ok"]
        icon = "✔" if ok else "✖"
        header = (f"{icon} {item['filename']} · {item['role']} · "
                  f"{format_size(item['size'])}")
        with st.expander(header, expanded=not ok):
            if item["description"]:
                st.caption(f"Penjelasan pengguna: {item['description']}")
            if not item["ok"]:
                st.error(item["error"])
                continue
            if not ok:
                st.markdown("Perlu diperbaiki")
                for c in item["blocking_failures"]:
                    line = f" _(baris {c['line']})_" if c.get("line") else ""
                    st.markdown(f"- {check_message(c)}{line}")
            if item["role"] == ROLE_SUPPORT:
                st.caption(
                    "Berkas pendukung: kontrak pipeline tidak berlaku, aturan "
                    "keamanan tetap penuh — berkas ini ikut dieksekusi saat "
                    "pipeline berjalan."
                )
            _render_group(GROUP_STRUCTURE, item["groups"][GROUP_STRUCTURE])
            _render_group(GROUP_SECURITY, item["groups"][GROUP_SECURITY])

    if not result["valid"]:
        st.markdown(t("ap.msg_fix_then_reupload"))
        return

    _render_valid_followup(result, form)




# ── Dataset uji lampiran: formulir kontributor ────────────────────────────

def _render_trial_dataset_form() -> tuple[object, str]:
    """(berkas, keterangan) dataset uji opsional.

    Mengembalikan (None, "") bila kontributor tidak melampirkan apa pun —
    pengajuan tanpa lampiran adalah jalur yang sah dan tetap berjalan.
    """
    from orchestrator.trial_dataset_service import (
        DATASET_SUFFIXES, MAX_TRIAL_DATASET_BYTES, human_size,
        inspect_attachment,
    )

    st.markdown(f"**{t('td.heading')}**")
    # SATU baris keterangan: apa gunanya berkas ini, dan batasnya. Halaman
    # ini berkuota teks kecil — memecahnya menjadi dua tidak menambah
    # kejelasan, hanya menambah baris.
    st.caption(t("td.intro") + " "
               + t("td.limit_note",
                   limit=human_size(MAX_TRIAL_DATASET_BYTES),
                   formats=", ".join(DATASET_SUFFIXES)))

    picked = st.file_uploader(
        t("td.lbl_file"), type=[s.lstrip(".") for s in DATASET_SUFFIXES],
        accept_multiple_files=False, key="contrib_trial_dataset")
    note = st.text_input(t("td.lbl_note"), key="contrib_trial_dataset_note",
                         placeholder=t("td.ph_note"))
    if picked is None:
        return None, ""

    size = len(picked.getvalue())
    if size > MAX_TRIAL_DATASET_BYTES:
        # Ditolak DI SINI juga, dengan menyebut angkanya — kontributor tahu
        # seberapa harus dikecilkan tanpa menebak.
        st.error(t("td.err_too_large", size=human_size(size),
                   limit=human_size(MAX_TRIAL_DATASET_BYTES)))
        return None, note

    st.success(t("td.attached_ok", filename=picked.name,
                 size=human_size(size)))
    _render_attachment_structure(picked)
    return picked, note


def _render_attachment_structure(upload) -> None:
    """Ringkasan pemeriksaan struktur, lewat diagnosa yang SUDAH ADA.

    Ditampilkan kepada kontributor sebelum ia mengajukan, supaya ia tahu
    berkasnya terbaca dengan benar — bukan menemukannya saat ditolak peninjau.
    """
    import tempfile
    from pathlib import Path as _Path

    from orchestrator.trial_dataset_service import inspect_attachment

    st.markdown(f"**{t('td.structure_heading')}**")
    tmp = _Path(tempfile.mkdtemp()) / (upload.name or "sample.csv")
    try:
        tmp.write_bytes(upload.getvalue())
        result = inspect_attachment(str(tmp))
    except Exception:                        # pragma: no cover - defensif
        st.info(t("td.structure_none"))
        return

    # Struktur yang tidak dikenal BUKAN kegagalan: pipeline yang dilampiri
    # dataset seperti ini justru sering membaca strukturnya sendiri.
    matched = [r.get("dataset_type") for r in result.get("reports") or []
               if r.get("compatible")]
    st.info(t("td.compatible_with", types=", ".join(matched)) if matched
            else t("td.structure_none"))


def _attach_trial_dataset(submission: dict, upload, note: str) -> None:
    """Simpan lampiran & catat keterangannya pada pengajuan yang baru dibuat."""
    from pathlib import Path as _Path

    from orchestrator.trial_dataset_service import (
        TrialDatasetError, attach_to_submission, store_attachment,
    )

    if upload is None:
        return
    try:
        info = store_attachment(
            upload, upload.name,
            package_name=_Path(submission["stored_path"]).name, note=note)
        attach_to_submission(submission["id"], info)
    except (TrialDatasetError, OSError) as exc:
        # Pengajuannya sendiri SUDAH tercatat; lampiran yang gagal disimpan
        # tidak membatalkannya — peninjau tetap dapat menguji dengan dataset
        # platform.
        st.warning(error_message(exc))
    except Exception as exc:
        # Termasuk kesalahan basis data. Rinciannya LENGKAP di log; yang
        # tampil kalimat yang dapat dipahami.
        logger.exception("Lampiran dataset uji pengajuan #%s gagal disimpan",
                         submission.get("id"))
        st.warning(t("ap.err_unexpected", kind=type(exc).__name__))


#: Kunci yang SELALU disertakan pada metadata pengajuan, meskipun nilainya
#: kosong. Membuang `dataset_type` hanya karena kosong membuat pengajuan
#: tercatat TANPA kuncinya sama sekali — dan itulah yang membuat uji coba
#: gagal di basis data alih-alih ditolak dengan pesan yang jelas.
_ALWAYS_KEEP_METADATA = ("dataset_type",)


def _submission_metadata(form: dict) -> dict:
    """Metadata pengajuan: nilai kosong dibuang, KECUALI kunci penting."""
    source = form or {}
    kept = {k: v for k, v in source.items() if v}
    for key in _ALWAYS_KEEP_METADATA:
        if key not in kept:
            kept[key] = source.get(key) or ""
    return kept


def _render_valid_followup(result: dict, form: dict) -> None:
    """Unduh + cuplikan registry terisi metadata + panduan aktivasi manual."""
    st.divider()
    st.info(t("ap.msg_valid_not_active"))

    st.markdown("Unduh berkas tervalidasi")
    cols = st.columns(min(3, len(result["files"])) or 1)
    for i, item in enumerate(result["files"]):
        cols[i % len(cols)].download_button(
            f"⬇ {item['filename']}",
            data=item["source"].encode("utf-8"),
            file_name=safe_staging_name(item["filename"]) or "pipeline.py",
            mime="text/x-python",
            use_container_width=True,
            key=f"contrib_dl_{item['filename']}",
        )

    user = current_user()
    entry_item = next(f for f in result["files"] if f["role"] == ROLE_ENTRY)
    if not can_upload(user):
        render_login_prompt(
            "Masuk sebagai Kontributor untuk mengajukan paket ini. Hasil "
            "validasi di atas tetap dapat dibaca tanpa masuk.",
            key="contrib_login_stage",
        )
    else:
        # Lampiran dikumpulkan SEBELUM tombol: nilainya harus sudah ada saat
        # pengajuan dibuat.
        trial_upload, trial_note = _render_trial_dataset_form()
        if st.button(t("ap.btn_submit_review"), key="contrib_submit_pipeline",
                     type="primary",
                     help=t("ap.help_submit_review")):
            # Nama kelas entry point dibaca STATIS dari AST — dibutuhkan
            # peninjau untuk mendaftarkan pipeline saat menyetujui.
            static_meta = extract_registry_metadata(entry_item["source"],
                                                    entry_item["filename"])
            try:
                submission = submit_pipeline(
                    [(f["filename"], f["source"]) for f in result["files"]],
                    entry_item["filename"], user=user,
                    metadata={**_submission_metadata(form),
                              "entry_class": static_meta.get("class_name")},
                    validation={
                        "valid": result["valid"],
                        "entry_points": result["entry_points"],
                        "files": [{"filename": f["filename"], "role": f["role"],
                                   "package_ok": f["package_ok"],
                                   "description": f["description"]}
                                  for f in result["files"]],
                    },
                )
            except (AuthError, OSError) as e:
                st.error(error_message(e))
            except Exception as e:
                logger.exception("Pengajuan pipeline gagal tak terduga")
                st.error(t("ap.err_unexpected", kind=type(e).__name__))
            else:
                _attach_trial_dataset(submission, trial_upload, trial_note)
                st.success(t("ap.msg_submitted_n",
                                  number=submission["id"]))

    if form.get("notes"):
        st.markdown(f"Catatan pengunggah: {form['notes']}")


# ── Jalur pipeline ────────────────────────────────────────────────────────

_OTHER_DATASET_OPTION = "Lainnya / belum terdaftar"


def _dataset_label(dataset_type: str) -> str:
    """Label dropdown: nama beratribusi ringkas, nilai internal tetap
    dataset_type. Opsi "lainnya" dibiarkan apa adanya."""
    if dataset_type == _OTHER_DATASET_OPTION:
        return dataset_type
    return get_research_short_label(dataset_type)


def _render_pipeline_flow() -> None:
    st.subheader(t("ap.sec_upload_pipeline"))
    _render_pipeline_requirements()
    st.divider()

    # Lapis TAMPILAN: persyaratan di atas tetap terbaca siapa pun, tetapi
    # kontrol unggahnya dimatikan bila belum berhak — supaya tidak ada tombol
    # yang tampak aktif padahal aksinya pasti ditolak lapis aksi.
    may_upload = _render_upload_gate("pipeline")

    uploaded = st.file_uploader(
        t("ap.lbl_pipeline_files"), type=["py"], accept_multiple_files=True,
        key="contrib_pipeline_files", disabled=not may_upload,
        help="Boleh lebih dari satu berkas `.py`. Tepat satu di antaranya "
             "menjadi entry point.",
    )
    uploaded = uploaded or []
    descriptions: dict[str, str] = {}
    if uploaded:
        st.markdown("Berkas terunggah")
        for f in uploaded:
            box = st.container(border=True)
            cols = box.columns([2, 3])
            try:
                size = len(f.getvalue())
            except Exception:  # pragma: no cover - defensive
                size = 0
            cols[0].markdown(f"`{f.name}` · {format_size(size)}")
            descriptions[f.name] = cols[1].text_input(
                t("ap.lbl_file_role"), key=f"contrib_desc_{f.name}",
                placeholder="mis. entry point / helper preprocessing",
                help=t("ap.help_file_role"),
            )

    st.divider()
    st.markdown(t("ap.note_metadata"))
    c1, c2 = st.columns(2)
    name = c1.text_input(t("ap.lbl_pipeline_name"), key="contrib_meta_name",
                         placeholder="mis. Random Forest — HIKARI2021")
    dtype_options = list(supported_datasets()) + [_OTHER_DATASET_OPTION]
    dtype_choice = c2.selectbox(
        t("ap.lbl_research_pipeline"), dtype_options, index=None,
        format_func=_dataset_label, placeholder="Pilih research pipeline…",
        key="contrib_meta_dtype",
        help="Menentukan `dataset_type` pada entri registry.",
    )
    algorithm = c1.text_input("Algoritma", key="contrib_meta_algo",
                              placeholder="mis. Random Forest")
    paper = c2.text_input(t("ap.lbl_paper"), key="contrib_meta_paper",
                          placeholder="mis. Rayyan (2024), Universitas Hasanuddin")
    notes = st.text_area(t("ap.lbl_note"), key="contrib_meta_notes", height=80,
                         help=t("ap.help_optional_report"))

    form = {
        "name": name,
        # "Lainnya" disimpan sebagai PENANDA eksplisit, bukan string kosong:
        # "jenisnya belum terdaftar" adalah keterangan yang berguna, sedangkan
        # string kosong tidak dapat dibedakan dari "tidak pernah diisi".
        "dataset_type": (DATASET_TYPE_UNREGISTERED
                         if dtype_choice == _OTHER_DATASET_OPTION
                         else (dtype_choice or "")),
        "algorithm": algorithm,
        "paper": paper,
        "notes": notes,
    }

    # Dataset target WAJIB: tanpa jenis, pipeline tidak dapat diuji maupun
    # dijalankan — jadi kekurangan itu dinyatakan di sini, saat masih murah
    # diperbaiki, bukan saat peninjau menekan tombol uji.
    if dtype_choice is None:
        st.caption(t("ap.err_dataset_type_required"))
    if st.button(t("ap.btn_upload_validate"), type="primary", key="contrib_validate",
                 disabled=not may_upload or dtype_choice is None,
                 help=(t("ap.err_dataset_type_required")
                       if dtype_choice is None else None)):
        problems = []
        if not uploaded:
            problems.append("unggah minimal satu berkas `.py`")
        if not (name or "").strip():
            problems.append("isi Nama pipeline")
        if problems:
            st.warning("Lengkapi dulu: " + "; ".join(problems) + ".")
        else:
            files: list[tuple[str, bytes]] = []
            progress = st.progress(0.0, text="Menyiapkan…")
            with st.status("Memvalidasi paket…", expanded=True) as status:
                total = len(uploaded)
                for i, f in enumerate(uploaded, 1):
                    st.write(f"Memeriksa `{f.name}` ({i}/{total})")
                    progress.progress(i / total, text=f"Memeriksa {f.name} ({i}/{total})")
                    try:
                        files.append((f.name, f.getvalue()))
                    except Exception as e:  # pragma: no cover - defensive
                        st.write(f"Gagal membaca `{f.name}`: {e}")
                # Validasi statis seluruh paket (tidak menjalankan apa pun).
                result = review_package(files, descriptions)
                status.update(label=f"Selesai — {result['summary']}",
                              state="complete", expanded=False)
            progress.empty()
            st.session_state[_RESULT_KEY] = result
            st.session_state[_FORM_KEY] = form

    result = st.session_state.get(_RESULT_KEY)
    if result:
        st.divider()
        _render_package_report(result, st.session_state.get(_FORM_KEY) or form)


# ── Jalur dataset ─────────────────────────────────────────────────────────

DATASET_EXTENSIONS = (".csv", ".ndjson", ".jsonl", ".json")
_SAFE_DATASET_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def safe_dataset_name(filename: str) -> str | None:
    """Nama berkas dataset yang aman, atau None bila tidak layak.

    Menolak (bukan memotong) nama ber-separator, nama aneh, dan ekstensi di
    luar daftar — sehingga unggahan tidak pernah dapat menulis ke luar
    `storage/datasets/`.
    """
    name = filename or ""
    if "/" in name or "\\" in name or name != Path(name).name:
        return None
    if name in ("", ".", "..") or not _SAFE_DATASET_NAME.match(name):
        return None
    if Path(name).suffix.lower() not in DATASET_EXTENSIONS:
        return None
    return name


def _dataset_target_path(filename: str) -> Path:
    return Path(DATASETS_DIR) / filename


def upload_size(uploaded) -> int:
    """Ukuran unggahan TANPA menyalin isinya ke objek bytes baru."""
    size = getattr(uploaded, "size", None)
    if isinstance(size, int):
        return size
    try:                                   # fallback: hitung lewat seek
        pos = uploaded.tell()
        uploaded.seek(0, 2)
        size = uploaded.tell()
        uploaded.seek(pos)
        return int(size)
    except Exception:                      # pragma: no cover - defensive
        return 0


def save_dataset_upload(src, target: Path, *, user: dict | None) -> int:
    """Simpan berkas dataset ke `storage/datasets/`.

    ``user`` WAJIB (keyword-only, tanpa default): izin diperiksa DI SINI, jadi
    aksi ini tidak dapat dipicu tanpa hak walau tombolnya berhasil ditekan.
    Mengembalikan jumlah byte yang ditulis.
    """
    require_upload(user)
    written, _truncated = copy_stream(src, target)
    return written


def copy_stream(src, target: Path, *, max_bytes: int | None = None,
                chunk: int = _COPY_CHUNK_BYTES) -> tuple[int, bool]:
    """Salin ``src`` ke ``target`` BERTAHAP. Mengembalikan (byte ditulis, terpotong).

    Tidak pernah memuat seluruh isi ke satu objek bytes — penting karena
    ``st.file_uploader`` sudah menahan berkas di RAM; menduplikasinya akan
    melipatgandakan pemakaian memori pada berkas berukuran GB.

    Bila ``max_bytes`` diberikan, penyalinan berhenti di sana dan dipotong pada
    newline TERAKHIR supaya tidak ada baris terpenggal (potongan dipakai untuk
    diagnosa yang memang berbasis sampel).
    """
    src.seek(0)
    written, truncated = 0, False
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as out:
        while True:
            want = chunk if max_bytes is None else min(chunk, max_bytes - written)
            if want <= 0:
                truncated = bool(src.read(1))     # masih ada sisa → terpotong
                break
            block = src.read(want)
            if not block:
                break
            out.write(block)
            written += len(block)
    src.seek(0)

    if truncated:
        # Rapikan ekor agar baris terakhir utuh.
        with open(target, "r+b") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            tail_start = max(0, size - chunk)
            fh.seek(tail_start)
            tail = fh.read()
            cut = tail.rfind(b"\n")
            if cut != -1:
                fh.truncate(tail_start + cut + 1)
                written = tail_start + cut + 1
    return written, truncated


def _diagnose_uploaded(uploaded, safe_name: str) -> dict | None:
    """Diagnosa unggahan TANPA menaruhnya di `storage/datasets/`.

    Potongan awal berkas ditulis ke berkas sementara di `storage/_upload_tmp/`
    (di dalam proyek agar lolos path-safety), didiagnosa dengan mesin sampling
    yang sudah ada, lalu berkas sementaranya SELALU dihapus. Hasilnya disimpan
    di session_state per (nama, ukuran) supaya rerun berikutnya tidak membaca
    ulang apa pun.
    """
    from orchestrator.dataset_diagnostics import diagnose_all

    key = (safe_name, upload_size(uploaded))
    cached = st.session_state.get(_DS_DIAG_KEY)
    if cached and cached[0] == key:
        return cached[1]

    tmp = UPLOAD_TMP_DIR / f"{os.getpid()}_{safe_name}"
    try:
        _written, truncated = copy_stream(uploaded, tmp,
                                          max_bytes=DIAGNOSIS_PREFIX_BYTES)
        diag = diagnose_all(str(tmp))
    except OSError as e:
        st.error(f"Gagal memeriksa berkas: {e}")
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:                    # pragma: no cover - defensive
            logger.warning("Berkas sementara %s gagal dihapus", tmp, exc_info=True)

    if truncated and diag.get("profile"):
        # Potongan awal berhenti sebelum akhir berkas: angka apa pun dari sini
        # adalah angka SAMPEL, jangan pernah tampil sebagai total.
        diag["profile"]["sampled"] = True
    st.session_state[_DS_DIAG_KEY] = (key, diag)
    return diag


def _render_dataset_requirements_overview() -> None:
    """Persyaratan kedua research pipeline sebagai diagram + tabel per tab,
    tanpa meminta pengguna memilih — diagnosa yang menyimpulkan kecocokannya.

    Panel persyaratan lengkap milik halaman Run Experiment dipakai apa adanya
    di dalam expander, jadi halaman itu tidak terpengaruh sama sekali.
    """
    render_dataset_instructions()


def _render_dataset_flow() -> None:
    st.subheader(t("ap.sec_add_dataset"))
    st.markdown(t("ap.note_checked_against_all"))
    _render_dataset_requirements_overview()

    st.divider()
    tab_upload, tab_server = st.tabs(["Unggah berkas", "Daftarkan dari server"])
    with tab_upload:
        _render_dataset_upload_tab()
    with tab_server:
        _render_dataset_server_tab()


def _render_dataset_upload_tab() -> None:
    limit_gb = MAX_DATASET_UPLOAD_BYTES / (1024 ** 3)
    may_upload = _render_upload_gate("dataset")
    uploaded = st.file_uploader(
        "Berkas dataset", type=["csv", "ndjson", "jsonl", "json"],
        accept_multiple_files=False, key="contrib_dataset_file",
        disabled=not may_upload,
        help=f"Batas unggah {limit_gb:.0f} GB. Berkas yang lebih besar "
             f"didaftarkan lewat tab Daftarkan dari server.",
    )
    if uploaded is None:
        return

    safe = safe_dataset_name(uploaded.name)
    if safe is None:
        st.error(
            "Nama berkas tidak valid. Gunakan huruf/angka/`._-` tanpa komponen "
            "direktori, berekstensi `.csv`, `.ndjson`, `.jsonl`, atau `.json`."
        )
        return

    size = upload_size(uploaded)
    if size > MAX_DATASET_UPLOAD_BYTES:
        st.error(f"Berkas terlalu besar ({format_size(size)}, batas "
                 f"{limit_gb:.0f} GB). Salin berkas ke `storage/datasets/` di "
                 f"server, lalu pakai tab **Daftarkan dari server** — tanpa "
                 f"batas ukuran dan tanpa penyalinan.")
        return

    with st.container(border=True):
        cols = st.columns(2)
        cols[0].markdown(f"`{safe}` · {format_size(size)}")

    # 1. Diagnosa DULU — belum ada apa pun yang ditulis ke storage/datasets/.
    with st.spinner("Memeriksa dataset…"):
        diag = _diagnose_uploaded(uploaded, safe)
    if diag is None:
        return
    if diag.get("error"):
        st.warning(diag["error"])
        return

    st.divider()
    _render_dataset_profile(diag.get("profile") or {}, safe, size)
    st.divider()
    _render_compatibility(diag)

    # 2. Baru menyimpan, atas tindakan eksplisit pengguna.
    st.divider()
    target = _dataset_target_path(safe)
    if target.exists():
        st.error(t("ap.err_file_exists", filename=safe))
        return
    if not diag.get("compatible_types"):
        st.warning(t("ap.msg_not_compatible_yet"))
    st.markdown(f"Tujuan: `{target}`")

    user = current_user()
    if not can_upload(user):
        render_login_prompt(
            "Masuk sebagai Kontributor untuk mengajukan dataset ini. "
            "Hasil pemeriksaan kecocokan di atas tetap dapat dibaca "
            "tanpa masuk.",
            key="contrib_login_dataset",
        )
        return
    # Dataset adalah DATA, bukan kode yang dieksekusi — jadi ia tidak melewati
    # tinjauan: begitu lolos pemeriksaan, berkasnya langsung tersimpan. Seluruh
    # pengaman sebelum titik ini tetap berlaku (batas ukuran, sanitasi nama,
    # penolakan menimpa, ekstensi yang diizinkan), dan `save_dataset_upload`
    # tetap memanggil `require_upload` sehingga izinnya ditegakkan di lapis aksi.
    if st.button(t("ap.btn_save_dataset"), type="primary",
                 key="contrib_submit_dataset",
                 help=t("ap.help_dataset_direct")):
        try:
            written = save_dataset_upload(uploaded, target, user=user)
        except (AuthError, PermissionDenied, OSError) as e:
            st.error(error_message(e))
            return
        except Exception as e:
            logger.exception("Penyimpanan dataset gagal tak terduga")
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
            return
        # Daftar dataset di-cache; unggahan baru harus langsung terlihat, jadi
        # penelusuran folder berikutnya dipaksa membaca ulang dari disk.
        from ui.views.run_experiment import invalidate_dataset_options
        invalidate_dataset_options()
        st.success(t("ap.msg_saved_as", filename=safe,
                            size=format_size(written)))


def _render_dataset_server_tab() -> None:
    """Daftarkan berkas yang SUDAH ada di storage/datasets/ — tanpa batas
    ukuran dan tanpa penyalinan. Jalur untuk dataset besar (mis. EVE 5,9 GB)
    yang tidak masuk akal lewat peramban."""
    # Pembacaan folder memakai mekanisme yang SAMA dengan halaman Run Experiment.
    from ui.views.run_experiment import _all_dataset_options, _diagnose_selected

    st.markdown(t("ap.help_register_existing"))
    try:
        options = [p for p, _dtype in _all_dataset_options()]
    except Exception as e:                 # pragma: no cover - defensive
        st.error(f"Gagal memindai `storage/datasets/`: {e}")
        return
    if not options:
        st.info("Belum ada berkas di `storage/datasets/`. Salin berkas ke "
                "folder tersebut di server, lalu segarkan halaman ini.")
        return

    def _label(path: str) -> str:
        try:
            return f"{Path(path).name} · {format_size(Path(path).stat().st_size)}"
        except OSError:                    # pragma: no cover - defensive
            return Path(path).name

    chosen = st.selectbox("Berkas dataset", options, index=None,
                          format_func=_label, placeholder=t("ap.ph_pick_file"),
                          key="contrib_server_dataset")
    if not chosen:
        return

    if st.button(t("ap.btn_check_compat"), type="primary",
                 key="contrib_check_server"):
        st.session_state["_contrib_server_checked"] = chosen
    if st.session_state.get("_contrib_server_checked") != chosen:
        return

    # Memakai diagnosa ber-cache milik Run Experiment (path+mtime+ukuran), jadi
    # berkas besar tidak dibaca ulang antar-rerun.
    with st.spinner("Memeriksa dataset…"):
        diag = _diagnose_selected(chosen)
    if diag.get("error"):
        st.warning(diag["error"])
        return

    try:
        size = Path(chosen).stat().st_size
    except OSError:                        # pragma: no cover - defensive
        size = 0
    st.divider()
    _render_dataset_profile(diag.get("profile") or {}, Path(chosen).name, size)
    st.divider()
    _render_compatibility(diag)


_PROFILE_PREVIEW_COLUMNS = 10       # nama kolom yang disebut sebelum "… (+N lainnya)"


def _sample_note(profile: dict) -> str:
    """Catatan wajib bahwa angka berasal dari sampel, bukan seluruh berkas."""
    n = f"{profile.get('rows_read', 0):,}"
    if profile.get("sampled"):
        return (f"Angka di atas dari {n} baris pertama — berkas tidak dimuat "
                f"seluruhnya.")
    return f"Berdasarkan seluruh {n} baris berkas ini."


def _render_dataset_profile(profile: dict, filename: str, size_bytes: int) -> None:
    """Profil deskriptif berkas — SEMUA dari sampel yang sudah dibaca diagnosa.
    Tidak ada pembacaan berkas tambahan di sini."""
    fmt_names = {"csv": "CSV", "ndjson": "NDJSON", "unknown": "tidak dikenali"}
    is_json = profile.get("detected_format") == "ndjson"
    unit = "Kunci JSON" if is_json else "Kolom"

    rows = profile.get("rows_read", 0)
    # Jumlah baris TIDAK pernah diklaim sebagai total bila hanya dari sampel.
    rows_text = f"≥ {rows:,} (sampel)" if profile.get("sampled") else f"{rows:,}"

    st.subheader(t("ap.sec_dataset_profile"))

    pairs: list[tuple[str, str]] = [
        ("Berkas", f"`{filename}`"),
        ("Ukuran", format_size(size_bytes)),
        ("Format", fmt_names.get(profile.get("detected_format"), "?")),
        ("Baris", rows_text),
        (unit, str(profile.get("column_count", 0))),
    ]
    if profile.get("numeric_columns") is not None:
        pairs.append(("Tipe data", f"{profile['numeric_columns']} numerik · "
                                   f"{profile['non_numeric_columns']} non-numerik"))
    if profile.get("label_column"):
        pairs.append(("Kolom label", f"`{profile['label_column']}`"))
    elif is_json:
        pairs.append(("Kolom label", "dibentuk pipeline dari alert Suricata"))
    if profile.get("encoding") and profile["encoding"] != "utf-8":
        pairs.append(("Encoding", profile["encoding"]))
    if profile.get("malformed_lines"):
        pairs.append(("Baris gagal diparse", f"{profile['malformed_lines']:,} (diabaikan)"))

    with st.container(border=True):
        for label, value in pairs:
            cols = st.columns([1, 2])
            cols[0].markdown(label)
            cols[1].markdown(value)

    # Nama kolom: beberapa contoh + daftar lengkap di expander tertutup.
    columns = profile.get("columns") or []
    if columns:
        shown = columns[:_PROFILE_PREVIEW_COLUMNS]
        text = ", ".join(f"`{c}`" for c in shown)
        rest = len(columns) - len(shown)
        if rest > 0:
            text += f", … (+{rest} lainnya)"
        st.markdown(text)
        with st.expander(f"Semua {len(columns)} {unit.lower()}", expanded=False):
            st.code("\n".join(str(c) for c in columns), language=None)

    # Distribusi kelas dari sampel — selalu dengan keterangan sampel.
    counts = profile.get("class_counts") or {}
    if counts:
        total = sum(counts.values()) or 1
        st.markdown("Distribusi kelas")
        for value, n in counts.items():
            st.markdown(f"- `{value}` — {n:,} ({n / total * 100:.1f}%)")
    elif is_json:
        st.markdown("Indikasi kelas")
        st.markdown(f"- Event TLS — {profile.get('tls_rows', 0):,}")
        st.markdown(f"- Event beralert (calon kelas attack) — "
                    f"{profile.get('alert_rows', 0):,}")
    st.markdown(_sample_note(profile))


def _algorithms_for(dataset_type: str) -> list[str]:
    """Algoritma yang tersedia untuk sebuah dataset_type, DARI REGISTRY."""
    from config.pipeline_registry import get_pipelines_for_dataset
    seen: list[str] = []
    for info in get_pipelines_for_dataset(dataset_type).values():
        algo = info.get("algorithm") or info.get("name")
        if algo and algo not in seen:
            seen.append(algo)
    return seen


def _render_compatibility(diag: dict) -> None:
    """Kecocokan PER RESEARCH PIPELINE (bukan per algoritma).

    Memakai helper penyaji yang sudah ada di halaman Run Experiment supaya
    gayanya identik: _verdict / _cause_sentence / _action_sentence /
    _render_check_list.
    """
    from ui.views.run_experiment import (
        _VERDICT_LABEL, _action_sentence, _cause_sentence, _render_check_list,
        _sorted_results, _verdict,
    )

    results = diag.get("results") or {}
    if not results:
        st.warning(diag.get("error") or "Diagnosa kecocokan tidak tersedia.")
        return

    compatible = diag.get("compatible_types") or []
    st.subheader(t("ap.sec_compatibility"))
    if not compatible:
        st.warning(t("ap.msg_no_match_anywhere"))

    for dtype, result in _sorted_results(diag):
        # Satu blok per research pipeline; nama beratribusi ringkas, bukan ID mentah.
        with st.container(border=True):
            st.markdown(get_research_short_label(dtype))
            verdict = _verdict(result)
            headline = f"{_VERDICT_LABEL[verdict]} — {_cause_sentence(diag, dtype, result)}"

            if result.get("compatible"):
                st.success(headline)
                algos = _algorithms_for(dtype)
                if algos:
                    # Kecocokan ditentukan oleh dataset_type; algoritma adalah
                    # pilihan DI DALAM research pipeline yang sama — bukan
                    # pemeriksaan terpisah.
                    st.markdown(f"Tersedia **{len(algos)}** algoritma:")
                    for algo in algos:
                        st.markdown(f"- {algo}")
            else:
                (st.warning if verdict == "near" else st.error)(headline)
                action = _action_sentence(dtype, result)
                if action:
                    st.markdown(action)

            with st.expander("Rincian pemeriksaan kecocokan",
                             expanded=False):
                _render_check_list(result, dtype)

    if compatible:
        st.markdown("Langkah berikutnya: buka halaman **Run Experiment**, "
                    "pilih berkas ini, lalu pilih research pipeline & "
                    "algoritma.")


# ── Entry point halaman ───────────────────────────────────────────────────

def render() -> None:
    st.title(t("page.contribute"))

    mode = st.session_state.get(_MODE_KEY)
    if mode not in ("pipeline", "dataset", "users", "review"):
        _render_choice_boxes()
        return

    if st.button(t("ap.btn_back"), key="contrib_back"):
        for key in (_MODE_KEY, _RESULT_KEY, _FORM_KEY):
            st.session_state.pop(key, None)
        st.rerun()

    if mode == "pipeline":
        _render_pipeline_flow()
    elif mode == "users":
        _render_users_flow()
    elif mode == "review":
        _render_review_flow()
    else:
        _render_dataset_flow()
