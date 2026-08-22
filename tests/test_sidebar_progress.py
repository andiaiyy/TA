"""Tests for the sidebar "Sedang berjalan" block.

Three things must hold:

  * the view model is **pure** — 0 / 1–3 / >3 running experiments all produce
    the right rows and overflow count, and a percentage is NEVER invented when
    granular progress is missing;
  * the block **survives a dead broker or worker** rather than erroring or
    hanging the whole sidebar;
  * refreshing uses a **fragment**, not a periodic global rerun — a global rerun
    would disturb a user filling in the pipeline metadata form, picking an
    upload file, or sitting in the sign-in modal.
"""
import ast
import inspect
from pathlib import Path

import pytest

from ui.components.sidebar_chrome import BREADCRUMB_ROOT
from ui.components.sidebar_progress import (
    EMPTY_TEXT, MAX_ROWS, REFRESH_INTERVAL, TITLE_TEXT, build_progress_view,
    overflow_text, row_caption, shorten,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "ui" / "components" / "sidebar_progress.py"

NOW = 1_700_000_600.0                       # epoch tetap agar elapsed deterministik
STARTED = "2023-11-14T22:13:20+00:00"       # tepat 600 detik sebelum NOW


def _exp(i, status="RUNNING", pipeline="hikari2021.rfc_pipeline",
         dataset="HIKARI2021", created="2026-01-01T00:00:00+00:00"):
    return {"id": f"exp-{i}", "status": status, "pipeline_id": pipeline,
            "dataset_type": dataset, "created_at": created,
            "started_at": STARTED}


def _progress(percent=None, stage=None, index=None, total=None):
    """status_data seperti yang dikembalikan get_experiment_status."""
    cp = {}
    if percent is not None:
        cp["overall_percent"] = percent
    if stage:
        cp["stage_name"] = stage
    if index is not None:
        cp["stage_index"], cp["stage_total"] = index, total
    return {"status": "RUNNING", "celery_progress": cp}


# ── berapa baris yang tampil ──────────────────────────────────────────────

def test_nothing_running_produces_no_rows():
    view = build_progress_view([], now_epoch=NOW)
    assert view["rows"] == []
    assert view["extra"] == 0
    assert view["total"] == 0


def test_finished_experiments_are_not_shown():
    """Hanya RUNNING & QUEUED yang in-flight — sisanya bukan urusan blok ini."""
    done = [_exp(i, status=s) for i, s in
            enumerate(("COMPLETED", "FAILED", "CANCELLED"))]
    assert build_progress_view(done, now_epoch=NOW)["rows"] == []


@pytest.mark.parametrize("count", [1, 2, 3])
def test_up_to_three_are_all_shown(count):
    view = build_progress_view([_exp(i) for i in range(count)], now_epoch=NOW)
    assert len(view["rows"]) == count
    assert view["extra"] == 0
    assert view["total"] == count


def test_more_than_three_are_capped_with_a_remainder():
    view = build_progress_view([_exp(i) for i in range(7)], now_epoch=NOW)
    assert len(view["rows"]) == MAX_ROWS
    assert view["extra"] == 7 - MAX_ROWS
    assert view["total"] == 7
    assert overflow_text(view["extra"]) == "…+4 lainnya"


def test_the_remainder_is_counted_not_hardcoded():
    for total in (4, 5, 12):
        view = build_progress_view([_exp(i) for i in range(total)], now_epoch=NOW)
        assert view["extra"] == total - MAX_ROWS
        assert overflow_text(view["extra"]) == f"…+{total - MAX_ROWS} lainnya"


def test_no_overflow_line_when_everything_fits():
    assert overflow_text(0) == ""


def test_running_is_listed_before_queued():
    """Urutannya milik select_running — dipakai ulang, bukan ditulis ulang."""
    rows = build_progress_view(
        [_exp(1, status="QUEUED"), _exp(2, status="RUNNING")],
        now_epoch=NOW)["rows"]
    assert [r["status"] for r in rows] == ["RUNNING", "QUEUED"]


# ── progres tidak pernah dikarang ─────────────────────────────────────────

def test_percentage_is_none_when_granular_progress_is_missing():
    rows = build_progress_view([_exp(1)], status_reader=lambda _id: None,
                               now_epoch=NOW)["rows"]
    assert rows[0]["percent"] is None
    assert rows[0]["stage"] is None


def test_a_queued_job_gets_no_percentage():
    rows = build_progress_view([_exp(1, status="QUEUED")], now_epoch=NOW)["rows"]
    assert rows[0]["percent"] is None
    assert rows[0]["status"] == "QUEUED"


def test_percentage_is_shown_when_the_worker_reports_it():
    reader = lambda _id: _progress(percent=42, stage="Training", index=2, total=4)
    rows = build_progress_view([_exp(1)], status_reader=reader, now_epoch=NOW)["rows"]
    assert rows[0]["percent"] == 42
    assert "Fase 2/4" in rows[0]["stage"]
    assert "Training" in rows[0]["stage"]


def test_a_stage_without_numbers_still_shows_its_label():
    reader = lambda _id: _progress(stage="Preprocessing")
    rows = build_progress_view([_exp(1)], status_reader=reader, now_epoch=NOW)["rows"]
    assert rows[0]["percent"] is None
    assert rows[0]["stage"] == "Preprocessing"


def test_reading_progress_is_skipped_when_the_broker_is_down():
    """Broker mati: tidak ada pembacaan sama sekali, dan blok menandai dirinya."""
    called = []

    def _reader(eid):
        called.append(eid)
        return _progress(percent=99)

    view = build_progress_view([_exp(1)], status_reader=_reader,
                               can_read_progress=False, now_epoch=NOW)
    assert called == []                      # tidak memprobe broker yang mati
    assert view["degraded"] is True
    assert view["rows"][0]["percent"] is None


def test_a_failing_status_reader_never_breaks_the_block():
    def _boom(_id):
        raise RuntimeError("worker hilang")

    view = build_progress_view([_exp(1)], status_reader=_boom, now_epoch=NOW)
    assert len(view["rows"]) == 1            # tetap tampil…
    assert view["rows"][0]["percent"] is None  # …tanpa persen karangan
    assert view["rows"][0]["status"] == "RUNNING"


# ── ringkas untuk sidebar sempit ──────────────────────────────────────────

def test_long_names_are_ellipsised():
    long = "hikari2021.random_forest_undersampler_pipeline"
    out = shorten(long, 24)
    assert len(out) <= 24
    assert out.endswith("…")


def test_short_names_are_left_alone():
    assert shorten("dt_pipeline", 24) == "dt_pipeline"


def test_shorten_handles_missing_values():
    assert shorten(None, 10) == ""
    assert shorten("", 10) == ""


def test_row_fields_stay_within_the_sidebar_budget():
    rows = build_progress_view(
        [_exp(1, pipeline="x" * 80, dataset="y" * 80)], now_epoch=NOW)["rows"]
    assert len(rows[0]["title"]) <= 24
    assert len(rows[0]["dataset"]) <= 20


def test_caption_prefers_the_stage_over_the_bare_status():
    reader = lambda _id: _progress(percent=10, stage="Training", index=1, total=4)
    row = build_progress_view([_exp(1)], status_reader=reader,
                              now_epoch=NOW)["rows"][0]
    caption = row_caption(row)
    assert "Training" in caption
    assert "RUNNING" not in caption


def test_caption_falls_back_to_status_and_elapsed():
    row = build_progress_view([_exp(1)], now_epoch=NOW)["rows"][0]
    caption = row_caption(row)
    assert caption.startswith("RUNNING")
    assert "10m 00s" in caption              # 600 detik sejak STARTED


def test_elapsed_is_dash_when_the_start_time_is_unknown():
    e = _exp(1)
    e["started_at"] = e["created_at"] = None
    row = build_progress_view([e], now_epoch=NOW)["rows"][0]
    assert row["elapsed"] == "—"
    assert row_caption(row) == "RUNNING"      # tidak ada " · —" yang menggantung


# ── pembaruan memakai FRAGMEN, bukan rerun global ─────────────────────────

def test_the_refresh_uses_a_fragment_with_an_interval():
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_sidebar_progress")

    decorators = [d for d in fn.decorator_list if isinstance(d, ast.Call)]
    assert decorators, "render_sidebar_progress harus memakai @st.fragment"
    dec = decorators[0]
    assert getattr(dec.func, "attr", None) == "fragment"
    kwargs = {k.arg for k in dec.keywords}
    assert "run_every" in kwargs


def test_the_interval_is_about_fifteen_seconds():
    assert REFRESH_INTERVAL == "15s"


def test_streamlit_actually_supports_the_fragment_api():
    """Kalau st.fragment hilang di versi terpasang, ini gagal lebih dulu —
    bukan berubah diam-diam jadi rerun global."""
    import streamlit as st

    assert hasattr(st, "fragment")
    assert "run_every" in inspect.signature(st.fragment).parameters


def test_the_block_never_triggers_a_periodic_global_rerun():
    """Rerun global berkala akan mengganggu formulir & modal yang sedang dipakai."""
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {f"{getattr(c.func, 'attr', '')}" for c in calls}
    assert "sleep" not in names, "tidak boleh ada time.sleep berkala"
    assert "rerun" not in names, "tidak boleh ada st.rerun berkala"

    # Diperiksa lewat AST, bukan substring: docstring modul ini justru
    # MENJELASKAN kenapa time.sleep + st.rerun tidak dipakai.
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
                for a in n.names}
    assert "time" not in imported


def test_app_py_does_not_add_a_global_refresh_loop():
    src = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    assert "render_sidebar_progress()" in src
    assert "time.sleep" not in src
    assert "st.rerun()" not in src


# ── logika pembacaan dipakai ulang, bukan ditulis ulang ───────────────────

def test_the_existing_dashboard_helpers_are_reused():
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names}

    for helper in ("select_running", "progress_view", "elapsed_seconds",
                   "format_elapsed"):
        assert helper in imported, helper
    # Progres lintas-sesi & kesehatan tetap lewat orkestrator yang sudah ada.
    assert "get_experiment_status" in imported
    assert "check_execution_health" in imported


def test_no_new_progress_maths_is_defined_here():
    """Tidak ada perhitungan persen sendiri — semua lewat progress_view."""
    src = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for reimplementation in ("progress_view", "select_running", "elapsed_seconds",
                             "format_elapsed"):
        assert reimplementation not in defined, reimplementation


def test_the_db_read_is_narrowed_to_in_flight_rows():
    """Tiap 15 detik tidak boleh membaca seluruh tabel eksperimen."""
    src = MODULE.read_text(encoding="utf-8")
    assert "list_experiments_by_status" in src
    assert "list_experiments(" not in src


def test_the_reads_are_cached_briefly():
    from ui.components import sidebar_progress as sp

    assert sp.CACHE_TTL < 15                 # lebih pendek dari interval fragmen
    for fn in (sp._inflight_rows, sp._health):
        assert hasattr(fn, "clear"), f"{fn} harus di-cache st.cache_data"


# ── urutan blok sidebar & render di ketiga halaman ────────────────────────

def _module_level_call_lines(src: str) -> dict:
    """Baris tiap pemanggilan tingkat-modul di ui/app.py, untuk memeriksa urutan."""
    tree = ast.parse(src)
    lines = {}
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            name = getattr(node.value.func, "id", None)
            if name:
                lines[name] = node.lineno
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            name = getattr(node.value.func, "id", None)
            if name:
                lines[name] = node.lineno
    return lines


def test_app_py_orders_the_three_blocks_top_to_bottom():
    """Navigasi → progres → identitas, dan identitas paling bawah."""
    src = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    lines = _module_level_call_lines(src)

    for name in ("_select_page", "render_sidebar_progress", "render_mode_switch"):
        assert name in lines, name
    assert lines["_select_page"] < lines["render_sidebar_progress"]
    assert lines["render_sidebar_progress"] < lines["render_mode_switch"]

    # Identitas adalah blok sidebar TERAKHIR: tidak ada penulis sidebar lain
    # sesudahnya (routing halaman menulis ke badan halaman, bukan sidebar).
    after = {n: ln for n, ln in lines.items() if ln > lines["render_mode_switch"]}
    assert set(after) <= {"maybe_render_auth_dialog", "render"}, after


# Meniru urutan sidebar ui/app.py memakai komponen ASLI (termasuk option_menu),
# tanpa menjalankan app.py sendiri — script itu menjalankan init_db & seed saat
# diimpor. Urutan pemanggilan di app.py dijaga terpisah oleh
# test_app_py_orders_the_three_blocks_top_to_bottom.
SIDEBAR_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
from streamlit_option_menu import option_menu
from ui.components.sidebar_chrome import menu_styles, render_breadcrumb
from ui.components.sidebar_progress import render_sidebar_progress
from ui.views.login import maybe_render_auth_dialog, render_mode_switch

PAGES = ["Progress & Status", "Run Experiment", "Add Pipeline & Dataset"]
page = st.session_state.get("_page", "Progress & Status")

slot = st.sidebar.empty()
with st.sidebar:
    page = option_menu(menu_title=None, options=PAGES,
                       icons=["speedometer2", "play-circle", "plus-square"],
                       default_index=PAGES.index(page), styles=menu_styles())
st.session_state["_current_page"] = page
with slot:
    render_breadcrumb(page)

render_sidebar_progress()
render_mode_switch()
maybe_render_auth_dialog(page)

if page == "Progress & Status":
    from ui.views.view_results import render
elif page == "Run Experiment":
    from ui.views.run_experiment import render
else:
    from ui.views.contribute import render
render()
'''


def _run_sidebar(tmp_path, page):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "sidebar_app.py"
    script.write_text(SIDEBAR_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=300)
    at.session_state["_page"] = page
    at.run()
    return at


def _sidebar_text(at) -> list[str]:
    """Teks sidebar berurutan. Baris blok kini dirender sebagai markdown
    ber-inset, bukan st.caption, jadi keduanya digabung."""
    return [m.value for m in at.sidebar.markdown] + [
        c.value for c in at.sidebar.caption]


@pytest.mark.parametrize("page", ["Progress & Status", "Run Experiment",
                                  "Add Pipeline & Dataset"])
def test_the_sidebar_renders_on_every_page(tmp_path, page):
    at = _run_sidebar(tmp_path, page)
    assert at.exception is None or not at.exception
    assert any(TITLE_TEXT in t for t in _sidebar_text(at))


@pytest.mark.parametrize("page", ["Progress & Status", "Run Experiment",
                                  "Add Pipeline & Dataset"])
def test_the_block_order_is_breadcrumb_progress_identity(tmp_path, page):
    """Menu sendiri berada di dalam iframe komponen sehingga tidak terbaca
    AppTest; yang dapat diperiksa di sini adalah blok teks di sekitarnya, dan
    urutan pemanggilannya di app.py dijaga oleh test AST terpisah."""
    at = _run_sidebar(tmp_path, page)
    texts = [m.value for m in at.sidebar.markdown]

    breadcrumb = next(i for i, t in enumerate(texts) if BREADCRUMB_ROOT in t)
    progress = next(i for i, t in enumerate(texts) if TITLE_TEXT in t)
    # Blok identitas kini berupa pemicu popover (bukan markdown), jadi
    # keberadaannya diperiksa lewat tombol; yang diurutkan di sini adalah dua
    # blok teks di atasnya, dan identitas dipastikan hadir paling bawah.
    assert breadcrumb < progress, texts
    # Pemicu popover tidak terekspos sebagai button di AppTest; isi daftarnya
    # yang terlihat — kehadirannya membuktikan blok identitas ikut dirender.
    assert "Pengunjung" in [b.label for b in at.sidebar.button]


def test_each_block_is_separated_by_a_divider(tmp_path):
    at = _run_sidebar(tmp_path, "Run Experiment")
    assert len(at.sidebar.get("divider")) >= 2


def test_the_block_survives_an_unreadable_database(tmp_path, monkeypatch):
    """DB tidak terbaca: penanda ringkas, sidebar tidak error."""
    from ui.components import sidebar_progress as sp

    sp._inflight_rows.clear()
    monkeypatch.setattr(sp, "_inflight_rows",
                        lambda: (_ for _ in ()).throw(RuntimeError("db mati")))
    view = sp.load_progress_view()
    assert view["error"] is True
    assert view["rows"] == []


def test_a_dead_broker_only_degrades_the_block(tmp_path, monkeypatch):
    from ui.components import sidebar_progress as sp

    sp._inflight_rows.clear()
    sp._health.clear()
    monkeypatch.setattr(sp, "_inflight_rows", lambda: [_exp(1)])
    monkeypatch.setattr(sp, "_health", lambda: {"mode": "async", "broker_ok": False})

    view = sp.load_progress_view()
    assert view["error"] is False
    assert view["degraded"] is True
    assert view["rows"][0]["percent"] is None      # tidak mengarang persen


def test_a_known_stage_replaces_elapsed_rather_than_joining_it():
    """Ruang sempit: fase ATAU elapsed, tidak keduanya di satu baris."""
    reader = lambda _id: _progress(percent=10, stage="Training", index=1, total=4)
    row = build_progress_view([_exp(1)], status_reader=reader,
                              now_epoch=NOW)["rows"][0]
    caption = row_caption(row)
    assert row["elapsed"] not in caption
    assert len(caption) <= 40                # muat tanpa membungkus dua baris
