"""Optional Postgres sink for discovery and assessment results (write-only).

Lazily imported: SQLAlchemy and psycopg live in the ``postgres`` extra and are imported only
inside these modules. Off unless ``DBXF_DATABASE_URL`` is set. No number in the workbooks
depends on the database, and nothing is read back from it.

Tables (schema ``DBXF_DB_SCHEMA``, default ``databricks_to_fabric_premigration``):

* ``totals``      one row per scan: scan metadata + the count of every Databricks item type
* ``inventory``   one row per assessable object (discovery)
* ``finding``     one row per Databricks feature found on an object (discovery)
* ``estimation``  one row per object: complexity, automation level, hours (assessment)
* ``computation`` one row per scan: portfolio roll-up of the estimation (assessment)

Every row carries ``organization_id`` and ``job_id``. Persisting again for the same pair
replaces the previous rows in one transaction (never appends).
"""

from __future__ import annotations

__all__: list[str] = []
