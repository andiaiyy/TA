"""Kotak ringkasan angka, tata letak adaptif, dan biaya render.

Tiga hal yang dijaga di sini:

* **nilai tidak berubah** — kotak angka hanya mengubah CARA menampilkan; angka
  yang ditampilkan tetap dihitung dari sumber nyata;
* **selektor CSS cocok dengan bundel terpasang** — selektor yang salah gagal
  tanpa suara, dan itu sudah pernah terjadi di proyek ini;
* **pekerjaan berat per render tidak boleh naik lagi** — batasnya ditetapkan
  angka, bukan perkiraan, sehingga regresi tertangkap.
"""
from pathlib import Path

import pytest
import streamlit as st_mod

from tests.render_cost import RenderCost, clear_streamlit_caches
from ui.components import sections, theme

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = Path(st_mod.__file__).parent / "static" / "static" / "js"


def _html(fn, *args, **kwargs) -> list[str]:
    """Kumpulkan payload `st.html` yang dihasilkan sebuah penyaji."""
    from unittest.mock import patch

    out: list[str] = []
    with patch("streamlit.html", side_effect=lambda body: out.append(body)):
        fn(*args, **kwargs)
    return out


# ── BAGIAN 1: kotak ringkasan angka ───────────────────────────────────────

def test_each_cell_puts_the_number_above_its_label():
    block = _html(sections.render_counts,
                  [("dataset", 4), ("algoritma", 6), ("eksperimen", 45)])[0]
    for value, label in (("4", "dataset"), ("6", "algoritma"), ("45", "eksperimen")):
        cell = block.split(f">{value}<")[1]
        # Label muncul SESUDAH angkanya di dalam sel yang sama.
        assert cell.startswith("/span><span class=\"ids-count-l\">" + label)


def test_the_numbers_are_passed_through_untouched():
    """Kotak ini tidak boleh mengubah nilai apa pun."""
    block = _html(sections.render_counts, [("dataset", 4), ("eksperimen", 45)])[0]
    assert ">4<" in block and ">45<" in block
    assert ">5<" not in block and ">44<" not in block


def test_extra_wording_goes_to_a_tooltip_not_into_the_cell():
    block = _html(sections.render_counts,
                  [("dataset", 4, "Berkas dataset di storage/datasets/.")])[0]
    assert 'title="Berkas dataset di storage/datasets/."' in block
    # Label di dalam sel tetap PENDEK — keterangannya hanya di tooltip.
    label = block.split('class="ids-count-l">')[1].split("<")[0]
    assert label == "dataset"
    assert "storage" not in label


def test_a_missing_value_is_dropped_not_shown_empty():
    assert _html(sections.render_counts, [("dataset", None)]) == []


def test_the_box_has_a_border_rounded_corners_and_its_own_background():
    css = theme.stylesheet()
    block = css.split(".ids-counts {")[1].split("}")[0]
    assert "border:" in block
    assert "border-radius" in block
    assert "background" in block


def test_the_cells_are_separated_and_aligned_consistently():
    css = theme.stylesheet()
    cell = css.split(".ids-count {")[1].split("}")[0]
    assert "border-right" in cell and "border-bottom" in cell   # pemisah tipis
    assert "text-align: left" in cell                           # seragam


def test_the_number_is_bigger_than_the_label_and_not_touching_it():
    css = theme.stylesheet()
    number = css.split(".ids-count-n {")[1].split("}")[0]
    label = css.split(".ids-count-l {")[1].split("}")[0]

    size = float(number.split("font-size:")[1].split("rem")[0].strip())
    label_size = float(label.split("font-size:")[1].split("rem")[0].strip()
                       ) if "rem" in label.split("font-size:")[1][:12] else 0.84
    assert size > label_size
    assert size >= 1.4                                   # besar & tegas
    assert "margin-bottom" in number                     # jarak ke labelnya


def test_both_pages_use_the_same_box():
    """Baris ringkasan serupa di halaman lain memakai pola yang sama."""
    run_src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
        encoding="utf-8")
    ctx_src = (REPO_ROOT / "ui" / "components" / "contribute_context.py").read_text(
        encoding="utf-8")
    assert "render_counts(" in run_src
    assert "render_counts(" in ctx_src
    # Tidak ada lagi gaya kedua untuk hal yang sama.
    assert "st.metric(" not in ctx_src


def test_the_platform_summary_still_reports_the_same_numbers():
    """Nilainya tetap dari `platform_stats()`, bukan angka baru."""
    from ui.components.contribute_context import platform_stats, render_platform_summary

    stats = platform_stats()
    block = _html(render_platform_summary)[0]
    for key in ("research", "algorithms", "datasets"):
        assert f'>{stats[key]}<' in block, (key, stats[key])


# ── BAGIAN 2: adaptif ─────────────────────────────────────────────────────

BUNDLE_TESTIDS = ("COL_ROW", "COL_ONE", "DATAFRAME", "MAIN_BLOCK", "SEG_GROUP")


@pytest.mark.parametrize("name", BUNDLE_TESTIDS)
def test_every_testid_selector_exists_in_the_installed_bundle(name):
    """Selektor yang tidak ada di DOM gagal TANPA SUARA. Nama-nama ini
    dicocokkan dengan berkas frontend yang benar-benar terpasang."""
    value = getattr(theme, name)
    bundles = list(BUNDLE_DIR.glob("*.js"))
    assert bundles, BUNDLE_DIR
    assert any(value in b.read_text(encoding="utf-8", errors="ignore")
               for b in bundles), value
    assert f'[data-testid="{value}"]' in theme.stylesheet()


def test_columns_stack_instead_of_squeezing_on_narrow_widths():
    css = theme.stylesheet()
    rule = css.split(f'[data-testid="{theme.COL_ROW}"] > '
                     f'[data-testid="{theme.COL_ONE}"] {{')[1].split("}")[0]
    assert "100%" in rule
    assert "flex" in rule


def test_the_number_box_reflows_by_minimum_cell_width():
    """Sel berkurang jumlahnya di layar sempit, bukan mengecil tak terbaca."""
    block = theme.stylesheet().split(".ids-counts {")[1].split("}")[0]
    assert "auto-fit" in block
    assert f"minmax({theme.COUNT_CELL_MIN}, 1fr)" in block


def test_the_container_query_has_a_containment_root_and_a_fallback():
    """`@container` tanpa akar containment tidak pernah cocok — diam-diam."""
    css = theme.stylesheet()
    assert f'[data-testid="{theme.MAIN_BLOCK}"] {{ container-type: inline-size; }}' \
        .replace("{{", "{").replace("}}", "}") in css
    assert f"@container (max-width: {theme.STACK_WIDTH})" in css
    assert f"@media (max-width: {theme.STACK_WIDTH})" in css   # cadangan


def test_wide_tables_scroll_instead_of_being_squeezed():
    css = theme.stylesheet()
    scroll = css.split(".ids-cmp-scroll, .ids-ph-wrap {")[1].split("}")[0]
    assert "overflow-x: auto" in scroll
    assert f"min-width: {theme.CMP_MIN_W}" in css


def test_the_comparison_tables_are_wrapped_in_the_scroller():
    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
    assert src.count('<div class="ids-cmp-scroll">') == 2   # tabel utama & aksi


def test_no_main_element_uses_a_fixed_pixel_width():
    """Lebar tetap dalam piksel tidak ikut skala huruf maupun lebar konten."""
    css = theme.stylesheet()
    for hook in (".ids-counts {", ".ids-count {", ".ids-facts {",
                 f'[class*="st-key-{theme.ROW_KEY_PREFIX}"] {{'.replace("{{", "{")):
        block = css.split(hook)[1].split("}")[0]
        widths = [line for line in block.splitlines()
                  if "width" in line and "px" in line]
        assert not widths, (hook, widths)


def test_only_prose_keeps_a_readable_maximum_width():
    """Batas lebar baca melekat pada PROSA saja.

    Kotak angka dan baris katalog adalah BLOK DATA: keduanya mengikuti lebar
    penuh kolomnya. Sebelumnya keduanya dipatok {CARD_MAX_W}, sehingga isinya
    berhenti di ~3/4 lebar sementara garis pemisah di bawahnya membentang penuh
    — dan ketidakselarasan itu terbaca sebagai kesalahan render.
    """
    css = theme.stylesheet()

    counts = css.split(".ids-counts {")[1].split("}")[0]
    assert f"max-width: {theme.CARD_MAX_W}" not in counts
    assert "max-width: none" in counts

    row_hook = f'[class*="st-key-{theme.ROW_KEY_PREFIX}"] {{'.replace("{{", "{")
    row = css.split(row_hook)[1].split("}")[0]
    assert f"--ids-cat-textw: {theme.CARD_MAX_W}" not in row
    assert "--ids-cat-textw: none" in row

    # …sementara prosa TETAP dibatasi, lewat penanda khususnya.
    hook = (f'[class*="st-key-{theme.PROSE_KEY}"] '
            f'[data-testid="stMarkdownContainer"] p')
    assert theme.PROSE_W in css.split(hook + " {")[1].split("}")[0]


# ── BAGIAN 3: biaya render ────────────────────────────────────────────────

PAGES = {
    "Progress & Status": ("ui.views.view_results", {}),
    "Run Experiment": ("ui.views.run_experiment", {"_run_view": "execute"}),
    "Add Pipeline & Dataset": ("ui.views.contribute", {}),
}

#: Batas pekerjaan berat pada render PERTAMA (cache dingin). Angka ini
#: ditetapkan dari pengukuran nyata, bukan perkiraan — bila sebuah perubahan
#: menambah pembacaan berkas atau kueri, test ini gagal.
COLD_BUDGET = {
    "Progress & Status": 6,
    "Run Experiment": 12,
    "Add Pipeline & Dataset": 12,
}

#: Batas pada render BERIKUTNYA — inilah yang dialami pengguna saat
#: berinteraksi. Halaman riwayat menyisakan satu kueri karena status eksperimen
#: yang sedang berjalan TIDAK BOLEH di-cache.
WARM_BUDGET = {
    "Progress & Status": 2,
    "Run Experiment": 1,
    "Add Pipeline & Dataset": 1,
}


def _script(module: str, preset: dict, page: str) -> str:
    lines = [
        "import sys",
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})",
        "import streamlit as st",
        "from ui.components import theme",
        "theme.inject()",
        f"st.session_state['_current_page'] = {page!r}",
    ]
    lines += [f"st.session_state[{k!r}] = {v!r}" for k, v in preset.items()]
    lines += [f"from {module} import render", "render()"]
    return "\n".join(lines)


def _run(tmp_path, page: str):
    from streamlit.testing.v1 import AppTest

    module, preset = PAGES[page]
    script = tmp_path / "page.py"
    script.write_text(_script(module, preset, page), encoding="utf-8")
    clear_streamlit_caches()
    at = AppTest.from_file(str(script), default_timeout=900)

    with RenderCost() as cold:
        at.run()
    assert at.exception is None or not at.exception, (page, at.exception)
    with RenderCost() as warm:
        at.run()
    assert at.exception is None or not at.exception, (page, at.exception)
    return cold, warm


@pytest.mark.parametrize("page", sorted(PAGES))
def test_a_page_render_stays_within_its_work_budget(tmp_path, page):
    cold, warm = _run(tmp_path, page)
    assert cold.total <= COLD_BUDGET[page], (page, "dingin", cold.counts)
    assert warm.total <= WARM_BUDGET[page], (page, "panas", warm.counts)


def test_the_cost_counter_actually_observes_work():
    """Penjaga anggaran yang penghitungnya rusak akan lulus tanpa arti.

    Render pertama SELALU melakukan pekerjaan nyata; bila penghitungnya tidak
    melihat apa pun, batas di atas tidak menjaga apa-apa.
    """
    from database.db import list_experiments

    with RenderCost() as cost:
        list_experiments()
        list(Path(REPO_ROOT / "storage").glob("*"))
    assert cost.counts["db"] >= 1
    assert cost.counts["listdir"] >= 1


def test_the_counter_ignores_module_imports_but_sees_data_reads(tmp_path):
    """`open` hanya dihitung untuk berkas DATA, bukan impor modul Python."""
    from tests.render_cost import DATA_ROOT

    outside = tmp_path / "bukan-data.txt"
    outside.write_text("x", encoding="utf-8")
    inside = DATA_ROOT / "datasets"

    with RenderCost() as cost:
        outside.read_text(encoding="utf-8")
    assert cost.counts["open"] == 0

    if inside.exists():
        target = next((p for p in inside.iterdir() if p.is_file()), None)
        if target is not None:
            with RenderCost() as cost:
                with open(target, "rb") as fh:
                    fh.read(1)
            assert cost.counts["open"] == 1


def test_the_history_page_no_longer_reads_an_artifact_per_experiment():
    """ROC-AUC bukan kolom bawaan; membacanya berarti membuka `metrics.json`
    satu per satu untuk kolom yang tidak terlihat."""
    from ui.components import experiment_table as et
    from ui.views.view_results import _roc_column_visible

    assert "auc" not in et.DEFAULT_COLUMNS
    assert _roc_column_visible() is False


def test_the_rows_are_built_once_per_render():
    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
    body = src.split("def render():")[1]
    assert body.count("_build_rows(") == 1


def test_no_dialog_body_reads_files_or_the_database():
    """Data dialog disiapkan SEKALI saat dibuka — berlaku untuk SEMUA dialog."""
    import ast

    heavy = {
        "list_all_experiments", "list_experiments", "get_experiment",
        "get_full_experiment", "get_experiment_metrics", "get_experiment_status",
        "list_submissions", "list_registered", "load_metrics", "load_metadata",
        "diagnose_all", "parse_dataset", "check_health", "glob", "iterdir",
        "read_text", "read_csv", "_all_dataset_options", "_diagnose_selected",
        "_build_artifact_files", "_list_dataset_files", "_dataset_preview",
        "validate_dataset_for_ui", "_experiment_counts",
    }

    found: dict[str, list[str]] = {}
    for rel in ("ui/views/run_experiment.py", "ui/views/view_results.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        bodies = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Call)
                    and getattr(node.func.func, "attr", "") == "dialog_decorator"):
                bodies |= {a.id for a in node.args if isinstance(a, ast.Name)}
        funcs = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        for name in bodies:
            fn = funcs.get(name)
            if fn is None:
                continue
            calls = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                     for c in ast.walk(fn) if isinstance(c, ast.Call)}
            hits = sorted(c for c in calls & heavy if c)
            if hits:
                found[f"{rel}:{name}"] = hits

    assert not found, found


# ── Kesegaran data yang berubah ───────────────────────────────────────────

def test_the_dataset_list_refreshes_after_an_upload(tmp_path, monkeypatch):
    """Cache TIDAK BOLEH membuat berkas yang baru diunggah tak terlihat."""
    import ui.views.run_experiment as run_view

    calls = {"n": 0}

    def fake_cached(nonce: int, root: str):
        calls["n"] += 1
        return ([(f"file-{calls['n']}.csv", "HIKARI2021")], {})

    monkeypatch.setattr(run_view, "_dataset_options_cached", fake_cached)
    monkeypatch.setattr(run_view.st, "session_state", {})

    first = run_view._all_dataset_options()
    again = run_view._all_dataset_options()
    assert first == again or calls["n"] == 2      # nonce sama -> kunci sama

    run_view.invalidate_dataset_options()
    after = run_view._all_dataset_options()
    assert after != first                          # nonce berubah -> dibaca ulang


def test_the_upload_flow_invalidates_the_dataset_list():
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    saved_at = src.index("written = save_dataset_upload(")
    assert "invalidate_dataset_options()" in src[saved_at:saved_at + 1500]


def test_running_experiment_status_is_never_cached():
    """Status yang sedang berjalan harus selalu segar."""
    import ast

    src = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "render":
            calls = {getattr(c.func, "id", None) for c in ast.walk(node)
                     if isinstance(c, ast.Call)}
            assert "list_all_experiments" in calls      # dibaca langsung
    # Dan fungsinya sendiri tidak ber-cache.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_dash_health":
            decorators = [ast.unparse(d) for d in node.decorator_list]
            assert any("ttl=" in d for d in decorators)  # cache PENDEK, bukan abadi


def test_short_lived_caches_declare_a_ttl():
    """Data yang berubah hanya boleh di-cache dengan masa berlaku pendek."""
    import ast

    limits = {
        "_dataset_options_cached": 30,
        "_experiment_counts": 60,
        "_cached_health": 30,
        "_dash_health": 30,
    }
    for rel in ("ui/views/run_experiment.py", "ui/views/view_results.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in limits:
                continue
            text = " ".join(ast.unparse(d) for d in node.decorator_list)
            assert "ttl=" in text, node.name
            ttl = float(text.split("ttl=")[1].split(",")[0].split(")")[0])
            assert ttl <= limits[node.name], (node.name, ttl)
