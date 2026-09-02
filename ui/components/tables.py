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

KIND_TEXT = "text"          # teks bebas: rata kiri, elipsis + tooltip
KIND_NAME = "name"          # nama berkas/pipeline: rata kiri, tooltip penuh
KIND_NUM = "num"            # angka: rata KANAN, digit lebar-tetap
KIND_TIME = "time"          # waktu: rata kiri, format seragam
KIND_HASH = "hash"          # SHA-256: dipendekkan seragam, penuh di tooltip
KIND_VERSION = "version"    # nomor versi: rata kiri, sempit
KIND_STATUS = "status"      # status pendek
KIND_MARK = "mark"          # penanda satu karakter

#: Lebar kolom per JENIS — satu definisi untuk semua tabel di bagian ini.
#: Dalam ``rem`` (bukan piksel) supaya ikut skala huruf pengguna.
COLUMN_WIDTH = {
    KIND_VERSION: "5rem",
    KIND_HASH: "9.5rem",
    KIND_TIME: "11rem",
    KIND_NUM: "7rem",
    KIND_STATUS: "10rem",
    KIND_MARK: "2.5rem",
}

#: Jenis yang rata kanan. Hanya angka — supaya digitnya sejajar antar baris.
RIGHT_ALIGNED = (KIND_NUM,)

#: Panjang hash yang ditampilkan. Sama di SETIAP tabel; nilai penuh selalu
#: tetap dapat diakses lewat tooltip.
HASH_CHARS = 12

#: Keadaan kosong bawaan. Tiap tabel tetap wajib memberi kalimatnya sendiri
#: yang lebih tepat; ini hanya jaring pengaman supaya tidak pernah ada tabel
#: kosong tanpa keterangan.
EMPTY_FALLBACK = "Belum ada isi."


def short_hash(value, chars: int = HASH_CHARS) -> str:
    """Hash dipendekkan dengan cara yang SAMA di mana pun ia tampil."""
    text = str(value or "")
    return f"{text[:chars]}…" if len(text) > chars else text


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

    if kind == KIND_HASH:
        return short_hash(raw), str(full or raw or "")
    if kind == KIND_TIME:
        return format_time(raw), str(raw or "")
    if kind == KIND_VERSION:
        return "" if raw in (None, "") else f"v{raw}", ""
    if raw is None:
        return "", ""
    # Teks & angka apa adanya; elipsis dikerjakan CSS, tooltip membawa
    # nilai penuhnya sehingga tidak ada yang benar-benar hilang.
    return str(raw), str(full or raw)


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
            inner = (f"<code>{escape(text)}</code>"
                     if col["kind"] == KIND_HASH and text else escape(text))
            cells.append(f'<td class="ids-tbl-{klass}"{attr}>{inner}</td>')
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
