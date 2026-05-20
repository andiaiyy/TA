"""Tests for migration runner."""
import pytest
from database.migration import get_current_version, apply_migrations, reset_db
from database.db import init_db, create_experiment, list_experiments


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test.db")


def test_apply_migrations_from_scratch(tmp_db):
    from database.migration import MIGRATIONS
    expected_latest = max(m["version"] for m in MIGRATIONS)
    result = apply_migrations(tmp_db)
    assert 1 in result
    assert get_current_version(tmp_db) == expected_latest


def test_apply_migrations_idempotent(tmp_db):
    apply_migrations(tmp_db)
    result = apply_migrations(tmp_db)
    assert result == []


def test_reset_db(tmp_db):
    from database.migration import MIGRATIONS
    expected_latest = max(m["version"] for m in MIGRATIONS)
    apply_migrations(tmp_db)
    create_experiment("exp-1", "C", "/d.csv", "h", "p", "2026-01-01T00:00:00Z", tmp_db)
    reset_db(tmp_db)
    assert list_experiments(tmp_db) == []
    assert get_current_version(tmp_db) == expected_latest


def test_get_current_version_empty(tmp_db):
    assert get_current_version(tmp_db) == 0
