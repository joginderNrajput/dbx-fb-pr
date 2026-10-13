"""Settings: every threshold, cap and knob lives here.

Precedence, lowest first: code defaults -> ``--config file.yaml|toml`` -> ``DBXF_*``
environment variables -> CLI flags (applied with ``model_copy``).
"""

from __future__ import annotations

import re
import tomllib
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from dbx_premig.errors import ConfigError

__all__ = ["ALL_COLLECTORS", "Settings", "get_settings", "load_settings"]

#: Every live collector, in the order they run. ``--only`` selects a subset.
ALL_COLLECTORS: tuple[str, ...] = (
    "workspace",
    "notebooks",
    "repos",
    "jobs",
    "pipelines",
    "clusters",
    "instance_pools",
    "cluster_policies",
    "warehouses",
    "unity_catalog",
    "functions",
    "grants",
    "queries",
    "dashboards",
    "alerts",
    "models",
    "serving_endpoints",
    "experiments",
    "libraries",
    "secrets",
    "mounts",
    "identities",
)


class Settings(BaseSettings):
    """Runtime configuration. Environment variables use the ``DBXF_`` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="DBXF_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        frozen=True,
    )

    # ------------------------------------------------------------------ connection
    host: str | None = None
    """Workspace URL, e.g. https://adb-123.4.azuredatabricks.net (falls back to DATABRICKS_HOST)."""
    token: SecretStr | None = None
    """Personal access token (falls back to DATABRICKS_TOKEN). Never logged."""
    client_id: str | None = None
    """Service-principal OAuth client id (machine-to-machine auth)."""
    client_secret: SecretStr | None = None
    """Service-principal OAuth secret. Never logged."""
    profile: str | None = None
    """Profile name in ~/.databrickscfg to read host/token from."""
    request_timeout_s: Annotated[float, Field(gt=0, le=600)] = 90.0
    """Timeout for one REST call."""
    max_retries: Annotated[int, Field(ge=0, le=10)] = 4
    """Retries for 429 / 5xx / network errors (exponential back-off)."""
    retry_backoff_s: Annotated[float, Field(ge=0, le=60)] = 1.0
    """Base back-off; attempt n waits base * 2**n seconds."""
    page_size: Annotated[int, Field(ge=1, le=1000)] = 100
    """Page size requested from list endpoints that accept one."""
    verify_tls: bool = True
    """Verify the workspace TLS certificate. Only switch off for a lab behind a TLS proxy."""

    # ------------------------------------------------------------------ scope
    collectors: tuple[str, ...] = ALL_COLLECTORS
    """Which live collectors run (``--only``)."""
    catalogs: tuple[str, ...] = ()
    """Limit Unity Catalog collection to these catalogs (empty = all)."""
    schemas: tuple[str, ...] = ()
    """Limit Unity Catalog collection to these schemas: ``catalog.schema`` or a bare schema
    name matched in every collected catalog (empty = all)."""
    skip_catalogs: tuple[str, ...] = ("system", "samples", "__databricks_internal")
    """Catalogs never collected."""
    include_hive_metastore: bool = True
    """Collect legacy hive_metastore tables when Unity Catalog lists them."""
    skip_repos: bool = False
    """Skip /Repos when walking the workspace tree."""
    include_columns: bool = True
    """Write the Columns sheet (one row per table column)."""
    include_view_definitions: bool = True
    """Write view SQL to the Views sheet."""
    include_grants: bool = True
    """Collect Unity Catalog grants on catalogs and schemas."""

    # ------------------------------------------------------------------ safety caps
    max_notebooks: Annotated[int, Field(ge=1)] = 5000
    """Stop exporting notebooks after this many."""
    max_notebook_bytes: Annotated[int, Field(ge=1024)] = 5_000_000
    """Notebooks larger than this are inventoried but not scanned."""
    max_file_bytes: Annotated[int, Field(ge=1024)] = 50_000_000
    """Largest offline file read."""
    max_archive_entries: Annotated[int, Field(ge=1)] = 20_000
    """Most members accepted in one .zip / .dbc archive."""
    max_archive_bytes: Annotated[int, Field(ge=1024)] = 500_000_000
    """Largest total uncompressed size of one archive."""
    max_archive_ratio: Annotated[float, Field(gt=1)] = 200.0
    """Largest compression ratio of an archive member (zip-bomb guard)."""
    max_cell_chars: Annotated[int, Field(ge=100, le=32_767)] = 32_000
    """Longest text written to one Excel cell (Excel's limit is 32,767)."""

    # ------------------------------------------------------------------ readiness thresholds
    readiness_compatible_min: Annotated[int, Field(ge=0, le=100)] = 80
    """Readiness score at or above which an asset is Compatible."""
    readiness_partial_min: Annotated[int, Field(ge=0, le=100)] = 50
    """Readiness score at or above which an asset is Partial (below: Manual)."""
    occurrence_cap: Annotated[int, Field(ge=1)] = 10
    """Occurrences of one code feature beyond this add no more weight."""

    # ------------------------------------------------------------------ assessment
    assessment_rules: Path | None = None
    """Assessment rules file (complexity / automation / effort formulas). None = bundled."""

    # ------------------------------------------------------------------ API
    api_host: str = "127.0.0.1"
    """Listening address of the API server."""
    api_port: Annotated[int, Field(ge=1, le=65535)] = 7073
    """Listening port of the API server."""
    api_key: SecretStr | None = None
    """When set, every /v1 request must send it in the X-API-Key header."""
    api_work_dir: Path = Path("api_runs")
    """Where the API keeps uploaded files and generated workbooks of each run."""
    api_run_ttl_s: Annotated[int, Field(ge=60)] = 24 * 3600
    """How long a finished run (and its workbooks) stays downloadable; then 410 Gone."""
    api_max_workers: Annotated[int, Field(ge=1, le=32)] = 2
    """Runs executed in parallel by the API."""
    max_upload_bytes: Annotated[int, Field(ge=1024)] = 100_000_000
    """Largest discovery workbook accepted by the API (checked while streaming)."""
    cors_origins: tuple[str, ...] = ()
    """Origins allowed by CORS (empty = CORS off)."""

    # ------------------------------------------------------------------ database (optional)
    database_url: SecretStr | None = None
    """Postgres URL (postgresql+psycopg://user:pass@host:5432/db). Unset = no persistence."""
    db_schema: str = "databricks_to_fabric_premigration"
    """Postgres schema holding the discovery / assessment tables. Created by the migration if
    missing (the role then needs CREATE on the database)."""
    db_table_prefix: str = ""
    """Put in front of every table / index name, e.g. "dbx_" when the schema already holds
    another accelerator's totals / inventory / estimation / computation tables."""
    db_sslmode: str | None = None
    """libpq sslmode. None = "require" for remote hosts (Azure Database for PostgreSQL needs
    TLS) and "prefer" for localhost. An sslmode in the URL always wins."""
    db_connect_timeout_s: Annotated[int, Field(ge=1, le=300)] = 15
    """Seconds to wait for the database server to answer."""
    db_auto_migrate: bool = False
    """When true, the API applies the Alembic migrations (alembic upgrade head) at start-up."""

    # ------------------------------------------------------------------ logging
    log_level: str = "WARNING"
    """Console log level (``-v`` raises it to INFO)."""

    @field_validator("host")
    @classmethod
    def _normalise_host(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("https://", "http://")):
            value = "https://" + value
        return value

    @field_validator("db_schema")
    @classmethod
    def _schema_identifier(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
            raise ValueError("db_schema must be a lower-case SQL identifier")
        return value

    @field_validator("db_table_prefix")
    @classmethod
    def _prefix_identifier(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z_][a-z0-9_]{0,20}", value):
            raise ValueError("db_table_prefix must be lower-case letters, digits and _")
        return value

    @field_validator("db_sslmode")
    @classmethod
    def _sslmode(cls, value: str | None) -> str | None:
        modes = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        if value is not None and value not in modes:
            raise ValueError(f"db_sslmode must be one of {', '.join(sorted(modes))}")
        return value

    @field_validator("collectors")
    @classmethod
    def _known_collectors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(ALL_COLLECTORS))
        if unknown:
            raise ValueError(f"unknown collector(s): {', '.join(unknown)}")
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # First wins: CLI flags (init kwargs) > environment > .env > --config file > defaults.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _ConfigFileSource(settings_cls),
            file_secret_settings,
        )


#: Values of the --config file for the Settings() call in progress (see load_settings).
_CONFIG_FILE_VALUES: ContextVar[dict[str, Any] | None] = ContextVar(
    "dbxf_config_file", default=None
)


class _ConfigFileSource(PydanticBaseSettingsSource):
    """The ``--config`` YAML/TOML file, ranked below the environment."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return (_CONFIG_FILE_VALUES.get() or {}).get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(_CONFIG_FILE_VALUES.get() or {})


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"Cannot read the configuration file {path.name}.") from exc
    try:
        if path.suffix.lower() == ".toml":
            data: Any = tomllib.loads(raw.decode("utf-8"))
        elif path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(raw) or {}
        else:
            raise ConfigError(f"Configuration file {path.name} must be .yaml, .yml or .toml.")
    except (tomllib.TOMLDecodeError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Configuration file {path.name} is not valid.") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration file {path.name} must hold a mapping at the top.")
    return data


def load_settings(config_file: Path | None = None, **overrides: Any) -> Settings:
    """Build settings from defaults, an optional file, the environment and explicit overrides."""
    file_values = _read_config_file(config_file) if config_file else {}
    flags = {k: v for k, v in overrides.items() if v is not None}
    token = _CONFIG_FILE_VALUES.set(file_values)
    try:
        settings = Settings(**flags)
    except ValidationError as exc:
        fields = ", ".join(str(err["loc"][0]) for err in exc.errors() if err["loc"])
        raise ConfigError(f"Invalid setting(s): {fields or 'unknown'}.", detail=str(exc)) from exc
    finally:
        _CONFIG_FILE_VALUES.reset(token)
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide default settings (defaults + environment)."""
    return load_settings()
