"""Portfolio roll-up used by the CLI summary line and the tests.

The workbook does NOT use these numbers: its Totals sheet recomputes everything with live
formulas from the data sheets. A test asserts the two agree.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from dbx_premig.models import DiscoveryReport

__all__ = ["PortfolioSummary", "summarise"]


class PortfolioSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_assets: int
    by_readiness: dict[str, int]
    by_type: dict[str, int]
    average_readiness: float
    findings: int
    top_findings: tuple[tuple[str, int], ...]
    warnings: int


def summarise(report: DiscoveryReport) -> PortfolioSummary:
    assessments = report.assessments
    by_type = Counter(a.asset_type for a in assessments)
    by_ready = Counter(a.readiness for a in assessments)
    finding_assets: Counter[str] = Counter()
    for a in assessments:
        for f in a.findings:
            finding_assets[f.feature_id] += 1
    avg = sum(a.readiness_score for a in assessments) / len(assessments) if assessments else 0.0
    top = tuple(sorted(finding_assets.items(), key=lambda kv: (-kv[1], kv[0]))[:10])
    return PortfolioSummary(
        total_assets=len(assessments),
        by_readiness={
            k: by_ready.get(k, 0) for k in ("Compatible", "Partial", "Manual", "Unsupported")
        },
        by_type=dict(sorted(by_type.items())),
        average_readiness=round(avg, 1),
        findings=sum(len(a.findings) for a in assessments),
        top_findings=top,
        warnings=len(report.estate.warnings),
    )
