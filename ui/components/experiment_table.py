"""
Lapis MURNI untuk tabel riwayat "Progress & Status" — kolom bergrup, filter,
pemilih kolom, perbandingan berdampingan, dan ekspor CSV.

Tidak ada Streamlit dan tidak ada I/O di sini: pembacaan basis data dan artefak
disuntikkan sebagai fungsi (``roc_reader``, ``params_reader``), sehingga seluruh
perilaku dapat diuji dengan data biasa.

**Kejujuran metrik (aturan yang paling menentukan modul ini).** Angka
precision/recall/F1 TIDAK bermakna sama antar keluarga pipeline:

* HIKARI2021 melaporkan rata-rata berbobot seluruh kelas;
* EVE/Suricata melaporkan kelas serangan pada natural-holdout.

Karena itu setiap penyajian yang menyandingkan keduanya WAJIB membawa catatan
semantiknya (:func:`semantics_note`), perbandingan lintas keluarga memunculkan
peringatan (:func:`comparison_warnings`), berkas CSV membawa kolom keterangan
per baris, dan modul ini TIDAK PERNAH menyusun peringkat "model terbaik".

**Parameter tidak pernah dikarang.** Ada DUA asal-usul, dan keduanya dinyatakan
apa adanya lewat :data:`PARAM_PROVENANCE`:

* eksperimen yang dijalankan SEJAK mode eksekusi ada membawa kolom
  ``params_used`` — parameter yang benar-benar dipakai saat itu, tercatat per
  eksperimen;
* record lama (kolom itu NULL) jatuh kembali ke ``get_info()['fixed_params']``
  pipeline, yang bersifat DEFINISI — nilai yang berlaku pada kode saat ini,
  bukan yang direkam saat eksperimen berjalan.

Pipeline yang memang tidak punya sebuah kunci tetap mengisi "—" (mis. EVE tidak
memakai ``test_size``); tidak ada nilai yang ditebak untuk mengisi kekosongan.

**Mode eksekusi selalu terlihat.** Setiap baris membawa penandanya
(:func:`~orchestrator.run_mode.run_mode_badge`), kolom Mode ikut set bawaan,
CSV membawanya sebagai kolom tersendiri, dan mencampur run resmi dengan run
eksplorasi memunculkan peringatan — sekelas peringatan semantik metrik di atas.
Record dengan ``run_mode`` NULL dibaca sebagai RESMI, bukan "tidak diketahui".
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

from orchestrator.run_mode import (
    ALL_RUN_MODES, MIXED_MODE_WARNING, RUN_MODE_BADGES, format_params,
    load_params, locked_params, normalize_run_mode, run_mode_badge,
)

# ── Keluarga pipeline & semantik metrik ───────────────────────────────────

FAMILY_HIKARI = "HIKARI2021"
FAMILY_EVE = "EVE_SURICATA"

# Satu-satunya tempat semantik metrik dirumuskan.
METRIC_SEMANTICS = {
    FAMILY_HIKARI: "rata-rata berbobot seluruh kelas (weighted average)",
    FAMILY_EVE: "kelas serangan pada natural-holdout",
}
FAMILY_LABELS = {
    FAMILY_HIKARI: "HIKARI2021",
    FAMILY_EVE: "EVE/Suricata",
}

#: Keluarga → kunci semantik. `METRIC_SEMANTICS` di atas TIDAK diubah: ia
#: satu-satunya tempat semantik dirumuskan dan dipakai pembanding di tempat
#: lain. Yang ditambahkan hanya jalur terjemahannya.
METRIC_SEMANTICS_KEYS = {
    FAMILY_HIKARI: "ps.semantics_hikari",
    FAMILY_EVE: "ps.semantics_eve",
}


def semantics_of(family: str) -> str:
    """Semantik metrik satu keluarga, pada bahasa aktif."""
    from ui.i18n import t

    key = METRIC_SEMANTICS_KEYS.get(family)
    return t(key) if key else METRIC_SEMANTICS.get(family, "")

CROSS_FAMILY_WARNING = (
    "Eksperimen yang dipilih berasal dari keluarga pipeline berbeda. "
    "Precision/recall/F1 keduanya TIDAK sebanding langsung: "
    + "; ".join(f"{FAMILY_LABELS[f]} = {METRIC_SEMANTICS[f]}"
                for f in (FAMILY_HIKARI, FAMILY_EVE))
    + "."
)
DATASET_MISMATCH_WARNING = (
    "Eksperimen yang dipilih dijalankan pada dataset dengan hash berbeda — "
    "angkanya berasal dari data yang tidak sama."
)

PARAM_PROVENANCE = (
    "Parameter bertanda ✓ direkam saat eksperimen itu berjalan; sisanya dibaca "
    "dari definisi pipeline (get_info → fixed_params) pada kode saat ini, "
    "karena eksperimen lama belum mencatat parameternya."
)
PARAM_RECORDED_MARK = "✓"
MODE_COLUMN_NOTE = (
    "Kolom Mode: 🔒 Resmi = parameter terkunci, dasar perbandingan & replikasi; "
    "🧪 Eksplorasi = parameter disesuaikan, di luar perbandingan resmi."
)


def family_of(dataset_type) -> str | None:
    """Keluarga pipeline sebuah eksperimen, atau None bila tidak dikenal."""
    dt = (dataset_type or "").strip()
    return dt if dt in METRIC_SEMANTICS else None


def families_in(rows) -> list[str]:
    """Keluarga yang muncul pada sekumpulan baris, urut stabil."""
    seen = []
    for row in rows or []:
        fam = family_of(row.get("dataset"))
        if fam and fam not in seen:
            seen.append(fam)
    return seen


def semantics_note(rows) -> str:
    """Catatan semantik untuk sekumpulan baris.

    Selalu mengembalikan teks — bahkan untuk satu keluarga, karena pembaca tetap
    perlu tahu angka apa yang sedang ia lihat.
    """
    fams = families_in(rows)
    if not fams:
        return ""
    from ui.i18n import t

    # Nama keluarga (HIKARI2021, EVE/Suricata) TIDAK diterjemahkan.
    return t("ps.semantics_note", parts="; ".join(
        f"{FAMILY_LABELS[f]}: {semantics_of(f)}" for f in fams))


def is_cross_family(rows) -> bool:
    return len(families_in(rows)) > 1


# ── Definisi kolom ────────────────────────────────────────────────────────

# PENGENAL kelompok — dipakai untuk mengurutkan & mengelompokkan kolom, jadi
# nilainya tidak berbahasa. Labelnya dipetakan di `GROUP_LABEL_KEYS`.
GROUP_IDENTITY = "Identitas"
GROUP_PARAM = "Parameter"
GROUP_METRIC = "Metrik"
GROUP_ORDER = (GROUP_IDENTITY, GROUP_PARAM, GROUP_METRIC)
GROUP_LABEL_KEYS = {
    GROUP_IDENTITY: "ps.group_identity",
    GROUP_PARAM: "ps.group_param",
    GROUP_METRIC: "ps.group_metric",
}


def group_label(group: str) -> str:
    """Nama kelompok kolom pada bahasa aktif."""
    from ui.i18n import t

    key = GROUP_LABEL_KEYS.get(group)
    return t(key) if key else group

KIND_TEXT = "text"
KIND_METRIC = "metric"

# Kolom identitas & metrik — semuanya benar-benar ada di baris basis data
# (lihat database/models.py) atau di artefak metrics.json (roc_auc).
_IDENTITY_COLUMNS = [
    ("id", "ID", KIND_TEXT),
    ("waktu", "Waktu", KIND_TEXT),
    ("durasi", "Durasi", KIND_TEXT),
    ("pipeline", "Pipeline", KIND_TEXT),
    ("dataset", "Dataset", KIND_TEXT),
    ("berkas", "Berkas", KIND_TEXT),
    ("pemilik", "Pemilik", KIND_TEXT),
    ("status", "Status", KIND_TEXT),
    ("dataset_hash", "Hash dataset", KIND_TEXT),
    ("pipeline_version", "Versi pipeline", KIND_TEXT),
    ("mode", "Mode", KIND_TEXT),
]

#: Kunci kolom → kunci judul. Kunci kolomnya sendiri ("waktu", "durasi", …)
#: adalah PENGENAL: ia dipakai memilih kolom, menyusun CSV, dan menyimpan
#: pilihan pengguna — jadi ia tidak pernah berbahasa. Nama metrik
#: (Accuracy/Precision/Recall/F1-score/ROC-AUC) juga tidak diterjemahkan.
COLUMN_LABEL_KEYS = {
    "id": "ps.col_id",
    "waktu": "ps.col_time",
    "durasi": "ps.col_duration",
    "pipeline": "ps.col_pipeline",
    "dataset": "ps.col_dataset",
    "berkas": "ps.col_file",
    "pemilik": "ps.col_owner",
    "status": "ps.col_status",
    "dataset_hash": "ps.col_dataset_hash",
    "pipeline_version": "ps.col_pipeline_version",
    "mode": "ps.col_mode_header",
}


def column_label(key: str, fallback: str = "") -> str:
    """Judul satu kolom pada bahasa aktif; tanpa kunci → judul aslinya."""
    from ui.i18n import t

    label_key = COLUMN_LABEL_KEYS.get(key)
    return t(label_key) if label_key else fallback
_METRIC_COLUMNS = [
    ("accuracy", "Accuracy", KIND_METRIC),
    ("precision", "Precision", KIND_METRIC),
    ("recall", "Recall", KIND_METRIC),
    ("f1", "F1-score", KIND_METRIC),
    ("auc", "ROC-AUC", KIND_METRIC),
]

# Set inti yang tampil sebelum pengguna memilih apa pun.
# "mode" ikut set bawaan: run eksplorasi harus terbedakan SEKILAS, tanpa
# pengguna perlu membuka pemilih kolom lebih dulu.
DEFAULT_COLUMNS = ["waktu", "pipeline", "dataset", "mode", "status",
                   "accuracy", "f1"]

METRIC_DECIMALS = 4
MAX_COMPARE = 5


def parameter_keys(params_reader) -> list[str]:
    """Gabungan kunci parameter yang BENAR-BENAR ada pada pipeline terdaftar.

    Dihitung dari sumbernya, bukan didaftar manual: pipeline yang tidak punya
    sebuah kunci tidak akan pernah menampilkan nilai untuk kunci itu.
    """
    keys: list[str] = []
    for params in (params_reader() or {}).values():
        for key in (params or {}):
            if key not in keys:
                keys.append(key)
    return sorted(keys)


def build_columns(param_keys=()) -> list[dict]:
    """Spesifikasi kolom lengkap, bergrup Identitas | Parameter | Metrik."""
    # Judul identitas mengikuti bahasa; nama parameter dan nama metrik
    # TIDAK diterjemahkan — keduanya pengenal yang dibaca apa adanya.
    cols = [{"key": k, "label": column_label(k, lbl),
             "group": GROUP_IDENTITY, "kind": kind}
            for k, lbl, kind in _IDENTITY_COLUMNS]
    cols += [{"key": f"param_{k}", "label": k, "group": GROUP_PARAM,
              "kind": KIND_TEXT} for k in param_keys]
    cols += [{"key": k, "label": lbl, "group": GROUP_METRIC, "kind": kind}
             for k, lbl, kind in _METRIC_COLUMNS]
    return cols


def columns_by_group(columns) -> dict:
    """{grup: [kolom]} dengan urutan grup tetap."""
    out = {g: [] for g in GROUP_ORDER}
    for col in columns:
        out.setdefault(col["group"], []).append(col)
    return out


def visible_columns(columns, selected_keys) -> list[dict]:
    """Kolom yang ditampilkan, tetap dalam urutan spesifikasi (bukan urutan
    pilihan pengguna) agar tabel tidak berubah-ubah susunannya."""
    chosen = set(selected_keys or [])
    return [c for c in columns if c["key"] in chosen]


# ── Penyusun baris ────────────────────────────────────────────────────────

def _parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def format_duration(started_at, completed_at) -> str:
    start, end = _parse_iso(started_at), _parse_iso(completed_at)
    if start is None or end is None:
        return "—"
    secs = (end - start).total_seconds()
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs:.0f}s"
    if secs < 3600:
        return f"{secs / 60:.1f} menit"
    return f"{secs / 3600:.1f} jam"


def format_metric(value) -> str:
    """4 desimal, atau "—" bila memang tidak ada. Tidak pernah menebak 0."""
    if value is None or not isinstance(value, (int, float)) or value != value:
        return "—"
    return f"{float(value):.{METRIC_DECIMALS}f}"


def basename(path) -> str:
    if not path:
        return "—"
    return re.split(r"[\\/]", str(path))[-1] or "—"


def build_rows(experiments, *, roc_reader=None, params_reader=None) -> list[dict]:
    """Baris siap-tampil dari record eksperimen.

    ``roc_reader(experiment_id) -> float|None`` membaca roc_auc dari artefak;
    ``params_reader() -> {pipeline_id: {param: nilai}}`` memberi parameter
    tingkat-definisi. Keduanya opsional — tanpa keduanya, kolom terkait berisi
    None dan disajikan "—".

    Parameter satu baris diambil dari ``params_used`` record itu bila ada
    (nilai yang BENAR-BENAR dipakai saat itu), dan hanya jatuh ke definisi
    pipeline bila record-nya memang belum mencatat apa pun. ``_params_recorded``
    menandai yang mana, supaya UI tidak menyamakan keduanya.
    """
    params_map = (params_reader() or {}) if params_reader else {}
    rows = []
    for e in experiments or []:
        eid = e.get("id") or ""
        created = e.get("created_at")
        auc = None
        if roc_reader is not None:
            try:
                auc = roc_reader(eid)
            except Exception:               # artefak hilang/rusak ≠ tabel rusak
                auc = None

        row = {
            "_id": eid,
            "id": eid[:8],
            "waktu": (created or "—")[:19] if created else "—",
            "_created": _parse_iso(created),
            "durasi": format_duration(e.get("started_at"), e.get("completed_at")),
            "pipeline": e.get("pipeline_id") or "—",
            "dataset": e.get("dataset_type") or "—",
            "berkas": basename(e.get("dataset_path")),
            # Informasi saja — TIDAK dipakai menyaring apa pun.
            "pemilik": e.get("owner") or "sistem",
            "status": e.get("status") or "—",
            "dataset_hash": (e.get("dataset_hash") or "")[:12] or "—",
            "_dataset_hash_full": e.get("dataset_hash") or "",
            # NULL untuk pipeline bawaan (definisinya ada di git) — "—", bukan 0.
            "pipeline_version": (e.get("pipeline_version")
                                 if e.get("pipeline_version") is not None else "—"),
            # NULL -> "resmi": record lama dibuat saat seluruh parameter masih
            # terkunci, jadi ini fakta, bukan tebakan. Tidak pernah "?".
            "mode": run_mode_badge(e.get("run_mode")),
            "_mode": normalize_run_mode(e.get("run_mode")),
            "accuracy": e.get("accuracy"),
            "precision": e.get("precision_score"),
            "recall": e.get("recall"),
            "f1": e.get("f1_score"),
            "auc": auc,
        }
        recorded = load_params(e.get("params_used"))
        row["_params_used"] = recorded
        row["_params_recorded"] = bool(recorded)
        source = recorded or (params_map.get(row["pipeline"]) or {})
        for key, value in source.items():
            row[f"param_{key}"] = value
        rows.append(row)
    return rows


def cell_text(row, column) -> str:
    """Nilai satu sel sebagai teks siap-tampil."""
    value = row.get(column["key"])
    if column["kind"] == KIND_METRIC:
        return format_metric(value)
    if value is None or value == "":
        return "—"
    return str(value)


def best_flag_key(metric_key: str) -> str:
    return f"_best_{metric_key}"


def mark_best_within_family(rows) -> list[dict]:
    """Tandai nilai metrik TERBAIK **di dalam keluarganya masing-masing**.

    Sengaja tidak lintas keluarga: menyorot nilai tertinggi satu kolom tanpa
    memandang keluarga sama saja dengan menobatkan juara antar angka yang
    semantiknya berbeda (HIKARI weighted-average vs EVE kelas serangan). Baris
    tanpa keluarga yang dikenali tidak pernah ditandai.
    """
    rows = list(rows or [])
    for metric_key, _label, _kind in _METRIC_COLUMNS:
        flag = best_flag_key(metric_key)
        for row in rows:
            row[flag] = False
        by_family: dict[str, list[dict]] = {}
        for row in rows:
            fam = family_of(row.get("dataset"))
            if fam:
                by_family.setdefault(fam, []).append(row)
        for family_rows in by_family.values():
            values = [r.get(metric_key) for r in family_rows
                      if isinstance(r.get(metric_key), (int, float))
                      and r.get(metric_key) == r.get(metric_key)]
            if not values:
                continue
            top = max(values)
            for row in family_rows:
                value = row.get(metric_key)
                if isinstance(value, (int, float)) and value == top:
                    row[flag] = True
    return rows


BEST_MARK_NOTE = ("Nilai tertinggi disorot per kolom DI DALAM keluarga "
                  "pipeline masing-masing — bukan peringkat lintas keluarga.")
#: Kunci katalog untuk keterangan yang sama; konstanta di atas tetap acuan.
BEST_MARK_NOTE_KEY = "ps.best_mark_note"
CROSS_FAMILY_WARNING_KEY = "ps.cross_family_warning"
DATASET_MISMATCH_WARNING_KEY = "ps.dataset_mismatch_warning"
PARAM_PROVENANCE_KEY = "ps.param_provenance"
MODE_COLUMN_NOTE_KEY = "ps.mode_column_note"
MODE_FILTER_DEFAULT_NOTE_KEY = "ps.mode_filter_default_note"
ONLY_DIFF_LABEL_KEY = "ps.only_diff_label"
ALL_SAME_NOTE_KEY = "ps.all_same_note"


def cross_family_warning() -> str:
    """Peringatan lintas keluarga pada bahasa aktif — rumusan WAJIB.

    Nama keluarga tidak diterjemahkan; semantiknya diambil dari katalog,
    sehingga peringatan ini tidak dapat memuat dua bahasa sekaligus.
    """
    from ui.i18n import t

    return t("ps.cross_family_warning", parts="; ".join(
        f"{FAMILY_LABELS[f]} = {semantics_of(f)}"
        for f in (FAMILY_HIKARI, FAMILY_EVE)))


# ── Filter ────────────────────────────────────────────────────────────────

def filter_options(rows) -> dict:
    """Nilai yang benar-benar muncul pada data — bukan daftar tetap."""
    def uniq(key):
        return sorted({r.get(key) for r in rows or [] if r.get(key)})
    # Mode SELALU ditawarkan lengkap, bukan hanya yang kebetulan muncul: pilihan
    # "hanya eksplorasi" harus ada meski belum satu pun run eksplorasi dibuat.
    return {"pipelines": uniq("pipeline"), "datasets": uniq("dataset"),
            "statuses": uniq("status"), "modes": list(ALL_RUN_MODES)}


MODE_FILTER_LABELS = dict(RUN_MODE_BADGES)
MODE_FILTER_DEFAULT_NOTE = (
    "Bawaan menampilkan SEMUA mode — run eksplorasi tidak disembunyikan, "
    "hanya ditandai."
)


def apply_filters(rows, *, pipelines=None, datasets=None, statuses=None,
                  modes=None, start=None, end=None) -> list[dict]:
    """Saring baris YANG SUDAH DIBACA — tidak ada kueri ulang ke basis data.

    Daftar kosong/None berarti "tanpa batasan" untuk dimensi itu — termasuk
    ``modes``, sehingga bawaannya menampilkan kedua mode. Menyaring mode adalah
    pilihan pengguna, bukan penyembunyian otomatis.
    """
    wanted_modes = {normalize_run_mode(m) for m in modes} if modes else None
    out = []
    for row in rows or []:
        if pipelines and row.get("pipeline") not in pipelines:
            continue
        if wanted_modes is not None and row.get("_mode") not in wanted_modes:
            continue
        if datasets and row.get("dataset") not in datasets:
            continue
        if statuses and row.get("status") not in statuses:
            continue
        created = row.get("_created")
        if start is not None:
            if created is None or created.date() < start:
                continue
        if end is not None:
            if created is None or created.date() > end:
                continue
        out.append(row)
    return out


def result_summary(shown: int, total: int) -> str:
    from ui.i18n import t

    return t("ps.result_summary", shown=shown, total=total)


# ── Pencarian ekspresi (parser terbatas, TANPA eval/exec) ─────────────────

# Hanya nama metrik yang benar-benar ada sebagai kolom metrik.
_EXPR_FIELDS = {c[0]: c[0] for c in _METRIC_COLUMNS}
_EXPR_ALIASES = {"f1_score": "f1", "f1score": "f1", "roc_auc": "auc",
                 "roc": "auc", "acc": "accuracy", "prec": "precision"}
_EXPR_OPS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b, "<": lambda a, b: a < b,
}
_TERM_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")

EXPR_HELP = ("Contoh: `f1 > 0.8`, `accuracy >= 0.9 and auc > 0.85`. "
             "Nama yang dikenal: " + ", ".join(sorted(_EXPR_FIELDS)) + ".")


def expr_help() -> str:
    """Bantuan ekspresi pada bahasa aktif; nama metriknya tetap apa adanya."""
    from ui.i18n import t

    return t("ps.expr_help", names=", ".join(sorted(_EXPR_FIELDS)))


class ExpressionError(ValueError):
    """Ekspresi tidak dapat dipahami. Pesannya untuk ditampilkan apa adanya."""


def parse_expression(text):  # noqa: C901 — parser kecil, alurnya lurus
    """Ubah ekspresi menjadi daftar (field, op, angka). TIDAK memakai eval/exec.

    Hanya pola `nama operator angka` yang digabung dengan ``and`` yang diterima;
    apa pun di luar itu memunculkan :class:`ExpressionError` dengan pesan jelas.
    Mengembalikan [] untuk teks kosong (artinya: tanpa penyaringan).
    """
    from ui.i18n import t

    raw = (text or "").strip()
    if not raw:
        return []

    terms = []
    for chunk in re.split(r"\s+and\s+|&&|,", raw, flags=re.IGNORECASE):
        if not chunk.strip():
            continue
        match = _TERM_RE.match(chunk)
        if not match:
            raise ExpressionError(t("ps.expr_unknown_part",
                                    part=chunk.strip(), help=expr_help()))
        name, op, number = match.group(1).lower(), match.group(2), match.group(3)
        field = _EXPR_FIELDS.get(name) or _EXPR_ALIASES.get(name)
        if field is None:
            raise ExpressionError(t("ps.expr_not_metric",
                                    name=match.group(1), help=expr_help()))
        terms.append((field, op, float(number)))
    if not terms:
        raise ExpressionError(t("ps.expr_empty", help=expr_help()))
    return terms


def apply_expression(rows, terms) -> list[dict]:
    """Terapkan hasil :func:`parse_expression`. Baris tanpa nilai metrik itu
    TIDAK lolos — nilai yang tidak ada bukan berarti nol."""
    if not terms:
        return list(rows or [])
    out = []
    for row in rows or []:
        keep = True
        for field, op, number in terms:
            value = row.get(field)
            if not isinstance(value, (int, float)) or value != value:
                keep = False
                break
            if not _EXPR_OPS[op](float(value), number):
                keep = False
                break
        if keep:
            out.append(row)
    return out


# ── Perbandingan berdampingan ─────────────────────────────────────────────

_COMPARE_IDENTITY = ["pipeline", "dataset", "mode", "waktu", "status", "durasi",
                     "pemilik", "dataset_hash", "pipeline_version"]


def modes_in(rows) -> list[str]:
    """Mode yang muncul pada sekumpulan baris, urut tetap."""
    present = {row.get("_mode") or normalize_run_mode(row.get("run_mode"))
               for row in rows or []}
    return [m for m in ALL_RUN_MODES if m in present]


def is_mixed_mode(rows) -> bool:
    """True bila run resmi DAN run eksplorasi dipilih bersama-sama."""
    return len(modes_in(rows)) > 1


#: Konstanta peringatan di `orchestrator.run_mode` TIDAK diubah — ia tercatat
#: pada data lama. Kalimat yang TAMPIL dipetakan di sini.
MIXED_MODE_WARNING_KEY = "ps.mixed_mode_warning"


def comparison_warnings(rows) -> list[str]:
    """Peringatan WAJIB sebelum menyandingkan angka."""
    from ui.i18n import t

    warnings = []
    # Mode lebih dulu: perbedaan parameter membuat angka tidak sebanding
    # sebelum semantik metrik sempat menjadi soal.
    if is_mixed_mode(rows):
        warnings.append(t(MIXED_MODE_WARNING_KEY))
    if is_cross_family(rows):
        warnings.append(cross_family_warning())
    hashes = {r.get("_dataset_hash_full") for r in rows or []
              if r.get("_dataset_hash_full")}
    if len(hashes) > 1:
        warnings.append(t("ps.dataset_mismatch_warning"))
    return warnings


ALIGN_LEFT = "left"
ALIGN_RIGHT = "right"

ONLY_DIFF_LABEL = "Hanya tampilkan yang berbeda"
ALL_SAME_NOTE = ("Seluruh baris bernilai sama pada eksperimen yang dipilih — "
                 "tidak ada perbedaan untuk ditampilkan.")


def build_comparison(rows, param_keys=(), *, only_differences=False) -> dict:
    """Data perbandingan berdampingan: satu kolom per eksperimen.

    Mengembalikan::

        {"headers": [...], "ids": [...], "warnings": [...], "note": str,
         "diff_count": int, "total_count": int,
         "sections": [{"group": str, "fields": [
             {"label": str, "values": [...], "differs": bool, "align": str}]}]}

    ``differs`` menandai baris yang nilainya TIDAK sama di semua eksperimen —
    itulah yang perlu disorot pembaca. ``align`` menentukan perataan sel:
    metrik & parameter numerik rata KANAN supaya digitnya sejajar dan mudah
    dibandingkan sekilas, sisanya rata kiri.

    ``only_differences=True`` menyisakan baris yang berbeda saja. Penyaringan
    dilakukan DI SINI, atas nilai yang sudah dihitung — bukan dengan membaca
    ulang apa pun.
    """
    rows = list(rows or [])
    columns = {c["key"]: c for c in build_columns(param_keys)}
    diff_count = total_count = 0

    def section(group, keys, drop_empty=False):
        nonlocal diff_count, total_count
        fields = []
        for key in keys:
            col = columns.get(key)
            if col is None:
                continue
            values = [cell_text(r, col) for r in rows]
            # Baris parameter yang KOSONG di semua eksperimen tidak berguna
            # dibaca (mis. `max_iter` saat tak satu pun pipeline memakainya).
            if drop_empty and all(v == "—" for v in values):
                continue
            differs = len(set(values)) > 1
            total_count += 1
            if differs:
                diff_count += 1
            if only_differences and not differs:
                continue
            fields.append({"label": col["label"], "values": values,
                           "differs": differs, "align": _align_for(col, values)})
        return {"group": group, "group_label": group_label(group),
                "fields": fields}

    sections = [
        section(GROUP_IDENTITY, _COMPARE_IDENTITY),
        section(GROUP_PARAM, [f"param_{k}" for k in param_keys], drop_empty=True),
        section(GROUP_METRIC, [c[0] for c in _METRIC_COLUMNS]),
    ]
    return {
        "headers": [r.get("id", "—") for r in rows],
        "ids": [r.get("_id") for r in rows],
        "warnings": comparison_warnings(rows),
        "note": semantics_note(rows),
        "diff_count": diff_count,
        "total_count": total_count,
        "sections": [s for s in sections if s["fields"]],
    }


def _align_for(column, values) -> str:
    """Angka rata KANAN, label rata kiri.

    Kolom metrik selalu angka. Kolom parameter bisa angka (``n_estimators``)
    atau teks (``scaler``), jadi diputuskan dari nilainya yang sebenarnya —
    bukan dari nama kolomnya.
    """
    if column["kind"] == KIND_METRIC:
        return ALIGN_RIGHT
    if column["group"] == GROUP_PARAM and all(_looks_numeric(v) for v in values):
        return ALIGN_RIGHT
    return ALIGN_LEFT


def _looks_numeric(text) -> bool:
    candidate = str(text or "").strip()
    if candidate in ("", "—"):
        return True                          # sel kosong tidak memaksa perataan
    try:
        float(candidate)
    except ValueError:
        return False
    return True


def drop_from_comparison(rows, experiment_id):
    """Baris perbandingan tanpa satu eksperimen. MURNI — tidak membaca apa pun.

    Dipakai tombol "buang" di dalam modal: tabel diperbarui dari data yang sudah
    ada di memori, jadi menyusutkan pilihan tidak memicu pembacaan berkas/DB.
    """
    return [r for r in rows or [] if r.get("_id") != experiment_id]


def compare_selection_error(selected_ids) -> str:
    """Pesan bila pilihan tidak layak dibandingkan; "" bila layak.

    BATASNYA tidak berubah — hanya kalimatnya yang mengikuti bahasa.
    """
    from ui.i18n import t

    n = len(selected_ids or [])
    if n < 2:
        return t("ps.compare_need_two")
    if n > MAX_COMPARE:
        return t("ps.compare_too_many", max=MAX_COMPARE, selected=n)
    return ""


# ── Ekspor CSV ────────────────────────────────────────────────────────────

# Judul kolom KETERANGAN dalam bahasa bawaan. Dipertahankan sebagai konstanta
# karena ia nilai yang diimpor & diuji test lama; perenderannya memakai fungsi
# di bawah, yang mengikuti bahasa aktif saat ekspor dibuat.
CSV_SEMANTICS_COLUMN = "Semantik metrik"
CSV_MODE_COLUMN = "Mode eksekusi"
CSV_PARAMS_COLUMN = "Parameter dipakai"

#: Kunci kamus untuk ketiga judul kolom keterangan.
CSV_SEMANTICS_KEY = "csv.col_semantics"
CSV_MODE_KEY = "csv.col_mode"
CSV_PARAMS_KEY = "csv.col_params"

#: Padanan Inggris semantik metrik. `METRIC_SEMANTICS` sendiri TIDAK diubah —
#: ia satu-satunya tempat semantik dirumuskan dan dipakai pembanding di tempat
#: lain; yang ditambahkan hanya terjemahannya.
METRIC_SEMANTICS_EN = {
    FAMILY_HIKARI: "weighted average across all classes",
    FAMILY_EVE: "attack class on the natural holdout",
}


def csv_semantics_text(family) -> str:
    """Catatan semantik metrik pada bahasa aktif.

    WAJIB ikut ke berkas: CSV sering dibaca terpisah dari aplikasi, dan tanpa
    baris ini angka HIKARI (rata-rata berbobot) dan angka EVE (kelas serangan)
    terbaca seolah setara.
    """
    from ui.i18n import current_lang, t

    if not family:
        return t("csv.family_unknown")
    semantics = (METRIC_SEMANTICS[family] if current_lang() == "id"
                 else METRIC_SEMANTICS_EN.get(family, METRIC_SEMANTICS[family]))
    # Nama keluarga TIDAK diterjemahkan — ia nama dataset.
    return f"{FAMILY_LABELS[family]}: {semantics}"


def row_params_text(row) -> str:
    """Parameter satu baris sebagai teks, dengan nilai bawaan bila berbeda."""
    used = row.get("_params_used") or {}
    if not used:
        return ""
    try:
        locked = locked_params(row.get("pipeline") or "")
    except Exception:                   # pragma: no cover - defensif
        locked = {}
    return format_params(used, locked)


def to_csv(rows, columns) -> str:
    """CSV yang MENGIKUTI kolom & filter aktif, bukan dump basis data.

    Tiga kolom SELALU ikut, apa pun pilihan kolom pengguna: semantik metrik,
    mode eksekusi, dan parameter yang dipakai. Berkas CSV sering dibaca
    terpisah dari aplikasi — tanpa ketiganya, sebuah run eksplorasi akan
    terbaca persis seperti run resmi, dan itulah yang tidak boleh terjadi.
    """
    from ui.i18n import t
    from ui.components.validator_messages import run_mode_badge_text

    buffer = io.StringIO()
    # Nama kolom DATA (metrik, identitas eksperimen, nama pipeline) SENGAJA
    # tidak diterjemahkan: berkas ini diolah lintas bahasa — skrip analisis
    # yang mencari kolom "accuracy" harus tetap menemukannya berapa pun bahasa
    # antarmuka saat berkas dibuat. Yang mengikuti bahasa hanya tiga kolom
    # KETERANGAN di bawah, yang memang dibaca manusia.
    header = ([c["label"] for c in columns]
              + [t(CSV_SEMANTICS_KEY), t(CSV_MODE_KEY), t(CSV_PARAMS_KEY)])
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows or []:
        fam = family_of(row.get("dataset"))
        note = csv_semantics_text(fam)
        writer.writerow([cell_text(row, c) for c in columns]
                        + [note, run_mode_badge_text(row.get("_mode")),
                           row_params_text(row)])
    return buffer.getvalue()


def csv_filename(now=None) -> str:
    """Nama berkas dengan stempel waktu."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"eksperimen-{stamp}.csv"
