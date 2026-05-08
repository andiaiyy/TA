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
        raise FileNotFoundError(f"File not found: {file_path}")

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()
