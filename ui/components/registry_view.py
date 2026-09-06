"""
Bahan tampilan "Aktif" & "Riwayat versi" — lapis MURNI.

Kedua bagian itulah tempat KETERTELUSURAN pipeline kontribusi terlihat. Kalau
seseorang bertanya *"eksperimen ini memakai kode yang mana persisnya"*,
jawabannya harus dapat ditemukan di sana: versi berapa, hash apa, disetujui
siapa, disunting siapa, dan kodenya masih dapat dibaca.

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

from ui.components import tables as tbl

logger = logging.getLogger(__name__)

# ── Keadaan satu versi ────────────────────────────────────────────────────

# PENGENAL keadaan — dipakai untuk perbandingan dan tersimpan pada baris
# tabel, jadi nilainya TIDAK berbahasa. Kalimatnya ada di katalog.
STATE_OK = "ok"
STATE_MISSING = "berkas hilang"
STATE_TAMPERED = "hash tidak cocok"

#: Pengenal keadaan → kunci kalimat panjang & kunci label pendek.
STATE_REASON_KEYS = {
    STATE_OK: "",
    STATE_MISSING: "rv.state_missing",
    STATE_TAMPERED: "rv.state_tampered",
}
STATE_SHORT_KEYS = {
    STATE_OK: "",
    STATE_MISSING: "rv.state_missing_short",
    STATE_TAMPERED: "rv.state_tampered_short",
}


def state_reason(state: str) -> str:
    """Alasan sebuah keadaan pada bahasa aktif; "" untuk keadaan baik."""
    from ui.i18n import t

    key = STATE_REASON_KEYS.get(state, "")
    return t(key) if key else ""


def state_short(state: str) -> str:
    """Label pendek keadaan pada bahasa aktif."""
    from ui.i18n import t

    key = STATE_SHORT_KEYS.get(state, "")
    return t(key) if key else state

STATE_MARK = {STATE_OK: "✔", STATE_MISSING: "✖", STATE_TAMPERED: "✖"}
STATE_REASON = {
    STATE_OK: "",
    STATE_MISSING: ("Berkas versi ini tidak ditemukan di disk — pipeline tidak "
                    "dapat dimuat dan eksperimen barunya akan gagal."),
    STATE_TAMPERED: ("SHA-256 berkas berbeda dari yang tercatat saat "
                     "pendaftaran — berkas berubah di luar platform. Pemuatan "
                     "ditolak demi menjaga ketertelusuran."),
}

#: Kunci katalog untuk keterangan yang sama. Konstanta di bawah tetap ada
#: sebagai rumusan acuan yang diuji test lama.
DEACTIVATE_CONSEQUENCE_KEY = "rv.deactivate_consequence"
RETENTION_NOTE_KEY = "rv.retention_note"
READ_ONLY_NOTE_KEY = "rv.read_only_note"
EXPERIMENT_LINK_NOTE_KEY = "rv.experiment_link_note"
EMPTY_STATE_KEY = "rv.empty_active"
HISTORY_EMPTY_KEY = "rv.empty_history"

#: Nonaktifkan: konsekuensinya, satu baris.
DEACTIVATE_CONSEQUENCE = (
    "Menonaktifkan hanya menutup pipeline ini dari pilihan eksperimen BARU — "
    "eksperimen yang sudah ada tidak terpengaruh, dan berkas serta catatan "
    "versinya tetap utuh."
)
# Tiga hal WAJIB tersampaikan di sekitar riwayat & perbandingan:
#   1. versi lama tetap tersimpan  -> ketertelusuran,
#   2. perbandingan bersifat baca-saja,
#   3. menyunting menghasilkan versi baru.
# Ketiganya kini muat dalam DUA baris pendek. Yang dibuang hanyalah kalimat
# yang menjelaskan apa yang sudah terlihat di tabel (kolom hash, kolom versi).

#: Riwayat: kenapa versi lama tetap ada. (1)
RETENTION_NOTE = "Versi lama tetap tersimpan — eksperimen terdahulu tetap tertelusur."
#: Riwayat & perbandingan: baca-saja, dan jalan majunya. (2) + (3)
READ_ONLY_NOTE = "Baca-saja. Menyunting membuat versi BARU, tidak menimpa."
#: Keterbatasan penelusuran ke daftar eksperimen.
EXPERIMENT_LINK_NOTE = "Saring di Progress & Status lewat kolom Pipeline."
EMPTY_STATE = "Belum ada pipeline kontribusi — daftar akan terisi setelah ada pengajuan yang disetujui."


# ── Hash ──────────────────────────────────────────────────────────────────

#: Panjang hash yang ditampilkan — SATU nilai, milik penyaji tabel, supaya
#: hash di tabel dan hash di luar tabel tidak pernah dipendekkan berbeda.
SHORT_HASH = tbl.HASH_CHARS


def short_hash(value) -> str:
    """Hash dipendekkan SERAGAM. Nilai penuh dibawa penyaji sebagai tooltip."""
    return tbl.short_hash(value)


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


def summary_facts(summary: dict) -> list[tuple[str, str]]:
    """Identitas lengkap sebagai pasangan label–nilai.

    Pasangan yang kosong dibuang penyajinya, jadi pipeline tanpa penyunting
    tidak menampilkan baris "—" yang hanya memenuhi ruang.
    """
    from ui.i18n import t

    # Hanya LABELNYA yang berbahasa; nilainya berasal dari basis data dan
    # ditampilkan apa adanya.
    rows = [
        (t("rv.lbl_identity"), summary.get("pipeline_id") or ""),
        (t("rv.lbl_active_version"),
         f"v{summary['version']}" if summary.get("version") else ""),
        (t("rv.lbl_dataset_type"), summary.get("dataset_type") or ""),
        (t("rv.lbl_algorithm"), summary.get("algorithm") or ""),
        (t("rv.lbl_entry_class"), summary.get("entry_class") or ""),
        (t("rv.lbl_paper"), summary.get("paper") or ""),
        (t("rv.lbl_approved"),
         f"{summary['registered_by']} · {summary['registered_at']}"
         if summary.get("registered_by") else ""),
    ]
    if summary.get("edited_by"):
        rows.append((t("rv.lbl_last_edited"),
                     f"{summary['edited_by']} · {summary['edited_at']}"))
    if summary.get("change_note"):
        rows.append((t("rv.lbl_change_note"), summary["change_note"]))
    return rows


def usage_text(summary: dict) -> str:
    """Pemakaian, dipecah PER VERSI — di situlah dampak penyuntingan terlihat."""
    from ui.i18n import t

    used = [v for v in summary.get("versions") or [] if v["experiments"]]
    if not used:
        return t("rv.usage_none")
    parts = ", ".join(f"v{v['version']}: {v['experiments']}" for v in used)
    return t("rv.usage_some", total=summary["experiments"], parts=parts)


def running_text(summary: dict) -> str:
    """Penanda pipeline yang SEDANG dipakai eksperimen berjalan; "" bila tidak."""
    from ui.i18n import t

    running = [v for v in summary.get("versions") or [] if v["running"]]
    if not running:
        return ""
    parts = ", ".join(f"v{v['version']}: {v['running']}" for v in running)
    return t("rv.running_text", count=summary["running"], parts=parts)


# ── Riwayat versi ─────────────────────────────────────────────────────────

HISTORY_HEADERS = ("Versi", "Hash", "Oleh", "Waktu", "Catatan", "Status",
                   "Eksperimen")


def history_rows(versions, counts: dict, *, hash_reader=None) -> list[dict]:
    """Baris riwayat, terbaru di atas — bukti ketertelusuran.

    Tiap baris membawa hash, siapa membuatnya, kapan, catatan perubahan,
    statusnya, dan berapa eksperimen memakai versi ITU.
    """
    from ui.i18n import t

    counts = counts or {}
    out: list[dict] = []
    for row in versions or []:
        state, reason = version_state(row, hash_reader=hash_reader)
        # Status baris DIHITUNG penyaji (bukan nilai basis data), jadi ia
        # ikut bahasa. Catatan perubahan di bawah tetap apa adanya.
        status = t("rv.status_version_active" if row.get("active")
                   else "rv.status_version_inactive")
        if state != STATE_OK:
            status = f"{status} · {state_short(state)}"
        out.append({
            "version": row.get("version"),
            "pipeline_id": row.get("pipeline_id"),
            "hash": row.get("file_hash") or "",
            "who": row.get("edited_by") or row.get("registered_by") or "",
            "when": (row.get("edited_at") or row.get("registered_at") or "")[:19],
            "note": row.get("change_note") or t("rv.note_initial_version"),
            "active": bool(row.get("active")),
            "status": status,
            "state": state,
            "state_reason": reason,
            "experiments": int(counts.get(row.get("pipeline_id"), 0)),
        })
    return out


#: Kolom ikhtisar pipeline kontribusi — dipakai di bagian "Aktif".
#: Seluruh nilainya SUDAH dihitung ``pipeline_summary``; tabel ini hanya
#: menampilkannya berdampingan, tidak menambah satu kalimat pun.
ACTIVE_COLUMNS = (
    tbl.column("Pipeline", "name", kind=tbl.KIND_NAME,
               label_key="rv.col_pipeline"),
    tbl.column("Versi", "version", kind=tbl.KIND_VERSION,
               label_key="rv.col_version"),
    tbl.column("Hash", "file_hash", kind=tbl.KIND_HASH,
               label_key="rv.col_hash"),
    tbl.column("Dataset", "dataset_type", kind=tbl.KIND_STATUS,
               label_key="rv.col_dataset"),
    tbl.column("Status", "status_text", kind=tbl.KIND_STATUS,
               title_key="state_reason", label_key="rv.col_status"),
    tbl.column("Versi tercatat", "version_count", kind=tbl.KIND_NUM,
               label_key="rv.col_version_count"),
    tbl.column("Eksperimen", "experiments", kind=tbl.KIND_NUM,
               label_key="rv.col_experiments"),
)


def active_table_rows(summaries) -> list[dict]:
    """Baris ikhtisar dari ringkasan yang SUDAH ada — tanpa kueri tambahan."""
    from ui.i18n import t

    rows = []
    for summary in summaries or []:
        status = t("rv.status_active" if summary["is_active"]
                   else "rv.status_inactive")
        if summary["state"] != STATE_OK:
            status = f"{status} · {state_short(summary['state'])}"
        # Aktif tetapi tanpa dataset: keadaan yang PALING membingungkan bila
        # tidak dikatakan — halaman ini bilang aktif, halaman Jalankan
        # Eksperimen bilang belum dapat dijalankan.
        elif summary["is_active"] and not summary.get("runnable", True):
            status = f"{status} · {t('rv.status_no_dataset')}"
        rows.append(dict(summary, status_text=status,
                         _highlight=summary["is_active"]))
    return rows


#: Kolom riwayat versi — jenisnya menentukan perataan, format, dan lebar.
HISTORY_COLUMNS = (
    # Versi aktif dibedakan dengan penanda TEKSTUAL "←", bukan hanya latar &
    # bobot — supaya tetap terbaca tanpa warna. Karena itu kolomnya memakai
    # nilai jadi (`version_label`), tetapi lebarnya tetap lebar kolom "versi"
    # yang sama dengan tabel lain.
    tbl.column("Versi", "version_label", width=tbl.COLUMN_WIDTH[tbl.KIND_VERSION],
               label_key="rv.col_version"),
    tbl.column("Hash", "hash", kind=tbl.KIND_HASH, label_key="rv.col_hash"),
    tbl.column("Oleh", "who", kind=tbl.KIND_NAME, label_key="rv.col_by"),
    tbl.column("Waktu", "when", kind=tbl.KIND_TIME, label_key="rv.col_when"),
    tbl.column("Catatan", "note", label_key="rv.col_note"),
    tbl.column("Status", "status", kind=tbl.KIND_STATUS,
               title_key="state_reason", label_key="rv.col_status"),
    tbl.column("Eksperimen", "experiments", kind=tbl.KIND_NUM,
               label_key="rv.col_experiments"),
)

HISTORY_EMPTY = "Belum ada versi tercatat untuk pipeline ini."


def history_table_html(rows) -> str:
    """Tabel riwayat, lewat penyaji tabel BERSAMA.

    Dulu fungsi ini menyusun ``<td>``-nya sendiri dengan kelas ``ids-cmp``.
    Aturan kelas itu hanya disuntikkan di dalam dialog perbandingan pada
    halaman Progress & Status, jadi di halaman Add Pipeline & Dataset tabel ini
    tampil TANPA GAYA sama sekali — tanpa padding, garis pemisah, header yang
    dibedakan, maupun perataan angka. Memakai penyaji bersama menutup celah itu
    sekaligus menyamakan lebar kolom sejenis dengan tabel lain.
    """
    rows = [dict(row,
                 _highlight=bool(row.get("active")),
                 version_label=f"v{row.get('version')}"
                               + (" ←" if row.get("active") else ""))
            for row in rows or []]
    from ui.i18n import t

    return tbl.table_html(HISTORY_COLUMNS, rows, empty=t(HISTORY_EMPTY_KEY))


def compare_note(left: dict, right: dict) -> str:
    """Satu baris: hash kedua versi, dan apakah isinya identik.

    Ringkasan JUMLAH baris berubah datang dari :func:`diff_counts` — dihitung
    dari isi berkas, bukan ditebak dari hash. Hash hanya menjawab "sama atau
    tidak"; perbedaan per barisnya ditunjukkan oleh tabel diff.
    """
    if not left or not right:
        return ""
    lv, rv_ = left.get("version"), right.get("version")
    lh, rh = short_hash(left.get("file_hash")), short_hash(right.get("file_hash"))
    if (left.get("file_hash") or "") == (right.get("file_hash") or ""):
        return f"v{lv} `{lh}` = v{rv_} `{rh}` — identik."
    return f"v{lv} `{lh}` → v{rv_} `{rh}`"


# ── Perbandingan versi: per baris, memakai PUSTAKA BAWAAN ─────────────────
#
# `difflib` ada di pustaka standar Python — tidak ada dependensi baru yang
# dipasang untuk fitur ini, dan itu dijaga oleh test.
#
# Keputusan lama ("diff per baris tidak dibangun, hash sudah cukup") DIBALIK di
# sini: hash hanya menjawab *apakah* berbeda, sedangkan yang dibutuhkan peninjau
# adalah *bagian mana* yang berbeda — justru itu inti peninjauan kode.
#
# Seluruh lapis ini MURNI: teks masuk, baris keluar. Tidak ada berkas dibaca,
# tidak ada kode di-import atau dijalankan.

import difflib  # noqa: E402  (pustaka bawaan; diletakkan dekat pemakaiannya)

#: Baris tak berubah yang tetap ditampilkan di sekitar tiap perubahan.
DIFF_CONTEXT = 3

TAG_EQUAL, TAG_ADD, TAG_DEL = "equal", "add", "del"

#: Penanda TEKSTUAL — warna tidak pernah menjadi satu-satunya pembeda.
DIFF_MARK = {TAG_EQUAL: " ", TAG_ADD: "+", TAG_DEL: "−"}

#: Status satu berkas antar dua versi.
FILE_SAME = "tidak berubah"
FILE_CHANGED = "berubah"
FILE_ADDED = "baru"
FILE_REMOVED = "dihapus"

IDENTICAL_NOTE = "Kedua versi identik — tidak ada baris yang berbeda."


def line_rows(left_text: str, right_text: str) -> list[dict]:
    """Diff per baris: setiap baris jadi satu baris tabel.

    ``left``/``right`` adalah NOMOR BARIS di masing-masing sisi (``None`` bila
    baris itu tidak ada di sisi tersebut), sehingga nomor baris kedua versi
    dapat ditampilkan berdampingan.

    ``autojunk=False`` penting: heuristik bawaan ``SequenceMatcher`` menganggap
    baris yang sering berulang sebagai "sampah" dan diam-diam melewatkannya —
    pada kode sumber (baris kosong, ``return``) itu membuat diff-nya salah.
    """
    left = (left_text or "").splitlines()
    right = (right_text or "").splitlines()
    rows: list[dict] = []
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"tag": TAG_EQUAL, "left": i1 + k + 1,
                             "right": j1 + k + 1, "text": left[i1 + k]})
            continue
        # "replace" tampil sebagai penghapusan lalu penambahan — dua penanda
        # yang jelas, bukan satu baris yang ambigu.
        for k in range(i1, i2):
            rows.append({"tag": TAG_DEL, "left": k + 1, "right": None,
                         "text": left[k]})
        for k in range(j1, j2):
            rows.append({"tag": TAG_ADD, "left": None, "right": k + 1,
                         "text": right[k]})
    return rows


def diff_counts(rows) -> dict:
    """Jumlah baris ditambah & dihapus."""
    rows = rows or []
    return {"added": sum(1 for r in rows if r["tag"] == TAG_ADD),
            "removed": sum(1 for r in rows if r["tag"] == TAG_DEL)}


def is_identical(rows) -> bool:
    counts = diff_counts(rows)
    return counts["added"] == 0 and counts["removed"] == 0


def collapse_rows(rows, context: int = DIFF_CONTEXT) -> list[dict]:
    """Pecah menjadi segmen TAMPIL / TERSEMBUNYI.

    Bagian tak berubah yang jauh dari perubahan disembunyikan supaya perubahan
    tidak tenggelam di antara ratusan baris yang sama. Segmen tersembunyi tetap
    membawa barisnya, jadi tampilan dapat membukanya tanpa menghitung ulang.
    """
    rows = list(rows or [])
    if not rows:
        return []
    context = max(int(context), 0)
    keep = [False] * len(rows)
    for i, row in enumerate(rows):
        if row["tag"] != TAG_EQUAL:
            for j in range(max(0, i - context), min(len(rows), i + context + 1)):
                keep[j] = True

    segments: list[dict] = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and keep[j] == keep[i]:
            j += 1
        segments.append({"shown": keep[i], "rows": rows[i:j]})
        i = j
    return segments


def diff_table_html(rows, left_label: str = "", right_label: str = "") -> str:
    """Tabel diff: nomor baris KEDUA sisi, penanda tekstual, lalu isinya.

    Warnanya sengaja memakai lapisan tembus pandang (rgba) sehingga terbaca di
    tema terang maupun gelap tanpa dua palet terpisah — dan warna itu BUKAN
    satu-satunya pembeda: kolom penanda ``+``/``−`` tetap ada bila warna tidak
    terlihat (buta warna, cetak hitam-putih, kontras tinggi).
    """
    from html import escape

    rows = list(rows or [])
    if not rows:
        return ""
    head = (f'<tr><th class="ids-diff-n">{escape(str(left_label))}</th>'
            f'<th class="ids-diff-n">{escape(str(right_label))}</th>'
            f'<th class="ids-diff-m"></th><th class="ids-diff-t"></th></tr>')
    body = []
    for row in rows:
        tag = row["tag"]
        body.append(
            f'<tr class="ids-diff-{tag}">'
            f'<td class="ids-diff-n">{row["left"] or ""}</td>'
            f'<td class="ids-diff-n">{row["right"] or ""}</td>'
            f'<td class="ids-diff-m">{DIFF_MARK[tag]}</td>'
            f'<td class="ids-diff-t">{escape(row["text"])}</td></tr>')
    return ('<div class="ids-diff-scroll"><table class="ids-diff">'
            f'<thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>')


def file_diff_index(left_files: dict, right_files: dict) -> list[dict]:
    """Status tiap berkas antar dua versi — dasar pemilih berkas.

    Berkas yang identik cukup DITANDAI; isinya tidak perlu ditampilkan sama
    sekali, apalagi dibandingkan baris per baris.
    """
    left_files = left_files or {}
    right_files = right_files or {}
    out = []
    for name in sorted(set(left_files) | set(right_files)):
        left, right = left_files.get(name), right_files.get(name)
        if left is None:
            status = FILE_ADDED
        elif right is None:
            status = FILE_REMOVED
        elif left == right:
            status = FILE_SAME
        else:
            status = FILE_CHANGED
        counts = ({"added": 0, "removed": 0} if status == FILE_SAME
                  else diff_counts(line_rows(left or "", right or "")))
        out.append({"name": name, "status": status, **counts})
    return out


#: Kolom daftar berkas pada perbandingan versi.
FILE_INDEX_COLUMNS = (
    tbl.column("Berkas", "name", kind=tbl.KIND_NAME),
    tbl.column("Status", "status", kind=tbl.KIND_STATUS),
    tbl.column("Ditambah", "added", kind=tbl.KIND_NUM),
    tbl.column("Dihapus", "removed", kind=tbl.KIND_NUM),
)

FILE_INDEX_EMPTY = "Tidak ada berkas yang dapat dibandingkan."


def file_diff_index_html(index) -> str:
    """Daftar berkas + statusnya — berkas identik CUKUP ditandai.

    Ini yang menjawab "berkas mana saja yang berbeda" sekaligus, tanpa perlu
    membuka satu per satu; isi berkas yang identik tidak ditampilkan sama
    sekali.

    Dulu tabel ini mencampur DUA sistem kelas sekaligus (``ids-facts``, yang
    dimaksudkan untuk pasangan label-nilai, dan ``ids-cmp``, yang aturannya
    tidak terpasang di halaman ini). Sekarang ia memakai penyaji yang sama
    dengan tabel riwayat, jadi kolom sejenis berlebar sama.
    """
    rows = [dict(entry,
                 _highlight=entry["status"] != FILE_SAME,
                 added=entry["added"] or "—",
                 removed=entry["removed"] or "—")
            for entry in index or []]
    return tbl.table_html(FILE_INDEX_COLUMNS, rows, empty=FILE_INDEX_EMPTY)


def file_label(entry: dict) -> str:
    """Label pemilih berkas: nama + status + jumlah perubahan."""
    if entry["status"] == FILE_SAME:
        return f"{entry['name']} · {FILE_SAME}"
    delta = f"+{entry['added']} −{entry['removed']}"
    return f"{entry['name']} · {entry['status']} · {delta}"


def changed_only(index) -> list[dict]:
    return [e for e in (index or []) if e["status"] != FILE_SAME]
