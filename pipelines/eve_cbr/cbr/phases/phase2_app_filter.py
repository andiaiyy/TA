from __future__ import annotations


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

    candidates.append(Path(app_input_path).parent / "split_summary.json")

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
    Supports new incremental format:
        {"apps": {"http": {...}}}

    Supports old flat format:
        {"written_counts": {"http": ...}, "output_files": {"http": ...}}
    """
    apps = summary.get("apps")
    if isinstance(apps, dict) and isinstance(apps.get(app), dict):
        return apps[app]

    written_counts = summary.get("written_counts") if isinstance(summary.get("written_counts"), dict) else {}
    output_files = summary.get("output_files") if isinstance(summary.get("output_files"), dict) else {}

    if app in written_counts or app in output_files:
        return {
            "app": app,
            "written_rows": written_counts.get(app),
            "output_file": output_files.get(app),
            "legacy_summary_format": True,
        }

    return {}


def _read_phase1_summary(app_output_dir: Optional[Path]) -> dict[str, Any]:
    if app_output_dir is None:
        return {}

    p = Path(app_output_dir) / "phase1" / "summary.json"
    if not p.exists():
        return {}

    data = read_json(p, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _validate_file_name(app: str, app_input_path: Path) -> bool:
    name = app_input_path.name.lower()
    return app in name


def run_phase2(
    *,
    cfg: Any,
    app: str,
    app_input_path: Path,
    phase_dir: Path,
    app_output_dir: Optional[Path] = None,
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
    phase1_summary = _read_phase1_summary(app_output_dir)

    file_name_ok = _validate_file_name(app, app_input_path)
    summary_ok = bool(app_block)

    # Phase 2 is validation-only. Do not fail too aggressively unless the input
    # file itself is missing. Missing summary means warning, not data deletion.
    validation_status = "VALIDATED" if file_name_ok and summary_ok else "VALIDATED_WITH_WARNING"

    output_path = phase_dir / "validation_summary.json"

    written_rows = (
        app_block.get("written_rows")
        if app_block.get("written_rows") is not None
        else phase1_summary.get("written_rows")
    )

    summary = {
        "phase": 2,
        "title": "Pre-split Application Validation",
        "status": "completed" if validation_status == "VALIDATED" else "completed_with_warning",
        "validation_status": validation_status,
        "current_run": app.upper(),
        "app": app,
        "input": str(app_input_path),
        "output": str(output_path),
        "generated_at": now_iso(),

        "filtering": "skipped_already_split_by_prepipeline",
        "row_drop": 0,
        "dataset_output_created": False,

        "app_input_exists": True,
        "app_input_size_bytes": int(file_size_bytes(app_input_path)),
        "app_input_size_gib": float(file_size_gib(app_input_path)),
        "file_name_matches_app": bool(file_name_ok),

        "split_summary_path": str(split_summary_path) if split_summary_path else None,
        "prepipeline_app_summary_found": bool(summary_ok),

        "rows": _as_int(written_rows) if written_rows is not None else None,
        "ports_used": app_block.get("ports_used", []),
        "match_reason_counts": app_block.get("match_reason_counts", {}),
        "app_proto_counts": app_block.get("app_proto_counts", {}),
        "event_type_counts": app_block.get("event_type_counts", {}),
        "dest_port_summary": app_block.get("dest_port_summary", {}),
        "app_port_hit_summary": app_block.get("app_port_hit_summary", {}),

        "phase1_summary_used": bool(phase1_summary),
        "methodology_note": (
            "Phase 2 no longer performs application filtering because the pre-pipeline "
            "split script already produced eve_<app>.jsonl. This phase only validates "
            "the active app context and writes a small validation summary."
        ),
    }

    write_json(summary, output_path)

    print("\n" + "=" * 72)
    print("Phase 2 - Pre-split Application Validation")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Input       : {app_input_path}")
    print("Filtering   : skipped - already split by pre-pipeline")
    print(f"Rows        : {summary['rows']:,}" if isinstance(summary["rows"], int) else "Rows        : N/A")
    print(f"Status      : {validation_status}")
    print(f"Output      : {output_path}")
    if validation_status != "VALIDATED":
        if not summary_ok:
            print("Warning     : App block not found in split_summary.json")
        if not file_name_ok:
            print("Warning     : File name does not contain app name")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase2_run = run_phase2
phase2_validate_app = run_phase2
