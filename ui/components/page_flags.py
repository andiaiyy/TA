"""
Siklus hidup HALAMAN: flag yang hanya sah di halamannya, halaman yang sedang
aktif, dan penundaan pembaruan berkala yang terikat pada halaman itu.

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

**Kenapa penundaan pembaruan ikut di sini.** Halaman yang memantau eksperimen
menunda lalu menyegarkan diri. Bila penundaan itu satu ``time.sleep`` panjang,
run-nya TIDAK PERNAH SELESAI selama itu — Streamlit hanya memeriksa permintaan
rerun (mis. pengguna menekan menu halaman lain) di sela pemanggilan ``st.*``,
sehingga klik pengguna tertahan sampai tidurnya habis dan elemen halaman lama
masih tergambar di layar. :func:`wait_before_refresh` menunggu dalam potongan
kecil sambil menulis ke satu placeholder, sehingga titik periksa itu ada dan
perpindahan halaman langsung diproses.
"""
from __future__ import annotations

import time

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


def page_is_active(name: str) -> bool:
    """True bila ``name`` adalah halaman yang sedang dirender.

    Dipakai perulangan pembaruan berkala supaya ia terikat pada halamannya:
    halaman yang sudah ditinggalkan tidak boleh menjadwalkan gambar ulang.
    """
    return st.session_state.get(PAGE_KEY) == name


#: Panjang satu potongan tunggu. Cukup pendek supaya klik pengguna terasa
#: langsung, cukup panjang supaya tidak membanjiri frontend.
REFRESH_TICK_SECONDS = 0.5


def wait_before_refresh(seconds, *, label: str = "Menyegarkan dalam",
                        page: str | None = None) -> bool:
    """Tunggu sebelum menyegarkan, TANPA menahan perpindahan halaman.

    Mengembalikan True bila penungguannya selesai (pemanggil boleh menyegarkan),
    False bila halaman sudah berganti selama menunggu — dalam hal itu pemanggil
    TIDAK boleh menggambar atau menyegarkan apa pun lagi.

    Hitung mundurnya ditulis ke SATU placeholder yang dikosongkan setelah
    selesai, jadi tidak ada baris yang menumpuk dan tidak ada teks baru yang
    ditambahkan ke halaman — ia menggantikan baris statis yang sebelumnya
    memberitahukan jeda yang sama.
    """
    deadline = time.monotonic() + max(int(seconds or 0), 1)
    slot = st.empty()
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return page is None or page_is_active(page)
            if page is not None and not page_is_active(page):
                return False
            # Penulisan inilah titik periksa Streamlit: permintaan rerun yang
            # tertunda (klik menu halaman lain) diproses di sini, bukan setelah
            # seluruh jeda habis.
            slot.markdown(f"{label} {int(left) + 1} detik…")
            time.sleep(min(REFRESH_TICK_SECONDS, left))
    finally:
        slot.empty()
