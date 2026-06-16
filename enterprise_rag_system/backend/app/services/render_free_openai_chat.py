from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.constants import CHAT_MODEL, DEFAULT_TOP_K, OPENAI_EMBEDDING_MODEL


OPENAI_QUOTA_MESSAGE = (
    "Your OpenAI API key has no available quota. Please add billing/credits in "
    "OpenAI Platform or use another key."
)
DOCUMENT_NO_MENTION_MESSAGE = "The document does not mention this."


class RenderFreeChatError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    metadata: dict[str, Any]
    score: float


def chat_render_free_openai(
    *,
    collection_name: str,
    question: str,
    answer_length: str,
    openai_api_key: str,
) -> dict[str, Any]:
    settings = get_settings()
    qdrant_url = (settings.qdrant_url or "").strip()
    qdrant_api_key = (settings.qdrant_api_key or "").strip()
    _validate_qdrant_url(qdrant_url)

    try:
        from openai import OpenAI
        from qdrant_client import QdrantClient

        openai = OpenAI(api_key=openai_api_key, timeout=60, max_retries=1)
        embedding_response = openai.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=[question],
        )
        if not embedding_response.data:
            raise RenderFreeChatError("OpenAI returned an invalid embeddings response.")

        qdrant = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key or None,
            timeout=30,
            check_compatibility=False,
            trust_env=False,
        )
        vector_name = _existing_vector_name(qdrant, collection_name)
        points = _search_points(
            qdrant,
            collection_name,
            embedding_response.data[0].embedding,
            vector_name,
        )
        chunks = [_chunk_from_point(point) for point in points]
        chunks = [chunk for chunk in chunks if chunk is not None]
        context = _context_text(chunks)
        if context:
            completion = openai.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Answer using only the retrieved document context. Do not add external facts, "
                            "opinions, predictions, recommendations, or general knowledge. If the document "
                            f"context does not directly answer the question, say exactly: {DOCUMENT_NO_MENTION_MESSAGE} "
                            "Do not repeat the same sentence."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Answer length target: {answer_length}\n\n"
                            f"Retrieved context:\n{context}\n\n"
                            f"Question:\n{question}"
                        ),
                    },
                ],
            )
            answer = completion.choices[0].message.content if completion.choices else ""
        else:
            answer = DOCUMENT_NO_MENTION_MESSAGE
        if not (answer or "").strip():
            raise RenderFreeChatError("OpenAI returned an empty chat response.")
    except RenderFreeChatError:
        raise
    except Exception as exc:
        _raise_clean_error(exc)

    sources = [_source_from_chunk(chunk) for chunk in chunks]
    confidence = _confidence_level(chunks)
    trace = [
        {"message": "Retrieved matching chunks from the selected collection.", "kind": "info"},
        {"message": "Generated answer with OpenAI BYOK.", "kind": "success"},
    ]
    return {
        "answer": _dedupe_repeated_sentences(answer.strip()),
        "search_type": "vectorstore",
        "evaluation": "skipped",
        "iteration_count": 1,
        "retrieved_docs_count": len(chunks),
        "web_results_count": 0,
        "confidence_level": confidence,
        "retrieval_mode": "dense only",
        "retrieval_warning": "BM25 and local RAG runtime are disabled in Render Free MVP mode.",
        "llm_provider": "openai",
        "llm_model": CHAT_MODEL,
        "runtime_openai_active": True,
        "llm_fallback_warning": "",
        "llm_fallback_status": "not_used",
        "error_reason": "",
        "web_search_used": False,
        "web_search_available": False,
        "web_search_requires_approval": False,
        "trace_steps": trace,
        "trace": trace,
        "sources": sources,
    }


def render_free_chat_events(result: dict[str, Any]) -> Iterator[str]:
    for step in result.get("trace_steps", []):
        yield _sse("trace", step)
    yield _sse(
        "sources",
        {
            "sources": result.get("sources", []),
            "retrieved_docs_count": result.get("retrieved_docs_count", 0),
            "web_results_count": 0,
            "confidence_level": result.get("confidence_level", "unknown"),
            "retrieval_mode": result.get("retrieval_mode", "dense only"),
            "retrieval_warning": result.get("retrieval_warning", ""),
            "search_type": result.get("search_type", "vectorstore"),
            "web_search_used": False,
            "web_search_available": False,
            "web_search_requires_approval": False,
            "trace_steps": result.get("trace_steps", []),
        },
    )
    yield _sse("token", {"token": result.get("answer", "")})
    yield _sse("done", result)


def _search_points(client, collection_name: str, embedding: list[float], vector_name: str | None):
    if hasattr(client, "query_points"):
        kwargs: dict[str, Any] = {
            "collection_name": collection_name,
            "query": embedding,
            "limit": DEFAULT_TOP_K,
            "with_payload": True,
        }
        if vector_name:
            kwargs["using"] = vector_name
        return client.query_points(**kwargs).points

    query_vector: Any = embedding
    if vector_name:
        from qdrant_client.models import NamedVector

        query_vector = NamedVector(name=vector_name, vector=embedding)
    return client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=DEFAULT_TOP_K,
        with_payload=True,
    )


def _existing_vector_name(client, collection_name: str) -> str | None:
    info = client.get_collection(collection_name)
    vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
    if isinstance(vectors, dict) or hasattr(vectors, "keys"):
        available = [name for name in vectors.keys() if name]
        if "dense" in available:
            return "dense"
        if available:
            raise RenderFreeChatError(
                f"Collection '{collection_name}' does not use the supported 'dense' vector name."
            )
    return None


def _chunk_from_point(point) -> RetrievedChunk | None:
    payload = getattr(point, "payload", None) or {}
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    content = (
        payload.get("page_content")
        or payload.get("content")
        or payload.get("text")
        or metadata.get("page_content")
        or metadata.get("content")
        or metadata.get("text")
    )
    if not content:
        return None
    try:
        score = float(getattr(point, "score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return RetrievedChunk(content=str(content), metadata=metadata, score=score)


def _context_text(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = chunk.metadata
        file_name = metadata.get("file_name") or metadata.get("source") or "document"
        page = metadata.get("page_number") or metadata.get("page") or "n/a"
        blocks.append(f"[Source {index}: {file_name}, page {page}]\n{chunk.content[:5000]}")
    return "\n\n".join(blocks)


def _source_from_chunk(chunk: RetrievedChunk) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    metadata["retrieval_score"] = chunk.score
    return {
        "file_name": metadata.get("file_name") or metadata.get("source") or "document",
        "page_number": metadata.get("page_number") or metadata.get("page"),
        "chunk_id": metadata.get("chunk_id") or metadata.get("chunk_index"),
        "content": chunk.content,
        "score": chunk.score,
        "source_type": "vectorstore",
        "metadata": metadata,
    }


def _confidence_level(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "none"
    top_score = max(chunk.score for chunk in chunks)
    if top_score >= 0.75:
        return "high"
    if top_score >= 0.5:
        return "medium"
    return "low"


def _dedupe_repeated_sentences(answer: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in (answer or "").splitlines():
        line = raw_line.strip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        parts = line.split(". ")
        kept = []
        for index, part in enumerate(parts):
            sentence = part.strip()
            if not sentence:
                continue
            if index < len(parts) - 1 and not sentence.endswith("."):
                sentence = f"{sentence}."
            key = " ".join(sentence.lower().split())
            if key in seen:
                continue
            seen.add(key)
            kept.append(sentence)
        if kept:
            lines.append(" ".join(kept))
    return "\n".join(lines).strip()


def _validate_qdrant_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RenderFreeChatError("QDRANT_URL is not configured on the backend.")


def _raise_clean_error(error: Exception) -> None:
    status_code = getattr(error, "status_code", None)
    message = str(error).lower()
    if status_code == 429 or "insufficient_quota" in message or "quota" in message:
        raise RenderFreeChatError(OPENAI_QUOTA_MESSAGE, status_code=429) from error
    if status_code in {401, 403} or "api key" in message or "authentication" in message:
        raise RenderFreeChatError("The OpenAI API key was rejected.", status_code=400) from error
    if "not found" in message and "collection" in message:
        raise RenderFreeChatError("The selected collection was not found in Qdrant.", status_code=404) from error
    raise RenderFreeChatError("Chat is temporarily unavailable. Please try again.") from error


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
