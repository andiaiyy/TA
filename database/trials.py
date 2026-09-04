"""
Catatan uji coba pipeline — TERPISAH dari eksperimen penelitian.

Hasil uji coba tidak pernah masuk ke tabel ``experiments``. Itu keputusan
struktur, bukan sekadar konvensi: selama datanya tidak ada di sana, tidak ada
kueri riwayat, perbandingan, ekspor, atau hitungan statistik yang perlu
mengingat sebuah penyaring agar hasil skripsi tetap bersih. Menambahkan baris
ke ``experiments`` dengan penanda akan membalik bebannya — setiap kueri baru
menjadi kesempatan baru untuk mencemari data penelitian.

Catatan di sini SEMENTARA. Ia hidup selama peninjauan berlangsung, lalu
dihapus begitu keputusan diambil; yang bertahan hanyalah jejak ringkas pada
pengajuannya (lihat ``orchestrator.trial_service``).
"""
from __future__ import annotations

import json
import logging

from database.db import get_connection

logger = logging.getLogger(__name__)

STATUS_QUEUED = "QUEUED"
STATUS_RUNNING = "RUNNING"
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"

#: Status yang berarti "sudah selesai, apa pun hasilnya".
TERMINAL = (STATUS_PASSED, STATUS_FAILED)


def _row_to_dict(row) -> dict:
    item = dict(row)
    raw = item.pop("metrics_json", None)
    try:
        item["metrics"] = json.loads(raw) if raw else None
    except (TypeError, ValueError):          # pragma: no cover - defensive
        item["metrics"] = None
    return item


def create_trial(*, trial_id: str, submission_id: int, package_hash: str,
                 dataset_type: str, dataset_path: str, started_by: str,
                 started_at: str, db_path: str | None = None) -> None:
    """Catat sebuah uji coba yang baru dimulai."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO pipeline_trials
               (id, submission_id, package_hash, dataset_type, dataset_path,
                status, started_by, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trial_id, submission_id, package_hash, dataset_type, dataset_path,
             STATUS_RUNNING, started_by, started_at))
        conn.commit()


def finish_trial(trial_id: str, *, status: str, finished_at: str,
                 duration_s: float | None = None,
                 rows_used: int | None = None,
                 metrics: dict | None = None,
                 error_stage: str | None = None,
                 error_kind: str | None = None,
                 error_message: str | None = None,
                 artifacts_dir: str | None = None,
                 db_path: str | None = None) -> None:
    """Tutup sebuah uji coba.

    Rincian kegagalan (tahap, jenis, pesan) disimpan TERPISAH supaya
    ketiganya dapat ditampilkan apa adanya; meringkasnya menjadi satu kalimat
    "uji gagal" membuang justru informasi yang membuat fitur ini berguna.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            """UPDATE pipeline_trials
               SET status = ?, finished_at = ?, duration_s = ?, rows_used = ?,
                   metrics_json = ?, error_stage = ?, error_kind = ?,
                   error_message = ?, artifacts_dir = ?
               WHERE id = ?""",
            (status, finished_at, duration_s, rows_used,
             json.dumps(metrics) if metrics else None,
             error_stage, error_kind, error_message, artifacts_dir, trial_id))
        conn.commit()


def get_trial(trial_id: str, db_path: str | None = None) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM pipeline_trials WHERE id = ?",
                           (trial_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_trials(submission_id: int, db_path: str | None = None) -> list[dict]:
    """Uji coba sebuah pengajuan, terbaru lebih dulu."""
    with get_connection(db_path) as conn:
        # `rowid` memutus seri: stempel waktu berpresisi detik membuat dua
        # uji pada detik yang sama tidak dapat diurutkan, dan "uji terakhir"
        # yang salah pilih akan mengunci — atau membuka — persetujuan secara
        # keliru.
        rows = conn.execute(
            "SELECT * FROM pipeline_trials WHERE submission_id = ? "
            "ORDER BY started_at DESC, rowid DESC",
            (submission_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def latest_trial(submission_id: int, db_path: str | None = None) -> dict | None:
    trials = list_trials(submission_id, db_path)
    return trials[0] if trials else None


def latest_trials_for(submission_ids, db_path: str | None = None) -> dict:
    """``{submission_id: uji terakhir}`` untuk BANYAK pengajuan, satu kueri.

    Halaman peninjauan menampilkan seluruh antrean sekaligus, dan menanyakan
    "uji terakhirnya apa" satu per satu berarti satu kueri per pengajuan —
    biaya yang tumbuh mengikuti panjang antrean, dibayar pada setiap
    penggambaran ulang. Di sini pertanyaannya diajukan sekali untuk semuanya.

    Urutan pemenangnya SAMA PERSIS dengan :func:`list_trials`
    (``started_at DESC, rowid DESC``), termasuk pemutus seri ``rowid`` — kalau
    keduanya berbeda, "uji terakhir" versi daftar dan versi kartu bisa
    menunjuk baris yang berlainan, dan gerbang persetujuan ikut salah.
    Pengajuan tanpa uji sama sekali TIDAK muncul sebagai kunci.
    """
    ids = [int(i) for i in (submission_ids or [])]
    if not ids:
        return {}

    out: dict[int, dict] = {}
    with get_connection(db_path) as conn:
        # Dipecah agar tidak menabrak batas jumlah variabel SQLite (999).
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT * FROM pipeline_trials WHERE submission_id IN ({placeholders}) "
                "ORDER BY started_at DESC, rowid DESC",
                chunk).fetchall()
            for row in rows:
                item = _row_to_dict(row)
                # Baris pertama yang terlihat untuk sebuah pengajuan adalah
                # yang terbaru — urutannya sudah dijamin kueri di atas.
                out.setdefault(item["submission_id"], item)
    return out


def delete_trials(submission_id: int, db_path: str | None = None) -> list[dict]:
    """Hapus catatan uji sebuah pengajuan; kembalikan yang dihapus.

    Yang dikembalikan dipakai pemanggil untuk membersihkan artefaknya — baris
    basis data dan berkas di disk dihapus sebagai satu langkah, sehingga tidak
    ada artefak yatim yang kehilangan catatannya.
    """
    existing = list_trials(submission_id, db_path)
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM pipeline_trials WHERE submission_id = ?",
                     (submission_id,))
        conn.commit()
    return existing


def list_trials_older_than(cutoff_iso: str,
                           db_path: str | None = None) -> list[dict]:
    """Uji coba yang dimulai sebelum ``cutoff_iso`` — bahan pembersihan."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_trials WHERE started_at < ? "
            "ORDER BY started_at", (cutoff_iso,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_trial(trial_id: str, db_path: str | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM pipeline_trials WHERE id = ?", (trial_id,))
        conn.commit()
