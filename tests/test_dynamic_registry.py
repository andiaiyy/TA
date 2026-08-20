"""Tests for the phase-4 dynamic registry.

The three safeguards this phase lives or dies by:
  A. the ten built-in pipelines keep coming from the STATIC registry and can
     never be shadowed by an upload;
  B. uploaded pipelines are immutable and versioned — approving the same name
     again yields v2 while v1 keeps its file and hash;
  C. every load re-verifies the recorded SHA-256, and each experiment records
     pipeline_version + pipeline_hash.

Loading executes uploaded code, so every fixture here is a tiny pipeline
written into tmp_path — never anything from the real approved area.
"""
import io
import sqlite3
from pathlib import Path

import pytest

from config.pipeline_registry import PIPELINE_REGISTRY
from database.db import create_experiment, init_db
from database.models import UPLOADED_PREFIX
from orchestrator.auth_service import PermissionDenied
from orchestrator.dynamic_registry import (
    DynamicRegistryError, build_pipeline_id, file_sha256, get_all_pipelines,
    get_pipeline_instance_merged, get_pipelines_for_dataset_merged,
    get_registered, list_registered, load_pipeline_class,
    load_registered_instance, next_version, register_pipeline,
    safe_pipeline_name, set_pipeline_active, traceability_for,
)

ADMIN = {"username": "boss", "role": "research_admin"}
CONTRIBUTOR = {"username": "rina", "role": "contributor"}
VISITOR = None

VALID_PIPELINE = '''
from pipelines.base import BasePipeline


class UploadedPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return "ran"

    def get_info(self):
        return {"paper": "Uploaded (2026)", "algorithm": "Uploaded RF"}
'''

NOT_A_PIPELINE = '''
class JustAClass:
    pass
'''

EXPLODES_ON_IMPORT = '''
raise RuntimeError("kode top-level meledak")
'''


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "dyn.db")
    init_db(path)
    return path


def _write(tmp_path, name, source) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def _register(tmp_path, db, *, name="my_pipeline", source=VALID_PIPELINE,
              entry_class="UploadedPipeline", dataset_type="HIKARI2021",
              filename=None):
    entry = _write(tmp_path, filename or f"{name}.py", source)
    return register_pipeline(name=name, dataset_type=dataset_type,
                             entry_class=entry_class, entry_file=entry,
                             registered_by="boss", db_path=db)


# ── A. built-ins are untouchable ──────────────────────────────────────────

def test_all_ten_builtin_pipelines_survive_the_merge(db):
    merged = get_all_pipelines(db_path=db)
    for pipeline_id, entry in PIPELINE_REGISTRY.items():
        assert merged[pipeline_id] is entry        # objek yang SAMA, apa adanya
    assert len(PIPELINE_REGISTRY) == 10


def test_uploaded_pipelines_use_a_separate_namespace(tmp_path, db):
    item = _register(tmp_path, db)
    assert item["pipeline_id"].startswith(UPLOADED_PREFIX)
    assert not any(pid.startswith(UPLOADED_PREFIX) for pid in PIPELINE_REGISTRY)


def test_an_upload_can_never_shadow_a_builtin_id(tmp_path, db, monkeypatch):
    """Bahkan bila sebuah baris entah bagaimana memakai ID bawaan, entri statis
    yang dipertahankan."""
    import orchestrator.dynamic_registry as dyn

    hijack = {"pipeline_id": "hikari2021.rfc_pipeline", "name": "hijack",
              "version": 1, "dataset_type": "HIKARI2021", "entry_class": "X",
              "entry_file": "x.py", "file_hash": "0" * 64, "active": 1,
              "algorithm": None, "paper": None}
    monkeypatch.setattr(dyn, "list_registered", lambda **kw: [hijack])

    merged = dyn.get_all_pipelines(db_path=db)
    assert merged["hikari2021.rfc_pipeline"] is PIPELINE_REGISTRY["hikari2021.rfc_pipeline"]


def test_builtin_instances_never_go_through_the_dynamic_loader(db):
    from pipelines.hikari2021.rfc_pipeline import HikariRFCPipeline

    instance = get_pipeline_instance_merged("hikari2021.rfc_pipeline", db_path=db)
    assert isinstance(instance, HikariRFCPipeline)


def test_registry_still_works_when_the_uploaded_table_is_unreadable(db, monkeypatch):
    """Kegagalan membaca daftar terunggah tidak boleh merusak registry."""
    import orchestrator.dynamic_registry as dyn

    def boom(**kwargs):
        raise sqlite3.OperationalError("no such table: registered_pipelines")

    monkeypatch.setattr(dyn, "list_registered", boom)
    merged = dyn.get_all_pipelines(db_path=db)
    assert set(merged) == set(PIPELINE_REGISTRY)


def test_a_single_broken_entry_does_not_break_the_listing(tmp_path, db, monkeypatch):
    import orchestrator.dynamic_registry as dyn

    good = _register(tmp_path, db)
    broken = {"pipeline_id": "uploaded.broken@v1"}          # baris tidak lengkap
    monkeypatch.setattr(dyn, "list_registered",
                        lambda **kw: [dict(good), broken])

    merged = dyn.get_all_pipelines(db_path=db)
    assert good["pipeline_id"] in merged
    assert len(merged) >= len(PIPELINE_REGISTRY) + 1


# ── B. immutable & versioned ──────────────────────────────────────────────

def test_approving_the_same_name_twice_creates_v1_and_v2(tmp_path, db):
    first = _register(tmp_path, db, filename="v1.py")
    second = _register(tmp_path, db, filename="v2.py",
                       source=VALID_PIPELINE + "\n# versi kedua\n")

    assert first["version"] == 1 and second["version"] == 2
    assert first["pipeline_id"] == "uploaded.my_pipeline@v1"
    assert second["pipeline_id"] == "uploaded.my_pipeline@v2"
    assert first["file_hash"] != second["file_hash"]
    assert {r["pipeline_id"] for r in list_registered(db_path=db)} == {
        first["pipeline_id"], second["pipeline_id"]}


def test_creating_v2_leaves_v1_file_and_hash_untouched(tmp_path, db):
    first = _register(tmp_path, db, filename="v1.py")
    before_hash = file_sha256(first["entry_file"])
    before_text = Path(first["entry_file"]).read_text(encoding="utf-8")

    _register(tmp_path, db, filename="v2.py", source=VALID_PIPELINE + "\n# beda\n")

    assert Path(first["entry_file"]).read_text(encoding="utf-8") == before_text
    assert file_sha256(first["entry_file"]) == before_hash
    assert get_registered(first["pipeline_id"], db)["file_hash"] == before_hash


def test_versions_are_per_name(tmp_path, db):
    _register(tmp_path, db, name="alpha", filename="a.py")
    beta = _register(tmp_path, db, name="beta", filename="b.py")
    assert beta["version"] == 1
    assert next_version("alpha", db) == 2


def test_pipeline_id_embeds_the_version():
    assert build_pipeline_id("rf", 3) == "uploaded.rf@v3"


@pytest.mark.parametrize("raw, expected", [
    ("Random Forest", "random_forest"), ("  rf-2  ", "rf-2"),
    ("../evil", "evil"), ("RF@#$", "rf"),
])
def test_names_are_sanitised(raw, expected):
    assert safe_pipeline_name(raw) == expected


def test_blank_name_is_refused():
    with pytest.raises(DynamicRegistryError):
        safe_pipeline_name("   ")


# ── C. hash verification on every load ────────────────────────────────────

def test_loading_a_valid_uploaded_pipeline(tmp_path, db):
    item = _register(tmp_path, db)
    instance = load_registered_instance(item["pipeline_id"], db)
    assert instance.run(None) == "ran"
    assert instance.get_info()["algorithm"] == "Uploaded RF"


def test_a_changed_file_is_refused(tmp_path, db):
    """Inti pengaman C: berkas yang berubah setelah didaftarkan ditolak."""
    item = _register(tmp_path, db)
    Path(item["entry_file"]).write_text(
        VALID_PIPELINE.replace('"ran"', '"DIUBAH DIAM-DIAM"'), encoding="utf-8")

    with pytest.raises(DynamicRegistryError, match="Hash berkas tidak cocok"):
        load_registered_instance(item["pipeline_id"], db)


def test_a_missing_file_is_refused(tmp_path, db):
    item = _register(tmp_path, db)
    Path(item["entry_file"]).unlink()
    with pytest.raises(DynamicRegistryError, match="tidak ditemukan"):
        load_registered_instance(item["pipeline_id"], db)


def test_a_class_that_is_not_a_basepipeline_is_refused(tmp_path, db):
    item = _register(tmp_path, db, source=NOT_A_PIPELINE, entry_class="JustAClass")
    with pytest.raises(DynamicRegistryError, match="bukan turunan BasePipeline"):
        load_registered_instance(item["pipeline_id"], db)


def test_a_missing_class_is_refused(tmp_path, db):
    item = _register(tmp_path, db, entry_class="TidakAda")
    with pytest.raises(DynamicRegistryError, match="tidak ada"):
        load_registered_instance(item["pipeline_id"], db)


def test_a_module_that_explodes_is_reported_not_propagated(tmp_path, db):
    item = _register(tmp_path, db, source=EXPLODES_ON_IMPORT)
    with pytest.raises(DynamicRegistryError, match="Gagal memuat"):
        load_registered_instance(item["pipeline_id"], db)


def test_loading_never_adds_the_upload_folder_to_sys_path(tmp_path, db):
    import sys

    before = list(sys.path)
    item = _register(tmp_path, db)
    load_registered_instance(item["pipeline_id"], db)
    assert sys.path == before
    assert str(tmp_path) not in sys.path


def test_load_pipeline_class_verifies_before_executing(tmp_path):
    """Hash diperiksa SEBELUM modul dieksekusi: berkas yang meledak tetapi
    hash-nya salah harus gagal karena hash, bukan karena ledakannya."""
    entry = _write(tmp_path, "boom.py", EXPLODES_ON_IMPORT)
    with pytest.raises(DynamicRegistryError, match="Hash berkas tidak cocok"):
        load_pipeline_class(entry, "X", "0" * 64)


# ── activation is approved-only and admin-only ────────────────────────────

def test_inactive_pipelines_are_not_listed_or_loadable(tmp_path, db):
    item = _register(tmp_path, db)
    set_pipeline_active(item["pipeline_id"], False, actor=ADMIN, db_path=db)

    assert item["pipeline_id"] not in get_all_pipelines(db_path=db)
    assert load_registered_instance(item["pipeline_id"], db) is None
    # Record & berkas tetap ada — eksperimen lama tetap dapat ditelusuri.
    assert get_registered(item["pipeline_id"], db)["active"] == 0
    assert Path(item["entry_file"]).exists()


def test_reactivating_brings_it_back(tmp_path, db):
    item = _register(tmp_path, db)
    set_pipeline_active(item["pipeline_id"], False, actor=ADMIN, db_path=db)
    set_pipeline_active(item["pipeline_id"], True, actor=ADMIN, db_path=db)
    assert item["pipeline_id"] in get_all_pipelines(db_path=db)


@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR])
def test_only_research_admin_can_toggle_activation(tmp_path, db, actor):
    item = _register(tmp_path, db)
    with pytest.raises(PermissionDenied):
        set_pipeline_active(item["pipeline_id"], False, actor=actor, db_path=db)
    assert get_registered(item["pipeline_id"], db)["active"] == 1


def test_toggling_an_unknown_pipeline_is_reported(db):
    with pytest.raises(DynamicRegistryError, match="tidak ditemukan"):
        set_pipeline_active("uploaded.hantu@v1", False, actor=ADMIN, db_path=db)


# ── merged listing per dataset_type ───────────────────────────────────────

def test_uploaded_pipeline_appears_for_its_dataset_type(tmp_path, db):
    item = _register(tmp_path, db, dataset_type="HIKARI2021")
    hikari = get_pipelines_for_dataset_merged("HIKARI2021", db_path=db)
    eve = get_pipelines_for_dataset_merged("EVE_SURICATA", db_path=db)

    assert item["pipeline_id"] in hikari
    assert item["pipeline_id"] not in eve
    assert len(hikari) == 6 + 1                    # 6 bawaan HIKARI + 1 terunggah
    assert len(eve) == 4                           # 4 bawaan EVE, tidak berubah


def test_listing_does_not_execute_uploaded_code(tmp_path, db):
    """Menampilkan daftar tidak boleh menjalankan kode unggahan."""
    item = _register(tmp_path, db, source=EXPLODES_ON_IMPORT)
    merged = get_all_pipelines(db_path=db)         # tidak boleh raise
    assert merged[item["pipeline_id"]]["class"] is None
    assert merged[item["pipeline_id"]]["uploaded"] is True


# ── traceability recorded on experiments ──────────────────────────────────

def test_traceability_is_null_for_builtin_pipelines(db):
    assert traceability_for("hikari2021.rfc_pipeline", db) == {
        "pipeline_version": None, "pipeline_hash": None}


def test_traceability_returns_version_and_hash_for_uploads(tmp_path, db):
    item = _register(tmp_path, db)
    trace = traceability_for(item["pipeline_id"], db)
    assert trace["pipeline_version"] == 1
    assert trace["pipeline_hash"] == item["file_hash"]


def test_experiment_records_version_and_hash(tmp_path, db):
    item = _register(tmp_path, db)
    create_experiment(
        experiment_id="e-up", dataset_type="HIKARI2021", dataset_path="d.csv",
        dataset_hash="h", pipeline_id=item["pipeline_id"],
        created_at="2026-01-01T00:00:00", db_path=db,
        **traceability_for(item["pipeline_id"], db),
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT pipeline_version, pipeline_hash FROM experiments WHERE id='e-up'"
    ).fetchone()
    conn.close()
    assert row == (1, item["file_hash"])


def test_experiment_with_a_builtin_pipeline_leaves_the_columns_null(db):
    create_experiment(
        experiment_id="e-builtin", dataset_type="HIKARI2021", dataset_path="d.csv",
        dataset_hash="h", pipeline_id="hikari2021.rfc_pipeline",
        created_at="2026-01-01T00:00:00", db_path=db,
        **traceability_for("hikari2021.rfc_pipeline", db),
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT pipeline_version, pipeline_hash FROM experiments WHERE id='e-builtin'"
    ).fetchone()
    conn.close()
    assert row == (None, None)


def test_unknown_uploaded_id_yields_no_traceability(db):
    assert traceability_for("uploaded.hantu@v9", db) == {
        "pipeline_version": None, "pipeline_hash": None}


# ── execution path refuses tampered uploads ───────────────────────────────

def test_execute_pipeline_fails_clearly_when_the_hash_mismatches(tmp_path, db, monkeypatch):
    """Worker memakai jalur ini; kegagalan harus jelas, bukan menggantung."""
    import pandas as pd

    import orchestrator.execution_service as ex

    item = _register(tmp_path, db)
    Path(item["entry_file"]).write_text(VALID_PIPELINE + "\n# diubah\n",
                                        encoding="utf-8")
    monkeypatch.setattr(ex, "get_pipeline_instance_merged",
                        lambda pid: load_registered_instance(pid, db))

    with pytest.raises(ValueError, match="tidak dapat dimuat"):
        ex.execute_pipeline(item["pipeline_id"], pd.DataFrame({"a": [1]}),
                            "HIKARI2021")
