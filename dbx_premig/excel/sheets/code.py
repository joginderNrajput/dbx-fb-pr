"""Workspace code: Notebooks, Dependencies, Repos."""

from __future__ import annotations

from dbx_premig.excel.sheets.common import assessed_columns, yes_no
from dbx_premig.excel.types import Column, SheetSpec

__all__ = ["DEPENDENCIES", "NOTEBOOKS", "REPOS"]

N = "#,##0"

NOTEBOOKS = SheetSpec(
    name="Notebooks",
    title="Notebooks  ·  one row per notebook or code file",
    description=(
        "Every notebook and .py/.sql/.scala/.r file in the workspace (or the offline export): "
        "language, size, code features found and Fabric readiness."
    ),
    columns=[
        Column("Path", "path", 52),
        Column("Name", "name", 28),
        Column("Folder", "folder", 36),
        Column("Area", "area", 13),
        Column("Object type", "object_type", 11),
        Column("Language", "language", 10),
        Column("Lines", "lines", 9, numeric=True, number_format=N),
        Column("Cells", "cells", 8, numeric=True, number_format=N),
        Column("Size (bytes)", "size_bytes", 12, numeric=True, number_format=N),
        Column("Magic commands", "magic_commands", 10, numeric=True, number_format=N),
        Column(
            "SQL statements",
            "sql_statements",
            10,
            numeric=True,
            number_format=N,
            note="Approximate: SQL statements at line start plus spark.sql( calls",
        ),
        Column("Notebook calls", "runs_notebooks", 10, numeric=True, number_format=N),
        Column("Scanned", yes_no("scanned"), 9),
        Column("Modified", "modified_at", 16),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.notebooks,
    readiness_column="Readiness",
)

DEPENDENCIES = SheetSpec(
    name="Dependencies",
    title="Dependencies  ·  what calls what",
    description=(
        "Edges between assets: %run / dbutils.notebook.run, job tasks and DLT libraries. "
        "Resolved = No means the target was not found in this discovery."
    ),
    columns=[
        Column("From type", "from_type", 14),
        Column("From", "from_name", 44),
        Column("Relation", "relation", 18),
        Column("To", "to", 52),
        Column("Resolved", yes_no("resolved"), 10),
    ],
    rows=lambda r: r.estate.dependencies,
)

REPOS = SheetSpec(
    name="Repos",
    title="Repos  ·  Git folders",
    description="Git folders in the workspace; they map to Fabric Git integration.",
    columns=[
        Column("Path", "path", 50),
        Column("Repo id", "repo_id", 14),
        Column("URL", "url", 56),
        Column("Provider", "provider", 20),
        Column("Branch", "branch", 16),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.repos,
    readiness_column="Readiness",
)
