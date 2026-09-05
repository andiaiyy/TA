"""
Kerapian TABEL di bagian "Peninjauan Pengajuan".

Masalah yang ditutup di sini bukan "gaya kurang bagus", melainkan gaya yang
TIDAK PERNAH TERPASANG: tabel riwayat versi menuliskan markup berkelas
``ids-cmp``, sedangkan aturan kelas itu hidup sebagai blok ``<style>`` yang
hanya disuntikkan di dalam dialog perbandingan pada halaman Progress & Status.
Di halaman Add Pipeline & Dataset tabelnya karena itu tampil dengan gaya bawaan
peramban — tanpa padding, garis pemisah, header yang dibedakan, maupun perataan
angka.

Test di sini menjaga tiga hal: seluruh tabel memakai SATU penyaji, gayanya ada
di stylesheet GLOBAL (bukan blok yang bisa tertinggal), dan aturan tabelnya
benar-benar berlaku.
"""
import ast
import re
from pathlib import Path

import pytest

from ui.components import registry_view as rv
from ui.components import submission_review as sr
from ui.components import tables as tbl
from ui.components import theme

REPO_ROOT = Path(__file__).resolve().parents[1]
SECTION_FILES = {
    "manage_pipelines": REPO_ROOT / "ui" / "views" / "manage_pipelines.py",
    "contribute": REPO_ROOT / "ui" / "views" / "contribute.py",
    "registry_view": REPO_ROOT / "ui" / "components" / "registry_view.py",
    "submission_review": REPO_ROOT / "ui" / "components" / "submission_review.py",
}
SRC = {name: path.read_text(encoding="utf-8")
       for name, path in SECTION_FILES.items()}

ROWS = [
    {"version": 2, "hash": "a" * 64, "who": "boss",
     "when": "2026-08-30T21:04:11.123456", "note": "naikkan ambang",
     "active": True, "status": "aktif", "state": "ok", "state_reason": "",
     "experiments": 12, "pipeline_id": "p@v2"},
    {"version": 1, "hash": "b" * 64, "who": "andi",
     "when": "2026-08-28T10:00:00", "note": "versi awal", "active": False,
     "status": "tidak aktif", "state": "ok", "state_reason": "",
     "experiments": 3, "pipeline_id": "p@v1"},
]


# ── Satu mekanisme ───────────────────────────────────────────────────────

def test_every_table_in_this_section_uses_the_shared_renderer():
    """Pemeriksaan STRUKTURAL: tidak ada yang menyusun ``<td>`` sendiri."""
    for name, src in SRC.items():
        tree = ast.parse(src)
        # Docstring BOLEH menyebut `<td>` — beberapa memang menjelaskan kenapa
        # markup itu tidak lagi disusun tangan. Yang dilarang adalah markup
        # yang benar-benar dibangun.
        documentation = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    documentation.add(id(body[0].value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or id(node) in documentation:
                continue
            text = node.value
            # Diff kode punya alasan tersendiri (lihat test di bawah); blok
            # label-nilai & kotak angka bukan tabel data.
            if any(k in text for k in ("ids-diff", "ids-facts", "ids-counts")):
                continue
            assert "<td" not in text, (name, text[:60])
            assert "<table" not in text, (name, text[:60])


def test_the_shared_tables_all_emit_the_same_class():
    built = [
        rv.history_table_html(ROWS),
        rv.file_diff_index_html(rv.file_diff_index({"a.py": "x\n"},
                                                   {"a.py": "y\n"})),
        tbl.table_html(rv.ACTIVE_COLUMNS, []),
        tbl.table_html(sr.PENDING_COLUMNS, []),
    ]
    for html in built:
        assert 'class="ids-tbl"' in html
        assert "ids-tbl-scroll" in html
        # Kelas lama yang aturannya tidak terpasang di halaman ini.
        assert "ids-cmp" not in html


def test_the_table_style_lives_in_the_global_stylesheet():
    """Inilah bug aslinya: gaya tabel dulu ada di blok <style> per tampilan.

    Kalau aturan di bawah hilang dari stylesheet global, tabel di bagian ini
    kembali tampil tanpa gaya — dan kegagalannya TIDAK terlihat sebagai error.
    """
    css = theme.stylesheet()
    for rule in (".ids-tbl {", ".ids-tbl th, .ids-tbl td {",
                 ".ids-tbl thead th {", "table-layout: fixed",
                 ".ids-tbl-scroll {", "ids-tbl-num", "ids-tbl-empty"):
        assert rule in css, rule


def test_the_code_diff_keeps_its_own_mechanism_for_a_stated_reason():
    """Diff kode SENGAJA berbeda — dan alasannya tertulis di kodenya.

    Sel tabel data dipendekkan dengan elipsis dan ``white-space: nowrap``.
    Menerapkan itu pada baris KODE akan memotong kode yang sedang ditinjau dan
    meruntuhkan indentasinya — persis informasi yang dicari peninjau.
    """
    css = theme.stylesheet()
    diff = css.split(".ids-diff {")[1].split("}")[0]
    assert "font-family" in diff                      # monospace
    cells = css.split(".ids-diff .ids-diff-t {")[1].split("}")[0]
    assert "white-space: pre" in cells                # spasi dipertahankan
    assert "text-overflow" not in cells               # kode TIDAK dielipsis


# ── Aturan tabel ─────────────────────────────────────────────────────────

def test_text_is_left_aligned_and_numbers_are_right_aligned():
    html = rv.history_table_html(ROWS)
    assert '<td class="ids-tbl-num">12</td>' in html
    assert '<td class="ids-tbl-txt"' in html

    css = theme.stylesheet()
    cells = css.split(".ids-tbl th, .ids-tbl td {")[1].split("}")[0]
    assert "text-align: left" in cells
    num = css.split(
        ".ids-tbl th.ids-tbl-num, .ids-tbl td.ids-tbl-num {")[1].split("}")[0]
    assert "text-align: right" in num
    assert "tabular-nums" in num                      # digit lebar-tetap


def test_the_header_is_distinguished_from_the_body():
    css = theme.stylesheet()
    head = css.split(".ids-tbl thead th {")[1].split("}")[0]
    assert f"font-weight: {theme.WEIGHT_STRONG}" in head
    assert "background" in head                        # bobot DAN latar
    assert "sticky" in head                            # sejajar saat digulir


def test_similar_columns_share_one_width_across_every_table():
    """Kolom hash/waktu/versi berlebar SAMA di semua tabel."""
    tables = {
        "riwayat": rv.HISTORY_COLUMNS,
        "aktif": rv.ACTIVE_COLUMNS,
        "antrean": sr.PENDING_COLUMNS,
        "berkas": rv.FILE_INDEX_COLUMNS,
    }
    by_kind: dict[str, set] = {}
    for columns in tables.values():
        for col in columns:
            if col["kind"] in tbl.COLUMN_WIDTH:
                by_kind.setdefault(col["kind"], set()).add(col["width"])
    for kind, widths in by_kind.items():
        assert len(widths) == 1, (kind, widths)
        assert widths == {tbl.COLUMN_WIDTH[kind]}


def test_no_column_width_is_expressed_in_pixels():
    for width in tbl.COLUMN_WIDTH.values():
        assert width.endswith("rem"), width
    for columns in (rv.HISTORY_COLUMNS, rv.ACTIVE_COLUMNS, sr.PENDING_COLUMNS,
                    rv.FILE_INDEX_COLUMNS):
        for col in columns:
            assert not (col["width"] or "").endswith("px"), col


def test_row_height_padding_and_rules_are_uniform():
    css = theme.stylesheet()
    cells = css.split(".ids-tbl th, .ids-tbl td {")[1].split("}")[0]
    assert f"height: {theme.TABLE_ROW_H}" in cells
    assert f"padding: {theme.TABLE_PAD}" in cells
    # SATU gaya garis: tidak ada campuran tebal-tipis.
    tail = css.split(".ids-tbl")[1]
    borders = re.findall(r"border-bottom:\s*([^;]+);", tail)
    assert all("1px solid" in b for b in borders if "none" not in b), borders


# ── Nilai panjang ────────────────────────────────────────────────────────

def test_long_hashes_are_shortened_the_same_way_everywhere():
    assert tbl.short_hash("a" * 64) == "a" * 12 + "…"
    assert rv.short_hash("a" * 64) == tbl.short_hash("a" * 64)
    assert tbl.short_hash("abc") == "abc"              # pendek: apa adanya
    assert tbl.short_hash(None) == ""


def test_long_values_keep_their_full_value_in_a_tooltip():
    html = rv.history_table_html(ROWS)
    assert "a" * 12 + "…" in html                      # dipendekkan
    assert f'title="{"a" * 64}"' in html               # penuh, tetap terjangkau

    css = theme.stylesheet()
    cells = css.split(".ids-tbl th, .ids-tbl td {")[1].split("}")[0]
    assert "text-overflow: ellipsis" in cells
    assert "white-space: nowrap" in cells              # tinggi baris tetap rata


def test_times_share_one_format_across_tables():
    assert tbl.format_time("2026-08-30T21:04:11.123456") == "2026-08-30 21:04:11"
    assert tbl.format_time("2026-08-30 21:04:11") == "2026-08-30 21:04:11"
    assert tbl.format_time("") == ""
    assert tbl.format_time(None) == ""
    assert tbl.format_time("2026-08-30T21:04:11.9+07:00") == "2026-08-30 21:04:11"

    html = rv.history_table_html(ROWS)
    # Yang DITAMPILKAN seragam…
    assert ">2026-08-30 21:04:11<" in html
    assert ">2026-08-28 10:00:00<" in html
    assert ">2026-08-30T21:04" not in html
    # …sementara presisi penuhnya tetap terjangkau lewat tooltip, sama seperti
    # perlakuan hash: dipendekkan untuk dibaca, tidak ada yang hilang.
    assert 'title="2026-08-30T21:04:11.123456"' in html


# ── Keadaan kosong & jumlah ──────────────────────────────────────────────

@pytest.mark.parametrize("columns,empty", [
    (rv.HISTORY_COLUMNS, rv.HISTORY_EMPTY),
    (rv.FILE_INDEX_COLUMNS, rv.FILE_INDEX_EMPTY),
    (rv.ACTIVE_COLUMNS, rv.EMPTY_STATE),
    (sr.PENDING_COLUMNS, sr.EMPTY_STATE),
])
def test_every_table_states_its_empty_state(columns, empty):
    html = tbl.table_html(columns, [], empty=empty)
    assert "ids-tbl-empty" in html
    assert empty in html
    assert f'colspan="{len(columns)}"' in html
    # Headernya tetap ada, jadi pembaca tahu tabel apa yang kosong.
    assert "<thead>" in html


def test_a_capped_list_states_its_total():
    rows = [{"a": i} for i in range(25)]
    html = tbl.table_html([tbl.column("A", "a")], rows, limit=10)
    assert "10 dari 25" in html
    assert html.count("<tr") == 1 + 10 + 1          # header + 10 baris + hitungan


def test_an_uncapped_list_says_nothing_extra():
    rows = [{"a": i} for i in range(3)]
    html = tbl.table_html([tbl.column("A", "a")], rows, limit=10)
    assert "dari" not in html


# ── Adaptif ──────────────────────────────────────────────────────────────

def test_tables_scroll_instead_of_squashing():
    css = theme.stylesheet()
    scroll = css.split(".ids-tbl-scroll {")[1].split("}")[0]
    assert "overflow-x: auto" in scroll                # kolom banyak → mendatar
    assert "overflow-y: auto" in scroll                # baris banyak → menegak
    assert f"max-height: {theme.TABLE_MAX_H}" in scroll

    table = css.split(".ids-tbl {")[1].split("}")[0]
    assert f"min-width: {theme.TABLE_MIN_W}" in table  # tidak memampat
    assert "width: 100%" in table                      # lebar penuh kolomnya
    assert theme.PROSE_W not in table                  # batas prosa TIDAK kena


# ── AppTest: seluruh sub-tampilan, termasuk keadaan kosong ───────────────

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}


def _script(preset: dict) -> str:
    lines = [
        "import sys",
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})",
        "import streamlit as st",
        "from ui.components import theme",
        "theme.inject()",
        "st.session_state['_current_page'] = 'Add Pipeline & Dataset'",
        f"st.session_state['auth_user'] = {ADMIN!r}",
    ]
    lines += [f"st.session_state[{k!r}] = {v!r}" for k, v in preset.items()]
    lines += ["from ui.views.contribute import render", "render()"]
    return "\n".join(lines)


def _run(tmp_path, preset: dict, name: str):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / name
    script.write_text(_script(preset), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    at.run()
    return at


SUBVIEWS = {
    "pending": {},
    "active": {"_mp_section": "Aktif"},
    "history": {"_mp_section": "Riwayat versi"},
    "compare": {"_mp_section": "Riwayat versi", "_mp_compare": True},
}


@pytest.mark.parametrize("view", sorted(SUBVIEWS))
def test_every_subview_renders_for_a_research_admin(tmp_path, view):
    preset = dict(SUBVIEWS[view], _contrib_mode="review")
    at = _run(tmp_path, preset, f"sub_{view}.py")
    assert not at.exception, (view, at.exception)


@pytest.mark.parametrize("view", sorted(SUBVIEWS))
def test_no_subview_leaves_a_table_empty_without_saying_so(tmp_path, view):
    """Tiap tabel yang tergambar PUNYA isi, atau menyatakan kenapa tidak.

    Halaman ini dirender terhadap basis data proyek yang sebenarnya, jadi
    sebagian tabel memang berisi. Yang dijaga adalah invariannya: tidak pernah
    ada tabel yang kosong tanpa keterangan.
    """
    preset = dict(SUBVIEWS[view], _contrib_mode="review")
    at = _run(tmp_path, preset, f"empty_{view}.py")
    assert not at.exception, (view, at.exception)

    import grid_probe

    # Tabel yang barisnya dapat dipilih tunduk pada aturan yang LEBIH KETAT:
    # ia tidak pernah digambar kosong sama sekali. Judul kolom tanpa satu pun
    # baris terbaca seperti kegagalan memuat, dan pembacanya tidak punya cara
    # membedakannya dari "memang belum ada" — jadi keadaan kosongnya berupa
    # kalimat, bukan tabel hampa.
    for index in range(grid_probe.count(at)):
        assert grid_probe.rows(at, index=index), (view, "tabel kosong digambar")

    if view in ("pending", "active"):
        # Kedua bagian ini SELALU menjawab: entah tabel berisi, entah kalimat
        # yang menyatakan kenapa kosong. Yang dilarang adalah diam.
        text = " ".join(m.value for m in at.markdown)
        assert grid_probe.count(at) or "belum" in text.lower(), (view, text[:200])

    tables = [e.proto.body for e in at.get("html") if "ids-tbl" in e.proto.body]

    for html in tables:
        body = html.split("<tbody>")[1]
        if "ids-tbl-empty" in body:
            # Keterangannya benar-benar berisi, bukan sel kosong.
            stated = body.split('class="ids-tbl-empty"')[1].split("</td>")[0]
            assert stated.split(">", 1)[1].strip(), (view, stated)
        else:
            # Baris isi boleh membawa kelas (mis. `ids-tbl-on` untuk versi
            # aktif), jadi yang dicari adalah ELEMEN barisnya — bukan bentuk
            # `<tr>` tanpa atribut, yang kebetulan benar hanya selama tidak
            # ada baris yang disorot.
            assert "<tr" in body, (view, html[:150])   # ada baris isi
