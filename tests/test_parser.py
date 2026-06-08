"""Tests for dataset_parser.py."""
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from orchestrator.dataset_parser import parse_dataset


@pytest.fixture
def allow_tmp_path(tmp_path, monkeypatch):
    """Patch BASE_DIR so parse_dataset accepts files in tmp_path during tests."""
    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", tmp_path)
    monkeypatch.setattr(_s, "DATASETS_DIR", str(tmp_path))


def test_parse_valid_csv(tmp_path, allow_tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("A,B,Label\n1,2,BENIGN\n3,4,DDoS\n")
    df = parse_dataset(str(csv))
    assert len(df) == 2
    assert list(df.columns) == ["A", "B", "Label"]


def test_parse_strips_whitespace(tmp_path, allow_tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text(" A , B , Label \n1,2,X\n")
    df = parse_dataset(str(csv))
    assert "A" in df.columns
    assert "Label" in df.columns


def test_parse_replaces_infinity(tmp_path, allow_tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("A\n1\ninf\n-inf\n")
    df = parse_dataset(str(csv))
    assert df["A"].isna().sum() == 2


def test_parse_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_dataset("nonexistent.csv")


def test_parse_wrong_extension(tmp_path):
    f = tmp_path / "data.xlsx"
    f.write_text("fake")
    with pytest.raises(ValueError, match="Unsupported file format"):
        parse_dataset(str(f))


def test_parse_jsonl_extension_accepted(tmp_path, allow_tmp_path):
    """.jsonl files (Suricata native) must parse identically to .json (NDJSON)."""
    f = tmp_path / "data.jsonl"
    f.write_text(
        '{"timestamp": "2026-01-01T00:00:00", "event_type": "dns", "src_ip": "1.1.1.1"}\n'
        '{"timestamp": "2026-01-01T00:00:01", "event_type": "alert", "src_ip": "2.2.2.2"}\n'
    )
    df = parse_dataset(str(f))
    assert len(df) == 2
    assert "event_type" in df.columns
    assert set(df["event_type"]) == {"dns", "alert"}


def test_parse_ndjson_extension_accepted(tmp_path, allow_tmp_path):
    """.ndjson files (alternate Suricata extension) must parse identically."""
    f = tmp_path / "data.ndjson"
    f.write_text('{"k": 1}\n{"k": 2}\n')
    df = parse_dataset(str(f))
    assert len(df) == 2


def test_parse_path_traversal_blocked(tmp_path):
    """Path traversal attempts outside the project directory should be rejected."""
    evil_csv = tmp_path / "evil.csv"
    evil_csv.write_text("A,B\n1,2\n")

    from config.settings import BASE_DIR
    # Only assert the block when tmp_path is genuinely outside the project root
    if not tmp_path.resolve().is_relative_to(Path(BASE_DIR).resolve()):
        with pytest.raises(ValueError, match="Access denied"):
            parse_dataset(str(evil_csv))
