"""Tenant lifecycle status (approval gate).

Revision ID: dd90a2a5d172
Revises: f766bbd4df0d
Create Date: 2026-10-13 02:00:00

Adds `tenants.status` with values:
  - 'pending': New business signup awaiting platform admin approval.
  - 'active': Approved tenant actively taking and placing calls.
  - 'suspended': Business account temporarily disabled by platform admin.

Existing tenants are grandfathered as 'active' via server_default='active'.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dd90a2a5d172'
down_revision: Union[str, None] = 'f766bbd4df0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tenants',
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active')
    )
    op.create_index('ix_tenants_status', 'tenants', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_tenants_status', table_name='tenants')
    op.drop_column('tenants', 'status')
