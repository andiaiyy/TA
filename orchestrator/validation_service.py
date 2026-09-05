"""
Validation service — high-level validation for UI consumption.
No database access. No side effects.
"""
import pandas as pd

from orchestrator.dataset_parser import parse_dataset, resolve_dataset_path
from orchestrator.validator import validate_dataset, ValidationResult
# Skema & daftar jenis dibaca lewat pembaca GABUNGAN: bawaan + research
# pipeline terunggah. Lapis ini memang boleh membaca basis data; validator
# dan diagnosa tidak (lihat batasan impor masing-masing), jadi merekalah
# yang DISODORI skemanya dari sini.
from orchestrator.research_registry import all_dataset_types, schema_for
from orchestrator.dynamic_registry import get_pipelines_for_dataset_merged
from utils.hashing import sha256_file

_FAILURE = dict(
    row_count=None, column_count=None, label_column=None,
    unique_labels=None, dataset_hash=None,
    compatible_pipelines=None, validation_result=None,
)


def _validate_csv_memory_safe(dataset_type: str, resolved) -> ValidationResult:
    """Validate a CSV WITHOUT loading the whole file into memory.

    A 288 MB CSV expands to >1.5 GB as a full DataFrame and OOMs the small
    Docker VM when the UI validates inline. Instead:
      - columns / schema check  → small header sample (nrows=100)
      - row_count               → accurate, chunked single-column streaming pass
      - label uniques (Classes) → accurate, from the label column only (chunked)

    All displayed numbers stay accurate (not sample-based). The full file is
    still parsed by the worker via ``parse_dataset`` at execution time — this
    function does not touch that path.
    """
    schema = schema_for(dataset_type) or {}

    # Raw header names (no strip) so usecols matches the file exactly; map each
    # stripped name back to its raw header (mirrors parse_dataset's strip).
    raw_cols = pd.read_csv(resolved, nrows=0).columns.tolist()
    strip_to_raw = {c.strip(): c for c in raw_cols}

    # Small sample (stripped columns) for the column / schema / label checks.
    sample = pd.read_csv(resolved, nrows=100)
    sample.columns = sample.columns.str.strip()

    label_col = schema.get("label_column")
    raw_label = strip_to_raw.get(label_col) if label_col else None
    read_col = raw_label or (raw_cols[0] if raw_cols else None)

    # One chunked pass over a SINGLE column: accurate row_count + label uniques,
    # with tiny peak memory (never materialises the full frame).
    row_count = 0
    uniques: set = set()
    if read_col is not None:
        for chunk in pd.read_csv(resolved, usecols=[read_col], chunksize=200_000):
            row_count += len(chunk)
            if raw_label:
                uniques.update(chunk[read_col].dropna().unique().tolist())

    # Reuse validate_dataset()'s column/schema decisions on the header sample,
    # then override the count/label fields with the accurate streamed values.
    result = validate_dataset(sample, dataset_type,
                              schema=schema_for(dataset_type))
    result.row_count = row_count
    if raw_label:
        result.unique_labels = sorted(uniques, key=lambda x: str(x))
    if row_count == 0 and "DataFrame is empty (0 rows)" not in result.errors:
        result.errors.append("DataFrame is empty (0 rows)")
        result.is_valid = False
    return result


def validate_for_experiment(dataset_type: str, dataset_path: str) -> dict:
    """
    Full validation for the UI's "Validate Dataset" button.

    Returns dict with:
        success, error, row_count, column_count, label_column,
        unique_labels, dataset_hash, compatible_pipelines, validation_result

    NEVER raises for expected failures — returns success=False with error message.
    """
    if schema_for(dataset_type) is None:
        return {"success": False, "error": f"Unknown dataset type: {dataset_type}", **_FAILURE}

    try:
        resolved = resolve_dataset_path(dataset_path)
        if resolved.suffix.lower() == ".csv":
            # Memory-safe CSV validation — never load the full file in the UI
            # process (a large CSV would OOM the small Docker VM). The worker
            # still parses the full file via parse_dataset at execution time.
            result = _validate_csv_memory_safe(dataset_type, resolved)
        else:
            # NDJSON/JSON: parse_dataset already reads only a light ~100-record stub.
            df = parse_dataset(dataset_path)
            result = validate_dataset(
                df, dataset_type, schema=schema_for(dataset_type))
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e), **_FAILURE}

    if not result.is_valid:
        return {
            "success": False,
            "error": "; ".join(result.errors),
            "row_count": result.row_count,
            "column_count": result.column_count,
            "label_column": result.label_column,
            "unique_labels": result.unique_labels,
            "dataset_hash": None,
            "compatible_pipelines": None,
            "validation_result": result,
        }

    dataset_hash = sha256_file(dataset_path)
    # Bawaan (registry statis) + pipeline terunggah yang sudah disetujui.
    pipelines = get_pipelines_for_dataset_merged(dataset_type)

    return {
        "success": True,
        "error": None,
        "row_count": result.row_count,
        "column_count": result.column_count,
        "label_column": result.label_column,
        "unique_labels": result.unique_labels,
        "dataset_hash": dataset_hash,
        "compatible_pipelines": pipelines,
        "validation_result": result,
    }


def get_available_datasets() -> list[str]:
    """Return list of supported dataset type names."""
    return all_dataset_types()


def get_available_pipelines(dataset_type: str) -> dict:
    """Return pipelines compatible with a given dataset type."""
    return get_pipelines_for_dataset_merged(dataset_type)
