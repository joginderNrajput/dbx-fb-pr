"""Load and validate the assessment rules file (``data/assessment_rules.yaml`` by default).

Every expression is parsed at load time and checked against the variables available at its
stage, so a typo fails here (exit code 5) and never half-way through an assessment.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dbx_premig.errors import RulesError
from dbx_premig.estimation.formula import Formula, FormulaError
from dbx_premig.resources import rules_path

__all__ = [
    "ASSET_VARIABLES",
    "AUTOMATION_LEVELS",
    "COMPLEXITY_LEVELS",
    "AssessmentRules",
    "load_rules",
]

COMPLEXITY_LEVELS = ("Simple", "Medium", "Complex")
AUTOMATION_LEVELS = ("Fully automated", "Partially automated", "Manual")
SUPPORT_LEVELS = ("supported", "partial", "manual", "unsupported", "unknown")

ASSET_VARIABLES = frozenset(
    {
        "asset_type", "name", "readiness", "readiness_score", "findings", "occurrences",
        "penalty_total", "manual_findings", "unsupported_findings", "total_constructs",
        "supported_constructs", "unsupported_constructs", "unsupported_ratio", "lines",
        "cells", "notebook_calls", "sql_statements", "magic_commands", "size_bytes", "tasks",
        "columns", "definition_chars", "libraries",
    }
)  # fmt: skip
_STAGE_SIZE = ASSET_VARIABLES
_STAGE_SCORE = _STAGE_SIZE | {"size_points"}
_STAGE_LEVEL = _STAGE_SCORE | {"score"}
_STAGE_AUTOMATION = _STAGE_LEVEL | {"level"}
_STAGE_HOURS = _STAGE_AUTOMATION | {"automation_level", "base_hours", "dev_factor", "test_factor"}
_STAGE_MANUAL_DEV = _STAGE_HOURS | {"size_hours"}
_STAGE_MANUAL_TEST = _STAGE_MANUAL_DEV | {"manual_dev_hours"}
_STAGE_AUTO = _STAGE_MANUAL_TEST | {"manual_test_hours"}


@dataclass(frozen=True)
class AssessmentRules:
    version: int
    source_name: str
    sha256: str
    text: str
    base_constructs: float
    support_weights: dict[str, float]
    size_points: dict[str, Formula]
    score: Formula
    complexity_levels: tuple[tuple[str, Formula], ...]
    automation_levels: tuple[tuple[str, Formula], ...]
    base_hours: dict[str, dict[str, float]]
    size_hours: dict[str, Formula]
    automation_factors: dict[str, tuple[float, float]]
    manual_dev_hours: Formula
    manual_test_hours: Formula
    automation_dev_hours: Formula
    automation_test_hours: Formula
    hours_decimal_places: int

    @property
    def label(self) -> str:
        """Short identifier stored with every assessment: name, version and hash prefix."""
        return f"{self.source_name} v{self.version} ({self.sha256[:12]})"


def _req(data: dict[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise RulesError(f"Assessment rules: '{where}{key}' is missing.")
    return data[key]


def _formula(source: Any, known: frozenset[str], where: str) -> Formula:
    try:
        return Formula.parse(source, known)
    except FormulaError as exc:
        raise RulesError(f"Assessment rules: {where} is invalid ({exc}).") from exc


def _by_type(raw: Any, known: frozenset[str], where: str) -> dict[str, Formula]:
    if not isinstance(raw, dict) or "default" not in raw:
        raise RulesError(f"Assessment rules: {where} needs a mapping with a 'default' entry.")
    return {str(k): _formula(v, known, f"{where}.{k}") for k, v in raw.items()}


def _levels(raw: Any, expected: tuple[str, ...], known: frozenset[str], where: str
            ) -> tuple[tuple[str, Formula], ...]:  # fmt: skip
    if not isinstance(raw, list):
        raise RulesError(f"Assessment rules: {where} must be a list of {{level, when}}.")
    out: list[tuple[str, Formula]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "level" not in item or "when" not in item:
            raise RulesError(f"Assessment rules: {where}[{i}] needs 'level' and 'when'.")
        out.append((str(item["level"]), _formula(item["when"], known, f"{where}[{i}].when")))
    names = sorted(level for level, _ in out)
    if names != sorted(expected) or len(out) != len(expected):
        raise RulesError(
            f"Assessment rules: {where} must define exactly the levels {', '.join(expected)}."
        )
    return tuple(out)


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise RulesError(f"Assessment rules: {where} must be a non-negative number.")
    return float(value)


def parse_rules(text: str, source_name: str) -> AssessmentRules:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesError(f"Assessment rules file {source_name} is not valid YAML.") from exc
    if not isinstance(data, dict):
        raise RulesError(f"Assessment rules file {source_name} must hold a mapping.")
    version = _req(data, "version", "")
    if version != 1:
        raise RulesError(f"Assessment rules file {source_name}: version must be 1.")

    weights_raw = _req(data, "support_weights", "")
    if not isinstance(weights_raw, dict) or set(weights_raw) != set(SUPPORT_LEVELS):
        raise RulesError(
            f"Assessment rules: support_weights must give exactly {', '.join(SUPPORT_LEVELS)}."
        )
    weights = {k: _number(v, f"support_weights.{k}") for k, v in weights_raw.items()}
    if any(w > 1 for w in weights.values()):
        raise RulesError("Assessment rules: support_weights must be between 0 and 1.")

    cx = _req(data, "complexity", "")
    eff = _req(data, "effort", "")
    if not isinstance(cx, dict) or not isinstance(eff, dict):
        raise RulesError("Assessment rules: 'complexity' and 'effort' must be mappings.")

    base_raw = _req(eff, "base_hours", "effort.")
    if not isinstance(base_raw, dict) or "default" not in base_raw:
        raise RulesError("Assessment rules: effort.base_hours needs a 'default' entry.")
    base_hours: dict[str, dict[str, float]] = {}
    for asset_type, row in base_raw.items():
        if not isinstance(row, dict) or set(row) != set(COMPLEXITY_LEVELS):
            raise RulesError(
                f"Assessment rules: effort.base_hours.{asset_type} must give "
                f"{', '.join(COMPLEXITY_LEVELS)}."
            )
        base_hours[str(asset_type)] = {
            k: _number(v, f"effort.base_hours.{asset_type}.{k}") for k, v in row.items()
        }

    factors_raw = _req(eff, "automation_factors", "effort.")
    if not isinstance(factors_raw, dict) or set(factors_raw) != set(AUTOMATION_LEVELS):
        raise RulesError(
            f"Assessment rules: effort.automation_factors must give {', '.join(AUTOMATION_LEVELS)}."
        )
    factors: dict[str, tuple[float, float]] = {}
    for level, f in factors_raw.items():
        if not isinstance(f, dict) or set(f) != {"dev", "test"}:
            raise RulesError(f"Assessment rules: automation_factors.{level} needs dev and test.")
        factors[level] = (
            _number(f["dev"], f"automation_factors.{level}.dev"),
            _number(f["test"], f"automation_factors.{level}.test"),
        )

    places = data.get("hours_decimal_places", 2)
    if not isinstance(places, int) or not 0 <= places <= 6:
        raise RulesError("Assessment rules: hours_decimal_places must be 0-6.")

    return AssessmentRules(
        version=int(version),
        source_name=source_name,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        base_constructs=_number(data.get("base_constructs", 1), "base_constructs"),
        support_weights=weights,
        size_points=_by_type(_req(cx, "size_points", "complexity."), _STAGE_SIZE,
                             "complexity.size_points"),
        score=_formula(_req(cx, "score", "complexity."), _STAGE_SCORE, "complexity.score"),
        complexity_levels=_levels(_req(cx, "levels", "complexity."), COMPLEXITY_LEVELS,
                                  _STAGE_LEVEL, "complexity.levels"),
        automation_levels=_levels(_req(data, "automation", ""), AUTOMATION_LEVELS,
                                  _STAGE_AUTOMATION, "automation"),
        base_hours=base_hours,
        size_hours=_by_type(_req(eff, "size_hours", "effort."), _STAGE_HOURS,
                            "effort.size_hours"),
        automation_factors=factors,
        manual_dev_hours=_formula(_req(eff, "manual_dev_hours", "effort."), _STAGE_MANUAL_DEV,
                                  "effort.manual_dev_hours"),
        manual_test_hours=_formula(_req(eff, "manual_test_hours", "effort."),
                                   _STAGE_MANUAL_TEST, "effort.manual_test_hours"),
        automation_dev_hours=_formula(_req(eff, "automation_dev_hours", "effort."), _STAGE_AUTO,
                                      "effort.automation_dev_hours"),
        automation_test_hours=_formula(_req(eff, "automation_test_hours", "effort."),
                                       _STAGE_AUTO, "effort.automation_test_hours"),
        hours_decimal_places=places,
    )  # fmt: skip


def load_rules(path: Path | None = None) -> AssessmentRules:
    """The rules file at ``path``, or the bundled default."""
    target = path or rules_path()
    try:
        text = target.read_text("utf-8")
    except OSError as exc:
        raise RulesError(f"Cannot read the assessment rules file {target.name}.") from exc
    return parse_rules(text, target.name)
