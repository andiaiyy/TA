"""Identitas research pipeline: bawaan + terunggah, digabung — Tahap 1.

Apa yang membuat sebuah "research pipeline" ada di platform ini bukan satu
hal, melainkan tiga sumber statis:

* ``contracts/dataset_schemas.py`` -> ``dataset_type`` + skema datasetnya;
* ``config/research_attribution.py`` -> nama beratribusi & kredit penelitian;
* ``config/pipeline_registry.py`` -> daftar algoritmanya.

Hanya yang ketiga yang punya pasangan dinamis (``orchestrator/dynamic_registry``).
Akibatnya sebuah unggahan tidak pernah bisa berdiri sendiri: ia harus MENUMPANG
salah satu ``dataset_type`` bawaan, dan itulah sebabnya kartu peninjauan sempat
harus bertanya "ini ikut research pipeline mana". Pertanyaan itu akibat dari
ketiadaan jalur dinamis, bukan pilihan desain.

Modul ini melengkapi dua sumber sisanya, mengikuti pola yang sudah terbukti di
``dynamic_registry.get_all_pipelines()``.

**Kenapa di sini, bukan di contracts/ atau config/.** ``pipelines/`` mengimpor
``config.research_attribution`` di tujuh tempat (keenam pipeline HIKARI +
adapter cbr) dan TIDAK BOLEH mengimpor ``orchestrator``/``database``. Menaruh
pembaca gabungan di sana akan membalik arah impor lapisan. Jadi fungsi statisnya
dibiarkan apa adanya untuk ``pipelines/``, dan penggabungan hidup di lapis ini —
yang memang sudah boleh membaca basis data.

Tiga sifat yang dijaga:

A. **Statis SELALU menang.** ``dataset_type`` terunggah bernamespace
   ``uploaded:``; tabrakan dengan ``HIKARI2021``/``EVE_SURICATA`` tidak mungkin
   terjadi, dan bila entah bagaimana terjadi, entri bawaan yang dipertahankan.
B. **Skema DIDEKLARASIKAN, tidak pernah ditebak.** Isinya berasal dari isian
   kontributor; platform tidak pernah mengarang skema dari nama atau isi berkas.
C. **Kegagalan membaca tidak merusak yang bawaan.** Tabel yang hilang atau rusak
   menghasilkan daftar bawaan yang utuh, bukan halaman yang jatuh.
"""
from __future__ import annotations

import json
import logging

from contracts.dataset_schemas import DATASET_SCHEMAS
from contracts.dataset_schemas import get_schema as _static_schema
from contracts.dataset_schemas import supported_datasets as _static_types
from config.research_attribution import get_research_attribution as _static_attribution
from database.db import get_connection
from database.models import is_uploaded_research
from orchestrator.user_errors import UserFacingMixin
from utils.timestamps import now_iso

logger = logging.getLogger(__name__)


class ResearchRegistryError(UserFacingMixin, RuntimeError):
    """Identitas research tidak dapat dicatat."""

#: Bidang skema yang BENAR-BENAR dibaca platform — dihitung dari seluruh
#: pembacaan ``schema[...]`` di validator, diagnosa, eksekusi, dan tampilan
#: (label_column 15x, expected_top_level_keys 10x, file_format 3x,
#: expected_columns 3x). Deklarasi kontributor harus menghasilkan bentuk ini.
SCHEMA_FIELDS = ("label_column", "expected_columns", "file_format",
                 "expected_top_level_keys")


def _row_schema(raw) -> dict:
    """Skema tersimpan -> bentuk yang SAMA dengan skema bawaan."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    out = {
        "label_column": value.get("label_column") or "",
        "expected_columns": list(value.get("expected_columns") or []),
    }
    if value.get("file_format"):
        out["file_format"] = value["file_format"]
    if value.get("expected_top_level_keys"):
        out["expected_top_level_keys"] = list(value["expected_top_level_keys"])
    return out


# -- Pembacaan tabel -------------------------------------------------------

def list_research(*, active_only: bool = True,
                  db_path: str | None = None) -> list[dict]:
    """Research pipeline terunggah. Kegagalan membaca -> daftar KOSONG.

    Kosong, bukan lemparan: daftar bawaan harus tetap utuh walau tabel ini
    hilang atau rusak.
    """
    sql = "SELECT * FROM research_pipelines"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY name"
    try:
        with get_connection(db_path) as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]
    except Exception:
        logger.warning("Daftar research pipeline terunggah tidak terbaca - "
                       "hanya yang bawaan yang ditampilkan", exc_info=True)
        return []


def get_research(dataset_type: str, db_path: str | None = None) -> dict | None:
    if not is_uploaded_research(dataset_type):
        return None
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM research_pipelines WHERE dataset_type = ?",
                (dataset_type,)).fetchone()
        return dict(row) if row else None
    except Exception:
        logger.warning("Research pipeline %s tidak terbaca", dataset_type,
                       exc_info=True)
        return None


def research_override(dataset_type: str,
                      db_path: str | None = None) -> dict | None:
    """Baris `research_pipelines` sebuah jenis dataset — BAWAAN maupun unggahan.

    Berbeda dari :func:`get_research`, yang sengaja menolak jenis bawaan:
    fungsi ini justru dipakai untuk MENIMPA keterangan bawaan.

    Definisi research bawaan hidup di `contracts/` dan `config/` — berkas yang
    tidak boleh disentuh, dan memang tidak perlu: yang disunting Research Admin
    adalah METADATANYA, dan metadata itu disimpan sebagai baris timpaan di
    sini. Menghapus barisnya mengembalikan keterangan bawaan ke definisi git,
    utuh, tanpa satu berkas pun berubah.
    """
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM research_pipelines WHERE dataset_type = ?",
                (dataset_type,)).fetchone()
        return dict(row) if row else None
    except Exception:                       # pragma: no cover - defensif
        logger.warning("Timpaan research %s tidak terbaca", dataset_type,
                       exc_info=True)
        return None


def register_research(*, dataset_type: str, name: str, schema: dict,
                      registered_by: str, submission_id: int | None = None,
                      attribution: dict | None = None,
                      db_path: str | None = None) -> dict | None:
    """Catat identitas research sebuah unggahan. Bawaan tidak dapat ditimpa."""
    if not is_uploaded_research(dataset_type):
        raise ValueError(
            "dataset_type research terunggah harus bernamespace: "
            f"{dataset_type!r}")
    if dataset_type in DATASET_SCHEMAS:     # tidak mungkin; dijaga eksplisit
        raise ValueError(f"{dataset_type} bertabrakan dengan research bawaan")

    # `dataset_type` UNIK di level skema, jadi nama yang sudah terpakai membuat
    # INSERT di bawah gagal sebagai `IntegrityError` — kalimat basis data, di
    # tangan PENINJAU, saat menekan Setujui, jauh dari sebabnya. Ditolak di
    # sini sebagai kalimat yang dapat dibaca dan diterjemahkan.
    if get_research(dataset_type, db_path) is not None:
        raise ResearchRegistryError(
            f"Nama research \"{name}\" sudah dipakai research pipeline lain.",
            key="err.research_name_taken",
            values={"name": name, "research": dataset_type})

    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO research_pipelines "
            "(dataset_type, name, submission_id, schema_json, "
            " attribution_json, registered_by, registered_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (dataset_type, name, submission_id, json.dumps(schema or {}),
             json.dumps(attribution) if attribution else None,
             registered_by, now_iso()))
        conn.commit()
    logger.info("Research pipeline terunggah terdaftar: %s", dataset_type)
    return get_research(dataset_type, db_path)


# -- Pembaca GABUNGAN: inilah yang dipakai orchestrator & tampilan ---------

def update_research(dataset_type: str, *, name: str | None = None,
                    attribution: dict | None = None,
                    schema: dict | None = None, actor: dict | None,
                    db_path: str | None = None) -> dict:
    """Sunting metadata sebuah research pipeline. Hanya Research Admin.

    Berlaku untuk KEDUANYA. Research kontribusi punya barisnya sendiri dan
    barisnya diperbarui; research bawaan tidak punya baris, jadi sebuah baris
    TIMPAAN dibuat untuknya — definisi di `contracts/` dan `config/` tidak
    pernah disentuh, dan menghapus baris timpaan itu mengembalikan semuanya ke
    definisi git (lihat :func:`revert_research`).

    Yang disunting hanyalah KETERANGAN: nama tampil, atribusi penelitian, dan
    kontrak dataset. Tidak ada kode pipeline, hash, versi, atau berkas yang
    tersentuh — dan `dataset_type` tidak pernah berubah, karena baris
    `experiments` yang sudah ada menunjuk padanya.
    """
    from orchestrator.auth_service import require_approve  # hindari impor siklik

    require_approve(actor, db_path)
    dataset_type = str(dataset_type or "").strip()
    if not dataset_type:
        raise ResearchRegistryError("dataset_type kosong.",
                                    key="err.research_not_found",
                                    values={"research": ""})

    row = research_override(dataset_type, db_path)
    static_schema = _static_schema(dataset_type)
    if row is None and static_schema is None:
        raise ResearchRegistryError(
            f"Research pipeline tidak ditemukan: {dataset_type}",
            key="err.research_not_found", values={"research": dataset_type})

    # Bidang yang TIDAK diberikan tidak berubah. Skema selalu tersimpan utuh:
    # kolomnya NOT NULL, dan sebuah baris timpaan tanpa skema akan membuat
    # jenis bawaan kehilangan kontraknya.
    efektif_schema = schema if schema is not None else (
        _row_schema(row.get("schema_json")) if row else None) or static_schema or {}
    efektif_nama = (name or "").strip() or (row["name"] if row else
                                            dataset_type)
    if attribution is None:
        try:
            attribution = json.loads(row["attribution_json"] or "{}") if row else {}
        except (TypeError, ValueError):
            attribution = {}

    sekarang = now_iso()
    siapa = (actor or {}).get("username") or ""
    with get_connection(db_path) as conn:
        if row is None:
            conn.execute(
                "INSERT INTO research_pipelines "
                "(dataset_type, name, submission_id, schema_json, "
                " attribution_json, registered_by, registered_at, active, "
                " updated_at, updated_by) "
                "VALUES (?, ?, NULL, ?, ?, ?, ?, 1, ?, ?)",
                (dataset_type, efektif_nama, json.dumps(efektif_schema),
                 json.dumps(attribution), siapa, sekarang, sekarang, siapa))
        else:
            conn.execute(
                "UPDATE research_pipelines SET name = ?, schema_json = ?, "
                "attribution_json = ?, updated_at = ?, updated_by = ? "
                "WHERE dataset_type = ?",
                (efektif_nama, json.dumps(efektif_schema),
                 json.dumps(attribution), sekarang, siapa, dataset_type))
        conn.commit()
    logger.info("Research pipeline %s disunting oleh %s", dataset_type, siapa)
    return research_override(dataset_type, db_path) or {}


def revert_research(dataset_type: str, *, actor: dict | None,
                    db_path: str | None = None) -> bool:
    """Buang baris TIMPAAN sebuah research BAWAAN; True bila ada yang dibuang.

    Hanya untuk jenis bawaan: barisnya semata lapisan di atas definisi git,
    jadi membuangnya memulihkan keterangan aslinya tanpa kehilangan apa pun.
    Research KONTRIBUSI ditolak — barisnya bukan timpaan, melainkan satu-
    satunya tempat identitasnya hidup.
    """
    from orchestrator.auth_service import require_approve

    require_approve(actor, db_path)
    # Diperiksa lewat ruang namanya, bukan lewat ada-tidaknya definisi statis:
    # `get_research_attribution` mengembalikan bentuk kosong (bukan None) untuk
    # jenis yang tidak dikenalnya, sehingga penjaga berbasis itu meloloskan
    # research kontribusi — dan menghapus barisnya berarti menghapus
    # identitasnya, bukan memulihkan apa pun.
    if is_uploaded_research(dataset_type):
        raise ResearchRegistryError(
            f"Bukan research bawaan, tidak ada yang dapat dipulihkan: "
            f"{dataset_type}",
            key="err.research_not_builtin", values={"research": dataset_type})

    with get_connection(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM research_pipelines WHERE dataset_type = ?",
            (dataset_type,))
        conn.commit()
    return bool(cur.rowcount)


def all_dataset_types(db_path: str | None = None) -> list[str]:
    """`dataset_type` bawaan + terunggah yang aktif. Bawaan SELALU lebih dulu."""
    out = list(_static_types())
    for row in list_research(db_path=db_path):
        if row["dataset_type"] not in out:
            out.append(row["dataset_type"])
    return out


def _is_deliberate_override(dataset_type: str, row: dict | None) -> bool:
    """Apakah baris ini SUNTINGAN yang disengaja atas sebuah jenis bawaan.

    Jenis bawaan hanya boleh ditimpa oleh :func:`update_research`, yang selalu
    mengisi ``updated_at`` dan ``updated_by``. Baris yang muncul lewat jalur
    lain — disisipkan langsung ke basis data dengan nama bawaan — TIDAK
    menimpa apa pun: definisi di git tetap menang, persis seperti sebelum
    penyuntingan ada.

    Untuk jenis KONTRIBUSI pertanyaannya tidak berlaku: barisnya bukan lapisan
    di atas apa pun, ia satu-satunya tempat identitasnya hidup.
    """
    if row is None:
        return False
    if is_uploaded_research(dataset_type):
        return True
    return bool(str(row.get("updated_at") or "").strip())


def merge_schema(dataset_type: str, row: dict | None) -> dict | None:
    """Skema efektif dari (jenis, baris timpaan) — MURNI, tanpa basis data.

    Dipisah supaya pemanggil yang sudah memegang barisnya — halaman
    pengelolaan membaca seluruh baris sekali — tidak perlu membacanya lagi
    per research. Aturannya: SUNTINGAN yang disengaja menang, lalu bawaan.
    """
    if (row is not None and row.get("active")
            and _is_deliberate_override(dataset_type, row)):
        declared = _row_schema(row.get("schema_json"))
        if declared:
            return declared
    static = _static_schema(dataset_type)
    if static is not None:
        return static
    if row is None or not row.get("active"):
        return None
    return _row_schema(row.get("schema_json")) or None


def merge_attribution(dataset_type: str, row: dict | None) -> dict:
    """Atribusi efektif dari (jenis, baris timpaan) — MURNI, tanpa basis data."""
    static = _static_attribution(dataset_type) or {}
    if row is None or not _is_deliberate_override(dataset_type, row):
        return dict(static)

    try:
        declared = json.loads(row.get("attribution_json") or "{}")
    except (TypeError, ValueError):
        declared = {}
    if not isinstance(declared, dict):
        declared = {}

    if static:
        gabung = dict(static)
        gabung.update({k: v for k, v in declared.items()
                       if v not in (None, "", {}, [])})
        return gabung

    declared.setdefault("display_name", f"{row['name']} (kontribusi)")
    declared.setdefault("short_name", row["name"])
    return declared


def schema_for(dataset_type: str, db_path: str | None = None) -> dict | None:
    """Skema sebuah `dataset_type` - bawaan MENANG, lalu terunggah.

    Mengembalikan ``None`` untuk jenis tak dikenal, sama seperti
    ``contracts.dataset_schemas.get_schema``, sehingga seluruh pemanggil yang
    sudah menangani ``None`` tidak berubah perilakunya sama sekali.
    """
    # Timpaan yang DISUNTING Research Admin menang atas definisi bawaan —
    # itulah artinya "dapat disunting". Tanpa baris timpaan, jawabannya sama
    # persis seperti sebelumnya.
    return merge_schema(dataset_type, research_override(dataset_type, db_path))


def attribution_for(dataset_type: str, db_path: str | None = None) -> dict:
    """Atribusi sebuah `dataset_type`: definisi bawaan, DITIMPA suntingan.

    Suntingan Research Admin disimpan sebagai baris `research_pipelines` dan
    ditumpuk DI ATAS definisi bawaan — bidang yang tidak disunting tetap
    datang dari `config/research_attribution.py`, dan menghapus baris
    timpaannya mengembalikan seluruhnya ke definisi git.
    """
    return merge_attribution(dataset_type,
                             research_override(dataset_type, db_path))


# -- Dataset yang MENYATU dengan research pipeline ------------------------

def dataset_for(dataset_type: str, db_path: str | None = None) -> dict:
    """Keterangan dataset yang terikat pada research pipeline ini, atau ``{}``.

    Kosong berarti research ini memakai dataset PLATFORM — keadaan yang sah
    bagi keluarga bawaan dan bagi unggahan yang menumpang jenis bawaan.
    """
    row = get_research(dataset_type, db_path)
    if row is None:
        return {}
    try:
        value = json.loads(row.get("dataset_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def bind_dataset(dataset_type: str, info: dict,
                 db_path: str | None = None) -> dict:
    """Ikat sebuah dataset ke research pipeline terunggah.

    Dataset ini TIDAK masuk ``storage/datasets/``: ia hanya ditawarkan saat
    menjalankan algoritma milik research pipeline-nya sendiri. Itulah yang
    menjaga perbandingan tetap jujur — dataset kontribusi tidak dapat dipakai
    menjalankan pipeline bawaan yang menjadi dasar hasil penelitian, dan
    hasilnya tidak pernah tercampur ke riwayat yang sama.
    """
    if not is_uploaded_research(dataset_type):
        raise ValueError(
            f"Hanya research pipeline terunggah yang dapat mengikat dataset: "
            f"{dataset_type!r}")
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE research_pipelines SET dataset_json = ? WHERE dataset_type = ?",
            (json.dumps(info or {}), dataset_type))
        conn.commit()
    return dataset_for(dataset_type, db_path)


def dataset_files_for(dataset_type: str, db_path: str | None = None) -> list[str]:
    """Berkas dataset yang boleh dipakai research pipeline ini.

    * research BAWAAN -> ``[]``; pemanggil memakai isi ``storage/datasets/``
      seperti sebelumnya, dan jalur itu tidak berubah sama sekali;
    * research TERUNGGAH -> dataset terikatnya saja, dan hanya bila berkasnya
      benar-benar ada. Berkas yang hilang menghasilkan daftar kosong, bukan
      pilihan yang pasti gagal saat dijalankan.
    """
    if not is_uploaded_research(dataset_type):
        return []
    info = dataset_for(dataset_type, db_path)
    path = info.get("stored_path")
    if not path:
        return []
    # Impor di dalam fungsi: `submission_service` mengimpor modul ini, jadi
    # impor tingkat-modul akan melingkar.
    from orchestrator.submission_service import stored_location

    resolved = stored_location(path)
    return [str(resolved)] if resolved.is_file() else []


def display_name_for(dataset_type: str, db_path: str | None = None) -> str:
    """Nama tampilan. Jenis tak dikenal jatuh kembali ke pengenalnya sendiri —
    perilaku yang sama persis dengan sumber statisnya."""
    entry = attribution_for(dataset_type, db_path)
    return entry.get("display_name") or dataset_type


def short_label_from(dataset_type: str, entry: dict) -> str:
    """Label pendek dari atribusi yang SUDAH ada — MURNI, tanpa basis data.

    Dipisah karena pemanggil yang menyusun daftar sudah memegang atribusinya;
    memanggil `short_label_for()` di sana berarti membaca barisnya sekali lagi
    untuk setiap research.
    """
    if not entry:
        return dataset_type
    credit = str(entry.get("display_name") or "").split("—")[0].strip()
    short = entry.get("short_name") or dataset_type
    return f"{credit} — {short}" if credit and credit != short else short


def short_label_for(dataset_type: str, db_path: str | None = None) -> str:
    return short_label_from(dataset_type,
                            attribution_for(dataset_type, db_path))


def paper_credit_for(dataset_type: str, db_path: str | None = None) -> str:
    entry = attribution_for(dataset_type, db_path)
    return entry.get("paper_credit") or f"Research pipeline: {dataset_type}"


__all__ = [
    "SCHEMA_FIELDS", "all_dataset_types", "attribution_for",
    "bind_dataset", "dataset_files_for", "dataset_for",
    "display_name_for", "get_research", "list_research", "paper_credit_for",
    "register_research", "schema_for", "short_label_for",
]
