"""Tests for experiment history pagination."""
import pytest
from unittest.mock import patch
from database.db import init_db, create_experiment
from orchestrator.result_service import list_experiments_page


@pytest.fixture
def db_with_experiments(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    for i in range(25):
        create_experiment(
            f"exp-{i:03d}", "CICIDS2017", "/d.csv", f"hash{i}", "p.rf",
            f"2026-01-{i+1:02d}T00:00:00Z", db_path,
        )
    return db_path


def test_pagination_first_page(db_with_experiments):
    with patch("database.db.DB_PATH", db_with_experiments):
        rows, total = list_experiments_page(limit=10, offset=0)
    assert total == 25
    assert len(rows) == 10


def test_pagination_last_page(db_with_experiments):
    with patch("database.db.DB_PATH", db_with_experiments):
        rows, total = list_experiments_page(limit=10, offset=20)
    assert total == 25
    assert len(rows) == 5


def test_pagination_ordered_desc(db_with_experiments):
    with patch("database.db.DB_PATH", db_with_experiments):
        rows, _ = list_experiments_page(limit=5, offset=0)
    dates = [r["created_at"] for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_pagination_total_count(db_with_experiments):
    with patch("database.db.DB_PATH", db_with_experiments):
        _, total = list_experiments_page(limit=5, offset=0)
    assert total == 25


def test_pagination_empty_db(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_db(db_path)
    with patch("database.db.DB_PATH", db_path):
        rows, total = list_experiments_page(limit=10, offset=0)
    assert rows == []
    assert total == 0
