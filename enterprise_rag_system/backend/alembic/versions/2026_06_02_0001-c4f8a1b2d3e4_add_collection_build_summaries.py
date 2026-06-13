"""add collection build summaries

Revision ID: c4f8a1b2d3e4
Revises: a7c9d2e4f6b1
Create Date: 2026-06-02 00:01:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c4f8a1b2d3e4"
down_revision: str | None = "a7c9d2e4f6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collection_build_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("collection_name", sa.String(length=255), nullable=False),
        sa.Column("document_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("document_units_label", sa.String(length=32), nullable=False),
        sa.Column("document_units_value", sa.Integer(), nullable=True),
        sa.Column("chunks_created", sa.Integer(), nullable=False),
        sa.Column("vectors_stored", sa.Integer(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("last_built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_collection_build_summaries_collection_name"),
        "collection_build_summaries",
        ["collection_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_build_summaries_id"),
        "collection_build_summaries",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_build_summaries_user_id"),
        "collection_build_summaries",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_collection_build_summaries_user_collection",
        "collection_build_summaries",
        ["user_id", "collection_name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_collection_build_summaries_collection_without_user",
        "collection_build_summaries",
        ["collection_name"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_collection_build_summaries_collection_without_user",
        table_name="collection_build_summaries",
    )
    op.drop_index(
        "uq_collection_build_summaries_user_collection",
        table_name="collection_build_summaries",
    )
    op.drop_index(
        op.f("ix_collection_build_summaries_user_id"),
        table_name="collection_build_summaries",
    )
    op.drop_index(
        op.f("ix_collection_build_summaries_id"),
        table_name="collection_build_summaries",
    )
    op.drop_index(
        op.f("ix_collection_build_summaries_collection_name"),
        table_name="collection_build_summaries",
    )
    op.drop_table("collection_build_summaries")
