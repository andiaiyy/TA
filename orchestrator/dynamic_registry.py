"""
Registry dinamis — FASE 4.

Pipeline yang sudah DISETUJUI dapat dimuat dan dijalankan tanpa mengubah kode
registry. Mekanisme ini **menambah**, tidak menggantikan:
``config/pipeline_registry.py`` tetap satu-satunya sumber sepuluh pipeline
bawaan, dan berkas itu tidak pernah disentuh dari sini.

Tiga pengaman yang dijaga modul ini:

A. **Pipeline bawaan tidak dapat ditimpa.** Pipeline terunggah selalu berada di
   namespace ``uploaded.<nama>@v<N>``; saat menggabungkan, entri statis SELALU
   menang bila (secara teoretis) ada tabrakan ID.

B. **Immutable & berversi.** Menyetujui nama yang sama sekali lagi membuat
   ``version = max+1`` dengan berkas terpisah. Berkas/record versi lama tidak
   pernah ditimpa, sehingga eksperimen lama tetap menunjuk kode yang identik.

C. **Ketertelusuran.** Setiap entri menyimpan SHA-256 berkas entry point.
   Hash DIVERIFIKASI ULANG setiap kali kelas dimuat — termasuk di sisi worker,
   karena worker memakai jalur pemuatan yang sama (``execute_pipeline`` →
   ``get_pipeline_instance_merged``). Berkas yang berubah/rusak ditolak.

⚠️ Pemuatan memakai ``importlib.util.spec_from_file_location`` untuk BERKAS
SPESIFIK. Folder unggahan TIDAK PERNAH ditambahkan ke ``sys.path``, sehingga
berkas di sana tidak dapat membajak nama modul platform. Hanya pipeline
berstatus approved & active yang pernah dimuat — tidak ada jalan untuk memuat
pengajuan yang belum disetujui.
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import sys
from pathlib import Path

from database.db import _retry_on_locked, get_connection
from database.models import UPLOADED_PREFIX
from utils.timestamps import now_iso

logger = logging.getLogger(__name__)

_HASH_CHUNK = 1024 * 1024


class DynamicRegistryError(RuntimeError):
    """Pipeline terunggah tidak dapat dimuat (hash, berkas, atau kontrak)."""


# ── Identitas & versi ─────────────────────────────────────────────────────

def safe_pipeline_name(raw: str) -> str:
    """Nama pipeline yang aman untuk dipakai sebagai bagian ID."""
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_"
                      for ch in (raw or "").strip().lower())
    cleaned = cleaned.strip("_-")
    if not cleaned:
        raise DynamicRegistryError("Nama pipeline tidak sah.")
    return cleaned[:60]


def build_pipeline_id(name: str, version: int) -> str:
    """``uploaded.<nama>@v<N>`` — versi menjadi BAGIAN dari ID, sehingga
    eksperimen lama selamanya menunjuk versi yang dipakainya."""
    return f"{UPLOADED_PREFIX}{name}@v{version}"


def next_version(name: str, db_path: str | None = None) -> int:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM registered_pipelines WHERE name = ?",
            (name,)).fetchone()
        return int(row[0] or 0) + 1
    finally:
        conn.close()


# ── Query ─────────────────────────────────────────────────────────────────

def list_registered(*, active_only: bool = False,
                    db_path: str | None = None) -> list[dict]:
    sql = "SELECT * FROM registered_pipelines"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY name, version"
    conn = get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def get_registered(pipeline_id: str, db_path: str | None = None) -> dict | None:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM registered_pipelines WHERE pipeline_id = ?",
                           (pipeline_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Pendaftaran & penonaktifan ────────────────────────────────────────────

def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


@_retry_on_locked()
def register_pipeline(*, name: str, dataset_type: str, entry_class: str,
                      entry_file: str | Path, registered_by: str,
                      submission_id: int | None = None, algorithm: str | None = None,
                      paper: str | None = None, db_path: str | None = None) -> dict:
    """Daftarkan satu VERSI BARU pipeline terunggah.

    Tidak pernah menimpa: versi dihitung dari maksimum yang sudah ada + 1, dan
    (name, version) unik di level skema. Hash berkas dihitung SAAT INI dan
    disimpan sebagai patokan verifikasi saat dimuat nanti.
    """
    safe_name = safe_pipeline_name(name)
    entry_path = Path(entry_file)
    if not entry_path.is_file():
        raise DynamicRegistryError(f"Berkas entry point tidak ditemukan: {entry_path}")

    version = next_version(safe_name, db_path)
    pipeline_id = build_pipeline_id(safe_name, version)
    digest = file_sha256(entry_path)

    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO registered_pipelines
               (pipeline_id, name, version, submission_id, dataset_type,
                entry_class, entry_file, file_hash, algorithm, paper,
                registered_by, registered_at, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (pipeline_id, safe_name, version, submission_id, dataset_type,
             entry_class, str(entry_path), digest, algorithm, paper,
             registered_by, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Pipeline terunggah didaftarkan: %s (kelas %s, hash %s…)",
                pipeline_id, entry_class, digest[:12])
    return get_registered(pipeline_id, db_path)


@_retry_on_locked()
def set_pipeline_active(pipeline_id: str, active: bool, *, actor: dict | None,
                        db_path: str | None = None) -> dict:
    """Aktifkan/nonaktifkan pipeline terunggah. Hanya Research Admin.

    Menonaktifkan TIDAK menghapus record maupun berkas: eksperimen lama yang
    memakainya tetap tercatat lengkap dengan versi & hash-nya.
    """
    from orchestrator.auth_service import require_approve   # hindari impor siklik

    require_approve(actor, db_path)
    item = get_registered(pipeline_id, db_path)
    if item is None:
        raise DynamicRegistryError(f"Pipeline terdaftar tidak ditemukan: {pipeline_id}")

    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE registered_pipelines SET active = ? WHERE pipeline_id = ?",
                     (1 if active else 0, pipeline_id))
        conn.commit()
    finally:
        conn.close()
    logger.info("Pipeline %s di-%s oleh %s", pipeline_id,
                "aktifkan" if active else "nonaktifkan", (actor or {}).get("username"))
    return get_registered(pipeline_id, db_path)


# ── Pemuatan kelas (dengan verifikasi hash) ───────────────────────────────

def load_pipeline_class(entry_file: str | Path, entry_class: str,
                        expected_hash: str):
    """Muat sebuah kelas pipeline dari BERKAS SPESIFIK.

    Urutannya penting:
      1. berkas harus ada,
      2. SHA-256 harus sama persis dengan yang tercatat saat pendaftaran —
         berkas yang berubah ditolak SEBELUM kodenya dieksekusi,
      3. modul dimuat lewat spec_from_file_location (tanpa menyentuh sys.path),
      4. kelasnya harus ada dan benar-benar turunan ``BasePipeline`` dengan
         ``run`` & ``get_info``.
    """
    from pipelines.base import BasePipeline

    path = Path(entry_file)
    if not path.is_file():
        raise DynamicRegistryError(f"Berkas pipeline tidak ditemukan: {path}")

    actual = file_sha256(path)
    if actual != expected_hash:
        raise DynamicRegistryError(
            f"Hash berkas tidak cocok untuk {path.name}: tercatat "
            f"{expected_hash[:12]}…, ditemukan {actual[:12]}…. Berkas berubah "
            f"atau rusak — pemuatan ditolak.")

    # Nama modul unik & bernamespace: tidak menimpa modul platform mana pun,
    # dan folder unggahan TIDAK ditambahkan ke sys.path.
    module_name = f"_uploaded_pipeline_{actual[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise DynamicRegistryError(f"Tidak dapat menyiapkan pemuatan untuk {path.name}")

    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(module_name, None)
        raise DynamicRegistryError(
            f"Gagal memuat {path.name}: {type(e).__name__}: {e}") from e

    cls = getattr(module, entry_class, None)
    if cls is None:
        raise DynamicRegistryError(f"Kelas {entry_class} tidak ada di {path.name}")
    if not (isinstance(cls, type) and issubclass(cls, BasePipeline)):
        raise DynamicRegistryError(
            f"{entry_class} bukan turunan BasePipeline — ditolak.")
    for method in ("run", "get_info"):
        if not callable(getattr(cls, method, None)):
            raise DynamicRegistryError(
                f"{entry_class} tidak mengimplementasi {method}() — ditolak.")
    return cls


def load_registered_instance(pipeline_id: str, db_path: str | None = None):
    """Instance pipeline terunggah yang siap dijalankan, atau None bila
    pipeline_id itu bukan pipeline terunggah yang aktif.

    Raise DynamicRegistryError bila terdaftar tetapi tidak dapat dimuat —
    pemanggil (worker) mengubahnya menjadi kegagalan eksperimen yang jelas.
    """
    item = get_registered(pipeline_id, db_path)
    if item is None or not item["active"]:
        return None
    cls = load_pipeline_class(item["entry_file"], item["entry_class"],
                              item["file_hash"])
    return cls()


# ── Tampilan gabungan (statis + terunggah) ────────────────────────────────

def _entry_from_row(row: dict) -> dict:
    """Baris DB -> entri bergaya registry, TANPA memuat kelasnya.

    Menampilkan daftar tidak boleh mengeksekusi kode unggahan; kelas baru
    dimuat saat pipeline benar-benar dijalankan.
    """
    return {
        "dataset_type": row["dataset_type"],
        "name": f"{row['name']} v{row['version']} (terunggah)",
        "paper": row.get("paper") or "Pipeline terunggah (di luar git)",
        "algorithm": row.get("algorithm") or row["name"],
        "class": None,
        "stages": [],
        "uploaded": True,
        "version": row["version"],
        "file_hash": row["file_hash"],
        "entry_class": row["entry_class"],
        "entry_file": row["entry_file"],
    }


def get_all_pipelines(db_path: str | None = None) -> dict:
    """PIPELINE_REGISTRY statis + pipeline terunggah yang aktif.

    Entri statis SELALU menang: pipeline terunggah tidak pernah dapat menimpa
    ``hikari2021.*`` / ``eve_cbr.*``. Kegagalan membaca daftar terunggah tidak
    boleh merusak registry — pipeline bawaan tetap dikembalikan.
    """
    from config.pipeline_registry import PIPELINE_REGISTRY

    merged = dict(PIPELINE_REGISTRY)
    try:
        rows = list_registered(active_only=True, db_path=db_path)
    except Exception:
        logger.warning("Daftar pipeline terunggah tidak terbaca — "
                       "hanya pipeline bawaan yang ditampilkan", exc_info=True)
        return merged

    for row in rows:
        pipeline_id = row["pipeline_id"]
        if pipeline_id in merged:            # tidak mungkin terjadi (namespace
            logger.error(                    # berbeda), tetapi dijaga eksplisit
                "Pipeline terunggah %s bertabrakan dengan pipeline bawaan — "
                "entri bawaan dipertahankan.", pipeline_id)
            continue
        try:
            merged[pipeline_id] = _entry_from_row(row)
        except Exception:                    # pragma: no cover - defensive
            logger.warning("Entri pipeline terunggah %s dilewati", pipeline_id,
                           exc_info=True)
    return merged


def get_pipelines_for_dataset_merged(dataset_type: str,
                                     db_path: str | None = None) -> dict:
    return {pid: info for pid, info in get_all_pipelines(db_path).items()
            if info.get("dataset_type") == dataset_type}


def get_pipeline_instance_merged(pipeline_id: str, db_path: str | None = None):
    """Instance untuk pipeline_id apa pun — bawaan ATAU terunggah.

    Pipeline bawaan diambil lebih dulu dari registry statis, sehingga
    mekanisme dinamis tidak pernah berada di jalur eksekusi mereka.
    """
    from config.pipeline_registry import get_pipeline_instance

    instance = get_pipeline_instance(pipeline_id)
    if instance is not None:
        return instance
    if not str(pipeline_id).startswith(UPLOADED_PREFIX):
        return None
    return load_registered_instance(pipeline_id, db_path)


def traceability_for(pipeline_id: str, db_path: str | None = None) -> dict:
    """(pipeline_version, pipeline_hash) untuk dicatat pada eksperimen.

    Pipeline bawaan -> keduanya None: definisinya ada di git.
    """
    if not str(pipeline_id or "").startswith(UPLOADED_PREFIX):
        return {"pipeline_version": None, "pipeline_hash": None}
    try:
        item = get_registered(pipeline_id, db_path)
    except Exception:                        # pragma: no cover - defensive
        return {"pipeline_version": None, "pipeline_hash": None}
    if item is None:
        return {"pipeline_version": None, "pipeline_hash": None}
    return {"pipeline_version": item["version"], "pipeline_hash": item["file_hash"]}
