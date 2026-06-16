from __future__ import annotations

"""
Phase 7 - Cleaning Policy Builder

Purpose:
- Do NOT clean a full dataset here.
- Do NOT read Phase 6 shards.
- Do NOT write a cleaned Parquet/CSV dataset.
- Build cleaning, dtype, leakage-drop, and training-feature policies.
- Phase 8 applies these policies while exporting the final train/test dataset.

Input:
    phase5/feature_manifest.json
    phase5/base_feature_schema.json
    phase6/computed_feature_rules.json
    phase6/computed_feature_schema.json
    phase4/label_policy.json optional

Output:
    phase7_<app>_cleaning_policy.json
    phase7_<app>_final_schema.json
    phase7_<app>_leakage_drop_list.json
    phase7_<app>_training_feature_list.json
    phase7_<app>_summary.json

Generic aliases:
    cleaning_policy.json
    final_schema.json
    leakage_drop_list.json
    training_feature_list.json
    summary.json
"""

from collections import Counter
from pathlib import Path
from typing import Any

from ..io_utils import now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Leakage and helper column policy
# ============================================================

TARGET_COLUMNS = {
    "Target_alert",
    "Target_refined",
    "Target",
}

LABEL_AUDIT_COLUMNS = {
    "label_source",
    "refinement_reason",
    "label_reason",
    "label_status",
    "label_status_final",
    "label_confidence",
    "suspicious_by_probe",
}

ALERT_DERIVED_COLUMNS = {
    "has_alert",
    "alert_category",
    "alert_severity",
    "alert_signature",
    "alert_signature_id",
    "alert_gid",
    "alert_rev",
    "alert_action",
    "alert_metadata",
    "alert_count_window",
    "valid_alert_count_window",
}

PROBE_AUDIT_COLUMNS = {
    "probe_score_with_alert",
    "probe_level",
    "probe_reason",
    "is_suspicious_window",
    "fanout_high",
}

REFINEMENT_EVIDENCE_COLUMNS = {
    "probe_score_no_alert",
    "same_alert_window",
    "near_alert_window",
    "matched_alert_window",
    "minutes_to_alert_window",
}

IDENTIFIER_SPLIT_AUDIT_COLUMNS = {
    "timestamp",
    "src_ip",
    "dest_ip",
    "window_start",
    "first_seen",
    "last_seen",
}

HIGH_RISK_HASH_COLUMNS = {
    "event_type_h",
}

# These are not always leakage, but are unsafe as direct modeling inputs in this
# thesis pipeline because they are strongly tied to IDS/label construction.
PATTERN_DROP_PREFIXES = (
    "alert_",
    "label_",
    "evidence_",
)

PATTERN_DROP_SUBSTRINGS = (
    "_raw",
)


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


def _column_name_set_from_schema(schema: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    cols = schema.get("columns", [])
    if isinstance(cols, list):
        for c in cols:
            if isinstance(c, dict) and c.get("name"):
                out.add(str(c["name"]))
    return out


def _column_specs_from_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    cols = schema.get("columns", [])
    if not isinstance(cols, list):
        return []
    return [c for c in cols if isinstance(c, dict) and c.get("name")]


def _is_drop_column(name: str, spec: dict[str, Any] | None = None) -> tuple[bool, str]:
    n = str(name)
    nl = n.lower()

    direct_drop = (
        TARGET_COLUMNS
        | LABEL_AUDIT_COLUMNS
        | ALERT_DERIVED_COLUMNS
        | PROBE_AUDIT_COLUMNS
        | REFINEMENT_EVIDENCE_COLUMNS
        | IDENTIFIER_SPLIT_AUDIT_COLUMNS
        | HIGH_RISK_HASH_COLUMNS
    )

    if n in direct_drop or nl in {x.lower() for x in direct_drop}:
        return True, "direct_policy_drop"

    if any(nl.startswith(prefix) for prefix in PATTERN_DROP_PREFIXES):
        return True, "prefix_policy_drop"

    if any(substr in nl for substr in PATTERN_DROP_SUBSTRINGS):
        return True, "raw_or_audit_string_drop"

    if spec:
        role = str(spec.get("role", "")).lower()
        leakage_risk = str(spec.get("leakage_risk", "")).lower()
        training_candidate = bool(spec.get("training_candidate", False))

        if leakage_risk in {"high", "target"}:
            return True, f"schema_leakage_risk_{leakage_risk}"

        if role in {"label", "audit_label", "label_evidence/audit", "audit/refinement_evidence"}:
            return True, f"schema_role_{role}"

        if not training_candidate and leakage_risk != "low":
            return True, "schema_non_training_risky"

    return False, ""


def _safe_dtype(dtype: str) -> str:
    d = str(dtype or "").lower()
    if "int8" in d:
        return "int8"
    if "int16" in d:
        return "int16"
    if "int32" in d or d == "int":
        return "int32"
    if "int64" in d:
        return "int64"
    if "float32" in d or "float" in d:
        return "float32"
    if "datetime" in d:
        return "datetime"
    if "categorical" in d:
        return "category_or_hash"
    if "string" in d:
        return "string"
    return "auto"


def _build_combined_specs(
    base_schema: dict[str, Any],
    computed_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}

    for spec in _column_specs_from_schema(base_schema):
        name = str(spec["name"])
        combined[name] = {
            "name": name,
            "dtype": _safe_dtype(str(spec.get("dtype", ""))),
            "role": spec.get("role", "base"),
            "group": spec.get("group", "base"),
            "source_phase": "phase5",
            "training_candidate": bool(spec.get("training_candidate", False)),
            "leakage_risk": spec.get("leakage_risk", "low"),
        }

    for spec in _column_specs_from_schema(computed_schema):
        name = str(spec["name"])
        combined[name] = {
            "name": name,
            "dtype": _safe_dtype(str(spec.get("dtype", ""))),
            "role": "computed_feature",
            "group": spec.get("group", "computed"),
            "source_phase": "phase6",
            "training_candidate": bool(spec.get("training_candidate", False)),
            "leakage_risk": spec.get("leakage_risk", "low"),
            "inputs": spec.get("inputs", []),
        }

    return list(combined.values())


def _build_leakage_drop_list(specs: list[dict[str, Any]]) -> dict[str, Any]:
    explicit_names = set()
    reasons: dict[str, str] = {}

    for spec in specs:
        name = str(spec["name"])
        should_drop, reason = _is_drop_column(name, spec)
        if should_drop:
            explicit_names.add(name)
            reasons[name] = reason

    # Ensure critical drops exist even if not declared in schema preview.
    critical = (
        TARGET_COLUMNS
        | LABEL_AUDIT_COLUMNS
        | ALERT_DERIVED_COLUMNS
        | PROBE_AUDIT_COLUMNS
        | REFINEMENT_EVIDENCE_COLUMNS
        | IDENTIFIER_SPLIT_AUDIT_COLUMNS
        | HIGH_RISK_HASH_COLUMNS
    )
    for name in critical:
        explicit_names.add(name)
        reasons.setdefault(name, "critical_policy_drop")

    return {
        "phase": 7,
        "title": "Leakage Drop List",
        "created_at": now_iso(),
        "drop_columns": sorted(explicit_names),
        "drop_reasons": {k: reasons[k] for k in sorted(reasons)},
        "drop_prefixes": list(PATTERN_DROP_PREFIXES),
        "drop_substrings": list(PATTERN_DROP_SUBSTRINGS),
        "target_columns": sorted(TARGET_COLUMNS),
        "note": (
            "This list is applied before feature selection/modeling. "
            "Phase 8 may keep audit columns in exported files for traceability, "
            "but Phase 10/11 must exclude them from training features."
        ),
    }


def _build_training_feature_list(
    specs: list[dict[str, Any]],
    leakage_drop: dict[str, Any],
) -> dict[str, Any]:
    drop_cols = set(leakage_drop.get("drop_columns", []))
    approved: list[str] = []
    medium_risk_candidates: list[str] = []
    rejected: dict[str, str] = {}

    for spec in specs:
        name = str(spec["name"])
        should_drop, reason = _is_drop_column(name, spec)

        if name in drop_cols or should_drop:
            rejected[name] = reason or "in_drop_list"
            continue

        if not bool(spec.get("training_candidate", False)):
            rejected[name] = "not_training_candidate_in_schema"
            continue

        risk = str(spec.get("leakage_risk", "low")).lower()
        if risk == "low":
            approved.append(name)
        elif risk == "medium":
            medium_risk_candidates.append(name)
        else:
            rejected[name] = f"leakage_risk_{risk}"

    return {
        "phase": 7,
        "title": "Training Feature Candidate List",
        "created_at": now_iso(),
        "target_column": "Target_refined",
        "approved_low_risk_features": sorted(set(approved)),
        "medium_risk_review_features": sorted(set(medium_risk_candidates)),
        "rejected_features": rejected,
        "policy": {
            "use_for_modeling_by_default": "approved_low_risk_features",
            "medium_risk_requires_phase10_approval": True,
            "drop_all_audit_label_alert_columns": True,
        },
        "note": (
            "This is a pre-leakage-check feature list. Phase 10 correlation/leakage "
            "and Phase 11 modeling preparation may further reduce it."
        ),
    }


def _build_cleaning_policy(
    *,
    app: str,
    leakage_drop: dict[str, Any],
) -> dict[str, Any]:
    return {
        "phase": 7,
        "title": "Cleaning Policy",
        "app": app,
        "created_at": now_iso(),
        "mode": "policy_only_no_dataset_output",

        "missing_value_policy": {
            "numeric": "fillna_0_and_replace_inf_0",
            "categorical": "fill_unknown_then_stable_hash_if_used_for_modeling",
            "string_audit": "fill_unknown_and_keep_only_for_audit",
            "timestamp": "parse_to_utc; invalid_timestamp_to_zero_for_derived_time_features",
            "ip": "keep_for_split_audit_then_drop_before_modeling",
        },

        "dtype_policy": {
            "binary_flags": "int8",
            "small_integer": "int16_or_int32",
            "continuous_numeric": "float32",
            "categorical_hash": "int32",
            "target": "int8",
            "audit_strings": "string",
        },

        "sanitization_policy": {
            "replace_positive_inf": 0,
            "replace_negative_inf": 0,
            "replace_nan_numeric": 0,
            "strip_empty_string": "unknown",
            "invalid_numeric_parse": 0,
            "invalid_ip_parse": 0,
        },

        "modeling_exclusion_policy": {
            "drop_columns": leakage_drop.get("drop_columns", []),
            "drop_prefixes": leakage_drop.get("drop_prefixes", []),
            "drop_substrings": leakage_drop.get("drop_substrings", []),
        },

        "phase8_application_note": (
            "Phase 8 applies this policy while streaming eve_<app>.jsonl and writing train/test. "
            "No full clean dataset checkpoint is created in Phase 7."
        ),
    }


def _build_final_schema(
    *,
    app: str,
    specs: list[dict[str, Any]],
    leakage_drop: dict[str, Any],
) -> dict[str, Any]:
    drop_cols = set(leakage_drop.get("drop_columns", []))
    final_columns: list[dict[str, Any]] = []

    for spec in specs:
        name = str(spec["name"])
        should_drop, reason = _is_drop_column(name, spec)
        final_columns.append({
            "name": name,
            "dtype": spec.get("dtype", "auto"),
            "role": spec.get("role", ""),
            "group": spec.get("group", ""),
            "source_phase": spec.get("source_phase", ""),
            "training_candidate": bool(spec.get("training_candidate", False)),
            "leakage_risk": spec.get("leakage_risk", "low"),
            "drop_before_modeling": bool(name in drop_cols or should_drop),
            "drop_reason": reason if (name in drop_cols or should_drop) else "",
        })

    return {
        "phase": 7,
        "title": "Final Schema Policy",
        "app": app,
        "created_at": now_iso(),
        "target_column": "Target_refined",
        "columns": final_columns,
        "column_count": int(len(final_columns)),
        "note": (
            "Schema is declarative. Phase 8 materializes actual columns and may add "
            "summary-only diagnostics such as feature availability and missing counts."
        ),
    }


# ============================================================
# Runner
# ============================================================

def run_phase7(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    app_input_path: Path | None = None,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    phase5_dir = _phase_dir(phase_dir, "phase5")
    phase6_dir = _phase_dir(phase_dir, "phase6")
    phase4_dir = _phase_dir(phase_dir, "phase4")

    base_schema_path = phase5_dir / "base_feature_schema.json"
    feature_manifest_path = phase5_dir / "feature_manifest.json"
    computed_schema_path = phase6_dir / "computed_feature_schema.json"
    computed_rules_path = phase6_dir / "computed_feature_rules.json"
    label_policy_path = phase4_dir / "label_policy.json"

    base_schema = _read_optional_json(base_schema_path)
    feature_manifest = _read_optional_json(feature_manifest_path)
    computed_schema = _read_optional_json(computed_schema_path)
    computed_rules = _read_optional_json(computed_rules_path)
    label_policy = _read_optional_json(label_policy_path)

    specs = _build_combined_specs(base_schema, computed_schema)
    leakage_drop = _build_leakage_drop_list(specs)
    training_features = _build_training_feature_list(specs, leakage_drop)
    cleaning_policy = _build_cleaning_policy(app=app, leakage_drop=leakage_drop)
    final_schema = _build_final_schema(app=app, specs=specs, leakage_drop=leakage_drop)

    prefix = f"phase7_{app}"

    cleaning_policy_path = phase_dir / f"{prefix}_cleaning_policy.json"
    final_schema_path = phase_dir / f"{prefix}_final_schema.json"
    leakage_drop_path = phase_dir / f"{prefix}_leakage_drop_list.json"
    training_feature_path = phase_dir / f"{prefix}_training_feature_list.json"
    summary_path = phase_dir / f"{prefix}_summary.json"

    cleaning_policy_alias = phase_dir / "cleaning_policy.json"
    final_schema_alias = phase_dir / "final_schema.json"
    leakage_drop_alias = phase_dir / "leakage_drop_list.json"
    training_feature_alias = phase_dir / "training_feature_list.json"
    summary_alias = phase_dir / "summary.json"

    print("\n" + "=" * 72)
    print("Phase 7 - Cleaning Policy")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {base_schema_path}")
    print("Mode        : policy/schema only")
    print("=" * 72)

    write_json(cleaning_policy, cleaning_policy_path)
    write_json(cleaning_policy, cleaning_policy_alias)

    write_json(final_schema, final_schema_path)
    write_json(final_schema, final_schema_alias)

    write_json(leakage_drop, leakage_drop_path)
    write_json(leakage_drop, leakage_drop_alias)

    write_json(training_features, training_feature_path)
    write_json(training_features, training_feature_alias)

    group_counts = Counter(str(spec.get("group", "unknown")) for spec in specs)
    source_counts = Counter(str(spec.get("source_phase", "unknown")) for spec in specs)

    summary = {
        "phase": 7,
        "title": "Cleaning Policy",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),

        "input": {
            "phase5_base_feature_schema": str(base_schema_path),
            "phase5_feature_manifest": str(feature_manifest_path),
            "phase6_computed_feature_schema": str(computed_schema_path),
            "phase6_computed_feature_rules": str(computed_rules_path),
            "phase4_label_policy": str(label_policy_path),
            "phase5_base_schema_found": bool(base_schema),
            "phase5_manifest_found": bool(feature_manifest),
            "phase6_computed_schema_found": bool(computed_schema),
            "phase6_computed_rules_found": bool(computed_rules),
            "phase4_label_policy_found": bool(label_policy),
            "app_input_path": str(app_input_path) if app_input_path else None,
        },

        "mode": "policy_only_no_dataset_output",
        "dataset_output_created": False,
        "full_scan": False,

        "schema_column_count": int(len(specs)),
        "schema_group_counts": {str(k): int(v) for k, v in group_counts.items()},
        "schema_source_counts": {str(k): int(v) for k, v in source_counts.items()},

        "drop_columns_count": int(len(leakage_drop.get("drop_columns", []))),
        "approved_low_risk_feature_count": int(len(training_features.get("approved_low_risk_features", []))),
        "medium_risk_review_feature_count": int(len(training_features.get("medium_risk_review_features", []))),
        "rejected_feature_count": int(len(training_features.get("rejected_features", {}))),

        "output": {
            "cleaning_policy": str(cleaning_policy_path),
            "final_schema": str(final_schema_path),
            "leakage_drop_list": str(leakage_drop_path),
            "training_feature_list": str(training_feature_path),
            "summary": str(summary_path),
            "cleaning_policy_alias": str(cleaning_policy_alias),
            "final_schema_alias": str(final_schema_alias),
            "leakage_drop_list_alias": str(leakage_drop_alias),
            "training_feature_list_alias": str(training_feature_alias),
            "summary_alias": str(summary_alias),
        },

        "phase8_use": (
            "Phase 8 applies cleaning_policy.json, final_schema.json, leakage_drop_list.json, "
            "and training_feature_list.json while exporting train/test."
        ),
        "methodology_note": (
            "Phase 7 no longer creates a cleaned dataset checkpoint. It defines the cleaning "
            "and leakage policies used during Phase 8 export and later modeling preparation."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 7 - Cleaning Policy")
    print("=" * 72)
    print(f"Current Run        : {app.upper()}")
    print(f"Reading            : {base_schema_path}")
    print("Mode               : policy/schema only")
    print(f"Schema Columns     : {len(specs):,}")
    print(f"Drop Columns       : {len(leakage_drop.get('drop_columns', [])):,}")
    print(f"Training Candidates: {len(training_features.get('approved_low_risk_features', [])):,}")
    print(f"Output             : {summary_path}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase7_run = run_phase7
phase7_build_cleaning_policy = run_phase7
