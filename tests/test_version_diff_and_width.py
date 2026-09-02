"""
Perbandingan versi, pemisahan bagian, dan LEBAR teks yang tepat.

Tiga hal diuji di sini:

* **Diff versi** — "baca kode versi" tidak lagi sekadar menampilkan isi; ia
  menunjukkan BARIS MANA yang berbeda, memakai ``difflib`` dari pustaka BAWAAN.
  Tetap baca-saja: tidak ada jalur memulihkan atau menerapkan versi lama.
* **Pemisahan bagian** — ketiga bagian dipisahkan segmented control, satu
  bagian tampil pada satu waktu, dan keadaan tiap bagian TIDAK hilang saat
  berpindah.
* **Lebar** — batas lebar baca hanya mengenai PROSA. Blok data (tabel, blok
  kode, diff, daftar berkas, pasangan label-nilai, baris katalog, formulir)
  mengikuti lebar penuh kolomnya.
"""
import ast
import re
from pathlib import Path

import pytest

from ui.components import registry_view as rv
from ui.components import sections, theme
from ui.views import manage_pipelines as mp

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_SRC = (REPO_ROOT / "ui" / "views"
            / "manage_pipelines.py").read_text(encoding="utf-8")
CONTRIB_SRC = (REPO_ROOT / "ui" / "views"
               / "contribute.py").read_text(encoding="utf-8")
RV_SRC = (REPO_ROOT / "ui" / "components"
          / "registry_view.py").read_text(encoding="utf-8")

OLD = """def run(self):
    threshold = 0.5
    model = build()
    return model
"""
NEW = """def run(self):
    threshold = 0.8
    extra = tune()
    model = build()
    return model
"""


# ── BAGIAN 1: diff per baris ─────────────────────────────────────────────

def test_the_diff_marks_added_and_removed_lines():
    rows = rv.line_rows(OLD, NEW)
    added = [r["text"] for r in rows if r["tag"] == rv.TAG_ADD]
    removed = [r["text"] for r in rows if r["tag"] == rv.TAG_DEL]

    assert "    threshold = 0.8" in added
    assert "    extra = tune()" in added
    assert "    threshold = 0.5" in removed
    # Baris yang benar-benar sama TIDAK ditandai berubah.
    assert "    model = build()" not in added + removed


def test_the_summary_counts_match_the_marked_lines():
    rows = rv.line_rows(OLD, NEW)
    counts = rv.diff_counts(rows)
    assert counts == {"added": 2, "removed": 1}
    assert counts["added"] == sum(1 for r in rows if r["tag"] == rv.TAG_ADD)
    assert counts["removed"] == sum(1 for r in rows if r["tag"] == rv.TAG_DEL)


def test_identical_versions_are_stated_as_identical():
    rows = rv.line_rows(OLD, OLD)
    assert rv.is_identical(rows)
    assert rv.diff_counts(rows) == {"added": 0, "removed": 0}
    assert not [r for r in rows if r["tag"] != rv.TAG_EQUAL]
    assert "identik" in rv.IDENTICAL_NOTE.lower()


def test_both_sides_carry_line_numbers():
    rows = rv.line_rows(OLD, NEW)
    for row in rows:
        if row["tag"] == rv.TAG_EQUAL:
            assert row["left"] and row["right"]      # nomor di KEDUA sisi
        elif row["tag"] == rv.TAG_ADD:
            assert row["left"] is None and row["right"]
        else:
            assert row["left"] and row["right"] is None

    # Nomornya menaik dan tidak melompat pada masing-masing sisi.
    for side in ("left", "right"):
        seen = [r[side] for r in rows if r[side] is not None]
        assert seen == list(range(1, len(seen) + 1)), side


def test_the_marks_are_textual_not_colour_only():
    """Warna TIDAK boleh menjadi satu-satunya pembeda."""
    assert rv.DIFF_MARK[rv.TAG_ADD] == "+"
    assert rv.DIFF_MARK[rv.TAG_DEL] == "−"

    html = rv.diff_table_html(rv.line_rows(OLD, NEW), "v1", "v2")
    assert "ids-diff-m" in html                       # kolom penanda ada
    assert ">+<" in html and ">−<" in html
    # Nomor baris kedua sisi ikut tercetak.
    assert "v1" in html and "v2" in html


def test_unchanged_stretches_are_hidden_with_context():
    long_same = "\n".join(f"line {i}" for i in range(40))
    left = long_same + "\nAKHIR LAMA\n"
    right = long_same + "\nAKHIR BARU\n"
    rows = rv.line_rows(left, right)
    segments = rv.collapse_rows(rows, context=3)

    hidden = [s for s in segments if not s["shown"]]
    shown = [s for s in segments if s["shown"]]
    assert hidden, "bagian tak berubah yang panjang harus disembunyikan"
    assert shown, "perubahan beserta konteksnya harus tampil"

    # Tidak ada baris yang HILANG — hanya tidak ditampilkan lebih dulu.
    assert sum(len(s["rows"]) for s in segments) == len(rows)
    # Perubahan selalu berada di segmen yang tampil.
    for segment in hidden:
        assert all(r["tag"] == rv.TAG_EQUAL for r in segment["rows"])
    # Konteksnya sebanyak yang diminta.
    assert len(shown[-1]["rows"]) <= 3 + 2 + 3


def test_a_short_diff_is_not_collapsed_at_all():
    segments = rv.collapse_rows(rv.line_rows(OLD, NEW), context=3)
    assert all(s["shown"] for s in segments)


# ── BAGIAN 1: banyak berkas ──────────────────────────────────────────────

def test_identical_files_are_flagged_without_showing_their_body():
    left = {"up.py": OLD, "helper.py": "x = 1\n"}
    right = {"up.py": NEW, "helper.py": "x = 1\n"}
    index = rv.file_diff_index(left, right)
    by_name = {e["name"]: e for e in index}

    assert by_name["helper.py"]["status"] == rv.FILE_SAME
    assert by_name["helper.py"]["added"] == 0
    assert by_name["helper.py"]["removed"] == 0
    assert by_name["up.py"]["status"] == rv.FILE_CHANGED
    assert by_name["up.py"]["added"] == 2

    # Hanya berkas yang BERBEDA yang dapat dibuka perbandingannya.
    assert [e["name"] for e in rv.changed_only(index)] == ["up.py"]
    assert rv.FILE_SAME in rv.file_label(by_name["helper.py"])


def test_files_added_or_removed_between_versions_are_named():
    index = rv.file_diff_index({"a.py": "x\n"}, {"b.py": "y\n"})
    status = {e["name"]: e["status"] for e in index}
    assert status == {"a.py": rv.FILE_REMOVED, "b.py": rv.FILE_ADDED}


def test_the_file_index_table_names_every_file_and_its_status():
    index = rv.file_diff_index({"up.py": OLD, "helper.py": "x\n"},
                               {"up.py": NEW, "helper.py": "x\n"})
    html = rv.file_diff_index_html(index)
    assert "up.py" in html and "helper.py" in html
    assert rv.FILE_SAME in html and rv.FILE_CHANGED in html


# ── BAGIAN 1: bawaan & baca-saja ─────────────────────────────────────────

def test_the_default_pair_is_the_active_version_against_the_previous_one():
    rows = [{"version": 3, "active": True, "pipeline_id": "p@v3"},
            {"version": 2, "active": False, "pipeline_id": "p@v2"},
            {"version": 1, "active": False, "pipeline_id": "p@v1"}]
    left, right = mp.compare_defaults(rows)
    assert right["version"] == 3            # versi AKTIF
    assert left["version"] == 2             # versi SEBELUMNYA


def test_the_default_pair_survives_a_single_version_history():
    rows = [{"version": 1, "active": True, "pipeline_id": "p@v1"}]
    left, right = mp.compare_defaults(rows)
    assert left is right                    # dinyatakan identik, bukan galat
    assert mp.compare_defaults([]) == (None, None)


def test_the_default_pair_tracks_the_active_version_not_the_newest():
    """Versi aktif belum tentu yang terbaru — bawaan harus mengikuti yang AKTIF."""
    rows = [{"version": 3, "active": False, "pipeline_id": "p@v3"},
            {"version": 2, "active": True, "pipeline_id": "p@v2"},
            {"version": 1, "active": False, "pipeline_id": "p@v1"}]
    left, right = mp.compare_defaults(rows)
    assert right["version"] == 2
    assert left["version"] == 1


def test_no_external_library_is_used_for_the_comparison():
    """Perbandingan memakai pustaka BAWAAN Python."""
    imported = set()
    for node in ast.walk(ast.parse(RV_SRC)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "difflib" in imported, "pembandingnya memang difflib"
    for external in ("diff_match_patch", "deepdiff", "difflib2", "jsondiff",
                     "rapidfuzz", "Levenshtein", "pygments"):
        assert external not in imported, external

    # …dan tidak ada dependensi baru yang masuk ke requirements.
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for external in ("deepdiff", "diff-match-patch", "jsondiff"):
        assert external not in req, external


# ── BAGIAN 3: pemisahan bagian ───────────────────────────────────────────

def test_the_three_sections_are_separated_by_one_mechanism():
    assert mp.SECTIONS == (mp.SECTION_PENDING, mp.SECTION_ACTIVE,
                           mp.SECTION_HISTORY)
    body = CONTRIB_SRC.split("def _render_review_flow()")[1].split(
        chr(10) + "def ")[0]
    assert "mp.render_section_switch(" in body
    # SATU bagian tampil pada satu waktu — masing-masing keluar lebih awal.
    assert body.count("return") >= 3


def test_each_section_carries_a_title_and_a_count():
    assert mp.section_label(mp.SECTION_PENDING, 3, 7) == "Menunggu tinjauan (3)"
    assert mp.section_label(mp.SECTION_ACTIVE, 3, 7) == "Aktif (7)"
    assert mp.section_label(mp.SECTION_HISTORY, 3, 7) == "Riwayat versi"
    # Judul bagiannya memakai pola baku yang sama untuk ketiganya.
    assert 'render_section(t("ap.sec_pending", count=len(pending))' in CONTRIB_SRC
    assert 'render_section("Aktif"' in PAGE_SRC
    assert 'render_section("Riwayat versi"' in PAGE_SRC


def test_switching_sections_never_clears_section_state():
    """Berpindah bagian hanya mengubah penanda bagian — tidak membuang apa pun."""
    switch = PAGE_SRC.split("def render_section_switch(")[1].split(
        chr(10) + "def ")[0]
    assert ".pop(" not in switch
    assert "_clear_editor" not in switch
    for key in ("_EDIT_KEY", "_PACKAGE_KEY", "_CMP_LEFT_KEY", "_HISTORY_KEY"):
        assert key not in switch, key


def test_navigating_between_sections_happens_in_a_callback():
    """``SECTION_KEY`` terikat ke widget: menulisnya di badan skrip akan gagal."""
    assert "on_click=goto_section" in PAGE_SRC
    switch = PAGE_SRC.split("def render_section_switch(")[1].split(
        chr(10) + "def ")[0]
    assert f"key=SECTION_KEY" in switch


def test_the_editor_and_the_comparison_replace_their_section():
    """Keduanya tampilan TERSENDIRI, dengan tombol kembali yang jelas."""
    active = PAGE_SRC.split("def render_active(")[1].split(chr(10) + "def ")[0]
    # Penyunting dirender lalu bagian ini BERHENTI — tidak disisipkan di
    # tengah daftar.
    assert "render_editor(user)" in active
    assert active.index("render_editor(user)") < active.index("render_section(")

    history = PAGE_SRC.split("def render_history(")[1].split(chr(10) + "def ")[0]
    assert "_render_compare(rows, name)" in history
    assert "return" in history.split("_render_compare(rows, name)")[1][:40]

    assert '"← Kembali ke daftar aktif"' in PAGE_SRC
    assert 't("ap.btn_back_history")' in PAGE_SRC


def test_leaving_the_editor_keeps_unsaved_work():
    """Tombol kembali TIDAK boleh membuang suntingan yang belum disimpan."""
    editor = PAGE_SRC.split("def render_editor(")[1].split(chr(10) + "def ")[0]
    back = editor.split('"← Kembali ke daftar aktif"')[1][:400]
    assert "_clear_editor()" not in back
    assert "st.session_state.pop(_EDIT_KEY, None)" in back


# ── BAGIAN 4: lebar prosa vs blok data ───────────────────────────────────

def _declarations(css: str, selector: str) -> str:
    """Isi satu blok aturan, TANPA komentar."""
    block = css.split(selector + " {")[1].split("}")[0]
    return re.sub(r"/\*.*?\*/", "", block, flags=re.S)


def test_the_width_limit_is_not_a_blanket_rule_any_more():
    """Dulu SETIAP paragraf dibatasi; itulah yang memotong blok data."""
    css = theme.stylesheet()
    generic = _declarations(css, '[data-testid="stMarkdownContainer"] p')
    assert "max-width" not in generic, "aturan umum itu yang harus hilang"
    assert "font-size" in generic          # yang lain tetap


def test_the_width_limit_attaches_only_to_the_prose_marker():
    css = theme.stylesheet()
    hook = f'[class*="st-key-{theme.PROSE_KEY}"] [data-testid="stMarkdownContainer"] p'
    assert theme.PROSE_W in _declarations(css, hook)

    # Penanda prosa dipasang HANYA lewat `sections.prose`.
    src = (REPO_ROOT / "ui" / "components" / "sections.py").read_text(
        encoding="utf-8")
    assert f'f"{{PROSE_KEY}}{{key}}"' in src


@pytest.mark.parametrize("selector", [
    ".ids-counts",                       # kotak ringkasan angka
    ".ids-diff",                         # tampilan perbandingan
])
def test_data_blocks_are_not_clamped_to_a_reading_width(selector):
    declarations = _declarations(theme.stylesheet(), selector)
    assert "max-width: none" in declarations or "width: 100%" in declarations
    assert theme.PROSE_W not in declarations
    assert f"max-width: {theme.CARD_MAX_W}" not in declarations


def test_catalog_rows_follow_the_full_column_width():
    css = theme.stylesheet()
    hook = '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]'
    assert "--ids-cat-textw: none" in _declarations(css, hook)


def test_prose_is_only_used_for_sentences_not_for_data_blocks():
    """``prose()`` tidak boleh membungkus tabel, kode, atau daftar berkas."""
    for src in (PAGE_SRC, CONTRIB_SRC):
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "prose"):
                continue
            assert node.args, "prose() selalu membawa teksnya"
            rendered = ast.unparse(node.args[0])
            for data in ("_html(", "history_table(", "diff_table_html(",
                         "render_facts(", "st.code(", "<table"):
                assert data not in rendered, rendered


def test_prose_calls_carry_a_unique_key_per_module():
    for src in (PAGE_SRC, CONTRIB_SRC):
        keys = [kw.value.value for node in ast.walk(ast.parse(src))
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "prose"
                for kw in node.keywords
                if kw.arg == "key" and isinstance(kw.value, ast.Constant)]
        assert len(keys) == len(set(keys)), keys


def test_the_prose_helper_wraps_markdown_in_a_keyed_container():
    assert sections.PROSE_KEY == theme.PROSE_KEY
    body = (REPO_ROOT / "ui" / "components" / "sections.py").read_text(
        encoding="utf-8").split("def prose(")[1].split(chr(10) + "def ")[0]
    assert "st.container(key=" in body
    assert "st.markdown(text)" in body


# ── Verifikasi AppTest: seluruh halaman, tiga status pengguna ────────────

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIBUTOR = {"username": "andi", "role": "contributor", "status": "active"}
VISITOR = None

USER_STATES = {"pengunjung": VISITOR, "kontributor": CONTRIBUTOR,
               "research admin": ADMIN}

ALL_PAGES = {
    "Progress & Status": "ui.views.view_results",
    "Run Experiment": "ui.views.run_experiment",
    "Add Pipeline & Dataset": "ui.views.contribute",
}


def _page_script(module: str, page: str, user, preset: dict | None = None) -> str:
    lines = [
        "import sys",
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})",
        "import streamlit as st",
        "from ui.components import theme",
        "theme.inject()",
        f"st.session_state['_current_page'] = {page!r}",
    ]
    if user is not None:
        lines.append(f"st.session_state['auth_user'] = {user!r}")
    for key, value in (preset or {}).items():
        lines.append(f"st.session_state[{key!r}] = {value!r}")
    lines += [f"from {module} import render", "render()"]
    return "\n".join(lines)


def _app(tmp_path, module, page, user, preset=None, name="page.py"):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / name
    script.write_text(_page_script(module, page, user, preset), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=900)
    at.run()
    return at


@pytest.mark.parametrize("state", sorted(USER_STATES))
@pytest.mark.parametrize("page", sorted(ALL_PAGES))
def test_every_page_renders_without_exception(tmp_path, page, state):
    at = _app(tmp_path, ALL_PAGES[page], page, USER_STATES[state],
              name=f"{page}_{state}.py".replace(" ", "_").replace("&", "and"))
    assert not at.exception, (page, state, at.exception)


@pytest.mark.parametrize("section", list(mp.SECTIONS))
def test_each_review_section_renders_for_an_admin(tmp_path, section):
    at = _app(tmp_path, "ui.views.contribute", "Add Pipeline & Dataset", ADMIN,
              preset={"_contrib_mode": "review", mp.SECTION_KEY: section},
              name=f"sec_{section.replace(' ', '_')}.py")
    assert not at.exception, (section, at.exception)


def test_switching_sections_keeps_unsaved_editor_work(tmp_path):
    """Keadaan bagian TIDAK hilang saat berpindah — syarat memakai tab.

    Yang diuji adalah state NYATA yang dipakai fitur ini: paket yang sedang
    disunting (``_mp_package``), pipeline yang sedang disunting, dan pilihan
    versi pada tampilan perbandingan. Ketiganya kunci ``session_state`` biasa,
    jadi ia benar-benar menempuh perpindahan bagian — bukan kunci karangan yang
    hanya bolak-balik lewat ``session_state``.
    """
    draft = {"up.py": "# suntingan yang belum disimpan\n"}
    at = _app(tmp_path, "ui.views.contribute", "Add Pipeline & Dataset", ADMIN,
              preset={"_contrib_mode": "review",
                      mp.SECTION_KEY: mp.SECTION_PENDING,
                      mp._PACKAGE_KEY: draft,
                      mp._CMP_LEFT_KEY: "uploaded.contoh@v1"},
              name="switch.py")
    assert not at.exception, at.exception

    for section in (mp.SECTION_ACTIVE, mp.SECTION_HISTORY, mp.SECTION_PENDING):
        at.session_state[mp._SECTION_LAST] = section
        at.session_state[mp.SECTION_KEY] = section
        at.run()
        assert not at.exception, (section, at.exception)
        # Pekerjaan yang belum disimpan menempuh setiap perpindahan.
        assert at.session_state[mp._PACKAGE_KEY] == draft, section
        assert at.session_state[mp._CMP_LEFT_KEY] == "uploaded.contoh@v1", section


def test_the_switcher_would_notice_if_state_were_dropped(tmp_path):
    """Kontrol negatif: test di atas tidak lulus hanya karena kuncinya ada.

    Bila sesuatu benar-benar membuang state, ``session_state`` kehilangan
    kuncinya — dan itulah yang akan ditangkap.
    """
    at = _app(tmp_path, "ui.views.contribute", "Add Pipeline & Dataset", ADMIN,
              preset={"_contrib_mode": "review",
                      mp.SECTION_KEY: mp.SECTION_PENDING,
                      mp._PACKAGE_KEY: {"up.py": "x\n"}},
              name="switch_neg.py")
    assert not at.exception, at.exception
    assert mp._PACKAGE_KEY in at.session_state
    del at.session_state[mp._PACKAGE_KEY]
    assert mp._PACKAGE_KEY not in at.session_state
