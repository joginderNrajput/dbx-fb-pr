"""Totals: the single source of truth.

Every figure is a live formula over the data sheets, and the Discovery dashboard and chart
helper sheets hold only ``='Totals'!$B$n`` references. Edit a data row and every number
follows; edit a total and nothing else does.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from openpyxl.worksheet.worksheet import Worksheet

from dbx_premig.excel import theme
from dbx_premig.excel.layout import back_link, branding_band, data_range, set_widths
from dbx_premig.excel.writer import column_letter, spec_by_name
from dbx_premig.models import DiscoveryReport

__all__ = ["EFFORT_WEIGHTS", "TITLE", "TotalsRefs", "write_totals"]

TITLE = "Totals  ·  the single source of truth"

READINESS = ("Compatible", "Partial", "Manual", "Unsupported")

#: Editable effort weights (driver key, label, default weight). Heuristic, not a standard.
EFFORT_WEIGHTS: tuple[tuple[str, str, float], ...] = (
    ("notebooks", "Notebooks", 2),
    ("notebook_klines", "Notebook lines (thousands)", 4),
    ("jobs", "Jobs", 2),
    ("job_tasks", "Job tasks", 1),
    ("pipelines", "DLT pipelines", 12),
    ("clusters", "All-purpose clusters", 1),
    ("warehouses", "SQL warehouses", 2),
    ("tables", "Tables", 0.25),
    ("views", "Views", 1),
    ("mv_streaming", "Materialized views + streaming tables", 6),
    ("functions", "Functions", 1),
    ("queries", "SQL queries", 0.5),
    ("dashboards", "Dashboards", 8),
    ("alerts", "Alerts", 2),
    ("models", "ML models", 2),
    ("serving_endpoints", "Serving endpoints", 16),
    ("connections", "Connections", 1),
    ("secret_scopes", "Secret scopes", 0.5),
    ("manual", "Assets classified Manual", 4),
    ("unsupported", "Assets classified Unsupported", 8),
)


@dataclass
class TotalsRefs:
    """Where each metric landed: key -> absolute reference, e.g. 'Totals'!$B$9."""

    cells: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    asset_types: list[tuple[str, str, str]] = field(default_factory=list)  # label, count, -
    readiness: list[tuple[str, str]] = field(default_factory=list)
    top_findings: list[tuple[str, str]] = field(default_factory=list)

    def ref(self, key: str) -> str:
        return self.cells[key]


class _Builder:
    def __init__(self, ws: Worksheet, report: DiscoveryReport) -> None:
        self.ws = ws
        self.report = report
        self.row = 7
        self.refs = TotalsRefs()
        self._striped = False

    def rng(self, sheet: str, header: str) -> str:
        spec = spec_by_name(sheet)
        rows = len(spec.rows(self.report))
        return data_range(sheet, column_letter(spec, header), rows)

    def section(
        self, title: str, headers: tuple[str, ...] = ("Metric", "Value", "What it means")
    ) -> None:
        if self.row > 7:
            self.row += 1
        c = self.ws.cell(row=self.row, column=1, value=title)
        c.font = theme.SECTION_FONT
        self.ws.row_dimensions[self.row].height = 22
        self.row += 1
        for i, h in enumerate(headers, start=1):
            cell = self.ws.cell(row=self.row, column=i, value=h)
            cell.font = theme.HEADER_FONT
            cell.fill = theme.HEADER_FILL
            cell.alignment = theme.HEADER_ALIGN if i > 1 else theme.LEFT
        self.row += 1
        self._striped = False

    def metric(self, key: str, label: str, formula: str, meaning: str, fmt: str = "#,##0") -> str:
        r = self.row
        a = self.ws.cell(row=r, column=1, value=label)
        b = self.ws.cell(row=r, column=2, value=formula)
        c = self.ws.cell(row=r, column=3, value=meaning)
        a.font = theme.font(theme.INK, 10, True)
        b.font = theme.font(theme.INK, 10, True)
        b.alignment = theme.RIGHT
        b.number_format = fmt
        c.font = theme.NOTE_FONT
        if self._striped:
            for cell in (a, b):
                cell.fill = theme.fill(theme.ZEBRA)
        self._striped = not self._striped
        ref = f"'Totals'!$B${r}"
        self.refs.cells[key] = ref
        self.refs.labels[key] = label
        self.row += 1
        return ref

    def counta(self, key: str, label: str, sheet: str, header: str, meaning: str) -> str:
        return self.metric(key, label, f"=COUNTA({self.rng(sheet, header)})", meaning)

    def countif(
        self, key: str, label: str, sheet: str, header: str, criteria: str, meaning: str
    ) -> str:
        return self.metric(key, label, f'=COUNTIF({self.rng(sheet, header)},"{criteria}")', meaning)

    def total(self, key: str, label: str, sheet: str, header: str, meaning: str) -> str:
        return self.metric(key, label, f"=SUM({self.rng(sheet, header)})", meaning)


def write_totals(ws: Worksheet, report: DiscoveryReport) -> TotalsRefs:
    set_widths(ws, [46, 16, 16, 16, 16, 16, 16, 60])
    branding_band(ws, TITLE, 8)
    back_link(
        ws,
        "Every number on the Discovery sheet comes from here, and every number here is a live "
        "formula over the data sheets.",
    )
    b = _Builder(ws, report)

    b.section("Portfolio readiness")
    b.counta(
        "assets",
        "Assessable objects",
        "Assets",
        "Asset type",
        "One row each on Assets; the objects that need a migration decision",
    )
    for level in READINESS:
        b.countif(
            level.lower(),
            f"{level} assets",
            "Assets",
            "Readiness",
            level,
            {
                "Compatible": "Readiness score >= 80: lift and shift with small edits",
                "Partial": "Score 50-79: convert and configure",
                "Manual": "Score < 50: redesign or rewrite",
                "Unsupported": "Uses a feature with no Fabric equivalent",
            }[level],
        )
    b.metric(
        "avg_readiness",
        "Average readiness score",
        f"=IFERROR(AVERAGE({b.rng('Assets', 'Readiness score')}),0)",
        "Simple average over all assessable objects (0-100)",
        "0.0",
    )
    b.counta(
        "findings",
        "Findings",
        "Findings",
        "Rule",
        "Databricks features found on assets; see Findings",
    )
    b.counta(
        "warnings",
        "Discovery warnings",
        "Warnings",
        "Message",
        "Endpoints or files discovery could not read; see Warnings",
    )

    b.section("Workspace code")
    b.counta(
        "notebooks",
        "Notebooks and code files",
        "Notebooks",
        "Path",
        "Notebooks plus .py/.sql/.scala/.r workspace files",
    )
    b.total("notebook_lines", "Lines of code", "Notebooks", "Lines", "Including comments")
    b.metric(
        "notebook_klines",
        "Lines of code (thousands)",
        f"=ROUND({b.refs.ref('notebook_lines')}/1000,1)",
        "For the effort weights",
        "#,##0.0",
    )
    for lang in ("PYTHON", "SQL", "SCALA", "R"):
        b.countif(
            f"lang_{lang.lower()}",
            f"{lang.title() if lang != 'SQL' else 'SQL'} notebooks",
            "Notebooks",
            "Language",
            lang,
            "By default language",
        )
    b.countif(
        "not_scanned",
        "Notebooks not scanned",
        "Notebooks",
        "Scanned",
        "No",
        "Too large or not exportable; review by hand",
    )
    b.total(
        "magic_commands",
        "Magic commands",
        "Notebooks",
        "Magic commands",
        "%run, %sql, %sh, %pip ... cells",
    )
    b.counta("repos", "Git folders (Repos)", "Repos", "Path", "Map to Fabric Git integration")
    b.counta(
        "dependencies",
        "Dependencies",
        "Dependencies",
        "Relation",
        "Notebook calls, job tasks and DLT sources",
    )
    b.countif(
        "unresolved",
        "Unresolved dependencies",
        "Dependencies",
        "Resolved",
        "No",
        "Targets not found in this discovery (deleted, outside scope or dynamic)",
    )

    b.section("Orchestration")
    b.counta("jobs", "Jobs", "Jobs", "Job id", "Each becomes a Fabric Data Factory pipeline")
    b.counta("job_tasks", "Job tasks", "JobTasks", "Task key", "Each becomes a pipeline activity")
    b.countif(
        "scheduled_jobs",
        "Scheduled jobs",
        "Jobs",
        "Schedule (Quartz cron)",
        "?*",
        "Quartz cron to map onto Fabric schedules",
    )
    b.countif(
        "continuous_jobs",
        "Continuous jobs",
        "Jobs",
        "Continuous",
        "Yes",
        "Always-on streaming jobs",
    )
    b.counta(
        "pipelines",
        "DLT pipelines",
        "DLTPipelines",
        "Pipeline id",
        "No direct equivalent: redesign",
    )

    b.section("Compute")
    b.counta(
        "clusters",
        "All-purpose clusters",
        "Clusters",
        "Cluster id",
        "Job and pipeline clusters are not counted",
    )
    b.countif(
        "gpu_clusters", "GPU clusters", "Clusters", "GPU", "Yes", "No GPU Spark pools in Fabric"
    )
    b.countif(
        "init_clusters",
        "Clusters with init scripts",
        "Clusters",
        "Init scripts",
        ">0",
        "Move setup into a Fabric Environment",
    )
    b.counta("instance_pools", "Instance pools", "InstancePools", "Pool id", "")
    b.counta("cluster_policies", "Cluster policies", "ClusterPolicies", "Policy id", "")
    b.counta(
        "warehouses",
        "SQL warehouses",
        "SQLWarehouses",
        "Warehouse id",
        "Fabric Warehouse / SQL analytics endpoint",
    )
    b.counta("libraries", "Cluster libraries", "Libraries", "Library", "Distinct libraries")

    b.section("Data estate")
    b.counta("catalogs", "Catalogs", "Catalogs", "Catalog", "Unity Catalog and hive_metastore")
    b.counta("schemas", "Schemas", "Schemas", "Schema", "")
    b.counta("tables_all", "Tables and views", "Tables", "Full name", "Every object on Tables")
    b.countif("managed_tables", "Managed tables", "Tables", "Table type", "MANAGED", "")
    b.countif("external_tables", "External tables", "Tables", "Table type", "EXTERNAL", "")
    b.countif("views", "Views", "Tables", "Table type", "VIEW", "View SQL needs translation")
    b.countif(
        "materialized_views",
        "Materialized views",
        "Tables",
        "Table type",
        "MATERIALIZED_VIEW",
        "Rebuild as Materialized Lake Views",
    )
    b.countif(
        "streaming_tables",
        "Streaming tables",
        "Tables",
        "Table type",
        "STREAMING_TABLE",
        "Rebuild as streaming jobs",
    )
    b.metric(
        "mv_streaming",
        "Materialized views + streaming tables",
        f"={b.refs.ref('materialized_views')}+{b.refs.ref('streaming_tables')}",
        "For the effort weights",
    )
    b.countif(
        "foreign_tables",
        "Foreign tables",
        "Tables",
        "Table type",
        "FOREIGN",
        "Lakehouse Federation",
    )
    b.countif(
        "hive_tables",
        "hive_metastore tables",
        "Tables",
        "Catalog",
        "hive_metastore",
        "Legacy metastore",
    )
    b.metric(
        "tables",
        "Tables (excluding views)",
        f"={b.refs.ref('tables_all')}-{b.refs.ref('views')}-{b.refs.ref('materialized_views')}",
        "",
    )
    b.counta("columns", "Columns", "Columns", "Column", "Across all tables and views")
    b.counta("volumes", "Volumes", "Volumes", "Full name", "Lakehouse Files / shortcuts")
    b.counta(
        "external_locations", "External locations", "ExternalLocations", "Name", "OneLake shortcuts"
    )
    b.counta("storage_credentials", "Storage credentials", "StorageCredentials", "Name", "")
    b.counta("connections", "Connections", "Connections", "Name", "Lakehouse Federation")
    b.counta("functions", "Functions", "Functions", "Full name", "UC SQL / Python UDFs")
    b.counta("grants", "Grants", "Grants", "Principal", "Principal-securable pairs")

    b.section("Analytics and ML")
    b.counta("queries", "SQL queries", "SQLQueries", "Query id", "Saved Databricks SQL queries")
    b.counta("dashboards", "Dashboards", "Dashboards", "Dashboard id", "Rebuild in Power BI")
    b.counta("alerts", "Alerts", "Alerts", "Alert id", "Activator / pipeline notifications")
    b.counta("models", "ML models", "Models", "Full name", "Registered MLflow models")
    b.counta(
        "serving_endpoints",
        "Serving endpoints",
        "ServingEndpoints",
        "Name",
        "Rehost outside Fabric",
    )
    b.counta("experiments", "MLflow experiments", "Experiments", "Experiment id", "")

    b.section("Security and platform")
    b.counta("secret_scopes", "Secret scopes", "SecretScopes", "Scope", "Azure Key Vault")
    b.total("secrets", "Secrets", "SecretScopes", "Secrets", "Values must be re-entered")
    b.counta("mounts", "DBFS mounts", "Mounts", "Mount point", "OneLake shortcuts")
    b.countif("users", "Users", "Identities", "Type", "User", "")
    b.countif("groups", "Groups", "Identities", "Type", "Group", "")
    b.countif(
        "service_principals", "Service principals", "Identities", "Type", "Service principal", ""
    )

    # ------------------------------------------------------------- readiness by asset type
    b.section("Readiness by asset type", ("Asset type", "Assets", *READINESS, "Avg score"))
    types = Counter(a.asset_type for a in report.assessments)
    t_rng = b.rng("Assets", "Asset type")
    r_rng = b.rng("Assets", "Readiness")
    s_rng = b.rng("Assets", "Readiness score")
    for asset_type, _n in sorted(types.items(), key=lambda kv: (-kv[1], kv[0].casefold())):
        r = b.row
        ws.cell(row=r, column=1, value=asset_type).font = theme.font(theme.INK, 10, True)
        ws.cell(row=r, column=2, value=f"=COUNTIF({t_rng},$A{r})")
        for i, level in enumerate(READINESS, start=3):
            ws.cell(row=r, column=i, value=f'=COUNTIFS({t_rng},$A{r},{r_rng},"{level}")')
        ws.cell(row=r, column=7, value=f"=IFERROR(AVERAGEIF({t_rng},$A{r},{s_rng}),0)")
        for col in range(2, 8):
            cell = ws.cell(row=r, column=col)
            cell.alignment = theme.RIGHT
            cell.number_format = "0.0" if col == 7 else "#,##0"
            cell.font = theme.BODY_FONT
        b.refs.asset_types.append((f"'Totals'!$A${r}", f"'Totals'!$B${r}", ""))
        b.row += 1
    for level in READINESS:
        b.refs.readiness.append((level, b.refs.ref(level.lower())))

    # ------------------------------------------------------------- top findings
    b.section(
        "Findings by rule",
        (
            "Rule",
            "Assets affected",
            "Fabric support",
            "Category",
            "",
            "",
            "",
            "What to do in Fabric",
        ),
    )
    affected: Counter[str] = Counter()
    info: dict[str, tuple[str, str, str]] = {}
    for a in report.assessments:
        for f in a.findings:
            affected[f.feature_id] += 1
            info[f.feature_id] = (f.support, f.category, f.guidance)
    rule_rng = b.rng("Findings", "Rule")
    for rule, _n in sorted(affected.items(), key=lambda kv: (-kv[1], kv[0])):
        r = b.row
        support, category, guidance = info[rule]
        ws.cell(row=r, column=1, value=rule).font = theme.font(theme.INK, 10, True)
        cnt = ws.cell(row=r, column=2, value=f"=COUNTIF({rule_rng},$A{r})")
        cnt.alignment = theme.RIGHT
        ws.cell(row=r, column=3, value=support).font = theme.BODY_FONT
        ws.cell(row=r, column=4, value=category).font = theme.BODY_FONT
        ws.cell(row=r, column=8, value=guidance).font = theme.NOTE_FONT
        b.refs.top_findings.append((f"'Totals'!$A${r}", f"'Totals'!$B${r}"))
        b.row += 1

    # ------------------------------------------------------------- effort weights
    b.section(
        "Migration effort points (heuristic, editable)",
        ("Driver", "Portfolio count", "Weight", "Points", "", "", "", "How to use"),
    )
    first = b.row
    for key, label, weight in EFFORT_WEIGHTS:
        r = b.row
        ws.cell(row=r, column=1, value=label).font = theme.font(theme.INK, 10, True)
        ws.cell(row=r, column=2, value=f"={b.refs.ref(key)}").alignment = theme.RIGHT
        w = ws.cell(row=r, column=3, value=weight)
        w.fill = theme.fill(theme.YELLOW_INPUT)
        w.font = theme.font(theme.BLUE_INPUT, 10, True)
        w.alignment = theme.RIGHT
        ws.cell(row=r, column=4, value=f"=B{r}*C{r}").alignment = theme.RIGHT
        for col in (2, 4):
            ws.cell(row=r, column=col).number_format = "#,##0.0"
        b.row += 1
    ws.cell(
        row=first,
        column=8,
        value=(
            "Blue cells on yellow are editable. Points = count x weight; the defaults are this "
            "tool's assumptions, not an industry standard. Use the total to compare estates, "
            "not as hours."
        ),
    ).alignment = theme.WRAP
    ws.cell(row=first, column=8).font = theme.NOTE_FONT
    r = b.row
    ws.cell(row=r, column=1, value="Portfolio points").font = theme.font(theme.GREEN, 11, True)
    total = ws.cell(row=r, column=4, value=f"=SUM(D{first}:D{r - 1})")
    total.font = theme.font(theme.GREEN, 11, True)
    total.number_format = "#,##0.0"
    total.alignment = theme.RIGHT
    b.refs.cells["effort_points"] = f"'Totals'!$D${r}"
    b.refs.labels["effort_points"] = "Portfolio points"
    ws.freeze_panes = "A7"
    return b.refs
