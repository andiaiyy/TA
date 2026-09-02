"""
Antrean persetujuan unggahan — FASE 3.

Unggahan tidak lagi langsung selesai: berkas masuk **area penampungan** dan
sebuah record ``submissions`` berstatus ``pending`` dibuat. Research Admin
meninjau lalu menyetujui atau menolak.

Batas lingkup (Fase 4 = registry dinamis, BUKAN di sini):
  - dataset disetujui  -> berkas dipindah ke ``storage/datasets/`` sehingga
    dapat dipilih untuk eksperimen (dataset adalah DATA, bukan kode);
  - pipeline disetujui -> status menjadi ``approved`` dan berkasnya dipindah ke
    area approved. **Registry TIDAK disentuh** — pendaftaran tetap manual.

⚠️ SECURITY
  - Berkas pipeline yang diunggah TIDAK PERNAH diimpor/di-exec di mana pun;
    modul ini hanya memindahkan berkas dan membaca teksnya untuk ditampilkan.
  - Seluruh area penampungan berada di ``storage/`` — bukan package Python,
    tidak pernah diimpor platform — dan TIDAK PERNAH di ``storage/datasets/``
    (folder itu dibaca sebagai dataset siap pakai).
  - Nama berkas disanitasi; separator/ekstensi asing ditolak; menimpa berkas
    yang sudah ada ditolak.
  - Izin diperiksa DI SINI (bukan hanya di UI): mengajukan butuh
    ``can_upload``, meninjau butuh ``can_approve``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from config.settings import DATASETS_DIR, STORAGE_DIR
from database.db import _retry_on_locked, get_connection
from database.models import (
    ALL_KINDS, KIND_DATASET, KIND_PIPELINE, SUBMISSION_APPROVED,
    SUBMISSION_PENDING, SUBMISSION_REJECTED,
)
from orchestrator.auth_service import AuthError, require_approve, require_upload
from utils.timestamps import now_iso

logger = logging.getLogger(__name__)

# ── Area penampungan (di luar jalur import platform, di luar datasets/) ────
_STORAGE = Path(STORAGE_DIR)
PIPELINE_ROOT = _STORAGE / "uploaded_pipelines"
DATASET_ROOT = _STORAGE / "uploaded_datasets"

SUBMISSION_DIRS = {
    KIND_PIPELINE: {
        SUBMISSION_PENDING: PIPELINE_ROOT / "pending",
        SUBMISSION_APPROVED: PIPELINE_ROOT / "approved",
        SUBMISSION_REJECTED: PIPELINE_ROOT / "rejected",
    },
    KIND_DATASET: {
        SUBMISSION_PENDING: DATASET_ROOT / "pending",
        SUBMISSION_APPROVED: DATASET_ROOT / "approved",
        SUBMISSION_REJECTED: DATASET_ROOT / "rejected",
    },
}

_CHUNK = 4 * 1024 * 1024        # 4 MB per blok — jangan muat berkas ke memori


class SubmissionError(AuthError):
    """Kegagalan pengajuan/peninjauan yang layak ditampilkan ke pengguna."""


@dataclass
class StoredFile:
    path: Path
    sha256: str
    size: int


# ── Util berkas ───────────────────────────────────────────────────────────

def _sanitize(filename: str, allowed_suffixes: tuple[str, ...]) -> str:
    """Nama berkas aman, atau raise. Menolak (bukan memotong) komponen
    direktori, karakter aneh, dan ekstensi di luar daftar."""
    name = (filename or "").strip()
    if not name or name != Path(name).name or "/" in name or "\\" in name:
        raise SubmissionError(
            f"Nama berkas tidak aman: {filename!r}",
            key="err.unsafe_filename",
            values={"filename": repr(filename)})
    if name in (".", ".."):
        raise SubmissionError(
            f"Nama berkas tidak aman: {filename!r}",
            key="err.unsafe_filename",
            values={"filename": repr(filename)})
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
           for ch in name):
        raise SubmissionError(
            f"Nama berkas hanya boleh huruf/angka/._- : {filename!r}",
            key="err.filename_charset", values={"filename": repr(filename)})
    if Path(name).suffix.lower() not in allowed_suffixes:
        raise SubmissionError(
            f"Ekstensi tidak didukung: {filename!r} "
            f"(diizinkan: {', '.join(allowed_suffixes)})",
            key="err.unsupported_extension",
            values={"ext": repr(filename),
                    "allowed": ", ".join(allowed_suffixes)})
    return name


def _unique_target(directory: Path, name: str) -> Path:
    """Path tujuan yang belum terpakai di area penampungan.

    Penampungan boleh menerima nama yang sama dari pengajuan berbeda, jadi
    di sini kita beri akhiran urut — BUKAN menimpa. (Untuk ``storage/datasets/``
    aturannya berbeda: menimpa ditolak mentah-mentah, lihat _move_into.)"""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(2, 1000):
        candidate = directory / f"{stem}__{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise SubmissionError("Terlalu banyak berkas dengan nama serupa.",
            key="err.too_many_similar_names")


def _write_stream(src, target: Path) -> StoredFile:
    """Salin stream ke target BERTAHAP sambil menghitung SHA-256 sekali jalan.

    Tidak pernah memuat seluruh isi ke memori — unggahan dataset bisa GB."""
    digest = hashlib.sha256()
    size = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.seek(0)
    except Exception:                       # pragma: no cover - stream tanpa seek
        pass
    with open(target, "wb") as out:
        while True:
            block = src.read(_CHUNK)
            if not block:
                break
            out.write(block)
            digest.update(block)
            size += len(block)
    return StoredFile(target, digest.hexdigest(), size)


def _write_text(text: str, target: Path) -> StoredFile:
    data = (text or "").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return StoredFile(target, hashlib.sha256(data).hexdigest(), len(data))


def _move_into(source: Path, directory: Path, *, refuse_overwrite: bool) -> Path:
    """Pindahkan berkas/folder ke `directory`. Raise bila menimpa dan
    `refuse_overwrite` — dipakai untuk `storage/datasets/`."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / source.name
    if target.exists():
        if refuse_overwrite:
            raise SubmissionError(
                f"`{source.name}` sudah ada di `{directory.name}/`. Ganti nama "
                f"berkasnya — platform tidak menimpa berkas yang sudah ada.",
                key="err.dataset_file_exists",
                values={"filename": source.name, "folder": directory.name})
        target = _unique_target(directory, source.name)
    shutil.move(str(source), str(target))
    return target


# ── Query ─────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    item = dict(row)
    for key in ("metadata_json", "validation_json"):
        raw = item.get(key)
        item[key.replace("_json", "")] = json.loads(raw) if raw else {}
    return item


def get_submission(submission_id: int, db_path: str | None = None) -> dict | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM submissions WHERE id = ?",
                           (submission_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_submissions(*, status: str | None = None, kind: str | None = None,
                     submitted_by: str | None = None,
                     db_path: str | None = None) -> list[dict]:
    """Daftar pengajuan, terbaru dulu. Tanpa filter = semuanya."""
    sql = "SELECT * FROM submissions"
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if submitted_by:
        where.append("submitted_by = ?")
        params.append(submitted_by)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY submitted_at DESC, id DESC"

    conn = get_connection(db_path)
    try:
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@_retry_on_locked()
def _insert(record: dict, db_path: str | None = None) -> int:
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """INSERT INTO submissions
               (kind, status, submitted_by, submitted_at, original_filename,
                stored_path, file_hash, file_size, metadata_json, validation_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record["kind"], SUBMISSION_PENDING, record["submitted_by"],
             now_iso(), record["original_filename"], str(record["stored_path"]),
             record["file_hash"], record["file_size"],
             json.dumps(record.get("metadata") or {}, ensure_ascii=False),
             json.dumps(record.get("validation") or {}, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


# ── Mengajukan ────────────────────────────────────────────────────────────

DATASET_SUFFIXES = (".csv", ".ndjson", ".jsonl", ".json")
PIPELINE_SUFFIXES = (".py",)


def submit_dataset(src, filename: str, *, user: dict | None,
                   metadata: dict | None = None, validation: dict | None = None,
                   db_path: str | None = None) -> dict:
    """Ajukan sebuah berkas dataset untuk ditinjau.

    Berkas ditulis ke ``storage/uploaded_datasets/pending/`` — TIDAK ke
    ``storage/datasets/``, sehingga tidak muncul sebagai dataset siap pakai
    sebelum disetujui. Raise PermissionDenied bila pemanggil tidak berhak.
    """
    require_upload(user, db_path)
    safe = _sanitize(filename, DATASET_SUFFIXES)
    target = _unique_target(SUBMISSION_DIRS[KIND_DATASET][SUBMISSION_PENDING], safe)

    stored = _write_stream(src, target)
    try:
        submission_id = _insert({
            "kind": KIND_DATASET, "submitted_by": user["username"],
            "original_filename": safe, "stored_path": stored.path,
            "file_hash": stored.sha256, "file_size": stored.size,
            "metadata": metadata, "validation": validation,
        }, db_path)
    except Exception:
        # Jangan tinggalkan berkas yatim bila pencatatan gagal.
        stored.path.unlink(missing_ok=True)
        raise
    logger.info("Pengajuan dataset #%s oleh %s: %s (%s byte)",
                submission_id, user["username"], safe, stored.size)
    return get_submission(submission_id, db_path)


def submit_pipeline(files: list[tuple[str, str]], entry_filename: str, *,
                    user: dict | None, metadata: dict | None = None,
                    validation: dict | None = None,
                    db_path: str | None = None) -> dict:
    """Ajukan satu PAKET pipeline (satu atau beberapa berkas ``.py``).

    ``files`` adalah [(nama, teks source)] yang SUDAH divalidasi statis.
    Seluruh berkas paket ditaruh dalam satu folder di area pending; satu record
    submissions mewakili paket itu (``stored_path`` = foldernya,
    ``original_filename``/``file_hash`` mengacu pada entry point, dan rincian
    per berkas disimpan di ``metadata_json``). Source hanya DITULIS sebagai
    teks — tidak pernah diimpor atau dieksekusi.
    """
    require_upload(user, db_path)
    if not files:
        raise SubmissionError("Tidak ada berkas untuk diajukan.",
            key="err.no_files_to_submit")
    safe_entry = _sanitize(entry_filename, PIPELINE_SUFFIXES)

    pending_root = SUBMISSION_DIRS[KIND_PIPELINE][SUBMISSION_PENDING]
    package_dir = _unique_target(pending_root, Path(safe_entry).stem)
    package_dir.mkdir(parents=True, exist_ok=True)

    written: list[dict] = []
    entry_hash, total = "", 0
    try:
        for name, source in files:
            safe = _sanitize(name, PIPELINE_SUFFIXES)
            stored = _write_text(source, package_dir / safe)
            written.append({"filename": safe, "sha256": stored.sha256,
                            "size": stored.size})
            total += stored.size
            if safe == safe_entry:
                entry_hash = stored.sha256
        if not entry_hash:
            raise SubmissionError(
                f"Entry point `{safe_entry}` tidak ada di antara berkas paket.",
                key="err.entry_not_in_files",
                values={"filename": safe_entry})

        meta = dict(metadata or {})
        meta["files"] = written
        meta["entry_filename"] = safe_entry
        submission_id = _insert({
            "kind": KIND_PIPELINE, "submitted_by": user["username"],
            "original_filename": safe_entry, "stored_path": package_dir,
            "file_hash": entry_hash, "file_size": total,
            "metadata": meta, "validation": validation,
        }, db_path)
    except Exception:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise
    logger.info("Pengajuan pipeline #%s oleh %s: %s (%d berkas)",
                submission_id, user["username"], safe_entry, len(written))
    return get_submission(submission_id, db_path)


# ── Meninjau ──────────────────────────────────────────────────────────────

@_retry_on_locked()
def _finish_review(submission_id: int, status: str, actor: dict, note: str,
                   stored_path: Path, db_path: str | None) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            """UPDATE submissions
               SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?,
                   stored_path = ?
               WHERE id = ?""",
            (status, actor["username"], now_iso(), note or None,
             str(stored_path), submission_id),
        )
        conn.commit()
    finally:
        conn.close()


def _load_pending(submission_id: int, db_path: str | None) -> dict:
    item = get_submission(submission_id, db_path)
    if item is None:
        raise SubmissionError(
            f"Pengajuan #{submission_id} tidak ditemukan.",
            key="err.submission_not_found",
            values={"number": submission_id})
    if item["status"] != SUBMISSION_PENDING:
        raise SubmissionError(
            f"Pengajuan #{submission_id} sudah berstatus {item['status']}.")
    return item


def approve_submission(submission_id: int, *, actor: dict | None, note: str = "",
                       dataset_type: str | None = None,
                       db_path: str | None = None) -> dict:
    """Setujui sebuah pengajuan. Hanya Research Admin.

    Dataset  -> berkas dipindah ke ``storage/datasets/`` (menimpa DITOLAK)
                sehingga tersedia untuk eksperimen.
    Pipeline -> paket dipindah ke area approved, statusnya menjadi ``approved``,
                dan (Fase 4) versinya DIDAFTARKAN ke registry dinamis sehingga
                dapat dipilih & dijalankan. ``config/pipeline_registry.py``
                tetap tidak disentuh: pipeline terunggah hidup di tabel
                ``registered_pipelines`` dengan namespace ``uploaded.*``.
                ``dataset_type`` wajib untuk pipeline (diambil dari metadata
                pengajuan bila peninjau tidak menentukannya).

    Berkas dipindah LEBIH DULU; bila pencatatan DB gagal, pemindahan dibatalkan
    agar tidak ada berkas/record yang tertinggal tidak konsisten.
    """
    require_approve(actor, db_path)
    item = _load_pending(submission_id, db_path)

    # GERBANG UJI COBA. Pipeline hanya boleh disetujui setelah benar-benar
    # dijalankan di platform ini, pada kode yang persis sama dengan yang akan
    # disetujui. Diperiksa di sini — bukan hanya di tampilan — supaya
    # memanggil fungsi ini langsung tidak dapat melewatinya.
    from orchestrator.trial_service import approval_blocker

    blocked = approval_blocker(item, db_path)
    if blocked:
        raise SubmissionError(
            "Pengajuan ini belum lolos uji coba pada platform, sehingga belum "
            "dapat disetujui.", key=blocked)

    source = Path(item["stored_path"])
    if not source.exists():
        raise SubmissionError(
            f"Berkas pengajuan tidak ditemukan: {source}",
            key="err.submission_file_missing",
            values={"path": str(source)})

    if item["kind"] == KIND_DATASET:
        destination_dir = Path(DATASETS_DIR)
        refuse_overwrite = True
    else:
        destination_dir = SUBMISSION_DIRS[KIND_PIPELINE][SUBMISSION_APPROVED]
        refuse_overwrite = False

    if item["kind"] == KIND_PIPELINE:
        # Pastikan syarat pendaftaran lengkap SEBELUM apa pun dipindahkan,
        # supaya kegagalan tidak meninggalkan berkas setengah jalan.
        _pipeline_registration_plan(item, dataset_type)

    moved = _move_into(source, destination_dir, refuse_overwrite=refuse_overwrite)
    try:
        _finish_review(submission_id, SUBMISSION_APPROVED, actor, note, moved, db_path)
        if item["kind"] == KIND_PIPELINE:
            _register_approved_pipeline(item, moved, actor, dataset_type, db_path)
    except Exception:
        shutil.move(str(moved), str(source))     # kembalikan seperti semula
        raise
    _discard_trials_quietly(submission_id, db_path)
    logger.info("Pengajuan #%s disetujui oleh %s -> %s",
                submission_id, actor["username"], moved)
    return get_submission(submission_id, db_path)


def _discard_trials_quietly(submission_id: int, db_path: str | None) -> None:
    """Buang hasil uji setelah keputusan diambil.

    Kegagalan membersihkan TIDAK boleh membatalkan keputusan yang sudah sah —
    berkasnya sudah pindah dan statusnya sudah tercatat. Sisanya ditangani
    pembersihan berkala (`trial_service.cleanup_stale_trials`).
    """
    try:
        from orchestrator.trial_service import discard_trials

        discard_trials(submission_id, db_path)
    except Exception:                        # pragma: no cover - defensif
        logger.exception(
            "Gagal membuang hasil uji pengajuan #%s — akan dibersihkan "
            "pembersihan berkala", submission_id)


def _pipeline_registration_plan(item: dict, dataset_type: str | None) -> tuple[str, str, str]:
    """(nama, dataset_type, entry_class) untuk pendaftaran — atau raise."""
    metadata = item.get("metadata") or {}
    resolved_type = (dataset_type or metadata.get("dataset_type") or "").strip()
    if not resolved_type:
        raise SubmissionError(
            "Pipeline ini belum punya dataset_type. Tentukan dataset target "
            "saat meninjau sebelum menyetujui.",
            key="err.no_dataset_type")
    entry_class = (metadata.get("entry_class") or "").strip()
    if not entry_class:
        raise SubmissionError(
            "Nama kelas entry point tidak diketahui pada metadata pengajuan.",
            key="err.no_entry_class")
    name = (metadata.get("name") or Path(item["original_filename"]).stem)
    return name, resolved_type, entry_class


def _register_approved_pipeline(item: dict, package_dir: Path, actor: dict,
                                dataset_type: str | None, db_path: str | None) -> None:
    """Daftarkan versi baru ke registry dinamis (Fase 4)."""
    from orchestrator.dynamic_registry import register_pipeline

    name, resolved_type, entry_class = _pipeline_registration_plan(item, dataset_type)
    entry_file = package_dir / item["original_filename"]
    metadata = item.get("metadata") or {}
    register_pipeline(
        name=name, dataset_type=resolved_type, entry_class=entry_class,
        entry_file=entry_file, registered_by=actor["username"],
        submission_id=item["id"], algorithm=metadata.get("algorithm"),
        paper=metadata.get("paper"), db_path=db_path,
    )


def reject_submission(submission_id: int, *, actor: dict | None, note: str,
                      db_path: str | None = None) -> dict:
    """Tolak sebuah pengajuan. Hanya Research Admin; catatan alasan WAJIB.

    Berkasnya dipindah ke area rejected (bukan dihapus) agar masih dapat
    ditinjau ulang bila diperlukan.
    """
    require_approve(actor, db_path)
    if not (note or "").strip():
        raise SubmissionError("Catatan alasan wajib diisi saat menolak.",
            key="err.reject_reason_required")
    item = _load_pending(submission_id, db_path)
    source = Path(item["stored_path"])

    moved = source
    if source.exists():
        moved = _move_into(source, SUBMISSION_DIRS[item["kind"]][SUBMISSION_REJECTED],
                           refuse_overwrite=False)
    try:
        _finish_review(submission_id, SUBMISSION_REJECTED, actor, note.strip(),
                       moved, db_path)
    except Exception:
        if moved != source:
            shutil.move(str(moved), str(source))
        raise
    _discard_trials_quietly(submission_id, db_path)
    logger.info("Pengajuan #%s ditolak oleh %s", submission_id, actor["username"])
    return get_submission(submission_id, db_path)


def read_submission_sources(item: dict) -> list[tuple[str, str]]:
    """[(nama, teks)] berkas pipeline sebuah pengajuan, untuk DITAMPILKAN.

    Membaca berkas sebagai TEKS saja — tidak pernah diimpor maupun dieksekusi.
    """
    if item.get("kind") != KIND_PIPELINE:
        return []
    folder = Path(item["stored_path"])
    if not folder.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(folder.glob("*.py")):
        try:
            out.append((path.name, path.read_text(encoding="utf-8")))
        except OSError:                     # pragma: no cover - defensive
            logger.warning("Berkas pengajuan tidak terbaca: %s", path)
    return out
