"""Formulir unggah selengkap pipeline bawaan — dan panel yang membuktikannya.

Panel "Tentang Research Pipeline" menggambar 15 baris untuk HIKARI2021. Untuk
research pipeline terunggah ia menggambar 8: delapan barisnya kosong karena
tidak pernah ada yang menanyakan isinya. Jenis penelitian, judul, institusi,
cakupan, sumber dataset, catatan sumber — semuanya fakta TENTANG PENELITIAN,
bukan tentang program, jadi tidak satu pun dapat diturunkan dari kode. Yang
memang sifat KODE (`app`, `anti_leakage`, `metrics_policy`) justru tetap
TINGGAL di kode, dan hanya ditawarkan sebagai daftar periksa opsional —
formulir tidak boleh menjadi sumber kebenaran kedua bagi sifat kodenya.

Berkas ini menjaga tiga hal:
  1. formulir MENANYAKAN setiap bagian, terpisah, tanpa menebak;
  2. pengajuan MEMBAWA jawabannya ke bentuk yang sama persis dengan atribusi
     bawaan — kunci yang sama, sarang yang sama, sehingga panel membacanya
     tanpa cabang khusus;
  3. panelnya benar-benar bertambah — diukur, bukan diasumsikan.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from orchestrator.pipeline_validator import (
    EXPECTED_INFO_KEYS, OPTIONAL_INFO_KEYS, PASS,
)
from orchestrator.submission_service import research_attribution_of

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")
RUNEXP_SRC = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
    encoding="utf-8")

# Formulir yang DIISI LENGKAP — persis bentuk yang dikirim halaman unggah.
FULL_FORM = {
    "paper": "Contoh Kontributor (2026) — Deteksi Trafik Kampus",
    "source_type": "Skripsi",
    "researcher": "Contoh Kontributor",
    "title": "Klasifikasi Trafik Terenkripsi",
    "institution": "Universitas Hasanuddin",
    "year": "2026",
    "dataset_name": "Trafik Kampus 2026",
    "dataset_attribution": "Tim Jaringan UNHAS (2026)",
    "dataset_note": "varian ringkas, pengambilan Maret 2026",
    "scope": "Perbandingan Random Forest dan Decision Tree pada trafik kampus",
}

UPLOADED_INFO = {
    "paper": "Contoh Kontributor (2026) — Deteksi Trafik Kampus",
    "algorithm": "Random Forest", "preprocessing_steps": "scaling",
    "feature_selection": "SelectKBest (k=20)", "fixed_params": {"n": 1},
    "train_test_split": "80/20 stratified",
}

NL = chr(10)


def _flow() -> str:
    return CONTRIB_SRC.split("def _render_pipeline_flow(")[1].split(
        NL + "def ")[0]


def _entry_source(pairs: dict) -> str:
    """Sebuah entry point sah dengan `get_info()` berisi `pairs`."""
    body = ", ".join(f'"{k}": "x"' for k in pairs)
    return NL.join([
        "from pipelines.base import BasePipeline",
        "",
        "",
        "class P(BasePipeline):",
        "    def run(self, pipeline_input, progress=None):",
        "        return None",
        "",
        "    def get_info(self):",
        "        return {" + body + "}",
        "",
    ])


def _info_check(source: str):
    from orchestrator.pipeline_validator import validate_pipeline_source

    report = validate_pipeline_source(source, "p.py")
    return next(c for c in report.checks
                if "get_info" in c.name and "dict" in c.name)


# ── 1. Formulir menanyakan setiap bagian ─────────────────────────────────

@pytest.mark.parametrize("key", [
    "ap.lbl_source_type", "ap.lbl_researcher", "ap.lbl_title",
    "ap.lbl_institution", "ap.lbl_year", "ap.lbl_scope",
    "ap.sec_dataset_source", "ap.lbl_dataset_name",
    "ap.lbl_dataset_attribution", "ap.lbl_dataset_note",
])
def test_the_form_asks_for_every_fact_the_panel_shows(key):
    assert key in _flow(), key


@pytest.mark.parametrize("key", [
    "ap.lbl_source_type", "ap.ph_source_type", "ap.lbl_title",
    "ap.lbl_institution", "ap.lbl_scope", "ap.sec_dataset_source",
    "ap.lbl_dataset_name", "ap.lbl_dataset_attribution",
    "ap.lbl_dataset_note", "ap.ph_dataset_note", "ap.info_optional",
    "ap.gain_app", "ap.gain_anti_leakage", "ap.gain_metrics_policy",
])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


def test_the_research_kind_is_a_closed_list_with_no_default():
    """Diketik bebas, "skripsi"/"Skripsi"/"S1" menjadi tiga jenis berbeda pada
    kolom yang sama. Dan tanpa ``index=None`` pilihan pertama tersimpan sebagai
    jawaban yang tidak pernah diberikan siapa pun."""
    from ui.views.contribute import SOURCE_TYPES

    assert isinstance(SOURCE_TYPES, tuple) and len(SOURCE_TYPES) >= 4
    assert "Skripsi" in SOURCE_TYPES and "Jurnal" in SOURCE_TYPES
    flow = _flow()
    assert "selectbox(" in flow and "SOURCE_TYPES" in flow
    assert "index=None" in flow


def test_the_submission_carries_every_answer():
    flow = _flow()
    for field in ('"source_type": source_type', '"researcher": researcher',
                  '"title": title', '"institution": institution',
                  '"year": year', '"dataset_name": dataset_name',
                  '"dataset_attribution": dataset_attribution',
                  '"dataset_note": dataset_note', '"scope": scope'):
        assert field in flow, field


# ── 2. Bentuknya sama persis dengan atribusi bawaan ──────────────────────

def test_the_attribution_lands_in_the_shape_the_panel_reads():
    """Kunci dan sarangnya sama dengan atribusi bawaan — kalau tidak, panelnya
    butuh cabang khusus untuk unggahan, dan cabang itulah yang akan lupa
    diperbarui."""
    attr = research_attribution_of({"metadata": FULL_FORM},
                                   "Deteksi Trafik Kampus")

    assert attr["pipeline_source"] == {
        "type": "Skripsi", "authors": "Contoh Kontributor",
        "title": "Klasifikasi Trafik Terenkripsi",
        "institution": "Universitas Hasanuddin", "year": "2026"}
    assert attr["dataset_source"] == {
        "name": "Trafik Kampus 2026",
        "attribution": "Tim Jaringan UNHAS (2026)",
        "note": "varian ringkas, pengambilan Maret 2026"}
    assert attr["scope"].startswith("Perbandingan Random Forest")


def test_an_unanswered_field_is_absent_not_empty():
    """Sebuah string kosong tersimpan sebagai fakta, lalu tergambar sebagai
    baris kosong. Yang tidak dijawab harus HILANG, bukan kosong."""
    attr = research_attribution_of(
        {"metadata": {"researcher": "Budi", "year": "2026"}}, "Uji")

    assert attr["pipeline_source"] == {"authors": "Budi", "year": "2026"}
    assert "dataset_source" not in attr
    assert "scope" not in attr
    assert "" not in attr.values()


def test_older_submissions_keep_working():
    """Pengajuan sebelum R hanya punya `study` gabungan. Ia tetap menghasilkan
    kredit yang sama seperti dulu — tidak ada yang rusak, hanya kurang."""
    attr = research_attribution_of(
        {"metadata": {"researcher": "Budi", "year": "2026",
                      "study": "Universitas Hasanuddin"}}, "Uji")

    assert attr["paper_credit"] == "Budi (2026), Universitas Hasanuddin"
    assert attr["pipeline_source"]["institution"] == "Universitas Hasanuddin"


# ── 3. Panelnya benar-benar bertambah — DIUKUR ───────────────────────────

def _rows(research, label, info, attribution) -> int:
    from ui.views.run_experiment import (
        _dataset_info_lines, research_about_groups,
    )
    groups = research_about_groups(research, label, info, attribution,
                                   _dataset_info_lines(research))
    return sum(len(rows) for _title, rows in groups)


def test_a_filled_form_lifts_the_panel_by_at_least_five_rows():
    """Diukur, bukan diasumsikan: formulir lama vs formulir baru, panel yang
    sama, pipeline yang sama."""
    old = research_attribution_of(
        {"metadata": {"paper": FULL_FORM["paper"],
                      "researcher": "Contoh Kontributor", "year": "2026",
                      "study": "Universitas Hasanuddin"}},
        "Deteksi Trafik Kampus")
    new = research_attribution_of({"metadata": FULL_FORM},
                                  "Deteksi Trafik Kampus")

    before = _rows("uploaded:x", old["display_name"], UPLOADED_INFO, old)
    after = _rows("uploaded:x", new["display_name"], UPLOADED_INFO, new)
    assert after >= before + 5, (before, after)


def test_the_uploaded_source_group_matches_the_builtin_one():
    """Kelompok "Penelitian sumber" pipeline bawaan punya tujuh baris. Formulir
    yang terisi lengkap harus menghasilkan tujuh juga — bukan sebagian."""
    from orchestrator.research_registry import attribution_for
    from ui.views.run_experiment import research_about_groups

    def source_rows(attr, label):
        for title, rows in research_about_groups("X", label, UPLOADED_INFO,
                                                 attr):
            if title == "Penelitian sumber":
                return [k for k, _v in rows]
        return []

    builtin = source_rows(attribution_for("HIKARI2021"),
                          "Rayyan (2024) — HIKARI2021")
    attr = research_attribution_of({"metadata": FULL_FORM},
                                   "Deteksi Trafik Kampus")
    uploaded = source_rows(attr, attr["display_name"])

    assert builtin == uploaded, (builtin, uploaded)


# ── 4. Kunci get_info() opsional: ditawarkan, tidak dituntut ─────────────

def test_the_optional_keys_are_exactly_what_the_panel_reads():
    """Daftar ini hanya berguna bila ia sama dengan yang benar-benar dibaca
    panel; sebuah kunci yang tidak digambar apa pun tidak layak diminta."""
    panel = RUNEXP_SRC.split("def research_about_groups(")[1].split(
        NL + "def ")[0]
    for key in OPTIONAL_INFO_KEYS:
        assert f'info.get("{key}")' in panel, key
    assert not set(OPTIONAL_INFO_KEYS) & set(EXPECTED_INFO_KEYS)


def test_a_missing_optional_key_is_never_a_warning():
    """Ia bukan bagian kontrak. Memperingatkannya akan mengajari kontributor
    bahwa kontraknya lebih besar daripada yang sebenarnya."""
    check = _info_check(_entry_source({k: "x" for k in EXPECTED_INFO_KEYS}))

    assert check.status == PASS
    assert (check.values or {}).get("optional_keys") == []


def test_a_present_optional_key_is_recorded():
    keys = {k: "x" for k in EXPECTED_INFO_KEYS}
    keys.update({"app": "x", "metrics_policy": "x"})
    check = _info_check(_entry_source(keys))

    assert (check.values or {})["optional_keys"] == ["app", "metrics_policy"]


def test_the_page_offers_the_absent_optional_keys():
    from ui.views.contribute import _INFO_KEY_GAIN, _optional_keys_of

    entry = {"report": {"checks": [
        {"values": {"present_keys": list(EXPECTED_INFO_KEYS),
                    "missing_keys": [], "optional_keys": ["app"]}}]}}
    assert _optional_keys_of(entry) == ["anti_leakage", "metrics_policy"]
    assert set(_INFO_KEY_GAIN) == set(OPTIONAL_INFO_KEYS)
    assert _optional_keys_of({}) == []


def test_the_offer_never_reuses_the_language_of_a_defect():
    """Kalimatnya menyebut apa yang DIDAPAT. Menyebutnya "hilang" akan membuat
    tawaran terbaca sebagai tuntutan."""
    from ui.i18n.core import lookup

    for key in ("ap.gain_app", "ap.gain_anti_leakage",
                "ap.gain_metrics_policy"):
        text = lookup(key, "id").lower()
        assert "tidak muncul" not in text and "hilang" not in text, key


def test_the_source_under_validation_is_still_parsed_once():
    """Aturan lama, dijaga lagi di sini: satu pohon, satu himpunan aturan."""
    body = (REPO_ROOT / "orchestrator" / "pipeline_validator.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(body))
              if isinstance(n, ast.FunctionDef) and n.name == "_check_get_info")
    assert "ast.parse" not in ast.get_source_segment(body, fn)


# ── 5. Kontrak dataset kontribusi dibaca dari yang DIDEKLARASIKAN ────────

def test_the_declared_contract_is_what_the_panel_shows(monkeypatch):
    """``contracts.dataset_schemas`` hanya mengenal jenis bawaan. Tanpa
    cadangan, panel menyebut kolom label `label` untuk dataset yang kolom
    labelnya bernama lain — menyatakan sesuatu yang TIDAK BENAR."""
    import orchestrator.research_registry as rr
    import ui.views.run_experiment as rx

    monkeypatch.setattr(rx, "get_schema", lambda _dt: None)
    monkeypatch.setattr(rr, "schema_for", lambda _dt, db_path=None: None)
    assert rx._dataset_info_lines("uploaded:contoh_uji") == [
        "**Tipe dataset:** uploaded:contoh_uji (kolom label `label`)."]

    monkeypatch.setattr(rr, "schema_for", lambda _dt, db_path=None: {
        "label_column": "serangan", "file_format": "csv",
        "expected_columns": ["durasi", "serangan"]})
    lines = rx._dataset_info_lines("uploaded:contoh_uji")

    assert "**Kolom label:** `serangan`" in lines
    assert any(line.startswith("**Format berkas:** CSV") for line in lines)
    assert any("2 kolom" in line for line in lines)


def test_the_builtin_dataset_lines_are_untouched():
    import ui.views.run_experiment as rx

    assert rx._dataset_info_lines("HIKARI2021")[0] == \
        "**Format berkas:** CSV (varian ALLFLOWMETER)"
    assert len(rx._dataset_info_lines("HIKARI2021")) == 3
    assert len(rx._dataset_info_lines("EVE_SURICATA")) == 3
