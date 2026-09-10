"""
Konteks halaman "Add Pipeline & Dataset": satu pertanyaan yang memang diajukan
sebelum mengunggah, dan jawabannya hanya bila diketuk.

Dahulu halaman ini dibuka tiga angka ringkas (jumlah research pipeline,
algoritma, dataset) dan satu baris hak pengguna. Keduanya sudah dicabut.
Angka-angka itu menerangkan platform, bukan menuntun tindakan, dan berdiri
tepat di antara pengguna dan pilihan jalur yang ia datangi; barisnya hak
mengulangi apa yang sudah dikatakan kontrol yang hidup atau mati di hadapannya.

Yang tersisa dua, dan keduanya menjawab sesuatu yang tidak dijawab tempat lain:

* **Ajakan masuk bagi pengunjung.** Tanpa ini halamannya menampilkan sederet
  kontrol mati tanpa keterangan apa pun mengapa.
* **Alur pasca-unggah, di dalam dropdown.** Dua jalur dengan dua aturan yang
  BERBEDA: dataset (DATA) tersimpan langsung, pipeline (KODE yang akan
  dieksekusi) menunggu tinjauan Research Admin. Kalimat lama menyamakan
  keduanya, sehingga pengunggah dataset menunggu sesuatu yang tidak pernah
  datang.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.i18n import t

from ui.components.instructions import inject_css, render_flow

logger = logging.getLogger(__name__)

# Alur SESUDAH mengunggah, dipakai di tampilan awal halaman.
# Dua jalur, dua aturan: dataset (DATA) tersimpan langsung; pipeline (KODE
# yang akan dieksekusi) tetap melewati tinjauan Research Admin.
AFTER_UPLOAD_FLOW = [
    ("📤", "Unggah"),
    ("🔍", "Periksa berkas"),
    ("✅", "Dataset tersimpan"),
    ("👤", "Pipeline ditinjau"),
]
AFTER_UPLOAD_FLOW_ALT = "ap.after_upload_alt"

#: Indeks langkah → kunci label. Ikon & urutannya tetap di konstanta di atas.
AFTER_UPLOAD_FLOW_KEYS = ("ap.flow_upload", "ap.flow_check_file",
                          "ap.flow_dataset_stored", "ap.flow_pipeline_reviewed")


def after_upload_flow_display():
    """Langkah alur setelah unggah, pada bahasa aktif."""
    from ui.i18n import t

    return [(icon, t(key))
            for (icon, _label), key in zip(AFTER_UPLOAD_FLOW,
                                           AFTER_UPLOAD_FLOW_KEYS)]


# ── Ajakan masuk ──────────────────────────────────────────────────

def render_sign_in_invite(user: dict | None) -> None:
    """Ajakan masuk, HANYA bagi pengunjung.

    Dahulu fungsi ini juga menggambar satu baris status ("Kontributor, boleh
    mengajukan pipeline & dataset"). Baris itu dicabut: pengguna yang sudah
    masuk melihat haknya dari kontrol yang hidup atau mati di hadapannya, dan
    kalimat yang mengulanginya hanya menunda ia sampai ke kontrol itu.

    Ajakan masuknya TIDAK ikut dicabut. Bagi pengunjung, tanpa kalimat ini
    halamannya menampilkan sederet kontrol mati tanpa satu pun keterangan
    mengapa — dan "kenapa saya tidak bisa menekan apa pun" adalah pertanyaan
    yang harus dijawab sebelum ia ditanyakan.
    """
    from ui.views.login import render_login_prompt

    from ui.i18n import t

    if not user:
        render_login_prompt(t("ap.cap_login_prompt"))



# ── Apa yang terjadi setelah mengunggah ───────────────────────────────────

def submission_counts(user: dict | None) -> dict:
    """{status: jumlah} pengajuan MILIK pengguna ini. Kosong untuk pengunjung.

    Hanya membaca; tidak menyaring tampilan eksperimen siapa pun.
    """
    if not user or not user.get("username"):
        return {}
    try:
        from orchestrator.submission_service import list_submissions
        mine = list_submissions(submitted_by=user["username"])
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Daftar pengajuan tidak terbaca", exc_info=True)
        return {}

    counts: dict[str, int] = {}
    for item in mine:
        status = item.get("status") or "?"
        counts[status] = counts.get(status, 0) + 1
    return counts


def render_after_upload(user: dict | None) -> None:
    """Alur pasca-unggah + ringkasan antrean pengajuan milik pengguna."""
    from ui.i18n import t

    render_flow(after_upload_flow_display(), alt=t(AFTER_UPLOAD_FLOW_ALT))

    counts = submission_counts(user)
    if not counts:
        return

    from database.models import SUBMISSION_PENDING
    from ui.i18n import t

    # Status pengajuan adalah PENGENAL di basis data; hanya labelnya dipetakan.
    order = [(SUBMISSION_PENDING, "ap.sub_pending"),
             ("approved", "ap.sub_approved"),
             ("rejected", "ap.sub_rejected")]
    parts = [f"{t(label_key)}: **{counts[key]}**"
             for key, label_key in order if counts.get(key)]
    other = sum(v for k, v in counts.items() if k not in dict(order))
    if other:
        parts.append(f"{t('ap.sub_other')}: **{other}**")
    if parts:
        st.caption(t("ap.sub_yours", parts=" · ".join(parts)))

    _render_rejection_notes(user)


def rejection_notes(items) -> list[tuple[int, str]]:
    """[(nomor pengajuan, catatan peninjau)] untuk yang DITOLAK dan bercatatan.

    Fungsi MURNI, dipisah dari perenderannya supaya dapat diperiksa tanpa
    menjalankan halaman.

    Hanya yang ditolak: pengajuan yang disetujui sudah menjelaskan dirinya
    sendiri lewat pipeline yang muncul di daftar, sedangkan yang ditolak tidak
    meninggalkan jejak apa pun selain catatan ini.
    """
    out = []
    for item in items or []:
        if (item.get("status") or "") != "rejected":
            continue
        note = str(item.get("review_note") or "").strip()
        if note:
            out.append((item.get("id"), note))
    return out


def _render_rejection_notes(user: dict | None) -> None:
    """Alasan penolakan — satu-satunya umpan balik yang kontributor terima.

    Dahulu ini hanya terbaca di kolom terakhir tabel "Pengajuan saya". Tabel itu
    dibuang; catatannya TIDAK, karena tanpanya seorang kontributor mengunggah
    ulang kesalahan yang sama tanpa pernah tahu apa yang salah.
    """
    from ui.i18n import t

    try:
        from orchestrator.submission_service import list_submissions
        mine = list_submissions(submitted_by=user["username"])
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Catatan penolakan tidak terbaca", exc_info=True)
        return

    for sid, note in rejection_notes(mine):
        st.markdown(t("ap.rejection_note", id=sid, note=note))


def render_related_pages() -> None:
    """Kaitan ke halaman lain, satu baris.

    Dua aturan yang BERBEDA, dan bedanya disebut: dataset tersimpan langsung
    setelah lolos pemeriksaan, sementara pipeline menunggu persetujuan karena
    isinya kode yang akan dieksekusi. Kalimat lama menyamakan keduanya,
    sehingga pengunggah dataset menunggu sesuatu yang tidak pernah datang.
    """
    from ui.i18n import t

    st.markdown(t("ap.related_pages", page=t("page.run_experiment")))


# ── Panel konteks (dipakai di tampilan awal halaman) ──────────────────────

def render_page_context(user: dict | None) -> None:
    """Ajakan masuk bila perlu, lalu satu dropdown alur pasca-unggah.

    Dahulu halaman ini dibuka tiga angka ringkas dan satu baris hak pengguna,
    keduanya sebelum pilihan jalurnya. Angka-angka itu menerangkan platform,
    bukan menuntun tindakan, dan berdiri tepat di antara pengguna dan pilihan
    yang ia datangi. Yang tersisa sekarang menjawab satu pertanyaan yang memang
    diajukan sebelum mengunggah, dan hanya bila ia diketuk.
    """
    inject_css()
    render_sign_in_invite(user)
    with st.expander(t("ctx.after_upload_q"), expanded=False):
        render_after_upload(user)
        # Kaitan ke halaman lain ikut MASUK ke sini: ia menjawab pertanyaan
        # yang sama — apa yang terjadi sesudah berkasnya diterima.
        render_related_pages()
