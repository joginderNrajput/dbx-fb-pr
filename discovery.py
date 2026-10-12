# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#     "openpyxl>=3.1",
#     "pillow>=10.0",
#     "pydantic>=2.6",
#     "pydantic-settings>=2.2",
#     "PyYAML>=6.0",
#     "rich>=13.0",
#     "typer>=0.12",
# ]
# ///
"""Databricks -> Microsoft Fabric discovery: the entry point.

    python discovery.py                         # interactive: asks what to scan
    python discovery.py discover --host ... --token ...       # live workspace (read-only)
    python discovery.py discover --input ./exports            # offline export / snapshot
    uv run discovery.py discover --help                       # nothing installed beforehand

This file has no logic of its own: it hands over to ``dbx_premig.cli.main``. It is also the
PyInstaller entry point (``packaging/dbx_premig.spec``), so the built executable behaves the
same way: double-click it for the prompts, or pass the same arguments.
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    # Running from a source checkout without installing: make the package importable.
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from dbx_premig.cli import main

if __name__ == "__main__":
    main()
