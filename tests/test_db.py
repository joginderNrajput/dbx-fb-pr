from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from dbx_premig.config import Settings, load_settings
from dbx_premig.db.engine import (
    MIGRATED_TABLES,
    ddl_sql,
    describe_target,
    get_engine,
    migrate,
    sslmode_for,
)
from dbx_premig.db.persist import persist_assessment
from dbx_premig.errors import ConfigError, DatabaseError
from dbx_premig.service import run_analysis
from tests.conftest import SNAPSHOT


def test_offline_sql_creates_every_table() -> None:
    sql = ddl_sql(load_settings())
    for table in MIGRATED_TABLES:
        assert f"CREATE TABLE databricks_to_fabric_premigration.{table} (" in sql
    assert "databricks_to_fabric_premigration.dbx_premig_alembic_version" in sql
    prefixed = ddl_sql(load_settings(db_schema="shared", db_table_prefix="dbx_"))
    assert "CREATE TABLE shared.dbx_totals (" in prefixed
    assert "shared.dbx_alembic_version" in prefixed and "shared.totals (" not in prefixed


@pytest.mark.parametrize(
    ("url", "setting", "expected"),
    [
        ("postgresql+psycopg://u:p@localhost:5432/db", None, "prefer"),
        ("postgresql+psycopg://u:p@srv.postgres.database.azure.com:5432/db", None, "require"),
        ("postgresql://u:p@srv.postgres.database.azure.com/db?sslmode=verify-full", None, None),
        ("postgresql+psycopg://u:p@localhost/db", "disable", "disable"),
    ],
)
def test_sslmode(url: str, setting: str | None, expected: str | None) -> None:
    s = load_settings(database_url=SecretStr(url), db_sslmode=setting)
    assert sslmode_for(s) == expected


def test_db_setting_validation() -> None:
    with pytest.raises(ConfigError):
        load_settings(db_table_prefix="Bad-Prefix")
    with pytest.raises(ConfigError):
        load_settings(db_sslmode="sometimes")


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
    assert migrate(pg_settings) == migrate(pg_settings) == "0001"


@pytest.mark.database
def test_migrated_database_matches_the_models(pg_settings: Settings) -> None:
    """No drift between the Alembic revisions and db/schema.py."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from dbx_premig.db.schema import build_tables

    engine = get_engine(pg_settings)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"include_schemas": True, "include_name": lambda name, type_, _p: (
                type_ != "schema" or name == pg_settings.db_schema)},
        )  # fmt: skip
        diff = compare_metadata(ctx, build_tables(pg_settings.db_schema).metadata)
    engine.dispose()
    diff = [d for d in diff if "alembic_version" not in str(d)]
    assert diff == []


@pytest.mark.database
def test_shared_schema_guard_and_prefix(tmp_path: Path, pg_settings: Settings) -> None:
    """A schema holding another tool's 'totals' is never touched; a prefix side-steps it."""
    import uuid

    engine = get_engine(pg_settings)
    schema = f"s_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(sa.text(f'CREATE TABLE "{schema}".totals (total_workflows int)'))
        conn.execute(sa.text(f'CREATE TABLE "{schema}".alembic_version (version_num text)'))
        conn.execute(sa.text(f"INSERT INTO \"{schema}\".alembic_version VALUES ('alteryx1')"))
    try:
        shared = pg_settings.model_copy(update={"db_schema": schema})
        with pytest.raises(DatabaseError, match="did not create"):
            migrate(shared)
        prefixed = shared.model_copy(update={"db_table_prefix": "dbx_"})
        assert migrate(prefixed) == "0001"
        run = run_analysis(prefixed, input_path=SNAPSHOT, output_dir=tmp_path)
        out = persist_assessment(run.result, prefixed, organization_id="o", job_id="j")
        assert out.rows["estimation"] == 41
        with engine.connect() as conn:
            names = {r[0] for r in conn.execute(sa.text(
                "select table_name from information_schema.tables where table_schema = :s"),
                {"s": schema})}  # fmt: skip
            other = conn.execute(sa.text(f'select * from "{schema}".alembic_version')).all()
        assert {f"dbx_{t}" for t in MIGRATED_TABLES} <= names and "totals" in names
        assert other == [("alteryx1",)]  # the other tool's migration state is untouched
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.database
def test_downgrade_removes_the_tables(pg_settings: Settings) -> None:
    from alembic import command

    from dbx_premig.db.engine import _alembic_config, current_revision

    engine = get_engine(pg_settings)
    with engine.connect() as conn:
        cfg = _alembic_config(pg_settings)
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
        conn.commit()
        left = set(sa.inspect(conn).get_table_names(schema=pg_settings.db_schema))
    engine.dispose()
    assert not left & set(MIGRATED_TABLES)
    assert current_revision(pg_settings) is None
    assert migrate(pg_settings) == "0001"


@pytest.mark.database
def test_value_too_long_is_reported(tmp_path: Path, pg_settings: Settings) -> None:
    run = run_analysis(pg_settings, input_path=SNAPSHOT, output_dir=tmp_path)
    with pytest.raises(DatabaseError, match="organization_id"):
        persist_assessment(run.result, pg_settings, organization_id="o" * 200, job_id="j")
