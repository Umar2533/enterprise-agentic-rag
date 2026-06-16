"""add user collection embedding metadata

Revision ID: 7f2e9c1a6b30
Revises: c4f8a1b2d3e4
Create Date: 2026-06-16 00:01:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "7f2e9c1a6b30"
down_revision: str | None = "c4f8a1b2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_collections",
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "user_collections",
        sa.Column("vector_size", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_collections", "vector_size")
    op.drop_column("user_collections", "embedding_model")
