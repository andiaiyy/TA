"""
File hashing utilities for dataset integrity tracking.
"""
import hashlib
from pathlib import Path


def sha256_file(file_path: str, chunk_size: int = 8192) -> str:
    """
    Compute SHA-256 hash of a file.

    Args:
        file_path: Path to file.
        chunk_size: Read chunk size in bytes.

    Returns:
        Hex digest string.

    Raises:
        FileNotFoundError: If file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        # Cross-environment fallback: when UI and worker run in different
        # environments (e.g. UI in Docker emitting /app/... paths, worker on
        # the Windows host, or vice versa), the absolute path from the other
        # side won't resolve here. Retry against the local DATASETS_DIR using
        # only the basename. Datasets live as flat files in that directory,
        # so basename lookup is unambiguous.
        from config.settings import DATASETS_DIR
        candidate = Path(DATASETS_DIR) / path.name
        if candidate.exists():
            path = candidate
        else:
            raise FileNotFoundError(f"File not found: {file_path}")

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
