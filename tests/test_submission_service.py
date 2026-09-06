"""Tests for the phase-3 approval queue (orchestrator/submission_service.py).

Covers the whole life cycle — submit → review → approve/reject — plus the two
properties that matter most:
  * a pending dataset NEVER lands in storage/datasets/ (that folder is read as
    "ready to use"), and pre-existing datasets keep working without any
    submission record;
  * approving a pipeline marks it approved and NEVER touches the registry
    (dynamic registration is phase 4).

Everything runs against tmp_path directories and a throwaway DB.
"""
import hashlib
import io
import json
from pathlib import Path

import pytest

from database.db import init_db
from database.models import (
    KIND_DATASET, KIND_PIPELINE, SUBMISSION_APPROVED, SUBMISSION_PENDING,
    SUBMISSION_REJECTED,
)
from orchestrator.auth_service import PermissionDenied
from orchestrator.submission_service import (
    SubmissionError, approve_submission, get_submission, list_submissions,
    read_submission_sources, reject_submission, submit_dataset, submit_pipeline,
)
from tests._trial_helpers import pass_trial

VISITOR = None
CONTRIBUTOR = {"username": "rina", "role": "contributor"}
ADMIN = {"username": "boss", "role": "research_admin"}

DATASET_BYTES = b"a,b,Label\n1,2,0\n3,4,1\n"
PIPELINE_SOURCE = (
    "from pipelines.base import BasePipeline\n\n\n"
    "class MyPipeline(BasePipeline):\n"
    "    def run(self, pipeline_input, progress=None):\n        return None\n\n"
    "    def get_info(self):\n        return {'paper': 'x'}\n"
)


class _Upload(io.BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name
        self.size = len(data)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated storage tree + DB. Nothing touches the real project folders."""
    import orchestrator.submission_service as svc

    datasets = tmp_path / "datasets"
    datasets.mkdir()
    dirs = {
        KIND_PIPELINE: {
            SUBMISSION_PENDING: tmp_path / "up_pipe" / "pending",
            SUBMISSION_APPROVED: tmp_path / "up_pipe" / "approved",
            SUBMISSION_REJECTED: tmp_path / "up_pipe" / "rejected",
        },
        KIND_DATASET: {
            SUBMISSION_PENDING: tmp_path / "up_data" / "pending",
            SUBMISSION_APPROVED: tmp_path / "up_data" / "approved",
            SUBMISSION_REJECTED: tmp_path / "up_data" / "rejected",
        },
    }
    monkeypatch.setattr(svc, "SUBMISSION_DIRS", dirs)
    monkeypatch.setattr(svc, "DATASETS_DIR", str(datasets))

    db = str(tmp_path / "sub.db")
    init_db(db)
    # db_path harus ikut ke setiap panggilan; bungkus supaya test ringkas.
    monkeypatch.setattr(svc, "_DEFAULT_DB_FOR_TESTS", db, raising=False)
    return {"db": db, "datasets": datasets, "dirs": dirs, "tmp": tmp_path}


# ── submitting ────────────────────────────────────────────────────────────

def test_submitting_a_dataset_creates_a_pending_record(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])

    assert item["status"] == SUBMISSION_PENDING
    assert item["kind"] == KIND_DATASET
    assert item["submitted_by"] == "rina"
    assert item["file_size"] == len(DATASET_BYTES)
    assert item["file_hash"] == hashlib.sha256(DATASET_BYTES).hexdigest()
    assert Path(item["stored_path"]).read_bytes() == DATASET_BYTES


def test_a_pending_dataset_never_lands_in_the_datasets_folder(env):
    """Inti Fase 3: folder datasets/ dibaca sebagai siap pakai."""
    submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                   user=CONTRIBUTOR, db_path=env["db"])
    assert list(env["datasets"].iterdir()) == []
    pending = env["dirs"][KIND_DATASET][SUBMISSION_PENDING]
    assert [p.name for p in pending.iterdir()] == ["d.csv"]


def test_submitting_a_pipeline_package_stores_every_file(env):
    files = [("my_pipeline.py", PIPELINE_SOURCE), ("helpers.py", "x = 1\n")]
    item = submit_pipeline(files, "my_pipeline.py", user=CONTRIBUTOR,
                           metadata={"name": "RF"}, db_path=env["db"])

    folder = Path(item["stored_path"])
    assert folder.is_dir()
    assert {p.name for p in folder.glob("*.py")} == {"my_pipeline.py", "helpers.py"}
    assert item["original_filename"] == "my_pipeline.py"
    assert item["file_hash"] == hashlib.sha256(PIPELINE_SOURCE.encode()).hexdigest()
    assert item["file_size"] == len(PIPELINE_SOURCE.encode()) + len(b"x = 1\n")
    assert {f["filename"] for f in item["metadata"]["files"]} == {
        "my_pipeline.py", "helpers.py"}
    assert item["metadata"]["name"] == "RF"


def test_submission_records_validation_summary(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"],
                          validation={"compatible_types": ["HIKARI2021"]})
    assert item["validation"]["compatible_types"] == ["HIKARI2021"]
    # Tersimpan sebagai JSON di kolomnya.
    assert json.loads(item["validation_json"])["compatible_types"] == ["HIKARI2021"]


def test_pipeline_entry_point_must_be_among_the_files(env):
    with pytest.raises(SubmissionError, match="Entry point"):
        submit_pipeline([("helpers.py", "x = 1\n")], "my_pipeline.py",
                        user=CONTRIBUTOR, db_path=env["db"])
    # Tidak meninggalkan folder paket yatim.
    pending = env["dirs"][KIND_PIPELINE][SUBMISSION_PENDING]
    assert not pending.exists() or list(pending.iterdir()) == []


# ── permissions, enforced in the FUNCTIONS ────────────────────────────────

@pytest.mark.parametrize("user", [VISITOR, {"username": "x", "role": "wizard"}])
def test_visitors_cannot_submit(env, user):
    with pytest.raises(PermissionDenied):
        submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                       user=user, db_path=env["db"])
    with pytest.raises(PermissionDenied):
        submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py",
                        user=user, db_path=env["db"])
    assert list_submissions(db_path=env["db"]) == []


def test_contributor_cannot_approve_or_reject(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    with pytest.raises(PermissionDenied):
        approve_submission(item["id"], actor=CONTRIBUTOR, db_path=env["db"])
    with pytest.raises(PermissionDenied):
        reject_submission(item["id"], actor=CONTRIBUTOR, note="tidak", db_path=env["db"])
    assert get_submission(item["id"], env["db"])["status"] == SUBMISSION_PENDING
    assert list(env["datasets"].iterdir()) == []


def test_visitor_cannot_approve(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    with pytest.raises(PermissionDenied):
        approve_submission(item["id"], actor=VISITOR, db_path=env["db"])


# ── approving ─────────────────────────────────────────────────────────────

def test_approving_a_dataset_makes_it_available(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    done = approve_submission(item["id"], actor=ADMIN, note="ok", db_path=env["db"])

    assert done["status"] == SUBMISSION_APPROVED
    assert done["reviewed_by"] == "boss"
    assert done["reviewed_at"]
    assert done["review_note"] == "ok"
    # Berkas pindah ke folder dataset siap pakai…
    assert (env["datasets"] / "d.csv").read_bytes() == DATASET_BYTES
    # …dan tidak tertinggal di penampungan.
    assert list(env["dirs"][KIND_DATASET][SUBMISSION_PENDING].iterdir()) == []


def test_approving_a_dataset_refuses_to_overwrite(env):
    (env["datasets"] / "d.csv").write_bytes(b"data lama yang tidak boleh hilang\n")
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])

    with pytest.raises(SubmissionError, match="sudah ada"):
        approve_submission(item["id"], actor=ADMIN, db_path=env["db"])

    assert (env["datasets"] / "d.csv").read_bytes().startswith(b"data lama")
    assert get_submission(item["id"], env["db"])["status"] == SUBMISSION_PENDING


def test_approving_a_pipeline_moves_it_without_touching_the_static_registry(env):
    """Sejak Fase 4 persetujuan MENDAFTARKAN pipeline ke registry dinamis —
    tetapi `config/pipeline_registry.py` yang statis tetap tidak tersentuh."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    before = dict(PIPELINE_REGISTRY)
    item = submit_pipeline([("my_pipeline.py", PIPELINE_SOURCE)], "my_pipeline.py",
                           user=CONTRIBUTOR, db_path=env["db"],
                           metadata={"name": "my_pipeline",
                                     "entry_class": "MyPipeline"})
    pass_trial(item["id"], env["db"])     # persetujuan bergerbang uji coba
    done = approve_submission(item["id"], actor=ADMIN, dataset_type="HIKARI2021",
                              db_path=env["db"])

    assert done["status"] == SUBMISSION_APPROVED
    moved = Path(done["stored_path"])
    assert moved.parent == env["dirs"][KIND_PIPELINE][SUBMISSION_APPROVED]
    assert (moved / "my_pipeline.py").read_text(encoding="utf-8") == PIPELINE_SOURCE
    # Registry STATIS tidak berubah sama sekali…
    assert dict(PIPELINE_REGISTRY) == before
    assert not any(pid.startswith("uploaded.") for pid in PIPELINE_REGISTRY)
    # …pipeline-nya hidup di tabel registry dinamis dengan namespace terpisah.
    from orchestrator.dynamic_registry import list_registered
    registered = list_registered(db_path=env["db"])
    assert [r["pipeline_id"] for r in registered] == ["uploaded.my_pipeline@v1"]
    assert registered[0]["dataset_type"] == "HIKARI2021"


def test_approving_a_pipeline_without_a_dataset_type_is_refused(env):
    """Tanpa dataset target, pipeline tidak tahu harus muncul di mana —
    persetujuan ditolak dengan pesan jelas dan berkas tidak dipindah."""
    item = submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py",
                           user=CONTRIBUTOR, db_path=env["db"],
                           metadata={"entry_class": "MyPipeline"})
    pass_trial(item["id"], env["db"])
    with pytest.raises(SubmissionError, match="dataset_type"):
        approve_submission(item["id"], actor=ADMIN, db_path=env["db"])

    assert get_submission(item["id"], env["db"])["status"] == SUBMISSION_PENDING
    assert Path(item["stored_path"]).exists()          # masih di pending


def test_approving_the_same_pipeline_name_twice_creates_two_versions(env):
    """Immutability Fase 4: v1 tetap utuh saat v2 dibuat."""
    from orchestrator.dynamic_registry import list_registered

    meta = {"name": "rf_baru", "entry_class": "MyPipeline"}
    first = submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py", user=CONTRIBUTOR,
                            db_path=env["db"], metadata=meta)
    pass_trial(first["id"], env["db"])
    approve_submission(first["id"], actor=ADMIN, dataset_type="HIKARI2021",
                       db_path=env["db"])

    second_source = PIPELINE_SOURCE + "\n# revisi\n"
    second = submit_pipeline([("p.py", second_source)], "p.py", user=CONTRIBUTOR,
                             db_path=env["db"], metadata=meta)
    pass_trial(second["id"], env["db"])
    approve_submission(second["id"], actor=ADMIN, dataset_type="HIKARI2021",
                       db_path=env["db"])

    rows = {r["pipeline_id"]: r for r in list_registered(db_path=env["db"])}
    assert set(rows) == {"uploaded.rf_baru@v1", "uploaded.rf_baru@v2"}
    v1, v2 = rows["uploaded.rf_baru@v1"], rows["uploaded.rf_baru@v2"]
    assert v1["file_hash"] != v2["file_hash"]
    # Berkas v1 tidak tersentuh oleh pendaftaran v2.
    assert Path(v1["entry_file"]).read_text(encoding="utf-8") == PIPELINE_SOURCE
    assert Path(v2["entry_file"]).read_text(encoding="utf-8") == second_source


def test_an_already_reviewed_submission_cannot_be_reviewed_again(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    approve_submission(item["id"], actor=ADMIN, db_path=env["db"])
    with pytest.raises(SubmissionError, match="sudah berstatus"):
        approve_submission(item["id"], actor=ADMIN, db_path=env["db"])


# ── rejecting ─────────────────────────────────────────────────────────────

def test_rejecting_requires_a_note(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    for blank in ("", "   ", None):
        with pytest.raises(SubmissionError, match="wajib"):
            reject_submission(item["id"], actor=ADMIN, note=blank, db_path=env["db"])
    assert get_submission(item["id"], env["db"])["status"] == SUBMISSION_PENDING


def test_rejecting_records_the_reason_and_keeps_the_file(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    done = reject_submission(item["id"], actor=ADMIN, note="  kolom label kurang  ",
                             db_path=env["db"])

    assert done["status"] == SUBMISSION_REJECTED
    assert done["reviewed_by"] == "boss"
    assert done["review_note"] == "kolom label kurang"
    # Berkas disimpan (bukan dihapus diam-diam) agar dapat ditinjau ulang.
    assert Path(done["stored_path"]).exists()
    assert Path(done["stored_path"]).parent == env["dirs"][KIND_DATASET][SUBMISSION_REJECTED]
    assert list(env["datasets"].iterdir()) == []


# ── file-name safety ──────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["../evil.csv", "..\\evil.csv", "/etc/passwd.csv",
                                 "sub/dir/d.csv", "evil.exe", "", "..",
                                 "spasi nama.csv"])
def test_unsafe_dataset_names_are_refused(env, bad):
    with pytest.raises(SubmissionError):
        submit_dataset(_Upload(bad, DATASET_BYTES), bad, user=CONTRIBUTOR,
                       db_path=env["db"])
    assert list_submissions(db_path=env["db"]) == []


@pytest.mark.parametrize("bad", ["../evil.py", "sub/dir/p.py", "p.txt"])
def test_unsafe_pipeline_names_are_refused(env, bad):
    with pytest.raises(SubmissionError):
        submit_pipeline([(bad, PIPELINE_SOURCE)], bad, user=CONTRIBUTOR,
                        db_path=env["db"])


def test_two_submissions_with_the_same_name_do_not_overwrite(env):
    a = submit_dataset(_Upload("d.csv", b"pertama\n"), "d.csv",
                       user=CONTRIBUTOR, db_path=env["db"])
    b = submit_dataset(_Upload("d.csv", b"kedua\n"), "d.csv",
                       user=CONTRIBUTOR, db_path=env["db"])
    assert a["stored_path"] != b["stored_path"]
    assert Path(a["stored_path"]).read_bytes() == b"pertama\n"
    assert Path(b["stored_path"]).read_bytes() == b"kedua\n"


# ── listing & reading ─────────────────────────────────────────────────────

def test_listing_filters_by_status_kind_and_submitter(env):
    submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                   user=CONTRIBUTOR, db_path=env["db"])
    submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py", user=ADMIN, db_path=env["db"])

    assert len(list_submissions(db_path=env["db"])) == 2
    assert len(list_submissions(kind=KIND_DATASET, db_path=env["db"])) == 1
    assert len(list_submissions(submitted_by="rina", db_path=env["db"])) == 1
    assert len(list_submissions(status=SUBMISSION_PENDING, db_path=env["db"])) == 2
    assert len(list_submissions(status=SUBMISSION_APPROVED, db_path=env["db"])) == 0


def test_sources_are_read_as_text_only(env):
    item = submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py",
                           user=CONTRIBUTOR, db_path=env["db"])
    sources = read_submission_sources(get_submission(item["id"], env["db"]))
    assert sources == [("p.py", PIPELINE_SOURCE)]


def test_reading_sources_of_a_dataset_returns_nothing(env):
    item = submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])
    assert read_submission_sources(get_submission(item["id"], env["db"])) == []


def test_submission_service_never_imports_or_executes_uploads():
    """Statis: modul ini hanya memindahkan & membaca teks."""
    import ast

    import orchestrator.submission_service as svc

    tree = ast.parse(Path(svc.__file__).read_text(encoding="utf-8"))
    called, imported = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                called.add(fn.id)
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                called.add(f"{fn.value.id}.{fn.attr}")
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not (called & {"exec", "eval", "compile", "__import__"})
    assert not (imported & {"importlib", "runpy", "subprocess"})


# ── pre-existing datasets keep working ────────────────────────────────────

def test_existing_datasets_need_no_submission_record(env, monkeypatch):
    """Dataset lama (BAB III) tidak melalui antrean dan harus tetap terpilih."""
    import ui.views.run_experiment as rx

    (env["datasets"] / "ALLFLOWMETER_HIKARI2021.csv").write_bytes(b"x")
    (env["datasets"] / "eve_sample.jsonl").write_bytes(b"{}")
    monkeypatch.setattr(rx, "DATASETS_DIR", str(env["datasets"]))

    from database.models import is_uploaded_research

    options = rx._all_dataset_options()
    builtin = {Path(p).name for p, dtype in options
               if not is_uploaded_research(dtype)}
    assert builtin == {"ALLFLOWMETER_HIKARI2021.csv", "eve_sample.jsonl"}
    # Selebihnya — bila ada — adalah dataset MILIK research pipeline
    # kontribusi. Dataset seperti itu memang tidak pernah tinggal di
    # `storage/datasets/`, jadi ia tidak dapat dituntut ada di folder ini;
    # yang dijaga di sini adalah dataset bawaan tetap terpilih tanpa antrean.
    for path, dtype in options:
        if Path(path).name not in builtin:
            assert is_uploaded_research(dtype), (path, dtype)
    # …dan tidak ada satu pun record submissions untuk keduanya.
    assert list_submissions(db_path=env["db"]) == []
