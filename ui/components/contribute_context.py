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

from ui.components.instructions import inject_css, render_flow

logger = logging.getLogger(__name__)

# Alur SESUDAH mengunggah, dipakai di tampilan awal halaman.
# Dua jalur, dua aturan: dataset (DATA) tersimpan langsung; pipeline (KODE
# yang akan dieksekusi) tetap melewati tinjauan Research Admin.
AFTER_UPLOAD_FLOW = [
    ("📤", "Unggah"),
    ("🔍", "Periksa otomatis"),
    ("✅", "Dataset tersimpan"),
    ("👤", "Pipeline ditinjau"),
]
AFTER_UPLOAD_FLOW_ALT = (
    "Setelah diperiksa: dataset langsung tersimpan; pipeline menunggu tinjauan "
    "Research Admin karena berisi kode yang dieksekusi."
)


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
    """Tiga angka ringkas + satu baris kaitan ke halaman lain."""
    stats = platform_stats()
    cols = st.columns(3)
    cols[0].metric("Research pipeline", stats["research"])
    cols[1].metric("Algoritma", stats["algorithms"])
    cols[2].metric("Dataset di server", stats["datasets"])
    if stats["contributed"]:
        st.caption(f"{stats['contributed']} pipeline hasil kontribusi sudah "
                   f"aktif di registry.")


# ── Status & hak pengguna ─────────────────────────────────────────────────

def capability(user: dict | None) -> dict:
    """Status pengguna + apa yang boleh dilakukannya.

    ``{"label", "what", "may_upload", "may_review"}``. Kedua boolean DIBACA dari
    ``can_upload``/``can_approve`` — helper yang sama dengan yang ditegakkan
    lapis aksi — dan kalimatnya dipilih dari boolean itu, bukan dari peran.
    Jadi tampilan ini tidak mungkin menjanjikan hak yang sebenarnya ditolak.
    """
    from database.models import role_label
    from orchestrator.auth_service import can_approve, can_upload

    may_upload, may_review = bool(can_upload(user)), bool(can_approve(user))

    # Frasa, bukan kalimat — apa yang boleh dilakukan, tanpa kata pengisi.
    if not user:
        label = "Mode pengunjung"
        what = "membaca & menjalankan pemeriksaan"
    else:
        label = role_label(user.get("role")) or "Pengguna"
        if may_review:
            what = "mengajukan, meninjau, mengelola pengguna"
        elif may_upload:
            what = "mengajukan pipeline & dataset"
        else:
            what = "menunggu persetujuan — belum dapat mengajukan"

    return {"label": label, "what": what,
            "may_upload": may_upload, "may_review": may_review}


def render_capability(user: dict | None) -> None:
    """Satu baris status + ajakan masuk bila memang relevan."""
    from ui.views.login import render_login_prompt

    cap = capability(user)
    st.markdown(f"**{cap['label']}** — {cap['what']}")
    if not user:
        # Keterangan WAJIB "kenapa aksi tak tersedia" — diringkas sependek
        # mungkin; penunjuk jalur masuknya ditambahkan render_login_prompt.
        render_login_prompt("Mengajukan berkas memerlukan akun.")
    elif not cap["may_upload"]:
        st.caption("Menunggu persetujuan — halaman tetap dapat dibaca.")


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
    render_flow(AFTER_UPLOAD_FLOW, alt=AFTER_UPLOAD_FLOW_ALT)

    counts = submission_counts(user)
    if not counts:
        return

    from database.models import SUBMISSION_PENDING
    order = [(SUBMISSION_PENDING, "Menunggu tinjauan"), ("approved", "Disetujui"),
             ("rejected", "Ditolak")]
    parts = [f"{label}: **{counts[key]}**" for key, label in order if counts.get(key)]
    other = sum(v for k, v in counts.items() if k not in dict(order))
    if other:
        parts.append(f"lainnya: **{other}**")
    if parts:
        st.caption("Pengajuan Anda — " + " · ".join(parts) + ".")


def render_related_pages() -> None:
    """Kaitan ke halaman lain, satu baris."""
    st.caption("Setelah disetujui, dataset & pipeline muncul di **Run Experiment**.")


# ── Panel konteks (dipakai di tampilan awal halaman) ──────────────────────

def render_page_context(user: dict | None) -> None:
    """Konteks platform → status & hak pengguna → alur pasca-unggah.

    Urutan ini sengaja mendahului pilihan jalur: pengguna tahu lebih dulu ia
    menambah ke ekosistem seperti apa dan ia boleh apa, sebelum memilih.
    """
    inject_css()
    render_platform_summary()
    render_capability(user)
    with st.expander("Apa yang terjadi setelah saya mengunggah?", expanded=False):
        render_after_upload(user)
    # Kaitan ke halaman lain tetap di tampilan utama: satu baris, dan justru
    # inilah alasan seseorang mengunggah.
    render_related_pages()
