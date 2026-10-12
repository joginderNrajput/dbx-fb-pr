"""Workbook engine: data-sheet rendering and the fixed sheet order.

``SHEET_ORDER`` is declared once here; tests assert the written file matches it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import column_index_from_string
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from dbx_premig.config import Settings
from dbx_premig.excel import theme
from dbx_premig.excel.layout import (
    DATA_START_ROW,
    HEADER_ROW,
    back_link,
    branding_band,
    set_widths,
)
from dbx_premig.excel.sheets.analytics import (
    ALERTS,
    DASHBOARDS,
    EXPERIMENTS,
    MODELS,
    SERVING_ENDPOINTS,
    SQL_QUERIES,
)
from dbx_premig.excel.sheets.assessment import ASSETS, FINDINGS, WARNINGS
from dbx_premig.excel.sheets.code import DEPENDENCIES, NOTEBOOKS, REPOS
from dbx_premig.excel.sheets.compute import (
    CLUSTER_POLICIES,
    CLUSTERS,
    INSTANCE_POOLS,
    LIBRARIES,
    SQL_WAREHOUSES,
)
from dbx_premig.excel.sheets.data import (
    CATALOGS,
    COLUMNS,
    CONNECTIONS,
    EXTERNAL_LOCATIONS,
    FUNCTIONS,
    GRANTS,
    SCHEMAS,
    STORAGE_CREDENTIALS,
    TABLES,
    VIEWS,
    VOLUMES,
)
from dbx_premig.excel.sheets.orchestration import DLT_PIPELINES, JOB_TASKS, JOBS
from dbx_premig.excel.sheets.platform import IDENTITIES, MOUNTS, SECRET_SCOPES
from dbx_premig.excel.types import Column, SheetSpec, Value

__all__ = [
    "CHART_SHEETS",
    "DATA_SHEETS",
    "MAX_DATA_ROWS",
    "SHEET_ORDER",
    "column_letter",
    "spec_by_name",
    "write_data_sheet",
]

#: Data sheets, in workbook order (Discovery comes first, the reference sheets last).
DATA_SHEETS: tuple[SheetSpec, ...] = (
    ASSETS,
    FINDINGS,
    NOTEBOOKS,
    DEPENDENCIES,
    REPOS,
    JOBS,
    JOB_TASKS,
    DLT_PIPELINES,
    CLUSTERS,
    INSTANCE_POOLS,
    CLUSTER_POLICIES,
    SQL_WAREHOUSES,
    LIBRARIES,
    CATALOGS,
    SCHEMAS,
    TABLES,
    COLUMNS,
    VIEWS,
    VOLUMES,
    EXTERNAL_LOCATIONS,
    STORAGE_CREDENTIALS,
    CONNECTIONS,
    FUNCTIONS,
    GRANTS,
    SQL_QUERIES,
    DASHBOARDS,
    ALERTS,
    MODELS,
    SERVING_ENDPOINTS,
    EXPERIMENTS,
    SECRET_SCOPES,
    MOUNTS,
    IDENTITIES,
    WARNINGS,
)

CHART_SHEETS = ("ChartReadiness", "ChartAssetTypes", "ChartTopFindings")

SHEET_ORDER: tuple[str, ...] = (
    "Discovery",
    *(s.name for s in DATA_SHEETS),
    "Information",
    "Totals",
    *CHART_SHEETS,
)

#: Excel's row limit minus the branding band and header.
MAX_DATA_ROWS = 1_048_576 - DATA_START_ROW

_ILLEGAL = {c for c in range(32) if c not in (9, 10, 13)}
_ILLEGAL_TABLE = dict.fromkeys(_ILLEGAL)


def spec_by_name(name: str) -> SheetSpec:
    for spec in DATA_SHEETS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def column_letter(spec: SheetSpec, header: str) -> str:
    """Letter of the column with this header on a data sheet."""
    for i, col in enumerate(spec.columns, start=1):
        if col.header == header:
            return str(get_column_letter(i))
    raise KeyError(f"{spec.name} has no column {header!r}")


def _cell_value(col: Column, row: Any, report: Any) -> Value:
    if callable(col.value):
        return col.value(row, report)
    if not col.value:
        return None
    value: Value = getattr(row, col.value)
    return value


def _clean_text(text: str, limit: int) -> str:
    text = text.translate(_ILLEGAL_TABLE)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_data_sheet(
    ws: Worksheet, spec: SheetSpec, report: Any, settings: Settings, home: str = "Discovery"
) -> int:
    """Render one data sheet. Returns the number of data rows written."""
    columns = list(spec.columns)
    set_widths(ws, [c.width for c in columns])
    branding_band(ws, spec.title, len(columns))
    back_link(ws, spec.description, home)
    ws.row_dimensions[HEADER_ROW].height = 30

    for i, col in enumerate(columns, start=1):
        cell = ws.cell(row=HEADER_ROW, column=i, value=col.header)
        cell.font = theme.HEADER_FONT
        cell.fill = theme.HEADER_FILL
        cell.alignment = theme.HEADER_ALIGN
        if col.note:
            cell.comment = Comment(col.note, "Kanerika discovery", width=320, height=110)

    rows: Sequence[Any] = spec.rows(report)
    if len(rows) > MAX_DATA_ROWS:
        rows = rows[:MAX_DATA_ROWS]
    zebra = theme.fill(theme.ZEBRA)
    for offset, row in enumerate(rows):
        r = DATA_START_ROW + offset
        striped = offset % 2 == 1
        for i, col in enumerate(columns, start=1):
            is_formula = bool(col.formula)
            value: Value = col.formula.format(r=r) if col.formula else _cell_value(col, row, report)
            if isinstance(value, bool):
                value = "Yes" if value else "No"
            if isinstance(value, str) and not is_formula:
                value = _clean_text(value, settings.max_cell_chars)
            cell = ws.cell(row=r, column=i, value=value)
            if isinstance(value, str) and value.startswith("=") and not is_formula:
                cell.data_type = "s"  # client text is never a formula
            cell.font = theme.BODY_FONT
            if striped:
                cell.fill = zebra
            if col.numeric:
                cell.alignment = theme.RIGHT
                if col.number_format:
                    cell.number_format = col.number_format
            elif col.wrap:
                cell.alignment = theme.WRAP

    last_col = get_column_letter(len(columns))
    last_row = max(DATA_START_ROW, DATA_START_ROW + len(rows) - 1)
    ws.freeze_panes = f"A{DATA_START_ROW}"
    ws.auto_filter.ref = f"A{HEADER_ROW}:{last_col}{last_row}"
    if spec.readiness_column and rows:
        letter = column_letter(spec, spec.readiness_column)
        rng = f"{letter}{DATA_START_ROW}:{letter}{last_row}"
        for level, (bg, fg) in theme.READINESS_COLOURS.items():
            ws.conditional_formatting.add(
                rng,
                CellIsRule(
                    operator="equal",
                    formula=[f'"{level}"'],
                    fill=PatternFill("solid", bgColor=bg),
                    font=Font(color=fg, bold=True),
                ),
            )
    if spec.tab_colour:
        ws.sheet_properties.tabColor = spec.tab_colour
    return len(rows)


def order_sheets(wb: Workbook, order: Sequence[str] = SHEET_ORDER) -> None:
    """Put the sheets in ``order`` (anything unexpected goes last)."""
    rank = {name: i for i, name in enumerate(order)}
    wb._sheets.sort(key=lambda ws: rank.get(ws.title, len(rank)))


def col_index(letter: str) -> int:
    return int(column_index_from_string(letter))
