"""Initial tables: totals, inventory, finding, estimation, computation.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from dbx_premig.db.migrations.naming import names

__all__: list[str] = []

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Count columns of the totals table (one per Databricks item type), frozen at this revision.
COUNT_COLUMNS = (
    "notebooks",
    "notebook_lines",
    "python_notebooks",
    "sql_notebooks",
    "scala_notebooks",
    "r_notebooks",
    "notebooks_not_scanned",
    "repos",
    "dependencies",
    "unresolved_dependencies",
    "jobs",
    "job_tasks",
    "scheduled_jobs",
    "continuous_jobs",
    "dlt_pipelines",
    "clusters",
    "gpu_clusters",
    "clusters_with_init_scripts",
    "instance_pools",
    "cluster_policies",
    "sql_warehouses",
    "libraries",
    "catalogs",
    "schemas",
    "tables",
    "managed_tables",
    "external_tables",
    "views",
    "materialized_views",
    "streaming_tables",
    "foreign_tables",
    "hive_metastore_tables",
    "columns",
    "volumes",
    "external_locations",
    "storage_credentials",
    "connections",
    "functions",
    "grants",
    "sql_queries",
    "dashboards",
    "alerts",
    "ml_models",
    "serving_endpoints",
    "experiments",
    "secret_scopes",
    "secrets",
    "mounts",
    "users",
    "groups",
    "service_principals",
    "assessable_assets",
    "compatible_assets",
    "partial_assets",
    "manual_assets",
    "unsupported_assets",
    "findings",
    "warnings",
)


def upgrade() -> None:
    schema, p = names()

    op.create_table(
        f"{p}totals",
        sa.Column("scan_id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.Text()),
        sa.Column("mode", sa.String(20)),
        sa.Column("cloud", sa.String(20)),
        sa.Column("workspace_id", sa.String(64)),
        sa.Column("metastore", sa.String(255)),
        sa.Column("collectors", sa.Text()),
        sa.Column("discovery_workbook", sa.String(255)),
        sa.Column("captured_at", sa.String(40)),
        sa.Column("discovered_at", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        *(sa.Column(name, sa.BigInteger()) for name in COUNT_COLUMNS),
        sa.Column("avg_readiness_score", sa.Numeric(10, 2)),
        sa.Column("organization_id", sa.String(128)),
        sa.Column("job_id", sa.String(128)),
        schema=schema,
    )
    op.create_index(
        f"{p}ix_totals_org_job", f"{p}totals", ["organization_id", "job_id"], schema=schema
    )
    op.create_table(
        f"{p}inventory",
        sa.Column("inventory_id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id", sa.Integer(), sa.ForeignKey(f"{schema}.{p}totals.scan_id"), nullable=False
        ),
        sa.Column("asset_key", sa.Text(), nullable=False),
        sa.Column("asset_type", sa.String(50)),
        sa.Column("asset_name", sa.Text(), nullable=False),
        sa.Column("location", sa.Text()),
        sa.Column("fabric_target", sa.String(255)),
        sa.Column("readiness", sa.String(20)),
        sa.Column("readiness_score", sa.Integer()),
        sa.Column("findings", sa.Integer()),
        sa.Column("finding_ids", sa.Text()),
        sa.Column("lines", sa.Integer()),
        sa.Column("cells", sa.Integer()),
        sa.Column("tasks", sa.Integer()),
        sa.Column("columns", sa.Integer()),
        sa.Column("organization_id", sa.String(128)),
        sa.Column("job_id", sa.String(128)),
        sa.UniqueConstraint("scan_id", "asset_key", name=f"{p}inventory_scan_id_asset_key_key"),
        schema=schema,
    )
    op.create_index(
        f"{p}ix_inventory_org_job", f"{p}inventory", ["organization_id", "job_id"], schema=schema
    )
    op.create_table(
        f"{p}finding",
        sa.Column("finding_id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id", sa.Integer(), sa.ForeignKey(f"{schema}.{p}totals.scan_id"), nullable=False
        ),
        sa.Column(
            "inventory_id", sa.Integer(), sa.ForeignKey(f"{schema}.{p}inventory.inventory_id")
        ),
        sa.Column("asset_type", sa.String(50)),
        sa.Column("rule", sa.String(100), nullable=False),
        sa.Column("category", sa.String(100)),
        sa.Column("occurrences", sa.Integer()),
        sa.Column("penalty", sa.Integer()),
        sa.Column("support", sa.String(20)),
        sa.Column("guidance", sa.Text()),
        sa.Column("organization_id", sa.String(128)),
        sa.Column("job_id", sa.String(128)),
        schema=schema,
    )
    op.create_index(
        f"{p}ix_finding_org_job", f"{p}finding", ["organization_id", "job_id"], schema=schema
    )
    op.create_table(
        f"{p}estimation",
        sa.Column("estimation_id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id", sa.Integer(), sa.ForeignKey(f"{schema}.{p}totals.scan_id"), nullable=False
        ),
        sa.Column(
            "inventory_id", sa.Integer(), sa.ForeignKey(f"{schema}.{p}inventory.inventory_id")
        ),
        sa.Column("asset_name", sa.Text(), nullable=False),
        sa.Column("asset_type", sa.String(50)),
        sa.Column("location", sa.Text()),
        sa.Column("total_constructs", sa.Integer()),
        sa.Column("supported", sa.Numeric(14, 6)),
        sa.Column("unsupported", sa.Numeric(14, 6)),
        sa.Column("complexity_score", sa.Integer()),
        sa.Column("complexity_level", sa.String(20)),
        sa.Column("recommended_target", sa.String(255)),
        sa.Column("automation_level", sa.String(30)),
        sa.Column("readiness", sa.String(20)),
        sa.Column("manual_dev_hours", sa.Numeric(14, 6)),
        sa.Column("manual_test_hours", sa.Numeric(14, 6)),
        sa.Column("automation_dev_hours", sa.Numeric(14, 6)),
        sa.Column("automation_test_hours", sa.Numeric(14, 6)),
        sa.Column("hours_saved", sa.Numeric(14, 6)),
        sa.Column("organization_id", sa.String(128)),
        sa.Column("job_id", sa.String(128)),
        sa.UniqueConstraint(
            "scan_id", "inventory_id", name=f"{p}estimation_scan_id_inventory_id_key"
        ),
        schema=schema,
    )
    op.create_index(
        f"{p}ix_estimation_org_job", f"{p}estimation", ["organization_id", "job_id"], schema=schema
    )
    op.create_table(
        f"{p}computation",
        sa.Column("computation_id", sa.Integer(), primary_key=True),
        sa.Column(
            "scan_id",
            sa.Integer(),
            sa.ForeignKey(f"{schema}.{p}totals.scan_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("assessment_generated_at", sa.DateTime(timezone=True)),
        sa.Column("total_assets", sa.Integer()),
        sa.Column("total_constructs", sa.Integer()),
        sa.Column("supported_constructs", sa.Numeric(14, 6)),
        sa.Column("unsupported_constructs", sa.Numeric(14, 6)),
        sa.Column("simple_count", sa.Integer()),
        sa.Column("medium_count", sa.Integer()),
        sa.Column("complex_count", sa.Integer()),
        sa.Column("fully_automated", sa.Integer()),
        sa.Column("partially_automated", sa.Integer()),
        sa.Column("manual", sa.Integer()),
        sa.Column("manual_dev_hours", sa.Numeric(14, 6)),
        sa.Column("manual_test_hours", sa.Numeric(14, 6)),
        sa.Column("total_manual_hours", sa.Numeric(14, 6)),
        sa.Column("automation_dev_hours", sa.Numeric(14, 6)),
        sa.Column("automation_test_hours", sa.Numeric(14, 6)),
        sa.Column("total_automation_hours", sa.Numeric(14, 6)),
        sa.Column("hours_saved", sa.Numeric(14, 6)),
        sa.Column("saving_pct", sa.Numeric(14, 6)),
        sa.Column("rules_version", sa.String(255)),
        sa.Column("organization_id", sa.String(128)),
        sa.Column("job_id", sa.String(128)),
        schema=schema,
    )
    op.create_index(
        f"{p}ix_computation_org_job",
        f"{p}computation",
        ["organization_id", "job_id"],
        schema=schema,
    )


def downgrade() -> None:
    schema, p = names()
    op.drop_table(f"{p}computation", schema=schema)
    op.drop_table(f"{p}estimation", schema=schema)
    op.drop_table(f"{p}finding", schema=schema)
    op.drop_table(f"{p}inventory", schema=schema)
    op.drop_table(f"{p}totals", schema=schema)
