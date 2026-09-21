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
from html import escape

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

    _render_my_submissions(user)
    _render_rejection_notes(user)


#: Lebar kolom daftar "Pengajuan saya". Nama paling lebar: di situlah teks
#: terpanjang berada.
_MY_SUB_COLS = (
    ("ap.my_subs_col_id", 2),
    ("ap.my_subs_col_name", 9),
    ("ap.my_subs_col_status", 4),
    ("ap.my_subs_col_check", 5),
    ("trial.my_subs_col", 4),
)


def _render_my_submissions(user: dict | None) -> None:
    """Daftar pengajuan milik pengguna ini, satu baris masing-masing.

    Yang ditampilkan hanya fakta yang MEMANG sudah tersimpan pada barisnya.
    Tanpa daftar ini seorang kontributor tidak dapat membedakan pengajuannya
    satu sama lain, tidak tahu pemeriksaannya lolos atau tidak, dan tidak
    pernah mengetahui bahwa paketnya sudah disunting peninjau.
    """
    from ui.i18n import t

    rows = my_submission_rows(user)
    if not rows:
        return

    st.markdown(f"**{t('ap.my_subs_head')}**")
    with st.container():
        st.markdown('<span class="ids-queue-head"></span>',
                    unsafe_allow_html=True)
        kepala = st.columns([b for _k, b in _MY_SUB_COLS],
                            vertical_alignment="center")
        for kol, (kunci, _b) in zip(kepala, _MY_SUB_COLS):
            kol.markdown(f"**{t(kunci)}**")

    for row in rows:
        with st.container(border=True):
            st.markdown('<span class="ids-queue-row"></span>',
                        unsafe_allow_html=True)
            sel = st.columns([b for _k, b in _MY_SUB_COLS],
                             vertical_alignment="center")
            sel[0].markdown(f"#{row['id']}")
            sel[1].markdown(escape(row["nama"] or "-"))
            sel[2].markdown(escape(_status_label(row["status"])))
            sel[3].markdown(escape(_check_label(row["diperiksa"])))
            sel[4].markdown(escape(row["uji"] or t("trial.my_subs_none")))
            if row["revisi"]:
                st.caption(t("ap.my_subs_revised", count=row["revisi"]))


def _status_label(status: str) -> str:
    """Label status pengajuan pada bahasa aktif; pengenal mentah bila tak dikenal."""
    from database.models import SUBMISSION_PENDING
    from ui.i18n import t

    peta = {SUBMISSION_PENDING: "ap.sub_pending",
            "approved": "ap.sub_approved",
            "rejected": "ap.sub_rejected"}
    kunci = peta.get(status)
    return t(kunci) if kunci else (status or "-")


def _check_label(lolos) -> str:
    """"lolos" / "tidak lolos" / "belum diperiksa" — ketiganya dibedakan.

    `None` BUKAN "tidak lolos": ia berarti tidak ada catatannya, dan menyebut
    keduanya dengan kata yang sama membuat kontributor memperbaiki kode yang
    tidak pernah salah.
    """
    from ui.i18n import t

    if lolos is None:
        return t("ap.my_subs_check_none")
    return t("ap.my_subs_check_ok" if lolos else "ap.my_subs_check_bad")


def my_submission_rows(user: dict | None, *, reader=None) -> list[dict]:
    """Satu baris per pengajuan MILIK pengguna ini. MURNI terhadap tampilan.

    Sebelumnya kontributor hanya menerima ANGKA: "pending: 4". Empat pengajuan
    berbeda, satu di antaranya sudah diuji dan satu lagi paketnya sudah
    disunting peninjau, dan tidak satu pun dari itu terbaca olehnya — bahkan
    nomor pengajuannya sendiri tidak. Yang dikembalikan di sini adalah fakta
    yang MEMANG sudah tersimpan pada barisnya, bukan keterangan baru:

    ``id``, ``nama``, ``status``, apakah pemeriksaan statisnya lolos,
    hasil uji terakhir, berapa kali paketnya direvisi peninjau, dan catatan
    peninjau bila ada.

    ``reader`` disuntikkan saat menguji.
    """
    if not user or not user.get("username"):
        return []
    if reader is None:
        from orchestrator.submission_service import list_submissions
        reader = list_submissions
    try:
        mine = reader(submitted_by=user["username"]) or []
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Daftar pengajuan tidak terbaca", exc_info=True)
        return []

    keluar = []
    for item in mine:
        metadata = item.get("metadata") or {}
        keluar.append({
            "id": item.get("id"),
            "nama": str(metadata.get("name")
                        or item.get("original_filename") or "").strip(),
            "status": str(item.get("status") or "").strip(),
            "diperiksa": _static_ok(item),
            "uji": _trial_summary(item),
            "revisi": _revision_count(item),
            "catatan": str(item.get("review_note") or "").strip(),
            "diajukan": str(item.get("submitted_at") or "").strip(),
        })
    return keluar


def _static_ok(item: dict):
    """True/False hasil pemeriksaan statis; None bila tidak ada catatannya."""
    import json as _json

    raw = item.get("validation") or item.get("validation_json")
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, dict) or not raw:
        return None
    if "valid" in raw:
        return bool(raw["valid"])
    laporan = raw.get("files") or raw.get("reports")
    if isinstance(laporan, list) and laporan:
        return all(bool(r.get("valid")) for r in laporan if isinstance(r, dict))
    return None


def _trial_summary(item: dict) -> str:
    """Keadaan uji coba terakhir pengajuan ini; "" bila belum pernah diuji."""
    import json as _json

    raw = item.get("trial") or item.get("trial_json")
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except (TypeError, ValueError):
            return ""
    if not isinstance(raw, dict) or not raw:
        return ""
    return str(raw.get("status") or raw.get("state") or "").strip()


def _revision_count(item: dict) -> int:
    """Berapa kali paket ini disunting peninjau. 0 bila tidak pernah."""
    from orchestrator.submission_service import revision_history

    try:
        return len(revision_history(item) or [])
    except Exception:                       # pragma: no cover - defensif
        return 0


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
