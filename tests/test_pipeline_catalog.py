"""Tests for the pipeline catalog and the catalog/execute view split.

Two properties carry the weight here:

  * the catalog is **derived**, never typed — group titles come from the
    attribution source, algorithms from the registry, and every description
    from that pipeline's own ``get_info()``. Adding a pipeline to the registry
    must show up without touching the catalog module;
  * a monitored experiment is **never hidden** behind the catalog. Polling wins
    over any view preference, and the back button is locked while it runs.
"""
import ast
from pathlib import Path

import pytest

import ui.views.run_experiment as rx
from ui.components import pipeline_catalog as pc

REPO_ROOT = Path(__file__).resolve().parents[1]

FAKE_REGISTRY = {
    "fam_a.dt": {"dataset_type": "FAM_A", "algorithm": "Decision Tree"},
    "fam_a.rf": {"dataset_type": "FAM_A", "algorithm": "Random Forest"},
    "fam_b.xgb": {"dataset_type": "FAM_B", "algorithm": "XGBoost"},
}
FAKE_INFO = {
    "fam_a.dt": {"algorithm": "Decision Tree",
                 "feature_selection": "None — all numeric features",
                 "preprocessing_steps": ["drop ids", "split 70/30"],
                 "fixed_params": {"random_state": 42}},
    "fam_a.rf": {"algorithm": "Random Forest",
                 "feature_selection": "None — all numeric features"},
    "fam_b.xgb": {"algorithm": "XGBoost", "feature_selection": "MI / RFE / PCA",
                  "anti_leakage": ["group_hash split"],
                  "metrics_policy": "natural-holdout primary"},
}


def _catalog():
    return pc.build_catalog(
        registry_reader=lambda: FAKE_REGISTRY,
        info_reader=lambda pid: FAKE_INFO.get(pid, {}),
        name_reader=lambda dt: f"Judul {dt}",
    )


# ── the catalog is derived from structured sources ────────────────────────

def test_the_catalog_has_one_group_per_research_pipeline():
    catalog = _catalog()
    assert [g["dataset_type"] for g in catalog] == ["FAM_A", "FAM_B"]
    assert [g["title"] for g in catalog] == ["Judul FAM_A", "Judul FAM_B"]


def test_each_group_lists_its_own_algorithms():
    catalog = {g["dataset_type"]: g for g in _catalog()}
    assert [a["algorithm"] for a in catalog["FAM_A"]["algorithms"]] == [
        "Decision Tree", "Random Forest"]
    assert [a["algorithm"] for a in catalog["FAM_B"]["algorithms"]] == ["XGBoost"]


def test_every_algorithm_keeps_its_real_pipeline_id():
    ids = {a["pipeline_id"] for g in _catalog() for a in g["algorithms"]}
    assert ids == set(FAKE_REGISTRY)


def test_the_counts_are_computed_from_the_catalog():
    counts = pc.catalog_counts(_catalog())
    assert counts == {"research": 2, "algorithms": 3}
    assert pc.summary_text(counts) == "2 research pipeline · 3 algoritma tersedia"


def test_adding_a_pipeline_shows_up_without_touching_the_module():
    """Angka & daftar tidak pernah tetap: registry yang menentukan."""
    bigger = dict(FAKE_REGISTRY)
    bigger["fam_b.lsvc"] = {"dataset_type": "FAM_B", "algorithm": "Linear SVC"}
    catalog = pc.build_catalog(registry_reader=lambda: bigger,
                               info_reader=lambda pid: {}, name_reader=str)
    assert pc.catalog_counts(catalog) == {"research": 2, "algorithms": 4}


def test_summaries_come_from_get_info():
    catalog = {g["dataset_type"]: g for g in _catalog()}
    dt = catalog["FAM_A"]["algorithms"][0]
    assert dt["summary"] == "None — all numeric features"
    xgb = catalog["FAM_B"]["algorithms"][0]
    assert xgb["summary"] == "MI / RFE / PCA"


def test_a_pipeline_without_any_describable_key_gets_no_invented_summary():
    catalog = pc.build_catalog(registry_reader=lambda: {"x.y": {
        "dataset_type": "Z", "algorithm": "Algo"}},
        info_reader=lambda pid: {}, name_reader=str)
    assert catalog[0]["algorithms"][0]["summary"] == ""


def test_details_only_contain_keys_that_exist():
    catalog = {g["dataset_type"]: g for g in _catalog()}
    labels = dict(catalog["FAM_A"]["algorithms"][0]["details"])
    assert "Langkah preprocessing" in labels
    assert "Parameter tetap" in labels
    assert "Anti-kebocoran" not in labels        # DT tidak punya kunci itu

    xgb_labels = dict(catalog["FAM_B"]["algorithms"][0]["details"])
    assert "Anti-kebocoran" in xgb_labels
    assert "Kebijakan metrik" in xgb_labels


def test_a_broken_pipeline_does_not_break_the_catalog():
    def _boom(pid):
        raise RuntimeError("get_info rusak")

    catalog = pc.build_catalog(registry_reader=lambda: FAKE_REGISTRY,
                               info_reader=_boom, name_reader=str)
    assert pc.catalog_counts(catalog)["algorithms"] == 3
    assert all(a["summary"] == "" for g in catalog for a in g["algorithms"])


def test_entries_without_a_dataset_type_are_skipped():
    catalog = pc.build_catalog(
        registry_reader=lambda: {"broken": {"algorithm": "X"}},
        info_reader=lambda pid: {}, name_reader=str)
    assert catalog == []


# ── against the REAL registry ─────────────────────────────────────────────

def test_the_real_catalog_matches_the_real_registry():
    from config.pipeline_registry import PIPELINE_REGISTRY

    catalog = pc.build_catalog()
    counts = pc.catalog_counts(catalog)

    families = {e["dataset_type"] for e in PIPELINE_REGISTRY.values()}
    assert counts["research"] == len(families)
    assert counts["algorithms"] == len(PIPELINE_REGISTRY)

    for group in catalog:
        expected = sum(1 for e in PIPELINE_REGISTRY.values()
                       if e["dataset_type"] == group["dataset_type"])
        assert len(group["algorithms"]) == expected, group["dataset_type"]


def test_the_real_titles_come_from_the_attribution_source():
    from config.research_attribution import get_research_display_name

    for group in pc.build_catalog():
        assert group["title"] == get_research_display_name(group["dataset_type"])
        assert group["title"] != group["dataset_type"]      # benar-benar beratribusi


def test_the_real_groups_carry_dataset_requirements_from_the_schema():
    for group in pc.build_catalog():
        joined = " ".join(group["dataset_lines"])
        assert "Format berkas" in joined
        assert "Kolom label" in joined


def test_no_pipeline_description_is_typed_into_the_module():
    """Regresi: keterangan tidak boleh dipindah jadi teks statis di modul ini."""
    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    for leaked in ("Random Forest", "XGBoost", "Decision Tree", "HIKARI2021",
                   "RandomUnderSampler", "StandardScaler", "Niswar", "Rayyan"):
        assert leaked not in src, leaked


def test_the_catalog_shows_no_metrics():
    """Katalog deskriptif — angka hasil tinggal di Progress & Status."""
    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    for metric in ("accuracy", "f1_score", "roc_auc", "precision_score",
                   "recall", "metrics.json"):
        assert metric not in src, metric

    for group in pc.build_catalog():
        for algo in group["algorithms"]:
            blob = (algo["summary"] + repr(algo["details"])).lower()
            for metric in ("accuracy", "f1-score", "roc-auc"):
                assert metric not in blob, (algo["pipeline_id"], metric)


def test_long_text_is_ellipsised_not_wrapped():
    assert pc.shorten("x" * 200, 20).endswith("…")
    assert len(pc.shorten("x" * 200, 20)) == 20
    assert pc.shorten("pendek", 20) == "pendek"
    assert pc.shorten(None, 10) == ""


def test_the_catalog_colours_are_theme_safe():
    import re

    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    css = src.split("_CSS = ")[1].split('"""')[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), css
    # SATU warna aksen — boleh dipakai di beberapa tempat, asal tokennya sama.
    accents = set(re.findall(r"var\(--[a-z-]+", css)) - {"var(--text-color"}
    assert accents == {"var(--primary-color"}, accents
    assert "var(--primary-color, currentColor)" in css
    # Warna netral lainnya harus transparan supaya aman di kedua tema.
    for colour in re.findall(r"background:\s*([^;]+);", css):
        assert ("rgba(" in colour or "transparent" in colour), colour


def test_catalog_content_is_escaped():
    """Judul & keterangan masuk ke markup, jadi harus lewat escape()."""
    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    body = src.split("def _line(")[1].split("\ndef ")[0]
    assert "escape(" in body


# ── view mechanism ────────────────────────────────────────────────────────

@pytest.fixture
def state(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(rx.st, "session_state", fake)
    return fake


def test_the_default_view_is_the_catalog(state):
    assert rx.current_view() == rx.VIEW_CATALOG


def test_going_to_execute_sticks(state):
    rx.go_to_execute()
    assert state[rx._VIEW_KEY] == rx.VIEW_EXECUTE
    assert rx.current_view() == rx.VIEW_EXECUTE


def test_going_back_to_the_catalog_sticks(state):
    rx.go_to_execute()
    rx.go_to_catalog()
    assert rx.current_view() == rx.VIEW_CATALOG


def test_choosing_an_algorithm_carries_it_to_the_execute_view(state):
    rx.go_to_execute("hikari2021.dt_pipeline")
    assert rx.current_view() == rx.VIEW_EXECUTE
    assert state[rx._PENDING_KEY] == "hikari2021.dt_pipeline"


# ── the critical rule: a monitored experiment is never hidden ─────────────

def test_a_running_experiment_forces_the_execute_view(state):
    state[rx._VIEW_KEY] = rx.VIEW_CATALOG        # preferensi pengguna…
    state["polling_experiment_id"] = "exp-1"     # …kalah oleh polling
    assert rx.is_polling() is True
    assert rx.current_view() == rx.VIEW_EXECUTE


def test_a_finished_result_defaults_to_the_execute_view(state):
    state["last_result"] = {"success": True}
    assert rx.current_view() == rx.VIEW_EXECUTE


def test_a_deliberate_return_to_the_catalog_is_honoured_after_a_result(state):
    """Hasil TIDAK memaksa selamanya: pengguna tetap boleh membuka katalog,
    dan hasilnya tidak dihapus sehingga masih ada saat ia kembali."""
    state["last_result"] = {"success": True}
    rx.go_to_catalog()
    assert rx.current_view() == rx.VIEW_CATALOG
    assert state["last_result"] == {"success": True}

    rx.go_to_execute()
    assert rx.current_view() == rx.VIEW_EXECUTE


def test_a_failed_result_does_not_count_as_monitoring(state):
    state["last_result"] = {"success": False}
    assert rx.has_visible_result() is False
    assert rx.current_view() == rx.VIEW_CATALOG


def test_going_back_never_drops_the_monitoring_state(state):
    """Tombol kembali tidak boleh menghapus pantauan eksperimen."""
    state["polling_experiment_id"] = "exp-1"
    state["last_result"] = {"success": True}
    rx.go_to_catalog()

    assert state["polling_experiment_id"] == "exp-1"
    assert state["last_result"] == {"success": True}
    assert rx.current_view() == rx.VIEW_EXECUTE   # tetap dipaksa selama berjalan


def test_the_back_button_is_disabled_while_an_experiment_runs():
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("def _render_execute_header()")[1].split("\ndef ")[0]
    assert "disabled=running" in body
    assert "is_polling()" in body


# ── pending selection is only applied when it fits ────────────────────────

def test_a_pending_pipeline_is_applied_to_the_selectboxes(state):
    state[rx._PENDING_KEY] = "fam_a.dt"
    rx._apply_pending_selection({"FAM_A": {"Decision Tree": "fam_a.dt"}})

    assert state["research_select"] == "FAM_A"
    assert state["algorithm_select"] == "Decision Tree"
    assert rx._PENDING_KEY not in state


def test_an_incompatible_pending_pipeline_is_reported_not_forced(state):
    """Memasang nilai yang bukan salah satu opsi akan merusak selectbox."""
    state[rx._PENDING_KEY] = "fam_b.xgb"
    rx._apply_pending_selection({"FAM_A": {"Decision Tree": "fam_a.dt"}})

    assert "research_select" not in state
    assert state[rx._PENDING_MISS_KEY] == "fam_b.xgb"


def test_no_pending_selection_leaves_the_selectboxes_alone(state):
    state["research_select"] = "FAM_A"
    rx._apply_pending_selection({"FAM_A": {"Decision Tree": "fam_a.dt"}})
    assert state["research_select"] == "FAM_A"


# ── the moved execute flow is intact ──────────────────────────────────────

def test_the_execute_flow_keeps_all_of_its_early_returns():
    """Alur lama DIPINDAHKAN, bukan ditulis ulang: kelima jalan keluarnya tetap."""
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("def _render_execute():")[1].split("\n# ─── ")[0]

    for guard in ("Belum ada berkas dataset di", "if not dataset_path:",
                  "if not v.get(\"success\"):", "if not pipelines:",
                  'if "polling_experiment_id" in st.session_state:'):
        assert guard in body, guard


def test_the_execute_flow_still_has_its_sections_and_gates():
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("def _render_execute():")[1].split("\n# ─── ")[0]

    for kept in ("Dataset Selection", "Pipeline Selection", "Execute",
                 "_render_execution_status_panel", "_diagnose_selected",
                 "_maybe_render_compat_dialog", "_run_with_status",
                 "_poll_experiment", "_display_results",
                 "disabled=not can_run", "_research_compatible"):
        assert kept in body, kept


def test_the_execute_flow_is_not_duplicated():
    """Hanya SATU definisi alur eksekusi & satu tombol jalankan."""
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

    assert names.count("_render_execute") == 1
    assert names.count("render") == 1
    assert src.count('st.button("Run Experiment", type="primary"') == 1


def test_the_catalog_view_does_not_reimplement_the_flow():
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("def _render_catalog_view()")[1].split("\ndef ")[0]
    for flow in ("validate_dataset_for_ui", "_run_with_status", "_poll_experiment",
                 "_diagnose_selected", "st.selectbox"):
        assert flow not in body, flow


def test_the_running_experiment_has_a_safety_net_past_the_early_returns():
    """Titik polling berada sesudah empat early-return; bila salah satunya
    aktif, stage view tetap dirender oleh jaring pengaman di render()."""
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    body = src.split("def render():")[1]
    assert "_POLL_RENDERED_KEY" in body
    assert "_poll_experiment(" in body


# ── AppTest: kedua tampilan benar-benar terender ──────────────────────────

RUN_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
# Dipop, bukan dibaca: preset adalah keadaan AWAL. Kalau diterapkan ulang tiap
# rerun, flag yang baru dibersihkan aplikasi akan dipasang lagi oleh harness.
for key, value in (st.session_state.pop("_preset", None) or {{}}).items():
    st.session_state[key] = value
from ui.views.run_experiment import render
render()
'''


def _run_page(tmp_path, preset=None):
    from streamlit.testing.v1 import AppTest

    script = tmp_path / "run_page.py"
    script.write_text(RUN_APP.format(repo=str(REPO_ROOT)), encoding="utf-8")
    at = AppTest.from_file(str(script), default_timeout=600)
    if preset:
        at.session_state["_preset"] = preset
    at.run()
    return at


def _button_labels(at):
    return [b.label for b in at.button]


def test_the_catalog_renders_without_exception(tmp_path):
    at = _run_page(tmp_path)
    assert at.exception is None or not at.exception


def test_the_catalog_opens_by_default_with_every_algorithm(tmp_path):
    """Algoritma tampil sebagai CHIP di blok, bukan sebagai tombol sendiri."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    at = _run_page(tmp_path)
    assert "Run Experiment" in _button_labels(at)

    chips = " ".join(m.value for m in at.markdown if "ids-cat-chips" in m.value)
    for entry in PIPELINE_REGISTRY.values():
        assert entry["algorithm"] in chips, entry["algorithm"]


def test_each_block_has_only_name_description_and_algorithms(tmp_path):
    """Blok ringkas: keterangan panjang tidak boleh bocor ke katalog."""
    at = _run_page(tmp_path)
    block_text = " ".join(m.value for m in at.markdown
                          if "ids-cat-" in m.value and "<style>" not in m.value)

    for moved in ("preprocessing", "fixed_params", "anti_leakage",
                  "Hyperparameter", "Kolom label", "Format berkas",
                  "random_state", "Reproduksi"):
        assert moved not in block_text, moved

    # Satu tombol Detail per research pipeline.
    assert _button_labels(at).count("Detail") == len(pc.build_catalog())


def test_the_catalog_shows_both_attributed_groups(tmp_path):
    from config.research_attribution import get_research_display_name
    from config.pipeline_registry import PIPELINE_REGISTRY

    at = _run_page(tmp_path)
    markup = " ".join(m.value for m in at.markdown)
    for dataset_type in {e["dataset_type"] for e in PIPELINE_REGISTRY.values()}:
        assert get_research_display_name(dataset_type) in markup


def test_the_catalog_counts_are_rendered(tmp_path):
    at = _run_page(tmp_path)
    markup = " ".join(m.value for m in at.markdown)
    assert pc.summary_text(pc.catalog_counts(pc.build_catalog())) in markup


def test_the_block_itself_has_no_expanders(tmp_path):
    """Keterangan panjang tidak lagi menggantung di katalog — semuanya di modal."""
    at = _run_page(tmp_path)
    assert at.get("expander") == []


def test_the_modal_carries_the_collapsible_sections(tmp_path):
    at = _run_page(tmp_path, {rx.CATALOG_DETAIL_KEY: "EVE_SURICATA"})
    labels = [e.label for e in at.get("expander")]

    assert "Hyperparameter terkunci" in labels
    assert "Langkah preprocessing" in labels
    assert "Persyaratan dataset" in labels
    # AppTest tidak mengekspos status buka/tutup expander, jadi dipastikan di
    # sumbernya: seluruh bagian sekunder didekorasi expanded=False.
    src = (REPO_ROOT / "ui" / "components"
           / "pipeline_catalog.py").read_text(encoding="utf-8")
    body = src.split("def render_modal_body(")[1]
    assert "expanded=True" not in body
    assert body.count("expanded=False") >= 2


def test_the_execute_view_renders_without_exception(tmp_path):
    at = _run_page(tmp_path, {"_run_view": "execute"})
    assert at.exception is None or not at.exception
    assert "← Katalog" in _button_labels(at)
    assert any(s.label == "Pilih dataset" for s in at.selectbox)


def test_pressing_run_experiment_moves_to_the_execute_view(tmp_path):
    at = _run_page(tmp_path)
    next(b for b in at.button if b.label == "Run Experiment").click().run()

    assert at.exception is None or not at.exception
    assert at.session_state.filtered_state.get(rx._VIEW_KEY) == rx.VIEW_EXECUTE


def test_running_from_the_modal_carries_the_pipeline_into_the_execute_view(tmp_path):
    at = _run_page(tmp_path, {rx.CATALOG_DETAIL_KEY: "HIKARI2021"})
    next(b for b in at.button if b.label == "Jalankan pipeline ini").click().run()

    state = at.session_state.filtered_state
    assert state.get(rx._VIEW_KEY) == rx.VIEW_EXECUTE
    # Pilihan menunggu dataset yang cocok; kuncinya masih tersimpan.
    assert state.get(rx._PENDING_KEY) or "research_select" in state
    # Modal ikut ditutup saat berpindah tampilan.
    assert rx.CATALOG_DETAIL_KEY not in state


def test_a_running_experiment_is_never_hidden_behind_the_catalog(tmp_path):
    """Aturan kritis, diuji ujung-ke-ujung: preferensi katalog pun kalah."""
    at = _run_page(tmp_path, {"_run_view": "catalog",
                              "polling_experiment_id": "tidak-ada-di-db"})
    assert at.exception is None or not at.exception

    labels = _button_labels(at)
    assert "← Katalog" in labels
    assert "Run Experiment" not in labels        # katalog TIDAK dirender

    # Stage view tetap tercapai walau alur eksekusi berhenti di early-return.
    assert any("Experiment not found" in e.value for e in at.error)


def test_the_back_button_is_locked_while_an_experiment_runs(tmp_path):
    at = _run_page(tmp_path, {"polling_experiment_id": "exp-1"})
    back = next(b for b in at.button if b.label == "← Katalog")
    assert back.disabled is True

    # Alasan tombol terkunci kini menempel pada tombol itu sendiri (help=),
    # bukan sebagai baris keterangan kecil di bawahnya.
    assert "dikunci" in (back.help or "")


def test_the_back_button_is_free_when_nothing_runs(tmp_path):
    at = _run_page(tmp_path, {"_run_view": "execute"})
    back = next(b for b in at.button if b.label == "← Katalog")
    assert back.disabled is False


def test_a_finished_result_lands_on_the_execute_view(tmp_path):
    at = _run_page(tmp_path, {"last_result": {"success": True}})
    assert "← Katalog" in _button_labels(at)
    assert "Run Experiment" not in _button_labels(at)


def test_the_selected_pipeline_marker_is_shown(tmp_path):
    """Label pipeline dinaikkan menjadi teks isi — ini identitas yang sedang
    dikerjakan, bukan catatan pinggir."""
    at = _run_page(tmp_path, {"_run_view": "execute"})
    body = " ".join(m.value for m in at.markdown)
    assert "Pipeline:" in body
