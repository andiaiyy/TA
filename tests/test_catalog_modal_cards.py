"""Tests for the catalog detail modal and the two-panel upload cards.

The modal repeats a mistake the auth modal already made once, so it is pinned
hard: a button may only *set a flag*, the ``@st.dialog`` function is called from
the main script flow, and the flag is cleared on all three exits — close, view
switch, and page change. A flag that survives a page change is what made the
sign-in modal reopen by itself.

The cards are presentation only: `can_upload` decides whether the button looks
usable, while `require_upload` in the action layer stays the real gate.
"""
import ast
import re
from pathlib import Path

import pytest

import ui.views.run_experiment as rx
from ui.components import page_flags, pipeline_catalog as pc, upload_cards as uc

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SRC = REPO_ROOT / "ui" / "components" / "pipeline_catalog.py"
RUN_SRC = REPO_ROOT / "ui" / "views" / "run_experiment.py"

GROUP = {
    "dataset_type": "FAM_A",
    "title": "Judul FAM_A",
    "short": "Penjelasan singkat satu kalimat.",
    "dataset_lines": ["Format berkas: `.csv` — satu baris per **flow**",
                      "Kolom label: `Label` — `0` benign"],
    "paper": "Reproduksi Seseorang (2024)",
    "algorithms": [
        {"pipeline_id": "fam_a.dt", "algorithm": "Decision Tree",
         "summary": "s", "details": [],
         "info": {"feature_selection": "None", "fixed_params": {"seed": 1},
                  "preprocessing_steps": ["a", "b"]}},
        {"pipeline_id": "fam_a.rf", "algorithm": "Random Forest",
         "summary": "s", "details": [],
         "info": {"feature_selection": "None", "metrics_policy": "weighted"}},
    ],
}


# ── modal content comes from structured sources ───────────────────────────

def test_the_rows_are_label_value_pairs_with_an_icon():
    rows = pc.modal_rows(GROUP)
    assert rows
    for icon, label, value in rows:
        assert icon and label and value
        assert isinstance(value, str)


def test_the_rows_include_schema_registry_and_paper_facts():
    labels = {label: value for _icon, label, value in pc.modal_rows(GROUP)}

    assert labels["Feature selection"] == "None"          # dari get_info
    assert "Format berkas" in labels                      # dari skema
    assert labels["Algoritma (2)"] == "Decision Tree, Random Forest"
    assert labels["Paper"].startswith("Reproduksi")


def test_the_algorithm_count_is_computed():
    smaller = dict(GROUP, algorithms=GROUP["algorithms"][:1])
    labels = [label for _i, label, _v in pc.modal_rows(smaller)]
    assert "Algoritma (1)" in labels


def test_differing_values_across_algorithms_are_all_listed():
    """Kalau algoritma dalam satu keluarga berbeda, tidak ada yang disembunyikan."""
    mixed = dict(GROUP, algorithms=[
        dict(GROUP["algorithms"][0], info={"feature_selection": "None"}),
        dict(GROUP["algorithms"][1], info={"feature_selection": "PCA"}),
    ])
    labels = {label: value for _i, label, value in pc.modal_rows(mixed)}
    assert labels["Feature selection"] == "None / PCA"


def test_markdown_markers_are_stripped_from_row_values():
    """Baris dirender sebagai HTML mentah — backtick & ** tidak akan diproses."""
    values = [value for _i, _l, value in pc.modal_rows(GROUP)]
    joined = " ".join(values)
    assert "`" not in joined
    assert "**" not in joined
    assert pc.plain_text("`a` and **b**") == "a and b"


def test_rows_are_omitted_when_the_key_does_not_exist():
    bare = dict(GROUP, algorithms=[dict(GROUP["algorithms"][0], info={})],
                dataset_lines=[], paper="")
    labels = [label for _i, label, _v in pc.modal_rows(bare)]
    assert labels == ["Algoritma (1)"]


def test_sections_are_per_algorithm_and_only_when_present():
    sections = dict(pc.modal_sections(GROUP))

    assert [a for a, _v in sections["Hyperparameter terkunci"]] == ["Decision Tree"]
    assert [a for a, _v in sections["Langkah preprocessing"]] == ["Decision Tree"]
    assert [a for a, _v in sections["Kebijakan metrik"]] == ["Random Forest"]
    assert "Anti-kebocoran" not in sections


def test_the_row_markup_escapes_its_content():
    html = pc.rows_html([("i", "<b>label</b>", "<script>x</script>")])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;label" in html


def test_the_chips_escape_their_content():
    html = pc.chips_html(["<img onerror=1>"])
    assert "<img" not in html
    assert "&lt;img" in html


def test_every_real_group_produces_a_usable_modal():
    for group in pc.build_catalog():
        rows = pc.modal_rows(group)
        assert rows
        labels = [label for _i, label, _v in rows]
        assert any(l.startswith("Algoritma (") for l in labels)
        assert "Paper" in labels
        assert pc.modal_sections(group)          # minimal satu bagian dilipat


def test_nothing_that_left_the_block_is_lost():
    """Setiap keterangan yang dulu tampil di blok kini ada di modal."""
    for group in pc.build_catalog():
        blob = (repr(pc.modal_rows(group)) + repr(pc.modal_sections(group))).lower()
        for moved in ("feature selection", "hyperparameter", "preprocessing",
                      "paper"):
            assert moved in blob, (group["dataset_type"], moved)


# ── modal mechanism: flag only, main flow, three clean exits ──────────────

@pytest.fixture
def state(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(rx.st, "session_state", fake)
    monkeypatch.setattr(page_flags.st, "session_state", fake)
    return fake


def test_the_detail_button_only_sets_a_flag(state):
    rx.request_catalog_detail("FAM_A")
    assert state == {rx.CATALOG_DETAIL_KEY: "FAM_A"}


def test_closing_clears_the_flag(state):
    state[rx.CATALOG_DETAIL_KEY] = "FAM_A"
    rx.close_catalog_detail()
    assert rx.CATALOG_DETAIL_KEY not in state


def test_switching_view_clears_the_flag(state):
    for switch in (rx.go_to_execute, rx.go_to_catalog):
        state[rx.CATALOG_DETAIL_KEY] = "FAM_A"
        switch()
        assert rx.CATALOG_DETAIL_KEY not in state, switch.__name__


def test_changing_page_clears_the_flag(state):
    state[rx.CATALOG_DETAIL_KEY] = "FAM_A"
    page_flags.drop_stale_page_flags("Run Experiment")   # run pertama
    assert state[rx.CATALOG_DETAIL_KEY] == "FAM_A"       # halaman sama, tetap

    assert page_flags.drop_stale_page_flags("Progress & Status") is True
    assert rx.CATALOG_DETAIL_KEY not in state


def test_staying_on_the_page_never_clears_the_flag(state):
    page_flags.drop_stale_page_flags("Run Experiment")
    state[rx.CATALOG_DETAIL_KEY] = "FAM_A"
    for _ in range(3):
        assert page_flags.drop_stale_page_flags("Run Experiment") is False
    assert state[rx.CATALOG_DETAIL_KEY] == "FAM_A"


def test_the_catalog_flag_is_registered_as_page_scoped():
    assert rx.CATALOG_DETAIL_KEY in page_flags.PAGE_SCOPED_KEYS


def test_app_clears_page_flags_before_dispatching():
    src = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    assert "drop_stale_page_flags(page)" in src
    assert src.index("drop_stale_page_flags(page)") < src.index(
        'if page == "Progress & Status"')


def test_the_dialog_is_only_called_from_the_main_flow():
    """Regresi: memanggil st.dialog dari dalam kolom/container pernah error."""
    tree = ast.parse(RUN_SRC.read_text(encoding="utf-8"))
    callers = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "_catalog_detail_dialog"):
                    callers.add(fn.name)
    assert callers == {"_maybe_render_catalog_detail"}, callers

    body = RUN_SRC.read_text(encoding="utf-8").split(
        "def _render_catalog_view() -> None:")[1].split("\ndef ")[0]
    assert "_catalog_detail_dialog" not in body
    assert "request_catalog_detail" in body


def test_the_dialog_is_decorated_once_at_module_level():
    """Diperiksa lewat AST: dekorasinya dipecah dua baris, jadi pencocokan
    substring akan meleset."""
    tree = ast.parse(RUN_SRC.read_text(encoding="utf-8"))
    # Dekorasinya kini lewat util bersama, yang selalu memasang on_dismiss.
    titles = [node.args[0].value for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and getattr(node.func, "attr", None) in ("dialog", "dialog_decorator")
              and node.args and isinstance(node.args[0], ast.Constant)]
    assert titles.count("Detail Research Pipeline") == 1, titles

    # Didekorasi di tingkat modul, bukan di dalam sebuah fungsi.
    module_level = {n.targets[0].id for n in tree.body
                    if isinstance(n, ast.Assign)
                    and isinstance(n.targets[0], ast.Name)}
    nested = {t.id for node in tree.body if isinstance(node, ast.If)
              for n in node.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name)}
    assert "_catalog_detail_dialog" in module_level | nested


def test_a_stale_flag_is_dropped_without_rendering(state, monkeypatch):
    opened = []
    monkeypatch.setattr(rx, "_catalog_detail_dialog", lambda g: opened.append(g))
    state[rx.CATALOG_DETAIL_KEY] = "SUDAH_TIDAK_ADA"

    rx._maybe_render_catalog_detail([{"dataset_type": "FAM_A"}])
    assert opened == []
    assert rx.CATALOG_DETAIL_KEY not in state


def test_the_dialog_opens_when_the_flag_matches(state, monkeypatch):
    opened = []
    monkeypatch.setattr(rx, "_catalog_detail_dialog", lambda g: opened.append(g))
    state[rx.CATALOG_DETAIL_KEY] = "FAM_A"

    rx._maybe_render_catalog_detail([{"dataset_type": "FAM_A"}])
    assert [g["dataset_type"] for g in opened] == ["FAM_A"]


def test_no_flag_means_no_dialog(state, monkeypatch):
    opened = []
    monkeypatch.setattr(rx, "_catalog_detail_dialog", lambda g: opened.append(g))
    rx._maybe_render_catalog_detail([{"dataset_type": "FAM_A"}])
    assert opened == []


# ── upload cards ──────────────────────────────────────────────────────────

def test_there_are_four_uniform_cards():
    # Dua jalur unggah + dua jalur pengelolaan, semuanya berbentuk kartu sama.
    assert [c["mode"] for c in uc.CARDS] == ["pipeline", "dataset",
                                             "review", "users"]


def test_each_card_has_a_two_panel_structure():
    for card in uc.CARDS:
        html = uc.card_html(art=uc.pipeline_art(), tint=card["tint"],
                            title=card["title"], text=card["text"])
        assert "ids-card-art" in html            # panel atas: ilustrasi
        assert "ids-card-body" in html           # panel bawah: teks
        assert f"height:{uc.ART_HEIGHT_PX}px" in html
        assert f"min-height:{uc.BODY_MIN_HEIGHT_PX}px" in html


def test_both_cards_share_the_same_panel_heights():
    """Tinggi seragam supaya dua kartu berdampingan rata."""
    heights = {
        re.search(r"height:(\d+)px", uc.card_html(
            art="", tint=c["tint"], title=c["title"], text=c["text"])).group(1)
        for c in uc.CARDS
    }
    assert len(heights) == 1


def test_the_illustrations_are_inline_svg():
    for art in (uc.pipeline_art(), uc.dataset_art()):
        assert art.startswith("<svg")
        assert "</svg>" in art
        assert "<img" not in art
        assert "http" not in art               # tidak ada sumber daya eksternal


def test_the_illustrations_follow_the_theme_text_colour():
    for art in (uc.pipeline_art(), uc.dataset_art()):
        assert "currentColor" in art
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", art)


def test_the_illustrations_carry_alt_text():
    for art in (uc.pipeline_art(), uc.dataset_art()):
        assert 'role="img"' in art
        assert "aria-label=" in art


def test_the_two_cards_use_different_tints():
    assert uc.TINT_PIPELINE != uc.TINT_DATASET


def test_the_tints_are_translucent_so_both_themes_work():
    for tint in (uc.TINT_PIPELINE, uc.TINT_DATASET):
        assert tint.startswith("rgba(")
        alpha = float(tint.rstrip(")").split(",")[-1])
        assert 0 < alpha <= 0.2, tint          # lembut, bukan blok warna


def test_no_external_asset_or_library_is_used():
    src = (REPO_ROOT / "ui" / "components" / "upload_cards.py").read_text(
        encoding="utf-8")
    for banned in ("http://", "https://", "<img", "st.image", "import requests",
                   "base64"):
        assert banned not in src, banned


def test_card_text_is_escaped():
    html = uc.card_html(art="", tint="rgba(0,0,0,.1)",
                        title="<b>t</b>", text="<script>x</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_card_text_stays_short():
    for card in uc.CARDS:
        assert len(card["text"]) <= 130, card["mode"]


# ── cards: permission is display-only ─────────────────────────────────────

def _render_cards(monkeypatch, may_upload, may_approve=False,
                  may_manage_users=False):
    """Kumpulkan argumen tombol + markup tanpa merender Streamlit sungguhan."""
    calls, markup = [], []

    class _Col:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(uc.st, "markdown",
                        lambda html, **k: markup.append(str(html)))
    monkeypatch.setattr(uc.st, "columns", lambda n, **k: [_Col() for _ in range(n)])
    monkeypatch.setattr(uc.st, "button",
                        lambda label, **kw: calls.append((label, kw)) or False)
    uc.render_upload_cards(may_upload=may_upload, may_approve=may_approve,
                           may_manage_users=may_manage_users)
    return calls, markup


def test_the_buttons_are_disabled_for_a_visitor(monkeypatch):
    calls, markup = _render_cards(monkeypatch, may_upload=False)
    assert len(calls) == 4
    for _label, kwargs in calls:
        assert kwargs["disabled"] is True

    # Alasannya TAMPIL sebagai keterangan pada kartu (bukan tooltip yang hanya
    # muncul saat disorot), dan menunjuk ke pemilih mode di sidebar.
    notes = " ".join(m for m in markup if "ids-card-note" in m)
    assert "Perlu akun Kontributor." in notes
    assert "Khusus Research Admin." in notes
    assert uc.SIGN_IN_HINT in notes


def test_the_upload_buttons_are_enabled_for_a_contributor(monkeypatch):
    """Kontributor boleh mengunggah; kartu admin tetap mati tetapi tetap tampil."""
    calls, markup = _render_cards(monkeypatch, may_upload=True)
    assert len(calls) == 4

    by_key = {kwargs["key"]: kwargs["disabled"] for _label, kwargs in calls}
    assert by_key["contrib_go_pipeline"] is False
    assert by_key["contrib_go_dataset"] is False
    assert by_key["contrib_go_review"] is True
    assert by_key["contrib_go_users"] is True

    # Kartu admin tetap menjelaskan fungsinya walau aksinya tidak tersedia.
    joined = " ".join(markup)
    assert "Peninjauan Pengajuan" in joined
    assert "Kelola Pengguna" in joined


def test_every_button_is_enabled_for_a_research_admin(monkeypatch):
    calls, _markup = _render_cards(monkeypatch, may_upload=True,
                                   may_approve=True, may_manage_users=True)
    assert len(calls) == 4
    assert all(kwargs["disabled"] is False for _label, kwargs in calls)


def test_the_admin_cards_carry_a_role_badge(monkeypatch):
    _calls, markup = _render_cards(monkeypatch, may_upload=True,
                                   may_approve=True, may_manage_users=True)
    joined = " ".join(markup)
    assert joined.count("ids-card-badge") == 2
    assert "Research Admin" in joined


def test_the_cards_are_laid_out_two_by_two():
    rows = uc.card_rows()
    assert [len(r) for r in rows] == [2, 2]


def test_the_cards_never_decide_permission_themselves():
    """Kartu hanya MENERIMA keputusan izin lewat argumen; ia tidak pernah
    memanggil helper izin maupun membaca identitas sendiri.

    Diperiksa lewat AST, bukan substring: docstring modulnya justru MENJELASKAN
    bahwa `can_upload` dibaca di tempat lain.
    """
    src = (REPO_ROOT / "ui" / "components" / "upload_cards.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)

    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    for decider in ("can_upload", "require_upload", "current_user",
                    "user_role", "is_account_active"):
        assert decider not in called, decider

    imported = {a.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not (imported & {"can_upload", "require_upload", "current_user"})

    # Tidak menyentuh session_state sama sekali.
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_the_action_layer_guard_is_untouched():
    import inspect

    from orchestrator import submission_service as svc
    for fn in (svc.submit_pipeline, svc.submit_dataset):
        assert "require_upload" in inspect.getsource(fn), fn.__name__


def test_the_page_passes_the_real_permission_helper():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    assert "may_upload=bool(can_upload(user))" in src
    assert "may_approve=bool(can_approve(user))" in src
    assert "may_manage_users=bool(can_manage_users(user))" in src
    # Kotak lama benar-benar hilang, tidak sekadar disembunyikan.
    assert 'box.subheader("Unggah Pipeline")' not in src
    assert 'key="contrib_go_pipeline"' not in src


# ── AppTest: both pages render for all three roles ────────────────────────

CONTRIB_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
user = st.session_state.pop("_as", None)
if user:
    st.session_state["auth_user"] = user
import ui.views.contribute as c
c.render()
'''

VISITOR = None
CONTRIBUTOR = {"username": "rina", "role": "contributor", "status": "active"}
ADMIN = {"username": "ai", "role": "research_admin", "status": "active"}


def _run_contribute(tmp_path, user):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "cards_app.py"
    script.write_text(CONTRIB_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=600)
    if user:
        at.session_state["_as"] = user
    at.run()
    return at


@pytest.mark.parametrize("user", [VISITOR, CONTRIBUTOR, ADMIN],
                         ids=["pengunjung", "kontributor", "research_admin"])
def test_the_contribute_page_renders_with_cards(tmp_path, user):
    at = _run_contribute(tmp_path, user)
    assert at.exception is None or not at.exception

    cards = [m.value for m in at.markdown
             if "ids-card-art" in m.value and "<svg" in m.value]
    assert len(cards) == 4

    labels = [b.label for b in at.button]
    assert "Unggah pipeline" in labels
    assert "Unggah dataset" in labels


@pytest.mark.parametrize("user, expected", [
    (VISITOR, True), (CONTRIBUTOR, False), (ADMIN, False)],
    ids=["pengunjung-nonaktif", "kontributor-aktif", "admin-aktif"])
def test_the_card_buttons_follow_the_permission(tmp_path, user, expected):
    at = _run_contribute(tmp_path, user)
    for label in ("Unggah pipeline", "Unggah dataset"):
        button = next(b for b in at.button if b.label == label)
        assert button.disabled is expected, label


def test_a_visitor_still_sees_what_the_cards_are_for(tmp_path):
    at = _run_contribute(tmp_path, VISITOR)
    text = " ".join(m.value for m in at.markdown)
    assert "Unggah Pipeline" in text
    assert "Unggah Dataset" in text
    assert "Perlu akun Kontributor" in text
    assert any("Masuk" in i.value for i in at.info)


def test_pressing_a_card_opens_its_flow(tmp_path):
    at = _run_contribute(tmp_path, CONTRIBUTOR)
    next(b for b in at.button if b.label == "Unggah dataset").click().run()

    assert at.exception is None or not at.exception
    assert at.session_state.filtered_state.get("_contrib_mode") == "dataset"
