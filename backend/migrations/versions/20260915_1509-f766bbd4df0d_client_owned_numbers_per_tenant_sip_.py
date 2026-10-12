"""Client-owned phone numbers: per-tenant SIP trunks + number provenance/verification.

Revision ID: f766bbd4df0d
Revises: 86f3515243eb

Clarivo used to buy DIDs on its own Vobiz account and hand them to customers. That
put our name on the CAF for lines other businesses answer, which is a licensing
position we are not able to hold. The supported model is now the reverse: the
customer keeps the number with their own operator and forwards it into a SIP trunk
we create for them alone. This migration adds the two things the database needed
before that model could exist.

**`phone_numbers.source`** records who the subscriber of record is. Until now that
fact survived only inside an audit-log detail blob, so the database could not answer
"which numbers are we the subscriber of?" — the first question anyone reviewing the
licensing position asks.

Backfilled to `platform_provisioned`, then refined down to `bring_your_own` for any
row the audit trail proves was customer-supplied (`number.connected` with
`detail.source = 'bring_your_own'`). The default direction is deliberate: for a
compliance question, over-stating our exposure is the safe error, because it means
we re-examine a number that turns out to be fine rather than miss one that is not.

**`phone_numbers.verification_status` / `verified_at`** carry proof that a number
really belongs to the tenant claiming it. A number is claimable exactly once
platform-wide, so without proof the first account to type a competitor's number
would capture that competitor's calls.

Existing rows are backfilled as **verified**, with `verified_at` set to the row's own
`created_at` rather than now(). This is the one part of this migration that is not
merely additive, and getting it wrong breaks production: call routing requires
`verification_status = 'verified'`, so leaving live numbers at the column default of
'pending' would silence every inbound call for every existing tenant the moment this
deploys. Using `created_at` avoids inventing a verification event dated to the
deploy; it is not a real proof timestamp for these rows and is not claimed to be, it
is the honest statement "this number predates verification and was grandfathered".

`server_default` is kept on both new NOT NULL columns instead of being dropped after
the backfill. The ORM supplies its own value on every insert, so the default is only
a safety net — but it is the difference between a hand-written INSERT working and
failing, and it costs nothing.

**`sip_trunks`** is the per-tenant trunk: LiveKit's trunk/dispatch-rule ids plus the
digest credentials the customer hands to their operator. One row per clinic, enforced
by a UNIQUE index rather than a plain one — a second row would split a tenant's
numbers across two trunks with two different passwords, and the failure would show up
as intermittently unanswered calls.

Nothing is inserted here. Trunks are created lazily by
`backend/services/livekit_sip.py` the first time a tenant needs one, because the
credentials must be generated per tenant and a trunk for a clinic that never connects
a number is just an unused LiveKit resource.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f766bbd4df0d'
down_revision: Union[str, None] = '86f3515243eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----- phone number provenance + verification ---------------------------
    op.add_column(
        "phone_numbers",
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
            server_default="bring_your_own",
        ),
    )
    op.add_column(
        "phone_numbers",
        sa.Column(
            "verification_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("phone_numbers", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.add_column("phone_numbers", sa.Column("provider", sa.String(length=60), nullable=True))

    # Grandfather every pre-existing number. See the module docstring: routing now
    # requires 'verified', so this UPDATE is what keeps live tenants' calls working
    # across the deploy.
    op.execute(
        """
        UPDATE phone_numbers
           SET source = 'platform_provisioned',
               verification_status = 'verified',
               verified_at = created_at
        """
    )

    # Refine using the only record that distinguished the two sources before this
    # column existed. Guarded on the table being present so the migration cannot
    # fail on a database where audit_logs is missing for any reason.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.audit_logs') IS NOT NULL THEN
            UPDATE phone_numbers pn
               SET source = 'bring_your_own'
             WHERE EXISTS (
                     SELECT 1
                       FROM audit_logs al
                      WHERE al.action = 'number.connected'
                        AND al.target_type = 'phone_number'
                        AND al.target_id = pn.id::text
                        AND al.detail->>'source' = 'bring_your_own'
                   );
          END IF;
        END $$
        """
    )

    # ----- per-tenant SIP trunks -------------------------------------------
    op.create_table(
        "sip_trunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clinic_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("livekit_trunk_id", sa.String(length=64), nullable=True),
        sa.Column("livekit_dispatch_rule_id", sa.String(length=64), nullable=True),
        sa.Column("auth_username", sa.String(length=64), nullable=False),
        sa.Column("auth_password", sa.String(length=128), nullable=False),
        sa.Column("sip_host", sa.String(length=255), nullable=True),
        sa.Column("allowed_addresses", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("livekit_trunk_id"),
    )
    # UNIQUE, not a plain index: one trunk per clinic is the invariant the design
    # rests on, so the database enforces it rather than the application remembering to.
    op.create_index("ix_sip_trunks_clinic_id", "sip_trunks", ["clinic_id"], unique=True)


def downgrade() -> None:
    # Dropping sip_trunks discards the digest credentials we issued to customers.
    # The LiveKit trunks themselves are NOT deleted (they live in LiveKit, not here),
    # so calls keep arriving but nothing can map them back to a tenant, and re-running
    # the upgrade issues NEW credentials that every customer's operator config would
    # then have to be updated to match. Reversible in schema terms, disruptive in
    # practice — export this table before downgrading a live database.
    op.drop_index("ix_sip_trunks_clinic_id", table_name="sip_trunks")
    op.drop_table("sip_trunks")

    # Losing `source` loses the only structured record of which numbers we are the
    # subscriber of; the audit trail still holds it for bring-your-own rows.
    # Losing verification_status returns the schema to a state where an unverified
    # number is indistinguishable from a proven one, which is what allowed a number
    # to be claimed without proof in the first place.
    op.drop_column("phone_numbers", "provider")
    op.drop_column("phone_numbers", "verified_at")
    op.drop_column("phone_numbers", "verification_status")
    op.drop_column("phone_numbers", "source")
