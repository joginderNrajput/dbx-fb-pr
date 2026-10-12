"""Engine creation, schema DDL and the one function allowed to render the database URL."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dbx_premig.config import Settings
from dbx_premig.errors import DatabaseError

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

__all__ = ["create_schema", "ddl_sql", "describe_target", "get_engine"]


def _sqlalchemy() -> Any:
    try:
        import sqlalchemy
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise DatabaseError(
            "Database support is not installed: pip install 'dbx-premig[postgres]'."
        ) from exc
    return sqlalchemy


def describe_target(settings: Settings) -> str:
    """host:port/database of the configured URL; never the credentials."""
    if settings.database_url is None:
        return "(not configured)"
    sa = _sqlalchemy()
    try:
        url = sa.engine.make_url(settings.database_url.get_secret_value())
    except Exception:
        return "(invalid URL)"
    return f"{url.host or 'localhost'}:{url.port or 5432}/{url.database or ''}"


def get_engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise DatabaseError("No database configured: set DBXF_DATABASE_URL.")
    sa = _sqlalchemy()
    raw = settings.database_url.get_secret_value()
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    try:
        engine: Engine = sa.create_engine(raw, pool_pre_ping=True, future=True)
    except Exception as exc:
        raise DatabaseError(
            f"Invalid database URL for {describe_target(settings)} ({type(exc).__name__})."
        ) from None
    return engine


def ddl_sql(schema: str) -> str:
    """CREATE SCHEMA / TABLE / INDEX statements for Postgres (the migration file)."""
    _sqlalchemy()
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from dbx_premig.db.schema import build_tables

    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    tables = build_tables(schema)
    parts = [f"CREATE SCHEMA IF NOT EXISTS {schema};"]
    for table in tables.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: str(i.name)):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return "\n\n".join(parts) + "\n"


def create_schema(settings: Settings) -> str:
    """Create the schema and any missing table (existing tables are never altered)."""
    sa = _sqlalchemy()
    from dbx_premig.db.schema import build_tables

    engine = get_engine(settings)
    tables = build_tables(settings.db_schema)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))
            tables.metadata.create_all(conn, checkfirst=True)
    except sa.exc.SQLAlchemyError as exc:
        raise DatabaseError(
            f"Could not create the tables on {describe_target(settings)} ({type(exc).__name__})."
        ) from None
    finally:
        engine.dispose()
    return describe_target(settings)
