"""Kartu katalog, expander berkelompok, dan sisa halaman saat berpindah.

Tiga hal tampilan dan satu bug perilaku:

* katalog berupa KARTU BERKOTAK — jarak di dalam kartu lebih rapat daripada
  jarak antar kartu, tombolnya seragam, sorotnya halus;
* expander "Tentang Research Pipeline" berupa label-nilai BERKELOMPOK, dan
  isinya tidak boleh berkurang sedikit pun dibanding bentuk bullet lamanya;
* berpindah halaman saat eksperimen berjalan tidak meninggalkan sisa gambar
  halaman sebelumnya, sementara pantauan eksperimennya tetap utuh.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SRC = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
RESULTS_SRC = (REPO_ROOT / "ui" / "views" / "view_results.py").read_text(encoding="utf-8")
APP_SRC = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
FLAGS_SRC = (REPO_ROOT / "ui" / "components" / "page_flags.py").read_text(encoding="utf-8")
CATALOG_SRC = (REPO_ROOT / "ui" / "components" / "pipeline_catalog.py").read_text(
    encoding="utf-8")


# ── Kartu katalog ─────────────────────────────────────────────────────────

def test_the_catalog_renders_boxed_cards_not_hairline_separators():
    """Tiap research pipeline berada dalam wadah BERBATAS, bukan dipisah garis."""
    from ui.components import pipeline_catalog as pc

    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert "st.container(border=True, key=card_key(" in body
    assert "ids-cat-sep" not in body              # pemisah garis lama hilang
    assert pc.card_key("HIKARI2021") == "cat_card_HIKARI2021"


def test_the_card_css_hook_matches_the_installed_frontend():
    """Kaitan CSS kartu adalah kelas `st-key-<key>` yang BENAR-BENAR ada pada
    bundel frontend terpasang — bukan testid tebakan."""
    import streamlit as st_mod

    from ui.components import theme

    bundle_dir = Path(st_mod.__file__).parent / "static" / "static" / "js"
    bundles = list(bundle_dir.glob("*.js"))
    assert bundles, bundle_dir
    assert any("st-key-" in b.read_text(encoding="utf-8", errors="ignore")
               for b in bundles)
    assert '[class*="st-key-' + theme.CARD_KEY_PREFIX + '"]' in theme.stylesheet()


def test_the_card_prefix_has_exactly_one_owner():
    """Gaya dan kode memakai konstanta yang SAMA."""
    from ui.components import pipeline_catalog as pc
    from ui.components import theme

    assert pc.CARD_KEY_PREFIX is theme.CARD_KEY_PREFIX
    assert 'CARD_KEY_PREFIX = "cat_card_"' in (
        REPO_ROOT / "ui" / "components" / "theme.py").read_text(encoding="utf-8")


def test_card_spacing_is_tighter_inside_than_between():
    from ui.components import theme

    hook = '[class*="st-key-' + theme.CARD_KEY_PREFIX + '"]'
    block = theme.stylesheet().split(hook + " {")[1].split("}")[0]
    assert "margin-bottom: " + theme.GAP_BETWEEN_BLOCKS in block   # antar kartu
    assert theme.GAP_IN_BLOCK in block                             # dalam kartu
    assert float(theme.GAP_IN_BLOCK.rstrip("rem")) < float(
        theme.GAP_BETWEEN_BLOCKS.rstrip("rem"))


def test_cards_have_a_max_width_and_a_gentle_hover():
    from ui.components import theme

    css = theme.stylesheet()
    hook = '[class*="st-key-' + theme.CARD_KEY_PREFIX + '"]'
    block = css.split(hook + " {")[1].split("}")[0]
    assert "max-width: " + theme.CARD_MAX_W in block
    assert "border-radius" in block
    assert "background" in block                 # latar beda dari halaman

    hover = css.split(hook + ":hover {")[1].split("}")[0]
    assert "background" in hover
    for heavy in ("transform", "box-shadow"):    # sorot HALUS, tidak berat
        assert heavy not in hover
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_the_two_card_buttons_stay_uniform():
    from ui.components import theme

    css = theme.stylesheet()
    shared = css.split('[class*="st-key-cat_run_"] button, '
                       '[class*="st-key-cat_detail_"] button {')[1].split("}")[0]
    assert "width: " + theme.CATALOG_BTN_W in shared
    assert "min-height" in shared


def test_the_card_content_did_not_grow():
    """Isi kartu TETAP: nama, penjelasan singkat, chip, dua tombol."""
    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert body.count(".button(") == 2
    for piece in ("ids-cat-title", "ids-cat-short", "chips_html("):
        assert piece in body
    assert "st.caption(" not in body


def test_the_summary_row_above_the_cards_survives():
    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert "summary_text(counts)" in body
    assert body.index("summary_text(counts)") < body.index("for group in catalog")


# ── Expander "Tentang Research Pipeline" ─────────────────────────────────

PIPELINES = (("HIKARI2021", "hikari2021.rfc_pipeline"),
             ("EVE_SURICATA", "eve_cbr.xgb"))


def _groups(dtype: str, pid: str):
    from config.pipeline_registry import PIPELINE_REGISTRY
    from config.research_attribution import get_research_attribution
    from ui.views.run_experiment import _dataset_info_lines, research_about_groups

    info = PIPELINE_REGISTRY[pid]["class"]().get_info() or {}
    return (research_about_groups(dtype, "Label", info,
                                  get_research_attribution(dtype),
                                  _dataset_info_lines(dtype)),
            info, get_research_attribution(dtype))


def test_the_about_expander_keeps_every_piece_of_information():
    """Bentuknya berubah menjadi label-nilai; ISINYA tidak boleh berkurang."""
    from ui.views.run_experiment import _dataset_info_lines

    for dtype, pid in PIPELINES:
        groups, info, attribution = _groups(dtype, pid)
        rendered = " ".join(str(v) for _t, pairs in groups for _k, v in pairs)

        source = attribution.get("pipeline_source") or {}
        for key in ("type", "authors", "title", "institution"):
            if source.get(key):
                assert str(source[key]) in rendered, (dtype, key)
        if source.get("year"):
            assert str(source["year"]) in rendered
        if attribution.get("scope"):
            assert str(attribution["scope"]) in rendered
        for key in ("paper", "feature_selection", "app", "metrics_policy"):
            if info.get(key):
                assert str(info[key]) in rendered, (dtype, key)
        for item in info.get("anti_leakage") or []:
            assert str(item) in rendered
        for line in _dataset_info_lines(dtype):
            value = line.split(":**", 1)[1] if ":**" in line else line
            assert value.strip() in rendered, (dtype, line[:40])


def test_the_about_expander_is_grouped_label_value_not_nested_bullets():
    groups, _info, _attr = _groups(*PIPELINES[0])
    assert [t for t, _ in groups] == ["Penelitian sumber", "Dataset",
                                      "Cakupan & metode"]

    # Judul panjang tetap SATU nilai, tidak dipecah menjadi beberapa baris.
    judul = dict(groups[0][1])["Judul"]
    assert "\n" not in judul and len(judul) > 40

    body = RUN_SRC.split('st.expander("Tentang Research Pipeline')[1][:1600]
    assert "render_facts(_pairs, columns=1)" in body
    assert "  - **" not in body                  # bullet bertingkat lama hilang


def test_long_values_are_not_split_across_pairs():
    """Kalimat paper tetap utuh sebagai satu nilai."""
    for dtype, pid in PIPELINES:
        groups, info, _attr = _groups(dtype, pid)
        if info.get("paper"):
            assert dict(groups[0][1])["Paper"] == info["paper"]


def test_empty_groups_are_dropped_instead_of_shown_empty():
    from ui.views.run_experiment import research_about_groups

    titles = [t for t, _ in research_about_groups("X", "", {}, {}, ())]
    assert "Cakupan & metode" not in titles


def test_a_line_without_a_bold_label_is_kept_whole():
    from ui.views.run_experiment import _strip_markdown_label

    assert _strip_markdown_label("**Format berkas:** CSV") == ("Format berkas", "CSV")
    assert _strip_markdown_label("tanpa label") == ("", "tanpa label")


# ── BUG: sisa halaman sebelumnya saat berpindah ──────────────────────────

def test_page_content_lives_in_one_placeholder_cleared_on_switch():
    """Sisa halaman sebelumnya dibuang SEBELUM halaman baru digambar."""
    assert "_page_slot = st.empty()" in APP_SRC
    assert "_page_changed = drop_stale_page_flags(page)" in APP_SRC

    routing = APP_SRC.split("# ── Page routing")[1]
    clear_at = routing.index("_page_slot.empty()")
    draw_at = routing.index("with _page_slot.container():")
    assert clear_at < draw_at
    for view in ("view_results", "run_experiment", "contribute"):
        assert routing.index(view) > draw_at, view


def test_the_periodic_refresh_is_bound_to_its_page():
    """Perulangan pembaruan tidak boleh terus menggambar setelah pindah."""
    from ui.views import run_experiment as run_view
    from ui.views import view_results as results_view

    assert run_view.PAGE_NAME == "Run Experiment"
    assert results_view.PAGE_NAME == "Progress & Status"
    for src in (RUN_SRC, RESULTS_SRC):
        assert "wait_before_refresh(interval, page=PAGE_NAME)" in src
        assert "time.sleep(interval)" not in src   # tidur pemblokir lama hilang


def test_page_names_match_the_real_menu():
    import re

    from ui.views import run_experiment as run_view
    from ui.views import view_results as results_view

    listed = re.search(r"_PAGES\s*=\s*\(([^)]*)\)", APP_SRC, re.S).group(1)
    names = re.findall(r'"([^"]+)"', listed)
    assert run_view.PAGE_NAME in names
    assert results_view.PAGE_NAME in names


def test_waiting_is_interruptible_rather_than_one_long_sleep():
    """Streamlit hanya memeriksa permintaan rerun di sela pemanggilan `st.*`;
    tidur satu kali panjang menahan klik pengguna dan menyisakan gambar lama."""
    from ui.components import page_flags

    body = FLAGS_SRC.split("def wait_before_refresh(")[1].split("\ndef ")[0]
    assert "while True:" in body
    assert "slot.markdown(" in body              # titik periksa
    assert "slot.empty()" in body                # tidak meninggalkan jejak
    assert page_flags.REFRESH_TICK_SECONDS <= 1


def test_waiting_stops_when_the_page_changed(monkeypatch):
    """Halaman berganti selagi menunggu -> False, pemanggil berhenti menggambar."""
    import streamlit as st_mod

    from ui.components import page_flags

    class _Slot:
        def markdown(self, *_a, **_k):
            pass

        def empty(self):
            pass

    monkeypatch.setattr(st_mod, "empty", lambda: _Slot())
    monkeypatch.setattr(page_flags, "page_is_active", lambda name: False)
    assert page_flags.wait_before_refresh(5, page="Run Experiment") is False


def test_waiting_completes_when_the_page_is_still_active(monkeypatch):
    import streamlit as st_mod

    from ui.components import page_flags

    class _Slot:
        def markdown(self, *_a, **_k):
            pass

        def empty(self):
            pass

    monkeypatch.setattr(st_mod, "empty", lambda: _Slot())
    monkeypatch.setattr(page_flags, "page_is_active", lambda name: True)
    monkeypatch.setattr(page_flags, "REFRESH_TICK_SECONDS", 0.01)
    assert page_flags.wait_before_refresh(1, page="Run Experiment") is True


def test_monitoring_state_survives_a_page_switch():
    """Yang dihentikan hanya penggambaran — eksperimennya tetap terpantau."""
    from ui.components import page_flags

    joined = " ".join(page_flags.PAGE_SCOPED_KEYS)
    assert "polling_experiment_id" not in joined
    assert "_stage_starts" not in joined

    body = RUN_SRC.split("def _poll_experiment(")[1].split("\ndef ")[0]
    # Cabang "masih berjalan" — sampai cabang status berikutnya.
    running_branch = body.split('if status in ("QUEUED", "RUNNING"):')[1].split(
        "\n    elif status ==")[0]
    assert "wait_before_refresh(" in running_branch
    # Menunggu / berpindah halaman TIDAK PERNAH membuang kunci pantauan. Yang
    # boleh membuangnya hanya tombol Batalkan (permintaan pengguna) dan cabang
    # selesai/gagal — bukan jalur tunggu ini.
    wait_tail = running_branch[running_branch.index("wait_before_refresh("):]
    assert 'pop("polling_experiment_id"' not in wait_tail
    assert "Cancel Experiment" not in wait_tail


def test_the_sidebar_progress_fragment_only_draws_into_the_sidebar():
    """Fragmen sidebar BUKAN penyebab sisa di area utama: ia hanya menggambar
    ke sidebar, dan memang harus tetap hidup di semua halaman."""
    src = (REPO_ROOT / "ui" / "components" / "sidebar_progress.py").read_text(
        encoding="utf-8")
    body = src.split("def render_sidebar_progress(")[1]
    assert "with st.sidebar:" in body


def test_no_widget_key_is_shared_between_pages():
    """Tabrakan kunci antar-halaman akan membuat elemen lama dipakai ulang."""
    import ast
    import collections

    keys = collections.defaultdict(set)
    for name in ("view_results", "run_experiment", "contribute"):
        tree = ast.parse((REPO_ROOT / "ui" / "views" / f"{name}.py")
                         .read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (kw.arg == "key" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    keys[kw.value.value].add(name)
    shared = {k: sorted(v) for k, v in keys.items() if len(v) > 1}
    assert not shared, shared
