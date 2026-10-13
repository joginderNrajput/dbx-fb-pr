"""Engine creation, Alembic migrations and the one function allowed to render the DB URL."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from dbx_premig.config import Settings
from dbx_premig.errors import DatabaseError

if TYPE_CHECKING:
    from alembic.config import Config
    from sqlalchemy.engine import Engine

__all__ = [
    "MIGRATED_TABLES",
    "current_revision",
    "ddl_sql",
    "describe_target",
    "get_engine",
    "migrate",
    "sslmode_for",
    "version_table",
]

#: Tables created by the migrations (without the prefix).
MIGRATED_TABLES = ("totals", "inventory", "finding", "estimation", "computation")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "", None}


def _sqlalchemy() -> Any:
    try:
        import sqlalchemy
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise DatabaseError(
            "Database support is not installed: pip install 'dbx-premig[postgres]'."
        ) from exc
    return sqlalchemy


def _url(settings: Settings) -> Any:
    sa = _sqlalchemy()
    assert settings.database_url is not None
    raw = settings.database_url.get_secret_value()
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return sa.engine.make_url(raw)


def describe_target(settings: Settings) -> str:
    """host:port/database of the configured URL; never the credentials."""
    if settings.database_url is None:
        return "(not configured)"
    try:
        url = _url(settings)
    except Exception:
        return "(invalid URL)"
    return f"{url.host or 'localhost'}:{url.port or 5432}/{url.database or ''}"


def sslmode_for(settings: Settings) -> str | None:
    """sslmode to request: the setting, else "require" for remote hosts (Azure needs TLS),
    "prefer" for localhost. None when the URL already carries an sslmode (it wins)."""
    url = _url(settings)
    if "sslmode" in url.query:
        return None
    if settings.db_sslmode:
        return settings.db_sslmode
    return "prefer" if url.host in _LOCAL_HOSTS else "require"


def get_engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise DatabaseError("No database configured: set DBXF_DATABASE_URL (for example in .env).")
    sa = _sqlalchemy()
    try:
        url = _url(settings)
        connect_args: dict[str, Any] = {"connect_timeout": settings.db_connect_timeout_s}
        mode = sslmode_for(settings)
        if mode:
            connect_args["sslmode"] = mode
        engine: Engine = sa.create_engine(
            url, pool_pre_ping=True, future=True, connect_args=connect_args
        )
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError(
            f"Invalid database URL for {describe_target(settings)} ({type(exc).__name__})."
        ) from None
    return engine


def _alembic_config(settings: Settings) -> Config:
    try:
        from alembic.config import Config
    except ImportError as exc:  # pragma: no cover - depends on the installed extras
        raise DatabaseError(
            "Alembic is not installed: pip install 'dbx-premig[postgres]'."
        ) from exc
    from dbx_premig.resources import migrations_path

    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_path()))
    cfg.attributes["settings"] = settings
    cfg.attributes["schema"] = settings.db_schema
    cfg.attributes["prefix"] = settings.db_table_prefix
    return cfg


def version_table(prefix: str) -> str:
    """Our Alembic version table: never the shared name ``alembic_version``."""
    return f"{prefix}alembic_version" if prefix else "dbx_premig_alembic_version"


def _version_table(settings: Settings) -> str:
    return version_table(settings.db_table_prefix)


def _guard_foreign_tables(conn: Any, settings: Settings) -> None:
    """Refuse to migrate over same-named tables this tool did not create (shared schema)."""
    sa = _sqlalchemy()
    inspector = sa.inspect(conn)
    schema = settings.db_schema
    if not inspector.has_schema(schema):
        return
    existing = set(inspector.get_table_names(schema=schema))
    if _version_table(settings) in existing:
        return  # our own tables: Alembic knows where they are
    p = settings.db_table_prefix
    clash = sorted(f"{p}{t}" for t in MIGRATED_TABLES if f"{p}{t}" in existing)
    if clash:
        raise DatabaseError(
            f"Schema {schema} already has table(s) {', '.join(clash)} that this tool did not "
            "create (another accelerator's?). Nothing was changed. Set DBXF_DB_TABLE_PREFIX "
            "(e.g. dbx_) or DBXF_DB_SCHEMA to a different schema, then run db-init again."
        )


def migrate(settings: Settings, revision: str = "head") -> str:
    """Apply the Alembic migrations (``alembic upgrade head``). Returns the new revision."""
    sa = _sqlalchemy()
    from alembic import command

    engine = get_engine(settings)
    cfg = _alembic_config(settings)
    try:
        with engine.connect() as conn:
            _guard_foreign_tables(conn, settings)
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, revision)
            conn.commit()
            return _current(conn, settings) or "(none)"
    except DatabaseError:
        raise
    except sa.exc.SQLAlchemyError as exc:
        raise DatabaseError(
            f"Migrating {describe_target(settings)} failed ({type(exc).__name__}): check the "
            "URL, the network / firewall rules and that the role may create tables in "
            f"schema {settings.db_schema}."
        ) from None
    finally:
        engine.dispose()


def _current(conn: Any, settings: Settings) -> str | None:
    from alembic.runtime.migration import MigrationContext

    ctx = MigrationContext.configure(
        conn,
        opts={
            "version_table": _version_table(settings),
            "version_table_schema": settings.db_schema,
        },
    )
    return ctx.get_current_revision()


def current_revision(settings: Settings) -> str | None:
    """The revision the database is at (None: not migrated yet)."""
    sa = _sqlalchemy()
    engine = get_engine(settings)
    try:
        with engine.connect() as conn:
            return _current(conn, settings)
    except sa.exc.SQLAlchemyError as exc:
        raise DatabaseError(
            f"Cannot read the migration state of {describe_target(settings)} "
            f"({type(exc).__name__})."
        ) from None
    finally:
        engine.dispose()


def ddl_sql(settings: Settings) -> str:
    """The SQL the migrations would run (Alembic offline mode); needs no database."""
    from alembic import command

    cfg = _alembic_config(settings)
    buffer = io.StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, "head", sql=True)
    return buffer.getvalue()
