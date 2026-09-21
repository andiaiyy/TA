"""
SATU penyaji tabel untuk seluruh bagian "Peninjauan Pengajuan".

**Kenapa modul ini ada.** Tabel riwayat versi menuliskan markup berkelas
``ids-cmp`` — kelas yang aturannya hidup di ``ui/views/view_results.py`` sebagai
blok ``<style>`` dan hanya disuntikkan DI DALAM dialog perbandingan pada halaman
Progress & Status. Di halaman Add Pipeline & Dataset blok itu tidak pernah
disuntikkan, sehingga tabelnya tampil dengan gaya bawaan peramban: tanpa padding
sel, tanpa garis pemisah, tanpa header yang dibedakan, tanpa perataan angka,
tanpa elipsis. Satu-satunya aturan yang sampai adalah ``min-width`` di
stylesheet global. Itulah sebab tabel di bagian ini terlihat berantakan — bukan
gaya yang kurang bagus, melainkan gaya yang TIDAK PERNAH TERPASANG.

Modul ini menutup kemungkinan itu terulang:

* gayanya didefinisikan SEKALI di ``ui/components/theme`` (kelas ``ids-tbl``),
  jadi ia ikut stylesheet global dan berlaku di halaman mana pun;
* markup-nya dibangun SEKALI di sini, jadi tidak ada tabel yang menyusun
  ``<td>``-nya sendiri dan mengarang perataan atau lebar kolomnya.

**Kolom sejenis berlebar sama.** Lebar per JENIS kolom (versi, hash, waktu,
angka, status, aksi) diambil dari :data:`COLUMN_WIDTH` — satu sumber, sehingga
kolom "Hash" pada riwayat versi dan pada daftar berkas tidak mungkin berbeda
lebar. Satuannya ``rem``, bukan piksel, supaya ikut skala huruf pengguna.
"""
from __future__ import annotations

from html import escape

import streamlit as st

# ── Jenis kolom ──────────────────────────────────────────────────────────
#
# Jenis menentukan TIGA hal sekaligus — perataan, format, dan lebar — supaya
# ketiganya tidak mungkin ditetapkan sendiri-sendiri di tiap pemanggil.

# Kosakata ini sengaja hanya memuat jenis yang BENAR-BENAR dipakai sebuah
# kolom. Jenis tanpa pemakai bukan kemampuan cadangan: ia membawa lebar,
# cabang format, dan aturan tooltip yang tidak pernah dijalankan, dan pembaca
# berikutnya tidak punya cara membedakannya dari yang hidup. `KIND_HASH`,
# `KIND_VERSION`, dan `KIND_MARK` dicabut bersama tabel versi algoritma,
# riwayat versi, dan pembandingnya — satu-satunya tabel yang memakainya.

KIND_TEXT = "text"          # teks bebas: rata kiri, elipsis + tooltip
KIND_NAME = "name"          # nama berkas/pipeline: rata kiri, tooltip penuh
KIND_NUM = "num"            # angka: rata KANAN, digit lebar-tetap
KIND_TIME = "time"          # waktu: rata kiri, format seragam
KIND_STATUS = "status"      # status pendek

#: Lebar kolom per JENIS — satu definisi untuk semua tabel di bagian ini.
#: Dalam ``rem`` (bukan piksel) supaya ikut skala huruf pengguna.
COLUMN_WIDTH = {
    KIND_TIME: "11rem",
    KIND_NUM: "7rem",
    KIND_STATUS: "10rem",
}

#: Jenis yang rata kanan. Hanya angka — supaya digitnya sejajar antar baris.
RIGHT_ALIGNED = (KIND_NUM,)

#: Keadaan kosong bawaan. Tiap tabel tetap wajib memberi kalimatnya sendiri
#: yang lebih tepat; ini hanya jaring pengaman supaya tidak pernah ada tabel
#: kosong tanpa keterangan.
EMPTY_FALLBACK = "Belum ada isi."

#: Penanda SATU SEL yang tidak punya nilai. Bukan kalimat, melainkan tanda:
#: sel yang benar-benar kosong terbaca seperti kolom yang lupa diisi,
#: sedangkan tanda ini menyatakan "memang tidak ada".
#:
#: Bernama, bukan literal yang diulang di lima berkas: ia pernah berupa tanda
#: pisah, dan menggantinya berarti memburu setiap salinannya satu per satu.
EMPTY_CELL = "-"


#: Nama bulan ringkas. Ditulis di sini dan bukan lewat `strftime`, sebab
#: `strftime` memakai locale sistem: pada mesin berbahasa Inggris ia akan
#: mencetak "Sep" di tengah kalimat berbahasa Indonesia, dan itu berubah-ubah
#: menurut mesin yang menjalankannya.
_BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
          "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def dataset_code(nilai) -> str:
    """Pengenal research SEBAGAIMANA DITULIS DI LAYAR: tanpa awalan ruang nama.

    `uploaded:ensemble_trafik_terenkripsi` menjadi
    `ensemble_trafik_terenkripsi`. Awalan itu milik MESIN — ia memisahkan
    ruang nama kontribusi dari yang bawaan supaya keduanya tidak pernah
    bertabrakan — dan tidak menjawab satu pun pertanyaan pembacanya.

    Yang TERSIMPAN tidak disentuh: pengenalnya tetap utuh di basis data, di
    registry, dan pada tiap baris eksperimen. Yang berubah hanya tulisannya.
    """
    from database.models import RESEARCH_PREFIX

    teks = str(nilai or "")
    return teks[len(RESEARCH_PREFIX):] if teks.startswith(RESEARCH_PREFIX) else teks


def human_datetime(nilai, *, seconds: bool = False) -> str:
    """`2026-09-14T06:47:23` menjadi `14 Sep 2026, 06:47`.

    Detik dibuang secara BAWAAN: ia tidak pernah menjawab pertanyaan yang
    membuat orang melihat tanggal. Nilai yang tidak berbentuk ISO dikembalikan
    apa adanya, sebab menampilkan yang tersimpan lebih jujur daripada
    menampilkan kosong.

    ``seconds=True`` mempertahankannya, dan itu bukan selera: tabel riwayat
    eksperimen memuat run yang dijalankan berturut-turut dalam satu menit yang
    sama, dan tanpa detik ketiganya terbaca sebagai waktu yang sama persis.

    Dipakai riwayat revisi PENGAJUAN, riwayat versi PIPELINE AKTIF, dan
    riwayat EKSPERIMEN. Ketiganya menjawab "kapan ini terjadi", jadi ketiganya
    menulisnya sama.
    """
    teks = str(nilai or "").strip()
    if len(teks) < 16 or teks[4] != "-" or teks[7] != "-":
        return teks
    try:
        tahun, bulan, hari = int(teks[:4]), int(teks[5:7]), int(teks[8:10])
        jam = teks[11:19] if seconds else teks[11:16]
    except ValueError:
        return teks
    if not 1 <= bulan <= 12:
        return teks
    return f"{hari} {_BULAN[bulan - 1]} {tahun}, {jam}"


def format_time(value) -> str:
    """Waktu dengan format seragam di seluruh tabel: ``YYYY-MM-DD HH:MM:SS``.

    Nilai ISO memisahkan tanggal dan jam dengan ``T``; ditampilkan sebagai
    spasi supaya terbaca, dan dipotong pada detik — pecahan detik serta zona
    waktu tidak menambah apa pun bagi pembaca dan hanya melebarkan kolom.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:19].replace("T", " ")


def column(label: str, key: str, *, kind: str = KIND_TEXT,
           width: str | None = None, title_key: str | None = None,
           label_key: str | None = None) -> dict:
    """Satu kolom. ``title_key`` menunjuk nilai PENUH untuk tooltip.

    ``label_key`` adalah kunci katalog untuk judul kolom. Definisi kolom
    adalah konstanta modul — dievaluasi sekali saat impor — jadi judulnya
    tidak boleh diterjemahkan di sini; ``label`` tetap menjadi cadangan bila
    kuncinya belum ada.
    """
    return {"label": label, "key": key, "kind": kind,
            "width": width or COLUMN_WIDTH.get(kind), "title_key": title_key,
            "label_key": label_key}


def _label(col: dict) -> str:
    """Judul kolom pada bahasa aktif; tanpa kunci → judul aslinya."""
    from ui.i18n import t

    key = col.get("label_key")
    return t(key) if key else col["label"]


def _cell(row: dict, col: dict) -> tuple[str, str]:
    """(teks tampil, teks tooltip) untuk satu sel."""
    kind = col["kind"]
    raw = row.get(col["key"])
    full = row.get(col["title_key"]) if col.get("title_key") else raw

    if kind == KIND_TIME:
        return format_time(raw), str(raw or "")
    if raw is None:
        return "", ""
    # Teks & angka apa adanya; elipsis dikerjakan CSS, tooltip membawa
    # nilai penuhnya sehingga tidak ada yang benar-benar hilang.
    return str(raw), str(full or raw)


def cell(row: dict, col: dict) -> tuple[str, str]:
    """(teks tampil, teks tooltip) untuk satu sel — bentuk PUBLIK dari
    :func:`_cell`.

    Tabel HTML dan tabel AgGrid memakai fungsi yang sama supaya keduanya
    menampilkan nilai yang identik: waktu diformat dengan aturan yang sama, dan
    nilai yang terpotong di layar tetap membawa nilai penuhnya pada tooltip.
    Tanpa ini, dua tabel yang menampilkan baris yang sama dapat menampilkannya
    secara berbeda, dan tidak ada yang memberi tahu bahwa itu terjadi.

    Pemendekan hash dan awalan "v" pada nomor versi dahulu juga dijanjikan di
    sini. Keduanya dicabut bersama jenis kolomnya; menyisakan janjinya berarti
    docstring ini menjamin sesuatu yang tidak lagi dikerjakan siapa pun.
    """
    return _cell(row, col)


def table_html(columns, rows, *, empty: str = EMPTY_FALLBACK,
               limit: int | None = None) -> str:
    """Markup tabel — SATU bentuk untuk semua tabel di bagian ini.

    ``limit`` membatasi jumlah baris yang digambar; totalnya tetap disebutkan
    supaya pembaca tahu ada berapa seluruhnya. Yang tidak digambar tetap dapat
    dicapai lewat gulir vertikal wadahnya.
    """
    columns = list(columns or [])
    rows = list(rows or [])
    if not columns:
        return ""

    cols = "".join(
        f'<col style="width: {c["width"]}" />' if c.get("width") else "<col />"
        for c in columns)

    head = "".join(
        f'<th class="ids-tbl-{"num" if c["kind"] in RIGHT_ALIGNED else "txt"}">'
        f'{escape(_label(c))}</th>' for c in columns)

    shown = rows[:limit] if limit else rows
    body = []
    for row in shown:
        cells = []
        for col in columns:
            text, title = _cell(row, col)
            klass = "num" if col["kind"] in RIGHT_ALIGNED else "txt"
            attr = f' title="{escape(title)}"' if title and title != text else ""
            # Dahulu sel hash dibungkus <code> supaya heksanya terbaca
            # monospace. Jenis hash sudah dicabut, jadi pembungkusnya ikut:
            # tidak ada lagi kolom yang isinya menuntut perlakuan itu.
            cells.append(f'<td class="ids-tbl-{klass}"{attr}>'
                         f'{escape(text)}</td>')
        mark = ' class="ids-tbl-on"' if row.get("_highlight") else ""
        body.append(f"<tr{mark}>{''.join(cells)}</tr>")

    if not body:
        # KEADAAN KOSONG: satu baris yang menjelaskan, bukan tabel kosong.
        body.append(f'<tr><td class="ids-tbl-empty" colspan="{len(columns)}">'
                    f"{escape(empty)}</td></tr>")
    elif limit and len(rows) > limit:
        body.append(f'<tr><td class="ids-tbl-empty" colspan="{len(columns)}">'
                    f"{len(shown)} dari {len(rows)}</td></tr>")

    return ('<div class="ids-tbl-scroll"><table class="ids-tbl">'
            f"<colgroup>{cols}</colgroup>"
            f"<thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def render_table(columns, rows, *, empty: str = EMPTY_FALLBACK,
                 limit: int | None = None) -> None:
    """Gambar tabel. Pembungkus tipis supaya pemanggil tidak menyentuh HTML."""
    st.html(table_html(columns, rows, empty=empty, limit=limit))
