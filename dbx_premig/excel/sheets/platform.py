"""Security and platform: SecretScopes, Mounts, Identities."""

from __future__ import annotations

from dbx_premig.excel.sheets.common import assessed_columns, yes_no
from dbx_premig.excel.types import Column, SheetSpec

__all__ = ["IDENTITIES", "MOUNTS", "SECRET_SCOPES"]

N = "#,##0"

SECRET_SCOPES = SheetSpec(
    name="SecretScopes",
    title="Secret scopes  ·  names only, never values",
    description=(
        "Secret scopes and the NAMES of their keys. Values cannot be exported: re-enter them "
        "in Azure Key Vault."
    ),
    columns=[
        Column("Scope", "scope", 26),
        Column("Backend", "backend", 16),
        Column("Secrets", "secrets", 9, numeric=True, number_format=N),
        Column("Key names", "keys", 60),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.secret_scopes,
    readiness_column="Readiness",
)

MOUNTS = SheetSpec(
    name="Mounts",
    title="DBFS mounts",
    description=(
        "Legacy /mnt mounts; replace them with OneLake shortcuts and fix /mnt paths in code."
    ),
    columns=[
        Column("Mount point", "mount_point", 40),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.mounts,
    readiness_column="Readiness",
)

IDENTITIES = SheetSpec(
    name="Identities",
    title="Identities  ·  users, groups and service principals",
    description="Workspace principals, to map onto Entra ID users / groups and Fabric roles.",
    columns=[
        Column("Type", "identity_type", 16),
        Column("Name", "name", 36),
        Column("Id / application id", "identifier", 38),
        Column("Active", yes_no("active"), 8),
        Column("Groups", "groups", 8, numeric=True, number_format=N),
        Column("Members", "members", 9, numeric=True, number_format=N),
    ],
    rows=lambda r: r.estate.identities,
)
