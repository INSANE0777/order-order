"""add user and user_session tables for authentication

Revision ID: e81a3d92f74b
Revises: c56da0a58c0b
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e81a3d92f74b'
down_revision: str | None = 'c56da0a58c0b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'user',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_email'), ['email'], unique=True)

    op.create_table(
        'user_session',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('session_token', sa.String(length=64), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_session', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_session_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_session_session_token'), ['session_token'], unique=True)
        batch_op.create_index(batch_op.f('ix_user_session_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('user_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_session_user_id'))
        batch_op.drop_index(batch_op.f('ix_user_session_session_token'))
        batch_op.drop_index(batch_op.f('ix_user_session_expires_at'))
    op.drop_table('user_session')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_email'))
    op.drop_table('user')
