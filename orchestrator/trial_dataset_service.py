"""
Dataset CONTOH yang dilampirkan kontributor untuk menguji pipelinenya.

Alasan fitur ini ada: pipeline baru bisa saja memerlukan struktur data yang
belum ada di platform. Tanpa dataset yang sesuai, pipeline seperti itu tidak
akan pernah dapat diuji — dan karena persetujuan bergerbang uji coba, ia juga
tidak akan pernah dapat disetujui.

Berkas ini adalah CONTOH untuk membuktikan pipeline BERJALAN, bukan data
penelitian. Karena itu:

* ia disimpan di area penampungan pengajuan, **bukan** di
  ``storage/datasets/`` — sehingga tidak pernah terbaca sebagai dataset siap
  pakai dan tidak dapat dipilih siapa pun untuk eksperimen;
* ukurannya dibatasi jauh lebih ketat daripada unggahan dataset biasa
  (:data:`MAX_TRIAL_DATASET_BYTES`);
* namanya disanitasi dengan aturan yang sama dengan berkas pengajuan lain;
* hash-nya dicatat saat diajukan dan DIVERIFIKASI ulang sebelum dipakai;
* ia dihapus bersama hasil uji setelah keputusan diambil.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

from database.db import get_connection
from orchestrator.auth_service import require_approve, require_upload

#: Penanda "dipanggil dari dalam, izinnya sudah ditegakkan lebih dulu".
#: BUKAN ``None``: None berarti PENGUNJUNG di seluruh platform ini, dan
#: memakainya sebagai penanda internal justru meloloskan pengunjung.
INTERNAL = object()
from orchestrator.submission_service import (
    DATASET_SUFFIXES, PIPELINE_ROOT, StoredFile, SubmissionError, _sanitize,
    stored_location,
    _unique_target, _write_stream,
)

logger = logging.getLogger(__name__)

#: Akar dataset lampiran. Di bawah area penampungan pengajuan, dan SENGAJA
#: bukan di `storage/datasets/`: apa pun yang ada di sana terbaca sebagai
#: dataset siap pakai oleh halaman Run Experiment.
TRIAL_DATASET_ROOT = PIPELINE_ROOT / "trial_datasets"

#: Batas ukuran dataset lampiran: 25 MB, sekitar 200× lebih kecil daripada
#: batas unggah dataset platform (5 GB).
#:
#: Angkanya diturunkan dari kegunaannya, bukan dikira-kira: uji coba membaca
#: paling banyak 50.000 baris (``TRIAL_LIMITS["max_rows"]``), dan 25 MB sudah
#: memuat jauh lebih banyak dari itu untuk fitur flow maupun catatan EVE. Lebih
#: besar dari ini tidak menambah satu pun kemampuan uji — ia hanya menambah
#: berkas yang harus disimpan sementara lalu dihapus.
MAX_TRIAL_DATASET_BYTES = 25 * 1024 * 1024


class TrialDatasetError(SubmissionError):
    """Dataset lampiran ditolak — ukuran, nama, format, atau hash."""


def human_size(num_bytes: int) -> str:
    """Ukuran yang terbaca manusia; dipakai pada pesan penolakan."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"                 # pragma: no cover - tak tercapai


def check_size(size: int) -> None:
    """Tolak berkas yang melampaui batas, dengan MENYEBUT angkanya.

    Pesan yang hanya berkata "terlalu besar" memaksa kontributor menebak
    seberapa harus dikecilkan.
    """
    if size > MAX_TRIAL_DATASET_BYTES:
        raise TrialDatasetError(
            f"Dataset uji {human_size(size)} melampaui batas "
            f"{human_size(MAX_TRIAL_DATASET_BYTES)}.",
            key="td.err_too_large",
            values={"size": human_size(size),
                    "limit": human_size(MAX_TRIAL_DATASET_BYTES)})


def store_attachment(src, filename: str, *, package_name: str,
                     note: str = "") -> dict:
    """Simpan dataset lampiran; kembalikan KETERANGANNYA.

    ``src`` adalah stream unggahan. Ditulis bertahap lewat ``_write_stream``
    yang sama dengan pengajuan lain, jadi hash dan ukurannya dihitung sekali
    jalan tanpa memuat berkas ke memori.

    Nama disanitasi lebih dulu: pemisah jalur, karakter di luar pola, dan
    ekstensi di luar daftar semuanya DITOLAK — bukan dipotong.
    """
    try:
        safe = _sanitize(filename, DATASET_SUFFIXES)
    except SubmissionError as exc:
        # Aturan sanitasinya TIDAK berubah — hanya jenis galatnya diseragamkan,
        # supaya pemanggil (termasuk formulir) cukup menangkap satu jenis dan
        # tidak ada penolakan yang lolos tanpa tertangani.
        raise TrialDatasetError(str(exc), key=getattr(exc, "key", ""),
                                values=getattr(exc, "values", {})) from exc
    folder = TRIAL_DATASET_ROOT / package_name
    folder.mkdir(parents=True, exist_ok=True)
    target = _unique_target(folder, safe)    # menimpa DITOLAK, diberi akhiran

    stored: StoredFile = _write_stream(src, target)
    try:
        check_size(stored.size)
    except TrialDatasetError:
        target.unlink(missing_ok=True)       # jangan tinggalkan berkas ditolak
        raise

    return {
        "filename": safe,
        "stored_path": str(stored.path),
        "sha256": stored.sha256,
        "size": stored.size,
        "format": target.suffix.lower().lstrip("."),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "note": (note or "").strip(),
    }


def attach_to_submission(submission_id: int, info: dict,
                         db_path: str | None = None, *,
                         actor: dict | None = INTERNAL) -> None:
    """Catat keterangan lampiran pada pengajuan.

    ``actor`` diperiksa DI SINI bila diberikan: sebuah audit menemukan fungsi
    ini sama sekali tidak menanyakan izin, sehingga satu-satunya penghalangnya
    adalah tombol di layar — persis yang dilarang prinsip platform ini.
    Pemanggil INTERNAL yang izinnya sudah ditegakkan lebih dulu (jalur
    persetujuan, penolakan, penghapusan) memanggilnya tanpa ``actor``.
    """
    if actor is not INTERNAL:
        require_upload(actor, db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE submissions SET trial_dataset_json = ? WHERE id = ?",
            (json.dumps(info), submission_id))
        conn.commit()


def attachment_of(item: dict) -> dict | None:
    """Keterangan dataset lampiran sebuah pengajuan, atau None."""
    raw = (item or {}).get("trial_dataset_json")
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):           # pragma: no cover - defensif
        return None


def verify_attachment(item: dict) -> str:
    """Path dataset lampiran yang SUDAH diverifikasi, atau raise.

    Hash dicocokkan dengan yang tercatat saat diajukan. Berkas yang berubah
    setelah pengajuan ditolak SEBELUM dipakai — pengaman yang sama dengan yang
    berlaku pada berkas kode pipeline.
    """
    from orchestrator.dynamic_registry import file_sha256

    info = attachment_of(item)
    if not info:
        raise TrialDatasetError(
            "Pengajuan ini tidak melampirkan dataset uji.",
            key="td.err_no_attachment")

    path = stored_location(info["stored_path"])
    if not path.is_file():
        raise TrialDatasetError(
            f"Berkas dataset lampiran tidak ditemukan: {path.name}",
            key="td.err_file_missing", values={"filename": path.name})

    actual = file_sha256(path)
    if actual != info["sha256"]:
        raise TrialDatasetError(
            f"Hash dataset lampiran tidak cocok untuk {path.name}: tercatat "
            f"{info['sha256'][:12]}…, ditemukan {actual[:12]}…. Berkas berubah "
            f"setelah diajukan: pemakaian ditolak.",
            key="td.err_hash_mismatch",
            values={"filename": path.name, "recorded": info["sha256"][:12],
                    "found": actual[:12]})
    return str(path)


def inspect_attachment(path: str, dataset_type: str | None = None) -> dict:
    """Pemeriksaan struktur lewat DIAGNOSA yang sudah ada, dengan pencuplikan.

    Memakai ``diagnose_all``/``diagnose_dataset`` apa adanya — aturannya tidak
    disentuh. Berkas dibaca sebagai CUPLIKAN, bukan dimuat seluruhnya.
    """
    from orchestrator.dataset_diagnostics import diagnose_all, diagnose_dataset

    try:
        if dataset_type:
            return {"reports": [diagnose_dataset(path, dataset_type)]}
        result = diagnose_all(path)
        # `results` berbentuk {dataset_type: laporan} — nilainya yang dipakai.
        reports = (result or {}).get("results") or {}
        return {"reports": list(reports.values()),
                "compatible_types": list(
                    (result or {}).get("compatible_types") or [])}
    except Exception as exc:                 # pragma: no cover - defensif
        logger.warning("Pemeriksaan dataset lampiran gagal: %s", exc)
        return {"reports": [], "error": str(exc)}


def discard_attachment(item: dict, db_path: str | None = None, *,
                       actor: dict | None = INTERNAL) -> bool:
    """Hapus berkas lampiran DAN keterangannya. True bila ada yang dihapus.

    Dipanggil bersama pembersihan hasil uji setelah keputusan diambil, supaya
    berkas contoh tidak tertinggal di area penampungan.

    ``actor`` diperiksa DI SINI bila diberikan. Pemanggil INTERNAL — jalur
    persetujuan, penolakan, penghapusan — sudah menegakkan izinnya lebih dulu
    dan memanggilnya tanpa ``actor``; pemanggil dari layar menyertakannya,
    sehingga tombol tidak pernah menjadi satu-satunya penghalang.
    """
    if actor is not INTERNAL:
        require_approve(actor, db_path)
    info = attachment_of(item)
    if not info:
        return False

    path = stored_location(info.get("stored_path"))
    folder = path.parent
    path.unlink(missing_ok=True)
    # Folder pengajuan ini ikut dibuang bila sudah kosong — jangan tinggalkan
    # folder yatim yang tidak lagi punya berkas maupun catatan.
    try:
        if folder.is_dir() and folder.parent == TRIAL_DATASET_ROOT \
                and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:                          # pragma: no cover - defensif
        logger.warning("Folder dataset lampiran tidak dapat dibuang: %s", folder)

    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE submissions SET trial_dataset_json = NULL WHERE id = ?",
            (item["id"],))
        conn.commit()
    logger.info("Dataset lampiran pengajuan #%s dibuang: %s",
                item["id"], info.get("filename"))
    return True


def orphan_attachment_dirs(db_path: str | None = None) -> list[Path]:
    """Folder lampiran yang tidak lagi diacu pengajuan mana pun."""
    if not TRIAL_DATASET_ROOT.is_dir():
        return []
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT trial_dataset_json FROM submissions "
            "WHERE trial_dataset_json IS NOT NULL").fetchall()
    known = set()
    for row in rows:
        try:
            known.add(Path(json.loads(row[0])["stored_path"]).parent.name)
        except (TypeError, ValueError, KeyError):   # pragma: no cover
            continue
    return [p for p in TRIAL_DATASET_ROOT.iterdir()
            if p.is_dir() and p.name not in known]


def quarantine_root() -> Path:
    """Tempat folder yatim DIPINDAHKAN. Diturunkan dari akar lampiran.

    Berada di SEBELAH `trial_datasets/`, bukan di dalamnya: folder di dalamnya
    akan ikut terbaca sebagai lampiran yatim pada penyapuan berikutnya, dan
    karantina yang mengkarantina dirinya sendiri hanya menambah satu lapis
    kebingungan setiap kali aplikasi menyala.

    Diturunkan, bukan dipatok: test mengalihkan `TRIAL_DATASET_ROOT` ke tmp,
    dan karantina yang dipatok ke storage sungguhan akan menulis ke sana dari
    dalam test.
    """
    return TRIAL_DATASET_ROOT.parent / "_karantina"


def purge_orphans(db_path: str | None = None) -> int:
    """PINDAHKAN folder lampiran yatim ke karantina. Kembalikan jumlahnya.

    Dahulu fungsi ini `shutil.rmtree` — permanen, tanpa jeda, tanpa jejak,
    dijalankan SETIAP kali container UI menyala (lihat `ui/app._startup_cleanup`).

    Dalam keadaan normal ia tidak berbahaya: `delete_submission` sudah membuang
    lampirannya sendiri, jadi yatim hanya lahir dari keadaan yang sudah salah.
    Justru itu masalahnya. Ketika sebuah baris pengajuan hilang karena sebab
    yang belum diketahui, penghapusan ini mengubah "satu baris hilang" menjadi
    "dataset kontribusi hilang permanen" — dan menghapus pula bukti yang
    dibutuhkan untuk menemukan sebabnya. Itu terjadi dua kali dalam satu hari.

    Memindahkan, bukan menghapus, tidak menyelesaikan sebabnya. Ia membuat
    akibatnya DAPAT DIPULIHKAN, dan meninggalkan cap waktu yang menunjukkan
    kapan hal itu terjadi.

    Isi karantina TIDAK pernah dibuang otomatis: membuangnya keputusan orang,
    dan orang itu perlu melihatnya lebih dulu.
    """
    orphans = orphan_attachment_dirs(db_path)
    if not orphans:
        return 0

    tujuan = quarantine_root() / datetime.now().strftime("%Y%m%d_%H%M%S")
    tujuan.mkdir(parents=True, exist_ok=True)

    dipindah = 0
    for folder in orphans:
        sasaran = tujuan / folder.name
        # Nama yang sama dapat dikarantina lagi dalam detik yang sama.
        n = 1
        while sasaran.exists():
            sasaran = tujuan / f"{folder.name}__{n}"
            n += 1
        try:
            shutil.move(str(folder), str(sasaran))
        except OSError:                      # pragma: no cover - defensif
            logger.warning("Lampiran yatim %s tidak dapat dikarantina",
                           folder, exc_info=True)
            continue
        dipindah += 1
        logger.warning(
            "Lampiran yatim DIKARANTINA (tidak dihapus): %s -> %s. "
            "Bila ini tidak Anda duga, baris pengajuannya mungkin hilang; "
            "datanya masih utuh di jalur tujuan.", folder, sasaran)
    return dipindah


__all__ = [
    "MAX_TRIAL_DATASET_BYTES", "TRIAL_DATASET_ROOT", "TrialDatasetError",
    "attach_to_submission", "attachment_of", "check_size",
    "discard_attachment", "human_size", "inspect_attachment",
    "orphan_attachment_dirs", "purge_orphans", "quarantine_root",
    "store_attachment",
    "verify_attachment",
]
