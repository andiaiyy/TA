"""
Uji coba pipeline SEBELUM persetujuan.

Sejak fitur unggah ada, berlaku satu aturan: **kode yang belum disetujui tidak
pernah dijalankan** — itulah sebabnya validasi dibuat statis. Modul ini
membalik aturan itu untuk satu keperluan sempit, jadi pengamannya ditulis
di sini, di satu tempat, dan setiap satunya dijelaskan alasannya:

1. **Validator tetap gerbang pertama.** Hanya paket yang LOLOS pemeriksaan
   statis yang boleh diuji. Yang gagal tidak dapat diuji sama sekali — bukan
   "diuji dengan hati-hati", melainkan ditolak sebelum berkasnya dibuka.
2. **Hanya Research Admin.** Ditegakkan di fungsi lewat ``require_approve``,
   bukan dengan menyembunyikan tombol.
3. **Jalur eksekusi yang sama.** Uji coba memakai ``run_pipeline`` yang sama
   dengan eksperimen biasa, di dalam proses pekerja yang sama, sehingga batas
   waktu dan memori yang sudah berlaku tetap berlaku. Tidak ada jalur baru
   yang melewati pengaman yang ada.
4. **Batas lebih ketat.** Uji coba dibatasi waktu DAN jumlah baris, keduanya
   lebih ketat daripada eksperimen biasa — lihat :data:`TRIAL_LIMITS`.

Hasil uji TIDAK PERNAH masuk tabel ``experiments``: ia hidup di
``pipeline_trials`` dan dihapus setelah keputusan diambil. Lihat
``database/trials.py`` untuk alasannya.
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from config.settings import DATASETS_DIR
from database import trials as trial_db
from database.db import get_connection
from orchestrator.auth_service import require_approve
from orchestrator.user_errors import UserFacingMixin

logger = logging.getLogger(__name__)

#: Akar artefak uji. Terpisah dari `storage/artifacts/` supaya artefak uji
#: tidak pernah tercampur dengan artefak eksperimen penelitian, dan supaya
#: pembersihannya dapat dibuktikan dengan melihat satu folder.
TRIAL_ROOT = Path("storage/trials")

#: Batas uji coba — SENGAJA lebih ketat daripada eksperimen biasa.
#:
#: * ``max_seconds`` 300 detik vs 3600 detik pada eksperimen. Uji coba menjawab
#:   "apakah pipeline ini berjalan", bukan "berapa skor terbaiknya"; lima menit
#:   cukup untuk menemukan kesalahan kontrak, impor, bentuk data, dan kolom
#:   yang tidak ada — yang justru menjadi alasan fitur ini ada.
#: * ``max_rows`` 50.000 baris. Dataset penelitian di platform ini berukuran
#:   ratusan ribu sampai jutaan baris; membacanya seluruhnya membuat uji coba
#:   memakan memori sebesar eksperimen sungguhan, padahal kesalahan yang
#:   dicari muncul pada baris pertama sama seperti pada baris terakhir.
#: * ``stale_hours`` 24 jam: batas kewajaran sebuah peninjauan yang belum
#:   diputuskan (lihat :func:`cleanup_stale_trials`).
TRIAL_LIMITS = {
    "max_seconds": 300,
    "max_rows": 50_000,
    "stale_hours": 24,
}


class TrialError(UserFacingMixin, RuntimeError):
    """Uji coba tidak dapat dijalankan, atau ditolak pengamannya."""


# ── Sidik jari paket ─────────────────────────────────────────────────────

def package_fingerprint(files: dict) -> str:
    """Sidik jari isi paket pengajuan.

    Algoritmanya SAMA PERSIS dengan `manage_pipelines.package_fingerprint`
    (SHA-256 atas nama+isi tiap berkas, urut nama), supaya "uji ini masih
    berlaku" dinilai dengan ukuran yang sama dengan "pemeriksaan ini masih
    berlaku"; sebuah test menjaga keduanya tidak berpisah diam-diam. Ditulis
    ulang di sini, bukan diimpor, karena orchestrator tidak boleh bergantung
    pada lapisan tampilan.

    Menyunting satu karakter pun mengubah nilainya — itulah yang menutup celah
    "uji versi bersih lalu sunting lalu setujui".
    """
    import hashlib

    digest = hashlib.sha256()
    for name in sorted(files or {}):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((files[name] or "").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def submission_files(item: dict) -> dict:
    """{nama berkas: teks} paket sebuah pengajuan."""
    from orchestrator.submission_service import read_submission_sources

    return {name: text for name, text in read_submission_sources(item)}


def submission_fingerprint(item: dict) -> str:
    return package_fingerprint(submission_files(item))


# ── Pengaman 1: hanya yang lolos validasi statis ─────────────────────────

def static_validation_passed(item: dict) -> bool:
    """Apakah paket pengajuan ini LOLOS pemeriksaan statis.

    Dibaca dari hasil validasi yang tersimpan pada pengajuan — hasil yang sama
    yang ditampilkan kepada peninjau. Bila tidak ada hasilnya, jawabannya
    TIDAK: ketiadaan bukti bukan bukti kelulusan.
    """
    raw = item.get("validation") or item.get("validation_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return False
    if not isinstance(raw, dict):
        return False
    if "valid" in raw:
        return bool(raw["valid"])
    # Bentuk paket: sekumpulan laporan per berkas. Seluruhnya harus valid.
    reports = raw.get("files") or raw.get("reports")
    if isinstance(reports, list) and reports:
        return all(bool(r.get("valid")) for r in reports if isinstance(r, dict))
    return False


def trial_blocker(item: dict) -> str:
    """Alasan uji coba TIDAK dapat dijalankan; "" bila boleh.

    Alasannya selalu dinyatakan — tombol mati tanpa keterangan membuat
    peninjau menebak apa yang salah.
    """
    from database.models import KIND_PIPELINE, SUBMISSION_PENDING

    if item.get("kind") != KIND_PIPELINE:
        return "trial.only_pipeline"
    if item.get("status") != SUBMISSION_PENDING:
        return "trial.not_pending"
    if not static_validation_passed(item):
        return "trial.static_failed"
    return ""


# ── Gerbang persetujuan ──────────────────────────────────────────────────

#: Penanda "tidak ada uji yang disodorkan pemanggil" — dibedakan dari `None`,
#: yang merupakan jawaban yang SAH ("pengajuan ini belum pernah diuji").
_NO_TRIAL_GIVEN = object()


def approval_blocker(item: dict, db_path: str | None = None, *,
                     trial=_NO_TRIAL_GIVEN) -> str:
    """Alasan pengajuan ini BELUM boleh disetujui; "" bila boleh.

    Tiga keadaan yang berbeda dibedakan, karena tindakan pemulihannya berbeda:
    belum pernah diuji, uji terakhirnya gagal, dan uji terakhirnya sudah tidak
    berlaku karena kodenya berubah sesudahnya.

    ``trial`` OPSIONAL: uji terakhir yang sudah diambil pemanggil (mis. lewat
    ``latest_trials_for`` untuk seluruh antrean sekaligus). Bila tidak
    diberikan, uji itu diambil di sini seperti sebelumnya — pemanggil lama
    tidak berubah perilakunya sama sekali. Yang dihemat hanyalah PEMBACAAN;
    aturannya di bawah tetap sama persis, dan sidik jari paket tetap dihitung
    ULANG di sini, tidak pernah diambil dari nilai yang disodorkan.
    """
    from database.models import KIND_PIPELINE

    if item.get("kind") != KIND_PIPELINE:
        return ""                            # dataset tidak memerlukan uji

    if trial is _NO_TRIAL_GIVEN:
        trial = trial_db.latest_trial(item["id"], db_path)
    if trial is None:
        return "trial.gate_untested"
    if trial["status"] != trial_db.STATUS_PASSED:
        return "trial.gate_failed"
    if trial["package_hash"] != submission_fingerprint(item):
        # Kode berubah SESUDAH uji berhasil. Ini persis celah yang harus
        # tertutup: menguji versi yang bersih lalu menyunting lalu menyetujui.
        return "trial.gate_stale"
    return ""


def may_approve(item: dict, db_path: str | None = None) -> bool:
    return approval_blocker(item, db_path) == ""


# ── Menjalankan uji coba ─────────────────────────────────────────────────


#: Nilai yang kontributor pilih ketika jenis datasetnya BELUM terdaftar di
#: platform. Disimpan sebagai penanda eksplisit, bukan string kosong: "saya
#: tahu jenisnya belum ada di daftar" adalah keterangan, sedangkan string
#: kosong tidak dapat dibedakan dari "tidak pernah diisi".
DATASET_TYPE_UNREGISTERED = "unregistered"


def _usable_type(value) -> str:
    """Jenis dataset yang benar-benar dapat dipakai, atau "".

    Penanda `unregistered` dan string kosong sama-sama BUKAN jenis yang dapat
    dipakai memuat dan menjalankan pipeline — keduanya disaring di sini,
    sekali, supaya tidak ada pemanggil yang perlu mengingatnya.
    """
    text = str(value or "").strip()
    if not text or text == DATASET_TYPE_UNREGISTERED:
        return ""
    return text


def declared_dataset_type(item: dict) -> str:
    """Jenis yang DIDEKLARASIKAN pipeline pengajuan ini, dibaca STATIS.

    Dibaca dari teks sumbernya lewat pembaca statis yang sama dengan yang
    dipakai saat mengunggah — berkasnya tidak pernah diimpor maupun
    dijalankan untuk menjawab pertanyaan ini.
    """
    from ui.components.pipeline_upload import extract_registry_metadata

    metadata = item.get("metadata") or {}
    entry_name = metadata.get("entry_filename") or ""
    for name, source in submission_files(item).items():
        if entry_name and name != entry_name:
            continue
        try:
            found = extract_registry_metadata(source, name) or {}
        except Exception:                    # pragma: no cover - defensif
            continue
        usable = _usable_type(found.get("dataset_type"))
        if usable:
            return usable
    return ""


def platform_dataset_type(dataset_path: str | None) -> str:
    """Jenis milik berkas platform yang dipilih, dari mekanisme yang ada.

    Ini sumber PALING BERWENANG: apa pun yang tertulis di tempat lain, inilah
    data yang benar-benar akan dibaca pipeline.
    """
    if not dataset_path:
        return ""
    try:
        from config.settings import DATASETS_DIR
        from ui.views.run_experiment import _dataset_options_cached

        options, _sizes = _dataset_options_cached(0, str(DATASETS_DIR))
        target = Path(dataset_path).resolve()
        for path, dtype in options:
            if Path(path).resolve() == target:
                return _usable_type(dtype)
    except Exception:                        # pragma: no cover - defensif
        logger.exception("Jenis dataset platform tidak terbaca untuk %s",
                         dataset_path)
    return ""


def resolve_dataset_type(item: dict, source: str,
                         dataset_path: str | None = None) -> str:
    """Jenis dataset untuk sebuah uji coba — SATU-SATUNYA penentu.

    Urutannya, dan alasannya:

    1. **berkas platform yang dipilih** — paling berwenang, karena itulah data
       yang benar-benar dibaca; apa pun yang dideklarasikan di tempat lain
       kalah oleh kenyataan isi berkasnya;
    2. **deklarasi pipeline** (dibaca statis dari sumbernya) — pernyataan
       penulis pipeline tentang data yang ia harapkan;
    3. **metadata pengajuan** — isian kontributor pada formulir, yang paling
       mudah terlewat dan karena itu paling akhir.

    Untuk dataset LAMPIRAN, langkah 1 dilewati: lampiran tidak punya jenis
    sendiri — ia disediakan UNTUK pipeline ini, jadi jenisnya adalah jenis
    yang pipeline itu deklarasikan (dengan cadangan metadata pengajuan).

    Mengembalikan "" bila tidak ada satu pun sumber menghasilkan jenis yang
    dapat dipakai. Pemanggil WAJIB berhenti pada keadaan itu — lihat
    :func:`run_trial`.
    """
    if source != SOURCE_ATTACHED:
        found = platform_dataset_type(dataset_path)
        if found:
            return found

    found = declared_dataset_type(item)
    if found:
        return found

    return _usable_type((item.get("metadata") or {}).get("dataset_type"))


def dataset_type_blocker(item: dict, source: str,
                         dataset_path: str | None = None, *,
                         resolved: str | None = None) -> str:
    """Kunci pesan bila jenis dataset tak dapat ditentukan; "" bila dapat.

    Dipakai TAMPILAN untuk menonaktifkan tombol beserta alasannya, dan dipakai
    :func:`run_trial` untuk menolak lebih awal — satu aturan, dua tempat yang
    menanyakannya, bukan dua aturan.

    ``resolved`` OPSIONAL: jenis yang SUDAH ditentukan pemanggil lewat
    :func:`resolve_dataset_type`. Menyodorkannya menghindari penentuan kedua
    yang membaca berkas paket sekali lagi untuk pertanyaan yang sama. Ia hanya
    boleh berisi hasil fungsi itu — bukan tebakan pemanggil — karena kunci
    pesannya tetap diputuskan DI SINI, satu tempat.
    """
    value = (resolved if resolved is not None
             else resolve_dataset_type(item, source, dataset_path))
    return "" if value else "td.err_unknown_dataset_type"


def _entry_from_submission(item: dict) -> tuple[Path, str, str]:
    """(berkas titik masuk, nama kelas, sha256 berkas) sebuah pengajuan."""
    from orchestrator.dynamic_registry import file_sha256

    metadata = item.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    entry_file = metadata.get("entry_filename") or metadata.get("entry_file")
    entry_class = metadata.get("class_name") or metadata.get("entry_class")
    folder = Path(item["stored_path"])
    if not entry_file or not entry_class:
        raise TrialError(
            "Pengajuan ini tidak mencatat titik masuk & nama kelasnya, "
            "sehingga tidak ada yang dapat dimuat untuk diuji.",
            key="trial.err_no_entry")
    path = folder / entry_file if folder.is_dir() else folder
    if not path.is_file():
        raise TrialError(
            f"Berkas titik masuk tidak ditemukan: {path}",
            key="trial.err_entry_missing", values={"path": str(path)})
    return path, entry_class, file_sha256(path)


#: Sumber dataset uji. Keduanya melewati JALUR EKSEKUSI yang sama; yang
#: membedakan hanya asal path-nya, dan bahwa lampiran diverifikasi hash-nya.
SOURCE_PLATFORM = "platform"
SOURCE_ATTACHED = "attached"


def run_trial(submission_id: int, *, dataset_type: str | None = None,
              dataset_path: str | None = None, actor: dict | None,
              source: str = SOURCE_PLATFORM,
              db_path: str | None = None) -> dict:
    """Jalankan uji coba sebuah pengajuan. Hanya Research Admin.

    Urutan pemeriksaannya penting dan tidak boleh ditukar: izin dulu, lalu
    kelayakan paket (validasi statis), baru berkasnya dibuka. Kode yang gagal
    pemeriksaan statis tidak pernah sampai ke tahap dimuat.

    ``source`` memilih dataset PLATFORM (dipilih admin dari yang tersedia)
    atau dataset LAMPIRAN pengajuan. Pada lampiran, hash-nya diverifikasi
    lebih dulu: berkas yang berubah setelah diajukan ditolak sebelum dipakai.

    ``dataset_type`` TIDAK perlu diberikan: ia ditentukan
    :func:`resolve_dataset_type` di sini. Argumennya dipertahankan hanya untuk
    pemanggil lama; nilai yang tidak dapat dipakai diabaikan, bukan diteruskan
    apa adanya ke penyimpanan.
    """
    from orchestrator.submission_service import get_submission

    # (2) Izin — di FUNGSI, bukan di tampilan.
    require_approve(actor, db_path)

    item = get_submission(submission_id, db_path)
    if item is None:
        raise TrialError(f"Pengajuan #{submission_id} tidak ditemukan.",
                         key="trial.err_not_found",
                         values={"id": submission_id})

    # (1) Validator tetap gerbang pertama.
    blocker = trial_blocker(item)
    if blocker:
        raise TrialError(
            "Pengajuan ini tidak dapat diuji: paketnya belum lolos "
            "pemeriksaan statis atau tidak lagi menunggu tinjauan.",
            key=blocker)

    # Sumber dataset diselesaikan SETELAH pengaman paket lolos, supaya
    # pengajuan yang memang tidak boleh diuji tidak pernah membuka berkas
    # apa pun — termasuk lampirannya.
    # Jenis dataset ditentukan SEKALI, di sini, SEBELUM catatan apa pun
    # ditulis — dan sebelum jalurnya dinormalkan. Urutan ini disengaja: bila
    # jenis MAUPUN berkas sama-sama belum ada, "jenis belum diketahui" yang
    # perlu didengar peninjau, karena yang harus diperbaiki adalah metadata
    # pengajuannya, bukan pilihan berkasnya.
    resolved_type = _usable_type(dataset_type) or resolve_dataset_type(
        item, source, dataset_path)
    if not resolved_type:
        raise TrialError(
            "Jenis dataset belum diketahui, jadi uji coba tidak dapat "
            "dijalankan. Lengkapi dataset target pada metadata pengajuan, "
            "atau pilih dataset platform yang jenisnya dikenali.",
            key="td.err_unknown_dataset_type")
    dataset_type = resolved_type

    dataset_path, dataset_label = _resolve_dataset(item, source, dataset_path)

    entry_path, entry_class, entry_hash = _entry_from_submission(item)
    fingerprint = submission_fingerprint(item)

    trial_id = str(uuid.uuid4())
    started = datetime.now()
    trial_db.create_trial(
        trial_id=trial_id, submission_id=submission_id,
        package_hash=fingerprint, dataset_type=dataset_type,
        dataset_path=dataset_path, started_by=actor["username"],
        started_at=started.isoformat(timespec="seconds"), db_path=db_path)

    outcome = _execute_trial(
        trial_id=trial_id, entry_path=entry_path, entry_class=entry_class,
        entry_hash=entry_hash, dataset_type=dataset_type,
        dataset_path=dataset_path, started=started, db_path=db_path)
    _record_trail(submission_id, db_path=db_path, source=source,
                  dataset_label=dataset_label)
    return outcome


def _resolve_dataset(item: dict, source: str,
                     dataset_path: str | None) -> tuple[str, str]:
    """(path, label) dataset yang akan dipakai — atau raise.

    Label ikut dikembalikan supaya jejak uji dapat mencatat dataset MANA yang
    dipakai, bukan sekadar bahwa uji pernah dijalankan.
    """
    from orchestrator.trial_dataset_service import (
        attachment_of, verify_attachment,
    )

    if source == SOURCE_ATTACHED:
        info = attachment_of(item) or {}
        # Verifikasi hash: berkas yang berubah setelah diajukan ditolak.
        return verify_attachment(item), info.get("filename") or "—"

    if not dataset_path:
        raise TrialError(
            "Pilih dataset lebih dulu sebelum menjalankan uji coba.",
            key="td.err_no_dataset_chosen")
    return dataset_path, Path(dataset_path).name


def _execute_trial(*, trial_id, entry_path, entry_class, entry_hash,
                   dataset_type, dataset_path, started, db_path, runner=None):
    """Jalankan satu uji coba dan catat hasilnya.

    Setiap kegagalan dicatat dengan TAHAP tempatnya terjadi. Itulah nilai
    utama fitur ini: peninjau perlu tahu pipeline berhenti saat memuat, saat
    membaca dataset, saat berjalan, atau karena melampaui batas waktu — bukan
    sekadar bahwa ia gagal.

    ``runner`` hanya untuk test; bawaannya pelaksana berbatas yang sungguhan.
    """
    from workers.trial_runner import run_bounded

    run = runner or run_bounded
    try:
        outcome = run(
            entry_file=str(entry_path), entry_class=entry_class,
            entry_hash=entry_hash, dataset_type=dataset_type,
            dataset_path=dataset_path, max_rows=TRIAL_LIMITS["max_rows"],
            max_seconds=TRIAL_LIMITS["max_seconds"])
    except Exception as exc:
        # Pelaksana berbatas menjadikan kegagalan PIPELINE sebagai hasil, bukan
        # lemparan — tetapi ia masih dapat gagal karena sebab LINGKUNGAN
        # (proses anak tidak dapat dijalankan, antrean tidak dapat dibuat).
        # Tanpa penangan ini catatan uji tertinggal selamanya pada status
        # QUEUED: catatan setengah jadi yang tidak pernah punya kesimpulan.
        # Kegagalan lingkungan pun dicatat sebagai KEGAGALAN yang berkesudahan.
        logger.exception("Pelaksana uji coba %s gagal dijalankan", trial_id)
        from workers.trial_runner import STAGE_SETUP

        outcome = {
            "ok": False,
            # Nama tahap diambil dari konstanta, bukan ditulis sebagai teks di
            # sini: `trial_stage()` menerjemahkan lewat pemetaan nama tahap,
            # dan nama yang tidak terdaftar akan tampil apa adanya — satu
            # kalimat Inggris dengan potongan Indonesia di dalamnya.
            "stage": STAGE_SETUP,
            "kind": type(exc).__name__,
            "message": str(exc),
            "rows_used": None,
        }

    duration = round((datetime.now() - started).total_seconds(), 3)
    finished_at = datetime.now().isoformat(timespec="seconds")

    if outcome.get("ok"):
        metrics = outcome.get("metrics") or {}
        trial_db.finish_trial(
            trial_id, status=trial_db.STATUS_PASSED, finished_at=finished_at,
            duration_s=duration, rows_used=outcome.get("rows_used"),
            metrics=metrics, db_path=db_path)
        return {"success": True, "trial_id": trial_id, "metrics": metrics,
                "duration_s": duration, "rows_used": outcome.get("rows_used")}

    # Kegagalan disimpan LENGKAP dan apa adanya: tahap, jenis, dan pesannya.
    # Menyederhanakannya menjadi "uji gagal" membuang informasi yang justru
    # menjadi alasan fitur ini ada.
    trial_db.finish_trial(
        trial_id, status=trial_db.STATUS_FAILED, finished_at=finished_at,
        duration_s=duration, rows_used=outcome.get("rows_used"),
        error_stage=outcome.get("stage"), error_kind=outcome.get("kind"),
        error_message=outcome.get("message"), db_path=db_path)
    logger.warning("Uji coba %s gagal pada tahap %s: %s: %s", trial_id,
                   outcome.get("stage"), outcome.get("kind"),
                   outcome.get("message"))
    return {"success": False, "trial_id": trial_id,
            "stage": outcome.get("stage"), "kind": outcome.get("kind"),
            "message": outcome.get("message"), "duration_s": duration,
            "rows_used": outcome.get("rows_used")}


# ── Jejak ringkas pada pengajuan ─────────────────────────────────────────

def _record_trail(submission_id: int, db_path: str | None = None, *,
                  source: str = SOURCE_PLATFORM,
                  dataset_label: str = "") -> None:
    """Tulis jejak RINGKAS uji terakhir ke kolom ``submissions.trial_json``.

    Inilah satu-satunya bagian yang bertahan setelah keputusan diambil: siapa
    menguji, kapan, dataset apa, hasilnya, dan ringkasannya. Ia riwayat
    peninjauan — bukan hasil penelitian.
    """
    trial = trial_db.latest_trial(submission_id, db_path)
    if trial is None:
        return
    trail = {
        "trial_id": trial["id"],
        "started_by": trial["started_by"],
        "started_at": trial["started_at"],
        "finished_at": trial["finished_at"],
        "dataset_type": trial["dataset_type"],
        "dataset_path": trial["dataset_path"],
        # Dataset MANA yang dipakai — platform atau lampiran, beserta namanya.
        "dataset_source": source,
        "dataset_name": dataset_label or Path(trial["dataset_path"]).name,
        "status": trial["status"],
        "duration_s": trial["duration_s"],
        "rows_used": trial["rows_used"],
        "metrics": trial["metrics"],
        "error_stage": trial["error_stage"],
        "error_kind": trial["error_kind"],
        "error_message": trial["error_message"],
    }
    with get_connection(db_path) as conn:
        conn.execute("UPDATE submissions SET trial_json = ? WHERE id = ?",
                     (json.dumps(trail), submission_id))
        conn.commit()


def trial_trail(item: dict) -> dict | None:
    """Jejak ringkas yang tersimpan pada sebuah pengajuan."""
    raw = item.get("trial_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):           # pragma: no cover - defensive
        return None


# ── Pembersihan ──────────────────────────────────────────────────────────

def _remove_artifacts(trial: dict) -> None:
    """Buang folder artefak sebuah uji, bila ada."""
    folder = trial.get("artifacts_dir") or str(TRIAL_ROOT / trial["id"])
    path = Path(folder)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def discard_trials(submission_id: int, db_path: str | None = None) -> int:
    """Hapus SELURUH hasil uji sebuah pengajuan: catatan + artefaknya.

    Dipanggil setelah keputusan diambil. Jejak ringkas pada pengajuan tidak
    ikut terhapus — ia memang dimaksudkan bertahan.
    """
    # Dataset lampiran ikut dibuang: ia berkas CONTOH yang hanya hidup
    # selama peninjauan berlangsung.
    _discard_attachment(submission_id, db_path)

    removed = trial_db.delete_trials(submission_id, db_path)
    for trial in removed:
        _remove_artifacts(trial)
    # Folder sisa tanpa catatan (mis. proses yang mati di tengah) ikut dibuang,
    # supaya tidak ada berkas yatim yang tertinggal atas nama pengajuan ini.
    for trial in removed:
        leftover = TRIAL_ROOT / trial["id"]
        if leftover.is_dir():                # pragma: no cover - defensive
            shutil.rmtree(leftover, ignore_errors=True)
    if removed:
        logger.info("Hasil uji pengajuan #%s dibuang: %d catatan",
                    submission_id, len(removed))
    return len(removed)


def _discard_attachment(submission_id: int, db_path: str | None) -> None:
    """Buang dataset lampiran pengajuan ini, bila ada.

    Kegagalan membuang TIDAK boleh membatalkan pembersihan hasil uji; sisanya
    ditangani `trial_dataset_service.purge_orphans`.
    """
    try:
        from orchestrator.submission_service import get_submission
        from orchestrator.trial_dataset_service import discard_attachment

        item = get_submission(submission_id, db_path)
        if item:
            discard_attachment(item, db_path)
    except Exception:                        # pragma: no cover - defensif
        logger.exception(
            "Dataset lampiran pengajuan #%s gagal dibuang", submission_id)


def cleanup_stale_trials(hours: int | None = None,
                         db_path: str | None = None) -> int:
    """Buang uji coba yang menggantung lebih lama dari batas kewajaran.

    Keputusan peninjauan tidak selalu diambil. Tanpa pembersihan ini, hasil
    uji yang tidak pernah diputuskan akan menumpuk di disk tanpa ada yang
    membacanya. Batasnya 24 jam: cukup lama untuk peninjauan yang tertunda
    semalam, cukup pendek agar tidak menjadi timbunan.
    """
    limit = hours if hours is not None else TRIAL_LIMITS["stale_hours"]
    cutoff = (datetime.now() - timedelta(hours=limit)).isoformat(
        timespec="seconds")
    stale = trial_db.list_trials_older_than(cutoff, db_path)
    for trial in stale:
        _remove_artifacts(trial)
        trial_db.delete_trial(trial["id"], db_path)
    if stale:
        logger.info("%d hasil uji lama dibersihkan (lebih dari %d jam)",
                    len(stale), limit)
    return len(stale)


def orphan_trial_dirs(db_path: str | None = None) -> list[Path]:
    """Folder artefak uji yang tidak lagi punya catatan — bahan pemeriksaan."""
    if not TRIAL_ROOT.is_dir():
        return []
    with get_connection(db_path) as conn:
        known = {r[0] for r in conn.execute("SELECT id FROM pipeline_trials")}
    return [p for p in TRIAL_ROOT.iterdir() if p.is_dir() and p.name not in known]


__all__ = [
    "DATASET_TYPE_UNREGISTERED", "SOURCE_ATTACHED", "SOURCE_PLATFORM",
    "TRIAL_LIMITS", "TRIAL_ROOT", "TrialError",
    "approval_blocker", "cleanup_stale_trials", "dataset_type_blocker",
    "declared_dataset_type", "discard_trials",
    "may_approve", "orphan_trial_dirs", "package_fingerprint",
    "platform_dataset_type", "resolve_dataset_type", "run_trial",
    "static_validation_passed", "submission_fingerprint", "trial_blocker",
    "trial_trail",
]
