from __future__ import annotations

"""
Phase 4 - Label Refinement Policy Builder

Purpose:
- Use Phase 3 aggregate probing evidence.
- Build conservative refinement keys/policy.
- Do NOT read the full app JSONL.
- Do NOT write a row-level labeled dataset.
- Do NOT perform IP-only relabeling.

Phase 4 does not directly finalize every row. Instead, it produces a policy and
key files that Phase 8 will apply while exporting the final feature-ready
dataset.

Input:
    outputs/<app>/phase3/phase3_<app>_probe_features.jsonl
    outputs/<app>/phase3/phase3_<app>_alert_ip_index.jsonl
    outputs/<app>/phase3/phase3_<app>_summary.json
    outputs/<app>/phase1/summary.json optional

Output:
    phase4_<app>_label_policy.json
    phase4_<app>_suspicious_keys.jsonl
    phase4_<app>_refined_label_summary.json
    phase4_<app>_refinement_audit.csv

Also writes generic aliases:
    label_policy.json
    suspicious_keys.jsonl
    refined_label_summary.json
    refinement_audit.csv
    summary.json
"""

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ..io_utils import (
    dumps_json,
    file_size_bytes,
    loads_json_line,
    now_iso,
    open_maybe_gzip,
    read_json,
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


def _parse_window(value: Any) -> Optional[datetime]:
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


def _window_key(value: Any) -> str:
    dt = _parse_window(value)
    if dt is None:
        return str(value or "").strip()
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _minutes_between(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds()) / 60.0


def _jsonl_iter(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return

    with open_maybe_gzip(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = loads_json_line(line)
                if isinstance(obj, dict):
                    yield obj
            except Exception:
                continue


def _write_jsonl_record(handle, record: dict[str, Any]) -> None:
    handle.write(dumps_json(record, indent=False))
    handle.write(b"\n")


def _copy_text_file(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def _phase_dir(app_output_dir: Path, name: str) -> Path:
    return Path(app_output_dir) / name


def _sibling_phase_dir(phase_dir: Path, sibling: str) -> Path:
    return Path(phase_dir).parent / sibling


def _find_first_existing(candidates: Iterable[Path]) -> Optional[Path]:
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _phase3_paths(app: str, phase_dir: Path) -> dict[str, Optional[Path]]:
    phase3_dir = _sibling_phase_dir(phase_dir, "phase3")

    return {
        "probe_features": _find_first_existing([
            phase3_dir / f"phase3_{app}_probe_features.jsonl",
            phase3_dir / "probe_features.jsonl",
        ]),
        "alert_ip_index": _find_first_existing([
            phase3_dir / f"phase3_{app}_alert_ip_index.jsonl",
            phase3_dir / "alert_ip_index.jsonl",
        ]),
        "suspicious_windows": _find_first_existing([
            phase3_dir / f"phase3_{app}_suspicious_windows.jsonl",
            phase3_dir / "suspicious_windows.jsonl",
        ]),
        "summary": _find_first_existing([
            phase3_dir / f"phase3_{app}_summary.json",
            phase3_dir / "summary.json",
        ]),
    }


def _phase1_summary_path(phase_dir: Path) -> Optional[Path]:
    phase1 = _sibling_phase_dir(phase_dir, "phase1") / "summary.json"
    return phase1 if phase1.exists() else None


def _load_phase3_summary(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _load_phase1_summary(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}
    data = read_json(path, default={}, required=False)
    return data if isinstance(data, dict) else {}


def _get_thresholds_from_phase3(phase3_summary: dict[str, Any], cfg: Any) -> dict[str, float]:
    probing_cfg = getattr(cfg, "probing", None)

    same_percentile = float(getattr(probing_cfg, "same_window_probe_percentile", 90.0) or 90.0)
    near_percentile = float(getattr(probing_cfg, "near_window_probe_percentile", 95.0) or 95.0)
    extreme_percentile = float(getattr(probing_cfg, "extreme_probe_percentile", 99.0) or 99.0)

    stats = phase3_summary.get("probe_score_stats", {})
    no_alert = stats.get("probe_score_no_alert", {}) if isinstance(stats, dict) else {}

    # The patched Phase 3 stores p90/p95/p99 using the configured percentiles.
    same = _safe_float(no_alert.get("p90"), 0.0)
    near = _safe_float(no_alert.get("p95"), same)
    extreme = _safe_float(no_alert.get("p99"), near)

    return {
        "same_window_percentile": same_percentile,
        "near_window_percentile": near_percentile,
        "extreme_percentile": extreme_percentile,
        "same_window_score_threshold": same,
        "near_window_score_threshold": near,
        "extreme_score_threshold": extreme,
    }


def _load_alert_windows(alert_ip_index_path: Optional[Path]) -> tuple[set[tuple[str, str]], dict[str, list[datetime]], int]:
    """
    Returns:
        alert_key_set: {(src_ip, window_start)}
        alert_windows_by_src_ip: {src_ip: [datetime, ...]}
        count
    """
    alert_key_set: set[tuple[str, str]] = set()
    alert_windows_by_src_ip: dict[str, list[datetime]] = defaultdict(list)

    if alert_ip_index_path is None or not alert_ip_index_path.exists():
        return alert_key_set, alert_windows_by_src_ip, 0

    count = 0
    for rec in _jsonl_iter(alert_ip_index_path):
        src_ip = str(rec.get("src_ip", "")).strip()
        win_key = _window_key(rec.get("window_start"))
        win_dt = _parse_window(win_key)

        if not src_ip or not win_key:
            continue

        alert_key_set.add((src_ip, win_key))
        if win_dt is not None:
            alert_windows_by_src_ip[src_ip].append(win_dt)
        count += 1

    for src_ip in list(alert_windows_by_src_ip):
        alert_windows_by_src_ip[src_ip] = sorted(alert_windows_by_src_ip[src_ip])

    return alert_key_set, alert_windows_by_src_ip, count


def _nearest_alert_window(
    *,
    src_ip: str,
    window_start: str,
    alert_windows_by_src_ip: dict[str, list[datetime]],
    near_window_radius: int,
    window_minutes: int,
) -> tuple[bool, Optional[str], Optional[float]]:
    win_dt = _parse_window(window_start)
    if win_dt is None:
        return False, None, None

    max_minutes = max(0, int(near_window_radius)) * max(1, int(window_minutes))
    if max_minutes <= 0:
        return False, None, None

    best_dt: Optional[datetime] = None
    best_minutes: Optional[float] = None

    for alert_dt in alert_windows_by_src_ip.get(src_ip, []):
        diff = _minutes_between(win_dt, alert_dt)

        # near window excludes same window; same-window is handled separately.
        if diff <= 0:
            continue

        if diff <= max_minutes:
            if best_minutes is None or diff < best_minutes:
                best_minutes = diff
                best_dt = alert_dt

    if best_dt is None:
        return False, None, None

    return True, best_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), best_minutes


def _make_policy(
    *,
    app: str,
    thresholds: dict[str, float],
    window_minutes: int,
    near_window_radius: int,
    max_benign_conversion_pct: float,
) -> dict[str, Any]:
    return {
        "phase": 4,
        "title": "Label Refinement Policy",
        "app": app,
        "created_at": now_iso(),

        "prohibited_rule": (
            "Do not relabel all traffic from a source IP only because the source IP was once malicious. "
            "IP-only relabeling is disabled because it can cause label explosion."
        ),

        "label_columns": {
            "Target_alert": "Initial label based on event_type=alert OR valid Suricata alert evidence.",
            "Target_refined": "Final label after conservative probing-based refinement.",
            "suspicious_by_probe": "Suspicious probing marker; not always malicious.",
            "label_source": "Source of label decision.",
            "refinement_reason": "Technical reason used by the policy.",
        },

        "policy_order": [
            {
                "rule": "base_alert_positive",
                "condition": "row has event_type=alert OR valid Suricata alert evidence",
                "Target_refined": 1,
                "suspicious_by_probe": 0,
                "label_source": "alert_confirmed",
            },
            {
                "rule": "probe_refined_same_window",
                "condition": (
                    "no-alert row + same src_ip + same alert window + "
                    "probe_score_no_alert >= same_window_score_threshold + fanout_high"
                ),
                "Target_refined": 1,
                "suspicious_by_probe": 1,
                "label_source": "probe_refined_same_window",
            },
            {
                "rule": "probe_refined_near_alert_window",
                "condition": (
                    "no-alert row + same src_ip + near alert window + "
                    "probe_score_no_alert >= near_window_score_threshold + fanout_high"
                ),
                "Target_refined": 1,
                "suspicious_by_probe": 1,
                "label_source": "probe_refined_near_alert_window",
            },
            {
                "rule": "suspicious_probe_only",
                "condition": (
                    "no-alert row + extreme probing without strong alert association. "
                    "This remains Target_refined=0 but suspicious_by_probe=1."
                ),
                "Target_refined": 0,
                "suspicious_by_probe": 1,
                "label_source": "suspicious_probe_only",
            },
            {
                "rule": "benign_no_evidence",
                "condition": "no base alert evidence and no conservative probing association",
                "Target_refined": 0,
                "suspicious_by_probe": 0,
                "label_source": "benign_no_evidence",
            },
        ],

        "thresholds": {
            **thresholds,
            "window_minutes": int(window_minutes),
            "near_window_radius": int(near_window_radius),
            "max_benign_conversion_pct": float(max_benign_conversion_pct),
        },

        "phase8_application_note": (
            "Phase 8 applies this policy while exporting the final dataset. "
            "Rows with event_type=alert OR valid alerts become Target_refined=1 directly. "
            "Only no-base-alert rows may use keys in suspicious_keys.jsonl."
        ),
    }


def _audit_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "app": record.get("app"),
        "src_ip": record.get("src_ip"),
        "window_start": record.get("window_start"),
        "label_action": record.get("label_action"),
        "label_source": record.get("label_source"),
        "Target_refined_for_no_alert": record.get("Target_refined_for_no_alert"),
        "suspicious_by_probe": record.get("suspicious_by_probe"),
        "probe_score_no_alert": record.get("probe_score_no_alert"),
        "probe_score_with_alert": record.get("probe_score_with_alert"),
        "probe_level": record.get("probe_level"),
        "fanout_high": record.get("fanout_high"),
        "event_count_window": record.get("event_count_window"),
        "unique_dest_ip_window": record.get("unique_dest_ip_window"),
        "unique_dest_port_window": record.get("unique_dest_port_window"),
        "event_type_alert_count_window": record.get("event_type_alert_count_window"),
        "valid_alert_count_window": record.get("valid_alert_count_window"),
        "base_alert_positive_count_window": record.get("base_alert_positive_count_window"),
        "alert_count_window": record.get("alert_count_window"),
        "no_alert_count_window": record.get("no_alert_count_window"),
        "matched_alert_window": record.get("matched_alert_window"),
        "minutes_to_alert_window": record.get("minutes_to_alert_window"),
        "refinement_reason": record.get("refinement_reason"),
    }


# ============================================================
# Runner
# ============================================================

def run_phase4(
    *,
    cfg: Any,
    app: str,
    phase_dir: Path,
    app_output_dir: Optional[Path] = None,
    **_: Any,
) -> dict[str, Any]:
    app = _normalize_app(app)
    phase_dir = Path(phase_dir)
    phase_dir.mkdir(parents=True, exist_ok=True)

    probing_cfg = getattr(cfg, "probing", None)
    window_minutes = int(getattr(probing_cfg, "window_minutes", 5) or 5)
    near_window_radius = int(getattr(probing_cfg, "near_window_radius", 1) or 1)
    max_benign_conversion_pct = float(getattr(probing_cfg, "max_benign_conversion_pct", 5.0) or 5.0)

    phase3 = _phase3_paths(app, phase_dir)
    phase3_summary = _load_phase3_summary(phase3.get("summary"))
    phase1_summary = _load_phase1_summary(_phase1_summary_path(phase_dir))

    thresholds = _get_thresholds_from_phase3(phase3_summary, cfg)

    prefix = f"phase4_{app}"
    label_policy_path = phase_dir / f"{prefix}_label_policy.json"
    suspicious_keys_path = phase_dir / f"{prefix}_suspicious_keys.jsonl"
    refined_summary_path = phase_dir / f"{prefix}_refined_label_summary.json"
    audit_path = phase_dir / f"{prefix}_refinement_audit.csv"

    # Generic aliases expected by later phases.
    label_policy_alias = phase_dir / "label_policy.json"
    suspicious_keys_alias = phase_dir / "suspicious_keys.jsonl"
    refined_summary_alias = phase_dir / "refined_label_summary.json"
    audit_alias = phase_dir / "refinement_audit.csv"
    summary_alias = phase_dir / "summary.json"

    print("\n" + "=" * 72)
    print("Phase 4 - Label Refinement Policy Builder")
    print("=" * 72)
    print(f"Current Run : {app.upper()}")
    print(f"Reading     : {phase3.get('probe_features')}")
    print("Mode        : conservative keys/policy only")
    print("=" * 72)

    if phase3.get("probe_features") is None or not Path(phase3["probe_features"]).exists():
        summary = {
            "phase": 4,
            "title": "Label Refinement Policy Builder",
            "status": "completed_with_warning",
            "app": app,
            "current_run": app.upper(),
            "generated_at": now_iso(),
            "warning": "Phase 3 probe_features file was not found. No refinement keys were generated.",
            "phase3_files": {k: str(v) if v else None for k, v in phase3.items()},
        }
        policy = _make_policy(
            app=app,
            thresholds=thresholds,
            window_minutes=window_minutes,
            near_window_radius=near_window_radius,
            max_benign_conversion_pct=max_benign_conversion_pct,
        )
        write_json(policy, label_policy_path)
        write_json(policy, label_policy_alias)
        write_json(summary, refined_summary_path)
        write_json(summary, refined_summary_alias)
        write_json(summary, summary_alias)
        suspicious_keys_path.write_bytes(b"")
        suspicious_keys_alias.write_bytes(b"")
        audit_path.write_text("", encoding="utf-8")
        audit_alias.write_text("", encoding="utf-8")
        return summary

    alert_key_set, alert_windows_by_src_ip, alert_ip_windows = _load_alert_windows(phase3.get("alert_ip_index"))

    policy = _make_policy(
        app=app,
        thresholds=thresholds,
        window_minutes=window_minutes,
        near_window_radius=near_window_radius,
        max_benign_conversion_pct=max_benign_conversion_pct,
    )
    write_json(policy, label_policy_path)
    write_json(policy, label_policy_alias)

    action_counter: Counter = Counter()
    probe_level_counter: Counter = Counter()

    probe_windows_read = 0
    keys_written = 0
    same_window_keys = 0
    near_window_keys = 0
    suspicious_only_keys = 0

    audit_fieldnames = [
        "app",
        "src_ip",
        "window_start",
        "label_action",
        "label_source",
        "Target_refined_for_no_alert",
        "suspicious_by_probe",
        "probe_score_no_alert",
        "probe_score_with_alert",
        "probe_level",
        "fanout_high",
        "event_count_window",
        "unique_dest_ip_window",
        "unique_dest_port_window",
        "event_type_alert_count_window",
        "valid_alert_count_window",
        "base_alert_positive_count_window",
        "alert_count_window",
        "no_alert_count_window",
        "matched_alert_window",
        "minutes_to_alert_window",
        "refinement_reason",
    ]

    with (
        suspicious_keys_path.open("wb") as f_keys,
        audit_path.open("w", newline="", encoding="utf-8") as f_audit,
    ):
        writer = csv.DictWriter(f_audit, fieldnames=audit_fieldnames)
        writer.writeheader()

        for rec in _jsonl_iter(Path(phase3["probe_features"])):
            probe_windows_read += 1

            src_ip = str(rec.get("src_ip", "")).strip()
            win = _window_key(rec.get("window_start"))

            if not src_ip or not win:
                continue

            key = (src_ip, win)

            score_no_alert = _safe_float(rec.get("probe_score_no_alert"), 0.0)
            score_with_alert = _safe_float(rec.get("probe_score_with_alert"), 0.0)
            fanout_high = _safe_int(rec.get("fanout_high"), 0) == 1

            same_alert_window = key in alert_key_set
            near_alert_window, matched_alert_window, minutes_to_alert = _nearest_alert_window(
                src_ip=src_ip,
                window_start=win,
                alert_windows_by_src_ip=alert_windows_by_src_ip,
                near_window_radius=near_window_radius,
                window_minutes=window_minutes,
            )

            label_action: Optional[str] = None
            target_for_no_alert = 0
            suspicious_by_probe = 0
            label_source = "benign_no_evidence"
            refinement_reason = "below_conservative_threshold"

            # Conservative priority:
            # 1. Same alert window + >= P90 + fanout.
            # 2. Near alert window + >= P95 + fanout.
            # 3. Extreme probe without strong alert association = suspicious only.
            if (
                same_alert_window
                and fanout_high
                and score_no_alert >= thresholds["same_window_score_threshold"]
            ):
                label_action = "probe_refined_same_window"
                target_for_no_alert = 1
                suspicious_by_probe = 1
                label_source = "probe_refined_same_window"
                refinement_reason = "same_src_ip_same_alert_window_and_probe_score_ge_p90_and_fanout_high"
                same_window_keys += 1

            elif (
                near_alert_window
                and fanout_high
                and score_no_alert >= thresholds["near_window_score_threshold"]
            ):
                label_action = "probe_refined_near_alert_window"
                target_for_no_alert = 1
                suspicious_by_probe = 1
                label_source = "probe_refined_near_alert_window"
                refinement_reason = "same_src_ip_near_alert_window_and_probe_score_ge_p95_and_fanout_high"
                near_window_keys += 1

            elif (
                fanout_high
                and score_no_alert >= thresholds["extreme_score_threshold"]
            ):
                label_action = "suspicious_probe_only"
                target_for_no_alert = 0
                suspicious_by_probe = 1
                label_source = "suspicious_probe_only"
                refinement_reason = "extreme_probe_without_strong_alert_association"
                suspicious_only_keys += 1

            if label_action is None:
                continue

            out = {
                "app": app,
                "src_ip": src_ip,
                "window_start": win,
                "key": {
                    "app": app,
                    "src_ip": src_ip,
                    "window_start": win,
                },
                "label_action": label_action,
                "label_source": label_source,
                "Target_refined_for_no_alert": int(target_for_no_alert),
                "suspicious_by_probe": int(suspicious_by_probe),
                "refinement_reason": refinement_reason,

                "probe_score_no_alert": float(score_no_alert),
                "probe_score_with_alert": float(score_with_alert),
                "probe_level": rec.get("probe_level"),
                "fanout_high": int(fanout_high),

                "event_count_window": _safe_int(rec.get("event_count_window"), 0),
                "unique_dest_ip_window": _safe_int(rec.get("unique_dest_ip_window"), 0),
                "unique_dest_port_window": _safe_int(rec.get("unique_dest_port_window"), 0),
                "total_bytes_window": _safe_int(rec.get("total_bytes_window"), 0),
                "total_pkts_window": _safe_int(rec.get("total_pkts_window"), 0),
                "event_type_alert_count_window": _safe_int(rec.get("event_type_alert_count_window"), 0),
                "valid_alert_count_window": _safe_int(rec.get("valid_alert_count_window"), 0),
                "base_alert_positive_count_window": _safe_int(
                    rec.get("base_alert_positive_count_window", rec.get("valid_alert_count_window", 0)),
                    0,
                ),
                "alert_count_window": _safe_int(rec.get("alert_count_window"), 0),
                "no_alert_count_window": _safe_int(rec.get("no_alert_count_window"), 0),

                "same_alert_window": int(same_alert_window),
                "near_alert_window": int(near_alert_window),
                "matched_alert_window": matched_alert_window,
                "minutes_to_alert_window": minutes_to_alert,
            }

            _write_jsonl_record(f_keys, out)
            writer.writerow(_audit_row(out))

            keys_written += 1
            action_counter[label_action] += 1
            probe_level_counter[str(rec.get("probe_level", "unknown"))] += 1

    # Generic alias copies.
    _copy_text_file(suspicious_keys_path, suspicious_keys_alias)
    _copy_text_file(audit_path, audit_alias)

    initial_label_counts = phase1_summary.get("label_counts", {})
    initial_benign = phase1_summary.get("benign") or phase1_summary.get("initial_benign")
    initial_attack = phase1_summary.get("attack") or phase1_summary.get("initial_malicious")

    probe_refined_keys = same_window_keys + near_window_keys

    summary = {
        "phase": 4,
        "title": "Label Refinement Policy Builder",
        "status": "completed",
        "current_run": app.upper(),
        "app": app,
        "generated_at": now_iso(),

        "input": {
            "phase3_probe_features": str(phase3.get("probe_features")),
            "phase3_alert_ip_index": str(phase3.get("alert_ip_index")),
            "phase3_summary": str(phase3.get("summary")),
            "phase1_summary": str(_phase1_summary_path(phase_dir)) if _phase1_summary_path(phase_dir) else None,
        },
        "output": {
            "label_policy": str(label_policy_path),
            "suspicious_keys": str(suspicious_keys_path),
            "refined_label_summary": str(refined_summary_path),
            "refinement_audit": str(audit_path),
            "summary_alias": str(summary_alias),
        },

        "label_policy": {
            "label_mode": "event_type_or_valid_alert",
            "base_alert_positive": "event_type == alert OR valid Suricata alert evidence",
            "phase3_alert_ip_index_note": (
                "Patched Phase 3 writes alert_ip_index windows when "
                "base_alert_positive_count_window > 0. Legacy valid-alert-only "
                "indexes are still readable but may undercount alert windows."
            ),
        },
        "probe_windows_read": int(probe_windows_read),
        "alert_ip_windows": int(alert_ip_windows),
        "keys_written": int(keys_written),
        "probe_refined_keys": int(probe_refined_keys),
        "same_window_refined_keys": int(same_window_keys),
        "near_window_refined_keys": int(near_window_keys),
        "suspicious_only_keys": int(suspicious_only_keys),

        "action_counts": {str(k): int(v) for k, v in action_counter.items()},
        "probe_level_counts": {str(k): int(v) for k, v in probe_level_counter.items()},

        "initial_label_counts_from_phase1": initial_label_counts,
        "initial_benign_from_phase1": initial_benign,
        "initial_attack_from_phase1": initial_attack,

        "thresholds": thresholds,
        "window_minutes": int(window_minutes),
        "near_window_radius": int(near_window_radius),
        "max_benign_conversion_pct": float(max_benign_conversion_pct),

        "safety_guards": {
            "ip_only_relabeling_enabled": False,
            "requires_same_or_near_base_alert_window_for_target_change": True,
            "extreme_probe_without_alert_association_is_suspicious_only": True,
            "final_row_counts_deferred_to_phase8": True,
        },

        "output_size_bytes": {
            "label_policy": int(file_size_bytes(label_policy_path)),
            "suspicious_keys": int(file_size_bytes(suspicious_keys_path)),
            "refinement_audit": int(file_size_bytes(audit_path)),
        },

        "methodology_note": (
            "Phase 4 creates conservative refinement keys from Phase 3 aggregate evidence. "
            "It does not scan the full app JSONL and does not write a row-level labeled dataset. "
            "It uses base alert windows aligned with split/Phase 8: event_type=alert OR valid alert evidence. "
            "Phase 8 applies these keys while exporting the final dataset."
        ),
    }

    write_json(summary, refined_summary_path)
    write_json(summary, refined_summary_alias)
    write_json(summary, summary_alias)

    print("\n" + "=" * 72)
    print("Phase 4 - Label Refinement Policy Builder")
    print("=" * 72)
    print(f"Current Run           : {app.upper()}")
    print(f"Reading               : {phase3.get('probe_features')}")
    print(f"Alert IP Windows      : {alert_ip_windows:,}")
    print("Alert Policy          : event_type_or_valid_alert")
    print(f"Probe Windows Read    : {probe_windows_read:,}")
    print(f"Probe Refined Keys    : {probe_refined_keys:,}")
    print(f"Suspicious-only Keys  : {suspicious_only_keys:,}")
    print(f"Output                : {refined_summary_path}")
    print("=" * 72 + "\n")

    return summary


# Backward-compatible aliases for pipeline fallback registry.
phase4_run = run_phase4
phase4_label_refinement = run_phase4
