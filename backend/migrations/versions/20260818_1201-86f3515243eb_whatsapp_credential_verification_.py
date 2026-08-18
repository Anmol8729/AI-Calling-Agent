"""tenants.whatsapp_verified_at: when the WhatsApp credentials last passed a live check.

Revision ID: 86f3515243eb
Revises: 9089ca857f27

The dashboard used to infer a WhatsApp connection from "an access token is stored"
(`whatsapp_access_token_set`). That is a different fact: a stored token can be
expired, revoked, or pointed at a phone number ID the app cannot see, and the
sender fails silently in all three cases because `send_template` only logs a
warning and returns False. So the tenant saw a connected-looking setting while no
message was ever delivered.

This column records the result of an actual probe against the Cloud API, which is
what the Connected / Not Connected badge now reads. NULL means never verified.

Nullable with no server default on purpose: existing tenants have genuinely never
been verified, and NULL says exactly that. Backfilling a timestamp would invent a
check that never happened.

`POST /api/clinics/whatsapp/verify` sets it; both that route and
`PUT /api/clinics/settings` clear it whenever the phone number ID or access token
changes, so the badge can never vouch for credentials nobody checked.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "86f3515243eb"
down_revision: Union[str, None] = "9089ca857f27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("whatsapp_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Drops only the record of when credentials were last checked. The credentials
    # themselves live in the other whatsapp_* columns and are untouched, so the
    # feature keeps working — the badge just falls back to "Not Connected".
    op.drop_column("tenants", "whatsapp_verified_at")
