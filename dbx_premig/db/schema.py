"""Table definitions (SQLAlchemy Core): what the code writes to.

The database itself is created and changed only by the Alembic migrations in
``db/migrations/versions``; ``tests/test_db.py`` checks that a database migrated to head
matches these definitions exactly (no drift). ``prefix`` (``DBXF_DB_TABLE_PREFIX``) is put in
front of every table, index and constraint name, so the tables can share a schema with
another accelerator's tables of the same names.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

from dbx_premig.excel.discovery_reader import COUNT_KEYS

__all__ = ["DbTables", "build_tables"]

_ORG = 128
_HOURS = Numeric(14, 6)


class DbTables:
    def __init__(self, metadata: MetaData, tables: dict[str, Table]) -> None:
        self.metadata = metadata
        self.totals = tables["totals"]
        self.inventory = tables["inventory"]
        self.finding = tables["finding"]
        self.estimation = tables["estimation"]
        self.computation = tables["computation"]

    @property
    def children_first(self) -> tuple[Table, ...]:
        """Delete order (children before parents)."""
        return (self.computation, self.estimation, self.finding, self.inventory, self.totals)


def _owner() -> list[Column]:  # type: ignore[type-arg]
    return [
        Column("organization_id", String(_ORG)),
        Column("job_id", String(_ORG)),
    ]


def build_tables(schema: str, prefix: str = "") -> DbTables:
    md = MetaData(schema=schema)
    s = f"{schema}.{prefix}"
    p = prefix
    count_cols = [
        Column(key, Numeric(10, 2) if key == "avg_readiness_score" else BigInteger)
        for key in COUNT_KEYS
    ]
    totals = Table(
        f"{p}totals",
        md,
        Column("scan_id", Integer, primary_key=True, autoincrement=True),
        Column("source", Text),
        Column("mode", String(20)),
        Column("cloud", String(20)),
        Column("workspace_id", String(64)),
        Column("metastore", String(255)),
        Column("collectors", Text),
        Column("discovery_workbook", String(255)),
        Column("captured_at", String(40)),
        Column("discovered_at", String(40)),
        Column("created_at", DateTime(timezone=True), server_default=func.now()),
        *count_cols,
        *_owner(),
        Index(f"{p}ix_totals_org_job", "organization_id", "job_id"),
    )
    inventory = Table(
        f"{p}inventory",
        md,
        Column("inventory_id", Integer, primary_key=True, autoincrement=True),
        Column("scan_id", Integer, ForeignKey(f"{s}totals.scan_id"), nullable=False),
        Column("asset_key", Text, nullable=False),
        Column("asset_type", String(50)),
        Column("asset_name", Text, nullable=False),
        Column("location", Text),
        Column("fabric_target", String(255)),
        Column("readiness", String(20)),
        Column("readiness_score", Integer),
        Column("findings", Integer),
        Column("finding_ids", Text),
        Column("lines", Integer),
        Column("cells", Integer),
        Column("tasks", Integer),
        Column("columns", Integer),
        *_owner(),
        UniqueConstraint("scan_id", "asset_key", name=f"{p}inventory_scan_id_asset_key_key"),
        Index(f"{p}ix_inventory_org_job", "organization_id", "job_id"),
    )
    finding = Table(
        f"{p}finding",
        md,
        Column("finding_id", Integer, primary_key=True, autoincrement=True),
        Column("scan_id", Integer, ForeignKey(f"{s}totals.scan_id"), nullable=False),
        Column("inventory_id", Integer, ForeignKey(f"{s}inventory.inventory_id")),
        Column("asset_type", String(50)),
        Column("rule", String(100), nullable=False),
        Column("category", String(100)),
        Column("occurrences", Integer),
        Column("penalty", Integer),
        Column("support", String(20)),
        Column("guidance", Text),
        *_owner(),
        Index(f"{p}ix_finding_org_job", "organization_id", "job_id"),
    )
    estimation = Table(
        f"{p}estimation",
        md,
        Column("estimation_id", Integer, primary_key=True, autoincrement=True),
        Column("scan_id", Integer, ForeignKey(f"{s}totals.scan_id"), nullable=False),
        Column("inventory_id", Integer, ForeignKey(f"{s}inventory.inventory_id")),
        Column("asset_name", Text, nullable=False),
        Column("asset_type", String(50)),
        Column("location", Text),
        Column("total_constructs", Integer),
        Column("supported", _HOURS),
        Column("unsupported", _HOURS),
        Column("complexity_score", Integer),
        Column("complexity_level", String(20)),
        Column("recommended_target", String(255)),
        Column("automation_level", String(30)),
        Column("readiness", String(20)),
        Column("manual_dev_hours", _HOURS),
        Column("manual_test_hours", _HOURS),
        Column("automation_dev_hours", _HOURS),
        Column("automation_test_hours", _HOURS),
        Column("hours_saved", _HOURS),
        *_owner(),
        UniqueConstraint("scan_id", "inventory_id", name=f"{p}estimation_scan_id_inventory_id_key"),
        Index(f"{p}ix_estimation_org_job", "organization_id", "job_id"),
    )
    computation = Table(
        f"{p}computation",
        md,
        Column("computation_id", Integer, primary_key=True, autoincrement=True),
        Column("scan_id", Integer, ForeignKey(f"{s}totals.scan_id"), nullable=False,
               unique=True),
        Column("assessment_generated_at", DateTime(timezone=True)),
        Column("total_assets", Integer),
        Column("total_constructs", Integer),
        Column("supported_constructs", _HOURS),
        Column("unsupported_constructs", _HOURS),
        Column("simple_count", Integer),
        Column("medium_count", Integer),
        Column("complex_count", Integer),
        Column("fully_automated", Integer),
        Column("partially_automated", Integer),
        Column("manual", Integer),
        Column("manual_dev_hours", _HOURS),
        Column("manual_test_hours", _HOURS),
        Column("total_manual_hours", _HOURS),
        Column("automation_dev_hours", _HOURS),
        Column("automation_test_hours", _HOURS),
        Column("total_automation_hours", _HOURS),
        Column("hours_saved", _HOURS),
        Column("saving_pct", _HOURS),
        Column("rules_version", String(255)),
        *_owner(),
        Index(f"{p}ix_computation_org_job", "organization_id", "job_id"),
    )  # fmt: skip
    return DbTables(
        md,
        {
            "totals": totals,
            "inventory": inventory,
            "finding": finding,
            "estimation": estimation,
            "computation": computation,
        },
    )
