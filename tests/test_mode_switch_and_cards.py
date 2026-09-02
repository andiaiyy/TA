"""
Perpindahan mode, akun kontributor aktif otomatis, dan kartu admin.

Tiga hal dijaga di sini:

* **Pemilih mode adalah TAMPILAN dari keadaan nyata.** Nilai dropdown tidak
  boleh pernah menunjukkan peran yang tidak dimiliki, dan keluar harus
  membersihkan SELURUH penanda sesi — bukan hanya identitasnya.
* **Akun Kontributor langsung aktif.** Tidak ada lagi antrean persetujuan AKUN.
  Persetujuan pengajuan PIPELINE tetap ada dan TIDAK boleh ikut hilang.
* **Kartu admin hanya untuk Research Admin** — dan penyembunyian itu BUKAN
  pengaman: izin tetap ditegakkan di fungsi aksinya.
"""
import ast
import sqlite3
from pathlib import Path

import pytest

from database.models import (
    ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN, STATUS_ACTIVE, STATUS_PENDING,
)
from orchestrator import auth_service as auth
from ui.components import upload_cards as uc
from ui.i18n.core import lookup

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGIN_SRC = (REPO_ROOT / "ui" / "views" / "login.py").read_text(encoding="utf-8")
CONTRIB_SRC = (REPO_ROOT / "ui" / "views"
               / "contribute.py").read_text(encoding="utf-8")

ADMIN = {"username": "boss", "role": ROLE_RESEARCH_ADMIN, "status": STATUS_ACTIVE}
CONTRIB = {"username": "andi", "role": ROLE_CONTRIBUTOR, "status": STATUS_ACTIVE}


# ── BAGIAN 1: pemilih mode ───────────────────────────────────────────────

def test_the_dropdown_takes_its_value_only_from_session_state():
    """Dua sumber kebenaran untuk satu widget = kedipan.

    Memberi ``index=`` SEKALIGUS menulis ``session_state`` untuk kunci yang
    sama membuat Streamlit memperingatkan ("created with a default value but
    also had its value set via the Session State API") dan membuat pilihan
    tampak melompat balik. Nilainya kini datang dari satu tempat saja.
    """
    body = LOGIN_SRC.split("def render_mode_switch(")[1].split("\ndef ")[0]
    call = body.split("st.selectbox(")[1].split(")")[0]
    assert "key=_MODE_PICK_KEY" in call
    assert "index=" not in call


def test_choosing_a_role_never_writes_a_role_into_the_session():
    """Pemilih mode tidak boleh MEMBERIKAN peran — hanya membuka jalur masuk."""
    func = next(n for n in ast.walk(ast.parse(LOGIN_SRC))
                if isinstance(n, ast.FunctionDef)
                and n.name == "render_mode_switch")
    for node in ast.walk(func):
        # Larangan: st.session_state[SESSION_USER_KEY] = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    assert "SESSION_USER_KEY" not in ast.dump(target), \
                        ast.dump(node)


def test_logout_clears_every_session_marker():
    body = LOGIN_SRC.split("def logout(")[1].split("\ndef ")[0]
    assert "SESSION_USER_KEY" in body
    assert "DIALOG_KEYS" in body                 # flag modal
    assert "clear_view_state()" in body          # penanda sub-tampilan
    assert "close_auth_dialog()" in body


def test_view_state_is_swept_by_prefix_not_by_a_second_list():
    """Daftar nama kedua pasti tertinggal; awalan tidak."""
    from ui.components.page_flags import VIEW_STATE_PREFIXES

    assert "_contrib" in VIEW_STATE_PREFIXES
    assert "_mp_" in VIEW_STATE_PREFIXES

    # Setiap penanda sub-tampilan yang benar-benar dipakai kedua view harus
    # tertangkap oleh salah satu awalan.
    for src in (CONTRIB_SRC,
                (REPO_ROOT / "ui" / "views"
                 / "manage_pipelines.py").read_text(encoding="utf-8")):
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Name)
                        and target.id.endswith("_KEY")
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                        and node.value.value.startswith("_")):
                    key = node.value.value
                    assert key.startswith(VIEW_STATE_PREFIXES), key


def test_one_action_triggers_exactly_one_rerun():
    """Satu aksi cukup satu rerun — rerun beruntun yang membuat tersendat."""
    body = LOGIN_SRC.split("def render_mode_switch(")[1].split("\ndef ")[0]
    branch = body.split("if choice != current:")[1]
    assert branch.count("st.rerun()") == 1


def test_selecting_the_active_mode_does_nothing():
    """Perbandingan `choice != current` yang menjaganya — bukan cabang khusus."""
    body = LOGIN_SRC.split("def render_mode_switch(")[1].split("\ndef ")[0]
    assert "if choice != current:" in body


# ── BAGIAN 2: akun langsung aktif ────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    from database.db import init_db

    path = str(tmp_path / "users.db")
    init_db(path)

    def _conn(p=None):
        conn = sqlite3.connect(p or path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("database.db.get_connection", _conn)
    monkeypatch.setattr("orchestrator.auth_service.get_connection", _conn)
    return path


def test_registration_produces_an_active_account_that_can_upload(db):
    user = auth.register_account("pendatang", "rahasia123", "rahasia123",
                                 reason="riset", db_path=db)
    assert user["status"] == STATUS_ACTIVE
    assert user["role"] == ROLE_CONTRIBUTOR

    stored = auth.get_user("pendatang", db)
    assert stored["status"] == STATUS_ACTIVE
    # Langsung boleh mengunggah — tanpa persetujuan siapa pun.
    assert auth.can_upload(dict(stored))
    auth.require_upload(dict(stored))          # tidak melempar


def test_registration_can_never_grant_research_admin(db):
    user = auth.register_account("penyusup", "rahasia123", "rahasia123",
                                 db_path=db)
    assert user["role"] == ROLE_CONTRIBUTOR
    assert not auth.is_research_admin(dict(user))
    # Peran tidak diambil dari masukan pengguna: tidak ada parameter peran.
    import inspect
    assert "role" not in inspect.signature(auth.register_account).parameters


def test_the_traceability_fields_are_still_recorded(db):
    """Akun tidak lagi menunggu, tetapi jejaknya tetap dicatat."""
    auth.register_account("tercatat", "rahasia123", "rahasia123",
                          reason="untuk skripsi", db_path=db)
    stored = auth.get_user("tercatat", db)
    assert stored["requested_at"]
    assert stored["reason"] == "untuk skripsi"


def test_legacy_pending_accounts_are_activated_without_losing_data(db):
    """Akun lama yang menunggu DIAKTIFKAN, bukan dihapus."""
    from database.migration import MIGRATIONS

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO users (username, password_hash, role, status, "
        "created_at, requested_at, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lama", "hash", ROLE_CONTRIBUTOR, STATUS_PENDING,
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "menunggu sejak lama"))
    conn.commit()

    migration = next(m for m in MIGRATIONS if m["version"] == 22)
    conn.execute(migration["sql"])
    conn.commit()

    row = conn.execute(
        "SELECT * FROM users WHERE username = 'lama'").fetchone()
    conn.close()
    assert row["status"] == STATUS_ACTIVE            # status berpindah…
    assert row["password_hash"] == "hash"            # …sisanya utuh
    assert row["role"] == ROLE_CONTRIBUTOR
    assert row["reason"] == "menunggu sejak lama"
    assert row["requested_at"] == "2026-01-01T00:00:00"


def test_pipeline_submissions_still_require_approval():
    """Yang dihapus persetujuan AKUN — bukan persetujuan PIPELINE."""
    from orchestrator import submission_service as ss

    src = (REPO_ROOT / "orchestrator"
           / "submission_service.py").read_text(encoding="utf-8")
    body = src.split("def approve_submission(")[1].split("\ndef ")[0]
    assert "require_approve(" in body
    assert hasattr(ss, "approve_submission")
    assert hasattr(ss, "reject_submission")


def test_no_ui_text_still_promises_account_approval():
    """Sisa kalimat 'menunggu persetujuan' untuk AKUN sudah dibersihkan."""
    for src, name in ((LOGIN_SRC, "login"), (CONTRIB_SRC, "contribute")):
        tree = ast.parse(src)
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                body = getattr(node, "body", None) or []
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docs.add(id(body[0].value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docs):
                text = node.value.lower()
                # "menunggu tinjauan" (pengajuan PIPELINE) tetap boleh.
                assert "pendaftaran menunggu" not in text, (name, node.value)
                assert "menunggu persetujuan" not in text, (name, node.value)


# ── BAGIAN 3: kartu admin ────────────────────────────────────────────────

def test_a_contributor_sees_only_the_two_upload_cards():
    cards = uc.visible_cards(may_approve=False, may_manage_users=False,
                             signed_in=True)
    assert [c["mode"] for c in cards] == ["pipeline", "dataset"]


def test_a_research_admin_sees_all_four_cards():
    cards = uc.visible_cards(may_approve=True, may_manage_users=True,
                             signed_in=True)
    assert [c["mode"] for c in cards] == ["pipeline", "dataset", "review",
                                          "users"]


def test_a_visitor_sees_the_two_upload_cards_and_a_one_line_note():
    cards = uc.visible_cards(may_approve=False, may_manage_users=False,
                             signed_in=False)
    assert [c["mode"] for c in cards] == ["pipeline", "dataset"]
    # Keberadaan jalur admin tetap disebut — satu baris, tanpa kartunya.
    assert "Research Admin" in lookup(uc.VISITOR_ADMIN_NOTE, "id")
    assert "Research Admin" in lookup(uc.VISITOR_ADMIN_NOTE, "en")
    assert "\n" not in uc.VISITOR_ADMIN_NOTE
    assert len(uc.VISITOR_ADMIN_NOTE) <= 90


def test_the_card_grid_stays_even_in_every_state():
    """Dua kartu maupun empat kartu sama-sama mengisi baris penuh."""
    for count in (2, 4):
        cards = uc.CARDS[:count]
        rows = uc.card_rows(cards)
        assert all(len(row) == uc.CARDS_PER_ROW for row in rows), count
        assert sum(len(row) for row in rows) == count


# ── BAGIAN 3: menyembunyikan BUKAN pengaman ──────────────────────────────

@pytest.mark.parametrize("actor", [None, CONTRIB])
def test_review_actions_are_refused_at_the_function_for_non_admins(actor):
    with pytest.raises(auth.AuthError):
        auth.require_approve(actor)


@pytest.mark.parametrize("actor", [None, CONTRIB])
def test_user_management_is_refused_at_the_function_for_non_admins(actor):
    with pytest.raises(auth.AuthError):
        auth.require_manage_users(actor)


def test_a_research_admin_passes_both_gates():
    auth.require_approve(ADMIN)
    auth.require_manage_users(ADMIN)


def test_hiding_the_cards_did_not_remove_the_function_level_gate():
    """Kartu boleh disembunyikan; gerbangnya harus tetap dipanggil."""
    for src, fn in ((CONTRIB_SRC, "_render_review_flow"),
                    (CONTRIB_SRC, "_render_users_flow")):
        body = src.split(f"def {fn}(")[1].split("\ndef ")[0]
        assert "can_approve(" in body or "can_manage_users(" in body, fn


# ── AppTest: alur perpindahan mode yang sebenarnya ───────────────────────

MODE_SCRIPT = f'''
import sys
sys.path.insert(0, r"{REPO_ROOT}")
import streamlit as st
from ui.views.login import render_mode_switch
st.session_state.setdefault("_current_page", "Add Pipeline & Dataset")
render_mode_switch()
'''

SUBVIEW_STATE = {
    "_contrib_mode": "review",
    "_mp_section": "Riwayat versi",
    "_mp_edit": "uploaded.contoh@v2",
    "_mp_package": {"up.py": "x = 1"},
}


def _mode_app(tmp_path, name, **state):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / name
    script.write_text(MODE_SCRIPT, encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=120)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_a_visitor_choosing_contributor_only_opens_the_login_path(tmp_path):
    at = _mode_app(tmp_path, "visitor.py")
    assert at.selectbox[0].value == "Pengunjung"

    at.selectbox[0].select("Kontributor").run()
    # Jalur masuk terbuka…
    assert "_auth_dialog" in at.session_state
    # …tetapi TIDAK ada peran yang diberikan, dan dropdown kembali jujur.
    assert "auth_user" not in at.session_state
    assert at.selectbox[0].value == "Pengunjung"


def test_closing_the_modal_without_signing_in_leaves_nothing_behind(tmp_path):
    at = _mode_app(tmp_path, "closed.py")
    at.selectbox[0].select("Kontributor").run()

    del at.session_state["_auth_dialog"]        # modal ditutup tanpa masuk
    at.run()

    assert at.selectbox[0].value == "Pengunjung"
    assert "auth_user" not in at.session_state
    assert "_mode_acted" not in at.session_state


def test_an_admin_choosing_visitor_signs_out_and_clears_the_subview(tmp_path):
    at = _mode_app(tmp_path, "signout.py", auth_user=ADMIN, **SUBVIEW_STATE)
    assert at.selectbox[0].value == "Research Admin"

    at.selectbox[0].select("Pengunjung").run()

    assert at.selectbox[0].value == "Pengunjung"
    assert "auth_user" not in at.session_state
    for key in SUBVIEW_STATE:
        assert key not in at.session_state, key


def test_an_admin_choosing_another_role_signs_out_then_offers_sign_in(tmp_path):
    """Keputusan: memilih peran lain = keluar lalu masuk sebagai akun lain."""
    at = _mode_app(tmp_path, "swap.py", auth_user=ADMIN, **SUBVIEW_STATE)
    at.selectbox[0].select("Kontributor").run()

    assert "auth_user" not in at.session_state      # sesi lama diakhiri
    assert "_auth_dialog" in at.session_state       # jalur masuk terbuka
    assert at.selectbox[0].value == "Pengunjung"    # keadaan yang NYATA
    for key in SUBVIEW_STATE:
        assert key not in at.session_state, key


def test_selecting_the_active_mode_opens_nothing(tmp_path):
    at = _mode_app(tmp_path, "same.py", auth_user=ADMIN)
    at.selectbox[0].select("Research Admin").run()

    assert "_auth_dialog" not in at.session_state
    assert at.session_state["auth_user"] == ADMIN
    assert at.selectbox[0].value == "Research Admin"


@pytest.mark.parametrize("user", [None, CONTRIB, ADMIN])
def test_the_mode_control_always_shows_the_real_mode(tmp_path, user):
    state = {"auth_user": user} if user else {}
    at = _mode_app(tmp_path, f"real_{user['role'] if user else 'guest'}.py",
                   **state)
    expected = {None: "Pengunjung", ROLE_CONTRIBUTOR: "Kontributor",
                ROLE_RESEARCH_ADMIN: "Research Admin"}[
        user["role"] if user else None]
    assert at.selectbox[0].value == expected
    assert not at.exception
