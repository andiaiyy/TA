"""Tests for the platform-wide UI tidy-up.

Three things are easy to break silently and are pinned here:

  * **hover belongs only to what you can click.** A hover effect on a plain
    caption or on a disabled button tells the user "press me" when nothing will
    happen, so the rules are scoped and the disabled case is explicitly inert;
  * **the factual notes survive a cosmetic pass.** Sampling caveats, "static
    check, the file is not executed", "valid ≠ active", the cross-family metric
    warning, and the upload limit are all statements the platform must keep
    making. A tidy-up must move them, never delete or shrink them;
  * **permission behaviour is untouched.** The sign-in button is gone from the
    contribution page, but the reason and the way in are still stated, and the
    action layer still refuses.
"""
import ast
import re
from pathlib import Path

import pytest

from ui.components import theme
from ui.components import upload_cards as uc
import ui.views.login as login

REPO_ROOT = Path(__file__).resolve().parents[1]
CSS = theme.stylesheet()


# ── shared style, defined once ────────────────────────────────────────────

def test_the_shared_style_is_injected_from_one_place_only():
    """Gaya berulang tidak boleh disalin ke banyak berkas view."""
    app_src = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    assert "theme.inject()" in app_src

    injectors = []
    for path in (REPO_ROOT / "ui").rglob("*.py"):
        if "theme.inject()" in path.read_text(encoding="utf-8"):
            injectors.append(path.name)
    assert injectors == ["app.py"], injectors


def test_only_four_text_sizes_are_defined():
    """Judul halaman & judul bagian dari Streamlit; modul ini menambah dua
    tingkat sisanya — teks isi dan keterangan."""
    sizes = {theme.FONT_SECTION, theme.FONT_BODY, theme.FONT_CAPTION}
    assert len(sizes) == 3                   # + judul halaman dari Streamlit = 4

    # Dinormalkan: CSS boleh menulis ".84rem" maupun "0.84rem".
    declared = {f"{float(v):.2f}" for v in
                re.findall(r"font-size:\s*([0-9.]*[0-9])rem", CSS)}
    allowed = {f"{float(v.rstrip('rem')):.2f}" for v in sizes}
    assert declared <= allowed, (declared, allowed)


def test_only_two_font_weights_are_used():
    weights = set(re.findall(r"font-weight:\s*(\d+)", CSS))
    assert weights <= {theme.WEIGHT_NORMAL, theme.WEIGHT_STRONG}, weights


def test_captions_were_made_bigger_not_smaller():
    """Bawaan Streamlit untuk caption ±0.75rem — terlalu kecil untuk catatan
    faktual yang wajib terbaca."""
    assert float(theme.FONT_CAPTION.rstrip("rem")) > 0.80
    assert "[data-testid=\"stCaptionContainer\"]" in CSS


def test_long_text_blocks_are_width_limited():
    assert "max-width: 78ch" in CSS


# ── hover: only on what is clickable ──────────────────────────────────────

def test_clickable_elements_get_hover_and_a_pointer():
    assert ".stButton > button:not(:disabled):hover" in CSS
    assert "cursor: pointer" in CSS
    assert ".ids-clickable:hover" in CSS


def test_disabled_buttons_never_react():
    """Sorot pada tombol mati menjanjikan sesuatu yang tidak akan terjadi."""
    assert ".stButton > button:disabled" in CSS
    assert "cursor: not-allowed" in CSS
    assert ".stButton > button:disabled:hover { background-color: inherit; }" in CSS

    # Aturan sorotnya sendiri MENGECUALIKAN yang disabled.
    # Setiap aturan sorot tombol mengecualikan yang disabled — kecuali aturan
    # yang memang SENGAJA menetralkannya.
    hover_rules = [line for line in CSS.splitlines() if ":hover" in line]
    for rule in hover_rules:
        if ".stButton" not in rule and ".stDownloadButton" not in rule:
            continue
        if ":disabled:hover" in rule:        # aturan penetral, bukan pemberi efek
            continue
        assert ":not(:disabled)" in rule, rule


def test_plain_text_has_no_hover_rule():
    """Caption & markdown biasa tidak boleh ikut bereaksi."""
    for selector in ("stCaptionContainer:hover", "stMarkdownContainer:hover",
                     ".ids-card:hover", ".ids-card-text:hover"):
        assert selector not in CSS, selector


def test_the_transition_is_short_and_subtle():
    assert 120 <= theme.HOVER_MS <= 180
    # Tidak ada efek yang menggeser tata letak atau membesarkan mencolok.
    for heavy in ("transform:", "scale(", "translateY"):
        assert heavy not in CSS, heavy

    # Bayangan hanya boleh menandai KEADAAN AKTIF (kartu terangkat pada pemilih
    # algoritma), bukan efek sorot — sorot cukup perubahan latar.
    for line in CSS.splitlines():
        if "box-shadow:" in line:
            assert "hover" not in line, line
    shadowed = [l for l in CSS.splitlines() if "box-shadow:" in l]
    assert len(shadowed) <= 1, shadowed


def test_the_active_segment_looks_raised():
    """Pilihan aktif = kartu terangkat; pilihan lain redup tanpa latar."""
    container = CSS.split('[data-testid="stSegmentedControl"] {')[1].split("}")[0]
    assert "background: rgba(127,127,127,.09)" in container   # wadah lembut
    assert "flex-wrap: wrap" in container                     # enam algoritma muat

    active = CSS.split(
        '[data-testid="stSegmentedControl"] button[aria-checked="true"] {'
    )[1].split("}")[0]
    assert "box-shadow:" in active
    assert "opacity: 1" in active
    assert f"font-weight: {theme.WEIGHT_STRONG}" in active

    idle = CSS.split('[data-testid="stSegmentedControl"] button {')[1].split("}")[0]
    assert "background: transparent" in idle
    assert "opacity: .62" in idle
    assert "white-space: normal" in idle      # membungkus, bukan terpotong


def test_reduced_motion_turns_transitions_off():
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    block = CSS.split("@media (prefers-reduced-motion: reduce)")[1]
    assert "transition: none !important" in block


def test_hover_colours_are_theme_safe():
    """Warna sorot transparan/mengikuti tema — tidak ada heksa yang bisa
    menjadi tak terbaca di salah satu tema."""
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS), CSS
    assert theme.TINT_HOVER.startswith("rgba(")
    assert "var(--primary-color" in CSS


# ── the four cards ────────────────────────────────────────────────────────

def test_there_are_four_cards_in_two_rows():
    assert len(uc.CARDS) == 4
    assert [len(row) for row in uc.card_rows()] == [2, 2]


def test_every_card_has_the_same_shape():
    for card in uc.CARDS:
        assert set(card) >= {"mode", "title", "text", "button", "tint",
                             "need", "badge", "denied"}
        html = uc.card_html(art="<svg/>", tint=card["tint"], title=card["title"],
                            text=card["text"], badge=card["badge"])
        assert 'class="ids-card"' in html
        assert f"height:{uc.ART_HEIGHT_PX}px" in html
        assert f"min-height:{uc.BODY_MIN_HEIGHT_PX}px" in html


def test_only_the_admin_cards_carry_a_role_badge():
    badged = {c["mode"] for c in uc.CARDS if c["badge"]}
    assert badged == {"review", "users"}
    for card in uc.CARDS:
        if card["badge"]:
            assert card["badge"] == "Research Admin"


def test_every_card_has_its_own_illustration():
    arts = {mode: fn() for mode, fn in uc._ART.items()}
    assert set(arts) == {c["mode"] for c in uc.CARDS}
    assert len(set(arts.values())) == 4          # tidak ada yang dipakai ulang
    for art in arts.values():
        assert art.startswith("<svg") and "currentColor" in art
        assert "<img" not in art and "http" not in art.replace(
            "http://www.w3.org/2000/svg", "")


def test_the_card_illustrations_need_no_library():
    src = (REPO_ROOT / "ui" / "components" / "upload_cards.py").read_text(
        encoding="utf-8")
    for banned in ("import base64", "st.image", "requests", "PIL"):
        assert banned not in src, banned


def test_card_content_is_escaped():
    html = uc.card_html(art="<svg/>", tint="rgba(0,0,0,.1)",
                        title="<script>x</script>", text="&", badge="<b>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


# ── the sign-in button is gone, the guidance is not ───────────────────────

def test_the_contribution_page_has_no_sign_in_button():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    labels = [n.args[0].value for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and getattr(n.func, "attr", None) == "button"
              and n.args and isinstance(n.args[0], ast.Constant)]
    assert "Masuk" not in labels, labels


def test_the_login_prompt_renders_no_widget():
    src = Path(login.__file__).read_text(encoding="utf-8")
    body = src.split("def render_login_prompt(")[1].split("\ndef ")[0]
    assert "st.button" not in body
    assert "st.info" in body


def test_the_guidance_points_at_the_sidebar_picker():
    assert "pemilih mode" in login.SIGN_IN_HINT.lower()
    assert "kiri bawah" in login.SIGN_IN_HINT.lower()
    assert "pemilih mode" in uc.SIGN_IN_HINT.lower()


def test_a_disabled_card_always_explains_itself(monkeypatch):
    """Tombol mati tanpa keterangan adalah jalan buntu."""
    notes = []

    class _Col:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(uc.st, "markdown", lambda html, **k: notes.append(str(html)))
    monkeypatch.setattr(uc.st, "columns", lambda n, **k: [_Col() for _ in range(n)])
    monkeypatch.setattr(uc.st, "button", lambda label, **kw: False)
    uc.render_upload_cards(may_upload=False)

    joined = " ".join(n for n in notes if "ids-card-note" in n)
    for card in uc.CARDS:
        assert card["denied"] in joined, card["mode"]
    assert uc.SIGN_IN_HINT in joined


def test_the_cards_still_decide_nothing_about_permission():
    """Kartu hanya MENERIMA keputusan izin; penegakannya tetap di lapis aksi."""
    src = (REPO_ROOT / "ui" / "components" / "upload_cards.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    for decider in ("can_upload", "can_approve", "can_manage_users",
                    "require_upload", "require_approve", "current_user"):
        assert decider not in called, decider


def test_the_action_layer_guards_are_unchanged():
    import inspect

    from orchestrator import submission_service as svc
    assert "require_upload" in inspect.getsource(svc.submit_pipeline)
    assert "require_upload" in inspect.getsource(svc.submit_dataset)
    assert "require_approve" in inspect.getsource(svc.approve_submission)


# ── mode picker: bottom of the sidebar, compact list ──────────────────────

def test_the_mode_block_is_pushed_to_the_bottom():
    """Percobaan pertama gagal karena flex dipasang pada stSidebarUserContent,
    padahal elemen sidebar bersaudara di dalam stVerticalBlock DI DALAMNYA.
    Yang benar: blok itulah yang dijadikan kolom fleksibel."""
    assert ('[data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"]'
            in CSS)
    flex_block = CSS.split(
        '[data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"] {'
    )[1].split("}")[0]
    assert "display: flex" in flex_block
    assert "flex-direction: column" in flex_block
    assert "min-height: calc(100vh" in flex_block

    # Wadah yang MEMUAT jangkar didorong ke dasar.
    assert "*:has(.ids-mode-anchor)" in CSS
    assert "margin-top: auto" in CSS

    # Bukan position:fixed — itu akan menumpuk di atas isi lain.
    assert "position: fixed" not in CSS and "position:fixed" not in CSS


def test_the_anchor_lives_inside_one_container():
    """Jangkar HARUS berada di dalam st.container() yang sama dengan isi blok.
    Sebuah <div> yang dibuka di satu st.markdown dan ditutup di panggilan lain
    tidak pernah membungkus apa pun — itu sebab percobaan sebelumnya gagal."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    body = src.split("def render_mode_switch()")[1].split("\ndef ")[0]

    assert "with st.container():" in body
    assert "_MODE_ANCHOR" in body
    # Tidak ada lagi div yang dibuka & ditutup di panggilan terpisah.
    assert "'<div" not in body and '"<div' not in body
    assert "</div>" not in body

    # Pemilih mode TIDAK lagi memakai st.popover: panelnya di-portal ke
    # document.body sehingga menembus batas sidebar dan menimpa konten.
    assert "st.popover(" not in body
    anchor_at = body.index("_MODE_ANCHOR")
    toggle_at = body.index("auth_mode_toggle")
    assert anchor_at < toggle_at             # jangkar mendahului isinya


def test_the_picker_list_is_compact():
    """Panel selebar isinya & dibatasi tegas — bukan selebar sidebar."""
    body = CSS.split('[data-testid="stPopoverBody"] {')[1].split("}")[0]
    assert "min-width: 0 !important" in body
    assert "width: max-content" in body
    assert f"max-width: {theme.POPOVER_MAX_W}" in body

    buttons = CSS.split(
        '[data-testid="stPopoverBody"] .stButton > button {')[1].split("}")[0]
    assert "padding: .1rem .5rem" in buttons        # padding vertikal tipis
    assert "min-height: 0" in buttons
    assert "white-space: nowrap" in buttons         # satu baris per pilihan
    assert "gap: .1rem" in CSS                      # baris rapat


def test_the_picker_panel_is_narrower_than_the_sidebar():
    """Sidebar bawaan Streamlit ±21rem; panel dibatasi jauh di bawah itu."""
    assert theme.POPOVER_MAX_W.endswith("rem")
    assert float(theme.POPOVER_MAX_W.rstrip("rem")) <= 14


def test_the_picker_labels_are_short_phrases():
    """Isi daftar hanya nama mode — tanpa kalimat penjelas."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    body = src.split("def render_mode_switch()")[1].split(chr(10) + "def ")[0]

    assert login._MODE_VISITOR == "Pengunjung"
    assert "Masuk sebagai" not in body              # label lama yang panjang
    # Penjelasan pindah ke help=, bukan baris teks di dalam daftar.
    assert body.count("help=") >= 3



def test_the_layout_has_breathing_room():
    """KOREKSI ARAH: jarak dikembalikan & DIPERLEBAR, bukan dirapatkan.
    Yang dipotong adalah jumlah kata, bukan ruang kosongnya."""
    assert f'[data-testid="stVerticalBlock"] {{ gap: {theme.GAP_ELEMENT}; }}' in CSS
    assert f"margin: {theme.GAP_SECTION} 0" in CSS
    assert "padding-top: 2.6rem" in CSS            # naik lagi dari 1.6rem

    # Nilainya benar-benar lebih lebar daripada perapatan sebelumnya.
    assert float(theme.GAP_ELEMENT.rstrip("rem")) >= 1.0     # sebelumnya .55rem
    assert float(theme.GAP_SECTION.rstrip("rem")) >= 1.8     # sebelumnya .9rem


def test_buttons_have_space_around_them():
    assert ".stButton, .stDownloadButton { margin: .35rem 0; }" in CSS
    assert '[data-testid="stHorizontalBlock"] { gap: 1rem; }' in CSS


def test_the_compact_gap_applies_only_inside_the_mode_picker():
    """Satu-satunya tempat yang sengaja rapat adalah daftar pemilih mode."""
    tight = [l for l in CSS.splitlines() if "gap: .1rem" in l]
    assert tight and all("stPopoverBody" in l for l in tight), tight


def test_picking_a_role_still_grants_nothing():
    """Aturan penting tidak berubah oleh perapian tampilan."""
    src = Path(login.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_mode_switch")

    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                assert not isinstance(target, ast.Subscript), ast.dump(target)

    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    for granting in ("set_user_role", "set_user_status", "create_user"):
        assert granting not in called, granting
    assert "request_auth_dialog" in called


def test_the_picker_still_says_it_grants_nothing():
    """Penegasannya kini di tooltip pilihan peran, bukan baris teks — tetapi
    tetap tersampaikan (butir 16)."""
    assert "tidak memberikan peran" in login._ROLE_HELP
    assert "membuka formulir masuk" in login._ROLE_HELP.lower()
    assert "bukan dipilih di sini" in login._OTHER_ROLE_HELP


def test_the_algorithm_picker_uses_the_segmented_control():
    import streamlit as st

    assert hasattr(st, "segmented_control"), "versi Streamlit ini punya komponennya"

    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
        encoding="utf-8")
    block = src.split("_algo_names = list(algo_to_pid.keys())")[1][:700]
    assert "st.segmented_control(" in block
    assert 'key="algorithm_select"' in block
    # Jalur cadangan tetap ada untuk Streamlit tanpa komponen itu.
    assert "st.radio(" in block


def test_the_selected_algorithm_still_drives_the_pipeline_id():
    """Perilaku pemilihan tidak berubah: nilai terpilih tetap diterjemahkan ke
    pipeline_id lewat peta yang sama."""
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
        encoding="utf-8")
    assert "selected = algo_to_pid.get(algorithm) if algorithm else None" in src


def test_many_algorithms_wrap_instead_of_being_cut_off():
    """HIKARI punya enam algoritma — harus membungkus, bukan terpotong."""
    assert '[data-testid="stSegmentedControl"]' in CSS
    assert "flex-wrap: wrap" in CSS

    from config.pipeline_registry import PIPELINE_REGISTRY
    hikari = [e for e in PIPELINE_REGISTRY.values()
              if e["dataset_type"] == "HIKARI2021"]
    assert len(hikari) == 6


# ── the mandatory notes survived ──────────────────────────────────────────

MANDATORY = {
    "cuplikan": "angka dataset berasal dari cuplikan",
    "tidak dijalankan": "pemeriksaan statis, berkas tidak dijalankan",
    "menunggu persetujuan": "valid != aktif / status akun",
}


@pytest.mark.parametrize("needle, why", list(MANDATORY.items()))
def test_the_mandatory_notes_still_exist_somewhere(needle, why):
    found = [p.name for p in (REPO_ROOT / "ui").rglob("*.py")
             if needle in p.read_text(encoding="utf-8")]
    assert found, why


def test_the_metric_semantics_warning_survives():
    from ui.components import experiment_table as et

    assert "TIDAK sebanding" in et.CROSS_FAMILY_WARNING
    assert "weighted" in et.METRIC_SEMANTICS[et.FAMILY_HIKARI].lower()
    assert "natural-holdout" in et.METRIC_SEMANTICS[et.FAMILY_EVE]


def test_the_upload_limit_note_survives():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    assert "Batas unggah" in src
    assert "MAX_DATASET_UPLOAD_BYTES" in src


def test_the_static_check_note_survives():
    from ui.components import instructions

    src = Path(instructions.__file__).read_text(encoding="utf-8")
    assert "tidak dijalankan" in src
    assert "bukan</b> berarti" in src or "bukan" in src


def test_no_mandatory_note_was_shrunk_below_the_caption_size():
    """Perapian tidak boleh mengecilkan keterangan wajib."""
    for module in ("instructions.py", "sidebar_chrome.py", "pipeline_catalog.py",
                   "upload_cards.py", "theme.py"):
        src = (REPO_ROOT / "ui" / "components" / module).read_text(encoding="utf-8")
        for size in re.findall(r"font-size:\s*([0-9.]+)rem", src):
            assert float(size) >= 0.74, (module, size)


# ── BAGIAN 2: kata dipotong, informasi wajib tetap ────────────────────────

def _words(text: str) -> int:
    import re
    t = re.sub(r"<[^>]+>", " ", text)
    t = re.sub(r"[`*_#|]", " ", t)
    return len([w for w in t.split() if any(c.isalpha() for c in w)])


def test_the_mandatory_notes_survived_the_cut():
    """Diringkas sependek mungkin, tetapi informasinya tetap tersampaikan."""
    from ui.components import instructions as ins

    src = Path(ins.__file__).read_text(encoding="utf-8")
    # "pemeriksaan statis — berkas tidak dijalankan" + "lolos != aktif"
    assert "statis" in src and "tidak dijalankan" in src
    assert "bukan</b> berarti aktif" in src
    # "berdasarkan cuplikan"
    assert "cuplikan" in src


def test_the_shortened_notes_are_actually_short():
    from ui.components import instructions as ins

    src = Path(ins.__file__).read_text(encoding="utf-8")
    static = src.split("🔒 Pemeriksaan")[1].split('"""')[0].split(")")[0]
    sample = src.split("🔍 Angka berasal")[1].split(")")[0]
    assert _words(static) <= 20, static
    assert _words(sample) <= 20, sample


def test_the_capability_line_is_a_phrase_not_a_sentence():
    from ui.components.contribute_context import capability

    for user in (None, {"username": "a", "role": "contributor",
                        "status": "active"}):
        what = capability(user)["what"]
        assert _words(what) <= 8, what
        assert "?" not in what
        for filler in ("Anda dapat", "silakan", "Perlu diketahui"):
            assert filler not in what


def test_the_upload_limit_note_still_states_the_limit():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    assert "Batas unggah" in src
    assert "MAX_DATASET_UPLOAD_BYTES" in src


def test_the_not_signed_in_reason_still_points_at_the_picker():
    from ui.components import upload_cards as uc

    assert "pemilih mode" in uc.SIGN_IN_HINT.lower()
    assert "pemilih mode" in login.SIGN_IN_HINT.lower()


def test_detail_moved_to_help_not_deleted():
    """Yang dipotong dari badan teks harus muncul kembali sebagai tooltip."""
    from ui.components import instructions as ins

    src = Path(ins.__file__).read_text(encoding="utf-8")
    assert "__subclasses__" in src            # rincian sandbox-escape
    assert "help=" in src

    run_src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
        encoding="utf-8")
    assert "FAILED (stale)" in run_src        # akibat broker mati
    assert "ids_worker" in run_src
