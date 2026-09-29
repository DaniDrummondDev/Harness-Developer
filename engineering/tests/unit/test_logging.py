from __future__ import annotations

import io
import logging

import pytest

from orchestrator.utils.logging import configure_logging


def test_logs_go_to_given_stream_with_consistent_format() -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream)
    logging.getLogger("orchestrator.test").info("hello")
    assert "INFO" in stream.getvalue()
    assert "orchestrator.test: hello" in stream.getvalue()


def test_level_filters_messages() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", stream=stream)
    logging.getLogger("orchestrator.test").info("hidden")
    assert stream.getvalue() == ""


def test_reconfiguring_does_not_duplicate_handlers() -> None:
    configure_logging("INFO", stream=io.StringIO())
    logger = configure_logging("INFO", stream=io.StringIO())
    # pytest may attach its own capture handlers; count only the Harness one.
    owned = [h for h in logger.handlers if getattr(h, "_harness_handler", False)]
    assert len(owned) == 1


def test_invalid_level() -> None:
    with pytest.raises(ValueError, match="invalid log level"):
        configure_logging("LOUD")
