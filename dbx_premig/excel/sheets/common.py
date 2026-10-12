"""Column helpers shared by the data sheets."""

from __future__ import annotations

from typing import Any

from dbx_premig.excel.types import Column, Value
from dbx_premig.models import DiscoveryReport

__all__ = ["READINESS_NOTE", "assessed_columns", "yes_no"]

READINESS_NOTE = (
    "Readiness = 100 minus the catalog penalty of each finding. Compatible >= 80, "
    "Partial >= 50, Manual < 50; Unsupported = a finding with no Fabric equivalent. "
    "A heuristic of this tool, tunable in features.yaml and the settings."
)


def yes_no(attr: str) -> Any:
    def get(row: Any, _report: DiscoveryReport) -> Value:
        return "Yes" if getattr(row, attr) else "No"

    return get


def _assessed(field: str) -> Any:
    def get(row: Any, report: DiscoveryReport) -> Value:
        a = report.assessment_for(row.asset_key)
        if a is None:
            return None
        if field == "findings":
            return a.finding_ids
        value: Value = getattr(a, field)
        return value

    return get


def assessed_columns() -> list[Column]:
    """Fabric target, Readiness score, Readiness, Findings: from the asset's assessment."""
    return [
        Column("Fabric target", _assessed("fabric_target"), 34),
        Column(
            "Readiness score",
            _assessed("readiness_score"),
            11,
            numeric=True,
            number_format="0",
            note=READINESS_NOTE,
        ),
        Column("Readiness", _assessed("readiness"), 13),
        Column(
            "Findings", _assessed("findings"), 48, note="Rule ids; details on the Findings sheet"
        ),
    ]
