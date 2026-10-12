"""Data estate (Unity Catalog / hive_metastore): catalogs down to columns, plus governance."""

from __future__ import annotations

from dbx_premig.excel.sheets.common import assessed_columns, yes_no
from dbx_premig.excel.types import Column, SheetSpec

__all__ = [
    "CATALOGS",
    "COLUMNS",
    "CONNECTIONS",
    "EXTERNAL_LOCATIONS",
    "FUNCTIONS",
    "GRANTS",
    "SCHEMAS",
    "STORAGE_CREDENTIALS",
    "TABLES",
    "VIEWS",
    "VOLUMES",
]

N = "#,##0"
_T = "'Tables'!$A$7:$A$1048576"
_TB = "'Tables'!$B$7:$B$1048576"
_TF = "'Tables'!$F$7:$F$1048576"

CATALOGS = SheetSpec(
    name="Catalogs",
    title="Catalogs  ·  Unity Catalog and hive_metastore",
    description=(
        "Catalogs collected (system, samples and internal catalogs are skipped). "
        "Schemas, Tables and Views are live counts of the sheets below."
    ),
    columns=[
        Column("Catalog", "name", 24),
        Column("Type", "catalog_type", 22),
        Column("Owner", "owner", 22),
        Column(
            "Schemas",
            formula="=COUNTIF('Schemas'!$A$7:$A$1048576,$A{r})",
            width=9,
            numeric=True,
            number_format=N,
        ),
        Column("Tables", formula=f"=COUNTIF({_T},$A{{r}})", width=9, numeric=True, number_format=N),
        Column(
            "Views",
            formula=f'=COUNTIFS({_T},$A{{r}},{_TF},"*VIEW")',
            width=9,
            numeric=True,
            number_format=N,
        ),
        Column("Storage root", "storage_root", 44),
        Column("Isolation mode", "isolation_mode", 12),
        Column("Created", "created_at", 16),
        Column("Comment", "comment", 30),
    ],
    rows=lambda r: r.estate.catalogs,
)

SCHEMAS = SheetSpec(
    name="Schemas",
    title="Schemas",
    description=(
        "Schemas per catalog with live counts of their tables, views, volumes and functions."
    ),
    columns=[
        Column("Catalog", "catalog", 22),
        Column("Schema", "schema_name", 24),
        Column("Full name", "full_name", 34),
        Column("Owner", "owner", 22),
        Column(
            "Tables",
            formula=f"=COUNTIFS({_T},$A{{r}},{_TB},$B{{r}})",
            width=9,
            numeric=True,
            number_format=N,
        ),
        Column(
            "Views",
            formula=f'=COUNTIFS({_T},$A{{r}},{_TB},$B{{r}},{_TF},"*VIEW")',
            width=9,
            numeric=True,
            number_format=N,
        ),
        Column(
            "Volumes",
            formula="=COUNTIFS('Volumes'!$B$7:$B$1048576,$A{r},'Volumes'!$C$7:$C$1048576,$B{r})",
            width=9,
            numeric=True,
            number_format=N,
        ),
        Column(
            "Functions",
            formula=(
                "=COUNTIFS('Functions'!$B$7:$B$1048576,$A{r},'Functions'!$C$7:$C$1048576,$B{r})"
            ),
            width=9,
            numeric=True,
            number_format=N,
        ),
        Column("Created", "created_at", 16),
        Column("Comment", "comment", 30),
    ],
    rows=lambda r: r.estate.schemas,
)

TABLES = SheetSpec(
    name="Tables",
    title="Tables and views  ·  one row per object",
    description=(
        "Every table, view, materialized view and streaming table: format, layout, Delta "
        "features, security and Fabric readiness."
    ),
    columns=[
        Column("Catalog", "catalog", 18),
        Column("Schema", "schema_name", 18),
        Column("Name", "name", 28),
        Column("Full name", "full_name", 40),
        Column("Object", lambda row, _r: _object_label(row.table_type), 16),
        Column("Table type", "table_type", 18),
        Column("Format", "data_format", 10),
        Column("Columns", "columns", 9, numeric=True, number_format=N),
        Column("Partition columns", "partition_columns", 20),
        Column("Storage location", "storage_location", 48),
        Column("Owner", "owner", 22),
        Column("Created", "created_at", 16),
        Column("Updated", "updated_at", 16),
        Column("Change data feed", yes_no("change_data_feed"), 10),
        Column("Deletion vectors", yes_no("deletion_vectors"), 10),
        Column("Row filter", yes_no("row_filter"), 9),
        Column("Column masks", "column_masks", 9, numeric=True, number_format=N),
        Column("Special types", "special_types", 16),
        Column("Comment", "comment", 30),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.tables,
    readiness_column="Readiness",
)


def _object_label(table_type: str) -> str:
    return {
        "MANAGED": "Table (managed)",
        "EXTERNAL": "Table (external)",
        "VIEW": "View",
        "MATERIALIZED_VIEW": "Materialized view",
        "STREAMING_TABLE": "Streaming table",
        "FOREIGN": "Foreign table",
    }.get(table_type, table_type.title() or "Table")


# Tables!F (Table type) is used by Catalogs / Schemas / Totals formulas: keep it in column F
# (pinned by tests/test_workbook.py::test_formula_columns_stay_put).

COLUMNS = SheetSpec(
    name="Columns",
    title="Columns  ·  one row per table column",
    description="The schema of every table and view: data type, nullability, partitioning, masks.",
    columns=[
        Column("Table", "table", 40),
        Column("Position", "position", 9, numeric=True, number_format=N),
        Column("Column", "name", 28),
        Column("Data type", "data_type", 26),
        Column("Nullable", yes_no("nullable"), 9),
        Column("Partition index", "partition_index", 10),
        Column("Masked", yes_no("masked"), 8),
        Column("Comment", "comment", 36),
    ],
    rows=lambda r: r.estate.columns,
)

VIEWS = SheetSpec(
    name="Views",
    title="View definitions",
    description=(
        "SQL of every view and materialized view (Databricks SQL dialect). Views read by a "
        "Fabric Warehouse need translation to T-SQL."
    ),
    columns=[
        Column("Full name", "full_name", 40),
        Column("Type", "view_type", 18),
        Column("Definition (chars)", "definition_chars", 11, numeric=True, number_format=N),
        Column("3-part names referenced", "references", 11, numeric=True, number_format=N),
        Column("Definition", "definition", 100, wrap=False),
    ],
    rows=lambda r: r.estate.views,
)

VOLUMES = SheetSpec(
    name="Volumes",
    title="Volumes  ·  governed file storage",
    description="Unity Catalog volumes; copy the files or shortcut the storage into a Lakehouse.",
    columns=[
        Column("Full name", "full_name", 36),
        Column("Catalog", "catalog", 18),
        Column("Schema", "schema_name", 18),
        Column("Name", "name", 22),
        Column("Volume type", "volume_type", 11),
        Column("Storage location", "storage_location", 48),
        Column("Owner", "owner", 22),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.volumes,
    readiness_column="Readiness",
)

EXTERNAL_LOCATIONS = SheetSpec(
    name="ExternalLocations",
    title="External locations",
    description="Cloud storage paths registered in Unity Catalog; each becomes a OneLake shortcut.",
    columns=[
        Column("Name", "name", 26),
        Column("URL", "url", 56),
        Column("Credential", "credential", 22),
        Column("Read only", yes_no("read_only"), 9),
        Column("Owner", "owner", 22),
        Column("Comment", "comment", 30),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.external_locations,
    readiness_column="Readiness",
)

STORAGE_CREDENTIALS = SheetSpec(
    name="StorageCredentials",
    title="Storage credentials",
    description="Identities Unity Catalog uses to reach storage. Secrets are never exported.",
    columns=[
        Column("Name", "name", 26),
        Column("Credential type", "credential_type", 28),
        Column("Owner", "owner", 22),
        Column("Read only", yes_no("read_only"), 9),
        Column("Comment", "comment", 30),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.storage_credentials,
    readiness_column="Readiness",
)

CONNECTIONS = SheetSpec(
    name="Connections",
    title="Connections  ·  Lakehouse Federation",
    description=(
        "Foreign connections (no options or credentials are read). Recreate them in Fabric."
    ),
    columns=[
        Column("Name", "name", 26),
        Column("Connection type", "connection_type", 18),
        Column("Owner", "owner", 22),
        Column("Read only", yes_no("read_only"), 9),
        Column("Created", "created_at", 16),
        Column("Comment", "comment", 30),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.connections,
    readiness_column="Readiness",
)

FUNCTIONS = SheetSpec(
    name="Functions",
    title="Functions  ·  Unity Catalog UDFs",
    description="SQL and Python UDFs registered in Unity Catalog.",
    columns=[
        Column("Full name", "full_name", 36),
        Column("Catalog", "catalog", 16),
        Column("Schema", "schema_name", 16),
        Column("Name", "name", 22),
        Column("Language", "language", 10),
        Column("Return type", "return_type", 18),
        Column("Parameters", "parameters", 30),
        Column("Table function", yes_no("table_function"), 9),
        Column("Body (chars)", "body_chars", 10, numeric=True, number_format=N),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.functions,
    readiness_column="Readiness",
)

GRANTS = SheetSpec(
    name="Grants",
    title="Grants  ·  Unity Catalog privileges",
    description=(
        "Privileges on catalogs and schemas. Fabric has no 1:1 GRANT model: map these to "
        "workspace roles, item permissions and OneLake security."
    ),
    columns=[
        Column("Securable type", "securable_type", 12),
        Column("Securable", "securable", 34),
        Column("Principal", "principal", 32),
        Column("Privileges", "privileges", 60),
    ],
    rows=lambda r: r.estate.grants,
)
