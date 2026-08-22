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

**Parameter tidak pernah dikarang.** Basis data maupun artefak tidak menyimpan
hiperparameter per eksperimen (metadata.json hanya memuat identitas dataset,
daftar fitur, label_mapping, dan versi lingkungan). Satu-satunya sumber nyata
adalah ``get_info()['fixed_params']`` milik pipeline, yang bersifat
DEFINISI — nilai yang berlaku pada kode saat ini, bukan yang direkam saat
eksperimen berjalan. Modul ini membacanya apa adanya, menandai asal-usulnya
lewat :data:`PARAM_PROVENANCE`, dan mengisi "—" untuk pipeline yang memang tidak
punya kunci itu (mis. EVE tidak memakai ``test_size``).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

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
    "Parameter dibaca dari definisi pipeline (get_info → fixed_params) pada "
    "kode saat ini, bukan direkam per eksperimen — basis data dan artefak "
    "tidak menyimpan hiperparameter per proses."
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
    return "Semantik metrik — " + "; ".join(
        f"{FAMILY_LABELS[f]}: {METRIC_SEMANTICS[f]}" for f in fams) + "."


def is_cross_family(rows) -> bool:
    return len(families_in(rows)) > 1


# ── Definisi kolom ────────────────────────────────────────────────────────

GROUP_IDENTITY = "Identitas"
GROUP_PARAM = "Parameter"
GROUP_METRIC = "Metrik"
GROUP_ORDER = (GROUP_IDENTITY, GROUP_PARAM, GROUP_METRIC)

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
]
_METRIC_COLUMNS = [
    ("accuracy", "Accuracy", KIND_METRIC),
    ("precision", "Precision", KIND_METRIC),
    ("recall", "Recall", KIND_METRIC),
    ("f1", "F1-score", KIND_METRIC),
    ("auc", "ROC-AUC", KIND_METRIC),
]

# Set inti yang tampil sebelum pengguna memilih apa pun.
DEFAULT_COLUMNS = ["waktu", "pipeline", "dataset", "status", "accuracy", "f1"]

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
    cols = [{"key": k, "label": lbl, "group": GROUP_IDENTITY, "kind": kind}
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
            "accuracy": e.get("accuracy"),
            "precision": e.get("precision_score"),
            "recall": e.get("recall"),
            "f1": e.get("f1_score"),
            "auc": auc,
        }
        for key, value in (params_map.get(row["pipeline"]) or {}).items():
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


# ── Filter ────────────────────────────────────────────────────────────────

def filter_options(rows) -> dict:
    """Nilai yang benar-benar muncul pada data — bukan daftar tetap."""
    def uniq(key):
        return sorted({r.get(key) for r in rows or [] if r.get(key)})
    return {"pipelines": uniq("pipeline"), "datasets": uniq("dataset"),
            "statuses": uniq("status")}


def apply_filters(rows, *, pipelines=None, datasets=None, statuses=None,
                  start=None, end=None) -> list[dict]:
    """Saring baris YANG SUDAH DIBACA — tidak ada kueri ulang ke basis data.

    Daftar kosong/None berarti "tanpa batasan" untuk dimensi itu.
    """
    out = []
    for row in rows or []:
        if pipelines and row.get("pipeline") not in pipelines:
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
    return f"{shown} dari {total} eksperimen"


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


class ExpressionError(ValueError):
    """Ekspresi tidak dapat dipahami. Pesannya untuk ditampilkan apa adanya."""


def parse_expression(text):
    """Ubah ekspresi menjadi daftar (field, op, angka). TIDAK memakai eval/exec.

    Hanya pola `nama operator angka` yang digabung dengan ``and`` yang diterima;
    apa pun di luar itu memunculkan :class:`ExpressionError` dengan pesan jelas.
    Mengembalikan [] untuk teks kosong (artinya: tanpa penyaringan).
    """
    raw = (text or "").strip()
    if not raw:
        return []

    terms = []
    for chunk in re.split(r"\s+and\s+|&&|,", raw, flags=re.IGNORECASE):
        if not chunk.strip():
            continue
        match = _TERM_RE.match(chunk)
        if not match:
            raise ExpressionError(
                f"Bagian `{chunk.strip()}` tidak dikenali. {EXPR_HELP}")
        name, op, number = match.group(1).lower(), match.group(2), match.group(3)
        field = _EXPR_FIELDS.get(name) or _EXPR_ALIASES.get(name)
        if field is None:
            raise ExpressionError(
                f"`{match.group(1)}` bukan nama metrik. {EXPR_HELP}")
        terms.append((field, op, float(number)))
    if not terms:
        raise ExpressionError(f"Ekspresi kosong. {EXPR_HELP}")
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

_COMPARE_IDENTITY = ["pipeline", "dataset", "waktu", "status", "durasi",
                     "pemilik", "dataset_hash", "pipeline_version"]


def comparison_warnings(rows) -> list[str]:
    """Peringatan WAJIB sebelum menyandingkan angka."""
    warnings = []
    if is_cross_family(rows):
        warnings.append(CROSS_FAMILY_WARNING)
    hashes = {r.get("_dataset_hash_full") for r in rows or []
              if r.get("_dataset_hash_full")}
    if len(hashes) > 1:
        warnings.append(DATASET_MISMATCH_WARNING)
    return warnings


def build_comparison(rows, param_keys=()) -> dict:
    """Data perbandingan berdampingan: satu kolom per eksperimen.

    Mengembalikan::

        {"headers": [...], "warnings": [...], "note": str,
         "sections": [{"group": str, "fields": [
             {"label": str, "values": [...], "differs": bool}]}]}

    ``differs`` menandai baris yang nilainya TIDAK sama di semua eksperimen —
    itulah yang perlu disorot pembaca.
    """
    rows = list(rows or [])
    columns = {c["key"]: c for c in build_columns(param_keys)}

    def section(group, keys, drop_empty=False):
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
            fields.append({"label": col["label"], "values": values,
                           "differs": len(set(values)) > 1})
        return {"group": group, "fields": fields}

    sections = [
        section(GROUP_IDENTITY, _COMPARE_IDENTITY),
        section(GROUP_PARAM, [f"param_{k}" for k in param_keys], drop_empty=True),
        section(GROUP_METRIC, [c[0] for c in _METRIC_COLUMNS]),
    ]
    return {
        "headers": [r.get("id", "—") for r in rows],
        "warnings": comparison_warnings(rows),
        "note": semantics_note(rows),
        "sections": [s for s in sections if s["fields"]],
    }


def compare_selection_error(selected_ids) -> str:
    """Pesan bila pilihan tidak layak dibandingkan; "" bila layak."""
    n = len(selected_ids or [])
    if n < 2:
        return "Pilih minimal dua eksperimen untuk dibandingkan."
    if n > MAX_COMPARE:
        return (f"Maksimal {MAX_COMPARE} eksperimen dapat dibandingkan "
                f"sekaligus (dipilih {n}).")
    return ""


# ── Ekspor CSV ────────────────────────────────────────────────────────────

CSV_SEMANTICS_COLUMN = "Semantik metrik"


def to_csv(rows, columns) -> str:
    """CSV yang MENGIKUTI kolom & filter aktif, bukan dump basis data.

    Setiap baris membawa keterangan semantik metriknya sendiri, sehingga berkas
    ini tidak menyesatkan bila dibuka terpisah dari aplikasi.
    """
    buffer = io.StringIO()
    header = [c["label"] for c in columns] + [CSV_SEMANTICS_COLUMN]
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows or []:
        fam = family_of(row.get("dataset"))
        note = (f"{FAMILY_LABELS[fam]}: {METRIC_SEMANTICS[fam]}" if fam
                else "keluarga pipeline tidak dikenal")
        writer.writerow([cell_text(row, c) for c in columns] + [note])
    return buffer.getvalue()


def csv_filename(now=None) -> str:
    """Nama berkas dengan stempel waktu."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"eksperimen-{stamp}.csv"
