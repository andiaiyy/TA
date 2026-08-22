"""
Siklus hidup SEMUA modal di aplikasi, dalam satu pola.

Sebuah modal Streamlit dibuka lewat flag di ``session_state``: tombol menulis
flag, alur utama script membacanya lalu memanggil fungsi ber-``@st.dialog``.
Polanya benar, tetapi rapuh pada satu titik — **flag yang tidak dibersihkan akan
membuka modal itu lagi pada rerun berikutnya**. Gejalanya: modal "muncul
sendiri" setiap kali pengguna menyentuh apa pun. Bug ini sudah pernah terjadi
pada modal masuk/daftar, lalu berulang pada modal detail & perbandingan.

Ada LIMA jalur keluar yang semuanya harus membersihkan flag:

1. aksi di dalam modal berhasil (mis. "Jalankan", "Batalkan");
2. tombol Tutup;
3. penutupan bawaan — tombol X, Esc, klik di luar. Ini yang paling sering
   terlewat: bawaan ``st.dialog`` adalah ``on_dismiss="ignore"``, artinya modal
   hanya tertutup di peramban sementara flagnya tetap hidup;
4. berpindah halaman (ditangani ``ui/components/page_flags``, yang membaca
   :data:`DIALOG_KEYS` dari sini);
5. berpindah tampilan di dalam satu halaman (mis. katalog ↔ eksekusi).

Modul ini menyediakan pembuka/penutup/pemeriksa yang seragam, plus
:func:`dialog_decorator` yang selalu memasang ``on_dismiss`` sehingga jalur (3)
tidak mungkin terlupa.
"""
from __future__ import annotations

import streamlit as st

# Seluruh flag modal yang ada. Terdaftar di satu tempat supaya pembersihan
# saat berpindah halaman tidak pernah ketinggalan satu pun.
DETAIL_KEY = "_detail_id"                  # detail eksperimen (Progress & Status)
COMPARE_KEY = "_hist_compare_ids"          # perbandingan eksperimen
COMPAT_KEY = "_compat_check_type"          # uji kecocokan dataset (Run Experiment)
CATALOG_DETAIL_KEY = "_catalog_detail"     # detail research pipeline (katalog)
CATALOG_RUN_KEY = "_catalog_run"           # pilih dataset untuk menjalankan
AUTH_KEY = "_auth_dialog"                  # masuk/daftar

DIALOG_KEYS: tuple[str, ...] = (
    DETAIL_KEY, COMPARE_KEY, COMPAT_KEY,
    CATALOG_DETAIL_KEY, CATALOG_RUN_KEY, AUTH_KEY,
)

# Flag milik halaman Run Experiment — dibersihkan bersama saat pengguna
# berpindah antara tampilan katalog dan eksekusi.
RUN_VIEW_KEYS: tuple[str, ...] = (CATALOG_DETAIL_KEY, CATALOG_RUN_KEY, COMPAT_KEY)


def open_dialog(key: str, value=True) -> None:
    """Tandai sebuah modal harus terbuka.

    HANYA boleh dipanggil dari dalam blok ``if st.button(...)``. Memanggilnya di
    aliran render biasa akan menulis ulang flag pada setiap rerun, sehingga
    modalnya tidak akan pernah bisa ditutup.
    """
    st.session_state[key] = value


def close_dialog(*keys: str) -> None:
    """Bersihkan satu atau beberapa flag modal. Aman dipanggil berulang."""
    for key in keys:
        st.session_state.pop(key, None)


def close_all_dialogs() -> None:
    """Tutup seluruh modal — dipakai saat konteksnya berubah total."""
    close_dialog(*DIALOG_KEYS)


def dialog_state(key: str):
    """Nilai flag, atau None. Sengaja TANPA nilai bawaan: bawaan yang truthy
    akan membuat modal dianggap terbuka sejak awal."""
    return st.session_state.get(key)


def is_open(key: str) -> bool:
    return bool(dialog_state(key))


def dismiss_handler(key: str):
    """Callback ``on_dismiss``: membersihkan flag saat modal ditutup lewat
    tombol X / Esc / klik di luar."""
    def _on_dismiss() -> None:
        close_dialog(key)
    return _on_dismiss


def dialog_decorator(title: str, key: str, **kwargs):
    """``st.dialog`` yang SELALU membawa ``on_dismiss`` untuk flag-nya.

    Dipakai menggantikan ``st.dialog`` langsung supaya jalur penutupan bawaan
    tidak mungkin terlewat. Pada Streamlit yang belum punya ``on_dismiss``,
    dekorasinya tetap jalan tanpa parameter itu.
    """
    try:
        return st.dialog(title, on_dismiss=dismiss_handler(key), **kwargs)
    except TypeError:                       # pragma: no cover - Streamlit < 1.49
        return st.dialog(title, **kwargs)


def store_payload(key: str, payload) -> None:
    """Simpan data yang dipakai badan modal.

    Dibaca sekali saat modal DIBUKA, bukan pada setiap interaksi di dalamnya —
    tanpa ini, menekan apa pun di dalam modal akan memicu pembacaan berkas/DB
    ulang dan terasa tersendat.
    """
    st.session_state[f"{key}__payload"] = payload


def payload(key: str):
    """Data yang disimpan :func:`store_payload`, atau None."""
    return st.session_state.get(f"{key}__payload")


def clear_payload(key: str) -> None:
    st.session_state.pop(f"{key}__payload", None)
