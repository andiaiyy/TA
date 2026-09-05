"""
Konteks halaman "Add Pipeline & Dataset" — menjawab pertanyaan pengguna
SEBELUM ia mencoba: saya sedang menambah ke ekosistem seperti apa, saya boleh
apa, dan apa yang terjadi setelah saya mengunggah.

Prinsip modul ini sama dengan ``ui/components/instructions.py``:

* **Tidak ada angka tetap.** Jumlah research pipeline & algoritma dihitung dari
  ``config/pipeline_registry``; jumlah dataset dari isi ``storage/datasets/``
  lewat mekanisme yang SAMA dengan halaman Run Experiment; jumlah pengajuan dari
  tabel pengajuan. Menambah entri registry atau menaruh berkas baru langsung
  mengubah tampilan tanpa menyentuh berkas ini.
* **Hak akses dibaca, bukan disimpulkan ulang.** Baris "Anda boleh apa" memanggil
  ``can_upload``/``can_approve`` yang sama dengan yang ditegakkan lapis aksi —
  modul ini tidak pernah menilai peran sendiri, jadi tampilan tidak mungkin
  menyimpang dari izin sebenarnya.
* **Kesalahan umum diturunkan dari pemeriksaan NYATA.** Butir-butirnya merujuk
  nama check yang benar-benar ada di validator (``_CAUSE_PRIORITY``) dan di
  diagnosa dataset (``_CHECK_TITLES``); tidak ada yang dikarang.
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


# ── Ringkasan keadaan platform ────────────────────────────────────────────

def platform_stats() -> dict:
    """Angka keadaan platform, DIHITUNG saat dipanggil.

    ``research``   — banyak research pipeline (dataset_type berbeda di registry)
    ``algorithms`` — banyak algoritma yang dapat dijalankan, dijumlahkan per
                     research pipeline (dedup nama algoritma di dalam satu
                     research pipeline, sama seperti daftar pilihan di
                     halaman Run Experiment)
    ``datasets``   — banyak berkas dataset di ``storage/datasets/``, dibaca
                     lewat mekanisme yang sama dengan halaman Run Experiment
    ``contributed``— banyak pipeline hasil kontribusi yang sudah terdaftar
    """
    stats = {"research": 0, "algorithms": 0, "datasets": 0, "contributed": 0}

    try:
        from config.pipeline_registry import list_all_pipelines
        registry = list_all_pipelines()
        per_research: dict[str, set] = {}
        for info in registry.values():
            dtype = info.get("dataset_type")
            if not dtype:
                continue
            algo = info.get("algorithm") or info.get("name")
            per_research.setdefault(dtype, set())
            if algo:
                per_research[dtype].add(algo)
        stats["research"] = len(per_research)
        stats["algorithms"] = sum(len(a) for a in per_research.values())
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Registry tidak terbaca untuk ringkasan platform", exc_info=True)

    try:
        from ui.views.run_experiment import _all_dataset_options
        stats["datasets"] = len(_all_dataset_options())
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Folder dataset tidak terbaca", exc_info=True)

    try:
        from orchestrator.dynamic_registry import list_registered
        stats["contributed"] = len(list_registered(active_only=True))
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Registry dinamis tidak terbaca", exc_info=True)

    return stats


def render_platform_summary() -> None:
    """Tiga angka ringkas, dalam KOTAK yang sama dengan halaman Run Experiment.

    Sebelumnya bagian ini memakai `st.metric` berjajar sementara halaman lain
    memakai kotak sel angka — dua gaya untuk hal yang sama. Sekarang keduanya
    memakai penyaji yang sama, jadi tampilannya tidak mungkin berbeda.
    """
    from ui.components.sections import render_counts

    stats = platform_stats()
    render_counts([
        ("research pipeline", stats["research"],
         (f"{stats['contributed']} pipeline hasil kontribusi sudah aktif di "
          f"registry." if stats["contributed"] else
          "Research pipeline yang terdaftar di registry.")),
        ("algoritma", stats["algorithms"],
         "Dijumlahkan per research pipeline."),
        ("dataset", stats["datasets"],
         "Berkas dataset di storage/datasets/."),
    ])


# ── Status & hak pengguna ─────────────────────────────────────────────────

def capability(user: dict | None) -> dict:
    """Status pengguna + apa yang boleh dilakukannya.

    ``{"label", "what", "may_upload", "may_review"}``. Kedua boolean DIBACA dari
    ``can_upload``/``can_approve`` — helper yang sama dengan yang ditegakkan
    lapis aksi — dan kalimatnya dipilih dari boolean itu, bukan dari peran.
    Jadi tampilan ini tidak mungkin menjanjikan hak yang sebenarnya ditolak.
    """
    from orchestrator.auth_service import can_approve, can_upload

    may_upload, may_review = bool(can_upload(user)), bool(can_approve(user))

    # Frasa, bukan kalimat — apa yang boleh dilakukan, tanpa kata pengisi.
    from ui.i18n import t

    if not user:
        label = t("ap.cap_visitor_label")
        # Disebut spesifik: OBJEK yang dapat dibaca dan diperiksa,
        # plus batasnya. Sesuai perilaku nyata — `can_upload(None)`
        # False, sedangkan diagnosa kecocokan dataset berada sebelum
        # gerbang izin sehingga pengunjung benar-benar dapat
        # menjalankannya.
        what = t("ap.cap_visitor_what")
    else:
        label = role_display(user.get("role")) or t("ap.cap_user_fallback")
        if may_review:
            what = t("ap.cap_may_review")
        elif may_upload:
            what = t("ap.cap_may_upload")
        else:
            what = t("ap.cap_pending")

    return {"label": label, "what": what,
            "may_upload": may_upload, "may_review": may_review}


#: Peran tersimpan → kunci label tampilan. Nilai perannya sendiri
#: (`contributor`, `research_admin`) TIDAK berbahasa dan tidak diubah.
ROLE_LABEL_KEYS = {
    "contributor": "ap.role_contributor",
    "research_admin": "ap.role_research_admin",
}


def role_display(role: str | None) -> str:
    """Nama peran pada bahasa aktif.

    Peran yang belum punya kunci jatuh kembali ke label lama, bukan ke teks
    kosong — peran baru tetap terbaca meski belum diterjemahkan.
    """
    from database.models import normalize_role, role_label
    from ui.i18n import t

    key = ROLE_LABEL_KEYS.get(normalize_role(role))
    return t(key) if key else role_label(role)


def render_capability(user: dict | None) -> None:
    """Satu baris status + ajakan masuk bila memang relevan."""
    from ui.views.login import render_login_prompt

    from ui.i18n import t

    cap = capability(user)
    _status = f"**{cap['label']}** — {cap['what']}"
    if user and not cap["may_upload"]:
        _status += " " + t("ap.cap_pending_readable")
    st.markdown(_status)
    if not user:
        # Keterangan WAJIB "kenapa aksi tak tersedia" — diringkas sependek
        # mungkin; penunjuk jalur masuknya ditambahkan render_login_prompt.
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
    """Konteks platform → status & hak pengguna → alur pasca-unggah.

    Urutan ini sengaja mendahului pilihan jalur: pengguna tahu lebih dulu ia
    menambah ke ekosistem seperti apa dan ia boleh apa, sebelum memilih.
    """
    inject_css()
    render_platform_summary()
    render_capability(user)
    with st.expander(t("ctx.after_upload_q"), expanded=False):
        render_after_upload(user)
    # Kaitan ke halaman lain tetap di tampilan utama: satu baris, dan justru
    # inilah alasan seseorang mengunggah.
    render_related_pages()
