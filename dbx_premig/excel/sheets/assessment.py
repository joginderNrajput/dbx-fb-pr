"""Readiness views: Assets (one row per assessable object), Findings, Warnings."""

from __future__ import annotations

from collections.abc import Sequence

from dbx_premig.excel.sheets.common import READINESS_NOTE
from dbx_premig.excel.types import Column, SheetSpec
from dbx_premig.models import DiscoveryReport

__all__ = ["ASSETS", "FINDINGS", "WARNINGS", "FindingRow"]

N = "#,##0"


class FindingRow:
    """A finding flattened with its asset (rendering only)."""

    __slots__ = (
        "asset",
        "asset_type",
        "category",
        "guidance",
        "occurrences",
        "penalty",
        "rule",
        "support",
    )

    def __init__(self, **kw: object) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def _finding_rows(report: DiscoveryReport) -> Sequence[FindingRow]:
    rows = [
        FindingRow(
            asset_type=a.asset_type,
            asset=a.location or a.name if a.asset_type == "Notebook" else a.name,
            rule=f.feature_id,
            category=f.category,
            occurrences=f.occurrences,
            penalty=f.penalty,
            support=f.support,
            guidance=f.guidance,
        )
        for a in report.assessments
        for f in a.findings
    ]
    return rows


ASSETS = SheetSpec(
    name="Assets",
    title="Assets  ·  Fabric readiness of every object",
    description=(
        "One row per assessable object across all sheets: its Fabric target and readiness. "
        "Totals and the dashboard count from here."
    ),
    columns=[
        Column("Asset type", "asset_type", 18),
        Column("Name", "name", 40),
        Column("Location / id", "location", 48),
        Column("Fabric target", "fabric_target", 40),
        Column(
            "Findings",
            lambda a, _r: len(a.findings),
            9,
            numeric=True,
            number_format=N,
        ),
        Column("Finding ids", lambda a, _r: a.finding_ids, 50),
        Column(
            "Readiness score",
            "readiness_score",
            11,
            numeric=True,
            number_format="0",
            note=READINESS_NOTE,
        ),
        Column("Readiness", "readiness", 13),
    ],
    rows=lambda r: r.assessments,
    readiness_column="Readiness",
)

FINDINGS = SheetSpec(
    name="Findings",
    title="Findings  ·  Databricks features that need work in Fabric",
    description=(
        "One row per feature found on an asset, with the catalog's support verdict and what "
        "to do in Fabric. Filter by Rule to see every asset a feature touches."
    ),
    columns=[
        Column("Asset type", "asset_type", 18),
        Column("Asset", "asset", 44),
        Column("Rule", "rule", 20),
        Column("Category", "category", 18),
        Column("Occurrences", "occurrences", 12, numeric=True, number_format=N),
        Column("Penalty", "penalty", 9, numeric=True, number_format=N),
        Column("Fabric support", "support", 14),
        Column("What to do in Fabric", "guidance", 90),
    ],
    rows=_finding_rows,
)

WARNINGS = SheetSpec(
    name="Warnings",
    title="Warnings  ·  what discovery could not do",
    description=(
        "Endpoints that were not readable (permissions, feature not enabled), files that "
        "could not be parsed, and anything skipped. Read this one."
    ),
    columns=[
        Column("Source", "source", 30),
        Column(
            "#",
            formula="=COUNTIF($A$7:$A{r},$A{r})",
            width=6,
            numeric=True,
            note="Running number of the warning within its source",
        ),
        Column("Message", "message", 120),
    ],
    rows=lambda r: r.estate.warnings,
)
