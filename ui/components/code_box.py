"""Kotak sunting skrip yang MEWARNAI token selagi diketik.

`st.text_area` mengembalikan teks biasa dan tidak dapat mewarnai apa pun, jadi
permukaan mengetiknya selalu polos. Di sini dipakai `streamlit-code-editor`
(Ace, pintasan papan tik VS Code) supaya kode berwarna sejak huruf pertama,
bukan hanya saat dibaca.

Ada DUA hal yang tidak boleh dilewatkan tentang komponen itu, dan keduanya
gagal DIAM-DIAM kalau diabaikan:

1. **Yang dikembalikannya kamus, bukan teks.** Bentuknya
   ``{"id", "type", "lang", "text", "selected", "cursor"}``. Kode pemanggil
   yang mengira isinya untai akan menyimpan kamus itu apa adanya ke suntingan
   tertunda, lalu menuliskannya sebagai isi berkas.
2. **Render pertama mengembalikan teks KOSONG.** Selama pengguna belum
   mengetik apa pun, ``text`` berisi untai kosong sementara ``type`` juga
   kosong. Membaca ``text`` mentah-mentah berarti berkasnya tampak terhapus
   begitu layar dibuka. Yang membedakan "belum ada jawaban" dari "isinya
   memang dikosongkan pengguna" adalah ``type``, bukan panjang ``text``.

Keduanya dibereskan di `source_editor`, sekali, supaya tidak ada pemanggil
yang perlu mengingatnya.

**Cadangan.** Komponen ini pihak ketiga dan dapat gagal dimuat: wheel-nya tidak
terpasang, atau versinya tidak cocok dengan Streamlit yang sedang berjalan.
Kalau itu terjadi, yang boleh terjadi hanyalah kehilangan WARNA, bukan
kehilangan halaman peninjauan. Karena itu ada jalur cadangan `st.text_area`
yang isinya tetap dapat disunting dan disimpan seperti biasa.
"""
from __future__ import annotations

import streamlit as st

#: Komponen editor, atau None kalau paketnya tidak dapat dimuat. Diambil
#: SEKALI saat modul ini diimpor; kegagalannya tidak boleh menjatuhkan halaman.
try:  # pragma: no cover - cabangnya bergantung pada lingkungan pemasangan
    from code_editor import code_editor as _code_editor
except Exception:  # pragma: no cover
    _code_editor = None

#: Tinggi kotak dalam BARIS, bukan piksel: itulah satuan yang dipakai Ace.
DEFAULT_LINES = 24

#: Kapan editor mengirim balik isinya. "debounce" mengirim sesudah jeda
#: mengetik, "blur" saat kotaknya ditinggalkan. Tanpa keduanya, isinya hanya
#: terkirim ketika sebuah tombol di dalam editor ditekan, dan tombol "Simpan
#: suntingan" di luar editor akan selalu membaca isi yang tertinggal satu
#: langkah.
RESPONSE_MODE = ["debounce", "blur"]


def editor_available() -> bool:
    """Apakah editor berwarna dapat dipakai pada pemasangan ini."""
    return _code_editor is not None


def _from_response(respons, semula: str) -> str:
    """Teks yang berlaku dari satu jawaban editor.

    `semula` dipakai selama editor BELUM menjawab. Yang menentukan itu adalah
    `type`: pada render pertama ia kosong, dan `text` yang juga kosong di sana
    bukan berarti berkasnya dikosongkan.
    """
    if not isinstance(respons, dict) or not respons.get("type"):
        return semula
    return respons.get("text") or ""


def current_text(key: str, semula: str) -> str:
    """Isi kotak bernama `key` apa adanya, dari lapis mana pun yang dipakai.

    Dipakai kode yang membaca kotak dari LUAR gambarannya, misalnya saat
    berpindah berkas dan isi kotak yang ditinggalkan perlu diselamatkan.
    Nilainya dapat berupa untai (jalur cadangan) atau kamus (jalur editor),
    dan pemanggilnya tidak perlu tahu yang mana.
    """
    nilai = st.session_state.get(key)
    if nilai is None:
        return semula
    if isinstance(nilai, dict):
        return _from_response(nilai, semula)
    return str(nilai)


def source_editor(value: str, *, key: str, label: str,
                  lines: int = DEFAULT_LINES) -> str:
    """Gambar kotak sunting skrip dan kembalikan isinya yang BERLAKU.

    `label` tidak pernah terlihat: nama berkasnya sudah disebut di atas kotak.
    Ia tetap diisi demi pembaca layar pada jalur cadangan.
    """
    if _code_editor is None:
        st.markdown('<span class="ids-code-editor"></span>',
                    unsafe_allow_html=True)
        return st.text_area(label, value=value, height=lines * 21, key=key,
                            label_visibility="collapsed")

    respons = _code_editor(
        value, lang="python", theme="default", shortcuts="vscode",
        height=lines, key=key, response_mode=RESPONSE_MODE,
        # Baris panjang MENGGULIR, tidak dilipat: baris yang dilipat menggeser
        # isi ke baris berikutnya, sehingga nomor baris pada temuan validator
        # tidak lagi berpadanan dengan apa yang terlihat.
        options={"wrap": False, "showLineNumbers": True})
    return _from_response(respons, value)
