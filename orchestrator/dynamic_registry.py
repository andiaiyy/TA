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
import importlib.machinery
import importlib.util
import json
import logging
import sys
from pathlib import Path

from database.db import _retry_on_locked, get_connection
from database.models import UPLOADED_PREFIX
from utils.timestamps import now_iso
from orchestrator.user_errors import UserFacingMixin

logger = logging.getLogger(__name__)

_HASH_CHUNK = 1024 * 1024


class DynamicRegistryError(UserFacingMixin, RuntimeError):
    """Pipeline terunggah tidak dapat dimuat (hash, berkas, atau kontrak)."""


# ── Identitas & versi ─────────────────────────────────────────────────────

def safe_pipeline_name(raw: str) -> str:
    """Nama pipeline yang aman untuk dipakai sebagai bagian ID."""
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_"
                      for ch in (raw or "").strip().lower())
    cleaned = cleaned.strip("_-")
    if not cleaned:
        raise DynamicRegistryError("Nama pipeline tidak sah.",
                                   key="err.bad_pipeline_name")
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
                      paper: str | None = None, edited_by: str | None = None,
                      edited_at: str | None = None, change_note: str | None = None,
                      stages: list | None = None,
                      db_path: str | None = None) -> dict:
    """Daftarkan satu VERSI BARU pipeline terunggah.

    Tidak pernah menimpa: versi dihitung dari maksimum yang sudah ada + 1, dan
    (name, version) unik di level skema. Hash berkas dihitung SAAT INI dan
    disimpan sebagai patokan verifikasi saat dimuat nanti.

    ``edited_by``/``edited_at``/``change_note`` hanya terisi bila versi ini
    lahir dari PENYUNTINGAN Research Admin. Versi 1 lahir dari persetujuan,
    jadi ketiganya kosong di sana — itu fakta, bukan data yang hilang.

    ``stages`` adalah label fase progres yang dibaca STATIS dari panggilan
    `_emit_progress()` pada kode paketnya. Pipeline bawaan menyimpannya di
    `config/pipeline_registry.py`; yang terunggah tidak punya tempat itu, dan
    tanpa ini bar progresnya berjalan tanpa nama fase padahal pipelinenya SUDAH
    memancarkan fase itu. Kosong berarti paketnya memang tidak memanggil
    `_emit_progress` — keadaan yang sah.

    POTRET ``get_info()`` diambil DI SINI, sekali, dan disimpan bersama
    barisnya. Ia menjadi satu-satunya sumber keterangan bagi katalog dan
    halaman riwayat, sehingga keduanya tidak perlu memuat kode kontribusi hanya
    untuk menjelaskannya. Diambil di sini — bukan dititipkan pemanggil — karena
    setiap versi baru lahir dari berkas yang berbeda: menyunting kode tanpa
    memotret ulang akan menyimpan keterangan versi lama pada versi baru.
    """
    safe_name = safe_pipeline_name(name)
    entry_path = Path(entry_file)
    if not entry_path.is_file():
        raise DynamicRegistryError(
            f"Berkas entry point tidak ditemukan: {entry_path}",
            key="err.entry_file_missing", values={"path": str(entry_path)})

    version = next_version(safe_name, db_path)
    pipeline_id = build_pipeline_id(safe_name, version)
    digest = file_sha256(entry_path)

    conn = get_connection(db_path)
    try:
        conn.execute(
            """INSERT INTO registered_pipelines
               (pipeline_id, name, version, submission_id, dataset_type,
                entry_class, entry_file, file_hash, algorithm, paper,
                registered_by, registered_at, active,
                edited_by, edited_at, change_note, stages_json, info_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (pipeline_id, safe_name, version, submission_id, dataset_type,
             entry_class, str(entry_path), digest, algorithm, paper,
             registered_by, now_iso(), edited_by, edited_at, change_note,
             json.dumps(list(stages)) if stages else None,
             _dumped_info(_snapshot_info(entry_path, entry_class, digest))),
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("Pipeline terunggah didaftarkan: %s (kelas %s, hash %s…)",
                pipeline_id, entry_class, digest[:12])
    return get_registered(pipeline_id, db_path)


@_retry_on_locked()
def refresh_info(pipeline_id: str, *, actor: dict | None,
                 db_path: str | None = None) -> dict:
    """Ambil ULANG potret ``get_info()`` sebuah pipeline terdaftar.

    Dibutuhkan HANYA oleh baris yang terdaftar sebelum kolom potretnya ada.
    Baris seperti itu tidak dapat menjelaskan dirinya — katalog menampilkannya
    tanpa hyperparameter maupun langkah preprocessing — dan satu-satunya cara
    jujur mengisinya adalah memuat kodenya sekali lagi, SENGAJA, atas perintah
    Research Admin. Bukan diam-diam saat halaman digambar: itu mengembalikan
    persis biaya yang dihapus, tepat pada baris yang paling lama.

    Hash tetap diverifikasi seperti biasa; berkas yang berubah ditolak sebelum
    kodenya dieksekusi. Hanya Research Admin.
    """
    from orchestrator.auth_service import require_approve   # hindari impor siklik

    require_approve(actor, db_path)
    item = get_registered(pipeline_id, db_path)
    if item is None:
        raise DynamicRegistryError(
            f"Pipeline terdaftar tidak ditemukan: {pipeline_id}",
            key="err.pipeline_not_registered",
            values={"pipeline": pipeline_id})

    dumped = _dumped_info(_snapshot_info(Path(item["entry_file"]),
                                         item["entry_class"],
                                         item["file_hash"]))
    if dumped is None:
        raise DynamicRegistryError(
            f"Keterangan {pipeline_id} tidak dapat dibaca dari berkasnya.",
            key="err.info_snapshot_failed",
            values={"pipeline": pipeline_id})

    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE registered_pipelines SET info_json = ? "
                     "WHERE pipeline_id = ?", (dumped, pipeline_id))
        conn.commit()
    finally:
        conn.close()
    logger.info("Potret get_info() %s diperbarui oleh %s", pipeline_id,
                (actor or {}).get("username"))
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
        raise DynamicRegistryError(
            f"Pipeline terdaftar tidak ditemukan: {pipeline_id}",
            key="err.pipeline_not_registered",
            values={"pipeline": pipeline_id})

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


# ── Research pipeline sebagai SATU kesatuan ───────────────────────────────
#
# Sebuah research pipeline terunggah memuat beberapa algoritma; tiap algoritma
# adalah satu baris `registered_pipelines` dengan `dataset_type` yang sama.
# Sampai di sini, satu-satunya kendali yang ada bekerja per baris — padahal
# yang paling sering dimaksud adalah "matikan research pipeline ini", dan
# melakukannya satu per satu berarti keadaan setengah jalan setiap kali ada
# yang terlewat.


def research_algorithms(dataset_type: str,
                        db_path: str | None = None) -> list[dict]:
    """Seluruh algoritma sebuah research pipeline — aktif maupun tidak.

    Diurutkan seperti `list_registered`: nama lalu versi, sehingga daftarnya
    stabil antar penggambaran.
    """
    wanted = str(dataset_type or "")
    if not wanted:
        return []
    return [row for row in list_registered(db_path=db_path)
            if row.get("dataset_type") == wanted]


def research_active_count(dataset_type: str,
                          db_path: str | None = None) -> tuple[int, int]:
    """(berapa yang aktif, berapa seluruhnya) pada satu research pipeline."""
    rows = research_algorithms(dataset_type, db_path)
    return sum(1 for r in rows if r.get("active")), len(rows)


def set_research_active(dataset_type: str, active: bool, *, actor: dict | None,
                        db_path: str | None = None) -> list[dict]:
    """Aktifkan/nonaktifkan SELURUH algoritma satu research pipeline.

    Hanya Research Admin, dan hanya research pipeline TERUNGGAH: keluarga
    bawaan (`hikari2021.*`, `eve_cbr.*`) adalah pembanding tetap skripsi ini —
    kodenya tidak disunting dan ketersediaannya tidak dimatikan dari sini.

    Satu transaksi: kalau salah satu baris gagal ditulis, tidak ada satu pun
    yang berubah. Keadaan setengah jalan — sebagian algoritma hidup, sebagian
    mati, tanpa ada yang menghendakinya — justru yang paling membingungkan.
    """
    from database.models import is_uploaded_research
    from orchestrator.auth_service import require_approve   # hindari impor siklik

    require_approve(actor, db_path)
    if not is_uploaded_research(dataset_type):
        raise DynamicRegistryError(
            f"Research pipeline bawaan tidak dapat diubah dari sini: "
            f"{dataset_type}",
            key="err.research_builtin_readonly",
            values={"research": str(dataset_type)})

    rows = research_algorithms(dataset_type, db_path)
    if not rows:
        raise DynamicRegistryError(
            f"Research pipeline tidak ditemukan: {dataset_type}",
            key="err.research_not_found",
            values={"research": str(dataset_type)})

    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE registered_pipelines SET active = ? "
                     "WHERE dataset_type = ?",
                     (1 if active else 0, dataset_type))
        conn.commit()
    finally:
        conn.close()
    logger.info("Research pipeline %s di-%s (%s algoritma) oleh %s",
                dataset_type, "aktifkan" if active else "nonaktifkan",
                len(rows), (actor or {}).get("username"))
    return research_algorithms(dataset_type, db_path)


def last_active_algorithm_blocker(pipeline_id: str,
                                  db_path: str | None = None) -> str:
    """Alasan algoritma ini tidak boleh dinonaktifkan sendirian; "" bila boleh.

    Mematikan algoritma terakhir yang masih hidup membuat research pipeline-nya
    lenyap dari halaman Jalankan Eksperimen tanpa pernah dikatakan "research
    pipeline ini dimatikan". Yang dimaksud pada keadaan itu hampir selalu
    "matikan seluruhnya" — jadi itulah yang ditawarkan, bukan hasil yang sama
    yang dicapai diam-diam.
    """
    row = get_registered(pipeline_id, db_path)
    if row is None:
        return "err.pipeline_not_registered"
    if not row.get("active"):
        return ""                                  # sudah nonaktif
    live, _total = research_active_count(row.get("dataset_type"), db_path)
    return "mp.blocked_last_algorithm" if live <= 1 else ""


# ── Pemuatan kelas (dengan verifikasi hash) ───────────────────────────────

class _VerifiedSourceLoader(importlib.machinery.SourceFileLoader):
    """Pemuat yang TIDAK PERNAH memakai bytecode tersimpan.

    Sebuah `.pyc` dianggap sah bila **detik** mtime dan **ukuran** sumbernya
    cocok. Berkas yang ditulis ulang dalam detik yang sama dengan ukuran yang
    sama — dua versi sebuah pipeline yang hanya berbeda beberapa huruf — lolos
    pemeriksaan itu, sehingga yang DIJALANKAN adalah bytecode lama sementara
    hash yang baru saja diverifikasi adalah isi yang baru.

    Itu membatalkan justru apa yang dijaga pemeriksaan hash: bahwa kode yang
    berjalan adalah kode yang diperiksa. Di sini kode selalu disusun dari byte
    yang sama dengan yang dihitung hash-nya — dan tidak ada `.pyc` yang ditulis
    ke dalam folder unggahan.
    """

    def get_code(self, fullname):
        return self.source_to_code(self.get_data(self.path), self.path)


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
    from orchestrator.submission_service import stored_location

    # Jalur berkas dicatat ABSOLUT saat pendaftaran. Platform ini berpindah
    # antara container dan host di atas folder `storage/` yang sama, jadi jalur
    # yang benar di satu lingkungan salah di lingkungan lain — dan pipeline
    # yang berkasnya ada persis di sana dilaporkan "bermasalah". Impor di dalam
    # fungsi: `submission_service` mengimpor modul ini.
    path = stored_location(entry_file)
    if not path.is_file():
        raise DynamicRegistryError(
            f"Berkas pipeline tidak ditemukan: {path}",
            key="err.pipeline_file_missing", values={"path": str(path)})

    actual = file_sha256(path)
    if actual != expected_hash:
        raise DynamicRegistryError(
            f"Hash berkas tidak cocok untuk {path.name}: tercatat "
            f"{expected_hash[:12]}…, ditemukan {actual[:12]}…. Berkas berubah "
            f"atau rusak — pemuatan ditolak.",
            key="err.hash_mismatch",
            values={"file": path.name, "recorded": expected_hash[:12],
                    "found": actual[:12]})

    # Nama modul unik & bernamespace: tidak menimpa modul platform mana pun,
    # dan folder unggahan TIDAK ditambahkan ke sys.path.
    module_name = f"_uploaded_pipeline_{actual[:16]}"
    spec = importlib.util.spec_from_file_location(
        module_name, path, loader=_VerifiedSourceLoader(module_name, str(path)))
    if spec is None or spec.loader is None:
        raise DynamicRegistryError(
            f"Tidak dapat menyiapkan pemuatan untuk {path.name}",
            key="err.cannot_prepare_load", values={"path": path.name})

    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(module_name, None)
        raise DynamicRegistryError(
            f"Gagal memuat {path.name}: {type(e).__name__}: {e}",
            key="err.pipeline_load_failed",
            values={"filename": path.name, "kind": type(e).__name__,
                    "detail": str(e)}) from e

    cls = getattr(module, entry_class, None)
    if cls is None:
        raise DynamicRegistryError(
            f"Kelas {entry_class} tidak ada di {path.name}",
            key="err.class_not_in_file",
            values={"cls": entry_class, "filename": path.name})
    if not (isinstance(cls, type) and issubclass(cls, BasePipeline)):
        raise DynamicRegistryError(
            f"{entry_class} bukan turunan BasePipeline — ditolak.",
            key="err.not_a_base_pipeline", values={"cls": entry_class})
    for method in ("run", "get_info"):
        if not callable(getattr(cls, method, None)):
            raise DynamicRegistryError(
                f"{entry_class} tidak mengimplementasi {method}() — ditolak.",
                key="err.missing_contract_method",
                values={"cls": entry_class, "method": method})
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

def _stages_of(row: dict) -> list:
    """Fase progres sebuah baris registry; [] bila tidak ada atau rusak.

    Baris LAMA tidak punya kolomnya sama sekali, dan itu bukan kesalahan —
    jawabannya sama dengan "paket ini tidak memancarkan fase".
    """
    raw = row.get("stages_json")
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):           # pragma: no cover - defensif
        logger.warning("stages_json tidak terbaca pada %s", row.get("pipeline_id"))
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _snapshot_info(entry_file: Path, entry_class: str,
                   digest: str) -> dict | None:
    """``get_info()`` paket ini, dipanggil sekali saat pendaftaran.

    Ini SATU-SATUNYA tempat kode kontribusi dimuat demi keterangan, dan ia
    terjadi pada saat kode itu memang sudah divalidasi dan diuji. Sesudahnya
    tidak ada halaman tampilan yang perlu mengimpornya lagi.

    Kegagalan TIDAK menggagalkan pendaftaran: pipeline yang sah tidak boleh
    ditolak karena keterangannya tidak terbaca. Yang hilang hanya
    keterangannya, dan kehilangan itu terlihat sebagai potret kosong.
    """
    try:
        instance = load_pipeline_class(entry_file, entry_class, digest)()
        info = instance.get_info()
    except Exception:
        logger.warning("get_info() tidak dapat dipotret untuk %s (kelas %s)",
                       entry_file, entry_class, exc_info=True)
        return None
    return info if isinstance(info, dict) else None


def _dumped_info(info: dict | None) -> str | None:
    """Potret ``get_info()`` sebagai JSON; None bila tidak dapat dipotret.

    Nilai yang tidak dapat diserialkan TIDAK menggagalkan pendaftaran: sebuah
    pipeline yang sah tidak boleh ditolak karena keterangannya membawa objek
    aneh. Yang hilang hanyalah keterangannya, dan kehilangan itu terlihat.
    """
    if not info:
        return None
    try:
        return json.dumps(info, default=str)
    except (TypeError, ValueError):           # pragma: no cover - defensif
        logger.warning("get_info() tidak dapat dipotret sebagai JSON")
        return None


def _info_of(row: dict) -> dict:
    """Potret ``get_info()`` sebuah baris registry; {} bila tidak ada.

    Baris yang terdaftar sebelum kolomnya ada tidak punya potret — jawabannya
    "tidak diketahui", dan pemanggilnya yang memutuskan bagaimana mengatakan
    itu kepada pembaca.
    """
    raw = row.get("info_json")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):           # pragma: no cover - defensif
        logger.warning("info_json tidak terbaca pada %s", row.get("pipeline_id"))
        return {}
    return value if isinstance(value, dict) else {}


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
        # Fase progres paket ini, bila kodenya memancarkannya. Dibaca dari
        # baris registry — BUKAN dengan menengok pengajuannya, yang berarti
        # satu kueri tambahan untuk setiap pipeline pada setiap penggambaran.
        "stages": _stages_of(row),
        # Potret `get_info()`. Inilah yang membuat katalog dan halaman riwayat
        # dapat MENJELASKAN pipeline ini tanpa mengimpor kodenya.
        "info": _info_of(row),
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
