"""Per-asset readiness: a documented, rule-based classification.

``readiness_score = max(0, 100 - sum(penalty x weight(occurrences)))`` where a feature seen
``n`` times weighs ``1 + 0.1 x (min(n, occurrence_cap) - 1)``. Then, first match wins:

1. any finding whose catalog verdict is ``unsupported``  -> **Unsupported**
2. score >= ``readiness_compatible_min`` (80)             -> **Compatible**
3. score >= ``readiness_partial_min`` (50)                -> **Partial**
4. otherwise                                              -> **Manual**

This is a heuristic of this tool (the thresholds are settings), not an industry standard.
"""

from __future__ import annotations

from collections.abc import Iterable

from dbx_premig.catalog.loader import Catalog
from dbx_premig.config import Settings
from dbx_premig.models import AssetAssessment, AssetRecord, Finding, WarningRow

__all__ = ["READINESS_LEVELS", "assess_assets", "classify", "weighted_penalty"]

READINESS_LEVELS = ("Compatible", "Partial", "Manual", "Unsupported")


def weighted_penalty(penalty: int, occurrences: int, cap: int) -> float:
    return penalty * (1 + 0.1 * (min(max(occurrences, 1), cap) - 1))


def classify(score: int, findings: Iterable[Finding], settings: Settings) -> str:
    if any(f.support == "unsupported" for f in findings):
        return "Unsupported"
    if score >= settings.readiness_compatible_min:
        return "Compatible"
    if score >= settings.readiness_partial_min:
        return "Partial"
    return "Manual"


def assess_assets(
    assets: Iterable[AssetRecord], catalog: Catalog, settings: Settings
) -> tuple[tuple[AssetAssessment, ...], tuple[WarningRow, ...]]:
    """Assessment per asset plus a warning for each feature id missing from the catalog."""
    out: list[AssetAssessment] = []
    unknown: set[str] = set()
    for asset in assets:
        findings: list[Finding] = []
        total = 0.0
        for hit in asset.features:
            entry = catalog.feature(hit.feature_id)
            if entry.support == "unknown":
                unknown.add(hit.feature_id)
            findings.append(
                Finding(
                    feature_id=entry.id,
                    category=entry.category,
                    occurrences=hit.occurrences,
                    penalty=entry.penalty,
                    support=entry.support,
                    guidance=entry.guidance,
                )
            )
            total += weighted_penalty(entry.penalty, hit.occurrences, settings.occurrence_cap)
        score = max(0, 100 - int(total + 0.5))
        out.append(
            AssetAssessment(
                key=asset.key,
                asset_type=asset.asset_type,
                name=asset.name,
                location=asset.location,
                fabric_target=catalog.target_for(asset.asset_type),
                readiness_score=score,
                readiness=classify(score, findings, settings),
                findings=tuple(findings),
            )
        )
    warnings = tuple(
        WarningRow(
            source="support catalog",
            message=f"Feature {fid} is not in the support catalog; classified as unknown.",
        )
        for fid in sorted(unknown)
    )
    return tuple(out), warnings
