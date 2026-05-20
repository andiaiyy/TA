"""Tests for experiment cancellation — DB and service layer."""
import pytest
from unittest.mock import patch, MagicMock
from database.db import cancel_experiment, create_experiment, get_experiment, set_running, init_db
from orchestrator.experiment_service import cancel_experiment as svc_cancel


# ─── DB layer ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    return db


def _insert(db, exp_id, status="QUEUED"):
    create_experiment(
        experiment_id=exp_id,
        dataset_type="CICIDS2017",
        dataset_path="/fake/path.csv",
        dataset_hash="abc123",
        pipeline_id="cicids2017.rfc",
        created_at="2026-01-01T00:00:00Z",
        db_path=db,
    )
    if status == "RUNNING":
        set_running(exp_id, started_at="2026-01-01T00:01:00Z", db_path=db)


def test_cancel_queued_succeeds(tmp_db):
    _insert(tmp_db, "exp-cancel-1", status="QUEUED")
    result = cancel_experiment("exp-cancel-1", completed_at="2026-01-01T01:00:00Z", db_path=tmp_db)
    assert result is True
    exp = get_experiment("exp-cancel-1", db_path=tmp_db)
    assert exp["status"] == "FAILED"
    assert exp["error_message"] == "Cancelled by user"


def test_cancel_running_succeeds(tmp_db):
    _insert(tmp_db, "exp-cancel-2", status="RUNNING")
    result = cancel_experiment("exp-cancel-2", completed_at="2026-01-01T01:00:00Z", db_path=tmp_db)
    assert result is True
    exp = get_experiment("exp-cancel-2", db_path=tmp_db)
    assert exp["status"] == "FAILED"
    assert exp["error_message"] == "Cancelled by user"


def test_cancel_finished_returns_false(tmp_db):
    from database.db import set_finished
    _insert(tmp_db, "exp-cancel-3", status="RUNNING")
    set_finished(
        "exp-cancel-3",
        completed_at="2026-01-01T01:00:00Z",
        accuracy=0.9,
        precision_score=0.9,
        recall=0.9,
        f1_score=0.9,
        metrics_path="/fake/metrics.json",
        model_path="/fake/model.pkl",
        db_path=tmp_db,
    )
    result = cancel_experiment("exp-cancel-3", completed_at="2026-01-01T02:00:00Z", db_path=tmp_db)
    assert result is False
    exp = get_experiment("exp-cancel-3", db_path=tmp_db)
    assert exp["status"] == "FINISHED"


# ─── Service layer ────────────────────────────────────────────────────────────

def test_svc_cancel_nonexistent():
    with patch("orchestrator.experiment_service.get_experiment", return_value=None):
        r = svc_cancel("nonexistent-id")
    assert r["success"] is False
    assert "not found" in r["message"]


def test_svc_cancel_finished():
    fake_exp = {"id": "exp-x", "status": "FINISHED"}
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp):
        r = svc_cancel("exp-x")
    assert r["success"] is False
    assert "Cannot cancel" in r["message"]


def test_svc_cancel_queued_sync():
    fake_exp = {"id": "exp-y", "status": "QUEUED"}
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp), \
         patch("orchestrator.experiment_service.USE_ASYNC", False), \
         patch("orchestrator.experiment_service.db_cancel_experiment", return_value=True) as mock_db, \
         patch("orchestrator.experiment_service.now_iso", return_value="2026-01-01T01:00:00Z"):
        r = svc_cancel("exp-y")
    mock_db.assert_called_once_with("exp-y", completed_at="2026-01-01T01:00:00Z")
    assert r["success"] is True
    assert r["experiment_id"] == "exp-y"


def test_svc_cancel_queued_async():
    # Pre-task_id behaviour: when no task_id is stored, async branch must
    # not touch Celery and must still mark the DB FAILED. (No assertion on
    # revoke here — see test_svc_cancel_async_revokes_by_task_id for the
    # positive case.)
    fake_exp = {"id": "exp-z", "status": "QUEUED", "task_id": None}
    mock_celery = MagicMock()
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp), \
         patch("orchestrator.experiment_service.USE_ASYNC", True), \
         patch("orchestrator.experiment_service.db_cancel_experiment", return_value=True), \
         patch("orchestrator.experiment_service.now_iso", return_value="2026-01-01T01:00:00Z"), \
         patch("workers.celery_worker.app", mock_celery):
        r = svc_cancel("exp-z")
    assert r["success"] is True


def test_svc_cancel_async_revokes_by_task_id():
    """Async cancel must revoke using the stored Celery task id, NOT experiment_id."""
    fake_exp = {"id": "exp-z", "status": "QUEUED", "task_id": "celery-task-abc"}
    mock_celery = MagicMock()
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp), \
         patch("orchestrator.experiment_service.USE_ASYNC", True), \
         patch("orchestrator.experiment_service.db_cancel_experiment", return_value=True), \
         patch("orchestrator.experiment_service.now_iso", return_value="2026-01-01T01:00:00Z"), \
         patch("workers.celery_worker.app", mock_celery):
        r = svc_cancel("exp-z")
    mock_celery.control.revoke.assert_called_once_with(
        "celery-task-abc", terminate=True, signal="SIGTERM"
    )
    # Defensive: make sure we did NOT revoke by experiment_id
    call_args = mock_celery.control.revoke.call_args
    assert call_args.args[0] != "exp-z"
    assert r["success"] is True


def test_svc_cancel_async_no_task_id_is_safe():
    """Async cancel with task_id=None must skip revoke but still update DB."""
    fake_exp = {"id": "exp-no-task", "status": "QUEUED", "task_id": None}
    mock_celery = MagicMock()
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp), \
         patch("orchestrator.experiment_service.USE_ASYNC", True), \
         patch("orchestrator.experiment_service.db_cancel_experiment", return_value=True) as mock_db, \
         patch("orchestrator.experiment_service.now_iso", return_value="2026-01-01T01:00:00Z"), \
         patch("workers.celery_worker.app", mock_celery):
        r = svc_cancel("exp-no-task")
    mock_celery.control.revoke.assert_not_called()
    mock_db.assert_called_once_with("exp-no-task", completed_at="2026-01-01T01:00:00Z")
    assert r["success"] is True


def test_svc_cancel_sync_mode_no_revoke():
    """Sync-mode cancel must never import or touch the Celery app."""
    fake_exp = {"id": "exp-sync", "status": "RUNNING", "task_id": None}
    mock_celery = MagicMock()
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp), \
         patch("orchestrator.experiment_service.USE_ASYNC", False), \
         patch("orchestrator.experiment_service.db_cancel_experiment", return_value=True), \
         patch("orchestrator.experiment_service.now_iso", return_value="2026-01-01T01:00:00Z"), \
         patch("workers.celery_worker.app", mock_celery):
        r = svc_cancel("exp-sync")
    # In sync mode the USE_ASYNC branch is skipped entirely, so the mocked
    # celery app must be completely untouched (no attribute access at all).
    assert mock_celery.mock_calls == []
    assert r["success"] is True


# ─── task_id column / migration ──────────────────────────────────────────────

def test_create_experiment_starts_with_null_task_id(tmp_db):
    """Freshly inserted experiments must have task_id = NULL."""
    _insert(tmp_db, "exp-null-task", status="QUEUED")
    exp = get_experiment("exp-null-task", db_path=tmp_db)
    assert "task_id" in exp
    assert exp["task_id"] is None


def test_migrations_apply_cleanly_on_fresh_db(tmp_path):
    """init_db then apply_migrations on a brand-new DB must not raise.

    init_db creates the experiments table from CREATE_EXPERIMENTS_TABLE,
    which already includes task_id. Migration v2 then tries to ADD COLUMN
    task_id — without the runner's PRAGMA guard SQLite would raise
    'duplicate column name: task_id'.
    """
    from database.migration import apply_migrations, get_current_version
    db = str(tmp_path / "fresh.db")
    init_db(db)
    applied = apply_migrations(db)
    assert 2 in applied, f"Expected v2 to be recorded, got {applied}"
    assert get_current_version(db) >= 2
    # And the column is usable
    _insert(db, "exp-fresh", status="QUEUED")
    exp = get_experiment("exp-fresh", db_path=db)
    assert exp["task_id"] is None


def test_migrations_apply_cleanly_on_v1_db(tmp_path):
    """A DB created when only v1 existed must gain task_id via migration v2."""
    import sqlite3
    from database.migration import apply_migrations, get_current_version, CREATE_SCHEMA_VERSION_TABLE
    from utils.timestamps import now_iso
    db = str(tmp_path / "v1.db")

    # Hand-build a v1-shape DB: experiments table WITHOUT task_id, plus
    # _schema_version recording v1. Simulates an existing user DB.
    legacy_sql = """
    CREATE TABLE experiments (
        id                TEXT PRIMARY KEY,
        dataset_type      TEXT NOT NULL,
        dataset_path      TEXT NOT NULL,
        dataset_hash      TEXT NOT NULL,
        pipeline_id       TEXT NOT NULL,
        status            TEXT NOT NULL DEFAULT 'QUEUED',
        created_at        TEXT NOT NULL,
        started_at        TEXT,
        completed_at      TEXT,
        accuracy          REAL,
        precision_score   REAL,
        recall            REAL,
        f1_score          REAL,
        metrics_path      TEXT,
        model_path        TEXT,
        error_message     TEXT
    );
    """
    conn = sqlite3.connect(db)
    try:
        conn.execute(legacy_sql)
        conn.execute(CREATE_SCHEMA_VERSION_TABLE)
        conn.execute(
            "INSERT INTO _schema_version (version, applied_at, description) VALUES (?, ?, ?)",
            (1, now_iso(), "Create experiments table"),
        )
        conn.commit()
    finally:
        conn.close()

    # Sanity: task_id absent before migration
    conn = sqlite3.connect(db)
    cols_before = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}
    conn.close()
    assert "task_id" not in cols_before

    applied = apply_migrations(db)
    assert applied == [2]
    assert get_current_version(db) == 2

    conn = sqlite3.connect(db)
    cols_after = {row[1] for row in conn.execute("PRAGMA table_info(experiments)").fetchall()}
    conn.close()
    assert "task_id" in cols_after
