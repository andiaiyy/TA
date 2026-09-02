"""
Pengalih bahasa di sidebar.

**Bentuk: segmented control dua pilihan (ID / EN).** Dua bahasa adalah pilihan
yang sangat kecil dan saling meniadakan, jadi keduanya layak tampil sekaligus —
sekali klik, tanpa membuka daftar. Sebuah ``selectbox`` akan memakan dua
interaksi untuk memilih dari dua kemungkinan, dan tingginya sama saja.

**Posisi: paling bawah, DI DALAM blok identitas, tepat di atas pemilih mode.**
Urutan sidebar yang sudah ada adalah navigasi → progres → identitas. Bahasa
bukan navigasi (ia tidak memindahkan halaman) dan bukan progres; ia setelan
pribadi tampilan — golongan yang sama dengan "saya masuk sebagai siapa".
Menaruhnya di blok identitas membuat semua setelan diri berkumpul di satu sudut,
dan blok itu memang sudah terdorong ke dasar sidebar.

**Berpindah bahasa tidak mengganggu apa pun.** Yang ditulis hanya satu kunci
``session_state``; halaman aktif, pilihan dataset/pipeline, flag dialog, dan
pemantauan eksperimen tidak disentuh. Perpindahannya memakai ``on_change``,
sehingga Streamlit menjalankan ulang skrip SEKALI dengan sendirinya — tidak ada
``st.rerun()`` tambahan yang akan menjadi rerun kedua untuk satu aksi.
"""
from __future__ import annotations

import streamlit as st

from ui.i18n import LANGUAGES, current_lang, t
from ui.i18n.core import LANG_KEY

#: Kunci widget. Berbeda dari :data:`ui.i18n.core.LANG_KEY` supaya nilai widget
#: dan keadaan bahasa tidak menjadi dua sumber kebenaran untuk satu kunci —
#: kekeliruan yang persis pernah membuat pemilih mode berkedip.
WIDGET_KEY = "lang_pick"


def _apply() -> None:
    """Salin pilihan widget ke keadaan bahasa. Dipanggil sebagai ``on_change``."""
    chosen = st.session_state.get(WIDGET_KEY)
    if chosen in LANGUAGES:
        st.session_state[LANG_KEY] = chosen


def render_language_switch() -> None:
    """Dua pilihan berdampingan di sidebar. Tersedia untuk SEMUA pengguna.

    Tidak ada pemeriksaan izin di sini dan memang tidak boleh ada: bahasa
    antarmuka bukan hak istimewa, dan pengunjung yang belum masuk justru yang
    paling mungkin membutuhkannya.
    """
    current = current_lang()
    # Nilai widget disamakan dengan bahasa nyata SEBELUM widget dibuat — satu
    # saat yang dibolehkan untuk menulis nilai widget.
    if st.session_state.get(WIDGET_KEY) not in LANGUAGES:
        st.session_state[WIDGET_KEY] = current

    st.segmented_control(
        t("sidebar.language_title"),
        options=list(LANGUAGES),
        format_func=lambda code: LANGUAGES[code],
        key=WIDGET_KEY,
        on_change=_apply,
        label_visibility="collapsed",
        help=t("lang.help"),
    )
