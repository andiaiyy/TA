"""Kelengkapan ``get_info()`` dinyatakan — beserta APA YANG HILANG.

Enam kunci metadata (``paper``, ``algorithm``, ``preprocessing_steps``,
``feature_selection``, ``fixed_params``, ``train_test_split``) selama ini hanya
berstatus WARN di validator, terkubur sebagai satu baris di antara belasan
pemeriksaan, dan halaman unggah tidak pernah menyebutnya sama sekali. Akibatnya
terukur: paket dengan ``get_info()`` seadanya menghasilkan **0 parameter
tampil**, sementara pipeline bawaan menghasilkan **8 tampil, 2 dapat diubah** —
transparansi hyperparameter dan mode eksplorasi mati bersamaan.

Dua posisi desain yang dijaga di sini:

* **Ditampilkan, tidak ditanyakan.** ``fixed_params`` adalah sifat KODE yang
  akan dijalankan. Isian formulir untuknya melahirkan sumber kebenaran kedua
  yang dapat berbeda dari kodenya, lalu tersimpan sebagai fakta.
* **Memperingatkan, bukan menghalangi.** ``get_info()`` tak lengkap tidak
  membuat pipelinenya salah — hanya kurang terbaca.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.pipeline_validator import (
    EXPECTED_INFO_KEYS, validate_pipeline_source,
)


def declared_info_keys(source: str) -> tuple[list, list]:
    """(ada, belum) — dibaca dari laporan validasi, seperti halaman unggah.

    Source yang divalidasi hanya boleh disentuh SATU `ast.parse`, jadi jawaban
    ini memang datang dari pemeriksaan yang sudah dihitung, bukan dari parse
    kedua. Pembungkus ini menempuh jalur yang sama dengan UI.
    """
    from ui.views.contribute import _info_keys_of

    report = validate_pipeline_source(source, "x.py").to_dict()
    return _info_keys_of({"report": report})

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")

COMPLETE = '''
from pipelines.base import BasePipeline


class P(BasePipeline):
    def run(self, pipeline_input, progress=None):
        pass

    def get_info(self):
        return {"paper": "x", "algorithm": "RF", "preprocessing_steps": [],
                "feature_selection": None, "fixed_params": {},
                "train_test_split": {}}
'''

MINIMAL = '''
from pipelines.base import BasePipeline


class P(BasePipeline):
    def run(self, pipeline_input, progress=None):
        pass

    def get_info(self):
        return {"algorithm": "RF"}
'''

DYNAMIC = '''
from pipelines.base import BasePipeline


class P(BasePipeline):
    def run(self, pipeline_input, progress=None):
        pass

    def get_info(self):
        out = {}
        out["algorithm"] = "RF"
        return out
'''


# ── Membaca kunci ────────────────────────────────────────────────────────

def test_a_complete_get_info_reports_nothing_missing():
    present, missing = declared_info_keys(COMPLETE)
    assert present == list(EXPECTED_INFO_KEYS)
    assert missing == []


def test_a_minimal_get_info_names_every_missing_key():
    present, missing = declared_info_keys(MINIMAL)
    assert present == ["algorithm"]
    assert set(missing) == set(EXPECTED_INFO_KEYS) - {"algorithm"}


def test_a_dynamic_get_info_is_not_accused_of_being_incomplete():
    """Dict yang dibangun dinamis memang tidak dapat dibaca statis. Menuduhnya
    "semuanya hilang" akan menyalahkan paket yang boleh jadi lengkap."""
    assert declared_info_keys(DYNAMIC) == ([], [])


@pytest.mark.parametrize("source", ["def (", "", "x = 1"])
def test_unreadable_source_answers_empty_instead_of_raising(source):
    """Ia dipanggil untuk setiap berkas pada halaman unggah."""
    assert declared_info_keys(source) == ([], [])


def test_the_builtin_pipelines_are_complete():
    """Penjaga anti-hampa: kalau pembacanya salah, pipeline bawaan pun akan
    terbaca tidak lengkap."""
    source = (REPO_ROOT / "pipelines" / "hikari2021"
              / "rfc_pipeline.py").read_text(encoding="utf-8")
    present, missing = declared_info_keys(source)
    assert missing == [], missing
    assert present == list(EXPECTED_INFO_KEYS)


def test_the_key_list_has_one_source():
    """"Yang diperiksa" dan "yang dilaporkan" tidak boleh berbeda: keduanya
    membaca `EXPECTED_INFO_KEYS` yang sama."""
    body = (REPO_ROOT / "orchestrator" / "pipeline_validator.py").read_text(
        encoding="utf-8").split("def _check_get_info(")[1].split(
        chr(10) + "def ")[0]
    assert body.count("EXPECTED_INFO_KEYS") == 2       # present & missing
    assert '"missing_keys": list(missing)' in body
    assert '"present_keys": list(present)' in body


def test_the_page_never_parses_the_source_a_second_time():
    """PENGAMAN: source yang divalidasi hanya boleh disentuh SATU `ast.parse`.

    Satu pohon, satu himpunan aturan — tidak ada jalur kedua yang dapat
    memperlakukan kode yang sama secara berbeda.
    """
    import ast

    from ui.views.contribute import _info_keys_of

    # KODE-nya saja: memindai teks mentah menyamakan `ast.parse(...)` dengan
    # kalimat "hanya boleh disentuh satu ast.parse" di dalam docstring —
    # larangan yang menangkap penjelasan, bukan perbuatan.
    fn = ast.parse(CONTRIB_SRC).body
    node = next(n for n in fn
                if isinstance(n, ast.FunctionDef) and n.name == "_info_keys_of")
    node.body = node.body[1:]                  # buang docstring-nya
    body = ast.unparse(node)
    for forbidden in ("ast.", "parse", "compile", "exec"):
        assert forbidden not in body, forbidden
    assert "present_keys" in body

    # …dan ia benar-benar bekerja atas laporan, bukan atas source.
    assert _info_keys_of({"report": {"checks": [
        {"values": {"present_keys": ["algorithm"], "missing_keys": ["paper"]}}
    ]}}) == (["algorithm"], ["paper"])


def test_reading_the_keys_touches_neither_database_nor_disk(monkeypatch):
    import sqlite3

    from ui.views.contribute import _info_keys_of

    def _boom(*a, **k):
        raise AssertionError("pembaca kunci membuka basis data")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    assert declared_info_keys(MINIMAL)[0] == ["algorithm"]
    assert _info_keys_of({}) == ([], [])          # laporan kosong ≠ galat


# ── Apa yang hilang, dinyatakan ──────────────────────────────────────────

def test_every_expected_key_has_a_stated_consequence():
    """Kunci tanpa kalimat akan lolos tanpa menyebut akibatnya sama sekali —
    daftar periksa yang diam pada satu barisnya lebih buruk daripada tidak ada.
    """
    from ui.views.contribute import _INFO_KEY_COST

    assert set(_INFO_KEY_COST) == set(EXPECTED_INFO_KEYS)


@pytest.mark.parametrize("key", sorted({
    "ap.cost_paper", "ap.cost_algorithm", "ap.cost_preprocessing",
    "ap.cost_feature_selection", "ap.cost_fixed_params",
    "ap.cost_train_test_split", "ap.info_incomplete",
    "ap.info_incomplete_note"}))
def test_every_sentence_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


def test_the_costliest_key_is_named_as_the_costliest():
    """``fixed_params`` bukan sekadar "kurang terbaca": tanpa itu TIDAK ADA
    parameter yang tampil, dan mode eksplorasi mati. Terukur 8 vs 0."""
    from ui.i18n.core import lookup

    assert "tidak ada satu pun parameter" in lookup("ap.cost_fixed_params",
                                                    "id").lower()
    assert "no parameter" in lookup("ap.cost_fixed_params", "en").lower()


def test_the_measured_consequence_is_real():
    """Angka yang dipakai menulis kalimat itu diukur, bukan diperkirakan."""
    from config.pipeline_registry import PIPELINE_REGISTRY
    from orchestrator.run_mode import param_rows

    full = PIPELINE_REGISTRY["hikari2021.rfc_pipeline"]["class"]().get_info()
    rows = param_rows("hikari2021.rfc_pipeline", info=full)
    assert len(rows) >= 8
    assert any(r["tunable"] for r in rows)

    without = param_rows("hikari2021.rfc_pipeline",
                         info={"algorithm": "Random Forest"})
    assert without == []


# ── Sifat tampilannya ────────────────────────────────────────────────────

def test_the_page_shows_the_keys_instead_of_asking_for_them():
    """``fixed_params`` adalah sifat KODE. Isian formulir untuknya menjadi
    sumber kebenaran kedua yang dapat berbeda dari kode yang berjalan."""
    body = CONTRIB_SRC.split("def _render_info_completeness(")[1].split(
        chr(10) + "def ")[0]
    for widget in ("text_input", "text_area", "selectbox", "number_input"):
        assert widget not in body, widget


def test_the_note_points_at_the_code_not_at_the_form():
    from ui.i18n.core import lookup

    assert "get_info()" in lookup("ap.info_incomplete_note", "id")
    assert "kode Anda" in lookup("ap.info_incomplete_note", "id")


def test_it_warns_and_never_blocks():
    """Keputusan yang diambil: memperingatkan. ``get_info()`` tak lengkap tidak
    membuat pipelinenya salah."""
    body = CONTRIB_SRC.split("def _render_info_completeness(")[1].split(
        chr(10) + "def ")[0]
    for blocker in ("disabled=", "st.stop()", "return False", "raise "):
        assert blocker not in body, blocker

    from ui.i18n.core import lookup

    assert "tidak menghalangi" in lookup("ap.info_incomplete_note", "id").lower()


def test_a_complete_package_is_not_nagged():
    """Daftar periksa yang selalu muncul berhenti dibaca."""
    body = CONTRIB_SRC.split("def _render_info_completeness(")[1].split(
        chr(10) + "def ")[0]
    assert "if not missing:" in body
    assert "continue" in body


def test_only_entry_points_are_checked():
    """Berkas pendukung tidak punya ``get_info()`` — menuduhnya tidak lengkap
    adalah peringatan yang tidak dapat ditindaklanjuti."""
    body = CONTRIB_SRC.split("def _render_info_completeness(")[1].split(
        chr(10) + "def ")[0]
    assert 'f["role"] == ROLE_ENTRY' in body


def test_the_checklist_adds_no_small_text():
    """Kuota teks kecil halaman ini sudah penuh (3/3)."""
    from tests import small_text_audit as audit

    items = audit.audit("Add Pipeline & Dataset")
    assert len(items) <= audit.QUOTA, [i["text"] for i in items]
