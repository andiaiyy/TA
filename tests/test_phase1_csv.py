"""
Unit + integration tests for Phase 1 CSV input support.

Tiny synthetic fixtures — all tests run in seconds.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The 7-phase EVE pipeline was archived (recoverable) under
# pipelines/_archive/eve_suricata_7phase/. phase1.py is self-contained, so this
# test still validates the archived Phase 1 CSV ingestion from its new location.
from pipelines._archive.eve_suricata_7phase.phases.phase1 import (
    _row_to_event,
    Phase1DiskConfig,
    phase1_load_and_label,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_FIELDNAMES = [
    "timestamp", "flow_id", "src_ip", "src_port", "dest_ip", "dest_port",
    "proto", "event_type",
    "alert.action", "alert.severity", "alert.category", "alert.metadata.confidence",
    "flow.pkts_toserver", "flow.pkts_toclient",
]


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_ndjson(path: Path, events: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _attack_row(src_ip: str = "1.2.3.4", i: int = 0) -> dict:
    return {
        "timestamp": "2025-01-01T00:00:00Z",
        "flow_id": str(i),
        "src_ip": src_ip,
        "src_port": "4444",
        "dest_ip": "10.0.0.1",
        "dest_port": "80",
        "proto": "TCP",
        "event_type": "alert",
        "alert.action": "allowed",
        "alert.severity": "3",
        "alert.category": "Malware",
        "alert.metadata.confidence": "high",
        "flow.pkts_toserver": "2",
        "flow.pkts_toclient": "1",
    }


def _benign_row(i: int = 0) -> dict:
    return {
        "timestamp": "2025-01-01T00:00:00Z",
        "flow_id": str(1000 + i),
        "src_ip": f"10.0.0.{i + 1}",
        "src_port": "55000",
        "dest_ip": "8.8.8.8",
        "dest_port": "443",
        "proto": "TCP",
        "event_type": "flow",
        "alert.action": "",
        "alert.severity": "",
        "alert.category": "",
        "alert.metadata.confidence": "",
        "flow.pkts_toserver": "10",
        "flow.pkts_toclient": "8",
    }


# ---------------------------------------------------------------------------
# Test 1: nested event reconstruction from dotted CSV columns
# ---------------------------------------------------------------------------

def test_csv_event_reconstruction():
    row = _attack_row()
    event = _row_to_event(row)

    assert event is not None
    assert isinstance(event.get("alert"), dict), "alert sub-dict must exist"
    assert event["alert"]["category"] == "Malware"
    assert event["alert"]["severity"] == "3"          # string — dtype=str
    assert isinstance(event["alert"].get("metadata"), dict)
    assert event["alert"]["metadata"]["confidence"] == "high"
    assert isinstance(event.get("flow"), dict), "flow sub-dict must exist"
    assert event["flow"]["pkts_toserver"] == "2"
    assert event["src_ip"] == "1.2.3.4"


# ---------------------------------------------------------------------------
# Test 2: empty alert columns → no "alert" key → _label_target returns 0
# ---------------------------------------------------------------------------

def test_csv_no_alert_means_no_alert_dict():
    row = _benign_row()
    event = _row_to_event(row)

    assert event is not None
    assert "alert" not in event, (
        "alert sub-dict must be absent when all alert.* columns are empty"
    )


# ---------------------------------------------------------------------------
# Test 3: missing src_ip → None
# ---------------------------------------------------------------------------

def test_csv_missing_src_ip_returns_none():
    row = _attack_row()
    row["src_ip"] = ""
    assert _row_to_event(row) is None

    row2 = {k: v for k, v in _attack_row().items() if k != "src_ip"}
    assert _row_to_event(row2) is None


# ---------------------------------------------------------------------------
# Test 4: end-to-end Phase 1 on a 20-row CSV (5 attacks, 15 benign)
# ---------------------------------------------------------------------------

def test_csv_phase1_end_to_end(tmp_path):
    rows = [_attack_row(f"1.2.3.{i}", i) for i in range(5)]
    rows += [_benign_row(i) for i in range(15)]

    csv_path = tmp_path / "eve_small.csv"
    _write_csv(csv_path, rows)

    df, summary = phase1_load_and_label(
        csv_path,
        seed=42,
        disk=Phase1DiskConfig(
            output_dir=tmp_path / "out",
            write_format="csv",   # avoid parquet dependency in tests
        ),
    )

    assert summary["attack_total"] == 5, f"attack_total={summary['attack_total']}"
    assert summary["benign_total"] == 15, f"benign_total={summary['benign_total']}"
    assert summary["attack_written"] == 5
    assert df is not None and len(df) > 0
    assert "Target" in df.columns


# ---------------------------------------------------------------------------
# Test 5: NDJSON path regression guard
# ---------------------------------------------------------------------------

def test_jsonl_path_unchanged(tmp_path):
    events = []
    for i in range(5):
        events.append({
            "timestamp": "2025-01-01T00:00:00Z",
            "flow_id": i,
            "src_ip": f"1.2.3.{i}",
            "src_port": 4444,
            "dest_ip": "10.0.0.1",
            "dest_port": 80,
            "proto": "TCP",
            "event_type": "alert",
            "alert": {"action": "allowed", "severity": 3, "category": "Malware"},
            "flow": {"pkts_toserver": 2, "pkts_toclient": 1},
        })
    for i in range(15):
        events.append({
            "timestamp": "2025-01-01T00:00:00Z",
            "flow_id": 1000 + i,
            "src_ip": f"10.0.0.{i + 1}",
            "src_port": 55000,
            "dest_ip": "8.8.8.8",
            "dest_port": 443,
            "proto": "TCP",
            "event_type": "flow",
            "flow": {"pkts_toserver": 10, "pkts_toclient": 8},
        })

    ndjson_path = tmp_path / "eve.json"
    _write_ndjson(ndjson_path, events)

    df, summary = phase1_load_and_label(
        ndjson_path,
        seed=42,
        disk=Phase1DiskConfig(
            output_dir=tmp_path / "out_ndjson",
            write_format="csv",
        ),
    )

    assert summary["attack_total"] == 5
    assert summary["benign_total"] == 15
    assert summary["attack_written"] == 5
    assert len(df) > 0 and "Target" in df.columns
