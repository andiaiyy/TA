"""Kredit penelitian terstruktur — dan label yang berhenti mengulang dirinya.

``short_label_for`` menyusun labelnya sebagai ``"<kredit> — <nama pendek>"``,
dengan kreditnya diambil dari bagian ``display_name`` SEBELUM tanda hubung.
Pipeline bawaan menyimpan ``"Rayyan (2024) — Klasifikasi Trafik Terenkripsi
HIKARI2021"``, jadi kreditnya "Rayyan (2024)" dan labelnya "Rayyan (2024) —
HIKARI2021".

Research pipeline terunggah dahulu menyimpan ``"<nama> (kontribusi)"`` — tanpa
tanda hubung. Tidak ada kredit yang ditemukan, seluruh kalimat dipakai sebagai
kredit, dan hasilnya nama yang mengulang dirinya:

    Deteksi Anomali (kontribusi) — Deteksi Anomali

Sebabnya bukan di penyusun label, melainkan di apa yang disimpan. Dan sebab
yang lebih dalam: formulir hanya punya SATU kolom teks bebas, yang tidak dapat
dipisah kembali menjadi bagian-bagiannya tanpa menebak.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.submission_service import (
    research_attribution_of, research_credit,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIB_SRC = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
    encoding="utf-8")


# ── Menyusun kalimat kredit ──────────────────────────────────────────────

def test_the_credit_follows_the_builtin_shape():
    assert research_credit("Budi", "2026", "Universitas Hasanuddin") == \
        "Budi (2026), Universitas Hasanuddin"


def test_a_missing_part_is_dropped_not_padded():
    """"— (—)" bukan keterangan, hanya ruang yang terisi."""
    assert research_credit("Budi", "2026") == "Budi (2026)"
    assert research_credit("Budi", "", "UNHAS") == "Budi, UNHAS"
    assert research_credit("Budi") == "Budi"


def test_no_researcher_leaves_only_what_is_known():
    assert research_credit("", "2026", "UNHAS") == "UNHAS"
    assert research_credit("", "", "") == ""
    assert research_credit(None, None, None) == ""


def test_whitespace_is_not_mistaken_for_a_value():
    assert research_credit("   ", "  ", "  ") == ""


def test_a_year_given_as_a_number_still_reads_right():
    """Isian formulir berupa teks, tetapi pemanggil lain boleh mengirim int."""
    assert research_credit("Budi", 2026) == "Budi (2026)"


# ── Nama tampil ──────────────────────────────────────────────────────────

def _item(**metadata):
    return {"id": 1, "metadata": metadata}


def test_the_display_name_puts_the_credit_before_the_name():
    """Pola yang SAMA dengan atribusi bawaan — itulah yang membuat
    `short_label_for` menemukan kreditnya."""
    got = research_attribution_of(
        _item(researcher="Budi", year="2026", study="UNHAS"), "Deteksi Anomali")
    assert got["display_name"] == "Budi (2026), UNHAS — Deteksi Anomali"
    assert got["short_name"] == "Deteksi Anomali"
    assert got["paper_credit"] == "Budi (2026), UNHAS"


def test_an_old_submission_falls_back_to_its_free_text_field():
    """Pengajuan LAMA hanya menyimpan satu kolom bebas; ia dipakai apa adanya."""
    got = research_attribution_of(_item(paper="Budi (2026), UNHAS"),
                                  "Deteksi Anomali")
    assert got["display_name"] == "Budi (2026), UNHAS — Deteksi Anomali"


def test_no_credit_at_all_never_invents_one():
    """Mengarang peneliti yang tidak pernah disebut siapa pun lebih buruk
    daripada nama tanpa kredit."""
    got = research_attribution_of(_item(), "Deteksi Anomali")
    assert got["display_name"] == "Deteksi Anomali"
    assert "paper_credit" not in got


def test_building_the_attribution_reads_nothing(monkeypatch):
    import sqlite3

    def _boom(*a, **k):
        raise AssertionError("penyusun atribusi membuka basis data")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    research_attribution_of(_item(researcher="Budi", year="2026"), "X")


# ── Label yang berhenti mengulang ────────────────────────────────────────

def _registered(tmp_path, attribution: dict) -> str:
    from database.migration import apply_migrations
    from orchestrator.research_registry import register_research

    db = tmp_path / "credit.db"
    apply_migrations(str(db))
    register_research(dataset_type="uploaded:deteksi_anomali",
                      name="Deteksi Anomali",
                      schema={"label_column": "a", "expected_columns": ["a"],
                              "file_format": "csv"},
                      registered_by="boss", submission_id=1,
                      attribution=attribution, db_path=str(db))
    return str(db)


def test_the_short_label_no_longer_repeats_the_name(tmp_path):
    from orchestrator.research_registry import short_label_for

    db = _registered(tmp_path, research_attribution_of(
        _item(researcher="Budi", year="2026"), "Deteksi Anomali"))
    assert short_label_for("uploaded:deteksi_anomali", db_path=db) == \
        "Budi (2026) — Deteksi Anomali"


def test_the_old_shape_was_the_thing_that_repeated(tmp_path):
    """Penjaga anti-hampa: membuktikan bentuk LAMA memang menghasilkan
    pengulangan itu — kalau tidak, test di atas lulus tanpa membuktikan apa pun.
    """
    from orchestrator.research_registry import short_label_for

    db = _registered(tmp_path, {"display_name": "Deteksi Anomali (kontribusi)",
                                "short_name": "Deteksi Anomali"})
    assert short_label_for("uploaded:deteksi_anomali", db_path=db) == \
        "Deteksi Anomali (kontribusi) — Deteksi Anomali"


def test_a_pipeline_without_credit_shows_just_its_name(tmp_path):
    from orchestrator.research_registry import short_label_for

    db = _registered(tmp_path, research_attribution_of(_item(),
                                                       "Deteksi Anomali"))
    assert short_label_for("uploaded:deteksi_anomali", db_path=db) == \
        "Deteksi Anomali"


def test_the_builtin_labels_are_untouched():
    from orchestrator.research_registry import short_label_for

    assert short_label_for("HIKARI2021") == "Rayyan (2024) — HIKARI2021"


# ── Formulir ─────────────────────────────────────────────────────────────

def test_the_form_asks_for_the_parts_not_one_free_text_field():
    """Satu kolom bebas tidak dapat dipisah kembali menjadi bagian-bagiannya
    tanpa menebak — dan menebak itulah yang melahirkan label yang salah."""
    flow = CONTRIB_SRC.split("def _render_pipeline_flow(")[1].split(
        chr(10) + "def ")[0]
    for key in ("ap.lbl_researcher", "ap.lbl_year", "ap.lbl_institution"):
        assert key in flow, key
    assert "ap.lbl_paper" not in CONTRIB_SRC


def test_the_orphaned_label_left_the_catalog():
    from ui.i18n.catalog import CATALOG

    assert "ap.lbl_paper" not in CATALOG


def test_the_submission_keeps_both_the_sentence_and_its_parts():
    """Kalimatnya dipakai apa adanya oleh entri registry dan laporan — persis
    seperti sebelumnya; bagian-bagiannya yang membuat nama tampil benar."""
    flow = CONTRIB_SRC.split("def _render_pipeline_flow(")[1].split(
        chr(10) + "def ")[0]
    for field in ('"paper": paper', '"researcher": researcher',
                  '"year": year', '"institution": institution'):
        assert field in flow, field


def test_the_form_shows_what_the_label_will_become():
    """Akibat isian ini tidak terlihat sampai pipelinenya disetujui, jadi ia
    diperlihatkan sekarang."""
    flow = CONTRIB_SRC.split("def _render_pipeline_flow(")[1].split(
        chr(10) + "def ")[0]
    assert "ap.credit_preview" in flow

    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        text = lookup("ap.credit_preview", lang)
        assert "{credit}" in text and "{name}" in text, lang


@pytest.mark.parametrize("key", ["ap.sec_credit", "ap.lbl_researcher",
                                 "ap.lbl_year", "ap.lbl_institution",
                                 "ap.credit_preview"])
def test_every_new_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)
