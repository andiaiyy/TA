"""
Simple schema migration runner.

Usage:
    python -m database.migration          # apply pending migrations
    python -m database.migration --reset  # drop all + recreate (dev only)
"""
import sqlite3
from database import models
from database.db import get_connection
from utils.timestamps import now_iso

MIGRATIONS = [
    {
        "version": 1,
        "description": "Create experiments table",
        "sql": models.CREATE_EXPERIMENTS_TABLE,
    },
    # v2 is idempotent: the column may already exist on a fresh DB because
    # CREATE_EXPERIMENTS_TABLE in models.py now declares task_id directly.
    # The runner inspects add_column and skips the ALTER if the column is present.
    {
        "version": 2,
        "description": "Add task_id column to experiments (Celery AsyncResult.id)",
        "sql": "ALTER TABLE experiments ADD COLUMN task_id TEXT",
        "add_column": ("experiments", "task_id"),
    },
]

CREATE_SCHEMA_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS _schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    description TEXT
);
"""


def get_current_version(db_path: str | None = None) -> int:
    """Return highest applied migration version, or 0."""
    conn = get_connection(db_path)
    try:
        conn.execute(CREATE_SCHEMA_VERSION_TABLE)
        conn.commit()
        row = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()
        return row[0] or 0
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if `column` is already present on `table`.

    Uses PRAGMA table_info — safe because table/column come from the
    MIGRATIONS list (developer-controlled), not user input.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}  # row[1] = column name
    return column in existing


def apply_migrations(db_path: str | None = None) -> list[int]:
    """Apply all pending migrations. Returns list of applied version numbers.

    Migrations declaring ``add_column: (table, column)`` are idempotent: the
    runner inspects the schema first and skips the SQL if the column is
    already present. This lets a new column live in both
    ``CREATE_EXPERIMENTS_TABLE`` (so fresh DBs get it via init_db) and an
    ALTER migration (so existing DBs get it via apply_migrations) without
    SQLite raising "duplicate column name" on a fresh DB.
    """
    current = get_current_version(db_path)
    applied = []
    conn = get_connection(db_path)
    try:
        conn.execute(CREATE_SCHEMA_VERSION_TABLE)
        for m in MIGRATIONS:
            if m["version"] > current:
                add_column = m.get("add_column")
                if add_column and _column_exists(conn, *add_column):
                    print(
                        f"Skipping migration {m['version']} SQL "
                        f"(column {add_column[0]}.{add_column[1]} already present); "
                        f"recording version"
                    )
                else:
                    print(f"Applying migration {m['version']}: {m['description']}")
                    conn.execute(m["sql"])
                conn.execute(
                    "INSERT INTO _schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                    (m["version"], now_iso(), m["description"]),
                )
                conn.commit()
                applied.append(m["version"])
        if not applied:
            print("No pending migrations.")
    finally:
        conn.close()
    return applied


def reset_db(db_path: str | None = None) -> None:
    """Drop all tables and reapply all migrations. DEV ONLY."""
    print("Resetting database — all data will be lost!")
    conn = get_connection(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS experiments")
        conn.execute("DROP TABLE IF EXISTS _schema_version")
        conn.commit()
    finally:
        conn.close()
    apply_migrations(db_path)
    print("Database reset complete.")


if __name__ == "__main__":
    import sys
    if "--reset" in sys.argv:
        reset_db()
    else:
        apply_migrations()
