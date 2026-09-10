"""Ringkasan berkas terpilih dicabut dari halaman Run Experiment.

Setelah sebuah dataset dipilih, halaman itu dahulu melaporkan delapan hal
tentang berkasnya: research pipeline, format, ukuran, jumlah baris, jumlah
kolom, kolom label, jumlah kelas, dan daftar research yang cocok. Seluruhnya
benar dan seluruhnya dihitung dari data yang memang sudah ada, tetapi tidak satu
pun menuntun langkah berikutnya — dan kedelapannya berdiri di antara pemilih
dataset dan bagian Pemilihan Research Pipeline yang menyusulinya.

SATU hal ikut hilang bersamanya, dan itu disengaja: baris "Cocok untuk" adalah
satu-satunya konfirmasi POSITIF bahwa berkasnya dapat dipakai. Sesudah ini,
tanda itu adalah bagian Pemilihan Research Pipeline yang terisi — daftar yang
memang hanya memuat pipeline yang cocok.

Jalur GAGALNYA tidak boleh ikut hilang, dan berkas ini yang menjaganya: berkas
yang tidak cocok dengan research pipeline mana pun tetap mendapat peringatan
dan satu kotak per research beserta tombol uji kecocokannya. Menghapus laporan
boleh; menghapus jalan keluar tidak.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_PATH = REPO_ROOT / "ui" / "views" / "run_experiment.py"
RUN_SRC = RUN_PATH.read_text(encoding="utf-8")
RUN_TREE = ast.parse(RUN_SRC)


def _script(preset: dict) -> str:
    return (
        "import os, sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        f"os.chdir(r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        + "".join(f"st.session_state[{k!r}] = {v!r}\n" for k, v in preset.items())
        + "from ui.views.run_experiment import render\nrender()\n"
    )


def _run(tmp_path, preset):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "run_page.py"
    script.write_text(_script(preset), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    at.run()
    return at


def _pick(kind: str) -> str:
    from ui.views.run_experiment import _all_dataset_options

    paths = [p for p, _ in _all_dataset_options()]
    match = [p for p in paths if kind in p]
    if not match:
        pytest.skip(f"berkas {kind!r} tidak tersedia")
    return match[0]


def _facts_calls() -> list[ast.Call]:
    return [n for n in ast.walk(RUN_TREE)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
            == "render_facts"]


# ── Yang dicabut benar-benar hilang ──────────────────────────────────────

@pytest.mark.parametrize("nama", ["_dataset_facts", "_compatible_names"])
def test_the_dead_builders_are_gone(nama):
    """`_compatible_names` hanya melayani baris itu; ia ikut mati."""
    import re

    import ui.views.run_experiment as rx

    assert not hasattr(rx, nama), nama
    # Batas kata: `declared_dataset_facts` adalah fungsi LAIN yang masih hidup
    # (keterangan yang dinyatakan pengunggah research kontribusi), dan
    # pencocokan substring polos akan menudingnya.
    assert not re.search(rf"(?<![A-Za-z0-9_]){nama}\(", RUN_SRC), nama


def test_no_facts_row_describes_the_file_any_more():
    """Diperiksa pada apa yang DIBANGUN, bukan pada kata-katanya."""
    sumber = [ast.unparse(c) for c in _facts_calls()]

    assert sumber, "seluruh ringkasan hilang; ringkasan pipeline ikut tercabut"
    for teks in sumber:
        assert "_dataset_facts" not in teks, teks


def test_the_pipeline_summary_is_untouched():
    """Ia menerangkan apa yang AKAN DIJALANKAN, bukan melaporkan keadaan."""
    import ui.views.run_experiment as rx

    assert hasattr(rx, "_pipeline_facts")
    assert any("_pipeline_facts" in ast.unparse(c) for c in _facts_calls())


def test_the_comment_no_longer_points_at_a_row_that_is_gone():
    """Kode yang menerangkan dirinya secara keliru menyesatkan pembaca
    berikutnya lebih lama daripada tampilan yang salah."""
    assert 'baris "Cocok untuk"' not in RUN_SRC


# ── Jalur "tidak ada yang cocok" TETAP utuh ──────────────────────────────

def test_an_incompatible_file_still_gets_its_warning_and_its_boxes(tmp_path):
    from ui.i18n.core import lookup

    at = _run(tmp_path, {"_current_page": "Run Experiment",
                         "_run_view": "execute",
                         "dataset_select": _pick("Thursday")})

    assert at.exception is None or not at.exception
    peringatan = " ".join(w.value for w in at.warning)
    assert lookup("re.msg_no_auto_match", "id") in peringatan, peringatan
    assert at.button, "tombol uji kecocokan hilang"


def test_the_compat_machinery_is_still_wired(tmp_path):
    """Kotak dan modalnya dipanggil dari alur utama, bukan tercabut bersama
    baris ringkasannya."""
    assert "_render_compat_boxes(_diag)" in RUN_SRC
    assert "_maybe_render_compat_dialog(_diag)" in RUN_SRC
    assert "_any_compatible(_diag)" in RUN_SRC


# ── Keadaan lain tidak ikut rusak ────────────────────────────────────────

def test_the_empty_state_counts_row_still_stands(tmp_path):
    at = _run(tmp_path, {"_current_page": "Run Experiment",
                         "_run_view": "execute"})

    assert at.exception is None or not at.exception
    kotak = [e.proto.body for e in at.get("html") if "ids-count" in e.proto.body]
    assert kotak, "baris keadaan kosong ikut tercabut"


def test_the_page_renders_for_the_catalog_view(tmp_path):
    at = _run(tmp_path, {"_current_page": "Run Experiment"})

    assert at.exception is None or not at.exception
