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
    """Nama yang belum terpakai di sebuah folder. TIDAK membuat apa pun.

    Penampungan boleh menerima nama yang sama dari pengajuan berbeda, jadi di
    sini kita beri akhiran urut — BUKAN menimpa. (Untuk ``storage/datasets/``
    aturannya berbeda: menimpa ditolak mentah-mentah, lihat _move_into.)

    Dipakai untuk nama BERKAS. Folder paket memakai :func:`_reserve_dir`, yang
    memesan namanya secara atomik.
    """
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


def _reserve_dir(directory: Path, name: str) -> Path:
    """Folder paket yang namanya DIPESAN secara atomik.

    "Periksa lalu buat" adalah balapan: dua pengunggah yang menekan kirim pada
    saat yang sama sama-sama melihat nama itu kosong, lalu keduanya menulis ke
    folder yang SAMA — satu paket berisi berkas milik paket lain, dan hash yang
    tercatat tidak cocok lagi dengan apa pun. Terukur: sepuluh pengajuan
    serentak menghasilkan dua yang berbagi folder.

    ``mkdir`` tanpa ``exist_ok`` bersifat atomik di sistem berkas, jadi yang
    kalah cepat menerima ``FileExistsError`` dan mencoba nama berikutnya.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(1, 1000):
        candidate = directory / (name if i == 1 else f"{stem}__{i}{suffix}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
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
                f"berkasnya: platform tidak menimpa berkas yang sudah ada.",
                key="err.dataset_file_exists",
                values={"filename": source.name, "folder": directory.name})
        if source.is_dir():
            return _move_beside(source, _reserve_dir(directory, source.name))
        target = _unique_target(directory, source.name)
    shutil.move(str(source), str(target))
    return target


def _move_beside(source: Path, target: Path) -> Path:
    """Pindahkan ISI folder ``source`` ke ``target`` yang SUDAH dipesan.

    `_reserve_dir` memesan namanya dengan `mkdir` atomik — itulah yang menutup
    balapan dua pengunggah yang menekan kirim bersamaan. Konsekuensinya di
    sini: `shutil.move` ke folder yang sudah ada menaruh sumbernya DI DALAM
    folder itu (`p__2/p/…`) alih-alih menjadi folder itu. Jadi yang dipindahkan
    adalah isinya, lalu folder sumber yang tinggal kosong dibuang.
    """
    for anak in source.iterdir():
        shutil.move(str(anak), str(target / anak.name))
    try:
        source.rmdir()
    except OSError:                          # pragma: no cover - defensif
        logger.warning("Folder sumber tidak dapat dibuang: %s", source)
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


def _static_review(written: list[dict], package_dir) -> dict:
    """Hasil pemeriksaan statis paket yang BARU SAJA ditulis.

    Memakai ``review_package`` — mekanisme yang sama persis dengan jalur
    formulir, jadi tidak ada aturan validator kedua yang bisa menyimpang.
    Kegagalan membaca tidak menggagalkan pengajuan: yang tersimpan menjadi
    hasil "tidak dapat diperiksa", dan itu keterangan yang jujur.
    """
    from ui.components.pipeline_upload import review_package

    try:
        payload = [(b["filename"],
                    (package_dir / b["filename"]).read_bytes())
                   for b in written]
        return review_package(payload)
    except Exception:                        # pragma: no cover - defensif
        logger.warning("Pemeriksaan statis pengajuan tidak dapat dijalankan",
                       exc_info=True)
        return {"valid": False, "files": [], "entry_points": [],
                "n_problem_files": 0,
                "cause": "Paket tidak dapat diperiksa saat diajukan.",
                "summary": "Tidak dapat diperiksa."}


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
    # `_reserve_dir` sudah membuatnya, dan pembuatan itulah pemesanannya.
    package_dir = _reserve_dir(pending_root, Path(safe_entry).stem)

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
            "metadata": meta,
            # DIHITUNG di sini bila pemanggil tidak menyodorkannya. Tanpa ini,
            # pengajuan lahir dengan `validation_json` kosong, dan gerbang uji
            # membaca kekosongan itu sebagai "gagal validasi statis" — sebuah
            # jalan buntu permanen: tidak dapat diuji, karena itu tidak dapat
            # disetujui, dan tidak ada satu pun jalur untuk memperbaikinya.
            # Jalur formulir tetap menyodorkan hasilnya sendiri dan tidak
            # berubah perilakunya sama sekali.
            "validation": (validation if validation is not None
                           else _static_review(written, package_dir)),
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
    # Folder putaran revisi dibuang di tempat yang sama dengan hasil uji coba,
    # dan karena alasan yang sama: keputusan sudah tercatat, pemulihan tidak
    # mungkin lagi diperlukan, dan yang tersisa hanyalah salinan yang tidak
    # ditunjuk siapa pun. Paket yang berlaku dijaga di KEDUA lokasinya, karena
    # entri putaran terakhir masih menyebut letaknya sebelum dipindah.
    _discard_revision_folders_quietly(
        item, keep=[moved, source, revision_of(item).get("original_path")])
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


def _discard_revision_folders_quietly(item: dict, keep) -> None:
    """Buang folder PUTARAN revisi yang tidak lagi diperlukan.

    Tiap putaran meninggalkan satu salinan penuh paketnya di area penampungan,
    dan selama pengajuannya masih pending salinan itu memang berguna: dari
    sanalah riwayat dapat dibuka. Begitu keputusan diambil, ia tidak lagi
    ditunjuk siapa pun. Tanpa langkah ini, empat putaran berarti empat paket
    yang tidak terpakai dan tidak pernah dibersihkan — persis seperti hasil uji
    coba sebelum `_discard_trials_quietly` ada.

    Yang dibuang dihitung sebagai SELISIH, ditulis di sini supaya terbaca:
    seluruh folder putaran, DIKURANGI apa pun yang ada di ``keep``. Peninjau
    memanggilnya dengan paket yang berlaku (di lokasi lama maupun barunya) dan
    kiriman asli kontributor, sehingga keduanya tidak pernah dapat ikut
    terbuang karena kebetulan urutan penamaannya.

    Kegagalan membersihkan TIDAK boleh membatalkan keputusan yang sudah sah:
    berkasnya sudah pindah dan statusnya sudah tercatat.
    """
    try:
        dijaga = {stored_location(p).resolve() for p in keep if p}
        for entri in revision_history(item):
            folder = stored_location(entri.get("path") or "")
            if not entri.get("path") or folder.resolve() in dijaga:
                continue
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
    except Exception:                        # pragma: no cover - defensif
        logger.exception(
            "Gagal membuang folder revisi pengajuan #%s", (item or {}).get("id"))


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
    # Bidang yang sama punya DUA nama: formulir unggah menyimpannya sebagai
    # `researcher`, sedangkan entri registry yang dirakit di bawah menyebutnya
    # `authors`. Pengajuan yang lahir dari entri — seperti pengajuan yang
    # disusun ulang dari paket yang sudah terdaftar — membawa nama yang kedua.
    # Keduanya dibaca, sehingga kreditnya tidak pernah jatuh ke institusi saja
    # hanya karena namanya dieja berbeda.
    researcher = (metadata.get("researcher") or metadata.get("authors") or "")
    credit = research_credit(researcher,
                             metadata.get("year"), institution)
    # Cadangan terakhir: pengajuan paling lama hanya punya satu kolom bebas.
    credit = credit or str(metadata.get("paper") or "").strip()

    # Pemisahnya dibaca dari `research_registry`, bukan diketik ulang:
    # label di sini dan label yang dirakit registry itu HARUS sama, dan
    # dua salinan pasti menyimpang suatu saat.
    from orchestrator.research_registry import LABEL_SEP

    display = f"{credit}{LABEL_SEP}{name}" if credit else name
    out = {k: v for k, v in (("display_name", display),
                             ("short_name", name),
                             ("paper_credit", credit),
                             ("scope", str(metadata.get("scope") or "").strip()),
                             ("pipeline_source",
                              _clean({"type": metadata.get("source_type"),
                                      "authors": researcher,
                                      "title": metadata.get("title"),
                                      "institution": institution,
                                      "year": metadata.get("year")})),
                             ("dataset_source",
                              _clean({"name": metadata.get("dataset_name"),
                                      "attribution":
                                          metadata.get("dataset_attribution"),
                                      "note": metadata.get("dataset_note"),
                                      # Keterangan dataset yang DITERIMA
                                      # pipeline ini. Empat bidang inilah yang
                                      # membuat panel persyaratan sebuah
                                      # research kontribusi dapat berkata
                                      # selengkap research bawaan tanpa
                                      # mengarang satu kalimat pun.
                                      "row_unit":
                                          metadata.get("dataset_row_unit"),
                                      "label_meaning":
                                          metadata.get("dataset_label_meaning"),
                                      "feature_nature":
                                          metadata.get("dataset_feature_nature"),
                                      "class_count":
                                          metadata.get("dataset_class_count"),
                                      # Contoh nilai & kolom yang boleh ada
                                      # tetapi diabaikan: dua bidang terakhir
                                      # yang dahulu hanya dipunyai tabel
                                      # persyaratan milik platform.
                                      "sample_values":
                                          metadata.get("dataset_sample_values"),
                                      "ignored_columns":
                                          _joined(metadata.get(
                                              "dataset_ignored_columns"))})),
                             # Keterangan METODE. Ia tinggal di sini, bukan di
                             # dalam potret `info_json`, karena potret itu milik
                             # satu versi satu algoritma dan tidak boleh diubah
                             # — ia rekaman apa yang kodenya katakan. Keterangan
                             # ini milik researchnya, berlaku untuk seluruh
                             # algoritma dan versinya, dan justru HARUS dapat
                             # diperbaiki. Penggabungannya terjadi saat tampil,
                             # dengan aturan yang sama: kode menang.
                             ("method_notes", info_extra_of(metadata)),
                             ) if v}
    return out


def _joined(value) -> str:
    """Daftar -> satu kalimat berkoma; teks dibiarkan apa adanya."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    return str(value or "").strip()


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
            # Yang DIKETAHUI di sini saja: nama yang terbaca statis dari
            # kodenya, lalu yang diketik di formulir. Cadangan berikutnya
            # (`get_info()["algorithm"]`, baru nama kelas) ditentukan
            # `register_pipeline`, sebab di sanalah potret `get_info()` ada.
            # Menjatuhkannya ke nama kelas DI SINI membuat cadangan yang lebih
            # baik itu tidak pernah terpakai: pipeline terdaftar sebagai
            # "AuditSinglePipeline" padahal kodenya menyebut "Decision Tree".
            algorithm=(entry.get("algorithm") or metadata.get("algorithm")
                       or None),
            paper=metadata.get("paper"),
            # Fase milik BERKAS ini, bukan milik paketnya: satu paket boleh
            # memuat beberapa algoritma dengan urutan fase yang berbeda.
            stages=entry.get("stages") or None,
            # Keterangan metode dari FORMULIR — hanya untuk paket yang
            # MENUMPANG jenis dataset bawaan. Paket itu tidak punya baris
            # research sendiri, jadi tidak ada tempat lain yang memilikinya dan
            # potretlah satu-satunya rumahnya. Research yang BERDIRI SENDIRI
            # menyimpannya di baris researchnya (`research_attribution_of`)
            # supaya dapat disunting; menitipkannya ke potret juga akan
            # membuat salinan basi yang menutupi suntingan itu.
            #
            # Apa pun jalurnya, ia hanya mengisi kunci yang `get_info()`
            # pipeline ini tidak menyebutkan — kode selalu menang, lihat
            # `dynamic_registry.merge_info`.
            info_extra=_info_extra_for(item, metadata, entry),
            db_path=db_path,
        )


def placement_for_algorithm(item: dict, class_name: str) -> list[dict]:
    """Berkas yang ditugaskan kepada SATU algoritma, beserta fasenya.

    Yang ikut: berkas yang menyebut kelas ini, dan berkas bertanda "semua
    algoritma" — sebuah `common_prep.py` yang dipakai bersama memang milik
    ketiganya. Yang ditugaskan kepada algoritma LAIN tidak ikut: baris registry
    ini menggambarkan satu algoritma, dan membawa berkas milik tetangganya akan
    membuat katalog menyebut berkas yang tidak ada hubungannya.

    Fungsi MURNI.
    """
    keluar = []
    for nama, entri in sorted(placement_of(item).items()):
        milik = [str(a) for a in (entri or {}).get("algorithms") or []]
        if class_name not in milik and ALGO_ALL not in milik:
            continue
        keluar.append({"filename": nama,
                       "phases": [str(f) for f in (entri or {}).get("phases") or []],
                       "shared": ALGO_ALL in milik})
    return keluar


def _info_extra_for(item: dict, metadata: dict, entry: dict) -> dict | None:
    """Keterangan tambahan satu baris registry: metode + peta penempatan.

    Peta ikut sebagai KETERANGAN, menumpang `info_json` yang sudah ada. Tidak
    ada kolom baru, dan tidak satu pun pembacanya berada di jalur menjalankan
    pipeline: `entry_class`, `entry_file`, hash, dan `stages` tetap ditentukan
    hal yang sama seperti sebelumnya.
    """
    # Keterangan metode dari FORMULIR hanya untuk paket yang MENUMPANG jenis
    # dataset bawaan; yang berdiri sendiri menyimpannya di baris researchnya.
    tambahan = {} if is_standalone(item) else dict(info_extra_of(metadata))
    berkas = placement_for_algorithm(item, entry.get("class_name") or "")
    if berkas:
        tambahan["file_placement"] = berkas
    return tambahan or None


def info_extra_of(metadata: dict | None) -> dict:
    """Keterangan metode yang dinyatakan pengunggah di FORMULIR.

    Empat kunci ini ditulis pipeline BAWAAN di dalam ``get_info()`` dan
    ditampilkan pada modal katalog serta panel "Tentang Research Pipeline",
    tetapi validator tidak mewajibkannya — jadi paket kontribusi hampir tidak
    pernah memuatnya, dan keempat tempat itu kosong. Menanyakannya di formulir
    menutup kekosongan itu tanpa menolak satu pun paket lama.

    Baris kosong dibuang; ``anti_leakage`` menjadi DAFTAR karena penyajinya
    memang menggabungkan daftar menjadi satu kalimat.

    Fungsi MURNI.
    """
    metadata = metadata or {}
    anti = [b.strip() for b in
            str(metadata.get("info_anti_leakage") or "").splitlines() if b.strip()]
    keluar = {"app": str(metadata.get("info_app") or "").strip(),
              "metrics_policy": str(metadata.get("info_metrics_policy") or "").strip(),
              "dataset": str(metadata.get("info_dataset") or "").strip()}
    out = {k: v for k, v in keluar.items() if v}
    if anti:
        out["anti_leakage"] = anti

    # Dua kunci berikut dahulu TIDAK dapat diisi siapa pun: modal katalog
    # menampilkan bagian "Hyperparameter terkunci" dan "Langkah preprocessing",
    # tetapi formulir tidak menanyakan keduanya — jadi paket yang kodenya tidak
    # menyebutkannya menampilkan dua bagian yang selamanya kosong, tanpa satu
    # pun tempat untuk mengisinya.
    #
    # Bentuknya dibuat SAMA dengan yang ditulis kode: daftar untuk langkah,
    # peta untuk hyperparameter. Penyajinya membedakan keduanya (lihat
    # `pipeline_catalog._render_value`), jadi mengirim teks polos akan
    # tergambar sebagai satu baris keterangan alih-alih daftar.
    langkah = [b.strip() for b in
               str(metadata.get("info_preprocessing") or "").splitlines()
               if b.strip()]
    if langkah:
        out["preprocessing_steps"] = langkah
    params = parse_fixed_params(metadata.get("info_fixed_params"))
    if params:
        out["fixed_params"] = params
    return out


def parse_fixed_params(teks) -> dict:
    """``"test_size: 0.3"`` per baris menjadi ``{"test_size": "0.3"}``. MURNI.

    Baris tanpa pemisah DIABAIKAN, bukan disimpan sebagai kunci tanpa nilai:
    "n_estimators" sendirian tidak menyatakan apa pun tentang parameter, dan
    menyimpannya membuat modal menampilkan baris yang isinya kosong.

    Nilainya dibiarkan sebagai TEKS. Menebak tipenya — 0.3 menjadi float, True
    menjadi bool — berarti menampilkan nilai yang bentuknya tidak persis sama
    dengan yang diketik pengunggah, dan bagian ini hanya menerangkan.
    """
    keluar: dict[str, str] = {}
    for baris in str(teks or "").splitlines():
        bersih = baris.strip()
        if not bersih:
            continue
        for pemisah in (":", "="):
            if pemisah in bersih:
                kunci, _, nilai = bersih.partition(pemisah)
                kunci, nilai = kunci.strip(), nilai.strip()
                if kunci and nilai:
                    keluar[kunci] = nilai
                break
    return keluar


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

    # 5. Folder paketnya — yang BERLAKU dan, bila pernah direvisi, folder
    #    kiriman asli kontributor juga. Melewatkan yang kedua meninggalkan
    #    berkas yatim: tidak ada baris basis data yang menunjuknya lagi, jadi
    #    tidak ada pula yang akan membuangnya nanti.
    folders = [stored_location(item.get("stored_path"))]
    asal = revision_of(item).get("original_path")
    if asal:
        folders.append(stored_location(asal))
    # Dan folder tiap PUTARAN di antara keduanya. Tanpa ini, menghapus sebuah
    # pengajuan yang pernah direvisi tiga kali tetap meninggalkan dua paket
    # yatim: tidak ada baris yang menunjuknya, jadi tidak ada pula yang akan
    # membuangnya nanti.
    folders += [stored_location(e["path"]) for e in revision_history(item)
                if e.get("path")]
    for folder in folders:
        try:
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:                      # pragma: no cover - defensif
            logger.warning("Folder pengajuan #%s tidak dapat dibuang: %s",
                           submission_id, folder)

    logger.info("Pengajuan #%s dihapus oleh %s", submission_id,
                actor["username"])
    return summary


# ── Revisi paket oleh peninjau, SEBELUM disetujui ───────────────────
#
# Peninjau mengunduh paket, menyuntingnya di luar platform, lalu mengunggahnya
# kembali. Yang terjadi setelah itu bukan "berkasnya diganti": paket hasil
# revisi menjadi paket yang BERLAKU — `stored_path`, `file_hash`, dan daftar
# berkas di `metadata_json` semuanya beralih menunjuk kepadanya — sementara
# kiriman asli kontributor tetap ada di disk dan tercatat di `revision_json`.
#
# Arah itu dipilih dengan sadar, dan konsekuensinya ada dua sisi.
#
# Sisi baiknya: SETIAP pembaca yang sudah ada ikut benar tanpa diubah satu
# baris pun. `approve_submission` memindahkan paket yang berlaku,
# `read_submission_sources` menampilkannya, `trial_service` mengujinya, dan
# kunci cache pemeriksaan statis di UI — yang berupa `file_hash` — batal
# dengan sendirinya begitu isinya berubah. Sembilan pembaca, nol perubahan.
#
# Sisi yang harus dijaga: `file_hash` tidak lagi membuktikan apa yang dikirim
# kontributor. Itulah tugas `revision_json`, dan itulah sebabnya kolom itu ada.

#: Berapa banyak berkas `.py` yang boleh dibawa satu revisi. Sama dengan batas
#: pengajuan awal — revisi bukan pintu belakang untuk paket yang lebih besar.
MAX_REVISION_FILES = 20


def package_digest(item: dict) -> str:
    """Sidik jari SELURUH paket — bukan titik masuknya saja.

    ``file_hash`` hanya melacak titik masuk. Sebuah revisi yang menyentuh
    berkas PENDUKUNG karena itu tidak mengubahnya, dan apa pun yang memakainya
    sebagai penanda kesegaran akan menyajikan hasil lama untuk paket yang
    isinya sudah berbeda — terukur: peninjau membaca "lolos" untuk kode yang
    bukan lagi kode itu.

    DITURUNKAN, bukan disimpan: ``metadata["files"]`` sudah memuat sha256 tiap
    berkas, ditulis jalur unggah maupun jalur revisi. Jadi tidak ada kolom
    baru, tidak ada migrasi, dan pengajuan lama ikut benar tanpa pengisian
    mundur apa pun.

    Urutannya distabilkan dengan mengurutkan nama berkas: dua paket dengan isi
    sama harus menghasilkan sidik jari sama, apa pun urutan penulisannya.

    Pengajuan yang — entah bagaimana — tidak punya daftar berkas jatuh kembali
    ke ``file_hash``. Itu perilaku hari ini, jadi tidak ada yang memburuk.
    """
    berkas = _meta_files(item)
    if not berkas:
        return (item or {}).get("file_hash") or ""
    bahan = ";".join(f"{f.get('filename')}:{f.get('sha256')}"
                     for f in sorted(berkas, key=lambda f: str(f.get("filename"))))
    return hashlib.sha256(bahan.encode("utf-8")).hexdigest()


def revision_of(item: dict) -> dict:
    """Catatan revisi sebuah pengajuan; ``{}`` bila belum pernah direvisi."""
    raw = (item or {}).get("revision_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):          # pragma: no cover - defensif
        logger.warning("revision_json tidak terbaca pada pengajuan #%s",
                       (item or {}).get("id"))
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_revised(item: dict) -> bool:
    """Apakah paket yang berlaku berasal dari peninjau, bukan dari pengaju."""
    return bool(revision_of(item))


def submitted_hash(item: dict) -> str:
    """Hash titik masuk yang BENAR-BENAR dikirim kontributor.

    Berbeda dari ``item["file_hash"]`` begitu pengajuannya direvisi: yang di
    kolom adalah paket yang berlaku, yang di sini adalah buktinya.
    """
    return revision_of(item).get("original_hash") or (item or {}).get("file_hash") or ""


#: Penanda algoritma "semua", untuk berkas pendukung yang dipakai bersama.
#: Disimpan sebagai PENGENAL, bukan kalimat berbahasa: labelnya diterjemahkan
#: saat digambar, sehingga peta yang tersimpan tidak berubah arti ketika
#: pengguna berganti bahasa. Tinggal di sini, bukan di lapis tampilan, karena
#: ia bagian dari bentuk data yang ditulis ke `metadata_json`.
ALGO_ALL = "*"


def placement_of(item: dict) -> dict:
    """Peta penempatan berkas yang TERSIMPAN; ``{}`` bila belum pernah diisi.

    Yang dikembalikan hanya apa yang benar-benar disimpan. Semaian dari
    pembacaan kode dikerjakan lapis penyaji (`submission_review.
    seeded_placement`), sebab ia turunan yang dapat dihitung ulang kapan saja
    dan tidak boleh mengendap di basis data sebagai keputusan manusia.
    """
    peta = (item or {}).get("metadata") or {}
    nilai = peta.get("placement")
    return nilai if isinstance(nilai, dict) else {}


@_retry_on_locked()
def set_placement(submission_id: int, placement: dict, *, actor: dict | None,
                  db_path: str | None = None) -> dict:
    """Simpan peta penempatan berkas sebuah pengajuan. Hanya Research Admin.

    Peta ini MENERANGKAN: ia menjawab berkas mana bekerja pada fase mana untuk
    algoritma yang mana. Tidak satu pun pembacanya berada di jalur menjalankan
    pipeline, dan tidak ada yang berubah pada apa yang dimuat saat eksperimen
    dijalankan.

    Nama berkas yang tidak ada di paket DITOLAK, bukan disimpan diam-diam:
    peta yang menyebut berkas yang tidak ada adalah peta yang berbohong, dan
    satu-satunya yang membacanya adalah layar yang dipakai memutuskan.
    """
    require_approve(actor, db_path)
    item = get_submission(submission_id, db_path)
    if not item:
        raise SubmissionError(f"Pengajuan #{submission_id} tidak ditemukan.",
                              key="err.submission_not_found",
                              values={"number": submission_id})

    dikenal = {f.get("filename") for f in _meta_files(item)}
    bersih: dict[str, dict] = {}
    for nama, entri in (placement or {}).items():
        if nama not in dikenal:
            raise SubmissionError(
                f"Berkas `{nama}` tidak ada di paket pengajuan ini.",
                key="ap.placement_unknown_file", values={"filename": nama})
        fase = [str(f) for f in (entri or {}).get("phases") or [] if str(f).strip()]
        algo = [str(a) for a in (entri or {}).get("algorithms") or [] if str(a).strip()]
        if fase or algo:
            bersih[nama] = {"phases": fase, "algorithms": algo}

    meta = dict(item.get("metadata") or {})
    if bersih:
        meta["placement"] = bersih
    else:
        meta.pop("placement", None)
    with get_connection(db_path) as conn:
        conn.execute("UPDATE submissions SET metadata_json = ? WHERE id = ?",
                     (json.dumps(meta), submission_id))
        conn.commit()
    logger.info("Penempatan berkas pengajuan #%s disimpan oleh %s (%d berkas)",
                submission_id, actor["username"], len(bersih))
    return get_submission(submission_id, db_path)


def revision_history(item: dict) -> list[dict]:
    """SETIAP putaran revisi pengajuan ini, terurut menaik; ``[]`` bila belum.

    Kolomnya dahulu menyimpan satu putaran saja dan MENIMPA dirinya tiap kali
    direvisi. Akibatnya terukur pada data yang ada: sebuah pengajuan berkata
    "revisi ke-3" sementara catatan putaran 1 dan 2 sudah tidak ada di mana
    pun, dan tidak ada apa pun di layar yang dapat membukanya. Itulah yang
    diperbaiki `history`.

    Bentuk LAMA tetap terbaca, dan dibaca dengan JUJUR. Putaran yang catatannya
    memang sudah hilang TIDAK dikarang: yang dikembalikan adalah satu entri —
    putaran terakhir, satu-satunya yang masih ada buktinya — dengan penanda
    ``partial`` yang berarti "ada putaran sebelum ini yang tidak tercatat".
    Mengisinya dengan tanggal atau nama tebakan akan membuat layar berbohong
    lebih meyakinkan daripada kolom yang kosong.

    Fungsi MURNI: tidak menyentuh basis data maupun disk. Entri yang menyebut
    folder yang sudah dibersihkan tetap sah sebagai catatan, jadi yang membaca
    memeriksa keberadaan foldernya sendiri (lihat :func:`revision_sources`).
    """
    catatan = revision_of(item)
    if not catatan:
        return []
    riwayat = catatan.get("history")
    if isinstance(riwayat, list):
        # `partial` dinormalkan di sini, sekali, supaya tiap pembaca menerima
        # bentuk yang SAMA apa pun asal datanya — entri yang baru ditulis tidak
        # menyimpannya, sebab tidak ada yang hilang padanya.
        entri = [{"partial": False, **e} for e in riwayat if isinstance(e, dict)]
        if entri:
            return sorted(entri, key=lambda e: int(e.get("round") or 0))
    putaran = int(catatan.get("round") or 1)
    return [{
        "round": putaran,
        "by": catatan.get("by") or "",
        "at": catatan.get("at") or "",
        "note": catatan.get("note") or "",
        # Paket yang BERLAKU adalah hasil putaran terakhir, jadi itulah
        # foldernya. Putaran sebelumnya tidak pernah dicatat jalurnya.
        "path": str((item or {}).get("stored_path") or ""),
        "changed": list(catatan.get("changed") or []),
        "added": list(catatan.get("added") or []),
        "kept": list(catatan.get("kept") or []),
        "partial": putaran > 1,
    }]


def revision_sources(entry: dict) -> list[tuple[str, str]]:
    """``[(nama, teks)]`` berkas satu PUTARAN revisi, untuk DITAMPILKAN.

    Dibaca sebagai teks, tidak pernah diimpor maupun dijalankan — aturan yang
    sama dengan :func:`read_submission_sources`. Folder yang sudah dibersihkan
    mengembalikan ``[]``: itu keadaan yang wajar setelah pengajuannya
    diputuskan, bukan kesalahan.
    """
    jalur = (entry or {}).get("path")
    if not jalur:
        return []
    folder = stored_location(jalur)
    if not folder.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(folder.glob("*.py")):
        try:
            out.append((path.name, path.read_text(encoding="utf-8")))
        except OSError:                      # pragma: no cover - defensif
            logger.warning("Berkas putaran revisi tidak terbaca: %s", path)
    return out


def revision_blocker(item: dict) -> str:
    """Alasan pengajuan ini tidak dapat direvisi; ``""`` bila boleh.

    Fungsi MURNI: tidak menyentuh basis data maupun disk. Dipakai UI untuk
    mematikan tombol DENGAN keterangan, dan dipakai lagi oleh aksinya sendiri
    — tombol yang tersembunyi tidak pernah menjadi satu-satunya penghalang.
    """
    if not item:
        return "err.submission_not_found"
    if item.get("kind") != KIND_PIPELINE:
        return "ap.revise_only_pipeline"
    if item.get("status") != SUBMISSION_PENDING:
        return "ap.revise_only_pending"
    return ""


def may_revise(item: dict) -> bool:
    return not revision_blocker(item)


@_retry_on_locked()
def revise_submission(submission_id: int, files: list[tuple[str, str]],
                      entry_filename: str, *, note: str,
                      actor: dict | None,
                      db_path: str | None = None) -> dict:
    """Ganti paket sebuah pengajuan pending dengan hasil suntingan peninjau.

    Urutannya sengaja begini, dan tiap langkah adalah pengaman:

    1. **izin** — hanya Research Admin, ditegakkan di sini dan bukan di tombol;
    2. **keadaan** — hanya pengajuan pipeline yang masih `pending`;
    3. **catatan WAJIB** — peninjau mengubah kiriman orang lain, jadi alasannya
       tercatat bersama perbuatannya, bukan diingat-ingat;
    4. **validasi statis** — gagal berarti berhenti DI SINI, sebelum ada satu
       berkas pun yang ditulis;
    5. **tulis ke folder BARU** — folder kiriman asli tidak pernah disentuh;
    6. **alihkan** `stored_path`/`file_hash`/daftar berkas ke paket baru, dan
       catat kiriman aslinya di `revision_json` sebagai bukti.

    Kode kontribusi TIDAK PERNAH dijalankan di sini: berkasnya ditulis sebagai
    teks dan divalidasi secara statis, sama seperti jalur pengajuan awal.
    """
    # Validator yang SAMA dengan jalur unggah, bukan `validate_package`.
    # Keduanya memeriksa berkas dengan cara yang sama, tetapi
    # `validate_package` menambah satu aturan milik penyunting versi: tepat
    # satu titik masuk. Sebuah PENGAJUAN boleh membawa beberapa algoritma —
    # jalur unggah memang menerimanya — sehingga memakainya di sini membuat
    # paket yang sudah diterima platform tidak dapat direvisi sama sekali,
    # dengan pesan yang menyalahkan kodenya.
    from ui.components.pipeline_upload import (
        extract_registry_metadata, review_package,
    )

    require_approve(actor, db_path)

    item = get_submission(submission_id, db_path)
    blocked = revision_blocker(item)
    if blocked:
        raise SubmissionError(
            f"Pengajuan #{submission_id} tidak dapat direvisi.", key=blocked,
            values={"number": submission_id})

    if not (note or "").strip():
        raise SubmissionError(
            "Catatan revisi wajib diisi.", key="ap.revise_note_required")
    if not files:
        raise SubmissionError("Tidak ada berkas untuk direvisi.",
                              key="err.no_files_to_submit")
    if len(files) > MAX_REVISION_FILES:
        raise SubmissionError(
            f"Terlalu banyak berkas: {len(files)}.",
            key="ap.revise_too_many_files",
            values={"count": len(files), "max": MAX_REVISION_FILES})

    safe_entry = _sanitize(entry_filename, PIPELINE_SUFFIXES)
    diunggah = {_sanitize(name, PIPELINE_SUFFIXES): source
                for name, source in files}

    # Yang diunggah MENAMBAL paket yang berlaku, bukan menggantinya.
    #
    # Peninjau yang menyunting satu berkas dari paket berisi empat akan
    # mengunggah satu berkas, karena itulah yang ia ubah. Memperlakukan
    # unggahan sebagai paket utuh membuat tiga berkas lainnya hilang tanpa
    # sepatah kata: berkas pendukung yang masih diimpor lenyap, dan titik
    # masuknya berpindah ke berkas yang kebetulan tersisa. Paket seperti itu
    # tetap lolos pemeriksaan statis, karena yang tersisa memang sah.
    #
    # Membuang sebuah berkas karena itu bukan efek samping dari menyunting
    # berkas lain; ia tindakan tersendiri yang harus dinyatakan.
    berlaku = dict(read_submission_sources(item))
    bersih = {**berlaku, **diunggah}
    if safe_entry not in bersih:
        raise SubmissionError(
            f"Entry point `{safe_entry}` tidak ada di antara berkas paket.",
            key="err.entry_not_in_files", values={"filename": safe_entry})

    # 4. VALIDASI SEBELUM MENULIS. Paket yang ditolak tidak meninggalkan jejak
    #    apa pun di disk — inilah sebabnya langkah ini mendahului langkah 5.
    report = review_package([(nama, teks.encode("utf-8"))
                             for nama, teks in bersih.items()])
    if not report.get("valid"):
        raise SubmissionError(
            "Paket revisi tidak lolos pemeriksaan statis.",
            key="ap.revise_invalid_package")
    if safe_entry not in (report.get("entry_points") or []):
        raise SubmissionError(
            f"`{safe_entry}` bukan titik masuk pada paket revisi.",
            key="ap.revise_entry_not_a_pipeline",
            values={"filename": safe_entry})

    # Asal tiap berkas pada paket hasil gabungan, untuk ditampilkan kembali.
    asal = {nama: ("diubah" if nama in berlaku and berlaku[nama] != teks
                   else "tetap" if nama in berlaku else "ditambahkan")
            for nama, teks in bersih.items()}

    # Revisi yang tidak mengubah apa pun BUKAN revisi.
    #
    # Yang terjadi tanpa pemeriksaan ini terbaca pada data sungguhan: sebuah
    # pengajuan berakhir di "revisi ke-3" dengan `changed: []` dan `added: []`
    # pada ketiga putarannya, masing-masing meninggalkan satu salinan penuh
    # paket yang sama di disk. Peninjau mengunggah ulang isi yang sama, dan
    # platform mencatatnya sebagai perbuatan.
    #
    # Ditolak DI SINI, sebelum `package_dir` dibuat, sehingga tidak ada satu
    # berkas pun yang ditulis — aturan yang sama dengan penolakan validasi
    # statis di atasnya.
    if not any(a in ("diubah", "ditambahkan") for a in asal.values()):
        raise SubmissionError(
            "Tidak ada berkas yang berubah pada revisi ini.",
            key="ap.revise_no_change")

    asli = revision_of(item)
    original_path = asli.get("original_path") or item["stored_path"]
    original_hash = asli.get("original_hash") or item["file_hash"]
    original_files = asli.get("original_files") or _meta_files(item)
    putaran = int(asli.get("round") or 0) + 1
    # Dibaca SEBELUM kolomnya ditulis ulang: sesudah itu, putaran sebelumnya
    # hanya ada di sini.
    riwayat_sebelumnya = revision_history(item)

    pending_root = SUBMISSION_DIRS[KIND_PIPELINE][SUBMISSION_PENDING]
    package_dir = _reserve_dir(pending_root, f"{Path(safe_entry).stem}__rev")

    written: list[dict] = []
    entry_hash, total = "", 0
    try:
        for name, source in bersih.items():
            stored = _write_text(source, package_dir / name)
            written.append({"filename": name, "sha256": stored.sha256,
                            "size": stored.size})
            total += stored.size
            if name == safe_entry:
                entry_hash = stored.sha256

        meta = dict(item.get("metadata") or {})
        meta["files"] = written
        meta["entry_filename"] = safe_entry

        # Peta penempatan mengikuti BERKAS. Yang masih ada mempertahankan
        # penempatannya, yang dibuang revisi ini ikut hilang, dan berkas baru
        # TIDAK dibuatkan entri: ia memang belum ditempatkan, dan mengarangnya
        # di sini akan menyembunyikan keadaan yang justru harus terbaca.
        peta = {n: v for n, v in placement_of(item).items() if n in bersih}
        if peta:
            meta["placement"] = peta
        else:
            meta.pop("placement", None)

        # POTRET ULANG apa yang dikatakan kode revisi. Tanpa ini metadata
        # tetap menggambarkan paket LAMA: menyetujuinya akan mendaftarkan nama
        # kelas yang tidak ada lagi di berkasnya, dan pipeline itu baru
        # ketahuan gagal saat eksperimen dijalankan — bukan saat disetujui.
        # Dibaca STATIS dengan pembaca yang sama persis dengan jalur unggah;
        # tidak ada kode paket yang diimpor maupun dijalankan.
        algoritma = []
        for nama in report.get("entry_points") or []:
            statis = extract_registry_metadata(bersih[nama], nama) or {}
            algoritma.append({"filename": nama,
                              "class_name": statis.get("class_name"),
                              "algorithm": statis.get("algorithm"),
                              "stages": list(statis.get("stages") or [])})
        if algoritma:
            meta["algorithms"] = algoritma
            # Dipertahankan untuk pembaca yang hanya mengenal satu titik masuk.
            utama = next((a for a in algoritma if a["filename"] == safe_entry),
                         algoritma[0])
            meta["entry_class"] = utama["class_name"]
        # Satu cap waktu dipakai dua kali, sehingga entri riwayat dan ringkasan
        # putaran terakhir tidak pernah menyebut dua saat yang berbeda untuk
        # satu perbuatan yang sama.
        saat = now_iso()
        entri = {
            "round": putaran,
            "by": actor["username"],
            "at": saat,
            "note": note.strip(),
            # Foldernya dicatat, karena riwayat yang tidak dapat DIBUKA hanya
            # memindahkan pertanyaannya: "apa yang diubah pada putaran 1" tetap
            # tidak terjawab oleh sebaris catatan.
            "path": str(package_dir),
            # Apa yang sesungguhnya berubah pada putaran ini. Tanpa ini,
            # "revisi ke-2" tidak memberi tahu apa pun tentang isinya.
            "changed": sorted(n for n, a in asal.items() if a == "diubah"),
            "added": sorted(n for n, a in asal.items() if a == "ditambahkan"),
            "kept": sorted(n for n, a in asal.items() if a == "tetap"),
        }
        catatan = {
            # Kunci tingkat atas TETAP menggambarkan putaran TERAKHIR. Delapan
            # pembaca yang sudah ada membacanya, dan tidak satu pun perlu tahu
            # bahwa riwayatnya kini tersimpan.
            **{k: v for k, v in entri.items() if k != "path"},
            "original_path": str(original_path),
            "original_hash": original_hash,
            "original_files": original_files,
            # Dan ini yang baru: seluruh putaran, termasuk yang ini. Bentuk
            # lama yang belum punya kunci ini terbaca sebagai riwayat berisi
            # satu entri, jadi tidak ada pengisian mundur yang diperlukan.
            "history": [*riwayat_sebelumnya, entri],
        }
        with get_connection(db_path) as conn:
            conn.execute(
                """UPDATE submissions
                   SET stored_path = ?, file_hash = ?, file_size = ?,
                       original_filename = ?, metadata_json = ?,
                       revision_json = ?
                   WHERE id = ?""",
                (str(package_dir), entry_hash, total, safe_entry,
                 json.dumps(meta), json.dumps(catatan), submission_id))
            conn.commit()
    except Exception:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise

    logger.info("Pengajuan #%s direvisi oleh %s (putaran %s, %d berkas)",
                submission_id, actor["username"], putaran, len(written))
    return get_submission(submission_id, db_path)


def _meta_files(item: dict) -> list[dict]:
    """Daftar berkas pada metadata sebuah pengajuan; [] bila tidak terbaca.

    Dibaca dari ``item["metadata"]`` yang sudah diurai ``_row_to_dict``, bukan
    dari ``metadata_json`` mentah — supaya satu tempat saja yang tahu bentuk
    penyimpanannya.
    """
    files = (item.get("metadata") or {}).get("files")
    return [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []


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
    _discard_revision_folders_quietly(
        item, keep=[moved, source, revision_of(item).get("original_path")])
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
