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
    # v3-v4: fondasi autentikasi (Fase 1). Keduanya ADITIF — tabel experiments
    # tidak pernah dibuat ulang, dan tidak ada data lama yang disentuh.
    {
        "version": 3,
        "description": "Create users table (authentication phase 1)",
        "sql": models.CREATE_USERS_TABLE,
    },
    {
        "version": 4,
        "description": "Add nullable owner column to experiments (prepared for phase 2)",
        "sql": "ALTER TABLE experiments ADD COLUMN owner TEXT",
        "add_column": ("experiments", "owner"),
    },
    # v5: penamaan peran Fase 2. Hanya MENGUBAH NILAI kolom role pada baris yang
    # masih memakai nama lama — tidak ada pengguna yang dihapus, tidak ada tabel
    # yang dibuat ulang, dan tabel experiments tidak tersentuh sama sekali.
    {
        "version": 5,
        "description": "Rename legacy roles (admin -> research_admin, researcher -> contributor)",
        "sql": (
            "UPDATE users SET role = CASE role "
            "WHEN 'admin' THEN 'research_admin' "
            "WHEN 'researcher' THEN 'contributor' "
            "ELSE role END "
            "WHERE role IN ('admin', 'researcher')"
        ),
    },
    # v6: antrean persetujuan (Fase 3). Tabel BARU — tidak menyentuh experiments
    # maupun users, jadi seluruh data lama tidak terpengaruh sama sekali.
    {
        "version": 6,
        "description": "Create submissions table (upload approval queue)",
        "sql": models.CREATE_SUBMISSIONS_TABLE,
    },
    # v7-v9: registry dinamis (Fase 4). Satu tabel BARU + dua kolom nullable.
    # Tabel experiments tidak dibuat ulang dan record lama tidak diisi mundur.
    {
        "version": 7,
        "description": "Create registered_pipelines table (dynamic registry)",
        "sql": models.CREATE_REGISTERED_PIPELINES_TABLE,
    },
    {
        "version": 8,
        "description": "Add nullable pipeline_version to experiments (traceability)",
        "sql": "ALTER TABLE experiments ADD COLUMN pipeline_version INTEGER",
        "add_column": ("experiments", "pipeline_version"),
    },
    {
        "version": 9,
        "description": "Add nullable pipeline_hash to experiments (traceability)",
        "sql": "ALTER TABLE experiments ADD COLUMN pipeline_hash TEXT",
        "add_column": ("experiments", "pipeline_hash"),
    },
    # v10-v15: registrasi mandiri + status akun. ADITIF seluruhnya, dan
    # default 'active' memastikan akun yang SUDAH ADA (termasuk Research Admin
    # hasil seed) tidak pernah mendadak menjadi pending.
    {
        "version": 10,
        "description": "Add status column to users (default active for existing accounts)",
        "sql": "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "add_column": ("users", "status"),
    },
    {
        "version": 11,
        "description": "Mirror legacy is_active=0 accounts into status='disabled'",
        "sql": "UPDATE users SET status = 'disabled' WHERE is_active = 0",
    },
    {
        "version": 12,
        "description": "Add requested_at to users (self sign-up metadata)",
        "sql": "ALTER TABLE users ADD COLUMN requested_at TEXT",
        "add_column": ("users", "requested_at"),
    },
    {
        "version": 13,
        "description": "Add reason to users (why access is requested)",
        "sql": "ALTER TABLE users ADD COLUMN reason TEXT",
        "add_column": ("users", "reason"),
    },
    {
        "version": 14,
        "description": "Add activated_by to users (who approved the account)",
        "sql": "ALTER TABLE users ADD COLUMN activated_by TEXT",
        "add_column": ("users", "activated_by"),
    },
    {
        "version": 15,
        "description": "Add activated_at to users (when the account was approved)",
        "sql": "ALTER TABLE users ADD COLUMN activated_at TEXT",
        "add_column": ("users", "activated_at"),
    },
    # v16-v18: mode eksekusi + pencatatan parameter. ADITIF seluruhnya —
    # tiga ALTER TABLE ADD COLUMN nullable pada `experiments`. Tabel TIDAK
    # dibuat ulang, tidak ada baris yang disentuh, dan tidak ada nilai yang
    # diisi mundur: record lama tetap NULL, dan NULL dibaca sebagai run RESMI
    # (orchestrator/run_mode.normalize_run_mode).
    {
        "version": 16,
        "description": "Add nullable run_mode to experiments (NULL = official)",
        "sql": "ALTER TABLE experiments ADD COLUMN run_mode TEXT",
        "add_column": ("experiments", "run_mode"),
    },
    {
        "version": 17,
        "description": "Add nullable params_used (JSON) to experiments",
        "sql": "ALTER TABLE experiments ADD COLUMN params_used TEXT",
        "add_column": ("experiments", "params_used"),
    },
    {
        "version": 18,
        "description": "Add nullable params_changed flag to experiments",
        "sql": "ALTER TABLE experiments ADD COLUMN params_changed INTEGER",
        "add_column": ("experiments", "params_changed"),
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
