from __future__ import annotations

"""
Phase 11 - Modeling Readiness / Split Audit

Purpose:
- Do NOT split again. Train/test was already created in Phase 8.
- Do NOT read raw eve_<app>.jsonl.
- Do NOT read full train.csv/test.csv.
- Do NOT write another modeling dataset.
- Validate that Phase 8 train/test outputs exist.
- Read Phase 8 summaries and Phase 10 feature policies.
- Produce a modeling manifest for Phase 12/13/14.

Best practice:
- Phase 8 owns dataset materialization and split.
- Phase 10 owns correlation/leakage screening.
- Phase 11 only checks readiness and freezes the modeling feature contract.

Input:
    phase8/export_summary.json
    phase8/split_summary.json
    phase8/schema.json
    phase8/feature_roles.json
    phase8/label_distribution.csv
    phase10/features_to_drop.json
    phase10/features_for_modeling.json
    phase10/corr_NOLEAK.csv

Output:
    phase11_<app>_modeling_manifest.json
    phase11_<app>_readiness_summary.json
    phase11_<app>_modeling_features.txt
    phase11_<app>_train_test_distribution.csv

Generic aliases:
    modeling_manifest.json
    readiness_summary.json
    modeling_features.txt
    train_test_distribution.csv
    summary.json
"""

import csv
import json
from pathlib import Path
from typing import Any, Optional

from ..io_utils import file_size_bytes, file_size_gib, now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Helpers
# ============================================================

def _normalize_app(app: str) -> str:
    app = str(app).strip().lower()
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app={app!r}. Expected one of {sorted(VALID_APPS)}")
    return app


def _phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except Exception:
        return []


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _as_int_dict(obj: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        try:
            out[str(k)] = int(v)
        except Exception:
            continue
    return out


def _write_text_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _extract_modeling_features(features_for_modeling: dict[str, Any], corr_noleak_rows: list[dict[str, Any]]) -> list[str]:
    for key in ("approved_numeric_features", "features", "modeling_features", "approved_features"):
        value = features_for_modeling.get(key)
        if isinstance(value, list) and value:
            return sorted({str(x) for x in value if str(x).strip()})

    ranked = features_for_modeling.get("ranked_by_abs_correlation_noleak")
    if isinstance(ranked, list) and ranked:
        return [str(x) for x in ranked if str(x).strip()]

    out: list[str] = []
    for row in corr_noleak_rows:
        f = str(row.get("Feature", "")).strip()
        if f and f not in out:
            out.append(f)
    return out


def _train_test_paths(export_summary: dict[str, Any], split_summary: dict[str, Any]) -> tuple[Optional[Path], Optional[Path]]:
    train_raw = export_summary.get("train_path") or split_summary.get("train_path")
    test_raw = export_summary.get("test_path") or split_summary.get("test_path")

    train_path = Path(train_raw) if train_raw else None
    test_path = Path(test_raw) if test_raw else None
    return train_path, test_path


def _split_counts(export_summary: dict[str, Any], split_summary: dict[str, Any]) -> dict[str, int]:
    train = _safe_int(export_summary.get("train_rows"), _safe_int(split_summary.get("train_rows"), 0))
    test = _safe_int(export_summary.get("test_rows"), _safe_int(split_summary.get("test_rows"), 0))
    return {"train": train, "test": test, "total": train + test}


def _global_target_counts(export_summary: dict[str, Any]) -> dict[str, int]:
    return _as_int_dict(export_summary.get("target_counts"))


def _per_split_target_counts(export_summary: dict[str, Any], split_summary: dict[str, Any]) -> dict[str, dict[str, int]]:
    """
    Preferred shape after Phase 8 minor patch:
        export_summary["target_counts_by_split"] = {
            "train": {"0": ..., "1": ...},
            "test": {"0": ..., "1": ...}
        }

    Also supports:
        train_target_counts / test_target_counts
    """
    by_split = export_summary.get("target_counts_by_split") or split_summary.get("target_counts_by_split")
    if isinstance(by_split, dict):
        return {
            "train": _as_int_dict(by_split.get("train")),
            "test": _as_int_dict(by_split.get("test")),
        }

    train = (
        _as_int_dict(export_summary.get("train_target_counts"))
        or _as_int_dict(split_summary.get("train_target_counts"))
    )
    test = (
        _as_int_dict(export_summary.get("test_target_counts"))
        or _as_int_dict(split_summary.get("test_target_counts"))
    )

    if train or test:
        return {"train": train, "test": test}

    return {"train": {}, "test": {}}


def _distribution_rows(
    *,
    split_counts: dict[str, int],
    global_target_counts: dict[str, int],
    target_counts_by_split: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for split in ("train", "test"):
        total = int(split_counts.get(split, 0))
        class_counts = target_counts_by_split.get(split, {})
        benign = int(class_counts.get("0", 0))
        attack = int(class_counts.get("1", 0))

        if not class_counts:
            rows.append({
                "split": split,
                "label": "ALL",
                "count": total,
                "ratio_percent": 100.0 if total > 0 else 0.0,
                "source": "phase8_split_summary_rows_only",
                "note": "Per-split benign/attack counts unavailable. Patch Phase 8 to store target_counts_by_split for exact values.",
            })
            continue

        for label, count in (("benign", benign), ("attack", attack)):
            rows.append({
                "split": split,
                "label": label,
                "count": int(count),
                "ratio_percent": float(count / total * 100.0) if total > 0 else 0.0,
                "source": "phase8_target_counts_by_split",
                "note": "",
            })

    global_total = sum(global_target_counts.values())
    if global_target_counts:
        rows.append({
            "split": "all",
            "label": "benign",
            "count": int(global_target_counts.get("0", 0)),
            "ratio_percent": float(global_target_counts.get("0", 0) / global_total * 100.0) if global_total > 0 else 0.0,
            "source": "phase8_export_summary_global_target_counts",
            "note": "",
        })
        rows.append({
            "split": "all",
            "label": "attack",
            "count": int(global_target_counts.get("1", 0)),
            "ratio_percent": float(global_target_counts.get("1", 0) / global_total * 100.0) if global_total > 0 else 0.0,
            "source": "phase8_export_summary_global_target_counts",
            "note": "",
        })

    return rows


def _schema_column_count(schema: dict[str, Any]) -> int:
    cols = schema.get("columns")
    if isinstance(cols, list):
        return len(cols)
    return _safe_int(schema.get("column_count"), 0)


def _file_status(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {
            "path": None,
            "exists": False,
            "size_bytes": 0,
            "size_gib": 0.0,
        }
    exists = path.exists()
    return {
        "path": str(path),
        "exists": bool(exists),
        "size_bytes": int(file_size_bytes(path)) if exists else 0,
        "size_gib": float(file_size_gib(path)) if exists else 0.0,
    }


# ============================================================
# Runner
# ============================================================

def run_phase11(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    phase8_dir = _phase_dir(phase_dir, "phase8")
    phase10_dir = _phase_dir(phase_dir, "phase10")

    export_summary_path = phase8_dir / "export_summary.json"
    split_summary_path = phase8_dir / "split_summary.json"
    schema_path = phase8_dir / "schema.json"
    feature_roles_path = phase8_dir / "feature_roles.json"
    label_distribution_path = phase8_dir / "label_distribution.csv"

    features_to_drop_path = phase10_dir / "features_to_drop.json"
    features_for_modeling_path = phase10_dir / "features_for_modeling.json"
    corr_noleak_path = phase10_dir / "corr_NOLEAK.csv"

    export_summary = _read_optional_json(export_summary_path)
    split_summary = _read_optional_json(split_summary_path)
    schema = _read_optional_json(schema_path)
    feature_roles = _read_optional_json(feature_roles_path)
    features_to_drop = _read_optional_json(features_to_drop_path)
    features_for_modeling = _read_optional_json(features_for_modeling_path)
    corr_noleak_rows = _read_csv_rows(corr_noleak_path)
    label_distribution_rows = _read_csv_rows(label_distribution_path)

    train_path, test_path = _train_test_paths(export_summary, split_summary)
    split_counts = _split_counts(export_summary, split_summary)
    global_counts = _global_target_counts(export_summary)
    counts_by_split = _per_split_target_counts(export_summary, split_summary)

    modeling_features = _extract_modeling_features(features_for_modeling, corr_noleak_rows)
    drop_columns = features_to_drop.get("drop_columns", [])
    if not isinstance(drop_columns, list):
        drop_columns = []

    distribution_rows = _distribution_rows(
        split_counts=split_counts,
        global_target_counts=global_counts,
        target_counts_by_split=counts_by_split,
    )

    prefix = f"phase11_{app}"

    manifest_path = phase_dir / f"{prefix}_modeling_manifest.json"
    readiness_path = phase_dir / f"{prefix}_readiness_summary.json"
    features_txt_path = phase_dir / f"{prefix}_modeling_features.txt"
    distribution_csv_path = phase_dir / f"{prefix}_train_test_distribution.csv"

    manifest_alias = phase_dir / "modeling_manifest.json"
    readiness_alias = phase_dir / "readiness_summary.json"
    features_txt_alias = phase_dir / "modeling_features.txt"
    distribution_csv_alias = phase_dir / "train_test_distribution.csv"
    summary_alias = phase_dir / "summary.json"

    train_status = _file_status(train_path)
    test_status = _file_status(test_path)

    warnings: list[str] = []
    if not train_status["exists"]:
        warnings.append("Phase 8 train file does not exist.")
    if not test_status["exists"]:
        warnings.append("Phase 8 test file does not exist.")
    if not counts_by_split.get("train") or not counts_by_split.get("test"):
        warnings.append(
            "Exact benign/attack distribution per train/test is not available. "
            "Add target_counts_by_split to Phase 8 for exact Phase 11 reporting."
        )
    if not modeling_features:
        warnings.append("Modeling feature list is empty. Check Phase 10 features_for_modeling.json.")
    if not export_summary:
        warnings.append("Phase 8 export_summary.json not found or empty.")
    if not features_to_drop:
        warnings.append("Phase 10 features_to_drop.json not found or empty.")

    readiness_ok = (
        train_status["exists"]
        and test_status["exists"]
        and bool(modeling_features)
        and bool(export_summary)
    )

    manifest = {
        "phase": 11,
        "title": "Modeling Readiness / Split Audit",
        "app": app,
        "created_at": now_iso(),
        "status": "ready" if readiness_ok else "ready_with_warning",

        "read_policy": {
            "raw_jsonl_reread": False,
            "train_test_full_reread": False,
            "dataset_resplit": False,
            "source": "Phase 8 summaries + Phase 10 feature policy",
        },

        "dataset_files": {
            "train": train_status,
            "test": test_status,
        },

        "target_column": (
            getattr(getattr(cfg, "split", None), "target_column", None)
            or export_summary.get("target_column")
            or split_summary.get("target_column")
            or "Target_refined"
        ),

        "split": {
            "strategy": split_summary.get("split_strategy") or export_summary.get("split_strategy"),
            "train_rows": int(split_counts.get("train", 0)),
            "test_rows": int(split_counts.get("test", 0)),
            "total_rows": int(split_counts.get("total", 0)),
            "global_target_counts": global_counts,
            "target_counts_by_split": counts_by_split,
            "per_split_target_counts_available": bool(counts_by_split.get("train") and counts_by_split.get("test")),
        },

        "features": {
            "schema_column_count": int(_schema_column_count(schema)),
            "feature_roles_count": int(len(feature_roles)) if isinstance(feature_roles, dict) else 0,
            "drop_columns_count": int(len(drop_columns)),
            "modeling_feature_count": int(len(modeling_features)),
            "modeling_features": modeling_features,
            "drop_columns": sorted(str(x) for x in drop_columns),
        },

        "upstream": {
            "phase8_export_summary": str(export_summary_path),
            "phase8_split_summary": str(split_summary_path),
            "phase8_schema": str(schema_path),
            "phase8_feature_roles": str(feature_roles_path),
            "phase8_label_distribution": str(label_distribution_path),
            "phase10_features_to_drop": str(features_to_drop_path),
            "phase10_features_for_modeling": str(features_for_modeling_path),
            "phase10_corr_noleak": str(corr_noleak_path),
        },

        "warnings": warnings,
        "next_phase_contract": {
            "phase12_should_read": "modeling_manifest.json",
            "phase12_should_use_train_file": str(train_path) if train_path else None,
            "phase12_should_use_modeling_features": "modeling_features.txt",
            "phase12_should_not_resplit": True,
        },
    }

    readiness_summary = {
        "phase": 11,
        "title": "Modeling Readiness / Split Audit",
        "status": "completed" if readiness_ok else "completed_with_warning",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),

        "train_rows": int(split_counts.get("train", 0)),
        "test_rows": int(split_counts.get("test", 0)),
        "total_rows": int(split_counts.get("total", 0)),

        "train_target_counts": counts_by_split.get("train", {}),
        "test_target_counts": counts_by_split.get("test", {}),
        "global_target_counts": global_counts,
        "per_split_target_counts_available": bool(counts_by_split.get("train") and counts_by_split.get("test")),

        "modeling_feature_count": int(len(modeling_features)),
        "drop_columns_count": int(len(drop_columns)),
        "train_file_exists": bool(train_status["exists"]),
        "test_file_exists": bool(test_status["exists"]),
        "warnings": warnings,

        "output": {
            "modeling_manifest": str(manifest_path),
            "readiness_summary": str(readiness_path),
            "modeling_features": str(features_txt_path),
            "train_test_distribution": str(distribution_csv_path),
        },
        "note": (
            "Phase 11 does not split again. It audits the Phase 8 split and freezes the "
            "Phase 10 no-leak modeling feature contract."
        ),
    }

    write_json(manifest, manifest_path)
    write_json(manifest, manifest_alias)

    write_json(readiness_summary, readiness_path)
    write_json(readiness_summary, readiness_alias)
    write_json(readiness_summary, summary_alias)

    _write_text_lines(features_txt_path, modeling_features)
    _write_text_lines(features_txt_alias, modeling_features)

    _write_csv(
        distribution_csv_path,
        distribution_rows,
        ["split", "label", "count", "ratio_percent", "source", "note"],
    )
    _write_csv(
        distribution_csv_alias,
        distribution_rows,
        ["split", "label", "count", "ratio_percent", "source", "note"],
    )

    print("\n" + "=" * 72)
    print("Phase 11 - Modeling Readiness / Split Audit")
    print("=" * 72)
    print(f"Current Run      : {app.upper()}")
    print(f"Train Rows       : {split_counts.get('train', 0):,}")
    print(f"Test Rows        : {split_counts.get('test', 0):,}")

    train_counts = counts_by_split.get("train", {})
    test_counts = counts_by_split.get("test", {})
    if train_counts and test_counts:
        print(f"Train Benign     : {int(train_counts.get('0', 0)):,}")
        print(f"Train Attack     : {int(train_counts.get('1', 0)):,}")
        print(f"Test Benign      : {int(test_counts.get('0', 0)):,}")
        print(f"Test Attack      : {int(test_counts.get('1', 0)):,}")
    else:
        print("Train/Test Label : unavailable in current Phase 8 summary")

    print(f"Model Features   : {len(modeling_features):,}")
    print(f"Drop Columns     : {len(drop_columns):,}")
    print(f"Output           : {readiness_path}")
    if warnings:
        print(f"Warnings         : {len(warnings)}")
    print("=" * 72 + "\n")

    return readiness_summary


# Backward-compatible aliases for pipeline fallback registry.
phase11_run = run_phase11
phase11_modeling_preparation = run_phase11
phase11_modeling_split = run_phase11
