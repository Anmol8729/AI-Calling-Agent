"""Revoke anon/authenticated table grants so the public anon key cannot reach data.

Revision ID: 3a7f91c4e2b8
Revises: 2c2168e1d70e

Why
---
Enabling Google sign-in puts `SUPABASE_URL` and the **anon key** into the frontend
bundle, where they are public by design. That makes the project's PostgREST API
(`/rest/v1/<table>`) reachable from any browser. The application's own connection is
unaffected — it uses the `postgres` role, which bypasses RLS — but PostgREST requests
run as `anon` or `authenticated`, where RLS does apply.

Measured before this change: `anon` and `authenticated` held
`SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER` on **every** table in
`public` (Supabase's default grants). The only thing preventing access was that RLS
was enabled with zero policies, which denies by default.

That is a single control protecting everything. Disabling RLS on one table — two
clicks in the Supabase dashboard — or adding one over-broad policy would expose every
tenant's patients, call transcripts, payments and users to anyone who reads the
JavaScript bundle. Revoking the grants adds a second, independent control: access
would then need BOTH a grant and a policy.

Scope and safety
----------------
* The backend and the voice agent connect as `postgres` and are unaffected.
* The frontend only calls Supabase's `/auth/v1/*` endpoints (sign-in), never
  PostgREST, so nothing in the product loses access.
* Supabase Studio uses its own privileged role and keeps working.
* Fully reversible — `downgrade()` restores the grants exactly.

Also alters DEFAULT PRIVILEGES so tables created later do not silently receive these
grants again, which is how this would otherwise come back.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "3a7f91c4e2b8"
down_revision: Union[str, None] = "2c2168e1d70e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = "anon, authenticated"


def upgrade() -> None:
    # Existing tables and sequences.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLES}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLES}")
    op.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {ROLES}")
    # Without this, the next table created gets the grants back.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {ROLES}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {ROLES}"
    )
    # USAGE on the schema is left in place: it grants nothing on its own once the
    # table privileges are gone, and removing it can upset Supabase tooling that
    # merely introspects the schema.


def downgrade() -> None:
    # Restores Supabase's defaults. Note that doing so returns the database to a
    # state where RLS is the *only* thing protecting business data from anyone
    # holding the public anon key.
    op.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {ROLES}")
    op.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {ROLES}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {ROLES}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {ROLES}"
    )
