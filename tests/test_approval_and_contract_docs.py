"""Tests for the new approval rule and the pipeline-contract documentation.

Two guarantees carry the weight here:

  * **Data and code are treated differently.** A dataset is data: once it passes
    the checks it is written straight to ``storage/datasets/`` with no waiting
    record. A pipeline is code that will be executed, so it still becomes a
    pending submission that only a Research Admin can approve. Losing that
    distinction would let unreviewed code into the platform.

  * **The contract documentation cannot go stale.** Field names shown to a
    pipeline author are read programmatically from the real dataclasses. A
    doc that names a field which does not exist produces pipelines that fail
    validation and fail at run time, so the names are compared against
    ``dataclasses.fields`` rather than typed out.
"""
import dataclasses
import io
from pathlib import Path

import pytest

from contracts.pipeline_contracts import PipelineInput, PipelineResult
from database.models import (
    KIND_DATASET, KIND_PIPELINE, ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN,
    STATUS_ACTIVE, SUBMISSION_APPROVED, SUBMISSION_PENDING, SUBMISSION_REJECTED,
)
from orchestrator.auth_service import (
    PermissionDenied, can_approve, can_upload, register_account,
)
from ui.components import instructions as ins

REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD_PASSWORD = "rahasia123"


# ── BAGIAN 1: akun aktif langsung ─────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from database.db import init_db

    path = str(tmp_path / "approval.db")
    init_db(path)
    return path


def test_registration_yields_an_active_contributor(db):
    """Tidak lagi menunggu persetujuan."""
    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)

    assert user["status"] == STATUS_ACTIVE
    assert user["role"] == ROLE_CONTRIBUTOR
    assert can_upload(user) is True
    assert can_approve(user) is False        # tetap bukan Research Admin


def test_registration_still_cannot_hand_out_research_admin(db):
    import inspect

    assert "role" not in inspect.signature(register_account).parameters
    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    assert user["role"] != ROLE_RESEARCH_ADMIN


# ── BAGIAN 1: dataset langsung, pipeline tetap ditinjau ───────────────────

class _Upload(io.BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name
        self.size = len(data)


@pytest.fixture
def storage(tmp_path, monkeypatch, db):
    import orchestrator.submission_service as svc
    import ui.components.pipeline_upload as up
    import ui.views.contribute as contrib

    datasets = tmp_path / "datasets"
    datasets.mkdir()
    dirs = {
        KIND_PIPELINE: {SUBMISSION_PENDING: tmp_path / "p" / "pending",
                        SUBMISSION_APPROVED: tmp_path / "p" / "approved",
                        SUBMISSION_REJECTED: tmp_path / "p" / "rejected"},
        KIND_DATASET: {SUBMISSION_PENDING: tmp_path / "d" / "pending",
                       SUBMISSION_APPROVED: tmp_path / "d" / "approved",
                       SUBMISSION_REJECTED: tmp_path / "d" / "rejected"},
    }
    monkeypatch.setattr(svc, "SUBMISSION_DIRS", dirs)
    monkeypatch.setattr(svc, "DATASETS_DIR", str(datasets))
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(contrib, "DATASETS_DIR", str(datasets))
    return {"db": db, "datasets": datasets, "dirs": dirs}


def test_a_dataset_is_written_straight_to_storage(storage):
    """Data, bukan kode — tidak ada record menunggu sama sekali.

    `require_upload` TIDAK dilumpuhkan di sini: akun hasil pendaftaran kini
    memang aktif, jadi penjaga izinnya dilewati secara sah.
    """
    import ui.views.contribute as contrib
    from orchestrator.submission_service import list_submissions

    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                            db_path=storage["db"])
    target = storage["datasets"] / "d.csv"
    written = contrib.save_dataset_upload(_Upload("d.csv", b"a,b\n1,2\n"),
                                          target, user=user)

    assert target.exists()                                   # berkas ada
    assert written == target.stat().st_size
    assert list_submissions(db_path=storage["db"]) == []      # NOL record menunggu


def test_a_pipeline_still_becomes_a_pending_submission(storage):
    """Kode yang akan dieksekusi tetap melewati tinjauan."""
    from orchestrator.submission_service import list_submissions, submit_pipeline

    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                            db_path=storage["db"])
    item = submit_pipeline([("p.py", "x = 1\n")], "p.py", user=user,
                           db_path=storage["db"])

    assert item["kind"] == KIND_PIPELINE
    assert item["status"] == SUBMISSION_PENDING
    waiting = list_submissions(status=SUBMISSION_PENDING, db_path=storage["db"])
    assert [s["id"] for s in waiting] == [item["id"]]


def test_uploading_without_login_is_still_refused(storage):
    """Lapis aksi tetap menolak — bukan sekadar tombol yang dimatikan."""
    import ui.views.contribute as contrib
    from orchestrator.submission_service import submit_pipeline

    with pytest.raises(PermissionDenied):
        contrib.save_dataset_upload(_Upload("d.csv", b"a\n1\n"),
                                    storage["datasets"] / "d.csv", user=None)
    with pytest.raises(PermissionDenied):
        submit_pipeline([("p.py", "x = 1\n")], "p.py", user=None,
                        db_path=storage["db"])


def test_only_a_research_admin_may_approve(storage):
    from orchestrator.submission_service import approve_submission, submit_pipeline

    contributor = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                                   db_path=storage["db"])
    item = submit_pipeline([("p.py", "x = 1\n")], "p.py", user=contributor,
                           db_path=storage["db"])

    with pytest.raises(PermissionDenied):
        approve_submission(item["id"], actor=contributor, db_path=storage["db"])


def test_the_review_queue_shows_pipelines_only():
    """Dataset tidak pernah masuk antrean lagi."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    body = src.split("def _render_review_flow()")[1].split(chr(10) + "def ")[0]

    assert 's["kind"] == KIND_PIPELINE' in body
    # Dataset lama tetap ditangani, tidak dibuang.
    assert 's["kind"] == KIND_DATASET' in body
    assert "approve_submission" in body


def test_the_ui_explains_why_the_two_differ():
    """Alasannya harus tercermin: pipeline KODE, dataset DATA."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(encoding="utf-8")
    # Kalimatnya kini datang dari kamus; yang diperiksa adalah kuncinya
    # dipakai DAN teksnya benar-benar menyatakan pembedaan itu.
    from ui.i18n.core import lookup

    assert 't("ap.help_only_pipelines_reviewed")' in src
    assert 't("ap.help_dataset_direct")' in src
    assert "kode yang dieksekusi" in lookup("ap.help_only_pipelines_reviewed", "id")
    assert "Tersimpan langsung" in lookup("ap.help_dataset_direct", "id")


# ── BAGIAN 2: dokumentasi kontrak tidak boleh basi ────────────────────────

def test_input_fields_match_the_real_dataclass():
    """Dibandingkan TERPROGRAM — dokumentasi tidak bisa menyimpang."""
    shown = [f["name"] for f in ins.pipeline_input_fields()]
    real = [f.name for f in dataclasses.fields(PipelineInput)]
    assert shown == real


def test_result_fields_match_the_real_dataclass():
    shown = [f["name"] for f in ins.pipeline_result_fields()]
    real = [f.name for f in dataclasses.fields(PipelineResult)]
    assert shown == real


def test_required_versus_optional_follows_the_dataclass_defaults():
    for cls, getter in ((PipelineInput, ins.pipeline_input_fields),
                        (PipelineResult, ins.pipeline_result_fields)):
        by_name = {f.name: f for f in dataclasses.fields(cls)}
        for shown in getter():
            field = by_name[shown["name"]]
            optional = (field.default is not dataclasses.MISSING
                        or field.default_factory is not dataclasses.MISSING)
            assert shown["required"] is not optional, shown["name"]


def test_no_invented_field_names_appear_in_the_module():
    """Nama yang TIDAK ada di kontrak tidak boleh muncul sebagai field."""
    real = {f.name for f in dataclasses.fields(PipelineInput)}
    real |= {f.name for f in dataclasses.fields(PipelineResult)}

    for invented in ("data", "dataframe", "X_train", "y_true", "metrics",
                     "f1", "precision_score", "target_column"):
        assert invented not in real                  # memang bukan field nyata
        for shown in ins.pipeline_input_fields() + ins.pipeline_result_fields():
            assert shown["name"] != invented


def test_every_shown_field_has_a_meaning():
    for shown in ins.pipeline_input_fields() + ins.pipeline_result_fields():
        assert shown["meaning"], shown["name"]


def test_the_skeleton_uses_only_real_field_names():
    code = ins.contract_skeleton()
    required = [f["name"] for f in ins.pipeline_result_fields() if f["required"]]

    for name in required:
        assert f"{name}=..." in code
    # extra_info opsional -> tidak dipaksakan ke kerangka minimal.
    assert "extra_info=" not in code
    assert "pipeline_input.df" in code
    assert "pipeline_input.label_column" in code

    import ast
    ast.parse(code)                                  # contoh harus bisa diurai


# ── BAGIAN 2: wajib vs disarankan ─────────────────────────────────────────

def test_required_info_keys_come_from_the_validator():
    from orchestrator.pipeline_validator import EXPECTED_INFO_KEYS

    assert ins.required_info_keys() == tuple(EXPECTED_INFO_KEYS)
    assert set(ins.required_info_keys()) == {
        "paper", "algorithm", "preprocessing_steps", "feature_selection",
        "fixed_params", "train_test_split"}


def test_suggested_keys_are_marked_as_not_required():
    assert set(ins.SUGGESTED_INFO_KEYS) == {
        "dataset_requirements", "target", "evaluation_metrics", "random_seed"}
    assert not set(ins.SUGGESTED_INFO_KEYS) & set(ins.required_info_keys())
    assert "bukan wajib" in ins.SUGGESTED_INFO_NOTE
    assert "pipeline bawaan" in ins.SUGGESTED_INFO_NOTE


def test_the_builtin_pipelines_really_lack_the_suggested_keys():
    """Dasar klaim di atas: kalau pipeline bawaan sudah punya, menyebutnya
    'belum ada' akan menjadi bohong."""
    from config.pipeline_registry import PIPELINE_REGISTRY

    for pid, meta in PIPELINE_REGISTRY.items():
        info = meta["class"]().get_info() or {}
        for key in ins.SUGGESTED_INFO_KEYS:
            assert key not in info, (pid, key)


def test_a_missing_key_is_only_a_warning():
    """Validator memperlakukan kunci yang hilang sebagai peringatan."""
    from orchestrator.pipeline_validator import validate_pipeline_source

    source = (
        "from pipelines.base import BasePipeline\n\n\n"
        "class P(BasePipeline):\n"
        "    def run(self, pipeline_input, progress=None):\n        return None\n\n"
        "    def get_info(self):\n        return {'paper': 'x'}\n"
    )
    report = validate_pipeline_source(source, filename="p.py")
    info_checks = [c for c in report.to_dict()["checks"]
                   if c["name"] == "get_info() mengembalikan dict"]

    assert info_checks
    assert all(c["status"] != "fail" for c in info_checks)
    assert ins.missing_info_severity() == "peringatan"


# ── BAGIAN 2: tahapan jujur soal siapa yang mengerjakan ───────────────────

def test_the_stage_list_says_who_does_what():
    owners = {name: owner for _n, name, owner, _note in ins.EXECUTION_STAGES}

    assert owners["Validasi masukan"] == ins.OWNER_PLATFORM
    assert owners["Simpan artefak"] == ins.OWNER_PLATFORM
    assert owners["Latih model"] == ins.OWNER_PIPELINE
    assert owners["Kembalikan PipelineResult"] == ins.OWNER_PIPELINE


def test_the_stage_list_is_the_full_nine_steps():
    numbers = [n for n, *_rest in ins.EXECUTION_STAGES]
    assert numbers == list(range(1, 10))


def test_the_anti_leak_steps_are_highlighted():
    assert ins.ANTI_LEAK_STAGES == (2, 3)
    assert "anti-kebocoran" in ins.ANTI_LEAK_NOTE
    names = {n: name for n, name, *_r in ins.EXECUTION_STAGES}
    assert "Pisah latih/uji" in names[2]
    assert "data latih SAJA" in names[3]


def test_the_forbidden_list_is_complete_and_framed():
    joined = " ".join(ins.FORBIDDEN_ACTIONS).lower()
    for needle in ("dataset asli", "hyperparameter terkunci", "data uji",
                   "algoritma", "seleksi fitur"):
        assert needle in joined, needle
    assert "perbandingan" in ins.FORBIDDEN_FRAME
    assert "dapat diulang" in ins.FORBIDDEN_FRAME


# ── BAGIAN 3 & 4: perilaku tidak berubah ──────────────────────────────────

def test_the_selected_algorithm_still_resolves_to_a_pipeline_id():
    src = (REPO_ROOT / "ui" / "views" / "run_experiment.py").read_text(
        encoding="utf-8")
    assert "selected = algo_to_pid.get(algorithm) if algorithm else None" in src
    assert "st.segmented_control(" in src


@pytest.mark.parametrize("pipeline_id, expected_stages, has_fs", [
    ("hikari2021.nbgc_pipeline", 3, False),
    ("hikari2021.dt_pipeline", 4, False),
    ("hikari2021.lr_pipeline", 5, True),
    ("eve_cbr.xgb", 10, True),
])
def test_the_phase_graph_follows_each_pipeline(pipeline_id, expected_stages,
                                               has_fs):
    from config.pipeline_registry import PIPELINE_REGISTRY
    from ui.components import pipeline_catalog as pc

    info = PIPELINE_REGISTRY[pipeline_id]["class"]().get_info() or {}
    stages = pc.phase_graph_stages(pipeline_id, info)
    labels = [s["label"] for s in stages]

    assert len(stages) == expected_stages
    assert ("Feature selection" in labels) is has_fs
