"""TODO(after 1.0.0 - optional Postgres sink): write-only persistence of a discovery.

Lazily imported, behind the ``postgres`` extra, off unless ``DBXF_DATABASE_URL`` is set.
Excluded from the PyInstaller build.
"""

from __future__ import annotations

__all__: list[str] = []
