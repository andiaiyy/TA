"""
Bahan peninjauan satu pengajuan pipeline — lapis MURNI.

Titik ini adalah gerbang terakhir sebelum kode asing dijalankan platform, jadi
peninjau harus bisa memutuskan dengan yakin. Modul ini menyiapkan bahannya:
ringkasan untuk daftar, pasangan label–nilai untuk identitas, dan rincian per
berkas — semuanya dari data yang MEMANG SUDAH TERSIMPAN pada pengajuan.

**Tidak ada data baru yang diperkenalkan.** Yang berubah hanya penyajiannya:
sebelumnya metadata dan hasil validasi dibuang mentah-mentah sebagai blob
``st.json``; sekarang isinya dibaca dan disusun.

Sumbernya tiga, semuanya sudah ada sejak pengajuan dibuat:

* kolom baris pengajuan — ``submitted_by``, ``submitted_at``, ``file_hash``,
  ``file_size``, ``original_filename``;
* ``metadata_json`` — isian formulir pengunggah (nama, dataset target,
  algoritma, paper, catatan), ``entry_class``, ``entry_filename``, dan daftar
  berkas beserta ukuran & sha256 masing-masing;
* ``validation_json`` — hasil validasi saat diajukan, termasuk **penjelasan per
  berkas dari pengunggah** dan peran tiap berkas.

**Rincian pemeriksaan dihitung ulang dari TEKS yang tersimpan** lewat
``review_package`` — mekanisme yang sama persis dengan yang dipakai jalur
unggah, tanpa satu pun aturan validator diubah. Itu perlu karena nomor baris
temuan tidak ikut disimpan saat pengajuan dibuat, dan peninjau butuh nomor baris
untuk menghubungkan temuan dengan kodenya.

**Statis, selalu.** Tidak ada jalur di modul ini yang meng-import, mengevaluasi,
atau menjalankan kode pengajuan. Sumbernya dibaca sebagai teks dan diurai
menjadi pohon sintaks; itu saja.
"""
from __future__ import annotations

import logging

from orchestrator.pipeline_validator import FAIL, WARN
from ui.components import tables as tbl

logger = logging.getLogger(__name__)

# ── Verdict satu pengajuan ────────────────────────────────────────────────
# Lolos-bersih dan lolos-dengan-peringatan SAMA-SAMA dapat disetujui —
# peringatan bukan penghalang. Tetapi keduanya harus dapat dibedakan sekilas,
# karena peringatan itulah yang paling sering luput saat meninjau terburu-buru.

VERDICT_CLEAN = "bersih"
VERDICT_WARN = "peringatan"
VERDICT_PROBLEM = "bermasalah"

VERDICT_MARK = {VERDICT_CLEAN: "✔", VERDICT_WARN: "⚠", VERDICT_PROBLEM: "✖"}
VERDICT_LABEL = {
    VERDICT_CLEAN: "lolos tanpa catatan",
    VERDICT_WARN: "lolos dengan peringatan",
    VERDICT_PROBLEM: "ada masalah",
}
#: Putusan → kunci katalog. Putusannya sendiri PENGENAL, tidak berbahasa.
VERDICT_LABEL_KEYS = {
    VERDICT_CLEAN: "sr.verdict_clean",
    VERDICT_WARN: "sr.verdict_warned",
    VERDICT_PROBLEM: "sr.verdict_problem",
}


def verdict_label(verdict: str) -> str:
    """Kalimat putusan pada bahasa aktif."""
    from ui.i18n import t

    key = VERDICT_LABEL_KEYS.get(verdict)
    return t(key) if key else VERDICT_LABEL.get(verdict, verdict)

# Catatan "pemeriksaan statis" dulu ada DUA — satu di sini, satu di
# ``manage_pipelines`` — dan keduanya tampil berurutan pada halaman yang sama,
# mengatakan hal yang sama dengan kalimat berbeda. Yang bertahan adalah
# ``manage_pipelines.STATIC_CHECK_NOTE`` karena ia menyebut satu hal lebih
# banyak: berkasnya DIBACA, tidak dijalankan.
#: Akibat menyetujui, dinyatakan SEBELUM tombolnya ditekan. Satu baris.
#: Kunci katalog untuk kedua keterangan; konstanta tetap acuan.
APPROVAL_CONSEQUENCE_KEY = "sr.approve_consequence"
WARNING_REMINDER_KEY = "sr.warning_note"

APPROVAL_CONSEQUENCE = (
    "Menyetujui membuat versi 1 beserta hash-nya dan pipeline **langsung dapat "
    "dijalankan** pengguna."
)
#: Pengingat saat ada peringatan (bukan kegagalan). Satu baris.
WARNING_REMINDER = (
    "Ada peringatan: belum tentu masalah, tetapi sebaiknya dibaca sebelum "
    "menyetujui."
)
#: Keadaan kosong.
EMPTY_STATE = "Tidak ada pengajuan pipeline yang menunggu tinjauan."
#: Kunci katalog untuk kalimat yang sama; konstanta di atas tetap acuan.
EMPTY_STATE_KEY = "sr.empty_state"


# ── Pembacaan data tersimpan ──────────────────────────────────────────────

def _meta(item: dict) -> dict:
    value = (item or {}).get("metadata")
    return value if isinstance(value, dict) else {}


def _validation(item: dict) -> dict:
    value = (item or {}).get("validation")
    return value if isinstance(value, dict) else {}


def entry_filename(item: dict) -> str:
    """Nama berkas titik masuk, dari metadata pengajuan."""
    return str(_meta(item).get("entry_filename")
               or (item or {}).get("original_filename") or "")


def stored_files(item: dict) -> list[dict]:
    """[{filename, sha256, size}] — daftar berkas yang BENAR-BENAR disimpan.

    Pengajuan pipeline adalah satu PAKET: satu titik masuk plus berkas
    pendukung. Daftar ini yang membuktikan berapa berkas ada di dalamnya.
    """
    files = _meta(item).get("files")
    return [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []


def uploader_notes(item: dict) -> dict[str, str]:
    """{nama berkas: penjelasan pengunggah}.

    Pengaju sudah mengisi penjelasan per berkas saat mengunggah; inilah konteks
    yang paling membantu peninjau, dan sebelumnya tidak pernah ditampilkan
    selain sebagai bagian blob JSON.
    """
    out: dict[str, str] = {}
    for entry in _validation(item).get("files") or []:
        if isinstance(entry, dict) and entry.get("filename"):
            out[str(entry["filename"])] = str(entry.get("description") or "").strip()
    return out


def metadata_rows(item: dict) -> list[tuple[str, str]]:
    """Identitas & metadata sebagai pasangan label–nilai ringkas.

    Pasangan yang kosong dibuang oleh penyajinya, jadi tidak ada baris "—" yang
    hanya memenuhi ruang.
    """
    meta = _meta(item)
    return [
        ("Nama pipeline", meta.get("name") or ""),
        ("Dataset target", meta.get("dataset_type") or ""),
        ("Algoritma", meta.get("algorithm") or ""),
        ("Kelas titik masuk", meta.get("entry_class") or ""),
        ("Paper / rujukan", meta.get("paper") or ""),
        ("Catatan pengaju", meta.get("notes") or ""),
        ("Diajukan oleh", (item or {}).get("submitted_by") or ""),
        ("Waktu", ((item or {}).get("submitted_at") or "")[:19]),
        ("SHA-256 titik masuk", ((item or {}).get("file_hash") or "")[:16] + "…"
         if (item or {}).get("file_hash") else ""),
    ]


# ── Pemeriksaan ulang, STATIS ─────────────────────────────────────────────

def review_stored_package(item: dict, *, source_reader=None) -> dict:
    """Jalankan ulang pemeriksaan statis atas berkas yang TERSIMPAN.

    Memakai ``review_package`` — mekanisme yang sama persis dengan jalur
    unggah, tanpa satu pun aturan validator diubah. Yang diperiksa adalah teks
    yang ada di disk saat ini, sehingga nomor baris temuan cocok dengan kode
    yang sedang dibaca peninjau.

    Penjelasan per berkas dari pengunggah ikut disuntikkan supaya tetap melekat
    pada berkasnya masing-masing.

    ``source_reader`` disuntikkan saat menguji; secara bawaan ia membaca berkas
    pengajuan sebagai TEKS lewat ``read_submission_sources``.
    """
    if source_reader is None:
        from orchestrator.submission_service import read_submission_sources
        source_reader = read_submission_sources

    try:
        sources = source_reader(item) or []
    except Exception:                       # pragma: no cover - defensif
        logger.warning("Sumber pengajuan tidak terbaca", exc_info=True)
        sources = []
    if not sources:
        return {"valid": False, "files": [], "entry_points": [],
                "n_problem_files": 0, "cause": "Berkas pengajuan tidak terbaca.",
                "summary": "Tidak dapat diperiksa."}

    from ui.components.pipeline_upload import review_package

    payload = [(name, text.encode("utf-8")) for name, text in sources]
    return review_package(payload, descriptions=uploader_notes(item))


def warning_checks(reviewed: dict) -> list[dict]:
    """Seluruh pemeriksaan berstatus WARN pada sebuah paket."""
    out: list[dict] = []
    for entry in (reviewed or {}).get("files") or []:
        for check in (entry.get("report") or {}).get("checks") or []:
            if check.get("status") == WARN:
                out.append({**check, "filename": entry.get("filename", "")})
    return out


def verdict_of(reviewed: dict) -> str:
    """`bersih` | `peringatan` | `bermasalah` untuk satu paket."""
    if not (reviewed or {}).get("valid"):
        return VERDICT_PROBLEM
    return VERDICT_WARN if warning_checks(reviewed) else VERDICT_CLEAN


def verdict_text(reviewed: dict) -> str:
    """Penanda + label verdict, siap ditempel di baris daftar."""
    verdict = verdict_of(reviewed)
    label = verdict_label(verdict)
    if verdict == VERDICT_WARN:
        label += f" ({len(warning_checks(reviewed))})"
    elif verdict == VERDICT_PROBLEM:
        count = (reviewed or {}).get("n_problem_files") or 0
        if count:
            label += f" ({count} berkas)"
    return f"{VERDICT_MARK[verdict]} {label}"


# ── Daftar pengajuan ──────────────────────────────────────────────────────

def sort_pending(items) -> list[dict]:
    """TERLAMA MENUNGGU LEBIH DULU.

    Antrean tinjauan bukan tumpukan: yang paling lama menunggu paling berhak
    ditinjau duluan, dan urutan itu tidak boleh berubah-ubah antar rerun.
    """
    return sorted(items or [],
                  key=lambda s: (str(s.get("submitted_at") or ""), s.get("id") or 0))


def summary_row(item: dict, reviewed: dict) -> dict:
    """Satu baris daftar: apa yang dibutuhkan untuk memilih apa yang dibuka."""
    meta = _meta(item)
    files = stored_files(item)
    return {
        "id": item.get("id"),
        "name": meta.get("name") or item.get("original_filename") or "",
        "submitted_by": item.get("submitted_by") or "",
        "submitted_at": (item.get("submitted_at") or "")[:19],
        "file_count": len(files) or len((reviewed or {}).get("files") or []),
        "verdict": verdict_of(reviewed),
        "verdict_text": verdict_text(reviewed),
    }


#: Kolom antrean tinjauan. Nilainya SELURUHNYA dari :func:`summary_row` —
#: tabel ini menyusun berdampingan apa yang sudah dihitung, bukan menambah
#: informasi baru.
PENDING_COLUMNS = (
    tbl.column("Pengajuan", "name", kind=tbl.KIND_NAME,
               label_key="rv.col_submission"),
    tbl.column("Hasil periksa", "verdict_text", kind=tbl.KIND_STATUS,
               label_key="rv.col_check_result"),
    tbl.column("Berkas", "file_count", kind=tbl.KIND_NUM,
               label_key="rv.col_file"),
    tbl.column("Diajukan oleh", "submitted_by", kind=tbl.KIND_NAME,
               label_key="rv.col_submitted_by"),
    tbl.column("Waktu", "submitted_at", kind=tbl.KIND_TIME,
               label_key="rv.col_when"),
)


# ── Menyaring, mengurutkan, memenggal — SEBELUM apa pun diperiksa ─────────
# Ketiganya bekerja pada kolom baris pengajuan APA ADANYA: nomor, nama, dan
# pengaju. Tidak satu pun membuka berkas paket.
#
# Urutan langkahnya yang penting: menyaring dan memenggal lebih dulu, baru
# memeriksa. Pemeriksaan statis membaca seluruh berkas sebuah paket, jadi
# memeriksa dulu lalu memenggal berarti membayar untuk pengajuan yang tidak
# jadi ditampilkan — biaya yang tumbuh mengikuti panjang antrean, bukan
# mengikuti apa yang benar-benar dilihat peninjau.

#: Banyak baris per halaman daftar. Dipilih supaya seluruh halaman muat dibaca
#: tanpa menggulir pada layar biasa, dan supaya pemeriksaan statis yang dibayar
#: satu render tetap terbatas pada angka ini — bukan pada panjang antrean.
PAGE_SIZE = 10

SORT_OLDEST = "oldest"
SORT_NEWEST = "newest"


def search_text(item: dict) -> str:
    """Teks yang dicari untuk satu pengajuan, huruf kecil.

    Isinya kolom yang MEMANG sudah ada di baris pengajuan — tidak ada berkas
    yang dibuka untuk menyusunnya.
    """
    meta = _meta(item)
    parts = [
        f"#{item.get('id')}",
        str(meta.get("name") or ""),
        str(item.get("original_filename") or ""),
        str(item.get("submitted_by") or ""),
    ]
    return " ".join(p for p in parts if p).lower()


def filter_pending(items, query: str) -> list[dict]:
    """Pengajuan yang cocok dengan ``query``. Kosong berarti semuanya.

    Pencocokannya sederhana dan tanpa kejutan: seluruh kata pada kueri harus
    muncul pada teks pencarian pengajuan itu.
    """
    words = (query or "").strip().lower().split()
    if not words:
        return list(items or [])
    out = []
    for item in items or []:
        haystack = search_text(item)
        if all(word in haystack for word in words):
            out.append(item)
    return out


def order_pending(items, sort: str = SORT_OLDEST) -> list[dict]:
    """Urutkan antrean. Bawaannya TERLAMA MENUNGGU LEBIH DULU.

    Bawaannya tidak berubah dari :func:`sort_pending` — antrean tinjauan bukan
    tumpukan. ``SORT_NEWEST`` hanya membalik urutannya, memakai kunci yang sama
    supaya keduanya tidak dapat berbeda cara memutus seri.
    """
    ordered = sort_pending(items)
    return list(reversed(ordered)) if sort == SORT_NEWEST else ordered


def page_count(total: int, size: int = PAGE_SIZE) -> int:
    """Banyak halaman untuk ``total`` baris; minimal 1 supaya selalu ada."""
    size = max(1, int(size or PAGE_SIZE))
    return max(1, -(-max(0, int(total)) // size))


def page_slice(items, page: int = 1, size: int = PAGE_SIZE) -> list[dict]:
    """Satu halaman dari daftar. Halaman di luar jangkauan dijepit, bukan
    menghasilkan daftar kosong — pengguna tidak boleh terdampar pada halaman
    yang tidak ada setelah antreannya menyusut."""
    items = list(items or [])
    size = max(1, int(size or PAGE_SIZE))
    last = page_count(len(items), size)
    page = min(max(1, int(page or 1)), last)
    start = (page - 1) * size
    return items[start:start + size]


def result_note(shown: int, total: int) -> tuple[int, int]:
    """(ditampilkan, seluruhnya) — supaya penyaring tidak menyembunyikan
    antrean tanpa disadari."""
    return int(shown), int(total)


def pending_table_rows(items, reviewer) -> list[dict]:
    """Baris antrean. ``reviewer`` mengembalikan hasil periksa satu pengajuan.

    Pemeriksaannya disuntikkan, bukan dipanggil di sini, supaya lapis ini tetap
    MURNI dan tetap memakai cache yang sama dengan kartunya — tidak ada berkas
    yang dibaca dua kali untuk satu render.
    """
    return [summary_row(item, reviewer(item)) for item in items or []]


def summary_line(row: dict) -> str:
    """Baris daftar sebagai satu teks — nama menonjol, sisanya konteks.

    Nama berkas, nama pengaju, dan waktunya berasal dari basis data dan
    ditampilkan apa adanya; hanya kerangka kalimatnya yang berbahasa.
    """
    from ui.i18n import t

    return t("sr.summary_line", name=row["name"],
             verdict=row["verdict_text"], files=row["file_count"],
             who=row["submitted_by"], when=row["submitted_at"])


# ── Berkas satu paket ─────────────────────────────────────────────────────

def file_rows(item: dict, reviewed: dict) -> list[dict]:
    """Setiap berkas paket: nama, peran, ukuran, penjelasan, verdict.

    Titik masuk didahulukan, lalu berkas pendukung urut nama — supaya peninjau
    membaca yang paling menentukan lebih dulu. SELURUH berkas ikut, bukan hanya
    titik masuknya.
    """
    sizes = {f.get("filename"): f.get("size") for f in stored_files(item)}
    notes = uploader_notes(item)

    rows: list[dict] = []
    for entry in (reviewed or {}).get("files") or []:
        name = entry.get("filename", "")
        rows.append({
            "filename": name,
            "role": entry.get("role") or "",
            "size": sizes.get(name),
            "description": entry.get("description") or notes.get(name, ""),
            "ok": bool(entry.get("package_ok")),
            "entry": entry,
        })
    rows.sort(key=lambda r: (r["role"] != "entry point", r["filename"].lower()))
    return rows


def numbered_source(text: str, *, start: int = 1) -> str:
    """Sumber dengan NOMOR BARIS, supaya temuan mudah dicocokkan.

    Nomornya rata kanan selebar nomor terbesar, jadi kolom kodenya tetap lurus.
    """
    lines = str(text or "").splitlines() or [""]
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{start + i:>{width}} | {line}"
                     for i, line in enumerate(lines))


def finding_lines(entry: dict) -> list[int]:
    """Nomor baris temuan (WARN/FAIL) pada satu berkas, urut & unik."""
    seen: list[int] = []
    for check in (entry.get("report") or {}).get("checks") or []:
        line = check.get("line")
        if check.get("status") in (WARN, FAIL) and isinstance(line, int):
            if line not in seen:
                seen.append(line)
    return sorted(seen)
