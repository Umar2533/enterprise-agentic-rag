from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CollectionBuildSummary(Base):
    __tablename__ = "collection_build_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    collection_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_units_label: Mapped[str] = mapped_column(String(32), nullable=False)
    document_units_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks_created: Mapped[int] = mapped_column(Integer, nullable=False)
    vectors_stored: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    last_built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


Index(
    "uq_collection_build_summaries_user_collection",
    CollectionBuildSummary.user_id,
    CollectionBuildSummary.collection_name,
    unique=True,
    postgresql_where=CollectionBuildSummary.user_id.is_not(None),
)
Index(
    "uq_collection_build_summaries_collection_without_user",
    CollectionBuildSummary.collection_name,
    unique=True,
    postgresql_where=CollectionBuildSummary.user_id.is_(None),
)
