"""
Penyuntingan pipeline kontribusi — SELALU sebagai versi baru.

Menyetujui sebuah pengajuan membuat pipeline langsung aktif, dan Research Admin
boleh menyuntingnya bila ada yang perlu disesuaikan. Kemampuan itu berbahaya
bagi klaim reproducibility kalau dibangun sembarangan, jadi modul ini menegakkan
tiga pengaman — dan ketiganya hidup DI SINI, di lapis aksi, bukan di tampilan:

**A. Tidak pernah menimpa.** :func:`save_new_version` menulis berkas ke folder
versi BARU dan mendaftarkan versi berikutnya. Berkas, hash, dan baris registry
versi sebelumnya tidak pernah disentuh — eksperimen yang sudah berjalan tetap
dapat ditelusuri ke kode yang benar-benar dipakainya. Versi lama hanya
dinonaktifkan (``active = 0``); ia tetap ada dan tetap dapat dimuat untuk
penelusuran.

**B. Tidak ada jalur menyimpan kode yang gagal validasi.** Sumber divalidasi
ulang lewat ``validate_pipeline_source`` SEBELUM satu berkas pun ditulis. Ini
menutup celah yang paling penting: mengunggah versi bersih, menunggu
persetujuan, lalu menyunting menjadi berbahaya. Aturan validatornya sendiri
tidak diubah sedikit pun — modul ini hanya memanggilnya.

**C. Pipeline bawaan tidak dapat disentuh.** Setiap fungsi yang mengubah sesuatu
menolak identitas yang bukan milik ruang nama kontribusi
(``database.models.UPLOADED_PREFIX``). Sepuluh pipeline bawaan tetap datang dari
registry statis dan tidak punya jalan masuk ke sini.

**Validasi tetap STATIS.** Tidak ada satu pun jalur di modul ini yang meng-import
atau menjalankan kode yang sedang ditinjau/disunting: sumbernya dibaca sebagai
TEKS, diurai menjadi pohon sintaks oleh validator, lalu ditulis sebagai teks.
"""
from __future__ import annotations

import logging
from pathlib import Path

from database.db import get_connection
from database.models import UPLOADED_PREFIX
from orchestrator.dynamic_registry import (
    DynamicRegistryError, file_sha256, get_registered, next_version,
    register_pipeline, safe_pipeline_name,
)
from orchestrator.submission_service import PIPELINE_ROOT
from utils.timestamps import now_iso

logger = logging.getLogger(__name__)

#: Berkas tiap versi disimpan TERPISAH di sini — satu folder per versi, tidak
#: pernah saling menimpa. Berada di bawah ``storage/`` yang TIDAK pernah
#: ditambahkan ke ``sys.path``; pemuatannya lewat ``spec_from_file_location``
#: pada berkas spesifik (lihat ``orchestrator/dynamic_registry``).
VERSIONS_ROOT = Path(PIPELINE_ROOT) / "versions"


class PipelineEditError(DynamicRegistryError):
    """Penyuntingan ditolak. Pesannya layak ditampilkan apa adanya."""


# ── Pengaman C: hanya pipeline kontribusi ─────────────────────────────────

def is_contributed(pipeline_id) -> bool:
    """True hanya untuk pipeline di ruang nama kontribusi."""
    return str(pipeline_id or "").startswith(UPLOADED_PREFIX)


def require_contributed(pipeline_id) -> None:
    """Tolak apa pun yang bukan pipeline kontribusi.

    Sepuluh pipeline bawaan adalah dasar seluruh hasil penelitian. Mereka
    didefinisikan di ``config/pipeline_registry`` dan TIDAK punya baris di
    ``registered_pipelines``, jadi menyunting/menonaktifkannya lewat halaman
    ini tidak mungkin — penolakan di sini membuat kemustahilan itu eksplisit
    dan teruji, bukan kebetulan.
    """
    if not is_contributed(pipeline_id):
        raise PipelineEditError(
            f"`{pipeline_id}` bukan pipeline kontribusi. Pipeline bawaan "
            f"berasal dari registry statis dan tidak dapat disunting, "
            f"dinonaktifkan, atau ditimpa dari halaman ini.",
            key="err.not_contributed", values={"pipeline": pipeline_id}
        )


# ── Membaca sumber sebagai TEKS ───────────────────────────────────────────

def read_source(pipeline_id: str, db_path: str | None = None) -> str:
    """Isi berkas entry point sebuah versi, sebagai teks.

    Dibaca sebagai TEKS BIASA — tidak di-import, tidak dijalankan. Inilah yang
    ditampilkan peninjau dan yang disunting.
    """
    require_contributed(pipeline_id)
    item = get_registered(pipeline_id, db_path)
    if item is None:
        raise PipelineEditError(
            f"Pipeline terdaftar tidak ditemukan: {pipeline_id}",
            key="err.pipeline_not_registered",
            values={"pipeline": pipeline_id})
    path = Path(item["entry_file"])
    if not path.is_file():
        raise PipelineEditError(
            f"Berkas versi ini tidak ditemukan: {path.name}",
            key="err.version_file_missing", values={"path": path.name})
    return path.read_text(encoding="utf-8")


def read_package(pipeline_id: str, db_path: str | None = None) -> dict[str, str]:
    """{nama berkas: teks} SELURUH berkas satu versi.

    Sebuah pipeline kontribusi boleh berupa PAKET: satu titik masuk plus berkas
    pendukung, semuanya berada di folder versi yang sama. Membaca hanya titik
    masuknya membuat berkas pendukung tidak pernah dapat disunting — dan lebih
    buruk, membuat versi berikutnya lahir tanpa berkas itu.

    Dibaca sebagai TEKS. Tidak pernah di-import maupun dijalankan.
    """
    require_contributed(pipeline_id)
    item = get_registered(pipeline_id, db_path)
    if item is None:
        raise PipelineEditError(
            f"Pipeline terdaftar tidak ditemukan: {pipeline_id}",
            key="err.pipeline_not_registered",
            values={"pipeline": pipeline_id})

    entry = Path(item["entry_file"])
    folder = entry.parent
    if not folder.is_dir():
        raise PipelineEditError(
            f"Folder versi tidak ditemukan: {folder.name}",
            key="err.version_folder_missing",
            values={"folder": folder.name})

    out: dict[str, str] = {}
    for path in sorted(folder.glob("*.py")):
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError:                     # pragma: no cover - defensif
            logger.warning("Berkas versi tidak terbaca: %s", path)
    if entry.name not in out:
        raise PipelineEditError(
            f"Berkas titik masuk tidak ditemukan: {entry.name}",
            key="err.entry_file_not_found",
            values={"filename": entry.name})
    return out


def entry_name(pipeline_id: str, db_path: str | None = None) -> str:
    """Nama berkas titik masuk satu versi."""
    item = get_registered(pipeline_id, db_path)
    return Path(item["entry_file"]).name if item else ""


# ── Pengaman B: validasi ulang, statis ────────────────────────────────────

def validate_source(source: str, filename: str = "pipeline.py"):
    """Validasi STATIS sumber yang sedang disunting.

    Meneruskan apa adanya ke ``validate_pipeline_source``; aturan pemeriksaan
    tidak diubah maupun dilonggarkan di sini. Tidak pernah menjalankan kode.
    """
    from orchestrator.pipeline_validator import validate_pipeline_source
    return validate_pipeline_source(source, filename)


def validate_package(files: dict[str, str]) -> dict:
    """Validasi STATIS seluruh berkas paket + aturan tingkat paket.

    Meneruskan ke ``review_package`` — mekanisme yang SAMA dengan jalur unggah
    dan jalur peninjauan. Berkas pendukung tetap wajib lolos pemeriksaan
    keamanan, dan kode tidak pernah dijalankan.

    **Satu aturan tambahan yang HANYA berlaku di sini: tepat satu titik masuk.**

    Jalur unggah sengaja menerima banyak titik masuk — satu pengajuan memang
    boleh membawa beberapa algoritma sekaligus. Penyunting versi berbeda: satu
    baris ``registered_pipelines`` memetakan ke SATU ``entry_class``, jadi
    titik masuk kedua di paket yang sama tidak akan pernah dimuat. Ia akan
    terbaca seperti algoritma baru padahal tidak terdaftar dan tidak dapat
    dijalankan — kegagalan yang senyap.

    Menambah algoritma dilakukan lewat pengajuan + peninjauan, bukan lewat
    penyuntingan versi.
    """
    from ui.components.pipeline_upload import review_package

    payload = [(name, text.encode("utf-8")) for name, text in (files or {}).items()]
    result = review_package(payload)

    entry_points = result.get("entry_points") or []
    if len(entry_points) > 1:
        listed = ", ".join(f"`{name}`" for name in entry_points)
        result = {
            **result,
            "valid": False,
            "cause": (
                f"Ditemukan {len(entry_points)} titik masuk ({listed}). Satu "
                f"versi pipeline memetakan ke satu kelas, jadi titik masuk "
                f"kedua tidak akan pernah dimuat. Tambahkan algoritma lewat "
                f"pengajuan baru, bukan lewat penyuntingan versi."),
        }
    return result


def package_rejection_reason(reviewed) -> str:
    """Kalimat singkat kenapa sebuah PAKET belum boleh disimpan; "" bila lolos."""
    if reviewed is None:
        return "Tekan **Periksa** dulu — kode harus lolos validasi sebelum disimpan."
    if reviewed.get("valid"):
        return ""
    cause = (reviewed.get("cause") or reviewed.get("summary")
             or "Validasi belum lolos.")
    return f"{cause} Kode yang gagal validasi tidak dapat disimpan."


def rejection_reason(report) -> str:
    """Kalimat singkat kenapa sebuah sumber belum boleh disimpan; "" bila lolos."""
    if report is None:
        return "Tekan **Periksa** dulu — kode harus lolos validasi sebelum disimpan."
    if getattr(report, "valid", False):
        return ""
    failures = [c for c in getattr(report, "checks", [])
                if getattr(c, "status", "") == "fail"]
    if not failures:                        # pragma: no cover - defensif
        return "Validasi belum lolos."
    first = failures[0]
    line = f" (baris {first.line})" if getattr(first, "line", None) else ""
    return (f"{len(failures)} pemeriksaan gagal — mis. {first.message}{line}. "
            f"Perbaiki dulu; kode yang gagal validasi tidak dapat disimpan.")


# ── Pengaman A: menyimpan = versi BARU ────────────────────────────────────

def version_dir(name: str, version: int) -> Path:
    """Folder berkas satu versi. Satu folder per versi, tidak pernah dipakai ulang."""
    return VERSIONS_ROOT / safe_pipeline_name(name) / f"v{int(version)}"


def save_new_version(pipeline_id: str, source: str | None = None, *,
                     files: dict[str, str] | None = None, change_note: str,
                     actor: dict | None, db_path: str | None = None) -> dict:
    """Simpan hasil suntingan sebagai VERSI BARU. Mengembalikan baris versi baru.

    Urutannya sengaja begini, dan tiap langkah adalah pengaman:

    1. **izin** — hanya Research Admin (ditegakkan di fungsi, bukan di tombol);
    2. **ruang nama** — pipeline bawaan ditolak (pengaman C);
    3. **catatan perubahan** — wajib, karena inilah isi riwayat;
    4. **validasi statis** — gagal berarti berhenti di sini, SEBELUM ada berkas
       yang ditulis (pengaman B);
    5. **tulis SELURUH berkas paket** ke folder versi berikutnya — versi lama
       tidak tersentuh (pengaman A);
    6. **daftarkan versi baru** sebagai aktif, lalu nonaktifkan versi lama —
       record & berkasnya tetap ada.

    Dua cara memanggil, keduanya menghasilkan versi yang LENGKAP:

    * ``source`` — isi baru titik masuk saja. Berkas pendukung versi sekarang
      ikut disalin apa adanya, sehingga versi baru tetap utuh. Inilah yang dulu
      keliru: versi hasil suntingan lahir tanpa berkas pendukungnya dan karena
      itu tidak dapat dimuat sendiri.
    * ``files`` — seluruh isi paket sekaligus, untuk penyunting banyak berkas.

    Paket berisi lebih dari satu berkas divalidasi lewat ``validate_package``
    (aturan tingkat paket ikut ditegakkan); paket satu berkas memakai jalur
    validasi yang sama persis seperti sebelumnya.
    """
    from orchestrator.auth_service import require_approve

    require_approve(actor, db_path)
    require_contributed(pipeline_id)

    note = (change_note or "").strip()
    if not note:
        raise PipelineEditError(
            "Catatan perubahan wajib diisi — ia yang menjelaskan versi ini di "
            "riwayat.",
            key="err.change_note_required")

    current = get_registered(pipeline_id, db_path)
    if current is None:
        raise PipelineEditError(
            f"Pipeline terdaftar tidak ditemukan: {pipeline_id}",
            key="err.pipeline_not_registered",
            values={"pipeline": pipeline_id})

    filename = Path(current["entry_file"]).name

    if files is not None:
        payload = {name: text for name, text in files.items()
                   if isinstance(text, str)}
        if filename not in payload:
            raise PipelineEditError(
                f"Berkas titik masuk `{filename}` tidak ada di antara berkas "
                f"yang disimpan.",
                key="err.entry_not_in_package",
                values={"filename": filename})
    else:
        text = source if isinstance(source, str) else ""
        if not text.strip():
            raise PipelineEditError(
            "Sumber kosong — tidak ada yang dapat disimpan.",
            key="err.source_empty")
        # Berkas pendukung versi sekarang IKUT, supaya versi baru lengkap.
        payload = dict(read_package(pipeline_id, db_path))
        payload[filename] = text

    if not any((payload.get(name) or "").strip() for name in payload):
        raise PipelineEditError(
            "Sumber kosong — tidak ada yang dapat disimpan.",
            key="err.source_empty")

    # Berhenti SEBELUM menulis apa pun. Tidak ada berkas setengah jadi dan
    # tidak ada versi baru yang lahir dari kode yang gagal validasi.
    if len(payload) > 1:
        reviewed = validate_package(payload)
        if not reviewed.get("valid"):
            raise PipelineEditError(package_rejection_reason(reviewed))
    else:
        report = validate_source(payload[filename], filename)
        if not report.valid:
            raise PipelineEditError(rejection_reason(report))

    name = current["name"]
    version = next_version(name, db_path)
    target_dir = version_dir(name, version)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    # Nama variabel loop SENGAJA bukan `name`: `name` di atas adalah nama
    # PIPELINE, dan menimpanya di sini membuat versi baru terdaftar dengan
    # nama berkas — pipeline yang sama sekali berbeda.
    for member in payload:
        if (target_dir / member).exists():  # pragma: no cover - defensif
            raise PipelineEditError(
                f"Berkas versi {version} sudah ada — penyimpanan dibatalkan "
                f"agar tidak menimpa apa pun.",
                key="err.version_file_exists", values={"version": version})
    for member, content in payload.items():
        (target_dir / member).write_text(content, encoding="utf-8")

    stamp = now_iso()
    created = register_pipeline(
        name=name, dataset_type=current["dataset_type"],
        entry_class=current["entry_class"], entry_file=target,
        registered_by=current["registered_by"],
        submission_id=current.get("submission_id"),
        algorithm=current.get("algorithm"), paper=current.get("paper"),
        edited_by=(actor or {}).get("username"), edited_at=stamp,
        change_note=note, db_path=db_path,
    )

    # Versi lama DINONAKTIFKAN, bukan dihapus: berkas, hash, dan barisnya tetap
    # utuh supaya eksperimen yang memakainya tetap dapat ditelusuri.
    _set_active_raw(pipeline_id, False, db_path)

    logger.info("Pipeline %s disunting menjadi %s oleh %s (hash %s…)",
                pipeline_id, created["pipeline_id"],
                (actor or {}).get("username"), created["file_hash"][:12])
    return created


def _set_active_raw(pipeline_id: str, active: bool, db_path: str | None) -> None:
    """Ubah bendera aktif tanpa memeriksa izin ulang.

    Dipakai HANYA dari dalam :func:`save_new_version`, yang izinnya sudah
    ditegakkan di awal. Jalur yang dipakai UI tetap
    ``dynamic_registry.set_pipeline_active`` yang memeriksa izin sendiri.
    """
    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE registered_pipelines SET active = 0 WHERE pipeline_id = ?"
                     if not active else
                     "UPDATE registered_pipelines SET active = 1 WHERE pipeline_id = ?",
                     (pipeline_id,))
        conn.commit()
    finally:
        conn.close()


# ── Riwayat & pemakaian ───────────────────────────────────────────────────

def version_history(name: str, db_path: str | None = None) -> list[dict]:
    """Seluruh versi sebuah pipeline kontribusi, terbaru lebih dulu.

    Inilah bukti ketertelusuran: tiap baris membawa hash, siapa mengubah,
    kapan, dan catatan perubahannya.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM registered_pipelines WHERE name = ? "
            "ORDER BY version DESC", (safe_pipeline_name(name),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_blocker(pipeline_id: str, db_path: str | None = None) -> str:
    """Alasan versi ini BELUM boleh dihapus; "" bila boleh.

    SATU aturan, dua yang menanyakannya: tampilan memakainya untuk
    menonaktifkan tombol beserta alasannya, dan :func:`delete_version`
    memakainya untuk menolak — sehingga memanggil fungsinya langsung tidak
    dapat melewati gerbang yang sama.

    Yang dijaga adalah janji yang sudah tertulis di
    ``dynamic_registry.set_pipeline_active``: eksperimen lama tetap tercatat
    lengkap dengan versi & hash-nya. Menghapus versi yang pernah dipakai
    membuat ``experiments.pipeline_id`` menunjuk sesuatu yang tidak ada lagi,
    dan pertanyaan "eksperimen ini memakai kode yang mana persisnya" berhenti
    punya jawaban.

    Menonaktifkan tetap tersedia untuk kasus itu: ia menghilangkan pipeline
    dari pilihan tanpa menghapus catatannya.
    """
    used = experiment_counts(db_path).get(pipeline_id, 0)
    if used:
        return "mp.delete_blocked_used"
    if running_experiments(pipeline_id, db_path):
        return "mp.delete_blocked_running"
    return ""


def may_delete(pipeline_id: str, db_path: str | None = None) -> bool:
    return delete_blocker(pipeline_id, db_path) == ""


def delete_version(pipeline_id: str, *, actor: dict | None,
                   db_path: str | None = None) -> dict:
    """Hapus SATU versi pipeline kontribusi: barisnya dan berkasnya.

    Versi LAIN sekeluarga tidak tersentuh — menghapus v2 tidak menyentuh v1
    maupun v3, karena masing-masing punya berkas dan hash sendiri.

    Mengembalikan keterangan apa yang terhapus, supaya pemanggil dapat
    mengatakannya apa adanya alih-alih "berhasil".
    """
    from orchestrator.auth_service import require_approve
    from orchestrator.dynamic_registry import get_registered

    require_approve(actor, db_path)

    row = get_registered(pipeline_id, db_path)
    if row is None:
        raise PipelineEditError(
            f"Pipeline terdaftar tidak ditemukan: {pipeline_id}",
            key="err.pipeline_not_registered",
            values={"pipeline": pipeline_id})

    blocker = delete_blocker(pipeline_id, db_path)
    if blocker:
        raise PipelineEditError(
            "Versi ini tidak dapat dihapus karena masih dipakai eksperimen.",
            key=blocker)

    entry = Path(row["entry_file"])
    folder = entry.parent
    removed_files = []

    conn = get_connection(db_path)
    try:
        conn.execute("DELETE FROM registered_pipelines WHERE pipeline_id = ?",
                     (pipeline_id,))
        conn.commit()
    finally:
        conn.close()

    # Berkas dibuang SETELAH barisnya hilang: bila penghapusan baris gagal,
    # berkasnya masih utuh dan keadaannya tetap konsisten. Urutan sebaliknya
    # meninggalkan baris yang menunjuk berkas yang sudah tidak ada.
    try:
        if entry.is_file():
            entry.unlink()
            removed_files.append(entry.name)
        # Folder versi ikut dibuang bila sudah kosong — jangan tinggalkan
        # folder yatim tanpa berkas maupun catatan.
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        logger.warning("Berkas versi %s tidak dapat dibuang seluruhnya",
                       pipeline_id, exc_info=True)

    logger.info("Versi %s dihapus oleh %s", pipeline_id,
                (actor or {}).get("username"))
    return {"pipeline_id": pipeline_id, "name": row["name"],
            "version": row["version"], "files": removed_files}


def experiment_counts(db_path: str | None = None) -> dict[str, int]:
    """{pipeline_id: jumlah eksperimen} — hanya untuk ruang nama kontribusi."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT pipeline_id, COUNT(*) FROM experiments "
            "WHERE pipeline_id LIKE ? GROUP BY pipeline_id",
            (UPLOADED_PREFIX + "%",)).fetchall()
        return {r[0]: int(r[1]) for r in rows}
    finally:
        conn.close()


def running_experiments(pipeline_id: str, db_path: str | None = None) -> int:
    """Berapa eksperimen yang SEDANG berjalan memakai versi ini.

    Dipakai untuk memperingatkan penyunting: menyimpan versi baru tidak
    mengganggu eksekusi yang sedang jalan (ia memakai berkas versi lama yang
    tetap ada), tetapi peninjau berhak tahu.
    """
    from database.models import STATUS_QUEUED, STATUS_RUNNING

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM experiments WHERE pipeline_id = ? "
            "AND status IN (?, ?)",
            (pipeline_id, STATUS_RUNNING, STATUS_QUEUED)).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def current_hash(pipeline_id: str, db_path: str | None = None) -> str:
    """Hash berkas versi ini SEKARANG — dihitung ulang dari disk.

    Berbeda dari nilai yang tercatat bila berkasnya diutak-atik di luar
    platform; perbedaan itulah yang membuat pemuatan ditolak.
    """
    item = get_registered(pipeline_id, db_path)
    if item is None:
        return ""
    path = Path(item["entry_file"])
    return file_sha256(path) if path.is_file() else ""
