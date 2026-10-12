from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from dbx_premig.config import Settings, load_settings
from dbx_premig.db.engine import ddl_sql, describe_target, get_engine
from dbx_premig.db.persist import persist_assessment
from dbx_premig.errors import ConfigError, DatabaseError
from dbx_premig.service import run_analysis
from tests.conftest import SNAPSHOT

MIGRATION = Path(__file__).parent.parent / "dbx_premig" / "db" / "migrations" / "0001_initial.sql"


def test_migration_file_matches_schema() -> None:
    assert MIGRATION.read_text() == ddl_sql("databricks_to_fabric_premigration")


def test_describe_target_hides_credentials() -> None:
    s = load_settings(database_url=SecretStr("postgresql://u:secret@db.example.com:6543/premig"))
    assert describe_target(s) == "db.example.com:6543/premig"
    assert describe_target(load_settings()) == "(not configured)"


def test_no_database_configured() -> None:
    with pytest.raises(DatabaseError, match="DBXF_DATABASE_URL"):
        get_engine(load_settings())


def test_schema_name_is_an_identifier() -> None:
    with pytest.raises(ConfigError):
        load_settings(db_schema='x"; drop table y; --')


def test_unreachable_database_is_a_clean_error(tmp_path: Path, settings: Settings) -> None:
    run = run_analysis(settings, input_path=SNAPSHOT, output_dir=tmp_path)
    s = load_settings(database_url=SecretStr("postgresql://u:pw@127.0.0.1:9/none"))
    with pytest.raises(DatabaseError) as exc:
        persist_assessment(run.result, s, organization_id="o", job_id="j")
    assert "pw" not in exc.value.message
    with pytest.raises(DatabaseError, match="required"):
        persist_assessment(run.result, s, organization_id="", job_id="j")


@pytest.mark.database
def test_persist_and_replace(tmp_path: Path, pg_settings: Settings) -> None:
    run = run_analysis(pg_settings, input_path=SNAPSHOT, output_dir=tmp_path)
    first = persist_assessment(run.result, pg_settings, organization_id="o1", job_id="j1")
    assert first.rows == {"totals": 1, "inventory": 41, "finding": 70, "estimation": 41,
                          "computation": 1}  # fmt: skip
    other = persist_assessment(run.result, pg_settings, organization_id="o1", job_id="j2")
    again = persist_assessment(run.result, pg_settings, organization_id="o1", job_id="j1")
    assert again.replaced_scans == 1 and again.scan_id not in (first.scan_id, other.scan_id)
    engine = get_engine(pg_settings)
    schema = pg_settings.db_schema
    with engine.connect() as conn:

        def q(sql: str) -> list[tuple[object, ...]]:
            return [tuple(r) for r in conn.execute(sa.text(sql.replace("S.", f"{schema}.")))]

        assert q("select count(*) from S.totals") == [(2,)]
        assert q("select count(*) from S.estimation where job_id='j1'") == [(41,)]
        c = run.result.computation
        row = q("select total_assets, complex_count, total_manual_hours, saving_pct "
                "from S.computation where job_id='j1'")[0]  # fmt: skip
        assert row[0] == c.total_assets and row[1] == c.complex_count
        assert float(row[2]) == pytest.approx(c.total_manual_hours)  # type: ignore[arg-type]
        assert float(row[3]) == pytest.approx(c.saving_pct)  # type: ignore[arg-type]
        # every estimation row points at its inventory row
        assert q(
            "select count(*) from S.estimation e join S.inventory i "
            "on e.inventory_id = i.inventory_id and i.asset_name = e.asset_name"
        ) == [(82,)]
        totals = q("select notebooks, columns, assessable_assets from S.totals where job_id='j1'")
        assert totals == [(6, 12, 41)]
    engine.dispose()


@pytest.mark.database
def test_db_init_is_idempotent(pg_settings: Settings) -> None:
    from dbx_premig.db.engine import create_schema

    assert create_schema(pg_settings) == create_schema(pg_settings)


@pytest.mark.database
def test_value_too_long_is_reported(tmp_path: Path, pg_settings: Settings) -> None:
    run = run_analysis(pg_settings, input_path=SNAPSHOT, output_dir=tmp_path)
    with pytest.raises(DatabaseError, match="organization_id"):
        persist_assessment(run.result, pg_settings, organization_id="o" * 200, job_id="j")
