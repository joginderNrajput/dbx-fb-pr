"""Alembic environment.

Used two ways, both reading the database from the tool's settings (``DBXF_DATABASE_URL``,
``.env``) — ``alembic.ini`` holds no URL:

* ``python discovery.py db-init`` (or the API with ``DBXF_DB_AUTO_MIGRATE=true``) calls
  ``engine.migrate()``, which passes the settings and an open connection in
  ``config.attributes``;
* ``alembic upgrade head`` from the repository root (``alembic.ini``) loads the settings
  itself.

The version table is ``dbx_premig_alembic_version`` (``<prefix>alembic_version`` with a table
prefix) in the target schema, so it never mixes with another tool's ``alembic_version``.
"""

from __future__ import annotations

from alembic import context

from dbx_premig.config import Settings, load_settings
from dbx_premig.db.engine import version_table
from dbx_premig.db.schema import build_tables

__all__: list[str] = []

config = context.config
settings: Settings = config.attributes.get("settings") or load_settings()
config.attributes.setdefault("schema", settings.db_schema)
config.attributes.setdefault("prefix", settings.db_table_prefix)
SCHEMA = config.attributes["schema"]
VERSION_TABLE = version_table(config.attributes["prefix"])
target_metadata = build_tables(SCHEMA, config.attributes["prefix"]).metadata


def _offline() -> None:
    """Emit SQL instead of running it (``db-init --print-sql`` / ``alembic upgrade --sql``)."""
    context.configure(
        dialect_name="postgresql",
        literal_binds=True,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        context.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
        context.run_migrations()


def _online() -> None:
    import sqlalchemy as sa

    from dbx_premig.db.engine import get_engine

    connection = config.attributes.get("connection")
    engine = None
    if connection is None:
        engine = get_engine(settings)
        connection = engine.connect()
    try:
        if not sa.inspect(connection).has_schema(SCHEMA):
            connection.execute(sa.text(f'CREATE SCHEMA "{SCHEMA}"'))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
            version_table_schema=SCHEMA,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if engine is not None:
            connection.close()
            engine.dispose()


if context.is_offline_mode():
    _offline()
else:
    _online()
