from __future__ import annotations

"""
Phase 1 - Initial Application Summary

Purpose:
- Do not re-read / parse the full app JSONL.
- Use pre-pipeline split_summary.json when available.
- Show a simple console summary:
    Phase 1 - Initial Application Summary
    Current Run : HTTP
    Reading     : eve_http.jsonl
    Benign      : ...
    Attack      : ...
    Output      : summary.json
- Write a compact summary.json for later phases/reports.

Expected inputs:
- app_input_path: active eve_<app>.jsonl
- split_summary.json from pre-pipeline
"""

from pathlib import Path
from typing import Any, Optional

from ..io_utils import file_size_bytes, file_size_gib, now_iso, read_json, require_file, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


def _normalize_app(app: str) -> str:
    app = str(app).strip().lower()
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app={app!r}. Expected one of {sorted(VALID_APPS)}")
    return app


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _ratio(part: Optional[int], total: Optional[int]) -> Optional[float]:
    if part is None or total is None or total <= 0:
        return None
    return float(part) / float(total) * 100.0


def _fmt_count(value: Optional[int]) -> str:
    if value is None:
        return "N/A"
    return f"{int(value):,}"


def _fmt_ratio(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.4f}%"


def _candidate_split_summaries(
    *,
    cfg: Any,
    app_input_path: Path,
    explicit_path: Optional[Path] = None,
) -> list[Path]:
    candidates: list[Path] = []

    if explicit_path:
        candidates.append(Path(explicit_path))

    cfg_summary = getattr(cfg, "prepipeline_summary_path", None)
    if cfg_summary:
        candidates.append(Path(cfg_summary))

    storage = getattr(cfg, "storage", None)
    if storage is not None:
        split_app_dir = getattr(storage, "split_app_dir", None)
        if split_app_dir:
            candidates.append(Path(split_app_dir) / "split_summary.json")

    # Works if app_input_path still points to split_app/eve_<app>.jsonl.
    candidates.append(Path(app_input_path).parent / "split_summary.json")

    # Deduplicate.
    out: list[Path] = []
    seen = set()
    for p in candidates:
        key = str(p)
        if key not in seen:
            out.append(p)
            seen.add(key)
    return out


def _load_split_summary(candidates: list[Path]) -> tuple[dict[str, Any], Optional[Path]]:
    for path in candidates:
        if path.exists() and path.is_file():
            data = read_json(path, default={}, required=False)
            if isinstance(data, dict):
                return data, path
    return {}, None


def _get_app_block(summary: dict[str, Any], app: str) -> dict[str, Any]:
    """
    Supports both new incremental format:
        {"apps": {"http": {...}}}

    and legacy flat format:
        {"written_counts": {"http": ...}, "output_files": {"http": ...}}
    """
    apps = summary.get("apps")
    if isinstance(apps, dict) and isinstance(apps.get(app), dict):
        return apps[app]

    # Legacy fallback.
    written_counts = summary.get("written_counts") if isinstance(summary.get("written_counts"), dict) else {}
    output_files = summary.get("output_files") if isinstance(summary.get("output_files"), dict) else {}

    if app in written_counts or app in output_files:
        return {
            "app": app,
            "written_rows": written_counts.get(app),
            "output_file": output_files.get(app),
            "label_counts": {},
            "legacy_summary_format": True,
        }

    return {}


def _extract_counts(app_block: dict[str, Any]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Return:
        benign, attack, total

    New pre-pipeline summary should contain:
        label_counts: {"benign": ..., "malicious": ...}

    For older summaries without label_counts, return N/A for benign/attack.
    """
    label_counts = app_block.get("label_counts")
    if isinstance(label_counts, dict) and label_counts:
        benign = _as_int(label_counts.get("benign"))
        attack = _as_int(label_counts.get("malicious"))
        total = benign + attack
        return benign, attack, total

    written = app_block.get("written_rows")
    if written is not None:
        return None, None, _as_int(written)

    return None, None, None


def run_phase1(
    *,
    cfg: Any,
    app: str,
    app_input_path: Path,
    phase_dir: Path,
    prepipeline_summary_path: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    app_input_path = require_file(app_input_path, label=f"{app} app JSONL")
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    split_summary, split_summary_path = _load_split_summary(
        _candidate_split_summaries(
            cfg=cfg,
            app_input_path=app_input_path,
            explicit_path=prepipeline_summary_path,
        )
    )

    app_block = _get_app_block(split_summary, app)
    benign, attack, total = _extract_counts(app_block)

    benign_ratio = _ratio(benign, total)
    attack_ratio = _ratio(attack, total)

    output_path = phase_dir / "summary.json"

    summary = {
        "phase": 1,
        "title": "Initial Application Summary",
        "status": "completed" if app_block else "completed_with_warning",
        "current_run": app.upper(),
        "app": app,
        "reading": str(app_input_path),
        "output": str(output_path),
        "generated_at": now_iso(),

        "split_summary_path": str(split_summary_path) if split_summary_path else None,
        "prepipeline_app_summary_found": bool(app_block),

        "total": total,
        "benign": benign,
        "attack": attack,
        "benign_ratio_percent": benign_ratio,
        "attack_ratio_percent": attack_ratio,

        "input_file_size_bytes": int(file_size_bytes(app_input_path)),
        "input_file_size_gib": float(file_size_gib(app_input_path)),

        "source_counts": {
            "label_counts": app_block.get("label_counts", {}),
            "written_rows": app_block.get("written_rows"),
            "matched_rows": app_block.get("matched_rows"),
        },
        "note": (
            "Phase 1 only reports initial benign/attack evidence from the pre-pipeline summary. "
            "It does not create the final Target label and does not scan the full JSONL again."
        ),
    }

    write_json(summary, output_path)

    print("\n" + "=" * 72)
    print("Phase 1 - Initial Application Summary")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {app_input_path}")
    print(f"Benign      : {_fmt_count(benign)} - {_fmt_ratio(benign_ratio)}")
    print(f"Attack      : {_fmt_count(attack)} - {_fmt_ratio(attack_ratio)}")
    print(f"Output      : {output_path}")
    if not app_block:
        print("Warning     : App summary not found in split_summary.json")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase1_run = run_phase1
phase1_initial_profiling = run_phase1
