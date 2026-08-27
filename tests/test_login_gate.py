"""Tests for the phase-2 identity model: visitor mode + per-action protection.

Replaces the phase-1 assumptions (a global login gate in ui/app.py). The model
now is: the app opens WITHOUT login, every page is reachable, viewing/running
experiments is open to everyone, and only risky actions (upload, approve,
manage users) require an account.
"""
import ast
import re
from pathlib import Path

import pytest

import ui.views.login as login

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_session(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(login.st, "session_state", state)
    return state


# ── session helpers ───────────────────────────────────────────────────────

def test_no_user_means_visitor_mode(clean_session):
    assert login.current_user() is None
    assert login.is_authenticated() is False


def test_authenticated_when_a_user_is_in_session(clean_session):
    clean_session[login.SESSION_USER_KEY] = {"username": "rina", "role": "contributor"}
    assert login.is_authenticated() is True
    assert login.current_user()["username"] == "rina"


@pytest.mark.parametrize("garbage", [None, {}, {"role": "contributor"}, "rina", 42])
def test_malformed_session_values_are_treated_as_visitor(clean_session, garbage):
    clean_session[login.SESSION_USER_KEY] = garbage
    assert login.is_authenticated() is False


def test_logout_returns_to_visitor_mode(clean_session):
    clean_session[login.SESSION_USER_KEY] = {"username": "rina", "role": "contributor"}
    clean_session["_auth_failed_attempts"] = 2
    login.logout()
    assert login.SESSION_USER_KEY not in clean_session
    assert "_auth_failed_attempts" not in clean_session


def test_logout_does_not_touch_experiment_state(clean_session):
    """Berganti identitas tidak boleh mengganggu eksperimen yang berjalan."""
    clean_session[login.SESSION_USER_KEY] = {"username": "rina", "role": "contributor"}
    clean_session["polling_experiment_id"] = "exp-123"
    clean_session["last_result"] = {"success": True}
    login.logout()
    assert clean_session["polling_experiment_id"] == "exp-123"
    assert clean_session["last_result"] == {"success": True}


# ── what must never be stored ─────────────────────────────────────────────

def test_only_identity_fields_are_written_to_the_session():
    """Hanya username, peran, dan status — tidak pernah password/hash."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    stored_keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    stored_keys.add(key.value)
    assert stored_keys == {"username", "role", "status"}, stored_keys


def test_failure_message_does_not_leak_which_field_was_wrong():
    src = Path(login.__file__).read_text(encoding="utf-8")
    assert "Username atau password salah." in src
    for leaky in ("tidak ditemukan", "user tidak ada", "username tidak dikenal"):
        assert leaky not in src.lower()


def test_password_input_is_masked():
    assert 'type="password"' in Path(login.__file__).read_text(encoding="utf-8")


# ── the app opens WITHOUT a login gate ────────────────────────────────────

def _app_source() -> str:
    return (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")


def test_app_has_no_global_login_gate():
    """Regresi terhadap model lama: tidak ada st.stop() yang memblokir halaman."""
    src = _app_source()
    assert "if not is_authenticated():" not in src
    assert "render_login()" not in src
    assert "st.stop()" not in src


def test_every_page_is_still_dispatched():
    src = _app_source()
    for page in ("Progress & Status", "Run Experiment", "Add Pipeline & Dataset"):
        assert f'page == "{page}"' in src
    for module in ("view_results", "run_experiment", "contribute"):
        assert module in src


def test_mode_switch_is_rendered_after_the_page_menu():
    """Switch mode berada di BAWAH menu halaman (sidebar), bukan di depan."""
    src = _app_source()
    menu = src.index("page = _select_page()")
    switch = src.index("render_mode_switch()", menu)
    dispatch = src.index('if page == "Progress & Status"')
    assert menu < switch < dispatch


def test_mode_switch_sits_under_a_divider_in_the_sidebar():
    src = Path(login.__file__).read_text(encoding="utf-8")
    body = src.split("def render_mode_switch()")[1].split("\ndef ")[0]
    assert "with st.sidebar:" in body
    assert "st.divider()" in body
    assert "Mode pengunjung" in body
    assert "Keluar" in body


def test_the_sidebar_panel_has_no_credential_inputs():
    """Identitas ringkas saja — pengisian dipindah seluruhnya ke modal."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    body = src.split("def render_mode_switch()")[1].split("\ndef ")[0]
    for widget in ("st.text_input", "st.text_area", "st.form("):
        assert widget not in body, widget


def test_sidebar_button_only_sets_a_flag(monkeypatch):
    """Regresi: dialog TIDAK boleh dipanggil dari dalam blok sidebar."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    body = src.split("def render_mode_switch()")[1].split("\ndef ")[0]
    assert "request_auth_dialog(" in body

    # Diperiksa lewat AST, bukan substring: `request_auth_dialog` mengandung
    # `_auth_dialog` sebagai bagian namanya.
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "render_mode_switch")
    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_auth_dialog" not in called        # tidak memanggil modal langsung
    assert "request_auth_dialog" in called

    state: dict = {}
    monkeypatch.setattr(login.st, "session_state", state)
    login.request_auth_dialog("login")
    assert state == {"_auth_dialog": "login"}


def test_the_dialog_is_rendered_from_the_main_flow(monkeypatch):
    """Dipanggil dari ui/app.py di luar `with st.sidebar`, memakai flag."""
    app_src = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    # Halaman aktif ikut dikirim supaya flag tidak terbawa pindah halaman.
    assert "maybe_render_auth_dialog(page)" in app_src
    # Tidak berada di dalam blok sidebar mana pun di app.py.
    for line in app_src.splitlines():
        if "maybe_render_auth_dialog(" in line and not line.strip().startswith("#"):
            assert not line.startswith(" "), line

    opened: list = []
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", {"_auth_dialog": "login"})
    login.maybe_render_auth_dialog()
    assert opened == [True]


def test_the_dialog_is_not_reopened_without_a_flag(monkeypatch):
    opened: list = []
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", {})
    login.maybe_render_auth_dialog()
    assert opened == []


def test_closing_clears_the_flag(monkeypatch):
    state = {"_auth_dialog": "signup"}
    monkeypatch.setattr(login.st, "session_state", state)
    login.close_auth_dialog()
    assert "_auth_dialog" not in state


# ── siklus hidup flag: modal tidak boleh muncul sendiri ───────────────────
# Regresi untuk bug "modal masuk/daftar terbuka setiap kali membuka halaman
# lain": flag `_auth_dialog` dibaca dari ui/app.py — alur yang jalan di SEMUA
# halaman — jadi ia harus dibersihkan di setiap jalur keluar.

def test_nothing_opens_the_dialog_without_a_button_press(monkeypatch):
    """(a) Tanpa penekanan tombol: flag tidak ada, modal tidak dirender."""
    opened: list = []
    state: dict = {}
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", state)

    for page in ("Progress & Status", "Progress & Status", "Run Experiment"):
        login.maybe_render_auth_dialog(page)

    assert opened == []
    assert login._DIALOG_KEY not in state


def test_pressing_the_button_arms_the_flag(monkeypatch):
    """(b) Setelah tombol ditekan: flag ada dan modal terbuka di halaman itu."""
    opened: list = []
    state: dict = {}
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", state)

    login.maybe_render_auth_dialog("Run Experiment")       # run pertama
    login.request_auth_dialog(login._MODE_LOGIN)           # tombol ditekan
    assert state[login._DIALOG_KEY] == "login"

    login.maybe_render_auth_dialog("Run Experiment")       # rerun, halaman sama
    assert opened == [True]


def test_a_successful_login_clears_the_flag(monkeypatch):
    """(c) Berhasil masuk -> flag dibersihkan, modal tidak terbuka lagi."""
    opened: list = []
    state = {login._DIALOG_KEY: "login"}
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", state)
    monkeypatch.setattr(login, "authenticate", lambda u, p: {
        "username": u, "role": "contributor", "status": "active"})

    assert login._attempt_login("rina", "rahasia123") is True
    login.close_auth_dialog()               # jalur yang dipakai _render_login_tab
    login.maybe_render_auth_dialog("Add Pipeline & Dataset")

    assert login._DIALOG_KEY not in state
    assert opened == []


def test_the_flag_does_not_survive_a_page_change(monkeypatch):
    """(d) Diminta di halaman A, pengguna pindah ke B -> modal TIDAK ikut."""
    opened: list = []
    state: dict = {}
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", state)

    login.maybe_render_auth_dialog("Run Experiment")
    login.request_auth_dialog(login._MODE_LOGIN)
    login.maybe_render_auth_dialog("Run Experiment")
    assert opened == [True]                 # terbuka di halaman asalnya

    login.maybe_render_auth_dialog("Progress & Status")     # pindah halaman
    assert login._DIALOG_KEY not in state
    assert opened == [True]                 # tidak dirender lagi

    login.maybe_render_auth_dialog("Progress & Status")     # rerun berikutnya
    assert opened == [True]


def test_a_stale_flag_cannot_leak_into_another_page(monkeypatch):
    """Flag sisa dari sesi sebelumnya pun dibuang saat halaman berganti."""
    opened: list = []
    state = {login._DIALOG_KEY: "signup", login._DIALOG_PAGE_KEY: "Run Experiment"}
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", state)

    login.maybe_render_auth_dialog("Progress & Status")
    assert opened == []
    assert login._DIALOG_KEY not in state


def test_native_dismissal_clears_the_flag_too():
    """Tombol X / Esc / klik di luar memakai `on_dismiss`.

    Bawaan Streamlit adalah `on_dismiss="ignore"` — modal tertutup di peramban
    tetapi flag tetap hidup, sehingga rerun berikutnya membukanya lagi. Inilah
    akar bug "modal muncul sendiri", jadi callback-nya wajib terpasang.
    """
    src = Path(login.__file__).read_text(encoding="utf-8")
    assert "on_dismiss=close_auth_dialog" in src

    body = src.split("if _HAS_ST_DIALOG:")[1].split("\ndef ")[0]
    assert "st.dialog(" in body


def test_the_flag_is_only_ever_set_inside_a_button_block():
    """Bukan efek samping render: penulisan flag hanya di dalam blok tombol.

    Diperiksa lewat AST — `request_auth_dialog` adalah SATU-SATUNYA penulis
    flag, dan setiap pemanggilnya berada di dalam sebuah `if`.
    """
    src = Path(login.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 1. Hanya satu fungsi yang menulis ke session_state[_DIALOG_KEY].
    writers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Name)
                        and target.slice.id == "_DIALOG_KEY"):
                    writers.add(fn.name)
    assert writers == {"request_auth_dialog"}, writers

    # 2. SETIAP pemanggilan request_auth_dialog berada di dalam blok
    #    `if st.button(...)`, bukan di aliran render biasa. Diperiksa lewat
    #    rantai induk tiap pemanggilan (bukan dengan menghitung node `If`,
    #    yang akan menghitung ganda saat `if` bersarang).
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def _guarded_by_button(call: ast.Call) -> bool:
        """Pemanggilan berada di dalam blok yang dipicu INTERAKSI pengguna.

        Dua bentuk yang sah, keduanya bukan efek samping render:

        * `if st.button(...)` — tombol biasa;
        * `if choice != current` — pemilih mode kini DROPDOWN, dan blok ini
          hanya benar saat pengguna memilih nilai yang berbeda dari mode yang
          berlaku. Pengulangannya dicegah `_remember_mode_action`, diperiksa
          di bawah.
        """
        node = call
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.If):
                test_src = ast.dump(node.test)
                if "'button'" in test_src or '"button"' in test_src:
                    return True
                if "'choice'" in test_src and "'current'" in test_src:
                    return True
        return False

    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
             and getattr(c.func, "id", None) == "request_auth_dialog"]
    assert calls, "tidak ada pemanggilan request_auth_dialog sama sekali"
    for call in calls:
        assert _guarded_by_button(call), ast.dump(call)

    # 3. Satu pilihan dropdown hanya boleh membuka modal SEKALI. Tanpa penanda
    #    ini, pilihan yang sama akan menyalakan flag lagi pada setiap rerun —
    #    persis bentuk bug "modal muncul sendiri" yang dijaga test ini.
    assert "_remember_mode_action" in src
    assert "_MODE_ACTED_KEY" in src


def test_the_dialog_gate_has_no_truthy_default():
    """`.get(flag)` tanpa default — bukan `.get(flag, True)` atau sejenisnya."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    gate = src.split("def maybe_render_auth_dialog(")[1].split("\ndef ")[0]
    assert "st.session_state.get(_DIALOG_KEY)" in gate
    for bad in ("_DIALOG_KEY, True", "_DIALOG_KEY, _MODE", '_DIALOG_KEY, "'):
        assert bad not in gate, bad

    # Flag tidak pernah diinisialisasi bernilai truthy saat modul dimuat.
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assert not isinstance(target, ast.Subscript), ast.dump(target)


def test_an_authenticated_session_never_keeps_the_dialog_open(monkeypatch):
    """Sudah masuk lewat jalur lain -> flag dibuang, modal tidak muncul."""
    opened: list = []
    monkeypatch.setattr(login, "_auth_dialog", lambda: opened.append(True))
    monkeypatch.setattr(login.st, "session_state", {
        "_auth_dialog": "login",
        login.SESSION_USER_KEY: {"username": "Ai", "role": "research_admin",
                                 "status": "active"},
    })
    login.maybe_render_auth_dialog()
    assert opened == []


def test_one_dialog_holds_both_forms():
    """Satu modal dua mode — bukan dua dialog terpisah.

    Titik dekorasi boleh lebih dari satu (ada jalur cadangan untuk Streamlit
    yang belum punya `on_dismiss`), asalkan seluruhnya membuat modal yang SAMA.
    """
    src = Path(login.__file__).read_text(encoding="utf-8")
    titles = re.findall(r'st\.dialog\(\s*"([^"]+)"', src)
    assert titles and len(set(titles)) == 1, titles
    body = src.split("def _auth_dialog_body()")[1].split("\ndef ")[0]
    assert "_render_login_tab()" in body
    assert "_render_signup_tab()" in body
    assert "Tutup" in body


def test_login_prompts_elsewhere_open_the_same_modal():
    """Ajakan masuk di halaman lain memakai flag yang sama, bukan form sendiri."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    prompt = src.split("def render_login_prompt(")[1].split("\ndef ")[0]
    # Tidak ada lagi tombol "Masuk" di badan halaman: jalur masuk satu-satunya
    # adalah pemilih mode di sidebar, dan keterangannya menunjuk ke sana.
    assert "st.button" not in prompt
    assert "st.text_input" not in prompt
    assert "SIGN_IN_HINT" in prompt

    contrib_src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    assert "render_login_prompt(" in contrib_src
    assert "auth_login_form" not in contrib_src      # tidak ada form auth kedua


def test_self_registration_can_only_produce_a_pending_contributor():
    """Registrasi mandiri kini ADA, tetapi tetap bukan jalan memperoleh peran:
    halaman login hanya boleh memanggil `register_account`, yang selalu
    menghasilkan Kontributor berstatus menunggu persetujuan."""
    login_src = Path(login.__file__).read_text(encoding="utf-8")

    assert "register_account" in login_src
    # Tidak boleh ada jalur pembuatan akun lain di lapis login…
    assert "create_user(" not in login_src
    assert "create_user_as" not in login_src
    # …dan peran tidak pernah disebut/dikirim dari formulir pendaftaran.
    signup = login_src.split("def _render_signup_tab()")[1].split("\ndef ")[0]
    for token in ("role", "research_admin", "ROLE_"):
        assert token not in signup, token


# ── no ownership filtering anywhere ───────────────────────────────────────

def test_experiment_reads_are_never_filtered_by_owner():
    db_src = (REPO_ROOT / "database" / "db.py").read_text(encoding="utf-8")
    assert "WHERE owner" not in db_src
    assert "owner = ?" not in db_src

    # `owner` hanya boleh muncul sebagai kolom TAMPILAN "Pemilik" — tidak pernah
    # sebagai penyaring. Penyusun barisnya kini ada di ui/components/
    # experiment_table.py, jadi keduanya ikut diperiksa.
    for name in (REPO_ROOT / "ui" / "views" / "view_results.py",
                 REPO_ROOT / "ui" / "components" / "experiment_table.py"):
        for line in name.read_text(encoding="utf-8").splitlines():
            if "owner" in line:
                assert ("pemilik" in line.lower() or "#" in line), f"{name}: {line}"


def test_history_table_shows_a_pemilik_column_defaulting_to_sistem():
    """Diperiksa pada perilakunya, bukan pada teks sumbernya."""
    from ui.components import experiment_table as et

    rows = et.build_rows([
        {"id": "a", "owner": None, "dataset_type": "HIKARI2021"},
        {"id": "b", "owner": "rina", "dataset_type": "HIKARI2021"},
    ])
    assert [r["pemilik"] for r in rows] == ["sistem", "rina"]

    labels = {c["label"] for c in et.build_columns()}
    assert "Pemilik" in labels


def test_the_owner_column_is_never_a_filter_dimension():
    """Filter yang tersedia tidak memuat pemilik — riwayat tetap terbuka."""
    from ui.components import experiment_table as et

    rows = et.build_rows([{"id": "a", "owner": "rina",
                           "dataset_type": "HIKARI2021"}])
    # Jaminannya: TIDAK ADA dimensi kepemilikan. Dimensi lain boleh bertambah
    # (mis. mode eksekusi) — yang dijaga adalah pemilik tidak pernah menjadi
    # penyaring, sehingga riwayat tetap terbuka bagi siapa pun.
    dimensions = set(et.filter_options(rows))
    assert not dimensions & {"owner", "owners", "pemilik", "users"}
    assert dimensions == {"pipelines", "datasets", "statuses", "modes"}
    assert len(et.apply_filters(rows)) == 1
