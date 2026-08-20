"""Tests for the phase-2 permission matrix and its enforcement.

Two layers are covered:
  1. the pure predicates in orchestrator/auth_service (visitor / contributor /
     research_admin × upload / approve / manage users / view / run),
  2. the ACTION functions themselves — saving a pipeline to staging and saving
     a dataset must refuse when the caller has no right, not merely have their
     button hidden.
"""
import io
import sqlite3

import pytest

from database.db import create_experiment, init_db, list_experiments
from database.migration import apply_migrations
from database.models import (
    ALL_ROLES, ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN, normalize_role, role_label,
)
from orchestrator.auth_service import (
    AuthError, PermissionDenied, can_approve, can_manage_users,
    can_run_experiment, can_upload, can_view_experiments, create_user,
    create_user_as, is_research_admin, list_users, require_approve,
    require_manage_users, require_upload, set_user_active, user_role,
)

VISITOR = None
CONTRIBUTOR = {"username": "rina", "role": ROLE_CONTRIBUTOR}
RESEARCH_ADMIN = {"username": "boss", "role": ROLE_RESEARCH_ADMIN}
GOOD_PASSWORD = "correct horse battery"


# ── the matrix ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user, upload, approve, manage", [
    (VISITOR, False, False, False),
    (CONTRIBUTOR, True, False, False),
    (RESEARCH_ADMIN, True, True, True),
])
def test_permission_matrix(user, upload, approve, manage):
    assert can_upload(user) is upload
    assert can_approve(user) is approve
    assert can_manage_users(user) is manage


@pytest.mark.parametrize("user", [VISITOR, CONTRIBUTOR, RESEARCH_ADMIN])
def test_viewing_and_running_are_open_to_everyone(user):
    """Keputusan inti Fase 2: membaca hasil & menjalankan eksperimen bebas."""
    assert can_view_experiments(user) is True
    assert can_run_experiment(user) is True


def test_only_research_admin_is_research_admin():
    assert is_research_admin(RESEARCH_ADMIN) is True
    assert is_research_admin(CONTRIBUTOR) is False
    assert is_research_admin(VISITOR) is False


@pytest.mark.parametrize("garbage", [{}, {"role": "research_admin"}, "boss", 42,
                                     {"username": ""}])
def test_malformed_identities_are_treated_as_visitors(garbage):
    assert user_role(garbage) is None
    assert can_upload(garbage) is False
    assert can_approve(garbage) is False


def test_legacy_role_names_still_resolve():
    """Baris lama Fase 1 ('admin'/'researcher') tetap terbaca benar walau
    migrasi v5 belum berjalan."""
    assert can_approve({"username": "boss", "role": "admin"}) is True
    assert can_upload({"username": "rina", "role": "researcher"}) is True
    assert can_approve({"username": "rina", "role": "researcher"}) is False


def test_unknown_role_grants_nothing():
    """Peran rusak/tak dikenal = hak paling kecil (setara pengunjung), BUKAN
    diam-diam diberi hak kontributor."""
    weird = {"username": "x", "role": "wizard"}
    assert user_role(weird) is None
    assert can_upload(weird) is False
    assert can_approve(weird) is False
    assert can_manage_users(weird) is False
    # …tetapi membaca & menjalankan tetap terbuka untuk siapa pun.
    assert can_view_experiments(weird) is True


def test_role_labels_are_human_readable():
    assert role_label(ROLE_CONTRIBUTOR) == "Kontributor"
    assert role_label(ROLE_RESEARCH_ADMIN) == "Research Admin"
    assert role_label("admin") == "Research Admin"          # nama lama
    assert normalize_role(None) == ROLE_CONTRIBUTOR


# ── require_* guards ──────────────────────────────────────────────────────

def test_require_upload_rejects_visitors():
    with pytest.raises(PermissionDenied):
        require_upload(VISITOR)
    require_upload(CONTRIBUTOR)          # tidak raise
    require_upload(RESEARCH_ADMIN)


def test_require_approve_rejects_contributors():
    with pytest.raises(PermissionDenied):
        require_approve(CONTRIBUTOR)
    with pytest.raises(PermissionDenied):
        require_approve(VISITOR)
    require_approve(RESEARCH_ADMIN)


def test_require_manage_users_rejects_contributors():
    with pytest.raises(PermissionDenied):
        require_manage_users(CONTRIBUTOR)
    require_manage_users(RESEARCH_ADMIN)


# ── enforcement inside the ACTION functions, not just the UI ──────────────

class _FakeUpload(io.BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name
        self.size = len(data)


PIPELINE_SOURCE = "from pipelines.base import BasePipeline\n"


@pytest.mark.parametrize("user", [VISITOR, {"username": "x", "role": "wizard"}])
def test_saving_a_pipeline_to_staging_is_refused_without_rights(tmp_path, monkeypatch, user):
    import ui.components.pipeline_upload as up
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "staging")

    with pytest.raises(PermissionDenied):
        up.save_to_staging(PIPELINE_SOURCE, "p.py", user=user)
    assert not (tmp_path / "staging").exists()      # tidak ada berkas tertulis


def test_saving_a_pipeline_to_staging_works_for_a_contributor(tmp_path, monkeypatch):
    import ui.components.pipeline_upload as up
    monkeypatch.setattr(up, "STAGING_DIR", tmp_path / "staging")

    target = up.save_to_staging(PIPELINE_SOURCE, "p.py", user=CONTRIBUTOR)
    assert target.read_text(encoding="utf-8") == PIPELINE_SOURCE


def test_pipeline_staging_requires_the_user_argument_explicitly():
    """`user` keyword-only tanpa default: pemanggil tidak bisa lupa memberinya
    (lupa = TypeError, bukan diam-diam lolos)."""
    import inspect

    import ui.components.pipeline_upload as up

    param = inspect.signature(up.save_to_staging).parameters["user"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


@pytest.mark.parametrize("user", [VISITOR, {"username": "x", "role": "wizard"}])
def test_saving_a_dataset_is_refused_without_rights(tmp_path, user):
    import ui.views.contribute as contrib

    target = tmp_path / "datasets" / "d.csv"
    with pytest.raises(PermissionDenied):
        contrib.save_dataset_upload(_FakeUpload("d.csv", b"a,b\n1,2\n"), target, user=user)
    assert not target.exists()


def test_saving_a_dataset_works_for_a_contributor(tmp_path):
    import ui.views.contribute as contrib

    payload = b"a,b\n1,2\n"
    target = tmp_path / "datasets" / "d.csv"
    written = contrib.save_dataset_upload(_FakeUpload("d.csv", payload), target,
                                          user=CONTRIBUTOR)
    assert written == len(payload)
    assert target.read_bytes() == payload


def test_dataset_save_requires_the_user_argument_explicitly():
    import inspect

    import ui.views.contribute as contrib

    param = inspect.signature(contrib.save_dataset_upload).parameters["user"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty


# ── user management guards ────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "perm.db")
    init_db(path)
    create_user("boss", GOOD_PASSWORD, ROLE_RESEARCH_ADMIN, path)
    create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, path)
    return path


def test_contributor_cannot_create_accounts(db):
    with pytest.raises(PermissionDenied):
        create_user_as(CONTRIBUTOR, "baru", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    assert len(list_users(db)) == 2


def test_visitor_cannot_create_accounts(db):
    with pytest.raises(PermissionDenied):
        create_user_as(VISITOR, "baru", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)


def test_research_admin_can_create_accounts(db):
    created = create_user_as(RESEARCH_ADMIN, "baru", GOOD_PASSWORD,
                             ROLE_CONTRIBUTOR, db)
    assert created["username"] == "baru"
    assert created["role"] == ROLE_CONTRIBUTOR
    assert "password_hash" not in created


def test_contributor_cannot_toggle_accounts(db):
    with pytest.raises(PermissionDenied):
        set_user_active("rina", False, actor=CONTRIBUTOR, db_path=db)


def test_research_admin_can_deactivate_and_reactivate(db):
    off = set_user_active("rina", False, actor=RESEARCH_ADMIN, db_path=db)
    assert off["is_active"] == 0
    on = set_user_active("rina", True, actor=RESEARCH_ADMIN, db_path=db)
    assert on["is_active"] == 1


def test_research_admin_cannot_deactivate_themselves(db):
    """Cegah sistem terkunci tanpa admin aktif."""
    with pytest.raises(AuthError, match="sendiri"):
        set_user_active("boss", False, actor=RESEARCH_ADMIN, db_path=db)
    assert next(u for u in list_users(db) if u["username"] == "boss")["is_active"] == 1


def test_toggling_an_unknown_user_is_reported(db):
    with pytest.raises(AuthError, match="tidak ditemukan"):
        set_user_active("hantu", False, actor=RESEARCH_ADMIN, db_path=db)


def test_listed_users_never_expose_password_hashes(db):
    for user in list_users(db):
        assert "password_hash" not in user
        assert user["role"] in ALL_ROLES
        assert user["role_label"]


# ── ownership: recorded, never used to filter ─────────────────────────────

def _seed_experiment(db_path, exp_id, owner):
    create_experiment(
        experiment_id=exp_id, dataset_type="HIKARI2021", dataset_path="d.csv",
        dataset_hash="h", pipeline_id="hikari2021.rfc_pipeline",
        created_at="2026-01-01T00:00:00", db_path=db_path, owner=owner,
    )


def test_experiment_owner_defaults_to_null(tmp_path):
    """Dijalankan tanpa login -> owner NULL, sama seperti record lama."""
    path = str(tmp_path / "own.db")
    init_db(path)
    create_experiment(
        experiment_id="e1", dataset_type="HIKARI2021", dataset_path="d.csv",
        dataset_hash="h", pipeline_id="p", created_at="2026-01-01T00:00:00",
        db_path=path,                                   # owner tidak diberikan
    )
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT owner FROM experiments WHERE id='e1'").fetchone()[0] is None
    conn.close()


def test_experiment_owner_is_recorded_when_given(tmp_path):
    path = str(tmp_path / "own.db")
    init_db(path)
    _seed_experiment(path, "e1", "rina")
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT owner FROM experiments WHERE id='e1'").fetchone()[0] == "rina"
    conn.close()


def test_create_and_run_experiment_owner_is_optional():
    """Tanda tangan tetap kompatibel: pemanggilan lama tanpa owner harus sah."""
    import inspect

    from orchestrator.experiment_service import create_and_run_experiment

    param = inspect.signature(create_and_run_experiment).parameters["owner"]
    assert param.default is None


def test_listing_returns_every_owner_including_null(tmp_path):
    """TIDAK ADA filter kepemilikan: semua record tetap terbaca oleh siapa pun."""
    path = str(tmp_path / "own.db")
    init_db(path)
    _seed_experiment(path, "sistem-1", None)
    _seed_experiment(path, "milik-rina", "rina")
    _seed_experiment(path, "milik-boss", "boss")

    rows = list_experiments(path)
    assert len(rows) == 3
    assert {r["owner"] for r in rows} == {None, "rina", "boss"}


def test_owner_is_not_passed_into_the_computation_path():
    """Worker/pipeline tidak boleh tahu owner — murni metadata pencatatan."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for rel in ("workers/celery_worker.py", "pipelines/base.py",
                "contracts/pipeline_contracts.py"):
        assert "owner" not in (repo / rel).read_text(encoding="utf-8"), rel


# ── role migration keeps every account ────────────────────────────────────

def test_role_migration_renames_without_deleting_users(tmp_path):
    path = str(tmp_path / "legacy_roles.db")
    init_db(path)
    conn = sqlite3.connect(path)
    for name, role in (("boss", "admin"), ("rina", "researcher"), ("x", "contributor")):
        conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at, is_active)"
            " VALUES (?, 'pbkdf2_sha256$1$aa$bb', ?, '2026-01-01', 1)", (name, role))
    conn.commit()
    conn.close()

    apply_migrations(path)

    conn = sqlite3.connect(path)
    roles = dict(conn.execute("SELECT username, role FROM users"))
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3   # nol yang hilang
    conn.close()
    assert roles == {"boss": ROLE_RESEARCH_ADMIN, "rina": ROLE_CONTRIBUTOR,
                     "x": ROLE_CONTRIBUTOR}
