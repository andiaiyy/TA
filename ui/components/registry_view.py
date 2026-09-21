"""
Bahan tampilan "Aktif" — lapis MURNI.

Modul ini menjawab satu pertanyaan: *"pipeline kontribusi ini sebenarnya
apa, versi berapa, dan berkasnya masih utuh atau tidak"*. Jawabannya dipakai
dua tempat — kartu bagian "Aktif" pada Peninjauan Pengajuan
(``ui/views/manage_pipelines.py``) dan penanda keadaan di katalog pipeline
(``ui/components/pipeline_catalog.py``).

**Yang DICABUT dari modul ini.** Dahulu ia juga membangun tabel versi
algoritma, tabel riwayat versi, dan seluruh pembanding dua versi (diff baris,
pelipatan baris yang sama, indeks berkas). Tampilan yang memakainya sudah
dihapus, jadi pembangunnya ikut dicabut — 356 baris yang tidak lagi punya
satu pun pemanggil. Yang tersisa di berkas ini hanyalah yang benar-benar
terjangkau dari kedua pemakai di atas.

Datanya tidak ikut hilang: ``registered_pipelines`` dan ``pipeline_versions``
tetap utuh, dan ``orchestrator/pipeline_versions.version_history`` tetap
menyediakan riwayatnya bagi pemanggil mana pun.

**Tidak ada data baru.** Seluruhnya dari kolom yang sudah tersimpan pada
``registered_pipelines`` dan ``experiments``; yang berubah hanya penyajiannya.

**Hitungan per versi datang gratis.** Identitas pipeline kontribusi berbentuk
``uploaded.<nama>@v<N>`` — nomor versinya melekat pada ``pipeline_id`` yang
dicatat setiap eksperimen. Jadi ``experiment_counts()`` yang berkunci
``pipeline_id`` SUDAH per versi; jumlah untuk satu pipeline tinggal menjumlahkan
versi-versinya. Tidak ada mekanisme penyaringan baru yang perlu dibangun.

**Memeriksa "gagal dimuat" TANPA menjalankan kode.** Sebuah versi dinyatakan
bermasalah bila berkasnya hilang atau SHA-256-nya tidak lagi cocok dengan yang
tercatat — keduanya dapat diketahui dengan membaca berkas dan menghitung
hash-nya, tanpa satu baris pun dieksekusi. Itu persis pemeriksaan yang menolak
pemuatan saat eksekusi, jadi tampilannya jujur terhadap apa yang akan terjadi.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ── Keadaan satu versi ────────────────────────────────────────────────────

# PENGENAL keadaan — dipakai untuk perbandingan dan tersimpan pada baris
# tabel, jadi nilainya TIDAK berbahasa. Kalimatnya ada di katalog.
STATE_OK = "ok"
STATE_MISSING = "berkas hilang"
STATE_TAMPERED = "hash tidak cocok"

#: Pengenal keadaan → kunci kalimat alasannya. Label pendeknya sudah
#: dicabut bersama tabel versi yang dahulu menampilkannya.
STATE_REASON_KEYS = {
    STATE_OK: "",
    STATE_MISSING: "rv.state_missing",
    STATE_TAMPERED: "rv.state_tampered",
}


def state_reason(state: str) -> str:
    """Alasan sebuah keadaan pada bahasa aktif; "" untuk keadaan baik."""
    from ui.i18n import t

    key = STATE_REASON_KEYS.get(state, "")
    return t(key) if key else ""


# ── Pengelompokan versi ───────────────────────────────────────────────────

def group_versions(rows) -> dict[str, list[dict]]:
    """{nama pipeline: [versi, terbaru dulu]} dari seluruh baris registry."""
    grouped: dict[str, list[dict]] = {}
    for row in rows or []:
        grouped.setdefault(row.get("name") or "", []).append(dict(row))
    for versions in grouped.values():
        versions.sort(key=lambda r: r.get("version") or 0, reverse=True)
    return grouped


def active_version(versions) -> dict | None:
    """Versi yang sedang aktif, atau None bila pipeline ini dinonaktifkan."""
    for row in versions or []:
        if row.get("active"):
            return row
    return None


def newest_version(versions) -> dict | None:
    return (versions or [None])[0]


# ── Keadaan berkas satu versi ─────────────────────────────────────────────

def version_state(row: dict, *, hash_reader=None) -> tuple[str, str]:
    """(keadaan, alasan) satu versi — TANPA menjalankan kodenya.

    ``hash_reader(path) -> str`` disuntikkan saat menguji; secara bawaan ia
    menghitung SHA-256 berkas di disk.
    """
    if hash_reader is None:
        from orchestrator.dynamic_registry import file_sha256

        def hash_reader(path):
            # Ditambatkan ke `storage/` yang berlaku: tanpa itu sebuah versi
            # yang berkasnya utuh tampil sebagai "hilang" hanya karena
            # jalurnya dicatat dari lingkungan yang lain.
            from orchestrator.submission_service import stored_location

            target = stored_location(path)
            return file_sha256(target) if target.is_file() else ""

    try:
        actual = hash_reader(row.get("entry_file") or "")
    except Exception:                       # pragma: no cover - defensif
        logger.debug("Hash versi tidak terbaca", exc_info=True)
        actual = ""

    if not actual:
        return STATE_MISSING, state_reason(STATE_MISSING)
    if actual != (row.get("file_hash") or ""):
        return STATE_TAMPERED, state_reason(STATE_TAMPERED)
    return STATE_OK, ""


# ── Ringkasan satu pipeline ───────────────────────────────────────────────

def pipeline_summary(name: str, versions, counts: dict, *,
                     running: dict | None = None,
                     hash_reader=None, dataset_reader=None) -> dict:
    """Identitas + ketertelusuran satu pipeline kontribusi.

    ``counts`` adalah {pipeline_id: jumlah eksperimen} — sudah per VERSI karena
    nomor versi melekat pada pipeline_id.

    ``dataset_reader(dataset_type) -> bool`` menjawab "adakah dataset yang
    dapat dipakainya". Ia DISUNTIKKAN, dan bawaannya membaca sumber yang sama
    dengan katalog. Tanpa jawaban itu, halaman ini menyebut sebuah pipeline
    "aktif" sementara halaman Jalankan Eksperimen menyebutnya belum dapat
    dijalankan — dua halaman, dua kebenaran, dan pembacanya menyimpulkan
    sistemnya tidak sinkron. Ia memang tidak sinkron.
    """
    versions = list(versions or [])
    running = running or {}
    current = active_version(versions) or newest_version(versions) or {}
    state, reason = version_state(current, hash_reader=hash_reader)

    if dataset_reader is None:
        from ui.components.pipeline_catalog import has_dataset_for

        dataset_reader = has_dataset_for
    try:
        runnable = bool(dataset_reader(current.get("dataset_type") or ""))
    except Exception:                       # pragma: no cover - defensif
        runnable = True                     # ragu = jangan menuduh

    per_version = [
        {"version": row.get("version"),
         "pipeline_id": row.get("pipeline_id"),
         "experiments": int(counts.get(row.get("pipeline_id"), 0)),
         "running": int(running.get(row.get("pipeline_id"), 0)),
         "active": bool(row.get("active"))}
        for row in versions
    ]
    return {
        "name": name,
        "pipeline_id": current.get("pipeline_id"),
        "version": current.get("version"),
        "dataset_type": current.get("dataset_type") or "",
        "algorithm": current.get("algorithm") or "",
        "paper": current.get("paper") or "",
        "entry_class": current.get("entry_class") or "",
        "entry_file": current.get("entry_file") or "",
        "file_hash": current.get("file_hash") or "",
        "registered_by": current.get("registered_by") or "",
        "registered_at": (current.get("registered_at") or "")[:19],
        "edited_by": current.get("edited_by") or "",
        "edited_at": (current.get("edited_at") or "")[:19],
        "change_note": current.get("change_note") or "",
        "is_active": bool(current.get("active")),
        # Dari pengajuan yang mana ia lahir — riwayat hidupnya dapat ditelusuri
        # balik tanpa menebak dari nama.
        "submission_id": current.get("submission_id"),
        # Aktif BELUM berarti dapat dijalankan: datasetnya harus ada.
        "runnable": runnable,
        "state": state,
        "state_reason": reason,
        "versions": per_version,
        "experiments": sum(v["experiments"] for v in per_version),
        "running": sum(v["running"] for v in per_version),
        "version_count": len(versions),
    }
