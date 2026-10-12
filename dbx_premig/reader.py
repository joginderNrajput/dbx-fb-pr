"""Hardened readers for offline inputs (untrusted input boundary).

* Archives (``.zip`` / ``.dbc``): the whole manifest is validated **before a byte is read**:
  entry-count and total-size caps, no symlinks, no absolute paths or ``..`` escapes, no
  suspicious compression ratios. Members are then streamed into memory with a live byte
  counter. Nothing is ever extracted to disk (no ``extractall``). Nested archives are skipped.
* JSON (``.ipynb``, ``.dbc`` members, snapshots) is parsed with the standard library; no
  XML is read anywhere, so no entity expansion is possible.
* Every ``read_*`` function returns a value; a failure is a ``ReadFailure`` the caller turns
  into a warning. One bad file never ends a run.
"""

from __future__ import annotations

import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from dbx_premig.config import Settings
from dbx_premig.discovery import SOURCE_EXTENSIONS
from dbx_premig.errors import InvalidSnapshotError
from dbx_premig.models import FileRef, RawSnapshot

__all__ = [
    "CodeObject",
    "ReadFailure",
    "decode_text",
    "read_archive",
    "read_file",
    "read_snapshot",
    "source_from_dbc_json",
    "source_from_ipynb",
    "validate_archive",
]

_CHUNK = 64 * 1024
_LANG_BY_EXT = {".py": "PYTHON", ".sql": "SQL", ".scala": "SCALA", ".r": "R", ".ipynb": "PYTHON"}
_DBC_LANG_BY_EXT = {".python": "PYTHON", ".scala": "SCALA", ".sql": "SQL", ".r": "R"}
_NOTEBOOK_HEADERS = (
    "# Databricks notebook source",
    "-- Databricks notebook source",
    "// Databricks notebook source",
)
CELL_SEPARATORS = (
    "# COMMAND ----------",
    "-- COMMAND ----------",
    "// COMMAND ----------",
)


@dataclass(frozen=True)
class CodeObject:
    """One notebook or code file read from an offline input."""

    path: str
    language: str
    object_type: str  # NOTEBOOK | FILE
    source: str
    size: int
    cells: int | None = None


@dataclass(frozen=True)
class ReadFailure:
    source: str
    reason: str


def decode_text(raw: bytes) -> str:
    """The one sanctioned bytes -> text accessor (UTF-8 with BOM handling, never fails)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", "replace")


def _object_type(text: str) -> str:
    head = text.lstrip()[:64]
    return "NOTEBOOK" if head.startswith(_NOTEBOOK_HEADERS) else "FILE"


def source_from_ipynb(text: str) -> tuple[str, int] | None:
    """(source joined with cell separators, cell count), or None if it is not a notebook."""
    try:
        nb = json.loads(text)
    except ValueError:
        return None
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        return None
    parts: list[str] = []
    for cell in nb["cells"]:
        if not isinstance(cell, dict):
            continue
        src = cell.get("source", "")
        parts.append("".join(src) if isinstance(src, list) else str(src))
    return "\n# COMMAND ----------\n".join(parts), len(parts)


def source_from_dbc_json(text: str) -> tuple[str, str, int] | None:
    """(source, language, cells) of a notebook stored inside a .dbc archive, else None."""
    try:
        nb = json.loads(text)
    except ValueError:
        return None
    if not isinstance(nb, dict) or not isinstance(nb.get("commands"), list):
        return None
    commands = [str(c.get("command", "")) for c in nb["commands"] if isinstance(c, dict)]
    language = str(nb.get("language", "")).upper() or "PYTHON"
    return "\n# COMMAND ----------\n".join(commands), language, len(commands)


# --------------------------------------------------------------------------- archives


def validate_archive(zf: zipfile.ZipFile, name: str, settings: Settings) -> str | None:
    """Return a refusal reason, or None when the manifest is safe to stream."""
    infos = zf.infolist()
    if len(infos) > settings.max_archive_entries:
        return f"{name} has {len(infos)} entries (cap {settings.max_archive_entries})"
    total = 0
    for info in infos:
        member = info.filename
        pure = PurePosixPath(member.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or (len(member) > 1 and member[1] == ":"):
            return f"{name} has an entry that escapes the archive"
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            return f"{name} contains a symbolic link"
        total += info.file_size
        if total > settings.max_archive_bytes:
            return f"{name} expands beyond {settings.max_archive_bytes} bytes"
        if info.compress_size and info.file_size / info.compress_size > settings.max_archive_ratio:
            return f"{name} has a member with a suspicious compression ratio"
    return None


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes | None:
    """Stream one member with a live byte counter; None if it exceeds its declared size."""
    out = bytearray()
    cap = min(info.file_size, limit)
    with zf.open(info) as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > cap:
                return None
    return bytes(out)


def read_archive(ref: FileRef, settings: Settings) -> list[CodeObject | ReadFailure] | ReadFailure:
    """Notebooks and code files inside a .zip source export or a .dbc archive."""
    try:
        zf = zipfile.ZipFile(ref.path)
    except (zipfile.BadZipFile, OSError):
        return ReadFailure(ref.relative_path, "not a readable zip / dbc archive")
    with zf:
        refusal = validate_archive(zf, ref.relative_path, settings)
        if refusal:
            return ReadFailure(ref.relative_path, f"unsafe archive refused: {refusal}")
        results: list[CodeObject | ReadFailure] = []
        infos = sorted(
            (i for i in zf.infolist() if not i.is_dir()),
            key=lambda i: (i.filename.casefold(), i.filename),
        )
        for info in infos:
            member = info.filename.replace("\\", "/")
            suffix = PurePosixPath(member).suffix.lower()
            display = f"{ref.relative_path}!/{member}"
            if suffix in {".zip", ".dbc"}:
                results.append(ReadFailure(display, "nested archive skipped"))
                continue
            wanted = suffix in SOURCE_EXTENSIONS or suffix == ".ipynb"
            if ref.kind == "dbc":
                wanted = wanted or suffix in _DBC_LANG_BY_EXT
            if not wanted:
                continue
            raw = _read_member(zf, info, settings.max_notebook_bytes)
            if raw is None:
                results.append(ReadFailure(display, "member larger than the notebook cap"))
                continue
            obj = _code_object(member, suffix, raw, dbc=ref.kind == "dbc", prefix=ref.relative_path)
            results.append(obj if obj else ReadFailure(display, "not a readable notebook"))
        return results


def _code_object(
    member: str, suffix: str, raw: bytes, *, dbc: bool, prefix: str
) -> CodeObject | None:
    text = decode_text(raw)
    path = f"{prefix}!/{member}"
    if dbc and suffix in _DBC_LANG_BY_EXT:
        parsed = source_from_dbc_json(text)
        if parsed is None:
            return None
        src, lang, cells = parsed
        return CodeObject(path, lang, "NOTEBOOK", src, len(raw), cells)
    if suffix == ".ipynb":
        nb = source_from_ipynb(text)
        if nb is None:
            return None
        return CodeObject(path, "PYTHON", "NOTEBOOK", nb[0], len(raw), nb[1])
    return CodeObject(path, _LANG_BY_EXT.get(suffix, ""), _object_type(text), text, len(raw))


# --------------------------------------------------------------------------- files


def read_file(ref: FileRef, settings: Settings) -> CodeObject | ReadFailure:
    """Read one loose source / .ipynb file."""
    if ref.size_bytes > min(settings.max_file_bytes, settings.max_notebook_bytes):
        return ReadFailure(ref.relative_path, "file larger than the notebook cap")
    try:
        raw = Path(ref.path).read_bytes()
    except OSError as exc:
        return ReadFailure(ref.relative_path, f"unreadable ({type(exc).__name__})")
    suffix = Path(ref.path).suffix.lower()
    if ref.kind == "ipynb":
        nb = source_from_ipynb(decode_text(raw))
        if nb is None:
            return ReadFailure(ref.relative_path, "not a valid Jupyter notebook")
        return CodeObject(ref.relative_path, "PYTHON", "NOTEBOOK", nb[0], len(raw), nb[1])
    text = decode_text(raw)
    return CodeObject(
        ref.relative_path, _LANG_BY_EXT.get(suffix, ""), _object_type(text), text, len(raw)
    )


def read_snapshot(path: Path, settings: Settings) -> RawSnapshot:
    """Load a snapshot written by ``--save-snapshot``. Raises InvalidSnapshotError."""
    try:
        size = path.stat().st_size
        if size > settings.max_archive_bytes:
            raise InvalidSnapshotError(f"Snapshot {path.name} is larger than the safety cap.")
        data: Any = json.loads(decode_text(path.read_bytes()))
    except OSError as exc:
        raise InvalidSnapshotError(f"Cannot read snapshot {path.name}.") from exc
    except ValueError as exc:
        raise InvalidSnapshotError(f"Snapshot {path.name} is not valid JSON.") from exc
    try:
        snap = RawSnapshot.model_validate(data)
    except ValidationError as exc:
        raise InvalidSnapshotError(
            f"{path.name} is not a discovery snapshot.", detail=str(exc)
        ) from exc
    if snap.format_version != 1:
        raise InvalidSnapshotError(
            f"Snapshot {path.name} has format version {snap.format_version}; expected 1."
        )
    return snap
