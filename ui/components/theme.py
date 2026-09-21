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

Ada SATU perkecualian, dan ia disengaja: tombol "Info" halaman kontribusi —
satu aturan yang melayani jalur unggah pipeline maupun tambah dataset. Alasan
aturan di atas adalah warna yang dipaku dapat kehilangan kontras terhadap latar
yang berubah; tombol itu menetapkan latar DAN teksnya sekaligus (hitam/putih)
plus tepi semi-transparan, sehingga kontrasnya milik tombol itu sendiri dan
tidak bergantung pada latar halaman. Perkecualian ini tidak boleh menjadi
preseden untuk warna heksa lepas.

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

# Padding kiri/kanan baris tabel pengguna. Dipakai DUA aturan sekaligus —
# baris berbingkai dan header yang tidak berbingkai — supaya kolom keduanya
# berdiri di trek yang sama. Nilainya MILIK KITA, bukan warisan padding
# kontainer Streamlit (`calc(1rem - 1px)`): satu sumber, jadi keduanya tidak
# mungkin berselisih, dan tidak ada ketergantungan pada konstanta internal
# Streamlit yang boleh berubah kapan saja.
USER_ROW_PAD = ".55rem"
#: Tinggi tombol di dalam baris tabel. Lebih pendek daripada tombol biasa:
#: tombol setinggi bawaan menaikkan tinggi seluruh barisnya.
ROW_BTN_H = "2.15rem"

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

# Jarak vertikal DI DALAM formulir kontribusi, dan hanya di sana. Halaman lain
# tetap memakai `GAP_ELEMENT` yang lapang: yang dirapatkan adalah formulir
# panjang berisi belasan ruas, tempat jarak selebar satu baris teks membuat
# separuh ruasnya jatuh di luar layar.
GAP_FORM = "0.55rem"
#: Tinggi seragam untuk kotak teks, pilihan, dan angka pada formulir itu.
INPUT_H = "2.5rem"
GAP_BETWEEN_BLOCKS = "2.75rem"  # antar blok penelitian

# Lebar tetap tombol aksi katalog — seragam di semua blok. Cukup untuk
# "Siapkan Eksperimen" dalam SATU baris: label yang membungkus membuat tombol
# ini lebih tinggi daripada "Detail" di sebelahnya, dan barisnya terlihat
# miring justru pada aksi utamanya.
CATALOG_BTN_W = "12rem"

# ── Tombol HITAM ─────────────────────────────────────────────────────────
# Awalan kunci widget yang digambar hitam. SATU daftar, satu aturan: dua
# tempat yang harus diingat untuk diubah bersama pasti berbeda sendiri suatu
# saat. Isinya dua kelompok, dan keduanya membawa janji yang sama — "ini akan
# membuka sesuatu", bukan "ini akan mengeksekusi sesuatu":
#
#   contrib_info_  tombol panduan halaman kontribusi
#   cat_run_       "Siapkan Eksperimen" pada tiap blok katalog
#   _catalog_run   "Siapkan Eksperimen" di dalam modal detail
#   _run_go        "Siapkan Eksperimen" di atas katalog
#   run_info       tombol detail di judul halaman Run Experiment
#
# Tombol yang BENAR-BENAR menjalankan eksperimen sengaja TIDAK ada di sini:
# ia tetap merah, karena warnanya ikut memberi tahu bahwa yang berikutnya
# terjadi memakan waktu dan menulis hasil.
#
# `idsdark_` bukan kunci tombol melainkan kunci WADAH yang membungkusnya,
# dipasang `dark_button_scope`. Itu yang membuat tombol BERGANTI-KEADAAN dapat
# hitam hanya pada salah satu keadaannya: tombol "Nonaktifkan"/"Aktifkan"
# adalah satu tombol dengan satu kunci, jadi kuncinya sendiri tidak dapat
# menceritakan keadaan mana yang sedang digambar.
DARK_BTN_SCOPES = ("contrib_info_", "cat_run_", "_catalog_run", "_run_go",
                   "run_info", "idsdark_")


def dark_button_scope(target, *, dark: bool, key: str):
    """Wadah bagi satu tombol; yang HITAM hanya bila ``dark``.

    Selalu mengembalikan wadah pada ``target`` yang sama — juga ketika tidak
    hitam — supaya tombol di dalamnya tetap jatuh di kolom yang sama dan tata
    letaknya tidak berubah mengikuti keadaan.

    Kunci TOMBOLNYA tidak disentuh. Itu disengaja: kunci tombol adalah
    identitas widget yang dipakai test dan keadaan sesi, dan mengubahnya
    menurut keadaan akan membuat satu tombol menjadi dua yang berganti-ganti.
    """
    return target.container(key=f"idsdark_{key}") if dark else target.container()


def _dark_btn_selector(akhiran: str) -> str:
    """Selektor gabungan untuk seluruh cakupan tombol hitam.

    BUKAN ``.stButton > button``: bentuk itu mengandaikan ada pembungkus
    `.stButton` tepat di antara wadah berkunci dan tombolnya — andaian yang
    ternyata tidak berlaku, sehingga aturan ini tidak pernah cocok dengan apa
    pun dan seluruh tombolnya tetap merah.

    BUKAN pula ``button`` polos. Cakupan di atas adalah AWALAN kunci, dan
    `contrib_info_` juga cocok dengan kunci kolom isian `contrib_info_metrics`,
    `contrib_info_anti`, `contrib_info_pre`, dan `contrib_info_params`. Ikon
    bantuan `help=` pada label kolom-kolom itu adalah `button` juga, sehingga
    aturan ini ikut mengecatnya: tanda tanya dalam lingkaran berubah menjadi
    kotak hitam. Sasarannya kini testid tombol Streamlit yang sesungguhnya —
    ikon bantuan bukan `stBaseButton`, jadi ia tidak lagi tersentuh.
    """
    return ",\n".join(
        f'[class*="st-key-{scope}"] [data-testid^="stBaseButton-"]{akhiran}'
        for scope in DARK_BTN_SCOPES)


DARK_BTN_BASE = _dark_btn_selector("")
DARK_BTN_HOVER = (_dark_btn_selector(":not(:disabled):hover") + ",\n"
                  + _dark_btn_selector(":not(:disabled):focus-visible"))
DARK_BTN_CHILD = _dark_btn_selector(" *")

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

# ── PROSA vs BLOK DATA ───────────────────────────────────────────────────
# Batas lebar baca HANYA berlaku untuk prosa (kalimat & paragraf penjelasan).
# Blok data — tabel, blok kode, tampilan perbandingan, daftar berkas, pasangan
# label-nilai, baris katalog, formulir — mengikuti lebar penuh kolomnya.
# `ch` mengikat batasnya pada lebar KARAKTER, jadi ia ikut skala huruf pengguna
# alih-alih terkunci pada piksel.
PROSE_W = "78ch"
#: Awalan kunci container penanda prosa (lihat `sections.prose`).
PROSE_KEY = "ids-prose-"

# Lebar minimum kolom teks diff sebelum wadahnya menggulir mendatar.
DIFF_MIN_W = "30rem"

# ── Tabel baku ───────────────────────────────────────────────────────────
# Tinggi baris, padding sel, dan tinggi maksimum wadah — SATU nilai untuk
# seluruh tabel, sehingga dua tabel di halaman yang sama tidak mungkin punya
# kepadatan yang berbeda. Semuanya rem, bukan piksel.
#: Garis pemisah baris tabel, dan rona latar header-nya. Dahulu keduanya
#: ditulis literal di beberapa aturan; dijadikan konstanta karena kini ada
#: pembaca KEDUA — tabel AgGrid, yang hidup di dalam iframe dan tidak dapat
#: dijangkau stylesheet ini sama sekali. Satu sumber nilai, dua konsumen; tanpa
#: ini keduanya pasti menyimpang suatu saat.
LINE_SOFT = "rgba(127,127,127,.22)"
HEAD_TINT = "rgba(127,127,127,.11)"

TABLE_ROW_H = "2.2rem"
TABLE_PAD = "0.38rem 0.5rem"
#: Wadah tabel menggulir setelah setinggi ini — daftar panjang tidak lagi
#: mendorong seluruh halaman ke bawah.
TABLE_MAX_H = "26rem"
#: Lebar minimum sebelum wadahnya menggulir mendatar.
TABLE_MIN_W = "34rem"

# Huruf monospace untuk kode & diff: lebar karakter seragam supaya baris yang
# sebanding benar-benar sejajar. Daftar cadangan, bukan satu nama font.
MONO_STACK = ('ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, '
              '"Liberation Mono", monospace')

# Testid tata letak Streamlit. Seperti SEG_GROUP di atas, nilainya diambil dari
# bundel frontend yang terpasang dan dijaga test — bukan ditebak.
COL_ROW = "stHorizontalBlock"
COL_ONE = "stColumn"
DATAFRAME = "stDataFrame"
MAIN_BLOCK = "stMainBlockContainer"

# Awalan kunci container kartu katalog. Didefinisikan DI SINI karena theme
# adalah lapis dasar; modul katalog mengimpornya dari sini, bukan sebaliknya,
# sehingga CSS dan kode tidak mungkin memakai awalan yang berbeda.
ROW_KEY_PREFIX = "cat_row_"

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
/* Teks isi: ukuran tetap. Lebar TIDAK dibatasi di sini.
   ── Kenapa batas lebarnya pindah ────────────────────────────────────────
   Dulu baris ini juga memuat `max-width: 78ch`, dan itu ATURAN UMUM: ia
   mengenai SETIAP paragraf di seluruh aplikasi. Akibatnya blok data yang
   kebetulan ditulis sebagai markdown — daftar berkas, baris label-nilai,
   keterangan di bawah tabel — ikut berhenti di ~3/4 lebar kolom dan terlihat
   seperti salah render, bukan seperti keputusan.

   Batas lebar kini HANYA melekat pada prosa, lewat penanda `.ids-prose`
   (lihat `sections.prose`). Blok data mengikuti lebar penuh kolomnya. */
[data-testid="stMarkdownContainer"] p {{ font-size: {FONT_BODY}; }}

/* PROSA: kalimat penjelasan & paragraf. Hanya di sinilah lebar dibatasi,
   supaya mata tidak menempuh baris yang terlalu panjang. Kaitannya kelas
   `st-key-<key>` pada container berkunci — hook yang sama dengan baris
   katalog, bukan testid tebakan. */
[class*="st-key-{PROSE_KEY}"] [data-testid="stMarkdownContainer"] p {{
    max-width: {PROSE_W};
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
/* Pil peran/penanda — SATU aturan untuk seluruh aplikasi. Namanya sengaja
   tidak menyebut "card": ia dipakai kartu kontribusi maupun tabel pengguna,
   dan kelas kedua yang isinya sama pasti menyimpang suatu saat. */
.ids-badge {{
    display: inline-block; font-size: {FONT_CAPTION}; font-weight: {WEIGHT_STRONG};
    padding: .05rem .5rem; border-radius: 999px; margin-left: .35rem;
    border: 1px solid var(--primary-color, currentColor); opacity: .85;
    vertical-align: middle;
    /* Pil adalah SATU label. "Research Admin" yang patah dua di kolom sempit
       berhenti menjadi pil — ia menjadi gumpalan dua baris yang menaikkan
       tinggi seluruh barisnya, sehingga baris-baris pada satu tabel tidak lagi
       setinggi sama. Yang benar: pil menolak patah, dan kolomnya yang
       dilebarkan sampai cukup (lihat `_USER_COLS`). */
    white-space: nowrap;
}}
/* Varian BERISI: bentuk yang sama, latar penuh, tanpa garis tepi. Latarnya
   datang INLINE dari pemanggil — pola yang sama dengan `tint` kartu — karena
   warnanya menandai KATEGORI (peran mana), dan kategori itu milik datanya,
   bukan milik stylesheet. Dipakai kolom Peran pada tabel pengguna, tempat dua
   peran harus terbedakan sekilas tanpa dibaca hurufnya. */
.ids-badge-solid {{
    border: none; opacity: 1; margin-left: 0;
}}

/* Baris kedua di bawah judul sebuah BARIS tabel: kontributor, tahun, lembaga.
   Ia keterangan, bukan isi — jadi ia lebih kecil dan redup daripada judulnya,
   dan itulah yang membuat judulnya terbaca lebih dulu. Dipakai tabel kelola
   research; kelasnya umum supaya tabel lain tidak perlu menirunya sendiri. */
.ids-row-sub {{
    display: block;
    font-size: {FONT_CAPTION};
    opacity: .62;
    line-height: 1.4;
    /* Nama panjang MELIPAT, tidak memotong barisnya. */
    overflow-wrap: anywhere;
}}

/* ── Baris tabel pengguna: rapat, dan sekolom dengan headernya ─────────
   PENTING — nama testid. Pada Streamlit {ST_VERSION} yang terpasang, kontainer
   berbingkai `st.container(border=True)` adalah `[data-testid="stVerticalBlock"]`
   yang membawa `padding: calc(1rem - 1px)`. TIDAK ADA
   `stVerticalBlockBorder` + `Wrapper` di versi ini — nama itu (sengaja tidak
   ditulis utuh supaya tidak ada test yang lolos hanya karena menemukannya di
   komentar) tidak muncul sama sekali di aset terpasang, jadi aturan yang
   menyasarnya tidak akan menggayai apa pun.

   Karena testid itu dipakai SETIAP blok vertikal — termasuk blok akar halaman
   — lingkupnya dikunci jangkar pada KEDALAMAN TETAP (`> .stElementContainer`).
   `:has()` bebas akan ikut cocok pada setiap nenek moyang barisnya dan
   mencabut padding seluruh halaman.

   Padding horizontalnya ditulis ulang, bukan diwarisi: header tidak berbingkai
   sehingga tidak berpadding, dan selisih itu menggeser tiap kolom dengan besar
   berbeda (±15px di kiri, mengecil ke kanan) — itulah kolom yang terbaca
   meleset dari judulnya. Kedua aturan memakai `USER_ROW_PAD` yang sama. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-user-row),
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-compat-row),
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-queue-row) {{
    padding: .3rem {USER_ROW_PAD};
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-user-head),
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-compat-head),
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-queue-head) {{
    padding-inline: {USER_ROW_PAD};
}}
/* Jangkarnya tidak boleh menyisakan jejak. Menyembunyikan span-nya saja tidak
   cukup: wadah elemennya tetap menjadi anak flex, dan `gap` kontainer masih
   menyisakan satu jarak setinggi 1rem di atas barisnya — justru menambah
   tinggi yang sedang dikurangi. Jadi wadahnya ikut dikeluarkan dari layout. */
div[data-testid="stVerticalBlock"] > .stElementContainer:has(.ids-user-row),
div[data-testid="stVerticalBlock"] > .stElementContainer:has(.ids-user-head),
div[data-testid="stVerticalBlock"] > .stElementContainer:has(.ids-compat-row),
div[data-testid="stVerticalBlock"] > .stElementContainer:has(.ids-compat-head),
div[data-testid="stVerticalBlock"] > .stElementContainer:has(.ids-queue-row),
div[data-testid="stVerticalBlock"] > .stElementContainer:has(.ids-queue-head) {{
    display: none;
}}

/* ── Kotak sunting skrip: chrome editor ────────────────────────────────
   `st.text_area` mengembalikan teks biasa kepada Python, dan justru itulah
   yang membuatnya dapat digerakkan test. Warna tokennya dibawa penyorot
   bawaan Streamlit di tab "Pratinjau" sebelahnya; yang diurus di sini hanya
   bentuk permukaan mengetiknya.

   Yang membedakan permukaan ini dari kotak teks biasa: huruf monospace,
   `tab-size` empat spasi seperti berkas pipeline-nya sendiri, dan baris
   panjang yang MENGGULIR alih-alih dilipat. Baris yang dilipat memindahkan
   isi ke baris berikutnya, sehingga nomor baris pada temuan validator tidak
   lagi berpadanan dengan apa yang terlihat.

   Warnanya tetap transparan (`rgba` beralfa rendah), mengikuti aturan aman
   lintas tema di kepala berkas ini. Latar gelap yang dipaku, seperti yang
   dipakai editor sungguhan, akan menjadi lubang hitam pada tema terang. */
.stElementContainer:has(.ids-code-editor) {{ display: none; }}
.stElementContainer:has(.ids-code-editor) + .stElementContainer textarea {{
    font-family: {MONO_STACK};
    font-size: {FONT_CAPTION};
    line-height: 1.5;
    tab-size: 4;
    white-space: pre;
    overflow-x: auto;
    background: rgba(127,127,127,.06);
    border: 1px solid rgba(127,127,127,.3);
}}

/* ── Formulir kontribusi: rapat, dan HANYA di sini ─────────────────────
   Aturan "ruang napas" di kepala berkas ini tetap berlaku untuk seluruh
   halaman lain, dan sebuah test menjaganya. Yang dikecualikan satu hal:
   formulir unggah yang memuat belasan ruas berurutan. Pada jarak selebar satu
   baris teks, separuh ruasnya jatuh di luar layar, dan pengisinya menggulir
   naik-turun hanya untuk memeriksa apa yang sudah ia isi.

   Lingkupnya dikunci jangkar `.ids-form-compact`, jadi tidak ada satu pun
   halaman lain yang ikut terapat tanpa diminta. */
.stElementContainer:has(.ids-form-compact) {{ display: none; }}

div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact),
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    [data-testid="stVerticalBlock"] {{
    gap: {GAP_FORM};
}}
/* Kolom berdampingan ikut dirapatkan mendatar, tetapi tidak sampai berdempet. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    [data-testid="{COL_ROW}"] {{
    gap: .75rem;
}}
/* Label MENEMPEL pada kotaknya sendiri. Label yang mengambang di tengah dua
   ruas membuat pembacanya menebak ia milik yang mana. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    label {{
    margin-bottom: .1rem;
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    label p {{
    margin-bottom: 0;
    line-height: 1.35;
}}
/* Tinggi SERAGAM untuk tiap jenis masukan: kotak teks, pilihan, dan angka
   yang berbeda tinggi membuat barisnya terlihat miring. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    .stTextInput input,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    .stNumberInput input,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    div[data-baseweb="select"] > div {{
    min-height: {INPUT_H};
}}
/* Kotak panjang: cukup untuk dibaca, tidak sampai mendominasi layar. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    textarea {{
    min-height: 4.5rem;
    line-height: 1.5;
}}
/* Judul sub-bagian di dalam formulir dekat dengan isinya sendiri, dan
   jaraknya ke bagian sebelumnya lebih kecil daripada di halaman lain. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    h2,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    h3 {{
    margin-top: {GAP_ELEMENT};
    margin-bottom: .25rem;
}}
/* Pemisah antar-bagian di dalam formulir: tetap ada sebagai pengelompok,
   tetapi tidak selebar pemisah antar-halaman. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    hr,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    [data-testid="stDivider"] {{
    margin: {GAP_ELEMENT} 0;
}}
/* Tombol tidak perlu ruang tambahan di formulir serapat ini. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-form-compact)
    .stButton {{
    margin: .1rem 0;
}}

/* ── Tombol di dalam baris pengguna: rapat, tidak meninggikan barisnya ──
   Dahulu kolom terakhir memuat dua tombol BERTUMPUK, jadi setiap baris
   setinggi dua tombol selebar kolom. Sekarang tindakan utamanya berdampingan
   dengan satu panel ringkas, dan tombolnya sendiri dirapatkan: tombol setinggi
   bawaan pada baris tabel membuat barisnya naik tanpa menambah apa pun yang
   dapat dibaca. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-user-row)
    .stButton button,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-user-row)
    [data-testid="stPopover"] button {{
    min-height: {ROW_BTN_H};
    padding: .1rem .55rem;
    font-size: {FONT_CAPTION};
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-user-row)
    .stButton {{
    margin: 0;
}}
/* Panel tindakan: isinya tombol penuh lebar, jadi ia tidak perlu selebar
   panel bawaan yang dipakai penyaring. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-user-row)
    [data-testid="stHorizontalBlock"] {{
    gap: .35rem;
}}

/* ── Halaman Progres & Status: ringan, rapat, tidak seperti lembar sebar ─
   Halaman ini dahulu terbaca berat karena tiga hal yang semuanya di luar
   tabelnya: judul sebesar judul bab, jarak antar-bagian selebar satu layar
   kecil, dan kotak keterangan biru pekat selebar halaman untuk satu kalimat.
   Tabelnya sendiri diatur terpisah lewat `custom_css` milik komponennya.

   Lingkupnya dikunci jangkar, jadi halaman lain tetap memakai skalanya
   sendiri. */
.stElementContainer:has(.ids-progress-page) {{ display: none; }}

div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    h1 {{
    /* UKURANNYA tidak diubah, dan itu disengaja: skala halaman ini empat
       tingkat, satu ukuran tambahan akan menjadi tingkat kelima, dan memakai
       ukuran angka statistik di sini akan mengaburkan arti ukuran itu. Yang
       dikurangi RUANG di sekelilingnya — itulah yang membuat judul terbaca
       memakan sepertiga layar, bukan besar hurufnya sendiri. */
    line-height: 1.15;
    padding-top: 0;
    padding-bottom: .2rem;
    margin-bottom: .1rem;
}}
/* Jarak antar-bagian: cukup untuk memisahkan, tidak sampai memutus. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    hr,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    [data-testid="stDivider"] {{
    margin: {GAP_ELEMENT} 0;
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    h2,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    h3 {{
    margin-top: {GAP_ELEMENT};
    margin-bottom: .35rem;
}}
/* Kotak keterangan: latar samar, bukan biru pekat selebar halaman. Warnanya
   tetap membawa arti, hanya kadarnya yang diturunkan. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    [data-testid="stAlert"] {{
    padding: .55rem .8rem;
    border-radius: .6rem;
    font-size: {FONT_CAPTION};
}}
/* Baris kontrol di atas tabel berdiri sebagai SATU baris alat: tingginya
   seragam dan jaraknya rapat, alih-alih empat kendali yang masing-masing
   terbaca seperti kartu tersendiri. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    [data-testid="{COL_ROW}"] {{
    gap: .5rem;
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    .stButton button,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    .stDownloadButton button,
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    [data-testid="stPopover"] button {{
    min-height: {ROW_BTN_H};
    font-size: {FONT_CAPTION};
    border-radius: .55rem;
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-progress-page)
    .stTextInput input {{
    min-height: {ROW_BTN_H};
    font-size: {FONT_CAPTION};
    border-radius: .55rem;
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
/* ── Daftar baris katalog ──────────────────────────────────────────────
   TIDAK ada wadah berkotak per research pipeline. Yang memisahkan satu baris
   dari baris berikutnya adalah GARIS TIPIS selebar penuh area konten plus
   hierarki jarak — bukan kotak.

   Kaitannya kelas `st-key-<key>` yang ditambahkan Streamlit pada container
   berkunci (lihat pipeline_catalog.row_key) — bukan testid tebakan.

   Hierarki jarak inilah yang membuat pengelompokan terbaca tanpa kotak:
   jarak DI DALAM baris rapat (lihat `.ids-cat-*` di pipeline_catalog),
   jarak ANTAR baris longgar ({GAP_SECTION} di atas & di bawah garis). */
[class*="st-key-{ROW_KEY_PREFIX}"] {{
    /* BARIS KATALOG = blok data: mengikuti lebar penuh kolomnya.
       Variabelnya tetap ada sebagai satu titik kendali untuk `.ids-cat-*`,
       tetapi nilainya kini `none`. Sebelumnya {CARD_MAX_W}, yang membuat
       judul, penjelasan, dan chip berhenti di ~3/4 lebar sementara garis
       pemisah di bawahnya membentang penuh — ketidakselarasan itulah yang
       terbaca sebagai kesalahan. Elipsis `.ids-cat-note` tetap bekerja: ia
       memotong pada lebar NYATA, jadi kolom yang lebih lebar menampilkan
       lebih banyak teks alih-alih memotong di titik yang sama. */
    --ids-cat-textw: none;
    /* Garis pemisah SELEBAR PENUH — sengaja tidak ikut dibatasi max-width,
       karena yang dibatasi hanyalah blok teksnya. */
    border-bottom: 1px solid rgba(127,127,127,.22);
    padding: {GAP_SECTION} .25rem;
    margin: 0;
    transition: background-color {HOVER_MS}ms ease;
}}
/* Sorot SANGAT tipis saat kursor melintas — menandakan baris dapat dituju,
   tanpa gerakan, bayangan, maupun garis tambahan. */
[class*="st-key-{ROW_KEY_PREFIX}"]:hover {{
    background: rgba(127,127,127,.06);
}}
/* Baris terakhir tidak perlu garis penutup. */
[class*="st-key-{ROW_KEY_PREFIX}"]:last-of-type {{ border-bottom: none; }}
/* Tombol adalah elemen TERAKHIR dalam baris — jarak bawahnya sudah dipegang
   padding baris itu sendiri. */
[class*="st-key-{ROW_KEY_PREFIX}"] [data-testid="stHorizontalBlock"] {{
    margin-bottom: 0;
}}

/* Tombol aksi katalog: SERAGAM antar blok, tetapi luwes terhadap lebar.
   Mengisi lebar kolomnya sampai batas {CATALOG_BTN_W}; pada kolom yang lebih
   sempit ia menyusut mengikuti kolom alih-alih meluber. Kolomnya sendiri
   menumpuk menjadi vertikal di bawah {STACK_WIDTH} (aturan stColumn di atas),
   jadi tombol berdampingan saat lebar cukup dan menumpuk saat sempit. */
[class*="st-key-cat_run_"] button, [class*="st-key-cat_detail_"] button {{
    width: 100%;
    max-width: {CATALOG_BTN_W};
    min-width: 0;
    min-height: 2.3rem;
    white-space: normal;                 /* label membungkus, tidak terpotong */
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

/* ── Chip katalog: penanda asal & keadaan ──────────────────────────────── */
/* Keadaan TIDAK disampaikan lewat warna saja: setiap chip bermasalah juga
   membawa kata ("bermasalah"/"belum ada dataset") dan kalimat sebabnya di
   bawah baris. Warna hanya mempercepat pemindaian. */
.ids-cat-chip-mark {{
    opacity: .72;
    font-size: .82em;
    margin-left: .35rem;
}}
.ids-cat-chip-broken {{
    border-color: rgba(200, 70, 70, .55) !important;
    color: rgb(190, 70, 70);
}}
.ids-cat-chip-warn {{
    border-color: rgba(200, 150, 60, .55) !important;
    color: rgb(170, 120, 40);
}}

/* Label mode + dropdown-nya adalah SATU kesatuan: baris label menyebut mode
   yang sedang berlaku, dropdown di bawahnya yang menggantinya. Jaraknya
   dirapatkan supaya label tidak terbaca mengambang di antara pengalih bahasa
   dan dropdown. Jarak ke unsur DI ATASNYA justru dilebihkan sedikit, agar
   pasangan ini terpisah jelas dari pengalih bahasa. */
.ids-mode-label {{ display: none; }}
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"]
    > *:has(.ids-mode-label) {{
    margin-top: .5rem;
    margin-bottom: 0;
}}
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"]
    > *:has(.ids-mode-label) + * {{
    margin-top: .1rem;
    margin-bottom: .1rem;
}}

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

/* ── Formulir detail: satu bentuk, bukan kumpulan kartu ────────────────
   Bagian "Yang diperiksa" dahulu menggambar SATU KOTAK BERBATAS per ruas:
   sepuluh ruas berarti sepuluh kotak bersudut lengkung, masing-masing dengan
   padding sendiri. Yang terbaca bukan sebuah formulir, melainkan tumpukan
   kartu yang tiap barisnya berbobot sama.

   Di sini ia menjadi satu tabel datar. Hierarkinya dibawa UKURAN, BOBOT, dan
   WARNA, bukan garis: label lebih kecil dan redup, nilainya seukuran teks isi
   dan tebal. Garis hanya sebagai pemisah baris yang tipis, dan latar yang
   sangat samar dipasang di tingkat FORMULIR, bukan per ruas. */
.ids-facts-detail {{
    background: rgba(127,127,127,.04);
    border-radius: .4rem;
    padding: .15rem .6rem;
}}
.ids-facts-detail th, .ids-facts-detail td {{
    padding: .42rem .1rem;               /* padat, tetapi tetap bernapas */
    vertical-align: baseline;
    border-bottom: 1px solid rgba(127,127,127,.12);
    line-height: 1.5;
}}
/* Baris terakhir tidak diberi garis: garis yang menggantung di dasar kotak
   terbaca seperti tabel yang terpotong. */
.ids-facts-detail tr:last-child th, .ids-facts-detail tr:last-child td {{
    border-bottom: none;
}}
.ids-facts-detail .ids-fact-k {{
    font-size: {FONT_CAPTION};           /* LEBIH KECIL daripada nilainya */
    /* Bobotnya tetap dua tingkat yang sudah berlaku, 400 dan 600: menambah
       tingkat ketiga hanya untuk satu tabel akan merusak skala yang dipakai
       seluruh halaman. Pembedanya ukuran dan warna, bukan bobot ketiga. */
    font-weight: {WEIGHT_NORMAL};
    opacity: .58;
    white-space: nowrap;                 /* label tidak ikut melipat */
    padding-right: .75rem;
}}
.ids-facts-detail .ids-fact-v {{
    font-size: {FONT_BODY};
    font-weight: {WEIGHT_STRONG};
    opacity: 1;
}}
/* Nilai panjang (mis. catatan pengaju) mengambil sisa lebar barisnya sendiri,
   alih-alih melipat menjadi empat baris di dalam kolom sempit sementara
   separuh baris di sebelahnya kosong. */
.ids-facts-detail .ids-fact-wide {{
    width: auto;
    white-space: normal;
    overflow-wrap: anywhere;
}}
.ids-facts-detail .ids-fact-k, .ids-facts-detail .ids-fact-v {{
    width: auto;
}}
/* Layar sempit: label dan nilai menumpuk, label tetap rata kiri. */
@media (max-width: {STACK_WIDTH}) {{
    .ids-facts-detail th, .ids-facts-detail td {{
        display: block;
        width: 100%;
        border-bottom: none;
        padding: .1rem 0;
    }}
    .ids-facts-detail .ids-fact-k {{ white-space: normal; }}
    .ids-facts-detail .ids-fact-v {{
        padding-bottom: .5rem;
        border-bottom: 1px solid rgba(127,127,127,.12);
    }}
}}

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
    /* BLOK DATA: mengikuti lebar penuh kolomnya. Dulu dibatasi {CARD_MAX_W},
       sehingga kotak angka berhenti di ~3/4 lebar dan tampak seperti cacat
       render. Sel-selnya sendiri sudah punya lebar minimum, jadi melebar
       berarti kolomnya bertambah — bukan angkanya jadi renggang. */
    max-width: none;
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

/* ── Kolom yang BENAR-BENAR dapat menyusut ─────────────────────────────
   `min-width` bawaan sebuah flex item adalah `auto`: ia MENOLAK menyusut di
   bawah lebar isinya. Sebuah kolom Streamlit berisi tombol berlabel panjang
   atau kode satu kata karena itu melebar melewati jatahnya dan MENINDIH kolom
   di sebelahnya — "Nonaktifkan" di tabel Kelola Research tergambar menumpuk
   di atas "Sunting", dan rasio `st.columns` yang diminta halaman tidak pernah
   benar-benar berlaku.

   Aturan menumpuk di bawah ini memakai selektor yang lebih khusus DAN berdiri
   sesudahnya, jadi `min-width: 100%` miliknya tetap menang saat sempit. */
[data-testid="{COL_ONE}"] {{ min-width: 0; }}
/* …dan isi kolomnya ikut menyusut alih-alih meluber keluar. Labelnya
   MEMBUNGKUS, bukan terpotong: tombol yang berbunyi "Nonaktifk" tidak
   mengatakan apa pun tentang apa yang akan terjadi bila ditekan. */
[data-testid="{COL_ONE}"] [data-testid^="stBaseButton-"] {{
    min-width: 0;
    max-width: 100%;
    white-space: normal;
}}
/* Kode satu kata (jenis dataset) memutus di mana saja daripada mendorong
   kolomnya melebar. */
[data-testid="{COL_ONE}"] code {{ overflow-wrap: anywhere; }}

/* ── Kolom AKSI pada baris tabel ───────────────────────────────────────
   Tombol tidak pernah dipaksa lebih sempit daripada labelnya: bila tidak muat
   berdampingan, ia PINDAH ke baris berikutnya. Memampatkannya menghasilkan
   "Nona / ktifka / n" — tiga baris yang menindih tombol di sebelahnya dan
   tidak terbaca sebagai apa pun.

   `min-width: 0` di atas membuat kolom BOLEH menyusut; di sini kolom tombol
   justru tidak boleh, sebab yang menyusut bukan teks yang dapat membungkus
   rapi melainkan satu kata perintah. Keduanya tidak bertentangan: yang satu
   melepaskan rasio kolom, yang satu lagi memberi tombol lantai. */
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-queue-row)
    [data-testid="{COL_ROW}"] [data-testid="{COL_ROW}"] {{
    flex-wrap: wrap;
    row-gap: .35rem;
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-queue-row)
    [data-testid="{COL_ROW}"] [data-testid="{COL_ROW}"]
    > [data-testid="{COL_ONE}"] {{
    flex: 1 1 auto;
    min-width: max-content;
}}
div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-queue-row)
    [data-testid="{COL_ROW}"] [data-testid="{COL_ROW}"]
    [data-testid^="stBaseButton-"] {{
    white-space: nowrap;
}}

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

/* ── Tabel baku (`ids-tbl`) ────────────────────────────────────────────
   SATU definisi untuk seluruh tabel di bagian Peninjauan Pengajuan, di
   stylesheet GLOBAL — bukan blok <style> yang disuntikkan per tampilan.

   Itu bedanya dengan `ids-cmp`: aturan `ids-cmp` hidup sebagai <style> di
   dalam dialog perbandingan pada halaman Progress & Status, jadi tabel yang
   memakai kelas itu di halaman LAIN tampil tanpa gaya sama sekali — persis
   yang terjadi pada tabel riwayat versi. Aturan di bawah tidak bisa
   "tertinggal" karena ia bagian dari stylesheet yang selalu terpasang. */
.ids-tbl-scroll {{
    /* Gulir MENDATAR saat kolomnya banyak, VERTIKAL saat barisnya panjang —
       tidak memampat sampai teks terpotong. */
    overflow-x: auto;
    overflow-y: auto;
    max-height: {TABLE_MAX_H};
    -webkit-overflow-scrolling: touch;
}}
.ids-tbl {{
    width: 100%;                         /* BLOK DATA: lebar penuh kolomnya */
    min-width: {TABLE_MIN_W};
    border-collapse: collapse;
    /* `fixed` membuat lebar kolom ditentukan colgroup, bukan oleh isi sel.
       Tanpa ini lebar kolom MELOMPAT antar tabel dan antar render begitu ada
       satu nilai yang panjang. */
    table-layout: fixed;
    font-size: {FONT_BODY};
}}
/* Tinggi baris & padding SERAGAM untuk th maupun td. */
.ids-tbl th, .ids-tbl td {{
    padding: {TABLE_PAD};
    line-height: 1.45;
    height: {TABLE_ROW_H};
    vertical-align: middle;
    text-align: left;                    /* teks rata kiri, bawaan */
    /* Nilai panjang DIPENDEKKAN, tidak dibungkus — membungkus membuat tinggi
       baris tidak rata. Nilai penuhnya ada di atribut `title`. */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    /* SATU gaya garis pemisah: tipis, sama di seluruh tabel. Tidak ada
       campuran tebal-tipis. */
    border-bottom: 1px solid {LINE_SOFT};
}}
/* Header dibedakan lewat BOBOT + LATAR, dan tetap terlihat saat digulir. */
.ids-tbl thead th {{
    font-weight: {WEIGHT_STRONG};
    background: {HEAD_TINT};
    position: sticky;
    top: 0;
    z-index: 1;
}}
/* Angka rata KANAN dengan digit lebar-tetap supaya sejajar antar baris. */
.ids-tbl th.ids-tbl-num, .ids-tbl td.ids-tbl-num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
}}
/* Baris terakhir tidak perlu garis penutup — wadahnya sudah membatasi. */
.ids-tbl tbody tr:last-child td {{ border-bottom: none; }}
/* Baris yang ditonjolkan (mis. versi aktif): latar, bukan garis tebal. */
.ids-tbl tr.ids-tbl-on td {{
    background: rgba(127,127,127,.13);
    font-weight: {WEIGHT_STRONG};
}}
/* Keadaan kosong & baris hitungan: tenang, dan BOLEH membungkus karena ia
   kalimat, bukan nilai kolom. */
.ids-tbl td.ids-tbl-empty {{
    opacity: .7;
    white-space: normal;
    border-bottom: none;
}}

/* Baris aksi pada blok pipeline kontribusi: tombolnya SEragam.
   Label seperti "Aktifkan kembali" jauh lebih panjang daripada "Riwayat";
   tanpa tinggi minimum bersama, yang membungkus jadi lebih tinggi daripada
   tetangganya dan barisnya terlihat miring. `white-space: normal` membuatnya
   membungkus alih-alih terpotong. Kaitannya kunci container yang memang sudah
   ada (lihat `_render_pipeline_block`). */
/* Tombol baris tabel "Aktif": labelnya TIDAK boleh patah di tengah kata.
   "Nonaktifkan" pecah menjadi "Nonaktifka" + "n" ketika kolomnya menyempit,
   dan satu huruf yang jatuh sendirian ke baris kedua membuat tombolnya lebih
   tinggi daripada tetangganya — barisnya terlihat miring.

   `nowrap` saja tidak cukup: tanpa lebar minimum, kolom yang menyempit tetap
   memotong teksnya. Keduanya dipasang bersama, dan pada layar sempit aturan
   penumpukan global membuat tiap tombol selebar penuh sehingga keduanya
   tidak pernah bertabrakan. */
[class*="st-key-rs_edit_"] .stButton > button,
[class*="st-key-rs_toggle_"] .stButton > button,
[class*="st-key-rs_revert_"] .stButton > button {{
    white-space: nowrap;
    min-width: 6.5rem;
}}

[class*="st-key-mp_active_"] .stButton > button {{
    min-height: 2.3rem;
    white-space: normal;
}}

/* ── Tombol "Info" halaman kontribusi ──────────────────────────────────
   SATU aturan untuk KEDUA halaman (unggah pipeline & tambah dataset). Keduanya
   memakai kunci berawalan `contrib_info_`, jadi gayanya tidak dapat berbeda
   sendiri di satu halaman — kesalahan yang pasti terjadi bila ada dua aturan
   kembar yang harus diingat untuk diubah bersama.

   Satu-satunya warna PADAT di berkas ini, dan perkecualiannya disengaja:
   tombol ini membawa seluruh panduan halaman, jadi ia harus terbaca sebagai
   satu-satunya benda gelap di sana — bukan tombol kelima yang serupa
   tetangganya.

   Aturan "tidak ada heksa" berlaku karena warna yang dipaku dapat menjadi tak
   terbaca saat pengguna berpindah tema. Pasangan di bawah tidak bisa: latar
   dan teksnya DITETAPKAN BERSAMA, sehingga kontrasnya milik tombol itu sendiri
   dan tidak bergantung pada latar halaman. Tepi tipis semi-transparan menjaga
   batasnya tetap terlihat di tema gelap, tempat hitam bertemu hitam. */
/* `!important` DIPERLUKAN, dan sebabnya terukur: seluruh tombol dalam daftar
   ini bertipe `primary`, dan gaya primary milik Streamlit menang atas aturan
   ini — tombolnya tetap merah betapapun rapinya selektor di atas ditulis.
   Yang lolos selama ini hanya tombol Info, satu-satunya yang BUKAN primary,
   sehingga daftar ini tampak bekerja padahal tiga perempatnya tidak.

   Penjaga strukturalnya pun tidak menangkapnya: ia memeriksa tombolnya
   memakai KUNCI yang benar, bukan tombolnya benar-benar berubah warna. */
{DARK_BTN_BASE} {{
    background-color: #111418 !important;
    color: #ffffff !important;
    border: 1px solid rgba(255, 255, 255, .28) !important;
}}
{DARK_BTN_HOVER} {{
    background-color: #000000 !important;
    color: #ffffff !important;
    border-color: rgba(255, 255, 255, .55) !important;
}}
/* Label anak (Streamlit membungkus teks tombol dalam <p>) ikut mewarisi. */
{DARK_BTN_CHILD} {{
    color: inherit !important;
}}

/* ── Halaman Tambah Pipeline & Dataset: SELURUH tombol utamanya hitam ───
   Didasarkan pada HALAMAN, bukan pada daftar kunci tombol. Halaman itu punya
   belasan tombol `primary` — validasi, ajukan, setujui, simpan revisi, simpan
   versi, hapus — dan mendaftarkan kuncinya satu per satu berarti tombol
   berikutnya yang ditambahkan seseorang akan merah sendirian tanpa ada yang
   menyadarinya.

   Penandanya satu span tersembunyi yang digambar halaman itu (lihat
   `contribute.render`). `[data-testid="stBaseButton-primary"]` adalah
   penanda tombol utama milik Streamlit sendiri — bukan tebakan: frontendnya
   menyusunnya sebagai `stBaseButton-${{kind}}`.

   Tombol yang BENAR-BENAR menjalankan eksperimen tidak ada di halaman ini,
   jadi merahnya tetap utuh di tempatnya. */
.ids-page-dark {{ display: none; }}

[data-testid="stMain"]:has(.ids-page-dark)
    [data-testid="stBaseButton-primary"] {{
    background-color: #111418 !important;
    color: #ffffff !important;
    border: 1px solid rgba(255, 255, 255, .28) !important;
}}
[data-testid="stMain"]:has(.ids-page-dark)
    [data-testid="stBaseButton-primary"]:not(:disabled):hover {{
    background-color: #000000 !important;
    color: #ffffff !important;          /* latar & teks DITETAPKAN BERSAMA */
    border-color: rgba(255, 255, 255, .55) !important;
}}
[data-testid="stMain"]:has(.ids-page-dark)
    [data-testid="stBaseButton-primary"] * {{
    color: inherit !important;
}}

/* ── Diff versi: baris ditambah / dihapus ──────────────────────────────
   Warna memakai lapisan TEMBUS PANDANG di atas latar halaman, jadi satu palet
   bekerja di tema terang maupun gelap — tidak ada dua definisi yang bisa
   berbeda sendiri.

   Warna BUKAN satu-satunya pembeda. Tiap baris membawa kolom penanda `+`/`−`
   dan garis tebal di tepi kiri, sehingga tetap terbaca pada buta warna, mode
   kontras tinggi, atau cetak hitam-putih. */
.ids-diff-scroll {{ overflow-x: auto; overflow-y: hidden; }}
.ids-diff {{
    width: 100%;                         /* BLOK DATA: lebar penuh kolomnya */
    min-width: {DIFF_MIN_W};
    border-collapse: collapse;
    font-family: {MONO_STACK};
    /* Memakai tingkat "keterangan" yang SUDAH ADA, bukan ukuran baru: tabel
       ini padat, tetapi menambah tingkat teks kelima hanya untuk satu tabel
       akan merusak sistem empat tingkat yang berlaku di seluruh halaman. */
    font-size: {FONT_CAPTION};
    line-height: 1.5;
}}
.ids-diff th {{
    font-family: inherit;
    font-size: {FONT_CAPTION};
    font-weight: {WEIGHT_STRONG};
    opacity: .7;
    text-align: right;
    padding: .1rem .45rem;
    border-bottom: 1px solid rgba(127,127,127,.3);
}}
.ids-diff td {{ padding: 0 .45rem; vertical-align: top; }}
/* Nomor baris kedua sisi: rata kanan, lebar sesempit isinya, tidak dapat
   diseleksi ikut terbawa saat kode disalin. */
.ids-diff .ids-diff-n {{
    width: 1%;
    white-space: nowrap;
    text-align: right;
    opacity: .5;
    user-select: none;
    font-variant-numeric: tabular-nums;
    border-right: 1px solid rgba(127,127,127,.16);
}}
/* Kolom penanda tekstual — inilah yang menggantikan warna bila warna hilang.
   Garis tepinya memakai `border-left`, BUKAN `box-shadow`: bayangan di
   halaman ini disediakan khusus untuk menandai keadaan AKTIF, dan memakainya
   di sini akan mengaburkan arti itu. */
.ids-diff .ids-diff-m {{
    width: 1%;
    white-space: pre;
    text-align: center;
    font-weight: {WEIGHT_STRONG};
    user-select: none;
    padding: 0 .3rem;
    border-left: .18rem solid transparent;
}}
.ids-diff .ids-diff-t {{ white-space: pre; overflow-wrap: normal; }}
.ids-diff-add {{ background: rgba(46,160,67,.16); }}
.ids-diff-del {{ background: rgba(248,81,73,.16); }}
.ids-diff-add .ids-diff-m {{ border-left-color: rgba(46,160,67,.9); }}
.ids-diff-del .ids-diff-m {{ border-left-color: rgba(248,81,73,.9); }}
/* Bagian tak berubah: tenang, supaya perubahan yang menonjol. */
.ids-diff-equal {{ opacity: .72; }}

/* ── Halaman peninjauan satu pengajuan ───────────────────────────────────
   Warna di sini MENANDAI KEADAAN, tidak menghias — aturan yang sama yang
   sudah berlaku pada chip katalog (`ids-cat-chip-broken/-warn`) dan pada
   diff versi. Tiga keadaan, dan bedanya berakibat nyata bagi peninjau:
   lolos, lolos dengan peringatan, dan ada masalah.

   Ronanya `rgba` beralfa rendah, jadi ia menjadi pastel di tema terang dan
   rona tipis di tema gelap tanpa perlu dua definisi. Warna TIDAK PERNAH
   menjadi satu-satunya pembawa keterangan: tiap blok tetap memuat kalimat
   keadaannya, sehingga tetap terbaca tanpa melihat warna sama sekali. */
.ids-rv-head {{
    border-left: .22rem solid var(--ids-rv-line, rgba(127,127,127,.5));
    background: var(--ids-rv-tint, rgba(127,127,127,.06));
    border-radius: .35rem;
    padding: .6rem .85rem;
    margin: .15rem 0 .75rem;
}}
.ids-rv-name {{
    font-size: {FONT_SECTION};
    font-weight: {WEIGHT_STRONG};
    line-height: 1.3;
}}
.ids-rv-verdict {{
    font-size: {FONT_BODY};
    font-weight: {WEIGHT_STRONG};
    color: var(--ids-rv-line, inherit);
    margin-top: .1rem;
}}
.ids-rv-meta {{
    font-size: {FONT_CAPTION};
    opacity: .72;
    margin-top: .15rem;
}}

/* Kepala satu berkas paket — menggantikan label expander yang dibuang. */
.ids-rv-file {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: .5rem;
    border-left: .18rem solid var(--ids-rv-line, rgba(127,127,127,.45));
    padding: .3rem .6rem;
    margin: .9rem 0 .4rem;
    background: var(--ids-rv-tint, rgba(127,127,127,.05));
    border-radius: .25rem;
}}
.ids-rv-fname {{ font-weight: {WEIGHT_STRONG}; }}
.ids-rv-ftail {{ font-size: {FONT_CAPTION}; opacity: .72; }}

/* Ketiga keadaan. Hijau/kuning/merah yang SAMA dengan yang sudah dipakai
   di tempat lain, supaya "merah" berarti hal yang sama di seluruh aplikasi. */
.ids-rv-ok {{
    --ids-rv-line: rgba(46,160,67,.9);
    --ids-rv-tint: rgba(46,160,67,.10);
}}
.ids-rv-warn {{
    --ids-rv-line: rgba(200,150,60,.95);
    --ids-rv-tint: rgba(200,150,60,.12);
}}
.ids-rv-bad {{
    --ids-rv-line: rgba(200,70,70,.9);
    --ids-rv-tint: rgba(200,70,70,.12);
}}

/* Tiga zona. Bedanya BUKAN selera tata letak: keliru mengira zona kerja
   sebagai zona baca berarti menekan tombol yang mengubah keadaan sambil
   mengira sedang membaca.

   Yang membedakan ketiganya adalah AKIBATNYA, dan gayanya mengikuti itu:

     baca      — tidak mengubah apa pun. Tenang.
     pengujian — mengubah sesuatu, tetapi DAPAT DIULANG.
     keputusan — TIDAK dapat diulang.

   Karena itu zona keputusan bergaris lebih tebal: ia satu-satunya yang
   akibatnya tidak dapat ditarik kembali. */
.ids-zone {{
    /* Ukuran JUDUL, bukan ukuran keterangan. Sebelumnya ia memakai skala
       keterangan (lebih KECIL daripada teks isi di bawahnya), sehingga judul
       bagian terbaca lebih lemah daripada hal yang dijudulinya. */
    font-size: {FONT_SECTION};
    font-weight: {WEIGHT_STRONG};
    letter-spacing: .02em;
    padding: .1rem 0 .5rem;
    margin-bottom: .5rem;
    border-bottom: 1px solid rgba(127,127,127,.22);
}}
/* KETIGA zona memakai judul REDUP yang sama. Dahulu dua di antaranya biru,
   dan akibatnya sebuah halaman peninjauan memuat tiga judul bagian dengan dua
   warna berbeda — sementara judul bagian lain di aplikasi ini (Riwayat revisi,
   Berkas paket, Kontrak dataset) semuanya redup. Yang biru karena itu terbaca
   seperti tautan atau seperti sesuatu yang berbeda jenisnya, padahal ia judul
   bagian yang sama saja.

   Perbedaan zona keputusan TIDAK hilang: ia tetap satu-satunya yang bergaris
   bawah tebal. Yang membedakannya kini ketebalan, bukan warna — dan ketebalan
   tetap terbaca oleh mata yang tidak membedakan warna. */
/* ── Kartu "Sedang berjalan" di sidebar ────────────────────────────────
   Isinya sebuah blok: judul, nama pipeline, bar progres, keterangan fase.
   Dahulu keempatnya mengambang di antara dua garis pemisah, sehingga terbaca
   seperti empat hal yang kebetulan berdekatan.

   LEMBUT, bukan tegas: tepi semi-transparan dan latar tipis dari warna netral
   yang sama dengan blok lain, jadi ia menjadi pastel di tema terang dan gelap
   di tema gelap tanpa satu pun warna yang dipaku. Sudutnya membulat mengikuti
   kartu lain di aplikasi ini.

   Jangkarnya span tersembunyi — Streamlit tidak memberi kelas pada wadahnya,
   jadi yang dicari CSS adalah wadah yang MEMUAT jangkar itu. Pola yang sama
   dengan `.ids-form-compact`. */
.stElementContainer:has(.ids-run-card) {{ display: none; }}

/* Wadahnya hanya JANGKAR POSISI, tanpa rupa. Kotaknya sendiri digambar oleh
   `.ids-run` di bawah — yaitu oleh elemen yang benar-benar memuat teksnya.
   Sebelumnya rupa itu menempel pada wadah Streamlit, dan wadah itu ternyata
   tidak setinggi isinya: latarnya berhenti di tengah kartu dan baris fase
   tergambar di luar kotaknya sendiri. */
[data-testid="stSidebarUserContent"]
    div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card) {{
    position: relative;                  /* jangkar tombol yang menumpanginya */
    gap: 0;
}}

/* Tombol yang MENUMPANG kartu. Ia menutupi seluruh kartu dan dibuat tembus
   pandang: yang terlihat kartunya, yang ditekan tombol Streamlit sungguhan —
   jadi fokus papan ketik dan pembaca layar tetap bekerja. Tautan HTML akan
   lebih sederhana, tetapi ia memuat ulang halaman dan membuang keadaan sesi,
   termasuk eksperimen yang sedang dipantau. */
[data-testid="stSidebarUserContent"]
    div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card)
    .stButton {{
    position: absolute;
    inset: 0;
    margin: 0;
    z-index: 2;
}}
[data-testid="stSidebarUserContent"]
    div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card)
    .stButton > button {{
    width: 100%;
    height: 100%;
    padding: 0;
    border: none;
    border-radius: 12px;
    background: transparent;
    color: transparent;                  /* labelnya hanya untuk pembaca layar */
}}
[data-testid="stSidebarUserContent"]
    div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card)
    .stButton > button:not(:disabled):hover {{
    background: rgba(127,127,127,.07);
}}
[data-testid="stSidebarUserContent"]
    div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card)
    .stButton > button:focus-visible {{
    outline: 2px solid var(--primary-color, currentColor);
    outline-offset: -2px;
}}

/* ── Isi kartu ────────────────────────────────────────────────────────
   Empat baris pendek, hierarki dibentuk oleh UKURAN dan kepekatan — bukan
   oleh garis pemisah atau label tambahan. */
/* KOTAKNYA. Dipasang pada elemen kartu, bukan pada wadah Streamlit, sehingga
   tepinya selalu mengikuti tinggi isinya — berapa pun baris yang tergambar. */
.ids-run {{
    line-height: 1.3;
    border: 1px solid rgba(127,127,127,.20);
    border-radius: 12px;
    background: {TINT_NEUTRAL};
    padding: .5rem .7rem .6rem;
}}
/* Jarak antar kartu saat beberapa run berjalan sekaligus. Cukup untuk
   memisahkan, tidak sampai membuat tumpukannya memakan sidebar. */
[data-testid="stSidebarUserContent"]
    div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card)
    + div[data-testid="stVerticalBlock"]:has(> .stElementContainer .ids-run-card) {{
    margin-top: .4rem;
}}
.ids-run-live {{
    display: flex;
    align-items: center;
    gap: .35rem;
    font-size: {FONT_CAPTION};
    opacity: .55;
}}
.ids-run-dot {{
    width: 6px; height: 6px; border-radius: 999px; flex: 0 0 6px;
    background: rgb(52,168,83);
    animation: ids-run-pulse 1.8s ease-in-out infinite;
}}
@keyframes ids-run-pulse {{
    0%, 100% {{ opacity: 1; }}
    50%      {{ opacity: .25; }}
}}
/* Identitas run: pipeline · dataset pada SATU baris, dipotong ellipsis.
   Membungkus akan menaikkan tinggi kartu mengikuti panjang nama — dan kartu
   yang tingginya berbeda-beda membuat tumpukan beberapa run terbaca miring. */
.ids-run-name, .ids-run-phase {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.ids-run-name {{
    font-weight: {WEIGHT_STRONG};
    font-size: {FONT_BODY};
    margin-top: .1rem;
}}
/* Titik tengah pemisah: yang memisahkan "pipeline mana" dari "atas data
   mana". Ia tanda baca, jadi ia lebih redup daripada keduanya. */
.ids-run-dot-sep {{ opacity: .35; margin: 0 .3rem; }}
/* Dataset ikut di baris yang sama, tetapi lebih redup: yang dicari mata lebih
   dulu adalah nama pipeline-nya. */
.ids-run-ds {{ font-weight: {WEIGHT_NORMAL}; opacity: .6; }}
/* Kartu yang SEDANG dipantau. Tepi tipis, bukan latar pekat: ia menjawab
   "yang ini", bukan "yang ini penting". Dipasang pada kartunya sendiri,
   sepasang dengan kotaknya. */
.ids-run--active {{ border-color: rgba(127,127,127,.48) !important; }}
.ids-run-foot {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: .5rem;
    margin-top: .35rem;
    font-size: {FONT_CAPTION};
}}
/* Fase adalah jawaban utamanya, jadi ia yang paling pekat di baris ini. */
.ids-run-phase {{ font-weight: {WEIGHT_STRONG}; min-width: 0; }}
.ids-run-pct {{ opacity: .5; flex: 0 0 auto; font-variant-numeric: tabular-nums; }}
.ids-run-track {{
    height: 3px;
    border-radius: 999px;
    background: rgba(127,127,127,.20);
    overflow: hidden;
    margin-top: .3rem;
}}
.ids-run-fill {{
    height: 100%;
    background: var(--primary-color, currentColor);
    opacity: .75;
    border-radius: 999px;
}}

.ids-zone-read, .ids-zone-test {{ opacity: .62; }}

.ids-zone-work {{
    opacity: .62;
    border-bottom-width: 2px;
    border-bottom-color: rgba(127,127,127,.42);
}}

@media (prefers-reduced-motion: reduce) {{
    .stButton > button, .stDownloadButton > button,
    [data-testid="stPopover"] > button, .ids-clickable,
    [data-testid="{SEG_GROUP}"] button {{
        transition: none !important;
    }}
    /* Titik berdenyut BERHENTI, tetapi tidak hilang: ia tetap penanda bahwa
       ada yang berjalan, dan itu keterangan — bukan hiasan. */
    .ids-run-dot {{ animation: none !important; }}
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
