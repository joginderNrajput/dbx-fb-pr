"""The Discovery sheet: navigation, KPI tiles, scan summary and charts.

Every number is a ``='Totals'!$B$n`` formula; nothing here is a literal copy of a value.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from dbx_premig.excel import theme
from dbx_premig.excel.charts import add_dashboard_charts
from dbx_premig.excel.layout import branding_band, nav_link
from dbx_premig.excel.sheets.totals import TotalsRefs
from dbx_premig.excel.writer import CHART_SHEETS, SHEET_ORDER
from dbx_premig.models import DiscoveryReport
from dbx_premig.version import APP_NAME, APP_VERSION

__all__ = ["TILES", "TITLE", "write_dashboard"]

TITLE = "DATABRICKS DISCOVERY  ·  WHAT THE WORKSPACE CONTAINS"

_NAV_LABELS = {
    "JobTasks": "Job Tasks",
    "DLTPipelines": "DLT Pipelines",
    "InstancePools": "Instance Pools",
    "ClusterPolicies": "Cluster Policies",
    "SQLWarehouses": "SQL Warehouses",
    "ExternalLocations": "External Locations",
    "StorageCredentials": "Storage Credentials",
    "SQLQueries": "SQL Queries",
    "ServingEndpoints": "Serving Endpoints",
    "SecretScopes": "Secret Scopes",
}

#: Four rows of four tiles: (Totals key, label). The last row is the risk row (red).
TILES: tuple[tuple[tuple[str, str], ...], ...] = (
    (
        ("notebooks", "NOTEBOOKS & CODE FILES"),
        ("jobs", "JOBS"),
        ("pipelines", "DLT PIPELINES"),
        ("clusters", "ALL-PURPOSE CLUSTERS"),
    ),
    (("catalogs", "CATALOGS"), ("schemas", "SCHEMAS"), ("tables", "TABLES"), ("views", "VIEWS")),
    (
        ("warehouses", "SQL WAREHOUSES"),
        ("queries", "SQL QUERIES"),
        ("dashboards", "DASHBOARDS"),
        ("models", "ML MODELS"),
    ),
    (
        ("manual", "MANUAL-REDESIGN ASSETS"),
        ("unsupported", "UNSUPPORTED ASSETS"),
        ("unresolved", "UNRESOLVED DEPENDENCIES"),
        ("warnings", "DISCOVERY WARNINGS"),
    ),
)

_TILE_COLS = (8, 17, 26, 35)  # H, Q, Z, AI; each tile is 8 columns wide
_TILE_ROWS = (7, 12, 17, 22)
_SUMMARY_LABEL_COL = 44  # AR
_SUMMARY_VALUE_COL = 54  # BB
_LAST_COL = 62  # BJ


def _merge(ws: Worksheet, r1: int, c1: int, r2: int, c2: int) -> None:
    ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def _tile(ws: Worksheet, row: int, col: int, ref: str, label: str, risk: bool) -> None:
    bg = theme.RED_TINT if risk else theme.GREEN_TINT
    accent = theme.RED if risk else theme.GREEN
    value = ws.cell(row=row, column=col, value=f"={ref}")
    value.font = theme.font(theme.RED if risk else theme.INK, 24, True, theme.DISPLAY_FONT)
    value.alignment = Alignment(horizontal="center", vertical="bottom")
    value.number_format = "#,##0"
    lab = ws.cell(row=row + 2, column=col, value=label)
    lab.font = theme.font(theme.SLATE, 8, True)
    lab.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
    bottom = Border(bottom=Side(style="medium", color=accent))
    for r in range(row, row + 4):
        for c in range(col, col + 8):
            cell = ws.cell(row=r, column=c)
            cell.fill = theme.fill(bg)
            if r == row + 3:
                cell.border = bottom
    _merge(ws, row, col, row + 1, col + 7)
    _merge(ws, row + 2, col, row + 3, col + 7)


def _summary_row(
    ws: Worksheet, row: int, label: str, value: object, striped: bool, colour: str = theme.INK
) -> None:
    bg = theme.fill(theme.ZEBRA if striped else theme.WHITE)
    a = ws.cell(row=row, column=_SUMMARY_LABEL_COL, value=label)
    b = ws.cell(row=row, column=_SUMMARY_VALUE_COL, value=value)
    a.font = theme.font(theme.INK, 9)
    b.font = theme.font(colour, 9, True)
    a.alignment = theme.LEFT
    b.alignment = Alignment(horizontal="right", vertical="center", shrink_to_fit=True)
    if isinstance(value, str) and value.startswith("='Totals'"):
        b.number_format = "#,##0.0" if "avg" in label.lower() else "#,##0"
    for c in range(_SUMMARY_LABEL_COL, _LAST_COL + 1):
        ws.cell(row=row, column=c).fill = bg
    _merge(ws, row, _SUMMARY_LABEL_COL, row, _SUMMARY_VALUE_COL - 1)
    _merge(ws, row, _SUMMARY_VALUE_COL, row, _LAST_COL)
    if isinstance(value, str) and not value.startswith("="):
        b.data_type = "s"


def write_dashboard(ws: Worksheet, report: DiscoveryReport, refs: TotalsRefs) -> None:
    for c in range(1, _LAST_COL + 1):
        ws.column_dimensions[get_column_letter(c)].width = 3.3
    branding_band(ws, TITLE, _LAST_COL)
    scan = report.scan
    ws["A5"] = f"Source: {scan.source}   ·   mode: {scan.mode}   ·   generated {scan.generated_at}"
    ws["A5"].font = theme.font(theme.INK, 9, True)
    ws["A5"].data_type = "s"
    for r in range(7, 45):
        ws.row_dimensions[r].height = 18
    ws.row_dimensions[6].height = 8

    # Navigation column.
    nav = ws.cell(row=7, column=1, value="NAVIGATE")
    nav.font = theme.font(theme.SLATE, 8, True)
    nav.alignment = theme.CENTER
    _merge(ws, 7, 1, 7, 6)
    visible = [s for s in SHEET_ORDER if s not in CHART_SHEETS]
    for i, name in enumerate(visible):
        r = 8 + i
        cell = ws.cell(row=r, column=1, value=nav_link(name, _NAV_LABELS.get(name, name)))
        current = name == "Discovery"
        cell.font = theme.font(theme.WHITE if current else theme.INK, 9, True)
        cell.alignment = theme.CENTER
        for c in range(1, 7):
            ws.cell(row=r, column=c).fill = theme.fill(theme.NAVY if current else theme.ZEBRA)
        _merge(ws, r, 1, r, 6)

    # KPI tiles.
    for tile_row, tiles in zip(_TILE_ROWS, TILES, strict=True):
        risk = tile_row == _TILE_ROWS[-1]
        for col, (key, label) in zip(_TILE_COLS, tiles, strict=True):
            _tile(ws, tile_row, col, refs.ref(key), label, risk)

    # Scan summary.
    head = ws.cell(row=7, column=_SUMMARY_LABEL_COL, value="SCAN SUMMARY")
    head.font = theme.font(theme.WHITE, 9, True, theme.DISPLAY_FONT)
    head.alignment = theme.CENTER
    for c in range(_SUMMARY_LABEL_COL, _LAST_COL + 1):
        ws.cell(row=7, column=c).fill = theme.HEADER_FILL
    _merge(ws, 7, _SUMMARY_LABEL_COL, 7, _LAST_COL)
    t = refs.ref
    rows: list[tuple[str, object, str]] = [
        ("Mode", "Live workspace scan" if scan.mode == "live" else "Offline export", theme.INK),
        ("Workspace / input", scan.source, theme.INK),
        ("Cloud", scan.cloud or "-", theme.INK),
        ("Unity Catalog metastore", scan.metastore or "-", theme.INK),
        ("Collectors run", str(len(scan.collectors)), theme.INK),
        ("Assessable objects", f"={t('assets')}", theme.INK),
        ("Compatible", f"={t('compatible')}", theme.GREEN_DARK),
        ("Partial", f"={t('partial')}", theme.AMBER),
        ("Manual", f"={t('manual')}", theme.RED),
        ("Unsupported", f"={t('unsupported')}", theme.PURPLE),
        ("Average readiness score", f"={t('avg_readiness')}", theme.INK),
        ("Lines of code", f"={t('notebook_lines')}", theme.INK),
        ("Columns catalogued", f"={t('columns')}", theme.INK),
        ("Secret scopes / secrets", f'={t("secret_scopes")}&" / "&{t("secrets")}', theme.INK),
        (
            "Users / groups / SPs",
            f'={t("users")}&" / "&{t("groups")}&" / "&{t("service_principals")}',
            theme.INK,
        ),
        ("Effort points (heuristic)", f"={refs.cells['effort_points']}", theme.INK),
        ("Captured", scan.captured_at, theme.INK),
        ("Discovered by", f"{APP_NAME} {APP_VERSION} (Kanerika)", theme.INK),
    ]
    for i, (label, value, colour) in enumerate(rows):
        _summary_row(ws, 8 + i, label, value, i % 2 == 0, colour)

    glance = ws.cell(row=28, column=8, value="AT A GLANCE")
    glance.font = theme.font(theme.GREEN, 9, True, theme.DISPLAY_FONT)
    add_dashboard_charts(ws, refs)
    ws.page_setup.fitToHeight = 1  # the dashboard prints on a single page
    ws.sheet_properties.tabColor = theme.GREEN
