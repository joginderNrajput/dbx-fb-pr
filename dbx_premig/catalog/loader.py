"""Load and validate the Databricks -> Fabric support catalog (``data/features.yaml``)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError, field_validator

from dbx_premig.errors import CatalogError
from dbx_premig.resources import catalog_path

__all__ = [
    "SUPPORT_LEVELS",
    "Catalog",
    "CodePattern",
    "FeatureEntry",
    "TaskType",
    "load_catalog",
]

SUPPORT_LEVELS = ("supported", "partial", "manual", "unsupported", "unknown")
_REGEX_FLAGS = re.IGNORECASE | re.MULTILINE


class FeatureEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: str
    applies: str
    pattern: str | None = None
    penalty: int
    support: str
    guidance: str

    @field_validator("support")
    @classmethod
    def _support_level(cls, value: str) -> str:
        if value not in SUPPORT_LEVELS[:-1]:
            raise ValueError(f"support must be one of {', '.join(SUPPORT_LEVELS[:-1])}")
        return value

    @field_validator("applies")
    @classmethod
    def _applies(cls, value: str) -> str:
        if value not in {"code", "structural"}:
            raise ValueError("applies must be code or structural")
        return value


class TaskType(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    activity: str
    feature: str | None = None


class CodePattern(BaseModel):
    """A compiled code-scan rule handed to the parser."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    feature_id: str
    regex: re.Pattern[str]


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    asset_targets: dict[str, str]
    job_task_types: dict[str, TaskType]
    features: tuple[FeatureEntry, ...]

    _by_id: dict[str, FeatureEntry] = PrivateAttr(default_factory=dict)

    def feature(self, feature_id: str) -> FeatureEntry:
        """Entry for an id; an unknown id gets a synthetic ``unknown`` entry (never dropped)."""
        if not self._by_id:
            self._by_id.update({e.id: e for e in self.features})
        entry = self._by_id.get(feature_id)
        if entry is not None:
            return entry
        # model_construct: "unknown" is deliberately outside the validated verdicts.
        return FeatureEntry.model_construct(
            id=feature_id,
            category="unknown",
            applies="structural",
            penalty=0,
            support="unknown",
            guidance="Not in the support catalog; review manually and add it to features.yaml",
        )

    def is_known(self, feature_id: str) -> bool:
        return self.feature(feature_id).support != "unknown"

    def code_patterns(self) -> tuple[CodePattern, ...]:
        return tuple(
            CodePattern(feature_id=e.id, regex=re.compile(e.pattern, _REGEX_FLAGS))
            for e in self.features
            if e.applies == "code" and e.pattern
        )

    def target_for(self, asset_type: str) -> str:
        return self.asset_targets.get(asset_type, "Review manually")


def _validate(data: Any, name: str) -> Catalog:
    try:
        catalog = Catalog.model_validate(data)
    except ValidationError as exc:
        raise CatalogError(f"The support catalog {name} is invalid.", detail=str(exc)) from exc
    ids = [e.id for e in catalog.features]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise CatalogError(f"The support catalog {name} repeats ids: {', '.join(duplicates)}.")
    for entry in catalog.features:
        if entry.applies == "code":
            if not entry.pattern:
                raise CatalogError(f"Catalog entry {entry.id} applies to code but has no pattern.")
            try:
                re.compile(entry.pattern, _REGEX_FLAGS)
            except re.error as exc:
                raise CatalogError(f"Catalog entry {entry.id} has an invalid pattern.") from exc
    for task, spec in catalog.job_task_types.items():
        if spec.feature and spec.feature not in ids:
            raise CatalogError(f"Job task type {task} names unknown feature {spec.feature}.")
    return catalog


def load_catalog_file(path: Path) -> Catalog:
    try:
        data = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"Cannot read the support catalog {path.name}.") from exc
    return _validate(data, path.name)


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    """The bundled catalog (cached)."""
    return load_catalog_file(catalog_path("features.yaml"))
