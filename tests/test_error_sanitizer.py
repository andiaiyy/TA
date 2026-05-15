"""Tests for error message sanitizer."""
from utils.error_sanitizer import sanitize_error


def test_sanitize_windows_path():
    msg = r"FileNotFoundError: D:\Program\TA\storage\datasets\file.csv not found"
    result = sanitize_error(msg)
    assert "D:\\" not in result
    assert "<path>" in result
    assert "FileNotFoundError:" in result


def test_sanitize_unix_path():
    msg = "FileNotFoundError: /app/storage/datasets/file.csv not found"
    result = sanitize_error(msg)
    assert "/app/storage" not in result
    assert "<path>" in result


def test_sanitize_no_path():
    msg = "ValueError: Unknown pipeline id: cicids2017.fake"
    assert sanitize_error(msg) == msg


def test_sanitize_empty_string():
    assert sanitize_error("") == ""


def test_sanitize_none():
    assert sanitize_error(None) is None


def test_sanitize_multiple_windows_paths():
    msg = r"Error copying D:\Program\TA\a.csv to D:\Program\TA\b.csv"
    result = sanitize_error(msg)
    assert result.count("<path>") == 2
    assert "Error copying" in result


def test_sanitize_preserves_error_type():
    msg = r"PermissionError: [Errno 13] D:\Program\TA\storage\experiments.db"
    result = sanitize_error(msg)
    assert "PermissionError" in result
    assert "Errno 13" in result
    assert "<path>" in result


def test_sanitize_custom_replacement():
    msg = r"Error: D:\Program\TA\file.csv"
    result = sanitize_error(msg, replacement="[REDACTED]")
    assert "[REDACTED]" in result
    assert "D:\\" not in result
