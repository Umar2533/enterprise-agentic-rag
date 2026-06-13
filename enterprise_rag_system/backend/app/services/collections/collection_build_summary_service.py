import csv
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.documents import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    DEFAULT_EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    OPENAI_EMBEDDING_MODEL,
)
from app.models.collection_build_summary import CollectionBuildSummary


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def embedding_model_for_provider(embedding_provider: str) -> str:
    return OPENAI_EMBEDDING_MODEL if embedding_provider == "openai" else EMBEDDING_MODEL


def file_type_from_path(file_path: str | Path) -> str:
    return Path(file_path).suffix.lower().lstrip(".") or "unknown"


def document_units(
    file_path: str | Path,
    file_type: str,
    chunks: Iterable[Document],
) -> tuple[str, int | None]:
    path = Path(file_path)
    try:
        if file_type == "pdf":
            pages = {
                str(chunk.metadata.get("page_number"))
                for chunk in chunks
                if chunk.metadata.get("page_number") not in (None, "")
            }
            return "Pages", len(pages) or None
        if file_type == "csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return "Rows", sum(1 for _ in csv.reader(handle))
        if file_type in {"txt", "md"}:
            return "Lines", len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeError, csv.Error):
        pass
    return "N/A", None


def get_collection_build_summary(
    db: Session,
    collection_name: str,
    user_id: int | None,
) -> CollectionBuildSummary | None:
    stmt = select(CollectionBuildSummary).where(
        CollectionBuildSummary.collection_name == collection_name,
    )
    if user_id is None:
        stmt = stmt.where(CollectionBuildSummary.user_id.is_(None))
    else:
        stmt = stmt.where(CollectionBuildSummary.user_id == user_id)
    return db.execute(stmt).scalar_one_or_none()


def get_collection_build_summary_for_collection(
    db: Session,
    collection_name: str,
) -> CollectionBuildSummary | None:
    stmt = (
        select(CollectionBuildSummary)
        .where(CollectionBuildSummary.collection_name == collection_name)
        .order_by(CollectionBuildSummary.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def upsert_collection_build_summary(
    db: Session,
    *,
    user_id: int | None,
    collection_name: str,
    document_name: str,
    file_type: str,
    document_units_label: str,
    document_units_value: int | None,
    chunks_created: int,
    vectors_stored: int,
    chunk_size: int,
    chunk_overlap: int,
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER,
) -> CollectionBuildSummary:
    summary = get_collection_build_summary(db, collection_name, user_id)
    values = {
        "document_name": document_name,
        "file_type": file_type,
        "document_units_label": document_units_label,
        "document_units_value": document_units_value,
        "chunks_created": chunks_created,
        "vectors_stored": vectors_stored,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "embedding_model": embedding_model_for_provider(embedding_provider),
        "last_built_at": utc_now(),
    }
    if summary is None:
        summary = CollectionBuildSummary(
            user_id=user_id,
            collection_name=collection_name,
            **values,
        )
    else:
        for field, value in values.items():
            setattr(summary, field, value)
        summary.updated_at = utc_now()

    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary
