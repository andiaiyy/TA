"""Lima perbaikan tampilan — dan penjaga agar dua di antaranya tidak "diam" lagi.

Dua butir pertama pernah ditulis tetapi TIDAK PERNAH TERLIHAT, dan itu bukan
kebetulan: keduanya gagal pada hal yang tidak diperiksa test mana pun.

* **Segmented control** digayakan lewat testid `stSegmentedControl` — nama yang
  TIDAK ADA di DOM Streamlit. Widgetnya benar, gayanya tidak pernah berlaku.
  Test lama malah mengunci nama yang salah itu, jadi semuanya hijau sementara
  layarnya tidak berubah. Penjaga sekarang: konstanta penyasar dibandingkan
  dengan berkas frontend Streamlit yang BENAR-BENAR terpasang.
* **Graf fase** dikirim lewat ``st.markdown(unsafe_allow_html=True)``. Markdown
  Streamlit melewati react-markdown, yang membangun ulang HTML mentah sebagai
  elemen di namespace HTML — ``<rect>``/``<line>`` di dalamnya tidak pernah
  menjadi bentuk SVG. Ditambah warnanya diserahkan ke kelas CSS eksternal.
  Penjaga sekarang: dirender lewat ``st.html`` dan setiap bentuk membawa atribut
  presentasinya sendiri, jadi graf tidak bergantung stylesheet mana pun.
"""
import ast
from pathlib import Path

import pytest
import streamlit as st_mod

from config.pipeline_registry import PIPELINE_REGISTRY
from ui.components import experiment_table as et
from ui.components import pipeline_catalog as pc
from ui.components import theme
from ui.views import login

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SRC = REPO_ROOT / "ui" / "views" / "run_experiment.py"
CATALOG_SRC = REPO_ROOT / "ui" / "components" / "pipeline_catalog.py"
VIEW_SRC = REPO_ROOT / "ui" / "views" / "view_results.py"
CSS = theme.stylesheet()


def _info(pipeline_id: str) -> dict:
    return PIPELINE_REGISTRY[pipeline_id]["class"]().get_info() or {}


# ── 1. Pemilih algoritma = segmented control ──────────────────────────────

def test_the_algorithm_picker_uses_the_segmented_widget():
    """Bukan dropdown/selectbox/radio vertikal."""
    body = RUN_SRC.read_text(encoding="utf-8").split("_algo_names = ")[1]
    body = body.split("selected = algo_to_pid.get")[0]

    assert 'hasattr(st, "segmented_control")' in body
    assert "st.segmented_control(" in body
    assert "st.selectbox(" not in body
    # Padanan untuk Streamlit lama boleh radio, tetapi HARUS mendatar.
    assert "horizontal=True" in body


def test_the_installed_streamlit_really_has_the_segmented_widget():
    """Kalau tidak ada, cabang padanannya yang dipakai — dan itu harus disadari."""
    assert hasattr(st_mod, "segmented_control")


def test_the_segmented_styling_targets_names_that_exist_in_the_dom():
    """INTI bug butir 1. Penyasar dibandingkan dengan frontend terpasang."""
    static = Path(st_mod.__file__).parent / "static" / "static" / "js"
    bundles = "".join(f.read_text(encoding="utf-8", errors="ignore")
                      for f in static.glob("*.js"))
    assert bundles, "berkas frontend Streamlit tidak ditemukan"

    assert theme.SEG_GROUP in bundles
    assert "segmented_controlActive" in bundles
    assert f'[data-testid="{theme.SEG_GROUP}"]' in CSS
    assert f'[data-testid="{theme.SEG_ITEM_ACTIVE}"]' in CSS
    # Nama lama tidak boleh kembali sebagai penyasar.
    assert "stSegmented" + "Control" not in CSS


def test_the_container_is_soft_and_the_active_option_is_a_raised_card():
    container = CSS.split(f'[data-testid="{theme.SEG_GROUP}"] {{')[1].split("}")[0]
    assert "background: rgba(127,127,127,.09)" in container   # wadah lembut
    assert "border-radius" in container

    active = CSS.split(f'[data-testid="{theme.SEG_ITEM_ACTIVE}"],')[1].split("}")[0]
    assert "box-shadow:" in active                            # terangkat
    assert "background: rgba(127,127,127,.26)" in active       # latar kontras

    idle = CSS.split(f'[data-testid="{theme.SEG_GROUP}"] button {{')[1].split("}")[0]
    assert "background: transparent" in idle                   # lain: tanpa latar
    assert "opacity: .62" in idle                              # dan redup


def test_six_hikari_algorithms_may_wrap_but_are_never_cut_off():
    hikari = [e for e in PIPELINE_REGISTRY.values()
              if e["dataset_type"] == "HIKARI2021"]
    assert len(hikari) == 6

    container = CSS.split(f'[data-testid="{theme.SEG_GROUP}"] {{')[1].split("}")[0]
    assert "flex-wrap: wrap" in container
    idle = CSS.split(f'[data-testid="{theme.SEG_GROUP}"] button {{')[1].split("}")[0]
    assert "white-space: normal" in idle          # boleh membungkus
    assert "text-overflow" not in idle            # tidak dipotong "…"
    assert "height: auto" in idle                 # baris kedua muat


def test_the_selection_behaviour_is_unchanged():
    """Nilai terpilih tetap diteruskan lewat jalur yang sama."""
    src = RUN_SRC.read_text(encoding="utf-8")
    assert "selected = algo_to_pid.get(algorithm) if algorithm else None" in src
    assert 'st.session_state["selected_pipeline"] = selected' in src
    # Kedua cabang memakai key yang sama, jadi hasilnya identik apa pun cabangnya.
    assert src.count('key="algorithm_select"') == 2


# ── 2. Graf fase di modal detail ──────────────────────────────────────────

def test_the_phase_graph_is_rendered_inside_the_detail_modal():
    body = CATALOG_SRC.read_text(encoding="utf-8").split(
        "def render_modal_body(")[1].split(chr(10) + "def ")[0]
    assert "render_phase_graph(" in body


def test_the_graph_is_sent_through_st_html_not_markdown():
    """INTI bug butir 2: markdown Streamlit tidak menggambar SVG."""
    body = CATALOG_SRC.read_text(encoding="utf-8").split(
        "def render_phase_graph(")[1].split(chr(10) + "def ")[0]
    assert "st.html(" in body
    # markdown hanya boleh sebagai cadangan Streamlit lama.
    assert 'hasattr(st, "html")' in body


def test_every_shape_carries_its_own_colour():
    """Graf harus terbaca tanpa stylesheet eksternal apa pun.

    Tanpa ini, `<rect>` jatuh ke bawaan SVG (isi hitam pekat) begitu blok gaya
    katalog tidak ikut ke cakupan DOM yang sama.
    """
    svg = pc.phase_graph_svg(pc.phase_graph_stages(
        "hikari2021.dt_pipeline", _info("hikari2021.dt_pipeline")))
    for shape, attr in (("<rect", "stroke="), ("<line", "stroke="),
                        ("<text", "fill=")):
        chunks = [c for c in svg.split("<") if c.startswith(shape[1:])]
        assert chunks
        for chunk in chunks:
            assert attr in chunk, chunk[:60]


def test_the_graph_is_theme_safe_and_needs_no_external_library():
    svg = pc.phase_graph_svg(pc.phase_graph_stages(
        "eve_cbr.xgb", _info("eve_cbr.xgb")))
    # Warna mengikuti tema lewat currentColor — tidak ada heksa yang dipaku.
    assert "currentColor" in svg
    assert "#" not in svg.split("<title>")[0]
    for token in ("cdn.", "https://", "<script", "@import"):
        assert token not in svg.replace("http://www.w3.org/2000/svg", ""), token


def test_the_graph_carries_alt_text():
    stages = pc.phase_graph_stages("hikari2021.dt_pipeline",
                                   _info("hikari2021.dt_pipeline"))
    svg = pc.phase_graph_svg(stages)
    assert 'role="img"' in svg
    assert "<title>" in svg
    assert "aria-label=" in svg
    assert pc.phase_graph_alt(stages)


def test_many_stages_scroll_horizontally_instead_of_wrapping():
    svg = pc.phase_graph_svg(pc.phase_graph_stages(
        "eve_cbr.xgb", _info("eve_cbr.xgb")))
    assert "overflow-x:auto" in svg          # digulir, bukan dibungkus
    assert "viewBox=" in svg


def test_the_orchestrator_stage_is_styled_differently_and_explained():
    svg = pc.phase_graph_svg(pc.phase_graph_stages(
        "hikari2021.dt_pipeline", _info("hikari2021.dt_pipeline")))
    assert "stroke-dasharray" in svg         # garis putus untuk tahap platform
    assert svg.count("stroke-dasharray") == len(pc.PRE_STAGES)
    assert "platform" in pc.PRE_STAGE_NOTE.lower()


# ── 2b. Graf BERBEDA antar pipeline (bukan template seragam) ──────────────

def _labels(pipeline_id):
    return [s["label"] for s in
            pc.phase_graph_stages(pipeline_id, _info(pipeline_id))]


def test_a_pipeline_without_feature_selection_never_shows_that_stage():
    for pipeline_id in ("hikari2021.nbgc_pipeline", "hikari2021.dt_pipeline"):
        info = _info(pipeline_id)
        assert not pc.uses_feature_selection(info.get("feature_selection"))
        assert "Feature selection" not in _labels(pipeline_id)


def test_a_pipeline_with_feature_selection_shows_it_before_training():
    labels = _labels("hikari2021.lr_pipeline")
    assert "Feature selection" in labels
    training = next(i for i, l in enumerate(labels) if "train" in l.lower())
    assert labels.index("Feature selection") < training


def test_two_different_pipelines_produce_different_graphs():
    """Bukti butir 2: satu HIKARI tanpa seleksi fitur vs satu EVE."""
    hikari = _labels("hikari2021.nbgc_pipeline")
    eve = _labels("eve_cbr.xgb")

    assert hikari != eve
    assert len(hikari) == 3 and len(eve) == 10
    assert "Feature selection" not in hikari
    assert "Feature selection" in eve
    # Isinya pun berbeda, bukan sekadar panjangnya.
    assert not set(hikari) & set(eve)


def test_the_stage_counts_are_not_uniform_across_the_registry():
    counts = {pid: len(_labels(pid)) for pid in PIPELINE_REGISTRY}
    assert len(set(counts.values())) > 1, counts
    assert counts["hikari2021.nbgc_pipeline"] < counts["eve_cbr.xgb"]


def test_the_stages_come_from_the_registry_not_a_hardcoded_list():
    """Tahap dibaca lewat pembaca yang disuntikkan — bukan daftar tetap."""
    fake = {"stages": ["A", "B"]}
    labels = [s["label"] for s in pc.phase_graph_stages(
        "apa pun", {"feature_selection": "None"}, registry_reader=lambda _p: fake)]
    assert labels == ["A", "B"]


# ── 3. Dialog perbandingan ────────────────────────────────────────────────

def _rows(*extra):
    base = dict(pipeline_id="hikari2021.rfc_pipeline", dataset_type="HIKARI2021",
                status="FINISHED", created_at="2026-01-01T00:00:00",
                accuracy=0.86, f1_score=0.88)
    return et.build_rows([{**base, "id": f"exp{i}" * 8, **e}
                          for i, e in enumerate(extra)])


def test_the_comparison_groups_rows_and_aligns_numbers():
    from ui.views.view_results import comparison_table_html

    rows = _rows({}, {"accuracy": 0.9})
    data = et.build_comparison(rows)
    groups = [s["group"] for s in data["sections"]]
    assert groups == [g for g in et.GROUP_ORDER if g in groups]
    assert et.GROUP_IDENTITY in groups and et.GROUP_METRIC in groups

    metric = next(f for s in data["sections"] for f in s["fields"]
                  if f["label"] == "Accuracy")
    assert metric["align"] == et.ALIGN_RIGHT
    label_field = next(f for s in data["sections"] for f in s["fields"]
                       if f["label"] == "Pipeline")
    assert label_field["align"] == et.ALIGN_LEFT

    html = comparison_table_html(data)
    assert html.count("<table") == 1               # satu tabel = kolom selaras
    assert "ids-cmp-group" in html                 # pemisah antar-kelompok
    assert "ids-cmp-r" in html and "ids-cmp-l" in html


def test_differing_rows_are_marked_and_equal_rows_are_left_quiet():
    rows = _rows({}, {"accuracy": 0.9})
    data = et.build_comparison(rows)
    by_label = {f["label"]: f for s in data["sections"] for f in s["fields"]}
    assert by_label["Accuracy"]["differs"] is True
    assert by_label["Pipeline"]["differs"] is False


def test_only_differences_hides_the_rest():
    rows = _rows({}, {"accuracy": 0.9})
    full = et.build_comparison(rows)
    slim = et.build_comparison(rows, only_differences=True)

    shown = [f["label"] for s in slim["sections"] for f in s["fields"]]
    assert shown and all(
        next(f for x in full["sections"] for f in x["fields"]
             if f["label"] == label)["differs"] for label in shown)
    assert slim["diff_count"] == full["diff_count"]
    assert slim["total_count"] == full["total_count"]


def test_dropping_an_experiment_updates_the_table_without_reading_anything():
    rows = _rows({}, {"accuracy": 0.9}, {"accuracy": 0.7})
    left = et.drop_from_comparison(rows, rows[1]["_id"])

    assert [r["_id"] for r in left] == [rows[0]["_id"], rows[2]["_id"]]
    data = et.build_comparison(left)
    assert len(data["headers"]) == 2
    assert data["ids"] == [rows[0]["_id"], rows[2]["_id"]]


def test_the_comparison_keeps_both_mandatory_warnings():
    rows = _rows({}, {"dataset_type": "EVE_SURICATA", "pipeline_id": "eve_cbr.dt",
                      "run_mode": "exploration"})
    warnings = et.comparison_warnings(rows)
    from orchestrator import run_mode as rm

    assert rm.MIXED_MODE_WARNING in warnings            # campuran mode
    assert et.CROSS_FAMILY_WARNING in warnings          # semantik metrik


def test_the_dialog_computes_its_data_once_and_stores_it():
    """Interaksi di dalam modal tidak boleh memicu pembacaan berkas/DB ulang."""
    src = VIEW_SRC.read_text(encoding="utf-8")
    body = src.split("def _comparison_payload(")[1].split(chr(10) + "def ")[0]
    assert "dlg.payload(" in body and "dlg.store_payload(" in body

    dialog = src.split("def _comparison_body(")[1].split(chr(10) + "def ")[0]
    # Badan modal hanya membaca payload; tidak ada pembacaan DB/artefak di sana.
    for reader in ("get_full_experiment", "list_all_experiments",
                   "load_metrics", "load_metadata", "_roc_auc"):
        assert reader not in dialog, reader
    assert "_comparison_payload(" in dialog


def test_the_dialog_offers_dropping_and_opening_details():
    dialog = VIEW_SRC.read_text(encoding="utf-8").split(
        "def _comparison_body(")[1].split(chr(10) + "def ")[0]
    assert "_cmp_drop_" in dialog and "_drop_from_comparison(" in dialog
    assert "_cmp_open_" in dialog and "dlg.open_dialog(dlg.DETAIL_KEY" in dialog


def test_every_exit_clears_the_comparison_flag_and_payload():
    src = VIEW_SRC.read_text(encoding="utf-8")
    # Tutup, buka-detail, dan pilihan menyusut: semuanya lewat satu pembersih.
    assert src.count("_close_comparison()") >= 2
    closer = src.split("def _close_comparison(")[1].split(chr(10) + "def ")[0]
    assert "close_dialog(_COMPARE_KEY)" in closer
    assert "clear_payload(_COMPARE_KEY)" in closer

    # Berpindah halaman: flag ikut daftar terpusat.
    from ui.components import dialogs as dlg
    assert dlg.COMPARE_KEY in dlg.DIALOG_KEYS


# ── 4. Teks pengunjung tidak ambigu ───────────────────────────────────────

def test_the_visitor_line_names_what_can_actually_be_done():
    from ui.components.contribute_context import capability

    what = capability(None)["what"]
    assert "membaca persyaratan" in what
    assert "memeriksa kecocokan dataset" in what
    assert "Kontributor" in what
    # Frasa ambigu lama benar-benar hilang.
    assert "menjalankan pemeriksaan" not in what


def test_the_visitor_line_matches_real_behaviour():
    """Yang dituliskan harus benar: pengunjung memang tidak dapat mengunggah."""
    from orchestrator.auth_service import can_approve, can_upload

    assert can_upload(None) is False
    assert can_approve(None) is False

    # Dan diagnosa kecocokan memang berada SEBELUM gerbang izin, jadi
    # "memeriksa kecocokan dataset" bukan kemampuan yang dikarang.
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    tab = src.split("def _render_dataset_server_tab(")[1].split(chr(10) + "def ")[0]
    assert 't("ap.btn_check_compat")' in tab
    assert "can_upload" not in tab and "require_upload" not in tab


def test_no_bare_pemeriksaan_is_left_in_the_page_texts():
    """Setiap "pemeriksaan" yang tampil menyebut OBJEK-nya."""
    import ui.components.contribute_context as cc

    texts = [cc.capability(None)["what"], cc.AFTER_UPLOAD_FLOW_ALT]
    texts += [label for _icon, label in cc.AFTER_UPLOAD_FLOW]
    for text in texts:
        low = text.lower()
        for bare in ("menjalankan pemeriksaan", "periksa otomatis",
                     "setelah diperiksa:"):
            assert bare not in low, text


# ── 5. Pemilih mode = dropdown ringkas ────────────────────────────────────

def test_the_mode_switch_is_a_dropdown():
    body = Path(login.__file__).read_text(encoding="utf-8").split(
        "def render_mode_switch()")[1].split(chr(10) + "def ")[0]
    assert "st.selectbox(" in body
    assert "st.popover(" not in body             # dulu bocor keluar sidebar
    assert "auth_pick_" not in body              # bukan barisan tombol lagi


def test_the_dropdown_options_are_short_labels():
    options = login.mode_options()
    assert options[0] == "Pengunjung"
    assert "Kontributor" in options and "Research Admin" in options
    for option in options:
        assert len(option) <= 16, option
        assert len(option.split()) <= 2, option


def test_the_dropdown_stays_inside_the_sidebar():
    """Daftar mode tetap sempit — TETAPI lewat kontrol pemicunya.

    Dulu lebar daftar dikekang langsung lewat `max-width` pada
    `stSelectboxVirtualDropdown`. Aturan itu berlaku GLOBAL (daftarnya dirender
    ke `document.body`, jadi tidak bisa dibedakan per halaman), sehingga
    pemilih dataset di Run Experiment ikut menyempit. Yang benar adalah
    mengekang KONTROL-nya: baseui menyamakan lebar daftar dengan lebar kontrol
    pemicunya, jadi daftar mode tetap sempit tanpa menyeret dropdown lain.
    """
    control = CSS.split(
        '[data-testid="stSidebar"] [data-baseweb="select"] {')[1].split("}")[0]
    assert f"max-width: {theme.POPOVER_MAX_W}" in control
    assert float(theme.POPOVER_MAX_W.rstrip("rem")) <= 14      # sidebar ±21rem

    # Cap global pada daftar TIDAK boleh kembali.
    items = CSS.split(f'[data-testid="{theme.DROPDOWN_ID}"] li {{')[1].split("}")[0]
    assert "max-width" not in items
    assert "min-height: 0" in items
    assert "white-space: nowrap" in items                      # satu baris
    assert "text-overflow: ellipsis" in items                  # nama panjang


def test_the_dropdown_name_exists_in_the_installed_frontend():
    """Pelajaran butir 1: penyasar tidak boleh ditebak."""
    static = Path(st_mod.__file__).parent / "static" / "static" / "js"
    bundles = "".join(f.read_text(encoding="utf-8", errors="ignore")
                      for f in static.glob("*.js"))
    assert theme.DROPDOWN_ID in bundles


def test_the_mode_block_is_still_the_last_thing_in_the_sidebar():
    body = Path(login.__file__).read_text(encoding="utf-8").split(
        "def render_mode_switch()")[1].split(chr(10) + "def ")[0]
    assert "with st.sidebar:" in body
    assert "_MODE_ANCHOR" in body
    assert ".ids-mode-anchor" in CSS
    assert "margin-top: auto" in CSS


def test_picking_a_role_writes_no_role_anywhere():
    """Aturan yang tidak boleh goyah oleh perubahan bentuk kontrol."""
    tree = ast.parse(Path(login.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_mode_switch")

    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                assert not isinstance(target, ast.Subscript), ast.dump(target)

    called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "request_auth_dialog" in called       # hanya membuka jalur masuk
    assert "authenticate" not in called
    assert "create_user" not in called


def test_the_help_text_keeps_the_honest_note():
    assert "tidak memberikan peran" in login._MODE_PICK_HELP
    assert "bukan dipilih di sini" in login._MODE_PICK_HELP


# ── Ketiga halaman terender untuk tiga status ─────────────────────────────

PAGES = ("Progress & Status", "Run Experiment", "Add Pipeline & Dataset")
IDENTITIES = {
    "pengunjung": None,
    "kontributor": {"username": "rina", "role": "contributor", "status": "active"},
    "research_admin": {"username": "ai", "role": "research_admin", "status": "active"},
}


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("who", sorted(IDENTITIES))
def test_every_page_renders_for_every_identity(tmp_path, page, who):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "app_probe.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, r{str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from ui.components import theme\n"
        "from ui.views.login import render_mode_switch\n"
        "theme.inject()\n"
        f"page = {page!r}\n"
        "st.session_state['_current_page'] = page\n"
        "if page == 'Progress & Status':\n"
        "    from ui.views.view_results import render\n"
        "elif page == 'Run Experiment':\n"
        "    from ui.views.run_experiment import render\n"
        "else:\n"
        "    from ui.views.contribute import render\n"
        "render()\n"
        "render_mode_switch()\n",
        encoding="utf-8")

    at = AppTest.from_file(str(script), default_timeout=300)
    user = IDENTITIES[who]
    if user:
        at.session_state[login.SESSION_USER_KEY] = user
    at.run()
    assert at.exception is None or not at.exception, (page, who, at.exception)

    # Pemilih mode selalu hadir, dan menunjuk mode yang benar.
    picker = at.selectbox(key="auth_mode_pick")
    expected = "Pengunjung" if user is None else login.role_label(user["role"])
    assert picker.value == expected
