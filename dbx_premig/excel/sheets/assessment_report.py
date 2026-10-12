"""Sheets of the assessment workbook (built on top of a discovery workbook).

Estimation holds the per-asset values computed from the rules file. Every other number
(Summary, EffortByType, the dashboard and the chart helpers) is a live formula over
Estimation, so editing an Estimation row updates the whole workbook.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from openpyxl.worksheet.worksheet import Worksheet

from dbx_premig.excel import theme
from dbx_premig.excel.layout import back_link, branding_band, nav_link, set_widths
from dbx_premig.excel.types import Column, SheetSpec
from dbx_premig.models import AssessmentResult
from dbx_premig.version import APP_NAME, APP_VERSION

__all__ = [
    "ABOUT_TITLE",
    "ASSESSMENT_SHEETS",
    "DASHBOARD_TITLE",
    "EFFORT_BY_TYPE",
    "ESTIMATION",
    "RULES_TITLE",
    "SUMMARY_TITLE",
    "SummaryRefs",
    "write_about",
    "write_rules",
    "write_summary",
]

N = "#,##0"
H = "#,##0.00"
DASHBOARD_TITLE = "DATABRICKS → FABRIC ASSESSMENT  ·  COMPLEXITY, AUTOMATION, EFFORT"
SUMMARY_TITLE = "Summary  ·  the single source of truth"
RULES_TITLE = "Rules  ·  the formulas this assessment used"
ABOUT_TITLE = "About  ·  how to read this assessment"

ESTIMATION = SheetSpec(
    name="Estimation",
    title="Estimation  ·  complexity, automation and hours per asset",
    description=(
        "One row per assessable object from the discovery workbook, computed with the rules "
        "file shown on Rules. Totals and charts are formulas over this sheet."
    ),
    columns=[
        Column("Asset type", "asset_type", 18),
        Column("Asset", "asset_name", 40),
        Column("Location / id", "location", 36),
        Column("Fabric target", "fabric_target", 34),
        Column("Readiness", "readiness", 12),
        Column("Readiness score", "readiness_score", 10, numeric=True, number_format="0"),
        Column("Constructs", "total_constructs", 10, numeric=True, number_format=N,
               note="The object itself plus one per distinct Databricks feature found"),
        Column("Supported", "supported", 10, numeric=True, number_format="0.0#",
               note="Constructs weighted by catalog verdict (support_weights in the rules)"),
        Column("Unsupported", "unsupported", 11, numeric=True, number_format="0.0#"),
        Column("Complexity score", "complexity_score", 11, numeric=True, number_format="0"),
        Column("Complexity", "complexity_level", 11),
        Column("Automation", "automation_level", 18),
        Column("Manual dev hours", "manual_dev_hours", 11, numeric=True, number_format=H),
        Column("Manual test hours", "manual_test_hours", 11, numeric=True, number_format=H),
        Column("Total manual hours", formula="=M{r}+N{r}", width=11, numeric=True,
               number_format=H),
        Column("Automation dev hours", "automation_dev_hours", 11, numeric=True,
               number_format=H),
        Column("Automation test hours", "automation_test_hours", 11, numeric=True,
               number_format=H),
        Column("Total automation hours", formula="=P{r}+Q{r}", width=11, numeric=True,
               number_format=H),
        Column("Hours saved", "hours_saved", 10, numeric=True, number_format=H),
        Column("Asset key", "asset_key", 30),
    ],
    rows=lambda r: r.estimations,
    readiness_column="Readiness",
)  # fmt: skip

_E = "'Estimation'!"


def _rng(col: str) -> str:
    return f"{_E}${col}$7:${col}$1048576"


EFFORT_BY_TYPE = SheetSpec(
    name="EffortByType",
    title="Effort by asset type",
    description="Live roll-up of Estimation per asset type: complexity, automation and hours.",
    columns=[
        Column("Asset type", lambda t, _r: t, 22),
        Column("Assets", formula=f"=COUNTIF({_rng('A')},$A{{r}})", width=9, numeric=True,
               number_format=N),
        *(
            Column(level, formula=f'=COUNTIFS({_rng("A")},$A{{r}},{_rng("K")},"{level}")',
                   width=9, numeric=True, number_format=N)
            for level in ("Simple", "Medium", "Complex")
        ),
        *(
            Column(level, formula=f'=COUNTIFS({_rng("A")},$A{{r}},{_rng("L")},"{level}")',
                   width=12, numeric=True, number_format=N)
            for level in ("Fully automated", "Partially automated", "Manual")
        ),
        Column("Manual hours", formula=f"=SUMIF({_rng('A')},$A{{r}},{_rng('O')})", width=11,
               numeric=True, number_format=H),
        Column("Automation hours", formula=f"=SUMIF({_rng('A')},$A{{r}},{_rng('R')})",
               width=12, numeric=True, number_format=H),
        Column("Hours saved", formula=f"=SUMIF({_rng('A')},$A{{r}},{_rng('S')})", width=11,
               numeric=True, number_format=H),
        Column("Saving %", formula="=IFERROR(K{r}/I{r},0)", width=9, numeric=True,
               number_format="0.0%"),
    ],
    rows=lambda r: [t for t, _ in sorted(Counter(e.asset_type for e in r.estimations).items(),
                                         key=lambda kv: (-kv[1], kv[0].casefold()))],
)  # fmt: skip

ASSESSMENT_SHEETS = ("Assessment", "Estimation", "EffortByType", "Summary", "Rules", "About")


@dataclass
class SummaryRefs:
    cells: dict[str, str] = field(default_factory=dict)

    def ref(self, key: str) -> str:
        return self.cells[key]


def _section(ws: Worksheet, row: int, title: str, headers: tuple[str, ...]) -> int:
    ws.cell(row=row, column=1, value=title).font = theme.SECTION_FONT
    ws.row_dimensions[row].height = 22
    for i, h in enumerate(headers, start=1):
        cell = ws.cell(row=row + 1, column=i, value=h)
        cell.font = theme.HEADER_FONT
        cell.fill = theme.HEADER_FILL
        cell.alignment = theme.HEADER_ALIGN if i > 1 else theme.LEFT
    return row + 2


#: Summary metrics: (key = computation column, label, formula, format, meaning).
SUMMARY_METRICS: tuple[tuple[str, str, str, str, str], ...] = (
    ("total_assets", "Assets assessed", f"=COUNTA({_rng('A')})", N,
     "One row each on Estimation"),
    ("total_constructs", "Constructs", f"=SUM({_rng('G')})", N,
     "Objects plus the Databricks features they use"),
    ("supported_constructs", "Supported constructs", f"=SUM({_rng('H')})", "#,##0.0#",
     "Weighted by catalog verdict"),
    ("unsupported_constructs", "Unsupported constructs", f"=SUM({_rng('I')})", "#,##0.0#",
     "Constructs minus supported"),
    ("simple_count", "Simple", f'=COUNTIF({_rng("K")},"Simple")', N, "Complexity level"),
    ("medium_count", "Medium", f'=COUNTIF({_rng("K")},"Medium")', N, "Complexity level"),
    ("complex_count", "Complex", f'=COUNTIF({_rng("K")},"Complex")', N, "Complexity level"),
    ("fully_automated", "Fully automated", f'=COUNTIF({_rng("L")},"Fully automated")', N,
     "Converted by the accelerator with review"),
    ("partially_automated", "Partially automated",
     f'=COUNTIF({_rng("L")},"Partially automated")', N, "Accelerator plus manual work"),
    ("manual", "Manual", f'=COUNTIF({_rng("L")},"Manual")', N, "Redesign or rebuild by hand"),
    ("manual_dev_hours", "Manual development hours", f"=SUM({_rng('M')})", H,
     "Without the accelerator"),
    ("manual_test_hours", "Manual testing hours", f"=SUM({_rng('N')})", H, ""),
    ("total_manual_hours", "Total manual hours", "", H, "Development + testing"),
    ("automation_dev_hours", "Automation development hours", f"=SUM({_rng('P')})", H,
     "With the accelerator"),
    ("automation_test_hours", "Automation testing hours", f"=SUM({_rng('Q')})", H, ""),
    ("total_automation_hours", "Total automation hours", "", H, "Development + testing"),
    ("hours_saved", "Hours saved", f"=SUM({_rng('S')})", H, "Manual minus automation"),
    ("saving_pct", "Saving %", "", "0.0%", "Hours saved / total manual hours"),
)  # fmt: skip


def write_summary(ws: Worksheet, result: AssessmentResult) -> SummaryRefs:
    set_widths(ws, [44, 18, 70])
    branding_band(ws, SUMMARY_TITLE, 3)
    back_link(ws, "Every assessment number comes from here; every value is a formula over "
                  "Estimation.", "Assessment")  # fmt: skip
    refs = SummaryRefs()
    row = _section(ws, 7, "Portfolio computation", ("Metric", "Value", "What it means"))
    for i, (key, label, formula, fmt, meaning) in enumerate(SUMMARY_METRICS):
        r = row + i
        if key == "total_manual_hours":
            formula = f"={refs.ref('manual_dev_hours')}+{refs.ref('manual_test_hours')}"
        elif key == "total_automation_hours":
            formula = f"={refs.ref('automation_dev_hours')}+{refs.ref('automation_test_hours')}"
        elif key == "saving_pct":
            formula = f"=IFERROR({refs.ref('hours_saved')}/{refs.ref('total_manual_hours')},0)"
        ws.cell(row=r, column=1, value=label).font = theme.font(theme.INK, 10, True)
        b = ws.cell(row=r, column=2, value=formula)
        b.font = theme.font(theme.INK, 10, True)
        b.alignment = theme.RIGHT
        b.number_format = fmt
        ws.cell(row=r, column=3, value=meaning).font = theme.NOTE_FONT
        if i % 2:
            for c in (1, 2):
                ws.cell(row=r, column=c).fill = theme.fill(theme.ZEBRA)
        refs.cells[key] = f"'Summary'!$B${r}"
    row += len(SUMMARY_METRICS) + 1

    row = _section(ws, row, "Run", ("Property", "Value", ""))
    comp = result.computation
    scan = result.discovery.scan
    props = (
        ("Assessment generated", comp.assessment_generated_at),
        ("Rules", comp.rules_version),
        ("Discovery workbook", result.discovery.file_name),
        ("Discovery source", scan.source),
        ("Discovery mode", scan.mode),
        ("Discovery generated", scan.generated_at),
    )
    for i, (label, value) in enumerate(props):
        ws.cell(row=row + i, column=1, value=label).font = theme.font(theme.INK, 10, True)
        cell = ws.cell(row=row + i, column=2, value=value)
        cell.font = theme.BODY_FONT
        cell.data_type = "s"
    row += len(props) + 1

    row = _section(ws, row, "Discovery item counts (recomputed from the discovery rows)",
                   ("Item", "Count", ""))  # fmt: skip
    for i, (key, count) in enumerate(result.discovery.counts.items()):
        ws.cell(
            row=row + i, column=1, value=key.replace("_", " ").capitalize()
        ).font = theme.BODY_FONT
        cell = ws.cell(row=row + i, column=2, value=count)
        cell.alignment = theme.RIGHT
        cell.number_format = "#,##0.##"
        refs.cells[f"count_{key}"] = f"'Summary'!$B${row + i}"
    ws.freeze_panes = "A7"
    return refs


def write_rules(ws: Worksheet, result: AssessmentResult, rules_text: str, sha256: str) -> None:
    set_widths(ws, [8, 120])
    branding_band(ws, RULES_TITLE, 2)
    back_link(ws, "The exact rules file this assessment used. Edit a copy and re-run "
                  "'assess --rules' to change the formulas.", "Assessment")  # fmt: skip
    ws["A7"], ws["B7"] = "File", result.computation.rules_version
    ws["A8"], ws["B8"] = "SHA-256", sha256
    for c in ("A7", "A8"):
        ws[c].font = theme.font(theme.INK, 10, True)
    for i, h in enumerate(("Line", "Rules file"), start=1):
        cell = ws.cell(row=10, column=i, value=h)
        cell.font = theme.HEADER_FONT
        cell.fill = theme.HEADER_FILL
    mono = theme.font(theme.INK, 9, False, "Consolas")
    for n, line in enumerate(rules_text.splitlines(), start=1):
        ws.cell(row=10 + n, column=1, value=n).font = theme.NOTE_FONT
        cell = ws.cell(row=10 + n, column=2, value=line)
        cell.font = theme.font(theme.GREY_TEXT, 9, False, "Consolas") if line.lstrip().startswith(
            "#") else mono  # fmt: skip
        cell.data_type = "s"
    ws.freeze_panes = "A11"


_ABOUT = (
    ("What this workbook is",
     "An assessment of the Databricks estate in a discovery workbook: for every assessable "
     "object, its complexity (Simple / Medium / Complex), how much of its migration to "
     "Microsoft Fabric the Kanerika accelerator automates (Fully / Partially automated / "
     "Manual), and the development and testing hours with and without automation."),
    ("How the numbers are made",
     "Every formula comes from the rules file shown on the Rules sheet: size points and a "
     "complexity score per asset type, first-match-wins level and automation rules, base hours "
     "per type and level, and automation factors. Hours are rounded per asset; totals are sums "
     "of the rounded figures. Change the formulas by editing a copy of the rules file and "
     "re-running the assessment; no code change is needed."),
    ("What to review",
     "Sort Estimation by Total manual hours to see where effort concentrates, and EffortByType "
     "for the split by object type. Edit an Estimation row (for example a complexity or hours "
     "value after a workshop) and Summary, EffortByType and the dashboard follow."),
    ("Limits",
     "The hours are planning estimates from this tool's default rules, not a quote. They "
     "depend on what the discovery could see (read its Warnings sheet) and on the rules file."),
)  # fmt: skip


def write_about(ws: Worksheet, result: AssessmentResult) -> None:
    set_widths(ws, [30, 22, 22, 22, 22, 44])
    branding_band(ws, ABOUT_TITLE, 6)
    back_link(ws, "How to read this assessment.", "Assessment")
    row = 8
    for heading, text in _ABOUT:
        ws.cell(row=row, column=1, value=heading).font = theme.SECTION_FONT
        cell = ws.cell(row=row + 1, column=1, value=text)
        cell.font = theme.BODY_FONT
        cell.alignment = theme.WRAP
        ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=6)
        ws.row_dimensions[row + 1].height = 62
        row += 3
    ws.cell(row=row, column=1, value="Sheets").font = theme.SECTION_FONT
    entries = (
        ("Assessment", "Dashboard: tiles, run summary and charts (formulas into Summary)."),
        ("Estimation", ESTIMATION.description),
        ("EffortByType", EFFORT_BY_TYPE.description),
        ("Summary", "The single source of truth: portfolio computation and discovery counts."),
        ("Rules", "The rules file (formulas) used for this assessment."),
        ("About", "This page."),
    )
    for i, (name, text) in enumerate(entries, start=1):
        ws.cell(row=row + i, column=1, value=nav_link(name)).font = theme.font(
            theme.GREEN, 10, True
        )
        cell = ws.cell(row=row + i, column=2, value=text)
        cell.font = theme.BODY_FONT
        ws.merge_cells(start_row=row + i, start_column=2, end_row=row + i, end_column=6)
    row += len(entries) + 2
    ws.cell(row=row, column=1, value=f"{APP_NAME} {APP_VERSION} (Kanerika)").font = theme.NOTE_FONT
