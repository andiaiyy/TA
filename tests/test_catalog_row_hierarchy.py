"""Katalog sebagai DAFTAR BARIS berhierarki teks.

Membalik permintaan sebelumnya (kartu berkotak). Yang dijaga di sini:

* tidak ada wadah berbatas per research pipeline — pemisahnya garis tipis
  selebar penuh plus hierarki jarak;
* TIGA tingkat teks yang benar-benar berbeda, pada tiga sumbu sekaligus
  (ukuran, bobot, keredupan) — bukan tiga ukuran yang hampir sama;
* isi baris berasal dari registry/``get_info()``/skema, bukan teks baru;
* penjelasan dipotong satu baris, tetapi teks penuhnya TIDAK hilang.
"""
import re
from pathlib import Path

import pytest

from ui.components import pipeline_catalog as pc
from ui.components import theme

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SRC = (REPO_ROOT / "ui" / "components"
               / "pipeline_catalog.py").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    return css.split(selector + " {")[1].split("}")[0]


def _size(block: str) -> float:
    return float(re.search(r"font-size:\s*([0-9.]+)rem", block).group(1))


def _opacity(block: str) -> float:
    found = re.search(r"opacity:\s*([0-9.]+)", block)
    return float(found.group(1)) if found else 1.0


def _weight(block: str) -> int:
    found = re.search(r"font-weight:\s*([0-9]+)", block)
    return int(found.group(1)) if found else 400


# ── Tidak ada lagi kotak per item ─────────────────────────────────────────

def test_the_row_container_has_no_border_of_its_own():
    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert "st.container(border=False, key=row_key(" in body
    assert "border=True" not in body


def test_no_boxed_card_styling_remains():
    css = theme.stylesheet()
    row = _rule(css, '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]')
    declarations = re.sub(r"/\*.*?\*/", "", row, flags=re.S)
    assert "border-radius" not in declarations
    assert "background:" not in declarations       # latar hanya saat disorot
    assert "cat_card_" not in css


def test_rows_are_separated_by_one_thin_full_width_line():
    row = _rule(theme.stylesheet(),
                '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]')
    declarations = re.sub(r"/\*.*?\*/", "", row, flags=re.S)
    assert "border-bottom: 1px solid" in declarations
    # Garisnya TIDAK dibatasi lebar — dan kini teksnya pun tidak: baris katalog
    # adalah BLOK DATA, jadi keduanya membentang selebar area konten dan tetap
    # selaras satu sama lain.
    assert "max-width:" not in declarations
    assert "--ids-cat-textw: none" in declarations


# ── Tiga tingkat teks yang jelas berbeda ──────────────────────────────────

LEVELS = (".ids-cat-name", ".ids-cat-lead", ".ids-cat-note")


def test_the_three_levels_shrink_in_a_visible_step():
    sizes = [_size(_rule(pc._CSS, level)) for level in LEVELS]
    assert sizes == sorted(sizes, reverse=True), sizes
    # Bukan "hampir sama": tiap turunan minimal 10%, dan tingkat 1 jauh di atas
    # tingkat 3.
    for bigger, smaller in zip(sizes, sizes[1:]):
        assert (bigger - smaller) / bigger >= 0.10, (bigger, smaller)
    assert sizes[0] / sizes[-1] >= 1.4, sizes


def test_the_name_is_the_only_bold_level():
    weights = [_weight(_rule(pc._CSS, level)) for level in LEVELS]
    assert weights[0] >= 600
    assert weights[1] == weights[2] == 400


def test_only_the_third_level_is_dimmed():
    opacities = [_opacity(_rule(pc._CSS, level)) for level in LEVELS]
    assert opacities[0] == 1.0
    assert opacities[1] == 1.0
    assert opacities[2] <= 0.6, opacities        # paling redup


def test_the_levels_share_one_left_edge():
    """Perataan kiri SAMA — tidak ada indentasi tambahan pada tingkat mana pun."""
    for level in LEVELS + (".ids-cat-head",):
        block = _rule(pc._CSS, level)
        assert "margin-left" not in block, level
        assert "padding-left" not in block, level
        assert "text-indent" not in block, level


def test_the_font_stays_the_normal_one():
    """Bukan monospace."""
    assert "monospace" not in pc._CSS
    assert "font-family" not in pc._CSS          # mewarisi font aplikasi


# ── Isi baris berasal dari sumber terstruktur ─────────────────────────────

def test_row_content_comes_from_the_registry():
    catalog = pc.build_catalog()
    assert catalog

    # Registry GABUNGAN: katalog memang memuat pipeline kontribusi yang aktif.
    from orchestrator.dynamic_registry import get_all_pipelines
    registry = get_all_pipelines()

    for group in catalog:
        dtype = group["dataset_type"]
        expected = [p for p, e in registry.items()
                    if (e or {}).get("dataset_type") == dtype]
        assert len(group["algorithms"]) == len(expected), dtype

        head = pc.row_head_html(group)
        assert group["title"][:30] in head or "…" in head
        assert group["short"][:30] in head


def test_the_metadata_uses_only_data_already_on_the_page():
    for group in pc.build_catalog():
        meta = pc.row_meta_text(group)
        assert group["dataset_type"] in meta
        assert str(len(group["algorithms"])) in meta
        # Tidak ada informasi baru yang diperkenalkan.
        assert set(meta.split(" · ")) <= {
            group["dataset_type"], f"{len(group['algorithms'])} algoritma"}


def test_the_metadata_is_right_aligned_next_to_the_name():
    head = _rule(pc._CSS, ".ids-cat-head")
    meta = _rule(pc._CSS, ".ids-cat-meta")
    assert "display: flex" in head
    assert "align-items: baseline" in head       # sejajar dengan baris nama
    assert "margin-left: auto" in meta           # terdorong ke kanan
    assert "text-align: right" in meta


def test_an_empty_field_produces_no_empty_line():
    head = pc.row_head_html({"title": "T", "dataset_type": "DT",
                             "algorithms": [], "short": "", "paper": ""})
    assert "ids-cat-lead" not in head
    assert "ids-cat-note" not in head


# ── Penjelasan dipotong, tetapi tidak hilang ──────────────────────────────

def test_the_note_is_truncated_by_css_not_by_cutting_the_text():
    note = _rule(pc._CSS, ".ids-cat-note")
    assert "white-space: nowrap" in note
    assert "overflow: hidden" in note
    assert "text-overflow: ellipsis" in note


@pytest.mark.parametrize("group", pc.build_catalog(),
                         ids=lambda g: g["dataset_type"])
def test_the_full_note_survives_as_a_tooltip(group):
    """Dipotong di layar, UTUH di atribut `title`."""
    if not group.get("paper"):
        pytest.skip("pipeline ini tidak punya kredit paper")

    head = pc.row_head_html(group)
    fragment = head.split('class="ids-cat-note"')[1]
    tooltip = fragment.split('title="')[1].split('"')[0]

    from html import unescape
    assert unescape(tooltip) == group["paper"]   # tanpa dipotong sedikit pun


def test_the_full_note_is_also_still_in_the_detail_modal():
    """Jalur kedua: teks penuh tetap ada di pop-up Detail."""
    body = CATALOG_SRC.split("def render_modal_body(")[1].split("\ndef ")[0]
    assert "modal_rows(group)" in body
    for group in pc.build_catalog():
        rows = dict((label, value) for _icon, label, value
                    in pc.modal_rows(group))
        assert any(group["paper"] and group["paper"] in str(v)
                   for v in rows.values()), group["dataset_type"]


# ── Chip & tombol tidak berubah ───────────────────────────────────────────

def test_the_algorithm_chips_are_unchanged():
    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    # Chip kini menerima ENTRI algoritma (yang membawa asal & keadaannya),
    # bukan hanya nama — bentuk lama tetap didukung.
    assert 'chips_html(group.get("algorithms")' in body
    html = pc.chips_html(["Random Forest", "SVC"])
    assert html.count('class="ids-cat-chip"') == 2
    # Chip berada DI BAWAH penjelasan.
    assert body.index("row_head_html(") < body.index("chips_html(")


def test_the_two_buttons_stay_uniform_and_side_by_side():
    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert body.count(".button(") == 2
    assert 'st.columns([1, 1, 3])' in body        # dua kolom aksi berukuran sama
    assert 't("re.btn_run_short"), type="primary"' in body
    assert 'type="tertiary"' in body              # aksi sekunder lebih tenang

    css = theme.stylesheet()
    uniform = _rule(css, '[class*="st-key-cat_run_"] button, '
                         '[class*="st-key-cat_detail_"] button')
    # Seragam TAPI luwes: mengisi lebar kolomnya sampai batas atas yang sama
    # untuk kedua tombol. Diperiksa eksplisit — "max-width: 9.5rem" memuat
    # substring "width: 9.5rem", sehingga pemeriksaan longgar akan lolos
    # sekalipun lebar tetapnya sudah tidak ada.
    assert "width: 100%" in uniform
    assert "max-width: " + theme.CATALOG_BTN_W in uniform
    assert "min-height" in uniform


# ── Jarak & sorot ─────────────────────────────────────────────────────────

def test_spacing_inside_a_row_is_tighter_than_between_rows():
    row = _rule(theme.stylesheet(),
                '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]')
    between = float(re.search(r"padding:\s*([0-9.]+)rem", row).group(1))
    inside = [float(m) for m in re.findall(r"margin: 0 0 ([0-9.]+)rem", pc._CSS)]
    assert inside
    assert max(inside) < between, (max(inside), between)


def test_the_hover_is_a_faint_tint_only():
    css = theme.stylesheet()
    hover = _rule(css, '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]:hover')
    assert "background" in hover
    for heavy in ("transform", "box-shadow", "border-width"):
        assert heavy not in hover
    # Sangat tipis: alfa kecil.
    alpha = float(re.search(r"rgba\([0-9,\s]+,\s*([0-9.]+)\)", hover).group(1))
    assert alpha <= 0.10, alpha
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_reduced_motion_is_respected_by_the_row_styles():
    assert "@media (prefers-reduced-motion: reduce)" in pc._CSS


# ── Adaptif ───────────────────────────────────────────────────────────────

def test_the_head_wraps_so_metadata_can_drop_below_the_name():
    head = _rule(pc._CSS, ".ids-cat-head")
    assert "flex-wrap: wrap" in head


def test_the_colours_stay_theme_safe():
    """Tidak ada nilai heksa; netralnya transparan, aksennya token tema."""
    css = pc._CSS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    for level in LEVELS:
        block = _rule(css, level)
        assert "color:" not in block.replace("background-color", "")


# ── Halaman tetap terender untuk semua peran ──────────────────────────────

IDENTITIES = {
    "pengunjung": None,
    "kontributor": {"username": "rina", "role": "contributor", "status": "active"},
    "research_admin": {"username": "ai", "role": "research_admin", "status": "active"},
}


@pytest.mark.parametrize("who", sorted(IDENTITIES))
def test_the_catalog_view_renders_for_every_identity(tmp_path, who):
    from streamlit.testing.v1 import AppTest

    from ui.views import login

    script = tmp_path / "catalog_page.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        "st.session_state['_current_page'] = 'Run Experiment'\n"
        "st.session_state['_run_view'] = 'catalog'\n"
        "from ui.views.run_experiment import render\n"
        "render()\n",
        encoding="utf-8")

    at = AppTest.from_file(str(script), default_timeout=900)
    if IDENTITIES[who]:
        at.session_state[login.SESSION_USER_KEY] = IDENTITIES[who]
    at.run()
    assert at.exception is None or not at.exception, (who, at.exception)

    from ui.i18n.core import lookup

    labels = [b.label for b in at.button]
    groups = pc.build_catalog()
    # Label datang dari kamus; bahasa bawaan adalah Indonesia.
    assert labels.count(lookup("re.btn_run_short", "id")) == len(groups)
    assert labels.count(lookup("re.btn_detail", "id")) == len(groups)


def test_the_buttons_still_drive_the_same_callbacks(tmp_path):
    """Perilaku tombol TIDAK berubah — hanya tampilannya."""
    calls: dict[str, list] = {"run": [], "detail": []}

    from unittest.mock import patch

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Col:
        def __init__(self, fire): self._fire = fire
        def button(self, label, **kw): return self._fire(label)

    from ui.i18n.core import lookup

    # Label tombol kini datang dari kamus; bahasa bawaan Indonesia.
    fired = {"label": lookup("re.btn_run_short", "id")}

    with patch.object(pc.st, "container", lambda **kw: _Ctx()), \
         patch.object(pc.st, "markdown", lambda *a, **k: None), \
         patch.object(pc.st, "columns",
                      lambda spec, **k: [_Col(lambda l: l == fired["label"])
                                         for _ in range(len(spec))]):
        pc.render_catalog(on_run=calls["run"].append,
                          on_detail=calls["detail"].append)

    groups = [g["dataset_type"] for g in pc.build_catalog()]
    assert calls["run"] == groups
    assert calls["detail"] == []


# ── Luwes terhadap lebar area konten ──────────────────────────────────────

FLUID_LEVELS = (".ids-cat-head", ".ids-cat-lead", ".ids-cat-note")


def test_no_catalog_text_element_uses_a_fixed_pixel_size():
    """Piksel tetap tidak ikut lebar konten maupun skala huruf pengguna."""
    for level in LEVELS + (".ids-cat-head", ".ids-cat-chips", ".ids-cat-meta"):
        block = _rule(pc._CSS, level)
        offenders = [line.strip() for line in block.splitlines()
                     if "px" in line and "1px solid" not in line]
        assert not offenders, (level, offenders)


@pytest.mark.parametrize("level", FLUID_LEVELS)
def test_the_text_follows_the_available_width(level):
    """Mengikuti lebar wadah, dengan batas ATAS saja — bukan lebar tetap."""
    block = _rule(pc._CSS, level)
    assert "width: 100%" in block
    assert "max-width: var(--ids-cat-textw" in block
    # Tidak ada lebar minimum yang memaksa, dan tidak ada nilai tetap.
    assert "min-width: 0" in block or "min-width" not in block


def test_the_name_is_no_longer_cut_at_a_fixed_character_count():
    """Berapa yang muat ditentukan lebar NYATA, bukan angka karakter."""
    body = CATALOG_SRC.split("def row_head_html(")[1].split("\ndef ")[0]
    assert "shorten(" not in body
    assert "TITLE_CHARS" not in CATALOG_SRC

    long_title = "Sangat Panjang " * 12
    head = pc.row_head_html({"title": long_title, "dataset_type": "DT",
                             "algorithms": [], "short": "", "paper": ""})
    shown = head.split('class="ids-cat-name">')[1].split("</div>")[0]
    from html import unescape
    assert unescape(shown) == long_title     # utuh; CSS yang mengaturnya
    assert "…" not in shown


def test_the_name_can_shrink_so_the_metadata_stays_pinned_right():
    """Tanpa `min-width: 0` item flex menolak menyusut, dan metadata terdorong
    keluar pada lebar sempit."""
    name = _rule(pc._CSS, ".ids-cat-name")
    meta = _rule(pc._CSS, ".ids-cat-meta")
    assert "flex: 1 1 auto" in name
    assert "min-width: 0" in name
    assert "flex: 0 0 auto" in meta          # metadata tidak ikut menyusut
    assert "margin-left: auto" in meta       # tetap menempel kanan


def test_the_note_truncates_by_real_width_so_it_grows_with_the_container():
    """Elipsis dari lebar nyata: melebarkan jendela menampilkan lebih banyak."""
    note = _rule(pc._CSS, ".ids-cat-note")
    assert "text-overflow: ellipsis" in note
    assert "width: 100%" in note             # lebarnya mengikuti wadah
    assert "max-width: var(--ids-cat-textw" in note
    # Teks yang dikirim ke DOM TIDAK dipotong — hanya tampilannya.
    for group in pc.build_catalog():
        if not group.get("paper"):
            continue
        head = pc.row_head_html(group)
        shown = head.split('class="ids-cat-note"')[1].split(">")[1].split("<")[0]
        from html import unescape
        assert unescape(shown) == group["paper"]


def test_the_chips_wrap_instead_of_being_cut():
    chips = _rule(pc._CSS, ".ids-cat-chips")
    assert "flex-wrap: wrap" in chips
    assert "max-width: var(--ids-cat-textw" in chips
    one = _rule(pc._CSS, ".ids-cat-chip")
    assert "white-space: nowrap" in one      # satu chip utuh, tidak terbelah
    assert "overflow" not in one             # dan tidak pernah dipotong


def test_the_buttons_are_fluid_but_stack_when_narrow():
    css = theme.stylesheet()
    uniform = _rule(css, '[class*="st-key-cat_run_"] button, '
                         '[class*="st-key-cat_detail_"] button')
    assert "width: 100%" in uniform
    assert "max-width: " + theme.CATALOG_BTN_W in uniform
    assert "white-space: normal" in uniform  # label membungkus, tidak terpotong

    # Kolomnya menumpuk di bawah ambang sempit -> tombol menumpuk juga.
    stack = _rule(css, f'[data-testid="{theme.COL_ROW}"] > '
                       f'[data-testid="{theme.COL_ONE}"]')
    assert "100%" in stack
    assert f"@media (max-width: {theme.STACK_WIDTH})" in css


def test_the_maximum_text_width_is_a_relative_unit():
    """Batas atas ikut skala huruf pengguna, bukan piksel."""
    assert theme.CARD_MAX_W.endswith("rem")
    assert theme.CATALOG_BTN_W.endswith("rem")
    assert theme.STACK_WIDTH.endswith("rem")
