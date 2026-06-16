from __future__ import annotations

"""
I/O utilities for the CBR / Suricata EVE large-data pipeline.

Recommended location:
    src/cbr/io_utils.py

Purpose:
- Keep repeated file operations out of phase files.
- Support streaming JSONL processing.
- Support safe JSON/CSV writing.
- Support supervised per-app workflow:
    external archive/storage -> internal working dir -> archive outputs -> cleanup.
"""

import csv
import gzip
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence


# ============================================================
# Optional fast JSON parser
# ============================================================

try:
    import orjson  # type: ignore

    def loads_json_line(line: bytes) -> Dict[str, Any]:
        return orjson.loads(line)

    def dumps_json(obj: Any, *, indent: bool = True) -> bytes:
        if indent:
            return orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY)
        return orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY)

except Exception:

    def loads_json_line(line: bytes) -> Dict[str, Any]:
        return json.loads(line.decode("utf-8", errors="replace"))

    def dumps_json(obj: Any, *, indent: bool = True) -> bytes:
        text = json.dumps(obj, indent=2 if indent else None, ensure_ascii=False, default=str)
        return text.encode("utf-8")


# ============================================================
# Directory / file checks
# ============================================================

def ensure_dir(path: Path | str) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def require_file(path: Path | str, *, label: str = "required file") -> Path:
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def require_dir(path: Path | str, *, label: str = "required directory") -> Path:
    path = Path(path)
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def file_size_bytes(path: Path | str) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    return path.stat().st_size


def file_size_mib(path: Path | str) -> float:
    return file_size_bytes(path) / (1024 * 1024)


def file_size_gib(path: Path | str) -> float:
    return file_size_bytes(path) / (1024 * 1024 * 1024)


def remove_if_exists(path: Path | str) -> None:
    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


# ============================================================
# JSON helpers
# ============================================================

def read_json(path: Path | str, *, default: Any = None, required: bool = True) -> Any:
    path = Path(path)

    if not path.exists():
        if required:
            raise FileNotFoundError(f"JSON file not found: {path}")
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(data: Any, path: Path | str, *, indent: bool = True) -> Path:
    path = ensure_parent(path)
    payload = dumps_json(data, indent=indent)

    with path.open("wb") as f:
        f.write(payload)
        f.write(b"\n")

    return path


def append_jsonl(records: Iterable[Mapping[str, Any]], path: Path | str) -> Path:
    path = ensure_parent(path)

    with path.open("ab") as f:
        for record in records:
            f.write(dumps_json(dict(record), indent=False))
            f.write(b"\n")

    return path


# ============================================================
# JSONL streaming
# ============================================================

def open_maybe_gzip(path: Path | str, mode: str = "rt", encoding: str = "utf-8"):
    """
    Open normal or gzip file based on suffix.

    Examples:
        open_maybe_gzip("data.jsonl", "rb")
        open_maybe_gzip("data.jsonl.gz", "rt")
    """
    path = Path(path)
    if path.suffix.lower() == ".gz":
        return gzip.open(path, mode, encoding=None if "b" in mode else encoding)
    return path.open(mode, encoding=None if "b" in mode else encoding)


def iter_jsonl(
    path: Path | str,
    *,
    skip_empty: bool = True,
    return_errors: bool = False,
) -> Iterator[Dict[str, Any]]:
    """
    Stream JSONL records.

    If return_errors=False:
        malformed lines are skipped.

    If return_errors=True:
        yields dictionaries like:
            {"__error__": "...", "__line_no__": 123}
        for malformed records.
    """
    path = require_file(path, label="JSONL input")

    with open_maybe_gzip(path, "rb") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if skip_empty and not line:
                continue

            try:
                record = loads_json_line(line)
                if isinstance(record, dict):
                    yield record
                else:
                    if return_errors:
                        yield {
                            "__error__": "json_record_is_not_object",
                            "__line_no__": line_no,
                        }
            except Exception as exc:
                if return_errors:
                    yield {
                        "__error__": str(exc),
                        "__line_no__": line_no,
                    }


def count_jsonl_lines(path: Path | str) -> int:
    path = require_file(path, label="JSONL input")
    total = 0
    with open_maybe_gzip(path, "rb") as f:
        for _ in f:
            total += 1
    return total


# ============================================================
# CSV helpers
# ============================================================

def write_csv_rows(
    rows: Iterable[Mapping[str, Any]],
    path: Path | str,
    *,
    fieldnames: Optional[Sequence[str]] = None,
    extrasaction: str = "ignore",
) -> Path:
    """
    Write rows to CSV.

    If fieldnames is None, the first row determines field order.
    """
    path = ensure_parent(path)
    iterator = iter(rows)

    try:
        first = next(iterator)
    except StopIteration:
        with path.open("w", newline="", encoding="utf-8") as f:
            pass
        return path

    if fieldnames is None:
        fieldnames = list(first.keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction=extrasaction)
        writer.writeheader()
        writer.writerow(first)
        for row in iterator:
            writer.writerow(row)

    return path


def append_csv_rows(
    rows: Iterable[Mapping[str, Any]],
    path: Path | str,
    *,
    fieldnames: Sequence[str],
    write_header_if_new: bool = True,
    extrasaction: str = "ignore",
) -> Path:
    path = ensure_parent(path)
    is_new = (not path.exists()) or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction=extrasaction)

        if write_header_if_new and is_new:
            writer.writeheader()

        for row in rows:
            writer.writerow(row)

    return path


def read_csv_dicts(path: Path | str) -> Iterator[Dict[str, str]]:
    path = require_file(path, label="CSV input")
    with open_maybe_gzip(path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield dict(row)


# ============================================================
# Copy / archive / cleanup
# ============================================================

def copy_file(
    src: Path | str,
    dst: Path | str,
    *,
    overwrite: bool = False,
    label: str = "file",
) -> Path:
    src = require_file(src, label=f"source {label}")
    dst = ensure_parent(dst)

    if dst.exists() and not overwrite:
        return dst

    shutil.copy2(src, dst)
    return dst


def copy_tree(
    src: Path | str,
    dst: Path | str,
    *,
    overwrite: bool = True,
    ignore_names: Optional[Sequence[str]] = None,
) -> Path:
    src = require_dir(src, label="source directory")
    dst = Path(dst)

    if dst.exists():
        if overwrite:
            shutil.rmtree(dst)
        else:
            return dst

    ignore = None
    if ignore_names:
        ignore = shutil.ignore_patterns(*ignore_names)

    shutil.copytree(src, dst, ignore=ignore)
    return dst


def move_tree(
    src: Path | str,
    dst: Path | str,
    *,
    overwrite: bool = True,
) -> Path:
    src = require_dir(src, label="source directory")
    dst = Path(dst)

    if dst.exists() and overwrite:
        shutil.rmtree(dst)

    ensure_dir(dst.parent)
    shutil.move(str(src), str(dst))
    return dst


def cleanup_dir(path: Path | str, *, keep_dir: bool = False) -> None:
    path = Path(path)

    if not path.exists():
        return

    if keep_dir:
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        shutil.rmtree(path)


def archive_app_outputs(
    work_output_dir: Path | str,
    archive_output_dir: Path | str,
    *,
    overwrite: bool = True,
) -> Path:
    """
    Copy current app outputs from internal SSD to external archive.

    This intentionally copies rather than moves, so the caller can verify archive
    success before deleting the internal working directory.
    """
    return copy_tree(work_output_dir, archive_output_dir, overwrite=overwrite)


# ============================================================
# Compression helpers
# ============================================================

def gzip_file(
    src: Path | str,
    dst: Optional[Path | str] = None,
    *,
    remove_source: bool = False,
    chunk_size: int = 1024 * 1024 * 16,
) -> Path:
    """
    Compress a file to gzip.

    Used after training/evaluation when archiving CSV files.
    """
    src = require_file(src, label="source file for gzip")

    if dst is None:
        dst = src.with_suffix(src.suffix + ".gz")
    dst = ensure_parent(dst)

    with src.open("rb") as f_in, gzip.open(dst, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out, length=chunk_size)

    if remove_source:
        src.unlink()

    return dst


def gunzip_file(
    src: Path | str,
    dst: Optional[Path | str] = None,
    *,
    remove_source: bool = False,
    chunk_size: int = 1024 * 1024 * 16,
) -> Path:
    src = require_file(src, label="source gzip file")

    if dst is None:
        if src.suffix.lower() != ".gz":
            raise ValueError(f"Cannot infer destination for non-.gz file: {src}")
        dst = src.with_suffix("")
    dst = ensure_parent(dst)

    with gzip.open(src, "rb") as f_in, Path(dst).open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out, length=chunk_size)

    if remove_source:
        src.unlink()

    return Path(dst)


# ============================================================
# Progress / logging helpers
# ============================================================

class ProgressPrinter:
    """
    Lightweight progress printer for long streaming phases.

    Example:
        progress = ProgressPrinter("PHASE 8 http", every=1_000_000)
        for row in rows:
            progress.update()
        progress.done()
    """

    def __init__(self, label: str, *, every: int = 1_000_000) -> None:
        self.label = label
        self.every = max(1, int(every))
        self.count = 0
        self.start = time.time()
        self.last_print = self.start

    def update(self, n: int = 1, *, force: bool = False) -> None:
        self.count += n
        if force or self.count % self.every == 0:
            now = time.time()
            elapsed = max(now - self.start, 1e-9)
            speed = self.count / elapsed
            print(
                f"[{self.label}] rows={self.count:,} | "
                f"elapsed={elapsed/60:.2f} min | "
                f"speed={speed:,.0f} rows/s"
            )
            self.last_print = now

    def done(self) -> Dict[str, Any]:
        elapsed = time.time() - self.start
        speed = self.count / elapsed if elapsed > 0 else 0.0
        print(
            f"[{self.label}] DONE | rows={self.count:,} | "
            f"elapsed={elapsed/60:.2f} min | speed={speed:,.0f} rows/s"
        )
        return {
            "label": self.label,
            "rows": self.count,
            "elapsed_seconds": elapsed,
            "rows_per_second": speed,
        }


# ============================================================
# Manifest helpers
# ============================================================

def write_manifest(
    path: Path | str,
    *,
    app: str,
    phase: str,
    files: Mapping[str, Path | str],
    extra: Optional[Mapping[str, Any]] = None,
) -> Path:
    payload: Dict[str, Any] = {
        "app": app,
        "phase": phase,
        "files": {key: str(value) for key, value in files.items()},
        "created_at_unix": time.time(),
    }

    if extra:
        payload.update(dict(extra))

    return write_json(payload, path)


def summarize_files(files: Mapping[str, Path | str]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}

    for name, path_value in files.items():
        path = Path(path_value)
        summary[name] = {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": file_size_bytes(path) if path.exists() else 0,
            "size_mib": round(file_size_mib(path), 3) if path.exists() else 0.0,
        }

    return summary


# ============================================================
# Small safety helpers
# ============================================================

def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_divide(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    num = safe_float(numerator, 0.0)
    den = safe_float(denominator, 0.0)
    if den == 0.0:
        return default
    return num / den


def now_unix() -> float:
    return time.time()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
