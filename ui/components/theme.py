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

# Ukuran ANGKA pada kotak ringkasan. Ini BUKAN tingkat teks kelima: tidak ada
# kalimat yang memakainya — hanya angka statistik di dalam sel, yang memang
# harus terbaca sekilas dan terpisah jelas dari labelnya. Dinamai supaya
# perkecualiannya eksplisit, bukan angka lepas di tengah CSS.
FONT_DISPLAY = "1.6rem"

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

# Lebar maksimum satu kartu katalog. Pada layar lebar, kartu yang membentang
# sampai tepi membuat barisnya terlalu panjang untuk dibaca nyaman.
CARD_MAX_W = "46rem"

# Lebar MINIMUM satu sel angka. Kisi `auto-fit` memakai nilai ini untuk
# memutuskan berapa sel yang muat sebaris — itulah yang membuat kotak ringkasan
# berkurang kolomnya di layar sempit alih-alih memampat.
COUNT_CELL_MIN = "8rem"

# Ambang "sempit": di bawah ini susunan berkolom menumpuk menjadi vertikal.
# Satuan rem, bukan piksel tetap, supaya ikut skala huruf pengguna.
STACK_WIDTH = "40rem"

# Lebar minimum tabel perbandingan sebelum wadahnya menggulir mendatar.
CMP_MIN_W = "34rem"

# Testid tata letak Streamlit. Seperti SEG_GROUP di atas, nilainya diambil dari
# bundel frontend yang terpasang dan dijaga test — bukan ditebak.
COL_ROW = "stHorizontalBlock"
COL_ONE = "stColumn"
DATAFRAME = "stDataFrame"
MAIN_BLOCK = "stMainBlockContainer"

# Awalan kunci container kartu katalog. Didefinisikan DI SINI karena theme
# adalah lapis dasar; modul katalog mengimpornya dari sini, bukan sebaliknya,
# sehingga CSS dan kode tidak mungkin memakai awalan yang berbeda.
CARD_KEY_PREFIX = "cat_card_"

# Transisi sorot: cukup terasa, tidak sampai mengganggu.
HOVER_MS = 150

# ── Nama testid segmented control (st.segmented_control) ──────────────────
# Ini BUKAN pilihan gaya, melainkan fakta tentang DOM Streamlit yang terpasang.
# `st.segmented_control` dirender sebagai satu ButtonGroup, dan tombolnya
# memakai testid berpola `stBaseButton-<kind>`:
#
#   wadah          : stButtonGroup
#   tombol biasa   : stBaseButton-segmented_control
#   tombol terpilih: stBaseButton-segmented_controlActive
#
# Nilai-nilai ini diambil dari berkas frontend yang benar-benar terpasang
# (`streamlit/static/static/js/ButtonGroup.*.js` dan `BaseButton.*.js`).
# Sebelumnya CSS menyasar `stSegmentedControl` — nama yang tidak ada di DOM —
# sehingga gaya wadah/kartu terangkat tidak pernah berlaku. Ada test yang
# membandingkan konstanta di bawah dengan isi berkas frontend, jadi bila versi
# Streamlit berikutnya mengganti namanya, test itu gagal alih-alih gayanya
# hilang tanpa suara.
SEG_GROUP = "stButtonGroup"
SEG_ITEM = "stBaseButton-segmented_control"
SEG_ITEM_ACTIVE = "stBaseButton-segmented_controlActive"

# Daftar dropdown `st.selectbox`. Sama seperti konstanta di atas: nama NYATA
# dari frontend terpasang, bukan tebakan.
DROPDOWN_ID = "stSelectboxVirtualDropdown"
SELECT_ID = "stSelectbox"

# Kunci widget pemilih dataset di halaman Run Experiment. Streamlit menempelkan
# kelas `st-key-<key>` pada wadah widget ber-key, jadi ini cara MENYASAR SATU
# widget tanpa menyeret dropdown lain (mis. pemilih mode di sidebar) ikut
# membesar. Pola kelasnya juga diverifikasi terhadap bundel terpasang.
DATASET_SELECT_KEY = "dataset_select"
DATASET_SELECT_SCOPE = f"st-key-{DATASET_SELECT_KEY}"

# Tinggi kontrol pemilih dataset: nyaman ditekan & dibaca, tetapi tidak sampai
# mengubah tinggi baris elemen di sekitarnya. Ukuran TEKS-nya memakai
# `FONT_BODY` — aplikasi ini hanya mengenal empat tingkat ukuran teks, dan
# menambah tingkat kelima justru merusak konsistensi yang sedang dijaga.
SELECT_BIG_H = "3rem"

# Kelas penanda wadah isi bagian (lihat ui/components/sections.py).
SECTION_BODY_CLASS = "ids-section-body"
ST_VERSION = st.__version__

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
   PENTING — nama testid. `st.segmented_control` TIDAK merender testid bernama
   "stSegmented" + "Control" (nama itu sengaja tidak ditulis utuh di sini supaya
   tidak ada test yang lolos hanya karena menemukannya di komentar). Pada
   Streamlit {ST_VERSION} yang terpasang, widget ini adalah satu ButtonGroup:

       wadah  -> [data-testid="{SEG_GROUP}"]
       tombol -> [data-testid="{SEG_ITEM}"]            (tidak terpilih)
       tombol -> [data-testid="{SEG_ITEM_ACTIVE}"]     (terpilih)

   Aturan sebelumnya menyasar nama lama itu + `button[aria-checked]` saja —
   keduanya tidak ada di DOM, jadi TIDAK ADA yang tergaya dan widget tampil
   dengan gaya bawaan Streamlit. Nama di atas diambil dari berkas frontend yang
   benar-benar terpasang (`static/static/js/ButtonGroup.*.js` dan
   `BaseButton.*.js`), dan dijaga oleh test.

   `flex-wrap` + `white-space: normal` menjaga enam algoritma HIKARI tetap
   terbaca — membungkus ke baris kedua, bukan terpotong. */
[data-testid="{SEG_GROUP}"] {{
    flex-wrap: wrap;
    gap: .25rem;
    padding: .25rem;
    border-radius: 10px;
    background: rgba(127,127,127,.09);
    width: fit-content;
    max-width: 100%;
}}
[data-testid="{SEG_GROUP}"] button {{
    transition: background-color {HOVER_MS}ms ease, opacity {HOVER_MS}ms ease;
    cursor: pointer;
    border: none;
    background: transparent;
    border-radius: 8px;
    opacity: .62;                        /* pilihan lain: redup */
    white-space: normal;                 /* boleh membungkus, jangan terpotong */
    height: auto;
    min-height: 2rem;
}}
[data-testid="{SEG_GROUP}"] button:hover {{ opacity: .85; }}
/* Pilihan AKTIF: kartu terangkat — latar kontras + bayangan halus.
   Dua penyasar dipakai bersama: testid tombol aktif (yang benar pada versi
   terpasang) DAN aria-checked, supaya gayanya tidak hilang bila versi
   Streamlit berikutnya mengganti salah satunya. */
[data-testid="{SEG_GROUP}"] [data-testid="{SEG_ITEM_ACTIVE}"],
[data-testid="{SEG_GROUP}"] button[aria-checked="true"] {{
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
/* ── Kartu katalog ─────────────────────────────────────────────────────
   Tiap research pipeline berada dalam WADAH BERKOTAK, bukan sekadar dipisah
   garis. Kaitannya adalah kelas `st-key-<key>` yang ditambahkan Streamlit pada
   container berkunci (lihat pipeline_catalog.card_key) — bukan testid tebakan.

   Hierarki jaraknya: jarak DI DALAM kartu ({GAP_IN_BLOCK}) jauh lebih kecil
   daripada jarak ANTAR kartu ({GAP_BETWEEN_BLOCKS}), sehingga satu kartu
   terbaca sebagai satu kesatuan. */
[class*="st-key-{CARD_KEY_PREFIX}"] {{
    border-radius: 12px;
    background: rgba(127,127,127,.05);   /* sedikit beda dari latar halaman */
    padding: calc({GAP_IN_BLOCK} * 1.2);
    /* Jarak ANTAR kartu — lebih besar daripada jarak di dalamnya. */
    margin-bottom: {GAP_BETWEEN_BLOCKS};
    /* Teks tetap nyaman dibaca pada layar lebar. */
    max-width: {CARD_MAX_W};
    transition: background-color {HOVER_MS}ms ease,
                border-color {HOVER_MS}ms ease;
}}
/* Sorot HALUS saat kursor melintas: latar & garis menguat sedikit, tanpa
   gerakan atau bayangan. */
[class*="st-key-{CARD_KEY_PREFIX}"]:hover {{
    background: rgba(127,127,127,.10);
    border-color: rgba(127,127,127,.45);
}}
/* Elemen terakhir di dalam kartu tidak perlu jarak bawah tambahan. */
[class*="st-key-{CARD_KEY_PREFIX}"] [data-testid="stHorizontalBlock"] {{
    margin-bottom: 0;
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

/* ── Dropdown pemilih mode (sidebar, paling bawah) ─────────────────────
   Kontrolnya elemen sidebar biasa, jadi lebarnya sudah terkurung kolom
   sidebar. Daftarnya dirender ke lapisan mengambang — baseui mengunci
   lebarnya ke lebar kontrol pemicu, dan aturan di bawah mengekangnya sekali
   lagi supaya TIDAK PERNAH melebihi lebar blok mode walau lapisan itu
   dipindahkan ke `document.body`.

   Nama testid `{DROPDOWN_ID}` diambil dari berkas frontend Streamlit yang
   benar-benar terpasang dan dijaga test — pelajaran dari gaya segmented
   control yang dulu tidak pernah berlaku karena namanya ditebak. */
[data-testid="stSidebar"] [data-baseweb="select"] {{
    max-width: {POPOVER_MAX_W};          /* tidak melebihi lebar blok mode */
}}
[data-testid="stSidebar"] [data-baseweb="select"] > div {{
    min-height: 2.1rem;                  /* baris kecil, bukan kontrol tinggi */
    font-size: {FONT_CAPTION};
}}

/* ── Daftar pilihan (lapisan mengambang) ───────────────────────────────
   TIDAK ada `max-width` di sini. Sebelumnya ada, dan itulah sebab dropdown
   pemilihan dataset ikut menyempit: aturannya berlaku GLOBAL sementara daftar
   ini dirender ke `document.body`, sehingga tidak mungkin dibedakan per
   halaman lewat penyasar keturunan. Yang benar adalah mengekang KONTROL
   pemicunya (aturan sidebar di atas) — baseui menyamakan lebar daftar dengan
   lebar kontrolnya, jadi daftar mode tetap sempit dan daftar dataset ikut
   melebar bersama kontrolnya. */
[data-testid="{DROPDOWN_ID}"] li {{
    min-height: 0;
    /* Nama berkas panjang dipendekkan dengan elipsis, bukan dipotong keras.
       Nilai penuhnya tetap terbaca lewat tooltip bawaan baseui. */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}

/* ── Pemilih dataset (Run Experiment): kontrol BESAR ───────────────────
   Disasar lewat kelas `st-key-...` sehingga hanya widget ini yang membesar —
   pemilih mode di sidebar dan selectbox lain tidak ikut terpengaruh. */
.{DATASET_SELECT_SCOPE} [data-testid="{SELECT_ID}"],
.{DATASET_SELECT_SCOPE} [data-baseweb="select"] {{
    width: 100%;                         /* mengisi kolomnya, tidak menyempit */
    max-width: none;
}}
.{DATASET_SELECT_SCOPE} [data-baseweb="select"] > div {{
    min-height: {SELECT_BIG_H};          /* tinggi nyaman ditekan & dibaca */
    font-size: {FONT_BODY};              /* naik dari bawaan Streamlit */
}}
.{DATASET_SELECT_SCOPE} label {{
    font-size: {FONT_BODY};              /* labelnya ikut terbaca */
}}

/* ── Pola BAKU judul bagian ────────────────────────────────────────────
   Didefinisikan SEKALI di sini dan dipakai lewat `ui/components/sections.py`.
   Sebelumnya tiap bagian mengatur dirinya sendiri, sehingga "Pilih algoritma"
   dan "Execute" tampil berbeda dari bagian di atasnya. Jarak ANTAR-bagian
   sengaja jauh lebih besar daripada jarak judul ke isinya, supaya tiap bagian
   terbaca sebagai satu kelompok. */
[data-testid="stHeading"] {{
    margin: {GAP_SECTION} 0 {GAP_IN_BLOCK} 0;
    text-align: left;
}}
/* Bagian pertama pada sebuah halaman tidak perlu jarak atas ganda. */
[data-testid="stMain"] [data-testid="stVerticalBlock"]
    > [data-testid="stElementContainer"]:first-child [data-testid="stHeading"] {{
    margin-top: 0;
}}
/* Wadah isi bagian: satu gaya kotak untuk seluruh halaman. */
.{SECTION_BODY_CLASS} {{
    margin-bottom: {GAP_IN_BLOCK};
}}

/* ── Pasangan label-nilai & baris angka ────────────────────────────────
   Dipakai mengisi kolom di samping sebuah kontrol dengan informasi yang MEMANG
   sudah dihitung di tempat lain. Ukurannya SAMA dengan teks isi — kepadatan
   datang dari susunannya, bukan dari mengecilkan huruf. */
.ids-facts {{
    width: 100%;
    border-collapse: collapse;
    font-size: {FONT_BODY};
}}
.ids-facts th, .ids-facts td {{
    padding: .22rem .1rem;
    vertical-align: top;
    text-align: left;                    /* perataan kiri, sama dgn kolom lain */
    border-bottom: 1px solid rgba(127,127,127,.16);
}}
.ids-facts .ids-fact-k {{
    width: 22%;                          /* dua pasang label-nilai per baris */
    padding-right: .5rem;
    font-weight: {WEIGHT_NORMAL};
    opacity: .72;
    overflow-wrap: anywhere;
}}
.ids-facts .ids-fact-v {{
    width: 28%;
    padding-right: {GAP_IN_BLOCK};
    font-weight: {WEIGHT_STRONG};
    overflow-wrap: anywhere;
}}
/* Sel terakhir tidak perlu jarak kanan tambahan. */
.ids-facts tr > .ids-fact-v:last-child {{ padding-right: .1rem; }}

/* ── Kotak ringkasan angka ─────────────────────────────────────────────
   Wadah berbatas berisi sel-sel angka. KISI dengan lebar minimum per sel,
   bukan lebar tetap: pada layar sempit jumlah kolomnya berkurang sendiri
   (tiga sel -> dua -> satu) alih-alih memampat sampai angkanya tak terbaca. */
.ids-counts {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax({COUNT_CELL_MIN}, 1fr));
    border: 1px solid rgba(127,127,127,.28);
    border-radius: 10px;
    background: rgba(127,127,127,.05);   /* sedikit beda dari latar halaman */
    overflow: hidden;                    /* sudut membulat ikut memotong sel */
    max-width: {CARD_MAX_W};
}}
.ids-count {{
    display: flex;
    flex-direction: column;
    padding: {GAP_IN_BLOCK};
    /* Pemisah TIPIS antar-sel. Dipasang di dua sisi lalu digeser keluar oleh
       `overflow: hidden` pada wadahnya, sehingga sel terakhir di tiap baris
       tidak menyisakan garis menggantung. */
    border-right: 1px solid rgba(127,127,127,.22);
    border-bottom: 1px solid rgba(127,127,127,.22);
    text-align: left;                    /* perataan SERAGAM: semua rata kiri */
}}
.ids-count-n {{
    font-size: {FONT_DISPLAY};           /* angka besar & tegas */
    font-weight: {WEIGHT_STRONG};
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    /* JARAK jelas antara angka dan labelnya — tidak menempel. */
    margin-bottom: .3rem;
}}
.ids-count-l {{ font-size: {FONT_CAPTION}; opacity: .72; line-height: 1.3; }}

/* Akar containment untuk `@container` di bawah. Tanpa ini, container query
   TIDAK PERNAH cocok — dan gagalnya tanpa suara. `inline-size` hanya
   membatasi arah mendatar, jadi tinggi konten tidak terpengaruh. */
[data-testid="{MAIN_BLOCK}"] {{ container-type: inline-size; }}

/* ── Adaptif terhadap lebar konten ─────────────────────────────────────
   Nama testid di bawah DIAMBIL dari bundel frontend yang benar-benar
   terpasang (streamlit/static/static/js/*.js) dan dikunci oleh test — bukan
   ditebak. Selektor yang salah gagal tanpa suara, dan itu sudah pernah
   terjadi di proyek ini pada segmented control.

   Ambangnya memakai lebar KONTAINER, bukan lebar layar, sehingga tata letak
   tetap benar saat sidebar dibuka maupun ditutup — sidebar mengubah lebar
   konten tanpa mengubah lebar layar. */
@container (max-width: {STACK_WIDTH}) {{
    /* Kolom MENUMPUK jadi vertikal, bukan memampat sampai teks terpotong. */
    [data-testid="{COL_ROW}"] {{ flex-wrap: wrap; }}
    [data-testid="{COL_ROW}"] > [data-testid="{COL_ONE}"] {{
        flex: 1 1 100%;
        min-width: 100%;
    }}
    /* Pasangan label-nilai jatuh ke satu pasang per baris. */
    .ids-facts .ids-fact-k, .ids-facts .ids-fact-v {{ width: auto; }}
}}
/* Cadangan untuk peramban tanpa dukungan container query: ambang layar. */
@media (max-width: {STACK_WIDTH}) {{
    [data-testid="{COL_ROW}"] {{ flex-wrap: wrap; }}
    [data-testid="{COL_ROW}"] > [data-testid="{COL_ONE}"] {{
        flex: 1 1 100%;
        min-width: 100%;
    }}
}}

/* Tabel & kerangka lebar: DIGULIR mendatar, bukan dipaksa masuk sampai
   kolomnya terpotong. */
[data-testid="{DATAFRAME}"] {{ max-width: 100%; }}
.ids-cmp-scroll, .ids-ph-wrap {{
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
}}
/* Tabel perbandingan punya lebar minimum supaya kolomnya tetap terbaca; bila
   tidak muat, wadahnya yang menggulir. */
.ids-cmp {{ min-width: {CMP_MIN_W}; }}

@media (prefers-reduced-motion: reduce) {{
    .stButton > button, .stDownloadButton > button,
    [data-testid="stPopover"] > button, .ids-clickable,
    [data-testid="{SEG_GROUP}"] button {{
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
