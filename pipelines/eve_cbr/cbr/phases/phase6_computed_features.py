from __future__ import annotations

"""
Phase 6 - Computed Feature Rules Builder

Purpose:
- Do NOT generate a full computed-feature dataset here.
- Do NOT read Phase 5 dataset shards.
- Do NOT write Parquet/CSV checkpoints.
- Build deterministic computed-feature rules and schema.
- Phase 8 will apply these rules while exporting the final train/test dataset.

Input:
    phase5/feature_manifest.json
    phase5/base_feature_schema.json

Output:
    phase6_<app>_computed_feature_rules.json
    phase6_<app>_computed_feature_schema.json
    phase6_<app>_summary.json

Generic aliases for later phases:
    computed_feature_rules.json
    computed_feature_schema.json
    summary.json
"""

from collections import Counter
from pathlib import Path
from typing import Any

from ..io_utils import now_iso, read_json, write_json


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Helpers
# ============================================================

def _normalize_app(app: str) -> str:
    app = str(app).strip().lower()
    if app not in VALID_APPS:
        raise ValueError(f"Invalid app={app!r}. Expected one of {sorted(VALID_APPS)}")
    return app


def _safe_feature_names(manifest: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    specs = manifest.get("feature_specs", [])
    if isinstance(specs, list):
        for spec in specs:
            if isinstance(spec, dict) and spec.get("name"):
                out.add(str(spec["name"]))
    return out


def _phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _rule(
    name: str,
    *,
    expression: str,
    dtype: str,
    group: str,
    description: str,
    inputs: list[str],
    training_candidate: bool = True,
    leakage_risk: str = "low",
    safe_default: Any = 0,
) -> dict[str, Any]:
    return {
        "name": name,
        "expression": expression,
        "dtype": dtype,
        "group": group,
        "description": description,
        "inputs": inputs,
        "training_candidate": bool(training_candidate),
        "leakage_risk": leakage_risk,
        "safe_default": safe_default,
    }


# ============================================================
# Rule definitions
# ============================================================

def _core_computed_rules(app: str, available_features: set[str]) -> list[dict[str, Any]]:
    """
    Phase 8 should apply these rules with safe defaults:
    missing numeric input -> 0
    division denominator <= 0 -> 0
    log input < 0 -> log1p(max(x, 0))
    """
    rules = [
        _rule(
            "bytes_per_pkt",
            expression="total_bytes / max(total_pkts, 1)",
            dtype="float32",
            group="rate_ratio",
            description="Average bytes per packet.",
            inputs=["total_bytes", "total_pkts"],
        ),
        _rule(
            "pkts_per_sec",
            expression="total_pkts / max(duration, 1e-6)",
            dtype="float32",
            group="rate_ratio",
            description="Packet rate per second.",
            inputs=["total_pkts", "duration"],
        ),
        _rule(
            "bytes_per_sec",
            expression="total_bytes / max(duration, 1e-6)",
            dtype="float32",
            group="rate_ratio",
            description="Byte rate per second.",
            inputs=["total_bytes", "duration"],
        ),
        _rule(
            "bytes_toserver_ratio",
            expression="bytes_toserver / max(total_bytes, 1)",
            dtype="float32",
            group="rate_ratio",
            description="Fraction of bytes sent to server.",
            inputs=["bytes_toserver", "total_bytes"],
        ),
        _rule(
            "bytes_toclient_ratio",
            expression="bytes_toclient / max(total_bytes, 1)",
            dtype="float32",
            group="rate_ratio",
            description="Fraction of bytes sent to client.",
            inputs=["bytes_toclient", "total_bytes"],
        ),
        _rule(
            "pkts_toserver_ratio",
            expression="pkts_toserver / max(total_pkts, 1)",
            dtype="float32",
            group="rate_ratio",
            description="Fraction of packets sent to server.",
            inputs=["pkts_toserver", "total_pkts"],
        ),
        _rule(
            "pkts_toclient_ratio",
            expression="pkts_toclient / max(total_pkts, 1)",
            dtype="float32",
            group="rate_ratio",
            description="Fraction of packets sent to client.",
            inputs=["pkts_toclient", "total_pkts"],
        ),
        _rule(
            "log_total_bytes",
            expression="log1p(max(total_bytes, 0))",
            dtype="float32",
            group="log_transform",
            description="Log transformed total bytes.",
            inputs=["total_bytes"],
        ),
        _rule(
            "log_total_pkts",
            expression="log1p(max(total_pkts, 0))",
            dtype="float32",
            group="log_transform",
            description="Log transformed total packets.",
            inputs=["total_pkts"],
        ),
        _rule(
            "log_duration",
            expression="log1p(max(duration, 0))",
            dtype="float32",
            group="log_transform",
            description="Log transformed duration.",
            inputs=["duration"],
        ),
        _rule(
            "src_port_class",
            expression="classify_port(src_port)",
            dtype="int8",
            group="port",
            description="0 invalid, 1 well-known, 2 registered, 3 dynamic/private.",
            inputs=["src_port"],
        ),
        _rule(
            "dest_port_class",
            expression="classify_port(dest_port)",
            dtype="int8",
            group="port",
            description="0 invalid, 1 well-known, 2 registered, 3 dynamic/private.",
            inputs=["dest_port"],
        ),
        _rule(
            "dport_is_dns",
            expression="int(dest_port == 53)",
            dtype="int8",
            group="port",
            description="Destination port equals DNS port.",
            inputs=["dest_port"],
        ),
        _rule(
            "dport_is_http",
            expression="int(dest_port in {80, 8080, 8000, 8008, 8888})",
            dtype="int8",
            group="port",
            description="Destination port is common HTTP port.",
            inputs=["dest_port"],
        ),
        _rule(
            "dport_is_https",
            expression="int(dest_port in {443, 8443})",
            dtype="int8",
            group="port",
            description="Destination port is common TLS/HTTPS port.",
            inputs=["dest_port"],
        ),
        _rule(
            "dport_is_ssh",
            expression="int(dest_port == 22)",
            dtype="int8",
            group="port",
            description="Destination port equals SSH port.",
            inputs=["dest_port"],
        ),
        _rule(
            "ts_hour",
            expression="hour(timestamp)",
            dtype="int8",
            group="time",
            description="Hour of day from timestamp.",
            inputs=["timestamp"],
        ),
        _rule(
            "ts_dow",
            expression="dayofweek(timestamp)",
            dtype="int8",
            group="time",
            description="Day of week from timestamp.",
            inputs=["timestamp"],
        ),
        _rule(
            "ts_is_weekend",
            expression="int(ts_dow >= 5)",
            dtype="int8",
            group="time",
            description="Weekend indicator.",
            inputs=["timestamp"],
        ),
        _rule(
            "src_is_private",
            expression="is_private_ipv4(src_ip)",
            dtype="int8",
            group="ip",
            description="Private IPv4 indicator for source IP.",
            inputs=["src_ip"],
            training_candidate=True,
            leakage_risk="medium",
        ),
        _rule(
            "dest_is_private",
            expression="is_private_ipv4(dest_ip)",
            dtype="int8",
            group="ip",
            description="Private IPv4 indicator for destination IP.",
            inputs=["dest_ip"],
            training_candidate=True,
            leakage_risk="medium",
        ),
        _rule(
            "src_subnet24_h",
            expression="stable_hash(ipv4_subnet24(src_ip))",
            dtype="int32",
            group="ip",
            description="Hashed /24 subnet of source IP.",
            inputs=["src_ip"],
            training_candidate=False,
            leakage_risk="medium",
        ),
        _rule(
            "dest_subnet24_h",
            expression="stable_hash(ipv4_subnet24(dest_ip))",
            dtype="int32",
            group="ip",
            description="Hashed /24 subnet of destination IP.",
            inputs=["dest_ip"],
            training_candidate=False,
            leakage_risk="medium",
        ),
        _rule(
            "same_subnet24",
            expression="int(src_subnet24_h == dest_subnet24_h)",
            dtype="int8",
            group="ip",
            description="Source and destination are in the same /24 subnet.",
            inputs=["src_ip", "dest_ip"],
        ),
        _rule(
            "proto_h",
            expression="stable_hash(proto)",
            dtype="int32",
            group="categorical_hash",
            description="Stable hash encoding for transport protocol.",
            inputs=["proto"],
        ),
        _rule(
            "event_type_h",
            expression="stable_hash(event_type)",
            dtype="int32",
            group="categorical_hash",
            description="Stable hash encoding for Suricata event type. Drop before modeling if leakage check flags it.",
            inputs=["event_type"],
            training_candidate=False,
            leakage_risk="high",
        ),
        _rule(
            "app_proto_h",
            expression="stable_hash(app_proto)",
            dtype="int32",
            group="categorical_hash",
            description="Stable hash encoding for application protocol.",
            inputs=["app_proto"],
        ),
    ]

    # App-specific categorical hashing or indicators.
    if app == "http":
        rules.extend([
            _rule("http_method_h", expression="stable_hash(http_method)", dtype="int32", group="http", description="Stable hash of HTTP method.", inputs=["http_method"]),
            _rule("http_status_class", expression="floor(http_status / 100)", dtype="int8", group="http", description="HTTP status class.", inputs=["http_status"]),
        ])
    elif app == "tls":
        rules.extend([
            _rule("tls_version_h", expression="stable_hash(tls_version)", dtype="int32", group="tls", description="Stable hash of TLS version.", inputs=["tls_version"]),
            _rule("tls_has_sni", expression="int(tls_sni_len > 0)", dtype="int8", group="tls", description="TLS SNI exists.", inputs=["tls_sni_len"]),
        ])
    elif app == "dns":
        rules.extend([
            _rule("dns_rrtype_h", expression="stable_hash(dns_rrtype)", dtype="int32", group="dns", description="Stable hash of DNS rrtype.", inputs=["dns_rrtype"]),
            _rule("dns_rcode_h", expression="stable_hash(dns_rcode)", dtype="int32", group="dns", description="Stable hash of DNS rcode.", inputs=["dns_rcode"]),
            _rule("dns_query_name_present", expression="int(dns_rrname_len > 0)", dtype="int8", group="dns", description="DNS rrname exists.", inputs=["dns_rrname_len"]),
        ])
    elif app == "ssh":
        rules.extend([
            _rule("ssh_protocol_h", expression="stable_hash(ssh_protocol)", dtype="int32", group="ssh", description="Stable hash of SSH protocol.", inputs=["ssh_protocol"]),
            _rule("ssh_has_client_version", expression="int(ssh_client_version_len > 0)", dtype="int8", group="ssh", description="SSH client software version exists.", inputs=["ssh_client_version_len"]),
            _rule("ssh_has_server_version", expression="int(ssh_server_version_len > 0)", dtype="int8", group="ssh", description="SSH server software version exists.", inputs=["ssh_server_version_len"]),
        ])

    # Keep all rules, even if inputs are missing in the preview/manifest.
    # Phase 8 applies safe defaults. The availability metadata below records this.
    for rule in rules:
        inputs = set(rule.get("inputs", []))
        rule["inputs_declared_in_phase5_manifest"] = sorted(inputs & available_features)
        rule["missing_inputs_in_phase5_manifest"] = sorted(inputs - available_features)

    return rules


def _interaction_rules() -> list[dict[str, Any]]:
    """
    Keep interaction rules declarative and conservative.
    Phase 8 may materialize them only for approved numeric base columns.
    """
    return [
        _rule(
            "interaction_total_bytes_duration",
            expression="log_total_bytes * log_duration",
            dtype="float32",
            group="interaction",
            description="Interaction between byte volume and duration.",
            inputs=["log_total_bytes", "log_duration"],
        ),
        _rule(
            "interaction_total_pkts_duration",
            expression="log_total_pkts * log_duration",
            dtype="float32",
            group="interaction",
            description="Interaction between packet volume and duration.",
            inputs=["log_total_pkts", "log_duration"],
        ),
        _rule(
            "interaction_bytes_rate_packet_rate",
            expression="bytes_per_sec * pkts_per_sec",
            dtype="float32",
            group="interaction",
            description="Interaction between byte rate and packet rate.",
            inputs=["bytes_per_sec", "pkts_per_sec"],
        ),
    ]


def _row_stat_rules() -> list[dict[str, Any]]:
    """
    These are optional. They should only be applied to the final approved numeric
    no-leak feature set in Phase 8/10/11 if enabled.
    """
    return [
        _rule(
            "row_mean",
            expression="mean(selected_numeric_features)",
            dtype="float32",
            group="row_stat_optional",
            description="Row-wise mean over selected numeric no-leak features.",
            inputs=["selected_numeric_features"],
        ),
        _rule(
            "row_std",
            expression="std(selected_numeric_features)",
            dtype="float32",
            group="row_stat_optional",
            description="Row-wise standard deviation over selected numeric no-leak features.",
            inputs=["selected_numeric_features"],
        ),
        _rule(
            "row_max",
            expression="max(selected_numeric_features)",
            dtype="float32",
            group="row_stat_optional",
            description="Row-wise maximum over selected numeric no-leak features.",
            inputs=["selected_numeric_features"],
        ),
        _rule(
            "row_sum",
            expression="sum(selected_numeric_features)",
            dtype="float32",
            group="row_stat_optional",
            description="Row-wise sum over selected numeric no-leak features.",
            inputs=["selected_numeric_features"],
        ),
    ]


def _build_rules(app: str, manifest: dict[str, Any]) -> dict[str, Any]:
    available = _safe_feature_names(manifest)
    core_rules = _core_computed_rules(app, available)
    interaction = _interaction_rules()
    row_stats = _row_stat_rules()

    all_rules = core_rules + interaction + row_stats
    group_counts = Counter(str(r["group"]) for r in all_rules)

    return {
        "phase": 6,
        "title": "Computed Feature Rules",
        "app": app,
        "created_at": now_iso(),
        "mode": "rules_only_no_dataset_output",
        "safe_evaluation_policy": {
            "missing_numeric_input": 0,
            "missing_categorical_input": "unknown",
            "division_by_zero": 0,
            "invalid_timestamp": 0,
            "invalid_ip": 0,
            "infinite_or_nan_output": 0,
        },
        "materialization_phase": "phase8_export_dataset",
        "rules": all_rules,
        "rule_count": int(len(all_rules)),
        "rule_group_counts": {str(k): int(v) for k, v in group_counts.items()},
        "optional_rules": {
            "interaction_rules": [r["name"] for r in interaction],
            "row_stat_rules": [r["name"] for r in row_stats],
        },
        "leakage_note": (
            "Rules marked high leakage risk or target/audit role must not be used directly for modeling. "
            "Phase 7/10/11 will define final no-leak training columns."
        ),
    }


def _build_schema(app: str, rules: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": 6,
        "title": "Computed Feature Schema",
        "app": app,
        "created_at": now_iso(),
        "columns": [
            {
                "name": r["name"],
                "dtype": r["dtype"],
                "group": r["group"],
                "training_candidate": bool(r["training_candidate"]),
                "leakage_risk": r["leakage_risk"],
                "inputs": r["inputs"],
            }
            for r in rules.get("rules", [])
        ],
        "must_drop_before_modeling": [
            r["name"]
            for r in rules.get("rules", [])
            if r.get("leakage_risk") in {"high", "target"}
        ],
        "phase8_note": "Phase 8 may materialize these computed columns while streaming the app JSONL.",
    }


# ============================================================
# Runner
# ============================================================

def run_phase6(
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
    manifest_path = phase5_dir / "feature_manifest.json"
    schema_path = phase5_dir / "base_feature_schema.json"

    manifest = _read_optional_json(manifest_path)
    base_schema = _read_optional_json(schema_path)

    rules = _build_rules(app, manifest)
    computed_schema = _build_schema(app, rules)

    prefix = f"phase6_{app}"

    rules_path = phase_dir / f"{prefix}_computed_feature_rules.json"
    schema_out_path = phase_dir / f"{prefix}_computed_feature_schema.json"
    summary_path = phase_dir / f"{prefix}_summary.json"

    rules_alias = phase_dir / "computed_feature_rules.json"
    schema_alias = phase_dir / "computed_feature_schema.json"
    summary_alias = phase_dir / "summary.json"

    print("\n" + "=" * 72)
    print("Phase 6 - Computed Feature Rules")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {manifest_path}")
    print("Mode        : rules/schema only")
    print("=" * 72)

    write_json(rules, rules_path)
    write_json(rules, rules_alias)

    write_json(computed_schema, schema_out_path)
    write_json(computed_schema, schema_alias)

    rule_count = int(rules.get("rule_count", 0))
    training_candidate_count = int(sum(1 for r in rules.get("rules", []) if r.get("training_candidate")))
    high_leak_count = int(sum(1 for r in rules.get("rules", []) if r.get("leakage_risk") == "high"))

    summary = {
        "phase": 6,
        "title": "Computed Feature Rules",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),

        "input": {
            "phase5_feature_manifest": str(manifest_path),
            "phase5_base_feature_schema": str(schema_path),
            "phase5_manifest_found": bool(manifest),
            "phase5_base_schema_found": bool(base_schema),
            "app_input_path": str(app_input_path) if app_input_path else None,
        },

        "mode": "rules_only_no_dataset_output",
        "dataset_output_created": False,
        "full_scan": False,

        "rule_count": rule_count,
        "training_candidate_rule_count": training_candidate_count,
        "high_leakage_rule_count": high_leak_count,
        "rule_group_counts": rules.get("rule_group_counts", {}),

        "output": {
            "computed_feature_rules": str(rules_path),
            "computed_feature_schema": str(schema_out_path),
            "summary": str(summary_path),
            "computed_feature_rules_alias": str(rules_alias),
            "computed_feature_schema_alias": str(schema_alias),
            "summary_alias": str(summary_alias),
        },

        "phase8_use": (
            "Phase 8 reads computed_feature_rules.json and materializes these features "
            "while streaming the full app JSONL."
        ),
        "methodology_note": (
            "Phase 6 no longer generates a large computed-feature dataset. "
            "It defines deterministic formulas only, avoiding repeated full-data rewrites."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 6 - Computed Feature Rules")
    print("=" * 72)
    print(f"Current Run        : {app.upper()}")
    print(f"Reading            : {manifest_path}")
    print("Mode               : rules/schema only")
    print(f"Computed Rules     : {rule_count:,}")
    print(f"Training Candidates: {training_candidate_count:,}")
    print(f"Output             : {summary_path}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase6_run = run_phase6
phase6_build_computed_rules = run_phase6
