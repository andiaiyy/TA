"""Regression tests for the cross-environment path fallback (Fix A).

Fix A lives in:
  - utils/hashing.py::sha256_file
  - orchestrator/dataset_parser.py::parse_dataset

When the caller passes an absolute path that does NOT exist in the current
environment (e.g. a Windows path D:\\... seen by a Linux worker, or a Linux
path /app/... seen by a Windows host), both functions retry against
DATASETS_DIR using only the basename. Datasets live as flat files in that
directory, so basename lookup is unambiguous.

These tests would FAIL if Fix A is reverted, because Path(foreign_path)
would not exist and the original FileNotFoundError would propagate.
"""
import pytest

from utils.hashing import sha256_file
from orchestrator.dataset_parser import parse_dataset


@pytest.fixture
def datasets_dir_with_csv(tmp_path, monkeypatch):
    """Point DATASETS_DIR (and BASE_DIR for the safety check) to a tmp folder containing data.csv."""
    csv = tmp_path / "data.csv"
    csv.write_text("A,B,Label\n1,2,BENIGN\n3,4,DDoS\n")

    import config.settings as _s
    monkeypatch.setattr(_s, "BASE_DIR", tmp_path)
    monkeypatch.setattr(_s, "DATASETS_DIR", str(tmp_path))
    return csv


def test_sha256_file_fallback_resolves_by_basename(datasets_dir_with_csv):
    """A foreign absolute path that does not exist must be resolved via DATASETS_DIR / basename."""
    foreign_path = "/app/storage/datasets/data.csv"   # Linux-flavoured path not present here
    digest_via_fallback = sha256_file(foreign_path)
    digest_direct = sha256_file(str(datasets_dir_with_csv))
    assert digest_via_fallback == digest_direct, "fallback must hash the same bytes as the real file"
    assert len(digest_via_fallback) == 64           # SHA-256 hex digest length


def test_sha256_file_still_raises_when_basename_not_in_datasets_dir(datasets_dir_with_csv):
    """If both the original path AND the basename in DATASETS_DIR are missing, raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="File not found:"):
        sha256_file("/app/storage/datasets/absent_basename.csv")


def test_parse_dataset_fallback_resolves_by_basename(datasets_dir_with_csv):
    """parse_dataset must accept a foreign absolute path and load the file via DATASETS_DIR / basename."""
    foreign_path = "/app/storage/datasets/data.csv"
    df = parse_dataset(foreign_path)
    assert len(df) == 2
    assert list(df.columns) == ["A", "B", "Label"]


def test_parse_dataset_still_raises_when_basename_not_in_datasets_dir(datasets_dir_with_csv):
    """If neither the original path nor the basename exists, FileNotFoundError must still surface."""
    with pytest.raises(FileNotFoundError, match="File not found:"):
        parse_dataset("/app/storage/datasets/no_such_file.csv")
