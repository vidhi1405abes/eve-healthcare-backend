"""webhook failures

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02 15:46:40.643816

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('webhook_failures',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('provider_reference', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('event_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_failures'))
    )
    op.create_index(op.f('ix_webhook_failures_event_id'), 'webhook_failures', ['event_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_failures_event_id'), table_name='webhook_failures')
    op.drop_table('webhook_failures')
