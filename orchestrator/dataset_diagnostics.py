"""
Dataset compatibility diagnostics — "does this file fit that research pipeline,
and if not, exactly what is missing?"

Complements (never replaces) the existing validation chain:
  - contracts/dataset_schemas.py  → the RULES (file format, label column, columns)
  - orchestrator/validator.py     → schema/column verdict on a DataFrame
  - orchestrator/validation_service.py → the memory-safe UI validation of the
    ONE dataset_type the file was mapped to (100-row header sample + chunked
    single-column pass)

What this module adds: a *per-dataset_type* diagnosis of the SAME file against
EVERY registered dataset_type, with a specific, user-facing reason per failed
check — so a file that fits nothing still tells the user why, for each pipeline.

⚠️ MEMORY: datasets here reach ~555k rows (HIKARI CSV) to millions of lines
(EVE NDJSON) on a host with a ~3.5 GB ceiling, and this runs automatically on
dataset selection. Therefore:
  - the file is read ONCE, capped at SAMPLE_ROWS rows, and every dataset_type is
    evaluated against that same sample (``diagnose_all``),
  - NDJSON is streamed into counters only — no DataFrame, no record list, so
    peak memory is O(1) in the number of lines,
  - CSV is read with ``nrows`` (never the full file; ``parse_dataset``'s full
    read stays the worker/execution path only),
  - the only extra read is a single-column chunked pass used to confirm an
    otherwise ambiguous "one class" verdict (see _accurate_csv_label_values).

It never runs a pipeline, never loads a model, and never touches computation.

⚠️ IMPORT RESTRICTION: no imports from ui/ or database/. Pipeline constants are
imported lazily + defensively (never at module import time) so this module stays
cheap and can never break the UI when a pipeline package changes.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from contracts.dataset_schemas import get_schema, supported_datasets
from orchestrator.dataset_parser import resolve_dataset_path
from orchestrator.validator import validate_dataset

logger = logging.getLogger(__name__)

# Rows sampled for the deep (dtype + class distribution) checks. Big enough to
# infer column types and see both classes, small enough to stay far under the
# memory ceiling: 50k HIKARI rows ≈ 35 MB as a DataFrame, and NDJSON never
# materialises rows at all.
SAMPLE_ROWS = 50_000

# Chunk size for the single-column label pass — mirrors
# validation_service._validate_csv_memory_safe so both use one tuned value.
_LABEL_CHUNK_ROWS = 200_000

# How many column/key names to name explicitly in a message before "…". Kept
# small on purpose: a full 80-column dump is neither readable nor actionable.
_MAX_LISTED = 5

# Check keys — stable identifiers so the UI can render/order them.
CHECK_FORMAT = "format"
CHECK_LABEL = "label"
CHECK_FEATURES = "features"
CHECK_DTYPE = "dtype"
CHECK_CLASSES = "classes"

# Statuses. compatible == no check has status "fail".
PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"

# Human labels for the five checks — the ONE place these titles are written.
_CHECK_TITLES = {
    CHECK_FORMAT: "Format berkas",
    CHECK_LABEL: "Kolom label",
    CHECK_FEATURES: "Kolom fitur",
    CHECK_DTYPE: "Tipe data fitur",
    CHECK_CLASSES: "Distribusi kelas",
}


@dataclass
class DiagnosticCheck:
    """One evaluated rule. ``message`` is user-facing and always specific.

    ``count``/``examples`` carry the same facts as ``message`` in structured
    form (how many columns/keys/classes are involved, and a few real names) so
    the UI can write a short summary line without re-parsing the sentence.
    """
    key: str
    title: str
    status: str          # PASS | WARN | FAIL | SKIP
    message: str
    count: int = 0
    examples: list[str] = field(default_factory=list)
    # Bentuk yang dapat diterjemahkan. DITAMBAHKAN, bukan mengganti: `key`,
    # `status`, `count`, dan `examples` adalah KEPUTUSAN dan pembandingnya —
    # ketiganya tidak boleh berubah. `msg_key` menunjuk kalimat di kamus, dan
    # `values` membawa nilai sisipannya (nama kolom, jumlah) apa adanya.
    # Lapisan tampilan yang menyusun kalimatnya: lihat
    # ui/components/validator_messages.diagnostic_message.
    msg_key: str = ""
    values: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """True when the check does not block compatibility."""
        return self.status != FAIL


@dataclass
class DatasetSample:
    """Everything read from the file, in ONE pass, for ALL dataset types.

    CSV → a capped DataFrame (columns + dtypes + label values).
    NDJSON → counters only (keys seen, event types, TLS/alert evidence); records
    are never accumulated, so memory does not grow with the file.
    """
    path: str = ""
    detected_format: str = "unknown"      # "csv" | "ndjson" | "unknown"
    rows_read: int = 0
    truncated: bool = False               # hit SAMPLE_ROWS → numbers are sample-based
    columns: list[str] = field(default_factory=list)
    frame: pd.DataFrame | None = None     # CSV only, ≤ SAMPLE_ROWS rows
    key_counts: dict[str, int] = field(default_factory=dict)   # NDJSON top-level keys
    event_type_counts: dict[str, int] = field(default_factory=dict)
    tls_rows: int = 0                     # NDJSON: events identified as TLS
    alert_rows: int = 0                   # NDJSON: alert evidence (→ Attack class)
    malformed_lines: int = 0
    encoding: str = ""                    # CSV: the decoder that actually worked
    error: str | None = None


# ── Structured-source helpers (lazy + defensive: never break the UI) ───────

def _hikari_drop_cols() -> list[str]:
    """Non-feature columns HIKARI preprocessing drops (uid, IPs, traffic_category,
    index artifacts). Read from the pipeline itself so the dtype check does not
    flag columns the pipeline was always going to discard."""
    try:
        from pipelines.hikari2021._common import _DROP_COLS
        return list(_DROP_COLS)
    except Exception:  # pragma: no cover - defensive
        logger.debug("HIKARI _DROP_COLS unavailable for diagnostics", exc_info=True)
        return []


def _tls_ports() -> set[int]:
    """TLS ports from the SAME ports.txt the cbr splitter uses (priority-3 app
    detection). Empty set if unreadable — app_proto/event_type still decide."""
    try:
        from pipelines.eve_cbr.split.split_eve_by_app import read_ports_file
        ports_file = Path(__file__).resolve().parents[1] / "pipelines" / "eve_cbr" / "split" / "ports.txt"
        return set(read_ports_file(ports_file).get("tls", set()))
    except Exception:  # pragma: no cover - defensive
        logger.debug("TLS ports unavailable for diagnostics", exc_info=True)
        return set()


def required_format(dataset_type: str) -> str:
    """"csv" or "ndjson", derived from the schema exactly as the UI's type icon
    does: a schema that declares expected_top_level_keys is a per-line JSON
    format; anything else is tabular CSV."""
    schema = get_schema(dataset_type) or {}
    if schema.get("expected_top_level_keys") or schema.get("file_format") in ("json", "json_or_csv"):
        return "ndjson"
    return "csv"


def _fmt_list(names) -> str:
    names = [sanitize_display_value(n) for n in names]
    shown = ", ".join(f"`{n}`" for n in names[:_MAX_LISTED])
    if len(names) > _MAX_LISTED:
        shown += f", … (+{len(names) - _MAX_LISTED} lainnya)"
    return shown


# Characters that must never reach the UI as-is. U+FFFD is the big one: several
# public IDS datasets (CICIDS's "Web Attack <U+FFFD> Brute Force") ship with the
# replacement character already baked into the FILE — an en-dash that some
# upstream conversion destroyed. Decoding is not at fault there, so the value is
# repaired at the point it becomes display text.
_REPLACEMENT_CHARS = "�﻿"


def sanitize_display_value(value) -> str:
    """Make a raw dataset value safe and readable as UI text.

    - U+FFFD (the "�" glyph) → "-": it stands in for a dash in every real case
      we have seen, and showing mojibake helps nobody.
    - control characters (incl. newlines/tabs from ragged files) → space.
    - collapses the whitespace that substitution leaves behind.

    Purely cosmetic: it is applied to the text of a message, never to the value
    a check is evaluated against, so no verdict can change.
    """
    text = str(value)
    out = []
    for ch in text:
        if ch in _REPLACEMENT_CHARS:
            out.append("-")
        elif ch == "`":
            out.append("'")      # never break out of an inline-code span
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(" ")
        else:
            out.append(ch)
    return " ".join("".join(out).split()) or "(kosong)"


# ── The single read ───────────────────────────────────────────────────────

def read_dataset_sample(dataset_path: str, max_rows: int = SAMPLE_ROWS) -> DatasetSample:
    """Read at most ``max_rows`` rows/lines ONCE. Never raises."""
    sample = DatasetSample(path=str(dataset_path))
    try:
        resolved = resolve_dataset_path(dataset_path)
    except (FileNotFoundError, ValueError) as e:
        sample.error = str(e)
        return sample

    ext = resolved.suffix.lower()
    try:
        if ext == ".csv":
            _read_csv_sample(resolved, sample, max_rows)
        else:
            _read_ndjson_sample(resolved, sample, max_rows)
    except MemoryError:  # pragma: no cover - defensive
        sample.error = ("Berkas terlalu besar untuk disampel dengan aman di "
                        "lingkungan ini.")
    except Exception as e:
        sample.error = f"Berkas gagal dibaca/diparse: {e}"
    return sample


def _read_csv_sample(resolved: Path, sample: DatasetSample, max_rows: int) -> None:
    """CSV: one capped read. Headers stripped exactly like parse_dataset.

    Encoding: UTF-8 first, then cp1252 (which also covers latin-1) for the many
    IDS CSVs exported from Windows tooling. Without the fallback a single
    non-UTF-8 byte would abort the whole diagnosis with "berkas gagal dibaca".
    ``errors="replace"`` is deliberately NOT used — it manufactures the very "�"
    this fallback exists to avoid.
    """
    for encoding in ("utf-8", "cp1252"):
        try:
            df = pd.read_csv(resolved, nrows=max_rows, encoding=encoding)
            sample.encoding = encoding
            break
        except UnicodeDecodeError:
            logger.debug("CSV sample not decodable as %s: %s", encoding, resolved)
    else:  # pragma: no cover - both decoders failed
        raise ValueError("Encoding berkas CSV tidak dikenali (bukan UTF-8/cp1252).")
    df.columns = df.columns.str.strip()
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    sample.detected_format = "csv"
    sample.frame = df
    sample.columns = df.columns.tolist()
    sample.rows_read = len(df)
    # Hitting the cap means the file may hold more rows → numbers are sample-based.
    sample.truncated = len(df) >= max_rows


def _read_ndjson_sample(resolved: Path, sample: DatasetSample, max_rows: int) -> None:
    """NDJSON: stream into counters only — O(1) memory in the number of lines.

    TLS / alert detection mirrors the cbr splitter's own priority order
    (app_proto → event_type → port fallback) and its alert evidence rule, so the
    diagnosis matches what the pipeline would actually find.
    """
    tls_ports = _tls_ports()
    keys: dict[str, int] = {}
    events: dict[str, int] = {}
    parsed = 0

    with open(resolved, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if parsed >= max_rows:
                sample.truncated = True
                break
            try:
                obj = json.loads(line)
            except Exception:
                sample.malformed_lines += 1
                continue
            if not isinstance(obj, dict):
                sample.malformed_lines += 1
                continue
            parsed += 1

            for k in obj:
                keys[k] = keys.get(k, 0) + 1

            ev = str(obj.get("event_type") or "").strip().lower()
            if ev:
                events[ev] = events.get(ev, 0) + 1

            app_proto = str(obj.get("app_proto") or "").strip().lower()
            is_tls = app_proto == "tls" or ev == "tls"
            if not is_tls and tls_ports:
                for port_key in ("src_port", "dest_port"):
                    try:
                        if int(obj[port_key]) in tls_ports:
                            is_tls = True
                            break
                    except Exception:
                        continue
            if is_tls:
                sample.tls_rows += 1

            # Attack-class evidence, same signal the splitter labels on:
            # event_type == "alert" OR an alert object carrying a severity.
            alert = obj.get("alert")
            if ev == "alert" or (isinstance(alert, dict) and alert.get("severity") is not None):
                sample.alert_rows += 1

    sample.detected_format = "ndjson" if parsed else "unknown"
    sample.rows_read = parsed
    sample.key_counts = keys
    sample.event_type_counts = events
    sample.columns = sorted(keys)
    if not parsed:
        sample.error = (
            "Tidak ada objek JSON valid pada baris-baris awal berkas "
            "(format NDJSON = satu objek JSON per baris)."
        )


def _accurate_csv_label_values(resolved: Path, label_col: str) -> list:
    """Confirm the class set with a chunked pass over the LABEL COLUMN ONLY.

    Used only when the capped sample showed a single class on a truncated file —
    a CSV sorted by label would otherwise produce a false "one class" verdict.
    Same tiny-memory pattern as validation_service._validate_csv_memory_safe
    (one column, chunked, never the full frame). Returns [] on any failure.
    """
    try:
        raw_cols = pd.read_csv(resolved, nrows=0).columns.tolist()
        raw_label = {c.strip(): c for c in raw_cols}.get(label_col)
        if raw_label is None:
            return []
        uniques: set = set()
        for chunk in pd.read_csv(resolved, usecols=[raw_label], chunksize=_LABEL_CHUNK_ROWS):
            uniques.update(chunk[raw_label].dropna().unique().tolist())
            if len(uniques) > 1:
                break  # two classes is all the check needs
        return sorted(uniques, key=lambda x: str(x))
    except Exception:  # pragma: no cover - defensive
        logger.debug("Accurate label pass failed for %s", resolved, exc_info=True)
        return []


# ── The rules ─────────────────────────────────────────────────────────────

def diagnose_dataset(dataset_path: str, dataset_type: str,
                     sample: DatasetSample | None = None) -> dict:
    """Diagnose ONE dataset_type. Returns a plain dict (cache/JSON friendly):

        {compatible: bool, dataset_type, checks: [{key,title,status,message}],
         rows_read, sampled: bool, error: str|None}

    ``sample`` lets callers reuse a single read across every dataset_type
    (``diagnose_all``); when omitted the file is sampled here. Never raises.
    """
    if sample is None:
        sample = read_dataset_sample(dataset_path)

    schema = get_schema(dataset_type)
    base = {
        "dataset_type": dataset_type,
        "rows_read": sample.rows_read,
        "sampled": sample.truncated,
        "detected_format": sample.detected_format,
        "error": sample.error,
    }

    if schema is None:
        return {**base, "compatible": False, "checks": [
            asdict(DiagnosticCheck(CHECK_FORMAT, _CHECK_TITLES[CHECK_FORMAT], FAIL,
                                   f"Tipe dataset `{dataset_type}` tidak dikenal.",
                                   msg_key="dx.unknown_type",
                                   values={"dataset_type": dataset_type}))
        ]}

    if sample.error:
        # Unreadable/corrupt file: report it once, do not guess the rest.
        # `sample.error` adalah pesan KESALAHAN pembacaan berkas — lingkup
        # Tahap 3B, bukan 3A. Ia diteruskan apa adanya sebagai nilai sisipan;
        # yang berbahasa di sini hanya kalimat "dilewati" di bawahnya.
        checks = [DiagnosticCheck(CHECK_FORMAT, _CHECK_TITLES[CHECK_FORMAT], FAIL,
                                  sample.error, msg_key="dx.file_unreadable",
                                  values={"error": sample.error})]
        checks += [DiagnosticCheck(k, _CHECK_TITLES[k], SKIP,
                                   "Tidak dapat diperiksa karena berkas gagal dibaca.",
                                   msg_key="dx.skipped_unreadable")
                   for k in (CHECK_LABEL, CHECK_FEATURES, CHECK_DTYPE, CHECK_CLASSES)]
        return {**base, "compatible": False, "checks": [asdict(c) for c in checks]}

    want = required_format(dataset_type)
    if want == "ndjson":
        checks = _diagnose_ndjson_type(dataset_type, schema, sample)
    else:
        checks = _diagnose_csv_type(dataset_type, schema, sample)

    return {
        **base,
        "compatible": all(c.status != FAIL for c in checks),
        "checks": [asdict(c) for c in checks],
    }


def _format_check(dataset_type: str, sample: DatasetSample) -> DiagnosticCheck:
    """Shared file-format rule, derived from the schema."""
    want = required_format(dataset_type)
    got = sample.detected_format
    names = {"csv": "CSV", "ndjson": "NDJSON", "unknown": "tidak dikenali"}
    if got == want:
        unit = "satu baris per flow" if want == "csv" else "satu objek JSON per baris"
        return DiagnosticCheck(CHECK_FORMAT, _CHECK_TITLES[CHECK_FORMAT], PASS,
                               f"Terdeteksi {names[want]} ({unit}).",
                               msg_key=("dx.format_ok_csv" if want == "csv"
                                        else "dx.format_ok_ndjson"),
                               values={"format": names[want]})
    return DiagnosticCheck(
        CHECK_FORMAT, _CHECK_TITLES[CHECK_FORMAT], FAIL,
        f"Format terdeteksi **{names.get(got, got)}**, tetapi pipeline ini "
        f"membutuhkan **{names[want]}**.",
        msg_key="dx.format_wrong",
        values={"detected": names.get(got, got), "needed": names[want]},
    )


def _skip_rest(reason: str, keys, msg_key: str = "") -> list[DiagnosticCheck]:
    """Pemeriksaan yang DILEWATI — bukan gagal.

    Bedanya penting bagi pembaca: `skip` berarti "belum sempat diperiksa karena
    syarat sebelumnya belum terpenuhi", sedangkan `fail` berarti "diperiksa dan
    tidak memenuhi". Kalimatnya harus menyatakan itu di kedua bahasa.
    """
    return [DiagnosticCheck(k, _CHECK_TITLES[k], SKIP, reason, msg_key=msg_key)
            for k in keys]


def _diagnose_csv_type(dataset_type: str, schema: dict,
                       sample: DatasetSample) -> list[DiagnosticCheck]:
    """Tabular rules (HIKARI2021): label column, schema columns, numeric feature
    dtypes, ≥2 classes. Column verdicts reuse orchestrator.validator."""
    fmt = _format_check(dataset_type, sample)
    if fmt.status == FAIL or sample.frame is None:
        return [fmt] + _skip_rest(
            "Tidak diperiksa karena format berkas belum sesuai.",
            (CHECK_LABEL, CHECK_FEATURES, CHECK_DTYPE, CHECK_CLASSES),
            msg_key="dx.skipped_format")

    df = sample.frame
    label_col = schema.get("label_column") or "label"
    cols = list(df.columns)

    # Reuse the existing schema verdict on the (capped) sample — same rules the
    # platform validates with, no second definition of "missing column".
    result = validate_dataset(df.head(100), dataset_type)
    missing = list(result.missing_columns)

    checks = [fmt]

    # 2. Label column.
    if label_col in cols:
        checks.append(DiagnosticCheck(CHECK_LABEL, _CHECK_TITLES[CHECK_LABEL], PASS,
                                      f"Kolom label `{label_col}` ditemukan.",
                                      msg_key="dx.label_found",
                                      values={"column": label_col}))
    else:
        checks.append(DiagnosticCheck(
            CHECK_LABEL, _CHECK_TITLES[CHECK_LABEL], FAIL,
            f"Dataset Anda kurang kolom label `{label_col}`.",
            msg_key="dx.label_missing", values={"column": label_col}))

    # 3. Feature columns (present at all + schema completeness).
    feature_cols = [c for c in cols if c != label_col]
    missing_features = [c for c in missing if c != label_col]
    if not feature_cols:
        checks.append(DiagnosticCheck(
            CHECK_FEATURES, _CHECK_TITLES[CHECK_FEATURES], FAIL,
            "Tidak ada kolom fitur — berkas hanya berisi kolom label.",
            msg_key="dx.features_none"))
    elif missing_features:
        checks.append(DiagnosticCheck(
            CHECK_FEATURES, _CHECK_TITLES[CHECK_FEATURES], FAIL,
            f"Dataset Anda kurang {len(missing_features)} kolom yang diminta "
            f"skema: {_fmt_list(missing_features)}.",
            count=len(missing_features),
            examples=[sanitize_display_value(c) for c in missing_features[:_MAX_LISTED]],
            msg_key="dx.features_missing",
            values={"count": len(missing_features),
                    "columns": _fmt_list(missing_features)}))
    else:
        checks.append(DiagnosticCheck(
            CHECK_FEATURES, _CHECK_TITLES[CHECK_FEATURES], PASS,
            f"{len(feature_cols)} kolom selain label ditemukan; seluruh kolom "
            f"yang diminta skema lengkap.",
            msg_key="dx.features_ok", values={"count": len(feature_cols)}))

    # 4. Feature dtypes — non-numeric columns the pipeline does NOT drop.
    drops = set(_hikari_drop_cols())
    non_numeric = [c for c in df.select_dtypes(exclude=[np.number]).columns
                   if c != label_col and c not in drops]
    if not feature_cols:
        checks.append(DiagnosticCheck(CHECK_DTYPE, _CHECK_TITLES[CHECK_DTYPE], SKIP,
                                      "Tidak ada kolom fitur untuk diperiksa.",
                                      msg_key="dx.skipped_no_features"))
    elif non_numeric:
        # The pipeline drops leftover non-numeric columns as a safety net, so the
        # run still works — but those features are silently lost. Warn, specific.
        checks.append(DiagnosticCheck(
            CHECK_DTYPE, _CHECK_TITLES[CHECK_DTYPE], WARN,
            f"{len(non_numeric)} kolom fitur bukan numerik dan akan diabaikan "
            f"pipeline: {_fmt_list(non_numeric)}.",
            count=len(non_numeric),
            examples=[sanitize_display_value(c) for c in non_numeric[:_MAX_LISTED]],
            msg_key="dx.dtype_non_numeric",
            values={"count": len(non_numeric),
                    "columns": _fmt_list(non_numeric)}))
    else:
        checks.append(DiagnosticCheck(
            CHECK_DTYPE, _CHECK_TITLES[CHECK_DTYPE], PASS,
            "Seluruh kolom fitur bertipe numerik.",
            msg_key="dx.dtype_ok"))

    # 5. Class distribution.
    if label_col not in cols:
        checks.append(DiagnosticCheck(
            CHECK_CLASSES, _CHECK_TITLES[CHECK_CLASSES], SKIP,
            f"Tidak dapat diperiksa tanpa kolom `{label_col}`.",
            msg_key="dx.skipped_no_label", values={"column": label_col}))
    else:
        raw_values = sorted(df[label_col].dropna().unique().tolist(), key=lambda x: str(x))
        values = raw_values
        if len(values) < 2 and sample.truncated:
            # Ambiguous: a label-sorted CSV shows one class in the first rows.
            # Confirm with a label-column-only chunked pass before failing.
            try:
                confirmed = _accurate_csv_label_values(
                    resolve_dataset_path(sample.path), label_col)
            except Exception:  # pragma: no cover - defensive
                confirmed = []
            if len(confirmed) > len(values):
                values = confirmed
        # Label values come straight from the file and can carry mojibake, so
        # they are sanitised on their way into the message (never before the
        # uniqueness count, which stays exactly as the data says).
        names = [sanitize_display_value(v) for v in values[:_MAX_LISTED]]
        shown = _fmt_list(values) or "(kosong)"
        if len(values) >= 2:
            checks.append(DiagnosticCheck(
                CHECK_CLASSES, _CHECK_TITLES[CHECK_CLASSES], PASS,
                f"{len(values)} kelas terdeteksi pada kolom `{label_col}`: {shown}.",
                count=len(values), examples=names,
                msg_key="dx.classes_ok",
                values={"count": len(values), "column": label_col,
                        "classes": shown}))
        else:
            checks.append(DiagnosticCheck(
                CHECK_CLASSES, _CHECK_TITLES[CHECK_CLASSES], FAIL,
                f"Hanya satu kelas terdeteksi pada kolom `{label_col}` "
                f"({shown}); pipeline butuh dua kelas (benign & attack).",
                count=len(values), examples=names,
                msg_key="dx.classes_single",
                values={"column": label_col, "classes": shown}))

    return checks


def _diagnose_ndjson_type(dataset_type: str, schema: dict,
                          sample: DatasetSample) -> list[DiagnosticCheck]:
    """Per-line JSON rules (EVE Suricata). "Kolom" = kunci pada objek JSON.

    The label is NOT expected in the raw file: the pipeline derives `Target` from
    Suricata alerts. So the label check verifies the *alert evidence* that
    produces it, and the class check verifies both classes can exist.
    """
    fmt = _format_check(dataset_type, sample)
    if fmt.status == FAIL:
        return [fmt] + _skip_rest(
            "Tidak diperiksa karena format berkas belum sesuai.",
            (CHECK_LABEL, CHECK_FEATURES, CHECK_DTYPE, CHECK_CLASSES),
            msg_key="dx.skipped_format")

    label_col = schema.get("label_column") or "label"
    expected_keys = list(schema.get("expected_top_level_keys") or [])
    present = set(sample.columns)
    missing_keys = [k for k in expected_keys if k not in present]

    checks = [fmt]

    # 2. Label — derived from Suricata alerts, not required in the file.
    if sample.alert_rows > 0:
        checks.append(DiagnosticCheck(
            CHECK_LABEL, _CHECK_TITLES[CHECK_LABEL], PASS,
            f"Kolom `{label_col}` tidak perlu ada — pipeline menurunkannya dari "
            f"**alert Suricata**; {sample.alert_rows:,} event dengan bukti alert "
            f"ditemukan pada sampel.",
            msg_key="dx.eve_label_derived",
            values={"column": label_col, "events": f"{sample.alert_rows:,}"}))
    else:
        checks.append(DiagnosticCheck(
            CHECK_LABEL, _CHECK_TITLES[CHECK_LABEL], FAIL,
            f"Tidak ada bukti alert Suricata pada sampel, padahal `{label_col}` "
            f"diturunkan dari alert (`event_type` = `alert`, atau objek `alert` "
            f"yang memiliki `severity`). Label tidak dapat dibentuk.",
            msg_key="dx.eve_label_no_alert", values={"column": label_col}))

    # 3. Keys the schema expects + TLS events the pipeline analyses.
    if missing_keys:
        checks.append(DiagnosticCheck(
            CHECK_FEATURES, _CHECK_TITLES[CHECK_FEATURES], FAIL,
            f"Dataset Anda kurang {len(missing_keys)} kunci JSON yang diminta "
            f"skema: {_fmt_list(missing_keys)}.",
            count=len(missing_keys),
            examples=[sanitize_display_value(k) for k in missing_keys[:_MAX_LISTED]],
            msg_key="dx.eve_keys_missing",
            values={"count": len(missing_keys),
                    "keys": _fmt_list(missing_keys)}))
    elif sample.tls_rows == 0:
        checks.append(DiagnosticCheck(
            CHECK_FEATURES, _CHECK_TITLES[CHECK_FEATURES], FAIL,
            "Tidak ditemukan event TLS pada sampel (`app_proto`/`event_type` = "
            "`tls`, atau port TLS); pipeline ini hanya menganalisis trafik TLS.",
            msg_key="dx.eve_no_tls"))
    else:
        checks.append(DiagnosticCheck(
            CHECK_FEATURES, _CHECK_TITLES[CHECK_FEATURES], PASS,
            f"Seluruh kunci skema ada; {sample.tls_rows:,} event TLS ditemukan "
            f"pada sampel.",
            msg_key="dx.eve_keys_ok",
            values={"events": f"{sample.tls_rows:,}"}))

    # 4. Dtypes are not applicable — the pipeline engineers its own features.
    checks.append(DiagnosticCheck(
        CHECK_DTYPE, _CHECK_TITLES[CHECK_DTYPE], SKIP,
        "Tidak berlaku — pipeline merekayasa & menyeleksi fiturnya sendiri "
        "(MI/RFE/PCA) dari field EVE mentah.",
        msg_key="dx.eve_dtype_na"))

    # 5. Both classes must be reachable: TLS events (benign side) + alerts.
    if sample.tls_rows and sample.alert_rows:
        checks.append(DiagnosticCheck(
            CHECK_CLASSES, _CHECK_TITLES[CHECK_CLASSES], PASS,
            f"Dua kelas dapat terbentuk pada sampel: {sample.tls_rows:,} event "
            f"TLS dan {sample.alert_rows:,} event beralert.",
            msg_key="dx.eve_classes_ok",
            values={"tls": f"{sample.tls_rows:,}",
                    "alerts": f"{sample.alert_rows:,}"}))
    elif not sample.alert_rows:
        checks.append(DiagnosticCheck(
            CHECK_CLASSES, _CHECK_TITLES[CHECK_CLASSES], FAIL,
            "Hanya satu kelas yang dapat terbentuk: tidak ada event `alert` pada "
            "sampel, sehingga kelas attack akan kosong.",
            msg_key="dx.eve_classes_no_alert"))
    else:
        checks.append(DiagnosticCheck(
            CHECK_CLASSES, _CHECK_TITLES[CHECK_CLASSES], FAIL,
            "Hanya satu kelas yang dapat terbentuk: tidak ada event TLS pada "
            "sampel, sehingga kelas benign TLS akan kosong.",
            msg_key="dx.eve_classes_no_tls"))

    return checks


def build_profile(sample: DatasetSample) -> dict:
    """Metadata deskriptif berkas, dari SAMPEL yang SUDAH dibaca.

    Murni: hanya membaca ``sample`` — tidak membuka berkas, tidak membaca ulang,
    tidak menghitung apa pun atas seluruh dataset. Semua angka di sini adalah
    angka SAMPEL bila ``sampled`` bernilai True; pemanggil wajib menyatakannya.

    Tidak memengaruhi satu pun verdict: fungsi ini tidak dipakai oleh
    pemeriksaan mana pun, hanya menyusun tampilan.
    """
    profile: dict = {
        "detected_format": sample.detected_format,
        "rows_read": sample.rows_read,
        "sampled": sample.truncated,
        "encoding": sample.encoding,
        "malformed_lines": sample.malformed_lines,
        "columns": list(sample.columns),
        "column_count": len(sample.columns),
        "label_column": None,
        "class_counts": {},
        "numeric_columns": None,
        "non_numeric_columns": None,
        "tls_rows": sample.tls_rows,
        "alert_rows": sample.alert_rows,
        "error": sample.error,
    }

    # Kolom label = kolom label skema mana pun yang benar-benar ADA di berkas.
    present = set(sample.columns)
    for dtype in supported_datasets():
        label_col = (get_schema(dtype) or {}).get("label_column")
        if label_col and label_col in present:
            profile["label_column"] = label_col
            break

    frame = sample.frame
    if frame is None:
        return profile

    numeric = frame.select_dtypes(include=[np.number]).columns.tolist()
    profile["numeric_columns"] = len(numeric)
    profile["non_numeric_columns"] = len(frame.columns) - len(numeric)

    label_col = profile["label_column"]
    if label_col and label_col in frame.columns:
        counts = frame[label_col].dropna().value_counts()
        profile["class_counts"] = {
            sanitize_display_value(value): int(n) for value, n in counts.items()
        }
    return profile


def diagnose_all(dataset_path: str, max_rows: int = SAMPLE_ROWS) -> dict:
    """Read the file ONCE, then diagnose EVERY registered dataset_type from that
    same sample — the entry point the UI uses.

    Returns::

        {path, rows_read, sampled: bool, detected_format, error,
         results: {dataset_type: <diagnose_dataset dict>},
         compatible_types: [dataset_type, …]}
    """
    sample = read_dataset_sample(dataset_path, max_rows=max_rows)
    results = {dt: diagnose_dataset(dataset_path, dt, sample=sample)
               for dt in supported_datasets()}
    # Profil deskriptif disusun dari sampel yang SAMA (tanpa pembacaan baru),
    # selagi frame-nya masih ada. Murni tambahan untuk tampilan — tidak dipakai
    # oleh pemeriksaan mana pun, jadi tidak ada verdict yang berubah.
    profile = build_profile(sample)
    # Release the sampled frame as soon as every rule has been evaluated.
    sample.frame = None
    return {
        "path": str(dataset_path),
        "profile": profile,
        "rows_read": sample.rows_read,
        "sampled": sample.truncated,
        "detected_format": sample.detected_format,
        "malformed_lines": sample.malformed_lines,
        "error": sample.error,
        "results": results,
        "compatible_types": [dt for dt, r in results.items() if r["compatible"]],
    }
