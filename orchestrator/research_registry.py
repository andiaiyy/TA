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

def all_dataset_types(db_path: str | None = None) -> list[str]:
    """`dataset_type` bawaan + terunggah yang aktif. Bawaan SELALU lebih dulu."""
    out = list(_static_types())
    for row in list_research(db_path=db_path):
        if row["dataset_type"] not in out:
            out.append(row["dataset_type"])
    return out


def schema_for(dataset_type: str, db_path: str | None = None) -> dict | None:
    """Skema sebuah `dataset_type` - bawaan MENANG, lalu terunggah.

    Mengembalikan ``None`` untuk jenis tak dikenal, sama seperti
    ``contracts.dataset_schemas.get_schema``, sehingga seluruh pemanggil yang
    sudah menangani ``None`` tidak berubah perilakunya sama sekali.
    """
    static = _static_schema(dataset_type)
    if static is not None:
        return static
    row = get_research(dataset_type, db_path)
    if row is None or not row.get("active"):
        return None
    return _row_schema(row.get("schema_json")) or None


def attribution_for(dataset_type: str, db_path: str | None = None) -> dict:
    """Atribusi sebuah `dataset_type` - bawaan MENANG, lalu terunggah."""
    static = _static_attribution(dataset_type)
    if static:
        return static
    row = get_research(dataset_type, db_path)
    if row is None:
        return {}
    try:
        declared = json.loads(row["attribution_json"] or "{}")
    except (TypeError, ValueError):
        declared = {}
    if not isinstance(declared, dict):
        declared = {}
    # Nama tampilan SELALU ada: pembaca berhak tahu ini research kontribusi,
    # dan dari mana asalnya.
    declared.setdefault("display_name", f"{row['name']} (kontribusi)")
    declared.setdefault("short_name", row["name"])
    return declared


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


def short_label_for(dataset_type: str, db_path: str | None = None) -> str:
    entry = attribution_for(dataset_type, db_path)
    if not entry:
        return dataset_type
    credit = str(entry.get("display_name") or "").split("—")[0].strip()
    short = entry.get("short_name") or dataset_type
    return f"{credit} — {short}" if credit and credit != short else short


def paper_credit_for(dataset_type: str, db_path: str | None = None) -> str:
    entry = attribution_for(dataset_type, db_path)
    return entry.get("paper_credit") or f"Research pipeline: {dataset_type}"


__all__ = [
    "SCHEMA_FIELDS", "all_dataset_types", "attribution_for",
    "bind_dataset", "dataset_files_for", "dataset_for",
    "display_name_for", "get_research", "list_research", "paper_credit_for",
    "register_research", "schema_for", "short_label_for",
]
