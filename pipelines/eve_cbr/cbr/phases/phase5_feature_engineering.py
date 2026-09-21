from __future__ import annotations

"""
Phase 5 - Feature Engineering Manifest Builder

Purpose:
- Do NOT generate a full feature-engineered dataset here.
- Do NOT read Phase 4 row-level shards.
- Do NOT write Parquet/CSV checkpoints.
- Build feature extraction manifest, base schema, and a tiny preview only.
- The full feature-ready dataset is generated later in Phase 8.

Input:
    eve_<app>.jsonl                         small preview read only
    phase3/manifest.json                    optional
    phase4/label_policy.json                optional
    phase4/suspicious_keys.jsonl            optional

Output:
    phase5_<app>_feature_manifest.json
    phase5_<app>_base_feature_schema.json
    phase5_<app>_feature_preview.csv
    phase5_<app>_summary.json

Generic aliases for later phases:
    feature_manifest.json
    base_feature_schema.json
    feature_preview.csv
    summary.json
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import csv

from ..io_utils import (
    file_size_bytes,
    file_size_gib,
    loads_json_line,
    now_iso,
    open_maybe_gzip,
    read_json,
    require_file,
    write_json,
)


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Helpers
# ============================================================

def _normalize_app(app: str) -> str:
    app = str(app).strip().lower()
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app={app!r}. Expected one of {sorted(VALID_APPS)}")
    return app


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _get_nested(obj: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur


def _len_value(value: Any) -> int:
    if value is None:
        return 0
    return len(str(value))


def _counter_top(counter: Counter, n: int = 30) -> dict[str, int]:
    return {str(k): int(v) for k, v in counter.most_common(int(n))}


def _phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    obj = read_json(path, default={}, required=False)
    return obj if isinstance(obj, dict) else {}


def _field_spec(
    name: str,
    *,
    source: str,
    dtype: str,
    role: str,
    group: str,
    description: str,
    training_candidate: bool = True,
    leakage_risk: str = "low",
) -> dict[str, Any]:
    return {
        "name": name,
        "source": source,
        "dtype": dtype,
        "role": role,
        "group": group,
        "description": description,
        "training_candidate": bool(training_candidate),
        "leakage_risk": leakage_risk,
    }


# ============================================================
# Manifest definitions
# ============================================================

def _common_base_features() -> list[dict[str, Any]]:
    return [
        _field_spec("timestamp", source="timestamp", dtype="datetime/string", role="time_context", group="core", description="Original event timestamp.", training_candidate=False, leakage_risk="medium"),
        _field_spec("src_ip", source="src_ip", dtype="string", role="split_key/audit", group="core", description="Source IP. Used for source-IP split/audit, dropped before modeling.", training_candidate=False, leakage_risk="medium"),
        _field_spec("dest_ip", source="dest_ip", dtype="string", role="audit", group="core", description="Destination IP. Usually transformed to private/subnet features.", training_candidate=False, leakage_risk="medium"),
        _field_spec("src_port", source="src_port", dtype="int", role="base_feature", group="core", description="Source port."),
        _field_spec("dest_port", source="dest_port", dtype="int", role="base_feature", group="core", description="Destination port."),
        _field_spec("proto", source="proto", dtype="categorical", role="base_feature", group="core", description="Transport protocol, encoded later."),
        _field_spec("event_type", source="event_type", dtype="categorical", role="base_feature", group="core", description="Suricata event type, encoded later."),
        _field_spec("app_proto", source="app_proto", dtype="categorical", role="base_feature", group="core", description="Application protocol inferred by Suricata, encoded later."),

        _field_spec("pkts_toserver", source="flow.pkts_toserver", dtype="int", role="base_feature", group="flow", description="Packets from source to destination."),
        _field_spec("pkts_toclient", source="flow.pkts_toclient", dtype="int", role="base_feature", group="flow", description="Packets from destination to source."),
        _field_spec("bytes_toserver", source="flow.bytes_toserver", dtype="int", role="base_feature", group="flow", description="Bytes from source to destination."),
        _field_spec("bytes_toclient", source="flow.bytes_toclient", dtype="int", role="base_feature", group="flow", description="Bytes from destination to source."),
        _field_spec("duration", source="flow.age", dtype="float", role="base_feature", group="flow", description="Flow age/duration when available."),
        _field_spec("total_pkts", source="flow.pkts_toserver + flow.pkts_toclient", dtype="int", role="base_feature", group="flow", description="Total packet count."),
        _field_spec("total_bytes", source="flow.bytes_toserver + flow.bytes_toclient", dtype="int", role="base_feature", group="flow", description="Total byte count."),

        _field_spec("has_alert", source="alert", dtype="int", role="label_evidence/audit", group="alert_evidence", description="Whether alert object exists.", training_candidate=False, leakage_risk="high"),
        _field_spec("alert_category", source="alert.category", dtype="categorical", role="label_evidence/audit", group="alert_evidence", description="Suricata alert category.", training_candidate=False, leakage_risk="high"),
        _field_spec("alert_severity", source="alert.severity", dtype="int", role="label_evidence/audit", group="alert_evidence", description="Suricata alert severity.", training_candidate=False, leakage_risk="high"),
        _field_spec("alert_signature", source="alert.signature", dtype="string", role="label_evidence/audit", group="alert_evidence", description="Suricata alert signature.", training_candidate=False, leakage_risk="high"),
        _field_spec("alert_signature_id", source="alert.signature_id", dtype="int", role="label_evidence/audit", group="alert_evidence", description="Suricata alert signature ID.", training_candidate=False, leakage_risk="high"),
    ]


def _app_specific_features(app: str) -> list[dict[str, Any]]:
    if app == "http":
        return [
            _field_spec("http_method", source="http.http_method", dtype="categorical", role="app_feature", group="http", description="HTTP method, encoded later."),
            _field_spec("http_hostname_len", source="len(http.hostname)", dtype="int", role="app_feature", group="http", description="Length of HTTP hostname."),
            _field_spec("http_url_len", source="len(http.url)", dtype="int", role="app_feature", group="http", description="Length of HTTP URL."),
            _field_spec("http_user_agent_len", source="len(http.http_user_agent)", dtype="int", role="app_feature", group="http", description="Length of HTTP user agent when available."),
            _field_spec("http_status", source="http.status", dtype="int", role="app_feature", group="http", description="HTTP response status when available."),
        ]

    if app == "tls":
        return [
            _field_spec("tls_sni_len", source="len(tls.sni)", dtype="int", role="app_feature", group="tls", description="Length of TLS SNI/server name."),
            _field_spec("tls_version", source="tls.version", dtype="categorical", role="app_feature", group="tls", description="TLS version, encoded later."),
            _field_spec("tls_ja3_len", source="len(tls.ja3.hash)", dtype="int", role="app_feature", group="tls", description="JA3 hash length when available."),
            _field_spec("tls_ja3s_len", source="len(tls.ja3s.hash)", dtype="int", role="app_feature", group="tls", description="JA3S hash length when available."),
        ]

    if app == "dns":
        return [
            _field_spec("dns_rrname_len", source="len(dns.rrname)", dtype="int", role="app_feature", group="dns", description="Length of DNS queried/resource name."),
            _field_spec("dns_rrtype", source="dns.rrtype", dtype="categorical/int", role="app_feature", group="dns", description="DNS resource record type."),
            _field_spec("dns_rcode", source="dns.rcode", dtype="categorical", role="app_feature", group="dns", description="DNS response code."),
            _field_spec("dns_type", source="dns.type", dtype="categorical", role="app_feature", group="dns", description="DNS transaction type."),
        ]

    if app == "ssh":
        return [
            _field_spec("ssh_client_version_len", source="len(ssh.client.software_version)", dtype="int", role="app_feature", group="ssh", description="Length of SSH client software version."),
            _field_spec("ssh_server_version_len", source="len(ssh.server.software_version)", dtype="int", role="app_feature", group="ssh", description="Length of SSH server software version."),
            _field_spec("ssh_protocol", source="ssh.protocol", dtype="categorical", role="app_feature", group="ssh", description="SSH protocol value when available."),
        ]

    return []


def _phase3_feature_specs() -> list[dict[str, Any]]:
    return [
        _field_spec("event_count_window", source="phase3.probe_features", dtype="int", role="behavior_feature", group="probing", description="Number of events for src_ip in time window."),
        _field_spec("unique_dest_ip_window", source="phase3.probe_features", dtype="int", role="behavior_feature", group="probing", description="Unique destination IPs for src_ip in time window."),
        _field_spec("unique_dest_port_window", source="phase3.probe_features", dtype="int", role="behavior_feature", group="probing", description="Unique destination ports for src_ip in time window."),
        _field_spec("total_bytes_window", source="phase3.probe_features", dtype="int", role="behavior_feature", group="probing", description="Total bytes for src_ip in time window."),
        _field_spec("total_pkts_window", source="phase3.probe_features", dtype="int", role="behavior_feature", group="probing", description="Total packets for src_ip in time window."),
        _field_spec("probe_score_no_alert", source="phase3.probe_features", dtype="float", role="refinement_evidence", group="probing", description="Behavior-only probing score.", training_candidate=False, leakage_risk="medium"),
        _field_spec("probe_score_with_alert", source="phase3.probe_features", dtype="float", role="audit/refinement_evidence", group="probing", description="Probing score plus alert association; audit only.", training_candidate=False, leakage_risk="high"),
        _field_spec("fanout_high", source="phase3.probe_features", dtype="int", role="refinement_evidence", group="probing", description="High fan-out marker used by Phase 4.", training_candidate=False, leakage_risk="medium"),
        _field_spec("is_suspicious_window", source="phase3.probe_features", dtype="int", role="refinement_evidence", group="probing", description="Suspicious aggregate window marker.", training_candidate=False, leakage_risk="medium"),
    ]


def _phase4_label_specs() -> list[dict[str, Any]]:
    return [
        _field_spec("Target_alert", source="valid alert policy", dtype="int", role="label", group="label", description="Initial alert-based label.", training_candidate=False, leakage_risk="target"),
        _field_spec("Target_refined", source="phase4 policy + phase8 export", dtype="int", role="label", group="label", description="Final refined target label.", training_candidate=False, leakage_risk="target"),
        _field_spec("suspicious_by_probe", source="phase4.suspicious_keys", dtype="int", role="audit_label", group="label", description="Suspicious probing marker.", training_candidate=False, leakage_risk="high"),
        _field_spec("label_source", source="phase4.label_policy", dtype="categorical", role="audit_label", group="label", description="Source of label decision.", training_candidate=False, leakage_risk="high"),
        _field_spec("refinement_reason", source="phase4.label_policy", dtype="string", role="audit_label", group="label", description="Reason for label refinement decision.", training_candidate=False, leakage_risk="high"),
    ]


def _computed_feature_placeholders() -> list[dict[str, Any]]:
    """
    These are listed as planned outputs, but Phase 6 owns the actual formula
    rules. Phase 8 will apply both Phase 5 manifest and Phase 6 computed rules.
    """
    return [
        _field_spec("bytes_per_pkt", source="phase6 rule", dtype="float", role="computed_feature", group="computed_placeholder", description="Computed later in Phase 6/8."),
        _field_spec("pkts_per_sec", source="phase6 rule", dtype="float", role="computed_feature", group="computed_placeholder", description="Computed later in Phase 6/8."),
        _field_spec("bytes_per_sec", source="phase6 rule", dtype="float", role="computed_feature", group="computed_placeholder", description="Computed later in Phase 6/8."),
        _field_spec("log_total_bytes", source="phase6 rule", dtype="float", role="computed_feature", group="computed_placeholder", description="Computed later in Phase 6/8."),
        _field_spec("log_total_pkts", source="phase6 rule", dtype="float", role="computed_feature", group="computed_placeholder", description="Computed later in Phase 6/8."),
    ]


def _build_feature_manifest(
    *,
    app: str,
    phase3_manifest: dict[str, Any],
    phase4_policy: dict[str, Any],
) -> dict[str, Any]:
    feature_specs = (
        _common_base_features()
        + _app_specific_features(app)
        + _phase3_feature_specs()
        + _phase4_label_specs()
        + _computed_feature_placeholders()
    )

    groups: dict[str, int] = Counter(str(x["group"]) for x in feature_specs)
    training_candidates = [x["name"] for x in feature_specs if x.get("training_candidate")]
    audit_or_leakage = [x["name"] for x in feature_specs if not x.get("training_candidate")]

    return {
        "phase": 5,
        "title": "Feature Engineering Manifest",
        "app": app,
        "created_at": now_iso(),
        "mode": "manifest_only_no_dataset_output",

        "feature_specs": feature_specs,
        "feature_count": int(len(feature_specs)),
        "feature_group_counts": {str(k): int(v) for k, v in groups.items()},
        "training_candidate_features": training_candidates,
        "audit_or_leakage_features": audit_or_leakage,

        "join_requirements": {
            "phase3_probe_features": {
                "join_key": ["app", "window_start", "src_ip"],
                "required": True,
                "note": "Phase 8 joins aggregate probing evidence using this key.",
            },
            "phase4_suspicious_keys": {
                "join_key": ["app", "window_start", "src_ip"],
                "required": True,
                "note": "Phase 8 applies conservative label refinement keys using this key.",
            },
        },

        "upstream_refs": {
            "phase3_manifest_found": bool(phase3_manifest),
            "phase4_policy_found": bool(phase4_policy),
        },

        "phase6_note": (
            "Phase 5 defines extractable/base features. "
            "Phase 6 defines formulas for computed features such as rates, ratios, logs, and interactions."
        ),
        "phase8_note": (
            "Phase 8 is responsible for reading the full app JSONL and materializing this manifest "
            "into train/test dataset files."
        ),
    }


def _build_base_schema(app: str, manifest: dict[str, Any]) -> dict[str, Any]:
    feature_specs = manifest.get("feature_specs", [])
    return {
        "phase": 5,
        "title": "Base Feature Schema",
        "app": app,
        "created_at": now_iso(),
        "columns": [
            {
                "name": spec["name"],
                "dtype": spec["dtype"],
                "role": spec["role"],
                "group": spec["group"],
                "training_candidate": bool(spec["training_candidate"]),
                "leakage_risk": spec["leakage_risk"],
            }
            for spec in feature_specs
        ],
        "target_column": "Target_refined",
        "id_or_split_columns": ["src_ip", "dest_ip", "timestamp", "window_start"],
        "must_drop_before_modeling": [
            spec["name"]
            for spec in feature_specs
            if spec.get("leakage_risk") in {"high", "target"}
        ],
        "notes": [
            "This schema is declarative. It does not mean all columns already exist on disk.",
            "Phase 8 materializes actual columns while exporting the feature-ready dataset.",
            "Phase 7/10/11 decide final no-leak training columns.",
        ],
    }


# ============================================================
# Preview extraction
# ============================================================

def _preview_row(event: dict[str, Any], *, app: str) -> dict[str, Any]:
    flow = event.get("flow") if isinstance(event.get("flow"), dict) else {}
    alert = event.get("alert") if isinstance(event.get("alert"), dict) else {}

    row = {
        "timestamp": event.get("timestamp", ""),
        "src_ip": event.get("src_ip", ""),
        "dest_ip": event.get("dest_ip", ""),
        "src_port": _safe_int(event.get("src_port"), 0),
        "dest_port": _safe_int(event.get("dest_port"), 0),
        "proto": event.get("proto", ""),
        "event_type": event.get("event_type", ""),
        "app_proto": event.get("app_proto", ""),

        "pkts_toserver": _safe_int(flow.get("pkts_toserver"), 0),
        "pkts_toclient": _safe_int(flow.get("pkts_toclient"), 0),
        "bytes_toserver": _safe_int(flow.get("bytes_toserver"), 0),
        "bytes_toclient": _safe_int(flow.get("bytes_toclient"), 0),
        "duration": _safe_float(flow.get("age"), 0.0),

        "has_alert": 1 if alert else 0,
        "alert_category": alert.get("category", "") if alert else "",
        "alert_severity": _safe_int(alert.get("severity"), 0) if alert else 0,
    }

    row["total_pkts"] = row["pkts_toserver"] + row["pkts_toclient"]
    row["total_bytes"] = row["bytes_toserver"] + row["bytes_toclient"]

    if app == "http":
        row.update({
            "http_method": _get_nested(event, "http.http_method", ""),
            "http_hostname_len": _len_value(_get_nested(event, "http.hostname", "")),
            "http_url_len": _len_value(_get_nested(event, "http.url", "")),
            "http_user_agent_len": _len_value(_get_nested(event, "http.http_user_agent", "")),
            "http_status": _safe_int(_get_nested(event, "http.status"), 0),
        })
    elif app == "tls":
        row.update({
            "tls_sni_len": _len_value(_get_nested(event, "tls.sni", "")),
            "tls_version": _get_nested(event, "tls.version", ""),
            "tls_ja3_len": _len_value(_get_nested(event, "tls.ja3.hash", "")),
            "tls_ja3s_len": _len_value(_get_nested(event, "tls.ja3s.hash", "")),
        })
    elif app == "dns":
        row.update({
            "dns_rrname_len": _len_value(_get_nested(event, "dns.rrname", "")),
            "dns_rrtype": _get_nested(event, "dns.rrtype", ""),
            "dns_rcode": _get_nested(event, "dns.rcode", ""),
            "dns_type": _get_nested(event, "dns.type", ""),
        })
    elif app == "ssh":
        row.update({
            "ssh_client_version_len": _len_value(_get_nested(event, "ssh.client.software_version", "")),
            "ssh_server_version_len": _len_value(_get_nested(event, "ssh.server.software_version", "")),
            "ssh_protocol": _get_nested(event, "ssh.protocol", ""),
        })

    return row


def _write_preview_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in fieldnames:
                fieldnames.append(k)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_preview(
    *,
    app: str,
    app_input_path: Path,
    preview_rows: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    event_type_counter: Counter = Counter()
    app_proto_counter: Counter = Counter()
    malformed = 0
    scanned = 0

    if preview_rows <= 0:
        return rows, {
            "preview_rows_requested": int(preview_rows),
            "rows_scanned_for_preview": 0,
            "preview_rows_written": 0,
            "malformed_in_preview_scan": 0,
            "top_event_type_preview": {},
            "top_app_proto_preview": {},
        }

    with open_maybe_gzip(app_input_path, "rb") as f:
        for line in f:
            if len(rows) >= int(preview_rows):
                break

            scanned += 1
            line = line.strip()
            if not line:
                continue

            try:
                event = loads_json_line(line)
                if not isinstance(event, dict):
                    malformed += 1
                    continue
            except Exception:
                malformed += 1
                continue

            event_type_counter[_text(event.get("event_type"), "unknown") or "unknown"] += 1
            app_proto_counter[_text(event.get("app_proto"), "unknown") or "unknown"] += 1
            rows.append(_preview_row(event, app=app))

    stats = {
        "preview_rows_requested": int(preview_rows),
        "rows_scanned_for_preview": int(scanned),
        "preview_rows_written": int(len(rows)),
        "malformed_in_preview_scan": int(malformed),
        "top_event_type_preview": _counter_top(event_type_counter, 20),
        "top_app_proto_preview": _counter_top(app_proto_counter, 20),
    }
    return rows, stats


# ============================================================
# Runner
# ============================================================

def run_phase5(
    *,
    cfg: Any,
    app: str,
    app_input_path: Path,
    phase_dir: Path,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    app_input_path = require_file(app_input_path, label=f"{app} app JSONL")
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    preview_rows = int(getattr(cfg, "feature_preview_rows", 200) or 200)

    phase3_manifest = _read_optional_json(_phase_dir(phase_dir, "phase3") / "manifest.json")
    phase4_policy = _read_optional_json(_phase_dir(phase_dir, "phase4") / "label_policy.json")

    manifest = _build_feature_manifest(
        app=app,
        phase3_manifest=phase3_manifest,
        phase4_policy=phase4_policy,
    )
    schema = _build_base_schema(app, manifest)

    prefix = f"phase5_{app}"

    manifest_path = phase_dir / f"{prefix}_feature_manifest.json"
    schema_path = phase_dir / f"{prefix}_base_feature_schema.json"
    preview_path = phase_dir / f"{prefix}_feature_preview.csv"
    summary_path = phase_dir / f"{prefix}_summary.json"

    manifest_alias = phase_dir / "feature_manifest.json"
    schema_alias = phase_dir / "base_feature_schema.json"
    preview_alias = phase_dir / "feature_preview.csv"
    summary_alias = phase_dir / "summary.json"

    print("\n" + "=" * 72)
    print("Phase 5 - Feature Engineering Manifest")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {app_input_path}")
    print("Mode        : manifest/schema only")
    print("=" * 72)

    preview, preview_stats = _read_preview(
        app=app,
        app_input_path=app_input_path,
        preview_rows=preview_rows,
    )

    _write_preview_csv(preview, preview_path)
    _write_preview_csv(preview, preview_alias)

    write_json(manifest, manifest_path)
    write_json(manifest, manifest_alias)

    write_json(schema, schema_path)
    write_json(schema, schema_alias)

    feature_specs = manifest.get("feature_specs", [])
    training_candidate_count = int(sum(1 for x in feature_specs if x.get("training_candidate")))
    audit_count = int(len(feature_specs) - training_candidate_count)

    summary = {
        "phase": 5,
        "title": "Feature Engineering Manifest",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),

        "input": {
            "app_input_path": str(app_input_path),
            "app_input_size_bytes": int(file_size_bytes(app_input_path)),
            "app_input_size_gib": float(file_size_gib(app_input_path)),
            "phase3_manifest_found": bool(phase3_manifest),
            "phase4_policy_found": bool(phase4_policy),
        },

        "mode": "manifest_only_no_dataset_output",
        "dataset_output_created": False,
        "full_scan": False,

        "feature_count": int(len(feature_specs)),
        "training_candidate_count": training_candidate_count,
        "audit_or_leakage_count": audit_count,
        "feature_group_counts": manifest.get("feature_group_counts", {}),

        "preview": preview_stats,

        "output": {
            "feature_manifest": str(manifest_path),
            "base_feature_schema": str(schema_path),
            "feature_preview": str(preview_path),
            "summary": str(summary_path),
            "feature_manifest_alias": str(manifest_alias),
            "base_feature_schema_alias": str(schema_alias),
            "feature_preview_alias": str(preview_alias),
            "summary_alias": str(summary_alias),
        },

        "phase8_use": (
            "Phase 8 reads this manifest and materializes the full feature-ready dataset "
            "while exporting train/test files."
        ),
        "methodology_note": (
            "Phase 5 no longer generates a large dataset. It defines what features should "
            "be extracted or joined later. This avoids repeated full-data rewrites."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 5 - Feature Engineering Manifest")
    print("=" * 72)
    print(f"Current Run        : {app.upper()}")
    print(f"Reading            : {app_input_path}")
    print("Mode               : manifest/schema only")
    print(f"Planned Features   : {len(feature_specs):,}")
    print(f"Training Candidates: {training_candidate_count:,}")
    print(f"Preview Rows       : {preview_stats['preview_rows_written']:,}")
    print(f"Output             : {summary_path}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase5_run = run_phase5
phase5_build_feature_manifest = run_phase5
