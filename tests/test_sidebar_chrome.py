"""Tests for the sidebar chrome — breadcrumb, nav item styling, aligned lines.

The active-item highlight itself lives inside the ``streamlit-option-menu``
iframe, which AppTest cannot look into. So the split is:

  * the **style spec** is a pure function and is asserted directly (active vs
    inactive, one accent, theme-safe colours, uniform spacing);
  * the **breadcrumb** is native markup and is asserted end-to-end through
    AppTest, driven by the real ``option_menu`` so the page name it shows is the
    one the menu actually selected.
"""
import ast
import re
from html import escape
from pathlib import Path

import pytest

from ui.components.sidebar_chrome import (
    BREADCRUMB_ROOT, BREADCRUMB_SEP, FONT_MAIN, FONT_SMALL, INSET_PX,
    breadcrumb_text, menu_styles, progress_bar_html, sidebar_line,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "ui" / "components" / "sidebar_chrome.py"
PAGES = ["Progress & Status", "Run Experiment", "Add Pipeline & Dataset"]


# ── breadcrumb ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("page", PAGES)
def test_breadcrumb_names_the_active_page(page):
    text = breadcrumb_text(page)
    assert text == f"{BREADCRUMB_ROOT} {BREADCRUMB_SEP} {page}"
    assert page in text


def test_breadcrumb_uses_an_arrow_separator():
    assert BREADCRUMB_SEP == "›"
    assert BREADCRUMB_SEP in breadcrumb_text("Run Experiment")


def test_breadcrumb_degrades_when_the_page_is_unknown():
    assert breadcrumb_text("") == BREADCRUMB_ROOT
    assert breadcrumb_text(None) == BREADCRUMB_ROOT


def test_breadcrumb_is_not_a_link():
    """Menu-nya komponen iframe; tautan di sini pasti jadi tautan rusak."""
    src = MODULE.read_text(encoding="utf-8")
    body = src.split("def render_breadcrumb(")[1].split("\ndef ")[0]
    for linky in ("<a ", "href=", "st.page_link", "st.link_button"):
        assert linky not in body, linky


def test_breadcrumb_is_small_and_muted_but_not_bold():
    from ui.components import sidebar_chrome as sc

    captured = []
    original = sc.st.markdown
    try:
        sc.st.markdown = lambda html, **kw: captured.append(html)
        sc.render_breadcrumb("Run Experiment")
    finally:
        sc.st.markdown = original

    assert len(captured) == 1
    html = captured[0]
    assert f"font-size:{FONT_SMALL}" in html
    assert "opacity:.6" in html
    assert "font-weight:600" not in html


# ── nav item styling ──────────────────────────────────────────────────────

def test_the_selected_item_is_highlighted_and_the_others_are_plain():
    styles = menu_styles()
    plain, active = styles["nav-link"], styles["nav-link-selected"]

    assert plain.get("background-color") in (None, "transparent")
    assert active["background-color"] == "var(--secondary-background-color)"
    assert active["font-weight"] == "600"
    assert plain["font-weight"] == "400"
    assert "border-radius" in plain          # pill juga berlaku saat aktif


def test_the_highlight_is_a_soft_neutral_not_a_loud_colour():
    """Latar aktif memakai warna latar sekunder tema — bukan blok aksen."""
    active = menu_styles()["nav-link-selected"]
    assert active["background-color"] != "var(--primary-color)"
    assert active["color"] == "var(--text-color)"      # bukan teks putih paksa


def test_exactly_one_accent_colour_is_used():
    styles = menu_styles()
    blob = repr(styles)
    assert blob.count("var(--primary-color)") == 1
    accent_holder = styles["nav-link-selected"]["border-left"]
    assert "var(--primary-color)" in accent_holder


def test_colours_are_theme_variables_never_hardcoded():
    """Komponen ini iframe: CSS halaman tidak menjangkaunya, jadi warna WAJIB
    lewat variabel tema yang disuntikkan Streamlit ke dalam iframe."""
    blob = repr(menu_styles())
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", blob), blob
    for banned in ("white", "black", "rgb(", "rgba("):
        assert banned not in blob, banned
    for expected in ("var(--text-color)", "var(--secondary-background-color)",
                     "var(--primary-color)"):
        assert expected in blob, expected


def test_the_theme_variables_really_exist_inside_the_component_iframe():
    """Kalau paketnya berganti dan berhenti menyuntik variabel ini, warnanya
    akan runtuh diam-diam — jadi keberadaannya ikut dijaga di sini."""
    import os

    import streamlit_option_menu
    dist = Path(os.path.dirname(streamlit_option_menu.__file__)) / "frontend" / "dist"
    bundle = "".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in dist.glob("js/*.js"))
    for var in ("--text-color", "--secondary-background-color", "--primary-color"):
        assert var in bundle, var


def test_active_and_inactive_items_share_one_left_edge():
    """Item aktif punya garis aksen 3px; yang tidak aktif memakai garis
    transparan selebar sama, supaya teks keduanya tetap sebaris."""
    styles = menu_styles()
    plain, active = styles["nav-link"], styles["nav-link-selected"]

    width = lambda rule: rule.split("px")[0]
    assert width(plain["border-left"]) == width(active["border-left"])
    assert "transparent" in plain["border-left"]
    assert "transparent" not in active["border-left"]
    # Padding tidak diubah saat aktif, jadi teks tidak bergeser.
    assert "padding" not in active


def test_nav_text_lines_up_with_the_other_sidebar_lines():
    """Sisipan item navigasi (garis + padding) sama dengan sisipan baris teks."""
    plain = menu_styles()["nav-link"]
    border = int(plain["border-left"].split("px")[0])
    pad_left = int(plain["padding"].split()[1].replace("px", ""))
    assert border + pad_left == INSET_PX


def test_vertical_spacing_is_uniform_across_items():
    plain = menu_styles()["nav-link"]
    top, bottom = plain["margin"].split()
    assert top == "1px" and bottom == "0"
    pad_y = plain["padding"].split()[0]
    assert pad_y == "7px"                     # sama untuk aktif & tidak aktif
    assert "margin" not in menu_styles()["nav-link-selected"]


def test_icons_are_uniform_and_follow_the_text_colour():
    icon = menu_styles()["icon"]
    assert icon["font-size"] == "0.95rem"
    assert icon["color"] == "inherit"


def test_items_are_left_aligned_and_do_not_touch_the_edge():
    plain = menu_styles()["nav-link"]
    assert plain["text-align"] == "left"
    assert menu_styles()["container"]["padding"] == "0"
    assert int(plain["padding"].split()[1].replace("px", "")) > 0


def test_the_menu_container_stays_transparent():
    """Tanpa kotak berlatar sendiri — pemisah antar-blok berupa garis tipis."""
    assert menu_styles()["container"]["background-color"] == "transparent"


# ── aligned text lines ────────────────────────────────────────────────────

def test_every_line_uses_the_same_left_inset():
    # Padding kini shorthand: ada padding vertikal kecil supaya `overflow:hidden`
    # (untuk elipsis) tidak ikut memangkas tinggi huruf.
    for kwargs in ({}, {"muted": True}, {"strong": True}, {"small": True}):
        assert f"2px {INSET_PX}px" in sidebar_line("x", **kwargs)


def test_lines_are_not_vertically_clipped():
    """Regresi: jejak lokasi pernah terpotong tepi atas sidebar."""
    html = sidebar_line("Menu > Run Experiment", muted=True, small=True)
    assert "line-height:1.7" in html
    assert html.count("padding:2px 0 2px") == 1
    assert "text-overflow:ellipsis" in html      # panjang -> elipsis, bukan potong


def test_lines_clip_instead_of_wrapping():
    """Nama pipeline/username panjang dipotong elipsis, bukan membungkus —
    kalau membungkus, jarak antar-baris jadi tidak seragam."""
    html = sidebar_line("nama pengguna yang sangat panjang sekali")
    assert "white-space:nowrap" in html
    assert "text-overflow:ellipsis" in html
    assert "overflow:hidden" in html


def test_only_two_text_sizes_exist():
    sizes = {re.search(r"font-size:([^;]+);", sidebar_line("x", small=s)).group(1)
             for s in (False, True)}
    assert sizes == {FONT_MAIN, FONT_SMALL}


def test_line_content_is_escaped():
    html = sidebar_line("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_lines_carry_no_hardcoded_colour():
    """Di luar iframe dipakai warna teks yang diwarisi + opacity, sehingga aman
    di tema terang maupun gelap tanpa perlu tahu temanya."""
    html = sidebar_line("x", muted=True)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", html)
    assert "color:" not in html               # mewarisi warna teks Streamlit
    assert "opacity:.6" in html


def test_the_progress_bar_shares_the_same_inset():
    html = progress_bar_html(40)
    assert f"padding-left:{INSET_PX}px" in html
    assert "width:40%" in html


@pytest.mark.parametrize("value, expected", [
    (-5, "width:0%"), (0, "width:0%"), (42, "width:42%"),
    (100, "width:100%"), (140, "width:100%"),
])
def test_the_progress_bar_clamps_its_width(value, expected):
    assert expected in progress_bar_html(value)


def test_the_progress_bar_colour_survives_a_missing_theme_variable():
    assert "var(--primary-color,currentColor)" in progress_bar_html(50)


# ── app wiring ────────────────────────────────────────────────────────────

def _app_src() -> str:
    return (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")


def test_app_reserves_the_breadcrumb_slot_above_the_menu():
    """Jejak lokasi harus di ATAS menu, tetapi isinya baru diketahui SESUDAH
    menu dirender — karenanya tempatnya dipesan lebih dulu."""
    src = _app_src()
    slot = src.index("st.sidebar.empty()")
    menu = src.index("page = _select_page()")
    fill = src.index("render_breadcrumb(page)")
    assert slot < menu < fill


def test_app_uses_the_shared_style_spec():
    src = _app_src()
    assert "styles=menu_styles()" in src
    # Tidak ada dict gaya kedua yang bisa menyimpang.
    assert '"nav-link-selected"' not in src


def test_app_no_longer_hardcodes_a_menu_colour():
    src = _app_src()
    assert not re.search(r'^_ACCENT\s*=', src, re.M)
    assert "#eef2ff" not in src
    assert "#2563eb" not in src


def test_navigation_behaviour_is_unchanged():
    """Halaman, urutan, ikon, dan indeks default persis seperti sebelumnya."""
    src = _app_src()
    assert ('_PAGES = ("Progress & Status", "Run Experiment", '
            '"Add Pipeline & Dataset")') in src
    assert '_PAGE_ICONS = ("speedometer2", "play-circle", "plus-square")' in src
    assert '_DEFAULT_PAGE = "Progress & Status"' in src
    assert "default_index=_remembered_index()" in src
    # Jalur cadangan tanpa option_menu tetap ada.
    assert 'st.sidebar.radio("Navigation", _PAGES, index=_remembered_index())' in src


def test_no_block_is_wrapped_in_a_heavy_bordered_box():
    """Blok dipisah garis tipis, bukan kotak berbatas."""
    login_src = (REPO_ROOT / "ui" / "views" / "login.py").read_text(encoding="utf-8")
    body = login_src.split("def render_mode_switch()")[1].split("\ndef ")[0]
    assert "border=True" not in body
    assert "st.divider()" in body

    progress_src = (REPO_ROOT / "ui" / "components"
                    / "sidebar_progress.py").read_text(encoding="utf-8")
    assert "border=True" not in progress_src


# ── end-to-end: breadcrumb follows the real menu ──────────────────────────

CHROME_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
from streamlit_option_menu import option_menu
from ui.components.sidebar_chrome import menu_styles, render_breadcrumb

PAGES = {pages}
slot = st.sidebar.empty()
with st.sidebar:
    page = option_menu(menu_title=None, options=PAGES,
                       icons=["speedometer2", "play-circle", "plus-square"],
                       default_index=PAGES.index(st.session_state["_page"]),
                       styles=menu_styles())
with slot:
    render_breadcrumb(page)
st.write("PAGE=" + str(page))
'''


def _run_chrome(tmp_path, page):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "chrome_app.py"
    script.write_text(CHROME_APP.format(repo=str(REPO_ROOT), pages=repr(PAGES)),
                      encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=300)
    at.session_state["_page"] = page
    at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_the_menu_and_breadcrumb_render_without_exception(tmp_path, page):
    at = _run_chrome(tmp_path, page)
    assert at.exception is None or not at.exception


@pytest.mark.parametrize("page", PAGES)
def test_the_breadcrumb_follows_the_page_the_menu_selected(tmp_path, page):
    at = _run_chrome(tmp_path, page)

    assert f"PAGE={page}" in " ".join(m.value for m in at.markdown)
    crumbs = [m.value for m in at.sidebar.markdown if BREADCRUMB_ROOT in m.value]
    assert len(crumbs) == 1, crumbs
    # Dibandingkan dalam bentuk ter-escape: "Progress & Status" memang menjadi
    # "Progress &amp; Status" di markup, dan escaping itu disengaja.
    assert escape(breadcrumb_text(page)) in crumbs[0]
    # Halaman lain tidak ikut disebut.
    for other in PAGES:
        if other != page:
            assert escape(other) not in crumbs[0]


def test_the_module_defines_no_extra_text_sizes():
    """Batasi gaya: hanya dua ukuran teks yang dideklarasikan di modul ini."""
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    sizes = {n.value.value for n in ast.walk(tree)
             if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
             and isinstance(n.value.value, str) and n.value.value.endswith("rem")}
    assert sizes == {FONT_MAIN, FONT_SMALL}, sizes
