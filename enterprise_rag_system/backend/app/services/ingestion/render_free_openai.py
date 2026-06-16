from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.constants import OPENAI_EMBEDDING_MODEL
from app.services.llm.embeddings_service import embedding_vector_size_for_provider


class RenderFreeIngestionError(RuntimeError):
    pass


class RenderFreeCollectionExistsError(RenderFreeIngestionError):
    pass


@dataclass
class RenderFreeChunk:
    page_content: str
    metadata: dict[str, Any]


@dataclass
class RenderFreeIngestionResult:
    session_id: str
    collection_name: str
    filename: str
    chunks: list[RenderFreeChunk]
    skipped: bool = False


def ingest_render_free_openai(
    *,
    file_path: Path,
    filename: str,
    collection_name: str,
    chunk_size: int,
    chunk_overlap: int,
    openai_api_key: str,
    use_existing_collection: bool,
) -> RenderFreeIngestionResult:
    settings = get_settings()
    qdrant_url = (settings.qdrant_url or "").strip()
    qdrant_api_key = (settings.qdrant_api_key or "").strip()
    _validate_qdrant_url(qdrant_url)

    from openai import OpenAI
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )

    qdrant = QdrantClient(
        url=qdrant_url,
        api_key=qdrant_api_key or None,
        timeout=30,
        check_compatibility=False,
        trust_env=False,
    )
    collection_exists = qdrant.collection_exists(collection_name)
    if collection_exists and not use_existing_collection:
        raise RenderFreeCollectionExistsError(
            "Collection already exists. Please choose another name."
        )

    document_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
    if collection_exists:
        points, _ = qdrant.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="metadata.document_hash",
                        match=MatchValue(value=document_hash),
                    )
                ]
            ),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        if points:
            return RenderFreeIngestionResult(
                session_id=uuid.uuid4().hex,
                collection_name=collection_name,
                filename=filename,
                chunks=[],
                skipped=True,
            )

    chunks = _load_and_chunk(
        file_path=file_path,
        collection_name=collection_name,
        document_hash=document_hash,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    openai = OpenAI(api_key=openai_api_key, timeout=60, max_retries=1)
    embeddings: list[list[float]] = []
    for start in range(0, len(chunks), 64):
        response = openai.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=[chunk.page_content for chunk in chunks[start : start + 64]],
        )
        embeddings.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
    if len(embeddings) != len(chunks) or not embeddings:
        raise RenderFreeIngestionError("OpenAI returned an invalid embeddings response.")

    vector_name = _existing_vector_name(qdrant, collection_name) if collection_exists else None
    if not collection_exists:
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=len(embeddings[0]), distance=Distance.COSINE),
        )

    points = []
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection_name}:{document_hash}:{index}"))
        vector: list[float] | dict[str, list[float]] = embedding
        if vector_name:
            vector = {vector_name: embedding}
        points.append(
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "page_content": chunk.page_content,
                    "metadata": chunk.metadata,
                },
            )
        )
    qdrant.upsert(collection_name=collection_name, points=points, wait=True)
    return RenderFreeIngestionResult(
        session_id=uuid.uuid4().hex,
        collection_name=collection_name,
        filename=filename,
        chunks=chunks,
    )


def _load_and_chunk(
    *,
    file_path: Path,
    collection_name: str,
    document_hash: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[RenderFreeChunk]:
    pages = _load_pages(file_path)
    chunks: list[RenderFreeChunk] = []
    step = chunk_size - chunk_overlap
    for page_number, text in pages:
        normalized = text.strip()
        for start in range(0, len(normalized), step):
            content = normalized[start : start + chunk_size].strip()
            if not content:
                continue
            index = len(chunks)
            chunks.append(
                RenderFreeChunk(
                    page_content=content,
                    metadata={
                        "file_name": file_path.name,
                        "chunk_id": f"{file_path.stem}-{index:05d}",
                        "page_number": page_number,
                        "document_hash": document_hash,
                        "collection_name": collection_name,
                        "embedding_provider": "openai",
                        "embedding_model": OPENAI_EMBEDDING_MODEL,
                        "vector_size": embedding_vector_size_for_provider("openai"),
                        "chunk_index": index,
                    },
                )
            )
            if start + chunk_size >= len(normalized):
                break
    if not chunks:
        raise RenderFreeIngestionError("Document is empty or could not be parsed.")
    return chunks


def _load_pages(file_path: Path) -> list[tuple[int, str]]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        return [(index + 1, page.extract_text() or "") for index, page in enumerate(reader.pages)]
    if suffix == ".docx":
        import docx2txt

        return [(1, docx2txt.process(str(file_path)) or "")]
    if suffix == ".csv":
        rows = csv.reader(io.StringIO(file_path.read_text(encoding="utf-8-sig")))
        return [(1, "\n".join(", ".join(cell.strip() for cell in row) for row in rows))]
    return [(1, file_path.read_text(encoding="utf-8"))]


def _existing_vector_name(client, collection_name: str) -> str | None:
    info = client.get_collection(collection_name)
    vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
    if isinstance(vectors, dict) or hasattr(vectors, "keys"):
        available = [name for name in vectors.keys() if name]
        if "dense" in available:
            return "dense"
        if available:
            raise RenderFreeIngestionError(
                f"Collection '{collection_name}' does not use the supported 'dense' vector name."
            )
    return None


def _validate_qdrant_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RenderFreeIngestionError("QDRANT_URL is not configured on the backend.")
