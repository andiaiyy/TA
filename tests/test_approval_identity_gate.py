"""Peninjau tidak lagi ditanya "ini ikut research pipeline mana".

Isian "Dataset target" dahulu meminta peninjau memutuskan sesuatu yang bukan
kewenangannya: paket yang diunggah ADALAH research pipeline-nya sendiri, jadi
pengenalnya dibentuk dari namanya. Pertanyaan itu hilang.

Yang tidak boleh ikut hilang adalah KEJUJURANNYA. Sebuah pengajuan yang tidak
membawa identitas tetap tidak dapat disetujui — dan itu harus dikatakan pada
tombolnya, bukan dibiarkan meledak sebagai galat setelah ditekan. Modul ini
menjaga pembedaan itu: gerbang uji coba berkata "belum boleh SEKARANG",
gerbang identitas berkata "tidak akan pernah boleh sebelum diunggah ulang".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from database.models import KIND_DATASET, KIND_PIPELINE
from orchestrator.submission_service import approval_identity_blocker

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = {"label_column": "attack", "expected_columns": ["a", "b"],
          "file_format": "csv"}


def _item(**metadata):
    return {"id": 1, "kind": KIND_PIPELINE, "original_filename": "p.py",
            "metadata": metadata}


# ── Yang berdiri sendiri ─────────────────────────────────────────────────

def test_a_standalone_submission_with_a_name_passes():
    item = _item(name="Deteksi Anomali", declared_schema=SCHEMA)
    assert approval_identity_blocker(item) == ""


def test_a_standalone_submission_without_a_name_is_named_as_the_problem():
    """Nama kosong berarti pengenal tidak dapat dibentuk. Nama berkas tetap
    menjadi cadangan — jadi keduanya harus kosong untuk benar-benar buntu."""
    item = {"id": 1, "kind": KIND_PIPELINE, "original_filename": "",
            "metadata": {"declared_schema": SCHEMA}}
    assert approval_identity_blocker(item) == "ap.err_identity_no_name"


def test_a_name_that_yields_no_identifier_is_refused():
    """Nama yang seluruhnya tanda baca tidak menghasilkan pengenal yang sah."""
    item = _item(name="--- ///", declared_schema=SCHEMA)
    assert approval_identity_blocker(item) == "ap.err_identity_bad_name"


def test_the_file_name_still_serves_as_a_fallback_name():
    item = {"id": 1, "kind": KIND_PIPELINE, "original_filename": "rf_hikari.py",
            "metadata": {"declared_schema": SCHEMA}}
    assert approval_identity_blocker(item) == ""


# ── Yang lama (menumpang) ────────────────────────────────────────────────

def test_a_legacy_submission_without_a_dataset_type_is_refused():
    """Persis keadaan dua pengajuan yang sudah ada di basis data: tanpa
    kontrak, tanpa jenis. Tanpa gerbang ini, tombol Setujui tampak hidup lalu
    gagal dengan jejak teknis."""
    assert approval_identity_blocker(_item(name="A")) == "ap.err_identity_legacy"


def test_a_legacy_submission_with_a_type_but_no_entry_class_is_refused():
    item = _item(name="A", dataset_type="HIKARI2021")
    assert approval_identity_blocker(item) == "ap.err_identity_no_entry_class"


def test_a_complete_legacy_submission_still_passes():
    """Pengajuan lama yang LENGKAP tidak boleh ikut tertolak — perubahan ini
    membuang pertanyaannya, bukan membuang datanya."""
    item = _item(name="A", dataset_type="HIKARI2021", entry_class="DemoPipeline")
    assert approval_identity_blocker(item) == ""


def test_a_dataset_submission_is_never_blocked_by_this_gate():
    item = {"id": 1, "kind": KIND_DATASET, "original_filename": "d.csv",
            "metadata": {}}
    assert approval_identity_blocker(item) == ""


# ── Sifat gerbangnya ─────────────────────────────────────────────────────

def test_the_gate_touches_neither_database_nor_disk(monkeypatch):
    """Fungsi MURNI: ia dipanggil untuk SETIAP kartu yang tergambar."""
    import sqlite3

    def _boom(*a, **k):
        raise AssertionError("gerbang identitas membuka basis data")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    monkeypatch.setattr(Path, "read_text",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("gerbang identitas membaca berkas")))
    assert approval_identity_blocker(_item(name="A", declared_schema=SCHEMA)) == ""


@pytest.mark.parametrize("key", ["ap.err_identity_no_name",
                                 "ap.err_identity_bad_name",
                                 "ap.err_identity_legacy",
                                 "ap.err_identity_no_entry_class"])
def test_every_reason_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)


def test_every_reason_names_a_way_out():
    """Alasan yang tidak menyebut jalan keluar hanya memberi tahu peninjau
    bahwa ia buntu."""
    from ui.i18n.core import lookup

    for key in ("ap.err_identity_no_name", "ap.err_identity_bad_name",
                "ap.err_identity_legacy", "ap.err_identity_no_entry_class"):
        assert "ulang" in lookup(key, "id").lower(), key
        assert "resubmit" in lookup(key, "en").lower(), key


def test_the_identity_gate_wins_over_the_trial_gate():
    """"Tidak akan pernah boleh" lebih berguna daripada "belum diuji" — dan
    menyuruh peninjau menguji sesuatu yang tetap akan ditolak membuang
    waktunya."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    card = src.split("def _render_submission_review_card(")[1].split("\ndef ")[0]
    assert "gate = approval_identity_blocker(item) or gate" in card


def test_the_reviewer_can_no_longer_choose_a_dataset_type():
    """Pengaman inti perubahan ini: tidak ada jalan bagi peninjau untuk
    menuliskan `dataset_type` yang tidak berasal dari pengajuannya sendiri."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "dataset_type=chosen_type" not in src
    assert "ap.lbl_target_dataset" not in src
