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
from pathlib import Path, PurePosixPath

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

def stored_location(raw) -> Path:
    """Letak paket sebuah pengajuan, ditambatkan ke ``storage/`` yang BERLAKU.

    ``stored_path`` dicatat sebagai jalur ABSOLUT saat pengajuannya masuk.
    Platform ini dijalankan bergantian di dalam container
    (``/app/storage/...``) dan langsung di host (``D:...storage...``), dengan
    folder ``storage/`` yang SAMA dipasang ke keduanya. Jadi jalur yang benar
    di satu lingkungan salah di lingkungan lain — dan pembacanya melaporkan
    paket yang ada di depan matanya sebagai hilang. Dua pengajuan nyata
    terbaca NOL berkas karena ini, salah satunya masih berstatus `pending`:
    peninjaunya melihat paket kosong tanpa cara mengetahui sebabnya.

    Yang tetap benar di kedua lingkungan adalah EKORNYA — bagian setelah
    ``uploaded_pipelines/`` atau ``uploaded_datasets/``. Jadi: pakai jalurnya
    apa adanya bila memang ada; bila tidak, tambatkan ekor itu ke akar yang
    berlaku sekarang, dan hanya bila hasilnya benar-benar ada. Fungsi ini tidak
    pernah mengarang letak, dan tidak pernah menulis apa pun.
    """
    text = str(raw or "").strip()
    if not text:
        return Path(text)
    path = Path(text)
    if path.exists():
        return path

    parts = PurePosixPath(text.replace(chr(92), "/")).parts
    for anchor_name, root in (("uploaded_pipelines", PIPELINE_ROOT),
                              ("uploaded_datasets", DATASET_ROOT)):
        if anchor_name in parts:
            tail = parts[parts.index(anchor_name) + 1:]
            candidate = Path(root).joinpath(*tail)
            if candidate.exists():
                return candidate
    return path                 # tidak ditemukan: apa adanya, bukan tebakan



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
    """Pengajuan yang masih MENUNGGU. Dipakai penolakan."""
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


#: Status yang MASIH dapat ditinjau. Persetujuan tidak lagi menuntut `pending`:
#: pipeline yang sudah terdaftar dapat ditinjau ulang langsung dari halamannya,
#: dan menyetujuinya menghasilkan versi BARU.
#:
#: `rejected` sengaja TIDAK termasuk. Berkasnya sudah dipindah ke area
#: penolakan, dan menyetujuinya berarti menghidupkan kembali sesuatu yang sudah
#: diputuskan — keputusan yang harus ditempuh lewat pengajuan baru, bukan
#: lewat tombol setujui.
REVIEWABLE_STATUSES = (SUBMISSION_PENDING, SUBMISSION_APPROVED)


def _load_reviewable(submission_id: int, db_path: str | None) -> dict:
    """Pengajuan yang masih dapat DISETUJUI — menunggu atau sudah disetujui."""
    item = get_submission(submission_id, db_path)
    if item is None:
        raise SubmissionError(
            f"Pengajuan #{submission_id} tidak ditemukan.",
            key="err.submission_not_found",
            values={"number": submission_id})
    # Peninjauan ULANG hanya bermakna untuk PIPELINE: ia berversi, sehingga
    # menyetujuinya lagi menghasilkan versi baru. Dataset tidak berversi —
    # menyetujuinya dua kali tidak menghasilkan apa pun selain kebingungan,
    # jadi bagi dataset aturannya tetap sekali saja.
    allowed = (REVIEWABLE_STATUSES if item["kind"] == KIND_PIPELINE
               else (SUBMISSION_PENDING,))
    if item["status"] not in allowed:
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
    item = _load_reviewable(submission_id, db_path)

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

    source = stored_location(item["stored_path"])
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

    standalone = is_standalone(item)
    if item["kind"] == KIND_PIPELINE:
        # Pastikan syarat pendaftaran lengkap SEBELUM apa pun dipindahkan,
        # supaya kegagalan tidak meninggalkan berkas setengah jalan.
        if standalone:
            # Berdiri sendiri: pengenalnya dibentuk dari namanya, bukan dipilih
            # peninjau. Diperiksa di sini supaya nama yang tidak sah ditolak
            # sebelum satu berkas pun bergerak.
            _plan_research_identity(item)
        else:
            _pipeline_registration_plan(item, dataset_type)

    # Peninjauan ULANG: berkasnya sudah berada di folder tujuan. Memindahkannya
    # lagi akan membuat `_move_into` mencari nama yang belum terpakai dan
    # MENGGANTI NAMA foldernya (`pkg` -> `pkg__2`), memutus `stored_path` yang
    # tercatat pada versi yang sudah terdaftar.
    already_in_place = source.parent == destination_dir
    moved = source if already_in_place else _move_into(
        source, destination_dir, refuse_overwrite=refuse_overwrite)
    created_type = ""
    reviewed = False
    try:
        _finish_review(submission_id, SUBMISSION_APPROVED, actor, note, moved, db_path)
        reviewed = True
        if item["kind"] == KIND_PIPELINE:
            if standalone:
                # Identitas research dibuat LEBIH DULU, sehingga algoritmanya
                # terdaftar di bawah `dataset_type` BARUNYA — bukan menumpang
                # keluarga bawaan.
                created_type = _create_research_identity(item, actor, db_path)
                _register_approved_pipeline(item, moved, actor, created_type,
                                            db_path)
                # Datasetnya diikat SEBELUM hasil uji dibuang di bawah, karena
                # pembuangan itulah yang selama ini menghapus lampirannya.
                _bind_approved_dataset(item, created_type, db_path)
            else:
                _register_approved_pipeline(item, moved, actor, dataset_type,
                                            db_path)
    except Exception:
        # Pemulihan LENGKAP. Sebelumnya hanya berkasnya yang dikembalikan:
        # bila pendaftaran gagal SESUDAH `_finish_review` commit, pengajuan
        # tertinggal berstatus `approved` dengan `stored_path` menunjuk lokasi
        # yang berkasnya sudah dikembalikan — keadaan setengah jadi yang tidak
        # dapat diperbaiki dari antarmuka.
        _undo_registered_pipelines(submission_id, db_path)
        _undo_research_identity(created_type, db_path)
        if reviewed:
            _restore_submission_row(item, db_path)
        if not already_in_place:
            shutil.move(str(moved), str(source))   # kembalikan seperti semula
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


def declared_schema_of(item: dict) -> dict:
    """Kontrak dataset yang DIDEKLARASIKAN kontributor, atau ``{}``.

    Bentuknya harus memuat kolom label DAN daftar kolom wajib; deklarasi
    setengah jadi tidak dianggap deklarasi, karena skema tanpa keduanya tidak
    dapat dipakai memeriksa apa pun.
    """
    declared = (item.get("metadata") or {}).get("declared_schema")
    if not isinstance(declared, dict):
        return {}
    if not declared.get("label_column"):
        return {}
    if not declared.get("expected_columns"):
        return {}
    return declared


def is_standalone(item: dict) -> bool:
    """Apakah pengajuan ini research pipeline yang BERDIRI SENDIRI.

    SATU penentu, dipakai seluruh alur persetujuan dan tampilannya — bukan dua
    tempat yang bisa berbeda pendapat.

    Berdiri sendiri berarti ia membawa kontrak datasetnya sendiri, sehingga ia
    tidak perlu menumpang `dataset_type` bawaan dan peninjau tidak perlu
    ditanya "ini ikut research pipeline mana". Pengajuan LAMA tidak punya
    deklarasi itu dan tetap menumpang — perilakunya tidak berubah sama sekali.

    Fungsi MURNI: tidak menyentuh basis data maupun disk.
    """
    if item.get("kind") != KIND_PIPELINE:
        return False
    return bool(declared_schema_of(item))


def research_name_of(item: dict) -> str:
    """Nama research pipeline sebuah pengajuan berdiri sendiri."""
    metadata = item.get("metadata") or {}
    return str(metadata.get("name")
               or Path(item.get("original_filename") or "").stem or "").strip()


def _algorithms_of(item: dict) -> list[dict]:
    """Daftar algoritma sebuah pengajuan: ``[{filename, class_name, algorithm}]``.

    Pengajuan BARU mencatat seluruh entry point-nya. Pengajuan LAMA hanya
    mencatat satu ``entry_class`` — bentuk itu tetap dibaca apa adanya dan
    menghasilkan satu algoritma, persis seperti sebelumnya. Tidak ada yang
    diisi mundur.
    """
    metadata = item.get("metadata") or {}
    declared = metadata.get("algorithms")
    if isinstance(declared, list) and declared:
        out = []
        for entry in declared:
            if not isinstance(entry, dict):
                continue
            if entry.get("class_name") and entry.get("filename"):
                out.append(entry)
        if out:
            return out
    # Bentuk lama: satu entry point, namanya di `entry_class`.
    entry_class = (metadata.get("entry_class") or "").strip()
    if entry_class:
        return [{"filename": item["original_filename"],
                 "class_name": entry_class,
                 "algorithm": metadata.get("algorithm")}]
    return []


def _restore_submission_row(item: dict, db_path: str | None) -> None:
    """Kembalikan baris pengajuan ke keadaan SEBELUM persetujuan dicoba.

    Bukan sekadar mengubah status kembali ke `pending`: ``reviewed_by`` dan
    ``reviewed_at`` juga dipulihkan ke nilai aslinya. Menuliskannya dengan
    identitas peninjau saat ini akan membuat pengajuan yang persetujuannya
    GAGAL terlihat seperti sudah ditinjau — jejak yang tidak pernah terjadi.
    """
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE submissions SET status = ?, stored_path = ?, "
            "reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
            (item["status"], item["stored_path"], item.get("reviewed_by"),
             item.get("reviewed_at"), item.get("review_note"), item["id"]))
        conn.commit()


def _plan_research_identity(item: dict) -> tuple[str, str, dict]:
    """(dataset_type, nama, skema) research pipeline berdiri sendiri — atau raise.

    Dipanggil sebagai PRE-FLIGHT: seluruh syaratnya diperiksa sebelum satu
    berkas pun dipindah, sehingga kegagalan tidak meninggalkan apa pun.
    """
    from database.models import build_research_dataset_type

    name = research_name_of(item)
    if not name:
        raise SubmissionError(
            "Research pipeline ini belum punya nama, jadi pengenalnya tidak "
            "dapat dibentuk.", key="err.no_research_name")

    dataset_type = build_research_dataset_type(name)
    if not dataset_type:
        raise SubmissionError(
            f"Nama research pipeline tidak menghasilkan pengenal yang sah: "
            f"{name!r}", key="err.bad_research_name",
            values={"name": name})
    return dataset_type, name, declared_schema_of(item)


def planned_research_identity(item: dict) -> tuple[str, dict]:
    """(dataset_type, skema) yang AKAN dimiliki pengajuan ini — atau ``("", {})``.

    Bentuk :func:`_plan_research_identity` yang TIDAK MELEMPAR, untuk pemanggil
    yang hanya bertanya "kalau disetujui, jadinya apa?" dan tidak boleh gagal
    karena jawabannya belum ada.

    Ini yang membuka kebuntuan melingkar pada uji coba. Identitas sebuah
    research pipeline berdiri sendiri baru DIBUAT saat pengajuannya disetujui,
    sementara persetujuan menuntut uji coba yang lulus, dan uji coba menuntut
    identitas itu — sehingga tidak satu pun unggahan berdiri sendiri pernah
    dapat disetujui. Padahal jawabannya sudah lengkap di dalam pengajuan itu
    sendiri: namanya membentuk pengenalnya, dan kontrak datasetnya sudah
    dideklarasikan kontributor.

    Yang dikembalikan di sini DIHITUNG, bukan didaftarkan: tidak ada baris
    ``research_pipelines`` yang lahir lebih awal, dan persetujuan tetap satu-
    satunya tempat identitas itu benar-benar tercatat.

    Fungsi MURNI: tidak menyentuh basis data maupun disk.
    """
    if not is_standalone(item):
        return "", {}
    try:
        dataset_type, _name, schema = _plan_research_identity(item)
    except SubmissionError:
        # "Belum punya identitas yang sah" adalah jawaban, bukan kegagalan —
        # pemanggilnya (mis. penentu jenis dataset) tidak boleh melempar.
        return "", {}
    return dataset_type, schema


def research_credit(researcher: str, year="",
                    study: str = "") -> str:
    """Kredit penelitian sebagai SATU kalimat: "Budi (2026), UNHAS".

    Bentuknya mengikuti atribusi bawaan (`config/research_attribution.py`),
    sehingga kredit kontribusi dan kredit bawaan terbaca dengan pola yang sama.
    Bagian yang kosong dibuang, bukan diganti tanda hubung — "— (—)" bukan
    keterangan, hanya ruang yang terisi.

    Fungsi MURNI.
    """
    who = str(researcher or "").strip()
    when = str(year or "").strip()
    where = str(study or "").strip()
    if not who:
        return where
    head = f"{who} ({when})" if when else who
    return f"{head}, {where}" if where else head


def research_attribution_of(item: dict, name: str) -> dict:
    """Atribusi research pipeline sebuah pengajuan: nama tampil + kredit.

    ``display_name`` disusun sebagai ``"<kredit> — <nama>"`` — pola yang SAMA
    dengan atribusi bawaan, dan itu yang membuat labelnya benar. Sebelumnya ia
    disimpan sebagai ``"<nama> (kontribusi)"`` tanpa tanda hubung, sehingga
    ``short_label_for`` — yang mengambil bagian sebelum "—" sebagai kredit —
    tidak menemukan kredit apa pun dan menghasilkan nama yang mengulang
    dirinya: "Deteksi Anomali (kontribusi) — Deteksi Anomali".

    Pengajuan LAMA tidak membawa bagian kreditnya. Bagi mereka nama itulah
    satu-satunya yang diketahui, dan ia dipakai apa adanya — tanpa mengarang
    peneliti yang tidak pernah disebut siapa pun.

    Fungsi MURNI: tidak menyentuh basis data maupun disk.
    """
    metadata = item.get("metadata") or {}
    # `study` adalah bidang GABUNGAN pada pengajuan yang lebih lama, sebelum
    # judul dan institusi dipisah. Ia dipakai sebagai cadangan institusi supaya
    # pengajuan itu tetap menghasilkan kredit yang sama seperti dulu.
    institution = (metadata.get("institution")
                   or metadata.get("study") or "")
    credit = research_credit(metadata.get("researcher"),
                             metadata.get("year"), institution)
    # Cadangan terakhir: pengajuan paling lama hanya punya satu kolom bebas.
    credit = credit or str(metadata.get("paper") or "").strip()

    display = f"{credit} — {name}" if credit else name
    out = {k: v for k, v in (("display_name", display),
                             ("short_name", name),
                             ("paper_credit", credit),
                             ("scope", str(metadata.get("scope") or "").strip()),
                             ("pipeline_source",
                              _clean({"type": metadata.get("source_type"),
                                      "authors": metadata.get("researcher"),
                                      "title": metadata.get("title"),
                                      "institution": institution,
                                      "year": metadata.get("year")})),
                             ("dataset_source",
                              _clean({"name": metadata.get("dataset_name"),
                                      "attribution":
                                          metadata.get("dataset_attribution"),
                                      "note": metadata.get("dataset_note")})),
                             ) if v}
    return out


def _clean(values: dict) -> dict:
    """Bidang yang benar-benar terisi. Kosong DIBUANG, bukan diisi tanda hubung.

    Penyaji panelnya membuang baris yang nilainya kosong, jadi menyimpan ""
    hanya akan menjadi baris "—" yang memenuhi ruang tanpa mengatakan apa pun.
    """
    return {k: str(v).strip() for k, v in values.items()
            if str(v or "").strip()}


def _create_research_identity(item: dict, actor: dict,
                              db_path: str | None) -> str:
    """Buat identitas research pengajuan ini; kembalikan `dataset_type`-nya.

    Inilah yang membuat sebuah unggahan BERDIRI SENDIRI: ia mendapat
    ``dataset_type`` sendiri, skemanya sendiri, dan atribusinya sendiri —
    tidak lagi menumpang keluarga bawaan.
    """
    from orchestrator.research_registry import register_research

    dataset_type, name, schema = _plan_research_identity(item)
    attribution = research_attribution_of(item, name)

    register_research(dataset_type=dataset_type, name=name, schema=schema,
                      registered_by=actor["username"],
                      submission_id=item["id"], attribution=attribution,
                      db_path=db_path)
    return dataset_type


def _bind_approved_dataset(item: dict, dataset_type: str,
                           db_path: str | None) -> None:
    """Ikat dataset lampiran ke research pipeline yang baru dibuat.

    Sampai sekarang lampiran SELALU dibuang setelah keputusan — ia berkas
    contoh yang hanya hidup selama peninjauan. Untuk research pipeline yang
    berdiri sendiri itu keliru: tanpa datasetnya, algoritmanya terdaftar tetapi
    tidak pernah dapat dijalankan.

    Hash diverifikasi LEBIH DULU lewat pengaman yang sudah ada — berkas yang
    berubah setelah diajukan ditolak sebelum dipakai.
    """
    from orchestrator.research_registry import bind_dataset
    from orchestrator.trial_dataset_service import (
        attachment_of, verify_attachment,
    )

    info = attachment_of(item)
    if not info:
        return                       # tanpa lampiran: sah, memang tidak wajib

    verified = verify_attachment(item)          # raise bila hash tidak cocok
    bind_dataset(dataset_type, {**info, "stored_path": verified}, db_path)


def _undo_research_identity(dataset_type: str, db_path: str | None) -> None:
    """Buang identitas research yang terlanjur dibuat saat persetujuan gagal."""
    if not dataset_type:
        return
    try:
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM research_pipelines WHERE dataset_type = ?",
                         (dataset_type,))
            conn.commit()
    except Exception:                # pragma: no cover - defensif
        logger.exception("Identitas research %s gagal dibatalkan", dataset_type)


def _undo_registered_pipelines(submission_id: int, db_path: str | None) -> None:
    """Buang baris registry yang terlanjur dibuat saat persetujuan gagal."""
    try:
        with get_connection(db_path) as conn:
            conn.execute("DELETE FROM registered_pipelines WHERE submission_id = ?",
                         (submission_id,))
            conn.commit()
    except Exception:                # pragma: no cover - defensif
        logger.exception("Pendaftaran pengajuan #%s gagal dibatalkan",
                         submission_id)


def _register_approved_pipeline(item: dict, package_dir: Path, actor: dict,
                                dataset_type: str | None, db_path: str | None) -> None:
    """Daftarkan pipeline pengajuan ini ke registry dinamis.

    SATU pengajuan dapat menghasilkan BANYAK baris — satu per algoritma —
    yang berbagi ``dataset_type`` dan ``submission_id`` yang sama. Itulah yang
    membuat sebuah research pipeline kontribusi setara keluarga bawaan, yang
    memang punya beberapa algoritma sekaligus.

    Tiap algoritma memakai NAMA tersendiri, sehingga versinya dihitung per
    algoritma: menyetujui ulang menambah v2 pada masing-masing, bukan
    menumpuk versi satu sama lain.
    """
    from orchestrator.dynamic_registry import register_pipeline

    name, resolved_type, _entry_class = _pipeline_registration_plan(item, dataset_type)
    metadata = item.get("metadata") or {}
    algorithms = _algorithms_of(item)

    for entry in algorithms:
        entry_file = package_dir / entry["filename"]
        # Nama per algoritma. Dengan satu algoritma, namanya sama persis
        # dengan sebelumnya — pengajuan lama tidak berubah pengenalnya.
        algo_name = name if len(algorithms) == 1 else (
            f"{name}_{entry['class_name']}")
        register_pipeline(
            name=algo_name, dataset_type=resolved_type,
            entry_class=entry["class_name"],
            entry_file=entry_file, registered_by=actor["username"],
            submission_id=item["id"],
            algorithm=entry.get("algorithm") or metadata.get("algorithm"),
            paper=metadata.get("paper"),
            # Fase milik BERKAS ini, bukan milik paketnya: satu paket boleh
            # memuat beberapa algoritma dengan urutan fase yang berbeda.
            stages=entry.get("stages") or None, db_path=db_path,
        )


def deletion_summary(item: dict, db_path: str | None = None) -> dict:
    """Apa saja yang akan IKUT HILANG bila pengajuan ini dihapus.

    Dihitung SEBELUM konfirmasi, supaya yang ditanyakan ke peninjau adalah
    keputusan yang sudah diketahui akibatnya — bukan "yakin?" tanpa isi.
    """
    from database import trials as trial_db
    from orchestrator.trial_dataset_service import attachment_of

    folder = stored_location(item.get("stored_path"))
    try:
        trials = len(trial_db.list_trials(item["id"], db_path))
    except Exception:                        # pragma: no cover - defensif
        trials = 0

    attachment = attachment_of(item) or {}
    # Dataset yang sudah TERIKAT ke sebuah research pipeline BUKAN milik
    # pengajuan ini lagi — ia dataset pipeline itu. Menghapusnya bersama
    # pengajuannya akan membuat pipeline yang terdaftar kehilangan datanya.
    bound = _dataset_is_bound_to_research(item["id"], db_path)

    return {
        "folder": str(folder) if folder.name else "",
        "files": len(list(folder.glob("*.py"))) if folder.is_dir() else 0,
        "trials": trials,
        "attachment": "" if bound else (attachment.get("filename") or ""),
        "attachment_kept": bool(bound and attachment.get("filename")),
        "registered": len(_registered_of(item["id"], db_path)),
        # Identitas research yang lahir dari pengajuan ini: ikut hilang bila
        # tidak ada pipeline yang memakainya, BERTAHAN bila masih dipakai.
        "research": _research_identity_of(item["id"], db_path),
        "research_kept": bool(_research_in_use(item["id"], db_path)),
    }


def _research_identity_of(submission_id: int, db_path: str | None) -> str:
    """dataset_type identitas research yang lahir dari pengajuan ini; ""."""
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT dataset_type FROM research_pipelines "
                "WHERE submission_id = ?", (submission_id,)).fetchone()
        return row["dataset_type"] if row else ""
    except Exception:                        # pragma: no cover - defensif
        logger.exception("Identitas research pengajuan #%s tidak terbaca",
                         submission_id)
        return ""


def _research_in_use(submission_id: int, db_path: str | None) -> bool:
    """Apakah identitas itu masih dipakai pipeline yang terdaftar.

    Tidak tahu = anggap DIPAKAI. Menghapus identitas sebuah jenis dataset yang
    masih menjadi milik pipeline aktif akan membuat pipeline itu berhenti
    mengenali datanya sendiri; meninggalkan identitas yang tak terpakai hanya
    menahan satu nama.
    """
    dataset_type = _research_identity_of(submission_id, db_path)
    if not dataset_type:
        return False
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM registered_pipelines WHERE dataset_type = ?",
                (dataset_type,)).fetchone()
        return row is not None
    except Exception:                        # pragma: no cover - defensif
        logger.exception("Pemakaian research %s tidak terbaca", dataset_type)
        return True


def _registered_of(submission_id: int, db_path: str | None) -> list[dict]:
    """Baris registry yang lahir dari pengajuan ini."""
    from orchestrator.dynamic_registry import list_registered

    try:
        return [r for r in list_registered(db_path=db_path)
                if r.get("submission_id") == submission_id]
    except Exception:                        # pragma: no cover - defensif
        return []


def _dataset_is_bound_to_research(submission_id: int, db_path: str | None) -> bool:
    """Apakah lampiran pengajuan ini sudah menjadi dataset sebuah research."""
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM research_pipelines "
                "WHERE submission_id = ? AND dataset_json IS NOT NULL",
                (submission_id,)).fetchone()
        return row is not None
    except Exception:
        # Tidak tahu = anggap TERIKAT. Menghapus berkas yang mungkin dipakai
        # pipeline terdaftar jauh lebih merusak daripada meninggalkan berkas
        # yang mungkin yatim — yang yatim masih dapat disapu `purge_orphans`.
        logger.exception("Ikatan dataset pengajuan #%s tidak terbaca",
                         submission_id)
        return True


def delete_submission(submission_id: int, *, actor: dict | None,
                      db_path: str | None = None) -> dict:
    """Hapus sebuah pengajuan beserta jejaknya. Hanya Research Admin.

    Berlaku untuk SEMUA status. Menghapus pengajuan yang sudah DISETUJUI
    membuat ``registered_pipelines.submission_id`` menggantung: pipeline yang
    terdaftar tetap berjalan, tetapi halaman peninjauannya kehilangan kartunya.
    Itu konsekuensi yang dipilih sadar, dan halaman pipeline mengatakannya apa
    adanya ("pengajuannya telah dihapus"), bukan berpura-pura tidak terbaca.

    Yang TIDAK ikut: dataset yang sudah terikat ke sebuah research pipeline —
    ia milik pipeline itu sekarang, bukan milik pengajuannya.
    """
    from database import trials as trial_db
    from orchestrator.trial_dataset_service import discard_attachment

    require_approve(actor, db_path)

    item = get_submission(submission_id, db_path)
    if item is None:
        raise SubmissionError(
            f"Pengajuan #{submission_id} tidak ditemukan.",
            key="err.submission_not_found",
            values={"number": submission_id})

    summary = deletion_summary(item, db_path)

    # 1. Lampiran — hanya bila BELUM terikat.
    if not _dataset_is_bound_to_research(submission_id, db_path):
        try:
            discard_attachment(item, db_path)
        except Exception:                    # pragma: no cover - defensif
            logger.exception("Lampiran pengajuan #%s gagal dibuang",
                             submission_id)

    # 2. Hasil uji beserta artefaknya.
    try:
        from orchestrator.trial_service import discard_trials

        discard_trials(submission_id, db_path)
    except Exception:                        # pragma: no cover - defensif
        logger.exception("Hasil uji pengajuan #%s gagal dibuang", submission_id)

    # 3. Identitas research yang lahir dari pengajuan ini — HANYA bila tidak
    #    ada pipeline terdaftar yang memakainya.
    #
    #    Dibiarkan menggantung, ia tidak terlihat di mana pun DAN memblokir
    #    unggahan berikutnya dengan nama yang sama: `dataset_type` unik di
    #    level skema, sehingga pendaftaran ulang gagal — di tangan PENINJAU,
    #    saat menekan Setujui, jauh dari sebabnya.
    #
    #    Yang masih DIPAKAI tidak disentuh: pipeline yang terdaftar memakai
    #    jenis dataset itu sebagai miliknya, dan mencabutnya membuat pipeline
    #    yang masih berjalan berhenti mengenali datanya sendiri. Penghapusan
    #    pengajuan bukan penghapusan pipeline.
    keep_research = _research_in_use(submission_id, db_path)

    # 4. Baris pengajuan. Dihapus SEBELUM berkasnya, sehingga kegagalan
    #    menghapus berkas meninggalkan berkas yatim — bukan baris yang
    #    menunjuk berkas yang sudah tidak ada.
    with get_connection(db_path) as conn:
        if not keep_research:
            conn.execute("DELETE FROM research_pipelines WHERE submission_id = ?",
                         (submission_id,))
        conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
        conn.commit()

    # 5. Folder paketnya.
    folder = stored_location(item.get("stored_path"))
    try:
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    except OSError:                          # pragma: no cover - defensif
        logger.warning("Folder pengajuan #%s tidak dapat dibuang: %s",
                       submission_id, folder)

    logger.info("Pengajuan #%s dihapus oleh %s", submission_id,
                actor["username"])
    return summary


def approval_identity_blocker(item: dict) -> str:
    """Alasan pengajuan ini TIDAK PERNAH dapat disetujui apa adanya; "" bila
    tidak ada.

    Berbeda dari gerbang uji coba, yang menyatakan "belum boleh SEKARANG":
    yang di sini menyatakan "tidak akan pernah boleh sebelum diunggah ulang".
    Sebelumnya kekurangan ini baru terbongkar SESUDAH peninjau menekan Setujui,
    sebagai galat — padahal ia dapat diketahui tanpa menyentuh apa pun.

    Peninjau tidak lagi ditanya "ini ikut research pipeline mana": paket yang
    diunggah ADALAH research pipeline-nya sendiri, jadi pengenalnya dibentuk
    dari namanya. Pengajuan LAMA yang lahir sebelum aturan itu bisa jadi tidak
    membawa keduanya — dan itu dikatakan apa adanya, bukan ditutupi dengan
    isian yang meminta peninjau mengarang jawaban.

    Fungsi MURNI: tidak menyentuh basis data maupun disk.
    """
    from database.models import build_research_dataset_type

    if item.get("kind") != KIND_PIPELINE:
        return ""

    if is_standalone(item):
        name = research_name_of(item)
        if not name:
            return "ap.err_identity_no_name"
        if not build_research_dataset_type(name):
            return "ap.err_identity_bad_name"
        return ""

    # Menumpang jenis bawaan: sah, tetapi hanya bila jenisnya memang tercatat.
    metadata = item.get("metadata") or {}
    if not (metadata.get("dataset_type") or "").strip():
        return "ap.err_identity_legacy"
    if not (metadata.get("entry_class") or "").strip():
        return "ap.err_identity_no_entry_class"
    return ""


def reopen_blocker(item: dict, db_path: str | None = None) -> str:
    """Alasan pengajuan ini BELUM boleh ditinjau ulang; "" bila boleh.

    Alasannya selalu dinyatakan — tombol mati tanpa keterangan membuat peninjau
    menebak apa yang kurang.
    """
    from orchestrator.dynamic_registry import list_registered

    if item.get("status") != SUBMISSION_APPROVED:
        return "ap.reopen_not_approved"
    if item.get("kind") != KIND_PIPELINE:
        return "ap.reopen_only_pipeline"

    # Pipeline yang masih AKTIF sedang dapat dijalankan pengguna. Menariknya
    # kembali ke antrean saat itu membuat keadaan yang membingungkan: terdaftar
    # dan berjalan, tetapi juga "menunggu tinjauan". Nonaktifkan dulu — itu
    # keputusan sadar yang memang sudah ada tombolnya.
    try:
        rows = [r for r in list_registered(db_path=db_path)
                if r.get("submission_id") == item["id"]]
    except Exception:                        # pragma: no cover - defensif
        rows = []
    if any(r.get("active") for r in rows):
        return "ap.reopen_still_active"
    return ""


def may_reopen(item: dict, db_path: str | None = None) -> bool:
    return reopen_blocker(item, db_path) == ""


def reopen_submission(submission_id: int, *, actor: dict | None, note: str = "",
                      db_path: str | None = None) -> dict:
    """Kembalikan pengajuan yang sudah disetujui ke ANTREAN tinjauan.

    Sampai sekarang persetujuan adalah keadaan akhir: yang tersedia hanya
    menyalakan/mematikan pipelinenya dan menyunting berkasnya. Peninjauan
    penuh — uji coba, temuan, keputusan — tidak pernah dapat diulang, padahal
    justru itu yang dibutuhkan ketika sebuah pipeline dinonaktifkan karena
    bermasalah.

    Yang dilakukan di sini SATU hal: memindahkan pengajuannya kembali ke
    antrean. Ia TIDAK menyentuh versi yang sudah terdaftar — berkas dan
    barisnya tetap utuh, sehingga eksperimen lama tetap menunjuk kode yang
    persis sama. Menyetujuinya lagi nanti menghasilkan versi BARU lewat jalur
    yang sudah ada (``register_pipeline`` menghitung ``max(version) + 1``).

    Jejak peninjauan sebelumnya sengaja TIDAK dihapus: ``reviewed_by`` dan
    ``reviewed_at`` dibiarkan apa adanya sebagai riwayat, dan catatan alasan
    membuka ulang ditambahkan ke ``review_note``.
    """
    require_approve(actor, db_path)

    item = get_submission(submission_id, db_path)
    if item is None:
        raise SubmissionError(
            f"Pengajuan #{submission_id} tidak ditemukan.",
            key="err.submission_not_found",
            values={"number": submission_id})

    blocker = reopen_blocker(item, db_path)
    if blocker:
        raise SubmissionError(
            "Pengajuan ini belum dapat ditinjau ulang.", key=blocker)

    source = stored_location(item["stored_path"])
    moved = source
    if source.exists():
        moved = _move_into(source, SUBMISSION_DIRS[item["kind"]][SUBMISSION_PENDING],
                           refuse_overwrite=False)
    try:
        conn = get_connection(db_path)
        try:
            conn.execute(
                "UPDATE submissions SET status = ?, stored_path = ?, "
                "review_note = ? WHERE id = ?",
                (SUBMISSION_PENDING, str(moved),
                 (note or "").strip() or item.get("review_note"),
                 submission_id))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # Berkasnya dikembalikan bila pencatatannya gagal, supaya tidak ada
        # pengajuan berstatus approved yang berkasnya sudah pindah ke pending.
        if moved != source:
            shutil.move(str(moved), str(source))
        raise

    logger.info("Pengajuan #%s dibuka kembali untuk ditinjau oleh %s",
                submission_id, actor["username"])
    return get_submission(submission_id, db_path)


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
    source = stored_location(item["stored_path"])

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
    folder = stored_location(item["stored_path"])
    if not folder.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(folder.glob("*.py")):
        try:
            out.append((path.name, path.read_text(encoding="utf-8")))
        except OSError:                     # pragma: no cover - defensive
            logger.warning("Berkas pengajuan tidak terbaca: %s", path)
    return out
