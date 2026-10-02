"""initial schema: users, centres, tests, bookings, payments, webhook_events

Revision ID: 0001
Revises:
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('centres',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('location', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_centres')),
    sa.UniqueConstraint('name', 'location', name='uq_centres_name_location')
    )
    op.create_index(op.f('ix_centres_location'), 'centres', ['location'], unique=False)
    op.create_table('diagnostic_tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_diagnostic_tests'))
    )
    op.create_index(op.f('ix_diagnostic_tests_name'), 'diagnostic_tests', ['name'], unique=True)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('centre_id', sa.Integer(), nullable=False),
    sa.Column('appointment_datetime', sa.DateTime(timezone=True), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED', name='booking_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_bookings_amount_non_negative')),
    sa.ForeignKeyConstraint(['centre_id'], ['centres.id'], name=op.f('fk_bookings_centre_id_centres')),
    sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], name=op.f('fk_bookings_test_id_diagnostic_tests')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_bookings_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings'))
    )
    op.create_index(op.f('ix_bookings_status'), 'bookings', ['status'], unique=False)
    op.create_index(op.f('ix_bookings_user_id'), 'bookings', ['user_id'], unique=False)
    op.create_table('centre_tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('centre_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.CheckConstraint('price >= 0', name=op.f('ck_centre_tests_price_non_negative')),
    sa.ForeignKeyConstraint(['centre_id'], ['centres.id'], name=op.f('fk_centre_tests_centre_id_centres')),
    sa.ForeignKeyConstraint(['test_id'], ['diagnostic_tests.id'], name=op.f('fk_centre_tests_test_id_diagnostic_tests')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_centre_tests')),
    sa.UniqueConstraint('centre_id', 'test_id', name='uq_centre_tests_centre_id_test_id')
    )
    op.create_index(op.f('ix_centre_tests_centre_id'), 'centre_tests', ['centre_id'], unique=False)
    op.create_index(op.f('ix_centre_tests_test_id'), 'centre_tests', ['test_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('booking_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'SUCCESS', 'FAILED', name='payment_status'), nullable=False),
    sa.Column('provider_reference', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_payments_amount_non_negative')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name=op.f('fk_payments_booking_id_bookings')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_payments_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_payments_user_id_idempotency_key')
    )
    op.create_index(op.f('ix_payments_booking_id'), 'payments', ['booking_id'], unique=False)
    op.create_index(op.f('ix_payments_provider_reference'), 'payments', ['provider_reference'], unique=True)
    op.create_index(op.f('ix_payments_status'), 'payments', ['status'], unique=False)
    op.create_table('webhook_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('payment_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('event_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('outcome', sa.Enum('APPLIED', 'IGNORED', name='webhook_outcome'), nullable=True),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('SUCCESS', 'FAILED')", name=op.f('ck_webhook_events_status_valid')),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name=op.f('fk_webhook_events_payment_id_payments')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_events'))
    )
    op.create_index(op.f('ix_webhook_events_event_id'), 'webhook_events', ['event_id'], unique=True)
    op.create_index(op.f('ix_webhook_events_payment_id'), 'webhook_events', ['payment_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_events_payment_id'), table_name='webhook_events')
    op.drop_index(op.f('ix_webhook_events_event_id'), table_name='webhook_events')
    op.drop_table('webhook_events')
    op.drop_index(op.f('ix_payments_status'), table_name='payments')
    op.drop_index(op.f('ix_payments_provider_reference'), table_name='payments')
    op.drop_index(op.f('ix_payments_booking_id'), table_name='payments')
    op.drop_table('payments')
    op.drop_index(op.f('ix_centre_tests_test_id'), table_name='centre_tests')
    op.drop_index(op.f('ix_centre_tests_centre_id'), table_name='centre_tests')
    op.drop_table('centre_tests')
    op.drop_index(op.f('ix_bookings_user_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_status'), table_name='bookings')
    op.drop_table('bookings')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_diagnostic_tests_name'), table_name='diagnostic_tests')
    op.drop_table('diagnostic_tests')
    op.drop_index(op.f('ix_centres_location'), table_name='centres')
    op.drop_table('centres')
    op.execute('DROP TYPE webhook_outcome')
    op.execute('DROP TYPE payment_status')
    op.execute('DROP TYPE booking_status')
