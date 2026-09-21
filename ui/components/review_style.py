"""Bentuk halaman peninjauan: dua zona, dan satu kepala yang menyebut keadaan.

Halaman peninjauan satu pengajuan dahulu adalah satu expander berisi enam belas
blok teks, tiga expander bersarang, enam tombol — dua di antaranya tombol
kembali — dan dua paragraf peringatan. Semuanya berselang-seling, sehingga
tidak ada tempat yang jelas untuk memulai maupun mengakhiri.

Modul ini menyediakan pembedanya. Dua zona, karena keduanya dibaca dengan sikap
yang berbeda:

* :data:`ZONE_READ` — **yang diperiksa**. Identitas, berkas, temuan, kode.
  Tidak ada yang berubah karena membacanya.
* :data:`ZONE_WORK` — **keputusan**. Dataset uji, catatan, setujui/tolak/hapus.
  Setiap kendali di sini mengubah sesuatu.

Pembedaan itu bukan hiasan: keliru mengira zona kerja sebagai zona baca berarti
menekan tombol yang mengubah keadaan sambil mengira sedang membaca.
"""
from __future__ import annotations

from html import escape

import streamlit as st

#: Tiga zona halaman peninjauan. Nilainya PENGENAL, bukan kalimat — judulnya
#: disodorkan pemanggil supaya tetap berbahasa aktif.
ZONE_READ = "read"
ZONE_TEST = "test"
ZONE_WORK = "work"

ZONES = (ZONE_READ, ZONE_TEST, ZONE_WORK)


#: Hasil periksa → nama keadaan yang dipakai gaya. Sengaja DIPETAKAN, bukan
#: dipakai apa adanya: nilai `verdict` adalah pengenal milik `submission_review`
#: dan modul ini tidak boleh mengunci diri pada ejaannya.
_VERDICT_STATE = {"bersih": "ok", "peringatan": "warn", "bermasalah": "bad"}


def verdict_state(verdict: str) -> str:
    """Keadaan yang dipakai gaya: "ok", "warn", atau "bad".

    Hasil periksa yang tidak dikenal menjadi "warn", bukan "ok": menganggap
    yang tak dikenal sebagai bersih adalah kesalahan yang menutupi masalah.
    """
    return _VERDICT_STATE.get(str(verdict or ""), "warn")


def review_header(*, name: str, verdict: str, verdict_text: str, files,
                  who: str, when: str) -> None:
    """Kepala halaman satu pengajuan: nama besar, keadaan, lalu konteksnya.

    Nama pengaju dan waktunya berasal dari basis data dan ditampilkan apa
    adanya — hanya susunannya yang ditentukan di sini.
    """
    state = verdict_state(verdict)
    meta = " · ".join(str(part) for part in
                      (f"{files} berkas" if files else "", who, when) if part)
    st.markdown(
        f'<div class="ids-rv-head ids-rv-{state}">'
        f'<div class="ids-rv-name">{escape(str(name))}</div>'
        f'<div class="ids-rv-verdict">{escape(str(verdict_text))}</div>'
        f'<div class="ids-rv-meta">{escape(meta)}</div>'
        "</div>",
        unsafe_allow_html=True)


def file_heading(*, filename: str, role: str, size: str, ok: bool) -> None:
    """Kepala satu berkas paket — menggantikan label expander yang dibuang."""
    state = "ok" if ok else "bad"
    tail = " · ".join(part for part in (str(role), size) if part)
    st.markdown(
        f'<div class="ids-rv-file ids-rv-{state}">'
        f'<span class="ids-rv-fname">{escape(str(filename))}</span>'
        f'<span class="ids-rv-ftail">{escape(tail)}</span>'
        "</div>",
        unsafe_allow_html=True)


def zone_heading(zone: str, title: str, *, help: str = "") -> None:
    """Judul satu zona, dengan keterangannya di tooltip.

    ``zone`` menentukan penampilannya; ``title`` adalah kalimatnya. Zona yang
    tidak dikenal digambar apa adanya alih-alih hilang: judul yang lenyap lebih
    membingungkan daripada judul tanpa gaya.

    ``help`` adalah tempat KETERANGAN zona, mengikuti aturan yang sudah dipakai
    `sections.render_section`: keterangan judul tinggal di `help`, bukan
    sebagai baris teks di bawahnya. Zona peninjauan dahulu menaruhnya sebagai
    paragraf, dan empat paragraf semacam itu berdiri di antara peninjau dan
    keputusan yang harus ia ambil.

    Dirender sebagai atribut `title` pada divnya, bukan lewat widget Streamlit:
    judul zona ini memang satu div, dan `title` adalah tooltip bawaan peramban
    yang sama dengan yang dipakai sel tabel panjang di aplikasi ini.
    """
    kind = zone if zone in ZONES else ZONE_READ
    tip = f' title="{escape(help)}"' if help else ""
    st.markdown(
        f'<div class="ids-zone ids-zone-{kind}"{tip}>{escape(title)}</div>',
        unsafe_allow_html=True)
