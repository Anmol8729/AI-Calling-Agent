"""Add partial unique constraints to appointments table.

Revision ID: e8b1a3c5d792
Revises: dd90a2a5d172
Create Date: 2026-11-22 22:15:00

Enforces atomic database-level uniqueness:
1. `uq_appointments_clinic_scheduled_slot`: Prevents double bookings for the same
   clinic at the same start time while `status = 'scheduled'`.
2. `uq_appointments_clinic_token_day`: Prevents duplicate token numbers on the
   same date for the same clinic.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8b1a3c5d792'
down_revision: Union[str, None] = 'dd90a2a5d172'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_appointments_clinic_scheduled_slot',
        'appointments',
        ['clinic_id', 'appointment_at'],
        unique=True,
        postgresql_where=sa.text("status = 'scheduled' AND appointment_at IS NOT NULL"),
    )
    op.create_index(
        'uq_appointments_clinic_token_day',
        'appointments',
        ['clinic_id', 'token_date', 'token_number'],
        unique=True,
        postgresql_where=sa.text("token_date IS NOT NULL AND token_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_appointments_clinic_token_day',
        table_name='appointments',
        postgresql_where=sa.text("token_date IS NOT NULL AND token_number IS NOT NULL"),
    )
    op.drop_index(
        'uq_appointments_clinic_scheduled_slot',
        table_name='appointments',
        postgresql_where=sa.text("status = 'scheduled' AND appointment_at IS NOT NULL"),
    )
