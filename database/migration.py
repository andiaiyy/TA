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


def apply_migrations(db_path: str | None = None) -> list[int]:
    """Apply all pending migrations. Returns list of applied version numbers."""
    current = get_current_version(db_path)
    applied = []
    conn = get_connection(db_path)
    try:
        conn.execute(CREATE_SCHEMA_VERSION_TABLE)
        for m in MIGRATIONS:
            if m["version"] > current:
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
