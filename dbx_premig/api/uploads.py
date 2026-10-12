"""Upload checks: basename only, extension allow-list, magic bytes, streaming size cap."""

from __future__ import annotations

from pathlib import Path, PurePath
from typing import Protocol

__all__ = ["UploadRejected", "save_upload"]

_CHUNK = 1024 * 1024
_ZIP_MAGIC = b"PK\x03\x04"


class UploadRejected(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class _Upload(Protocol):
    filename: str | None

    async def read(self, size: int = -1) -> bytes: ...


async def save_upload(upload: _Upload, folder: Path, max_bytes: int) -> Path:
    """Stream an uploaded discovery workbook to ``folder``; never trust its name or size."""
    name = PurePath((upload.filename or "").replace("\\", "/")).name
    if not name.lower().endswith(".xlsx"):
        raise UploadRejected("Only a discovery workbook (.xlsx) can be uploaded.", 415)
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in name)[:120] or "upload.xlsx"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / safe
    size = 0
    first = b""
    with target.open("wb") as fh:
        while True:
            chunk = await upload.read(_CHUNK)
            if not chunk:
                break
            if not first:
                first = chunk[:4]
            size += len(chunk)
            if size > max_bytes:
                fh.close()
                target.unlink(missing_ok=True)
                raise UploadRejected(f"The upload is larger than {max_bytes} bytes.", 413)
            fh.write(chunk)
    if size == 0 or first != _ZIP_MAGIC:
        target.unlink(missing_ok=True)
        raise UploadRejected("The upload is not an .xlsx workbook (bad file signature).", 415)
    return target
