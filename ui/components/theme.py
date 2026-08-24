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

# Hierarki jarak di dalam blok katalog. Nilai DALAM-blok sengaja lebih kecil
# daripada ANTAR-blok: itulah yang membuat dua blok penelitian terbaca sebagai
# dua kesatuan terpisah, bukan satu daftar panjang.
GAP_IN_BLOCK = "0.75rem"        # antar elemen di dalam satu blok penelitian
GAP_BETWEEN_BLOCKS = "2.75rem"  # antar blok penelitian

# Lebar tetap tombol aksi katalog — seragam di semua blok.
CATALOG_BTN_W = "9.5rem"

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

/* ── BUG: jejak lokasi terpotong tepi atas sidebar ─────────────────────
   Isi sidebar mulai terlalu rapat ke tepi atas, sehingga baris pertama
   (jejak lokasi) terpangkas. Ruang atas ditambah, dan barisnya sendiri diberi
   line-height + padding vertikal supaya `overflow:hidden` (yang dipakai untuk
   elipsis) memotong ke SAMPING, bukan memangkas tinggi hurufnya. */
[data-testid="stSidebarUserContent"] {{ padding-top: 1.5rem; }}
[data-testid="stSidebarHeader"] {{ padding-bottom: .35rem; }}

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

/* ── Pemilih algoritma: wadah lembut, pilihan aktif terangkat ──────────
   Wadahnya berlatar netral tipis; pilihan aktif tampil sebagai kartu yang
   terangkat di atasnya, sisanya redup tanpa latar. `flex-wrap` + `white-space:
   normal` menjaga enam algoritma HIKARI tetap terbaca — membungkus ke baris
   kedua, bukan terpotong. */
[data-testid="stSegmentedControl"] {{
    flex-wrap: wrap;
    gap: .25rem;
    padding: .25rem;
    border-radius: 10px;
    background: rgba(127,127,127,.09);
}}
[data-testid="stSegmentedControl"] button {{
    transition: background-color {HOVER_MS}ms ease, opacity {HOVER_MS}ms ease;
    cursor: pointer;
    border: none;
    background: transparent;
    border-radius: 8px;
    opacity: .62;                        /* pilihan lain: redup */
    white-space: normal;                 /* boleh membungkus, jangan terpotong */
}}
[data-testid="stSegmentedControl"] button:hover {{ opacity: .85; }}
/* Pilihan AKTIF: kartu terangkat — latar kontras + bayangan halus. */
[data-testid="stSegmentedControl"] button[aria-checked="true"] {{
    background: rgba(127,127,127,.26);
    opacity: 1;
    font-weight: {WEIGHT_STRONG};
    box-shadow: 0 1px 3px rgba(0,0,0,.14);
}}

/* ── Katalog: hierarki jarak & tombol seragam ──────────────────────────
   Jarak DI DALAM satu blok penelitian lebih kecil daripada jarak ANTAR blok,
   supaya pengelompokannya terbaca. Pemisah antar blok memakai jarak terbesar
   di halaman ini. */
.ids-cat-title {{ margin: 0 0 {GAP_IN_BLOCK} 0; }}
.ids-cat-short {{ margin: 0 0 {GAP_IN_BLOCK} 0; }}
.ids-cat-chips {{
    margin: 0 0 calc({GAP_IN_BLOCK} * 1.6) 0;
    gap: .45rem;                         /* chip tidak berdempetan */
    row-gap: .5rem;
}}
/* Pemisah antar blok penelitian — jarak paling lebar. */
.ids-cat-sep {{
    border: none; border-top: 1px solid rgba(127,127,127,.22);
    margin: {GAP_BETWEEN_BLOCKS} 0 calc({GAP_BETWEEN_BLOCKS} / 2) 0;
}}

/* Tombol aksi katalog: lebar & tinggi SERAGAM di semua blok, sejajar. */
[class*="st-key-cat_run_"] button, [class*="st-key-cat_detail_"] button {{
    width: {CATALOG_BTN_W};
    min-height: 2.3rem;
}}
/* Aksi sekunder lebih tenang daripada aksi utama. */
[class*="st-key-cat_detail_"] button {{
    background: transparent;
    border-color: rgba(127,127,127,.35);
    font-weight: {WEIGHT_NORMAL};
}}

/* ── Pemilih mode: daftar mengembang DI DALAM sidebar ──────────────────
   Bukan lapisan mengambang lagi, jadi tidak ada yang bisa menimpa konten.
   Barisnya dibuat ringkas di sini. */
[class*="st-key-auth_pick_"] button,
[class*="st-key-auth_logout"] button,
[class*="st-key-auth_mode_toggle"] button {{
    padding: .15rem .55rem;
    min-height: 0;
    font-size: {FONT_CAPTION};
    line-height: 1.6;
    justify-content: flex-start;
}}
[class*="st-key-auth_pick_"], [class*="st-key-auth_logout"] {{ margin: 0; }}
[class*="st-key-auth_pick_"] .stButton,
[class*="st-key-auth_logout"] .stButton {{ margin: .1rem 0; }}

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
/* Popover masih dipakai di halaman lain (mis. pemilih kolom & filter di
   Progress & Status); aturannya dipertahankan agar panelnya tetap ringkas.
   Pemilih mode TIDAK lagi memakainya — lihat catatan di ui/views/login.py. */
[data-testid="stPopoverBody"] {{
    min-width: 0 !important;
    width: max-content;
    max-width: {POPOVER_MAX_W};
    padding: .35rem;
}}
[data-testid="stPopoverBody"] .stButton > button {{
    padding: .1rem .5rem;
    font-size: {FONT_CAPTION};
    min-height: 0;
    line-height: 1.5;
    white-space: nowrap;
    width: 100%;
    justify-content: flex-start;
}}
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
