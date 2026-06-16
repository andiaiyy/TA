from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from heapq import heappop, heappush
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from ..io_utils import (
    dumps_json,
    file_size_bytes,
    file_size_gib,
    loads_json_line,
    now_iso,
    open_maybe_gzip,
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
        return float(value)
    except Exception:
        return default


def _norm_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _norm_category(value: Any) -> str:
    return _norm_text(value).strip().lower()


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # Suricata usually emits ISO timestamps with timezone.
    try:
        text2 = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _floor_window(dt: datetime, window_minutes: int) -> datetime:
    seconds = int(window_minutes) * 60
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_flow_numbers(event: dict[str, Any]) -> tuple[int, int]:
    flow = event.get("flow")
    if not isinstance(flow, dict):
        return 0, 0

    bytes_toserver = _safe_int(flow.get("bytes_toserver"), 0)
    bytes_toclient = _safe_int(flow.get("bytes_toclient"), 0)
    pkts_toserver = _safe_int(flow.get("pkts_toserver"), 0)
    pkts_toclient = _safe_int(flow.get("pkts_toclient"), 0)

    return bytes_toserver + bytes_toclient, pkts_toserver + pkts_toclient


def _is_valid_alert(event: dict[str, Any]) -> bool:
    alert = event.get("alert")
    if not isinstance(alert, dict):
        return False

    severity = alert.get("severity")
    if severity is None:
        return False

    severity_int = _safe_int(severity, 0)
    if severity_int <= 0:
        return False

    category = _norm_category(alert.get("category"))
    if category in IGNORED_ALERT_CATEGORIES:
        return False

    return True


def _is_event_type_alert(event: dict[str, Any]) -> bool:
    return _norm_text(event.get("event_type"), "").lower() == "alert"


def _is_base_alert_positive(event: dict[str, Any]) -> bool:
    """
    Initial alert evidence used consistently with the pre-split and Phase 8.

    A row is treated as alert-positive when Suricata emits event_type=alert
    OR when the stricter valid-alert evidence is present. This prevents alert
    rows from disappearing simply because alert.severity/category is incomplete.
    """
    return _is_event_type_alert(event) or _is_valid_alert(event)


def _has_any_alert(event: dict[str, Any]) -> bool:
    return isinstance(event.get("alert"), dict)


def _counter_top(counter: Counter, n: int = 10) -> dict[str, int]:
    return {str(k): int(v) for k, v in counter.most_common(int(n))}


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0

    if q <= 0:
        return float(sorted_values[0])
    if q >= 100:
        return float(sorted_values[-1])

    pos = (len(sorted_values) - 1) * (float(q) / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def _score_components(
    *,
    event_count: int,
    unique_dest_ip: int,
    unique_dest_port: int,
    valid_alert_count: int,
    min_event_count: int,
    min_unique_dest_ip: int,
    min_unique_dest_port: int,
) -> tuple[float, float]:
    """
    Two scores are intentionally separated:

    probe_score_no_alert:
        behavioral probing score only.

    probe_score_with_alert:
        behavioral score plus alert association.
        Used for audit/refinement evidence, not directly as a training feature.
    """
    event_component = min(float(event_count) / max(1.0, float(min_event_count)), 5.0)
    dest_ip_component = min(float(unique_dest_ip) / max(1.0, float(min_unique_dest_ip)), 5.0)
    dest_port_component = min(float(unique_dest_port) / max(1.0, float(min_unique_dest_port)), 5.0)

    score_no_alert = (
        event_component * 1.00
        + dest_ip_component * 1.25
        + dest_port_component * 1.25
    )

    alert_component = min(float(valid_alert_count), 5.0)
    score_with_alert = score_no_alert + alert_component

    return float(score_no_alert), float(score_with_alert)


def _probe_level(score_no_alert: float, p90: float, p95: float, p99: float) -> str:
    if score_no_alert >= p99:
        return "extreme"
    if score_no_alert >= p95:
        return "high"
    if score_no_alert >= p90:
        return "medium"
    return "low"


def _probe_reason(
    *,
    event_count: int,
    unique_dest_ip: int,
    unique_dest_port: int,
    valid_alert_count: int,
    score_no_alert: float,
    min_event_count: int,
    min_unique_dest_ip: int,
    min_unique_dest_port: int,
    p90: float,
) -> str:
    reasons: list[str] = []
    if event_count >= min_event_count:
        reasons.append("high_event_count")
    if unique_dest_ip >= min_unique_dest_ip:
        reasons.append("many_dest_ip")
    if unique_dest_port >= min_unique_dest_port:
        reasons.append("many_dest_port")
    if valid_alert_count > 0:
        reasons.append("base_alert_window")
    if score_no_alert >= p90:
        reasons.append("score_ge_p90")
    return ";".join(reasons) if reasons else "below_threshold"


# ============================================================
# Aggregate bucket
# ============================================================

def _new_bucket(app: str, window_start: datetime, src_ip: str) -> dict[str, Any]:
    return {
        "app": app,
        "window_start_dt": window_start,
        "src_ip": src_ip,
        "event_count": 0,
        "dest_ips": set(),
        "dest_ports": set(),
        "dest_port_counter": Counter(),
        "event_type_counter": Counter(),
        "total_bytes": 0,
        "total_pkts": 0,
        "alert_count": 0,
        "event_type_alert_count": 0,
        "valid_alert_count": 0,
        "base_alert_positive_count": 0,
        "no_alert_count": 0,
        "first_seen": None,
        "last_seen": None,
    }


def _update_bucket(bucket: dict[str, Any], event: dict[str, Any], ts: datetime) -> None:
    dest_ip = _norm_text(event.get("dest_ip"))
    dest_port = _safe_int(event.get("dest_port"), 0)
    event_type = _norm_text(event.get("event_type"), "unknown") or "unknown"

    total_bytes, total_pkts = _get_flow_numbers(event)
    any_alert = _has_any_alert(event)
    event_type_alert = _is_event_type_alert(event)
    valid_alert = _is_valid_alert(event)
    base_alert_positive = bool(event_type_alert or valid_alert)

    bucket["event_count"] += 1

    if dest_ip:
        bucket["dest_ips"].add(dest_ip)

    if dest_port > 0:
        bucket["dest_ports"].add(dest_port)
        bucket["dest_port_counter"][dest_port] += 1

    bucket["event_type_counter"][event_type] += 1
    bucket["total_bytes"] += int(total_bytes)
    bucket["total_pkts"] += int(total_pkts)

    if any_alert:
        bucket["alert_count"] += 1

    if event_type_alert:
        bucket["event_type_alert_count"] += 1

    if valid_alert:
        bucket["valid_alert_count"] += 1

    if base_alert_positive:
        bucket["base_alert_positive_count"] += 1
    else:
        bucket["no_alert_count"] += 1

    first_seen = bucket.get("first_seen")
    last_seen = bucket.get("last_seen")

    if first_seen is None or ts < first_seen:
        bucket["first_seen"] = ts
    if last_seen is None or ts > last_seen:
        bucket["last_seen"] = ts


def _bucket_record(
    bucket: dict[str, Any],
    *,
    min_event_count: int,
    min_unique_dest_ip: int,
    min_unique_dest_port: int,
    p90: float,
    p95: float,
    p99: float,
) -> dict[str, Any]:
    event_count = int(bucket["event_count"])
    unique_dest_ip = int(len(bucket["dest_ips"]))
    unique_dest_port = int(len(bucket["dest_ports"]))
    alert_count = int(bucket["alert_count"])
    event_type_alert_count = int(bucket.get("event_type_alert_count", 0))
    valid_alert_count = int(bucket["valid_alert_count"])
    base_alert_positive_count = int(bucket.get("base_alert_positive_count", event_type_alert_count + valid_alert_count))
    no_alert_count = int(bucket["no_alert_count"])

    score_no_alert, score_with_alert = _score_components(
        event_count=event_count,
        unique_dest_ip=unique_dest_ip,
        unique_dest_port=unique_dest_port,
        valid_alert_count=base_alert_positive_count,
        min_event_count=min_event_count,
        min_unique_dest_ip=min_unique_dest_ip,
        min_unique_dest_port=min_unique_dest_port,
    )

    fanout_high = (
        unique_dest_ip >= min_unique_dest_ip
        or unique_dest_port >= min_unique_dest_port
    )

    suspicious = bool(
        score_no_alert >= p90
        and event_count >= min_event_count
        and fanout_high
    )

    return {
        "app": bucket["app"],
        "window_start": _iso(bucket["window_start_dt"]),
        "src_ip": bucket["src_ip"],

        "event_count_window": event_count,
        "unique_dest_ip_window": unique_dest_ip,
        "unique_dest_port_window": unique_dest_port,
        "total_bytes_window": int(bucket["total_bytes"]),
        "total_pkts_window": int(bucket["total_pkts"]),
        "bytes_per_event_window": float(bucket["total_bytes"] / event_count) if event_count else 0.0,
        "pkts_per_event_window": float(bucket["total_pkts"] / event_count) if event_count else 0.0,

        "alert_count_window": alert_count,
        "event_type_alert_count_window": event_type_alert_count,
        "valid_alert_count_window": valid_alert_count,
        "base_alert_positive_count_window": base_alert_positive_count,
        "no_alert_count_window": no_alert_count,

        "probe_score_no_alert": float(score_no_alert),
        "probe_score_with_alert": float(score_with_alert),
        "probe_level": _probe_level(score_no_alert, p90, p95, p99),
        "fanout_high": int(fanout_high),
        "is_suspicious_window": int(suspicious),
        "probe_reason": _probe_reason(
            event_count=event_count,
            unique_dest_ip=unique_dest_ip,
            unique_dest_port=unique_dest_port,
            valid_alert_count=base_alert_positive_count,
            score_no_alert=score_no_alert,
            min_event_count=min_event_count,
            min_unique_dest_ip=min_unique_dest_ip,
            min_unique_dest_port=min_unique_dest_port,
            p90=p90,
        ),

        "top_dest_ports": _counter_top(bucket["dest_port_counter"], 10),
        "top_event_types": _counter_top(bucket["event_type_counter"], 10),

        "first_seen": _iso(bucket["first_seen"]),
        "last_seen": _iso(bucket["last_seen"]),
    }


def _write_jsonl_record(handle, record: dict[str, Any]) -> None:
    handle.write(dumps_json(record, indent=False))
    handle.write(b"\n")


# ============================================================
# Runner
# ============================================================

def run_phase3(
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

    probing_cfg = getattr(cfg, "probing", None)
    window_minutes = int(getattr(probing_cfg, "window_minutes", 5) or 5)

    # Conservative default thresholds. These define behavior/fanout evidence.
    min_event_count = int(getattr(probing_cfg, "min_event_count", 50) or 50)
    min_unique_dest_ip = int(getattr(probing_cfg, "min_unique_dest_ip", 10) or 10)
    min_unique_dest_port = int(getattr(probing_cfg, "min_unique_dest_port", 5) or 5)

    # Percentile thresholds for Phase 4. Config owns the policy values.
    same_window_percentile = float(getattr(probing_cfg, "same_window_probe_percentile", 90.0) or 90.0)
    near_window_percentile = float(getattr(probing_cfg, "near_window_probe_percentile", 95.0) or 95.0)
    extreme_percentile = float(getattr(probing_cfg, "extreme_probe_percentile", 99.0) or 99.0)

    top_k = int(getattr(probing_cfg, "top_candidates", 1000) or 1000)

    prefix = f"phase3_{app}"
    probe_features_path = phase_dir / f"{prefix}_probe_features.jsonl"
    alert_ip_index_path = phase_dir / f"{prefix}_alert_ip_index.jsonl"
    suspicious_windows_path = phase_dir / f"{prefix}_suspicious_windows.jsonl"
    top_candidates_path = phase_dir / f"{prefix}_top_candidates.jsonl"
    summary_path = phase_dir / f"{prefix}_summary.json"
    generic_summary_path = phase_dir / "summary.json"
    manifest_path = phase_dir / "manifest.json"

    print("\n" + "=" * 72)
    print("Phase 3 - Probing Analysis")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {app_input_path}")
    print(f"Window Size : {window_minutes} minutes")
    print("Output Mode : aggregate probing evidence only")
    print("=" * 72)

    t0 = datetime.now()

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}

    rows_scanned = 0
    decoded_events = 0
    malformed = 0
    dropped_no_timestamp = 0
    dropped_no_src_ip = 0

    event_type_counter: Counter = Counter()
    app_proto_counter: Counter = Counter()
    dest_port_counter: Counter = Counter()
    valid_alert_rows = 0
    event_type_alert_rows = 0
    any_alert_rows = 0
    base_alert_positive_rows = 0

    progress_every = int(getattr(cfg, "phase_progress_every", 1_000_000) or 1_000_000)

    with open_maybe_gzip(app_input_path, "rb") as f:
        for line in f:
            rows_scanned += 1
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

            decoded_events += 1

            ts = _parse_timestamp(event.get("timestamp"))
            if ts is None:
                dropped_no_timestamp += 1
                continue

            src_ip = _norm_text(event.get("src_ip"))
            if not src_ip:
                dropped_no_src_ip += 1
                continue

            window_start = _floor_window(ts, window_minutes)
            window_key = _iso(window_start)
            key = (app, window_key or "", src_ip)

            bucket = buckets.get(key)
            if bucket is None:
                bucket = _new_bucket(app, window_start, src_ip)
                buckets[key] = bucket

            _update_bucket(bucket, event, ts)

            event_type_counter[_norm_text(event.get("event_type"), "unknown") or "unknown"] += 1
            app_proto_counter[_norm_text(event.get("app_proto"), "unknown") or "unknown"] += 1

            dest_port = _safe_int(event.get("dest_port"), 0)
            if dest_port > 0:
                dest_port_counter[dest_port] += 1

            if _has_any_alert(event):
                any_alert_rows += 1
            if _is_event_type_alert(event):
                event_type_alert_rows += 1
            if _is_valid_alert(event):
                valid_alert_rows += 1
            if _is_base_alert_positive(event):
                base_alert_positive_rows += 1

            if progress_every > 0 and rows_scanned % progress_every == 0:
                print(
                    f"[Phase 3 {app.upper()}] scanned={rows_scanned:,} | "
                    f"windows={len(buckets):,} | malformed={malformed:,}",
                    flush=True,
                )

    # First score pass for percentiles.
    no_alert_scores: list[float] = []
    with_alert_scores: list[float] = []

    for bucket in buckets.values():
        event_count = int(bucket["event_count"])
        unique_dest_ip = int(len(bucket["dest_ips"]))
        unique_dest_port = int(len(bucket["dest_ports"]))
        base_alert_positive_count = int(bucket.get("base_alert_positive_count", bucket.get("valid_alert_count", 0)))

        score_no_alert, score_with_alert = _score_components(
            event_count=event_count,
            unique_dest_ip=unique_dest_ip,
            unique_dest_port=unique_dest_port,
            valid_alert_count=base_alert_positive_count,
            min_event_count=min_event_count,
            min_unique_dest_ip=min_unique_dest_ip,
            min_unique_dest_port=min_unique_dest_port,
        )
        no_alert_scores.append(score_no_alert)
        with_alert_scores.append(score_with_alert)

    no_alert_sorted = sorted(no_alert_scores)
    with_alert_sorted = sorted(with_alert_scores)

    p50 = _percentile(no_alert_sorted, 50)
    p75 = _percentile(no_alert_sorted, 75)
    p90 = _percentile(no_alert_sorted, same_window_percentile)
    p95 = _percentile(no_alert_sorted, near_window_percentile)
    p99 = _percentile(no_alert_sorted, extreme_percentile)

    score_stats = {
        "probe_score_no_alert": {
            "p50": p50,
            "p75": p75,
            "p90": p90,
            "p95": p95,
            "p99": p99,
            "max": float(no_alert_sorted[-1]) if no_alert_sorted else 0.0,
        },
        "probe_score_with_alert": {
            "p50": _percentile(with_alert_sorted, 50),
            "p75": _percentile(with_alert_sorted, 75),
            "p90": _percentile(with_alert_sorted, 90),
            "p95": _percentile(with_alert_sorted, 95),
            "p99": _percentile(with_alert_sorted, 99),
            "max": float(with_alert_sorted[-1]) if with_alert_sorted else 0.0,
        },
    }

    probe_windows = 0
    suspicious_windows = 0
    alert_ip_windows = 0

    top_heap: list[tuple[float, int, dict[str, Any]]] = []
    sequence = 0

    with (
        probe_features_path.open("wb") as f_probe,
        alert_ip_index_path.open("wb") as f_alert,
        suspicious_windows_path.open("wb") as f_suspicious,
    ):
        for bucket in buckets.values():
            record = _bucket_record(
                bucket,
                min_event_count=min_event_count,
                min_unique_dest_ip=min_unique_dest_ip,
                min_unique_dest_port=min_unique_dest_port,
                p90=p90,
                p95=p95,
                p99=p99,
            )

            _write_jsonl_record(f_probe, record)
            probe_windows += 1

            if int(record.get("base_alert_positive_count_window", record.get("valid_alert_count_window", 0))) > 0:
                alert_record = {
                    "app": record["app"],
                    "window_start": record["window_start"],
                    "src_ip": record["src_ip"],
                    "event_type_alert_count_window": record.get("event_type_alert_count_window", 0),
                    "valid_alert_count_window": record["valid_alert_count_window"],
                    "base_alert_positive_count_window": record.get("base_alert_positive_count_window", record["valid_alert_count_window"]),
                    "alert_count_window": record["alert_count_window"],
                    "probe_score_no_alert": record["probe_score_no_alert"],
                    "probe_score_with_alert": record["probe_score_with_alert"],
                    "fanout_high": record["fanout_high"],
                    "event_count_window": record["event_count_window"],
                    "unique_dest_ip_window": record["unique_dest_ip_window"],
                    "unique_dest_port_window": record["unique_dest_port_window"],
                }
                _write_jsonl_record(f_alert, alert_record)
                alert_ip_windows += 1

            if int(record["is_suspicious_window"]) == 1:
                _write_jsonl_record(f_suspicious, record)
                suspicious_windows += 1

            # Keep top candidates by probe_score_with_alert.
            score_key = float(record["probe_score_with_alert"])
            sequence += 1
            item = (score_key, sequence, record)
            if len(top_heap) < top_k:
                heappush(top_heap, item)
            else:
                if score_key > top_heap[0][0]:
                    heappop(top_heap)
                    heappush(top_heap, item)

    top_candidates = [item[2] for item in sorted(top_heap, key=lambda x: (x[0], x[1]), reverse=True)]
    with top_candidates_path.open("wb") as f_top:
        for record in top_candidates:
            _write_jsonl_record(f_top, record)

    elapsed = (datetime.now() - t0).total_seconds()

    output_files = {
        "probe_features": str(probe_features_path),
        "alert_ip_index": str(alert_ip_index_path),
        "suspicious_windows": str(suspicious_windows_path),
        "top_candidates": str(top_candidates_path),
        "summary": str(summary_path),
        "summary_alias": str(generic_summary_path),
        "manifest": str(manifest_path),
    }

    summary = {
        "phase": 3,
        "title": "Probing Analysis",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "reading": str(app_input_path),
        "window_minutes": int(window_minutes),
        "generated_at": now_iso(),

        "rows_scanned": int(rows_scanned),
        "decoded_events": int(decoded_events),
        "malformed": int(malformed),
        "dropped_no_timestamp": int(dropped_no_timestamp),
        "dropped_no_src_ip": int(dropped_no_src_ip),

        "probe_windows": int(probe_windows),
        "suspicious_windows": int(suspicious_windows),
        "alert_ip_windows": int(alert_ip_windows),

        "alert_policy": {
            "label_mode": "event_type_or_valid_alert",
            "base_alert_positive": "event_type == alert OR valid Suricata alert evidence",
            "note": "Aligned with pre-split and Phase 8 so event_type=alert rows are not lost."
        },
        "any_alert_rows": int(any_alert_rows),
        "event_type_alert_rows": int(event_type_alert_rows),
        "valid_alert_rows": int(valid_alert_rows),
        "base_alert_positive_rows": int(base_alert_positive_rows),

        "aggregate_key": ["app", "window_start", "src_ip"],
        "threshold_policy": {
            "min_event_count": int(min_event_count),
            "min_unique_dest_ip": int(min_unique_dest_ip),
            "min_unique_dest_port": int(min_unique_dest_port),
            "same_window_percentile": float(same_window_percentile),
            "near_window_percentile": float(near_window_percentile),
            "extreme_percentile": float(extreme_percentile),
        },
        "probe_score_stats": score_stats,

        "top_event_type": _counter_top(event_type_counter, 20),
        "top_app_proto": _counter_top(app_proto_counter, 20),
        "top_dest_port": _counter_top(dest_port_counter, 20),

        "output_files": output_files,
        "output_size_bytes": {
            "probe_features": int(file_size_bytes(probe_features_path)),
            "alert_ip_index": int(file_size_bytes(alert_ip_index_path)),
            "suspicious_windows": int(file_size_bytes(suspicious_windows_path)),
            "top_candidates": int(file_size_bytes(top_candidates_path)),
        },
        "input_file_size_bytes": int(file_size_bytes(app_input_path)),
        "input_file_size_gib": float(file_size_gib(app_input_path)),

        "seconds": float(elapsed),

        "methodology_note": (
            "Phase 3 scans the full active app JSONL to compute source-IP time-window behavior. "
            "It outputs aggregate probing evidence only, not a row-level dataset copy."
        ),
        "label_note": (
            "Phase 3 does not change labels. It only records aggregate evidence. "
            "Alert evidence is tracked with the same base policy used by split/Phase 8: "
            "event_type == alert OR valid alert evidence. Phase 4 may use this evidence "
            "conservatively for label refinement. IP-only relabeling is not allowed."
        ),
    }

    write_json(summary, summary_path)
    write_json(summary, generic_summary_path)

    manifest = {
        "phase": 3,
        "app": app,
        "created_at": now_iso(),
        "files": output_files,
        "summary": {
            "probe_windows": int(probe_windows),
            "suspicious_windows": int(suspicious_windows),
            "alert_ip_windows": int(alert_ip_windows),
        },
    }
    write_json(manifest, manifest_path)

    print("\n" + "=" * 72)
    print("Phase 3 - Probing Analysis")
    print("=" * 72)
    print(f"Current Run        : {app.upper()}")
    print(f"Reading            : {app_input_path}")
    print(f"Window Size        : {window_minutes} minutes")
    print(f"Rows Scanned       : {rows_scanned:,}")
    print(f"Probe Windows      : {probe_windows:,}")
    print(f"Suspicious Windows : {suspicious_windows:,}")
    print(f"Alert IP Windows   : {alert_ip_windows:,}")
    print(f"Base Alert Rows    : {base_alert_positive_rows:,}")
    print(f"Output             : {summary_path}")
    print(f"Time               : {elapsed / 60:.2f} minutes")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase3_run = run_phase3
phase3_probing_analysis = run_phase3
