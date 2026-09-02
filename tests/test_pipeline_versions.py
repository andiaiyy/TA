"""Penyuntingan pipeline kontribusi — tiga pengaman yang menopang reproducibility.

**A. Tidak pernah menimpa.** Menyunting membuat versi BARU; berkas, hash, dan
baris versi sebelumnya tetap utuh, sehingga eksperimen lama tetap dapat
ditelusuri ke kode yang benar-benar dipakainya.

**B. Tidak ada jalur menyimpan kode yang gagal validasi.** Ini menutup celah
yang paling penting: mengunggah versi bersih, menunggu persetujuan, lalu
menyunting menjadi berbahaya.

**C. Pipeline bawaan tidak dapat disentuh.** Sepuluh pipeline bawaan adalah
dasar seluruh hasil penelitian dan tetap datang dari registry statis.

Memuat pipeline kontribusi berarti mengeksekusi kodenya, jadi SETIAP fixture di
sini adalah pipeline mungil yang ditulis ke ``tmp_path`` — tidak pernah sesuatu
dari area approved yang sebenarnya.
"""
import sqlite3
from pathlib import Path

import pytest

from config.pipeline_registry import PIPELINE_REGISTRY
from database.db import create_experiment, init_db
from database.models import UPLOADED_PREFIX
from orchestrator.auth_service import PermissionDenied
from orchestrator.dynamic_registry import (
    file_sha256, get_registered, list_registered, register_pipeline,
)
from orchestrator import pipeline_versions as pv

REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN = {"username": "boss", "role": "research_admin"}
CONTRIBUTOR = {"username": "rina", "role": "contributor"}
VISITOR = None

VALID = '''
from pipelines.base import BasePipeline


class UploadedPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        return "v1"

    def get_info(self):
        return {"paper": "Uploaded (2026)", "algorithm": "Uploaded RF"}
'''

VALID_EDITED = VALID.replace('return "v1"', 'return "v2"')

# Memakai modul TERLARANG — persis skenario "unggah bersih, sunting berbahaya".
MALICIOUS = '''
import subprocess

from pipelines.base import BasePipeline


class UploadedPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        subprocess.run(["rm", "-rf", "/"])
        return "pwned"

    def get_info(self):
        return {"paper": "x", "algorithm": "y"}
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Registry + area versi yang seluruhnya berada di dalam tmp_path."""
    db_path = str(tmp_path / "versions.db")
    init_db(db_path)

    versions = tmp_path / "versions"
    monkeypatch.setattr(pv, "VERSIONS_ROOT", versions)

    def _conn(path=None):
        conn = sqlite3.connect(path or db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("database.db.get_connection", _conn)

    entry = tmp_path / "approved" / "uploaded_pipeline.py"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(VALID, encoding="utf-8")

    row = register_pipeline(
        name="contoh", dataset_type="HIKARI2021",
        entry_class="UploadedPipeline", entry_file=entry,
        registered_by="boss", db_path=db_path,
    )
    return {"db": db_path, "v1": row, "entry": entry, "versions": versions}


# ── Pengaman A: menyunting membuat versi baru, versi lama utuh ────────────

def test_editing_creates_a_new_version(env):
    created = pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                                  change_note="perbaikan kecil", actor=ADMIN,
                                  db_path=env["db"])
    assert created["version"] == env["v1"]["version"] + 1
    assert created["pipeline_id"] != env["v1"]["pipeline_id"]
    assert created["pipeline_id"].startswith(UPLOADED_PREFIX)


def test_the_previous_file_and_hash_are_untouched(env):
    before_hash = env["v1"]["file_hash"]
    before_bytes = env["entry"].read_bytes()

    pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                        change_note="ubah", actor=ADMIN, db_path=env["db"])

    # Berkas versi lama: byte demi byte sama.
    assert env["entry"].read_bytes() == before_bytes
    assert file_sha256(env["entry"]) == before_hash
    # Barisnya juga masih ada, dengan hash yang sama.
    old = get_registered(env["v1"]["pipeline_id"], env["db"])
    assert old is not None
    assert old["file_hash"] == before_hash


def test_each_version_gets_its_own_file(env):
    created = pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                                  change_note="ubah", actor=ADMIN,
                                  db_path=env["db"])
    new_path = Path(created["entry_file"])
    assert new_path.is_file()
    assert new_path != env["entry"]
    assert new_path.read_text(encoding="utf-8") == VALID_EDITED
    # Hash yang tercatat memang hash berkas baru.
    assert created["file_hash"] == file_sha256(new_path)
    assert created["file_hash"] != env["v1"]["file_hash"]


def test_the_new_version_becomes_active_and_the_old_one_is_kept(env):
    created = pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                                  change_note="ubah", actor=ADMIN,
                                  db_path=env["db"])
    rows = {r["pipeline_id"]: r for r in list_registered(db_path=env["db"])}
    assert rows[created["pipeline_id"]]["active"] == 1
    # Dinonaktifkan, BUKAN dihapus — recordnya masih ada.
    assert env["v1"]["pipeline_id"] in rows
    assert rows[env["v1"]["pipeline_id"]]["active"] == 0


def test_an_experiment_on_the_old_version_stays_traceable(env):
    create_experiment(
        experiment_id="exp-lama", dataset_type="HIKARI2021",
        dataset_path="/d.csv", dataset_hash="h", created_at="2026-01-01T00:00:00",
        pipeline_id=env["v1"]["pipeline_id"], db_path=env["db"],
        pipeline_version=env["v1"]["version"],
        pipeline_hash=env["v1"]["file_hash"],
    )
    pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                        change_note="ubah", actor=ADMIN, db_path=env["db"])

    conn = sqlite3.connect(env["db"])
    row = conn.execute("SELECT pipeline_version, pipeline_hash FROM experiments "
                       "WHERE id = ?", ("exp-lama",)).fetchone()
    conn.close()
    # Versi & hash yang dicatat eksperimen masih menunjuk berkas yang ADA.
    assert row[0] == env["v1"]["version"]
    assert row[1] == file_sha256(env["entry"])


def test_the_history_records_who_changed_what_and_when(env):
    pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                        change_note="menyesuaikan preprocessing", actor=ADMIN,
                        db_path=env["db"])
    history = pv.version_history("contoh", db_path=env["db"])
    assert [r["version"] for r in history] == [2, 1]

    newest, first = history
    assert newest["edited_by"] == ADMIN["username"]
    assert newest["edited_at"]
    assert newest["change_note"] == "menyesuaikan preprocessing"
    # Versi 1 lahir dari PERSETUJUAN, bukan penyuntingan — kosong itu fakta.
    assert first["edited_by"] is None
    assert first["change_note"] is None
    assert first["registered_by"] == "boss"


def test_a_change_note_is_required(env):
    for note in ("", "   ", None):
        with pytest.raises(pv.PipelineEditError, match="[Cc]atatan perubahan"):
            pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                                change_note=note, actor=ADMIN, db_path=env["db"])


# ── Pengaman B: kode yang gagal validasi tidak dapat disimpan ─────────────

def test_a_previously_approved_pipeline_cannot_be_edited_into_something_unsafe(env):
    """Celah yang ditutup: unggah bersih -> disetujui -> sunting jadi berbahaya."""
    with pytest.raises(pv.PipelineEditError):
        pv.save_new_version(env["v1"]["pipeline_id"], MALICIOUS,
                            change_note="diam-diam", actor=ADMIN,
                            db_path=env["db"])

    # Tidak ada versi baru, dan tidak ada berkas yang ditulis.
    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]
    assert not list(env["versions"].rglob("*.py"))


@pytest.mark.parametrize("source", ["", "   ", "def broken(:\n"], ids=
                         ["kosong", "spasi", "sintaks rusak"])
def test_unusable_source_is_refused(env, source):
    with pytest.raises(pv.PipelineEditError):
        pv.save_new_version(env["v1"]["pipeline_id"], source,
                            change_note="ubah", actor=ADMIN, db_path=env["db"])
    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]


def test_the_validator_rules_themselves_are_untouched():
    """Modul ini hanya MEMANGGIL validator; aturannya tidak dilonggarkan."""
    src = (REPO_ROOT / "orchestrator" / "pipeline_versions.py").read_text(
        encoding="utf-8")
    assert "validate_pipeline_source" in src
    for tampering in ("FORBIDDEN_MODULES", "ALLOWED_MODULES", "REQUIRED_METHODS",
                      ".valid = ", "checks.remove", "checks.clear"):
        assert tampering not in src, tampering


def test_saving_is_blocked_until_the_check_passes():
    """Alasan tombol simpan nonaktif dinyatakan, bukan tombol yang diam saja."""
    assert pv.rejection_reason(None)                     # belum diperiksa
    bad = pv.validate_source(MALICIOUS, "x.py")
    assert not bad.valid
    reason = pv.rejection_reason(bad)
    assert reason and "gagal" in reason.lower()
    good = pv.validate_source(VALID, "x.py")
    assert good.valid
    assert pv.rejection_reason(good) == ""               # tidak ada penghalang


def test_the_editor_never_imports_or_runs_the_code_under_review():
    """Validasi tetap STATIS — di lapis aksi maupun di halaman."""
    import ast

    for rel in ("orchestrator/pipeline_versions.py",
                "ui/views/manage_pipelines.py"):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        called = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                  for c in ast.walk(tree) if isinstance(c, ast.Call)}
        for banned in ("exec", "eval", "compile", "__import__",
                       "spec_from_file_location", "exec_module",
                       "load_pipeline_class", "load_registered_instance",
                       "get_pipeline_instance_merged"):
            assert banned not in called, (rel, banned)


# ── Pengaman C: pipeline bawaan tidak dapat disentuh ─────────────────────

@pytest.mark.parametrize("pipeline_id", sorted(PIPELINE_REGISTRY))
def test_a_built_in_pipeline_can_never_be_edited(env, pipeline_id):
    assert not pv.is_contributed(pipeline_id)
    with pytest.raises(pv.PipelineEditError, match="bukan pipeline kontribusi"):
        pv.save_new_version(pipeline_id, VALID_EDITED, change_note="ubah",
                            actor=ADMIN, db_path=env["db"])


@pytest.mark.parametrize("pipeline_id", sorted(PIPELINE_REGISTRY))
def test_a_built_in_pipeline_source_is_not_served_for_editing(env, pipeline_id):
    with pytest.raises(pv.PipelineEditError, match="bukan pipeline kontribusi"):
        pv.read_source(pipeline_id, db_path=env["db"])


def test_the_management_page_only_ever_lists_contributed_pipelines(env):
    """Bagian "Aktif" dibangun dari registry DINAMIS, yang tidak pernah memuat
    pipeline bawaan."""
    rows = list_registered(active_only=True, db_path=env["db"])
    assert rows
    for row in rows:
        assert row["pipeline_id"].startswith(UPLOADED_PREFIX)
        assert row["pipeline_id"] not in PIPELINE_REGISTRY


def test_a_contributed_pipeline_cannot_take_a_built_in_identity(env):
    """Ruang nama terpisah — tabrakan identitas tidak mungkin terjadi."""
    from orchestrator.dynamic_registry import build_pipeline_id, safe_pipeline_name

    for pipeline_id in PIPELINE_REGISTRY:
        forged = build_pipeline_id(safe_pipeline_name(pipeline_id), 1)
        assert forged.startswith(UPLOADED_PREFIX)
        assert forged not in PIPELINE_REGISTRY


# ── Izin ditegakkan di FUNGSI ────────────────────────────────────────────

@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR],
                         ids=["pengunjung", "kontributor"])
def test_only_a_research_admin_can_save_a_new_version(env, actor):
    with pytest.raises(PermissionDenied):
        pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                            change_note="ubah", actor=actor, db_path=env["db"])
    assert [r["version"] for r in list_registered(db_path=env["db"])] == [1]


def test_permission_is_checked_before_anything_else(env):
    """Bukan sekadar menyembunyikan tombol: izin diperiksa DI DALAM fungsi,
    sebelum validasi maupun penulisan berkas."""
    import ast

    src = (REPO_ROOT / "orchestrator" / "pipeline_versions.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "save_new_version")
    calls = [getattr(c.func, "id", None) or getattr(c.func, "attr", None)
             for c in ast.walk(fn) if isinstance(c, ast.Call)]
    assert calls.index("require_approve") < calls.index("validate_source")
    assert "require_contributed" in calls


def test_deactivating_keeps_the_record_and_the_file(env):
    from orchestrator.dynamic_registry import set_pipeline_active

    path = Path(env["v1"]["entry_file"])
    set_pipeline_active(env["v1"]["pipeline_id"], False, actor=ADMIN,
                        db_path=env["db"])
    row = get_registered(env["v1"]["pipeline_id"], env["db"])
    assert row is not None and row["active"] == 0
    assert path.is_file()                       # berkasnya tidak dihapus


# ── Pemakaian & peringatan ───────────────────────────────────────────────

def test_the_experiment_count_only_covers_contributed_pipelines(env):
    create_experiment(experiment_id="e1", dataset_type="HIKARI2021",
                      dataset_path="/d.csv", dataset_hash="h",
                      created_at="2026-01-01T00:00:00",
                      pipeline_id=env["v1"]["pipeline_id"], db_path=env["db"])
    create_experiment(experiment_id="e2", dataset_type="HIKARI2021",
                      dataset_path="/d.csv", dataset_hash="h",
                      created_at="2026-01-02T00:00:00",
                      pipeline_id="hikari2021.rfc_pipeline", db_path=env["db"])

    counts = pv.experiment_counts(db_path=env["db"])
    assert counts == {env["v1"]["pipeline_id"]: 1}      # bawaan tidak ikut


def test_running_experiments_are_counted_for_the_warning(env):
    from database.db import set_running

    create_experiment(experiment_id="e1", dataset_type="HIKARI2021",
                      dataset_path="/d.csv", dataset_hash="h",
                      created_at="2026-01-01T00:00:00",
                      pipeline_id=env["v1"]["pipeline_id"], db_path=env["db"])
    assert pv.running_experiments(env["v1"]["pipeline_id"], env["db"]) == 1
    set_running("e1", started_at="2026-01-01T00:01:00", db_path=env["db"])
    assert pv.running_experiments(env["v1"]["pipeline_id"], env["db"]) == 1


def test_the_current_hash_is_recomputed_from_disk(env):
    assert pv.current_hash(env["v1"]["pipeline_id"], env["db"]) == \
        env["v1"]["file_hash"]
    env["entry"].write_text(VALID_EDITED, encoding="utf-8")
    # Berubah di disk -> hash berbeda dari yang tercatat; itulah yang membuat
    # pemuatan ditolak.
    assert pv.current_hash(env["v1"]["pipeline_id"], env["db"]) != \
        env["v1"]["file_hash"]


def test_version_files_live_outside_the_import_path(env):
    created = pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                                  change_note="ubah", actor=ADMIN,
                                  db_path=env["db"])
    import sys

    folder = str(Path(created["entry_file"]).parent)
    assert folder not in sys.path
    assert str(env["versions"]) not in sys.path
    # Dan modul produksi tidak pernah menambahkan folder unggahan ke sys.path.
    for rel in ("orchestrator/pipeline_versions.py",
                "orchestrator/dynamic_registry.py"):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "sys.path.append" not in src
        assert "sys.path.insert" not in src


def test_the_real_versions_root_is_under_storage_not_pipelines():
    """Berkas kontribusi tidak boleh mendarat di paket `pipelines/`."""
    root = Path(pv.VERSIONS_ROOT).resolve()
    assert (REPO_ROOT / "storage").resolve() in root.parents
    assert (REPO_ROOT / "pipelines").resolve() not in root.parents


# ── Alur menyeluruh: setujui -> aktif -> dijalankan -> tercatat ───────────

def test_an_approved_pipeline_is_active_and_runnable(env):
    """Menyetujui membuat pipeline langsung dapat dijalankan."""
    from orchestrator.dynamic_registry import (
        get_pipeline_instance_merged, get_pipelines_for_dataset_merged,
    )

    available = get_pipelines_for_dataset_merged("HIKARI2021", db_path=env["db"])
    assert env["v1"]["pipeline_id"] in available

    instance = get_pipeline_instance_merged(env["v1"]["pipeline_id"],
                                            db_path=env["db"])
    assert instance is not None
    assert instance.run(None) == "v1"          # kelasnya benar-benar termuat


def test_after_editing_the_new_version_is_the_one_offered(env):
    from orchestrator.dynamic_registry import (
        get_pipeline_instance_merged, get_pipelines_for_dataset_merged,
    )

    created = pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                                  change_note="ubah", actor=ADMIN,
                                  db_path=env["db"])
    available = get_pipelines_for_dataset_merged("HIKARI2021", db_path=env["db"])
    assert created["pipeline_id"] in available
    assert env["v1"]["pipeline_id"] not in available     # versi lama nonaktif

    instance = get_pipeline_instance_merged(created["pipeline_id"],
                                            db_path=env["db"])
    assert instance.run(None) == "v2"          # berkas versi BARU yang dimuat


def test_the_old_version_can_still_be_loaded_for_traceability(env):
    """Dinonaktifkan bukan berarti hilang: berkasnya masih dapat dimuat."""
    from orchestrator.dynamic_registry import load_pipeline_class

    pv.save_new_version(env["v1"]["pipeline_id"], VALID_EDITED,
                        change_note="ubah", actor=ADMIN, db_path=env["db"])
    old = get_registered(env["v1"]["pipeline_id"], env["db"])
    cls = load_pipeline_class(old["entry_file"], old["entry_class"],
                              old["file_hash"])
    assert cls().run(None) == "v1"             # kode yang BENAR-BENAR dipakai


def test_an_experiment_records_the_version_and_hash_it_used(env):
    """Ketertelusuran: eksperimen menyimpan versi & hash pipeline."""
    from orchestrator.dynamic_registry import traceability_for

    trace = traceability_for(env["v1"]["pipeline_id"], db_path=env["db"])
    assert trace["pipeline_version"] == env["v1"]["version"]
    assert trace["pipeline_hash"] == env["v1"]["file_hash"]

    create_experiment(
        experiment_id="e-trace", dataset_type="HIKARI2021",
        dataset_path="/d.csv", dataset_hash="h",
        created_at="2026-01-01T00:00:00",
        pipeline_id=env["v1"]["pipeline_id"], db_path=env["db"], **trace)

    conn = sqlite3.connect(env["db"])
    row = conn.execute("SELECT pipeline_version, pipeline_hash FROM experiments "
                       "WHERE id = ?", ("e-trace",)).fetchone()
    conn.close()
    assert row == (env["v1"]["version"], env["v1"]["file_hash"])


def test_a_built_in_pipeline_records_no_version_or_hash(env):
    """Record pipeline bawaan tetap kosong — definisinya ada di git."""
    from orchestrator.dynamic_registry import traceability_for

    for pipeline_id in PIPELINE_REGISTRY:
        trace = traceability_for(pipeline_id, db_path=env["db"])
        assert trace == {"pipeline_version": None, "pipeline_hash": None}
