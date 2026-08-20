"""Tests for self sign-up with an account that waits for approval.

The security property under test: a self-registered account is `pending`,
carries the `contributor` role no matter what was submitted, and has **zero
rights** until a Research Admin activates it — enforced in the ACTION
functions, not just in the UI.
"""
import io
import sqlite3

import pytest

from database.db import init_db
from database.migration import apply_migrations
from database.models import (
    KIND_DATASET, KIND_PIPELINE, ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN,
    STATUS_ACTIVE, STATUS_DISABLED, STATUS_PENDING, SUBMISSION_APPROVED,
    SUBMISSION_PENDING, SUBMISSION_REJECTED,
)
from orchestrator.auth_service import (
    MAX_USERNAME_LENGTH, MIN_PASSWORD_LENGTH, MIN_USERNAME_LENGTH, AuthError,
    PermissionDenied, authenticate, can_approve, can_manage_users, can_upload,
    create_user, get_user, is_account_active, list_pending_accounts, list_users,
    register_account, set_user_role, set_user_status,
)

GOOD_PASSWORD = "correct horse battery"
ADMIN = {"username": "boss", "role": ROLE_RESEARCH_ADMIN, "status": STATUS_ACTIVE}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "signup.db")
    init_db(path)
    create_user("boss", GOOD_PASSWORD, ROLE_RESEARCH_ADMIN, path)
    return path


# ── registration produces a rightless account ─────────────────────────────

def test_registration_creates_a_pending_contributor(db):
    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                            reason="mau unggah dataset TLS", db_path=db)

    assert user["status"] == STATUS_PENDING
    assert user["role"] == ROLE_CONTRIBUTOR
    assert user["reason"] == "mau unggah dataset TLS"
    assert user["requested_at"]
    assert "password_hash" not in user


def test_registration_never_accepts_a_role_from_the_caller(db):
    """Mendaftar tidak boleh menjadi jalan memperoleh Research Admin."""
    import inspect

    # Tidak ada parameter peran sama sekali pada API pendaftaran.
    assert "role" not in inspect.signature(register_account).parameters

    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    assert user["role"] == ROLE_CONTRIBUTOR


def test_a_pending_account_has_no_rights_at_all(db):
    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)

    assert is_account_active(user) is False
    assert can_upload(user) is False
    assert can_approve(user) is False
    assert can_manage_users(user) is False


def test_password_is_never_logged_during_registration(db, caplog):
    with caplog.at_level("DEBUG"):
        register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    assert GOOD_PASSWORD not in caplog.text
    assert "pbkdf2_sha256$" not in caplog.text


# ── input validation ──────────────────────────────────────────────────────

def test_duplicate_username_is_refused(db):
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    with pytest.raises(AuthError, match="sudah dipakai"):
        register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    assert len([u for u in list_users(db) if u["username"] == "rina"]) == 1


def test_duplicate_against_an_admin_created_account_is_refused(db):
    with pytest.raises(AuthError, match="sudah dipakai"):
        register_account("boss", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)


def test_short_password_is_refused(db):
    with pytest.raises(AuthError, match=str(MIN_PASSWORD_LENGTH)):
        register_account("rina", "a" * (MIN_PASSWORD_LENGTH - 1),
                         "a" * (MIN_PASSWORD_LENGTH - 1), db_path=db)
    assert get_user("rina", db) is None


def test_mismatched_confirmation_is_refused(db):
    with pytest.raises(AuthError, match="Konfirmasi"):
        register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD + "x", db_path=db)
    assert get_user("rina", db) is None


@pytest.mark.parametrize("bad, needle", [
    ("", "kosong"),
    ("ab", str(MIN_USERNAME_LENGTH)),
    ("x" * (MAX_USERNAME_LENGTH + 1), str(MAX_USERNAME_LENGTH)),
    ("rina spasi", "huruf"),
    ("rina@mail", "huruf"),
    ("../evil", "huruf"),
])
def test_invalid_usernames_are_refused_with_a_specific_message(db, bad, needle):
    with pytest.raises(AuthError, match=needle):
        register_account(bad, GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    assert list_pending_accounts(db) == []


@pytest.mark.parametrize("good", ["rina", "rina.dev", "rina_2", "rina-2"])
def test_reasonable_usernames_are_accepted(db, good):
    assert register_account(good, GOOD_PASSWORD, GOOD_PASSWORD,
                            db_path=db)["username"] == good


def test_reason_is_capped_in_length(db):
    user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                            reason="x" * 5000, db_path=db)
    assert len(user["reason"]) <= 300


# ── login behaviour per status ────────────────────────────────────────────

def test_a_pending_account_can_authenticate_but_stays_rightless(db):
    """Pilihan desain: boleh masuk supaya statusnya terlihat, hak tetap nol."""
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    user = authenticate("rina", GOOD_PASSWORD, db)

    assert user is not None
    assert user["status"] == STATUS_PENDING
    assert can_upload(user) is False


def test_a_disabled_account_cannot_authenticate(db):
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    set_user_status("rina", STATUS_DISABLED, actor=ADMIN, db_path=db)
    assert authenticate("rina", GOOD_PASSWORD, db) is None


def test_an_activated_account_can_authenticate_and_upload(db):
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    set_user_status("rina", STATUS_ACTIVE, actor=ADMIN, db_path=db)

    user = authenticate("rina", GOOD_PASSWORD, db)
    assert user["status"] == STATUS_ACTIVE
    assert can_upload(user) is True
    assert can_approve(user) is False           # tetap Kontributor


# ── ACTION LAYER: a pending account changes nothing ───────────────────────

class _Upload(io.BytesIO):
    def __init__(self, name, data):
        super().__init__(data)
        self.name = name
        self.size = len(data)


@pytest.fixture
def storage(tmp_path, monkeypatch, db):
    import orchestrator.submission_service as svc
    import ui.components.pipeline_upload as up

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
    return {"db": db, "datasets": datasets, "tmp": tmp_path}


def _files_on_disk(storage):
    return sorted(p.name for p in storage["tmp"].rglob("*")
                  if p.is_file() and p.suffix in (".csv", ".py"))


def test_a_pending_account_cannot_submit_a_dataset(storage):
    from orchestrator.submission_service import list_submissions, submit_dataset

    pending_user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                                    db_path=storage["db"])

    with pytest.raises(PermissionDenied, match="menunggu persetujuan"):
        submit_dataset(_Upload("d.csv", b"a,b\n1,2\n"), "d.csv",
                       user=pending_user, db_path=storage["db"])

    assert list_submissions(db_path=storage["db"]) == []      # nol record
    assert _files_on_disk(storage) == []                      # nol berkas
    assert list(storage["datasets"].iterdir()) == []


def test_a_pending_account_cannot_submit_a_pipeline(storage):
    from orchestrator.submission_service import list_submissions, submit_pipeline

    pending_user = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                                    db_path=storage["db"])

    with pytest.raises(PermissionDenied):
        submit_pipeline([("p.py", "x = 1\n")], "p.py", user=pending_user,
                        db_path=storage["db"])

    assert list_submissions(db_path=storage["db"]) == []
    assert _files_on_disk(storage) == []


def test_a_stale_session_claiming_active_is_still_refused(storage):
    """Sesi bisa basi: identitas mengaku aktif, tetapi DB bilang pending.
    Lapis aksi membaca ulang DB, jadi tetap ditolak."""
    from orchestrator.submission_service import list_submissions, submit_dataset

    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=storage["db"])
    stale = {"username": "rina", "role": ROLE_RESEARCH_ADMIN,
             "status": STATUS_ACTIVE}          # klaim palsu

    with pytest.raises(PermissionDenied):
        submit_dataset(_Upload("d.csv", b"a\n1\n"), "d.csv", user=stale,
                       db_path=storage["db"])
    assert list_submissions(db_path=storage["db"]) == []


def test_a_pending_account_cannot_approve(storage):
    from orchestrator.submission_service import (
        approve_submission, get_submission, submit_dataset,
    )

    contributor = register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD,
                                   db_path=storage["db"])
    set_user_status("rina", STATUS_ACTIVE, actor=ADMIN, db_path=storage["db"])
    contributor = get_user("rina", storage["db"])
    item = submit_dataset(_Upload("d.csv", b"a,b\n1,2\n"), "d.csv",
                          user=contributor, db_path=storage["db"])

    waiting = register_account("budi", GOOD_PASSWORD, GOOD_PASSWORD,
                               db_path=storage["db"])
    with pytest.raises(PermissionDenied):
        approve_submission(item["id"], actor=waiting, db_path=storage["db"])
    assert get_submission(item["id"], storage["db"])["status"] == SUBMISSION_PENDING


def test_after_activation_the_same_account_may_submit(storage):
    from orchestrator.submission_service import list_submissions, submit_dataset

    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=storage["db"])
    set_user_status("rina", STATUS_ACTIVE, actor=ADMIN, db_path=storage["db"])
    active_user = get_user("rina", storage["db"])

    submit_dataset(_Upload("d.csv", b"a,b\n1,2\n"), "d.csv",
                   user=active_user, db_path=storage["db"])
    assert len(list_submissions(db_path=storage["db"])) == 1


# ── activation is Research Admin only ─────────────────────────────────────

def test_activation_records_who_and_when(db):
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    activated = set_user_status("rina", STATUS_ACTIVE, actor=ADMIN, db_path=db)

    assert activated["status"] == STATUS_ACTIVE
    assert activated["activated_by"] == "boss"
    assert activated["activated_at"]
    assert activated["is_active"] == 1          # kolom lama ikut sinkron


@pytest.mark.parametrize("actor", [
    None,
    {"username": "rina", "role": ROLE_CONTRIBUTOR, "status": STATUS_ACTIVE},
    {"username": "budi", "role": ROLE_RESEARCH_ADMIN, "status": STATUS_PENDING},
])
def test_only_an_active_research_admin_may_activate(db, actor):
    register_account("calon", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    with pytest.raises(PermissionDenied):
        set_user_status("calon", STATUS_ACTIVE, actor=actor, db_path=db)
    assert get_user("calon", db)["status"] == STATUS_PENDING


def test_research_admin_cannot_disable_themselves(db):
    with pytest.raises(AuthError, match="sendiri"):
        set_user_status("boss", STATUS_DISABLED, actor=ADMIN, db_path=db)
    assert get_user("boss", db)["status"] == STATUS_ACTIVE


def test_role_promotion_is_admin_only_and_explicit(db):
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    set_user_status("rina", STATUS_ACTIVE, actor=ADMIN, db_path=db)
    contributor = get_user("rina", db)

    with pytest.raises(PermissionDenied):
        set_user_role("rina", ROLE_RESEARCH_ADMIN, actor=contributor, db_path=db)

    promoted = set_user_role("rina", ROLE_RESEARCH_ADMIN, actor=ADMIN, db_path=db)
    assert promoted["role"] == ROLE_RESEARCH_ADMIN


def test_pending_list_only_contains_waiting_accounts(db):
    register_account("rina", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    register_account("budi", GOOD_PASSWORD, GOOD_PASSWORD, db_path=db)
    set_user_status("rina", STATUS_ACTIVE, actor=ADMIN, db_path=db)

    waiting = [u["username"] for u in list_pending_accounts(db)]
    assert waiting == ["budi"]


# ── migration keeps existing accounts usable ──────────────────────────────

def test_migration_marks_existing_accounts_active_not_pending(tmp_path):
    """Akun lama (skema pra-status) TIDAK boleh mendadak menunggu persetujuan."""
    path = str(tmp_path / "legacy_users.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'researcher', created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1)""")
    for name, role, active in (("boss", "admin", 1), ("rina", "researcher", 1),
                               ("lama", "researcher", 0)):
        conn.execute("INSERT INTO users (username, password_hash, role, created_at,"
                     " is_active) VALUES (?, 'pbkdf2_sha256$1$aa$bb', ?, '2026-01-01', ?)",
                     (name, role, active))
    conn.commit()
    conn.close()

    apply_migrations(path)

    statuses = {u["username"]: u["status"] for u in list_users(path)}
    assert statuses["boss"] == STATUS_ACTIVE        # admin lama tetap aktif
    assert statuses["rina"] == STATUS_ACTIVE
    assert statuses["lama"] == STATUS_DISABLED      # is_active=0 -> disabled
    assert len(list_users(path)) == 3               # nol akun hilang


def test_the_seeded_research_admin_still_works(db):
    """Seed Fase 1 tetap dapat masuk dan hak-haknya utuh."""
    user = authenticate("boss", GOOD_PASSWORD, db)
    assert user is not None
    assert user["status"] == STATUS_ACTIVE
    assert can_approve(user) is True
    assert can_manage_users(user) is True


def test_admin_created_accounts_are_active_immediately(db):
    """Akun yang dibuat Research Admin tidak perlu menunggu persetujuan."""
    user = create_user("dibuatkan", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    assert user["status"] == STATUS_ACTIVE
    assert can_upload(user) is True
