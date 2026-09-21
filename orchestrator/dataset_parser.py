"""
Dataset parser — CSV loading and cleaning.

Loads a CSV file and performs minimal cleaning:
  - Strip whitespace from column headers
  - Replace infinity values with NaN

Does NOT:
  - Validate schema (that's validator.py)
  - Drop rows or columns
  - Impute missing values
  - Access database

⚠️  IMPORT RESTRICTION: No imports from ui/, database/, or pipelines/.
"""
import numpy as np
import pandas as pd
from pathlib import Path


def resolve_dataset_path(file_path: str) -> Path:
    """Resolve a dataset path applying the platform's safety rules; return the
    resolved Path.

    Shared by ``parse_dataset`` (the full-file EXECUTION read) and the
    memory-safe validation readers in ``orchestrator/validation_service.py`` so
    both enforce identical path safety.

    Steps:
      1. Existence check (+ basename fallback under DATASETS_DIR)
      2. Extension allow-list
      3. Within-project containment (prevents path traversal)

    Raises:
        FileNotFoundError: If the file does not exist (after fallback).
        ValueError: If the extension is unsupported or the path is outside the
            allowed project roots.
    """
    path = Path(file_path)

    if not path.exists():
        # Cross-environment fallback: when UI and worker run in different
        # environments (e.g. UI in Docker emitting /app/... paths, worker on
        # the Windows host, or vice versa), the absolute path from the other
        # side won't resolve here. Retry against the local DATASETS_DIR using
        # only the basename. The path-safety check below still constrains the
        # resolved candidate to live under DATASETS_DIR / BASE_DIR.
        from config.settings import DATASETS_DIR as _DATASETS_DIR
        candidate = Path(_DATASETS_DIR) / path.name
        if candidate.exists():
            path = candidate
        else:
            raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    if ext not in (".csv", ".json", ".jsonl", ".ndjson"):
        raise ValueError(
            f"Unsupported file format: {path.suffix}. Supported: .csv, .json, .jsonl, .ndjson"
        )

    # Path safety check — only allow files within the project directory.
    # Use is_relative_to (Python 3.9+) to avoid startswith substring confusion
    # (e.g. /project/foo matching /project/foobar) and Windows case issues.
    from config.settings import DATASETS_DIR, BASE_DIR
    resolved = path.resolve()
    allowed_roots = [
        Path(DATASETS_DIR).resolve(),
        Path(BASE_DIR).resolve(),
    ]
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError(
            f"Access denied: dataset path must be within the project directory. "
            f"Got: {resolved}"
        )
    return resolved


def parse_dataset(file_path: str) -> pd.DataFrame:
    """
    Load a dataset file and return a cleaned DataFrame.

    NOTE (memory): for CSV this reads the FULL file — it is the EXECUTION read
    used by the worker (which is sized for it). The UI validation path must NOT
    call this for large CSVs; it uses the memory-safe readers in
    ``orchestrator/validation_service.py`` instead. For NDJSON/JSON only a light
    ~100-record stub is read here (Phase 1 handles the full file downstream).

    Steps:
      1. Resolve + path-safety (resolve_dataset_path)
      2. Read (full CSV, or 100-record NDJSON stub)
      3. Strip whitespace from column names
      4. (CSV) Replace inf/-inf with NaN

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file format unsupported or outside allowed directories.
    """
    resolved = resolve_dataset_path(file_path)
    ext = resolved.suffix.lower()

    if ext == ".csv":
        # Full read — EXECUTION path. (UI validation uses a memory-safe reader.)
        # Use resolved path for the actual read to avoid TOCTOU between check and open.
        df = pd.read_csv(resolved)
        df.columns = df.columns.str.strip()
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df

    # .json — EVE Suricata NDJSON format (one JSON object per line).
    # Read a small stub for validation; Phase 1 handles the full file.
    import json as _json
    records = []
    with open(resolved, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
                if isinstance(obj, dict):
                    records.append(obj)
            except Exception:
                continue
            if len(records) >= 100:
                break
    if not records:
        raise ValueError(
            "JSON file contains no valid records. "
            "Expected NDJSON format (one JSON object per line, EVE Suricata)."
        )
    df = pd.json_normalize(records, max_level=1)
    df.columns = df.columns.str.strip()
    return df
