from dataclasses import dataclass
from threading import RLock
from typing import Dict, List, Tuple

from langchain_core.documents import Document

from app.core.constants import DEFAULT_EMBEDDING_PROVIDER
from app.services.llm.embeddings_service import normalize_embedding_provider
from app.services.retrieval.bm25_store import bm25_index_exists, bm25_index_path
from app.services.vectordb.factory import get_vector_db
from app.services.vectordb.qdrant_service import current_qdrant_scope_key


@dataclass
class CollectionRecord:
    collection_name: str
    source: str = "qdrant"
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    chunk_count: int = 0
    bm25_ready: bool = False


_LOCK = RLock()
_REGISTRY: Dict[Tuple[str, str], CollectionRecord] = {}
_DOCUMENTS: Dict[Tuple[str, str], List[Document]] = {}


def sync_collection_registry() -> List[dict]:
    scope_key = current_qdrant_scope_key()
    provider = get_vector_db()
    names = provider.list_collections() if hasattr(provider, "list_collections") else []
    records: List[dict] = []

    with _LOCK:
        seen = set(names)
        for stale_key in [key for key in _REGISTRY if key[0] == scope_key and key[1] not in seen]:
            _REGISTRY.pop(stale_key, None)
            _DOCUMENTS.pop(stale_key, None)

        for name in names:
            cache_key = (scope_key, name)
            documents = _DOCUMENTS.get(cache_key)
            chunk_count = len(documents) if documents is not None else _bm25_chunk_count(name)
            embedding_provider = _infer_embedding_provider(documents)
            record = CollectionRecord(
                collection_name=name,
                source="qdrant",
                embedding_provider=embedding_provider,
                chunk_count=chunk_count,
                bm25_ready=bm25_index_exists(name),
            )
            _REGISTRY[cache_key] = record
            if documents is not None:
                _DOCUMENTS[cache_key] = documents
            records.append(record.__dict__)

    return records


def register_collection(
    collection_name: str,
    documents: List[Document],
    embedding_provider: str,
    source: str = "runtime",
) -> None:
    embedding_provider = normalize_embedding_provider(embedding_provider)
    cache_key = (current_qdrant_scope_key(), collection_name)
    with _LOCK:
        _DOCUMENTS[cache_key] = list(documents)
        _REGISTRY[cache_key] = CollectionRecord(
            collection_name=collection_name,
            source=source,
            embedding_provider=embedding_provider,
            chunk_count=len(documents),
            bm25_ready=bm25_index_exists(collection_name) or bool(documents),
        )


def list_registered_collections(refresh: bool = False) -> List[dict]:
    scope_key = current_qdrant_scope_key()
    if refresh or not any(key[0] == scope_key for key in _REGISTRY):
        sync_collection_registry()
    with _LOCK:
        return [record.__dict__ for key, record in _REGISTRY.items() if key[0] == scope_key]


def collection_exists(collection_name: str) -> bool:
    cache_key = (current_qdrant_scope_key(), collection_name)
    if cache_key not in _REGISTRY:
        sync_collection_registry()
    with _LOCK:
        return cache_key in _REGISTRY


def get_collection_documents(collection_name: str) -> List[Document]:
    cache_key = (current_qdrant_scope_key(), collection_name)
    if cache_key not in _DOCUMENTS:
        sync_collection_registry()
    if cache_key not in _DOCUMENTS:
        provider = get_vector_db()
        documents = _safe_load_documents(provider, collection_name)
        with _LOCK:
            if documents:
                _DOCUMENTS[cache_key] = documents
                if cache_key in _REGISTRY:
                    _REGISTRY[cache_key].embedding_provider = _infer_embedding_provider(documents)
                    _REGISTRY[cache_key].chunk_count = len(documents)
    with _LOCK:
        return list(_DOCUMENTS.get(cache_key, []))


def remove_collection(collection_name: str) -> None:
    cache_key = (current_qdrant_scope_key(), collection_name)
    with _LOCK:
        _REGISTRY.pop(cache_key, None)
        _DOCUMENTS.pop(cache_key, None)


def _safe_load_documents(provider, collection_name: str) -> List[Document]:
    if not hasattr(provider, "load_documents"):
        return []
    try:
        return provider.load_documents(collection_name)
    except Exception:
        return []


def _bm25_chunk_count(collection_name: str) -> int:
    path = bm25_index_path(collection_name)
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


def _infer_embedding_provider(documents: List[Document] | None) -> str:
    for document in documents or []:
        provider = (document.metadata or {}).get("embedding_provider")
        if provider:
            try:
                return normalize_embedding_provider(str(provider))
            except ValueError:
                return DEFAULT_EMBEDDING_PROVIDER
    return DEFAULT_EMBEDDING_PROVIDER
