"""Bantuan test: catat uji coba yang BERHASIL untuk sebuah pengajuan.

Persetujuan kini bergerbang uji coba. Test lama yang menguji hal LAIN
(pemindahan berkas, pendaftaran versi, pencatatan keputusan) tetap perlu
melewati gerbang itu — helper ini menyiapkan prasyaratnya tanpa mengaburkan
apa yang sebenarnya sedang diuji.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from database import trials as trial_db


def pass_trial(submission_id: int, db_path: str, *,
               who: str = "boss", dataset_type: str = "HIKARI2021") -> str:
    """Catat satu uji coba BERHASIL pada isi paket saat ini."""
    from orchestrator.submission_service import get_submission
    from orchestrator.trial_service import submission_fingerprint

    item = get_submission(submission_id, db_path)
    trial_id = str(uuid.uuid4())
    now = datetime.now().isoformat(timespec="seconds")
    trial_db.create_trial(
        trial_id=trial_id, submission_id=submission_id,
        package_hash=submission_fingerprint(item),
        dataset_type=dataset_type, dataset_path="uji.csv",
        started_by=who, started_at=now, db_path=db_path)
    trial_db.finish_trial(
        trial_id, status=trial_db.STATUS_PASSED, finished_at=now,
        duration_s=1.0, rows_used=100, metrics={"accuracy": 0.9},
        db_path=db_path)
    return trial_id
