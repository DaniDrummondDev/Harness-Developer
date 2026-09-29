"""Centralised logging configuration.

Rules:
- all Harness modules log through `logging.getLogger(__name__)`, i.e. under
  the `orchestrator` logger namespace;
- logs go to **stderr**; primary CLI output goes to stdout, so the two never mix;
- the default level is WARNING, so normal CLI usage prints no log noise;
- never log secrets, environment variables, full command lines or config
  values that may hold credentials (callers are responsible; see utils/shell.py).

Future structured logging (JSON, run audit events) should be added by
swapping the formatter/handler here, without touching callers.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

ROOT_LOGGER_NAME = "orchestrator"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_HANDLER_MARKER = "_harness_handler"


def configure_logging(level: str = "WARNING", *, stream: TextIO | None = None) -> logging.Logger:
    """Configure the `orchestrator` logger. Idempotent: replaces its own handler.

    Raises:
        ValueError: `level` is not one of `LEVELS`.
    """
    normalised = level.upper()
    if normalised not in LEVELS:
        raise ValueError(f"invalid log level '{level}'; expected one of {', '.join(LEVELS)}")

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)

    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    setattr(handler, _HANDLER_MARKER, True)

    logger.addHandler(handler)
    logger.setLevel(normalised)
    logger.propagate = False
    return logger
