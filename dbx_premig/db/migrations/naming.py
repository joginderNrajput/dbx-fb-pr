"""Schema and table-name prefix of the migration in progress (set by ``env.py``).

Revisions call ``names()`` instead of hard-coding the schema, so the same migrations run
against ``DBXF_DB_SCHEMA`` / ``DBXF_DB_TABLE_PREFIX`` of any deployment.
"""

from __future__ import annotations

from alembic import context

__all__ = ["names"]


def names() -> tuple[str, str]:
    attrs = context.config.attributes
    return str(attrs["schema"]), str(attrs.get("prefix", ""))
