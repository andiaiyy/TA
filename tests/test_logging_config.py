"""Tests for logging configuration."""
import logging
from unittest.mock import patch


def test_setup_logging_default():
    from utils.logging_config import setup_logging
    setup_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO


def test_setup_logging_debug():
    from utils.logging_config import setup_logging
    with patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"}):
        setup_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_json_mode():
    from utils.logging_config import setup_logging
    with patch.dict("os.environ", {"JSON_LOGS": "true"}):
        setup_logging()  # should not raise
