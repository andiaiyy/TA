"""Tests for database CRUD operations."""
import pytest
from database.db import (
    init_db, create_experiment, set_running, set_finished,
    set_failed, get_experiment, list_experiments, list_experiments_by_status,
)


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


def test_init_db_creates_table(tmp_db):
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    assert any("experiments" in t[0] for t in tables)


def test_create_experiment(tmp_db):
    create_experiment("exp-1", "CICIDS2017", "/data.csv", "abc123", "pipeline.rf", "2026-01-01T00:00:00Z", tmp_db)
    exp = get_experiment("exp-1", tmp_db)
    assert exp is not None
    assert exp["status"] == "QUEUED"
    assert exp["accuracy"] is None


def test_set_running(tmp_db):
    create_experiment("exp-1", "CICIDS2017", "/data.csv", "abc", "p.rf", "2026-01-01T00:00:00Z", tmp_db)
    set_running("exp-1", "2026-01-01T00:01:00Z", tmp_db)
    exp = get_experiment("exp-1", tmp_db)
    assert exp["status"] == "RUNNING"


def test_set_finished(tmp_db):
    create_experiment("exp-1", "CICIDS2017", "/data.csv", "abc", "p.rf", "2026-01-01T00:00:00Z", tmp_db)
    set_running("exp-1", "2026-01-01T00:01:00Z", tmp_db)
    set_finished("exp-1", "2026-01-01T00:02:00Z", 0.95, 0.93, 0.91, 0.92, "metrics.json", "model.pkl", tmp_db)
    exp = get_experiment("exp-1", tmp_db)
    assert exp["status"] == "FINISHED"
    assert exp["accuracy"] == 0.95


def test_set_failed(tmp_db):
    create_experiment("exp-1", "CICIDS2017", "/data.csv", "abc", "p.rf", "2026-01-01T00:00:00Z", tmp_db)
    set_failed("exp-1", "2026-01-01T00:02:00Z", "Something broke", tmp_db)
    exp = get_experiment("exp-1", tmp_db)
    assert exp["status"] == "FAILED"
    assert exp["error_message"] == "Something broke"


def test_list_experiments_ordered(tmp_db):
    for i in range(3):
        create_experiment(f"exp-{i}", "CICIDS2017", "/d.csv", "h", "p", f"2026-01-0{i+1}T00:00:00Z", tmp_db)
    results = list_experiments(tmp_db)
    assert len(results) == 3
    assert results[0]["id"] == "exp-2"


def test_list_experiments_by_status(tmp_db):
    create_experiment("exp-1", "C", "/d.csv", "h", "p", "2026-01-01T00:00:00Z", tmp_db)
    create_experiment("exp-2", "C", "/d.csv", "h", "p", "2026-01-02T00:00:00Z", tmp_db)
    set_finished("exp-1", "2026-01-01T01:00:00Z", 0.9, 0.9, 0.9, 0.9, "m", "p", tmp_db)
    assert len(list_experiments_by_status("FINISHED", tmp_db)) == 1
    assert len(list_experiments_by_status("QUEUED", tmp_db)) == 1


def test_get_experiment_not_found(tmp_db):
    assert get_experiment("nonexistent", tmp_db) is None


def test_returns_plain_dict(tmp_db):
    create_experiment("exp-1", "C", "/d.csv", "h", "p", "2026-01-01T00:00:00Z", tmp_db)
    result = get_experiment("exp-1", tmp_db)
    assert type(result) is dict
