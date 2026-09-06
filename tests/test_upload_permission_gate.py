"""Regression tests for the upload permission leak.

Two layers, tested separately:

  * **Action layer (the one that matters).** Every function that persists
    something refuses a visitor and leaves nothing behind — no file, no record.
    These run without any Streamlit rendering, because that is exactly the
    scenario the UI cannot be trusted to prevent.

  * **Display layer.** For a visitor the upload controls are *disabled* and a
    sign-in prompt is shown, so no button ever looks usable while its action
    would be refused. The page and its requirements stay visible.

Also pinned here: viewing and running experiments stay open to everyone.
"""
import io
import sqlite3
from pathlib import Path

import pytest

from database.db import init_db, list_experiments
from database.models import (
    KIND_DATASET, KIND_PIPELINE, SUBMISSION_APPROVED, SUBMISSION_PENDING,
    SUBMISSION_REJECTED,
)
from orchestrator.auth_service import (
    PermissionDenied, can_run_experiment, can_view_experiments,
)

VISITOR = None
CONTRIBUTOR = {"username": "rina", "role": "contributor"}
ADMIN = {"username": "boss", "role": "research_admin"}
BROKEN_ROLE = {"username": "x", "role": "wizard"}

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
    """Isolated storage + DB, so a leak would be visible as a real file."""
    import orchestrator.submission_service as svc
    import ui.components.pipeline_upload as up

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
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "staging")

    db = str(tmp_path / "gate.db")
    init_db(db)
    return {"db": db, "datasets": datasets, "dirs": dirs, "tmp": tmp_path}


def _written_files(env) -> list[str]:
    """Everything that ended up on disk anywhere under the sandbox."""
    return sorted(p.name for p in env["tmp"].rglob("*")
                  if p.is_file() and p.suffix in (".csv", ".py", ".jsonl", ".json"))


# ── ACTION LAYER: a visitor changes nothing ───────────────────────────────

@pytest.mark.parametrize("user", [VISITOR, BROKEN_ROLE])
def test_submitting_a_dataset_without_rights_writes_nothing(env, user):
    from orchestrator.submission_service import list_submissions, submit_dataset

    with pytest.raises(PermissionDenied):
        submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                       user=user, db_path=env["db"])

    assert list_submissions(db_path=env["db"]) == []      # tidak ada record
    assert _written_files(env) == []                      # tidak ada berkas
    assert list(env["datasets"].iterdir()) == []


@pytest.mark.parametrize("user", [VISITOR, BROKEN_ROLE])
def test_submitting_a_pipeline_without_rights_writes_nothing(env, user):
    from orchestrator.submission_service import list_submissions, submit_pipeline

    with pytest.raises(PermissionDenied):
        submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py",
                        user=user, db_path=env["db"])

    assert list_submissions(db_path=env["db"]) == []
    assert _written_files(env) == []


@pytest.mark.parametrize("user", [VISITOR, BROKEN_ROLE])
def test_saving_a_dataset_file_without_rights_writes_nothing(env, user):
    import ui.views.contribute as contrib

    target = env["datasets"] / "d.csv"
    with pytest.raises(PermissionDenied):
        contrib.save_dataset_upload(_Upload("d.csv", DATASET_BYTES), target, user=user)
    assert not target.exists()


@pytest.mark.parametrize("user", [VISITOR, BROKEN_ROLE])
def test_staging_a_pipeline_without_rights_writes_nothing(env, user):
    import ui.components.pipeline_upload as up

    with pytest.raises(PermissionDenied):
        up.save_to_staging(PIPELINE_SOURCE, "p.py", user=user)
    assert not (env["tmp"] / "staging").exists()


def test_a_contributor_may_submit_both_kinds(env):
    from orchestrator.submission_service import list_submissions, submit_dataset, submit_pipeline

    submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                   user=CONTRIBUTOR, db_path=env["db"])
    submit_pipeline([("p.py", PIPELINE_SOURCE)], "p.py",
                    user=CONTRIBUTOR, db_path=env["db"])

    kinds = {s["kind"] for s in list_submissions(db_path=env["db"])}
    assert kinds == {KIND_DATASET, KIND_PIPELINE}


# ── ACTION LAYER: approval is Research Admin only ─────────────────────────

@pytest.fixture
def pending(env):
    from orchestrator.submission_service import submit_dataset

    return submit_dataset(_Upload("d.csv", DATASET_BYTES), "d.csv",
                          user=CONTRIBUTOR, db_path=env["db"])


@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR, BROKEN_ROLE])
def test_approving_without_rights_changes_nothing(env, pending, actor):
    from orchestrator.submission_service import approve_submission, get_submission

    with pytest.raises(PermissionDenied):
        approve_submission(pending["id"], actor=actor, db_path=env["db"])

    assert get_submission(pending["id"], env["db"])["status"] == SUBMISSION_PENDING
    assert list(env["datasets"].iterdir()) == []          # tidak dipublikasikan


@pytest.mark.parametrize("actor", [VISITOR, CONTRIBUTOR, BROKEN_ROLE])
def test_rejecting_without_rights_changes_nothing(env, pending, actor):
    from orchestrator.submission_service import get_submission, reject_submission

    with pytest.raises(PermissionDenied):
        reject_submission(pending["id"], actor=actor, note="tidak", db_path=env["db"])
    assert get_submission(pending["id"], env["db"])["status"] == SUBMISSION_PENDING


def test_a_research_admin_may_approve(env, pending):
    from orchestrator.submission_service import approve_submission

    done = approve_submission(pending["id"], actor=ADMIN, note="ok", db_path=env["db"])
    assert done["status"] == SUBMISSION_APPROVED
    assert (env["datasets"] / "d.csv").exists()


def test_every_state_changing_function_validates_the_identity_it_is_given():
    """Identitas datang sebagai argumen, tetapi perannya tetap divalidasi di
    dalam fungsi — bukan dipercaya begitu saja dari UI."""
    import inspect

    import ui.components.pipeline_upload as up
    import ui.views.contribute as contrib
    import orchestrator.submission_service as svc

    guarded = {
        svc.submit_dataset: "require_upload",
        svc.submit_pipeline: "require_upload",
        svc.approve_submission: "require_approve",
        svc.reject_submission: "require_approve",
        up.save_to_staging: "require_upload",
        contrib.save_dataset_upload: "require_upload",
    }
    for fn, guard in guarded.items():
        source = inspect.getsource(fn)
        assert guard in source, f"{fn.__name__} tidak memanggil {guard}"


# ── DISPLAY LAYER: controls disabled, never misleading ────────────────────

CONTRIB_APP = '''
import sys
sys.path.insert(0, r"{repo}")
import ui.views.contribute as c
c.render()
'''


def _run_page(tmp_path, mode, user=None):
    from streamlit.testing.v1 import AppTest

    app = tmp_path / "contrib_app.py"
    app.write_text(CONTRIB_APP.format(repo=str(Path(__file__).resolve().parents[1])),
                   encoding="utf-8")
    at = AppTest.from_file(str(app), default_timeout=300)
    at.session_state["_contrib_mode"] = mode
    if user:
        at.session_state["auth_user"] = user
    at.run()
    return at


@pytest.mark.parametrize("mode", ["dataset", "pipeline"])
def test_visitor_sees_disabled_upload_controls_and_a_sign_in_prompt(tmp_path, mode):
    at = _run_page(tmp_path, mode)

    assert at.exception is None or not at.exception
    uploaders = at.get("file_uploader")
    assert uploaders, "kontrol unggah harus tetap terlihat"
    assert all(u.proto.disabled for u in uploaders)
    # Tombol "Masuk" sudah tidak ada di halaman ini; keterangannya tetap ada
    # dan menunjuk ke pemilih mode di sidebar.
    assert not any("Masuk" == b.label for b in at.button)
    prompts = " ".join(i.value for i in at.info)
    assert "Masuk sebagai Kontributor" in prompts
    assert "pemilih mode" in prompts


@pytest.mark.parametrize("mode, must_show", [
    # Instruksi kini berupa diagram + tabel, bukan paragraf berjudul
    # "Persyaratan" — jadi yang diperiksa adalah ISI kontraknya.
    ("pipeline", ("BasePipeline", "run()", "get_info()")),
    # Halaman dataset menampilkan kontrak research yang SEDANG DIPILIH; dulu
    # seluruh research digambar berdampingan sebagai tab, sehingga `Label`
    # (HIKARI) dan `Target` (EVE) muncul bersamaan. Yang dijaga tetap sama —
    # instruksinya tidak disembunyikan dari pengunjung — dan kelengkapan
    # daftarnya diperiksa pada pemilihnya, di bawah.
    ("dataset", ("Label",)),
])
def test_visitor_still_sees_the_requirements(tmp_path, mode, must_show):
    """Halaman & instruksi TIDAK disembunyikan — hanya aksinya yang dimatikan."""
    at = _run_page(tmp_path, mode)
    text = (" ".join(m.value for m in at.markdown)
            + " ".join(c.value for c in at.caption))
    for token in must_show:
        assert token in text, token
    # Diagram alurnya pun ikut tampil bagi pengunjung.
    assert any("<svg" in m.value for m in at.markdown)


def test_a_visitor_can_reach_every_research_pipeline(tmp_path):
    """Menampilkan satu research pada satu waktu bukan menyembunyikan sisanya:
    seluruhnya tetap ditawarkan pemilih, dan pengunjung boleh menggantinya."""
    from orchestrator.research_registry import (
        all_dataset_types, short_label_for,
    )

    at = _run_page(tmp_path, "dataset")
    picker = at.selectbox(key="ins_dataset_research")

    # `options` sudah melewati `format_func`, jadi yang dibandingkan adalah
    # nama beratribusinya — dan itu memang yang dibaca pengunjung.
    assert list(picker.options) == [short_label_for(dt)
                                    for dt in all_dataset_types()]
    assert len(picker.options) >= 2
    assert not picker.proto.disabled


@pytest.mark.parametrize("mode", ["dataset", "pipeline"])
def test_contributor_gets_enabled_controls(tmp_path, mode):
    at = _run_page(tmp_path, mode, user=CONTRIBUTOR)
    assert all(not u.proto.disabled for u in at.get("file_uploader"))
    assert not any("Masuk" == b.label for b in at.button)


def test_no_button_looks_usable_while_its_action_would_be_refused(tmp_path):
    """Tombol aksi unggah harus disabled untuk pengunjung — tampilan dan izin
    tidak boleh berbeda."""
    at = _run_page(tmp_path, "pipeline")
    for button in at.button:
        if button.label in ("Unggah & Validasi", "Ajukan untuk ditinjau"):
            assert button.proto.disabled, button.label


def test_contributor_forcing_the_review_path_is_told_why(tmp_path):
    """Sudah masuk tetapi di luar peran: penolakan jelas, bukan diam-diam."""
    at = _run_page(tmp_path, "review", user=CONTRIBUTOR)
    assert any("Research Admin" in e.value for e in at.error)
    assert not any(b.label in ("Setujui", "Tolak") for b in at.button)


# ── what is open stays open ───────────────────────────────────────────────

def test_viewing_and_running_need_no_account():
    assert can_view_experiments(VISITOR) is True
    assert can_run_experiment(VISITOR) is True


def test_experiment_listing_is_not_permission_gated(env):
    from database.db import create_experiment

    create_experiment(experiment_id="e1", dataset_type="HIKARI2021",
                      dataset_path="d.csv", dataset_hash="h",
                      pipeline_id="hikari2021.rfc_pipeline",
                      created_at="2026-01-01T00:00:00", db_path=env["db"])
    rows = list_experiments(env["db"])          # tanpa identitas apa pun
    assert len(rows) == 1


def test_creating_an_experiment_requires_no_identity():
    """Menjalankan eksperimen tetap terbuka: owner opsional, tanpa penjaga izin."""
    import inspect

    from orchestrator.experiment_service import create_and_run_experiment

    source = inspect.getsource(create_and_run_experiment)
    assert "require_upload" not in source
    assert "require_approve" not in source
    assert inspect.signature(create_and_run_experiment).parameters["owner"].default is None
