"""Console logging: rich, quiet by default (WARNING), ``-v`` raises it to INFO.

Never log client content: no notebook source, SQL, connection strings or tokens. Log only
names, counts, durations and exception class names.
"""

from __future__ import annotations

import logging as _logging

from rich.console import Console
from rich.logging import RichHandler

__all__ = ["LOGGER_NAME", "configure_logging", "get_logger", "stderr_console"]

LOGGER_NAME = "dbx_premig"

#: stdout carries only the report path, so progress and logs go to stderr.
stderr_console = Console(stderr=True, highlight=False)


def configure_logging(level: str = "WARNING", verbose: bool = False) -> None:
    """Install the rich handler on the package logger (idempotent)."""
    logger = _logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    handler = RichHandler(console=stderr_console, show_path=False, rich_tracebacks=verbose)
    handler.setFormatter(_logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel("INFO" if verbose and level.upper() == "WARNING" else level.upper())
    logger.propagate = False


def get_logger(name: str) -> _logging.Logger:
    """Child logger of the package logger."""
    return _logging.getLogger(f"{LOGGER_NAME}.{name}")
