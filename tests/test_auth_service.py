"""Tests for orchestrator/auth_service.py + the phase-1 auth migration.

Every test runs against a throwaway SQLite file in tmp_path — the real
experiments DB is never touched. Passwords used here are fixtures, never logged.
"""
import sqlite3

import pytest

from database.db import init_db
from database.migration import apply_migrations
from database.models import ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN
from orchestrator.auth_service import (
    ADMIN_PASSWORD_ENV, ADMIN_USERNAME_ENV, AuthError, MIN_PASSWORD_LENGTH,
    authenticate, create_user, ensure_admin_seed, get_user, has_any_user,
    hash_password, list_users, verify_password,
)

GOOD_PASSWORD = "correct horse battery"


@pytest.fixture
def db(tmp_path):
    """Fresh DB with the full schema, isolated from the real one."""
    path = str(tmp_path / "auth_test.db")
    init_db(path)
    return path


# ── hashing ───────────────────────────────────────────────────────────────

def test_hash_is_salted_so_the_same_password_hashes_differently():
    a, b = hash_password(GOOD_PASSWORD), hash_password(GOOD_PASSWORD)
    assert a != b
    assert verify_password(GOOD_PASSWORD, a)
    assert verify_password(GOOD_PASSWORD, b)


def test_hash_never_contains_the_plain_password():
    hashed = hash_password(GOOD_PASSWORD)
    assert GOOD_PASSWORD not in hashed
    assert hashed.startswith("pbkdf2_sha256$")
    assert len(hashed.split("$")) == 4          # algo$iterasi$salt$digest


def test_verify_rejects_a_wrong_password():
    hashed = hash_password(GOOD_PASSWORD)
    assert verify_password("salah", hashed) is False
    assert verify_password("", hashed) is False


@pytest.mark.parametrize("garbage", ["", "bukan-hash", "a$b$c", None, 123,
                                     "md5$1$aa$bb"])
def test_verify_never_raises_on_malformed_hashes(garbage):
    assert verify_password(GOOD_PASSWORD, garbage) is False


def test_empty_password_cannot_be_hashed():
    with pytest.raises(AuthError):
        hash_password("")


# ── create_user ───────────────────────────────────────────────────────────

def test_create_user_stores_a_hash_not_the_password(db):
    create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    conn = sqlite3.connect(db)
    stored = conn.execute("SELECT password_hash FROM users WHERE username='rina'").fetchone()[0]
    conn.close()
    assert GOOD_PASSWORD not in stored
    assert verify_password(GOOD_PASSWORD, stored)


def test_create_user_result_never_exposes_the_hash(db):
    user = create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    assert "password_hash" not in user
    assert user["username"] == "rina"
    assert user["role"] == ROLE_CONTRIBUTOR
    assert user["is_active"] == 1


def test_duplicate_username_is_rejected(db):
    create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    with pytest.raises(AuthError, match="sudah dipakai"):
        create_user("rina", "another password", ROLE_CONTRIBUTOR, db)
    assert len(list_users(db)) == 1


def test_short_password_is_rejected(db):
    with pytest.raises(AuthError, match=str(MIN_PASSWORD_LENGTH)):
        create_user("rina", "a" * (MIN_PASSWORD_LENGTH - 1), ROLE_CONTRIBUTOR, db)
    assert list_users(db) == []


@pytest.mark.parametrize("bad", ["", "   "])
def test_blank_username_is_rejected(db, bad):
    with pytest.raises(AuthError):
        create_user(bad, GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)


def test_unknown_role_is_rejected(db):
    with pytest.raises(AuthError):
        create_user("rina", GOOD_PASSWORD, "superuser", db)


def test_username_is_trimmed(db):
    create_user("  rina  ", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    assert get_user("rina", db) is not None


# ── authenticate ──────────────────────────────────────────────────────────

def test_authenticate_accepts_valid_credentials(db):
    create_user("rina", GOOD_PASSWORD, ROLE_RESEARCH_ADMIN, db)
    user = authenticate("rina", GOOD_PASSWORD, db)
    assert user is not None
    assert user["role"] == ROLE_RESEARCH_ADMIN
    assert "password_hash" not in user


def test_authenticate_rejects_wrong_password(db):
    create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    assert authenticate("rina", "salah", db) is None


def test_authenticate_rejects_unknown_username(db):
    create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    assert authenticate("tidak-ada", GOOD_PASSWORD, db) is None


@pytest.mark.parametrize("sql", [
    "UPDATE users SET status = 'disabled' WHERE username = 'rina'",
    # Kolom lama saja: bila `status` dan `is_active` sempat berbeda, yang
    # menang adalah hak PALING KECIL.
    "UPDATE users SET is_active = 0 WHERE username = 'rina'",
])
def test_authenticate_rejects_an_inactive_account(db, sql):
    create_user("rina", GOOD_PASSWORD, ROLE_CONTRIBUTOR, db)
    conn = sqlite3.connect(db)
    conn.execute(sql)
    conn.commit()
    conn.close()
    assert authenticate("rina", GOOD_PASSWORD, db) is None


def test_authenticate_handles_empty_input(db):
    assert authenticate("", "", db) is None
    assert authenticate(None, None, db) is None


# ── ensure_admin_seed ─────────────────────────────────────────────────────

def test_seed_creates_the_admin_from_environment(db, monkeypatch):
    monkeypatch.setenv(ADMIN_USERNAME_ENV, "boss")
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, GOOD_PASSWORD)

    user = ensure_admin_seed(db)
    assert user is not None
    assert user["username"] == "boss"
    assert user["role"] == ROLE_RESEARCH_ADMIN
    assert authenticate("boss", GOOD_PASSWORD, db) is not None


def test_seed_is_idempotent_and_never_overwrites_the_password(db, monkeypatch):
    monkeypatch.setenv(ADMIN_USERNAME_ENV, "boss")
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, GOOD_PASSWORD)
    ensure_admin_seed(db)

    # Env berubah — akun yang sudah ada TIDAK boleh ditimpa.
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, "password lain sama sekali")
    ensure_admin_seed(db)

    assert len(list_users(db)) == 1
    assert authenticate("boss", GOOD_PASSWORD, db) is not None
    assert authenticate("boss", "password lain sama sekali", db) is None


def test_seed_without_a_password_creates_nothing(db, monkeypatch):
    """Tanpa ADMIN_PASSWORD: tidak ada admin berpassword lemah yang dibuat."""
    monkeypatch.delenv(ADMIN_PASSWORD_ENV, raising=False)
    monkeypatch.setenv(ADMIN_USERNAME_ENV, "boss")

    assert ensure_admin_seed(db) is None
    assert list_users(db) == []
    assert has_any_user(db) is False


def test_seed_with_a_short_password_creates_nothing(db, monkeypatch):
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, "abc")
    assert ensure_admin_seed(db) is None
    assert list_users(db) == []


def test_seed_defaults_the_username_to_admin(db, monkeypatch):
    monkeypatch.delenv(ADMIN_USERNAME_ENV, raising=False)
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, GOOD_PASSWORD)
    user = ensure_admin_seed(db)
    assert user["username"] == "admin"


def test_no_password_is_ever_written_to_the_log(db, monkeypatch, caplog):
    monkeypatch.setenv(ADMIN_USERNAME_ENV, "boss")
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, GOOD_PASSWORD)
    with caplog.at_level("DEBUG"):
        ensure_admin_seed(db)
        authenticate("boss", GOOD_PASSWORD, db)
        authenticate("boss", "tebakan-salah", db)
    text = caplog.text
    assert GOOD_PASSWORD not in text
    assert "tebakan-salah" not in text
    assert "pbkdf2_sha256$" not in text


# ── migration: additive, existing data untouched ──────────────────────────

def _legacy_db(tmp_path):
    """DB "lama": hanya tabel experiments versi awal + beberapa record."""
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE experiments (
            id TEXT PRIMARY KEY, dataset_type TEXT NOT NULL,
            dataset_path TEXT NOT NULL, dataset_hash TEXT NOT NULL,
            pipeline_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
            created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
            accuracy REAL, precision_score REAL, recall REAL, f1_score REAL,
            metrics_path TEXT, model_path TEXT, error_message TEXT
        )""")
    for i in range(15):
        conn.execute(
            "INSERT INTO experiments (id, dataset_type, dataset_path, dataset_hash,"
            " pipeline_id, status, created_at, accuracy, f1_score)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"exp-{i}", "HIKARI2021", "d.csv", "hash", "hikari2021.rfc_pipeline",
             "FINISHED", f"2026-01-{i + 1:02d}", 0.9 + i / 1000, 0.8 + i / 1000),
        )
    conn.commit()
    conn.close()
    return path


def test_migration_preserves_every_existing_experiment(tmp_path):
    path = _legacy_db(tmp_path)
    conn = sqlite3.connect(path)
    before_count = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    before_sum = conn.execute(
        "SELECT ROUND(SUM(accuracy + f1_score), 10) FROM experiments").fetchone()[0]
    conn.close()

    apply_migrations(path)

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == before_count == 15
    assert conn.execute(
        "SELECT ROUND(SUM(accuracy + f1_score), 10) FROM experiments").fetchone()[0] == before_sum
    conn.close()


def test_migration_adds_a_nullable_owner_column_defaulting_to_null(tmp_path):
    path = _legacy_db(tmp_path)
    apply_migrations(path)

    conn = sqlite3.connect(path)
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(experiments)")}
    assert "owner" in cols
    assert cols["owner"][3] == 0                 # notnull == 0 → nullable
    assert cols["owner"][4] is None              # tanpa default
    nulls = conn.execute("SELECT COUNT(*) FROM experiments WHERE owner IS NULL").fetchone()[0]
    assert nulls == 15                           # record lama tidak diisi sembarangan
    conn.close()


def test_migration_creates_the_users_table(tmp_path):
    path = _legacy_db(tmp_path)
    apply_migrations(path)

    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "users" in tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"id", "username", "password_hash", "role", "created_at", "is_active"} <= cols
    conn.close()


def test_migration_is_idempotent(tmp_path):
    path = _legacy_db(tmp_path)
    apply_migrations(path)
    again = apply_migrations(path)
    assert again == []                           # tidak ada yang diterapkan ulang

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 15
    conn.close()


def test_fresh_init_db_creates_both_tables(tmp_path):
    path = str(tmp_path / "fresh.db")
    init_db(path)
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"experiments", "users"} <= tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(experiments)")}
    assert "owner" in cols                       # DB baru langsung punya kolomnya
    conn.close()
