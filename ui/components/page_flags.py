"""
Pembersih flag modal yang hanya sah di HALAMANNYA sendiri.

Masalah yang dicegah: sebuah tombol men-set flag pembuka modal, lalu pengguna
berpindah halaman sebelum menutupnya. Karena flag hidup di ``session_state``,
kembali ke halaman itu akan membuka modalnya lagi — modal "muncul sendiri".
Bug persis ini pernah terjadi pada modal masuk/daftar.

Kenapa perlu dijalankan di tingkat aplikasi: sebuah view tidak dapat mendeteksi
kepergiannya sendiri. Saat pengguna membuka halaman lain, ``render()`` milik view
itu TIDAK dipanggil sama sekali, jadi tidak ada tempat baginya untuk menyadari
perpindahan. Yang tahu hanyalah ``ui/app.py``, yang berjalan pada setiap halaman
— karena itu ia yang memanggil :func:`drop_stale_page_flags` sekali per run.

Flag auth punya mekanisme setara di ``ui/views/login.py`` (ia menyimpan halaman
saat modal diminta); modul ini menangani flag modal milik halaman lain.
"""
from __future__ import annotations

import streamlit as st

from ui.components.dialogs import DIALOG_KEYS

# Kunci halaman aktif, ditulis ui/app.py setiap run.
PAGE_KEY = "_current_page"

# Halaman yang dirender pada run sebelumnya.
_LAST_PAGE_KEY = "_page_flags_last_page"

# Flag modal yang HANYA sah selama pengguna berada di halamannya. Daftarnya
# datang dari ui/components/dialogs.py — satu tempat pendaftaran, sehingga
# menambah modal baru di sana otomatis ikut dibersihkan di sini dan tidak ada
# daftar kedua yang bisa ketinggalan.
PAGE_SCOPED_KEYS: tuple[str, ...] = DIALOG_KEYS


def drop_stale_page_flags(current_page: str | None = None) -> bool:
    """Buang flag modal berhalaman bila halaman aktif BERGANTI sejak run lalu.

    Mengembalikan True bila perpindahan halaman terdeteksi. Dipanggil sekali per
    run dari ``ui/app.py``, sebelum halaman dirender — sehingga flag basi sudah
    hilang saat view memeriksanya.
    """
    page = current_page if current_page is not None else st.session_state.get(PAGE_KEY)
    if page is None:
        return False

    previous = st.session_state.get(_LAST_PAGE_KEY)
    st.session_state[_LAST_PAGE_KEY] = page
    if previous is None or previous == page:
        return False

    for key in PAGE_SCOPED_KEYS:
        st.session_state.pop(key, None)
    return True
