"""Walk an offline input path and list the files worth reading (untrusted input).

Accepted inputs (``--input``):

* a folder of exported notebooks / code files (``.py .sql .scala .r .ipynb``), walked
  recursively; ``.dbc`` and ``.zip`` workspace exports inside it are read too
* a single ``.dbc`` or ``.zip`` workspace export, or a single code file
* a ``.json`` snapshot written by an earlier live run (``--save-snapshot``)

Content is not parsed here. Symlinks are never followed. Order is deterministic.
"""

from __future__ import annotations

from pathlib import Path

from dbx_premig.errors import NothingFoundError, UnsupportedFileError
from dbx_premig.models import FileRef

__all__ = ["SOURCE_EXTENSIONS", "find_inputs", "kind_of"]

SOURCE_EXTENSIONS = {".py": "source", ".sql": "source", ".scala": "source", ".r": "source"}
_KINDS = {**SOURCE_EXTENSIONS, ".ipynb": "ipynb", ".dbc": "dbc", ".zip": "zip", ".json": "snapshot"}
_SKIP_DIRS = {".git", "__pycache__", ".ipynb_checkpoints", ".venv", "node_modules"}


def kind_of(path: Path) -> str | None:
    """Input kind from the file extension, or None when the file is not read."""
    return _KINDS.get(path.suffix.lower())


def _ref(path: Path, root: Path, kind: str) -> FileRef:
    rel = path.relative_to(root).as_posix() if path != root else path.name
    return FileRef(path=str(path), relative_path=rel, kind=kind, size_bytes=path.stat().st_size)


def find_inputs(input_path: Path) -> list[FileRef]:
    """FileRefs for everything readable under ``input_path``, sorted case-insensitively."""
    if input_path.is_symlink():
        raise UnsupportedFileError(f"Input {input_path.name} is a symbolic link; pass the target.")
    if not input_path.exists():
        raise NothingFoundError(f"Input {input_path} does not exist.")
    if input_path.is_file():
        kind = kind_of(input_path)
        if kind is None:
            raise UnsupportedFileError(
                f"{input_path.name} is not a supported input "
                "(.py .sql .scala .r .ipynb .dbc .zip or a .json snapshot)."
            )
        return [_ref(input_path, input_path.parent, kind)]

    refs: list[FileRef] = []
    stack = [input_path]
    while stack:
        folder = stack.pop()
        for entry in folder.iterdir():
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                    stack.append(entry)
                continue
            kind = kind_of(entry)
            # A .json inside a folder is not treated as a snapshot (it may be anything).
            if kind and kind != "snapshot":
                refs.append(_ref(entry, input_path, kind))
    refs.sort(key=lambda r: (r.relative_path.casefold(), r.relative_path))
    if not refs:
        raise NothingFoundError(
            f"No Databricks code or exports found under {input_path.name} "
            "(.py .sql .scala .r .ipynb .dbc .zip)."
        )
    return refs
