"""Analytics and ML: SQLQueries, Dashboards, Alerts, Models, ServingEndpoints, Experiments."""

from __future__ import annotations

from dbx_premig.excel.sheets.common import assessed_columns
from dbx_premig.excel.types import Column, SheetSpec

__all__ = ["ALERTS", "DASHBOARDS", "EXPERIMENTS", "MODELS", "SERVING_ENDPOINTS", "SQL_QUERIES"]

N = "#,##0"

SQL_QUERIES = SheetSpec(
    name="SQLQueries",
    title="SQL queries  ·  saved Databricks SQL queries",
    description="Saved queries; their SQL was scanned for Databricks-only features.",
    columns=[
        Column("Query id", "query_id", 38),
        Column("Name", "name", 34),
        Column("Owner", "owner", 26),
        Column("Warehouse id", "warehouse_id", 18),
        Column("Lines", "lines", 8, numeric=True, number_format=N),
        Column("Updated", "updated_at", 16),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.queries,
    readiness_column="Readiness",
)

DASHBOARDS = SheetSpec(
    name="Dashboards",
    title="Dashboards  ·  AI/BI and legacy SQL",
    description="Dashboards are rebuilt as Power BI reports on a semantic model.",
    columns=[
        Column("Dashboard id", "dashboard_id", 36),
        Column("Name", "name", 34),
        Column("Kind", "kind", 18),
        Column("Path", "path", 40),
        Column("Warehouse id", "warehouse_id", 18),
        Column("State", "state", 10),
        Column("Created", "created_at", 16),
        Column("Updated", "updated_at", 16),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.dashboards,
    readiness_column="Readiness",
)

ALERTS = SheetSpec(
    name="Alerts",
    title="Alerts  ·  Databricks SQL alerts",
    description="SQL alerts; rebuild them in Fabric Activator or as pipeline notifications.",
    columns=[
        Column("Alert id", "alert_id", 38),
        Column("Name", "name", 34),
        Column("Query id", "query_id", 38),
        Column("State", "state", 12),
        Column("Owner", "owner", 26),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.alerts,
    readiness_column="Readiness",
)

MODELS = SheetSpec(
    name="Models",
    title="ML models  ·  Unity Catalog and workspace registry",
    description="Registered MLflow models; re-register them in the Fabric MLflow registry.",
    columns=[
        Column("Full name", "full_name", 38),
        Column("Catalog", "catalog", 20),
        Column("Schema", "schema_name", 16),
        Column("Name", "name", 24),
        Column("Owner", "owner", 24),
        Column("Created", "created_at", 16),
        Column("Updated", "updated_at", 16),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.models,
    readiness_column="Readiness",
)

SERVING_ENDPOINTS = SheetSpec(
    name="ServingEndpoints",
    title="Model serving endpoints",
    description=(
        "Customer serving endpoints (Databricks-hosted foundation models are skipped). Fabric "
        "has no native model serving: rehost on Azure ML / AI Foundry."
    ),
    columns=[
        Column("Name", "name", 30),
        Column("State", "state", 12),
        Column("Task", "task", 16),
        Column("Served entities", "served_entities", 40),
        Column("Entity types", "entity_types", 20),
        Column("Creator", "creator", 24),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.serving_endpoints,
    readiness_column="Readiness",
)

EXPERIMENTS = SheetSpec(
    name="Experiments",
    title="MLflow experiments",
    description="Experiments and their run history; Fabric has native MLflow experiments.",
    columns=[
        Column("Experiment id", "experiment_id", 20),
        Column("Name", "name", 50),
        Column("Lifecycle stage", "lifecycle_stage", 14),
        Column("Last update", "last_update", 16),
    ],
    rows=lambda r: r.estate.experiments,
)
