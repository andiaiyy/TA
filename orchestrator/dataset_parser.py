"""
Dataset parser — CSV loading and cleaning.

Loads a CSV file and performs minimal cleaning:
  - Strip whitespace from column headers
  - Replace infinity values with NaN

Does NOT:
  - Validate schema (that's validator.py)
  - Drop rows or columns
  - Impute missing values
  - Access database

⚠️  IMPORT RESTRICTION: No imports from ui/, database/, or pipelines/.
"""
import numpy as np
import pandas as pd
from pathlib import Path


def parse_dataset(file_path: str) -> pd.DataFrame:
    """
    Load a CSV file and return a cleaned DataFrame.

    Steps:
      1. Check file exists
      2. Check .csv extension
      3. Check path is within allowed directories (prevents path traversal)
      4. Read CSV
      5. Strip whitespace from column names
      6. Replace inf/-inf with NaN

    Args:
        file_path: Path to CSV file.

    Returns:
        Cleaned DataFrame.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file is not .csv format or is outside allowed directories.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if path.suffix.lower() != ".csv":
        raise ValueError(f"Unsupported file format: {path.suffix}. Only .csv is supported.")

    # Path safety check — only allow files within the project directory.
    # Use is_relative_to (Python 3.9+) to avoid startswith substring confusion
    # (e.g. /project/foo matching /project/foobar) and Windows case issues.
    from config.settings import DATASETS_DIR, BASE_DIR
    resolved = path.resolve()
    allowed_roots = [
        Path(DATASETS_DIR).resolve(),
        Path(BASE_DIR).resolve(),
    ]
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError(
            f"Access denied: dataset path must be within the project directory. "
            f"Got: {resolved}"
        )

    # Use resolved path for the actual read to avoid TOCTOU between check and open.
    df = pd.read_csv(resolved)
    df.columns = df.columns.str.strip()
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    return df
