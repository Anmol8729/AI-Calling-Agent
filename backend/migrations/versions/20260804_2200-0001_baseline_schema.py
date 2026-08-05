"""Baseline: the schema as it stood when Alembic was introduced.

Revision ID: 0001_baseline
Revises: None

Background
----------
Before this, the schema was maintained by `Base.metadata.create_all` plus ~30
hand-written idempotent `ALTER TABLE ... IF NOT EXISTS` statements executed on every
boot. That is safe to re-run, but it has no version history and **no way to roll a
change back** — a bad column change on a live customer database could only be undone
by hand.

This revision is a SQUASHED baseline rather than a replay of that history. It builds
the current schema from the model metadata, so:

  * a **fresh** database gets the whole schema from `alembic upgrade head`;
  * an **existing** database is marked as already at this revision with
    `alembic stamp 0001_baseline`, which writes the version row WITHOUT executing
    anything. Verified safe here: autogenerate against the live database produced an
    empty diff, so the models and that database already agree exactly.

From here on, every schema change gets its own revision with a real `downgrade()`.

`checkfirst=True` makes the upgrade a no-op against a database that already has the
objects, so running it instead of stamping cannot damage anything either.
"""

from typing import Sequence, Union

from alembic import op

from backend.models import Base

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Metadata-driven so the baseline cannot drift from the models. Idempotent.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Only meaningful for a throwaway/fresh database — this drops every table.
    # Deliberately NOT wired to anything automatic. Running it against a database
    # with customer data destroys that data.
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
