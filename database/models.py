"""
Database schema definitions and status constants.
"""

STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_FINISHED = "FINISHED"
STATUS_FAILED = "FAILED"

ALL_STATUSES = [STATUS_QUEUED, STATUS_RUNNING, STATUS_FINISHED, STATUS_FAILED]

CREATE_EXPERIMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS experiments (
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

ALL_TABLES = [CREATE_EXPERIMENTS_TABLE]
