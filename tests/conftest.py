"""Shared fixtures. Neutralises DBXF_* / DATABRICKS_* variables AND the .env file, so a
developer's environment can never change the suite."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dbx_premig.config import Settings, get_settings, load_settings
from dbx_premig.models import DiscoveryReport, RawSnapshot

FIXTURES = Path(__file__).parent / "fixtures"
MINI = FIXTURES / "mini"
SNAPSHOT = MINI / "snapshot.json"
NOTEBOOKS = MINI / "notebooks"
FIXED_CLOCK = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-slow", action="store_true", default=False, help="run slow tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-slow"):
        return
    skip = pytest.mark.skip(reason="slow: use --run-slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith(("DBXF_", "DATABRICKS_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(tmp_path / "no-databrickscfg"))
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return load_settings()


@pytest.fixture
def snapshot(settings: Settings) -> RawSnapshot:
    from dbx_premig.reader import read_snapshot

    return read_snapshot(SNAPSHOT, settings)


@pytest.fixture
def report(snapshot: RawSnapshot, settings: Settings) -> DiscoveryReport:
    from dbx_premig.service import build_report

    return build_report(snapshot, settings, generated_at=FIXED_CLOCK)


#: Postgres for the `database` tests: DBXF_TEST_DATABASE_URL (skipped when unset).
_TEST_DB = os.environ.get("DBXF_TEST_DATABASE_URL")


@pytest.fixture
def pg_settings(tmp_path: Path) -> Iterator[Settings]:
    """Settings on a fresh schema of the test database (dropped afterwards)."""
    if not _TEST_DB:
        pytest.skip("set DBXF_TEST_DATABASE_URL to run the Postgres tests")
    import uuid

    from pydantic import SecretStr

    from dbx_premig.db.engine import migrate

    schema = f"t_{uuid.uuid4().hex[:10]}"
    settings = load_settings(database_url=SecretStr(_TEST_DB), db_schema=schema)
    migrate(settings)
    yield settings
    from dbx_premig.db.engine import get_engine

    engine = get_engine(settings)
    import sqlalchemy as sa

    with engine.begin() as conn:
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()
