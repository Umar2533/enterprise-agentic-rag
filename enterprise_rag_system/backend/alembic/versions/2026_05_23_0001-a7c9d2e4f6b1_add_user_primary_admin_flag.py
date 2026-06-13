"""add user primary admin flag

Revision ID: a7c9d2e4f6b1
Revises: d5067195524f
Create Date: 2026-05-23 00:01:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c9d2e4f6b1'
down_revision: str | None = 'd5067195524f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'is_primary_admin',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column('users', 'is_primary_admin', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'is_primary_admin')
