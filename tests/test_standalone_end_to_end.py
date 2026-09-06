"""Unggah → uji → setujui → muncul di Jalankan Eksperimen → JALAN.

Sampai perbaikan ini, sebuah research pipeline yang berdiri sendiri **tidak
akan pernah dapat disetujui**, jadi ia tidak pernah terdaftar, tidak pernah
muncul di halaman Jalankan Eksperimen, dan tidak pernah dapat dijalankan.
Jawabannya melingkar:

    approve_submission  butuh  uji coba LULUS
      └─ uji coba       butuh  dataset_type yang dapat dipakai
           └─ dataset_type dibuat  saat approve_submission

Dan sebuah kunci kedua di belakangnya: pelaksana uji mencari skemanya di tabel
``research_pipelines``, yang baru terisi setelah persetujuan.

Keduanya dibuka dengan MENGHITUNG identitas dari pengajuannya sendiri — namanya
membentuk pengenalnya, kontrak datasetnya sudah dideklarasikan — bukan dengan
mendaftarkan apa pun lebih awal, dan bukan dengan melonggarkan gerbangnya.

Modul ini menjaga seluruh rantai itu sebagai SATU test. Menguji tiap mata
rantai sendiri-sendiri tidak akan menangkap kebuntuan seperti ini: setiap
bagiannya benar, yang salah adalah urutannya.
"""
from __future__ import annotations

import csv
import random
import shutil
import sys
from pathlib import Path

import pytest

from database.migration import apply_migrations
from database.models import (
    KIND_PIPELINE, SUBMISSION_APPROVED, SUBMISSION_PENDING, SUBMISSION_REJECTED,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
USER = {"username": "andi", "role": "kontributor", "status": "active"}
ADMIN = {"username": "boss", "role": "research_admin", "status": "active"}

#: Pipeline yang BENAR-BENAR melatih model — bukan boneka yang mengembalikan
#: angka tetap. Kalau ia boneka, "berhasil dijalankan" tidak membuktikan apa pun
#: tentang jalur eksekusi yang sesungguhnya.
PIPELINE_SRC = '''
from pipelines.base import BasePipeline
from contracts.pipeline_contracts import PipelineResult


class KontribRFPipeline(BasePipeline):
    def run(self, pipeline_input, progress=None):
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (accuracy_score, confusion_matrix,
                                     f1_score, precision_score, recall_score)
        from sklearn.model_selection import train_test_split

        self._emit_progress(progress, "Preprocessing")
        df = pipeline_input.df
        label = pipeline_input.label_column
        y = df[label]
        X = df.drop(columns=[label]).select_dtypes(include="number")

        self._emit_progress(progress, "Training")
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.3, stratify=y, random_state=42)
        model = RandomForestClassifier(n_estimators=25, random_state=42)
        model.fit(X_tr, y_tr)

        self._emit_progress(progress, "Evaluating")
        pred = model.predict(X_te)
        return PipelineResult(
            accuracy=float(accuracy_score(y_te, pred)),
            precision=float(precision_score(y_te, pred, average="weighted",
                                            zero_division=0)),
            recall=float(recall_score(y_te, pred, average="weighted",
                                      zero_division=0)),
            f1_score=float(f1_score(y_te, pred, average="weighted",
                                    zero_division=0)),
            confusion_matrix=confusion_matrix(y_te, pred).tolist(),
            model=model,
            feature_names=list(X.columns),
            label_mapping={str(v): int(i)
                           for i, v in enumerate(sorted(y.unique()))},
        )

    def get_info(self):
        return {
            "paper": "Budi (2026), UNHAS",
            "algorithm": "Random Forest",
            "preprocessing_steps": ["Ambil kolom numerik"],
            "feature_selection": "None",
            "fixed_params": {"n_estimators": 25, "random_state": 42},
            "train_test_split": {"test_size": 0.3, "stratify": True,
                                 "random_state": 42},
        }
'''

SCHEMA = {"label_column": "attack",
          "expected_columns": ["f1", "f2", "f3", "attack"],
          "file_format": "csv"}

METADATA = {
    "name": "Deteksi Anomali",
    "algorithm": "Random Forest",
    "paper": "Budi (2026), UNHAS",
    "declared_schema": SCHEMA,
    "entry_class": "KontribRFPipeline",
    "algorithms": [{"filename": "kontrib_rf.py",
                    "class_name": "KontribRFPipeline",
                    "algorithm": "Random Forest"}],
}


def _dataset(path: Path, rows: int = 300) -> Path:
    """Dataset kecil yang BISA dipelajari — dua kelas yang benar-benar berbeda.

    Kalau labelnya acak, pipeline yang benar pun menghasilkan skor seperti
    menebak, dan test ini akan lulus/gagal karena keberuntungan.
    """
    rng = random.Random(7)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["f1", "f2", "f3", "attack"])
        for i in range(rows):
            label = i % 2
            writer.writerow([rng.gauss(label, 1), rng.gauss(label * 2, 1),
                             rng.random(), label])
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Lingkungan lengkap: basis data, area penampungan, dua akun nyata.

    Area penampungan dan dataset lampiran diletakkan DI DALAM proyek: pengaman
    lokasi berkas menolak jalur di luarnya, dan menonaktifkan pengaman itu akan
    membuat test ini menguji sesuatu yang tidak pernah terjadi di aplikasi.
    """
    from database.db import get_connection
    from orchestrator import submission_service as ss
    from orchestrator import trial_dataset_service as tds

    db = tmp_path / "e2e.db"
    apply_migrations(str(db))
    monkeypatch.setattr("database.db.DB_PATH", str(db), raising=False)
    monkeypatch.setattr("config.settings.DB_PATH", str(db), raising=False)

    base = REPO_ROOT / "storage" / "_diag_probe" / f"e2e_{tmp_path.name}"
    roots = {status: base / status
             for status in (SUBMISSION_PENDING, SUBMISSION_APPROVED,
                            SUBMISSION_REJECTED)}
    for folder in roots.values():
        folder.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(ss.SUBMISSION_DIRS, KIND_PIPELINE, roots)
    monkeypatch.setattr(tds, "TRIAL_DATASET_ROOT", base / "trial_datasets")

    conn = get_connection(str(db))
    try:
        for name, role in (("andi", "kontributor"), ("boss", "research_admin")):
            conn.execute(
                "INSERT INTO users (username, password_hash, role, status,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (name, "x", role, "active", "2026-01-01"))
        conn.commit()
    finally:
        conn.close()

    yield {"db": str(db), "tmp": tmp_path, "base": base}
    shutil.rmtree(base, ignore_errors=True)


def _submit(env) -> dict:
    """Ajukan paket + lampirkan datasetnya, lewat layanan yang sebenarnya."""
    from orchestrator import submission_service as ss
    from orchestrator import trial_dataset_service as tds

    sub = ss.submit_pipeline(
        [("kontrib_rf.py", PIPELINE_SRC)], "kontrib_rf.py", user=USER,
        metadata=dict(METADATA),
        validation={"valid": True, "entry_points": ["kontrib_rf.py"]},
        db_path=env["db"])
    data = _dataset(env["tmp"] / "anomali.csv")
    with data.open("rb") as fh:
        info = tds.store_attachment(fh, "anomali.csv",
                                    package_name="deteksi_anomali",
                                    note="dataset penelitian ini")
    tds.attach_to_submission(sub["id"], info, db_path=env["db"])
    return ss.get_submission(sub["id"], env["db"])


# ── Kedua kunci kebuntuan ────────────────────────────────────────────────

def test_the_dataset_type_is_known_before_approval(env):
    """Kunci pertama: pengenalnya DIHITUNG dari pengajuan, bukan dicari."""
    from orchestrator import trial_service as ts

    item = _submit(env)
    assert ts.resolve_dataset_type(item, ts.SOURCE_ATTACHED) == \
        "uploaded:deteksi_anomali"
    assert ts.dataset_type_blocker(item, ts.SOURCE_ATTACHED) == ""


def test_the_schema_is_known_before_approval(env):
    """Kunci kedua: skemanya berasal dari deklarasi pengajuan."""
    from orchestrator import trial_service as ts

    assert ts.planned_schema(_submit(env)) == SCHEMA


def test_nothing_is_registered_before_approval(env):
    """DIHITUNG, bukan didaftarkan lebih awal: persetujuan tetap satu-satunya
    tempat identitas itu benar-benar tercatat."""
    from orchestrator import dynamic_registry as dr
    from orchestrator import research_registry as rr

    item = _submit(env)
    from orchestrator import trial_service as ts

    assert ts.resolve_dataset_type(item, ts.SOURCE_ATTACHED)   # sudah terjawab…
    assert rr.list_research(db_path=env["db"]) == []           # …tanpa satu baris
    assert dr.list_registered(db_path=env["db"]) == []


def test_a_hitchhiking_submission_is_untouched(env):
    """Pengajuan LAMA yang menumpang jenis bawaan tidak berubah perilakunya."""
    from orchestrator import submission_service as ss
    from orchestrator import trial_service as ts

    meta = {k: v for k, v in METADATA.items() if k != "declared_schema"}
    meta["dataset_type"] = "HIKARI2021"
    sub = ss.submit_pipeline(
        [("kontrib_rf.py", PIPELINE_SRC)], "kontrib_rf.py", user=USER,
        metadata=meta, validation={"valid": True}, db_path=env["db"])
    item = ss.get_submission(sub["id"], env["db"])

    assert not ss.is_standalone(item)
    assert ts.planned_dataset_type(item) == ""      # tidak ada yang direncanakan
    assert ts.planned_schema(item) == {}            # pelaksana mencari sendiri
    assert ts.resolve_dataset_type(item, ts.SOURCE_ATTACHED) == "HIKARI2021"


# ── Rantai penuh ─────────────────────────────────────────────────────────

@pytest.mark.skipif(sys.platform not in ("win32", "linux", "darwin"),
                    reason="pelaksana uji memakai proses anak")
def test_the_whole_chain_from_upload_to_a_real_run(env):
    """SATU test untuk seluruh rantai — karena yang rusak adalah urutannya.

    Tidak satu pun gerbang dipalsukan di sini: uji coba benar-benar dijalankan,
    dan persetujuan benar-benar melewati `approval_blocker`.
    """
    from orchestrator import research_registry as rr
    from orchestrator import submission_service as ss
    from orchestrator import trial_service as ts
    from orchestrator.experiment_service import create_and_run_experiment
    from orchestrator.validation_service import (get_available_datasets,
                                                 validate_for_experiment)
    from ui.views.run_experiment import _list_dataset_files

    item = _submit(env)

    # 1. Uji coba — sungguhan, dengan dataset kontributornya sendiri.
    outcome = ts.run_trial(item["id"], source=ts.SOURCE_ATTACHED, actor=ADMIN,
                           db_path=env["db"])
    assert outcome["success"], outcome
    assert outcome["metrics"]["accuracy"] > 0.6, "modelnya tidak belajar apa pun"

    # 2. Persetujuan — gerbangnya ASLI.
    item = ss.get_submission(item["id"], env["db"])
    assert ts.approval_blocker(item, env["db"]) == ""
    assert ss.approve_submission(item["id"], actor=ADMIN, note="lolos",
                                 db_path=env["db"])["status"] == \
        SUBMISSION_APPROVED

    # 3. Muncul sebagai research pipeline tersendiri.
    dataset_type = rr.list_research(db_path=env["db"])[0]["dataset_type"]
    assert dataset_type == "uploaded:deteksi_anomali"
    assert dataset_type in get_available_datasets()

    # 4. Dataset yang ditawarkan untuknya adalah MILIKNYA, bukan milik platform.
    files = _list_dataset_files(dataset_type)
    assert len(files) == 1
    assert Path(files[0]).name.startswith("anomali")

    # 5. Lolos validasi, dan ia yang muncul sebagai pipeline yang cocok.
    prepared = validate_for_experiment(dataset_type, files[0])
    assert prepared["success"], prepared["error"]
    compatible = list(prepared["compatible_pipelines"] or {})
    assert compatible == ["uploaded.deteksi_anomali@v1"]

    # 6. Benar-benar dijalankan, lewat jalur eksperimen yang sama.
    result = create_and_run_experiment(dataset_type, files[0], compatible[0],
                                       owner="boss")
    assert result["success"], result.get("error")
    assert result["metrics"]["accuracy"] > 0.6

    from orchestrator.result_service import list_all_experiments
    rows = list_all_experiments()
    assert [r["pipeline_id"] for r in rows] == ["uploaded.deteksi_anomali@v1"]
    assert rows[0]["status"] == "FINISHED"


# ── Yang TIDAK boleh ikut terbuka ────────────────────────────────────────

def test_a_standalone_pipeline_refuses_a_platform_dataset(env):
    """Meluluskannya atas dataset platform membuat "sudah diuji" berbicara
    tentang data yang tidak akan pernah ia pakai — lebih berbahaya daripada
    tidak diuji, karena ia terbaca sebagai bukti."""
    from orchestrator import trial_service as ts

    item = _submit(env)
    with pytest.raises(ts.TrialError) as excinfo:
        ts._resolve_dataset(item, ts.SOURCE_PLATFORM, "storage/datasets/x.csv")
    assert excinfo.value.key == "td.err_standalone_needs_own_dataset"


def test_the_view_hides_the_platform_option_but_is_not_the_only_guard():
    """Menyembunyikan pilihan tidak pernah menjadi satu-satunya penghalang."""
    view = (REPO_ROOT / "ui" / "views" / "contribute.py").read_text(
        encoding="utf-8")
    assert "sources = [] if standalone else" in view

    service = (REPO_ROOT / "orchestrator" / "trial_service.py").read_text(
        encoding="utf-8")
    body = service.split("def _resolve_dataset(")[1].split(chr(10) + "def ")[0]
    assert "td.err_standalone_needs_own_dataset" in body


def test_the_approval_gate_itself_was_not_loosened():
    """Yang dibuka adalah kemampuan MENGUJI — bukan gerbangnya."""
    service = (REPO_ROOT / "orchestrator" / "trial_service.py").read_text(
        encoding="utf-8")
    gate = service.split("def approval_blocker(")[1].split(chr(10) + "def ")[0]
    for rule in ("trial.gate_untested", "trial.gate_failed", "trial.gate_stale"):
        assert rule in gate, rule


def test_the_schema_that_crosses_to_the_child_is_picklable():
    """Pelaksana uji berjalan di proses anak yang di-`spawn`."""
    import pickle

    assert pickle.loads(pickle.dumps(SCHEMA)) == SCHEMA

    runner = (REPO_ROOT / "workers" / "trial_runner.py").read_text(
        encoding="utf-8")
    body = runner.split("def run_bounded(")[1].split(chr(10) + "def ")[0]
    assert "dict(schema) if schema else None" in body


def test_the_runner_still_looks_up_a_schema_when_none_is_given():
    """Pemanggil lama — termasuk pipeline bawaan — tidak berubah perilakunya."""
    runner = (REPO_ROOT / "workers" / "trial_runner.py").read_text(
        encoding="utf-8")
    body = runner.split("def run_trial_pipeline(")[1].split(chr(10) + "def ")[0]
    assert "if not schema:" in body
    assert "schema_for(dataset_type)" in body
