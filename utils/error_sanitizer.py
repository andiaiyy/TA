"""
Error message sanitizer.

Strips absolute filesystem paths from exception messages before storing
them in the database or displaying them in the UI.
"""
import re

# Matches Windows absolute paths (C:\...) and Unix absolute paths (/segment/...)
_PATH_PATTERN = re.compile(
    r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n\s]*'  # Windows: C:\foo\bar
    r'|(?<!\w)/(?:[^/\0\s]+/)+[^/\0\s]*'                          # Unix: /app/storage/file
)


def sanitize_error(message: str, replacement: str = "<path>") -> str:
    """
    Replace absolute filesystem paths in an error string with a placeholder.

    Keeps the error type and description intact — only paths are redacted.

    Examples:
        "No such file: D:\\Program\\TA\\storage\\exp.db"
        → "No such file: <path>"

        "FileNotFoundError: [Errno 2] /app/storage/datasets/file.csv"
        → "FileNotFoundError: [Errno 2] <path>"
    """
    if not message:
        return message
    return _PATH_PATTERN.sub(replacement, message)
