"""Declarative sheet specs: every data sheet is a list of columns over a row source."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Column", "SheetSpec", "Value"]

Value = str | int | float | bool | None


@dataclass(frozen=True)
class Column:
    """One worksheet column.

    ``value`` is an attribute name on the row model or a function ``(row, report) -> value``.
    ``formula`` (optional) is a template with ``{r}`` for the row number; it wins over value.
    """

    header: str
    value: str | Callable[[Any, Any], Value] = ""
    width: float = 14
    numeric: bool = False
    number_format: str | None = None
    formula: str | None = None
    note: str | None = None
    wrap: bool = False


@dataclass(frozen=True)
class SheetSpec:
    """A data sheet: rows 1-5 branding band, header in row 6, data from row 7."""

    name: str
    title: str
    description: str
    columns: Sequence[Column]
    rows: Callable[[Any], Sequence[Any]]  # report -> rows (DiscoveryReport or AssessmentResult)
    readiness_column: str | None = None  # header of a Readiness column to colour
    tab_colour: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def numeric_columns(self) -> tuple[str, ...]:
        """Headers of right-aligned numeric columns (the NUMERIC_COLUMNS contract)."""
        return tuple(c.header for c in self.columns if c.numeric)
