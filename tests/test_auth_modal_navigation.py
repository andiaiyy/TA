"""End-to-end regression for "the sign-in modal opens by itself".

Symptom: the modal reappeared every time the user opened another page, even
though it should only ever open on a press of "Masuk".

Two causes, both about the flag's lifecycle rather than about how the dialog is
called:

  1. ``st.dialog`` defaults to ``on_dismiss="ignore"`` — closing the modal with
     X / Esc / a click outside closes it in the browser only. The flag in
     ``session_state`` survived, so the next rerun (typically the click on
     another page in the menu) rendered the modal again.
  2. The flag is read from ``ui/app.py``, which runs on *every* page. Unlike
     ``_detail_id`` (view_results) and ``_compat_check_type`` (run_experiment),
     which are only ever read inside their own page's ``render()``, this flag
     could survive a page change.

These tests drive the real functions through ``AppTest``. They live in their own
module on purpose: ``tests/test_login_gate.py`` has an autouse fixture that
replaces ``streamlit.session_state`` process-wide, which would make the app
under test write to a stub dict instead of the session AppTest inspects.
"""
from pathlib import Path

import pytest

import ui.views.login as login

REPO_ROOT = Path(__file__).resolve().parents[1]

# Meniru dua baris ui/app.py yang mengurus identitas (switch mode + modal),
# tanpa menjalankan app.py sungguhan — script itu menjalankan init_db & seed
# admin saat diimpor. Bahwa app.py memanggilnya persis begini dijaga oleh
# test_login_gate.py::test_the_dialog_is_rendered_from_the_main_flow.
NAV_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
from ui.views.login import maybe_render_auth_dialog, render_mode_switch

page = st.session_state.get("_test_page", "Progress & Status")
st.session_state["_current_page"] = page
render_mode_switch()
maybe_render_auth_dialog(page)
st.write("halaman aktif: " + page)
'''


@pytest.fixture
def app(tmp_path):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "nav_app.py"
    script.write_text(NAV_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    return AppTest.from_file(str(script), default_timeout=300)


def _dialog_is_open(at) -> bool:
    """Modal terbuka bila isinya ikut terender.

    Ditandai tombol "Tutup" milik modal: panel sidebar sengaja tidak memuat
    tombol/input itu (lihat test_the_sidebar_panel_has_no_credential_inputs).
    """
    return any(b.label == "Tutup" for b in at.button)


def _flag(at):
    """Nilai flag modal, lewat `filtered_state` (dict biasa).

    `key in at.session_state` bisa melempar KeyError bila ada kunci widget yang
    baru saja hilang dari halaman — kejadian normal setelah modal ditutup.
    """
    return at.session_state.filtered_state.get(login._DIALOG_KEY)


def _open_the_modal(at) -> None:
    next(b for b in at.button if b.label == "Masuk").click().run()


def test_the_modal_stays_closed_until_the_button_is_pressed(app):
    """Membuka halaman saja tidak pernah memunculkan modal."""
    app.run()
    assert app.exception is None or not app.exception
    assert not _dialog_is_open(app)
    assert _flag(app) is None


def test_repeated_reruns_never_summon_the_modal(app):
    """Rerun berkali-kali tanpa menekan tombol tetap tidak memunculkannya."""
    for _ in range(3):
        app.run()
        assert not _dialog_is_open(app)
    assert _flag(app) is None


def test_the_button_opens_the_modal_on_its_own_page(app):
    app.session_state["_test_page"] = "Run Experiment"
    app.run()
    assert not _dialog_is_open(app)

    _open_the_modal(app)
    assert _flag(app) == "login"
    assert _dialog_is_open(app)


def test_the_modal_does_not_follow_the_user_to_another_page(app):
    """Inti bug: buka halaman A → tekan Masuk → pindah ke B → tidak ada modal."""
    app.session_state["_test_page"] = "Run Experiment"
    app.run()
    _open_the_modal(app)
    assert _dialog_is_open(app)

    app.session_state["_test_page"] = "Progress & Status"     # pindah halaman
    app.run()
    assert app.exception is None or not app.exception
    assert not _dialog_is_open(app), "modal tidak boleh ikut ke halaman lain"
    assert _flag(app) is None

    app.run()                                                 # rerun berikutnya
    assert not _dialog_is_open(app)


def test_the_modal_does_not_come_back_on_a_third_page(app):
    """Berpindah beberapa halaman berturut-turut tetap bersih."""
    app.session_state["_test_page"] = "Add Pipeline & Dataset"
    app.run()
    _open_the_modal(app)
    assert _dialog_is_open(app)

    for page in ("Run Experiment", "Progress & Status", "Add Pipeline & Dataset"):
        app.session_state["_test_page"] = page
        app.run()
        assert not _dialog_is_open(app), page


def test_closing_with_the_tutup_button_clears_the_flag(app):
    """Tombol Tutup membuang flag — dan tanpa flag modal tidak pernah dirender.

    Yang diperiksa di sini adalah flag-nya, bukan pohon elemen sesudahnya:
    `st.rerun()` di dalam tombol Tutup membatalkan run itu, sehingga AppTest
    memegang pohon run yang dibatalkan (masih memuat widget modal) sementara
    Streamlit sudah membuang widget-widget itu dari session_state — memaksa
    `run()` lagi hanya menabrak keterbatasan AppTest, bukan bug aplikasi.
    Bahwa "tanpa flag = tidak dirender" berlaku dijamin oleh
    test_login_gate.py::test_the_dialog_is_not_reopened_without_a_flag, dan
    ujung-ke-ujungnya oleh test_the_modal_does_not_follow_the_user_to_another_page.
    """
    app.run()
    _open_the_modal(app)
    assert _dialog_is_open(app)
    assert _flag(app) == "login"

    next(b for b in app.button if b.label == "Tutup").click().run()
    assert _flag(app) is None


def test_reopening_after_a_page_change_still_works(app):
    """Membersihkan flag tidak boleh membuat tombolnya mati di halaman baru."""
    app.session_state["_test_page"] = "Run Experiment"
    app.run()
    _open_the_modal(app)

    app.session_state["_test_page"] = "Progress & Status"
    app.run()
    assert not _dialog_is_open(app)

    _open_the_modal(app)                     # tekan lagi di halaman baru
    assert _dialog_is_open(app)
    assert _flag(app) == "login"
