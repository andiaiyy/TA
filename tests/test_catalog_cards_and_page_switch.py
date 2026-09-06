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


# ── Daftar baris katalog ──────────────────────────────────────────────────

def test_the_catalog_renders_rows_not_boxed_cards():
    """Kebalikan dari permintaan sebelumnya: TIDAK ada wadah berbatas per item.

    Yang memisahkan satu research pipeline dari berikutnya adalah garis tipis
    selebar penuh + hierarki jarak, bukan kotak.
    """
    from ui.components import pipeline_catalog as pc

    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert "st.container(border=False, key=row_key(" in body
    assert "border=True" not in body              # tidak ada sisa gaya kartu
    assert pc.row_key("HIKARI2021") == "cat_row_HIKARI2021"


def test_no_card_styling_survives_anywhere():
    """Sisa gaya kartu per item tidak boleh tertinggal di CSS mana pun."""
    from ui.components import theme

    css = theme.stylesheet()
    hook = '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"] {'
    block = css.split(hook)[1].split("}")[0]
    # Kotak = sudut membulat + latar sendiri. Keduanya harus hilang dari baris.
    assert "border-radius" not in block
    assert "background:" not in block
    # Dan tidak ada lagi kunci/awalan kartu yang tersisa di seluruh basis kode.
    assert "cat_card_" not in css
    assert not hasattr(theme, "CARD_KEY_PREFIX")


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
    assert '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]' in theme.stylesheet()


def test_the_row_prefix_has_exactly_one_owner():
    """Gaya dan kode memakai konstanta yang SAMA."""
    from ui.components import pipeline_catalog as pc
    from ui.components import theme

    assert pc.ROW_KEY_PREFIX is theme.ROW_KEY_PREFIX
    assert 'ROW_KEY_PREFIX = "cat_row_"' in (
        REPO_ROOT / "ui" / "components" / "theme.py").read_text(encoding="utf-8")


def test_row_spacing_is_tighter_inside_than_between():
    """Hierarki jarak inilah yang membuat pengelompokan terbaca TANPA kotak."""
    from ui.components import pipeline_catalog as pc
    from ui.components import theme

    hook = '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]'
    block = theme.stylesheet().split(hook + " {")[1].split("}")[0]
    # Jarak ANTAR baris: padding besar di atas & di bawah garis pemisah.
    assert "padding: " + theme.GAP_SECTION in block
    between = float(theme.GAP_SECTION.rstrip("rem"))

    # Jarak DI DALAM baris: margin antar tingkat teks, jauh lebih rapat.
    import re
    inside = [float(m) for m in
              re.findall(r"margin: 0 0 ([0-9.]+)rem", pc._CSS)]
    assert inside, pc._CSS
    assert max(inside) < between, (max(inside), between)


def test_rows_are_separated_by_a_full_width_hairline_with_a_gentle_hover():
    from ui.components import theme

    css = theme.stylesheet()
    hook = '[class*="st-key-' + theme.ROW_KEY_PREFIX + '"]'
    block = css.split(hook + " {")[1].split("}")[0]

    # Garis tipis pemisah, dan TIDAK dibatasi lebar — selebar area konten.
    # Yang diperiksa DEKLARASI-nya, bukan teks komentar yang kebetulan
    # menyebut kata yang sama.
    import re
    declarations = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    assert "border-bottom: 1px solid" in declarations
    assert "max-width:" not in declarations
    # BARIS KATALOG = BLOK DATA: mengikuti lebar penuh kolomnya. Variabelnya
    # tetap satu titik kendali untuk `.ids-cat-*`, tetapi tidak lagi memotong
    # teksnya di ~3/4 lebar sementara garis pemisahnya membentang penuh.
    assert "--ids-cat-textw: none" in declarations

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
    # Lebarnya LUWES: mengisi kolom sampai batas atas, bukan lebar tetap.
    # Diperiksa eksplisit karena "max-width: 9.5rem" memuat substring
    # "width: 9.5rem" — assertion lama lolos tanpa memeriksa apa pun.
    assert "width: 100%" in shared
    assert "max-width: " + theme.CATALOG_BTN_W in shared
    assert "min-height" in shared


def test_the_row_content_did_not_grow():
    """Isi baris TETAP: nama, keterangan, penjelasan, chip, dua tombol.

    Tidak ada teks BARU yang ditambahkan untuk mengisi ruang — ketiga tingkat
    teksnya berasal dari bidang yang memang sudah ada di katalog.
    """
    from ui.components import pipeline_catalog as pc

    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert body.count(".button(") == 2
    for piece in ("row_head_html(", "chips_html("):
        assert piece in body

    # Satu-satunya teks tambahan adalah SEBAB sebuah pipeline tidak dapat
    # dipakai, dan ia BERSYARAT: katalog yang sehat tidak menambah satu baris
    # pun. Yang dijaga penjaga ini tetap sama — tidak ada teks baru untuk
    # mengisi ruang.
    assert body.count("st.caption(") == 1
    assert "group_problems(group)" in body
    healthy = {"dataset_type": "HIKARI2021", "algorithms": [
        {"pipeline_id": "hikari2021.dt_pipeline", "algorithm": "Decision Tree",
         "state": pc.STATE_OK, "state_reason": ""}]}
    assert pc.group_problems(healthy) == []

    head = pc.row_head_html({
        "title": "T", "short": "S", "paper": "P",
        "dataset_type": "DT", "algorithms": [{"algorithm": "A"}],
    })
    for level in ("ids-cat-name", "ids-cat-lead", "ids-cat-note"):
        assert level in head, level


def test_the_summary_row_above_the_cards_survives():
    """Baris ringkasan digambar SEBELUM perulangan barisnya.

    Yang dikunci adalah urutannya, bukan nama variabel yang diulang: sejak
    katalog dapat disaring, yang diulang bukan lagi `catalog` melainkan hasil
    penyaringannya. Mengunci namanya menjadikan tes ini penjaga ejaan, bukan
    penjaga tata letak.
    """
    import re

    body = CATALOG_SRC.split("def render_catalog(")[1].split("\ndef ")[0]
    assert "summary_text(counts)" in body
    loop = re.search(r"for group in (\w+):", body)
    assert loop, "perulangan baris katalog tidak ditemukan"
    assert body.index("summary_text(counts)") < loop.start()


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
