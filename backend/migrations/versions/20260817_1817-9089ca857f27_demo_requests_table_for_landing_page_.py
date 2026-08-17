"""demo_requests: callback leads captured by the landing page.

Revision ID: 9089ca857f27
Revises: e490979d4cb1

Brings the database in line with the landing-page work merged from product1/main,
which added `demo_requests` to `backend/db/schema.sql` and to the model but shipped no
migration. That file is never executed by the application, so the table did not exist
anywhere it mattered. Confirmed rather than assumed: `alembic check` against the live
database reported `Detected added table 'demo_requests'` plus both of its indexes, so
`POST /api/public/demo-request` would have failed on the first visitor who submitted
the form with `relation "demo_requests" does not exist`.

This is the same class of gap that `e490979d4cb1` closed for `patients.source` — worth
watching for on every merge that touches `schema.sql`.

Note this one is a NEW table rather than a column change, so a database left on
`DB_AUTO_SCHEMA=true` would have created it at boot via `create_all`. Production runs
with Alembic owning the schema, which is exactly why the migration is required.

No `server_default` on any column, deliberately. `id`, `status` and `created_at` all
default on the Python side in the model (`uuid4`, `'pending'`, `utcnow`), and every
insert goes through the ORM. `env.py` sets `compare_server_default=True`, so adding
defaults here that the model does not declare would make `alembic check` report drift
forever. `schema.sql` does declare them; that file is documentation at this point and
the difference is harmless.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9089ca857f27"
down_revision: Union[str, None] = "e490979d4cb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_IX = "ix_demo_requests_status"
_CREATED_AT_IX = "ix_demo_requests_created_at"


def upgrade() -> None:
    op.create_table(
        "demo_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        # pending | contacted | converted | dismissed
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Both columns the admin leads view sorts and filters on.
    op.create_index(_CREATED_AT_IX, "demo_requests", ["created_at"], unique=False)
    op.create_index(_STATUS_IX, "demo_requests", ["status"], unique=False)


def downgrade() -> None:
    # Drops marketing leads only. No tenant, user or patient data is touched — the
    # table is standalone and holds no foreign keys in either direction.
    op.drop_index(_STATUS_IX, table_name="demo_requests")
    op.drop_index(_CREATED_AT_IX, table_name="demo_requests")
    op.drop_table("demo_requests")
