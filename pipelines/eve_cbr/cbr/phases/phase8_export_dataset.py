from __future__ import annotations

"""
Phase 8 - Export Feature-Ready Dataset and Split

Purpose:
- Full-scan the active pre-split app JSONL.
- Materialize features from Phase 5 manifest and Phase 6 rules.
- Apply Phase 7 cleaning/leakage policy.
- Apply Phase 4 conservative label-refinement keys.
- Write train/test files directly.
- Write summaries needed by Phase 9 visualization and Phase 10 correlation/leakage.

Input:
    eve_<app>.jsonl
    phase3/phase3_<app>_probe_features.jsonl
    phase4/suspicious_keys.jsonl
    phase5/feature_manifest.json
    phase6/computed_feature_rules.json
    phase7/cleaning_policy.json
    phase7/leakage_drop_list.json
    phase7/training_feature_list.json

Output:
    train.csv or train.jsonl
    test.csv or test.jsonl
    export_summary.json
    split_summary.json
    schema.json
    feature_roles.json
    label_distribution.csv
    feature_availability.csv
    missing_value_summary.csv
    feature_group_summary.csv
    file_class_summary.csv
    visualization_aggregates.json
    visualization_aggregate_counts.csv
    visualization_numeric_histograms.csv
    visualization_sample.csv
    corr_leak_sample.csv
"""

import csv
import gzip
import hashlib
import ipaddress
import json
import math
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from ..io_utils import (
    dumps_json,
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

IGNORED_ALERT_CATEGORIES = {
    "generic protocol decode",
    "generic protocol command decode",
}


# ============================================================
# Basic helpers
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
        x = float(value)
        if math.isfinite(x):
            return x
        return default
    except Exception:
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    s = str(value)
    return s if s else default


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


def _stable_hash(value: Any, mod: int = 2**31 - 1) -> int:
    s = str(value if value is not None else "unknown")
    h = hashlib.blake2b(s.encode("utf-8", errors="ignore"), digest_size=8).digest()
    return int.from_bytes(h, "big") % int(mod)


def _private_ipv4(value: Any) -> int:
    try:
        ip = ipaddress.ip_address(str(value))
        return int(ip.version == 4 and ip.is_private)
    except Exception:
        return 0


def _subnet24(value: Any) -> str:
    try:
        ip = str(value)
        parts = ip.split(".")
        if len(parts) >= 3:
            return ".".join(parts[:3])
    except Exception:
        pass
    return "0.0.0"


def _classify_port(port: Any) -> int:
    p = _safe_int(port, 0)
    if 1 <= p <= 1023:
        return 1
    if 1024 <= p <= 49151:
        return 2
    if p >= 49152:
        return 3
    return 0


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _floor_window(dt: Optional[datetime], window_minutes: int) -> str:
    if dt is None:
        return ""
    seconds = int(window_minutes) * 60
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % seconds)
    out = datetime.fromtimestamp(floored, tz=timezone.utc)
    return out.strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_key(value: Any) -> str:
    dt = _parse_timestamp(value)
    if dt is not None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value or "").strip()


def _norm_category(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_valid_alert(event: dict[str, Any]) -> bool:
    alert = event.get("alert")
    if not isinstance(alert, dict):
        return False
    sev = alert.get("severity")
    if sev is None or _safe_int(sev, 0) <= 0:
        return False
    category = _norm_category(alert.get("category"))
    if category in IGNORED_ALERT_CATEGORIES:
        return False
    return True


def _is_event_type_alert(event: dict[str, Any]) -> bool:
    return str(event.get("event_type", "")).strip().lower() == "alert"


def _has_alert_object(event: dict[str, Any]) -> bool:
    return isinstance(event.get("alert"), dict)


def _alert_policy_diagnostics(event: dict[str, Any]) -> dict[str, int]:
    """
    Keep Phase 8 aligned with the pre-split label policy.

    The initial split summary uses event_type_or_valid_alert, therefore Phase 8
    must not silently downgrade event_type=alert rows to benign just because the
    stricter valid_alert test fails.
    """
    alert = event.get("alert") if isinstance(event.get("alert"), dict) else {}
    event_type_alert = _is_event_type_alert(event)
    alert_object = isinstance(alert, dict) and bool(alert)
    alert_severity_exists = bool(alert_object and alert.get("severity") is not None and str(alert.get("severity")).strip() != "")
    ignored_category = bool(alert_object and _norm_category(alert.get("category")) in IGNORED_ALERT_CATEGORIES)
    valid_alert = _is_valid_alert(event)
    base_alert_positive = bool(event_type_alert or valid_alert)

    return {
        "event_type_alert": int(event_type_alert),
        "alert_object_rows": int(alert_object),
        "alert_severity_exists_rows": int(alert_severity_exists),
        "ignored_alert_category_rows": int(ignored_category),
        "valid_alert_rows": int(valid_alert),
        "base_alert_positive_rows": int(base_alert_positive),
        "event_type_alert_not_valid_rows": int(event_type_alert and not valid_alert),
        "valid_alert_not_event_type_rows": int(valid_alert and not event_type_alert),
    }


def _open_text_output(path: Path, compression: Optional[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if compression == "gzip":
        return gzip.open(path, "wt", encoding="utf-8", newline="")
    return path.open("w", encoding="utf-8", newline="")


def _write_jsonl(handle, row: dict[str, Any]) -> None:
    handle.write(dumps_json(row, indent=False).decode("utf-8"))
    handle.write("\n")


def _phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _csv_write_dicts(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _count_text_lines(path: Path) -> Optional[int]:
    """Count lines for small generated text artifacts.

    This helper is intentionally not used for full train/test exports because
    rereading huge CSV/JSONL files can waste hours. For train/test we use the
    already tracked row counters plus CSV header knowledge.
    """
    try:
        if not path.exists() or not path.is_file():
            return None
        opener = gzip.open if "".join(path.suffixes).lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="ignore", newline="") as f:
            return sum(1 for _ in f)
    except Exception:
        return None


def _generated_line_entry(
    path: Path,
    *,
    physical_lines: Optional[int],
    data_rows: Optional[int] = None,
    method: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": str(path),
        "physical_lines": None if physical_lines is None else int(physical_lines),
        "line_count_method": method,
        "size_bytes": int(file_size_bytes(path)),
    }
    if data_rows is not None:
        out["data_rows"] = int(data_rows)
    return out


def _tabular_physical_lines(*, data_rows: int, export_format: str) -> int:
    # CSV files include one header line. JSONL files do not.
    return int(data_rows) if str(export_format).lower() == "jsonl" else int(data_rows) + 1


# ============================================================
# Upstream loaders
# ============================================================

def _load_probe_features(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Load compact aggregate probing features.

    Key:
        (src_ip, window_start)

    This is intentionally only the selected compact columns, not the full
    original record.
    """
    if path is None or not path.exists():
        return {}

    wanted = [
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "total_bytes_window",
        "total_pkts_window",
        "bytes_per_event_window",
        "pkts_per_event_window",
        "alert_count_window",
        "event_type_alert_count_window",
        "valid_alert_count_window",
        "base_alert_positive_count_window",
        "no_alert_count_window",
        "probe_score_no_alert",
        "probe_score_with_alert",
        "fanout_high",
        "is_suspicious_window",
    ]

    out: dict[tuple[str, str], dict[str, Any]] = {}
    with open_maybe_gzip(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = loads_json_line(line)
                if not isinstance(rec, dict):
                    continue
            except Exception:
                continue

            src_ip = str(rec.get("src_ip", "")).strip()
            win = _window_key(rec.get("window_start"))
            if not src_ip or not win:
                continue

            compact = {}
            for col in wanted:
                compact[col] = rec.get(col, 0)
            out[(src_ip, win)] = compact

    return out


def _load_suspicious_keys(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}

    out: dict[tuple[str, str], dict[str, Any]] = {}
    with open_maybe_gzip(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = loads_json_line(line)
                if not isinstance(rec, dict):
                    continue
            except Exception:
                continue

            src_ip = str(rec.get("src_ip", "")).strip()
            win = _window_key(rec.get("window_start"))
            if not src_ip or not win:
                continue

            out[(src_ip, win)] = rec

    return out


def _plan_refinement_budget(
    suspicious_keys: dict[tuple[str, str], dict[str, Any]],
    probe_lookup: dict[tuple[str, str], dict[str, Any]],
    *,
    max_benign_conversion_pct: float,
    enforce: bool,
) -> dict[str, Any]:
    """Fix 1: plan a row-level cap for no-alert -> attack refinement conversions.

    Phase 4 keys are conservative, but each (src_ip, window) key would otherwise
    convert EVERY no-alert row in that window. This computes a global budget of
    converted rows = max_benign_conversion_pct% of all no-alert rows, then
    allocates it to the strongest-evidence keys first (same-window > near-window
    > higher probe score). Keys/rows beyond the budget are not converted.

    Returns a plan dict consumed by the export loop and recorded in the summary.
    """
    info: dict[str, Any] = {
        "enforced": False,
        "max_benign_conversion_pct": float(max_benign_conversion_pct),
        "total_no_alert_rows": 0,
        "conversion_budget_rows": None,
        "allocation": {},
        "conversion_keys_total": 0,
        "keys_admitted": 0,
        "keys_capped": 0,
        "note": "",
    }

    conv_keys = [
        (key, rec)
        for key, rec in suspicious_keys.items()
        if _safe_int(rec.get("Target_refined_for_no_alert"), 0) == 1
    ]
    info["conversion_keys_total"] = len(conv_keys)

    if not enforce:
        info["note"] = "row_level_cap_disabled_legacy_behavior"
        return info
    if not conv_keys:
        info["note"] = "no_conversion_keys"
        return info

    total_no_alert = sum(_safe_int(v.get("no_alert_count_window"), 0) for v in probe_lookup.values())
    info["total_no_alert_rows"] = int(total_no_alert)
    if total_no_alert <= 0:
        # Cannot compute a denominator; fail open (legacy behavior) with a note.
        info["note"] = "no_alert_denominator_unavailable_cap_skipped"
        return info

    budget = int(total_no_alert * float(max_benign_conversion_pct) / 100.0)
    info["enforced"] = True
    info["conversion_budget_rows"] = int(budget)

    def _strength(item: tuple[tuple[str, str], dict[str, Any]]):
        _, rec = item
        return (
            _safe_int(rec.get("same_alert_window"), 0),
            _safe_int(rec.get("near_alert_window"), 0),
            _safe_float(rec.get("probe_score_no_alert"), 0.0),
        )

    conv_keys.sort(key=_strength, reverse=True)

    remaining = budget
    allocation: dict[tuple[str, str], int] = {}
    for key, rec in conv_keys:
        window_rows = _safe_int(rec.get("no_alert_count_window"), 0)
        if remaining <= 0:
            allocation[key] = 0
            if window_rows > 0:
                info["keys_capped"] += 1
            continue
        want = window_rows if window_rows > 0 else remaining
        alloc = max(0, min(want, remaining))
        allocation[key] = alloc
        remaining -= alloc
        if alloc > 0:
            info["keys_admitted"] += 1
        if window_rows > alloc:
            info["keys_capped"] += 1

    info["allocation"] = allocation
    return info


def _find_phase_file(phase_dir: Path, sibling: str, names: list[str]) -> Optional[Path]:
    d = _phase_dir(phase_dir, sibling)
    for name in names:
        p = d / name
        if p.exists():
            return p
    return None


# ============================================================
# Feature extraction
# ============================================================

def _extract_base_row(event: dict[str, Any], *, app: str, window_start: str) -> dict[str, Any]:
    flow = event.get("flow") if isinstance(event.get("flow"), dict) else {}
    alert = event.get("alert") if isinstance(event.get("alert"), dict) else {}

    row: dict[str, Any] = {
        "timestamp": event.get("timestamp", ""),
        "window_start": window_start,
        "src_ip": event.get("src_ip", ""),
        "dest_ip": event.get("dest_ip", ""),
        "src_port": _safe_int(event.get("src_port"), 0),
        "dest_port": _safe_int(event.get("dest_port"), 0),
        "proto": event.get("proto", ""),
        "event_type": event.get("event_type", ""),
        "app_proto": event.get("app_proto", ""),
        "application": app,

        "pkts_toserver": _safe_int(flow.get("pkts_toserver"), 0),
        "pkts_toclient": _safe_int(flow.get("pkts_toclient"), 0),
        "bytes_toserver": _safe_int(flow.get("bytes_toserver"), 0),
        "bytes_toclient": _safe_int(flow.get("bytes_toclient"), 0),
        "duration": _safe_float(flow.get("age"), 0.0),

        "has_alert": 1 if alert else 0,
        "alert_category": alert.get("category", "") if alert else "",
        "alert_severity": _safe_int(alert.get("severity"), 0) if alert else 0,
        "alert_signature": alert.get("signature", "") if alert else "",
        "alert_signature_id": _safe_int(alert.get("signature_id"), 0) if alert else 0,
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


def _apply_phase3_features(row: dict[str, Any], probe: dict[str, Any]) -> None:
    defaults = {
        "event_count_window": 0,
        "unique_dest_ip_window": 0,
        "unique_dest_port_window": 0,
        "total_bytes_window": 0,
        "total_pkts_window": 0,
        "bytes_per_event_window": 0.0,
        "pkts_per_event_window": 0.0,
        "alert_count_window": 0,
        "event_type_alert_count_window": 0,
        "valid_alert_count_window": 0,
        "base_alert_positive_count_window": 0,
        "no_alert_count_window": 0,
        "probe_score_no_alert": 0.0,
        "probe_score_with_alert": 0.0,
        "fanout_high": 0,
        "is_suspicious_window": 0,
    }

    for k, default in defaults.items():
        value = probe.get(k, default)
        if isinstance(default, float):
            row[k] = _safe_float(value, default)
        else:
            row[k] = _safe_int(value, default)


def _apply_labels(
    row: dict[str, Any],
    *,
    valid_alert: bool,
    event_type_alert: bool,
    key_rec: Optional[dict[str, Any]],
) -> None:
    # Keep Phase 8 aligned with split_eve_by_app.py LABEL_MODE=event_type_or_valid_alert.
    # Alert evidence must not be downgraded by probing/refinement keys.
    base_alert_positive = bool(event_type_alert or valid_alert)
    target_alert = 1 if base_alert_positive else 0

    if base_alert_positive:
        target_refined = 1
        suspicious_by_probe = 0
        if valid_alert:
            label_source = "alert_confirmed"
            refinement_reason = "valid_suricata_alert"
        else:
            label_source = "event_type_alert_confirmed"
            refinement_reason = "event_type_alert_policy"
    elif key_rec:
        target_refined = _safe_int(key_rec.get("Target_refined_for_no_alert"), 0)
        suspicious_by_probe = _safe_int(key_rec.get("suspicious_by_probe"), 0)
        label_source = str(key_rec.get("label_source", "suspicious_probe_only"))
        refinement_reason = str(key_rec.get("refinement_reason", "phase4_key_match"))
    else:
        target_refined = 0
        suspicious_by_probe = 0
        label_source = "benign_no_evidence"
        refinement_reason = "no_alert_or_probe_refinement_key"

    row["Target_alert"] = int(target_alert)
    row["Target_refined"] = int(target_refined)
    row["Target"] = int(target_refined)
    row["suspicious_by_probe"] = int(suspicious_by_probe)
    row["label_source"] = label_source
    row["refinement_reason"] = refinement_reason


def _apply_computed_features(row: dict[str, Any]) -> None:
    total_bytes = _safe_float(row.get("total_bytes"), 0.0)
    total_pkts = _safe_float(row.get("total_pkts"), 0.0)
    duration = _safe_float(row.get("duration"), 0.0)
    bytes_toserver = _safe_float(row.get("bytes_toserver"), 0.0)
    bytes_toclient = _safe_float(row.get("bytes_toclient"), 0.0)
    pkts_toserver = _safe_float(row.get("pkts_toserver"), 0.0)
    pkts_toclient = _safe_float(row.get("pkts_toclient"), 0.0)

    row["bytes_per_pkt"] = total_bytes / max(total_pkts, 1.0)
    row["pkts_per_sec"] = total_pkts / max(duration, 1e-6)
    row["bytes_per_sec"] = total_bytes / max(duration, 1e-6)

    row["bytes_toserver_ratio"] = bytes_toserver / max(total_bytes, 1.0)
    row["bytes_toclient_ratio"] = bytes_toclient / max(total_bytes, 1.0)
    row["pkts_toserver_ratio"] = pkts_toserver / max(total_pkts, 1.0)
    row["pkts_toclient_ratio"] = pkts_toclient / max(total_pkts, 1.0)

    row["log_total_bytes"] = math.log1p(max(total_bytes, 0.0))
    row["log_total_pkts"] = math.log1p(max(total_pkts, 0.0))
    row["log_duration"] = math.log1p(max(duration, 0.0))

    src_port = _safe_int(row.get("src_port"), 0)
    dest_port = _safe_int(row.get("dest_port"), 0)

    row["src_port_class"] = _classify_port(src_port)
    row["dest_port_class"] = _classify_port(dest_port)

    row["dport_is_dns"] = int(dest_port == 53)
    row["dport_is_http"] = int(dest_port in {80, 8080, 8000, 8008, 8888})
    row["dport_is_https"] = int(dest_port in {443, 8443})
    row["dport_is_ssh"] = int(dest_port == 22)

    ts = _parse_timestamp(row.get("timestamp"))
    if ts:
        row["ts_hour"] = ts.hour
        row["ts_dow"] = ts.weekday()
        row["ts_is_weekend"] = int(ts.weekday() >= 5)
    else:
        row["ts_hour"] = 0
        row["ts_dow"] = 0
        row["ts_is_weekend"] = 0

    src_ip = row.get("src_ip", "")
    dest_ip = row.get("dest_ip", "")

    row["src_is_private"] = _private_ipv4(src_ip)
    row["dest_is_private"] = _private_ipv4(dest_ip)
    row["src_subnet24_h"] = _stable_hash(_subnet24(src_ip))
    row["dest_subnet24_h"] = _stable_hash(_subnet24(dest_ip))
    row["same_subnet24"] = int(row["src_subnet24_h"] == row["dest_subnet24_h"])

    row["proto_h"] = _stable_hash(row.get("proto", ""))
    row["event_type_h"] = _stable_hash(row.get("event_type", ""))
    row["app_proto_h"] = _stable_hash(row.get("app_proto", ""))

    app = row.get("application", "")
    if app == "http":
        row["http_method_h"] = _stable_hash(row.get("http_method", ""))
        row["http_status_class"] = _safe_int(row.get("http_status"), 0) // 100
    elif app == "tls":
        row["tls_version_h"] = _stable_hash(row.get("tls_version", ""))
        row["tls_has_sni"] = int(_safe_int(row.get("tls_sni_len"), 0) > 0)
    elif app == "dns":
        row["dns_rrtype_h"] = _stable_hash(row.get("dns_rrtype", ""))
        row["dns_rcode_h"] = _stable_hash(row.get("dns_rcode", ""))
        row["dns_query_name_present"] = int(_safe_int(row.get("dns_rrname_len"), 0) > 0)
    elif app == "ssh":
        row["ssh_protocol_h"] = _stable_hash(row.get("ssh_protocol", ""))
        row["ssh_has_client_version"] = int(_safe_int(row.get("ssh_client_version_len"), 0) > 0)
        row["ssh_has_server_version"] = int(_safe_int(row.get("ssh_server_version_len"), 0) > 0)

    # Conservative interactions.
    row["interaction_total_bytes_duration"] = row["log_total_bytes"] * row["log_duration"]
    row["interaction_total_pkts_duration"] = row["log_total_pkts"] * row["log_duration"]
    row["interaction_bytes_rate_packet_rate"] = row["bytes_per_sec"] * row["pkts_per_sec"]


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            out[k] = 0 if k not in {"timestamp", "window_start", "src_ip", "dest_ip", "proto", "event_type", "app_proto", "application", "alert_category", "alert_signature", "label_source", "refinement_reason"} else ""
            continue

        if isinstance(v, float):
            out[k] = v if math.isfinite(v) else 0.0
        elif isinstance(v, (int, str)):
            out[k] = v
        else:
            out[k] = json.dumps(v, ensure_ascii=False, default=str)
    return out


def _split_destination(row: dict[str, Any], *, strategy: str, train_ratio: float, seed: int, row_no: int) -> str:
    train_ratio = max(0.0, min(1.0, float(train_ratio)))
    strategy = str(strategy or "group_hash").lower()

    if strategy == "group_hash":
        # Safer than src_ip-only for this pipeline.
        # src_ip-only can put an entire small app/class into one split when the
        # number of source IPs is limited. The app+window+src_ip key still avoids
        # pure row-random leakage while reducing the risk of empty train/test.
        key_parts = [
            row.get("application", ""),
            row.get("window_start", ""),
            row.get("src_ip", ""),
        ]
        key = "|".join(str(x) for x in key_parts if str(x).strip())
        if not key:
            key = row.get("dest_ip") or row_no

        h = _stable_hash(f"{seed}:{key}", mod=1_000_000)
        return "train" if (h / 1_000_000.0) < train_ratio else "test"

    if strategy == "random_stratified":
        key = f"{seed}:{row.get('src_ip','')}:{row.get('timestamp','')}:{row_no}"
        h = _stable_hash(key, mod=1_000_000)
        return "train" if (h / 1_000_000.0) < train_ratio else "test"

    if strategy == "time_based":
        # Streaming-safe fallback: deterministic hash if no precomputed cutoff exists.
        key = f"{seed}:time:{row.get('timestamp','')}:{row_no}"
        h = _stable_hash(key, mod=1_000_000)
        return "train" if (h / 1_000_000.0) < train_ratio else "test"

    key = f"{seed}:{row_no}"
    h = _stable_hash(key, mod=1_000_000)
    return "train" if (h / 1_000_000.0) < train_ratio else "test"


# ============================================================
# Output schema / samples
# ============================================================

def _build_fieldnames(app: str, computed_rules: dict[str, Any]) -> list[str]:
    common = [
        "timestamp", "window_start", "src_ip", "dest_ip", "src_port", "dest_port",
        "proto", "event_type", "app_proto", "application",
        "pkts_toserver", "pkts_toclient", "bytes_toserver", "bytes_toclient",
        "duration", "total_pkts", "total_bytes",
        "has_alert", "alert_category", "alert_severity", "alert_signature", "alert_signature_id",
    ]

    app_cols = {
        "http": ["http_method", "http_hostname_len", "http_url_len", "http_user_agent_len", "http_status", "http_method_h", "http_status_class"],
        "tls": ["tls_sni_len", "tls_version", "tls_ja3_len", "tls_ja3s_len", "tls_version_h", "tls_has_sni"],
        "dns": ["dns_rrname_len", "dns_rrtype", "dns_rcode", "dns_type", "dns_rrtype_h", "dns_rcode_h", "dns_query_name_present"],
        "ssh": ["ssh_client_version_len", "ssh_server_version_len", "ssh_protocol", "ssh_protocol_h", "ssh_has_client_version", "ssh_has_server_version"],
    }.get(app, [])

    phase3 = [
        "event_count_window", "unique_dest_ip_window", "unique_dest_port_window",
        "total_bytes_window", "total_pkts_window", "bytes_per_event_window", "pkts_per_event_window",
        "alert_count_window", "event_type_alert_count_window", "valid_alert_count_window",
        "base_alert_positive_count_window", "no_alert_count_window",
        "probe_score_no_alert", "probe_score_with_alert", "fanout_high", "is_suspicious_window",
    ]

    labels = [
        "Target_alert", "Target_refined", "Target",
        "suspicious_by_probe", "label_source", "refinement_reason",
    ]

    computed_from_rules = []
    for r in computed_rules.get("rules", []):
        if isinstance(r, dict) and r.get("name"):
            name = str(r["name"])
            if name not in computed_from_rules:
                computed_from_rules.append(name)

    fallback_computed = [
        "bytes_per_pkt", "pkts_per_sec", "bytes_per_sec",
        "bytes_toserver_ratio", "bytes_toclient_ratio",
        "pkts_toserver_ratio", "pkts_toclient_ratio",
        "log_total_bytes", "log_total_pkts", "log_duration",
        "src_port_class", "dest_port_class",
        "dport_is_dns", "dport_is_http", "dport_is_https", "dport_is_ssh",
        "ts_hour", "ts_dow", "ts_is_weekend",
        "src_is_private", "dest_is_private", "src_subnet24_h", "dest_subnet24_h", "same_subnet24",
        "proto_h", "event_type_h", "app_proto_h",
        "interaction_total_bytes_duration", "interaction_total_pkts_duration", "interaction_bytes_rate_packet_rate",
    ]

    out: list[str] = []
    for c in common + app_cols + phase3 + labels + computed_from_rules + fallback_computed:
        if c not in out:
            out.append(c)
    return out


def _schema_rows(fieldnames: list[str], feature_roles: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name in fieldnames:
        role = feature_roles.get(name, {})
        rows.append({
            "name": name,
            "role": role.get("role", ""),
            "group": role.get("group", ""),
            "dtype_policy": role.get("dtype", "auto"),
            "training_candidate": role.get("training_candidate", None),
            "leakage_risk": role.get("leakage_risk", ""),
        })
    return rows


def _feature_roles_from_inputs(
    base_schema: dict[str, Any],
    computed_schema: dict[str, Any],
    fieldnames: list[str],
) -> dict[str, Any]:
    roles: dict[str, Any] = {}

    for schema, source in ((base_schema, "phase5"), (computed_schema, "phase6")):
        cols = schema.get("columns", [])
        if isinstance(cols, list):
            for c in cols:
                if isinstance(c, dict) and c.get("name"):
                    roles[str(c["name"])] = {
                        **c,
                        "source_phase": source,
                    }

    # Ensure output-only labels and defaults are represented.
    for name in fieldnames:
        roles.setdefault(name, {
            "name": name,
            "role": "materialized_feature",
            "group": "materialized",
            "dtype": "auto",
            "training_candidate": name not in {"Target", "Target_alert", "Target_refined"},
            "leakage_risk": "target" if name in {"Target", "Target_alert", "Target_refined"} else "unknown",
            "source_phase": "phase8",
        })

    return roles


class _Reservoir:
    def __init__(self, k: int, seed: int) -> None:
        self.k = max(0, int(k))
        self.rng = random.Random(int(seed))
        self.n_seen = 0
        self.rows: list[dict[str, Any]] = []

    def add(self, row: dict[str, Any]) -> None:
        if self.k <= 0:
            return
        self.n_seen += 1
        if len(self.rows) < self.k:
            self.rows.append(dict(row))
            return
        j = self.rng.randint(1, self.n_seen)
        if j <= self.k:
            self.rows[j - 1] = dict(row)


class _NumericSummary:
    """Streaming numeric summary used by Phase 9 without rereading train/test."""

    def __init__(self) -> None:
        self.count = 0
        self.missing = 0
        self.nonzero = 0
        self.total = 0.0
        self.min_value: Optional[float] = None
        self.max_value: Optional[float] = None

    def add(self, value: Any) -> None:
        try:
            if value is None or value == "":
                self.missing += 1
                return
            x = float(value)
            if not math.isfinite(x):
                self.missing += 1
                return
        except Exception:
            self.missing += 1
            return

        self.count += 1
        self.total += x
        if x != 0:
            self.nonzero += 1
        self.min_value = x if self.min_value is None else min(self.min_value, x)
        self.max_value = x if self.max_value is None else max(self.max_value, x)

    def as_dict(self) -> dict[str, Any]:
        mean = self.total / self.count if self.count else 0.0
        return {
            "count": int(self.count),
            "missing": int(self.missing),
            "nonzero": int(self.nonzero),
            "min": float(self.min_value) if self.min_value is not None else None,
            "max": float(self.max_value) if self.max_value is not None else None,
            "sum": float(self.total),
            "mean": float(mean),
        }


def _counter_json(counter: Counter) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def _nested_counter_json(data: dict[Any, Counter]) -> dict[str, dict[str, int]]:
    return {str(k): _counter_json(v) for k, v in sorted(data.items(), key=lambda kv: str(kv[0]))}


def _top_counter_json(counter: Counter, *, top_n: int = 30) -> dict[str, int]:
    return {str(k): int(v) for k, v in counter.most_common(int(top_n))}


def _class_summary(
    *,
    role: str,
    path: Optional[Path],
    target_counts: Counter | dict[Any, Any],
    data_rows: Optional[int] = None,
    size_bytes: Optional[int] = None,
) -> dict[str, Any]:
    counts = Counter()
    if isinstance(target_counts, Counter):
        counts.update(target_counts)
    elif isinstance(target_counts, dict):
        for k, v in target_counts.items():
            counts[_safe_int(k, 0)] += _safe_int(v, 0)

    benign = int(counts.get(0, 0))
    attack = int(counts.get(1, 0))
    total = int(data_rows) if data_rows is not None else int(sum(counts.values()))
    if total <= 0:
        total = int(sum(counts.values()))
    return {
        "role": role,
        "path": str(path) if path is not None else None,
        "data_rows": int(total),
        "benign": benign,
        "attack": attack,
        "malicious": attack,
        "target_counts": _counter_json(counts),
        "benign_ratio": float(benign / total) if total else 0.0,
        "attack_ratio": float(attack / total) if total else 0.0,
        "size_bytes": int(size_bytes) if size_bytes is not None else (int(file_size_bytes(path)) if path is not None else 0),
    }


def _numeric_bucket(value: Any) -> str:
    x = _safe_float(value, 0.0)
    if x <= 0:
        return "0"
    if x <= 1:
        return "0-1"
    if x <= 10:
        return "1-10"
    if x <= 100:
        return "10-100"
    if x <= 1_000:
        return "100-1K"
    if x <= 10_000:
        return "1K-10K"
    if x <= 100_000:
        return "10K-100K"
    if x <= 1_000_000:
        return "100K-1M"
    return ">1M"


def _ratio_bucket(value: Any) -> str:
    x = _safe_float(value, 0.0)
    if x <= 0:
        return "0"
    if x < 0.25:
        return "0-0.25"
    if x < 0.50:
        return "0.25-0.50"
    if x < 0.75:
        return "0.50-0.75"
    if x < 1.00:
        return "0.75-1.00"
    return ">=1.00"


def _hist_bucket(feature: str, value: Any) -> str:
    if feature.endswith("_ratio") or feature in {"probe_score_no_alert", "probe_score_with_alert"}:
        return _ratio_bucket(value)
    return _numeric_bucket(value)


def _flatten_counts_rows(
    *,
    app: str,
    group_name: str,
    counter: Counter,
    top_n: Optional[int] = None,
) -> list[dict[str, Any]]:
    items = counter.most_common(int(top_n)) if top_n else sorted(counter.items(), key=lambda kv: str(kv[0]))
    return [
        {
            "app": app,
            "group": group_name,
            "key": str(k),
            "count": int(v),
        }
        for k, v in items
    ]


def _feature_name_lists() -> tuple[list[str], list[str]]:
    numeric_summary_features = [
        "total_pkts",
        "total_bytes",
        "duration",
        "bytes_per_pkt",
        "pkts_per_sec",
        "bytes_per_sec",
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "total_bytes_window",
        "total_pkts_window",
        "probe_score_no_alert",
        "probe_score_with_alert",
        "bytes_toserver_ratio",
        "bytes_toclient_ratio",
        "pkts_toserver_ratio",
        "pkts_toclient_ratio",
    ]
    histogram_features = [
        "total_pkts",
        "total_bytes",
        "duration",
        "bytes_per_pkt",
        "pkts_per_sec",
        "bytes_per_sec",
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "probe_score_no_alert",
        "probe_score_with_alert",
        "bytes_toserver_ratio",
        "pkts_toserver_ratio",
    ]
    return numeric_summary_features, histogram_features


# ============================================================
# Runner
# ============================================================

def run_phase8(
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

    split_cfg = getattr(cfg, "split", None)
    export_cfg = getattr(cfg, "export", None)
    probing_cfg = getattr(cfg, "probing", None)

    train_ratio = float(getattr(split_cfg, "train_ratio", 0.8) or 0.8)
    test_ratio = float(getattr(split_cfg, "test_ratio", 0.2) or 0.2)
    split_strategy = str(getattr(split_cfg, "strategy", "group_hash") or "group_hash")
    seed = int(getattr(split_cfg, "random_seed", getattr(cfg, "seed", 42)) or 42)
    target_column = str(getattr(split_cfg, "target_column", "Target_refined") or "Target_refined")

    export_format = str(getattr(export_cfg, "format", "csv") or "csv").lower()
    compression = getattr(export_cfg, "compression", None)
    if compression == "none":
        compression = None

    visualization_sample_rows = int(getattr(export_cfg, "visualization_sample_rows", 300_000) or 300_000)
    corr_leak_sample_rows = int(getattr(export_cfg, "corr_leak_sample_rows", 1_000_000) or 1_000_000)
    window_minutes = int(getattr(probing_cfg, "window_minutes", 5) or 5)

    phase3_probe_path = _find_phase_file(phase_dir, "phase3", [f"phase3_{app}_probe_features.jsonl", "probe_features.jsonl"])
    phase4_keys_path = _find_phase_file(phase_dir, "phase4", [f"phase4_{app}_suspicious_keys.jsonl", "suspicious_keys.jsonl"])
    phase5_manifest_path = _phase_dir(phase_dir, "phase5") / "feature_manifest.json"
    phase5_schema_path = _phase_dir(phase_dir, "phase5") / "base_feature_schema.json"
    phase6_rules_path = _phase_dir(phase_dir, "phase6") / "computed_feature_rules.json"
    phase6_schema_path = _phase_dir(phase_dir, "phase6") / "computed_feature_schema.json"
    phase7_policy_path = _phase_dir(phase_dir, "phase7") / "cleaning_policy.json"
    phase7_drop_path = _phase_dir(phase_dir, "phase7") / "leakage_drop_list.json"
    phase7_training_path = _phase_dir(phase_dir, "phase7") / "training_feature_list.json"

    feature_manifest = _read_optional_json(phase5_manifest_path)
    base_schema = _read_optional_json(phase5_schema_path)
    computed_rules = _read_optional_json(phase6_rules_path)
    computed_schema = _read_optional_json(phase6_schema_path)
    cleaning_policy = _read_optional_json(phase7_policy_path)
    leakage_drop = _read_optional_json(phase7_drop_path)
    training_features = _read_optional_json(phase7_training_path)

    print("\n" + "=" * 72)
    print("Phase 8 - Export Feature-Ready Dataset and Split")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {app_input_path}")
    print(f"Split       : {split_strategy} ({train_ratio:.2f}/{test_ratio:.2f})")
    print(f"Output      : {phase_dir}")
    print("=" * 72)

    print("Loading Phase 3/4 lookup evidence...")
    probe_lookup = _load_probe_features(phase3_probe_path)
    suspicious_keys = _load_suspicious_keys(phase4_keys_path)
    print(f"Probe lookup windows : {len(probe_lookup):,}")
    print(f"Phase 4 keys         : {len(suspicious_keys):,}")

    # Fix 1: cap no-alert -> attack refinement conversions at row level.
    max_benign_conversion_pct = float(getattr(probing_cfg, "max_benign_conversion_pct", 5.0) or 5.0)
    enforce_row_cap = bool(getattr(probing_cfg, "enforce_row_level_conversion_cap", True))
    refinement_budget = _plan_refinement_budget(
        suspicious_keys,
        probe_lookup,
        max_benign_conversion_pct=max_benign_conversion_pct,
        enforce=enforce_row_cap,
    )
    refinement_enforced = bool(refinement_budget.get("enforced"))
    refinement_allocation: dict[tuple[str, str], int] = refinement_budget.get("allocation", {})
    conversion_used: Counter = Counter()
    rows_converted_total = 0
    rows_conversion_capped_total = 0
    if refinement_enforced:
        print(
            f"Row-level cap        : ON | no_alert_rows={refinement_budget.get('total_no_alert_rows'):,} "
            f"| budget={refinement_budget.get('conversion_budget_rows'):,} "
            f"| keys_admitted={refinement_budget.get('keys_admitted')} "
            f"| keys_capped={refinement_budget.get('keys_capped')}"
        )
    else:
        print(f"Row-level cap        : OFF ({refinement_budget.get('note')})")

    fieldnames = _build_fieldnames(app, computed_rules)
    feature_roles = _feature_roles_from_inputs(base_schema, computed_schema, fieldnames)

    ext = "jsonl" if export_format == "jsonl" else "csv"
    suffix = f".{ext}.gz" if compression == "gzip" else f".{ext}"

    train_path = phase_dir / f"train{suffix}"
    test_path = phase_dir / f"test{suffix}"

    visualization_sample_path = phase_dir / "visualization_sample.csv"
    corr_leak_sample_path = phase_dir / "corr_leak_sample.csv"
    visualization_aggregates_path = phase_dir / "visualization_aggregates.json"
    visualization_aggregate_counts_path = phase_dir / "visualization_aggregate_counts.csv"
    visualization_numeric_histograms_path = phase_dir / "visualization_numeric_histograms.csv"
    file_class_summary_path = phase_dir / "file_class_summary.csv"
    export_summary_path = phase_dir / "export_summary.json"
    split_summary_path = phase_dir / "split_summary.json"
    schema_path = phase_dir / "schema.json"
    feature_roles_path = phase_dir / "feature_roles.json"
    label_dist_path = phase_dir / "label_distribution.csv"
    availability_path = phase_dir / "feature_availability.csv"
    missing_path = phase_dir / "missing_value_summary.csv"
    feature_group_path = phase_dir / "feature_group_summary.csv"
    manifest_path = phase_dir / "manifest.json"
    summary_alias = phase_dir / "summary.json"

    viz_sampler = _Reservoir(visualization_sample_rows, seed + 101)
    corr_sampler = _Reservoir(corr_leak_sample_rows, seed + 202)

    rows_seen = 0
    rows_written = 0
    malformed = 0
    no_timestamp = 0
    no_src_ip = 0

    split_counts = Counter()
    target_counts = Counter()
    target_alert_counts = Counter()
    label_source_counts = Counter()
    alert_policy_counts = Counter()

    # Needed by Phase 11 so it can report exact benign/attack distribution
    # per train/test without rereading train.csv/test.csv.
    target_counts_by_split = {
        "train": Counter(),
        "test": Counter(),
    }
    target_alert_counts_by_split = {
        "train": Counter(),
        "test": Counter(),
    }
    label_source_counts_by_split = {
        "train": Counter(),
        "test": Counter(),
    }

    availability_sample_limit = int(getattr(export_cfg, "summary_sample_rows", 100_000) or 100_000)
    availability_seen = 0
    present_counts = Counter()
    missing_counts = Counter()

    # Full-data aggregate statistics for Phase 9 visualization.
    # These are exact over all rows written by Phase 8, so Phase 9 can render
    # charts without sampling or rereading train/test files.
    numeric_summary_features, histogram_features = _feature_name_lists()
    viz_split_counts = Counter()
    viz_target_counts = Counter()
    viz_event_type_counts = Counter()
    viz_proto_counts = Counter()
    viz_app_proto_counts = Counter()
    viz_alert_severity_counts = Counter()
    viz_alert_category_counts = Counter()
    viz_label_source_counts = Counter()
    viz_dest_port_counts = Counter()
    viz_src_port_class_counts = Counter()
    viz_dest_port_class_counts = Counter()
    viz_target_by_split: dict[str, Counter] = defaultdict(Counter)
    viz_event_type_by_target: dict[int, Counter] = defaultdict(Counter)
    viz_proto_by_target: dict[int, Counter] = defaultdict(Counter)
    viz_alert_severity_by_target: dict[int, Counter] = defaultdict(Counter)
    viz_label_source_by_target: dict[int, Counter] = defaultdict(Counter)
    viz_numeric_summary: dict[str, _NumericSummary] = {name: _NumericSummary() for name in numeric_summary_features}
    viz_numeric_summary_by_target: dict[str, dict[int, _NumericSummary]] = {
        name: {0: _NumericSummary(), 1: _NumericSummary()} for name in numeric_summary_features
    }
    viz_histograms: dict[str, Counter] = {name: Counter() for name in histogram_features}
    viz_histograms_by_target: dict[str, dict[int, Counter]] = {
        name: {0: Counter(), 1: Counter()} for name in histogram_features
    }

    train_writer = None
    test_writer = None
    train_handle = None
    test_handle = None

    try:
        train_handle = _open_text_output(train_path, compression)
        test_handle = _open_text_output(test_path, compression)

        if export_format == "jsonl":
            train_writer = None
            test_writer = None
        else:
            train_writer = csv.DictWriter(train_handle, fieldnames=fieldnames, extrasaction="ignore")
            test_writer = csv.DictWriter(test_handle, fieldnames=fieldnames, extrasaction="ignore")
            train_writer.writeheader()
            test_writer.writeheader()

        progress_every = int(getattr(cfg, "phase_progress_every", 1_000_000) or 1_000_000)

        with open_maybe_gzip(app_input_path, "rb") as f:
            for line in f:
                rows_seen += 1
                raw = line.strip()
                if not raw:
                    continue

                try:
                    event = loads_json_line(raw)
                    if not isinstance(event, dict):
                        malformed += 1
                        continue
                except Exception:
                    malformed += 1
                    continue

                ts = _parse_timestamp(event.get("timestamp"))
                if ts is None:
                    no_timestamp += 1

                src_ip = str(event.get("src_ip", "") or "").strip()
                if not src_ip:
                    no_src_ip += 1

                win = _floor_window(ts, window_minutes)
                row = _extract_base_row(event, app=app, window_start=win)

                key = (str(row.get("src_ip", "")).strip(), win)
                _apply_phase3_features(row, probe_lookup.get(key, {}))

                alert_diag = _alert_policy_diagnostics(event)
                for diag_key, diag_value in alert_diag.items():
                    if diag_value:
                        alert_policy_counts[diag_key] += int(diag_value)

                valid_alert = bool(alert_diag.get("valid_alert_rows", 0))
                event_type_alert = bool(alert_diag.get("event_type_alert", 0))

                # Fix 1: gate refinement so a few keys cannot flip the majority
                # of no-alert rows. Alert-positive rows are unaffected (their
                # label comes from the alert evidence, not the key).
                eff_key_rec = suspicious_keys.get(key)
                if (
                    refinement_enforced
                    and eff_key_rec is not None
                    and not (valid_alert or event_type_alert)
                    and _safe_int(eff_key_rec.get("Target_refined_for_no_alert"), 0) == 1
                ):
                    alloc = int(refinement_allocation.get(key, 0))
                    if conversion_used[key] < alloc:
                        conversion_used[key] += 1
                        rows_converted_total += 1
                    else:
                        # Over budget: keep suspicious audit flag but do not
                        # convert this row to attack.
                        eff_key_rec = dict(eff_key_rec)
                        eff_key_rec["Target_refined_for_no_alert"] = 0
                        rows_conversion_capped_total += 1

                _apply_labels(
                    row,
                    valid_alert=valid_alert,
                    event_type_alert=event_type_alert,
                    key_rec=eff_key_rec,
                )
                _apply_computed_features(row)
                row = _clean_row(row)

                # Ensure all declared fields exist.
                for name in fieldnames:
                    if name not in row:
                        row[name] = 0

                dest = _split_destination(
                    row,
                    strategy=split_strategy,
                    train_ratio=train_ratio,
                    seed=seed,
                    row_no=rows_seen,
                )

                if export_format == "jsonl":
                    if dest == "train":
                        _write_jsonl(train_handle, {k: row.get(k, 0) for k in fieldnames})
                    else:
                        _write_jsonl(test_handle, {k: row.get(k, 0) for k in fieldnames})
                else:
                    if dest == "train":
                        train_writer.writerow(row)
                    else:
                        test_writer.writerow(row)

                split_counts[dest] += 1
                rows_written += 1

                target_value = _safe_int(row.get(target_column, row.get("Target_refined", 0)), 0)
                target_alert_value = _safe_int(row.get("Target_alert"), 0)
                label_source_value = str(row.get("label_source", "unknown"))

                target_counts[target_value] += 1
                target_alert_counts[target_alert_value] += 1
                label_source_counts[label_source_value] += 1

                if dest not in target_counts_by_split:
                    target_counts_by_split[dest] = Counter()
                    target_alert_counts_by_split[dest] = Counter()
                    label_source_counts_by_split[dest] = Counter()

                target_counts_by_split[dest][target_value] += 1
                target_alert_counts_by_split[dest][target_alert_value] += 1
                label_source_counts_by_split[dest][label_source_value] += 1

                # Exact full-data aggregates for Phase 9 visualization.
                viz_split_counts[dest] += 1
                viz_target_counts[target_value] += 1
                viz_target_by_split[dest][target_value] += 1

                event_type_value = str(row.get("event_type", "unknown") or "unknown")
                proto_value = str(row.get("proto", "unknown") or "unknown")
                app_proto_value = str(row.get("app_proto", "unknown") or "unknown")
                alert_category_value = str(row.get("alert_category", "none") or "none")
                alert_severity_value = str(row.get("alert_severity", 0) or 0)

                viz_event_type_counts[event_type_value] += 1
                viz_proto_counts[proto_value] += 1
                viz_app_proto_counts[app_proto_value] += 1
                viz_alert_category_counts[alert_category_value] += 1
                viz_alert_severity_counts[alert_severity_value] += 1
                viz_label_source_counts[label_source_value] += 1
                viz_dest_port_counts[str(row.get("dest_port", 0))] += 1
                viz_src_port_class_counts[str(row.get("src_port_class", 0))] += 1
                viz_dest_port_class_counts[str(row.get("dest_port_class", 0))] += 1

                viz_event_type_by_target[target_value][event_type_value] += 1
                viz_proto_by_target[target_value][proto_value] += 1
                viz_alert_severity_by_target[target_value][alert_severity_value] += 1
                viz_label_source_by_target[target_value][label_source_value] += 1

                normalized_target = 1 if target_value == 1 else 0
                for feature in numeric_summary_features:
                    if feature in row:
                        viz_numeric_summary[feature].add(row.get(feature))
                        viz_numeric_summary_by_target[feature][normalized_target].add(row.get(feature))
                for feature in histogram_features:
                    if feature in row:
                        bucket = _hist_bucket(feature, row.get(feature))
                        viz_histograms[feature][bucket] += 1
                        viz_histograms_by_target[feature][normalized_target][bucket] += 1

                viz_sampler.add(row)
                corr_sampler.add(row)

                if availability_seen < availability_sample_limit:
                    availability_seen += 1
                    for name in fieldnames:
                        value = row.get(name)
                        if value is None or value == "":
                            missing_counts[name] += 1
                        else:
                            present_counts[name] += 1

                if progress_every > 0 and rows_seen % progress_every == 0:
                    print(
                        f"[Phase 8 {app.upper()}] scanned={rows_seen:,} | "
                        f"written={rows_written:,} | train={split_counts['train']:,} | "
                        f"test={split_counts['test']:,}",
                        flush=True,
                    )

    finally:
        if train_handle is not None:
            train_handle.close()
        if test_handle is not None:
            test_handle.close()

    # Write samples after the full pass.
    _csv_write_dicts(visualization_sample_path, viz_sampler.rows, fieldnames)
    _csv_write_dicts(corr_leak_sample_path, corr_sampler.rows, fieldnames)

    schema = {
        "phase": 8,
        "app": app,
        "created_at": now_iso(),
        "target_column": target_column,
        "columns": _schema_rows(fieldnames, feature_roles),
        "column_count": len(fieldnames),
    }
    write_json(schema, schema_path)
    write_json(feature_roles, feature_roles_path)

    label_rows = [
        {"label_type": "Target_refined", "label": str(k), "count": int(v)}
        for k, v in sorted(target_counts.items(), key=lambda kv: str(kv[0]))
    ] + [
        {"label_type": "Target_alert", "label": str(k), "count": int(v)}
        for k, v in sorted(target_alert_counts.items(), key=lambda kv: str(kv[0]))
    ] + [
        {"label_type": "label_source", "label": str(k), "count": int(v)}
        for k, v in label_source_counts.most_common()
    ]
    _csv_write_dicts(label_dist_path, label_rows, ["label_type", "label", "count"])

    availability_rows = []
    for name in fieldnames:
        present = int(present_counts.get(name, 0))
        missing = int(missing_counts.get(name, 0))
        total = present + missing
        availability_rows.append({
            "column": name,
            "sample_rows": total,
            "present": present,
            "missing": missing,
            "availability_ratio": (present / total) if total else None,
        })
    _csv_write_dicts(availability_path, availability_rows, ["column", "sample_rows", "present", "missing", "availability_ratio"])
    _csv_write_dicts(missing_path, availability_rows, ["column", "sample_rows", "present", "missing", "availability_ratio"])

    group_counter = Counter()
    for name in fieldnames:
        group_counter[str(feature_roles.get(name, {}).get("group", "unknown"))] += 1
    group_rows = [{"group": k, "feature_count": int(v)} for k, v in group_counter.most_common()]
    _csv_write_dicts(feature_group_path, group_rows, ["group", "feature_count"])

    target_counts_by_split_json = {
        split_name: {str(k): int(v) for k, v in counter.items()}
        for split_name, counter in target_counts_by_split.items()
    }
    target_alert_counts_by_split_json = {
        split_name: {str(k): int(v) for k, v in counter.items()}
        for split_name, counter in target_alert_counts_by_split.items()
    }
    label_source_counts_by_split_json = {
        split_name: {str(k): int(v) for k, v in counter.items()}
        for split_name, counter in label_source_counts_by_split.items()
    }

    # Explicit class summary requested by downstream report/PDF:
    # total dataset + each physical split file. This lets later phases report
    # benign/attack counts without rereading huge train/test files.
    file_class_summary = {
        "dataset_total": _class_summary(
            role="dataset_total",
            path=None,
            target_counts=target_counts,
            data_rows=int(rows_written),
            size_bytes=int(file_size_bytes(train_path) + file_size_bytes(test_path)),
        ),
        "train": _class_summary(
            role="train",
            path=train_path,
            target_counts=target_counts_by_split.get("train", Counter()),
            data_rows=int(split_counts.get("train", 0)),
            size_bytes=int(file_size_bytes(train_path)),
        ),
        "test": _class_summary(
            role="test",
            path=test_path,
            target_counts=target_counts_by_split.get("test", Counter()),
            data_rows=int(split_counts.get("test", 0)),
            size_bytes=int(file_size_bytes(test_path)),
        ),
    }
    file_class_rows = [
        {
            "app": app,
            "file_key": key,
            "role": value.get("role"),
            "path": value.get("path"),
            "data_rows": value.get("data_rows"),
            "benign": value.get("benign"),
            "attack": value.get("attack"),
            "malicious": value.get("malicious"),
            "benign_ratio": value.get("benign_ratio"),
            "attack_ratio": value.get("attack_ratio"),
            "size_bytes": value.get("size_bytes"),
            "target_counts": dumps_json(value.get("target_counts", {}), indent=False).decode("utf-8"),
        }
        for key, value in file_class_summary.items()
    ]
    _csv_write_dicts(
        file_class_summary_path,
        file_class_rows,
        ["app", "file_key", "role", "path", "data_rows", "benign", "attack", "malicious", "benign_ratio", "attack_ratio", "size_bytes", "target_counts"],
    )

    visualization_numeric_summary = {
        name: summary.as_dict()
        for name, summary in viz_numeric_summary.items()
    }
    visualization_numeric_summary_by_target = {
        name: {str(cls): cls_summary.as_dict() for cls, cls_summary in summaries.items()}
        for name, summaries in viz_numeric_summary_by_target.items()
    }
    visualization_histograms = {
        name: _counter_json(counter)
        for name, counter in viz_histograms.items()
    }
    visualization_histograms_by_target = {
        name: {str(cls): _counter_json(counter) for cls, counter in cls_counters.items()}
        for name, cls_counters in viz_histograms_by_target.items()
    }
    visualization_aggregates = {
        "phase": 8,
        "app": app,
        "created_at": now_iso(),
        "source": "phase8_full_scan_exact_aggregates",
        "rows_seen": int(rows_seen),
        "rows_written": int(rows_written),
        "target_column": target_column,
        "split_counts": _counter_json(viz_split_counts),
        "target_counts": _counter_json(viz_target_counts),
        "target_counts_by_split": _nested_counter_json(viz_target_by_split),
        "event_type_counts_top": _top_counter_json(viz_event_type_counts, top_n=30),
        "proto_counts": _counter_json(viz_proto_counts),
        "app_proto_counts_top": _top_counter_json(viz_app_proto_counts, top_n=30),
        "alert_severity_counts": _counter_json(viz_alert_severity_counts),
        "alert_category_counts_top": _top_counter_json(viz_alert_category_counts, top_n=30),
        "label_source_counts": _counter_json(viz_label_source_counts),
        "dest_port_counts_top": _top_counter_json(viz_dest_port_counts, top_n=30),
        "src_port_class_counts": _counter_json(viz_src_port_class_counts),
        "dest_port_class_counts": _counter_json(viz_dest_port_class_counts),
        "event_type_counts_by_target_top": {str(k): _top_counter_json(v, top_n=30) for k, v in viz_event_type_by_target.items()},
        "proto_counts_by_target": _nested_counter_json(viz_proto_by_target),
        "alert_severity_counts_by_target": _nested_counter_json(viz_alert_severity_by_target),
        "label_source_counts_by_target": _nested_counter_json(viz_label_source_by_target),
        "numeric_summary": visualization_numeric_summary,
        "numeric_summary_by_target": visualization_numeric_summary_by_target,
        "numeric_histograms": visualization_histograms,
        "numeric_histograms_by_target": visualization_histograms_by_target,
        "note": (
            "Phase 9 should prefer this aggregate file over visualization_sample.csv when generating charts. "
            "The sample file remains available only for backward compatibility or scatter/preview plots."
        ),
    }
    write_json(visualization_aggregates, visualization_aggregates_path)

    aggregate_count_rows: list[dict[str, Any]] = []
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="split_counts", counter=viz_split_counts))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="target_counts", counter=viz_target_counts))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="event_type_counts_top", counter=viz_event_type_counts, top_n=30))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="proto_counts", counter=viz_proto_counts))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="app_proto_counts_top", counter=viz_app_proto_counts, top_n=30))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="alert_severity_counts", counter=viz_alert_severity_counts))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="alert_category_counts_top", counter=viz_alert_category_counts, top_n=30))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="label_source_counts", counter=viz_label_source_counts))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="dest_port_counts_top", counter=viz_dest_port_counts, top_n=30))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="src_port_class_counts", counter=viz_src_port_class_counts))
    aggregate_count_rows.extend(_flatten_counts_rows(app=app, group_name="dest_port_class_counts", counter=viz_dest_port_class_counts))
    _csv_write_dicts(
        visualization_aggregate_counts_path,
        aggregate_count_rows,
        ["app", "group", "key", "count"],
    )

    histogram_rows: list[dict[str, Any]] = []
    for feature, counter in viz_histograms.items():
        for bucket, count in sorted(counter.items(), key=lambda kv: str(kv[0])):
            histogram_rows.append({
                "app": app,
                "feature": feature,
                "target": "all",
                "bucket": str(bucket),
                "count": int(count),
            })
        for cls, cls_counter in viz_histograms_by_target.get(feature, {}).items():
            for bucket, count in sorted(cls_counter.items(), key=lambda kv: str(kv[0])):
                histogram_rows.append({
                    "app": app,
                    "feature": feature,
                    "target": str(cls),
                    "bucket": str(bucket),
                    "count": int(count),
                })
    _csv_write_dicts(
        visualization_numeric_histograms_path,
        histogram_rows,
        ["app", "feature", "target", "bucket", "count"],
    )

    split_warnings = []
    if int(split_counts.get("train", 0)) <= 0:
        split_warnings.append("train split is empty")
    if int(split_counts.get("test", 0)) <= 0:
        split_warnings.append("test split is empty")
    if not target_counts_by_split_json.get("train", {}).get("0") and not target_counts_by_split_json.get("train", {}).get("1"):
        split_warnings.append("train target distribution unavailable or empty")
    if not target_counts_by_split_json.get("test", {}).get("0") and not target_counts_by_split_json.get("test", {}).get("1"):
        split_warnings.append("test target distribution unavailable or empty")
    if len(target_counts) < 2:
        split_warnings.append(f"target column {target_column} has one class globally: {dict(target_counts)}")
    if len(target_counts_by_split.get("train", Counter())) < 2:
        split_warnings.append(f"train target has one class: {target_counts_by_split_json.get('train', {})}")
    if len(target_counts_by_split.get("test", Counter())) < 2:
        split_warnings.append(f"test target has one class: {target_counts_by_split_json.get('test', {})}")

    required_classes = {0, 1} if len(target_counts) >= 2 else set(target_counts.keys())
    train_classes = set(int(k) for k in target_counts_by_split.get("train", Counter()).keys())
    test_classes = set(int(k) for k in target_counts_by_split.get("test", Counter()).keys())
    split_class_coverage = {
        "required_classes": sorted(int(x) for x in required_classes),
        "train_classes": sorted(int(x) for x in train_classes),
        "test_classes": sorted(int(x) for x in test_classes),
        "train_has_all_required_classes": bool(required_classes.issubset(train_classes)) if required_classes else False,
        "test_has_all_required_classes": bool(required_classes.issubset(test_classes)) if required_classes else False,
        "coverage_ok": bool(required_classes.issubset(train_classes) and required_classes.issubset(test_classes)) if required_classes else False,
        "note": (
            "Phase 8 writes train/test in a single streaming pass. If coverage_ok is false, "
            "use a split strategy/config that preserves minority class coverage before Phase 12/13."
        ),
    }

    train_physical_lines = _tabular_physical_lines(data_rows=int(split_counts.get("train", 0)), export_format=export_format)
    test_physical_lines = _tabular_physical_lines(data_rows=int(split_counts.get("test", 0)), export_format=export_format)

    generated_file_line_counts = {
        "train": _generated_line_entry(
            train_path,
            physical_lines=train_physical_lines,
            data_rows=int(split_counts.get("train", 0)),
            method="tracked_rows_plus_csv_header" if export_format != "jsonl" else "tracked_jsonl_rows",
        ),
        "test": _generated_line_entry(
            test_path,
            physical_lines=test_physical_lines,
            data_rows=int(split_counts.get("test", 0)),
            method="tracked_rows_plus_csv_header" if export_format != "jsonl" else "tracked_jsonl_rows",
        ),
        "visualization_sample": _generated_line_entry(
            visualization_sample_path,
            physical_lines=len(viz_sampler.rows) + 1,
            data_rows=len(viz_sampler.rows),
            method="tracked_rows_plus_csv_header",
        ),
        "corr_leak_sample": _generated_line_entry(
            corr_leak_sample_path,
            physical_lines=len(corr_sampler.rows) + 1,
            data_rows=len(corr_sampler.rows),
            method="tracked_rows_plus_csv_header",
        ),
        "label_distribution": _generated_line_entry(
            label_dist_path,
            physical_lines=_count_text_lines(label_dist_path),
            data_rows=len(label_rows),
            method="small_file_line_count",
        ),
        "feature_availability": _generated_line_entry(
            availability_path,
            physical_lines=_count_text_lines(availability_path),
            data_rows=len(availability_rows),
            method="small_file_line_count",
        ),
        "missing_value_summary": _generated_line_entry(
            missing_path,
            physical_lines=_count_text_lines(missing_path),
            data_rows=len(availability_rows),
            method="small_file_line_count",
        ),
        "feature_group_summary": _generated_line_entry(
            feature_group_path,
            physical_lines=_count_text_lines(feature_group_path),
            data_rows=len(group_rows),
            method="small_file_line_count",
        ),
        "file_class_summary": _generated_line_entry(
            file_class_summary_path,
            physical_lines=_count_text_lines(file_class_summary_path),
            data_rows=len(file_class_rows),
            method="small_file_line_count",
        ),
        "visualization_aggregates": _generated_line_entry(
            visualization_aggregates_path,
            physical_lines=_count_text_lines(visualization_aggregates_path),
            data_rows=1,
            method="small_file_line_count",
        ),
        "visualization_aggregate_counts": _generated_line_entry(
            visualization_aggregate_counts_path,
            physical_lines=_count_text_lines(visualization_aggregate_counts_path),
            data_rows=len(aggregate_count_rows),
            method="small_file_line_count",
        ),
        "visualization_numeric_histograms": _generated_line_entry(
            visualization_numeric_histograms_path,
            physical_lines=_count_text_lines(visualization_numeric_histograms_path),
            data_rows=len(histogram_rows),
            method="small_file_line_count",
        ),
        "schema": _generated_line_entry(
            schema_path,
            physical_lines=_count_text_lines(schema_path),
            data_rows=len(fieldnames),
            method="small_file_line_count",
        ),
        "feature_roles": _generated_line_entry(
            feature_roles_path,
            physical_lines=_count_text_lines(feature_roles_path),
            data_rows=len(feature_roles),
            method="small_file_line_count",
        ),
    }

    split_summary = {
        "phase": 8,
        "app": app,
        "split_strategy": split_strategy,
        "train_ratio": train_ratio,
        "test_ratio": test_ratio,
        "target_column": target_column,
        "train_path": str(train_path),
        "test_path": str(test_path),
        "train_rows": int(split_counts.get("train", 0)),
        "test_rows": int(split_counts.get("test", 0)),
        "total_rows": int(rows_written),
        "seed": int(seed),
        "target_counts_by_split": target_counts_by_split_json,
        "target_alert_counts_by_split": target_alert_counts_by_split_json,
        "label_source_counts_by_split": label_source_counts_by_split_json,
        "train_target_counts": target_counts_by_split_json.get("train", {}),
        "test_target_counts": target_counts_by_split_json.get("test", {}),
        "file_class_summary": file_class_summary,
        "dataset_total_class_summary": file_class_summary.get("dataset_total", {}),
        "train_file_class_summary": file_class_summary.get("train", {}),
        "test_file_class_summary": file_class_summary.get("test", {}),
        "alert_policy_counts": {str(k): int(v) for k, v in alert_policy_counts.items()},
        "visualization_aggregates_path": str(visualization_aggregates_path),
        "visualization_source": "phase8_full_scan_exact_aggregates",
        "generated_file_line_counts": generated_file_line_counts,
        "split_class_coverage": split_class_coverage,
        "split_warnings": split_warnings,
    }
    write_json(split_summary, split_summary_path)

    export_summary = {
        "phase": 8,
        "title": "Export Feature-Ready Dataset and Split",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),

        "input": {
            "app_input_path": str(app_input_path),
            "app_input_size_bytes": int(file_size_bytes(app_input_path)),
            "app_input_size_gib": float(file_size_gib(app_input_path)),
            "phase3_probe_features": str(phase3_probe_path) if phase3_probe_path else None,
            "phase4_suspicious_keys": str(phase4_keys_path) if phase4_keys_path else None,
            "phase5_manifest": str(phase5_manifest_path),
            "phase6_rules": str(phase6_rules_path),
            "phase7_cleaning_policy": str(phase7_policy_path),
            "phase7_leakage_drop_list": str(phase7_drop_path),
            "phase7_training_feature_list": str(phase7_training_path),
        },

        "rows_seen": int(rows_seen),
        "rows_written": int(rows_written),
        "malformed": int(malformed),
        "no_timestamp": int(no_timestamp),
        "no_src_ip": int(no_src_ip),

        "output_format": export_format,
        "compression": compression,
        "train_path": str(train_path),
        "test_path": str(test_path),
        "train_rows": int(split_counts.get("train", 0)),
        "test_rows": int(split_counts.get("test", 0)),
        "train_size_bytes": int(file_size_bytes(train_path)),
        "test_size_bytes": int(file_size_bytes(test_path)),

        "target_counts": {str(k): int(v) for k, v in target_counts.items()},
        "target_alert_counts": {str(k): int(v) for k, v in target_alert_counts.items()},
        "label_source_counts": {str(k): int(v) for k, v in label_source_counts.items()},
        "alert_policy_counts": {str(k): int(v) for k, v in alert_policy_counts.items()},
        "label_policy": "event_type_or_valid_alert",

        "target_counts_by_split": target_counts_by_split_json,
        "target_alert_counts_by_split": target_alert_counts_by_split_json,
        "label_source_counts_by_split": label_source_counts_by_split_json,
        "train_target_counts": target_counts_by_split_json.get("train", {}),
        "test_target_counts": target_counts_by_split_json.get("test", {}),
        "file_class_summary": file_class_summary,
        "dataset_total_class_summary": file_class_summary.get("dataset_total", {}),
        "train_file_class_summary": file_class_summary.get("train", {}),
        "test_file_class_summary": file_class_summary.get("test", {}),
        "split_class_coverage": split_class_coverage,
        "split_warnings": split_warnings,

        "feature_count": int(len(fieldnames)),
        "probe_lookup_windows_loaded": int(len(probe_lookup)),
        "phase4_keys_loaded": int(len(suspicious_keys)),

        # Fix 1 audit: row-level refinement conversion cap.
        "refinement_row_cap": {
            "enforced": bool(refinement_enforced),
            "max_benign_conversion_pct": float(refinement_budget.get("max_benign_conversion_pct", 0.0)),
            "total_no_alert_rows": int(refinement_budget.get("total_no_alert_rows", 0) or 0),
            "conversion_budget_rows": refinement_budget.get("conversion_budget_rows"),
            "conversion_keys_total": int(refinement_budget.get("conversion_keys_total", 0) or 0),
            "keys_admitted": int(refinement_budget.get("keys_admitted", 0) or 0),
            "keys_capped": int(refinement_budget.get("keys_capped", 0) or 0),
            "rows_converted": int(rows_converted_total),
            "rows_conversion_capped": int(rows_conversion_capped_total),
            "note": str(refinement_budget.get("note", "")),
        },

        "summary_files": {
            "export_summary": str(export_summary_path),
            "split_summary": str(split_summary_path),
            "schema": str(schema_path),
            "feature_roles": str(feature_roles_path),
            "label_distribution": str(label_dist_path),
            "feature_availability": str(availability_path),
            "missing_value_summary": str(missing_path),
            "feature_group_summary": str(feature_group_path),
            "file_class_summary": str(file_class_summary_path),
            "visualization_aggregates": str(visualization_aggregates_path),
            "visualization_aggregate_counts": str(visualization_aggregate_counts_path),
            "visualization_numeric_histograms": str(visualization_numeric_histograms_path),
            "visualization_sample": str(visualization_sample_path),
            "corr_leak_sample": str(corr_leak_sample_path),
        },
        "generated_file_line_counts": generated_file_line_counts,
        "visualization_source": "phase8_full_scan_exact_aggregates",
        "visualization_aggregates_path": str(visualization_aggregates_path),
        "visualization_aggregate_count_rows": int(len(aggregate_count_rows)),
        "visualization_numeric_histogram_rows": int(len(histogram_rows)),

        "visualization_sample_rows": int(len(viz_sampler.rows)),
        "corr_leak_sample_rows": int(len(corr_sampler.rows)),
        "availability_sample_rows": int(availability_seen),

        "dataset_generation_note": (
            "Phase 8 is the first full dataset materialization step. Earlier phases produce "
            "summary, policy, schema, rules, and aggregate evidence only."
        ),
    }

    write_json(export_summary, export_summary_path)
    write_json(export_summary, summary_alias)

    manifest = {
        "phase": 8,
        "app": app,
        "created_at": now_iso(),
        "files": {
            "train": str(train_path),
            "test": str(test_path),
            "export_summary": str(export_summary_path),
            "split_summary": str(split_summary_path),
            "schema": str(schema_path),
            "feature_roles": str(feature_roles_path),
            "file_class_summary": str(file_class_summary_path),
            "visualization_aggregates": str(visualization_aggregates_path),
        },
        "file_class_summary": file_class_summary,
        "visualization_source": "phase8_full_scan_exact_aggregates",
        "generated_file_line_counts": generated_file_line_counts,
    }
    write_json(manifest, manifest_path)

    # Finalize self-referential small artifact line counts. Do a few passes so
    # export_summary/summary_alias/manifest counts stabilize after being updated.
    for _ in range(3):
        generated_file_line_counts["split_summary"] = _generated_line_entry(
            split_summary_path,
            physical_lines=_count_text_lines(split_summary_path),
            method="small_file_line_count",
        )
        generated_file_line_counts["export_summary"] = _generated_line_entry(
            export_summary_path,
            physical_lines=_count_text_lines(export_summary_path),
            method="small_file_line_count_self_referential",
        )
        generated_file_line_counts["summary_alias"] = _generated_line_entry(
            summary_alias,
            physical_lines=_count_text_lines(summary_alias),
            method="small_file_line_count_self_referential",
        )
        generated_file_line_counts["manifest"] = _generated_line_entry(
            manifest_path,
            physical_lines=_count_text_lines(manifest_path),
            method="small_file_line_count_self_referential",
        )
        export_summary["generated_file_line_counts"] = generated_file_line_counts
        manifest["generated_file_line_counts"] = generated_file_line_counts
        write_json(split_summary, split_summary_path)
        write_json(export_summary, export_summary_path)
        write_json(export_summary, summary_alias)
        write_json(manifest, manifest_path)

    print("\n" + "=" * 72)
    print("Phase 8 - Export Feature-Ready Dataset and Split")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Rows Seen   : {rows_seen:,}")
    print(f"Rows Written: {rows_written:,}")
    print(f"Train Rows  : {split_counts.get('train', 0):,}")
    print(f"Test Rows   : {split_counts.get('test', 0):,}")
    print(f"Target      : {dict(target_counts)}")
    print(f"Train Target: {target_counts_by_split_json.get('train', {})}")
    print(f"Test Target : {target_counts_by_split_json.get('test', {})}")
    print(
        "Class Files : "
        f"total benign={file_class_summary['dataset_total']['benign']:,} attack={file_class_summary['dataset_total']['attack']:,} | "
        f"train benign={file_class_summary['train']['benign']:,} attack={file_class_summary['train']['attack']:,} | "
        f"test benign={file_class_summary['test']['benign']:,} attack={file_class_summary['test']['attack']:,}"
    )
    print(f"File Lines  : train={train_physical_lines:,} | test={test_physical_lines:,} | "
          f"viz={len(viz_sampler.rows) + 1:,} | corr={len(corr_sampler.rows) + 1:,}")
    print(f"Viz Summary : {visualization_aggregates_path}")
    if split_warnings:
        print(f"Warnings    : {split_warnings}")
    print(f"Output      : {export_summary_path}")
    print("=" * 72 + "\n")

    return export_summary


# Backward-compatible aliases for pipeline fallback registry.
phase8_run = run_phase8
phase8_export_dataset = run_phase8
