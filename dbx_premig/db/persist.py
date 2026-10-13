"""Write one assessment (with its discovery) to Postgres in a single transaction.

Order: delete the previous rows of the same (organization_id, job_id) children first, then
insert totals -> inventory (RETURNING ids) -> finding -> estimation -> computation. A failure
rolls everything back. Values longer than a VARCHAR column are rejected with a message that
names the table, column, limit and length (never the value).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dbx_premig.config import Settings
from dbx_premig.errors import DatabaseError
from dbx_premig.logging import get_logger
from dbx_premig.models import AssessmentResult

__all__ = ["PersistOutcome", "persist_assessment"]

log = get_logger("db")


@dataclass(frozen=True)
class PersistOutcome:
    scan_id: int
    target: str
    rows: dict[str, int]
    replaced_scans: int


def _check_lengths(table: Any, rows: list[dict[str, Any]]) -> None:
    limits = {
        c.name: c.type.length
        for c in table.columns
        if getattr(c.type, "length", None) and c.type.__class__.__name__ == "String"
    }
    for row in rows:
        for name, limit in limits.items():
            value = row.get(name)
            if isinstance(value, str) and len(value) > limit:
                raise DatabaseError(
                    f"Value too long for {table.name}.{name}: limit {limit}, got {len(value)}."
                )


def _metric(metrics: dict[str, float], key: str) -> int | None:
    value = metrics.get(key)
    return int(value) if value is not None else None


def persist_assessment(
    result: AssessmentResult, settings: Settings, *, organization_id: str, job_id: str
) -> PersistOutcome:
    """Replace the rows of (organization_id, job_id) with this result. Raises DatabaseError."""
    import sqlalchemy as sa

    from dbx_premig.db.engine import describe_target, get_engine
    from dbx_premig.db.schema import build_tables

    if not organization_id or not job_id:
        raise DatabaseError("organization_id and job_id are both required to persist.")
    t = build_tables(settings.db_schema, settings.db_table_prefix)
    owner = {"organization_id": organization_id, "job_id": job_id}
    dw = result.discovery
    scan = dw.scan
    engine = get_engine(settings)
    counts: dict[str, int] = {}
    try:
        with engine.begin() as conn:
            old = [
                row[0]
                for row in conn.execute(
                    sa.select(t.totals.c.scan_id).where(
                        t.totals.c.organization_id == organization_id,
                        t.totals.c.job_id == job_id,
                    )
                )
            ]
            if old:
                for table in t.children_first:
                    conn.execute(
                        table.delete().where(
                            table.c.scan_id.in_(old),
                            table.c.organization_id == organization_id,
                            table.c.job_id == job_id,
                        )
                    )

            totals_row: dict[str, Any] = {
                "source": scan.source,
                "mode": scan.mode,
                "cloud": scan.cloud,
                "workspace_id": scan.workspace_id,
                "metastore": scan.metastore,
                "collectors": ", ".join(scan.collectors),
                "discovery_workbook": dw.file_name,
                "captured_at": scan.captured_at,
                "discovered_at": scan.generated_at,
                **{
                    k: (round(v, 2) if k == "avg_readiness_score" else int(v))
                    for k, v in dw.counts.items()
                },
                **owner,
            }
            _check_lengths(t.totals, [totals_row])
            scan_id = int(
                conn.execute(
                    t.totals.insert().returning(t.totals.c.scan_id), totals_row
                ).scalar_one()
            )
            counts["totals"] = 1

            inv_rows = [
                {
                    "scan_id": scan_id,
                    "asset_key": a.key,
                    "asset_type": a.asset_type,
                    "asset_name": a.name,
                    "location": a.location,
                    "fabric_target": a.fabric_target,
                    "readiness": a.readiness,
                    "readiness_score": a.readiness_score,
                    "findings": len(a.findings),
                    "finding_ids": ", ".join(f.feature_id for f in a.findings),
                    "lines": _metric(a.metrics, "lines"),
                    "cells": _metric(a.metrics, "cells"),
                    "tasks": _metric(a.metrics, "tasks"),
                    "columns": _metric(a.metrics, "columns"),
                    **owner,
                }
                for a in dw.assets
            ]
            ids: dict[str, int] = {}
            if inv_rows:
                _check_lengths(t.inventory, inv_rows)
                returned = conn.execute(
                    t.inventory.insert().returning(
                        t.inventory.c.inventory_id, t.inventory.c.asset_key,
                        sort_by_parameter_order=True,
                    ),
                    inv_rows,
                )  # fmt: skip
                ids = {key: int(iid) for iid, key in returned}
            counts["inventory"] = len(inv_rows)

            find_rows = [
                {
                    "scan_id": scan_id,
                    "inventory_id": ids.get(a.key),
                    "asset_type": a.asset_type,
                    "rule": f.feature_id,
                    "category": f.category,
                    "occurrences": f.occurrences,
                    "penalty": f.penalty,
                    "support": f.support,
                    "guidance": f.guidance,
                    **owner,
                }
                for a in dw.assets
                for f in a.findings
            ]
            if find_rows:
                _check_lengths(t.finding, find_rows)
                conn.execute(t.finding.insert(), find_rows)
            counts["finding"] = len(find_rows)

            est_rows = [
                {
                    "scan_id": scan_id,
                    "inventory_id": ids.get(e.asset_key),
                    "asset_name": e.asset_name,
                    "asset_type": e.asset_type,
                    "location": e.location,
                    "total_constructs": e.total_constructs,
                    "supported": e.supported,
                    "unsupported": e.unsupported,
                    "complexity_score": e.complexity_score,
                    "complexity_level": e.complexity_level,
                    "recommended_target": e.fabric_target,
                    "automation_level": e.automation_level,
                    "readiness": e.readiness,
                    "manual_dev_hours": e.manual_dev_hours,
                    "manual_test_hours": e.manual_test_hours,
                    "automation_dev_hours": e.automation_dev_hours,
                    "automation_test_hours": e.automation_test_hours,
                    "hours_saved": e.hours_saved,
                    **owner,
                }
                for e in result.estimations
            ]
            if est_rows:
                _check_lengths(t.estimation, est_rows)
                conn.execute(t.estimation.insert(), est_rows)
            counts["estimation"] = len(est_rows)

            comp = result.computation.model_dump()
            comp["assessment_generated_at"] = datetime.fromisoformat(
                comp["assessment_generated_at"]
            )
            comp_row = {"scan_id": scan_id, **comp, **owner}
            _check_lengths(t.computation, [comp_row])
            conn.execute(t.computation.insert(), comp_row)
            counts["computation"] = 1
    except DatabaseError:
        raise
    except sa.exc.SQLAlchemyError as exc:
        raise DatabaseError(
            f"Writing to {describe_target(settings)} failed ({type(exc).__name__}). "
            "Run 'db-init' if the tables do not exist yet."
        ) from None
    finally:
        engine.dispose()
    log.info("persisted scan %d to %s: %s", scan_id, describe_target(settings), counts)
    return PersistOutcome(
        scan_id=scan_id, target=describe_target(settings), rows=counts, replaced_scans=len(old)
    )
