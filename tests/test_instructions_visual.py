"""Tests for the visual instruction panels (ui/components/instructions.py).

Two things must hold no matter how pretty the panel gets:

  * every value shown still comes from the validator constants / dataset
    schemas — nothing retyped as static prose, so the panel can never drift
    from the rules actually enforced;
  * the honest notes survive the redesign — static checking (files are read,
    not executed), "passing ≠ active", and the sample-based caveat.
"""
import re
from pathlib import Path

import pytest

from contracts.dataset_schemas import get_schema, supported_datasets
from orchestrator.pipeline_validator import (
    ALLOWED_MODULES, BASE_CLASS_NAME, EXPECTED_INFO_KEYS, FORBIDDEN_CALLS,
    FORBIDDEN_MODULES, REQUIRED_METHODS,
)
from ui.components.instructions import (
    CHIP_PREVIEW, DATASET_FLOW, DATASET_FLOW_ALT, PIPELINE_FLOW,
    PIPELINE_FLOW_ALT, chips_html, dataset_checklist, dataset_contract_rows,
    dataset_sample_snippet, flow_diagram_svg,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE = REPO_ROOT / "ui" / "components" / "instructions.py"


# ── flow diagram ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("flow, alt", [(PIPELINE_FLOW, PIPELINE_FLOW_ALT),
                                       (DATASET_FLOW, DATASET_FLOW_ALT)])
def test_flow_diagram_has_a_step_per_stage(flow, alt):
    svg = flow_diagram_svg(flow, alt=alt)
    assert len(flow) == 4
    assert svg.count('class="ids-node"') == 4
    assert svg.count('class="ids-link"') == 3          # penghubung antar tahap
    for _icon, label in flow:
        assert label in svg


def test_flow_diagram_is_responsive():
    svg = flow_diagram_svg(PIPELINE_FLOW, alt=PIPELINE_FLOW_ALT)
    assert "viewBox=" in svg
    assert "width=" not in svg.split("<svg")[1].split(">")[0]   # lebar dari CSS


def test_flow_diagram_carries_alt_text():
    """Informasi tidak hilang bila SVG tidak tampil."""
    svg = flow_diagram_svg(PIPELINE_FLOW, alt=PIPELINE_FLOW_ALT)
    assert f"<title>{PIPELINE_FLOW_ALT}</title>" in svg
    assert 'role="img"' in svg
    assert f'aria-label="{PIPELINE_FLOW_ALT}"' in svg


def test_flow_diagram_escapes_dynamic_text():
    svg = flow_diagram_svg([("<x>", 'Tahap "A" & B')], alt="<alt> & lain")
    assert "<x>" not in svg.replace("<x>", "", 0) or "&lt;x&gt;" in svg
    assert "&amp;" in svg
    assert 'Tahap "A"' not in svg or "&quot;" in svg or "&#x27;" in svg


def test_empty_flow_renders_nothing():
    assert flow_diagram_svg([], alt="kosong") == ""


def test_pulse_is_staggered_between_stages():
    svg = flow_diagram_svg(PIPELINE_FLOW, alt=PIPELINE_FLOW_ALT)
    delays = re.findall(r"animation-delay:([0-9.]+)s", svg)
    assert len(delays) == 4
    assert delays == sorted(delays, key=float)         # bergiliran, tidak serempak
    assert len(set(delays)) == 4


# ── animation & theme safety ──────────────────────────────────────────────

def test_animation_is_disabled_for_reduced_motion():
    css = MODULE.read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: reduce)" in css
    block = css.split("@media (prefers-reduced-motion: reduce)")[1].split("}")[0:3]
    assert "animation: none" in "".join(block)


def test_colours_follow_the_streamlit_theme():
    """Teks & garis memakai currentColor; ada penyesuaian tema gelap."""
    css = MODULE.read_text(encoding="utf-8")
    assert "currentColor" in css
    assert "@media (prefers-color-scheme: dark)" in css
    # Latar tidak boleh dipaku putih/hitam yang rusak di tema sebaliknya.
    for hardcoded in ("background: #fff", "background: white",
                      "background: #000", "background: black"):
        assert hardcoded not in css


def test_no_external_animation_library_is_used():
    """Cukup CSS + SVG inline. (Namespace SVG w3.org bukan pemuatan sumber
    daya — ia tidak pernah diambil lewat jaringan, jadi dikecualikan.)"""
    src = MODULE.read_text(encoding="utf-8").replace(
        "http://www.w3.org/2000/svg", "")
    for token in ("cdn.", "http://", "https://", "<script", "@import"):
        assert token not in src, token


# ── chips come from the constants ─────────────────────────────────────────

def test_chip_overflow_count_is_computed_not_hardcoded():
    items = [f"m{i}" for i in range(CHIP_PREVIEW + 7)]
    html = chips_html(items, "ok")
    assert html.count('class="ids-chip ok"') == CHIP_PREVIEW
    assert f"+{len(items) - CHIP_PREVIEW} lainnya" in html


def test_chips_show_everything_when_short():
    html = chips_html(["numpy", "pandas"], "ok")
    assert "lainnya" not in html
    assert html.count('class="ids-chip ok"') == 2      # wadahnya "ids-chips"


def test_chips_escape_their_content():
    html = chips_html(["<script>alert(1)</script>"], "no")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_forbidden_module_chip_count_matches_the_validator(monkeypatch):
    """Angka "+N" ikut berubah bila konstanta validator berubah."""
    html = chips_html(sorted(FORBIDDEN_MODULES), "no")
    assert f"+{len(FORBIDDEN_MODULES) - CHIP_PREVIEW} lainnya" in html
    for module in sorted(FORBIDDEN_MODULES)[:CHIP_PREVIEW]:
        assert f">{module}<" in html


# ── the panel is generated from structured sources ────────────────────────

def _rendered_pipeline_panel(monkeypatch) -> list[str]:
    """Kumpulkan seluruh teks yang dirender panel pipeline."""
    import ui.components.instructions as ins

    out: list[str] = []
    for name in ("markdown", "caption", "code"):
        monkeypatch.setattr(ins.st, name, lambda s, **k: out.append(str(s)))

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(ins.st, "expander", lambda *a, **k: _Ctx())
    monkeypatch.setattr(ins.st, "columns", lambda n, **k: [_ColumnStub(out)] * n)
    ins.render_pipeline_instructions()
    return out


class _ColumnStub:
    def __init__(self, sink):
        self._sink = sink

    def caption(self, text, **kwargs):
        self._sink.append(str(text))

    def markdown(self, text, **kwargs):
        self._sink.append(str(text))

    def __enter__(self): return self

    def __exit__(self, *a): return False


def test_pipeline_panel_uses_validator_constants(monkeypatch):
    text = " ".join(_rendered_pipeline_panel(monkeypatch))

    assert BASE_CLASS_NAME in text
    for method in REQUIRED_METHODS:
        assert f"{method}()" in text
    for key in EXPECTED_INFO_KEYS:
        assert key in text
    # Jumlah modul ikut ditampilkan dari panjang konstanta.
    assert str(len(ALLOWED_MODULES)) in text
    assert str(len(FORBIDDEN_MODULES)) in text
    # Daftar lengkap (di expander) memuat setiap modul & pemanggilan terlarang.
    for module in sorted(FORBIDDEN_MODULES):
        assert module in text
    for call in sorted(FORBIDDEN_CALLS):
        assert call in text


def test_pipeline_panel_keeps_the_honest_notes(monkeypatch):
    text = " ".join(_rendered_pipeline_panel(monkeypatch)).lower()
    assert "statis" in text
    assert "tidak dijalankan" in text
    assert "research admin" in text
    assert "bukan" in text and "aktif" in text          # lolos ≠ langsung aktif


def test_pipeline_panel_has_no_wall_of_prose(monkeypatch):
    """Tampilan utama padat: yang panjang adalah markup (SVG/CSS), bukan
    paragraf. Teks biasa harus tetap pendek."""
    parts = _rendered_pipeline_panel(monkeypatch)
    prose = [p for p in parts
             if "<style>" not in p and "<svg" not in p and "<div" not in p]
    assert prose
    assert max(len(p) for p in prose) < 800


# ── dataset contract rows come from the schema ────────────────────────────

@pytest.mark.parametrize("dtype", supported_datasets())
def test_dataset_rows_come_from_the_schema(dtype):
    rows = dict(dataset_contract_rows(dtype))
    schema = get_schema(dtype)

    assert schema["label_column"] in rows["Kolom label"]
    assert rows["Format berkas"]
    assert rows["Sifat fitur"]
    assert "dua kelas" in rows["Jumlah kelas"]


@pytest.mark.parametrize("dtype", supported_datasets())
def test_dataset_sample_uses_real_column_names(dtype):
    snippet = dataset_sample_snippet(dtype)
    schema = get_schema(dtype)
    assert snippet

    if schema.get("expected_top_level_keys"):
        for key in ("timestamp", "event_type"):
            assert key in snippet
    else:
        assert schema["label_column"] in snippet
        for column in ("flow_duration", "fwd_pkts_tot"):
            assert column in schema["expected_columns"]
            assert column in snippet


@pytest.mark.parametrize("dtype", supported_datasets())
def test_dataset_checklist_is_one_line_per_point(dtype):
    items = dataset_checklist(dtype)
    assert len(items) == 4
    for item in items:
        assert "\n" not in item
        assert len(item) < 120
    assert any(get_schema(dtype)["label_column"] in i for i in items)


def test_dataset_panel_keeps_the_sample_caveat(monkeypatch):
    import ui.components.instructions as ins

    out: list[str] = []
    for name in ("markdown", "caption", "code", "divider"):
        monkeypatch.setattr(ins.st, name, lambda s=None, **k: out.append(str(s)))

    class _Ctx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(ins.st, "expander", lambda *a, **k: _Ctx())
    monkeypatch.setattr(ins.st, "tabs", lambda labels, **k: [_Ctx() for _ in labels])
    ins.render_dataset_instructions()

    text = " ".join(out).lower()
    assert "cuplikan" in text                    # angka berbasis cuplikan
    assert "research admin" in text              # menunggu tinjauan


# ── the shared Run Experiment panel is untouched ──────────────────────────

def test_the_shared_requirements_panel_is_reused_not_duplicated():
    """Panel persyaratan halaman Run Experiment dipakai apa adanya di dalam
    expander — tidak ada teks persyaratan yang disalin ulang ke sini."""
    src = MODULE.read_text(encoding="utf-8")
    assert "_render_dataset_requirements" in src

    run_src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(encoding="utf-8")
    assert "def _render_dataset_requirements(" in run_src   # masih di tempatnya
