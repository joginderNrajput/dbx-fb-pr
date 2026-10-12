"""Offline input -> ``RawSnapshot``: the offline half of the reader stage.

The result has the same shape as a live capture (a ``notebooks`` section), so the parser has
one input type whatever the source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dbx_premig.config import Settings
from dbx_premig.discovery import find_inputs
from dbx_premig.models import RawSnapshot
from dbx_premig.reader import CodeObject, ReadFailure, read_archive, read_file, read_snapshot

__all__ = ["snapshot_from_path"]


def _item(obj: CodeObject) -> dict[str, Any]:
    return {
        "path": obj.path,
        "object_type": obj.object_type,
        "language": obj.language,
        "size": obj.size,
        "cells": obj.cells,
        "origin": "offline",
        "source": obj.source,
    }


def snapshot_from_path(input_path: Path, settings: Settings) -> RawSnapshot:
    """Read a folder / archive / code file / snapshot into a RawSnapshot."""
    if input_path.is_file() and input_path.suffix.lower() == ".json":
        return read_snapshot(input_path, settings)
    refs = find_inputs(input_path)
    notebooks: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for ref in refs:
        if ref.kind in {"zip", "dbc"}:
            result = read_archive(ref, settings)
            entries = result if isinstance(result, list) else [result]
        else:
            entries = [read_file(ref, settings)]
        for entry in entries:
            if isinstance(entry, ReadFailure):
                warnings.append({"source": entry.source, "message": entry.reason})
            else:
                notebooks.append(_item(entry))
    return RawSnapshot(
        mode="offline",
        source=str(input_path),
        captured_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        meta={"cloud": "", "collectors": ["notebooks"], "input_files": len(refs)},
        sections={"notebooks": notebooks},
        warnings=warnings,
    )
