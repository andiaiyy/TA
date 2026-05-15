"""
SQLite CRUD operations.

⚠️  IMPORT RESTRICTION: Only orchestrator/ may import this module.

All functions accept an optional db_path for testability.
Default path comes from config.settings.DB_PATH.
"""
import sqlite3
import time
import functools
from config.settings import DB_PATH
from database.models import ALL_TABLES, STATUS_QUEUED


def _retry_on_locked(max_retries: int = 3, delay: float = 1.0):
    """Retry decorator for SQLite write operations that may hit database locks."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        last_error = e
                        time.sleep(delay * (attempt + 1))
                    else:
                        raise
            raise last_error
        return wrapper
    return decorator


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """
    Return a connection with Row factory and WAL mode enabled.

    WAL mode allows concurrent reads during writes — critical for
    Docker deployments where UI and Celery worker share the same DB file.
    Busy timeout prevents immediate 'database is locked' errors.
    """
    conn = sqlite3.connect(db_path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(db_path: str | None = None) -> None:
    """Create all tables if they don't exist."""
    conn = get_connection(db_path)
    try:
        for sql in ALL_TABLES:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


@_retry_on_locked()
def create_experiment(
    experiment_id: str,
    dataset_type: str,
    dataset_path: str,
    dataset_hash: str,
    pipeline_id: str,
    created_at: str,
    db_path: str | None = None,
) -> None:
    """Insert new experiment with status QUEUED."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO experiments (id, dataset_type, dataset_path, dataset_hash,
               pipeline_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (experiment_id, dataset_type, dataset_path, dataset_hash,
             pipeline_id, STATUS_QUEUED, created_at),
        )
        conn.commit()
    finally:
        conn.close()


@_retry_on_locked()
def set_running(experiment_id: str, started_at: str, db_path: str | None = None) -> None:
    """Update status to RUNNING. No-ops if experiment is not in QUEUED state."""
    import logging
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE experiments SET status = 'RUNNING', started_at = ? WHERE id = ? AND status = 'QUEUED'",
            (started_at, experiment_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            logging.getLogger(__name__).warning(
                "set_running: experiment %s was not QUEUED — skipping", experiment_id
            )
    finally:
        conn.close()


@_retry_on_locked()
def set_finished(
    experiment_id: str,
    completed_at: str,
    accuracy: float,
    precision_score: float,
    recall: float,
    f1_score: float,
    metrics_path: str,
    model_path: str,
    db_path: str | None = None,
) -> None:
    """Update status to FINISHED with metrics and paths. No-ops if not in RUNNING state."""
    import logging
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """UPDATE experiments SET status = 'FINISHED', completed_at = ?,
               accuracy = ?, precision_score = ?, recall = ?, f1_score = ?,
               metrics_path = ?, model_path = ?
               WHERE id = ? AND status = 'RUNNING'""",
            (completed_at, accuracy, precision_score, recall, f1_score,
             metrics_path, model_path, experiment_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            logging.getLogger(__name__).warning(
                "set_finished: experiment %s was not RUNNING — skipping", experiment_id
            )
    finally:
        conn.close()


@_retry_on_locked()
def set_failed(
    experiment_id: str,
    completed_at: str,
    error_message: str,
    db_path: str | None = None,
) -> None:
    """Update status to FAILED with error message. No-ops if already FINISHED/FAILED."""
    import logging
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE experiments SET status = 'FAILED', completed_at = ?, error_message = ?"
            " WHERE id = ? AND status IN ('QUEUED', 'RUNNING')",
            (completed_at, error_message, experiment_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            logging.getLogger(__name__).warning(
                "set_failed: experiment %s was not QUEUED/RUNNING — skipping", experiment_id
            )
    finally:
        conn.close()


def get_experiment(experiment_id: str, db_path: str | None = None) -> dict | None:
    """Return single experiment as dict, or None."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_experiments(db_path: str | None = None) -> list[dict]:
    """Return all experiments ordered by created_at DESC."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM experiments ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_experiments_paginated(
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> tuple[list[dict], int]:
    """
    Return a page of experiments + total count.

    Returns:
        (rows, total_count)
    """
    conn = get_connection(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM experiments ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], int(total)
    finally:
        conn.close()


@_retry_on_locked()
def cancel_experiment(
    experiment_id: str,
    completed_at: str,
    db_path: str | None = None,
) -> bool:
    """
    Cancel a QUEUED or RUNNING experiment by marking it FAILED.
    Returns True if the row was updated, False if already in a terminal state.
    """
    import logging
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """UPDATE experiments
               SET status = 'FAILED',
                   completed_at = ?,
                   error_message = 'Cancelled by user'
               WHERE id = ? AND status IN ('QUEUED', 'RUNNING')""",
            (completed_at, experiment_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            logging.getLogger(__name__).warning(
                "cancel_experiment: experiment %s not in QUEUED/RUNNING — skipped", experiment_id
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def list_experiments_by_status(status: str, db_path: str | None = None) -> list[dict]:
    """Return experiments filtered by status."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
