"""
Gaya bersama seluruh aplikasi — ditulis SEKALI di sini, disuntikkan sekali dari
``ui/app.py``, dipakai ulang semua halaman.

Isinya empat hal:

1. **Empat tingkat ukuran teks** dan tidak lebih: judul halaman → judul bagian →
   teks isi → keterangan. Ukurannya dinaikkan dari bawaan Streamlit yang terlalu
   kecil untuk keterangan, sehingga catatan faktual tetap nyaman dibaca.
2. **Umpan balik sorot** untuk elemen yang BENAR-BENAR dapat diklik. Tombol yang
   dinonaktifkan dan elemen biasa sengaja tidak diberi efek apa pun — sorot pada
   sesuatu yang tidak dapat ditekan justru menyesatkan.
3. **Gaya kartu** dua panel yang dipakai halaman kontribusi.
4. **Perataan**: satu garis kiri untuk isi halaman, dan angka rata kanan di
   tabel.

**Aman lintas tema.** Semua warna di sini transparan (``rgba`` beralfa rendah)
atau mengikuti ``currentColor``/``var(--primary-color)`` — tidak ada nilai heksa
yang bisa menjadi tak terbaca saat pengguna berpindah tema terang/gelap.

**Menghormati pengurangan gerak.** Seluruh transisi dimatikan pada
``prefers-reduced-motion: reduce``.
"""
from __future__ import annotations

import streamlit as st

# Empat tingkat ukuran teks — satu-satunya skala yang dipakai aplikasi.
FONT_SECTION = "1.05rem"        # judul bagian
FONT_BODY = "0.95rem"           # teks isi
FONT_CAPTION = "0.84rem"        # keterangan (dinaikkan dari bawaan ±0.75rem)

# Dua bobot saja.
WEIGHT_NORMAL = "400"
WEIGHT_STRONG = "600"

# Lebar maksimum panel pemilih mode. Sidebar Streamlit ±21rem, jadi nilai ini
# menjamin panelnya lebih sempit daripada blok mode yang memicunya.
POPOVER_MAX_W = "13rem"

# Jarak vertikal. Dua nilai saja: antar elemen di dalam bagian, dan antar
# bagian besar. Sengaja LEBIH LEBAR daripada bawaan Streamlit.
GAP_ELEMENT = "1rem"
GAP_SECTION = "2rem"

# Transisi sorot: cukup terasa, tidak sampai mengganggu.
HOVER_MS = 150

# Rona latar kartu & sorot. Netral transparan → lembut di kedua tema.
TINT_NEUTRAL = "rgba(127,127,127,.07)"
TINT_HOVER = "rgba(127,127,127,.14)"

_CSS = f"""
<style>
/* ── Ruang napas: jarak LEGA, bukan rapat ──────────────────────────────
   Perapatan sebelumnya membuat halaman terasa sesak. Yang dipotong seharusnya
   JUMLAH KATA, bukan jaraknya — jadi nilai di bawah justru memperlebar:
   sedikit kata, banyak ruang. Jarak terbesar ada di pemisah antar-bagian,
   supaya tiap bagian terbaca sebagai kelompok tersendiri. */
section.main .block-container {{ padding-top: 2.6rem; }}

/* Jarak antar elemen dalam satu bagian — lapang, tidak menempel. */
[data-testid="stVerticalBlock"] {{ gap: {GAP_ELEMENT}; }}

/* Pemisah antar-bagian besar: jarak paling lebar di halaman. */
hr, [data-testid="stDivider"] {{ margin: {GAP_SECTION} 0; }}

/* Judul bagian: bernapas di atasnya, dekat dengan isinya sendiri. */
h2, h3 {{ margin-top: {GAP_SECTION}; margin-bottom: .6rem; }}
h3 {{ font-size: {FONT_SECTION}; font-weight: {WEIGHT_STRONG}; }}

/* Ruang di sekitar tombol & kelompok tombol. */
.stButton, .stDownloadButton {{ margin: .35rem 0; }}
[data-testid="stHorizontalBlock"] {{ gap: 1rem; }}

/* Expander & panel: ruang di sekelilingnya. */
[data-testid="stExpander"] details {{ margin: .6rem 0; }}

/* ── Keterbacaan: keterangan tidak lagi sekecil bawaannya ──────────────── */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
    font-size: {FONT_CAPTION};
    line-height: 1.55;
    opacity: .78;                       /* cukup redup untuk sekunder, tetap terbaca */
}}
/* Teks isi: ukuran tetap & lebar dibatasi agar nyaman dibaca. */
[data-testid="stMarkdownContainer"] p {{
    font-size: {FONT_BODY};
    max-width: 78ch;
}}

/* ── Tabel: teks rata kiri, angka rata kanan ───────────────────────────── */
[data-testid="stTable"] td, [data-testid="stTable"] th {{ text-align: left; }}
.ids-num, td.ids-num {{ text-align: right; font-variant-numeric: tabular-nums; }}

/* ── Sorot: HANYA pada yang dapat diklik ───────────────────────────────── */
.stButton > button:not(:disabled),
.stDownloadButton > button:not(:disabled),
[data-testid="stPopover"] > button:not(:disabled) {{
    transition: background-color {HOVER_MS}ms ease, border-color {HOVER_MS}ms ease;
    cursor: pointer;
}}
.stButton > button:not(:disabled):hover,
.stDownloadButton > button:not(:disabled):hover,
[data-testid="stPopover"] > button:not(:disabled):hover {{
    background-color: {TINT_HOVER};
    border-color: var(--primary-color, currentColor);
}}
/* Yang dinonaktifkan tidak bereaksi sama sekali. */
.stButton > button:disabled,
.stDownloadButton > button:disabled {{
    cursor: not-allowed;
    transition: none;
}}
.stButton > button:disabled:hover {{ background-color: inherit; }}

/* Chip & baris yang dapat dipilih. */
.ids-clickable {{
    transition: background-color {HOVER_MS}ms ease;
    cursor: pointer;
}}
.ids-clickable:hover {{ background-color: {TINT_HOVER}; }}

/* ── Kartu dua panel ───────────────────────────────────────────────────── */
.ids-card {{
    border-radius: 14px; overflow: hidden; margin-bottom: .4rem;
    background: {TINT_NEUTRAL};
}}
.ids-card-art {{ display: flex; align-items: center; justify-content: center; }}
.ids-card-art svg {{ width: 76px; height: 76px; }}
.ids-card-body {{ padding: .7rem .9rem .35rem; }}
.ids-card-title {{
    font-size: {FONT_SECTION}; font-weight: {WEIGHT_STRONG}; margin-bottom: .2rem;
}}
.ids-card-text {{ font-size: {FONT_CAPTION}; opacity: .78; line-height: 1.55; }}
.ids-card-note {{
    font-size: {FONT_CAPTION}; opacity: .78; line-height: 1.5;
    margin: .15rem 0 .45rem;
}}
.ids-card-badge {{
    display: inline-block; font-size: {FONT_CAPTION}; font-weight: {WEIGHT_STRONG};
    padding: .05rem .5rem; border-radius: 999px; margin-left: .35rem;
    border: 1px solid var(--primary-color, currentColor); opacity: .85;
    vertical-align: middle;
}}

/* ── Pemilih algoritma: wadah lembut, pilihan aktif terangkat ──────────── */
[data-testid="stSegmentedControl"] {{ flex-wrap: wrap; }}
[data-testid="stSegmentedControl"] button {{
    transition: background-color {HOVER_MS}ms ease;
    cursor: pointer;
}}

/* ── Blok mode menempel di DASAR sidebar ───────────────────────────────
   PERINGATAN VERSI: dua selektor di bawah bergantung pada struktur internal
   Streamlit (data-testid). Diperiksa terhadap Streamlit 1.59.2 — bila versinya
   dinaikkan, periksa ulang bahwa `stSidebarUserContent` dan `stVerticalBlock`
   masih ada dan masih bersarang seperti ini.

   Percobaan sebelumnya GAGAL karena flex dipasang pada stSidebarUserContent
   saja. Streamlit menaruh SEMUA elemen sidebar di dalam satu stVerticalBlock
   di dalamnya, jadi wadah flex itu hanya punya satu anak dan pengatur jarak di
   dalam blok tidak pernah memuai. Yang benar adalah menjadikan BLOK ITU
   sendiri kolom fleksibel — di situlah elemen-elemen sidebar bersaudara. */
[data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"] {{
    display: flex;
    flex-direction: column;
    min-height: calc(100vh - 7rem);
}}
/* Anak mana pun yang MEMUAT jangkar didorong ke dasar. Memakai `:has()` agar
   tidak bergantung pada testid pembungkus st.container() — apa pun bentuk
   pembungkusnya, yang memuat jangkar itulah yang terdorong. */
[data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"]
    > *:has(.ids-mode-anchor) {{
    margin-top: auto;
}}
.ids-mode-anchor {{ display: none; }}

/* ── Pemilih mode di sidebar: daftar pilihan yang ringkas ──────────────── */
/* Panel selebar ISINYA, dibatasi tegas — bukan selebar sidebar. */
[data-testid="stPopoverBody"] {{
    min-width: 0 !important;
    width: max-content;
    max-width: {POPOVER_MAX_W};
    padding: .35rem;
}}
/* Baris pilihan: satu baris teks, padding vertikal tipis. */
[data-testid="stPopoverBody"] .stButton > button {{
    padding: .1rem .5rem;
    font-size: {FONT_CAPTION};
    min-height: 0;
    line-height: 1.5;
    white-space: nowrap;
    width: 100%;
    justify-content: flex-start;
}}
/* Jarak antar pilihan dirapatkan HANYA di sini — daftar pendek memang harus
   padat; jarak lega berlaku untuk isi halaman, bukan untuk menu ini. */
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] {{ gap: .1rem; }}
[data-testid="stPopoverBody"] [data-testid="stElementContainer"] {{ margin: 0; }}

@media (prefers-reduced-motion: reduce) {{
    .stButton > button, .stDownloadButton > button,
    [data-testid="stPopover"] > button, .ids-clickable,
    [data-testid="stSegmentedControl"] button {{
        transition: none !important;
    }}
}}
</style>
"""


def inject() -> None:
    """Sisipkan stylesheet bersama. Dipanggil SEKALI dari ui/app.py.

    Streamlit membangun ulang halaman setiap rerun, jadi ini memang dijalankan
    tiap kali — yang penting hanya ada SATU tempat definisinya, bukan salinan
    yang tersebar di tiap berkas view.
    """
    st.markdown(_CSS, unsafe_allow_html=True)


def stylesheet() -> str:
    """Isi stylesheet — dipakai test untuk memeriksa aturannya."""
    return _CSS
