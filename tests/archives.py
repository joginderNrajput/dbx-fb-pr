"""Hostile and valid archive fixtures, generated at test time (never committed)."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

__all__ = ["dbc_archive", "hostile_archives", "source_zip"]


def source_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "export/Shared/a.py", "# Databricks notebook source\ndbutils.widgets.get('x')\n"
        )
        zf.writestr("export/Shared/b.sql", "-- Databricks notebook source\nSELECT 1\n")
        zf.writestr("export/readme.txt", "ignored")
        zf.writestr("export/inner.zip", b"PK\x05\x06" + b"\x00" * 18)
    return path


def dbc_archive(path: Path) -> Path:
    nb = {
        "name": "etl",
        "language": "scala",
        "commands": [
            {"command": 'val df = spark.read.load("dbfs:/mnt/x")'},
            {"command": "%run ./helpers"},
        ],
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Shared/etl.scala", json.dumps(nb))
        zf.writestr("Shared/broken.python", "not json")
    return path


def hostile_archives(folder: Path) -> dict[str, Path]:
    """name -> archive the reader must refuse."""
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}

    out["zip_slip"] = folder / "slip.zip"
    with zipfile.ZipFile(out["zip_slip"], "w") as zf:
        zf.writestr("../../etc/evil.py", "print(1)")

    out["absolute"] = folder / "absolute.zip"
    with zipfile.ZipFile(out["absolute"], "w") as zf:
        zf.writestr("/etc/evil.py", "print(1)")

    out["symlink"] = folder / "symlink.zip"
    with zipfile.ZipFile(out["symlink"], "w") as zf:
        info = zipfile.ZipInfo("link.py")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")

    out["bomb"] = folder / "bomb.zip"
    with zipfile.ZipFile(out["bomb"], "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.py", "#" * 5_000_000)

    out["many"] = folder / "many.zip"
    with zipfile.ZipFile(out["many"], "w") as zf:
        for i in range(30):
            zf.writestr(f"n{i}.py", "x")

    out["not_zip"] = folder / "fake.dbc"
    out["not_zip"].write_bytes(b"this is not an archive")
    return out
