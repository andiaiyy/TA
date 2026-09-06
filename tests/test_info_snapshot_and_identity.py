"""Potret `get_info()` — dan identitas research yang berhenti menggantung.

Dua cacat yang bertemu di satu tempat.

**Satu.** Keterangan sebuah pipeline kontribusi hanya hidup di dalam kodenya.
Katalog menolak memuat kode itu — menampilkan daftar tidak boleh mengeksekusi
unggahan — sehingga kartunya tampil tanpa hyperparameter, tanpa langkah
preprocessing, tanpa apa pun. Halaman riwayat justru melakukan sebaliknya: ia
memuat dan menginstansiasi modulnya untuk setiap baris, pada setiap
penggambaran ulang. Keduanya salah dengan cara yang berlawanan.

Obatnya satu: `get_info()` DIPOTRET sekali saat pendaftaran. Sesudah itu tidak
ada halaman tampilan yang perlu mengimpor kode kontribusi, dan katalog punya
sesuatu untuk ditampilkan.

**Dua.** Menghapus sebuah pengajuan tidak pernah menyentuh identitas research
yang lahir darinya. Identitas itu memegang `dataset_type` yang UNIK, jadi
mengunggah ulang nama yang sama gagal sebagai `IntegrityError` — di tangan
peninjau, saat menekan Setujui, jauh dari sebabnya. Yang masih DIPAKAI pipeline
terdaftar tetap dipertahankan: penghapusan pengajuan bukan penghapusan
pipeline.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

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
            "feature_selection": "SelectKBest",
            "fixed_params": {"n_estimators": 100},
            "train_test_split": "80/20",
            "anti_leakage": ["split sebelum scaling"],
        }
"""


@pytest.fixture
def db(tmp_path) -> str:
    from database.db import init_db

    path = str(tmp_path / "snap.db")
    init_db(path)
    return path


@pytest.fixture
def entry(tmp_path) -> Path:
    file = tmp_path / "demo_pipeline.py"
    file.write_text(SOURCE, encoding="utf-8")
    return file


def _register(db: str, entry: Path, name: str = "demo"):
    from orchestrator.dynamic_registry import register_pipeline

    return register_pipeline(name=name, dataset_type="uploaded:demo",
                             entry_class="DemoPipeline", entry_file=entry,
                             registered_by="tester", db_path=db)


# ── Kolomnya ada di KEDUA jalur pembuatan ────────────────────────────────

def test_the_column_exists_on_a_freshly_created_database(db):
    """Migrasi 28 pernah ditambahkan hanya ke daftar migrasi, tidak ke
    pernyataan CREATE — dan basis data yang baru dibuat langsung rusak."""
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute(
            "PRAGMA table_info(registered_pipelines)")}
    assert "info_json" in columns


def test_the_column_arrives_by_migration_too(tmp_path):
    from database.migration import apply_migrations
    from database.models import CREATE_REGISTERED_PIPELINES_TABLE

    path = str(tmp_path / "old.db")
    older = CREATE_REGISTERED_PIPELINES_TABLE.replace("    info_json      TEXT,\n", "")
    assert "info_json" not in older
    with sqlite3.connect(path) as conn:
        conn.execute(older)
        conn.commit()
    apply_migrations(path)

    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute(
            "PRAGMA table_info(registered_pipelines)")}
    assert "info_json" in columns


# ── Potretnya diambil, sekali, saat pendaftaran ──────────────────────────

def test_registering_captures_what_the_code_says(db, entry):
    row = _register(db, entry)

    stored = json.loads(row["info_json"])
    assert stored["algorithm"] == "Random Forest"
    assert stored["fixed_params"] == {"n_estimators": 100}


def test_a_pipeline_whose_info_cannot_be_read_still_registers(db, tmp_path):
    """Pipeline yang sah tidak boleh ditolak karena keterangannya tidak
    terbaca. Yang hilang hanya keterangannya — dan kehilangan itu terlihat."""
    broken = tmp_path / "broken_pipeline.py"
    broken.write_text(SOURCE.replace('return {', 'raise RuntimeError("x")\n        return {'),
                      encoding="utf-8")
    row = _register(db, broken, name="broken")

    assert row is not None
    assert row["info_json"] is None


def test_each_version_carries_its_own_snapshot(db, entry, tmp_path):
    """Menyunting kode melahirkan versi baru. Memotret sekali lalu memakainya
    ulang akan menyimpan keterangan versi LAMA pada versi baru."""
    _register(db, entry)
    entry.write_text(SOURCE.replace('"Random Forest"', '"Decision Tree"'),
                     encoding="utf-8")
    second = _register(db, entry)

    assert second["version"] == 2
    assert json.loads(second["info_json"])["algorithm"] == "Decision Tree"


def test_the_code_that_runs_is_the_code_that_was_hashed(db, entry):
    """Sebuah `.pyc` dianggap sah bila DETIK mtime dan UKURAN sumbernya cocok.

    Dua versi yang hanya berbeda beberapa huruf — ditulis dalam detik yang
    sama, panjang yang sama — lolos pemeriksaan itu, sehingga yang dijalankan
    adalah bytecode LAMA sementara hash yang diverifikasi adalah isi BARU.
    Persis yang dijaga pemeriksaan hash, dibatalkan oleh sebuah cache.
    """
    from orchestrator.dynamic_registry import file_sha256, load_pipeline_class

    load_pipeline_class(entry, "DemoPipeline", file_sha256(entry))
    changed = SOURCE.replace('"Random Forest"', '"Decision Tree"')
    assert len(changed) == len(SOURCE)       # ukuran sama: syarat jebakannya
    entry.write_text(changed, encoding="utf-8")

    cls = load_pipeline_class(entry, "DemoPipeline", file_sha256(entry))
    assert cls().get_info()["algorithm"] == "Decision Tree"


def test_loading_writes_no_bytecode_into_the_upload_folder(db, entry):
    """Sebelumnya platform menulis `__pycache__` ke dalam folder unggahan —
    berkas yang tidak pernah diminta siapa pun, di tempat milik kontributor."""
    from orchestrator.dynamic_registry import file_sha256, load_pipeline_class

    load_pipeline_class(entry, "DemoPipeline", file_sha256(entry))
    assert not (entry.parent / "__pycache__").exists()


def test_the_merged_registry_hands_the_snapshot_on(db, entry):
    from orchestrator.dynamic_registry import get_all_pipelines

    row = _register(db, entry)
    entry_dict = get_all_pipelines(db)[row["pipeline_id"]]

    assert entry_dict["info"]["preprocessing_steps"] == "scaling"


# ── Tampilan berhenti memuat kode kontribusi ─────────────────────────────

def test_the_history_page_answers_from_the_snapshot(db, entry, monkeypatch):
    """Sebelumnya keterangan satu baris riwayat berarti memuat dan
    menginstansiasi modul kontributor — dua pembacaan basis data dan dua
    pembukaan berkas per pipeline, pada SETIAP penggambaran ulang."""
    import orchestrator.dynamic_registry as dr
    from orchestrator.execution_service import get_pipeline_info

    row = _register(db, entry)
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    def refuse(*_a, **_k):
        raise AssertionError("kode kontribusi dimuat untuk sekadar menjelaskan")

    monkeypatch.setattr(dr, "load_pipeline_class", refuse)
    info = get_pipeline_info(row["pipeline_id"])

    assert info["algorithm"] == "Random Forest"


def test_a_row_without_a_snapshot_is_unknown_not_reloaded(db, entry,
                                                          monkeypatch):
    """Jatuh kembali ke memuat berkas akan mengembalikan biaya yang baru saja
    dihapus, justru pada baris yang paling lama."""
    import orchestrator.dynamic_registry as dr
    from database.db import get_connection
    from orchestrator.execution_service import get_pipeline_info

    row = _register(db, entry)
    with get_connection(db) as conn:
        conn.execute("UPDATE registered_pipelines SET info_json = NULL "
                     "WHERE pipeline_id = ?", (row["pipeline_id"],))
        conn.commit()
    monkeypatch.setattr("database.db.DB_PATH", db, raising=False)

    def refuse(*_a, **_k):
        raise AssertionError("berkas dimuat diam-diam")

    monkeypatch.setattr(dr, "load_pipeline_class", refuse)
    assert get_pipeline_info(row["pipeline_id"]) is None


def test_a_builtin_pipeline_is_untouched(monkeypatch):
    from orchestrator.execution_service import get_pipeline_info

    info = get_pipeline_info("hikari2021.rfc_pipeline")
    assert info and info["algorithm"]


# ── Mengambil ulang potret: SENGAJA, oleh Research Admin ─────────────────

def _admin(db: str) -> dict:
    from database.db import get_connection

    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) "
            "VALUES ('bos', 'x', 'research_admin', '2026-01-01T00:00:00')")
        conn.commit()
    return {"username": "bos", "role": "research_admin"}


def test_refreshing_fills_a_missing_snapshot(db, entry):
    from database.db import get_connection
    from orchestrator.dynamic_registry import refresh_info

    row = _register(db, entry)
    with get_connection(db) as conn:
        conn.execute("UPDATE registered_pipelines SET info_json = NULL "
                     "WHERE pipeline_id = ?", (row["pipeline_id"],))
        conn.commit()

    filled = refresh_info(row["pipeline_id"], actor=_admin(db), db_path=db)
    assert json.loads(filled["info_json"])["algorithm"] == "Random Forest"


def test_refreshing_is_not_open_to_everyone(db, entry):
    from orchestrator.dynamic_registry import refresh_info

    row = _register(db, entry)
    with pytest.raises(Exception):
        refresh_info(row["pipeline_id"], actor={"username": "x",
                                                "role": "contributor"},
                     db_path=db)


def test_refreshing_verifies_the_file_has_not_changed(db, entry):
    """Hash tetap diperiksa: berkas yang berubah ditolak SEBELUM kodenya
    dieksekusi, sama seperti jalur menjalankan."""
    from orchestrator.dynamic_registry import refresh_info

    row = _register(db, entry)
    entry.write_text(SOURCE + "\n# berubah\n", encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        refresh_info(row["pipeline_id"], actor=_admin(db), db_path=db)
    assert getattr(excinfo.value, "key", "") == "err.info_snapshot_failed"


# ── Identitas research: hilang bila yatim, bertahan bila dipakai ─────────

def _identity(db: str, submission_id: int | None = 7,
              dataset_type: str = "uploaded:demo") -> None:
    from orchestrator.research_registry import register_research

    register_research(dataset_type=dataset_type, name="Demo",
                      schema={"label_column": "label"},
                      registered_by="tester", submission_id=submission_id,
                      db_path=db)


def test_a_taken_name_is_refused_in_words_not_as_a_database_error(db):
    from orchestrator.research_registry import (
        ResearchRegistryError, register_research,
    )

    _identity(db)
    with pytest.raises(ResearchRegistryError) as excinfo:
        _identity(db)

    assert excinfo.value.key == "err.research_name_taken"
    assert not isinstance(excinfo.value, sqlite3.IntegrityError)


def test_an_unused_identity_leaves_with_its_submission(db):
    from orchestrator.submission_service import _research_in_use

    _identity(db)
    assert _research_in_use(7, db) is False


def test_an_identity_still_in_use_is_kept(db, entry):
    """Pipeline yang terdaftar memakai jenis dataset itu sebagai MILIKNYA;
    mencabutnya membuat pipeline yang masih berjalan berhenti mengenali
    datanya sendiri."""
    from orchestrator.submission_service import _research_in_use

    _identity(db)
    _register(db, entry)                     # dataset_type: uploaded:demo
    assert _research_in_use(7, db) is True


def test_the_deletion_summary_says_which_way_it_will_go(db, entry):
    from orchestrator.submission_service import deletion_summary

    _identity(db)
    summary = deletion_summary({"id": 7, "stored_path": ""}, db)
    assert summary["research"] == "uploaded:demo"
    assert summary["research_kept"] is False

    _register(db, entry)
    assert deletion_summary({"id": 7, "stored_path": ""}, db)["research_kept"] \
        is True


def test_deleting_removes_the_orphan_so_the_name_frees_up(db):
    """Inti cacatnya: mengunggah ulang nama yang sama setelah pengajuannya
    dihapus gagal, dan gagalnya di tangan orang yang tidak dapat
    memperbaikinya."""
    from database.db import get_connection
    from orchestrator.research_registry import get_research

    _identity(db)
    # Yang dilakukan `delete_submission` pada langkah identitas.
    with get_connection(db) as conn:
        conn.execute("DELETE FROM research_pipelines WHERE submission_id = ?",
                     (7,))
        conn.commit()

    assert get_research("uploaded:demo", db) is None
    _identity(db)                            # nama itu bebas lagi
    assert get_research("uploaded:demo", db) is not None


def test_the_delete_path_asks_before_it_cuts():
    """Penghapusan identitas dijaga syarat, bukan tanpa syarat."""
    source = (REPO_ROOT / "orchestrator" / "submission_service.py").read_text(
        encoding="utf-8")
    body = source.split("def delete_submission(")[1].split(chr(10) + "def ")[0]

    assert "keep_research = _research_in_use(" in body
    assert "if not keep_research:" in body
    assert "DELETE FROM research_pipelines WHERE submission_id = ?" in body


def test_the_upload_page_says_it_before_the_reviewer_finds_out():
    from ui.views.contribute import _name_taken_warning

    source = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    flow = source.split("def _render_pipeline_flow(")[1].split(
        chr(10) + "def ")[0]

    assert "_name_taken_warning(name)" in flow
    assert _name_taken_warning("") == ""      # belum diketik: bukan benturan
