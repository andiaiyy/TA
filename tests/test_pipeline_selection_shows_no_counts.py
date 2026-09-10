"""Pemilihan Research Pipeline berhenti melaporkan keadaan platform.

Di bawah pemilih research pipeline dahulu berdiri tiga angka: berapa dataset di
folder, berapa algoritma pada research yang dipilih, berapa eksperimen pernah
dijalankan. Ketiganya benar dan ketiganya dihitung dari sumber nyata, tetapi
tidak satu pun menuntun langkah berikutnya — dan mereka berdiri tepat di antara
pemilih research pipeline dan pemilih algoritma yang menyusulinya.

Jumlah eksperimen sebelumnya tetap terbaca di halaman Progress & Status, tempat
riwayat memang dibaca.

SATU baris angka sengaja dipertahankan: yang muncul ketika **belum ada dataset
dipilih**. Ia keadaan kosong, bukan ringkasan — "ada lima berkas untuk dipilih"
adalah jawaban atas layar yang sedang tampak kosong, dan itu memang menuntun
langkah berikutnya.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_PATH = REPO_ROOT / "ui" / "views" / "run_experiment.py"
RUN_SRC = RUN_PATH.read_text(encoding="utf-8")
RUN_TREE = ast.parse(RUN_SRC)

# `os.chdir` disengaja: `storage/datasets/` dibaca sebagai jalur RELATIF, sama
# seperti saat aplikasi dijalankan dari akar repo. Tanpa ini AppTest berjalan
# dari direktori sementara, folder datasetnya terbaca kosong, dan baris keadaan
# kosong tidak pernah tergambar — bukan karena kodenya salah.
RUN_APP = '''
import os
import sys
sys.path.insert(0, r"{repo}")
os.chdir(r"{repo}")
import streamlit as st
for key, value in (st.session_state.pop("_preset", None) or {{}}).items():
    st.session_state[key] = value
from ui.views.run_experiment import render
render()
'''


def _counts_calls() -> list[ast.Call]:
    """Setiap panggilan `render_counts(...)` pada modul, sebagai simpul AST."""
    return [n for n in ast.walk(RUN_TREE)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
            == "render_counts"]


def _run_page(tmp_path, preset=None):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "run_page.py"
    script.write_text(RUN_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=600)
    if preset:
        at.session_state["_preset"] = preset
    at.run()
    return at


# ── Baris tiga angka benar-benar tidak ada lagi ──────────────────────────

def test_no_counts_row_carries_three_numbers_any_more():
    """Diperiksa pada BENTUK panggilannya, bukan pada kata-katanya: sebuah
    baris tiga angka tetap tiga angka betapapun labelnya ditulis ulang."""
    panjang = []
    for call in _counts_calls():
        arg = call.args[0] if call.args else None
        assert isinstance(arg, (ast.List, ast.Tuple)), ast.unparse(call)
        panjang.append(len(arg.elts))

    assert panjang, "tidak ada satu pun baris angka; keadaan kosong ikut hilang"
    assert max(panjang) == 1, panjang


@pytest.mark.parametrize("label", ["algoritma", "eksperimen"])
def test_the_two_platform_numbers_are_gone(label):
    for call in _counts_calls():
        assert label not in ast.unparse(call), (label, ast.unparse(call))


def test_the_experiment_counter_is_gone_with_the_row_it_served():
    """Kode yang tidak menggambar apa pun tetap dibaca sebagai fitur."""
    import ui.views.run_experiment as rx

    assert not hasattr(rx, "_experiment_counts")
    assert "def _experiment_counts(" not in RUN_SRC
    # Dan tidak ada sisa pemanggilnya.
    assert "_experiment_counts()" not in RUN_SRC


def test_the_history_count_is_not_quietly_rebuilt_somewhere_else():
    """Penjagaan terhadap "dipindah, bukan dicabut": tidak ada penghitung
    eksperimen baru yang menggantikannya di halaman ini."""
    assert "list_all_experiments" not in RUN_SRC


# ── Keadaan kosong TETAP ada dan tetap berguna ───────────────────────────

def test_the_empty_state_row_survives():
    call = _counts_calls()[0]
    teks = ast.unparse(call)

    assert "dataset" in teks
    assert "len(_ds_options)" in teks


def test_the_empty_state_row_is_drawn_when_nothing_is_picked(tmp_path):
    """Dibuktikan pada halaman yang benar-benar dirender."""
    at = _run_page(tmp_path, {"_run_view": "execute"})

    assert at.exception is None or not at.exception
    # `render_counts` memakai `st.html`, bukan `st.markdown`; elemennya
    # membawa isinya pada `body`, bukan `value`.
    isi = [str(getattr(e, "body", getattr(e, "value", ""))) for e in at.get("html")]
    kotak = [h for h in isi if "ids-count" in h]
    assert kotak, "baris keadaan kosong hilang"
    # Satu sel saja: dataset. Bukan tiga.
    assert kotak[0].count("ids-count-n") == 1, kotak[0]


def test_the_page_still_renders_for_the_catalog_view(tmp_path):
    at = _run_page(tmp_path)

    assert at.exception is None or not at.exception


# ── Sumbernya tetap satu, dan tetap dari sumber nyata ────────────────────

def test_the_shared_counts_renderer_is_still_the_only_one():
    """Tidak ada gaya kedua untuk hal yang sama."""
    assert "st.metric(" not in RUN_SRC
    assert len(_counts_calls()) == 1


def test_the_remaining_number_is_computed_not_typed():
    call = _counts_calls()[0]
    arg = call.args[0]
    sel = arg.elts[0]

    angka = ast.unparse(sel.elts[1])
    assert not angka.isdigit(), angka
    assert "len(" in angka
