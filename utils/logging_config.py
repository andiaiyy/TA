"""
Logging configuration.

Call setup_logging() once at application startup.
"""
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with consistent format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
