"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from dbx_premig.db.migrations.naming import names

__all__: list[str] = []

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    schema, p = names()
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    schema, p = names()
    ${downgrades if downgrades else "pass"}
