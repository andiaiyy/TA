#!/usr/bin/env python3
"""
Pre-pipeline: split selected Suricata EVE app(s) incrementally.

Purpose:
- This script is NOT part of main.py / pipeline.py.
- It is a pre-pipeline utility.
- It can process one app or several apps in one execution.
- It writes one output file per selected app:
    eve_http.jsonl, eve_tls.jsonl, eve_dns.jsonl, eve_ssh.jsonl
- It updates split_summary.json incrementally:
    run http       -> creates/updates apps.http
    run tls        -> creates/updates apps.tls while preserving apps.http
    run http again -> replaces only apps.http entry
    run http,tls   -> updates apps.http and apps.tls only

Important:
- Selected apps are processed in one raw-file scan.
- Example: --apps http,tls reads the raw EVE JSONL once, then writes
  eve_http.jsonl and eve_tls.jsonl during the same pass.
- Re-running a selected app still replaces only that app output/summary entry
  while preserving other completed app entries in split_summary.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, Literal, Optional, TextIO


# Type-safe app selector.
AppName = Literal["http", "tls", "dns", "ssh"]
LabelMode = Literal[
    "valid_alert",
    "event_type_alert",
    "event_type_or_valid_alert",
    "alert_object",
]
APP_TARGETS: tuple[AppName, ...] = ("tls","http")

# Raw Suricata EVE JSONL input.
INPUT_FILE = Path(r"D:/eve.json")
OUTPUT_DIR: Optional[Path] = None
_THIS_FILE = Path(__file__).resolve()
try:
    PROJECT_ROOT = _THIS_FILE.parents[3]
except IndexError:
    PROJECT_ROOT = _THIS_FILE.parent
PORTS_FILE = PROJECT_ROOT / "config" / "ports.txt"

# 0 = unlimited / no sampling.
# >0 = only write first N matched rows per app.
MAX_ROWS_PER_APP = 0

# If True, malformed lines are written to malformed_<app>.jsonl.
WRITE_MALFORMED = True

# Print progress every N raw lines scanned. 0 disables progress.
PROGRESS_EVERY = 100_000

# Useful when double-clicking on Windows.
PAUSE_ON_FINISH = True

# Initial label mode for split_summary.json only.
#
# valid_alert:
#   malicious only if alert dict exists, severity exists, and category is not ignored.
#   This is conservative, but can produce 0 malicious if all HTTP alerts are weak/generic.
#
# event_type_alert:
#   malicious if event_type == "alert".
#   This matches the older/simple interpretation and prevents alert rows from becoming benign.
#
# event_type_or_valid_alert:
#   malicious if event_type == "alert" OR valid alert evidence exists.
#
# alert_object:
#   malicious if alert object exists, regardless of severity/category.
#
# Recommendation for current test run:
#   event_type_or_valid_alert
LABEL_MODE: LabelMode = "event_type_or_valid_alert"

# Keep the split summary lightweight for very large EVE files.
# False = only keep selected-app essentials: rows, written counts, label counts,
#         compact alert diagnostics, match reasons, and output paths.
# True  = also keep large exploratory counters such as per-port histograms,
#         app_proto/event_type distributions, and alert category/signature top lists.
COLLECT_DETAILED_SUMMARY = False


# ============================================================
# LABEL POLICY FOR INITIAL BENIGN/MALICIOUS SUMMARY
# ============================================================

IGNORED_ALERT_CATEGORIES = {
    "generic protocol decode",
    "generic protocol command decode",
}


# ============================================================
# PORT TEMPLATE
# ============================================================
# This is NOT an active fallback.
# Active ports must come from configs/ports.txt.
# This template is only used to create an example ports.txt if missing.

PORT_TEMPLATE: Dict[str, set[int]] = {
    "dns": {53},
    "http": {80, 8080, 8000, 8008, 8888},
    "tls": {443, 8443},
    "ssh": {22},
}


VALID_APPS = {"http", "tls", "dns", "ssh"}


# ============================================================
# Utilities
# ============================================================

def normalize_app(value: object) -> str:
    if value is None:
        return ""
    app = str(value).strip().lower()
    app = app.replace("-", "_").replace(".", "_").replace("/", "_")
    app = re.sub(r"[^a-z0-9_]+", "_", app)
    app = re.sub(r"_+", "_", app).strip("_")
    return app


def normalize_category(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def safe_int(value: object) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def make_output_dir(input_path: Path, base_dir: Optional[Path]) -> Path:
    folder_name = re.sub(r"[^A-Za-z0-9_]+", "_", input_path.name).strip("_")
    if base_dir is None:
        base_dir = input_path.parent
    return base_dir / folder_name


def parse_app_targets(value: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = list(value)

    apps: list[str] = []
    for item in raw_items:
        app = normalize_app(item)
        if not app:
            continue
        if app not in VALID_APPS:
            raise ValueError(f"Invalid app target: {app!r}. Must be one of {sorted(VALID_APPS)}")
        if app not in apps:
            apps.append(app)

    if not apps:
        raise ValueError("At least one app target is required.")

    return tuple(apps)


def write_ports_template(path: Path) -> None:
    """
    Create a starter configs/ports.txt template if missing.

    The script still stops after creating this file, so the user can inspect/edit it.
    This prevents silent fallback to hidden hardcoded ports.
    """
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Port list for pre-pipeline app splitting.",
        "# This file is the single source of truth for port fallback.",
        "# Format: app=comma-separated-ports",
        "",
        "# Detection priority in split_eve_by_app_incremental.py:",
        "# 1. app_proto",
        "# 2. event_type",
        "# 3. src_port/dest_port fallback using these ports",
        "",
    ]

    for app in ("dns", "http", "tls", "ssh"):
        ports = ",".join(str(p) for p in sorted(PORT_TEMPLATE[app]))
        lines.append(f"{app}={ports}")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def read_ports_file(path: Path) -> Dict[str, set[int]]:
    """
    Read configs/ports.txt as the single source of truth.

    Supported format:
        http=80,8080,8000
        tls=443,8443
        dns=53
        ssh=22

    Empty lines and lines beginning with # are ignored.
    """
    path = Path(path)

    if not path.exists():
        write_ports_template(path)
        raise FileNotFoundError(
            f"Ports file was missing, so a template was created at: {path}\n"
            "Review/edit this file, then run the script again."
        )

    out: Dict[str, set[int]] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"Invalid ports file line, expected app=ports: {raw_line!r}")

        app_raw, ports_raw = line.split("=", 1)
        app = normalize_app(app_raw)
        if app not in VALID_APPS:
            raise ValueError(f"Invalid app in ports file: {app!r}")

        ports: set[int] = set()
        for item in ports_raw.split(","):
            item = item.strip()
            if not item:
                continue
            p = int(item)
            if not (0 <= p <= 65535):
                raise ValueError(f"Port out of range in ports file: {p}")
            ports.add(p)

        if not ports:
            raise ValueError(f"No ports configured for app={app!r} in {path}")

        out[app] = ports

    missing = VALID_APPS - set(out)
    if missing:
        raise ValueError(
            f"Missing app port definitions in {path}: {sorted(missing)}. "
            "Define all apps explicitly."
        )

    return out


def alert_diagnostics(obj: dict) -> dict:
    """
    Explain why a row is or is not counted as malicious.

    This is intentionally separate from is_malicious_initial() so the summary
    can show why malicious became 0.
    """
    event_type = normalize_app(obj.get("event_type"))
    alert = obj.get("alert")
    alert_is_dict = isinstance(alert, dict)

    category = ""
    severity = None
    signature = ""

    if alert_is_dict:
        category = normalize_category(alert.get("category"))
        severity = alert.get("severity")
        signature = str(alert.get("signature") or "").strip()

    severity_exists = severity is not None and str(severity).strip() != ""
    ignored_category = category in IGNORED_ALERT_CATEGORIES
    valid_alert = bool(alert_is_dict and severity_exists and not ignored_category)

    return {
        "event_type_alert": event_type == "alert",
        "alert_dict_exists": alert_is_dict,
        "alert_severity_exists": severity_exists,
        "ignored_alert_category": ignored_category,
        "valid_alert": valid_alert,
        "alert_category": category or "<missing>",
        "alert_signature": signature or "<missing>",
    }


def is_valid_alert(obj: dict) -> bool:
    """
    Conservative alert-based malicious evidence.

    Target_alert = 1 if:
    - alert exists and is a dict
    - alert.severity exists
    - alert.category is not ignored generic protocol decode category
    """
    return bool(alert_diagnostics(obj)["valid_alert"])


def is_malicious_initial(obj: dict, *, label_mode: LabelMode = LABEL_MODE) -> bool:
    """
    Initial benign/malicious label for split_summary.json.

    Important:
    This is NOT the final thesis label. Phase 4 still performs label refinement.
    """
    diag = alert_diagnostics(obj)
    mode = str(label_mode).strip().lower()

    if mode == "valid_alert":
        return bool(diag["valid_alert"])

    if mode == "event_type_alert":
        return bool(diag["event_type_alert"])

    if mode == "event_type_or_valid_alert":
        return bool(diag["event_type_alert"] or diag["valid_alert"])

    if mode == "alert_object":
        return bool(diag["alert_dict_exists"])

    raise ValueError(
        f"Invalid LABEL_MODE={label_mode!r}. "
        "Use valid_alert, event_type_alert, event_type_or_valid_alert, or alert_object."
    )


def get_ports(obj: dict) -> tuple[Optional[int], Optional[int]]:
    return safe_int(obj.get("src_port")), safe_int(obj.get("dest_port"))


def detect_target_app_match(
    obj: dict,
    *,
    target_app: str,
    app_ports: Dict[str, set[int]],
) -> tuple[bool, str, list[int]]:
    """
    Detect whether a row belongs to target_app.

    Priority:
    1. app_proto
    2. event_type
    3. src_port/dest_port fallback

    Returns:
        matched, reason, matched_ports
    """
    target_app = normalize_app(target_app)
    app_proto = normalize_app(obj.get("app_proto"))
    event_type = normalize_app(obj.get("event_type"))

    if app_proto == target_app:
        return True, "app_proto", []

    if event_type == target_app:
        return True, "event_type", []

    src_port, dest_port = get_ports(obj)
    ports = {p for p in (src_port, dest_port) if p is not None}
    known_ports = app_ports.get(target_app, set())
    matched_ports = sorted(ports & known_ports)

    if matched_ports:
        return True, "port_fallback", matched_ports

    return False, "unmatched", []


def update_port_summary(
    summary_counter: dict[int, Counter],
    port: Optional[int],
    *,
    is_malicious: bool,
) -> None:
    if port is None:
        return
    label = "malicious" if is_malicious else "benign"
    summary_counter[int(port)]["total"] += 1
    summary_counter[int(port)][label] += 1


def counter_to_dict(counter: Counter) -> dict:
    return {str(k): int(v) for k, v in counter.items()}


def nested_port_summary_to_dict(summary_counter: dict[int, Counter]) -> dict:
    out = {}
    for port in sorted(summary_counter):
        c = summary_counter[port]
        out[str(port)] = {
            "total": int(c.get("total", 0)),
            "benign": int(c.get("benign", 0)),
            "malicious": int(c.get("malicious", 0)),
        }
    return out


def compact_app_summary(app_summary: dict, *, detailed: bool = COLLECT_DETAILED_SUMMARY) -> dict:
    """Remove heavy exploratory counters from split_summary.json by default.

    The split utility is only a pre-pipeline splitter. For 800M-line input,
    storing per-port histograms, app_proto/event_type histograms, and alert
    category/signature top lists makes split_summary.json unnecessarily large.
    The important sanity-check information is preserved: selected app rows,
    written rows, label policy, label counts, compact alert diagnostics, match
    reasons, paths, and output size.
    """
    app_summary["detailed_summary_enabled"] = bool(detailed)
    if detailed:
        return app_summary

    for key in (
        "alert_category_counts_top50",
        "alert_signature_counts_top50",
        "app_proto_counts",
        "event_type_counts",
        "dest_port_summary",
        "src_port_summary",
        "app_port_hit_summary",
    ):
        app_summary.pop(key, None)

    app_summary["summary_policy"] = (
        "Lightweight summary: per-port histograms and verbose categorical "
        "distributions are disabled because this pre-pipeline step only needs "
        "selected-app row counts, label sanity checks, and output paths."
    )
    return app_summary


def print_split_progress(
    *,
    target_app: str,
    total_lines: int,
    matched_rows: int,
    written_rows: int,
    unmatched_rows: int,
    malformed: int,
    empty_lines: int,
    t0: float,
) -> None:
    """Heartbeat that prints based on raw scanned lines, not only matched rows."""
    elapsed = max(time.perf_counter() - t0, 1e-9)
    speed = total_lines / elapsed

    print(
        f"[split:{target_app}] scanned={total_lines:,} | "
        f"matched={matched_rows:,} | written={written_rows:,} | "
        f"unmatched={unmatched_rows:,} | malformed={malformed:,} | "
        f"empty={empty_lines:,} | speed={speed:,.0f} lines/s",
        flush=True,
    )


def atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def load_existing_summary(path: Path) -> dict:
    if not path.exists():
        return {
            "schema_version": 2,
            "description": "Incremental app split summary. Each app entry is replaceable independently.",
            "apps": {},
            "aggregate": {},
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "schema_version": 2,
            "description": "Incremental app split summary. Previous summary was unreadable.",
            "apps": {},
            "aggregate": {},
            "previous_summary_unreadable": str(path),
        }

    # Migrate old flat summary format if needed.
    if "apps" not in data:
        return {
            "schema_version": 2,
            "description": "Incremental app split summary. Legacy flat summary preserved.",
            "legacy_summary": data,
            "apps": {},
            "aggregate": {},
        }

    data.setdefault("schema_version", 2)
    data.setdefault("apps", {})
    data.setdefault("aggregate", {})
    return data


def recompute_aggregate(summary: dict) -> None:
    apps = summary.get("apps", {})
    written_counts = {}
    label_counts_by_app = {}
    output_files = {}
    completed_apps = []

    total_written = 0
    total_benign = 0
    total_malicious = 0

    for app, app_summary in sorted(apps.items()):
        completed_apps.append(app)
        written = int(app_summary.get("written_rows", 0))
        benign = int(app_summary.get("label_counts", {}).get("benign", 0))
        malicious = int(app_summary.get("label_counts", {}).get("malicious", 0))

        written_counts[app] = written
        label_counts_by_app[app] = {
            "benign": benign,
            "malicious": malicious,
        }
        output_files[app] = app_summary.get("output_file")

        total_written += written
        total_benign += benign
        total_malicious += malicious

    summary["aggregate"] = {
        "apps_completed": completed_apps,
        "written_counts": written_counts,
        "label_counts_by_app": label_counts_by_app,
        "output_files": output_files,
        "total_written_all_completed_apps": total_written,
        "total_benign_all_completed_apps": total_benign,
        "total_malicious_all_completed_apps": total_malicious,
        "last_updated_at": now_iso(),
    }


# ============================================================
# Split one app
# ============================================================

def split_one_app(
    *,
    input_file: Path,
    output_dir: Path,
    target_app: str,
    app_ports: Dict[str, set[int]],
    ports_file: Path,
    max_rows_per_app: int = 0,
    write_malformed: bool = True,
    progress_every: int = 100_000,
    label_mode: LabelMode = LABEL_MODE,
) -> dict:
    input_file = Path(input_file)
    output_dir = Path(output_dir)
    target_app = normalize_app(target_app)
    ports_file = Path(ports_file)

    if target_app not in VALID_APPS:
        raise ValueError(f"target_app must be one of {sorted(VALID_APPS)}, got: {target_app!r}")

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"eve_{target_app}.jsonl"
    summary_path = output_dir / "split_summary.json"
    malformed_path = output_dir / f"malformed_{target_app}.jsonl"

    # Important:
    # Re-running the same app overwrites only that app output file.
    # Existing other app files are preserved.
    writer = output_file.open("w", encoding="utf-8", newline="\n")

    malformed_writer: Optional[TextIO] = None
    if write_malformed:
        malformed_writer = malformed_path.open("w", encoding="utf-8", newline="\n")

    total_lines = 0
    empty_lines = 0
    malformed = 0
    matched_rows = 0
    written_rows = 0
    capped_skipped_rows = 0
    unmatched_rows = 0

    label_counts = Counter()
    match_reason_counts = Counter()
    event_type_counts = Counter()
    app_proto_counts = Counter()

    alert_diagnostic_counts = Counter()
    alert_category_counts = Counter()
    alert_signature_counts = Counter()

    dest_port_summary: dict[int, Counter] = defaultdict(Counter)
    src_port_summary: dict[int, Counter] = defaultdict(Counter)
    app_port_hit_summary: dict[int, Counter] = defaultdict(Counter)

    run_started = now_iso()
    t0 = time.perf_counter()

    print("\n--- APP SPLIT START ---", flush=True)
    print(f"App        : {target_app}", flush=True)
    print(f"Input      : {input_file}", flush=True)
    print(f"Output     : {output_file}", flush=True)
    print(f"Progress   : every {progress_every:,} raw lines" if progress_every > 0 else "Progress   : disabled", flush=True)

    try:
        with input_file.open("r", encoding="utf-8", errors="ignore") as f:
            for total_lines, line in enumerate(f, start=1):
                if progress_every > 0 and total_lines % progress_every == 0:
                    print_split_progress(
                        target_app=target_app,
                        total_lines=total_lines,
                        matched_rows=matched_rows,
                        written_rows=written_rows,
                        unmatched_rows=unmatched_rows,
                        malformed=malformed,
                        empty_lines=empty_lines,
                        t0=t0,
                    )

                raw = line.rstrip("\n")

                if not raw.strip():
                    empty_lines += 1
                    continue

                try:
                    obj = json.loads(raw)
                    if not isinstance(obj, dict):
                        raise ValueError("JSON line is not an object")
                except Exception:
                    malformed += 1
                    if malformed_writer is not None:
                        malformed_writer.write(raw + "\n")
                    continue

                matched, reason, matched_ports = detect_target_app_match(
                    obj,
                    target_app=target_app,
                    app_ports=app_ports,
                )

                if not matched:
                    unmatched_rows += 1
                    continue

                matched_rows += 1
                match_reason_counts[reason] += 1

                if COLLECT_DETAILED_SUMMARY:
                    app_proto = normalize_app(obj.get("app_proto")) or "<missing>"
                    event_type = normalize_app(obj.get("event_type")) or "<missing>"
                    app_proto_counts[app_proto] += 1
                    event_type_counts[event_type] += 1

                diag = alert_diagnostics(obj)
                for k in (
                    "event_type_alert",
                    "alert_dict_exists",
                    "alert_severity_exists",
                    "ignored_alert_category",
                    "valid_alert",
                ):
                    if diag.get(k):
                        alert_diagnostic_counts[k] += 1

                if COLLECT_DETAILED_SUMMARY and diag.get("alert_dict_exists"):
                    alert_category_counts[str(diag.get("alert_category") or "<missing>")] += 1
                    alert_signature_counts[str(diag.get("alert_signature") or "<missing>")] += 1

                malicious = is_malicious_initial(obj, label_mode=label_mode)
                label = "malicious" if malicious else "benign"
                label_counts[label] += 1

                if COLLECT_DETAILED_SUMMARY:
                    src_port, dest_port = get_ports(obj)
                    update_port_summary(src_port_summary, src_port, is_malicious=malicious)
                    update_port_summary(dest_port_summary, dest_port, is_malicious=malicious)

                    for p in matched_ports:
                        update_port_summary(app_port_hit_summary, p, is_malicious=malicious)

                if max_rows_per_app > 0 and written_rows >= max_rows_per_app:
                    capped_skipped_rows += 1
                    continue

                writer.write(raw + "\n")
                written_rows += 1

    finally:
        writer.close()
        if malformed_writer is not None:
            malformed_writer.close()

    elapsed = time.perf_counter() - t0
    run_finished = now_iso()

    app_summary = {
        "app": target_app,
        "input_file": str(input_file),
        "output_dir": str(output_dir),
        "output_file": str(output_file),
        "ports_file": str(ports_file),
        "ports_used": sorted(int(p) for p in app_ports.get(target_app, set())),
        "run_started_at": run_started,
        "run_finished_at": run_finished,
        "elapsed_seconds": float(elapsed),

        "total_lines_scanned": int(total_lines),
        "empty_lines": int(empty_lines),
        "malformed": int(malformed),
        "unmatched_rows": int(unmatched_rows),
        "matched_rows": int(matched_rows),
        "written_rows": int(written_rows),
        "capped_skipped_rows": int(capped_skipped_rows),
        "max_rows_per_app": int(max_rows_per_app),

        "label_policy": {
            "label_mode": str(label_mode),
            "malicious": (
                "event_type == alert OR valid Suricata alert evidence"
                if str(label_mode) == "event_type_or_valid_alert"
                else str(label_mode)
            ),
            "benign": "does not match the selected initial label mode",
            "ignored_alert_categories": sorted(IGNORED_ALERT_CATEGORIES),
            "note": (
                "This is an initial pre-pipeline summary label only. "
                "Final Target is created later by Phase 4 label refinement."
            ),
        },
        "label_counts": {
            "benign": int(label_counts.get("benign", 0)),
            "malicious": int(label_counts.get("malicious", 0)),
        },
        "alert_diagnostics": {
            "event_type_alert": int(alert_diagnostic_counts.get("event_type_alert", 0)),
            "alert_dict_exists": int(alert_diagnostic_counts.get("alert_dict_exists", 0)),
            "alert_severity_exists": int(alert_diagnostic_counts.get("alert_severity_exists", 0)),
            "ignored_alert_category": int(alert_diagnostic_counts.get("ignored_alert_category", 0)),
            "valid_alert": int(alert_diagnostic_counts.get("valid_alert", 0)),
            "why_zero_malicious_hint": (
                "If event_type_alert > 0 but valid_alert == 0, then the old strict valid_alert "
                "policy was rejecting alert rows because alert is missing, severity is missing, "
                "or category is ignored."
            ),
        },
        "alert_category_counts_top50": {
            str(k): int(v) for k, v in alert_category_counts.most_common(50)
        },
        "alert_signature_counts_top50": {
            str(k): int(v) for k, v in alert_signature_counts.most_common(50)
        },

        "match_reason_counts": counter_to_dict(match_reason_counts),
        "app_proto_counts": counter_to_dict(app_proto_counts),
        "event_type_counts": counter_to_dict(event_type_counts),

        "dest_port_summary": nested_port_summary_to_dict(dest_port_summary),
        "src_port_summary": nested_port_summary_to_dict(src_port_summary),
        "app_port_hit_summary": nested_port_summary_to_dict(app_port_hit_summary),

        "malformed_file": str(malformed_path) if write_malformed else None,
        "output_size_bytes": int(output_file.stat().st_size) if output_file.exists() else 0,
    }
    app_summary = compact_app_summary(app_summary)

    summary = load_existing_summary(summary_path)

    # Preserve other app summaries.
    # Re-running the same app replaces only this app entry.
    summary["input_file"] = str(input_file)
    summary["output_dir"] = str(output_dir)
    summary["ports_file"] = str(ports_file)
    summary["selected_apps_supported"] = sorted(VALID_APPS)
    summary["last_run_apps"] = summary.get("last_run_apps", [])
    summary["apps"][target_app] = app_summary

    recompute_aggregate(summary)
    atomic_write_json(summary_path, summary)

    print_split_progress(
        target_app=target_app,
        total_lines=total_lines,
        matched_rows=matched_rows,
        written_rows=written_rows,
        unmatched_rows=unmatched_rows,
        malformed=malformed,
        empty_lines=empty_lines,
        t0=t0,
    )

    print("\n=== APP SPLIT DONE ===")
    print(f"App        : {target_app}")
    print(f"Input      : {input_file}")
    print(f"Output     : {output_file}")
    print(f"Summary    : {summary_path}")
    print(f"Ports file : {ports_file}")
    print(f"Matched    : {matched_rows:,}")
    print(f"Written    : {written_rows:,}")
    print(f"Label mode : {label_mode}")
    print(f"Benign     : {label_counts.get('benign', 0):,}")
    print(f"Malicious  : {label_counts.get('malicious', 0):,}")
    print(f"Alert evt  : {alert_diagnostic_counts.get('event_type_alert', 0):,}")
    print(f"Alert obj  : {alert_diagnostic_counts.get('alert_dict_exists', 0):,}")
    print(f"Severity   : {alert_diagnostic_counts.get('alert_severity_exists', 0):,}")
    print(f"Ignored cat: {alert_diagnostic_counts.get('ignored_alert_category', 0):,}")
    print(f"Valid alert: {alert_diagnostic_counts.get('valid_alert', 0):,}")
    print(f"Elapsed    : {elapsed/60:.2f} min")

    return app_summary


def detect_selected_app_matches(
    obj: dict,
    *,
    target_apps: Iterable[str],
    app_ports: Dict[str, set[int]],
) -> dict[str, tuple[str, list[int]]]:
    """
    Detect all selected app matches for one JSON object in a single pass.

    This keeps the old per-target matching priority:
    1. app_proto
    2. event_type
    3. src_port/dest_port fallback

    Returns:
        {app: (reason, matched_ports)}
    """
    app_proto = normalize_app(obj.get("app_proto"))
    event_type = normalize_app(obj.get("event_type"))
    src_port, dest_port = get_ports(obj)
    ports = {p for p in (src_port, dest_port) if p is not None}

    matches: dict[str, tuple[str, list[int]]] = {}

    for app_raw in target_apps:
        app = normalize_app(app_raw)

        if app_proto == app:
            matches[app] = ("app_proto", [])
            continue

        if event_type == app:
            matches[app] = ("event_type", [])
            continue

        known_ports = app_ports.get(app, set())
        matched_ports = sorted(ports & known_ports)
        if matched_ports:
            matches[app] = ("port_fallback", matched_ports)

    return matches


def make_app_state(
    *,
    app: str,
    input_file: Path,
    output_dir: Path,
    ports_file: Path,
    app_ports: Dict[str, set[int]],
    write_malformed: bool,
    run_started: str,
) -> dict:
    """Create mutable per-app counters and output writers."""
    output_file = output_dir / f"eve_{app}.jsonl"
    malformed_path = output_dir / f"malformed_{app}.jsonl"

    # Re-running selected apps replaces only their files.
    writer = output_file.open("w", encoding="utf-8", newline="\n")
    malformed_writer: Optional[TextIO] = None
    if write_malformed:
        malformed_writer = malformed_path.open("w", encoding="utf-8", newline="\n")

    return {
        "app": app,
        "input_file": input_file,
        "output_dir": output_dir,
        "output_file": output_file,
        "ports_file": ports_file,
        "ports_used": sorted(int(p) for p in app_ports.get(app, set())),
        "malformed_path": malformed_path,
        "writer": writer,
        "malformed_writer": malformed_writer,
        "run_started_at": run_started,
        "matched_rows": 0,
        "written_rows": 0,
        "capped_skipped_rows": 0,
        "unmatched_rows": 0,
        "label_counts": Counter(),
        "match_reason_counts": Counter(),
        "event_type_counts": Counter(),
        "app_proto_counts": Counter(),
        "alert_diagnostic_counts": Counter(),
        "alert_category_counts": Counter(),
        "alert_signature_counts": Counter(),
        "dest_port_summary": defaultdict(Counter),
        "src_port_summary": defaultdict(Counter),
        "app_port_hit_summary": defaultdict(Counter),
    }


def close_app_states(states: dict[str, dict]) -> None:
    """Close all file handles safely."""
    for state in states.values():
        writer = state.get("writer")
        if writer is not None:
            writer.close()
            state["writer"] = None

        malformed_writer = state.get("malformed_writer")
        if malformed_writer is not None:
            malformed_writer.close()
            state["malformed_writer"] = None


def print_multi_app_progress(
    *,
    total_lines: int,
    empty_lines: int,
    malformed: int,
    no_selected_app_match: int,
    states: dict[str, dict],
    t0: float,
    final: bool = False,
) -> None:
    """
    Heartbeat for one-pass multi-app split.

    It rewrites the current terminal line instead of printing a new line every
    interval. This keeps long 800M-line runs readable.
    """
    elapsed = max(time.perf_counter() - t0, 1e-9)
    speed = total_lines / elapsed

    written_parts = []
    label_parts = []
    for app in sorted(states):
        state = states[app]
        labels = state.get("label_counts", Counter())
        written_parts.append(f"{app}={int(state['written_rows']):,}")
        label_parts.append(
            f"{app}:M={int(labels.get('malicious', 0)):,}/B={int(labels.get('benign', 0)):,}"
        )

    line = (
        f"[split:multi] read={total_lines:,} | "
        f"written({', '.join(written_parts)}) | "
        f"labels({', '.join(label_parts)}) | "
        f"skipped_other={no_selected_app_match:,} | "
        f"malformed={malformed:,} | empty={empty_lines:,} | "
        f"speed={speed:,.0f} lines/s"
    )

    last_width = int(getattr(print_multi_app_progress, "_last_width", 0))
    padded = line.ljust(last_width)
    sys.stdout.write("\r" + padded)
    sys.stdout.flush()
    setattr(print_multi_app_progress, "_last_width", max(last_width, len(line)))

    if final:
        sys.stdout.write("\n")
        sys.stdout.flush()
        setattr(print_multi_app_progress, "_last_width", 0)


def build_app_summary_from_state(
    *,
    state: dict,
    total_lines: int,
    empty_lines: int,
    malformed: int,
    run_finished: str,
    elapsed: float,
    max_rows_per_app: int,
    label_mode: LabelMode,
    write_malformed: bool,
) -> dict:
    """Convert mutable per-app state into split_summary.json payload."""
    output_file = Path(state["output_file"])
    malformed_path = Path(state["malformed_path"])
    label_counts: Counter = state["label_counts"]
    alert_diagnostic_counts: Counter = state["alert_diagnostic_counts"]
    alert_category_counts: Counter = state["alert_category_counts"]
    alert_signature_counts: Counter = state["alert_signature_counts"]

    app_summary = {
        "app": str(state["app"]),
        "process_mode": "single_pass_multi_app",
        "input_file": str(state["input_file"]),
        "output_dir": str(state["output_dir"]),
        "output_file": str(output_file),
        "ports_file": str(state["ports_file"]),
        "ports_used": list(state["ports_used"]),
        "run_started_at": str(state["run_started_at"]),
        "run_finished_at": run_finished,
        "elapsed_seconds": float(elapsed),

        "total_lines_scanned": int(total_lines),
        "empty_lines": int(empty_lines),
        "malformed": int(malformed),
        "unmatched_rows": int(state["unmatched_rows"]),
        "matched_rows": int(state["matched_rows"]),
        "written_rows": int(state["written_rows"]),
        "capped_skipped_rows": int(state["capped_skipped_rows"]),
        "max_rows_per_app": int(max_rows_per_app),

        "label_policy": {
            "label_mode": str(label_mode),
            "malicious": (
                "event_type == alert OR valid Suricata alert evidence"
                if str(label_mode) == "event_type_or_valid_alert"
                else str(label_mode)
            ),
            "benign": "does not match the selected initial label mode",
            "ignored_alert_categories": sorted(IGNORED_ALERT_CATEGORIES),
            "note": (
                "This is an initial pre-pipeline summary label only. "
                "Final Target is created later by Phase 4 label refinement."
            ),
        },
        "label_counts": {
            "benign": int(label_counts.get("benign", 0)),
            "malicious": int(label_counts.get("malicious", 0)),
        },
        "alert_diagnostics": {
            "event_type_alert": int(alert_diagnostic_counts.get("event_type_alert", 0)),
            "alert_dict_exists": int(alert_diagnostic_counts.get("alert_dict_exists", 0)),
            "alert_severity_exists": int(alert_diagnostic_counts.get("alert_severity_exists", 0)),
            "ignored_alert_category": int(alert_diagnostic_counts.get("ignored_alert_category", 0)),
            "valid_alert": int(alert_diagnostic_counts.get("valid_alert", 0)),
            "why_zero_malicious_hint": (
                "If event_type_alert > 0 but valid_alert == 0, then the old strict valid_alert "
                "policy was rejecting alert rows because alert is missing, severity is missing, "
                "or category is ignored."
            ),
        },
        "alert_category_counts_top50": {
            str(k): int(v) for k, v in alert_category_counts.most_common(50)
        },
        "alert_signature_counts_top50": {
            str(k): int(v) for k, v in alert_signature_counts.most_common(50)
        },

        "match_reason_counts": counter_to_dict(state["match_reason_counts"]),
        "app_proto_counts": counter_to_dict(state["app_proto_counts"]),
        "event_type_counts": counter_to_dict(state["event_type_counts"]),

        "dest_port_summary": nested_port_summary_to_dict(state["dest_port_summary"]),
        "src_port_summary": nested_port_summary_to_dict(state["src_port_summary"]),
        "app_port_hit_summary": nested_port_summary_to_dict(state["app_port_hit_summary"]),

        "malformed_file": str(malformed_path) if write_malformed else None,
        "output_size_bytes": int(output_file.stat().st_size) if output_file.exists() else 0,
    }
    return compact_app_summary(app_summary)


def split_selected_apps(
    *,
    input_file: Path,
    output_dir: Path,
    app_targets: Iterable[str],
    ports_file: Path,
    max_rows_per_app: int = 0,
    write_malformed: bool = True,
    progress_every: int = 100_000,
    label_mode: LabelMode = LABEL_MODE,
) -> dict:
    """
    Split selected apps in one raw-file scan.

    Example:
        --apps http,tls

    Behavior:
    - raw EVE JSONL is read once
    - eve_http.jsonl and eve_tls.jsonl are opened together
    - each matching row is written immediately to the relevant app output(s)
    - split_summary.json updates only selected app entries and preserves others
    """
    input_file = Path(input_file)
    output_dir = Path(output_dir)
    ports_file = Path(ports_file)

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    output_dir.mkdir(parents=True, exist_ok=True)

    app_targets = parse_app_targets(app_targets)
    app_ports = read_ports_file(ports_file)

    started = now_iso()
    t0 = time.perf_counter()

    states = {
        app: make_app_state(
            app=app,
            input_file=input_file,
            output_dir=output_dir,
            ports_file=ports_file,
            app_ports=app_ports,
            write_malformed=write_malformed,
            run_started=started,
        )
        for app in app_targets
    }

    total_lines = 0
    empty_lines = 0
    malformed = 0
    no_selected_app_match = 0

    print("\n=== PRE-PIPELINE SPLIT START ===")
    print(f"Mode       : single-pass multi-app")
    print(f"Input      : {input_file}")
    print(f"Output dir : {output_dir}")
    print(f"Apps       : {', '.join(app_targets)}")
    print(f"Ports file : {ports_file}")
    print(f"Progress   : every {progress_every:,} raw lines" if progress_every > 0 else "Progress   : disabled")
    print("================================")

    try:
        with input_file.open("r", encoding="utf-8", errors="ignore") as f:
            for total_lines, line in enumerate(f, start=1):
                raw = line.rstrip("\n")

                if not raw.strip():
                    empty_lines += 1
                    if progress_every > 0 and total_lines % progress_every == 0:
                        print_multi_app_progress(
                            total_lines=total_lines,
                            empty_lines=empty_lines,
                            malformed=malformed,
                            no_selected_app_match=no_selected_app_match,
                            states=states,
                            t0=t0,
                        )
                    continue

                try:
                    obj = json.loads(raw)
                    if not isinstance(obj, dict):
                        raise ValueError("JSON line is not an object")
                except Exception:
                    malformed += 1
                    if write_malformed:
                        for state in states.values():
                            malformed_writer = state.get("malformed_writer")
                            if malformed_writer is not None:
                                malformed_writer.write(raw + "\n")

                    if progress_every > 0 and total_lines % progress_every == 0:
                        print_multi_app_progress(
                            total_lines=total_lines,
                            empty_lines=empty_lines,
                            malformed=malformed,
                            no_selected_app_match=no_selected_app_match,
                            states=states,
                            t0=t0,
                        )
                    continue

                matches = detect_selected_app_matches(
                    obj,
                    target_apps=app_targets,
                    app_ports=app_ports,
                )

                if not matches:
                    no_selected_app_match += 1

                diag: Optional[dict] = None
                malicious: Optional[bool] = None
                src_port: Optional[int] = None
                dest_port: Optional[int] = None
                app_proto = normalize_app(obj.get("app_proto")) or "<missing>"
                event_type = normalize_app(obj.get("event_type")) or "<missing>"

                for app in app_targets:
                    state = states[app]

                    if app not in matches:
                        state["unmatched_rows"] += 1
                        continue

                    reason, matched_ports = matches[app]
                    state["matched_rows"] += 1
                    state["match_reason_counts"][reason] += 1
                    if COLLECT_DETAILED_SUMMARY:
                        state["app_proto_counts"][app_proto] += 1
                        state["event_type_counts"][event_type] += 1

                    if diag is None:
                        diag = alert_diagnostics(obj)
                    for k in (
                        "event_type_alert",
                        "alert_dict_exists",
                        "alert_severity_exists",
                        "ignored_alert_category",
                        "valid_alert",
                    ):
                        if diag.get(k):
                            state["alert_diagnostic_counts"][k] += 1

                    if COLLECT_DETAILED_SUMMARY and diag.get("alert_dict_exists"):
                        state["alert_category_counts"][str(diag.get("alert_category") or "<missing>")] += 1
                        state["alert_signature_counts"][str(diag.get("alert_signature") or "<missing>")] += 1

                    if malicious is None:
                        malicious = is_malicious_initial(obj, label_mode=label_mode)
                    label = "malicious" if malicious else "benign"
                    state["label_counts"][label] += 1

                    if COLLECT_DETAILED_SUMMARY:
                        if src_port is None and dest_port is None:
                            src_port, dest_port = get_ports(obj)
                        update_port_summary(state["src_port_summary"], src_port, is_malicious=malicious)
                        update_port_summary(state["dest_port_summary"], dest_port, is_malicious=malicious)

                        for p in matched_ports:
                            update_port_summary(state["app_port_hit_summary"], p, is_malicious=malicious)

                    if max_rows_per_app > 0 and int(state["written_rows"]) >= max_rows_per_app:
                        state["capped_skipped_rows"] += 1
                        continue

                    state["writer"].write(raw + "\n")
                    state["written_rows"] += 1

                if progress_every > 0 and total_lines % progress_every == 0:
                    print_multi_app_progress(
                        total_lines=total_lines,
                        empty_lines=empty_lines,
                        malformed=malformed,
                        no_selected_app_match=no_selected_app_match,
                        states=states,
                        t0=t0,
                    )

    finally:
        close_app_states(states)

    elapsed = time.perf_counter() - t0
    finished = now_iso()

    print_multi_app_progress(
        total_lines=total_lines,
        empty_lines=empty_lines,
        malformed=malformed,
        no_selected_app_match=no_selected_app_match,
        states=states,
        t0=t0,
        final=True,
    )

    summary_path = output_dir / "split_summary.json"
    summary = load_existing_summary(summary_path)
    summary["schema_version"] = max(int(summary.get("schema_version", 2)), 3)
    summary["description"] = "Single-pass app split summary. Each selected app entry is replaceable independently."
    summary["process_mode"] = "single_pass_multi_app"
    summary["input_file"] = str(input_file)
    summary["output_dir"] = str(output_dir)
    summary["ports_file"] = str(ports_file)
    summary["selected_apps_supported"] = sorted(VALID_APPS)
    summary["last_run_apps"] = list(app_targets)
    summary["last_run_started_at"] = started
    summary["last_run_finished_at"] = finished
    summary["last_run_elapsed_seconds"] = float(elapsed)
    summary["last_run_total_lines_scanned"] = int(total_lines)
    summary["last_run_no_selected_app_match"] = int(no_selected_app_match)
    summary.setdefault("apps", {})

    results = {}
    for app, state in states.items():
        app_summary = build_app_summary_from_state(
            state=state,
            total_lines=total_lines,
            empty_lines=empty_lines,
            malformed=malformed,
            run_finished=finished,
            elapsed=elapsed,
            max_rows_per_app=max_rows_per_app,
            label_mode=label_mode,
            write_malformed=write_malformed,
        )
        summary["apps"][app] = app_summary
        results[app] = app_summary

    recompute_aggregate(summary)
    summary["aggregate"]["process_mode"] = "single_pass_multi_app"
    summary["aggregate"]["last_run_total_lines_scanned"] = int(total_lines)
    summary["aggregate"]["last_run_no_selected_app_match"] = int(no_selected_app_match)
    atomic_write_json(summary_path, summary)

    print("\n=== PRE-PIPELINE SPLIT FINISHED ===")
    print(f"Mode       : single-pass multi-app")
    print(f"Apps       : {', '.join(app_targets)}")
    print(f"Read lines : {total_lines:,}")
    for app in app_targets:
        app_summary = results[app]
        labels = app_summary.get("label_counts", {})
        print(
            f"{app:<10} matched={app_summary['matched_rows']:,} | "
            f"written={app_summary['written_rows']:,} | "
            f"benign={int(labels.get('benign', 0)):,} | "
            f"malicious={int(labels.get('malicious', 0)):,} | "
            f"output={app_summary['output_file']}"
        )
    print(f"Summary    : {summary_path}")
    print(f"Elapsed    : {elapsed/60:.2f} min")

    return {
        "apps": results,
        "elapsed_seconds": float(elapsed),
        "total_lines_scanned": int(total_lines),
        "process_mode": "single_pass_multi_app",
    }


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Pre-pipeline: split selected Suricata EVE app(s) in one raw-file scan.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    ap.add_argument("--input-file", type=str, default=str(INPUT_FILE))
    ap.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR) if OUTPUT_DIR is not None else "")
    ap.add_argument(
        "--apps",
        type=str,
        default=",".join(APP_TARGETS),
        help="Comma-separated apps to process, e.g. http or http,tls,dns,ssh.",
    )
    ap.add_argument("--ports-file", type=str, default=str(PORTS_FILE))
    ap.add_argument("--max-rows", type=int, default=int(MAX_ROWS_PER_APP))
    ap.add_argument("--no-malformed", action="store_true")
    ap.add_argument("--progress-every", type=int, default=int(PROGRESS_EVERY))
    ap.add_argument(
        "--label-mode",
        type=str,
        default=str(LABEL_MODE),
        choices=["valid_alert", "event_type_alert", "event_type_or_valid_alert", "alert_object"],
        help="Initial label policy for split_summary.json.",
    )
    ap.add_argument("--no-pause", action="store_true")

    return ap.parse_args()


def main() -> None:
    args = parse_args()

    input_file = Path(args.input_file)
    output_dir = Path(args.output_dir) if str(args.output_dir).strip() else make_output_dir(input_file, None)
    ports_file = Path(args.ports_file)
    apps = parse_app_targets(str(args.apps))

    split_selected_apps(
        input_file=input_file,
        output_dir=output_dir,
        app_targets=apps,
        ports_file=ports_file,
        max_rows_per_app=int(args.max_rows),
        write_malformed=not bool(args.no_malformed),
        progress_every=int(args.progress_every),
        label_mode=str(args.label_mode),
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\n=== ERROR ===")
        print(exc)
        raise
    finally:
        if PAUSE_ON_FINISH:
            try:
                import sys
                if "--no-pause" not in sys.argv:
                    input("\nPress Enter to close...")
            except EOFError:
                pass
