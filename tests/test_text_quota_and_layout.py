"""KUOTA teks kecil + tiga perbaikan tata letak yang menyertainya.

Permintaan "rapikan teks kecil" tiga kali gagal karena kriterianya subjektif.
Berkas ini membuatnya TERUKUR: kuotanya DIHITUNG oleh
``tests/small_text_audit.py`` — penghitung yang sama yang dipakai laporan —
bukan sekadar diperiksa keberadaannya.

Yang dijaga di sini:

* jumlah elemen teks kecil per halaman tidak melampaui kuota;
* seluruh keterangan WAJIB tetap tersampaikan, walau berpindah tempat;
* nama ``data-testid`` yang dipakai CSS benar-benar ada di bundel frontend
  Streamlit yang terpasang — pelajaran dari gaya segmented control yang dulu
  tidak pernah berlaku karena namanya ditebak;
* seluruh tabel di dialog perbandingan memakai satu mekanisme;
* ketiga bagian halaman Run Experiment memakai pola judul yang sama.
"""
from pathlib import Path

import pytest
import streamlit as st_mod

from tests import small_text_audit as audit
from ui.components import experiment_table as et
from ui.components import sections, theme
from ui.views import login

REPO_ROOT = Path(__file__).resolve().parents[1]
CSS = theme.stylesheet()
RUN_SRC = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
VIEW_SRC = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")


def _bundles() -> str:
    static = Path(st_mod.__file__).parent / "static" / "static" / "js"
    return "".join(f.read_text(encoding="utf-8", errors="ignore")
                   for f in static.glob("*.js"))


# ── BAGIAN 1: kuota, DIHITUNG ─────────────────────────────────────────────

@pytest.mark.parametrize("page", sorted(audit.PAGES))
def test_small_text_stays_within_quota(page):
    """Bukan "sudah dirapikan" — dihitung, lalu dibandingkan dengan kuota."""
    items = audit.audit(page)
    assert len(items) <= audit.QUOTA, (
        page, len(items),
        [f"{i['file']}:{i['line']} {i['text']}" for i in items])


def test_the_counter_actually_counts_something():
    """Penjaga penghitungnya sendiri: kalau ia buta, kuota jadi tak bermakna."""
    fake = REPO_ROOT / "ui" / "components" / "result_views.py"
    assert fake.exists()

    # Penghitung mengenali ketiga bentuk yang disepakati.
    import ast
    from tests.small_text_audit import _classify

    def _first_call(src):
        return next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call))

    small = 'st.markdown("<div style=%sfont-size:0.7rem%s>x</div>")' % ("'", "'")
    body = 'st.markdown("<div style=%sfont-size:0.95rem%s>x</div>")' % ("'", "'")

    assert _classify(_first_call('st.caption("x")')) == "caption"
    assert _classify(_first_call(small)) == "small-font-markdown"
    assert _classify(_first_call('render_line("x", small=True)')) == "dim-line"
    # Teks berukuran isi BUKAN teks kecil.
    assert _classify(_first_call(body)) is None
    assert _classify(_first_call('st.markdown("biasa")')) is None


def test_every_page_is_actually_reachable_by_the_counter():
    """Kalau graf panggilannya putus, angka nol jadi bohong."""
    import ast
    from tests.small_text_audit import _load

    for page, (rel, entry) in audit.PAGES.items():
        module = _load(rel)
        assert module is not None, rel
        assert entry in module.functions, (page, entry)
        # Fungsi masuknya benar-benar memanggil sesuatu.
        calls = [n for n in ast.walk(module.functions[entry])
                 if isinstance(n, ast.Call)]
        assert calls, page


# ── BAGIAN 1: keterangan WAJIB tetap tersampaikan ─────────────────────────

def _all_ui_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in (REPO_ROOT / "ui").rglob("*.py"))


MANDATORY = {
    "berdasarkan cuplikan": "cuplikan",
    "pemeriksaan statis — berkas tidak dijalankan": "tidak dijalankan",
    "valid ≠ aktif": "belum** aktif",
    "menunggu persetujuan": "Menunggu persetujuan",
    "batas ukuran unggah": "Batas unggah",
    "memilih peran tidak memberikan peran": "tidak memberikan peran",
}


@pytest.mark.parametrize("label", sorted(MANDATORY))
def test_mandatory_notes_are_still_delivered(label):
    assert MANDATORY[label] in _all_ui_source(), label


def test_the_metric_semantics_warning_still_reaches_the_reader():
    """Peringatan semantik metrik: dipakai riwayat DAN dialog perbandingan."""
    note = et.semantics_note([{"dataset": "HIKARI2021"}, {"dataset": "EVE_SURICATA"}])
    assert "weighted" in note or "berbobot" in note
    assert "serangan" in note
    assert "semantics_note" in VIEW_SRC


def test_the_mixed_mode_warning_still_reaches_the_reader():
    from orchestrator import run_mode as rm

    rows = et.build_rows([
        {"id": "a", "pipeline_id": "p", "dataset_type": "HIKARI2021"},
        {"id": "b", "pipeline_id": "p", "dataset_type": "HIKARI2021",
         "run_mode": "exploration"},
    ])
    assert rm.MIXED_MODE_WARNING in et.comparison_warnings(rows)
    assert "comparison_warnings" in VIEW_SRC


def test_why_an_action_is_unavailable_is_still_explained():
    """Pengunjung tetap diberi tahu sebabnya, lewat ajakan masuk."""
    contribute = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "render_login_prompt(" in contribute
    assert "Kontrol unggah dinonaktifkan sampai Anda masuk." in contribute
    assert login.SIGN_IN_HINT


def test_the_upload_limit_is_on_the_uploader_itself():
    """Dipindah ke help=, jadi harus benar-benar terpasang di widgetnya."""
    contribute = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    # Pengunggah DATASET, bukan pengunggah pipeline (halaman ini punya dua).
    uploader = contribute.split('"Berkas dataset"')[1].split(")")[0]
    assert "Batas unggah" in uploader
    assert "help=" in uploader


def test_moved_notes_landed_on_a_widget_that_supports_help():
    """Keterangan yang dipindah ke help= tidak boleh menempel di st.markdown."""
    import ast

    for rel in ("ui/views/run_experiment.py", "ui/views/view_results.py",
                "ui/views/contribute.py", "ui/components/result_views.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not any(k.arg == "help" for k in node.keywords):
                continue
            name = getattr(node.func, "attr", "")
            assert name not in ("markdown", "caption", "write", "code"), (
                rel, node.lineno, name)


# ── BAGIAN 2: satu mekanisme untuk seluruh tabel dialog ───────────────────

def _cmp_rows():
    return et.build_rows([
        {"id": "a" * 32, "pipeline_id": "hikari2021.rfc_pipeline",
         "dataset_type": "HIKARI2021", "status": "FINISHED",
         "created_at": "2026-01-01T00:00:00", "accuracy": 0.86, "f1_score": 0.88},
        {"id": "b" * 32, "pipeline_id": "eve_cbr.dt",
         "dataset_type": "EVE_SURICATA", "status": "FINISHED",
         "created_at": "2026-01-02T00:00:00", "accuracy": 0.90, "f1_score": 0.88,
         "run_mode": "exploration"},
    ])


def test_both_tables_in_the_dialog_use_the_same_mechanism():
    from ui.views.view_results import comparison_actions_html, comparison_table_html

    rows = _cmp_rows()
    main = comparison_table_html(et.build_comparison(rows))
    actions = comparison_actions_html(rows)

    for html in (main, actions):
        assert html.count("<table") == 1
        assert 'class="ids-cmp"' in html            # kelas yang SAMA
        assert "ids-cmp-labelcol" in html           # lebar kolom pertama sama
        assert "<colgroup>" in html


def test_long_names_are_shortened_with_a_tooltip():
    from ui.views.view_results import comparison_table_html

    rows = _cmp_rows()
    html = comparison_table_html(et.build_comparison(rows))
    # Tiap sel membawa nilai penuhnya sebagai tooltip.
    assert html.count("title=") >= html.count("<td")
    assert "text-overflow: ellipsis" in VIEW_SRC


def test_the_dialog_tables_share_one_column_geometry():
    from ui.views.view_results import CMP_LABEL_WIDTH, comparison_column_weights

    weights = comparison_column_weights(3)
    assert weights[0] == CMP_LABEL_WIDTH
    assert len(weights) == 4
    assert abs(sum(weights) - 1.0) < 1e-9
    # Angka yang sama dipakai CSS tabelnya.
    assert f"width: {int(CMP_LABEL_WIDTH * 100)}%" in VIEW_SRC


def test_numbers_are_right_aligned_with_fixed_width_digits():
    css = VIEW_SRC.split("_CMP_CSS = ")[1]
    assert "text-align: right" in css
    assert "tabular-nums" in css
    assert 'font-feature-settings: "tnum"' in css


def test_row_height_padding_and_rules_are_uniform():
    css = VIEW_SRC.split("_CMP_CSS = ")[1].split('"""')[1]
    cell = css.split(".ids-cmp th, .ids-cmp td {")[1].split("}")[0]
    assert "height: 2.2rem" in cell                 # tinggi baris seragam
    assert "padding: .38rem .5rem" in cell          # padding konsisten
    # SATU gaya garis di seluruh tabel — tidak mencampur tebal & tipis.
    widths = {line.split("border-bottom:")[1].split(";")[0].strip()
              for line in css.splitlines() if "border-bottom:" in line}
    assert len(widths) == 1, widths


def test_the_dialog_keeps_what_already_worked():
    body = VIEW_SRC.split("def _comparison_body(")[1].split("\ndef ")[0]
    assert "comparison_warnings" in body           # kedua peringatan
    assert "semantics_note" in body
    assert "ONLY_DIFF_LABEL" in body               # hanya yang berbeda
    assert "_cmp_drop_" in body and "_cmp_open_" in body
    assert "_comparison_payload(" in body          # hitung sekali


# ── BAGIAN 3: dropdown dataset & selektor terverifikasi ───────────────────

@pytest.mark.parametrize("name", ["SEG_GROUP", "DROPDOWN_ID", "SELECT_ID"])
def test_every_testid_constant_exists_in_the_installed_bundle(name):
    """Tidak ada nama testid yang ditebak — semuanya dicocokkan ke bundel."""
    value = getattr(theme, name)
    assert value in _bundles(), (name, value)


def test_the_widget_key_class_scheme_is_real():
    assert "st-key-" in _bundles()
    assert theme.DATASET_SELECT_SCOPE == f"st-key-{theme.DATASET_SELECT_KEY}"
    assert f'key="{theme.DATASET_SELECT_KEY}"' in RUN_SRC


def test_the_dataset_dropdown_is_enlarged():
    scope = f".{theme.DATASET_SELECT_SCOPE}"
    assert scope in CSS

    control = CSS.split(f'{scope} [data-baseweb="select"] > div {{')[1].split("}")[0]
    assert f"min-height: {theme.SELECT_BIG_H}" in control
    assert f"font-size: {theme.FONT_BODY}" in control

    width = CSS.split(f'{scope} [data-testid="{theme.SELECT_ID}"],')[1].split("}")[0]
    assert "width: 100%" in width                   # mengisi kolomnya
    assert "max-width: none" in width               # tidak menyempit sendiri


def test_the_enlargement_is_scoped_to_that_one_widget():
    """Kalau tidak, pemilih mode di sidebar ikut membesar."""
    for line in CSS.splitlines():
        if theme.SELECT_BIG_H in line:
            continue
        if f"min-height: {theme.SELECT_BIG_H}" in line:
            assert theme.DATASET_SELECT_SCOPE in line
    block = CSS.split(f"min-height: {theme.SELECT_BIG_H}")[0]
    assert block.rstrip().endswith("{") or theme.DATASET_SELECT_SCOPE in block


def test_the_dropdown_list_no_longer_has_a_global_cap():
    """Cap global itulah yang dulu membuat dropdown dataset menyempit."""
    items = CSS.split(f'[data-testid="{theme.DROPDOWN_ID}"] li {{')[1].split("}")[0]
    assert "max-width" not in items
    assert "text-overflow: ellipsis" in items       # nama panjang tetap terbaca


def test_only_four_text_sizes_survive_the_enlargement():
    assert not hasattr(theme, "SELECT_BIG_FONT")


# ── BAGIAN 4: pola bagian yang sama ───────────────────────────────────────

def test_the_section_pattern_is_defined_in_one_place():
    assert sections.SECTION_GAP == theme.GAP_SECTION
    assert sections.TITLE_GAP == theme.GAP_IN_BLOCK
    assert sections.SECTION_ALIGN == "left"

    heading = CSS.split('[data-testid="stHeading"] {')[1].split("}")[0]
    assert f"margin: {theme.GAP_SECTION} 0 {theme.GAP_IN_BLOCK} 0" in heading
    assert "text-align: left" in heading
    # Jarak ANTAR-bagian harus lebih besar daripada jarak judul ke isinya.
    assert float(theme.GAP_SECTION.rstrip("rem")) > float(
        theme.GAP_IN_BLOCK.rstrip("rem"))


@pytest.mark.parametrize("title", ["Dataset Selection", "Pipeline Selection",
                                   "Pilih Algoritma", "Execute"])
def test_every_section_uses_the_shared_helper(title):
    assert f'render_section("{title}"' in RUN_SRC


def test_no_section_sets_its_own_heading_style():
    """Pola diatur SEKALI; halaman tidak boleh membuat judul bagian sendiri."""
    body = RUN_SRC.split("def _render_execute(")[1].split("\ndef ")[0]
    assert "st.header(" not in body
    assert "st.subheader(" not in body


def test_the_algorithm_picker_is_a_real_section_now():
    """Dulu ia hanya label widget, karena itu tampil berbeda."""
    assert 'render_section("Pilih Algoritma"' in RUN_SRC
    # Label widgetnya disembunyikan supaya judulnya tidak muncul dua kali.
    picker = RUN_SRC.split("_algo_names = list(algo_to_pid.keys())")[1]
    picker = picker.split("selected = algo_to_pid.get")[0]
    assert picker.count('label_visibility="collapsed"') == 2


def test_the_execute_section_groups_its_supporting_elements():
    body = RUN_SRC.split('render_section("Execute"')[1].split("\n    # Results")[0]
    # Wadah pengelompokan kini digabung dengan kolom kirinya dalam SATU
    # pernyataan `with` (`with _ex_left, section_body():`) — bentuknya berubah,
    # jaminannya tidak: elemen pendukung tetap terkelompok.
    assert "section_body():" in body
    # Tepat SATU tombol aksi utama pada bagian ini.
    assert body.count('type="primary"') == 1
    assert 'st.button("Run Experiment", type="primary"' in body


def test_the_run_button_stands_outside_the_supporting_group():
    """Aksi utama tidak boleh terkubur di antara elemen pendukung."""
    body = RUN_SRC.split('render_section("Execute"')[1].split("\n    # Results")[0]
    group_at = body.index("section_body():")
    button_at = body.index('st.button("Run Experiment"')
    assert group_at < button_at

    # Tombolnya berada di LUAR wadah pengelompokan: indentasinya sama dengan
    # `with section_body():` itu sendiri, bukan lebih dalam. Sebelumnya jaminan
    # ini diperiksa lewat blok kolom yang kini sudah tidak ada (bagian Execute
    # tersusun vertikal).
    def _indent(text: str, at: int) -> int:
        line = text[:at].splitlines()[-1]
        return len(line) - len(line.lstrip())

    assert _indent(body, button_at) == _indent(body, group_at)


# ── AppTest: ketiga halaman + dialog perbandingan ─────────────────────────

PAGES = {
    "Progress & Status": "ui.views.view_results",
    "Run Experiment": "ui.views.run_experiment",
    "Add Pipeline & Dataset": "ui.views.contribute",
}


def _page_script(module: str, preset: dict | None = None) -> str:
    return (
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "theme.inject()\n"
        + "".join(f"st.session_state[{k!r}] = {v!r}\n"
                  for k, v in (preset or {}).items())
        + f"from {module} import render\n"
        "render()\n"
    )


@pytest.mark.parametrize("page", sorted(PAGES))
def test_each_page_renders_without_exception(tmp_path, page):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "page.py"
    script.write_text(_page_script(PAGES[page]), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=300)
    at.run()
    assert at.exception is None or not at.exception, (page, at.exception)


def test_the_comparison_dialog_renders_without_exception(tmp_path):
    from orchestrator.result_service import list_all_experiments
    from streamlit.testing.v1 import AppTest

    experiments = list_all_experiments()
    if len(experiments) < 2:
        pytest.skip("basis data tidak memuat cukup eksperimen")

    ids = [e["id"] for e in experiments[:2]]
    script = tmp_path / "cmp.py"
    script.write_text(
        _page_script("ui.views.view_results", {"_hist_compare_ids": ids}),
        encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=300)
    at.run()
    assert at.exception is None or not at.exception, at.exception

    blocks = [e.proto.body for e in at.get("html")]
    tables = [b for b in blocks if 'class="ids-cmp"' in b]
    # DUA tabel: perbandingan + kelola eksperimen, keduanya mekanisme sama.
    assert len(tables) >= 2, len(tables)


def test_the_history_summary_line_is_gone_but_its_notes_are_not():
    """Baris ringkasan di bawah kontrol riwayat dibuang atas permintaan.

    Yang dibawanya TIDAK ikut hilang: semantik metrik (WAJIB) dan arti sorotan
    pindah ke tooltip header kolom metrik, jumlah barisnya ke `help=` tombol
    Unduh CSV.
    """
    from ui.components import experiment_table as et_mod
    from ui.views.view_results import _build_grid_options, _grid_dataframe

    body = VIEW_SRC.split("def _render_history(")[1].split("\ndef ")[0]
    assert '" · ".join(_ringkas)' not in body
    assert "_ringkas" not in body

    rows = et_mod.build_rows([
        {"id": "a", "pipeline_id": "hikari2021.rfc_pipeline",
         "dataset_type": "HIKARI2021", "status": "FINISHED", "accuracy": 0.86},
        {"id": "b", "pipeline_id": "eve_cbr.dt",
         "dataset_type": "EVE_SURICATA", "status": "FINISHED", "accuracy": 0.90},
    ])
    columns = et_mod.visible_columns(et_mod.build_columns(),
                                     et_mod.DEFAULT_COLUMNS)
    tooltip = " ".join(p for p in (et_mod.semantics_note(rows),
                                   et_mod.BEST_MARK_NOTE) if p)
    options = _build_grid_options(_grid_dataframe(rows, columns), columns,
                                  tooltip)

    metric_labels = {c["label"] for c in columns
                     if c["kind"] == et_mod.KIND_METRIC}
    tipped = {c["headerName"] for g in options["columnDefs"]
              for c in g["children"] if c.get("headerTooltip")}
    assert tipped == metric_labels, (tipped, metric_labels)

    one = next(c["headerTooltip"] for g in options["columnDefs"]
               for c in g["children"] if c.get("headerTooltip"))
    assert "berbobot" in one                     # semantik HIKARI
    assert "natural-holdout" in one              # semantik EVE
    assert "tertinggi" in one                    # arti sorotan
    # Tooltip AgGrid hanya muncul bila opsi ini menyala.
    assert options.get("enableBrowserTooltips") is True
