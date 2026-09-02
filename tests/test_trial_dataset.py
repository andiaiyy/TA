"""
Dataset uji yang dilampirkan kontributor — isolasinya, bukan sekadar fiturnya.

Berkas ini adalah CONTOH untuk membuktikan sebuah pipeline berjalan. Ia bukan
data penelitian, dan yang diuji di sini adalah bahwa ia tidak pernah menjadi
data penelitian:

* tidak masuk kumpulan dataset platform dan tidak dapat dipilih untuk
  eksperimen;
* ukurannya dibatasi jauh lebih ketat daripada unggahan dataset biasa;
* namanya disanitasi — berkas tidak pernah ditulis di luar area penampungan;
* hash-nya diverifikasi sebelum dipakai, sehingga berkas yang berubah setelah
  diajukan ditolak;
* ia dihapus bersama hasil uji setelah keputusan, tanpa berkas yatim.

Melampirkan bersifat OPSIONAL: pengajuan tanpa lampiran tetap berjalan dan
tetap dapat diuji dengan dataset platform.
"""
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from database import trials as trial_db
from database.migration import apply_migrations
from database.models import KIND_PIPELINE, SUBMISSION_PENDING
from orchestrator import trial_dataset_service as tds
from orchestrator import trial_service
from orchestrator.auth_service import AuthError

REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}
CONTRIBUTOR = {"username": "andi", "role": "contributor", "status": "active"}

PIPELINE_SOURCE = '''
from pipelines.base import BasePipeline


class TrialPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        raise NotImplementedError

    def get_info(self):
        return {}
'''

CSV_BYTES = b"a,b,Label\n1,2,0\n3,4,1\n5,6,0\n"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "trial2.db"
    apply_migrations(str(path))
    monkeypatch.setattr("database.db.DB_PATH", str(path), raising=False)
    return str(path)


@pytest.fixture
def staging(tmp_path, monkeypatch):
    """Area penampungan lampiran yang terisolasi dari proyek."""
    root = tmp_path / "trial_datasets"
    monkeypatch.setattr(tds, "TRIAL_DATASET_ROOT", root)
    return root


@pytest.fixture
def package(tmp_path):
    folder = tmp_path / "package"
    folder.mkdir()
    (folder / "trial_pipeline.py").write_text(PIPELINE_SOURCE, encoding="utf-8")
    return folder


def _insert_submission(db_path: str, package_dir: Path) -> int:
    metadata = {"entry_filename": "trial_pipeline.py",
                "class_name": "TrialPipeline",
                "dataset_type": "HIKARI2021"}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json,
                validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (KIND_PIPELINE, SUBMISSION_PENDING, "andi", "2026-01-01T00:00:00",
             "trial_pipeline.py", str(package_dir), "a" * 64, 100,
             json.dumps(metadata), json.dumps({"valid": True})))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _submission(db_path: str, submission_id: int) -> dict:
    from orchestrator.submission_service import get_submission

    return get_submission(submission_id, db_path)


def _attach(db_path, submission_id, *, name="sample.csv", data=CSV_BYTES,
            note="contoh kecil"):
    info = tds.store_attachment(io.BytesIO(data), name,
                                package_name=f"sub{submission_id}", note=note)
    tds.attach_to_submission(submission_id, info, db_path)
    return info


# ── Batas ukuran ─────────────────────────────────────────────────────────

def test_the_attachment_limit_is_far_stricter_than_a_normal_upload():
    """Ini berkas CONTOH, bukan dataset penelitian."""
    src = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "MAX_DATASET_UPLOAD_BYTES = 5 * 1024 * 1024 * 1024" in src
    assert tds.MAX_TRIAL_DATASET_BYTES < 5 * 1024 * 1024 * 1024 / 100


def test_the_limit_covers_the_rows_a_trial_can_read():
    """Batasnya diturunkan dari kegunaannya, bukan dikira-kira."""
    assert tds.MAX_TRIAL_DATASET_BYTES >= 10 * 1024 * 1024
    assert trial_service.TRIAL_LIMITS["max_rows"] == 50_000


def test_an_oversized_attachment_is_refused_with_the_numbers(db, staging,
                                                             package):
    sid = _insert_submission(db, package)
    big = b"x" * (tds.MAX_TRIAL_DATASET_BYTES + 1)
    with pytest.raises(tds.TrialDatasetError) as excinfo:
        tds.store_attachment(io.BytesIO(big), "big.csv",
                             package_name=f"sub{sid}")
    message = str(excinfo.value)
    assert "MB" in message                   # ukurannya DISEBUT
    assert getattr(excinfo.value, "key", "") == "td.err_too_large"


def test_a_refused_oversized_file_is_not_left_on_disk(db, staging, package):
    sid = _insert_submission(db, package)
    big = b"x" * (tds.MAX_TRIAL_DATASET_BYTES + 1)
    with pytest.raises(tds.TrialDatasetError):
        tds.store_attachment(io.BytesIO(big), "big.csv",
                             package_name=f"sub{sid}")
    leftover = list((staging / f"sub{sid}").glob("*")) if (
        staging / f"sub{sid}").is_dir() else []
    assert leftover == []


# ── Sanitasi nama ────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "../escape.csv", "sub/dir.csv", "sub\\dir.csv", "..", ".",
    "spasi nama.csv", "aneh$.csv",
])
def test_an_unsafe_filename_is_refused(db, staging, package, name):
    sid = _insert_submission(db, package)
    with pytest.raises(tds.TrialDatasetError):
        tds.store_attachment(io.BytesIO(CSV_BYTES), name,
                             package_name=f"sub{sid}")


def test_an_unsupported_extension_is_refused(db, staging, package):
    sid = _insert_submission(db, package)
    with pytest.raises(tds.TrialDatasetError):
        tds.store_attachment(io.BytesIO(b"x"), "sample.exe",
                             package_name=f"sub{sid}")


def test_nothing_is_ever_written_outside_the_staging_area(db, staging,
                                                          package):
    """Sanitasi menolak, bukan memotong — jadi tidak ada berkas yang lolos."""
    sid = _insert_submission(db, package)
    for name in ("../escape.csv", "sub/dir.csv", "..\\..\\out.csv"):
        with pytest.raises(tds.TrialDatasetError):
            tds.store_attachment(io.BytesIO(CSV_BYTES), name,
                                 package_name=f"sub{sid}")
    assert not (staging.parent / "escape.csv").exists()
    assert not (staging.parent.parent / "out.csv").exists()


def test_a_second_attachment_never_overwrites_the_first(db, staging, package):
    sid = _insert_submission(db, package)
    first = tds.store_attachment(io.BytesIO(CSV_BYTES), "sample.csv",
                                 package_name=f"sub{sid}")
    second = tds.store_attachment(io.BytesIO(b"a,b\n1,2\n"), "sample.csv",
                                  package_name=f"sub{sid}")
    assert first["stored_path"] != second["stored_path"]
    assert Path(first["stored_path"]).read_bytes() == CSV_BYTES


# ── Isolasi dari kumpulan dataset platform ───────────────────────────────

def test_the_attachment_lives_outside_the_platform_dataset_folder(db, staging,
                                                                  package):
    from config.settings import DATASETS_DIR

    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    stored = Path(info["stored_path"]).resolve()
    assert not stored.is_relative_to(Path(DATASETS_DIR).resolve())


def test_the_attachment_never_appears_in_the_platform_dataset_list(db, staging,
                                                                   package):
    """Dataset platform dibaca dari folder datasets/; lampiran tidak ada di sana."""
    from config.settings import DATASETS_DIR

    before = sorted(p.name for p in Path(DATASETS_DIR).iterdir()
                    if p.suffix.lower() in (".csv", ".json", ".jsonl",
                                            ".ndjson"))
    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    after = sorted(p.name for p in Path(DATASETS_DIR).iterdir()
                   if p.suffix.lower() in (".csv", ".json", ".jsonl",
                                           ".ndjson"))
    assert after == before
    assert info["filename"] not in after


def test_the_attachment_cannot_be_chosen_for_an_experiment(db, staging,
                                                           package):
    """Daftar dataset untuk eksperimen tidak pernah memuat lampiran."""
    from orchestrator.validation_service import get_available_datasets

    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    available = get_available_datasets()
    assert all(info["filename"] not in str(entry) for entry in available)


def test_an_attachment_never_becomes_a_research_experiment(db, staging,
                                                           package):
    conn = sqlite3.connect(db)
    before = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    conn.close()

    sid = _insert_submission(db, package)
    _attach(db, sid)

    conn = sqlite3.connect(db)
    after = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    conn.close()
    assert after == before


def test_the_migration_is_additive():
    from database.migration import MIGRATIONS

    entry = next(m for m in MIGRATIONS if m["version"] == 25)
    assert "ALTER TABLE submissions ADD COLUMN" in entry["sql"]
    assert "experiments" not in entry["sql"]
    assert "DROP" not in entry["sql"].upper()


# ── Verifikasi hash ──────────────────────────────────────────────────────

def test_an_unchanged_attachment_verifies(db, staging, package):
    sid = _insert_submission(db, package)
    _attach(db, sid)
    path = tds.verify_attachment(_submission(db, sid))
    assert Path(path).read_bytes() == CSV_BYTES


def test_an_attachment_changed_after_submission_is_refused(db, staging,
                                                           package):
    """Menutup kemungkinan berkas ditukar setelah diajukan."""
    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    Path(info["stored_path"]).write_bytes(b"a,b,Label\n9,9,1\n")

    with pytest.raises(tds.TrialDatasetError) as excinfo:
        tds.verify_attachment(_submission(db, sid))
    assert getattr(excinfo.value, "key", "") == "td.err_hash_mismatch"


def test_a_missing_attachment_file_is_reported(db, staging, package):
    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    Path(info["stored_path"]).unlink()

    with pytest.raises(tds.TrialDatasetError) as excinfo:
        tds.verify_attachment(_submission(db, sid))
    assert getattr(excinfo.value, "key", "") == "td.err_file_missing"


def test_a_trial_on_a_changed_attachment_is_refused(db, staging, package):
    """Verifikasi terjadi SEBELUM pipeline dijalankan."""
    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    Path(info["stored_path"]).write_bytes(b"a,b,Label\n9,9,1\n")

    with pytest.raises(tds.TrialDatasetError):
        trial_service.run_trial(
            sid, dataset_type="HIKARI2021", actor=ADMIN,
            source=trial_service.SOURCE_ATTACHED, db_path=db)
    assert trial_db.list_trials(sid, db) == []    # tidak ada uji yang dimulai


# ── Jalur eksekusi & batas yang sama ─────────────────────────────────────

def test_a_trial_on_an_attachment_uses_the_same_runner_and_limits(
        db, staging, package, monkeypatch):
    """Jalur & batasnya SAMA dengan Tahap 1 — hanya path-nya yang berbeda."""
    import workers.trial_runner as runner_mod

    seen = {}

    def fake_run_bounded(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "metrics": {"accuracy": 0.5}, "rows_used": 3}

    monkeypatch.setattr(runner_mod, "run_bounded", fake_run_bounded)

    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    out = trial_service.run_trial(
        sid, dataset_type="HIKARI2021", actor=ADMIN,
        source=trial_service.SOURCE_ATTACHED, db_path=db)

    assert out["success"] is True
    # Path yang dipakai adalah berkas LAMPIRAN, bukan dataset platform.
    assert seen["dataset_path"] == info["stored_path"]
    # Batasnya sama persis dengan Tahap 1.
    assert seen["max_rows"] == trial_service.TRIAL_LIMITS["max_rows"]
    assert seen["max_seconds"] == trial_service.TRIAL_LIMITS["max_seconds"]


def test_there_is_no_second_execution_path():
    """Uji dengan lampiran memakai fungsi yang SAMA, bukan salinan."""
    src = (REPO_ROOT / "orchestrator" / "trial_service.py").read_text(
        encoding="utf-8")
    # Hanya SATU tempat yang memanggil pelaksana berbatas.
    assert src.count("run_bounded") == 2      # impor + pemanggilan
    assert src.count("def _execute_trial") == 1


# ── Melampirkan bersifat OPSIONAL ────────────────────────────────────────

def test_a_submission_without_an_attachment_still_works(db, staging, package):
    sid = _insert_submission(db, package)
    item = _submission(db, sid)
    assert tds.attachment_of(item) is None
    assert trial_service.trial_blocker(item) == ""   # tetap dapat diuji


def test_a_submission_without_an_attachment_can_still_be_trialled(
        db, staging, package, monkeypatch):
    """Jalur Tahap 1 tetap utuh."""
    import orchestrator.trial_service as ts

    sid = _insert_submission(db, package)
    monkeypatch.setattr(
        ts, "_execute_trial",
        lambda **kw: {"success": True, "trial_id": kw["trial_id"],
                      "metrics": {}, "duration_s": 0.1, "rows_used": 3})
    out = ts.run_trial(sid, dataset_type="HIKARI2021",
                       dataset_path="storage/datasets/x.csv", actor=ADMIN,
                       source=ts.SOURCE_PLATFORM, db_path=db)
    assert out["success"] is True


def test_running_a_trial_without_choosing_a_dataset_is_refused(db, staging,
                                                              package):
    sid = _insert_submission(db, package)
    with pytest.raises(trial_service.TrialError) as excinfo:
        trial_service.run_trial(sid, dataset_type="HIKARI2021",
                                dataset_path=None, actor=ADMIN, db_path=db)
    assert getattr(excinfo.value, "key", "") == "td.err_no_dataset_chosen"


# ── Izin ─────────────────────────────────────────────────────────────────

def test_a_contributor_may_attach_but_never_run_a_trial(db, staging, package):
    sid = _insert_submission(db, package)
    _attach(db, sid)                          # melampirkan: boleh

    for actor in (None, CONTRIBUTOR):         # menjalankan uji: tidak
        with pytest.raises(AuthError):
            trial_service.run_trial(
                sid, dataset_type="HIKARI2021", actor=actor,
                source=trial_service.SOURCE_ATTACHED, db_path=db)


# ── Jejak mencatat dataset mana yang dipakai ─────────────────────────────

def test_the_trail_records_which_dataset_was_used(db, staging, package,
                                                  monkeypatch):
    import orchestrator.trial_service as ts

    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    monkeypatch.setattr(
        ts, "_execute_trial",
        lambda **kw: {"success": True, "trial_id": kw["trial_id"],
                      "metrics": {}, "duration_s": 0.1, "rows_used": 3})
    ts.run_trial(sid, dataset_type="HIKARI2021", actor=ADMIN,
                 source=ts.SOURCE_ATTACHED, db_path=db)

    trail = ts.trial_trail(_submission(db, sid))
    assert trail["dataset_source"] == ts.SOURCE_ATTACHED
    assert trail["dataset_name"] == info["filename"]


# ── Pembersihan ──────────────────────────────────────────────────────────

def test_the_attachment_is_deleted_with_the_trial_results(db, staging,
                                                          package):
    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    stored = Path(info["stored_path"])
    assert stored.exists()

    trial_service.discard_trials(sid, db)
    assert not stored.exists()
    assert tds.attachment_of(_submission(db, sid)) is None


def test_a_decision_removes_the_attachment(db, staging, package, monkeypatch):
    from orchestrator import submission_service as ss

    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    ss.reject_submission(sid, actor=ADMIN, note="cukup", db_path=db)

    assert not Path(info["stored_path"]).exists()


def test_no_orphan_folder_survives_the_cleanup(db, staging, package):
    sid = _insert_submission(db, package)
    _attach(db, sid)
    trial_service.discard_trials(sid, db)

    assert tds.orphan_attachment_dirs(db) == []
    leftovers = list(staging.iterdir()) if staging.is_dir() else []
    assert leftovers == []


def test_purge_orphans_removes_folders_with_no_record(db, staging):
    stray = staging / "sub999"
    stray.mkdir(parents=True)
    (stray / "left.csv").write_bytes(CSV_BYTES)

    assert tds.purge_orphans(db) == 1
    assert not stray.exists()


# ── Pemeriksaan struktur memakai diagnosa yang sudah ada ─────────────────

def test_the_structure_check_uses_the_existing_diagnostics(db, staging,
                                                           package):
    sid = _insert_submission(db, package)
    info = _attach(db, sid)
    result = tds.inspect_attachment(info["stored_path"])
    assert "reports" in result
    for report in result["reports"]:
        assert "dataset_type" in report
        assert "compatible" in report


def test_the_structure_check_samples_rather_than_loading_everything():
    """Pemeriksaan memakai pembaca CUPLIKAN, bukan pemuat penuh."""
    src = (REPO_ROOT / "orchestrator" / "trial_dataset_service.py").read_text(
        encoding="utf-8")
    assert "diagnose_all" in src or "diagnose_dataset" in src
    assert "parse_dataset" not in src         # pemuat penuh tidak dipakai
