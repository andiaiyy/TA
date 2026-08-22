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


# Label tombol pemilih mode: "Masuk sebagai <peran>". Menekannya HANYA membuka
# modal — peran yang dipilih tidak pernah diberikan (lihat test di bawah).
# Label pilihan kini PENDEK (hanya nama peran); penjelasannya di `help=`.
_PICK_LABEL = "Kontributor"


def _open_the_modal(at) -> None:
    next(b for b in at.button if b.label == _PICK_LABEL).click().run()


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


# ── pemilih mode tidak pernah memberi hak ─────────────────────────────────

@pytest.mark.parametrize("label", ["Kontributor", "Research Admin"])
def test_picking_a_role_only_opens_the_modal(app, label):
    """Memilih peran di sidebar TIDAK memberikan peran itu.

    Yang boleh terjadi hanyalah flag modal terbuka; tidak ada identitas maupun
    peran yang masuk ke session_state. Peran sebenarnya selalu ditentukan akun
    & statusnya di basis data.
    """
    app.run()
    next(b for b in app.button if b.label == label).click().run()

    assert _flag(app) == "login"
    state = app.session_state.filtered_state
    assert login.SESSION_USER_KEY not in state, state
    assert not any(v in ("contributor", "research_admin")
                   for v in state.values() if isinstance(v, str)), state


def test_the_picker_never_writes_a_role_into_the_session():
    """Diperiksa pada sumbernya: `render_mode_switch` boleh MEMBACA peran untuk
    ditampilkan, tetapi tidak boleh MENULIS apa pun yang memberi hak."""
    import ast

    src = Path(login.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_mode_switch")

    # Tidak ada penulisan ke session_state sama sekali di dalam fungsi ini.
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                assert not isinstance(t, ast.Subscript), ast.dump(t)

    # Tidak memanggil satu pun fungsi yang mengubah peran/status akun.
    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    for granting in ("set_user_role", "set_user_status", "create_user",
                     "create_user_as", "register_account"):
        assert granting not in called, granting

    # Satu-satunya jalur yang menyentuh session_state adalah pembuka modal.
    assert "request_auth_dialog" in called


def test_the_picker_offers_exactly_the_known_roles():
    from database.models import ALL_ROLES

    assert list(login._PICKABLE_ROLES) == list(ALL_ROLES)


def test_a_signed_in_user_sees_their_role_and_a_way_out(app):
    app.session_state["auth_user"] = {"username": "ai", "role": "research_admin",
                                      "status": "active"}
    app.run()
    labels = [b.label for b in app.button]
    # Kembali ke mode pengunjung = keluar dari akun (keterangannya di help=).
    assert "Pengunjung" in labels
    keluar = next(b for b in app.button if b.label == "Pengunjung")
    assert "Keluar" in (keluar.help or "")

    # Peran aktif tampil pada LABEL pemilih mode, bukan sebagai baris tambahan.
    roles = [b for b in app.button if b.label == "Research Admin"]
    assert roles and roles[0].disabled is True
