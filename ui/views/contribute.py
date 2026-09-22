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

import json
import logging
import os
import re
from pathlib import Path

import streamlit as st

from ui.i18n import t

# Nama & atribusi dibaca lewat pembaca GABUNGAN: bawaan + research
# pipeline terunggah. Nama fungsinya di-alias ke nama lama supaya tidak
# ada satu pun titik panggil yang berubah — yang bergeser hanya SUMBER-nya.
from orchestrator.research_registry import (
    short_label_for as get_research_short_label,
)
from config.settings import DATASETS_DIR, STORAGE_DIR
from database.models import (
    ALL_ROLES, ALL_USER_STATUSES, KIND_DATASET, KIND_PIPELINE,
    ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN, STATUS_ACTIVE, STATUS_DISABLED,
    STATUS_PENDING, SUBMISSION_APPROVED, SUBMISSION_PENDING,
    SUBMISSION_REJECTED, normalize_role, role_label, status_label,
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
    SubmissionError, approve_submission, list_submissions,
    read_submission_sources, reject_submission, submit_pipeline,
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
from orchestrator.submission_service import research_credit
from html import escape
from ui.components import code_box
from ui.components import dialogs as dlg
from ui.components import grid
# Satu penyaji cap waktu untuk seluruh aplikasi: dua tempat yang memformat
# tanggal sendiri-sendiri pasti berbeda bentuknya suatu saat.
from ui.components.research_manage import format_stamp
from ui.components import review_style as rp
from ui.components import submission_review as sr
from ui.components.contribute_context import render_page_context
from ui.components import tables as tbl
from ui.components.tables import human_datetime
from ui.components.theme import dark_button_scope
from ui.components.validator_messages import (
    check_message, error_message,
)
from ui.components.sections import (
    back_button, detail_facts, prose, render_facts, render_section,
)
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
    )
    if mode:
        st.session_state[_MODE_KEY] = mode
        st.rerun()


# ── Pengajuan: milik sendiri & peninjauan ─────────────────────────────────

# ── Penanda daftar peninjauan ─────────────────────────────────────────────
# Semuanya berawalan `_contrib`, jadi ``page_flags.VIEW_STATE_PREFIXES`` sudah
# membuangnya saat pengguna berpindah halaman — tidak perlu mekanisme baru,
# dan tidak ada daftar nama kedua yang bisa ketinggalan.
_OPEN_KEY = "_contrib_review_open"       # id pengajuan yang sedang dibuka


def _detail_is_open() -> bool:
    """Apakah sebuah tampilan DALAM sedang terbuka di halaman ini.

    Dahulu ada DUA pemilik keadaan: kartu pengajuan milik modul ini, dan
    tampilan pipeline/penyunting/perbandingan milik ``manage_pipelines``. Yang
    kedua sudah dicabut seluruhnya, jadi tinggal satu yang perlu ditanya.
    """
    return st.session_state.get(_OPEN_KEY) is not None


_QUERY_KEY = "_contrib_review_query"
_SORT_KEY = "_contrib_review_sort"
_PAGE_KEY = "_contrib_review_page"

#: Berkas yang sedang DISUNTING: ``{"id": <pengajuan>, "file": <nama>}``.
#: Berawalan `_contrib` seperti yang lain, jadi ia ikut terbuang saat pengguna
#: berpindah halaman tanpa perlu daftar nama kedua.
_EDIT_KEY = "_contrib_edit_open"


def _open_editor(submission_id: int, filename: str) -> None:
    """Buka layar penyuntingan satu berkas."""
    st.session_state[_EDIT_KEY] = {"id": int(submission_id),
                                   "file": str(filename)}


def _close_editor() -> None:
    """Kembali ke kartu peninjauan pengajuan yang SAMA, bukan ke antrean."""
    st.session_state.pop(_EDIT_KEY, None)


def _editing_file(item: dict) -> str:
    """Berkas pengajuan ini yang sedang disunting; ``""`` bila tidak ada.

    Ditanya per pengajuan, bukan sebagai bendera tunggal: layar penyuntingan
    milik pengajuan lain tidak boleh membajak kartu yang sedang dibuka.
    """
    keadaan = st.session_state.get(_EDIT_KEY) or {}
    if keadaan.get("id") != (item or {}).get("id"):
        return ""
    return str(keadaan.get("file") or "")


def _open_submission(submission_id: int) -> None:
    """Buka satu pengajuan. Dipanggil dari CALLBACK tombol/pemilih."""
    st.session_state[_OPEN_KEY] = submission_id


def _close_submission() -> None:
    """Kembali ke daftar. Penyaring & halaman SENGAJA tidak disentuh, supaya
    peninjau kembali ke tempat yang sama dengan saat ia membuka.

    Dahulu di sini ada penaik nonce grid: AgGrid mempertahankan baris
    tercentang, jadi kembali ke daftar akan langsung membuka lagi pengajuan
    yang barusan ditutup. Antreannya kini baris berkolom dengan tombol, dan
    tombol hanya bernilai true pada rerun tepat sesudah ditekan — tidak ada
    keadaan tersimpan yang dapat membuka apa pun sendiri, jadi tidak ada yang
    perlu dibatalkan.
    """
    st.session_state.pop(_OPEN_KEY, None)


def _render_pending_list(pending: list, user: dict) -> None:
    """Daftar antrean: cari, urutkan, penggal, lalu buka satu.

    Urutan langkahnya menentukan biayanya. Menyaring dan memenggal dikerjakan
    atas kolom baris pengajuan APA ADANYA; pemeriksaan statis — yang membaca
    seluruh berkas sebuah paket — baru dijalankan untuk baris yang benar-benar
    tampil di halaman ini. Jadi yang dibayar satu render mengikuti ukuran
    halaman, bukan panjang antrean.
    """
    # TANPA judul bagian: pengalih bagian tepat di atas daftar ini sudah
    # menuliskannya, beserta jumlahnya. Keterangannya pindah ke judul halaman
    # (lihat `_render_review_flow`).
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
        return _reviewed_package(item["id"], _package_key(item), item)

    # TABEL YANG BARISNYA DAPAT DIKLIK — mekanisme yang SAMA dengan riwayat
    # eksperimen pada halaman "Progress & Status": AgGrid dengan pemilihan
    # baris. Memilih sebuah baris langsung membuka pengajuannya; tidak ada
    # tombol "buka" terpisah, dan tidak ada daftar kedua di bawah tabelnya.
    # Antrean kosong: tabelnya tidak digambar — tabel tanpa baris terbaca
    # seperti kegagalan memuat. Keadaannya tetap DINYATAKAN, oleh baris jumlah
    # di bawah ini ("Menampilkan 0 dari 0 pengajuan menunggu."), jadi tidak ada
    # yang hilang tanpa kata.
    rows = sr.pending_table_rows(visible, _reviewed)
    if rows:
        _render_queue_grid(rows)

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


#: Kolom antrean tinjauan: (kunci label i18n, bobot lebar).
#:
#: Bentuknya BARIS BERKOLOM aplikasi, bukan AgGrid — alasan yang sama dengan
#: tabel Kecocokan: AgGrid hidup di iframe, gayanya tidak dapat dikendalikan
#: stylesheet aplikasi dan tidak dapat diperiksa tes mana pun. Kolomnya sama
#: persis dengan `sr.PENDING_COLUMNS` yang dahulu dipakai, jadi tidak ada
#: keterangan yang hilang saat bentuknya berubah.
_QUEUE_COLS = (
    ("rv.col_submission", 8),
    ("rv.col_check_result", 7),
    ("rv.col_file", 3),
    ("rv.col_submitted_by", 4),
    ("rv.col_when", 6),
    ("", 3),                                  # tombol buka
)


def _queue_badge(row: dict) -> str:
    """Hasil periksa sebagai PIL — hijau/kuning/merah yang sama dengan halaman
    detailnya, diff versi, dan chip katalog.

    Peninjau melihat mana yang perlu dibuka lebih dulu tanpa membaca satu per
    satu, dan teks di dalam pilnya tetap menyebut hasilnya: warna bukan
    satu-satunya pembawa keterangan.
    """
    latar = grid.STATE_TINT.get(sr.verdict_state(row), grid.STATE_TINT["warn"])
    return (f'<span class="ids-badge ids-badge-solid" '
            f'style="background:{latar};">'
            f'{escape(str(row.get("verdict_text") or ""))}</span>')


def _render_queue_grid(rows: list[dict]) -> None:
    """Antrean peninjauan: satu baris per pengajuan, tombol buka di barisnya."""
    lebar = [b for _, b in _QUEUE_COLS]

    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, (kunci, _) in zip(kepala, _QUEUE_COLS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for row in rows:
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            sel[0].markdown(
                f'<span title="{escape(str(row["name"]))}">'
                f'{escape(str(row["name"]))}</span>', unsafe_allow_html=True)
            sel[1].markdown(_queue_badge(row), unsafe_allow_html=True)
            sel[2].markdown(str(row["file_count"]))
            sel[3].markdown(escape(str(row["submitted_by"])))
            sel[4].markdown(tbl.format_time(row["submitted_at"]))
            if sel[5].button(t("ap.btn_open_submission"),
                             key=f"queue_open_{row['id']}",
                             use_container_width=True):
                _open_submission(int(row["id"]))
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
    open_id = st.session_state.get(_OPEN_KEY)
    item = next((s for s in pending if s["id"] == open_id), None)
    if open_id is not None and item is None:
        # Sudah tidak di antrean (baru saja diputuskan, atau antreannya
        # berubah). Kembali ke daftar alih-alih menggambar halaman kosong.
        _close_submission()

    if item is None:
        _render_pending_list(pending, user)
        return

    # Menyunting berkas punya LAYARNYA SENDIRI, dan layar itu menggantikan
    # kartu peninjauan alih-alih tumbuh di dalamnya. Dahulu kotak sunting
    # terbuka tepat di bawah kode, di dalam kartu yang juga memuat tabel
    # berkas, uji coba, dan tombol keputusan: mengubah kiriman orang lain dan
    # memutuskan nasibnya terjadi pada satu layar yang sama.
    if _editing_file(item):
        _render_edit_screen(item, user)
        return

    # ── Detail satu pengajuan ────────────────────────────────────────────
    back_button(key="review_back", on_click=_close_submission)

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
    # Judulnya dipesan DI SINI dan diisi setelah bagiannya diketahui: ia satu
    # tingkat di atas pengalih bagian, jadi ia harus tergambar di atasnya,
    # sementara keterangannya bergantung pada bagian mana yang sedang dibuka.
    kepala = st.container()
    if not can_approve(user):
        with kepala:
            render_section(t("ap.sec_review"))
        st.error(t("ap.denied_review"))
        return

    try:
        waiting = list_submissions(status=SUBMISSION_PENDING)
    except Exception as e:                  # pragma: no cover - defensive
        with kepala:
            render_section(t("ap.sec_review"))
        st.error(f"Gagal membaca antrean: {e}")
        return

    # Hanya PIPELINE yang ditinjau: isinya kode yang akan dieksekusi. Dataset
    # tersimpan langsung, jadi tidak pernah masuk antrean ini lagi.
    # TERLAMA MENUNGGU LEBIH DULU — antrean tinjauan, bukan tumpukan.
    pending = sr.sort_pending([s for s in waiting if s["kind"] == KIND_PIPELINE])
    # Angka pada tab "Aktif" HARUS berasal dari daftar yang digambar bagian
    # itu, bukan dari registry kontribusi: bagiannya mendaftar research
    # pipeline bawaan maupun kontribusi.
    from ui.components import research_manage as rs

    active_count = rs.active_count()
    section = mp.render_section_switch(len(pending), active_count)

    # SATU judul untuk halaman ini, bukan dua. Dahulu "Peninjauan Pengajuan"
    # berdiri sebagai subjudul lalu tiap bagian menuliskan judulnya sendiri
    # tepat di bawah pengalih bagian — sehingga "Menunggu tinjauan (1)"
    # terbaca dua kali berturut-turut, sekali sebagai tab yang sedang aktif
    # dan sekali lagi sebagai judul raksasa, dan yang paling besar di layar
    # justru yang paling tidak berarti: pengalihnya sudah mengatakannya.
    #
    # Keterangan tiap bagian TIDAK hilang, ia pindah ke judul yang satu ini
    # dan berganti mengikuti bagian yang sedang dibuka.
    with kepala:
        render_section(t("ap.sec_review"),
                       help=t("ap.help_active_list")
                       if section == mp.SECTION_ACTIVE
                       else t("ap.help_only_pipelines_reviewed"))

    if section == mp.SECTION_ACTIVE:
        mp.render_active(user)
        return

    # Mulai di sini SELURUHNYA milik bagian "Menunggu tinjauan". Kedua bagian
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


def _package_key(item: dict) -> str:
    """Kunci kesegaran sebuah paket pengajuan: sidik jari SELURUH berkasnya.

    Dahulu kuncinya `file_hash`, yang hanya melacak titik masuk. Terukur:
    merevisi berkas PENDUKUNG tidak mengubahnya, sehingga hasil periksa dan
    arsip unduhan yang ter-cache tetap milik paket lama — peninjau membaca
    "lolos" untuk kode yang bukan lagi kode itu, dan mengunduh isi yang usang.
    """
    from orchestrator.submission_service import package_digest

    return package_digest(item)


@st.cache_data(ttl=60, show_spinner=False)
def _reviewed_package(submission_id: int, package_key: str, _item: dict) -> dict:
    """Pemeriksaan STATIS berkas tersimpan, dihitung sekali per ISI paket.

    Kuncinya (id, sidik jari paket) berubah begitu berkas mana pun berubah —
    termasuk berkas pendukung — jadi membuka/menutup kartu tidak memicu
    validasi ulang, tetapi merevisi paket pasti memicunya. Tidak ada kode
    pengajuan yang di-import maupun dijalankan di sini.
    """
    return sr.review_stored_package(_item)


@st.cache_data(ttl=60, show_spinner=False)
def _package_archive(submission_id: int, package_key: str,
                     _sumber: list) -> bytes:
    """Arsip paket, disusun SEKALI per isi paket.

    Kuncinya sama dengan pemeriksaan statis di atas — (id, sidik jari paket)
    — dan itu tepat: begitu berkas mana pun berubah, sidik jarinya berubah dan
    arsipnya ikut disusun ulang tanpa mekanisme pembatalan tersendiri.

    Tanpa cache ini, seluruh berkas dikompresi ulang pada SETIAP penggambaran
    ulang halaman — memilih baris berkas, mengetik catatan, apa pun — dan
    biayanya tumbuh bersama jumlah berkas paket. Justru pertumbuhan itu yang
    dibuang dari halaman ini sebelumnya.
    """
    return sr.package_archive(_sumber)

def _render_check_groups(entry: dict) -> None:
    """Ringkasan pemeriksaan satu berkas, lalu HANYA yang tidak lolos.

    Sebelumnya seluruh pemeriksaan dicetak sebagai bulir — terukur enam per
    berkas, lima di antaranya mengatakan "tidak ada yang salah". Sepuluh berkas
    berarti lima puluh baris yang tidak menolong siapa pun menemukan masalah.

    Jumlahnya tetap DISEBUT: peninjau harus tahu pemeriksaannya benar-benar
    berjalan dan berapa banyak. Yang dibuang hanya perincian yang lolos.
    """
    tally = sr.check_tally(entry)
    if tally["total"]:
        st.markdown(t("sr.checks_tally", total=tally["total"],
                      passed=tally["passed"]))
    notable = sr.notable_checks(entry)
    if not notable:
        return
    for check in notable:
        icon = _STATUS_ICON.get(check["status"], "·")
        line = f" _(baris {check['line']})_" if check.get("line") else ""
        st.markdown(f"- {icon} **{check['name']}**: {check_message(check)}{line}")


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
        prose(t("trial.compat_unavailable"), key="compat_unavail_a")
        return
    # `diagnose_dataset` mengembalikan DICT (ramah cache/JSON), bukan objek.
    checks = (report or {}).get("checks") or []
    if not checks:
        prose(t("trial.compat_unavailable"), key="compat_unavail_b")
        return
    # Bentuknya SAMA dengan blok fakta pada bagian "Keputusan" di bawah:
    # pasangan label-nilai berlatar abu-abu, bukan daftar berbutir. Keduanya
    # menjawab pertanyaan sejenis, yaitu apa yang sistem ketahui tentang
    # kiriman ini, dan dua bentuk berbeda untuk satu jenis isi membuat halaman
    # ini terbaca seperti dua halaman yang disambung.
    #
    # Satu pasang per baris, bukan dua: kalimat pemeriksaan jauh lebih panjang
    # daripada nilai pada blok Keputusan, dan dua pasang sebaris membuatnya
    # melipat menjadi empat baris di dalam kolom sempit.
    mark = {"pass": "✔", "warn": "⚠", "fail": "✖"}
    pasangan = [(diagnostic_title(c),
                 f"{mark.get((c or {}).get('status') or '', '·')} "
                 f"{diagnostic_message(c)}")
                for c in checks]
    _render_fact_rows(pasangan, columns=1)


def _render_trial_outcome(trial: dict) -> None:
    """Hasil satu uji coba, di dalam satu dropdown.

    Kegagalan dilaporkan LENGKAP: tahap, jenis, dan pesannya. Itulah yang
    dicari peninjau — "uji gagal" saja tidak menolong siapa pun. Karena itu
    pula dropdown yang GAGAL terbuka sendiri: menyembunyikan kegagalan di
    balik satu klik adalah cara paling mudah membuatnya tidak terbaca.
    """
    berhasil = trial["status"] == trial_db.STATUS_PASSED
    judul = t("trial.outcome_passed" if berhasil else "trial.outcome_failed",
              when=(trial.get("started_at") or "")[:19])
    with st.expander(judul, expanded=not berhasil):
        st.caption(t("trial.tested_by", who=trial["started_by"],
                     when=(trial.get("started_at") or "")[:19],
                     dataset=trial.get("dataset_type") or "-"))
        if berhasil:
            st.success(t("trial.result_passed",
                         rows=trial.get("rows_used") or "-",
                         seconds=trial.get("duration_s") or "-"))
            _render_trial_metrics(trial.get("metrics") or {})
            return
        # Tahap & pesan diterjemahkan lebih dulu. Menyisipkannya mentah membuat
        # satu kalimat memuat dua bahasa — cacat yang sama dengan catatan kaki
        # metrik pada laporan PDF.
        from ui.components.validator_messages import (
            trial_failure_message, trial_stage,
        )

        st.error(t("trial.result_failed",
                   stage=trial_stage(trial.get("error_stage")) or "-"))
        st.markdown(t("trial.failure_detail",
                      kind=trial.get("error_kind") or "-",
                      message=trial_failure_message(
                          trial.get("error_kind"),
                          trial.get("error_message")) or "-"))


def _render_trial_metrics(metrics: dict) -> None:
    """Empat metrik sebagai KOTAK, sisanya sebagai baris fakta.

    Bentuk kotaknya sama dengan bagian "Hasil" di Jalankan Eksperimen, sebab
    angkanya memang angka yang sama. Yang dikotakkan dan yang tidak diputuskan
    `sr.trial_metric_split`, fungsi murni, supaya isinya dapat diperiksa tanpa
    menjalankan Streamlit.
    """
    kotak, sisa = sr.trial_metric_split(metrics)
    if not kotak and not sisa:
        prose(t("trial.no_metrics"), key="trial_no_metrics")
        return
    if kotak:
        kolom = st.columns(len(kotak))
        for kol, (label, nilai) in zip(kolom, kotak):
            kol.metric(label, f"{float(nilai):.4f}")
    if sisa:
        render_facts(sisa)


def _approve_help(gate: str, reviewed: dict, item: dict | None = None) -> str:
    """Keterangan tombol Setujui: SATU kalimat terpenting tentang menekannya.

    * terkunci  → APA yang kurang, sebab itulah yang harus dikerjakan dulu;
    * hidup     → APA akibatnya, dan bila paketnya berperingatan, bahwa
                  peringatan itu sebaiknya dibaca lebih dulu.

    Keduanya dahulu berdiri di layar sebagai paragraf dan spanduk peringatan di
    atas tombolnya, dibaca pada setiap pengajuan oleh peninjau yang sudah
    hafal. Fungsi MURNI supaya isinya dapat diuji tanpa merender halaman.
    """
    if gate:
        return t(gate)
    akibat = t(sr.APPROVAL_CONSEQUENCE_KEY)
    if sr.warning_checks(reviewed):
        akibat = f"{akibat} {t(sr.WARNING_REMINDER_KEY)}"
    # Berkas yang belum ditempatkan DISEBUTKAN, tidak menghalangi. Petanya
    # menerangkan, bukan menentukan apa yang dijalankan, jadi menahan
    # persetujuan karenanya akan menyangkutkan pengajuan demi keterangan.
    # Titik masuk disebut terpisah: yang belum ditempatkan di sana berarti
    # algoritmanya sendiri tidak tergambar di mana pun.
    kurang = sr.placement_gaps(item) if item else {"entry": [], "support": []}
    if kurang["entry"]:
        akibat = f"{akibat} {t('ap.placement_gap_entry', count=len(kurang['entry']))}"
    elif kurang["support"]:
        akibat = f"{akibat} {t('ap.placement_gap_support', count=len(kurang['support']))}"
    return akibat


def _trial_help(item: dict) -> str:
    """Keterangan zona Pengujian, untuk tooltip judulnya.

    Merakit dua kalimat yang dahulu berdiri sebagai paragraf di layar: batas
    uji coba (berapa baris, berapa detik) dan, khusus pengajuan yang berdiri
    sendiri, alasan dataset platform tidak ditawarkan. Batasnya dibaca dari
    `TRIAL_LIMITS`, bukan diketik ulang, supaya menaikkan batas tidak
    meninggalkan tooltip yang berbohong.
    """
    from orchestrator.submission_service import is_standalone

    limits = trial_service.TRIAL_LIMITS
    teks = t("trial.intro", rows=f"{limits['max_rows']:,}".replace(",", "."),
             seconds=limits["max_seconds"])
    if is_standalone(item):
        teks = f"{teks} {t('td.err_standalone_needs_own_dataset')}"
    return teks


def _render_reviewer_attachment(item: dict, user: dict | None, *,
                                buntu: bool = True) -> None:
    """Lampirkan dataset uji coba dari halaman peninjauan.

    Dua tempat memakainya, dan bedanya hanya satu kalimat. ``buntu=True``:
    tidak ada sumber dataset sama sekali (pengajuan berdiri sendiri tanpa
    lampiran), sehingga keadaannya perlu dinyatakan lebih dulu. ``buntu=False``:
    tawaran biasa di bawah daftar dataset platform, yang tidak perlu
    mengumumkan keadaan apa pun.

    Batas dan pemeriksaannya sama persis dengan jalur kontributor pada kedua
    keadaan: ukuran maksimum yang sama, penyimpan yang sama, dan pencatat yang
    sama. Yang berbeda hanya siapa yang mengunggah.
    """
    from orchestrator.trial_dataset_service import (
        MAX_TRIAL_DATASET_BYTES, human_size,
    )

    if buntu:
        st.info(t("td.needs_own_short"))
    if not can_approve(user):
        return

    sid = item["id"]
    unggah = st.file_uploader(
        t("td.lbl_reviewer_dataset"), type=["csv", "json", "jsonl", "ndjson"],
        key=f"rev_ds_{sid}",
        help=t("td.help_reviewer_dataset",
               size=human_size(MAX_TRIAL_DATASET_BYTES)))
    if unggah is None:
        return
    if st.button(t("td.btn_attach_dataset"), key=f"rev_ds_save_{sid}",
                 type="primary"):
        _attach_trial_dataset(item, unggah, t("td.note_reviewer_dataset"))
        st.rerun()


#: Tab "unggah dari perangkat". BUKAN sumber dataset: ia perbuatan, dan yang
#: terunggah dijalankan lewat tab lampiran. Dibedakan dari pengenal sumber
#: milik `trial_service` justru supaya ia tidak pernah sampai ke `run_trial`.
_SOURCE_UPLOAD = "_upload"


def _render_trial_step(item: dict, user: dict | None,
                       latest=_UNREADABLE) -> None:
    """Pilih dataset → lihat kecocokan → jalankan uji → baca hasilnya.

    ``latest`` OPSIONAL: uji terakhir pengajuan ini yang sudah diambil bersama
    seluruh antrean dalam satu kueri. Bila tidak diberikan, ia dibaca di sini
    seperti sebelumnya.
    """
    # Judul "Uji coba di platform" dan paragraf pembukanya dicabut: zona di
    # atas bagian ini sudah berjudul "Pengujian", dan batas uji cobanya kini
    # tinggal di `help` judul zona itu (lihat `trial_help`). Peninjau yang
    # membuka halaman ini datang untuk memutuskan, bukan untuk membaca ulang
    # aturan yang sama pada setiap pengajuan.

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
        prose(t("td.missing_dataset_type"), key="td_missing_dtype")

    from orchestrator.trial_dataset_service import attachment_of, human_size

    attachment = attachment_of(item)

    # Sumber dataset. Lampiran hanya ditawarkan bila memang ada — pengajuan
    # tanpa lampiran tetap dapat diuji lewat dataset platform (Tahap 1).
    #
    # KECUALI research pipeline yang berdiri sendiri: ia hanya boleh diuji
    # dengan datasetnya sendiri, karena setelah disetujui ia terikat ke dataset
    # itu. Meluluskannya atas dataset platform akan membuat "sudah diuji"
    # berbicara tentang data yang tidak akan pernah ia pakai. Aturan yang sama
    # ditegakkan lagi di `_resolve_dataset`, jadi menyembunyikan pilihan bukan
    # satu-satunya penghalang.
    standalone = bool(trial_service.planned_dataset_type(item))
    sources = [] if standalone else [trial_service.SOURCE_PLATFORM]
    if attachment:
        sources.append(trial_service.SOURCE_ATTACHED)
    if not sources:
        # Buntu yang PERNAH permanen: research pipeline yang berdiri sendiri
        # tidak boleh memakai dataset platform, dan bila kontributor tidak
        # melampirkan datasetnya maka tidak ada satu pun sumber. Uji coba
        # mustahil, `trial.gate_untested` mengunci persetujuan, dan pengajuan
        # itu tersangkut selamanya tanpa satu pun tindakan yang ditawarkan.
        #
        # Peninjau karena itu dapat melampirkannya sendiri di sini, lewat
        # gerbang yang SAMA dengan lampiran kontributor.
        _render_reviewer_attachment(item, user)
        return
    # Sumber dataset sebagai TAB. Tiga hal yang setara kini berdiri setara:
    # dataset platform, unggahan dari perangkat peninjau, dan lampiran
    # pengajuan. Sebelumnya dua di antaranya berupa pilihan radio sementara
    # yang ketiga menempel sebagai expander di bawah salah satunya.
    #
    # Polanya SAMA dengan `run_mode_controls.render_mode_tabs`, termasuk
    # alasannya: dengan `on_change` bawaan ("ignore") atribut `.open`
    # mengembalikan None untuk semua tab, sehingga penyajinya tidak dapat tahu
    # sumber mana yang dimaksud saat tombol Jalankan ditekan.
    #
    # Isi SELURUH tab tetap dijalankan Streamlit. Karena itu nilai dari tab
    # yang tidak terbuka DIBUANG di bawah, bukan diandalkan tidak terbentuk.
    tabs = [] if standalone else [trial_service.SOURCE_PLATFORM]
    if can_approve(user):
        # Unggah bukan sumber, ia perbuatan: yang terunggah muncul sebagai
        # lampiran, dan di situlah ia dijalankan.
        tabs.append(_SOURCE_UPLOAD)
    if attachment:
        tabs.append(trial_service.SOURCE_ATTACHED)
    if not tabs:
        _render_reviewer_attachment(item, user)
        return

    label = {
        trial_service.SOURCE_PLATFORM: t("td.source_platform"),
        _SOURCE_UPLOAD: t("td.sec_upload_own"),
        trial_service.SOURCE_ATTACHED: t("td.source_attached"),
    }
    wadah = st.tabs([label[s] for s in tabs],
                    key=f"trial_tab_{item['id']}", on_change="rerun")
    per_tab = dict(zip(tabs, wadah))
    terbuka = [s for s, w in per_tab.items() if w.open]
    source = terbuka[0] if terbuka else tabs[0]

    picked, dipilih = None, None
    if trial_service.SOURCE_PLATFORM in per_tab:
        with per_tab[trial_service.SOURCE_PLATFORM]:
            options = _trial_dataset_options()
            if not options:
                st.info(t("trial.compat_unavailable"))
            else:
                # Nilai pilihan adalah JALUR berkas; labelnya nama berkas yang
                # terbaca manusia. Jenisnya TIDAK dipakai sebagai nilai
                # pilihan — ia ditentukan `resolve_dataset_type`, satu-satunya
                # penentu.
                names = {path: Path(path).name for path, _dtype in options}
                dipilih = st.selectbox(
                    t("trial.lbl_dataset"), list(names),
                    index=None, placeholder=t("trial.ph_dataset"),
                    format_func=lambda path: names.get(path, path),
                    key=f"trial_ds_{item['id']}")
                if dipilih:
                    jenis = trial_service.resolve_dataset_type(
                        item, trial_service.SOURCE_PLATFORM, dipilih)
                    if jenis:
                        _render_trial_compatibility(jenis, dipilih)
                    # Batal berdiri di sini, bersama pilihan yang dibatalkannya.
                    # Yang dibatalkan adalah PILIHAN di layar: tidak ada
                    # lampiran, catatan uji, atau berkas yang tersentuh.
                    if st.button(t("trial.btn_clear_dataset"),
                                 key=f"trial_clear_{item['id']}",
                                 help=t("trial.help_clear_dataset")):
                        st.session_state.pop(f"trial_ds_{item['id']}", None)
                        st.rerun()

    if _SOURCE_UPLOAD in per_tab:
        with per_tab[_SOURCE_UPLOAD]:
            _render_reviewer_attachment(item, user, buntu=False)
            # Memilih tab dari kode TIDAK dapat diandalkan pada Streamlit
            # terpasang: menyetel kunci tabnya diterima, tetapi `.open` tetap
            # kosong sampai tab itu benar-benar diklik. Jadi jalannya
            # ditunjukkan alih-alih dipaksakan.
            # Keterangan "Sudah terlampir: ..." dicabut: tab lampirannya
            # sendiri sudah menyebut berkas yang terpasang.

    if trial_service.SOURCE_ATTACHED in per_tab:
        with per_tab[trial_service.SOURCE_ATTACHED]:
            # Berkas APA yang akan dipakai, dinyatakan sebelum dijalankan.
            st.markdown(t("td.attachment_facts",
                          filename=attachment.get("filename") or "-",
                          size=human_size(attachment.get("size") or 0),
                          when=(attachment.get("uploaded_at") or "")[:19]))
            # Jenis untuk lampiran datang dari PENENTU yang sama — lampiran
            # tidak punya jenis sendiri, ia memakai jenis pipeline yang sedang
            # diuji. Itu PERSIS pertanyaan yang sudah dijawab `intrinsic_type`.
            if intrinsic_type:
                _render_trial_compatibility(
                    intrinsic_type, attachment.get("stored_path") or "")

    # Hanya nilai dari tab yang TERBUKA yang boleh ikut. Nilai yang tertinggal
    # di tab lain tetap ada di memori, dan meneruskannya akan menjalankan uji
    # atas dataset yang tidak sedang dilihat siapa pun.
    if source == trial_service.SOURCE_PLATFORM:
        picked = dipilih
        resolved_type = (trial_service.resolve_dataset_type(
            item, source, picked) if picked else intrinsic_type)
        ready = bool(picked)
    elif source == trial_service.SOURCE_ATTACHED:
        resolved_type = intrinsic_type
        ready = True
    else:
        resolved_type = intrinsic_type
        ready = False

    # Gerbang jenis dataset — berlaku pada kedua sumber yang benar-benar
    # menjalankan sesuatu. Tombol yang pasti gagal tidak boleh aktif, dan
    # alasannya selalu dinyatakan. Kunci pesannya tetap diputuskan penentu,
    # bukan di sini — yang disodorkan hanya hasil penentuan di atas.
    #
    # Tab unggah tidak melewatinya sama sekali: ia bukan sumber, jadi
    # menanyakan "jenis datasetnya cocok atau tidak" kepadanya tidak ada
    # artinya. Sebabnya sendiri yang dinyatakan pada tombolnya.
    if source == _SOURCE_UPLOAD:
        type_blocker = ""
        sebab = t("td.upload_tab_not_a_source")
    else:
        type_blocker = trial_service.dataset_type_blocker(
            item, source, picked, resolved=resolved_type)
        if type_blocker:
            st.warning(t(type_blocker))
        sebab = t(type_blocker) if type_blocker else ""

    blocked = bool(sebab) or not ready
    if st.button(t("trial.btn_run"), key=f"trial_run_{item['id']}",
                 disabled=blocked, use_container_width=True,
                 help=sebab or None):
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
        prose(t("trial.err_history_unreadable"), key="trial_hist_err")
    elif latest:
        _render_trial_table(item)
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


#: Kolom tabel uji coba. Bentuknya mengikuti `_FILE_COLS`: kolom terakhir
#: tanpa judul, berisi tombol rincian.
_TRIAL_COLS = (
    ("trial.col_when", 6),
    ("trial.col_by", 4),
    ("trial.col_dataset", 5),
    ("trial.col_outcome", 9),
    ("", 3),                                  # tombol rincian
)


def _render_trial_table(item: dict) -> None:
    """SELURUH uji coba pengajuan ini sebagai tabel, terbaru di atas.

    Dahulu hanya uji TERAKHIR yang digambar, padahal setiap uji tersimpan.
    Yang hilang justru yang paling berarti: paket yang lolos pada percobaan
    keempat setelah tiga kali gagal terbaca persis sama dengan paket yang
    lolos sekali jalan.

    Sebab kegagalan TIDAK pindah ke modal. Menyembunyikan kegagalan di balik
    satu klik adalah cara paling mudah membuatnya tidak terbaca, dan itulah
    alasan dropdown yang gagal dahulu terbuka sendiri. Kolom Hasil karena itu
    menyebut tahap kegagalannya apa adanya; modal hanya menambah rinciannya.
    """
    semua = _safe_read("riwayat uji coba", trial_db.list_trials, item["id"],
                       default=None)
    if semua is None:
        # Kuncinya berbeda dari kalimat serupa di `_render_trial_step`: dua
        # `prose` berkunci sama pada satu modul membuat yang kedua menimpa
        # yang pertama, dan sebuah test menjaga keunikannya.
        prose(t("trial.err_history_unreadable"), key="trial_table_err")
        return
    baris = sr.trial_table_rows(semua)
    if not baris:
        prose(t("trial.no_trials_yet"), key="trial_none_yet")
        return

    from ui.components.validator_messages import trial_stage

    lebar = [b for _, b in _TRIAL_COLS]
    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, (kunci, _) in zip(kepala, _TRIAL_COLS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for row in baris:
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            sel[0].markdown(human_datetime(row["at"]))
            sel[1].markdown(escape(row["by"] or "-"))
            sel[2].markdown(escape(row["dataset"] or "-"))
            sel[3].markdown(_trial_badge(row, trial_stage),
                            unsafe_allow_html=True)
            if sel[4].button(t("trial.btn_detail"),
                             key=f"trial_detail_{item['id']}_{row['id']}",
                             use_container_width=True):
                dlg.open_dialog(dlg.TRIAL_DETAIL_KEY, row["id"])
                st.rerun()

    if dlg.is_open(dlg.TRIAL_DETAIL_KEY):
        dipilih = sr.trial_row_by_id(baris,
                                     dlg.dialog_state(dlg.TRIAL_DETAIL_KEY))
        if dipilih is None:
            # Uji cobanya tersapu petugas kebersihan sementara modal terbuka.
            dlg.close_dialog(dlg.TRIAL_DETAIL_KEY)
        else:
            _trial_detail_dialog(dipilih)


def _trial_badge(row: dict, trial_stage) -> str:
    """Kolom Hasil: lolos, atau GAGAL beserta tahapnya.

    Tahapnya ikut di sini, bukan hanya di modal, sebab itulah yang dicari
    peninjau: "uji gagal" saja tidak menolong siapa pun.
    """
    rona = grid.STATE_TINT.get(row["state"])
    gaya = f'style="background:{rona};"' if rona else ""
    if row["passed"]:
        teks = t("trial.outcome_short_passed")
    elif row["status"] == "FAILED":
        teks = t("trial.outcome_short_failed",
                 stage=trial_stage(row["error_stage"]) or "-")
    else:
        teks = row["status"]
    return (f'<span class="ids-badge ids-badge-solid" {gaya}>'
            f'{escape(teks)}</span>')


@dlg.dialog_decorator(" ", dlg.TRIAL_DETAIL_KEY, width="large")
def _trial_detail_dialog(row: dict) -> None:
    """Rincian satu uji coba. TAMBAHAN atas barisnya, bukan penggantinya."""
    st.markdown(f"**{t('trial.detail_title', when=human_datetime(row['at']))}**")
    st.caption(t("trial.tested_by", who=row["by"], when=row["at"],
                 dataset=row["dataset"] or "-"))
    if row["passed"]:
        st.success(t("trial.result_passed",
                     rows=row["rows_used"] or "-",
                     seconds=row["duration_s"] or "-"))
        _render_trial_metrics(row["metrics"])
    else:
        from ui.components.validator_messages import (
            trial_failure_message, trial_stage,
        )

        st.error(t("trial.result_failed",
                   stage=trial_stage(row["error_stage"]) or "-"))
        st.markdown(t("trial.failure_detail",
                      kind=row["error_kind"] or "-",
                      message=trial_failure_message(
                          row["error_kind"], row["error_message"]) or "-"))
    if st.button(t("action.close"), key="trial_detail_close",
                 use_container_width=True):
        dlg.close_dialog(dlg.TRIAL_DETAIL_KEY)
        st.rerun()


def _render_review_header(row: dict) -> None:
    """Kepala halaman: pengajuan mana, dan bagaimana hasil periksanya.

    Menggantikan label expander pembungkus yang dahulu memuat kalimat yang
    sama. Bedanya, kepala ini TIDAK dapat ditutup: pengajuan yang sedang dibuka
    adalah satu-satunya hal di halaman ini, jadi menyembunyikan namanya tidak
    pernah berguna.
    """
    rp.review_header(name=row["name"], verdict=row["verdict"],
                     verdict_text=row["verdict_text"],
                     files=row["file_count"], who=row["submitted_by"],
                     when=row["submitted_at"])


#: Jenis penelitian sumber. Nilainya PENGENAL yang tampil apa adanya pada
#: baris "Jenis" — dikunci ke daftar supaya seragam di seluruh katalog, persis
#: seperti atribusi bawaan yang memakai satu kata baku.
SOURCE_TYPES = ("Skripsi", "Tesis", "Disertasi", "Jurnal", "Laporan",
                "Lainnya")


#: Berkas paket yang sedang dibaca, per pengajuan. Berawalan `_contrib` supaya
#: `page_flags.VIEW_STATE_PREFIXES` sudah membuangnya saat pengguna berpindah
#: halaman — tidak perlu mekanisme baru.
_OPEN_FILE_KEY = "_contrib_open_file"


#: Kolom tabel berkas paket: (kunci label i18n, bobot lebar).
#:
#: Baris berkolom aplikasi, bukan AgGrid. Alasannya sama dengan antrean dan
#: tabel Kecocokan: AgGrid hidup di iframe, gayanya tidak dapat mengikuti
#: aplikasi, dan hasil gambarnya tidak dapat diperiksa tes mana pun.
_FILE_COLS = (
    ("sr.col_file", 8),
    ("sr.col_role", 4),
    ("rv.col_check_result", 6),
    ("sr.col_size", 3),
    ("sr.col_origin", 4),
    ("sr.col_placement", 6),
    ("", 3),                                  # tombol baca
)


def _file_badge(row: dict) -> str:
    """Hasil periksa satu berkas sebagai PIL, sewarna dengan seluruh aplikasi.

    Ronanya dibaca dari KEADAAN (`sr.file_state`) dan bukan dari kalimatnya:
    mewarnai berdasarkan teks berbahasa akan berhenti bekerja begitu pengguna
    berganti bahasa.
    """
    return grid.state_badge(row.get("check_text") or "", sr.file_state(row))


#: Suntingan yang BELUM disimpan, per pengajuan: {sid: {nama: teks}}.
#: Dikumpulkan lebih dulu dan disimpan sekali, karena satu putaran revisi
#: adalah satu keputusan peninjau, bukan satu berkas. Berawalan `_contrib`
#: sehingga `page_flags.VIEW_STATE_PREFIXES` membuangnya saat identitas
#: berganti: suntingan orang lain tidak boleh ikut terbawa.
_DRAFT_KEY = "_contrib_source_draft"


def draft_of(sid: int) -> dict:
    """Suntingan tertunda milik satu pengajuan."""
    return st.session_state.get(_DRAFT_KEY, {}).get(str(sid), {})


def _render_source_view(item: dict, filename: str, source: str) -> None:
    """Isi berkas, DIBACA. Menyuntingnya pindah ke layar tersendiri.

    Membaca adalah keadaan bawaan, sebab itulah yang dilakukan peninjau
    hampir sepanjang waktu, dan teks bernomor lebih mudah dipadankan dengan
    nomor baris pada temuan daripada kotak sunting.

    Nomor barisnya dibuat Streamlit sendiri lewat `line_numbers=True`, BUKAN
    ditempelkan ke teksnya. Awalan `12 | ` yang dahulu dipakai ikut terbaca
    penyorot sintaks sebagai kode, sehingga nomornya diwarnai sebagai angka
    dan baris pertama tiap berkas ditafsir keliru: warnanya salah justru pada
    tampilan yang paling sering dibaca peninjau.

    Tombolnya tidak lagi membuka kotak sunting di tempat: ia membuka layar
    penyuntingan (lihat `_render_edit_screen`). Menyunting kiriman orang lain
    dan memutuskan nasibnya tidak lagi berbagi satu layar.
    """
    from orchestrator.submission_service import revision_blocker

    sid = item["id"]
    tertunda = draft_of(sid)
    berlaku = tertunda.get(filename, source)

    st.code(berlaku, language="python", line_numbers=True, height=320)
    if filename in tertunda:
        st.markdown(t("ap.source_unsaved", filename=filename))


def _stash_edit(sid: int, filename: str, asli: dict) -> None:
    """Simpan isi kotak sunting berkas yang DITINGGALKAN ke suntingan tertunda.

    Dipanggil saat berpindah berkas dari dalam layar penyuntingan. Tanpa ini,
    berpindah berkas berarti kehilangan apa yang baru saja diketik.

    Yang isinya kembali sama dengan berkas aslinya DIBUANG dari daftar
    tertunda, bukan disimpan sebagai suntingan kosong: sebuah berkas yang
    tercatat "disunting" padahal isinya tidak berubah akan membuat penanda
    suntingan tertunda berbohong, dan membawa berkas yang tidak berubah ke
    formulir revisi.
    """
    # Kotak suntingnya komponen editor, dan yang tersimpan di `session_state`
    # untuk kunci itu adalah KAMUS jawabannya, bukan teks. `current_text`
    # yang menerjemahkannya, sekaligus menangani render pertama yang menjawab
    # dengan teks kosong. Membaca kunci itu mentah-mentah di sini berarti
    # menyimpan kamus sebagai isi berkas.
    kunci = f"edit_box_{sid}_{filename}"
    if kunci not in st.session_state:
        return
    teks = code_box.current_text(kunci, asli.get(filename, ""))
    draft = st.session_state.setdefault(_DRAFT_KEY, {}).setdefault(str(sid), {})
    if teks == asli.get(filename):
        draft.pop(filename, None)
    else:
        draft[filename] = teks


def _switch_edit_file(sid: int, asli: dict) -> None:
    """Pindah ke berkas lain TANPA kehilangan suntingan berkas sebelumnya."""
    berikutnya = st.session_state.get(f"edit_pick_{sid}")
    sebelumnya = str((st.session_state.get(_EDIT_KEY) or {}).get("file") or "")
    if not berikutnya or berikutnya == sebelumnya:
        return
    _stash_edit(sid, sebelumnya, asli)
    _open_editor(sid, berikutnya)


def _render_edit_screen(item: dict, user: dict) -> None:
    """Layar penyuntingan satu berkas paket. MENGGANTIKAN kartu peninjauan.

    Menyimpan TIDAK menulis diam-diam ke paket. Suntingan dikumpulkan dulu di
    `_DRAFT_KEY`, lalu masuk lewat jalur revisi yang sama dengan unggah-ulang:
    catatan wajib, validasi statis mendahului penulisan, kiriman asli tidak
    disentuh, dan berkas yang tidak disunting tetap ada. Itulah sebabnya layar
    ini tidak pernah memanggil jalur penulisan mana pun sendiri.

    Izinnya ditegakkan DI SINI juga, bukan hanya di tombol yang membukanya:
    sebuah pengajuan dapat diputuskan orang lain sementara layar ini terbuka.
    """
    from orchestrator.submission_service import (
        read_submission_sources, revision_blocker,
    )

    sid = item["id"]
    if not can_approve(user) or revision_blocker(item):
        _close_editor()
        st.rerun()

    asli = dict(_safe_read("berkas paket", read_submission_sources, item,
                           default=[]) or [])
    nama = _editing_file(item)
    if nama not in asli:
        # Berkasnya sudah tidak ada di paket (paketnya baru saja direvisi).
        # Kembali ke kartu, alih-alih menggambar penyunting tanpa isi.
        _close_editor()
        st.rerun()

    back_button(key=f"edit_back_{sid}", on_click=_close_editor)
    rp.zone_heading(rp.ZONE_WORK, t("ap.sec_edit_file", filename=nama))

    tertunda = draft_of(sid)
    if tertunda:
        st.markdown(t("ap.draft_pending", count=len(tertunda)))

    # Pemilih berkas: st.radio, bukan selectbox. Nilainya nama berkas apa
    # adanya, dan berpindah menyimpan suntingan berkas sebelumnya lebih dulu.
    if len(asli) > 1:
        st.radio(t("ap.lbl_edit_pick_file"), list(asli),
                 index=list(asli).index(nama), horizontal=True,
                 key=f"edit_pick_{sid}", on_change=_switch_edit_file,
                 args=(sid, asli))
        nama = _editing_file(item)

    # Kotak sunting berwarna. Warnanya hidup SELAGI diketik, bukan pada
    # pratinjau di sebelahnya: itulah yang membedakannya dari kotak teks biasa.
    #
    # Labelnya tidak pernah terlihat. Nama berkasnya sudah disebut dua kali
    # tepat di atas kotak ini (judul bagian dan pemilih berkas), tetapi pembaca
    # layar tetap memerlukannya.
    #
    # Nomor baris DITAMPILKAN editor di luar teksnya, jadi yang tersimpan tetap
    # isi berkasnya saja.
    berlaku = tertunda.get(nama, asli[nama])
    teks = code_box.source_editor(
        berlaku, key=f"edit_box_{sid}_{nama}",
        label=t("ap.lbl_edit_source", filename=nama))

    aksi = st.columns([1, 1, 3])
    if aksi[0].button(t("ap.btn_keep_edit"), key=f"edit_keep_{sid}_{nama}",
                      type="primary", use_container_width=True,
                      disabled=teks == asli[nama],
                      help=t("ap.help_keep_edit")):
        st.session_state.setdefault(_DRAFT_KEY, {}).setdefault(
            str(sid), {})[nama] = teks
        _close_editor()
        st.rerun()
    if aksi[1].button(t("ap.btn_discard_edit"), key=f"edit_drop_{sid}_{nama}",
                      use_container_width=True):
        st.session_state.get(_DRAFT_KEY, {}).get(str(sid), {}).pop(nama, None)
        _close_editor()
        st.rerun()


def _render_fact_rows(pairs, *, columns: int = 2) -> None:
    """Pasangan label-nilai sebagai SATU formulir datar.

    Dahulu tiap ruas digambar di dalam wadah berbatasnya sendiri: sepuluh ruas
    berarti sepuluh kotak bersudut lengkung, masing-masing dengan padding
    sendiri, dan label yang berbobot sama dengan nilainya. Yang terbaca bukan
    sebuah formulir, melainkan tumpukan kartu.

    Markupnya disusun lapis komponen, bukan di sini: halaman ini tidak pernah
    menyusun tabel sendiri, dan sebuah test menjaga aturan itu.
    """
    detail_facts(pairs, columns=columns)


def _render_file_table(item: dict, files: list[dict]) -> None:
    """Daftar berkas paket sebagai TABEL, lalu SATU berkas dibaca di bawahnya.

    Bentuk master-detail yang sama dengan antrean peninjauan dan daftar
    pipeline terdaftar — lihat `ui.components.grid`.

    Ini BUKAN expander yang dahulu dibuang. Expander menyembunyikan hasil
    periksa sampai tiap berkas dibuka satu per satu; tabel justru menampilkan
    hasil SELURUH berkas sekaligus dalam satu kolom berwarna, sehingga peninjau
    langsung melihat berkas mana yang bermasalah lalu membuka yang itu.
    """
    if not files:
        return

    rows = sr.file_table_rows(files, size_text=format_size)
    opened = st.session_state.get(_OPEN_FILE_KEY, {}).get(str(item["id"]))
    # Berkas yang SEDANG dibaca, atau `None` selama belum ada yang dibuka.
    #
    # Dahulu berkas pertama dibuka sendiri supaya halaman tidak kosong di
    # bawah tabelnya. Akibatnya kode satu berkas selalu terbentang tanpa
    # diminta, dan tabelnya terdorong jauh ke atas layar. Sekarang tabelnya
    # yang berdiri sendiri: kolom hasil periksa sudah mengatakan berkas mana
    # yang perlu dibuka, dan isinya dibuka ketika diminta.
    terbuka = opened if any(r["filename"] == opened for r in rows) else None
    lebar = [b for _, b in _FILE_COLS]

    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, (kunci, _) in zip(kepala, _FILE_COLS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for row in rows:
        nama = row["filename"]
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            tanda = "**" if nama == terbuka else ""
            sel[0].markdown(f"{tanda}{escape(str(nama))}{tanda}")
            sel[1].markdown(escape(str(row.get("role") or "")))
            sel[2].markdown(_file_badge(row), unsafe_allow_html=True)
            sel[3].markdown(escape(str(row.get("size_text") or "")))
            sel[4].markdown(escape(str(row.get("origin_text") or "")))
            sel[5].markdown(escape(str(row.get("placement_text") or "")))
            if sel[6].button(t("ap.btn_read_file"), key=f"file_open_{item['id']}_{nama}",
                             use_container_width=True, disabled=nama == terbuka):
                st.session_state.setdefault(
                    _OPEN_FILE_KEY, {})[str(item["id"])] = nama
                st.rerun()

    # Hasil periksa berkas TERBACA tanpa menekan apa pun: justru temuan itulah
    # yang dicari peninjau, dan menyembunyikannya membuat ia membuka setiap
    # berkas satu per satu. Yang menunggu tombol Baca hanyalah SKRIPNYA, sebab
    # kode yang terbentang sendiri mendorong tabelnya jauh ke atas layar.
    current = next((r for r in rows if r["filename"] == terbuka), rows[0])
    st.divider()
    _render_file_review(item, current, tampilkan_kode=terbuka is not None)


def _render_file_review(item: dict, row: dict, *,
                        tampilkan_kode: bool = True) -> None:
    """Satu berkas paket: peran, ukuran, penjelasan pengunggah, temuan, kode.

    TANPA expander. Sebuah expander per berkas berarti peninjau harus membuka
    setiap berkas satu per satu untuk tahu apakah ada temuan di dalamnya —
    padahal justru itu yang ia cari. Isinya kini tergambar langsung, dan
    kodenya tetap tinggal di wadah bergulir sehingga berkas panjang tidak
    mendominasi layar.
    """
    entry = row["entry"]

    rp.file_heading(filename=row["filename"], role=row["role"],
                    size=format_size(row["size"]) if row.get("size") else "",
                    ok=bool(row["ok"]))

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

    source = entry.get("source") or ""
    if tampilkan_kode:
        _render_source_view(item, row["filename"], source)
    _render_file_actions(item, row["filename"], source, entry)


def _render_file_actions(item: dict, filename: str, source: str,
                         entry: dict) -> None:
    """Sunting, unduh berkas ini, unduh paketnya: SATU baris.

    Ketiganya tindakan atas berkas yang sedang dibaca, dan sebelumnya berdiri
    bertumpuk sebagai tiga tombol selebar halaman — tumpukan yang membaca
    seperti tiga langkah berurutan, padahal ketiganya sejajar. Tombol yang
    tidak berlaku (menyunting, bagi yang tidak berwenang; unduh paket, bagi
    pengajuan yang paketnya tidak terbaca) tidak menyisakan kolom kosong:
    barisnya menyusut.
    """
    from orchestrator.submission_service import (
        read_submission_sources, revision_blocker,
    )

    sid = item["id"]
    boleh_sunting = can_approve(current_user()) and not revision_blocker(item)
    paket = _safe_read("berkas paket", read_submission_sources, item,
                       default=[]) or []

    lebar = [1] * (1 + int(boleh_sunting) + int(bool(paket)))
    kolom = iter(st.columns(lebar))

    if boleh_sunting:
        if next(kolom).button(t("ap.btn_edit_source"),
                              key=f"edit_open_{sid}_{filename}",
                              use_container_width=True,
                              help=t("ap.help_edit_source")):
            _open_editor(sid, filename)
            st.rerun()

    next(kolom).download_button(
        t("ap.btn_download_file"), data=source.encode("utf-8"),
        file_name=filename, mime="text/x-python",
        key=f"review_dl_{filename}_{id(entry)}",
        use_container_width=True, help=t("ap.help_open_outside"))

    if paket:
        next(kolom).download_button(
            t("ap.btn_download_package", count=len(paket)),
            data=_package_archive(sid, _package_key(item), paket),
            file_name=f"pengajuan_{sid}_paket.zip", mime="application/zip",
            key=f"review_dl_pkg_{sid}", use_container_width=True,
            help=t("ap.help_download_package"))


#: Penanda formulir unggah-ulang yang sedang terbuka, per pengajuan.
#: Berawalan `_contrib`, jadi `page_flags.VIEW_STATE_PREFIXES` sudah
#: membuangnya saat identitas berganti.
_REVISE_OPEN_KEY = "_contrib_revise_open"


# `human_datetime` DIPAKAI BERSAMA halaman pipeline aktif: riwayat revisi
# pengajuan dan riwayat versi pipeline menulis waktunya dengan bentuk yang
# sama, jadi pemformatnya tinggal di lapis komponen dan bukan di halaman ini.
# Namanya tetap terbuka di sini sebab halaman ini memakainya di empat tempat.


def _render_revision_history(item: dict) -> None:
    """Putaran revisi sebelumnya, dan berkas tiap putaran.

    Baris di atas menjawab "paket mana yang sedang saya lihat". Yang ini
    menjawab pertanyaan berikutnya, yang dahulu tidak dapat dijawab sama
    sekali: "apa yang terjadi pada putaran satu, dan mengapa". Catatannya
    dahulu ditimpa tiap kali direvisi, jadi sebuah pengajuan dapat berkata
    "revisi ke-3" sementara dua putaran pertamanya sudah tidak ada di mana pun.

    Putaran yang foldernya sudah dibersihkan tetap muncul, dengan catatannya.
    Dibersihkan setelah keputusan memang disengaja, dan mendiamkan putaran itu
    akan membuat riwayatnya bolong tanpa keterangan.
    """
    riwayat = sr.revision_rows(item)
    if not riwayat:
        return
    # Putaran PERTAMA pun ditampilkan. Dahulu ia dilewati karena baris keadaan
    # berwarna di kotak "Yang diperiksa" sudah mengatakannya; baris itu sudah
    # dicabut, jadi melewatkannya sekarang berarti sebuah paket hasil suntingan
    # peninjau terbaca persis seperti kiriman asli kontributor.

    # Kotaknya digambar DI SINI, sesudah penjaga di atas. Membungkusnya dari
    # luar akan menyisakan kotak kosong berjudul pada pengajuan yang baru satu
    # putaran, dan kotak kosong terbaca seperti sesuatu yang gagal dimuat.
    with st.container(border=True):
        rp.zone_heading(rp.ZONE_READ, t("ap.revision_history"))
        _render_revision_table(item, riwayat)


#: Kolom tabel riwayat revisi. Bentuknya mengikuti `_FILE_COLS`: kolom
#: terakhir tanpa judul, berisi tombol baca.
_ROUND_COLS = (
    ("ap.col_round", 4),
    ("ap.col_round_by", 5),
    ("ap.col_round_when", 6),
    ("ap.col_round_touched", 6),
    ("ap.col_round_note", 9),
    ("", 3),                                  # tombol baca
)

#: Putaran yang sedang dibaca, per pengajuan.
_OPEN_ROUND_KEY = "_contrib_open_round"


def _render_revision_table(item: dict, riwayat: list[dict]) -> None:
    """Putaran revisi sebagai TABEL, lalu SATU putaran dibaca di bawahnya.

    Bentuk master-detail yang sama dengan tabel berkas tepat di atasnya.
    Dahulu tiap putaran adalah satu expander yang, begitu dibuka, mencetak
    SELURUH isi tiap berkas yang disentuh. Yang tidak terjawab justru
    pertanyaan pokoknya: baris mana yang disunting.
    """
    sid = str(item["id"])
    urut = list(reversed(riwayat))            # yang terbaru lebih dulu
    dibuka = st.session_state.get(_OPEN_ROUND_KEY, {}).get(sid)
    terbuka = (dibuka if any(r["round"] == dibuka for r in urut)
               else urut[0]["round"])
    lebar = [b for _, b in _ROUND_COLS]

    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, (kunci, _) in zip(kepala, _ROUND_COLS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for baris in urut:
        putaran = baris["round"]
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            tanda = "**" if putaran == terbuka else ""
            sel[0].markdown(f"{tanda}{t('ap.round_n', round=putaran)}{tanda}")
            sel[1].markdown(escape(str(baris["by"] or "-")))
            sel[2].markdown(human_datetime(baris["at"]))
            sel[3].markdown(_round_touched_text(baris))
            sel[4].markdown(escape(_potong(baris["note"])))
            if sel[5].button(t("ap.btn_read_file"),
                             key=f"round_open_{item['id']}_{putaran}",
                             use_container_width=True,
                             disabled=putaran == terbuka):
                st.session_state.setdefault(
                    _OPEN_ROUND_KEY, {})[sid] = putaran
                st.rerun()

    st.divider()
    _render_revision_round(item, riwayat,
                           next(r for r in urut if r["round"] == terbuka))


def _potong(teks: str, *, batas: int = 60) -> str:
    """Teks yang dipotong supaya satu sel tabel tetap satu baris."""
    teks = " ".join(str(teks or "").split())
    return teks if len(teks) <= batas else teks[:batas - 1] + "…"


def _round_touched_text(baris: dict) -> str:
    """Berapa berkas disentuh putaran ini, dan yang mana."""
    if not baris["touched"]:
        return t("ap.round_touched_none")
    nama = baris["changed"] + baris["added"]
    return escape(t("ap.round_touched", count=len(nama),
                    files=_potong(", ".join(nama), batas=28)))


def _render_revision_round(item: dict, riwayat: list[dict],
                           baris: dict) -> None:
    """Satu putaran, dengan BARIS yang disunting disorot.

    Sisi "sebelum" sebuah putaran adalah hasil putaran sebelumnya; untuk
    putaran pertama, paket asli yang diarsipkan sebelum revisi mana pun.
    Keduanya folder di disk, dan keduanya dapat sudah dibersihkan setelah
    pengajuan diputuskan. Bila pembandingnya tidak ada, isi berkasnya tetap
    ditampilkan apa adanya beserta sebabnya: menebak sisi yang hilang akan
    membuat sorotan berbohong.
    """
    from orchestrator.submission_service import revision_of, revision_sources

    # Catatan peninjau, daftar berkas yang TETAP, dan kalimat "tidak mengubah
    # apa pun" tidak digambar lagi di sini: ketiganya sudah terbaca di baris
    # tabelnya, pada kolom Catatan dan kolom Berkas disentuh. Mengulanginya di
    # bawah tabel hanya menambah prosa yang dilewati mata.
    if not baris["touched"]:
        return

    sesudah = dict(_safe_read("paket putaran revisi", revision_sources,
                              baris, default=[]) or [])
    if not sesudah:
        st.markdown(t("ap.revision_round_gone"))
        return

    urut = sorted(riwayat, key=lambda r: r["round"])
    sebelum_entri = next(
        (r for r in reversed(urut) if r["round"] < baris["round"]), None)
    if sebelum_entri is not None:
        sumber_lama = {"path": sebelum_entri["path"]}
    else:
        # Putaran pertama: pembandingnya paket ASLI sebelum revisi mana pun.
        sumber_lama = {"path": revision_of(item).get("original_path") or ""}
    sebelum = dict(_safe_read("paket pembanding revisi", revision_sources,
                              sumber_lama, default=[]) or [])

    for nama in baris["changed"] + baris["added"]:
        st.markdown(f"`{escape(nama)}`")
        baru = sesudah.get(nama, "")
        # Berkas yang DITAMBAHKAN tidak punya sisi sebelum. Memaksanya menjadi
        # diff hanya menghasilkan satu blok hijau utuh yang tidak memberi tahu
        # apa pun lebih daripada isinya sendiri.
        if nama in baris["added"]:
            st.markdown(t("ap.round_file_added"))
            st.code(baru, language="python", line_numbers=True)
            continue
        if nama not in sebelum:
            st.markdown(t("ap.round_no_baseline"))
            st.code(baru, language="python", line_numbers=True)
            continue
        rows = sr.diff_rows(sebelum[nama], baru)
        if not rows:
            st.markdown(t("ap.round_file_same"))
            continue
        hitung = sr.diff_counts(rows)
        st.markdown(t("ap.round_diff_counts", added=hitung["added"],
                      removed=hitung["removed"]))
        st.markdown(
            sr.diff_html(rows, head_old=t("ap.col_diff_old"),
                         head_new=t("ap.col_diff_new"),
                         # Tanpa nilai, `t` mengembalikan kalimatnya apa
                         # adanya, dan `{count}` diisi penyusun tabelnya.
                         skipped_text=t("ap.diff_skipped")),
            unsafe_allow_html=True)



_PLACEMENT_SAVED_KEY = "_contrib_placement_saved"


def _placement_widget_keys(sid: int, nama: str) -> tuple[str, str]:
    return f"place_ph_{sid}_{nama}", f"place_algo_{sid}_{nama}"


def _render_placement_editor(item: dict, user: dict) -> None:
    """Menempatkan tiap berkas paket pada fase dan algoritmanya.

    Yang dijawab di sini: berkas mana bekerja pada fase mana, untuk algoritma
    yang mana. Sebelum ini tidak ada satu tempat pun yang menyatakannya, dan
    sebuah berkas pendukung yang dipakai tiga algoritma sekaligus hanya berdiri
    sebagai nama di daftar berkas.

    Petanya MENERANGKAN, tidak menentukan apa pun yang dijalankan. Karena itu
    berkas yang belum ditempatkan tidak pernah mematikan tombol Setujui: ia
    ditandai, dan jumlahnya disebut pada keterangan tombolnya.

    Peta awal disemai dari apa yang kode nyatakan; yang sudah disimpan
    Research Admin menang atas semaian itu.
    """
    from orchestrator.submission_service import SubmissionError, set_placement

    rp.zone_heading(rp.ZONE_WORK, t("ap.sec_placement"),
                    help=t("ap.help_placement"))
    peta = sr.seeded_placement(item)
    if not peta:
        st.markdown(t("ap.placement_no_files"))
        return

    sid = item["id"]
    fase_pilihan = sr.phase_options(item)
    algo_pilihan = sr.algorithm_options(item)
    if st.session_state.pop(f"{_PLACEMENT_SAVED_KEY}_{sid}", False):
        st.success(t("ap.msg_placement_saved"))

    if not can_approve(user):
        # Bukan peninjau: petanya tetap TERBACA, hanya tidak dapat diubah.
        for nama, entri in peta.items():
            st.markdown(t("ap.placement_row",
                          filename=nama,
                          phases=_placement_text(entri["phases"]),
                          algorithms=_placement_text(
                              [_algo_label(a) for a in entri["algorithms"]])))
        return

    tersunting: dict[str, dict] = {}
    for nama, entri in peta.items():
        kunci_fase, kunci_algo = _placement_widget_keys(sid, nama)
        st.markdown(f"`{escape(nama)}`")
        kol = st.columns(2)
        fase = kol[0].multiselect(
            t("ap.lbl_placement_phase"), fase_pilihan,
            default=[f for f in entri["phases"] if f in fase_pilihan],
            key=kunci_fase)
        # Kategori algoritma boleh DIBUAT di sini. Daftar bawaannya hanya
        # kelas yang benar-benar dideklarasikan paket; sebuah berkas pendukung
        # dapat melayani pengelompokan yang tidak punya kelasnya sendiri
        # (mis. "Praproses bersama"), dan memaksa peninjau memilih dari daftar
        # tertutup berarti menyuruhnya salah menempatkan berkas itu.
        algo = kol[1].multiselect(
            t("ap.lbl_placement_algorithm"),
            algo_pilihan + [a for a in entri["algorithms"]
                            if a not in algo_pilihan],
            default=entri["algorithms"], accept_new_options=True,
            format_func=_algo_label, key=kunci_algo,
            help=t("ap.help_placement_algorithm"))
        tersunting[nama] = {"phases": fase, "algorithms": algo}

    if st.button(t("ap.btn_save_placement"), key=f"place_save_{sid}",
                 use_container_width=True):
        try:
            set_placement(sid, tersunting, actor=user)
        except (AuthError, SubmissionError) as e:
            st.error(error_message(e))
        except Exception as e:
            logger.exception("Penempatan pengajuan #%s gagal disimpan", sid)
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
        else:
            st.session_state[f"{_PLACEMENT_SAVED_KEY}_{sid}"] = True
            st.rerun()


def _algo_label(value: str) -> str:
    """Nama kelas apa adanya; pengenal "semua algoritma" diterjemahkan."""
    return t("ap.placement_all_algorithms") if value == sr.ALGO_ALL else value


def _placement_text(values: list[str]) -> str:
    """Daftar penempatan sebagai satu baris; kosong menjadi penanda."""
    return ", ".join(values) if values else t("ap.placement_unassigned")


#: Asal berkas pada rencana revisi. Rona yang sama dengan tabel lain.
_REVISI_KEADAAN = {"diubah": "warn", "ditambahkan": "ok", "tetap": "none"}


def _revision_plan(berlaku: dict, diunggah: dict) -> list[tuple[str, str]]:
    """Keadaan tiap berkas bila revisi ini disimpan: diubah, ditambahkan, tetap.

    Dipisahkan dari penggambarannya karena dua hal membutuhkannya: tabel
    rencana, dan tombol Simpan — sebuah revisi yang seluruh berkasnya "tetap"
    tidak mengubah apa pun, dan tombol itu harus mati SEBELUM ditekan, bukan
    menghasilkan pesan galat sesudahnya.
    """
    semua = {**berlaku, **{n: s.decode("utf-8", "replace")
                           for n, s in diunggah.items()}}
    baris = []
    for nama in sorted(semua):
        if nama not in berlaku:
            baris.append((nama, "ditambahkan"))
        elif nama in diunggah and berlaku[nama].encode("utf-8") != diunggah[nama]:
            baris.append((nama, "diubah"))
        else:
            baris.append((nama, "tetap"))
    return baris


def _render_revision_plan(berlaku: dict, diunggah: dict) -> None:
    """Apa yang akan terjadi pada tiap berkas bila revisi ini disimpan.

    Tiga keadaan, dan ketiganya perlu terbaca: berkas yang DIUBAH, berkas yang
    DITAMBAHKAN, dan berkas yang TETAP. Yang terakhir justru yang paling
    penting: tanpa baris itu, peninjau yang mengunggah satu berkas tidak punya
    cara mengetahui bahwa tiga berkas lainnya tidak hilang.
    """
    baris = _revision_plan(berlaku, diunggah)

    st.markdown(f"**{t('ap.revision_plan')}**")
    for nama, keadaan in baris:
        rona = grid.STATE_TINT.get(_REVISI_KEADAAN[keadaan])
        gaya = f'style="background:{rona};"' if rona else ""
        st.markdown(
            f'<span class="ids-badge ids-badge-solid" {gaya}>'
            f'{escape(t("ap.revision_state_" + keadaan))}</span> '
            f'<code>{escape(nama)}</code>', unsafe_allow_html=True)


def _render_revision_upload(item: dict, user: dict) -> None:
    """Unggah balik paket hasil suntingan sebagai revisi pengajuan ini.

    Penghalangnya dibaca dari lapis aksi yang sama yang akan menolaknya nanti,
    jadi tombol yang tampak hidup selalu berarti aksinya memang boleh — dan
    tombol yang mati selalu menyebutkan sebabnya.
    """
    from orchestrator.submission_service import (
        SubmissionError, revise_submission, revision_blocker,
    )

    rp.zone_heading(rp.ZONE_WORK, t("ap.zone_revise"))
    stop = revision_blocker(item)
    if stop:
        st.markdown(t(stop))
        return

    sid = item["id"]
    tertunda = draft_of(sid)
    # Suntingan di tempat membuka bagian ini sendiri. Menyembunyikannya di
    # balik tombol lain berarti peninjau menyunting sesuatu lalu kehilangan
    # jalan untuk menyimpannya.
    if tertunda and st.session_state.get(_REVISE_OPEN_KEY) != sid:
        st.session_state[_REVISE_OPEN_KEY] = sid
    if st.session_state.get(_REVISE_OPEN_KEY) != sid:
        if st.button(t("ap.btn_revise"), key=f"revise_open_{sid}",
                     use_container_width=True, help=t("ap.help_revise")):
            st.session_state[_REVISE_OPEN_KEY] = sid
            st.rerun()
        return

    if tertunda:
        st.markdown(t("ap.draft_pending", count=len(tertunda)))

    berkas = st.file_uploader(
        t("ap.lbl_revision_files"), type=["py"], accept_multiple_files=True,
        key=f"revise_files_{sid}", help=t("ap.help_revision_files"))
    berkas = berkas or []

    # Titik masuk DIDETEKSI, tidak ditanyakan: `review_package` sudah membaca
    # kelas turunan `BasePipeline` dari AST tiap berkas, jadi meminta peninjau
    # menunjuknya berarti meminta jawaban yang sudah diketahui platform.
    #
    # Tetapi mendeteksi BUKAN berarti memilih ulang. Paket boleh membawa
    # beberapa algoritma, dan mengambil titik masuk pertama yang kebetulan
    # terbaca akan MENGGANTI identitas pengajuan diam-diam: sebuah revisi yang
    # tidak mengubah satu byte pun pernah menggeser titik masuknya dari
    # `svm_pipeline.py` ke `knn_pipeline.py`, sehingga kelas yang akan
    # didaftarkan saat disetujui bukan lagi kelas yang diajukan. Jadi titik
    # masuk yang SEDANG BERLAKU dipertahankan selama ia masih ada di paket
    # revisi; deteksi hanya dipakai bila ia benar-benar hilang.
    entry, terbaca, berubah = "", None, False
    if berkas or tertunda:
        # Yang diperiksa adalah paket HASIL GABUNGAN, bukan berkas yang baru
        # saja diunggah. Peninjau yang menyunting satu berkas mengunggah satu
        # berkas; membaca titik masuk dari unggahan itu saja akan menolak
        # revisi yang sah hanya karena berkas titik masuknya tidak ikut
        # diunggah, padahal ia tetap ada di paket.
        from orchestrator.submission_service import read_submission_sources

        berlaku = dict(_safe_read("paket berlaku", read_submission_sources,
                                  item, default=[]) or [])
        diunggah = {**{n: s.encode("utf-8") for n, s in tertunda.items()},
                    **{f.name: f.getvalue() for f in berkas}}
        gabungan = {**{n: s.encode("utf-8") for n, s in berlaku.items()},
                    **diunggah}

        terbaca = _safe_read("paket revisi", review_package,
                             list(gabungan.items()), default=None)
        titik = list((terbaca or {}).get("entry_points") or [])
        sekarang = str((item.get("metadata") or {}).get("entry_filename")
                       or item.get("original_filename") or "")
        # Mendeteksi BUKAN memilih ulang. Titik masuk yang SEDANG BERLAKU
        # dipertahankan selama ia masih ada; deteksi hanya dipakai bila ia
        # benar-benar hilang. Sebuah revisi yang tidak mengubah satu byte pun
        # pernah menggeser titik masuknya dari `svm_pipeline.py` ke
        # `knn_pipeline.py`, sehingga kelas yang didaftarkan saat disetujui
        # bukan lagi kelas yang diajukan.
        entry = sekarang if sekarang in titik else (titik[0] if titik else "")

        if entry:
            st.markdown(t("ap.revision_entry_found", filename=entry,
                          count=len(gabungan)))
            if sekarang and entry != sekarang:
                # Pergantian titik masuk adalah perubahan IDENTITAS, jadi ia
                # dikatakan, bukan dilakukan diam-diam.
                st.warning(t("ap.revision_entry_changed",
                             old=sekarang, new=entry))
        else:
            st.warning(t("ap.revision_no_entry"))

        # Apa yang akan terjadi pada TIAP berkas, sebelum Simpan ditekan.
        # Unggahan menambal paket yang berlaku, dan "berkas lain tetap" adalah
        # hal yang harus terbaca, bukan disimpulkan sendiri oleh peninjau.
        _render_revision_plan(berlaku, diunggah)

        # Unggahan yang isinya sama persis dengan paket yang berlaku bukan
        # revisi: ia hanya akan membuat satu putaran kosong beserta satu
        # salinan penuh paket yang sama di disk. Dikatakan di sini, sebelum
        # Simpan ditekan, dan ditolak lagi oleh `revise_submission` — tombol
        # yang mati tidak pernah menjadi satu-satunya penghalang.
        berubah = any(k in ("diubah", "ditambahkan")
                      for _, k in _revision_plan(berlaku, diunggah))
        if not berubah:
            st.warning(t("ap.revise_no_change"))

    catatan = st.text_area(t("ap.lbl_revision_note"), height=80,
                           key=f"revise_note_{sid}",
                           placeholder=t("ap.ph_revision_note"),
                           help=t("ap.help_revision_note"))

    aksi = st.columns([1, 1, 3])
    siap = bool(entry) and bool((catatan or "").strip()) and berubah
    sebab = ("" if siap else t("ap.revise_no_change") if entry and not berubah
             else t("ap.help_revision_incomplete"))
    if aksi[0].button(t("ap.btn_save_revision"), key=f"revise_save_{sid}",
                      type="primary", use_container_width=True,
                      disabled=not siap, help=sebab or None):
        try:
            isi = list(tertunda.items())
            isi += [(f.name, f.getvalue().decode("utf-8")) for f in berkas]
        except UnicodeDecodeError:
            st.error(t("ap.revise_not_text"))
            return
        try:
            revise_submission(sid, isi, entry, note=catatan, actor=user)
        except (AuthError, SubmissionError) as e:
            st.error(error_message(e))
        except Exception as e:
            logger.exception("Revisi pengajuan #%s gagal tak terduga", sid)
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
        else:
            st.session_state.pop(_REVISE_OPEN_KEY, None)
            st.session_state.get(_DRAFT_KEY, {}).pop(str(sid), None)
            st.success(t("ap.msg_revised", number=sid))
            st.rerun()

    if aksi[1].button(t("action.cancel"), key=f"revise_cancel_{sid}",
                      use_container_width=True):
        st.session_state.pop(_REVISE_OPEN_KEY, None)
        st.rerun()


def render_review_body(item: dict, user: dict) -> None:
    """Kartu peninjauan satu pengajuan — permukaan PUBLIK modul ini.

    Dipakai halaman pipeline terdaftar (``ui/views/manage_pipelines``) supaya
    peninjauan penuh tidak perlu disalin ke sana. Impornya LAZY di sisi
    pemanggil: ``contribute`` sudah mengimpor ``manage_pipelines`` di tingkat
    modul, jadi impor balik di tingkat modul akan sirkular.
    """
    _render_submission_review_card(item, user)


_CONFIRM_DEL_SUB_KEY = "_contrib_confirm_delete"


def _render_delete_submission(item: dict, user: dict) -> None:
    """Tombol "Hapus pengajuan" + konfirmasi yang MENYEBUT apa yang ikut hilang.

    Berlaku untuk semua status. Yang sudah disetujui ikut dapat dihapus —
    pipeline terdaftarnya tetap berjalan, hanya kartu peninjauannya yang
    hilang, dan itu dikatakan sebelum tombolnya ditekan.
    """
    from orchestrator.submission_service import (
        SubmissionError, delete_submission, deletion_summary,
    )

    sid = item["id"]
    if st.session_state.get(_CONFIRM_DEL_SUB_KEY) != sid:
        if st.button(t("ap.btn_delete_submission"), key=f"del_sub_{sid}",
                     use_container_width=True):
            st.session_state[_CONFIRM_DEL_SUB_KEY] = sid
            st.rerun()
        return

    summary = _safe_read("ringkasan penghapusan", deletion_summary, item,
                         default={}) or {}
    extra = ""
    if summary.get("attachment_kept"):
        extra += t("ap.delete_keeps_dataset")
    st.warning(t("ap.delete_confirm", number=sid,
                 files=summary.get("files", 0),
                 uji=summary.get("trials", 0), extra=extra))
    if summary.get("registered"):
        st.warning(t("ap.delete_warns_registered",
                     count=summary["registered"]))

    confirm = st.columns([1, 1, 3])
    if confirm[0].button(t("ap.btn_delete_submission"), key=f"del_yes_{sid}",
                         type="primary", use_container_width=True):
        try:
            delete_submission(sid, actor=user)
        except (AuthError, SubmissionError) as e:
            st.error(error_message(e))
        except Exception as e:
            logger.exception("Penghapusan pengajuan #%s gagal tak terduga", sid)
            st.error(t("ap.err_unexpected", kind=type(e).__name__))
        else:
            st.session_state.pop(_CONFIRM_DEL_SUB_KEY, None)
            _close_submission()
            st.success(t("ap.msg_submission_deleted", number=sid))
            st.rerun()
    if confirm[1].button(t("action.cancel"), key=f"del_no_{sid}",
                         use_container_width=True):
        st.session_state.pop(_CONFIRM_DEL_SUB_KEY, None)
        st.rerun()


def _render_submission_review_card(item: dict, user: dict,
                                   latest=_UNREADABLE) -> None:
    """Satu pengajuan: identitas, berkas, pemeriksaan, kode, keputusan.

    Seluruh isinya berasal dari pengajuan yang TERSIMPAN. Kode hanya
    ditampilkan sebagai teks — tidak pernah di-import maupun dijalankan.

    ``latest`` OPSIONAL: uji terakhir pengajuan ini, sudah diambil pemanggil
    (lihat ``database.trials.latest_trials_for``). Tanpa itu, kartu ini membaca
    sendiri.

    Dipanggil untuk pengajuan yang BENAR-BENAR DIBUKA saja — satu pada satu
    waktu, TANPA expander pembungkus: peninjau sudah memilih pengajuan ini,
    jadi wadah yang harus diklik untuk melihat isinya hanya menambah satu
    langkah tanpa menyembunyikan apa pun.

    Halamannya dibagi TIGA ZONA yang dibedakan secara visual, karena ketiganya
    dibaca dengan sikap yang berbeda:

    * **yang diperiksa** — identitas, daftar berkas, temuan, kode. Dibaca.
    * **pengujian** — menjalankan uji coba dan membaca hasilnya.
    * **keputusan** — catatan, setujui/tolak/hapus. Di sinilah keadaan berubah.

    Uji coba sempat tinggal di dalam zona "keputusan", padahal menjalankan uji
    dan memutuskan adalah dua pekerjaan berbeda — dan judul zonanya hanya
    menyebut yang kedua.
    """
    reviewed = _reviewed_package(item["id"], _package_key(item), item)
    row = sr.summary_row(item, reviewed)

    _render_review_header(row)

    with st.container(border=True):
        rp.zone_heading(rp.ZONE_READ, t("ap.zone_examined"))

        # 1. Identitas & metadata, dengan bentuk baris yang sama seperti
        #    tabel berkas di bawahnya.
        # Nilai yang berbentuk cap waktu ISO ditulis untuk dibaca orang.
        # Dilewatkan di SINI dan bukan di `sr.metadata_rows`, sebab fungsi itu
        # murni dan dipakai juga oleh pembaca yang membandingkan nilainya apa
        # adanya; `human_datetime` mengembalikan yang bukan cap waktu tanpa
        # mengubahnya, jadi melewatkan seluruh nilai aman.
        fakta = [(label, human_datetime(nilai))
                 for label, nilai in sr.metadata_rows(item)]
        # Sidik jari kiriman ASLI berdampingan dengan sidik jari paket yang
        # berlaku: keduanya hash, dan pembaca yang mencari salah satunya
        # sedang membandingkannya dengan yang lain. Hanya muncul bila paket
        # ini memang pernah direvisi.
        from orchestrator.submission_service import revision_of

        jejak = revision_of(item)
        if jejak.get("original_hash"):
            fakta.append((t("ap.lbl_original_package"),
                          jejak["original_hash"][:12] + "…"))
        _render_fact_rows(fakta)

        # 2 & 3. Berkas paket sebagai TABEL, lalu SATU berkas dibaca.
        #
        # Sebelumnya seluruh berkas digambar berurutan: tiap berkas menambah
        # sembilan blok teks dan satu blok kode setinggi 320px, jadi sepuluh
        # berkas berarti seratus blok dan ~3.200px kode di satu halaman.
        # Pertumbuhannya kini datar — satu BARIS per berkas — dan hasil
        # periksa seluruh berkas tetap terbaca sekaligus lewat kolom berwarna,
        # yang justru tidak dapat dilakukan expander.
        # Jumlah berkas dan hasil periksanya SUDAH tertulis di kepala kartu
        # ("4 berkas" dan lencana putusannya), jadi mengulangnya di sini hanya
        # menambah satu baris yang dilewati mata.

    # Tiga hal yang dahulu berdesakan di dalam satu kotak "Yang diperiksa":
    # metadata, berkas paket, dan riwayat revisi. Yang pertama menjawab
    # "pengajuan ini apa", yang kedua "isinya apa", yang ketiga "sudah
    # diapakan". Tiga pertanyaan, tiga kotak.
    with st.container(border=True):
        rp.zone_heading(rp.ZONE_READ, t("ap.zone_package_files"))
        _render_file_table(item, sr.file_rows(item, reviewed))

    _render_revision_history(item)

    # Tahap TERSENDIRI: menempatkan berkas adalah menyatakan sesuatu tentang
    # paket, bukan membaca hasil periksanya.
    with st.container(border=True):
        _render_placement_editor(item, user)

    # Tahap TERSENDIRI, bukan sambungan dari kotak di atas: mengunggah balik
    # paket adalah perbuatan, sedangkan kotak di atas adalah bacaan. Peninjau
    # harus dapat melihat batas antara "saya sedang memeriksa" dan "saya
    # sedang mengubah kiriman orang lain".
    with st.container(border=True):
        _render_revision_upload(item, user)


    from orchestrator.submission_service import is_standalone as _berdiri

    with st.container(border=True):
        # Judulnya menyebut PUTARAN yang diuji. Uji coba selalu berjalan atas
        # paket yang BERLAKU, dan paket yang berlaku berubah setiap kali
        # peninjau mengunggah revisi — jadi hasil uji yang terbaca di layar
        # dapat berasal dari putaran sebelumnya. Tanpa nomor putaran di
        # judulnya, "Passed" pada putaran 2 terbaca seolah-olah berlaku bagi
        # putaran 3 yang baru saja diunggah.
        rp.zone_heading(rp.ZONE_TEST, t("ap.zone_testing"),
                        help=_trial_help(item))
        _render_trial_step(item, user, latest)

    with st.container(border=True):
        # Keterangan identitas hanya berlaku bagi pengajuan yang berdiri
        # sendiri; memasangnya pada yang lain berarti tooltip yang berbohong.
        rp.zone_heading(
            rp.ZONE_WORK, t("ap.zone_decision"),
            help=t("ap.help_research_identity") if _berdiri(item) else "")

        # Pertanyaan "ini ikut research pipeline mana" hanya bermakna bagi
        # pengajuan yang MENUMPANG keluarga bawaan. Sebuah research pipeline
        # yang berdiri sendiri membawa kontrak datasetnya sendiri, jadi
        # pengenalnya dibentuk dari namanya — bukan dipilih peninjau. Menanyakan
        # itu di sana akan meminta keputusan yang tidak ada pilihannya.
        from orchestrator.submission_service import (
            approval_identity_blocker, declared_schema_of, is_standalone,
            research_name_of,
        )

        # TIDAK ADA "Dataset target" di sini. Peninjau tidak punya kewenangan
        # untuk menentukannya: paket yang diunggah ADALAH research pipeline-nya
        # sendiri, jadi pengenalnya dibentuk dari namanya. Meminta peninjau
        # memilih dataset target berarti meminta keputusan yang tidak ada
        # pilihan benarnya, lalu menyimpannya sebagai fakta.
        if is_standalone(item):
            from database.models import build_research_dataset_type

            declared = declared_schema_of(item)
            _render_fact_rows([
                (t("ap.lbl_research_identity"), research_name_of(item)),
                (t("ap.lbl_research_identifier"),
                 build_research_dataset_type(research_name_of(item))),
                (t("ap.lbl_label_column"), declared.get("label_column") or "-"),
                (t("ap.lbl_required_columns"),
                 str(len(declared.get("expected_columns") or []))),
            ])
        else:
            # Pengajuan LAMA: identitasnya tercatat pada metadatanya sendiri,
            # ditampilkan apa adanya. Bila memang tidak ada, itu dinyatakan
            # lewat gerbang di bawah — bukan ditambal dengan isian.
            meta = item.get("metadata") or {}
            _render_fact_rows([
                (t("ap.lbl_research_identity"), research_name_of(item)),
                (t("ap.lbl_research_identifier"),
                 (meta.get("dataset_type") or "").strip() or "-"),
            ])
        note = st.text_input(
            t("ap.lbl_review_note"), key=f"review_note_{item['id']}",
            placeholder=t("ap.ph_review_note"))

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
        # Identitas diperiksa LEBIH DULU: "tidak akan pernah dapat disetujui"
        # adalah keterangan yang lebih berguna daripada "belum diuji", dan
        # menyuruh peninjau menguji sesuatu yang tetap akan ditolak hanya
        # membuang waktunya.
        gate = approval_identity_blocker(item) or gate
        cols = st.columns(2)
        if cols[0].button(t("action.approve"),
                          key=f"review_approve_{item['id']}",
                          type="primary", use_container_width=True,
                          disabled=bool(gate),
                          help=_approve_help(gate, reviewed, item)):
            try:
                # `dataset_type` TIDAK disodorkan lagi: layanannya sudah
                # mengambilnya dari metadata pengajuan, dan tidak ada lagi
                # nilai pilihan peninjau yang dapat menimpanya.
                approve_submission(item["id"], actor=user, note=note)
            except AuthError as e:
                st.error(error_message(e))
            except Exception as e:
                # Menyetujui memindahkan berkas, menulis basis data, DAN
                # mendaftarkan pipeline — jadi OSError, kesalahan basis data,
                # maupun DynamicRegistryError semuanya mungkin di sini, dan
                # tidak satu pun turunan AuthError. Sebelumnya semuanya lolos
                # sebagai jejak teknis ke peninjau.
                logger.exception(
                    "Persetujuan pengajuan #%s gagal tak terduga",
                    item["id"])
                st.error(t("ap.err_unexpected", kind=type(e).__name__))
            else:
                st.success(
                    _latest_registration(item)
                    + f" Ditinjau {user['username']} pada {now_iso()[:19]}."
                    + (f" Catatan: {note}" if note.strip() else ""))
                st.rerun()
        _render_delete_submission(item, user)

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
    """Kalimat konfirmasi persetujuan — dan ke MANA hasilnya pergi.

    Sebelumnya ia hanya menyebut pengenal mesin dan hash berkas. Keduanya
    benar dan keduanya tidak menjawab pertanyaan yang sebenarnya ada di kepala
    peninjau setelah menekan Setujui: berhasil, lalu ada di mana?

    Maka yang disebut sekarang: NAMA research pipeline-nya sebagaimana pengguna
    lain akan melihatnya, berapa algoritma yang ikut, dan halaman tempatnya
    muncul. Bila datasetnya justru tidak ditemukan, itu dikatakan di sini juga
    — bukan ditemukan sendiri nanti di halaman lain.
    """
    from orchestrator.submission_service import research_name_of
    from ui.components.pipeline_catalog import has_dataset_for

    try:
        from orchestrator.dynamic_registry import list_registered
        rows = [r for r in list_registered()
                if r.get("submission_id") == item["id"]]
    except Exception:                       # pragma: no cover - defensif
        rows = []
    if not rows:
        return t("ap.msg_approved_live", research=research_name_of(item) or "-",
                 count=0)

    dataset_type = rows[0].get("dataset_type") or ""
    try:
        from orchestrator.research_registry import display_name_for

        research = display_name_for(dataset_type) or dataset_type
    except Exception:                       # pragma: no cover - defensif
        research = dataset_type
    key = ("ap.msg_approved_live" if has_dataset_for(dataset_type)
           else "ap.msg_approved_no_dataset")
    return t(key, research=research, count=len(rows))


# ── Kelola pengguna (Research Admin) ──────────────────────────────────────

# ── Kelola pengguna: bentuk tabel & filternya ────────────────────────────
#
# Lebar kolom ditulis SEKALI dan dipakai baris judul maupun baris isinya, jadi
# keduanya tidak mungkin bergeser satu sama lain.
#: Bobot lebar kolom tabel pengguna — SEBANDING dengan isi terpanjang tiap
#: kolom, bukan angka bulat yang rata. Diukur pada lebar konten ±1040px
#: (1 satuan ≈ 10px): Pengguna `Ai`+pil "akun Anda" 103px, Peran pil
#: "Research Admin" 96px, Status "Nonaktif" 43px, Instansi teks bebas, Dibuat
#: "17 Agu 2026, 13:59" 96px, Diaktifkan "Ai · 22 Agu 2026, 07:32" 123px,
#: tombol "Aktifkan kembali" 110px, tombol "Jadikan Kontributor" 126px.
#: Masing-masing dapat ±8% kelonggaran di atas kebutuhannya.
#:
#: Pembagian sebelumnya `[2,2,2,3,2,3,2,2]` memberi Status 92px untuk 43px isi
#: sementara Peran, Dibuat, dan kedua tombol kurang — sehingga pil patah dua,
#: tanggal turun ke baris kedua, dan label tombol terpotong menjadi
#: "Jadikan A…". Totalnya tidak pernah kurang: seluruh kebutuhan ±757px dari
#: ±840px yang tersedia. Itu salah bagi, bukan kurang ruang.
#:
#: Angkanya BOBOT, bukan piksel: rasionya bertahan di lebar jendela mana pun.
#: SATU kolom aksi, bukan dua. Dahulu kolom terakhir memuat DUA tombol
#: bertumpuk ("Jadikan Admin" di atas "Reset sandi"), sehingga setiap baris
#: setinggi dua tombol dan daftar sepuluh akun tidak muat di satu layar.
#: Sekarang tindakan utamanya berdiri sendiri dan dua tindakan lain masuk ke
#: satu panel ringkas di sebelahnya.
_USER_COLS = [11, 10, 5, 7, 10, 12, 16]
_USER_HEADERS = ("ap.users_col_username", "ap.users_col_role",
                 "ap.users_col_status", "ap.users_col_institution",
                 "ap.users_col_created", "ap.users_col_activated",
                 "ap.users_col_actions")

#: Akun yang sandinya sedang direset. Berawalan `_contrib` seperti penanda
#: sub-tampilan lain, jadi ia ikut terbuang saat pengguna berpindah halaman.
_RESET_PW_KEY = "_contrib_reset_password"

#: Penanda sel tanpa nilai — sama dengan yang dipakai tabel eksperimen.
_USER_EMPTY = "-"

#: Kunci filter di session_state. Berawalan `_contrib`, jadi `page_flags`
#: sudah membuangnya saat pengguna berpindah halaman.
_USER_FILTER_KEY = "_contrib_user_filters"


#: Peran → latar pilnya. Alpha-nya lebih pekat daripada `tint` kartu: di sana
#: warna hanya menghias panel besar, di sini ia yang membedakan dua nilai pada
#: satu kolom sempit. Ditulis rgba, bukan hex, mengikuti aturan warna repo ini.
_ROLE_TINT = {
    ROLE_RESEARCH_ADMIN: "rgba(148,163,184,.22)",   # abu netral
    ROLE_CONTRIBUTOR: "rgba(245,158,11,.30)",       # kuning keemasan
}


def _role_badge(row: dict) -> str:
    """Peran sebagai PIL berwarna, bukan teks datar.

    Dua peran pada satu kolom sempit terbaca sebagai dua kata yang mirip
    panjangnya; warna membuat bedanya tertangkap tanpa membaca hurufnya.
    Warnanya BUKAN satu-satunya pembeda — tulisannya tetap menyebut perannya,
    jadi pembaca yang tidak membedakan warna tidak kehilangan apa pun.
    """
    peran = normalize_role(row.get("role"))
    latar = _ROLE_TINT.get(peran, _ROLE_TINT[ROLE_CONTRIBUTOR])
    label = row.get("role_label") or role_label(peran)
    return (f'<span class="ids-badge ids-badge-solid" '
            f'style="background:{latar};">{escape(str(label))}</span>')


def _user_cell(value) -> str:
    """Nilai sel, atau penanda kosong. Tidak pernah menebak."""
    teks = str(value or "").strip()
    return teks or _USER_EMPTY


def _activated_cell(row: dict) -> str:
    """Siapa mengaktifkan akun ini, dan kapan.

    Keduanya hanya terisi bila akunnya memang pernah diaktifkan seorang
    Research Admin; pendaftaran mandiri langsung aktif tanpa melewati siapa
    pun, dan selnya memang kosong. Itu fakta, bukan data yang hilang.
    """
    siapa = str(row.get("activated_by") or "").strip()
    kapan = format_stamp(row.get("activated_at"))
    if siapa and kapan:
        return f"{siapa} · {kapan}"
    return _user_cell(siapa or kapan)


def _user_institutions(users) -> list[str]:
    """Instansi yang BENAR-BENAR ada pada daftar, urut abjad."""
    return sorted({str(u.get("institution") or "").strip()
                   for u in users if str(u.get("institution") or "").strip()})


def _match_user(row: dict, filters: dict) -> bool:
    """Fungsi MURNI: apakah satu baris lolos filter. Filter kosong = lolos."""
    cari = (filters.get("query") or "").strip().lower()
    if cari and cari not in str(row.get("username") or "").lower():
        return False
    if filters.get("roles") and row.get("role") not in filters["roles"]:
        return False
    if filters.get("statuses") and row.get("status") not in filters["statuses"]:
        return False
    if filters.get("institutions"):
        instansi = str(row.get("institution") or "").strip()
        if instansi not in filters["institutions"]:
            return False
    return True


def _render_user_filters(users) -> dict:
    """Filter bergaya riwayat eksperimen: satu popover, tanpa memenuhi halaman."""
    tersimpan = st.session_state.get(_USER_FILTER_KEY) or {}
    with st.popover(t("ap.users_filter"), use_container_width=False):
        query = st.text_input(t("ap.users_f_search"),
                              value=tersimpan.get("query", ""),
                              key="contrib_user_q")
        roles = st.multiselect(t("ap.lbl_role"), ALL_ROLES,
                               default=tersimpan.get("roles", []),
                               format_func=role_label, key="contrib_user_role")
        statuses = st.multiselect(t("ap.users_col_status"),
                                  list(ALL_USER_STATUSES),
                                  default=tersimpan.get("statuses", []),
                                  format_func=status_label,
                                  key="contrib_user_status")
        institutions = st.multiselect(t("ap.users_col_institution"),
                                      _user_institutions(users),
                                      default=[i for i in
                                               tersimpan.get("institutions", [])
                                               if i in _user_institutions(users)],
                                      key="contrib_user_inst")
        if st.button(t("ap.users_f_clear"), key="contrib_user_f_clear"):
            st.session_state.pop(_USER_FILTER_KEY, None)
            for kunci in ("contrib_user_q", "contrib_user_role",
                          "contrib_user_status", "contrib_user_inst"):
                st.session_state.pop(kunci, None)
            st.rerun()

    filters = {"query": query, "roles": roles, "statuses": statuses,
               "institutions": institutions}
    st.session_state[_USER_FILTER_KEY] = filters
    return filters


def _filter_users(users) -> list[dict]:
    """Saring daftarnya, lalu nyatakan berapa yang tampil dari berapa."""
    filters = _render_user_filters(users)
    hasil = [u for u in users if _match_user(u, filters)]
    if len(hasil) != len(users):
        st.markdown(t("ap.users_count", shown=len(hasil), total=len(users)))
    return hasil


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
        # Instansi memakai kunci yang SAMA dengan formulir Daftar: satu kalimat
        # untuk satu pertanyaan, di mana pun ia ditanyakan.
        new_institution = st.text_input(t("auth.lbl_institution"),
                                        key="contrib_new_institution",
                                        placeholder=t("auth.ph_institution"),
                                        help=t("auth.help_institution"))
        created = st.form_submit_button(t("ap.btn_create_account"), type="primary")
    if created:
        try:
            created_user = create_user_as(user, new_username, new_password,
                                          new_role,
                                          institution=new_institution)
        except AuthError as e:            # termasuk PermissionDenied
            st.error(error_message(e))
        else:
            st.success(f"Akun `{created_user['username']}` dibuat "
                       f"({created_user['role_label']}).")

    st.divider()
    try:
        users = list_users()
    except Exception as e:                # pragma: no cover - defensive
        st.error(f"Gagal membaca daftar pengguna: {e}")
        return
    if not users:
        st.markdown(t("ap.empty_no_accounts"))
        return

    users = _filter_users(users)
    if not users:
        # `markdown`, bukan `caption`: halaman ini berkuota tiga teks kecil dan
        # ketiganya sudah terpakai. Ini kalimat keadaan setara "Belum ada akun."
        # tepat di atasnya, yang memang memakai markdown.
        st.markdown(t("ap.users_none_match"))
        return

    # Baris berkolom, BUKAN tabel HTML: tombolnya harus benar-benar berada di
    # baris orangnya, dan sel tabel Streamlit tidak dapat memuat tombol asli.
    # Header dibungkus wadah berjangkar supaya padding kirinya SAMA dengan
    # baris berbingkai di bawahnya — tanpa itu judul kolom berdiri di trek yang
    # bergeser dari selnya. Lihat `USER_ROW_PAD` di theme.py.
    with st.container():
        st.markdown('<span class="ids-user-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(_USER_COLS, vertical_alignment="center")
        for kol, kunci in zip(kepala, _USER_HEADERS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for row in users:
        with st.container(border=True):
            # Jangkar perapat baris; aturannya tinggal di theme.py.
            st.markdown('<span class="ids-user-row"></span>',
                        unsafe_allow_html=True)
            # `center`: sel terpendek pun berdiri di tengah barisnya, jadi
            # tombol sejajar dengan pil dan teks di sebelahnya — bawaan `top`
            # menempelkan semuanya ke atas dan barisnya terbaca ragged.
            cols = st.columns(_USER_COLS, vertical_alignment="center")
            is_self = row["username"] == (user or {}).get("username")
            # Penanda "akun Anda" sebagai PIL, memakai aturan yang sama
            # dengan lencana peran di kartu kontribusi. Ia menandai baris yang
            # aksinya memang ditiadakan di bawah, jadi ia perlu terbaca sekilas
            # — bukan menyatu dengan namanya sebagai teks tebal biasa.
            nama = f"<code>{escape(row['username'])}</code>"
            if is_self:
                nama += (f'<span class="ids-badge">'
                         f'{escape(t("ap.users_self"))}</span>')
            cols[0].markdown(nama, unsafe_allow_html=True)
            cols[1].markdown(_role_badge(row), unsafe_allow_html=True)
            cols[2].markdown(row["status_label"])
            cols[3].markdown(_user_cell(row.get("institution")))
            cols[4].markdown(_user_cell(format_stamp(row.get("created_at"))))
            cols[5].markdown(_activated_cell(row))

            if is_self:
                # Akun sendiri tidak dapat dinonaktifkan atau diturunkan dari
                # sini: satu-satunya Research Admin yang mengunci dirinya
                # sendiri akan mengunci seluruh platform.
                continue

            # Tindakan UTAMA berdiri sendiri; dua yang lain masuk panel.
            # Ketiganya bertumpuk dahulu, dan itulah yang membuat barisnya
            # setinggi tiga tombol.
            utama, lainnya = cols[6].columns([2, 1])

            active = row["status"] == STATUS_ACTIVE
            label = t("ap.btn_deactivate") if active else t("ap.btn_reactivate")
            # Hitam HANYA saat ia menonaktifkan akun orang; mengaktifkan
            # kembali tidak mencabut akses siapa pun.
            with dark_button_scope(utama, dark=active,
                                         key=f"cu_{row['username']}"):
                ditekan = st.button(
                    label, key=f"contrib_toggle_{row['username']}",
                    use_container_width=True)
            if ditekan:
                try:
                    set_user_status(row["username"],
                                    STATUS_DISABLED if active else STATUS_ACTIVE,
                                    actor=user)
                except AuthError as e:
                    st.error(error_message(e))
                else:
                    st.rerun()

            with lainnya.popover(t("ap.users_col_actions"),
                                 use_container_width=True):
                # Peran Research Admin HANYA diberikan dari sini — tidak pernah
                # lewat pendaftaran mandiri.
                promote = row["role"] != ROLE_RESEARCH_ADMIN
                role_btn = (t("ap.btn_make_admin") if promote
                            else t("ap.btn_make_contributor"))
                if st.button(role_btn, key=f"contrib_role_{row['username']}",
                             use_container_width=True):
                    try:
                        set_user_role(
                            row["username"],
                            ROLE_RESEARCH_ADMIN if promote else ROLE_CONTRIBUTOR,
                            actor=user)
                    except AuthError as e:
                        st.error(error_message(e))
                    else:
                        st.rerun()
                # Untuk yang LUPA sandinya. Tanpa jalur ini, akun yang sandinya
                # hilang tidak dapat ditolong siapa pun: platform tidak punya
                # email, jadi tidak ada tautan pemulihan yang bisa dikirim.
                if st.button(t("ap.btn_reset_password"),
                             key=f"contrib_pw_{row['username']}",
                             use_container_width=True,
                             help=t("ap.help_reset_password")):
                    st.session_state[_RESET_PW_KEY] = row["username"]
                    st.rerun()

    _render_reset_password(user)


def _render_reset_password(user: dict | None) -> None:
    """Sandi sementara bagi satu akun, ditetapkan Research Admin.

    Formulirnya berdiri DI BAWAH daftar, bukan di dalam barisnya: menetapkan
    sandi menuntut dua isian dan satu penegasan, dan itu tidak muat di sel
    tabel tanpa membuat seluruh baris lain ikut menyempit.

    Aturan kekuatan sandinya dibaca dari lapis layanan, yang memakai konstanta
    yang sama dengan pendaftaran.
    """
    from orchestrator.auth_service import reset_password

    sasaran = st.session_state.get(_RESET_PW_KEY)
    if not sasaran:
        return

    with st.container(border=True):
        rp.zone_heading(rp.ZONE_WORK, t("ap.sec_reset_password",
                                        username=sasaran))
        st.markdown(t("ap.reset_password_lead"))
        baru = st.text_input(t("ap.lbl_new_password"), type="password",
                             key=f"reset_pw_{sasaran}")
        ulang = st.text_input(t("ap.lbl_confirm_password"), type="password",
                              key=f"reset_pw2_{sasaran}")
        aksi = st.columns([1, 1, 3])
        if aksi[0].button(t("ap.btn_save_password"), type="primary",
                          key=f"reset_pw_save_{sasaran}",
                          use_container_width=True):
            try:
                reset_password(sasaran, baru, ulang, actor=user)
            except (AuthError, PermissionDenied) as e:
                st.error(error_message(e))
            else:
                st.session_state.pop(_RESET_PW_KEY, None)
                st.success(t("ap.msg_password_reset", username=sasaran))
                st.rerun()
        if aksi[1].button(t("action.cancel"), key=f"reset_pw_cancel_{sasaran}",
                          use_container_width=True):
            st.session_state.pop(_RESET_PW_KEY, None)
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

    # DUA sebab, dan keduanya berbeda. Pengunjung perlu tahu jalan masuknya;
    # akun yang sudah masuk tetapi belum disetujui justru tidak boleh disuruh
    # masuk lagi — ia sudah di dalam, yang kurang adalah persetujuannya.
    # Dahulu keduanya menerima kalimat "silakan masuk" yang sama, dan status
    # menunggu itu hanya terbaca dari baris hak di panel pembuka yang kini
    # sudah dicabut. Sekarang ia menempel pada kontrol yang mati, tempat
    # pertanyaannya memang muncul.
    if user:
        st.info(t("ap.gate_pending"))
        return False

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

    Sejak panduannya pindah ke modal, fungsi ini HANYA dipanggil dari badan
    modal itu. Ia tetap ada sebagai satu titik masuk supaya isinya tidak perlu
    disalin ke dua tempat yang bisa berbeda sendiri.
    """
    render_pipeline_instructions()


def _pipeline_info_body() -> None:
    """Isi modal panduan — seluruh keterangan halaman unggah pipeline.

    Panduannya panjang dengan sendirinya: diagram alur, tabel kontrak, dua
    daftar modul, kerangka kode, lima tab kontrak, daftar kesalahan umum, dan
    persyaratan lengkap. Digambar inline, semuanya berdiri di ANTARA judul
    halaman dan pengunggah berkasnya — pengunggah yang sudah tahu aturannya
    harus menggulir melewati seluruhnya setiap kali, dan yang belum tahu tetap
    membacanya dengan tergesa karena kontrol yang dicarinya ada di bawah sana.

    Di dalam modal keduanya terlayani: halamannya menjadi tindakan, panduannya
    menjadi rujukan yang dibuka saat dibutuhkan. Isinya TIDAK diringkas — yang
    berpindah hanya tempatnya.
    """
    _render_pipeline_requirements()
    # Catatan metadata ikut: ia menerangkan apa yang harus diisi formulir, dan
    # itu panduan — bukan label bidang.
    st.markdown(t("ap.note_metadata"))
    if st.button(t("ap.btn_close_info"), key="contrib_info_close"):
        _close_pipeline_info()


# `st.dialog` HANYA ada di modul `st` — bukan pada DeltaGenerator hasil
# st.columns(). Dekorasi sekali di tingkat modul, pola yang sama dengan
# `_compat_dialog` di ui/views/run_experiment.py. Pada Streamlit lama yang
# belum punya st.dialog, jalur cadangannya adalah st.expander.
_HAS_ST_DIALOG = hasattr(st, "dialog")

if _HAS_ST_DIALOG:
    _pipeline_info_dialog = dlg.dialog_decorator(
        t("ap.dlg_pipeline_info"), dlg.PIPELINE_INFO_KEY,
        width="large")(_pipeline_info_body)
else:  # pragma: no cover - hanya untuk Streamlit < 1.37
    def _pipeline_info_dialog() -> None:
        with st.expander(t("ap.dlg_pipeline_info"), expanded=True):
            _pipeline_info_body()


def _request_pipeline_info() -> None:
    """Tombol HANYA menulis flag; modalnya dipanggil dari ALUR UTAMA script."""
    dlg.open_dialog(dlg.PIPELINE_INFO_KEY)


def _close_pipeline_info() -> None:
    dlg.close_dialog(dlg.PIPELINE_INFO_KEY)
    st.rerun()


def _maybe_render_pipeline_info() -> None:
    """Satu-satunya tempat fungsi ber-@st.dialog itu dipanggil.

    Bukan dari dalam blok tombol, bukan dari dalam kolom — keduanya konteks
    yang tidak sah untuk membuka dialog.
    """
    if dlg.is_open(dlg.PIPELINE_INFO_KEY):
        _pipeline_info_dialog()


# ── Jalur pipeline: laporan ───────────────────────────────────────────────

def _render_group(title: str, checks: list[dict]) -> None:
    if not checks:
        return
    st.markdown(f"**{title}**")
    for c in checks:
        icon = _STATUS_ICON.get(c["status"], "·")
        line = f" _(baris {c['line']})_" if c.get("line") else ""
        st.markdown(f"- {icon} **{c['name']}**: {check_message(c)}{line}")


def _render_package_report(result: dict, form: dict) -> None:
    st.subheader(t("ap.sec_validation"))
    n_files = len(result["files"])
    if result["valid"]:
        st.success(f"Valid: {n_files} berkas lolos, entry point "
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
                    "keamanan tetap penuh. Berkas ini ikut dieksekusi saat "
                    "pipeline berjalan."
                )
            _render_group(GROUP_STRUCTURE, item["groups"][GROUP_STRUCTURE])
            _render_group(GROUP_SECURITY, item["groups"][GROUP_SECURITY])

    if not result["valid"]:
        st.markdown(t("ap.msg_fix_then_reupload"))
        return

    _render_valid_followup(result, form)




# ── Dataset uji lampiran: formulir kontributor ────────────────────────────

def _kotak_bagian(judul: str):
    """Satu KELOMPOK isian formulir sebagai kotak berjudul.

    Formulir unggah dahulu memisahkan kelompoknya dengan judul tebal saja,
    sementara 18 tempat lain di berkas ini sudah memakai
    `st.container(border=True)`. Akibatnya formulir terpanjang di aplikasi
    justru yang paling sulit dibaca: tidak ada yang menandai di mana satu
    kelompok berakhir dan kelompok berikutnya mulai, sehingga isian "Tahun"
    dan "Nama dataset" terbaca seakan bertetangga padahal milik dua kelompok
    berbeda.

    Judulnya tetap di DALAM kotak, bukan di atasnya: judul yang melayang di
    luar kotak membuat jarak antar-kelompok tampak dua kali lebih besar
    daripada jarak di dalamnya.
    """
    kotak = st.container(border=True)
    kotak.markdown(f"**{judul}**")
    return kotak


def _render_algorithm_names(entry_files) -> dict:
    """Nama algoritma tiap titik masuk — DITANYAKAN, bukan dituntut dari kode.

    Nama inilah yang tampil sebagai keping pada kartu katalog dan sebagai
    kolom Pipeline pada riwayat eksperimen. Sampai sekarang ia HANYA dibaca
    dari ``get_info()["algorithm"]``, sehingga kontributor yang mengisi
    seluruh formulir dengan benar tetap mendapat kartu bertuliskan pengenal
    mesin — dan tidak ada satu pun isian yang dapat memperbaikinya.

    Yang kodenya SUDAH menyebutkan tidak ditanyakan lagi: ia hanya
    diberitahukan. Menawarkan kotak isian yang nilainya pasti diabaikan
    (kode selalu menang) adalah meminta pekerjaan yang tidak berguna.

    Mengembalikan ``{nama berkas: nama yang diketik}``.
    """
    diketik: dict[str, str] = {}
    perlu = []
    for entry in entry_files or []:
        meta = extract_registry_metadata(entry["source"],
                                         entry["filename"]) or {}
        if str(meta.get("algorithm") or "").strip():
            continue                        # kodenya sudah menyebutkan
        perlu.append((entry["filename"], meta.get("class_name") or ""))

    if not perlu:
        return diketik

    st.markdown(f"**{t('ap.sec_algorithm_names')}**")
    for filename, kelas in perlu:
        diketik[filename] = st.text_input(
            t("ap.lbl_algorithm_name", filename=filename),
            key=f"contrib_algo_name_{filename}",
            placeholder=kelas or t("ap.ph_algorithm_name"),
            help=t("ap.help_algorithm_name")).strip()
    return diketik


def _render_trial_dataset_form(wajib: bool = False) -> tuple[object, str]:
    """(berkas, keterangan) dataset uji.

    Mengembalikan (None, "") bila kontributor tidak melampirkan apa pun.
    Bagi pengajuan yang MENUMPANG research pipeline bawaan itu jalur yang sah:
    peninjau tetap dapat mengujinya dengan dataset platform.

    ``wajib`` menandai pengajuan yang BERDIRI SENDIRI. Pengajuan seperti itu
    tidak boleh memakai dataset platform, sehingga tanpa lampiran ia tidak
    dapat diuji coba dan karena itu tidak akan pernah dapat disetujui.
    Dahulu itu baru ketahuan di meja peninjau, sesudah kontributor menunggu;
    sekarang dikatakan di sini, sebelum ia mengirim.
    """
    from orchestrator.trial_dataset_service import (
        DATASET_SUFFIXES, MAX_TRIAL_DATASET_BYTES, human_size,
        inspect_attachment,
    )

    st.markdown(f"**{t('td.heading')}**")
    if wajib:
        st.warning(t("td.warn_standalone_needs_dataset"))
    # Apa gunanya berkas ini dan batasnya menempel pada pengunggahnya, bukan
    # berdiri sebagai baris tersendiri di atasnya: yang bertanya "berkas apa?"
    # sedang menatap kontrol itu, dan di situlah jawabannya harus ada.
    picked = st.file_uploader(
        t("td.lbl_file"), type=[s.lstrip(".") for s in DATASET_SUFFIXES],
        accept_multiple_files=False, key="contrib_trial_dataset",
        help=t("td.intro") + " "
             + t("td.limit_note",
                 limit=human_size(MAX_TRIAL_DATASET_BYTES),
                 formats=", ".join(DATASET_SUFFIXES)))
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
        attach_to_submission(submission["id"], info, actor=user)
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


#: Kunci ``get_info()`` → kunci kalimat yang menyebut apa yang HILANG bila ia
#: kosong. Bukan daftar hiasan: tiap akibat di bawah punya pembaca nyata di
#: kode ini, dan sebuah test menahan daftar ini tetap selengkap
#: ``EXPECTED_INFO_KEYS`` — kunci yang tidak punya kalimat akan lolos tanpa
#: menyebut akibatnya sama sekali.
_INFO_KEY_COST = {
    "paper": "ap.cost_paper",
    "algorithm": "ap.cost_algorithm",
    "preprocessing_steps": "ap.cost_preprocessing",
    "feature_selection": "ap.cost_feature_selection",
    "fixed_params": "ap.cost_fixed_params",
    "train_test_split": "ap.cost_train_test_split",
}

# Kunci OPSIONAL — apa yang DIDAPAT bila diisi. Dipisah dari `_INFO_KEY_COST`
# karena keduanya berbeda jenis: yang satu kerugian, yang satu tawaran.
_INFO_KEY_GAIN = {
    "app": "ap.gain_app",
    "anti_leakage": "ap.gain_anti_leakage",
    "metrics_policy": "ap.gain_metrics_policy",
}


def _info_keys_of(entry: dict) -> tuple[list, list]:
    """(kunci metadata yang ADA, yang BELUM) sebuah berkas — dari pemeriksaan
    yang SUDAH dihitung.

    Tidak mem-parse apa pun. Source yang sedang divalidasi hanya boleh disentuh
    SATU ``ast.parse``: satu pohon, satu himpunan aturan, tidak ada jalur kedua
    yang bisa memperlakukannya berbeda. Sebuah test menjaga jumlah itu tetap
    satu, dan jawaban di sini memang sudah dihitung ``_check_get_info``.
    """
    for check in (entry.get("report") or {}).get("checks") or []:
        values = check.get("values") or {}
        if "present_keys" in values or "missing_keys" in values:
            return (list(values.get("present_keys") or []),
                    list(values.get("missing_keys") or []))
    return [], []


def _optional_keys_of(entry: dict) -> list:
    """Kunci opsional yang BELUM ada pada sebuah berkas.

    Dibaca dari pemeriksaan yang sama seperti :func:`_info_keys_of` — tidak ada
    ``ast.parse`` kedua atas source yang sedang divalidasi.
    """
    from orchestrator.pipeline_validator import OPTIONAL_INFO_KEYS

    for check in (entry.get("report") or {}).get("checks") or []:
        values = check.get("values") or {}
        if "optional_keys" in values:
            have = set(values.get("optional_keys") or [])
            return [k for k in OPTIONAL_INFO_KEYS if k not in have]
    return []


def _name_taken_warning(name: str) -> str:
    """Peringatan bila nama research ini sudah dipakai; "" bila bebas.

    Pengenal sebuah research pipeline dibentuk dari NAMANYA, dan pengenal itu
    unik. Tanpa pemeriksaan di sini, benturan nama baru terbongkar jauh di
    hilir — saat PENINJAU menekan Setujui — sebagai kegagalan yang bukan
    miliknya dan tidak dapat diperbaikinya. Yang tahu namanya adalah orang yang
    sedang mengetiknya, sekarang.
    """
    from database.models import build_research_dataset_type

    dataset_type = build_research_dataset_type((name or "").strip())
    if not dataset_type:
        return ""
    try:
        from orchestrator.research_registry import get_research

        taken = get_research(dataset_type) is not None
    except Exception:                       # registry tak terbaca: jangan
        return ""                           # menghalangi atas dasar tidak tahu
    return t("err.research_name_taken", name=name) if taken else ""


def _render_info_completeness(result: dict) -> None:
    """Kelengkapan ``get_info()`` tiap entry point — dan APA YANG HILANG.

    Ditampilkan, tidak ditanyakan. Nilai-nilai ini adalah sifat KODE yang akan
    dijalankan; menyediakan isian formulir untuknya akan melahirkan sumber
    kebenaran kedua yang dapat berbeda dari kodenya, lalu tersimpan sebagai
    fakta. Yang ditawarkan di sini adalah pengetahuan, bukan tempat mengarang.

    MEMPERINGATKAN, bukan menghalangi: ``get_info()`` yang tidak lengkap tidak
    membuat pipelinenya salah — ia hanya membuatnya kurang terbaca. Yang harus
    diperbaiki adalah kodenya, dan kalimatnya menunjuk ke sana.
    """
    entries = [f for f in result["files"] if f["role"] == ROLE_ENTRY]
    missing_any = False
    for entry in entries:
        present, missing = _info_keys_of(entry)
        if not present and not missing:
            continue                    # dibangun dinamis: tidak dapat dibaca
        if not missing:
            continue
        missing_any = True
        st.markdown(t("ap.info_incomplete", filename=entry["filename"],
                      have=len(present), total=len(present) + len(missing)))
        for key in missing:
            st.markdown(f"- `{key}`: {t(_INFO_KEY_COST[key])}")
    if missing_any:
        prose(t("ap.info_incomplete_note"), key="info_incomplete")

    # Tawaran, bukan tuntutan: tiga kunci ini tidak ada di kontrak, jadi tidak
    # pernah menjadi peringatan — tetapi panel membacanya, dan kontributor
    # tidak punya cara lain mengetahui tempatnya ada.
    for entry in entries:
        absent = _optional_keys_of(entry)
        if not absent:
            continue
        st.markdown(t("ap.info_optional", filename=entry["filename"]))
        for key in absent:
            st.markdown(f"- `{key}`: {t(_INFO_KEY_GAIN[key])}")


def _render_valid_followup(result: dict, form: dict) -> None:
    """Unduh + cuplikan registry terisi metadata + panduan aktivasi manual."""
    st.divider()
    st.info(t("ap.msg_valid_not_active"))
    _render_info_completeness(result)

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
        # Nama algoritma DITANYAKAN di sini, bukan dituntut dari kode.
        #
        # Kartu katalog menampilkan nama ini. Sampai sekarang ia hanya dibaca
        # dari `get_info()["algorithm"]`, jadi kontributor yang mengisi seluruh
        # formulir dengan benar tetap mendapat kartu bertuliskan pengenal
        # mesinnya — dan tidak ada satu pun isian yang dapat memperbaikinya.
        entry_files = [f for f in result["files"] if f["role"] == ROLE_ENTRY]
        nama_algoritma = _render_algorithm_names(entry_files)

        trial_upload, trial_note = _render_trial_dataset_form(
            wajib=bool((form or {}).get("declared_schema", {}).get(
                "label_column")))
        if st.button(t("ap.btn_submit_review"), key="contrib_submit_pipeline",
                     type="primary",
                     help=t("ap.help_submit_review")):
            # Nama kelas SETIAP entry point dibaca STATIS dari AST —
            # dibutuhkan peninjau untuk mendaftarkan pipeline saat menyetujui.
            # Satu paket boleh memuat BANYAK entry point: sebuah research
            # pipeline kontribusi berdiri sendiri dan wajar membawa beberapa
            # algoritma, persis seperti keluarga bawaan.
            algorithms = []
            for entry in entry_files:
                found = extract_registry_metadata(entry["source"],
                                                  entry["filename"]) or {}
                algorithms.append({
                    "filename": entry["filename"],
                    "class_name": found.get("class_name"),
                    # Kode tetap menang; isian formulir hanya dipakai ketika
                    # kodenya memang tidak menyebutkan namanya.
                    "algorithm": (found.get("algorithm")
                                  or nama_algoritma.get(entry["filename"])
                                  or None),
                    # Fase progres, dibaca statis dari `_emit_progress()` pada
                    # berkas ini. Sudah terlanjur dihitung di atas; membuangnya
                    # berarti bar progresnya berjalan tanpa nama fase padahal
                    # pipelinenya memang memancarkannya saat berjalan.
                    "stages": list(found.get("stages") or []),
                })
            static_meta = extract_registry_metadata(entry_item["source"],
                                                    entry_item["filename"])
            try:
                submission = submit_pipeline(
                    [(f["filename"], f["source"]) for f in result["files"]],
                    entry_item["filename"], user=user,
                    metadata={**_submission_metadata(form),
                              # Dipertahankan untuk pengajuan lama & pembaca
                              # yang hanya mengenal satu entry point.
                              "entry_class": static_meta.get("class_name"),
                              # Daftar LENGKAP algoritma paket ini.
                              "algorithms": algorithms},
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

#: Kunci widget dataset lampiran. Nilainya dibaca DI SINI walau widgetnya
#: digambar jauh di bawah: Streamlit menyimpan nilai widget ber-key di
#: `session_state`, jadi pada penggambaran BERIKUTNYA berkasnya sudah ada
#: ketika bagian skema dirender. Itulah yang membuat daftar kolomnya terisi.
_TRIAL_DATASET_KEY = "contrib_trial_dataset"


def _real_column_names(names) -> list[str]:
    """Nama kolom yang benar-benar NAMA — kosong dan "Unnamed: N" dibuang.

    Berkas tanpa baris judul tetap terbaca pandas; kolomnya diberi nama
    pengganti "Unnamed: 0". Menawarkannya sebagai pilihan berarti menawarkan
    sesuatu yang bukan nama kolom, dan yang dipilih akan masuk ke kontrak
    dataset sebagai fakta.
    """
    # `names or []` TIDAK dapat dipakai: pandas Index melempar pada uji
    # kebenaran ("The truth value of a Index is ambiguous"), dan kegagalannya
    # akan tertelan penangkap galat pemanggil sebagai "tidak terbaca".
    out = []
    for name in (names if names is not None else []):
        text = str(name).strip()
        if text and not text.startswith("Unnamed:"):
            out.append(text)
    return out


def _attached_dataset_columns() -> list[str]:
    """Nama kolom dataset yang dilampirkan; [] bila belum ada atau tak terbaca.

    Hanya BARIS JUDULNYA yang dibaca (``nrows=0`` untuk CSV, satu record untuk
    NDJSON) — dataset kontribusi dapat berukuran besar, dan yang dibutuhkan di
    sini cuma nama kolomnya.

    Kegagalan membaca berarti daftar pilihan kosong, BUKAN halaman yang jatuh:
    berkas yang belum lengkap terunggah atau formatnya tidak terduga tetap
    boleh terjadi, dan pengunggah tetap dapat mengetik sendiri.
    """
    picked = st.session_state.get(_TRIAL_DATASET_KEY)
    if picked is None:
        return []
    try:
        import io

        import pandas as pd

        raw = picked.getvalue()
        name = str(getattr(picked, "name", "")).lower()
        if name.endswith((".ndjson", ".jsonl")):
            first = raw.split(b"\n", 1)[0].decode("utf-8", errors="replace")
            record = json.loads(first)
            return [str(k) for k in record] if isinstance(record, dict) else []
        if name.endswith(".json"):
            record = json.loads(raw.decode("utf-8", errors="replace"))
            if isinstance(record, list) and record:
                record = record[0]
            return [str(k) for k in record] if isinstance(record, dict) else []
        header = pd.read_csv(io.BytesIO(raw), nrows=0)
        return _real_column_names(header.columns)
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Header dataset lampiran tidak terbaca", exc_info=True)
        return []


def _detected_algorithms(uploaded_files) -> list[str]:
    """Nama algoritma yang TERBACA dari berkas terunggah, tanpa duplikat.

    Satu paket boleh membawa beberapa entry point, dan tiap entry point adalah
    satu algoritma — itulah sebabnya isian ini jamak.
    """
    found: list[str] = []
    for item in uploaded_files or []:
        try:
            source = item.getvalue().decode("utf-8", errors="replace")
            name = (extract_registry_metadata(source, item.name)
                    or {}).get("algorithm")
        except Exception:                   # pragma: no cover - defensif
            continue
        text = str(name or "").strip()
        if text and text not in found:
            found.append(text)
    return found


def _render_detected_stages(box, uploaded_file) -> None:
    """Fase progres yang TERBACA dari sebuah berkas — untuk diperiksa.

    Ditampilkan, bukan ditanyakan: urutannya sudah ada di dalam kode, jadi
    meminta pengunggah mengetiknya ulang akan melahirkan sumber kebenaran kedua
    yang dapat berbeda dari kode yang benar-benar berjalan.

    Yang terbaca adalah urutan KEMUNCULAN di berkas, dan itu belum tentu urutan
    saat berjalan — fase di dalam percabangan atau perulangan dapat menipu.
    Karena itu ia disodorkan untuk diperiksa, bukan dinyatakan sebagai fakta.

    Berkas yang tidak memanggil ``_emit_progress`` tidak menghasilkan apa pun,
    dan itu keadaan yang sah: bar progresnya berjalan tanpa nama fase.
    """
    try:
        source = uploaded_file.getvalue().decode("utf-8", errors="replace")
        stages = (extract_registry_metadata(source, uploaded_file.name)
                  or {}).get("stages") or []
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Fase tidak terbaca dari %s", uploaded_file.name,
                     exc_info=True)
        return
    if not stages:
        return
    box.markdown(t("ap.detected_stages",
                   stages=" → ".join(f"**{s}**" for s in stages)))


#: Format yang DITAWARKAN pada daftar. Bukan batas: daftarnya menerima nilai
#: baru yang diketik sendiri, sebab sebuah paket boleh membawa format yang
#: belum pernah dipakai platform ini.
DECLARABLE_FORMATS = ["csv", "ndjson", "jsonl", "json"]

#: Format yang isinya objek JSON, jadi kolom wajibnya adalah KUNCI tingkat
#: atas, bukan kolom tabel.
JSON_FAMILY = ("ndjson", "jsonl", "json")


def _normalise_format(value) -> str:
    """Format yang diketik sendiri, dirapikan menjadi satu bentuk baku.

    Tanpa ini "CSV", " csv " dan ".csv" menjadi tiga kontrak berbeda yang
    tidak satu pun cocok dengan `"csv"` yang dibaca pemeriksa dataset.
    """
    teks = str(value or "").strip().lower()
    return teks.lstrip(".")


def _render_pipeline_flow() -> None:
    # Jangkar kerapatan: seluruh ruas di bawahnya memakai jarak formulir,
    # bukan jarak lapang yang berlaku di halaman lain. Lingkupnya berhenti
    # di halaman ini (lihat `.ids-form-compact` pada `theme`).
    st.markdown('<span class="ids-form-compact"></span>',
                unsafe_allow_html=True)
    # Judul dan tombol panduan pada SATU baris: tombolnya menerangkan halaman
    # ini, bukan bagian mana pun di bawahnya, jadi tempatnya di sebelah judul.
    judul, aksi = st.columns([4, 1])
    judul.subheader(t("ap.sec_upload_pipeline"))
    if aksi.button(t("ap.btn_info"), key="contrib_info_pipeline",
                   use_container_width=True):
        _request_pipeline_info()
    st.divider()

    # Lapis TAMPILAN: panduannya tetap terbaca siapa pun lewat tombol di atas,
    # tetapi kontrol unggahnya dimatikan bila belum berhak — supaya tidak ada
    # tombol yang tampak aktif padahal aksinya pasti ditolak lapis aksi.
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
            _render_detected_stages(box, f)

    st.divider()
    # `ap.note_metadata` dahulu berdiri di sini. Ia menerangkan apa yang harus
    # diisi seluruh formulir di bawah — panduan, bukan label bidang — jadi ia
    # ikut pindah ke modal Info bersama panduan lainnya.
    c1, c2 = st.columns(2)
    name = c1.text_input(t("ap.lbl_pipeline_name"), key="contrib_meta_name",
                         placeholder="mis. Random Forest untuk HIKARI2021")
    # TIDAK ADA pertanyaan "ikut research pipeline mana". Paket yang diunggah
    # ADALAH sebuah research pipeline: ia membawa algoritmanya sendiri — boleh
    # lebih dari satu — dan kontrak datasetnya sendiri. Menanyakan induk kepada
    # sesuatu yang berdiri sendiri adalah pertanyaan tanpa jawaban yang benar,
    # dan jawabannya dahulu menentukan `dataset_type` yang keliru.
    # JAMAK: satu paket boleh membawa beberapa entry point, dan tiap entry
    # point adalah satu algoritma. Pilihannya diisi dari yang terbaca di
    # berkas terunggah; `accept_new_options` menjaga yang tidak terbaca statis
    # tetap dapat disebut.
    algorithms_picked = c2.multiselect(
        "Algoritma", _detected_algorithms(uploaded),
        default=_detected_algorithms(uploaded), accept_new_options=True,
        key="contrib_meta_algo", placeholder="mis. Random Forest")
    # Disimpan sebagai SATU kalimat: nilai ini hanya cadangan bagi entri
    # registry ketika kode paketnya sendiri tidak menyebut algoritmanya.
    algorithm = ", ".join(str(a).strip() for a in algorithms_picked
                          if str(a).strip())

    # Kredit penelitian TERSTRUKTUR, bukan satu kolom teks bebas. Nama tampil
    # research pipeline ini disusun dari ketiganya sebagai "<kredit> — <nama>",
    # pola yang sama dengan atribusi bawaan — dan itu yang membuat labelnya
    # tidak lagi mengulang namanya sendiri. Satu kolom bebas tidak dapat
    # dipisah kembali menjadi bagian-bagiannya tanpa menebak.
    # LIMA bidang, bukan tiga: panel "Tentang Research Pipeline" menggambar
    # jenis, penulis, judul, institusi, dan tahun sebagai baris TERPISAH. Tiga
    # bidang gabungan tidak dapat dipecah kembali menjadi lima tanpa menebak,
    # dan menebak berarti barisnya diisi keterangan yang salah.
    with _kotak_bagian(t("ap.sec_credit")):
        k1, k2, k3 = st.columns([2, 3, 1])
        source_type = k1.selectbox(
            t("ap.lbl_source_type"), SOURCE_TYPES, index=None,
            key="contrib_meta_source_type", placeholder=t("ap.ph_source_type"))
        researcher = k2.text_input(t("ap.lbl_researcher"),
                                   key="contrib_meta_researcher",
                                   placeholder="mis. A. Muh. Rayyan Eka Putra")
        year = k3.text_input(t("ap.lbl_year"), key="contrib_meta_year",
                             placeholder="2026", max_chars=4)
        k4, k5 = st.columns(2)
        title = k4.text_input(t("ap.lbl_title"), key="contrib_meta_title",
                              placeholder="mis. Klasifikasi Trafik Terenkripsi")
        institution = k5.text_input(t("ap.lbl_institution"),
                                    key="contrib_meta_institution",
                                    placeholder="mis. Universitas Hasanuddin")
        scope = st.text_input(t("ap.lbl_scope"), key="contrib_meta_scope",
                              placeholder="mis. Perbandingan Random Forest dan "
                                          "Decision Tree pada trafik kampus")
        paper = research_credit(researcher, year, institution)
        if paper:
            prose(t("ap.credit_preview", credit=paper, name=(name or "…").strip()),
                  key="credit_preview")

        # ── Sumber DATASET ───────────────────────────────────────────────────
        # Dari mana datanya berasal, dan milik siapa. Pipeline bawaan menyebutnya
        # ("HIKARI2021 (varian ALLFLOWMETER) — Ferriyan (2022)"); tanpa ini, baris
        # "Sumber dataset" pada panel unggahan kosong, dan pembacanya tidak punya
        # cara mengetahui data itu datang dari mana.
    with _kotak_bagian(t("ap.sec_dataset_source")):
        s1, s2 = st.columns(2)
        dataset_name = s1.text_input(t("ap.lbl_dataset_name"),
                                     key="contrib_meta_dataset_name",
                                     placeholder="mis. Trafik Kampus 2026")
        dataset_attribution = s2.text_input(
            t("ap.lbl_dataset_attribution"), key="contrib_meta_dataset_attr",
            placeholder="mis. Tim Jaringan UNHAS (2026)")
        dataset_note = st.text_input(t("ap.lbl_dataset_note"),
                                     key="contrib_meta_dataset_note",
                                     placeholder=t("ap.ph_dataset_note"))
        notes = st.text_area(t("ap.lbl_note"), key="contrib_meta_notes", height=80,
                             help=t("ap.help_optional_report"))

        # ── Kontrak dataset yang DIDEKLARASIKAN ──────────────────────────────
        # Sebuah research pipeline kontribusi berdiri sendiri: ia membawa
        # datasetnya sendiri, dan platform tidak dapat menebak seperti apa
        # bentuknya. Kontraknya DIDEKLARASIKAN di sini, lalu dipakai memeriksa
        # berkas datasetnya — platform tidak pernah mengarang skema dari nama
        # atau isi berkas.
        #
        # SELALU dideklarasikan, bukan hanya bila jenisnya "belum terdaftar":
        # setiap paket berdiri sendiri, jadi tidak pernah ada skema bawaan untuk
        # ditumpangi, dan platform tidak boleh mengarang satu dari nama berkas
        # maupun isinya.
    with _kotak_bagian(t("ap.sec_declare_schema")):
        # Keterangannya menempel pada kolom label, bidang PERTAMA bagian ini:
        # sebagai paragraf lepas ia berdiri di antara judul dan kontrolnya, dan
        # harus dibaca lebih dulu oleh setiap orang yang sudah tahu isinya.

        # Nama kolom DIPILIH dari dataset yang dilampirkan, bukan diketik. Salah
        # ketik satu huruf membuat kontrak ini tidak cocok dengan datasetnya, dan
        # tidak ada yang memberi tahu sampai uji coba dijalankan. Selama datasetnya
        # belum dilampirkan daftarnya kosong dan pengunggah tetap dapat mengetik
        # sendiri — tanpa dataset, memang tidak ada yang dapat ditawarkan.
        known = _attached_dataset_columns()
        if known:
            prose(t("ap.columns_from_dataset", count=len(known)),
                  key="columns_from_dataset")

        d1, d2 = st.columns(2)
        label_pick = d1.multiselect(
            t("ap.lbl_label_column"), known, max_selections=1,
            accept_new_options=True, key="contrib_schema_label",
            placeholder="mis. attack", help=t("ap.help_declare_schema"))
        label_column = label_pick[0] if label_pick else ""
        # Format TIDAK dikunci pada daftar. Yang ditawarkan adalah format yang
        # pengunggahnya memang terima, tetapi sebuah paket boleh membawa format
        # lain, dan formulir SUNTING research pipeline sudah menerima apa pun
        # sejak awal (kolom teks bebas di `research_manage`). Mengunci yang satu
        # sementara yang lain bebas membuat kontrak yang sama tidak dapat
        # dinyatakan lewat jalur unggah.
        file_format = _normalise_format(d2.selectbox(
            t("ap.lbl_file_format"), DECLARABLE_FORMATS, index=0,
            format_func=lambda value: str(value).upper(),
            accept_new_options=True, key="contrib_schema_format",
            help=t("ap.help_file_format")))
        columns = st.multiselect(
            t("ap.lbl_required_columns"), known, accept_new_options=True,
            key="contrib_schema_cols", placeholder="flow_duration, src_port, attack",
            help=t("ap.help_required_columns"))
        # Empat keterangan berikut menjawab pertanyaan yang selama ini tidak
        # pernah ditanyakan kepada pengunggah, sehingga panel persyaratan untuk
        # research kontribusi hanya dapat menyebut format dan nama kolom — dan
        # dahulu MENGARANG sisanya dengan kalimat milik HIKARI2021. Seluruhnya
        # OPSIONAL: yang tidak diisi tidak ditampilkan, bukan diisi tanda hubung.
        f1, f2 = st.columns(2)
        row_unit = f1.text_input(t("ap.lbl_row_unit"), key="contrib_schema_rowunit",
                                 placeholder=t("ap.ph_row_unit"),
                                 help=t("ap.help_dataset_facts"))
        label_meaning = f2.text_input(
            t("ap.lbl_label_meaning"), key="contrib_schema_labelmeaning",
            placeholder=t("ap.ph_label_meaning"))
        f3, f4 = st.columns([3, 1])
        feature_nature = f3.text_input(
            t("ap.lbl_feature_nature"), key="contrib_schema_features",
            placeholder=t("ap.ph_feature_nature"))
        # 0 berarti "tidak dinyatakan" — bukan "nol kelas". Baris jumlah kelas
        # memang tidak ditampilkan bila tidak diisi.
        class_count = f4.number_input(t("ap.lbl_class_count"), min_value=0,
                                      max_value=99, value=0, step=1,
                                      key="contrib_schema_classes",
                                      help=t("ap.help_class_count"))

        # ── Keterangan METODE ────────────────────────────────────────────────
        # Empat kunci berikut ditulis pipeline BAWAAN di dalam `get_info()` dan
        # ditampilkan pada modal katalog serta panel "Tentang Research Pipeline",
        # tetapi validator tidak mewajibkannya — jadi paket kontribusi hampir
        # tidak pernah memuatnya dan keempat tempat itu kosong. Isian di sini
        # HANYA mengisi kunci yang kode pipelinenya tidak menyebutkan: kode selalu
        # menang (lihat `dynamic_registry.merge_info`).
    with _kotak_bagian(t("ap.sec_method_notes")):
        m1, m2 = st.columns(2)
        info_app = m1.text_input(t("ap.lbl_info_app"), key="contrib_info_app",
                                 placeholder=t("ap.ph_info_app"),
                                 help=t("ap.help_method_notes"))
        info_metrics = m2.text_input(t("ap.lbl_info_metrics"),
                                     key="contrib_info_metrics",
                                     placeholder=t("ap.ph_info_metrics"))
        info_dataset = st.text_input(t("ap.lbl_info_dataset"),
                                     key="contrib_info_dataset",
                                     placeholder=t("ap.ph_info_dataset"))
        info_anti = st.text_area(t("ap.lbl_info_anti_leakage"), height=90,
                                 key="contrib_info_anti",
                                 placeholder=t("ap.ph_info_anti_leakage"),
                                 help=t("ap.help_info_anti_leakage"))
        # Dua bagian modal katalog — "Langkah preprocessing" dan "Hyperparameter
        # terkunci" — dahulu tidak punya isian sama sekali. Keduanya tetap ditampilkan,
        # jadi paket yang kodenya tidak menyebutkannya memperlihatkan dua bagian yang
        # selamanya kosong dan tidak seorang pun punya tempat mengisinya.
        #
        # Aturan yang sama dengan empat isian di atas: kode SELALU menang. Yang
        # diketik di sini hanya mengisi kunci yang `get_info()` pipelinenya memang
        # tidak menyebutkan.
        p1, p2 = st.columns(2)
        info_pre = p1.text_area(t("ap.lbl_info_preprocessing"), height=110,
                                key="contrib_info_pre",
                                placeholder=t("ap.ph_info_preprocessing"),
                                help=t("ap.help_info_preprocessing"))
        info_params = p2.text_area(t("ap.lbl_info_fixed_params"), height=110,
                                   key="contrib_info_params",
                                   placeholder=t("ap.ph_info_fixed_params"),
                                   help=t("ap.help_info_fixed_params"))

        # Dua bidang terakhir menerangkan DATASET-nya, bukan metodenya, jadi
        # keduanya menempel pada kontrak dataset di atas.
    sample_values = st.text_area(t("ap.lbl_sample_values"), height=70,
                                 key="contrib_sample_values",
                                 placeholder=t("ap.ph_sample_values"),
                                 help=t("ap.help_sample_values"))
    ignored_columns = st.multiselect(
        t("ap.lbl_ignored_columns"), known, accept_new_options=True,
        key="contrib_ignored_cols", help=t("ap.help_ignored_columns"))

    declared_schema = {
        "label_column": (label_column or "").strip(),
        "expected_columns": [str(c).strip() for c in columns if str(c).strip()],
        "file_format": file_format,
    }
    # Kunci tingkat atas berlaku untuk SELURUH keluarga JSON, bukan hanya
    # ndjson: sejak formatnya dapat diketik sendiri, memilih "jsonl" atau
    # "json" akan kehilangan kunci itu tanpa satu pun tanda.
    if file_format in JSON_FAMILY:
        declared_schema["expected_top_level_keys"] = columns
    # Nama ikut diperiksa DI SINI: pengenal research pipeline dibentuk dari
    # namanya, jadi nama kosong berarti pengajuan yang tidak akan pernah dapat
    # disetujui — dan itu harus ketahuan sekarang, bukan di meja peninjau.
    missing = [lbl for lbl, ok in (
        (t("ap.lbl_pipeline_name"), (name or "").strip()),
        (t("ap.lbl_label_column"), declared_schema["label_column"]),
        (t("ap.lbl_required_columns"), columns)) if not ok]
    if missing:
        st.warning(t("ap.err_schema_incomplete", fields=", ".join(missing)))

    form = {
        "name": name,
        # Kontrak dataset yang dideklarasikan kontributor. Kosong bila
        # pipelinenya menumpang jenis bawaan — itu keadaan yang sah, bukan
        # isian yang terlewat.
        "declared_schema": declared_schema,
        # PENANDA eksplisit, bukan string kosong: "jenisnya belum terdaftar"
        # adalah keterangan yang berguna, sedangkan string kosong tidak dapat
        # dibedakan dari "tidak pernah diisi". Pengenal yang sesungguhnya
        # dibentuk dari NAMA research pipeline ini saat pengajuan disetujui.
        "dataset_type": DATASET_TYPE_UNREGISTERED,
        "algorithm": algorithm,
        # Kalimat kreditnya — dipakai apa adanya oleh entri registry dan
        # laporan, persis seperti sebelumnya.
        "paper": paper,
        # …dan bagian-bagiannya, yang tidak dapat dipisah kembali dari
        # kalimat itu tanpa menebak. Kelimanya menjadi baris TERPISAH pada
        # panel "Tentang Research Pipeline".
        "source_type": source_type,
        "researcher": researcher,
        "title": title,
        "institution": institution,
        "year": year,
        # Dari mana datanya berasal, dan milik siapa.
        "dataset_name": dataset_name,
        "dataset_attribution": dataset_attribution,
        "dataset_note": dataset_note,
        # Keterangan dataset yang DITERIMA pipeline ini. Bukan aturan yang
        # ditegakkan validator — semata yang perlu diketahui orang yang hendak
        # mencocokkan berkasnya sendiri.
        "dataset_row_unit": row_unit,
        "dataset_label_meaning": label_meaning,
        "dataset_feature_nature": feature_nature,
        "dataset_class_count": int(class_count) if class_count else "",
        "dataset_sample_values": sample_values,
        "dataset_ignored_columns": ignored_columns,
        # Keterangan metode: mengisi `get_info()` yang tidak menyebutkannya.
        "info_app": info_app,
        "info_metrics_policy": info_metrics,
        "info_dataset": info_dataset,
        "info_anti_leakage": info_anti,
        "info_preprocessing": info_pre,
        "info_fixed_params": info_params,
        # Apa yang dibandingkan/dicakup penelitian ini.
        "scope": scope,
        "notes": notes,
    }

    # Nama dan kontrak dataset WAJIB: tanpa keduanya pipeline tidak dapat diuji
    # maupun dijalankan, dan pengenalnya tidak dapat dibentuk. Alasan tombol
    # nonaktif SELALU menempel pada tombolnya — tombol mati tanpa keterangan
    # membuat pengunggah menebak apa yang kurang.
    blocked = (t("ap.err_schema_incomplete", fields=", ".join(missing))
               if missing else "") or _name_taken_warning(name)
    if st.button(t("ap.btn_upload_validate"), type="primary", key="contrib_validate",
                 disabled=not may_upload or bool(blocked),
                 help=blocked or None):
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
                status.update(label=f"Selesai: {result['summary']}",
                              state="complete", expanded=False)
            progress.empty()
            st.session_state[_RESULT_KEY] = result
            st.session_state[_FORM_KEY] = form

    result = st.session_state.get(_RESULT_KEY)
    if result:
        st.divider()
        _render_package_report(result, st.session_state.get(_FORM_KEY) or form)

    # Modal panduan digambar TERAKHIR, dari alur utama script — sesudah seluruh
    # kolom dan container di atas selesai.
    _maybe_render_pipeline_info()


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

    MENIMPA DITOLAK di sini pula. Sebelumnya penolakan itu hanya ada di layar:
    tombolnya tidak digambar bila berkasnya sudah ada, sementara fungsi ini
    menyalin apa adanya. Sebuah audit memanggilnya langsung dan berhasil
    menimpa dataset yang sudah dipakai eksperimen — persis yang dilarang
    prinsip platform ini sendiri: menyembunyikan tombol tidak pernah menjadi
    satu-satunya penghalang.
    """
    require_upload(user)
    if Path(target).exists():
        raise SubmissionError(
            f"Berkas `{Path(target).name}` sudah ada di storage/datasets/.",
            key="ap.err_file_exists", values={"filename": Path(target).name})
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

    Sejak panduannya pindah ke modal, hanya badan modal itu yang memanggilnya.
    """
    render_dataset_instructions()


def _dataset_info_body() -> None:
    """Isi modal panduan halaman Tambah Dataset.

    PEMILIH research ikut masuk ke sini, dan itu disengaja. Tugasnya semata
    memilih *persyaratan siapa yang sedang dibaca* — ia tidak menentukan apa
    pun tentang berkas yang diunggah, karena berkas itu diperiksa terhadap
    seluruh research, bukan terhadap satu yang dipilih. Meninggalkannya di
    halaman berarti menyisakan kontrol yang tampak menentukan sesuatu padahal
    tidak mengubah apa-apa di halaman itu.

    Mengganti pilihan memicu rerun; modalnya tetap terbuka karena flagnya masih
    hidup, jadi persyaratan research lain dapat dibaca tanpa menutup apa pun.
    """
    st.markdown(t("ap.note_checked_against_all"))
    _render_dataset_requirements_overview()
    if st.button(t("ap.btn_close_info"), key="contrib_info_dataset_close"):
        _close_dataset_info()


if _HAS_ST_DIALOG:
    _dataset_info_dialog = dlg.dialog_decorator(
        t("ap.dlg_dataset_info"), dlg.DATASET_INFO_KEY,
        width="large")(_dataset_info_body)
else:  # pragma: no cover - hanya untuk Streamlit < 1.37
    def _dataset_info_dialog() -> None:
        with st.expander(t("ap.dlg_dataset_info"), expanded=True):
            _dataset_info_body()


def _request_dataset_info() -> None:
    dlg.open_dialog(dlg.DATASET_INFO_KEY)


def _close_dataset_info() -> None:
    dlg.close_dialog(dlg.DATASET_INFO_KEY)
    st.rerun()


def _maybe_render_dataset_info() -> None:
    """Dipanggil dari ALUR UTAMA script, bukan dari dalam tab atau tombol."""
    if dlg.is_open(dlg.DATASET_INFO_KEY):
        _dataset_info_dialog()


def _render_dataset_flow() -> None:
    # Jangkar kerapatan: seluruh ruas di bawahnya memakai jarak formulir,
    # bukan jarak lapang yang berlaku di halaman lain. Lingkupnya berhenti
    # di halaman ini (lihat `.ids-form-compact` pada `theme`).
    st.markdown('<span class="ids-form-compact"></span>',
                unsafe_allow_html=True)
    # Judul dan tombol panduan sebaris, sama seperti jalur pipeline.
    judul, aksi = st.columns([4, 1])
    judul.subheader(t("ap.sec_add_dataset"))
    if aksi.button(t("ap.btn_info"), key="contrib_info_dataset",
                   use_container_width=True):
        _request_dataset_info()

    st.divider()
    tab_upload, tab_server = st.tabs(["Unggah berkas", "Daftarkan dari server"])
    with tab_upload:
        _render_dataset_upload_tab()
    with tab_server:
        _render_dataset_server_tab()

    _maybe_render_dataset_info()


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
                 f"server, lalu pakai tab **Daftarkan dari server**, tanpa "
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
        except (AuthError, PermissionDenied, SubmissionError, OSError) as e:
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


def _sample_note(profile: dict) -> str:
    """Catatan bahwa angka berasal dari CUPLIKAN — dan hanya bila memang begitu.

    Berkas yang terbaca seluruhnya tidak lagi mengatakan apa pun. Kalimat
    "Berdasarkan seluruh 1.200 baris berkas ini" hanya menegaskan keadaan
    normal: kalau tidak ada catatan, angkanya memang angka berkas itu. Yang
    benar-benar perlu diberitahukan adalah kebalikannya — saat angkanya BUKAN
    dari seluruh berkas — dan itulah satu-satunya yang tersisa di sini.
    """
    if not profile.get("sampled"):
        return ""
    n = f"{profile.get('rows_read', 0):,}"
    return f"Angka di atas dari {n} baris pertama. Berkas tidak dimuat seluruhnya."


#: Sebanyak ini kelas ditulis utuh pada baris profil; sisanya diringkas.
#: Dataset penelitian di sini biner, tetapi berkas kontribusi boleh membawa
#: berapa pun kelas — dan satu baris kartu tidak boleh tumbuh tanpa batas.
_PROFILE_MAX_CLASSES = 6


def _class_distribution_text(profile: dict) -> str:
    """Distribusi kelas sebagai SATU nilai, siap menjadi baris profil.

    Angkanya persis seperti sebelumnya — jumlah dan persentase per kelas, dari
    sampel yang sama. Yang berubah hanya bentuknya: satu nilai yang dapat
    berdiri sejajar dengan "Baris" dan "Tipe data", bukan daftar tersendiri
    yang melayang di luar kartu.

    Berkas NDJSON tidak punya kolom label; untuk itu yang dilaporkan adalah
    indikasi kelasnya — dan itu dinyatakan sebagai indikasi, bukan distribusi.
    """
    counts = profile.get("class_counts") or {}
    if counts:
        total = sum(counts.values()) or 1
        bagian = [f"`{nilai}` {n:,} ({n / total * 100:.1f}%)"
                  for nilai, n in list(counts.items())[:_PROFILE_MAX_CLASSES]]
        sisa = len(counts) - len(bagian)
        if sisa > 0:
            bagian.append(f"… (+{sisa} kelas lain)")
        return " · ".join(bagian)

    if profile.get("detected_format") == "ndjson":
        return (f"Event TLS {profile.get('tls_rows', 0):,} · "
                f"beralert (calon kelas attack) "
                f"{profile.get('alert_rows', 0):,}")
    return ""


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

    # Distribusi kelas adalah FAKTA PROFIL, sejenis dengan jumlah baris dan
    # tipe data — jadi tempatnya di dalam kartu, bukan melayang di bawahnya.
    # Sebelumnya ia digambar di luar dan karena itu tidak terbaca sebagai
    # bagian profil sama sekali.
    distribusi = _class_distribution_text(profile)
    if distribusi:
        pairs.append(("Distribusi kelas" if profile.get("class_counts")
                      else "Indikasi kelas", distribusi))

    with st.container(border=True):
        for label, value in pairs:
            cols = st.columns([1, 2])
            cols[0].markdown(label)
            cols[1].markdown(value)

    # Nama kolom: HANYA daftar lengkap, di expander tertutup.
    #
    # Cuplikan sepuluh nama pertama dicabut. Ia tidak menjawab pertanyaan apa
    # pun: sepuluh nama dari 88 tidak memberi tahu apakah dataset ini cocok —
    # itu sudah dijawab tabel Kecocokan di bawahnya — dan siapa pun yang
    # benar-benar mencari sebuah kolom tetap harus membuka daftar lengkapnya.
    # Yang tersisa hanyalah satu baris panjang yang dilewati mata.
    columns = profile.get("columns") or []
    if columns:
        with st.expander(f"Semua {len(columns)} {unit.lower()}", expanded=False):
            st.code("\n".join(str(c) for c in columns), language=None)

    catatan = _sample_note(profile)
    if catatan:
        st.markdown(catatan)


def _algorithms_for(dataset_type: str) -> list[str]:
    """Algoritma yang tersedia untuk sebuah dataset_type, DARI REGISTRY."""
    from config.pipeline_registry import get_pipelines_for_dataset
    seen: list[str] = []
    for info in get_pipelines_for_dataset(dataset_type).values():
        algo = info.get("algorithm") or info.get("name")
        if algo and algo not in seen:
            seen.append(algo)
    return seen


#: Dtype yang modal rinciannya sedang dibuka.
#:
#: Dahulu ia bagian dari mesin pendeteksi penutupan: modal yang ditutup
#: meninggalkan baris AgGrid tetap tercentang, sehingga ia akan terbuka lagi
#: pada rerun berikutnya kecuali kunci gridnya diganti. Pemicunya kini sebuah
#: TOMBOL — bernilai true hanya pada rerun tepat sesudah ditekan — jadi seluruh
#: mesin itu (nonce grid + pembandingnya) dicabut. Yang tersisa hanya catatan
#: siapa yang sedang dibuka, dan itu dipakai tesnya untuk membuktikan
#: tombolnyalah yang membukanya.
_COMPAT_OPEN_KEY = "_contrib_compat_open"

#: Putusan diagnosa → keadaan sel. Ketiganya sudah berpasangan satu-satu dengan
#: rona `grid.STATE_TINT`. Putusan tak dikenal menjadi "warn", BUKAN "ok":
#: menganggap yang tak dikenal sebagai cocok adalah kesalahan yang menutupi
#: masalah — aturan yang sama dengan `sr.verdict_state`.
_COMPAT_STATE = {"ok": "ok", "near": "warn", "no": "bad"}

#: Kolom tabel kecocokan: (kunci label i18n, bobot lebar).
#:
#: Digambar sebagai BARIS BERKOLOM aplikasi, bukan AgGrid. AgGrid hidup di
#: iframe: stylesheet aplikasi tidak menjangkaunya, gaya yang disuntikkan lewat
#: `custom_css` kalah oleh tema bawaan komponennya, dan hasilnya tidak dapat
#: diperiksa tes mana pun — tiga ronde percobaan menghasilkan tabel yang masih
#: berstriping, tanpa pil, dengan kolom terpotong. Bentuk ini memakai DOM
#: aplikasi sendiri, tempat `.ids-badge` dan garis temanya memang hidup, dan
#: tombol rinciannya berdiri DI DALAM barisnya — bukan tumpukan tombol
#: terpisah di bawah tabel.
#:
#: Kolom "Sebab" memuat kalimat sebab untuk SETIAP baris, termasuk yang cocok
#: ("Seluruh pemeriksaan lulus."). Kalimat TINDAKAN ("Agar cocok: sediakan
#: berkas `.ndjson`…") tetap tinggal di modal: satu kolom harus berarti satu
#: hal pada semua barisnya.
_COMPAT_COLUMNS = (
    ("ap.col_compat_research", 7),
    ("ap.col_compat_verdict", 4),
    ("ap.col_compat_algos", 3),
    ("ap.col_compat_cause", 12),
    ("", 4),                                  # tombol rincian
)

#: Putusan → rona pil. Rona yang SAMA dengan tabel lain di aplikasi ini, dibaca
#: dari satu tempat supaya "hijau" berarti hal yang sama di mana pun.
_COMPAT_TINT = {
    "ok": grid.STATE_TINT["ok"],
    "warn": grid.STATE_TINT["warn"],
    "bad": grid.STATE_TINT["bad"],
}


def _compat_badge(row: dict) -> str:
    """Putusan sebagai PIL. Warnanya dari keadaan, katanya dari barisnya —
    warna tidak pernah menjadi satu-satunya pembawa keterangan."""
    latar = _COMPAT_TINT.get(_compat_state(row), _COMPAT_TINT["warn"])
    return (f'<span class="ids-badge ids-badge-solid" '
            f'style="background:{latar};">'
            f'{escape(str(row.get("verdict_text") or ""))}</span>')


def _compat_state(row: dict) -> str:
    """Keadaan satu baris kecocokan, dibaca dari PENGENAL putusannya.

    Bukan dari kalimatnya: mewarnai berdasarkan teks berbahasa akan berhenti
    bekerja begitu pengguna berganti bahasa.
    """
    return _COMPAT_STATE.get((row or {}).get("verdict"), "warn")


def _compat_rows(diag: dict) -> list[dict]:
    """Satu baris per research pipeline, urut Cocok → Hampir → Tidak cocok.

    Fungsi MURNI atas hasil diagnosa yang sudah ber-cache: tidak ada berkas
    yang dibaca dan tidak ada pipeline yang dijalankan di sini.
    """
    from ui.views.run_experiment import (
        _VERDICT_LABEL, _cause_sentence, _sorted_results, _verdict,
    )

    baris = []
    for dtype, result in _sorted_results(diag):
        verdict = _verdict(result)
        baris.append({
            "dataset_type": dtype,
            "research": get_research_short_label(dtype),
            "verdict": verdict,
            "verdict_text": _VERDICT_LABEL[verdict],
            "algo_count": len(_algorithms_for(dtype)),
            "cause": _cause_sentence(diag, dtype, result),
        })
    return baris


def _request_compat_details(dataset_type: str) -> None:
    """Tandai modal rincian harus dibuka untuk satu research pipeline.

    Berdiri sebagai helper `_request_*` sendiri, bukan sebaris di dalam alur
    render, karena `tests/test_dialog_lifecycle` melarang flag modal disetel
    sebagai EFEK SAMPING penggambaran: flag yang ditulis ulang pada setiap
    rerun tidak akan pernah bisa ditutup.

    Yang membuatnya sah di sini bukan namanya, melainkan bahwa pemanggilnya
    memang satu tindakan pengguna dan bukan penggambaran: ia hanya berjalan
    saat AgGrid melaporkan baris TERPILIH, dan nonce kunci grid dinaikkan
    begitu modalnya ditutup, sehingga pilihan yang sama tidak dapat bertahan
    ke rerun berikutnya — jaminan yang sama dengan yang diberikan tombol.
    """
    dlg.open_dialog(dlg.COMPAT_KEY, dataset_type)
    st.session_state[_COMPAT_OPEN_KEY] = dataset_type


def _maybe_render_compat_dialog(diag: dict) -> None:
    """Panggil modal kecocokan dari ALUR UTAMA script bila ada flagnya.

    Modal yang SAMA dengan halaman Run Experiment — satu isi, satu tempat
    dirawat. Bedanya hanya daftar algoritma, yang di sana tidak dikirim karena
    pemilihnya berdiri di halaman itu sendiri.
    """
    from ui.views.run_experiment import _compat_dialog

    dtype = dlg.dialog_state(dlg.COMPAT_KEY)
    if not dtype:
        return
    if dtype not in (diag.get("results") or {}):
        # Dataset berganti sejak barisnya diklik — jangan sajikan hasil basi.
        dlg.close_dialog(dlg.COMPAT_KEY)
        return
    _compat_dialog(diag, dtype, algorithms=_algorithms_for(dtype))


def _render_compatibility(diag: dict) -> None:
    """Kecocokan PER RESEARCH PIPELINE (bukan per algoritma), sebagai TABEL.

    Dahulu satu kartu berbingkai per research pipeline: spanduk putusan, daftar
    butir algoritma, kalimat tindakan, dan expander rincian. Tiga kartu tinggi
    untuk menjawab satu pertanyaan, "yang mana yang cocok dengan berkas saya?".
    Jawaban itu sebuah perbandingan, dan perbandingan dibaca berbaris: satu
    tabel, kolomnya dapat diurutkan, klik barisnya untuk rinciannya.

    Mekanismenya SAMA dengan antrean tinjauan dan riwayat eksperimen — lihat
    `ui.components.grid` — dan rinciannya memakai modal yang SUDAH ADA di
    halaman Run Experiment, bukan salinan kedua yang perlahan menyimpang.
    """
    results = diag.get("results") or {}
    if not results:
        st.warning(diag.get("error") or "Diagnosa kecocokan tidak tersedia.")
        return

    compatible = diag.get("compatible_types") or []
    st.subheader(t("ap.sec_compatibility"))
    if not compatible:
        st.warning(t("ap.msg_no_match_anywhere"))

    lebar = [b for _, b in _COMPAT_COLUMNS]

    # Header disejajarkan dengan barisnya lewat jangkar yang sama dengan tabel
    # pengguna — baris berbingkai berpadding, header tidak, dan selisih itu
    # menggeser tiap kolom dengan besar berbeda.
    with st.container():
        st.markdown('<span class="ids-compat-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns(lebar, vertical_alignment="center")
        for kol, (kunci, _) in zip(kepala, _COMPAT_COLUMNS):
            kol.markdown(f"**{t(kunci)}**" if kunci else "")

    for row in _compat_rows(diag):
        with st.container(border=True):
            st.markdown('<span class="ids-compat-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns(lebar, vertical_alignment="center")
            sel[0].markdown(row["research"])
            sel[1].markdown(_compat_badge(row), unsafe_allow_html=True)
            sel[2].markdown(str(row["algo_count"]))
            # Kalimat sebab bisa panjang; nilai PENUHnya tetap terjangkau lewat
            # tooltip, jadi tidak ada yang hilang saat kolomnya sempit.
            sel[3].markdown(
                f'<span title="{escape(row["cause"])}">'
                f'{escape(row["cause"])}</span>', unsafe_allow_html=True)
            if sel[4].button(t("ap.btn_compat_detail"),
                             key=f"compat_detail_{row['dataset_type']}",
                             use_container_width=True):
                _request_compat_details(row["dataset_type"])
                st.rerun()

    # Modal dipanggil dari ALUR UTAMA, sesudah tabelnya digambar — bukan dari
    # dalam blok tombol maupun dari dalam wadah berkolom.
    _maybe_render_compat_dialog(diag)


# ── Entry point halaman ───────────────────────────────────────────────────

def render() -> None:
    # Penanda halaman: seluruh tombol utama DI HALAMAN INI digambar hitam
    # (lihat `.ids-page-dark` di theme.py). Didasarkan pada halamannya, bukan
    # pada daftar kunci tombol — halaman ini punya belasan tombol `primary`,
    # dan mendaftarkannya satu per satu berarti tombol berikutnya yang
    # ditambahkan seseorang akan merah sendirian.
    st.markdown('<span class="ids-page-dark"></span>', unsafe_allow_html=True)
    st.title(t("page.contribute"))

    mode = st.session_state.get(_MODE_KEY)
    if mode not in ("pipeline", "dataset", "users", "review"):
        _render_choice_boxes()
        return

    # SATU tombol kembali, dan selalu yang PALING DALAM. Ketika sebuah detail
    # sedang terbuka — satu pengajuan, satu pipeline, penyunting, atau
    # perbandingan versi — tampilan itu sudah menggambar tombol kembalinya
    # sendiri. Menggambar tombol kedua di atasnya menaruh dua tombol bertumpuk
    # yang tujuannya berbeda tanpa ada yang menjelaskan bedanya; keluar sampai
    # ke pilihan jalur tetap dapat ditempuh dengan menekan kembali dua kali.
    if not _detail_is_open():
        if back_button(key="contrib_back"):
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
