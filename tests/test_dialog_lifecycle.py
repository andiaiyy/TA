"""Tests for dialog flag lifecycle, the Run Pipeline flow, and the phase graph.

The dialog half exists because the same bug kept coming back: a button sets a
flag, the user closes the modal with the X, and because ``st.dialog`` defaults to
``on_dismiss="ignore"`` the flag survives — so the next rerun opens the modal
again. It happened to the auth modal, then to detail and comparison. Every
dialog now goes through one shared lifecycle, and all five exits are pinned
here: successful action, Tutup, native dismiss, page change, view change.

The Run Pipeline half checks that compatibility reuses the existing cached
diagnosis rather than re-reading files, and that an empty result still explains
what the dataset would need.

The phase graph half checks the graph follows each pipeline's real stages —
a pipeline without feature selection must not show that step.
"""
import ast
from pathlib import Path

import pytest

import ui.views.run_experiment as rx
import ui.views.view_results as vr
import ui.views.login as login
from ui.components import dialogs as dlg, page_flags
from ui.components import pipeline_catalog as pc

REPO_ROOT = Path(__file__).resolve().parents[1]
VIEW_SRC = REPO_ROOT / "ui" / "views" / "view_results.py"
RUN_SRC = REPO_ROOT / "ui" / "views" / "run_experiment.py"
LOGIN_SRC = REPO_ROOT / "ui" / "views" / "login.py"


@pytest.fixture
def state(monkeypatch):
    fake: dict = {}
    for module in (dlg, rx, vr, login, page_flags):
        monkeypatch.setattr(module.st, "session_state", fake, raising=False)
    return fake


# ── the shared lifecycle utility ──────────────────────────────────────────

def test_every_dialog_flag_is_registered():
    """Satu daftar; kalau ada modal baru yang lupa didaftarkan, pembersihan
    saat pindah halaman akan melewatinya."""
    assert set(dlg.DIALOG_KEYS) == {
        dlg.DETAIL_KEY, dlg.COMPARE_KEY, dlg.COMPAT_KEY,
        dlg.CATALOG_DETAIL_KEY, dlg.CATALOG_RUN_KEY, dlg.AUTH_KEY,
    }
    assert len(set(dlg.DIALOG_KEYS)) == len(dlg.DIALOG_KEYS)


def test_open_close_and_check(state):
    for key in dlg.DIALOG_KEYS:
        assert dlg.is_open(key) is False
        dlg.open_dialog(key, "x")
        assert dlg.dialog_state(key) == "x"
        dlg.close_dialog(key)
        assert dlg.is_open(key) is False


def test_the_check_has_no_truthy_default(state):
    """Bawaan yang truthy akan membuat modal terbuka sejak awal."""
    assert dlg.dialog_state("belum_pernah_ada") is None
    assert dlg.is_open("belum_pernah_ada") is False


def test_closing_is_idempotent(state):
    dlg.close_dialog(dlg.DETAIL_KEY)
    dlg.close_dialog(dlg.DETAIL_KEY)          # tidak melempar


def test_close_all_clears_every_dialog(state):
    for key in dlg.DIALOG_KEYS:
        dlg.open_dialog(key, "x")
    dlg.close_all_dialogs()
    assert not any(dlg.is_open(k) for k in dlg.DIALOG_KEYS)


def test_the_decorator_always_wires_on_dismiss(monkeypatch):
    """Jalur penutupan bawaan (X/Esc) tidak boleh bisa terlupa."""
    seen = {}

    def _fake_dialog(title, **kwargs):
        seen.update({"title": title, **kwargs})
        return lambda fn: fn

    monkeypatch.setattr(dlg.st, "dialog", _fake_dialog)
    dlg.dialog_decorator("Judul", dlg.DETAIL_KEY, width="large")(lambda: None)

    assert seen["title"] == "Judul"
    assert seen["width"] == "large"
    assert callable(seen["on_dismiss"])


def test_the_dismiss_handler_clears_its_flag(state):
    dlg.open_dialog(dlg.COMPARE_KEY, ["a", "b"])
    dlg.dismiss_handler(dlg.COMPARE_KEY)()
    assert dlg.is_open(dlg.COMPARE_KEY) is False


def test_the_decorator_survives_an_older_streamlit(monkeypatch):
    calls = []

    def _fake_dialog(title, **kwargs):
        if "on_dismiss" in kwargs:
            raise TypeError("unexpected keyword argument 'on_dismiss'")
        calls.append(title)
        return lambda fn: fn

    monkeypatch.setattr(dlg.st, "dialog", _fake_dialog)
    dlg.dialog_decorator("Judul", dlg.DETAIL_KEY)(lambda: None)
    assert calls == ["Judul"]


# ── every dialog uses the shared decorator ────────────────────────────────

@pytest.mark.parametrize("src, title", [
    (VIEW_SRC, "Detail Eksperimen"),
    (VIEW_SRC, "Bandingkan Eksperimen"),
    (RUN_SRC, "Uji Kecocokan Dataset"),
    (RUN_SRC, "Detail Research Pipeline"),
    (RUN_SRC, "Jalankan Research Pipeline"),
])
def test_dialogs_are_decorated_through_the_shared_util(src, title):
    tree = ast.parse(src.read_text(encoding="utf-8"))
    shared, raw = [], []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == title):
            continue
        attr = getattr(node.func, "attr", None)
        if attr == "dialog_decorator":
            shared.append(node)
        elif attr == "dialog":
            raw.append(node)
    assert len(shared) == 1, title
    assert not raw, f"{title} masih memakai st.dialog langsung"


def test_the_auth_dialog_keeps_its_own_on_dismiss():
    """Modal auth sudah punya on_dismiss sejak perbaikan sebelumnya."""
    assert "on_dismiss=close_auth_dialog" in LOGIN_SRC.read_text(encoding="utf-8")


def test_no_flag_is_set_outside_a_button_block():
    """Flag yang di-set sebagai efek samping render membuat modal tidak pernah
    bisa ditutup — diperiksa lewat rantai induk tiap pemanggilan."""
    for src in (VIEW_SRC, RUN_SRC):
        tree = ast.parse(src.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "attr", None) == "open_dialog"):
                continue
            node, guarded = call, False
            while node in parents:
                node = parents[node]
                if isinstance(node, ast.If) and "button" in ast.dump(node.test):
                    guarded = True
                    break
                # Pembuka yang dibungkus fungsi sendiri (request_*) dihitung sah;
                # pemanggilnya yang diperiksa di test berikutnya.
                if isinstance(node, ast.FunctionDef) and node.name.startswith(
                        ("request_", "_request_")):
                    guarded = True
                    break
            assert guarded, f"{src.name}: {ast.dump(call)[:120]}"


def test_the_request_helpers_are_only_called_from_buttons():
    src = RUN_SRC.read_text(encoding="utf-8")
    catalog_src = (REPO_ROOT / "ui" / "components"
                   / "pipeline_catalog.py").read_text(encoding="utf-8")
    # Di katalog, keduanya hanya dipanggil sebagai callback di dalam if button.
    body = catalog_src.split("def render_catalog(")[1].split("\ndef ")[0]
    for callback in ("on_run(requested)", "on_detail(requested)"):
        assert callback in body
    # Tombolnya dibuat lewat kolom (cols[n].button), bukan st.button langsung.
    assert body.count(".button(") == 2
    # Halaman menyalurkan helper-nya sebagai callback, bukan memanggil langsung.
    assert "on_detail=request_catalog_detail" in src
    assert "on_run=request_catalog_run" in src


# ── the five exits, per dialog ────────────────────────────────────────────

def test_nothing_is_open_without_a_button_press(state):
    assert not any(dlg.is_open(k) for k in dlg.DIALOG_KEYS)


def test_switching_run_view_closes_every_run_dialog(state):
    for switch in (rx.go_to_execute, rx.go_to_catalog):
        for key in dlg.RUN_VIEW_KEYS:
            dlg.open_dialog(key, "x")
            dlg.store_payload(key, ["data"])
        switch()
        for key in dlg.RUN_VIEW_KEYS:
            assert not dlg.is_open(key), (switch.__name__, key)
            assert dlg.payload(key) is None, (switch.__name__, key)


def test_changing_page_closes_every_dialog(state):
    page_flags.drop_stale_page_flags("Run Experiment")
    for key in dlg.DIALOG_KEYS:
        dlg.open_dialog(key, "x")

    assert page_flags.drop_stale_page_flags("Progress & Status") is True
    assert not any(dlg.is_open(k) for k in dlg.DIALOG_KEYS)


def test_staying_on_a_page_keeps_dialogs_open(state):
    page_flags.drop_stale_page_flags("Run Experiment")
    dlg.open_dialog(dlg.CATALOG_DETAIL_KEY, "HIKARI2021")
    for _ in range(3):
        page_flags.drop_stale_page_flags("Run Experiment")
    assert dlg.is_open(dlg.CATALOG_DETAIL_KEY)


def test_a_stale_catalog_flag_is_dropped_without_rendering(state, monkeypatch):
    opened = []
    monkeypatch.setattr(rx, "_catalog_detail_dialog", lambda g: opened.append(g))
    dlg.open_dialog(dlg.CATALOG_DETAIL_KEY, "SUDAH_TIDAK_ADA")
    rx._maybe_render_catalog_detail([{"dataset_type": "HIKARI2021"}])
    assert opened == [] and not dlg.is_open(dlg.CATALOG_DETAIL_KEY)


def test_a_stale_run_flag_is_dropped_without_rendering(state, monkeypatch):
    opened = []
    monkeypatch.setattr(rx, "_catalog_run_dialog",
                        lambda dt, m: opened.append(dt))
    dlg.open_dialog(dlg.CATALOG_RUN_KEY, "SUDAH_TIDAK_ADA")
    rx._maybe_render_catalog_run([{"dataset_type": "HIKARI2021"}])
    assert opened == [] and not dlg.is_open(dlg.CATALOG_RUN_KEY)


def test_choosing_a_dataset_closes_the_run_popup(state, monkeypatch):
    dlg.open_dialog(dlg.CATALOG_RUN_KEY, "HIKARI2021")
    dlg.store_payload(dlg.CATALOG_RUN_KEY, [{"path": "a.csv"}])

    rx._use_dataset("HIKARI2021", "storage/datasets/a.csv")

    assert not dlg.is_open(dlg.CATALOG_RUN_KEY)
    assert dlg.payload(dlg.CATALOG_RUN_KEY) is None
    assert state["dataset_select"] == "storage/datasets/a.csv"
    assert state["research_select"] == "HIKARI2021"
    assert state[rx._VIEW_KEY] == rx.VIEW_EXECUTE


# ── heavy work happens once, not per interaction ──────────────────────────

def test_the_detail_payload_is_read_once(state, monkeypatch):
    reads = []
    monkeypatch.setattr(vr, "get_full_experiment",
                        lambda eid: reads.append(eid) or {"experiment": {"id": eid}})

    for _ in range(4):                      # empat interaksi di dalam modal
        vr._detail_payload("exp-1")
    assert reads == ["exp-1"]


def test_opening_another_experiment_reads_again(state, monkeypatch):
    reads = []
    monkeypatch.setattr(vr, "get_full_experiment",
                        lambda eid: reads.append(eid) or {"experiment": {"id": eid}})
    vr._detail_payload("exp-1")
    vr._detail_payload("exp-2")
    assert reads == ["exp-1", "exp-2"]


def test_the_pdf_is_not_rebuilt_on_every_interaction():
    """Laporan PDF dulu dibuat ulang tiap rerun modal — sumber rasa tersendat."""
    src = VIEW_SRC.read_text(encoding="utf-8")
    body = src.split("def _pdf_download_button(")[1].split("\ndef ")[0]
    assert "generate_report(" not in body      # tidak lagi dipanggil langsung
    assert "_cached_pdf(" in body
    assert "@st.cache_data" in src.split("def _cached_pdf(")[0].split("\n\n")[-1]


def test_the_run_popup_body_does_no_diagnosis():
    """Diagnosa dilakukan saat tombol ditekan, bukan tiap interaksi pop-up."""
    src = RUN_SRC.read_text(encoding="utf-8")
    body = src.split("def _catalog_run_body(")[1].split("\ndef ")[0]
    for heavy in ("matching_datasets(", "_diagnose_selected(",
                  "_all_dataset_options("):
        assert heavy not in body, heavy


def test_the_popup_computes_its_matches_when_opened(state, monkeypatch):
    monkeypatch.setattr(rx, "matching_datasets",
                        lambda dt: [{"path": "a.csv", "name": "a.csv", "size": "1 KB"}])
    rx.request_catalog_run("HIKARI2021")

    assert dlg.dialog_state(dlg.CATALOG_RUN_KEY) == "HIKARI2021"
    assert dlg.payload(dlg.CATALOG_RUN_KEY)[0]["name"] == "a.csv"


# ── Run Pipeline: compatibility reuses the cached diagnosis ───────────────

def _options(*names):
    return [(f"storage/datasets/{n}", "?") for n in names]


def test_matching_uses_the_existing_diagnosis(monkeypatch):
    seen = []

    def _diagnose(path):
        seen.append(path)
        return {"compatible_types": ["HIKARI2021"]}

    monkeypatch.setattr(rx, "format_size", lambda n: "1 KB")
    monkeypatch.setattr(Path, "stat", lambda self: type("S", (), {"st_size": 1})())

    out = rx.matching_datasets("HIKARI2021", options=_options("a.csv", "b.csv"),
                               diagnose=_diagnose, extensions=(".csv",))
    assert [m["name"] for m in out] == ["a.csv", "b.csv"]
    assert seen == ["storage/datasets/a.csv", "storage/datasets/b.csv"]


def test_files_of_the_wrong_format_are_never_diagnosed(monkeypatch):
    """Lapis pertama: ekstensi disaring dulu supaya folder besar tetap ringan."""
    seen = []

    def _diagnose(path):
        seen.append(path)
        return {"compatible_types": ["HIKARI2021"]}

    monkeypatch.setattr(rx, "format_size", lambda n: "1 KB")
    monkeypatch.setattr(Path, "stat", lambda self: type("S", (), {"st_size": 1})())

    out = rx.matching_datasets(
        "HIKARI2021", options=_options("a.csv", "b.jsonl", "c.json"),
        diagnose=_diagnose, extensions=(".csv",))
    assert [m["name"] for m in out] == ["a.csv"]
    assert seen == ["storage/datasets/a.csv"]      # dua lainnya tidak disentuh


def test_incompatible_files_are_left_out(monkeypatch):
    monkeypatch.setattr(rx, "format_size", lambda n: "1 KB")
    monkeypatch.setattr(Path, "stat", lambda self: type("S", (), {"st_size": 1})())
    out = rx.matching_datasets(
        "HIKARI2021", options=_options("a.csv"),
        diagnose=lambda p: {"compatible_types": ["EVE_SURICATA"]},
        extensions=(".csv",))
    assert out == []


def test_a_broken_file_does_not_break_the_check(monkeypatch):
    def _diagnose(path):
        if "bad" in path:
            raise RuntimeError("rusak")
        return {"compatible_types": ["HIKARI2021"]}

    monkeypatch.setattr(rx, "format_size", lambda n: "1 KB")
    monkeypatch.setattr(Path, "stat", lambda self: type("S", (), {"st_size": 1})())
    out = rx.matching_datasets("HIKARI2021", options=_options("bad.csv", "ok.csv"),
                               diagnose=_diagnose, extensions=(".csv",))
    assert [m["name"] for m in out] == ["ok.csv"]


def test_matching_is_decided_per_dataset_type_not_per_algorithm():
    src = RUN_SRC.read_text(encoding="utf-8")
    body = src.split("def matching_datasets(")[1].split("\ndef ")[0]
    assert 'compatible_types' in body
    assert "algorithm" not in body


def test_the_real_check_reuses_the_cached_diagnosis():
    """`_diagnose_selected` memanggil `_cached_diagnosis` (st.cache_data),
    jadi berkas yang sama tidak dibaca ulang."""
    src = RUN_SRC.read_text(encoding="utf-8")
    body = src.split("def _diagnose_selected(")[1].split("\ndef ")[0]
    assert "_cached_diagnosis(" in body
    assert "@st.cache_data" in src.split("def _cached_diagnosis(")[0].split("\n\n")[-1]

    matching = src.split("def matching_datasets(")[1].split("\ndef ")[0]
    assert "_diagnose_selected" in matching          # bukan mekanisme baru


def test_the_empty_case_explains_the_requirements():
    for dataset_type in ("HIKARI2021", "EVE_SURICATA"):
        rows = pc.run_requirements(dataset_type)
        labels = [label for label, _v in rows]
        assert "Format berkas" in labels
        assert "Kolom label" in labels
        for _label, value in rows:
            assert value and "`" not in value


def test_the_empty_popup_points_at_the_upload_page():
    src = RUN_SRC.read_text(encoding="utf-8")
    body = src.split("def _catalog_run_body(")[1].split("\ndef ")[0]
    assert "Add Pipeline & Dataset" in body
    assert "run_requirements" in body


# ── phase graph follows each pipeline ─────────────────────────────────────

def test_the_stages_come_from_the_registry():
    stages = pc.phase_graph_stages(
        "x.y", {}, registry_reader=lambda pid: {"stages": ["A", "B"]})
    assert [s["label"] for s in stages] == ["A", "B"]


def test_a_pipeline_without_feature_selection_does_not_show_that_step():
    for value in ("None — all numeric features used", "None", "", None,
                  "tidak ada"):
        stages = pc.phase_graph_stages(
            "x.y", {"feature_selection": value},
            registry_reader=lambda pid: {"stages": ["Preprocessing", "Training"]})
        assert [s["label"] for s in stages] == ["Preprocessing", "Training"], value


def test_a_pipeline_with_feature_selection_shows_it_before_training():
    stages = pc.phase_graph_stages(
        "x.y", {"feature_selection": "MI / RFE / PCA"},
        registry_reader=lambda pid: {"stages": ["Preprocessing", "Training"]})
    labels = [s["label"] for s in stages]
    assert labels == ["Preprocessing", "Feature selection", "Training"]


@pytest.mark.parametrize("pipeline_id, expected", [
    ("hikari2021.nbgc_pipeline", 3),        # tanpa balancing/scaling
    ("hikari2021.dt_pipeline", 4),
    ("hikari2021.svc_pipeline", 5),
    ("hikari2021.lr_pipeline", 5),          # PCA dihitung sebagai seleksi fitur
    ("eve_cbr.xgb", 10),
])
def test_the_real_graphs_differ_per_pipeline(pipeline_id, expected):
    """Bukan template seragam: jumlah tahapnya memang berbeda."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    info = PIPELINE_REGISTRY[pipeline_id]["class"]().get_info() or {}
    assert len(pc.phase_graph_stages(pipeline_id, info)) == expected


def test_hikari_pipelines_without_selection_really_omit_the_step():
    from config.pipeline_registry import PIPELINE_REGISTRY

    for pipeline_id in ("hikari2021.dt_pipeline", "hikari2021.rfc_pipeline",
                        "hikari2021.knn_pipeline", "hikari2021.nbgc_pipeline"):
        info = PIPELINE_REGISTRY[pipeline_id]["class"]().get_info() or {}
        labels = [s["label"] for s in pc.phase_graph_stages(pipeline_id, info)]
        assert "Feature selection" not in labels, pipeline_id


def test_an_unknown_pipeline_yields_no_graph():
    assert pc.phase_graph_stages("tidak.ada", {},
                                 registry_reader=lambda pid: None) == []


# ── phase graph markup ────────────────────────────────────────────────────

def test_the_graph_is_inline_svg_without_any_library():
    svg = pc.phase_graph_svg([{"label": "A", "kind": "stage", "note": ""}])
    assert svg.startswith("<div") and "<svg" in svg
    assert "<img" not in svg and "http" not in svg.replace(
        "http://www.w3.org/2000/svg", "")

    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    for banned in ("graphviz", "plotly", "networkx", "st.graphviz_chart"):
        assert banned not in src, banned


def test_cards_are_linked_and_counted():
    stages = [{"label": f"T{i}", "kind": "stage", "note": ""} for i in range(4)]
    svg = pc.phase_graph_svg(stages, pre_stages=())
    assert svg.count("ids-ph-card") == 4
    assert svg.count("ids-ph-link") == 3       # satu garis antar kartu


def test_the_orchestrator_stage_is_drawn_differently():
    svg = pc.phase_graph_svg([{"label": "Training", "kind": "stage", "note": ""}])
    assert "stroke-dasharray" in svg           # tahap pra-pipeline: garis putus
    assert "Parsing" in svg
    assert "bukan bagian dari pipeline" in pc.PRE_STAGE_NOTE


def test_a_long_graph_scrolls_instead_of_wrapping():
    stages = [{"label": f"Fase {i}", "kind": "stage", "note": ""} for i in range(12)]
    svg = pc.phase_graph_svg(stages)
    assert 'class="ids-ph-wrap"' in svg

    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    css = src.split("_CSS = ")[1].split('"""')[1]
    assert ".ids-ph-wrap { overflow-x: auto" in css


def test_the_graph_carries_alt_text():
    stages = [{"label": "Preprocessing", "kind": "stage", "note": ""}]
    svg = pc.phase_graph_svg(stages)
    assert 'role="img"' in svg and "aria-label=" in svg
    assert "<title>" in svg
    assert "Preprocessing" in pc.phase_graph_alt(stages)


def test_the_graph_escapes_its_labels():
    svg = pc.phase_graph_svg([{"label": "<script>x</script>", "kind": "stage",
                               "note": ""}])
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


def test_the_graph_colours_are_theme_safe():
    import re

    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    css = src.split("_CSS = ")[1].split('"""')[1]
    graph_css = "\n".join(l for l in css.splitlines() if "ids-ph" in l or
                          (l.strip().startswith(("fill", "stroke", "opacity"))))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", graph_css), graph_css
    assert "currentColor" in css
