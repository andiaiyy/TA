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

from database.models import SUBMISSION_PENDING
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

#: Penanda dipakai hanya oleh verdict yang MENUNTUT perhatian. Lolos-bersih
#: tidak: lencana hijau dan kalimat "lolos tanpa catatan" sudah
#: mengatakannya, dan ceklis di depannya hanya mengulang keduanya.
VERDICT_MARK = {VERDICT_CLEAN: "", VERDICT_WARN: "⚠",
                VERDICT_PROBLEM: "✖"}

#: Hasil periksa → KEADAAN yang dipakai mewarnai selnya. Dipetakan, bukan
#: dipakai apa adanya: nilai `verdict` adalah pengenal milik modul ini, dan
#: penyaji tabel tidak boleh mengunci diri pada ejaannya.
VERDICT_STATE = {VERDICT_CLEAN: "ok", VERDICT_WARN: "warn",
                 VERDICT_PROBLEM: "bad"}


def verdict_state(row: dict) -> str:
    """Keadaan sebuah baris antrean: "ok", "warn", atau "bad".

    Hasil yang tidak dikenal menjadi "warn", bukan "ok": menganggap yang tak
    dikenal sebagai bersih adalah kesalahan yang menutupi masalah — aturan
    yang sama dengan `review_style.verdict_state` pada halaman detailnya.
    """
    return VERDICT_STATE.get((row or {}).get("verdict"), "warn")


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

# Catatan "pemeriksaan statis" pernah ada DUA — satu di sini, satu di
# ``manage_pipelines`` — dan keduanya tampil berurutan pada halaman yang sama,
# mengatakan hal yang sama dengan kalimat berbeda. Keduanya kini DIBUANG:
# kalimat itu berdiri di kepala halaman, terbaca sebelum pembacanya tahu ia
# sedang melihat apa. Yang bertahan adalah keterangan di bawah ini — ia
# menempel pada TOMBOLNYA, jadi terbaca tepat saat keputusannya diambil.
#: Akibat menyetujui, dinyatakan SEBELUM tombolnya ditekan. Satu baris.
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


def declared_algorithms(item: dict) -> list[dict]:
    """Potret STATIS tiap titik masuk: ``[{filename, class_name, algorithm}]``.

    Ditulis jalur unggah dan diperbarui jalur revisi dengan membaca AST paket.
    Bentuk lama yang hanya punya `entry_class` menghasilkan daftar kosong —
    pembacanya sudah punya cadangan untuk itu.
    """
    daftar = _meta(item).get("algorithms")
    return [a for a in daftar if isinstance(a, dict)] if isinstance(daftar, list) else []


def _from_snapshot(item: dict, key: str) -> str:
    """Nilai ``key`` menurut KODE paket, digabung bila titik masuknya banyak.

    Dipakai sebagai CADANGAN saat isian kontributor kosong. Satu paket boleh
    membawa beberapa algoritma, dan menyebut yang pertama saja akan
    menyembunyikan sisanya dari peninjau.
    """
    nilai = []
    for a in declared_algorithms(item):
        satu = str(a.get(key) or "").strip()
        if satu and satu not in nilai:
            nilai.append(satu)
    return ", ".join(nilai)


def metadata_rows(item: dict) -> list[tuple[str, str]]:
    """Identitas & metadata sebagai pasangan label–nilai ringkas.

    Pasangan yang kosong dibuang oleh penyajinya, jadi tidak ada baris "—" yang
    hanya memenuhi ruang.

    **Isian kontributor menang; potret kode menjadi cadangan.** Algoritma dan
    paper adalah kolom formulir yang boleh dikosongkan, sementara kodenya
    sendiri sudah menyatakannya lewat `get_info()` dan potretnya SUDAH
    tersimpan. Menampilkan "(kosong)" untuk sesuatu yang platform ketahui
    membuat peninjau mengira paketnya tidak menyebutkan apa-apa.

    Nilai yang berasal dari potret DITANDAI, bukan disamarkan seolah diketik
    pengaju — keduanya sumber yang berbeda dan peninjau berhak tahu yang mana.
    """
    from ui.i18n import t

    meta = _meta(item)

    def dengan_cadangan(diisi: str, key: str) -> str:
        if str(diisi or "").strip():
            return diisi
        potret = _from_snapshot(item, key)
        return t("sr.from_code", value=potret) if potret else ""

    return [
        ("Nama pipeline", meta.get("name") or ""),
        ("Dataset target", meta.get("dataset_type") or ""),
        ("Algoritma", dengan_cadangan(meta.get("algorithm"), "algorithm")),
        ("Kelas titik masuk", meta.get("entry_class")
         or _from_snapshot(item, "class_name")),
        ("Paper / rujukan", dengan_cadangan(meta.get("paper"), "paper")),
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


def check_tally(entry: dict) -> dict:
    """Hitungan pemeriksaan satu berkas: total, lolos, peringatan, gagal.

    Dipakai menggantikan daftar bulir yang mencetak SETIAP pemeriksaan —
    termasuk yang lolos. Terukur enam bulir per berkas, lima di antaranya
    mengatakan "tidak ada yang salah", dan sepuluh berkas berarti lima puluh
    baris yang tidak menolong siapa pun.

    Jumlahnya tetap DISEBUT, bukan sekadar dihilangkan: peninjau harus tahu
    pemeriksaannya benar-benar berjalan dan berapa banyak. Yang dibuang hanya
    perinciannya.

    Fungsi MURNI.
    """
    checks = (entry or {}).get("report") or {}
    checks = checks.get("checks") or []
    return {
        "total": len(checks),
        "passed": sum(1 for c in checks if c.get("status") not in (WARN, FAIL)),
        "warned": sum(1 for c in checks if c.get("status") == WARN),
        "failed": sum(1 for c in checks if c.get("status") == FAIL),
    }


def notable_checks(entry: dict) -> list[dict]:
    """Pemeriksaan yang TIDAK lolos — gagal lebih dulu, lalu peringatan.

    Inilah yang benar-benar dicari peninjau. Urutannya disengaja: kegagalan
    menentukan boleh-tidaknya disetujui, peringatan hanya perlu dibaca.
    """
    checks = ((entry or {}).get("report") or {}).get("checks") or []
    return ([c for c in checks if c.get("status") == FAIL]
            + [c for c in checks if c.get("status") == WARN])


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
    return f"{VERDICT_MARK[verdict]} {label}".strip()


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


# ── Riwayat peninjauan ────────────────────────────────────────────────────
# Dulu daftar markdown datar yang hanya menyebut id, berkas, jenis, status,
# peninjau, dan catatan. Tiga hal yang SUDAH tersimpan tidak pernah tampil,
# padahal justru itu yang dicari saat membaca riwayat: KAPAN diputuskan, SIAPA
# yang mengajukan, dan bagaimana HASIL UJI COBANYA.

#: Status pengajuan adalah PENGENAL di basis data; hanya labelnya dipetakan.
#: Kuncinya sudah ada — dipakai bersama `render_submission_counts`.
STATUS_LABEL_KEYS = {
    SUBMISSION_PENDING: "ap.sub_pending",
    "approved": "ap.sub_approved",
    "rejected": "ap.sub_rejected",
}


def status_label(status: str) -> str:
    """Label status pengajuan pada bahasa aktif.

    Tinggal di sini, bukan di penyajinya: dua halaman memakainya sekarang —
    "Pengajuan saya" pada alur kontributor dan riwayat tinjauan pada tab
    Riwayat versi — dan dua salinan akan berarti dua peta status yang dapat
    berbeda pendapat.
    """
    from ui.i18n import t

    key = STATUS_LABEL_KEYS.get(status)
    return t(key) if key else status


HISTORY_COLUMNS = (
    tbl.column("Pengajuan", "name", kind=tbl.KIND_NAME,
               label_key="rv.col_submission"),
    tbl.column("Keputusan", "decision", kind=tbl.KIND_STATUS,
               label_key="sr.col_decision"),
    tbl.column("Uji coba", "trial", kind=tbl.KIND_STATUS,
               label_key="trial.col_outcome"),
    tbl.column("Diajukan oleh", "submitted_by", kind=tbl.KIND_NAME,
               label_key="rv.col_submitted_by"),
    tbl.column("Ditinjau", "reviewed_at", kind=tbl.KIND_TIME,
               label_key="sr.col_reviewed_at"),
    tbl.column("Oleh", "reviewed_by", kind=tbl.KIND_NAME,
               label_key="sr.col_reviewed_by"),
    tbl.column("Catatan", "note", kind=tbl.KIND_TEXT,
               label_key="sr.col_note", title_key="note_full"),
)

#: Panjang catatan pada sel tabel. Teks penuhnya tetap ada di tooltip lewat
#: `title_key`, jadi tidak ada yang hilang — hanya tidak melebarkan barisnya.
NOTE_PREVIEW = 60


def trial_outcome(item: dict) -> str:
    """Hasil uji coba sebuah pengajuan, dari jejak yang tersimpan.

    Diambil dari ``trial_json`` — jejak RINGKAS yang memang dimaksudkan
    bertahan setelah keputusan diambil. Pengajuan yang tidak pernah diuji
    menghasilkan "—", dan itu fakta, bukan data yang hilang.
    """
    import json as _json

    raw = (item or {}).get("trial_json")
    if not raw:
        return "-"
    try:
        trail = _json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return "-"
    if not isinstance(trail, dict):
        return "-"

    status = str(trail.get("status") or "").upper()
    if status == "PASSED":
        rows = trail.get("rows_used")
        secs = trail.get("duration_s")
        detail = ", ".join(str(x) for x in (
            f"{rows} baris" if rows else "",
            f"{secs}s" if secs else "") if x)
        return f"✔ lolos ({detail})" if detail else "✔ lolos"
    if status == "FAILED":
        stage = trail.get("error_stage") or ""
        return f"✖ gagal · {stage}" if stage else "✖ gagal"
    return status.lower() or "-"


def history_rows(items, *, status_label) -> list[dict]:
    """Baris riwayat peninjauan. ``status_label`` menerjemahkan statusnya.

    Fungsi MURNI: seluruh isinya berasal dari baris pengajuan yang sudah
    dibaca, jadi menampilkan riwayat tidak membuka berkas apa pun.
    """
    out = []
    for item in items or []:
        note = str(item.get("review_note") or "").strip()
        meta = _meta(item)
        out.append({
            "id": item.get("id"),
            "name": meta.get("name") or item.get("original_filename") or "",
            "decision": status_label(item.get("status")),
            "trial": trial_outcome(item),
            "submitted_by": item.get("submitted_by") or "-",
            "reviewed_at": (item.get("reviewed_at") or "")[:19] or "-",
            "reviewed_by": item.get("reviewed_by") or "-",
            "note": (note[:NOTE_PREVIEW - 1] + "…"
                     if len(note) > NOTE_PREVIEW else note) or "-",
            "note_full": note,
        })
    return out


# ── Berkas satu paket ─────────────────────────────────────────────────────

def package_archive(sources: list[tuple[str, str]]) -> bytes:
    """Isi arsip zip sebuah paket — fungsi MURNI, tanpa menyentuh disk.

    Dipisahkan dari penyajinya supaya isinya dapat diperiksa langsung: apa
    yang masuk ke arsip adalah hal yang harus benar, dan itu tidak boleh
    hanya teruji lewat tombol unduh yang isinya tidak terbaca AppTest.

    Disusun DI MEMORI dengan `zipfile` bawaan — tidak ada berkas perantara di
    disk dan tidak ada dependensi baru.
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as arsip:
        for nama, teks in sources or []:
            arsip.writestr(nama, teks)
    return buf.getvalue()


#: Asal sebuah berkas relatif terhadap kiriman kontributor.
ORIGIN_SUBMITTED = "kiriman"
ORIGIN_CHANGED = "diubah peninjau"
ORIGIN_ADDED = "ditambah peninjau"

ORIGIN_KEYS = {
    ORIGIN_SUBMITTED: "sr.origin_submitted",
    ORIGIN_CHANGED: "sr.origin_changed",
    ORIGIN_ADDED: "sr.origin_added",
}


def file_origin(item: dict, filename: str, digest: str) -> str:
    """Dari mana berkas ini berasal: kiriman kontributor, atau sentuhan peninjau.

    Dihitung dengan MEMBANDINGKAN sha256-nya terhadap daftar berkas kiriman
    asli yang tersimpan di `revision_json`. Itulah yang menjawab pertanyaan
    yang benar-benar dicari peninjau berikutnya — *apa yang diubah rekan saya* —
    dan bukan sekadar "paket ini pernah direvisi", yang setelah satu revisi
    berlaku sama untuk setiap berkas dan karena itu tidak memberi tahu apa pun.

    Pengajuan yang belum pernah direvisi: seluruh berkasnya kiriman, dan
    kolomnya memang seragam — tetapi seragam karena faktanya begitu.
    """
    from orchestrator.submission_service import revision_of

    catatan = revision_of(item)
    if not catatan:
        return ORIGIN_SUBMITTED
    asli = {f.get("filename"): f.get("sha256")
            for f in catatan.get("original_files") or []}
    if filename not in asli:
        return ORIGIN_ADDED
    if digest and asli[filename] and digest != asli[filename]:
        return ORIGIN_CHANGED
    return ORIGIN_SUBMITTED


# ── Penempatan berkas: fase dan algoritma ────────────────────────────────
#
# MENERANGKAN, bukan menentukan. Yang dijalankan tetap kelas titik masuk lewat
# kontrak yang sudah ada; peta ini menjawab pertanyaan yang selama ini tidak
# terjawab di mana pun: berkas mana bekerja pada fase mana, untuk algoritma
# yang mana. Sebuah `common_prep.py` yang dipakai tiga algoritma sekaligus
# tidak punya satu tempat pun yang menyatakan kaitannya sebelum ini.

#: Fase baku, dipakai saat paket tidak menyatakan tahapan apa pun sendiri.
DEFAULT_PHASES = ("Preprocessing", "Feature Engineering", "Training",
                  "Evaluation")

#: Algoritma "semua", untuk berkas pendukung yang dipakai bersama. Bentuk
#: datanya milik lapis layanan, jadi pengenalnya dibaca dari sana alih-alih
#: diketik ulang di sini: dua ejaan untuk satu penanda adalah cara termudah
#: membuat peta tersimpan tidak cocok dengan peta yang digambar.
from orchestrator.submission_service import ALGO_ALL      # noqa: E402


def phase_options(item: dict) -> list[str]:
    """Fase yang boleh dipilih untuk paket ini, urut dan tanpa duplikat.

    Sumber pertamanya adalah apa yang KODE nyatakan: `stages` tiap titik masuk,
    dibaca statis saat diunggah atau direvisi. Daftar baku hanya melengkapi,
    sebab paket yang tidak memanggil `_emit_progress` tidak menyatakan tahapan
    apa pun, dan peninjau tetap perlu sesuatu untuk dipilih.
    """
    urut: list[str] = []
    for algo in declared_algorithms(item):
        for fase in algo.get("stages") or []:
            teks = str(fase).strip()
            if teks and teks not in urut:
                urut.append(teks)
    for fase in DEFAULT_PHASES:
        if fase not in urut:
            urut.append(fase)
    return urut


def algorithm_options(item: dict) -> list[str]:
    """Algoritma yang dideklarasikan paket, ditambah "semua algoritma".

    Nilainya nama KELAS, bukan nama algoritma yang ditulis di formulir: kelas
    itulah yang benar-benar dibaca dari kode dan yang menjadi pengenal baris
    registry nanti.
    """
    urut = [str(a.get("class_name") or "").strip()
            for a in declared_algorithms(item)]
    return [ALGO_ALL] + [n for i, n in enumerate(urut)
                         if n and n not in urut[:i]]


def placement_entry(value) -> dict:
    """Satu entri peta, dibersihkan: ``{"phases": [...], "algorithms": [...]}``."""
    value = value if isinstance(value, dict) else {}
    return {
        "phases": [str(p) for p in (value.get("phases") or []) if str(p).strip()],
        "algorithms": [str(a) for a in (value.get("algorithms") or [])
                       if str(a).strip()],
    }


def seeded_placement(item: dict) -> dict:
    """Peta penempatan SELURUH berkas paket, tersemai dari pembacaan kode.

    Aturannya dua, dan keduanya menahan diri:

    * **Yang tersimpan menang.** Semaian hanya mengisi berkas yang belum punya
      entri, sehingga pembetulan Research Admin tidak pernah tertimpa oleh
      pembacaan ulang kode.
    * **Yang tidak dinyatakan kode tidak dikarang.** Titik masuk disemai dari
      `stages` dan kelasnya sendiri; berkas pendukung disemai KOSONG, karena
      kodenya memang tidak mengatakan apa pun tentangnya. Menebak dari nama
      berkas akan menghasilkan peta yang tampak lengkap dan diam-diam salah.

    MURNI: tidak menyentuh basis data maupun disk.
    """
    tersimpan = (_meta(item).get("placement") or {})
    tersimpan = tersimpan if isinstance(tersimpan, dict) else {}
    semaian = {a.get("filename"): {
        "phases": [str(s) for s in (a.get("stages") or []) if str(s).strip()],
        "algorithms": [str(a.get("class_name") or "").strip()]
        if str(a.get("class_name") or "").strip() else [],
    } for a in declared_algorithms(item) if a.get("filename")}

    out: dict[str, dict] = {}
    for berkas in stored_files(item):
        nama = str(berkas.get("filename") or "")
        if not nama:
            continue
        if nama in tersimpan:
            out[nama] = placement_entry(tersimpan[nama])
        else:
            out[nama] = placement_entry(semaian.get(nama))
    return out


def is_placed(entry: dict) -> bool:
    """Sebuah berkas dianggap ditempatkan bila fase DAN algoritmanya terisi.

    Salah satu saja tidak cukup: "berkas ini bekerja pada Training" tanpa
    algoritma tidak menjawab pertanyaannya pada paket berbilang algoritma, dan
    sebaliknya juga begitu.
    """
    bersih = placement_entry(entry)
    return bool(bersih["phases"] and bersih["algorithms"])


def placement_gaps(item: dict) -> dict:
    """Berapa berkas yang belum ditempatkan, titik masuk dihitung terpisah.

    Keduanya tidak sama beratnya: titik masuk yang belum ditempatkan berarti
    algoritmanya sendiri tidak tergambar di mana pun, sementara berkas
    pendukung yang belum ditempatkan hanya kehilangan kaitannya.
    """
    peta = seeded_placement(item)
    titik = {a.get("filename") for a in declared_algorithms(item)}
    kurang = [n for n, e in peta.items() if not is_placed(e)]
    return {"entry": sorted(n for n in kurang if n in titik),
            "support": sorted(n for n in kurang if n not in titik),
            "total": len(kurang)}


#: Empat metrik yang dikotakkan pada hasil uji coba, dengan nama yang dipakai
#: halaman hasil. Urutannya tetap: peninjau yang sudah membaca "Hasil" di
#: Jalankan Eksperimen tidak perlu mencari-cari di tempat kedua.
TRIAL_METRIC_BOXES = (("accuracy", "Accuracy"), ("precision", "Precision"),
                      ("recall", "Recall"), ("f1_score", "F1-Score"))


def trial_metric_split(metrics: dict) -> tuple[list[tuple[str, float]],
                                               list[tuple[str, str]]]:
    """Metrik uji coba, dipisah: yang DIKOTAKKAN dan yang tidak.

    Uji coba hanya menyimpan empat angka pokok ditambah jumlah fitur dan daftar
    kelas; tidak ada confusion matrix maupun kurva di sana. Karena itu yang
    tidak tersimpan tidak ikut dikembalikan: sebuah kotak berisi ``0,0000``
    untuk angka yang tidak pernah ada adalah kebohongan yang rapi, dan peninjau
    memakai angka itu untuk memutuskan.

    MURNI, dan itu sebabnya pemisahannya tinggal di sini alih-alih di dalam
    fungsi yang menggambar: isi tiap kotak adalah hal yang harus benar, dan
    AppTest tidak dapat membaca isi sebuah `st.metric` dengan yakin.
    """
    nilai = metrics or {}
    dikenal = {kunci for kunci, _ in TRIAL_METRIC_BOXES}
    # `bool` adalah turunan `int`, jadi tanpa penyaring itu sebuah `True` akan
    # tergambar sebagai kotak berisi 1,0000.
    kotak = [(label, float(nilai[kunci]))
             for kunci, label in TRIAL_METRIC_BOXES
             if isinstance(nilai.get(kunci), (int, float))
             and not isinstance(nilai.get(kunci), bool)]
    sisa = [(nama, f"{v:.4f}" if isinstance(v, float) else str(v))
            for nama, v in nilai.items() if nama not in dikenal]
    return kotak, sisa


def my_submission_rows(items: list[dict], username: str) -> list[dict]:
    """Pengajuan MILIK satu orang, terbaru lebih dulu, siap ditampilkan.

    Selama ini kontributor tidak punya satu pun cara mengetahui nasib
    kirimannya: antrean peninjauan dijaga izin Research Admin dan tidak disaring
    pemilik, dan tidak ada pemberitahuan apa pun. Setelah menekan kirim, yang ia
    baca hanya "menunggu peninjauan", lalu senyap — termasuk ketika kirimannya
    DITOLAK beserta alasan yang wajib ditulis peninjau.

    Penyaringnya nama pengaju, dibandingkan apa adanya: kolom itu diisi
    platform dari identitas yang sedang masuk, bukan dari isian pengguna.

    MURNI: tidak menyentuh basis data maupun disk.
    """
    nama = str(username or "").strip()
    if not nama:
        return []
    milik = [i for i in (items or []) if str(i.get("submitted_by") or "") == nama]
    milik.sort(key=lambda i: str(i.get("submitted_at") or ""), reverse=True)
    return [{
        "id": i.get("id"),
        "kind": i.get("kind") or "",
        "name": (_meta(i).get("name") or i.get("original_filename") or ""),
        "status": i.get("status") or "",
        "submitted_at": str(i.get("submitted_at") or "")[:19],
        "reviewed_at": str(i.get("reviewed_at") or "")[:19],
        "reviewed_by": i.get("reviewed_by") or "",
        # Alasan penolakan adalah satu-satunya hal yang dapat ditindaklanjuti
        # pengaju, jadi ia dibawa apa adanya, tidak dipotong.
        "note": str(i.get("review_note") or "").strip(),
    } for i in milik]


def revision_rows(item: dict) -> list[dict]:
    """Tiap putaran revisi sebagai satu baris siap ditampilkan.

    Menjawab pertanyaan yang selama ini tidak terjawab di layar: *apa yang
    terjadi pada putaran 1, dan apa alasannya*. Sebelum riwayat disimpan, yang
    ada hanya putaran terakhir; putaran sebelumnya hilang beserta catatannya.

    MURNI — tidak menyentuh disk. Apakah berkas satu putaran masih dapat dibuka
    ditentukan pemanggilnya lewat ``submission_service.revision_sources``, sebab
    folder yang sudah dibersihkan adalah keadaan yang WAJAR setelah pengajuan
    diputuskan, bukan kesalahan yang perlu dilaporkan di sini.
    """
    from orchestrator.submission_service import revision_history

    baris = []
    for entri in revision_history(item):
        diubah = list(entri.get("changed") or [])
        ditambah = list(entri.get("added") or [])
        baris.append({
            "round": int(entri.get("round") or 0),
            "by": entri.get("by") or "",
            "at": entri.get("at") or "",
            "note": (entri.get("note") or "").strip(),
            "path": entri.get("path") or "",
            "changed": diubah,
            "added": ditambah,
            "kept": list(entri.get("kept") or []),
            # Jumlah berkas yang benar-benar disentuh putaran ini. Nol berarti
            # putaran itu tidak mengubah apa pun: mungkin pada data lama, dan
            # sejak sekarang ditolak sebelum sempat terbentuk.
            "touched": len(diubah) + len(ditambah),
            # Ada putaran sebelum ini yang catatannya memang tidak tersimpan.
            "partial": bool(entri.get("partial")),
        })
    return baris


def file_rows(item: dict, reviewed: dict) -> list[dict]:
    """Setiap berkas paket: nama, peran, ukuran, penjelasan, verdict, asal.

    Titik masuk didahulukan, lalu berkas pendukung urut nama — supaya peninjau
    membaca yang paling menentukan lebih dulu. SELURUH berkas ikut, bukan hanya
    titik masuknya.
    """
    tersimpan = {f.get("filename"): f for f in stored_files(item)}
    sizes = {nama: f.get("size") for nama, f in tersimpan.items()}
    notes = uploader_notes(item)
    peta = seeded_placement(item)

    rows: list[dict] = []
    for entry in (reviewed or {}).get("files") or []:
        name = entry.get("filename", "")
        digest = (tersimpan.get(name) or {}).get("sha256") or ""
        rows.append({
            "filename": name,
            "role": entry.get("role") or "",
            "size": sizes.get(name),
            "description": entry.get("description") or notes.get(name, ""),
            "ok": bool(entry.get("package_ok")),
            "origin": file_origin(item, name, digest),
            "placement": peta.get(name, {}),
            "entry": entry,
        })
    rows.sort(key=lambda r: (r["role"] != "entry point", r["filename"].lower()))
    return rows


#: Kolom tabel berkas paket. Nilainya SELURUHNYA dari :func:`file_rows` dan
#: :func:`check_tally` — tabel ini menyusun berdampingan apa yang sudah
#: dihitung, bukan menambah keterangan baru.
FILE_COLUMNS = (
    tbl.column("Berkas", "filename", kind=tbl.KIND_NAME,
               label_key="sr.col_file"),
    tbl.column("Peran", "role", kind=tbl.KIND_STATUS, label_key="sr.col_role"),
    tbl.column("Hasil periksa", "check_text", kind=tbl.KIND_STATUS,
               label_key="rv.col_check_result"),
    tbl.column("Ukuran", "size_text", kind=tbl.KIND_STATUS,
               label_key="sr.col_size"),
    # Menjawab "apa yang diubah peninjau", bukan "paket ini pernah direvisi".
    tbl.column("Asal", "origin_text", kind=tbl.KIND_STATUS,
               label_key="sr.col_origin"),
    # Dan "berkas ini bekerja di mana": fase, algoritma, atau penanda bahwa ia
    # memang belum ditempatkan.
    tbl.column("Penempatan", "placement_text", kind=tbl.KIND_STATUS,
               label_key="sr.col_placement"),
)


def file_state(row: dict) -> str:
    """Keadaan sebuah baris berkas: "ok", "warn", atau "bad".

    Aturan yang sama dengan hasil periksa paketnya: gagal mengalahkan
    peringatan, dan yang tidak dikenal TIDAK dianggap bersih.
    """
    tally = row.get("tally") or {}
    if tally.get("failed"):
        return "bad"
    if tally.get("warned"):
        return "warn"
    return "ok" if tally.get("total") else "warn"


def placement_text(entry: dict) -> str:
    """Penempatan satu berkas sebagai satu baris pendek untuk tabel.

    Kosong TIDAK dibiarkan kosong: sel yang kosong terbaca sebagai "tidak ada
    datanya", sedangkan yang benar adalah "berkas ini belum ditempatkan", dan
    itu keadaan yang memang harus terlihat.
    """
    from ui.i18n import t

    bersih = placement_entry(entry)
    if not is_placed(bersih):
        return t("sr.placement_unassigned")
    algo = [t("sr.placement_all_algorithms") if a == ALGO_ALL else a
            for a in bersih["algorithms"]]
    return " / ".join([", ".join(bersih["phases"]), ", ".join(algo)])


def file_table_rows(rows: list[dict], *, size_text) -> list[dict]:
    """Baris tabel berkas — dari baris yang SUDAH disusun `file_rows`.

    ``size_text`` menyuntikkan pemformat ukuran, sehingga lapis ini tetap
    murni dan tidak perlu tahu bagaimana byte ditulis untuk dibaca manusia.
    """
    from ui.i18n import t

    out = []
    for row in rows or []:
        tally = check_tally(row.get("entry") or {})
        if tally["failed"]:
            text = t("sr.checks_failed", total=tally["total"],
                     count=tally["failed"])
        elif tally["warned"]:
            text = t("sr.checks_warned", total=tally["total"],
                     count=tally["warned"])
        else:
            text = t("sr.checks_clean", total=tally["total"])
        asal = row.get("origin") or ORIGIN_SUBMITTED
        out.append({**row, "tally": tally, "check_text": text,
                    "size_text": size_text(row.get("size") or 0),
                    "placement_text": placement_text(row.get("placement")),
                    "origin_text": t(ORIGIN_KEYS.get(asal, ""))
                    if ORIGIN_KEYS.get(asal) else asal})
    return out


def finding_lines(entry: dict) -> list[int]:
    """Nomor baris temuan (WARN/FAIL) pada satu berkas, urut & unik."""
    seen: list[int] = []
    for check in (entry.get("report") or {}).get("checks") or []:
        line = check.get("line")
        if check.get("status") in (WARN, FAIL) and isinstance(line, int):
            if line not in seen:
                seen.append(line)
    return sorted(seen)


# ── Perbandingan isi berkas antar putaran revisi ─────────────────────────
#
# Yang dijawab di sini: BARIS MANA yang disunting pada satu putaran. Daftar
# nama berkas saja tidak menjawabnya, dan mencetak seluruh isi berkas membuat
# pembacanya membandingkan dengan mata.
#
# Pembandingnya `difflib` BAWAAN. Itu bukan kebetulan: pustaka diff pihak
# ketiga dilarang masuk proyek ini, dan larangan itu dijaga sebuah test atas
# seluruh kode beserta `requirements.txt`.

#: Kelas baris, sepadan dengan `.ids-diff-add/-del/-equal` di `theme`.
DIFF_EQUAL = "equal"
DIFF_ADD = "add"
DIFF_DEL = "del"

#: Berapa baris tak berubah yang tetap ditampilkan di sekitar tiap perubahan.
#: Tanpa batas ini sebuah berkas 300 baris dengan tiga baris disunting akan
#: menggambar 300 baris, dan yang berubah justru tenggelam.
DIFF_CONTEXT = 3


def _diff_row(kind: str, old: int | None, new: int | None, text: str) -> dict:
    return {"kind": kind, "old": old, "new": new, "text": text}


def diff_rows(before: str, after: str, *,
              context: int | None = DIFF_CONTEXT) -> list[dict]:
    """Perbedaan dua isi berkas, baris demi baris.

    Tiap baris membawa nomor barisnya di KEDUA sisi: yang dihapus hanya punya
    nomor lama, yang ditambahkan hanya punya nomor baru. Itulah yang membuat
    temuan validator (yang bernomor baris) masih dapat dicocokkan.

    ``context`` membatasi baris tak berubah di sekitar perubahan. Bentangan
    yang dilewati diganti SATU baris penanda berjenis ``equal`` dengan
    ``text`` kosong dan kunci ``skipped`` berisi jumlahnya, jadi pembacanya
    tidak pernah mengira berkasnya lebih pendek daripada aslinya. ``None``
    berarti tampilkan seluruhnya.
    """
    import difflib

    lama = (before or "").splitlines()
    baru = (after or "").splitlines()
    keluar: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, lama, baru, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                keluar.append(_diff_row(DIFF_EQUAL, i1 + k + 1, j1 + k + 1,
                                        lama[i1 + k]))
            continue
        # "replace" adalah hapus lalu tambah: dua sisi digambar berurutan,
        # bukan digabung menjadi satu baris yang menyembunyikan salah satunya.
        for k in range(i1, i2):
            keluar.append(_diff_row(DIFF_DEL, k + 1, None, lama[k]))
        for k in range(j1, j2):
            keluar.append(_diff_row(DIFF_ADD, None, k + 1, baru[k]))
    return _fold_equal(keluar, context)


def _fold_equal(rows: list[dict], context: int | None) -> list[dict]:
    """Lipat bentangan tak berubah yang panjang menjadi satu baris penanda."""
    if context is None:
        return rows
    ubah = [i for i, r in enumerate(rows) if r["kind"] != DIFF_EQUAL]
    if not ubah:
        # Tidak ada yang berubah sama sekali: tidak ada yang perlu dilihat,
        # dan menggambar seluruh berkas di sini menyesatkan.
        return []
    simpan = set()
    for i in ubah:
        simpan.update(range(max(0, i - context), min(len(rows), i + context + 1)))

    keluar: list[dict] = []
    lewat = 0
    for i, baris in enumerate(rows):
        if i in simpan:
            if lewat:
                keluar.append({"kind": DIFF_EQUAL, "old": None, "new": None,
                               "text": "", "skipped": lewat})
                lewat = 0
            keluar.append(baris)
        else:
            lewat += 1
    if lewat:
        keluar.append({"kind": DIFF_EQUAL, "old": None, "new": None,
                       "text": "", "skipped": lewat})
    return keluar


def diff_counts(rows: list[dict]) -> dict:
    """Berapa baris ditambah dan berapa dihapus."""
    return {"added": sum(1 for r in rows if r["kind"] == DIFF_ADD),
            "removed": sum(1 for r in rows if r["kind"] == DIFF_DEL)}


#: Penanda tekstual tiap jenis baris. Inilah yang menggantikan warna ketika
#: warnanya hilang: buta warna, kontras tinggi, atau cetak hitam-putih.
_DIFF_MARK = {DIFF_ADD: "+", DIFF_DEL: "-", DIFF_EQUAL: " "}


def diff_html(rows: list[dict], *, head_old: str = "", head_new: str = "",
              skipped_text: str = "{count}") -> str:
    """Markup tabel perbandingan, memakai kelas `.ids-diff` yang sudah ada."""
    from html import escape

    if not rows:
        return ""
    keluar = ['<div class="ids-diff-scroll"><table class="ids-diff">',
              "<thead><tr>",
              f'<th class="ids-diff-n">{escape(head_old)}</th>',
              f'<th class="ids-diff-n">{escape(head_new)}</th>',
              '<th class="ids-diff-m"></th><th></th>',
              "</tr></thead><tbody>"]
    for baris in rows:
        kelas = "ids-diff-" + baris["kind"]
        if baris.get("skipped"):
            teks = skipped_text.format(count=baris["skipped"])
            keluar.append(
                f'<tr class="{kelas}"><td class="ids-diff-n"></td>'
                f'<td class="ids-diff-n"></td><td class="ids-diff-m"></td>'
                f'<td class="ids-diff-t">{escape(teks)}</td></tr>')
            continue
        lama = "" if baris["old"] is None else str(baris["old"])
        baru = "" if baris["new"] is None else str(baris["new"])
        keluar.append(
            f'<tr class="{kelas}">'
            f'<td class="ids-diff-n">{lama}</td>'
            f'<td class="ids-diff-n">{baru}</td>'
            f'<td class="ids-diff-m">{_DIFF_MARK[baris["kind"]]}</td>'
            f'<td class="ids-diff-t">{escape(baris["text"])}</td></tr>')
    keluar.append("</tbody></table></div>")
    return "".join(keluar)


# ── Riwayat uji coba satu pengajuan ──────────────────────────────────────

#: Hasil uji → KEADAAN pewarnaan, dipetakan seperti `VERDICT_STATE`. Status
#: yang tidak dikenal menjadi "warn", bukan "ok": menganggap yang tak dikenal
#: sebagai lolos adalah kesalahan yang menutupi masalah.
TRIAL_STATE = {"PASSED": "ok", "FAILED": "bad",
               "RUNNING": "warn", "QUEUED": "warn"}


def trial_table_rows(trials) -> list[dict]:
    """Tiap uji coba sebagai satu baris siap ditampilkan, terbaru lebih dulu.

    Layar dahulu hanya menggambar uji TERAKHIR, padahal setiap uji tersimpan.
    Yang hilang justru yang paling berarti bagi peninjau: sebuah paket yang
    lolos pada percobaan keempat setelah tiga kali gagal terbaca persis sama
    dengan paket yang lolos sekali jalan.

    MURNI: tidak menyentuh basis data. Pemanggilnya yang membaca `list_trials`.
    """
    keluar = []
    for trial in trials or []:
        status = str(trial.get("status") or "")
        keluar.append({
            "id": trial.get("id"),
            "status": status,
            "state": TRIAL_STATE.get(status, "warn"),
            "passed": status == "PASSED",
            "by": str(trial.get("started_by") or ""),
            "at": str(trial.get("started_at") or "")[:19],
            "dataset": str(trial.get("dataset_type") or ""),
            "rows_used": trial.get("rows_used"),
            "duration_s": trial.get("duration_s"),
            "error_stage": str(trial.get("error_stage") or ""),
            "error_kind": str(trial.get("error_kind") or ""),
            "error_message": str(trial.get("error_message") or ""),
            "metrics": trial.get("metrics") or {},
            "trial": trial,
        })
    return keluar


def trial_row_by_id(rows, trial_id) -> dict | None:
    """Satu baris menurut pengenalnya; ``None`` bila sudah tidak ada.

    Uji coba dapat disapu petugas kebersihan sementara modalnya terbuka, jadi
    pemanggilnya HARUS menyiapkan kemungkinan barisnya hilang.
    """
    for row in rows or []:
        if row.get("id") == trial_id:
            return row
    return None
