"""The assessment: complexity, automation level and hours per asset, from the rules file.

Order of evaluation per asset (each stage sees the results of the earlier ones)::

    size_points -> score -> level -> automation_level -> base_hours / size_hours /
    dev_factor / test_factor -> manual_dev_hours -> manual_test_hours ->
    automation_dev_hours -> automation_test_hours

Hours are rounded half-up per asset (``hours_decimal_places``); the portfolio computation
sums the rounded figures, so the Excel Summary and the database agree with a calculator.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from dbx_premig.errors import RulesError
from dbx_premig.estimation.complexity import weighted_penalty
from dbx_premig.estimation.formula import FormulaError, Value
from dbx_premig.estimation.rounding import round_hours
from dbx_premig.estimation.rules import AssessmentRules
from dbx_premig.models import (
    AssessmentResult,
    AssetInput,
    Computation,
    DiscoveryWorkbook,
    EstimationRow,
)

__all__ = ["assess_workbook", "asset_variables", "compute_portfolio", "estimate_asset"]

_METRICS = (
    "lines", "cells", "notebook_calls", "sql_statements", "magic_commands", "size_bytes",
    "tasks", "columns", "definition_chars", "libraries",
)  # fmt: skip


def asset_variables(asset: AssetInput, rules: AssessmentRules, cap: int = 10) -> dict[str, Value]:
    """The variables an expression sees for one asset."""
    weights = rules.support_weights
    supported = rules.base_constructs + sum(weights.get(f.support, 0.0) for f in asset.findings)
    total = rules.base_constructs + len(asset.findings)
    unsupported = total - supported
    env: dict[str, Value] = {
        "asset_type": asset.asset_type,
        "name": asset.name,
        "readiness": asset.readiness,
        "readiness_score": asset.readiness_score,
        "findings": len(asset.findings),
        "occurrences": sum(f.occurrences for f in asset.findings),
        "penalty_total": sum(
            weighted_penalty(f.penalty, f.occurrences, cap) for f in asset.findings
        ),
        "manual_findings": sum(1 for f in asset.findings if f.support == "manual"),
        "unsupported_findings": sum(1 for f in asset.findings if f.support == "unsupported"),
        "total_constructs": total,
        "supported_constructs": supported,
        "unsupported_constructs": unsupported,
        "unsupported_ratio": unsupported / total if total else 0.0,
    }
    for metric in _METRICS:
        env[metric] = float(asset.metrics.get(metric, 0.0))
    return env


def _first(levels: tuple[tuple[str, object], ...], env: dict[str, Value], where: str) -> str:
    for level, formula in levels:
        if formula.truth(env):  # type: ignore[attr-defined]
            return level
    raise RulesError(f"Assessment rules: no {where} level matched; end the list with 'true'.")


def estimate_asset(asset: AssetInput, rules: AssessmentRules, cap: int = 10) -> EstimationRow:
    env = asset_variables(asset, rules, cap)
    by_type = asset.asset_type
    try:
        size = rules.size_points.get(by_type, rules.size_points["default"])
        env["size_points"] = size.number(env)
        env["score"] = max(0.0, min(100.0, rules.score.number(env)))
        level = _first(rules.complexity_levels, env, "complexity")
        env["level"] = level
        automation = _first(rules.automation_levels, env, "automation")
        env["automation_level"] = automation
        env["base_hours"] = rules.base_hours.get(by_type, rules.base_hours["default"])[level]
        env["dev_factor"], env["test_factor"] = rules.automation_factors[automation]
        size_hours = rules.size_hours.get(by_type, rules.size_hours["default"])
        env["size_hours"] = size_hours.number(env)
        env["manual_dev_hours"] = rules.manual_dev_hours.number(env)
        env["manual_test_hours"] = rules.manual_test_hours.number(env)
        auto_dev = rules.automation_dev_hours.number(env)
        auto_test = rules.automation_test_hours.number(env)
    except FormulaError as exc:
        raise RulesError(
            f"Assessment rules failed on {asset.asset_type} '{asset.name}': {exc}."
        ) from exc
    places = rules.hours_decimal_places

    def r(x: object) -> float:
        return round_hours(max(0.0, float(x)), places)  # type: ignore[arg-type]

    mdev, mtest = r(env["manual_dev_hours"]), r(env["manual_test_hours"])
    adev, atest = r(auto_dev), r(auto_test)
    return EstimationRow(
        asset_key=asset.key,
        asset_type=asset.asset_type,
        asset_name=asset.name,
        location=asset.location,
        fabric_target=asset.fabric_target,
        readiness=asset.readiness,
        readiness_score=asset.readiness_score,
        total_constructs=int(round_hours(float(env["total_constructs"]), 0)),
        supported=round(float(env["supported_constructs"]), 6),
        unsupported=round(float(env["unsupported_constructs"]), 6),
        complexity_score=int(round_hours(float(env["score"]), 0)),
        complexity_level=level,
        automation_level=automation,
        manual_dev_hours=mdev,
        manual_test_hours=mtest,
        automation_dev_hours=adev,
        automation_test_hours=atest,
        hours_saved=round_hours(max(0.0, (mdev + mtest) - (adev + atest)), places),
    )


def compute_portfolio(
    rows: tuple[EstimationRow, ...], rules: AssessmentRules, generated_at: datetime
) -> Computation:
    places = rules.hours_decimal_places
    levels = Counter(r.complexity_level for r in rows)
    autos = Counter(r.automation_level for r in rows)

    def total(attr: str) -> float:
        return round_hours(sum(getattr(r, attr) for r in rows), places)

    mdev, mtest = total("manual_dev_hours"), total("manual_test_hours")
    adev, atest = total("automation_dev_hours"), total("automation_test_hours")
    manual_total = round_hours(mdev + mtest, places)
    auto_total = round_hours(adev + atest, places)
    saved = total("hours_saved")
    return Computation(
        assessment_generated_at=generated_at.replace(microsecond=0).isoformat(),
        total_assets=len(rows),
        total_constructs=sum(r.total_constructs for r in rows),
        supported_constructs=round(sum(r.supported for r in rows), 6),
        unsupported_constructs=round(sum(r.unsupported for r in rows), 6),
        simple_count=levels.get("Simple", 0),
        medium_count=levels.get("Medium", 0),
        complex_count=levels.get("Complex", 0),
        fully_automated=autos.get("Fully automated", 0),
        partially_automated=autos.get("Partially automated", 0),
        manual=autos.get("Manual", 0),
        manual_dev_hours=mdev,
        manual_test_hours=mtest,
        total_manual_hours=manual_total,
        automation_dev_hours=adev,
        automation_test_hours=atest,
        total_automation_hours=auto_total,
        hours_saved=saved,
        saving_pct=round(saved / manual_total, 6) if manual_total else 0.0,
        rules_version=rules.label,
    )


def assess_workbook(
    workbook: DiscoveryWorkbook,
    rules: AssessmentRules,
    *,
    occurrence_cap: int = 10,
    generated_at: datetime | None = None,
) -> AssessmentResult:
    """Assess every asset of a discovery workbook. Pure and deterministic for a given clock."""
    rows = tuple(estimate_asset(a, rules, occurrence_cap) for a in workbook.assets)
    when = generated_at or datetime.now(UTC)
    return AssessmentResult(
        discovery=workbook,
        estimations=rows,
        computation=compute_portfolio(rows, rules, when),
    )
