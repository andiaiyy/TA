"""Distribusi kelas adalah fakta PROFIL, dan tempatnya di dalam kartunya.

Angkanya sudah dihitung sejak lama — `build_profile` mengembalikan
`class_counts` dari sampel yang sama dengan sisa profil. Yang salah adalah
letaknya: ia digambar SESUDAH `st.container(border=True)` ditutup, sehingga
kartu "Profil dataset" memuat lima pasang label–nilai sementara distribusi
kelas melayang di bawahnya sebagai daftar tersendiri. Pembacanya tidak punya
alasan menyimpulkan keduanya satu hal.

Yang berubah hanya bentuk dan letaknya. Angkanya persis sama, dari sampel yang
sama, dan tetap disertai catatan "berdasarkan N baris" yang menyatakan apakah
angka itu dari seluruh berkas atau dari cuplikan.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import ui.views.contribute as c

PROFIL_CSV = {
    "detected_format": "csv", "rows_read": 600, "sampled": False,
    "encoding": "utf-8", "malformed_lines": 0,
    "columns": ["durasi", "byte_masuk", "serangan"], "column_count": 3,
    "label_column": "serangan", "class_counts": {0: 300, 1: 300},
    "numeric_columns": 2, "non_numeric_columns": 1,
}


# ── Nilainya: angka yang sama, satu baris ────────────────────────────────

def test_a_binary_split_reads_as_one_line():
    teks = c._class_distribution_text({"class_counts": {0: 300, 1: 300}})

    assert "`0` 300 (50.0%)" in teks
    assert "`1` 300 (50.0%)" in teks


def test_the_percentages_follow_the_real_imbalance():
    """HIKARI2021 sangat timpang; persentasenya harus mengatakan itu."""
    teks = c._class_distribution_text({"class_counts": {0: 5580, 1: 420}})

    assert "(93.0%)" in teks and "(7.0%)" in teks


def test_many_classes_do_not_stretch_the_row_without_end():
    """Satu baris kartu tidak boleh tumbuh sepanjang daftar kelasnya."""
    teks = c._class_distribution_text({"class_counts": {i: 10 for i in range(9)}})

    assert teks.count("·") == c._PROFILE_MAX_CLASSES
    assert "+3 kelas lain" in teks


def test_ndjson_reports_an_indication_not_a_distribution():
    """Berkas EVE tidak punya kolom label — labelnya dibentuk pipeline dari
    alert. Menyebutnya "distribusi kelas" akan menyatakan sesuatu yang belum
    ada."""
    teks = c._class_distribution_text(
        {"detected_format": "ndjson", "tls_rows": 12345, "alert_rows": 678})

    assert "Event TLS 12,345" in teks
    assert "calon kelas attack" in teks


def test_nothing_known_says_nothing():
    assert c._class_distribution_text({}) == ""
    assert c._class_distribution_text({"class_counts": {}}) == ""


# ── Letaknya: DI DALAM kartu ─────────────────────────────────────────────

def _render(profile):
    """Gambar profilnya; kembalikan (isi di dalam kartu, isi di luar kartu)."""
    dalam, luar, di_kartu = [], [], {"aktif": False}

    class _Ctx:
        def __enter__(self):
            di_kartu["aktif"] = True
            return self

        def __exit__(self, *a):
            di_kartu["aktif"] = False
            return False

    class _Col:
        def markdown(self, s=None, **kw):
            (dalam if di_kartu["aktif"] else luar).append(str(s))

    def _markdown(s=None, **kw):
        (dalam if di_kartu["aktif"] else luar).append(str(s))

    with patch.object(c.st, "container", lambda **kw: _Ctx()), \
         patch.object(c.st, "columns", lambda spec, **kw: [_Col(), _Col()]), \
         patch.object(c.st, "subheader", lambda s, **kw: luar.append(str(s))), \
         patch.object(c.st, "markdown", _markdown), \
         patch.object(c.st, "expander", lambda *a, **kw: _Ctx()), \
         patch.object(c.st, "code", lambda *a, **kw: None):
        c._render_dataset_profile(profile, "trafik_kampus.csv", 12363)
    return dalam, luar


def test_the_distribution_sits_inside_the_profile_card():
    dalam, luar = _render(PROFIL_CSV)

    assert "Distribusi kelas" in dalam
    assert "Distribusi kelas" not in luar
    assert any("300 (50.0%)" in x for x in dalam)


def test_it_stands_beside_the_other_profile_facts():
    """Bentuknya sama dengan baris profil lain: label di kiri, nilai di kanan."""
    dalam, _luar = _render(PROFIL_CSV)
    labels = dalam[::2]

    for wajib in ("Berkas", "Ukuran", "Format", "Baris", "Tipe data",
                  "Kolom label", "Distribusi kelas"):
        assert wajib in labels, wajib


def test_an_ndjson_profile_is_labelled_as_an_indication():
    dalam, _luar = _render({
        "detected_format": "ndjson", "rows_read": 5000, "sampled": True,
        "columns": ["timestamp", "event_type"], "column_count": 2,
        "class_counts": {}, "tls_rows": 900, "alert_rows": 12})

    assert "Indikasi kelas" in dalam
    assert "Distribusi kelas" not in dalam


def test_the_sample_caveat_still_follows_the_card():
    """Catatan "dari N baris" berlaku untuk SELURUH kartu, jadi ia tetap
    berada di bawahnya — dan tetap membedakan sampel dari berkas penuh."""
    _dalam, luar = _render(PROFIL_CSV)
    assert any("seluruh 600 baris" in x for x in luar)

    _dalam2, luar2 = _render({**PROFIL_CSV, "sampled": True, "rows_read": 500})
    assert any("500 baris pertama" in x for x in luar2)


def test_a_profile_without_classes_shows_no_empty_row():
    dalam, _luar = _render({**PROFIL_CSV, "class_counts": {}})

    assert "Distribusi kelas" not in dalam
    assert "Indikasi kelas" not in dalam


# ── Sumber angkanya tidak berubah ────────────────────────────────────────

def test_the_numbers_still_come_from_build_profile():
    """Tidak ada perhitungan baru dan tidak ada pembacaan berkas tambahan —
    `_render_dataset_profile` tetap hanya membaca dict yang disodorkan."""
    import ast
    from pathlib import Path

    source = Path(c.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef)
              and n.name == "_class_distribution_text")
    body = ast.get_source_segment(source, fn)

    for terlarang in ("open(", "read_csv", "parse_dataset", "get_connection"):
        assert terlarang not in body, terlarang
