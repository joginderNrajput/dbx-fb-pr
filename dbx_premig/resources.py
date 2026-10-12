"""Frozen-safe access to bundled data files.

Never compute a data path from ``__file__`` elsewhere: inside a PyInstaller one-file binary
the package lives under ``sys._MEIPASS``. This module is the only place that knows that.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["asset_path", "catalog_path", "package_root", "rules_path"]


def package_root() -> Path:
    """Directory holding the ``dbx_premig`` package (source tree, wheel or frozen binary)."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "dbx_premig"
    return Path(__file__).resolve().parent


def catalog_path(name: str) -> Path:
    """Path of a file in ``catalog/data``."""
    return package_root() / "catalog" / "data" / name


def asset_path(name: str) -> Path:
    """Path of a brand asset in ``excel/assets``."""
    return package_root() / "excel" / "assets" / name


def rules_path() -> Path:
    """The bundled default assessment rules file."""
    return package_root() / "estimation" / "data" / "assessment_rules.yaml"
