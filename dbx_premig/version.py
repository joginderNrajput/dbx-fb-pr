"""Product identity. Imports nothing so every module (and the PyInstaller spec) can read it."""

from __future__ import annotations

__all__ = ["APP_NAME", "APP_VERSION", "DIST_NAME", "SOURCE_PLATFORM", "TARGET_PLATFORM"]

APP_NAME = "Databricks Pre-Migration Discovery"
DIST_NAME = "dbx-premig"
APP_VERSION = "0.2.0"
SOURCE_PLATFORM = "Databricks"
TARGET_PLATFORM = "Microsoft Fabric"
