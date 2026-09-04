"""
Uji coba pipeline sebelum persetujuan — pengamannya, bukan sekadar fiturnya.

Fitur ini membalik aturan lama "kode yang belum disetujui tidak pernah
dijalankan". Yang diuji di sini karena itu bukan "uji coba berjalan",
melainkan bahwa setiap pengaman yang membuat pembalikan itu dapat diterima
benar-benar menahan beban:

* paket yang GAGAL pemeriksaan statis tidak dapat diuji sama sekali;
* hanya Research Admin yang dapat memicunya, ditegakkan di FUNGSI;
* persetujuan terkunci sampai uji berhasil — dan terkunci LAGI bila kodenya
  disunting sesudahnya (celah "uji versi bersih → sunting → setujui");
* hasil uji tidak pernah menjadi catatan penelitian;
* hasil uji terhapus setelah keputusan, tanpa berkas yatim;
* uji yang melampaui batas waktu dihentikan, bukan menggantung.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from database import trials as trial_db
from database.migration import apply_migrations
from database.models import (
    KIND_PIPELINE, SUBMISSION_APPROVED, SUBMISSION_PENDING,
)
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


# ── Basis data sementara ─────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Basis data terpisah: test ini tidak boleh menyentuh data penelitian."""
    path = tmp_path / "trial.db"
    apply_migrations(str(path))
    monkeypatch.setattr("database.db.DB_PATH", str(path), raising=False)
    return str(path)



@pytest.fixture
def small_csv():
    """Dataset kecil NYATA di dalam folder yang diizinkan.

    `resolve_dataset_path` hanya menerima berkas di dalam folder dataset
    platform, dan pengaman itu tetap berlaku bagi uji coba — jadi berkas
    bantu ini pun harus tinggal di sana.
    """
    import pandas as pd

    path = Path("storage/datasets/_trial_fixture.csv")
    pd.DataFrame({"a": range(20), "Label": [0, 1] * 10}).to_csv(
        path, index=False)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)

@pytest.fixture
def package(tmp_path):
    """Paket pengajuan di disk, dengan satu berkas titik masuk."""
    folder = tmp_path / "package"
    folder.mkdir()
    (folder / "trial_pipeline.py").write_text(PIPELINE_SOURCE, encoding="utf-8")
    return folder


def _insert_submission(db_path: str, package_dir: Path, *, valid: bool = True,
                       status: str = SUBMISSION_PENDING) -> int:
    """Satu pengajuan pipeline, dengan hasil validasi statis yang dipilih."""
    metadata = {"entry_filename": "trial_pipeline.py",
                "class_name": "TrialPipeline",
                "dataset_type": "HIKARI2021"}
    validation = {"valid": valid, "checks": []}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json,
                validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (KIND_PIPELINE, status, "andi", "2026-01-01T00:00:00",
             "trial_pipeline.py", str(package_dir), "a" * 64, 100,
             json.dumps(metadata), json.dumps(validation)))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _submission(db_path: str, submission_id: int) -> dict:
    from orchestrator.submission_service import get_submission

    return get_submission(submission_id, db_path)


def _fake_runner(*, ok=True, stage="menjalankan pipeline", kind="ValueError",
                 message="kolom Label tidak ada", metrics=None, rows=1000):
    """Pelaksana palsu: menguji ALUR, bukan pipeline pihak ketiga."""
    def runner(**kwargs):
        if ok:
            return {"ok": True, "metrics": metrics or {"accuracy": 0.9},
                    "rows_used": rows}
        return {"ok": False, "stage": stage, "kind": kind,
                "message": message, "rows_used": rows}
    return runner


def _run(db_path, submission_id, *, actor=ADMIN, runner=None, dataset="x.csv"):
    """Jalankan uji coba dengan pelaksana yang dapat dikendalikan test."""
    import orchestrator.trial_service as ts

    item = _submission(db_path, submission_id)
    ts.require_approve(actor, db_path)
    blocker = ts.trial_blocker(item)
    if blocker:
        raise ts.TrialError("ditolak pengaman", key=blocker)
    entry, entry_class, entry_hash = ts._entry_from_submission(item)
    trial_id = str(uuid.uuid4())
    from datetime import datetime

    started = datetime.now()
    trial_db.create_trial(
        trial_id=trial_id, submission_id=submission_id,
        package_hash=ts.submission_fingerprint(item),
        dataset_type="HIKARI2021", dataset_path=dataset,
        started_by=actor["username"],
        started_at=started.isoformat(timespec="seconds"), db_path=db_path)
    out = ts._execute_trial(
        trial_id=trial_id, entry_path=entry, entry_class=entry_class,
        entry_hash=entry_hash, dataset_type="HIKARI2021",
        dataset_path=dataset, started=started, db_path=db_path,
        runner=runner or _fake_runner())
    ts._record_trail(submission_id, db_path=db_path)
    return out


# ── Pengaman 1: validator tetap gerbang pertama ──────────────────────────

def test_a_package_that_failed_the_static_check_cannot_be_tested(db, package):
    sid = _insert_submission(db, package, valid=False)
    item = _submission(db, sid)
    assert trial_service.trial_blocker(item) == "trial.static_failed"


def test_a_package_with_no_validation_result_cannot_be_tested(db, package):
    """Ketiadaan bukti bukan bukti kelulusan."""
    sid = _insert_submission(db, package)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE submissions SET validation_json = NULL WHERE id = ?",
                 (sid,))
    conn.commit()
    conn.close()
    assert not trial_service.static_validation_passed(_submission(db, sid))


def test_a_passing_package_may_be_tested(db, package):
    sid = _insert_submission(db, package, valid=True)
    assert trial_service.trial_blocker(_submission(db, sid)) == ""


def test_a_decided_submission_cannot_be_tested(db, package):
    sid = _insert_submission(db, package, status=SUBMISSION_APPROVED)
    assert trial_service.trial_blocker(_submission(db, sid)) == "trial.not_pending"


# ── Pengaman 2: izin ditegakkan di FUNGSI ────────────────────────────────

def test_only_a_research_admin_may_trigger_a_trial(db, package):
    sid = _insert_submission(db, package)
    for actor in (None, CONTRIBUTOR):
        with pytest.raises(AuthError):
            trial_service.run_trial(sid, dataset_type="HIKARI2021",
                                    dataset_path="x.csv", actor=actor,
                                    db_path=db)


def test_the_permission_check_runs_before_anything_is_loaded(db, package):
    """Izin diperiksa SEBELUM berkas pengajuan disentuh."""
    sid = _insert_submission(db, package, valid=False)
    # Paketnya juga gagal validasi; yang harus muncul tetap AuthError, karena
    # izin adalah pemeriksaan pertama.
    with pytest.raises(AuthError):
        trial_service.run_trial(sid, dataset_type="HIKARI2021",
                                dataset_path="x.csv", actor=CONTRIBUTOR,
                                db_path=db)


# ── Gerbang persetujuan ──────────────────────────────────────────────────

def test_approval_is_blocked_before_any_trial(db, package):
    sid = _insert_submission(db, package)
    assert trial_service.approval_blocker(_submission(db, sid), db) == \
        "trial.gate_untested"
    assert not trial_service.may_approve(_submission(db, sid), db)


def test_approval_is_blocked_after_a_failed_trial(db, package):
    sid = _insert_submission(db, package)
    _run(db, sid, runner=_fake_runner(ok=False))
    assert trial_service.approval_blocker(_submission(db, sid), db) == \
        "trial.gate_failed"


def test_approval_is_allowed_after_a_passing_trial(db, package):
    sid = _insert_submission(db, package)
    _run(db, sid)
    assert trial_service.approval_blocker(_submission(db, sid), db) == ""
    assert trial_service.may_approve(_submission(db, sid), db)


def test_approving_without_a_trial_is_refused_at_the_function(db, package,
                                                              monkeypatch):
    """Gerbangnya di FUNGSI — menonaktifkan tombol saja tidak cukup."""
    from orchestrator import submission_service as ss

    sid = _insert_submission(db, package)
    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    with pytest.raises(ss.SubmissionError) as excinfo:
        ss.approve_submission(sid, actor=ADMIN, dataset_type="HIKARI2021",
                              db_path=db)
    assert getattr(excinfo.value, "key", "") == "trial.gate_untested"


# ── CELAH: sunting setelah uji berhasil ──────────────────────────────────

def test_editing_after_a_passing_trial_invalidates_it(db, package):
    """Celah "uji versi bersih → sunting → setujui" harus tertutup."""
    sid = _insert_submission(db, package)
    _run(db, sid)
    assert trial_service.may_approve(_submission(db, sid), db)

    # Satu karakter pun cukup.
    entry = package / "trial_pipeline.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# disunting\n",
                     encoding="utf-8")

    assert trial_service.approval_blocker(_submission(db, sid), db) == \
        "trial.gate_stale"
    assert not trial_service.may_approve(_submission(db, sid), db)


def test_forcing_approve_after_an_edit_is_refused(db, package, monkeypatch):
    from orchestrator import submission_service as ss

    sid = _insert_submission(db, package)
    _run(db, sid)
    entry = package / "trial_pipeline.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# disunting\n",
                     encoding="utf-8")

    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    with pytest.raises(ss.SubmissionError) as excinfo:
        ss.approve_submission(sid, actor=ADMIN, dataset_type="HIKARI2021",
                              db_path=db)
    assert getattr(excinfo.value, "key", "") == "trial.gate_stale"


def test_a_new_trial_restores_approval_after_an_edit(db, package):
    sid = _insert_submission(db, package)
    _run(db, sid)
    entry = package / "trial_pipeline.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# disunting\n",
                     encoding="utf-8")
    assert not trial_service.may_approve(_submission(db, sid), db)

    _run(db, sid)                            # diuji ulang pada kode yang baru
    assert trial_service.may_approve(_submission(db, sid), db)


def test_the_fingerprint_matches_the_editors(db):
    """Ukuran "masih berlaku" harus sama dengan yang dipakai penyunting."""
    from ui.views.manage_pipelines import package_fingerprint as editor

    files = {"a.py": "x = 1", "b.py": "y = 2"}
    assert trial_service.package_fingerprint(files) == editor(files)


# ── Menolak tidak memerlukan uji ─────────────────────────────────────────

def test_rejecting_never_requires_a_trial(db, package, monkeypatch):
    from orchestrator import submission_service as ss

    sid = _insert_submission(db, package)
    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    result = ss.reject_submission(sid, actor=ADMIN, note="tidak sesuai",
                                  db_path=db)
    assert result["status"] == "rejected"


# ── Isolasi dari data penelitian ─────────────────────────────────────────

def _experiment_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    finally:
        conn.close()


def test_a_trial_never_becomes_a_research_experiment(db, package):
    before = _experiment_count(db)
    sid = _insert_submission(db, package)
    _run(db, sid)
    _run(db, sid, runner=_fake_runner(ok=False))
    assert _experiment_count(db) == before


def test_trials_live_in_their_own_table(db, package):
    sid = _insert_submission(db, package)
    _run(db, sid)
    assert len(trial_db.list_trials(sid, db)) == 1
    assert _experiment_count(db) == 0


def test_no_query_of_experiments_can_see_a_trial(db, package):
    """Isolasinya STRUKTURAL: datanya memang tidak ada di sana."""
    from database.db import list_experiments

    sid = _insert_submission(db, package)
    _run(db, sid)
    assert list_experiments(db) == []


def test_the_experiments_table_was_not_altered():
    """Migrasi ini ADITIF: tabel eksperimen tidak disentuh sama sekali."""
    from database.migration import MIGRATIONS

    for migration in MIGRATIONS:
        if migration["version"] in (23, 24):
            assert "ALTER TABLE experiments" not in migration["sql"]
            assert "DROP" not in migration["sql"].upper()


# ── Jejak ringkas pada pengajuan ─────────────────────────────────────────

def test_the_trial_trail_is_recorded_on_the_submission(db, package):
    sid = _insert_submission(db, package)
    _run(db, sid)
    trail = trial_service.trial_trail(_submission(db, sid))
    assert trail is not None
    assert trail["started_by"] == ADMIN["username"]
    assert trail["status"] == trial_db.STATUS_PASSED
    assert trail["dataset_type"] == "HIKARI2021"
    assert trail["metrics"]


def test_the_trail_records_a_failure_in_full(db, package):
    """Jejak menyimpan tahap, jenis, dan pesan — bukan "uji gagal" saja."""
    sid = _insert_submission(db, package)
    _run(db, sid, runner=_fake_runner(
        ok=False, stage="membaca dataset", kind="KeyError",
        message="kolom 'Label' tidak ditemukan"))
    trail = trial_service.trial_trail(_submission(db, sid))
    assert trail["error_stage"] == "membaca dataset"
    assert trail["error_kind"] == "KeyError"
    assert "Label" in trail["error_message"]


# ── Pembersihan ──────────────────────────────────────────────────────────

def test_trials_are_discarded_after_a_decision(db, package, monkeypatch):
    from orchestrator import submission_service as ss

    sid = _insert_submission(db, package)
    _run(db, sid)
    assert trial_db.list_trials(sid, db)

    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    ss.reject_submission(sid, actor=ADMIN, note="cukup", db_path=db)
    assert trial_db.list_trials(sid, db) == []


def test_the_trail_survives_the_cleanup(db, package, monkeypatch):
    """Catatan sementara hilang; jejak ringkasnya tetap — itu memang niatnya."""
    from orchestrator import submission_service as ss

    sid = _insert_submission(db, package)
    _run(db, sid)
    monkeypatch.setattr(ss, "require_approve", lambda *a, **k: None)
    ss.reject_submission(sid, actor=ADMIN, note="cukup", db_path=db)

    assert trial_db.list_trials(sid, db) == []
    assert trial_service.trial_trail(_submission(db, sid)) is not None


def test_discarding_removes_the_artifact_folder(db, package, tmp_path,
                                                monkeypatch):
    monkeypatch.setattr(trial_service, "TRIAL_ROOT", tmp_path / "trials")
    sid = _insert_submission(db, package)
    _run(db, sid)

    trial = trial_db.latest_trial(sid, db)
    folder = (tmp_path / "trials") / trial["id"]
    folder.mkdir(parents=True)
    (folder / "metrics.json").write_text("{}", encoding="utf-8")

    trial_service.discard_trials(sid, db)
    assert not folder.exists()


def test_no_orphan_folder_is_left_behind(db, package, tmp_path, monkeypatch):
    monkeypatch.setattr(trial_service, "TRIAL_ROOT", tmp_path / "trials")
    sid = _insert_submission(db, package)
    _run(db, sid)
    trial = trial_db.latest_trial(sid, db)
    folder = (tmp_path / "trials") / trial["id"]
    folder.mkdir(parents=True)

    trial_service.discard_trials(sid, db)
    assert trial_service.orphan_trial_dirs(db) == []


def test_stale_trials_are_cleaned_up(db, package):
    """Peninjauan yang tidak kunjung diputuskan tidak menimbun hasil uji."""
    sid = _insert_submission(db, package)
    _run(db, sid)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE pipeline_trials SET started_at = ?",
                 ("2020-01-01T00:00:00",))
    conn.commit()
    conn.close()

    assert trial_service.cleanup_stale_trials(hours=24, db_path=db) == 1
    assert trial_db.list_trials(sid, db) == []


def test_a_recent_trial_survives_the_stale_cleanup(db, package):
    sid = _insert_submission(db, package)
    _run(db, sid)
    assert trial_service.cleanup_stale_trials(hours=24, db_path=db) == 0
    assert len(trial_db.list_trials(sid, db)) == 1


# ── Batas sumber daya ────────────────────────────────────────────────────

def test_the_trial_limits_are_stricter_than_a_normal_experiment():
    """Uji coba menjawab "apakah ini berjalan", bukan "berapa skornya"."""
    import re

    limits = trial_service.TRIAL_LIMITS
    worker = (REPO_ROOT / "workers" / "celery_worker.py").read_text(
        encoding="utf-8")
    soft = int(re.search(r"soft_time_limit=(\d+)", worker).group(1))
    assert limits["max_seconds"] < soft
    assert limits["max_rows"] > 0


def test_a_trial_that_overruns_is_stopped_not_left_hanging(small_csv):
    """Tenggatnya DIPAKSA di proses anak — bukan sekadar diharapkan.

    Pipelinenya tidur jauh melewati tenggat; tanpa pemaksaan, panggilan ini
    tidak akan pernah kembali dan peninjauan tertahan selamanya.
    """
    from workers import trial_runner

    path = REPO_ROOT / "tests" / "_trial_sleeper.py"
    outcome = trial_runner.run_bounded(
        entry_file=str(path), entry_class="SleeperPipeline",
        entry_hash=_sha256(path), dataset_type="HIKARI2021",
        dataset_path=str(small_csv), max_rows=10, max_seconds=5)

    assert outcome["ok"] is False
    assert outcome["stage"] == trial_runner.STAGE_TIMEOUT
    assert "5" in outcome["message"]


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_row_cap_is_applied_before_the_pipeline_sees_the_data(tmp_path):
    """Batas baris ditegakkan saat membaca, bukan sesudahnya."""
    import pandas as pd

    from workers.trial_runner import read_trial_dataset

    csv = Path("storage/datasets/_trial_rowcap_test.csv")
    pd.DataFrame({"a": range(500), "Label": [0, 1] * 250}).to_csv(
        csv, index=False)
    try:
        df = read_trial_dataset(str(csv), max_rows=50)
        assert len(df) == 50
    finally:
        csv.unlink(missing_ok=True)


# ── Kegagalan dilaporkan spesifik ────────────────────────────────────────

def test_a_failing_pipeline_reports_the_stage_and_the_kind(db, package):
    sid = _insert_submission(db, package)
    out = _run(db, sid, runner=_fake_runner(
        ok=False, stage="menjalankan pipeline", kind="NotImplementedError",
        message="run() belum diimplementasi"))

    assert out["success"] is False
    assert out["stage"] == "menjalankan pipeline"
    assert out["kind"] == "NotImplementedError"
    assert "run()" in out["message"]


def test_the_failure_message_is_never_flattened(db, package):
    """"Uji gagal" saja membuang justru informasi yang dicari peninjau."""
    sid = _insert_submission(db, package)
    detail = "KeyError pada kolom 'flow_duration' saat praproses"
    _run(db, sid, runner=_fake_runner(ok=False, message=detail))
    trial = trial_db.latest_trial(sid, db)
    assert trial["error_message"] == detail


def test_a_real_pipeline_failure_carries_its_own_message(small_csv):
    """Pipeline yang sengaja gagal saat BERJALAN, lewat pelaksana sungguhan."""
    from workers import trial_runner

    path = REPO_ROOT / "tests" / "_trial_broken.py"
    outcome = trial_runner.run_bounded(
        entry_file=str(path), entry_class="BrokenPipeline",
        entry_hash=_sha256(path), dataset_type="HIKARI2021",
        dataset_path=str(small_csv), max_rows=10, max_seconds=60)

    assert outcome["ok"] is False
    assert outcome["kind"], "jenis kesalahan harus disebut"
    assert outcome["stage"], "tahap harus disebut"
    assert outcome["message"], "pesan harus disebut"


# ── Pemuatan tanpa pendaftaran ───────────────────────────────────────────

def test_a_trial_never_registers_the_pipeline(db, package):
    """Pipeline yang diuji TIDAK menjadi pipeline aktif."""
    sid = _insert_submission(db, package)
    _run(db, sid)
    conn = sqlite3.connect(db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM registered_pipelines").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_the_loader_verifies_the_hash_before_executing(package):
    """Berkas yang berubah ditolak SEBELUM kodenya dijalankan."""
    from orchestrator.dynamic_registry import DynamicRegistryError, load_pipeline_class

    entry = package / "trial_pipeline.py"
    stale_hash = _sha256(entry)
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# berubah\n",
                     encoding="utf-8")

    with pytest.raises(DynamicRegistryError):
        load_pipeline_class(entry, "TrialPipeline", stale_hash)


# ── Jalur PREFETCH tidak boleh melonggarkan gerbang ──────────────────────
# Halaman peninjauan kini mengambil uji terakhir SELURUH antrean dalam satu
# kueri lalu menyodorkannya ke gerbang, supaya biayanya tidak tumbuh mengikuti
# panjang antrean. Yang dihemat HANYA pembacaan barisnya; sidik jari paket
# tetap dihitung ulang di dalam gerbang. Tanpa itu, "uji bersih lalu sunting
# lalu setujui" terbuka kembali lewat pintu belakang.

def test_the_gate_still_catches_an_edit_when_the_trial_is_prefetched(db, package):
    from database import trials as trial_db

    sid = _insert_submission(db, package)
    _run(db, sid)
    item = _submission(db, sid)

    prefetched = trial_db.latest_trials_for([sid], db)[sid]
    assert trial_service.approval_blocker(item, db, trial=prefetched) == ""

    entry = package / "trial_pipeline.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# disunting\n",
                     encoding="utf-8")

    # Baris uji yang disodorkan SENGAJA yang lama — persis keadaan yang
    # dialami halaman: barisnya diambil sebelum berkasnya disunting.
    assert trial_service.approval_blocker(item, db, trial=prefetched) == \
        "trial.gate_stale"


def test_the_prefetched_gate_agrees_with_the_unprefetched_one(db, package):
    """Menyodorkan uji tidak boleh mengubah JAWABAN, hanya pembacaannya."""
    from database import trials as trial_db

    sid = _insert_submission(db, package)
    item = _submission(db, sid)

    # (a) belum pernah diuji
    pre = trial_db.latest_trials_for([sid], db).get(sid)
    assert trial_service.approval_blocker(item, db, trial=pre) == \
        trial_service.approval_blocker(item, db)

    # (b) sudah diuji dan lolos
    _run(db, sid)
    item = _submission(db, sid)
    pre = trial_db.latest_trials_for([sid], db).get(sid)
    assert trial_service.approval_blocker(item, db, trial=pre) == \
        trial_service.approval_blocker(item, db) == ""

    # (c) berkas disunting sesudahnya
    entry = package / "trial_pipeline.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# x\n",
                     encoding="utf-8")
    pre = trial_db.latest_trials_for([sid], db).get(sid)
    assert trial_service.approval_blocker(item, db, trial=pre) == \
        trial_service.approval_blocker(item, db) == "trial.gate_stale"


def test_the_batched_reader_picks_the_same_trial_as_the_single_one(db, package):
    """Pemenangnya harus SAMA — termasuk pemutus seri `rowid`.

    Kalau keduanya berbeda, "uji terakhir" versi daftar dan versi kartu dapat
    menunjuk baris yang berlainan, dan gerbang ikut salah.
    """
    from database import trials as trial_db

    sid = _insert_submission(db, package)
    _run(db, sid)
    _run(db, sid)                            # uji kedua pada detik yang sama

    single = trial_db.latest_trial(sid, db)
    batched = trial_db.latest_trials_for([sid], db)[sid]
    assert batched["id"] == single["id"]


def test_the_batched_reader_omits_submissions_without_trials(db, package):
    from database import trials as trial_db

    sid = _insert_submission(db, package)
    assert trial_db.latest_trials_for([sid], db) == {}
    assert trial_db.latest_trials_for([], db) == {}


def test_the_detail_view_reads_one_submission_and_gates_the_same(db, package):
    """Jalur DETAIL master-detail membaca uji untuk SATU pengajuan saja.

    Bentuk panggilannya persis yang dipakai tampilan detail
    (`latest_trials_for([id])` lalu disodorkan ke gerbang). Yang diuji: membaca
    lebih sempit tidak mengubah jawaban gerbang — termasuk setelah berkasnya
    disunting.
    """
    from database import trials as trial_db

    sid = _insert_submission(db, package)
    _run(db, sid)
    item = _submission(db, sid)

    one = trial_db.latest_trials_for([sid], db)          # jalur detail
    whole = trial_db.latest_trials_for([sid, sid + 99], db)   # jalur daftar
    assert one[sid]["id"] == whole[sid]["id"]
    assert trial_service.approval_blocker(item, db, trial=one[sid]) == ""

    entry = package / "trial_pipeline.py"
    entry.write_text(entry.read_text(encoding="utf-8") + "\n# disunting\n",
                     encoding="utf-8")
    assert trial_service.approval_blocker(item, db, trial=one[sid]) == \
        "trial.gate_stale"
