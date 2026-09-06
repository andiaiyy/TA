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
    # v19-v21: jejak penyuntingan pipeline kontribusi. ADITIF seluruhnya —
    # tiga ALTER TABLE ADD COLUMN nullable pada `registered_pipelines`. Tabel
    # experiments TIDAK disentuh sama sekali, dan tidak ada nilai yang diisi
    # mundur: versi yang lahir dari persetujuan memang tidak punya penyunting.
    {
        "version": 19,
        "description": "Add nullable edited_by to registered_pipelines",
        "sql": "ALTER TABLE registered_pipelines ADD COLUMN edited_by TEXT",
        "add_column": ("registered_pipelines", "edited_by"),
    },
    {
        "version": 20,
        "description": "Add nullable edited_at to registered_pipelines",
        "sql": "ALTER TABLE registered_pipelines ADD COLUMN edited_at TEXT",
        "add_column": ("registered_pipelines", "edited_at"),
    },
    {
        "version": 21,
        "description": "Add nullable change_note to registered_pipelines",
        "sql": "ALTER TABLE registered_pipelines ADD COLUMN change_note TEXT",
        "add_column": ("registered_pipelines", "change_note"),
    },
    {
        # Akun Kontributor tidak lagi menunggu persetujuan. Akun lama yang
        # terlanjur berstatus `pending` DIAKTIFKAN — bukan dihapus: username,
        # hash password, peran, `requested_at`, dan `reason`-nya tetap utuh,
        # hanya statusnya yang berpindah. Tanpa ini, pendaftar lama akan
        # menunggu selamanya karena antrean persetujuannya sudah tidak ada.
        #
        # Akun `disabled` TIDAK ikut: menonaktifkan adalah keputusan sadar
        # seorang Research Admin, dan itu tetap berlaku.
        "version": 22,
        "description": "Activate legacy pending contributor accounts",
        "sql": ("UPDATE users SET status = 'active' "
                "WHERE status = 'pending'"),
    },
    {
        # Uji coba pipeline sebelum persetujuan. Catatannya hidup di TABEL
        # SENDIRI, bukan di `experiments`: hasil uji bukan hasil penelitian,
        # dan memisahkannya membuat "jumlah eksperimen penelitian tidak
        # berubah" menjadi sifat struktur — bukan janji yang bergantung pada
        # setiap kueri mengingat sebuah penyaring.
        #
        # Catatan di sini SEMENTARA: dihapus setelah keputusan diambil.
        "version": 23,
        "description": "Add pipeline_trials table (temporary pre-approval runs)",
        "sql": """
            CREATE TABLE IF NOT EXISTS pipeline_trials (
                id             TEXT PRIMARY KEY,
                submission_id  INTEGER NOT NULL,
                package_hash   TEXT NOT NULL,
                dataset_type   TEXT NOT NULL,
                dataset_path   TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'QUEUED',
                started_by     TEXT NOT NULL,
                started_at     TEXT NOT NULL,
                finished_at    TEXT,
                duration_s     REAL,
                rows_used      INTEGER,
                metrics_json   TEXT,
                error_stage    TEXT,
                error_kind     TEXT,
                error_message  TEXT,
                artifacts_dir  TEXT
            )
        """,
    },
    {
        # Jejak RINGKAS uji coba, menempel pada pengajuan. Ini satu-satunya
        # bagian yang bertahan setelah keputusan diambil — untuk riwayat,
        # bukan sebagai hasil penelitian.
        "version": 24,
        "description": "Add nullable trial_json to submissions (trial trail)",
        "sql": "ALTER TABLE submissions ADD COLUMN trial_json TEXT",
        "add_column": ("submissions", "trial_json"),
    },
    {
        # Dataset CONTOH yang dilampirkan kontributor untuk menguji
        # pipelinenya. Kolomnya menyimpan KETERANGAN berkasnya (nama, ukuran,
        # hash, format, waktu unggah, catatan kontributor) — berkasnya sendiri
        # ada di area penampungan pengajuan, BUKAN di `storage/datasets/`.
        #
        # NULLABLE: melampirkan bersifat opsional, dan pengajuan lama tidak
        # pernah punya lampiran.
        "version": 25,
        "description": "Add nullable trial_dataset_json to submissions",
        "sql": "ALTER TABLE submissions ADD COLUMN trial_dataset_json TEXT",
        "add_column": ("submissions", "trial_dataset_json"),
    },
    {
        # Identitas research pipeline TERUNGGAH. Tabel BARU — tidak menyentuh
        # `experiments`, `submissions`, maupun `registered_pipelines`, jadi
        # seluruh data lama tidak terpengaruh sama sekali.
        #
        # Baris `registered_pipelines` yang SUDAH ADA tetap membawa
        # `dataset_type` bawaan (mis. HIKARI2021) dan tetap berarti persis
        # seperti sebelumnya: menumpang keluarga bawaan. Tidak ada yang diisi
        # mundur ke model baru.
        "version": 26,
        "description": "Create research_pipelines table (uploaded research identity)",
        "sql": models.CREATE_RESEARCH_PIPELINES_TABLE,
    },
    {
        # Dataset yang MENYATU dengan research pipeline terunggah. Sebelumnya
        # lampiran dataset bersifat SEMENTARA: ia hanya hidup selama peninjauan
        # lalu dibuang. Sebuah research pipeline yang berdiri sendiri
        # membutuhkan datasetnya secara permanen — tanpa itu, algoritmanya
        # terdaftar tetapi tidak pernah dapat dijalankan.
        #
        # Kolom NULLABLE: research pipeline yang menumpang jenis bawaan memakai
        # dataset platform dan memang tidak punya dataset sendiri. Itu keadaan
        # yang sah, bukan isian yang terlewat.
        "version": 27,
        "description": "Add nullable dataset_json to research_pipelines (bound dataset)",
        "sql": "ALTER TABLE research_pipelines ADD COLUMN dataset_json TEXT",
        "add_column": ("research_pipelines", "dataset_json"),
    },
    {
        # Fase progres sebuah pipeline terunggah, dibaca STATIS dari panggilan
        # `_emit_progress()` pada kodenya saat diunggah. Pipeline bawaan
        # menyimpannya di `config/pipeline_registry.py`; yang terunggah tidak
        # punya tempat itu, sehingga bar progresnya berjalan tanpa nama fase
        # sementara pipelinenya SUDAH memancarkan fase itu saat berjalan.
        #
        # Kolom NULLABLE: paket yang tidak memanggil `_emit_progress` memang
        # tidak punya fase, dan itu keadaan yang sah — bukan isian terlewat.
        # Baris yang sudah ada tetap NULL dan berperilaku persis seperti
        # sebelumnya.
        "version": 28,
        "description": "Add nullable stages_json to registered_pipelines (progress phases)",
        "sql": "ALTER TABLE registered_pipelines ADD COLUMN stages_json TEXT",
        "add_column": ("registered_pipelines", "stages_json"),
    },    {
        # POTRET `get_info()`, diambil sekali saat pengajuannya disetujui.
        #
        # Tanpa ini, satu-satunya cara mengetahui hyperparameter, langkah
        # preprocessing, atau kebijakan metrik sebuah pipeline terunggah adalah
        # MEMUAT DAN MENGINSTANSIASI kodenya. Katalog menolak melakukannya —
        # menampilkan daftar tidak boleh mengeksekusi kode unggahan — sehingga
        # kartunya tampil kosong; halaman riwayat justru melakukannya, dua
        # pembacaan DB dan dua pembukaan berkas per pipeline pada SETIAP
        # penggambaran ulang.
        #
        # Potret juga lebih jujur secara waktu: ia menyatakan apa yang
        # dijanjikan kode SAAT DITINJAU, bukan apa yang dikatakannya hari ini.
        #
        # Kolom NULLABLE: pipeline yang terdaftar sebelum migrasi ini tidak
        # punya potret, dan kekosongan itu dinyatakan apa adanya.
        "version": 29,
        "description": "Add nullable info_json to registered_pipelines (get_info snapshot)",
        "sql": "ALTER TABLE registered_pipelines ADD COLUMN info_json TEXT",
        "add_column": ("registered_pipelines", "info_json"),
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
