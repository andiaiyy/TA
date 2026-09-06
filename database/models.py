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
    error_message     TEXT,
    task_id           TEXT,
    -- Kepemilikan eksperimen. NULLABLE dan default NULL: record lama (dibuat
    -- sebelum autentikasi ada) tetap terbaca apa adanya. Fase 1 TIDAK memakai
    -- kolom ini untuk memfilter apa pun — disiapkan untuk Fase 2.
    owner             TEXT,
    -- Ketertelusuran pipeline TERUNGGAH (Fase 4). NULL untuk pipeline bawaan:
    -- definisinya ada di git, jadi tidak perlu versi/hash terpisah. Record lama
    -- tetap NULL dan TIDAK pernah diisi mundur.
    pipeline_version  INTEGER,
    pipeline_hash     TEXT,
    -- Mode eksekusi (run resmi vs run eksplorasi). NULLABLE, dan NULL berarti
    -- RESMI: 48 record yang sudah ada dibuat sebelum kolom ini ada, semuanya
    -- memakai parameter terkunci, jadi membacanya sebagai resmi adalah fakta —
    -- bukan asumsi. Tidak ada record lama yang diisi mundur.
    run_mode          TEXT,
    -- Parameter yang BENAR-BENAR dipakai run ini, sebagai JSON. NULL pada
    -- record lama: nilainya tidak pernah dicatat saat itu, dan menebaknya
    -- justru akan mengarang. Pembacanya jatuh kembali ke definisi pipeline
    -- dengan asal-usul yang dinyatakan.
    params_used       TEXT,
    -- 1 bila ada parameter yang berbeda dari nilai terkunci. Turunan dari
    -- params_used, disimpan supaya penyaringan & penandaan tidak perlu
    -- membongkar JSON di setiap baris.
    params_changed    INTEGER
);
"""

# Akun pengguna. Password TIDAK PERNAH disimpan sebagai teks biasa — hanya
# turunan PBKDF2 bersalt (lihat orchestrator/auth_service.py).
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'contributor',
    created_at    TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    -- Status akun: sumber kebenaran untuk izin. `is_active` dipertahankan agar
    -- skema tetap aditif dan dijaga tetap sinkron, tetapi kode HANYA membaca
    -- `status` — "menunggu persetujuan" berbeda maknanya dari "dinonaktifkan",
    -- dan perbedaan itu perlu terlihat eksplisit.
    status        TEXT NOT NULL DEFAULT 'active',
    requested_at  TEXT,
    reason        TEXT,
    activated_by  TEXT,
    activated_at  TEXT
);
"""

# Status akun. Registrasi mandiri selalu menghasilkan `pending`: setara
# pengunjung (nol hak) sampai Research Admin mengaktifkannya.
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
ALL_USER_STATUSES = [STATUS_PENDING, STATUS_ACTIVE, STATUS_DISABLED]

USER_STATUS_LABELS = {
    STATUS_PENDING: "Menunggu persetujuan",
    STATUS_ACTIVE: "Aktif",
    STATUS_DISABLED: "Dinonaktifkan",
}


def normalize_status(status: str | None) -> str:
    """Status tidak dikenal diperlakukan sebagai `pending` (hak paling kecil)."""
    value = (status or "").strip()
    return value if value in ALL_USER_STATUSES else STATUS_PENDING


def status_label(status: str | None) -> str:
    return USER_STATUS_LABELS[normalize_status(status)]

# Dua peran akun. "Pengunjung" BUKAN peran — itu keadaan belum login
# (identitas None), dan tetap boleh melihat serta menjalankan eksperimen.
ROLE_CONTRIBUTOR = "contributor"          # boleh mengunggah dataset & pipeline
ROLE_RESEARCH_ADMIN = "research_admin"    # boleh mengunggah + menyetujui + kelola user
ALL_ROLES = [ROLE_CONTRIBUTOR, ROLE_RESEARCH_ADMIN]

# Label tampilan — satu tempat, supaya UI tidak menulis ulang string peran.
ROLE_LABELS = {
    ROLE_CONTRIBUTOR: "Kontributor",
    ROLE_RESEARCH_ADMIN: "Research Admin",
}

# Nama peran lama (Fase 1) -> peran baru. Dipakai oleh migrasi v5 dan sebagai
# toleransi baca bila ada baris yang belum termigrasi.
LEGACY_ROLE_MAP = {
    "admin": ROLE_RESEARCH_ADMIN,
    "researcher": ROLE_CONTRIBUTOR,
}


def normalize_role(role: str | None) -> str:
    """Peran lama/tak dikenal -> peran baru yang sah (default: kontributor)."""
    role = (role or "").strip()
    role = LEGACY_ROLE_MAP.get(role, role)
    return role if role in ALL_ROLES else ROLE_CONTRIBUTOR


def role_label(role: str | None) -> str:
    """Nama peran untuk ditampilkan ke pengguna."""
    return ROLE_LABELS.get(normalize_role(role), ROLE_LABELS[ROLE_CONTRIBUTOR])

# Antrean persetujuan unggahan (Fase 3). SATU tabel untuk kedua jenis, dibedakan
# oleh `kind`. Berkasnya sendiri TIDAK disimpan di sini — hanya lokasinya
# (`stored_path`, selalu di area penampungan yang tidak diimpor platform),
# sidik jarinya (`file_hash`), serta metadata & ringkasan validasi sebagai JSON.
CREATE_SUBMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS submissions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    kind              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    submitted_by      TEXT NOT NULL,
    submitted_at      TEXT NOT NULL,
    reviewed_by       TEXT,
    reviewed_at       TEXT,
    review_note       TEXT,
    original_filename TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    file_hash         TEXT NOT NULL,
    file_size         INTEGER NOT NULL,
    metadata_json     TEXT,
    validation_json   TEXT,
    -- Jejak RINGKAS uji coba (siapa menguji, kapan, dataset apa, hasilnya).
    -- NULLABLE: pengajuan lama tidak pernah diuji dan tetap terbaca apa adanya.
    trial_json        TEXT,
    -- Keterangan dataset CONTOH yang dilampirkan kontributor untuk menguji
    -- pipelinenya. Berkasnya ada di area penampungan pengajuan, bukan di
    -- `storage/datasets/`. NULLABLE: melampirkan bersifat opsional.
    trial_dataset_json TEXT
);
"""

KIND_DATASET = "dataset"
KIND_PIPELINE = "pipeline"
ALL_KINDS = [KIND_DATASET, KIND_PIPELINE]

SUBMISSION_PENDING = "pending"
SUBMISSION_APPROVED = "approved"
SUBMISSION_REJECTED = "rejected"
ALL_SUBMISSION_STATUSES = [SUBMISSION_PENDING, SUBMISSION_APPROVED, SUBMISSION_REJECTED]

# Pipeline TERUNGGAH yang sudah disetujui (Fase 4). Ini BUKAN pengganti
# config/pipeline_registry.py: sepuluh pipeline bawaan tetap didefinisikan
# secara statis di sana dan tidak pernah disentuh mekanisme ini.
#
# Immutability: (name, version) UNIQUE dan tidak pernah ditimpa — menyetujui
# nama yang sama sekali lagi membuat versi BARU dengan berkas terpisah,
# sehingga eksperimen lama tetap menunjuk kode yang persis sama.
CREATE_REGISTERED_PIPELINES_TABLE = """
CREATE TABLE IF NOT EXISTS registered_pipelines (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id    TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    version        INTEGER NOT NULL,
    submission_id  INTEGER,
    dataset_type   TEXT NOT NULL,
    entry_class    TEXT NOT NULL,
    entry_file     TEXT NOT NULL,
    file_hash      TEXT NOT NULL,
    algorithm      TEXT,
    paper          TEXT,
    registered_by  TEXT NOT NULL,
    registered_at  TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    -- Penyuntingan oleh Research Admin. NULLABLE: versi 1 lahir dari
    -- PERSETUJUAN, bukan penyuntingan, jadi ketiganya kosong di sana dan itu
    -- fakta — bukan data yang hilang. Menyunting TIDAK PERNAH menimpa baris
    -- ini; ia menambah baris versi berikutnya dengan ketiga kolom terisi.
    edited_by      TEXT,
    edited_at      TEXT,
    change_note    TEXT,
    -- Fase progres, dibaca STATIS dari panggilan `_emit_progress()` pada kode
    -- paketnya saat diunggah. Pipeline bawaan menyimpannya di
    -- `config/pipeline_registry.py`; yang terunggah tidak punya tempat itu.
    -- NULLABLE: paket yang tidak memancarkan fase memang tidak punya, dan bar
    -- progresnya berjalan tanpa nama fase — keadaan yang sah.
    stages_json    TEXT,
    -- Potret `get_info()` saat persetujuan. Dipakai katalog dan halaman
    -- riwayat untuk MENJELASKAN pipeline ini tanpa memuat kodenya. NULLABLE:
    -- pipeline yang terdaftar sebelum kolom ini ada tidak punya potret.
    info_json      TEXT,
    UNIQUE (name, version)
);
"""

# Prefiks namespace pipeline terunggah. Dipisahkan dari `hikari2021.*` /
# `eve_cbr.*` supaya tabrakan ID dengan pipeline bawaan tidak mungkin terjadi.
UPLOADED_PREFIX = "uploaded."


# Uji coba pipeline SEBELUM persetujuan — sengaja tabel tersendiri, bukan baris
# bertanda di `experiments`. Hasil uji bukan hasil penelitian: memisahkannya
# membuat "jumlah eksperimen penelitian tidak berubah" menjadi sifat struktur,
# bukan janji yang bergantung pada setiap kueri mengingat sebuah penyaring.
#
# Isinya SEMENTARA: dihapus setelah keputusan diambil. Yang bertahan hanyalah
# jejak ringkas pada `submissions.trial_json`.
CREATE_PIPELINE_TRIALS_TABLE = """
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
);
"""

# Research pipeline TERUNGGAH — identitas penelitiannya sendiri (Tahap 1).
#
# Sampai sekarang sebuah unggahan harus MENUMPANG salah satu `dataset_type`
# bawaan, karena hanya `contracts/dataset_schemas.py` dan
# `config/research_attribution.py` yang mendefinisikan apa itu "research
# pipeline" — dan keduanya statis. Itulah sebabnya kartu peninjauan sempat
# harus bertanya "ini ikut research pipeline mana": pertanyaan itu akibat,
# bukan pilihan desain.
#
# Tabel ini memberi unggahan identitasnya sendiri. Ia TIDAK menggantikan kedua
# berkas statis itu — keduanya tidak pernah disentuh, dan saat digabung entri
# statis SELALU menang (lihat orchestrator/research_registry.py).
#
# `schema_json` menyimpan kontrak dataset yang DIDEKLARASIKAN kontributor
# (kolom label, kolom wajib, format berkas). Platform tidak pernah mengarangnya
# dari isi berkas.
CREATE_RESEARCH_PIPELINES_TABLE = """
CREATE TABLE IF NOT EXISTS research_pipelines (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_type   TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    submission_id  INTEGER,
    schema_json    TEXT NOT NULL,
    attribution_json TEXT,
    registered_by  TEXT NOT NULL,
    registered_at  TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    -- Dataset yang MENYATU dengan research pipeline ini. NULL bila ia
    -- menumpang jenis bawaan dan memakai dataset platform.
    dataset_json   TEXT
);
"""

# Awalan `dataset_type` research pipeline terunggah. Dipisahkan supaya tabrakan
# dengan HIKARI2021 / EVE_SURICATA tidak mungkin terjadi — bukan tidak
# disengaja, melainkan tidak dapat terjadi.
RESEARCH_PREFIX = "uploaded:"


def build_research_dataset_type(name: str) -> str:
    """`uploaded:<nama>` — pengenal research pipeline terunggah."""
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_"
                      for ch in (name or "").strip().lower()).strip("_-")
    return f"{RESEARCH_PREFIX}{cleaned[:60]}" if cleaned else ""


def is_uploaded_research(dataset_type) -> bool:
    return str(dataset_type or "").startswith(RESEARCH_PREFIX)


TRIAL_QUEUED = "QUEUED"
TRIAL_RUNNING = "RUNNING"
TRIAL_PASSED = "PASSED"
TRIAL_FAILED = "FAILED"


ALL_TABLES = [CREATE_EXPERIMENTS_TABLE, CREATE_USERS_TABLE,
              CREATE_SUBMISSIONS_TABLE, CREATE_REGISTERED_PIPELINES_TABLE,
              CREATE_PIPELINE_TRIALS_TABLE,
              CREATE_RESEARCH_PIPELINES_TABLE]
