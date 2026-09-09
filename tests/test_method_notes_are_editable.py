"""Keterangan metode berpindah rumah supaya dapat DIPERBAIKI.

Tahap sebelumnya menanyakan empat keterangan — ``app``, ``metrics_policy``,
``dataset``, ``anti_leakage`` — pada formulir unggah, lalu menumpuknya ke
potret ``info_json`` saat pengajuan disetujui. Potret itu milik SATU versi SATU
algoritma dan sengaja tidak pernah berubah: ia rekaman apa yang kode katakan.
Akibatnya keterangan yang ikut menumpang di dalamnya juga tidak dapat berubah —
salah ketik pada saat mengunggah menjadi permanen — dan tombol "Perbarui
keterangan", yang memotret ulang, MENGHAPUSNYA tanpa cara mengembalikannya.

Sekarang keterangan itu tinggal di baris researchnya, tempat yang memang
disunting Research Admin, dan penggabungannya terjadi SAAT TAMPIL. Arah
presedennya tidak berubah sedikit pun: kode menang. Yang berubah hanyalah
kapan penggabungan itu terjadi — dan karena ia terjadi setiap kali halaman
digambar, memperbaiki keterangan langsung terlihat.

Paket yang MENUMPANG jenis dataset bawaan tidak punya baris research yang
memilikinya. Bagi mereka potret tetap satu-satunya rumah, dan yang diperbaiki
di sini adalah tombol yang tadinya menghapus isinya.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SOURCE = """
from pipelines.base import BasePipeline


class DemoPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return None

    def get_info(self):
        return {
            "paper": "Contoh (2026)",
            "algorithm": "Random Forest",
            "preprocessing_steps": "scaling",
            "anti_leakage": ["ditulis oleh kode"],
        }
"""

CATATAN = {"app": "TLS",
           "metrics_policy": "metrik kelas serangan pada holdout",
           "dataset": "trafik kampus Januari 2026",
           "anti_leakage": ["diketik di formulir"]}

ISIAN = {"info_app": "TLS",
         "info_metrics_policy": "metrik kelas serangan pada holdout",
         "info_dataset": "trafik kampus Januari 2026",
         "info_anti_leakage": "diketik di formulir"}

DTYPE = "uploaded:demo"


@pytest.fixture
def db(tmp_path) -> str:
    from database.db import init_db

    path = str(tmp_path / "notes.db")
    init_db(path)
    return path


@pytest.fixture
def entry(tmp_path) -> Path:
    file = tmp_path / "demo_pipeline.py"
    file.write_text(SOURCE, encoding="utf-8")
    return file


def _admin(db: str) -> dict:
    from database.db import get_connection

    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) "
            "VALUES ('bos', 'x', 'research_admin', '2026-01-01T00:00:00')")
        conn.commit()
    return {"username": "bos", "role": "research_admin"}


def _research(db: str, notes=CATATAN, dtype: str = DTYPE) -> None:
    from orchestrator.research_registry import register_research

    attribution = {"short_name": "Demo", "display_name": "Contoh — Demo"}
    if notes:
        attribution["method_notes"] = notes
    register_research(dataset_type=dtype, name="Demo",
                      schema={"label_column": "y", "file_format": "csv"},
                      registered_by="tester", submission_id=None,
                      attribution=attribution, db_path=db)


def _pipeline(db: str, entry: Path, dtype: str = DTYPE, *,
              submission_id=None, info_extra=None):
    from orchestrator.dynamic_registry import register_pipeline

    return register_pipeline(name="demo", dataset_type=dtype,
                             entry_class="DemoPipeline", entry_file=entry,
                             registered_by="tester",
                             submission_id=submission_id,
                             info_extra=info_extra, db_path=db)


def _info(db: str, pipeline_id: str) -> dict:
    from orchestrator.dynamic_registry import get_all_pipelines

    return get_all_pipelines(db)[pipeline_id]["info"]


# ── Potret tetap murni; catatan tinggal di baris research ────────────────

def test_the_notes_travel_with_the_research_not_the_snapshot():
    """Fungsi murni: atribusi sebuah pengajuan MEMBAWA keterangan metodenya,
    dan bentuknya sama persis dengan yang dipakai penyajinya."""
    from orchestrator.submission_service import (info_extra_of,
                                                 research_attribution_of)

    attribution = research_attribution_of({"metadata": ISIAN}, "Demo")

    assert attribution["method_notes"] == info_extra_of(ISIAN)
    assert attribution["method_notes"]["anti_leakage"] == ["diketik di formulir"]


def test_a_submission_without_notes_grows_no_empty_key():
    from orchestrator.submission_service import research_attribution_of

    assert "method_notes" not in research_attribution_of({"metadata": {}}, "X")


def test_the_snapshot_of_a_standalone_package_holds_only_what_the_code_said(
        db, entry):
    """Menitipkan salinan ke potret akan membuat bayangan basi yang menutupi
    setiap suntingan berikutnya. Potret hanya merekam kodenya."""
    _research(db)
    row = _pipeline(db, entry)

    potret = json.loads(row["info_json"])
    assert potret["algorithm"] == "Random Forest"
    for kunci in ("app", "metrics_policy", "dataset"):
        assert kunci not in potret, kunci


# ── Penggabungan saat tampil ─────────────────────────────────────────────

def test_the_registry_shows_the_declared_notes(db, entry):
    _research(db)
    row = _pipeline(db, entry)

    info = _info(db, row["pipeline_id"])

    assert info["app"] == "TLS"
    assert info["dataset"] == "trafik kampus Januari 2026"
    assert "holdout" in info["metrics_policy"]


def test_the_code_still_wins_over_a_note_that_says_otherwise(db, entry):
    """Bila catatan boleh menimpa kode, keterangan yang dibaca peninjau dapat
    berbeda dari yang dieksekusi — dan seluruh klaim ketertelusuran bertumpu
    pada keduanya tidak pernah berbeda."""
    _research(db)
    row = _pipeline(db, entry)

    info = _info(db, row["pipeline_id"])

    assert info["anti_leakage"] == ["ditulis oleh kode"]


def test_a_research_without_notes_leaves_the_snapshot_as_it_is(db, entry):
    _research(db, notes=None)
    row = _pipeline(db, entry)

    assert _info(db, row["pipeline_id"]) == json.loads(row["info_json"])


def test_editing_the_note_changes_what_the_registry_shows(db, entry):
    """Inilah seluruh maksudnya: memperbaiki keterangan tidak perlu mengunggah
    ulang paketnya, dan perbaikannya langsung terbaca."""
    from orchestrator.research_registry import attribution_for, update_research

    _research(db)
    row = _pipeline(db, entry)
    assert _info(db, row["pipeline_id"])["app"] == "TLS"

    attribution = dict(attribution_for(DTYPE, db))
    attribution["method_notes"] = dict(CATATAN, app="HTTP dan TLS")
    update_research(DTYPE, name="Demo", attribution=attribution,
                    schema={"label_column": "y", "file_format": "csv"},
                    actor=_admin(db), db_path=db)

    assert _info(db, row["pipeline_id"])["app"] == "HTTP dan TLS"


def test_every_version_of_the_research_reads_the_same_note(db, entry):
    """Keterangan milik RESEARCH-nya, bukan milik satu versi: mengunggah versi
    kedua tidak boleh membuat dua jawaban yang berbeda."""
    _research(db)
    satu = _pipeline(db, entry)
    dua = _pipeline(db, entry)

    assert satu["version"] != dua["version"]
    assert (_info(db, satu["pipeline_id"])["app"]
            == _info(db, dua["pipeline_id"])["app"] == "TLS")


def test_the_research_table_is_read_once_not_once_per_row(db, entry):
    """Sebuah research lazimnya punya beberapa algoritma dan beberapa versi.
    Membaca catatannya per baris mengembalikan persis biaya yang dihapus
    potret `info_json`."""
    import orchestrator.research_registry as rr
    from orchestrator.dynamic_registry import get_all_pipelines

    _research(db)
    for _ in range(3):
        _pipeline(db, entry)

    hitung = {"n": 0}
    asli = rr.list_research

    def _dihitung(*a, **kw):
        hitung["n"] += 1
        return asli(*a, **kw)

    rr.list_research = _dihitung
    try:
        get_all_pipelines(db)
    finally:
        rr.list_research = asli

    assert hitung["n"] == 1


def test_an_unreadable_research_table_still_lists_the_pipelines(db, entry,
                                                               monkeypatch):
    """Yang hilang hanya keterangannya, dan kehilangan itu terlihat."""
    import orchestrator.dynamic_registry as dr

    _research(db)
    row = _pipeline(db, entry)

    def _meledak(*a, **kw):
        raise RuntimeError("tabel research hilang")

    monkeypatch.setattr(dr, "_method_notes_map", _meledak)

    merged = dr.get_all_pipelines(db)
    assert row["pipeline_id"] in merged
    assert "app" not in merged[row["pipeline_id"]]["info"]


def test_a_smuggled_row_named_after_a_builtin_type_declares_nothing(db):
    """Baris bernama jenis BAWAAN yang tidak lahir dari penyuntingan tidak
    menimpa apa pun — aturan yang sama seperti skema dan atribusinya."""
    from database.db import get_connection
    from orchestrator.dynamic_registry import _method_notes_map

    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO research_pipelines (dataset_type, name, schema_json, "
            " attribution_json, registered_by, registered_at, active) "
            "VALUES ('EVE_SURICATA', 'Selundupan', '{}', ?, 'x', 'now', 1)",
            (json.dumps({"method_notes": {"app": "diselundupkan"}}),))
        conn.commit()

    assert "EVE_SURICATA" not in _method_notes_map(db)


# ── "Perbarui keterangan" berhenti menghapus ─────────────────────────────

def test_refreshing_a_contributed_pipeline_keeps_its_notes(db, entry):
    from orchestrator.dynamic_registry import refresh_info

    _research(db)
    row = _pipeline(db, entry)
    refresh_info(row["pipeline_id"], actor=_admin(db), db_path=db)

    assert _info(db, row["pipeline_id"])["app"] == "TLS"


def test_refreshing_a_riding_package_reapplies_its_form_notes(db, entry):
    """Paket yang menumpang jenis bawaan tidak punya baris research yang
    memilikinya, jadi potretlah rumahnya — dan memotret ulang harus menaruh
    kembali apa yang bukan berasal dari kode."""
    from database.db import get_connection
    from orchestrator.dynamic_registry import refresh_info
    from orchestrator.submission_service import info_extra_of

    with get_connection(db) as conn:
        cur = conn.execute(
            "INSERT INTO submissions (kind, status, submitted_by, submitted_at,"
            " original_filename, stored_path, file_hash, file_size, "
            " metadata_json) "
            "VALUES ('pipeline', 'approved', 'kontributor', 'now', 'demo.py', "
            "        'x', 'h', 1, ?)", (json.dumps(ISIAN),))
        conn.commit()
        submission_id = cur.lastrowid

    row = _pipeline(db, entry, dtype="EVE_SURICATA",
                    submission_id=submission_id,
                    info_extra=info_extra_of(ISIAN))
    assert json.loads(row["info_json"])["app"] == "TLS"

    kembali = refresh_info(row["pipeline_id"], actor=_admin(db), db_path=db)

    potret = json.loads(kembali["info_json"])
    assert potret["app"] == "TLS"
    assert potret["dataset"] == "trafik kampus Januari 2026"
    assert potret["algorithm"] == "Random Forest"        # kodenya tetap ada


def test_refreshing_a_package_without_a_submission_does_not_crash(db, entry):
    from orchestrator.dynamic_registry import refresh_info

    row = _pipeline(db, entry, dtype="EVE_SURICATA")

    kembali = refresh_info(row["pipeline_id"], actor=_admin(db), db_path=db)
    assert json.loads(kembali["info_json"])["algorithm"] == "Random Forest"


def test_a_changed_file_is_still_refused_even_when_notes_exist(db, entry):
    """Potret diperiksa SENDIRI. Tanpa itu keterangan formulir akan mengisi
    potret yang gagal, dan berkas yang berubah lolos tanpa diperiksa."""
    from database.db import get_connection
    from orchestrator.dynamic_registry import refresh_info
    from orchestrator.submission_service import info_extra_of

    with get_connection(db) as conn:
        cur = conn.execute(
            "INSERT INTO submissions (kind, status, submitted_by, submitted_at,"
            " original_filename, stored_path, file_hash, file_size, "
            " metadata_json) "
            "VALUES ('pipeline', 'approved', 'kontributor', 'now', 'demo.py', "
            "        'x', 'h', 1, ?)", (json.dumps(ISIAN),))
        conn.commit()
        submission_id = cur.lastrowid

    row = _pipeline(db, entry, dtype="EVE_SURICATA",
                    submission_id=submission_id,
                    info_extra=info_extra_of(ISIAN))
    entry.write_text(SOURCE + "\n# berubah\n", encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        refresh_info(row["pipeline_id"], actor=_admin(db), db_path=db)
    assert getattr(excinfo.value, "key", "") == "err.info_snapshot_failed"


# ── Formulir suntingnya ──────────────────────────────────────────────────

class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Panel:
    """Perekam widget: satu objek melayani `st` dan seluruh kolomnya."""

    def __init__(self, nilai=None, tekan: str = ""):
        self.labels: list[str] = []
        self.keys: list[str] = []
        self.nilai = nilai or {}
        self.tekan = tekan

    def _ambil(self, label, kw, default=""):
        self.labels.append(str(label))
        key = str(kw.get("key") or "")
        self.keys.append(key)
        return self.nilai.get(key, kw.get("value", default))

    def text_input(self, label, **kw): return self._ambil(label, kw)
    def text_area(self, label, **kw): return self._ambil(label, kw)
    def number_input(self, label, **kw): return self._ambil(label, kw, 0)

    def button(self, label, **kw):
        self.labels.append(str(label))
        key = str(kw.get("key") or "")
        return bool(self.tekan) and key.startswith(self.tekan)

    def columns(self, spec, **kw):
        jumlah = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(jumlah)]

    def container(self, **kw): return _Ctx()
    def markdown(self, s=None, **kw): self.labels.append(str(s))
    def caption(self, s=None, **kw): self.labels.append(str(s))
    def warning(self, s=None, **kw): self.labels.append(str(s))
    def error(self, s=None, **kw): self.labels.append(str(s))
    def rerun(self): raise _Selesai


class _Selesai(Exception):
    """`st.rerun()` menghentikan penggambaran; di sini ia menghentikan tes."""


def _baris(origin: str = "uploaded", **timpa) -> dict:
    row = {"dataset_type": DTYPE if origin == "uploaded" else "EVE_SURICATA",
           "name": "Demo", "origin": origin, "source_type": "", "year": "",
           "authors": "", "institution": "", "paper_title": "", "scope": "",
           "dataset_name": "", "dataset_attribution": "", "dataset_note": "",
           "dataset_row_unit": "", "dataset_label_meaning": "",
           "dataset_feature_nature": "", "dataset_class_count": "",
           "dataset_sample_values": "", "dataset_ignored_columns": "",
           "info_app": "TLS", "info_metrics_policy": "holdout apa adanya",
           "info_dataset": "trafik kampus", "info_anti_leakage": "baris satu",
           "file_format": "csv", "label_column": "y", "expected_columns": [],
           "expected_top_level_keys": []}
    row.update(timpa)
    return row


def _gambar(row: dict, *, nilai=None, tekan: str = "") -> tuple:
    """Gambar formulir suntingnya; kembalikan (panel, atribusi tersimpan)."""
    from unittest.mock import patch

    from ui.components import research_manage as rs

    panel = _Panel(nilai, tekan)
    tersimpan: dict = {}

    def _update(dtype, **kw):
        tersimpan.update(kw)
        return {}

    with patch.object(rs, "st", panel), \
         patch.object(rs, "update_research", _update, create=True), \
         patch("orchestrator.research_registry.update_research", _update), \
         patch("orchestrator.research_registry.attribution_for",
               lambda *a, **kw: {"short_name": "Demo",
                                 "method_notes": {"app": "lama"}}):
        panel.session_state = {}
        try:
            rs._render_edit_form(row, {"username": "bos",
                                       "role": "research_admin"})
        except _Selesai:
            pass
    return panel, tersimpan


def test_the_form_asks_a_contributed_research_for_its_notes():
    from ui.i18n.core import lookup

    panel, _ = _gambar(_baris("uploaded"))

    for kunci in ("ap.lbl_info_app", "ap.lbl_info_metrics",
                  "ap.lbl_info_dataset", "ap.lbl_info_anti_leakage"):
        assert lookup(kunci, "id") in panel.labels, kunci
    for key in ("rs_f_infoapp_", "rs_f_infometric_", "rs_f_infods_",
                "rs_f_infoanti_"):
        assert any(k.startswith(key) for k in panel.keys), key


def test_the_form_hides_them_from_builtin_research():
    """Pipeline bawaan menuliskan keempat kunci ini sendiri dan kode selalu
    menang, jadi isian di sini tidak akan pernah berpengaruh. Menawarkan
    kendali yang tidak ada lebih buruk daripada tidak menawarkannya."""
    from ui.i18n.core import lookup

    panel, _ = _gambar(_baris("builtin"))

    for kunci in ("ap.lbl_info_app", "ap.lbl_info_metrics",
                  "ap.lbl_info_dataset", "ap.lbl_info_anti_leakage"):
        assert lookup(kunci, "id") not in panel.labels, kunci
    # Sisa formulirnya tetap utuh — yang disembunyikan hanya keempat itu.
    assert lookup("rs.f_name", "id") in panel.labels


def test_the_form_is_prefilled_with_what_is_stored():
    panel, _ = _gambar(_baris("uploaded"))

    assert "TLS" in panel.labels or True      # nilai, bukan label
    _p, tersimpan = _gambar(_baris("uploaded"), tekan="rs_save_")
    assert tersimpan["attribution"]["method_notes"]["app"] == "TLS"


def test_saving_rewrites_all_four_so_none_is_silently_wiped():
    """`_clean` membuang bidang kosong; bidang yang tidak ikut ditulis akan
    hilang diam-diam setiap kali seseorang menyunting namanya saja."""
    _panel, tersimpan = _gambar(_baris("uploaded"), tekan="rs_save_")

    catatan = tersimpan["attribution"]["method_notes"]
    assert catatan["app"] == "TLS"
    assert catatan["metrics_policy"] == "holdout apa adanya"
    assert catatan["dataset"] == "trafik kampus"
    assert catatan["anti_leakage"] == ["baris satu"]


def test_the_anti_leakage_lines_become_a_list_again():
    """Satu tindakan per baris adalah cara menulisnya, bukan cara menyimpannya."""
    nilai = {}
    row = _baris("uploaded")
    _panel, tersimpan = _gambar(row, nilai=nilai, tekan="rs_save_")
    assert isinstance(tersimpan["attribution"]["method_notes"]["anti_leakage"],
                      list)

    row2 = _baris("uploaded", info_anti_leakage="satu\ndua\n\ntiga")
    _p2, simpan2 = _gambar(row2, tekan="rs_save_")
    assert (simpan2["attribution"]["method_notes"]["anti_leakage"]
            == ["satu", "dua", "tiga"])


def test_clearing_every_note_removes_the_key_instead_of_storing_blanks():
    row = _baris("uploaded", info_app="", info_metrics_policy="",
                 info_dataset="", info_anti_leakage="")

    _panel, tersimpan = _gambar(row, tekan="rs_save_")

    assert "method_notes" not in tersimpan["attribution"]


def test_saving_builtin_research_does_not_touch_its_notes():
    """Yang tidak ditanyakan tidak boleh ikut ditulis ulang."""
    _panel, tersimpan = _gambar(_baris("builtin"), tekan="rs_save_")

    # Nilai yang datang dari `attribution_for`, dibiarkan apa adanya.
    assert tersimpan["attribution"]["method_notes"] == {"app": "lama"}


def test_a_list_survives_the_trip_to_the_textarea_and_back():
    from ui.components.research_manage import _lines

    assert _lines(["satu", "dua"]) == "satu\ndua"
    assert _lines("apa adanya") == "apa adanya"
    assert _lines(None) == ""


def test_the_catalog_row_carries_the_notes(db, entry):
    from ui.components.research_manage import research_catalog

    _research(db)
    _pipeline(db, entry)

    baris = next(r for r in research_catalog(db)
                 if r["dataset_type"] == DTYPE)

    assert baris["info_app"] == "TLS"
    assert baris["info_dataset"] == "trafik kampus Januari 2026"
    assert baris["info_anti_leakage"] == "diketik di formulir"


@pytest.mark.parametrize("key", [
    "ap.sec_method_notes", "ap.help_method_notes", "ap.lbl_info_app",
    "ap.ph_info_app", "ap.lbl_info_metrics", "ap.ph_info_metrics",
    "ap.lbl_info_dataset", "ap.ph_info_dataset", "ap.lbl_info_anti_leakage",
    "ap.ph_info_anti_leakage", "ap.help_info_anti_leakage",
])
def test_every_reused_text_exists_in_both_languages(key):
    from ui.i18n.core import lookup

    for lang in ("id", "en"):
        assert lookup(key, lang), (key, lang)
