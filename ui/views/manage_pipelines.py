"""
Penyaji pengelolaan pipeline kontribusi — dipakai DI DALAM sub-tampilan
"Peninjauan Pengajuan" pada halaman "Add Pipeline & Dataset".

Ini BUKAN halaman tersendiri. Modul ini menyediakan dua penyaji: bagian
**Aktif** (kartu research pipeline) dan bagian **Riwayat tinjauan**. Bagian
"Menunggu tinjauan" tetap milik ``ui/views/contribute.py`` — kartu tinjauannya
di sana sudah lebih lengkap (ia menyediakan pemilih ``dataset_type`` yang
dibutuhkan ``approve_submission`` saat metadata pengajuan belum memuatnya),
jadi menggantinya justru akan menghilangkan kemampuan.

**Apa yang DICABUT dari modul ini, dan apa akibatnya.** Tabel versi algoritma,
halaman satu-pipeline yang dibuka dari barisnya, penyunting berkas paket,
riwayat versi, dan pembanding dua versi seluruhnya dihapus.

Dua tindakan benar-benar hilang dari UI bersamanya: **menyunting berkas sebuah
paket** dan **meninjau ulang sebuah pengajuan**. Keduanya tidak lagi dapat
dilakukan dari layar mana pun; menyunting kini berjalan lewat pengajuan baru,
dan ``reopen_submission`` tetap ada di orchestrator tanpa pemicu UI.

Dua tindakan lain TIDAK hilang, dan itu perlu disebut supaya tidak dicari di
tempat yang salah: **menonaktifkan** dan **menghapus satu versi algoritma**
tetap tersedia di panel "Kelola research pipeline" pada halaman *Jalankan
Eksperimen* (``ui/components/research_admin_panel.py``), bersama penghalang
dan konfirmasinya masing-masing.

Yang TIDAK hilang juga datanya. ``registered_pipelines``,
``pipeline_versions``, dan berkas versi di disk tetap utuh; setiap eksperimen
lama tetap dapat dilacak ke berkas dan hash yang benar-benar dipakainya, dan
``orchestrator/pipeline_versions`` tetap menyediakan seluruh fungsinya bagi
pemanggil lain. Yang dicabut tampilannya, bukan ketertelusurannya.

Yang perlu diketahui saat membaca berkas ini:

* **Modul ini tidak menegakkan izin.** Ia hanya menyembunyikan kontrol yang
  tidak relevan; penolakan sebenarnya ada di fungsi aksinya
  (``require_approve`` di ``orchestrator/submission_service``). Menyembunyikan
  tombol tidak pernah menjadi satu-satunya penghalang.
* **Kode kontribusi tidak pernah dijalankan di sini.** Tidak ada ``import``
  maupun eksekusi paket kontribusi di jalur mana pun pada modul ini.
"""
from __future__ import annotations

import logging

import streamlit as st

from ui.i18n import t

# Impor yang dahulu melayani penyunting berkas, tabel versi, dan pembandingnya
# ikut dicabut bersama tampilannya. Yang tersisa hanya yang benar-benar dipakai
# ketiga bagian yang masih hidup.
from orchestrator.dynamic_registry import list_registered
from orchestrator.pipeline_versions import experiment_counts, running_experiments
from ui.components import registry_view as rv
from ui.components.sections import prose

logger = logging.getLogger(__name__)

# Kunci state penyunting, riwayat versi, dan pembandingnya SUDAH DICABUT
# bersama tampilannya. Yang tersisa di modul ini hanya bagian yang aktif, jadi
# tidak ada satu pun kunci berumur-halaman yang perlu dipegang di sini.

# Bagian yang sedang tampil pada sub-tampilan "Peninjauan Pengajuan".
SECTION_PENDING = "Menunggu tinjauan"
SECTION_ACTIVE = "Aktif"
SECTION_KEY = "_mp_section"


# ── Pemisahan bagian ────────────────────────────────────────────────────
#
# MEKANISME YANG DIPILIH: segmented control di atas — satu bagian tampil pada
# satu waktu.
#
# Alasannya, dibanding bagian bertumpuk dengan pemisah tebal:
#
# 1. Keduanya adalah PEKERJAAN yang berbeda, bukan bacaan berurutan. Meninjau
#    antrean dan mengelola registry tidak pernah dilakukan bersamaan;
#    menumpuknya hanya memaksa menggulir melewati bagian yang tidak sedang
#    dikerjakan.
# 2. Masing-masing bisa PANJANG (satu kartu per pengajuan, satu kartu per
#    research pipeline). Jarak antar-bagian sebesar apa pun tidak menolong bila
#    bagian di atasnya sendiri sudah beberapa layar tingginya.
# 3. Hanya bagian terpilih yang dirender, jadi biaya membaca basis data ikut
#    turun: memuat "Menunggu tinjauan" tidak lagi menarik seluruh registry.
#
# BAGIAN KETIGA — riwayat tinjauan — SUDAH DICABUT. Yang hilang bersamanya
# disebut apa adanya: tidak ada lagi tempat di UI yang menampilkan pengajuan
# mana yang disetujui atau ditolak, kapan, dan oleh siapa. Datanya TIDAK
# dihapus; seluruh barisnya tetap di tabel `submissions` beserta
# `reviewed_by`, `reviewed_at`, dan `review_note`.
#
# KEADAAN TIDAK HILANG saat berpindah: state bagian hidup di
# ``st.session_state`` (pengajuan yang sedang dibuka) dan tidak dibuang oleh
# perpindahan — segmented control hanya mengubah `SECTION_KEY`.


#: Urutan baku kedua bagian.
SECTIONS = (SECTION_PENDING, SECTION_ACTIVE)

#: Bagian terakhir yang benar-benar tampil — BUKAN kunci widget, jadi boleh
#: ditulis kapan saja. `SECTION_KEY` sendiri terikat ke segmented control dan
#: hanya boleh disentuh sebelum widgetnya dibuat atau dari dalam callback.
_SECTION_LAST = "_mp_section_last"


#: Pengenal bagian → kunci labelnya. `SECTION_*` di atas adalah PENGENAL yang
#: disimpan di ``session_state`` dan dipakai untuk memilih bagian; ia TIDAK
#: diterjemahkan, sama seperti pengenal halaman. Yang berbahasa hanya labelnya.
SECTION_LABEL_KEYS = {
    SECTION_PENDING: "ap.sec_pending",
    SECTION_ACTIVE: "ap.sec_active",
}


def section_label(section: str, pending: int, active: int) -> str:
    """Label bagian + PENANDA JUMLAH, supaya isinya terbaca sebelum dibuka."""
    if section == SECTION_PENDING:
        return t("ap.sec_pending", count=pending)
    return t("ap.sec_active_n", count=active)


def render_section_switch(pending: int, active: int) -> str:
    """Segmented control pemilih bagian; mengembalikan bagian yang dipilih."""
    last = st.session_state.get(_SECTION_LAST, SECTION_PENDING)
    # Sebelum widget dibuat — sah, dan ini juga yang memulihkan pilihan bila
    # pengguna membatalkan pilihannya (segmented control dapat dilepas).
    if st.session_state.get(SECTION_KEY) not in SECTIONS:
        st.session_state[SECTION_KEY] = last
    chosen = st.segmented_control(
        t("ap.lbl_section"), list(SECTIONS), key=SECTION_KEY,
        format_func=lambda s: section_label(s, pending, active),
        label_visibility="collapsed")
    section = chosen if chosen in SECTIONS else last
    st.session_state[_SECTION_LAST] = section
    return section


# ── Bagian: Aktif ───────────────────────────────────────────────────────

def registry_snapshot() -> dict:
    """Seluruh pipeline kontribusi + angka pemakaiannya, dibaca SEKALI.

    Dikelompokkan per nama supaya versi-versinya dapat disajikan bersama;
    hitungan eksperimen sudah per VERSI karena nomor versi melekat pada
    ``pipeline_id`` yang dicatat tiap eksperimen.
    """
    try:
        rows = list_registered()
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Registry dinamis tidak terbaca", exc_info=True)
        return {"grouped": {}, "counts": {}, "running": {}}

    counts = experiment_counts()
    running = {row["pipeline_id"]: running_experiments(row["pipeline_id"])
               for row in rows}
    return {"grouped": rv.group_versions(rows), "counts": counts,
            "running": running}


def active_rows() -> list[dict]:
    """Ringkasan tiap pipeline kontribusi — aktif maupun tidak.

    Nama fungsinya dipertahankan karena sudah dipakai pemanggil lain; isinya
    kini SELURUH pipeline, dengan bendera ``is_active`` masing-masing, supaya
    yang dinonaktifkan tidak pernah hilang dari pandangan.
    """
    snap = registry_snapshot()
    out = [rv.pipeline_summary(name, versions, snap["counts"],
                               running=snap["running"])
           for name, versions in snap["grouped"].items()]
    out.sort(key=lambda s: (not s["is_active"], s["name"].lower()))
    return out


def render_active(user: dict) -> None:
    """Bagian "Aktif": kartu RESEARCH PIPELINE, bawaan maupun kontribusi.

    Tabel versi algoritma yang dahulu berada di bawahnya sudah dicabut, beserta
    halaman satu-pipeline yang dibuka dari barisnya. Yang benar-benar hilang
    bersamanya hanya dua: menyunting berkas paket dan meninjau ulang sebuah
    pengajuan. Menonaktifkan dan menghapus satu versi algoritma pindah tempat,
    bukan hilang — keduanya ada di panel "Kelola research pipeline" pada
    halaman Jalankan Eksperimen. Datanya TIDAK dihapus: `registered_pipelines`,
    `pipeline_versions`, dan berkas versinya tetap utuh, dan menyunting lewat
    pengajuan baru tetap menghasilkan versi seperti biasa.

    Yang tersisa di sini mengelola research pipeline sebagai satu kesatuan:
    mengaktifkan, menonaktifkan, dan menyunting atribusinya — lewat kartunya.
    """
    from ui.components import research_manage as rs

    # TANPA judul bagian: pengalih bagian tepat di atas sudah menuliskan
    # "Aktif" beserta jumlahnya, dan keterangannya kini menempel pada judul
    # halaman (lihat `contribute._render_review_flow`).
    rs.render(user, heading=False)

    # Kolom "Status" sebuah pipeline nonaktif menyebut keadaannya, tetapi tidak
    # menyebut AKIBATNYA. Kalimat ini yang menyebutkannya, dan ia tetap
    # dibutuhkan sekalipun tabelnya sudah tidak ada.
    idle = [s for s in active_rows() if not s["is_active"]]
    if idle:
        prose(t("mp.idle_heading", count=len(idle)), key="mp_idle_note")
