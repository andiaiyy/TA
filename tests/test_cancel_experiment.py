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
    fake_exp = {"id": "exp-z", "status": "QUEUED"}
    mock_celery = MagicMock()
    with patch("orchestrator.experiment_service.get_experiment", return_value=fake_exp), \
         patch("orchestrator.experiment_service.USE_ASYNC", True), \
         patch("orchestrator.experiment_service.db_cancel_experiment", return_value=True), \
         patch("orchestrator.experiment_service.now_iso", return_value="2026-01-01T01:00:00Z"), \
         patch("workers.celery_worker.app", mock_celery):
        r = svc_cancel("exp-z")
    assert r["success"] is True
