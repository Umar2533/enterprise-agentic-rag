from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import logging
import socket
import time
from typing import Any, Callable, List, TypeVar
from urllib.parse import urlparse
import uuid

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.core.config import get_settings
from app.core.runtime_credentials import RuntimeCredentials
from app.services.llm.embeddings_service import embedding_vector_size_for_provider, get_embeddings
from app.services.vectordb.base import VectorDB

_RUNTIME_QDRANT_URL: ContextVar[str] = ContextVar("runtime_qdrant_url", default="")
_RUNTIME_QDRANT_API_KEY: ContextVar[str] = ContextVar("runtime_qdrant_api_key", default="")
_INGESTION_QDRANT_RETRIES: ContextVar[bool] = ContextVar("ingestion_qdrant_retries", default=False)
logger = logging.getLogger(__name__)
_INGESTION_BACKOFF_SECONDS = (0.0, 1.5, 3.0)
_INGESTION_QDRANT_TIMEOUT_SECONDS = 90
_T = TypeVar("_T")


class QdrantConfigurationError(ValueError):
    """Raised when QDRANT_URL cannot be used to create a Qdrant client."""


class QdrantHostResolutionError(ConnectionError):
    """Raised when the configured Qdrant hostname cannot be resolved."""


class QdrantIngestionTimeoutError(ConnectionError):
    """Raised after transient Qdrant ingestion errors exhaust their retries."""


def validate_qdrant_url(url: str) -> str:
    value = str(url or "")
    stripped = value.strip()
    if not stripped or stripped.lower() in {"none", "null"}:
        raise QdrantConfigurationError("QDRANT_URL must be set to a full Qdrant Cloud URL.")
    if stripped != value or stripped[:1] in {'"', "'"} or stripped[-1:] in {'"', "'"}:
        raise QdrantConfigurationError("QDRANT_URL must not include extra spaces or quotes.")

    parsed = urlparse(stripped)
    hostname = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise QdrantConfigurationError(
            "QDRANT_URL must be a valid full URL such as https://xxxxx.cloud.qdrant.io."
        )
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        raise QdrantConfigurationError(
            "QDRANT_URL must point to the configured Qdrant Cloud host, not localhost."
        )
    return stripped


def sanitized_qdrant_host(url: str) -> str:
    try:
        return (urlparse(str(url or "").strip()).hostname or "<missing>").lower()
    except ValueError:
        return "<invalid>"


def current_qdrant_scope_key() -> str:
    settings = get_settings()
    url = (_RUNTIME_QDRANT_URL.get() or settings.qdrant_url or "").strip()
    api_key = (_RUNTIME_QDRANT_API_KEY.get() or settings.qdrant_api_key or "").strip()
    host = sanitized_qdrant_host(url) if url else "default"
    api_key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12] if api_key else "no-key"
    return f"{host}:{api_key_fingerprint}"


def _raise_qdrant_connection_error(error: Exception, url: str) -> None:
    current: BaseException | None = error
    while current is not None:
        message = str(current).lower()
        if isinstance(current, socket.gaierror) or "getaddrinfo failed" in message or "name resolution" in message:
            logger.warning("Qdrant hostname resolution failed host=%s", sanitized_qdrant_host(url))
            raise QdrantHostResolutionError(
                "Qdrant host could not be resolved. Check QDRANT_URL in .env."
            ) from error
        current = current.__cause__ or current.__context__
    raise error


def _is_transient_qdrant_error(error: Exception) -> bool:
    current: BaseException | None = error
    while current is not None:
        message = str(current).lower()
        if isinstance(current, socket.gaierror) or "getaddrinfo failed" in message or "name resolution" in message:
            return False
        if isinstance(current, (TimeoutError, socket.timeout, ConnectionResetError)):
            return True
        if (
            "winerror 10060" in message
            or "timed out" in message
            or "timeout" in message
            or "connection reset" in message
        ):
            return True
        module_name = type(current).__module__
        class_name = type(current).__name__
        if module_name.startswith("httpx") and class_name in {
            "ConnectError",
            "ConnectTimeout",
            "PoolTimeout",
            "ReadTimeout",
            "TimeoutException",
            "WriteTimeout",
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


def _run_ingestion_qdrant_operation(
    operation: Callable[[], _T],
    *,
    collection_name: str,
    operation_name: str,
    url: str,
) -> _T:
    host = sanitized_qdrant_host(url)
    for attempt, delay_seconds in enumerate(_INGESTION_BACKOFF_SECONDS, start=1):
        if delay_seconds:
            time.sleep(delay_seconds)
        logger.info(
            "Qdrant ingestion operation=%s attempt=%s/%s collection=%s host=%s",
            operation_name,
            attempt,
            len(_INGESTION_BACKOFF_SECONDS),
            collection_name,
            host,
        )
        try:
            return operation()
        except Exception as exc:
            if not _is_transient_qdrant_error(exc):
                _raise_qdrant_connection_error(exc, url)
            logger.warning(
                "Transient Qdrant ingestion failure operation=%s attempt=%s/%s collection=%s host=%s",
                operation_name,
                attempt,
                len(_INGESTION_BACKOFF_SECONDS),
                collection_name,
                host,
            )
            if attempt == len(_INGESTION_BACKOFF_SECONDS):
                raise QdrantIngestionTimeoutError(
                    "Qdrant connection timed out after retries. Please check internet/Qdrant cluster."
                ) from exc
    raise AssertionError("Qdrant ingestion retry loop completed without returning or raising.")


def _stable_point_ids(documents: List[Document], collection_name: str) -> List[str]:
    point_ids: List[str] = []
    for index, document in enumerate(documents):
        metadata = document.metadata or {}
        identity = "|".join(
            [
                collection_name,
                str(metadata.get("document_hash") or ""),
                str(metadata.get("chunk_index", index)),
                hashlib.sha256(document.page_content.encode("utf-8")).hexdigest(),
            ]
        )
        point_ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, identity)))
    return point_ids


@contextmanager
def qdrant_runtime_credentials(url: str = "", api_key: str = ""):
    url_token = _RUNTIME_QDRANT_URL.set((url or "").strip())
    api_key_token = _RUNTIME_QDRANT_API_KEY.set((api_key or "").strip())
    try:
        yield
    finally:
        try:
            _RUNTIME_QDRANT_URL.reset(url_token)
        except ValueError:
            _RUNTIME_QDRANT_URL.set("")
        try:
            _RUNTIME_QDRANT_API_KEY.reset(api_key_token)
        except ValueError:
            _RUNTIME_QDRANT_API_KEY.set("")


@contextmanager
def qdrant_ingestion_retries():
    retries_token = _INGESTION_QDRANT_RETRIES.set(True)
    try:
        yield
    finally:
        _INGESTION_QDRANT_RETRIES.reset(retries_token)


class QdrantVectorDB(VectorDB):
    def _credentials(self) -> tuple[str, str]:
        settings = get_settings()
        return (
            (_RUNTIME_QDRANT_URL.get() or settings.qdrant_url or "").strip(),
            (_RUNTIME_QDRANT_API_KEY.get() or settings.qdrant_api_key or "").strip(),
        )

    def _client(self) -> QdrantClient:
        url, api_key = self._credentials()
        url = validate_qdrant_url(url)
        logger.info("Creating Qdrant client host=%s", sanitized_qdrant_host(url))
        return _cached_qdrant_client(url, api_key)

    def list_collections(self) -> List[str]:
        url, _ = self._credentials()
        if not url:
            return []
        try:
            operation = lambda: [item.name for item in self._client().get_collections().collections]
            if _INGESTION_QDRANT_RETRIES.get():
                return _run_ingestion_qdrant_operation(
                    operation,
                    collection_name="<registry>",
                    operation_name="collection_exists",
                    url=url,
                )
            return operation()
        except QdrantIngestionTimeoutError:
            raise
        except QdrantConfigurationError as exc:
            logger.warning("Qdrant collection listing skipped: %s", exc)
            return []
        except Exception as exc:
            try:
                _raise_qdrant_connection_error(exc, url)
            except QdrantHostResolutionError:
                return []
            except Exception:
                return []
            return []

    def collection_point_count(self, collection_name: str) -> int:
        try:
            info = self._client().get_collection(collection_name)
        except Exception:
            return 0

        for attr in ("points_count", "vectors_count", "indexed_vectors_count"):
            value = getattr(info, attr, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
        return 0

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in set(self.list_collections())

    def ingestion_collection_exists(self, collection_name: str) -> bool:
        url, _ = self._credentials()
        url = validate_qdrant_url(url)
        return _run_ingestion_qdrant_operation(
            lambda: self._client().collection_exists(collection_name=collection_name),
            collection_name=collection_name,
            operation_name="collection_exists",
            url=url,
        )

    def document_hash_exists(self, collection_name: str, document_hash: str) -> bool:
        exists = (
            self.ingestion_collection_exists(collection_name)
            if _INGESTION_QDRANT_RETRIES.get()
            else self.collection_exists(collection_name)
        )
        if not exists:
            return False
        try:
            points, _ = self._client().scroll(
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
                with_payload=True,
                with_vectors=False,
            )
            return bool(points)
        except Exception:
            return False

    def delete_collection(self, collection_name: str) -> bool:
        if not self.collection_exists(collection_name):
            return False
        self._client().delete_collection(collection_name=collection_name)
        return True

    def existing_vectorstore(
        self,
        collection_name: str,
        embedding_provider: str,
        credentials: RuntimeCredentials | None = None,
        embedding_model: str | None = None,
        vector_size: int | None = None,
    ):
        url, _ = self._credentials()
        logger.info(
            "Attaching existing Qdrant collection collection=%s host=%s",
            collection_name,
            sanitized_qdrant_host(url),
        )
        try:
            client = self._client()
            vector_name, collection_vector_size = self._detect_existing_vector_config(client, collection_name)
        except (QdrantConfigurationError, QdrantHostResolutionError):
            raise
        except Exception as exc:
            _raise_qdrant_connection_error(exc, url)
        expected_vector_size = vector_size or embedding_vector_size_for_provider(
            embedding_provider,
            embedding_model,
        )
        if collection_vector_size and expected_vector_size and collection_vector_size != expected_vector_size:
            raise ValueError(
                f"Embedding vector dimension mismatch for collection '{collection_name}': "
                f"collection vector_size={collection_vector_size}, expected vector_size={expected_vector_size} "
                f"for embedding_provider={embedding_provider} embedding_model={embedding_model or '<default>'}."
            )
        kwargs = {
            "client": client,
            "embedding": get_embeddings(embedding_provider, credentials, model=embedding_model),
            "collection_name": collection_name,
        }
        if vector_name:
            kwargs["vector_name"] = vector_name
        return QdrantVectorStore(**kwargs)

    def load_documents(self, collection_name: str, batch_size: int = 256) -> List[Document]:
        if not self.collection_exists(collection_name):
            return []

        documents: List[Document] = []
        offset = None
        client = self._client()
        while True:
            points, offset = client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                document = self._document_from_payload(point.payload or {})
                if document:
                    documents.append(document)
            if offset is None:
                break
        return documents

    def build_vectorstore(
        self,
        documents: List[Document],
        collection_name: str,
        embedding_provider: str,
        credentials: RuntimeCredentials | None = None,
        embedding_model: str | None = None,
    ):
        url, api_key = self._credentials()
        url = validate_qdrant_url(url)
        logger.info(
            "Building Qdrant vector store collection=%s host=%s",
            collection_name,
            sanitized_qdrant_host(url),
        )

        point_ids = _stable_point_ids(documents, collection_name)

        try:
            return _run_ingestion_qdrant_operation(
                lambda: QdrantVectorStore.from_documents(
                    documents=documents,
                    embedding=get_embeddings(embedding_provider, credentials, model=embedding_model),
                    ids=point_ids,
                    url=url,
                    api_key=api_key or None,
                    collection_name=collection_name,
                    force_recreate=False,
                    timeout=_INGESTION_QDRANT_TIMEOUT_SECONDS,
                    check_compatibility=False,
                    trust_env=False,
                ),
                collection_name=collection_name,
                operation_name="create_get_collection_upsert",
                url=url,
            )
        except QdrantIngestionTimeoutError:
            raise
        except Exception as exc:
            _raise_qdrant_connection_error(exc, url)

    def build_retriever(
        self,
        documents: List[Document],
        collection_name: str,
        k: int,
        embedding_provider: str = "huggingface",
        credentials: RuntimeCredentials | None = None,
    ):
        vectorstore = self.build_vectorstore(documents, collection_name, embedding_provider, credentials)
        return vectorstore.as_retriever(search_kwargs={"k": k})

    @staticmethod
    def _document_from_payload(payload: dict) -> Document | None:
        content = (
            payload.get("page_content")
            or payload.get("content")
            or payload.get("text")
            or payload.get("document")
        )
        metadata = payload.get("metadata") or {}
        if not content and isinstance(metadata, dict):
            content = metadata.get("page_content") or metadata.get("content") or metadata.get("text")
        if not content:
            return None
        if not isinstance(metadata, dict):
            metadata = {}
        return Document(page_content=str(content), metadata=metadata)

    @staticmethod
    def _detect_existing_vector_name(client: QdrantClient, collection_name: str) -> str | None:
        vector_name, _ = QdrantVectorDB._detect_existing_vector_config(client, collection_name)
        return vector_name

    @staticmethod
    def _detect_existing_vector_config(client: QdrantClient, collection_name: str) -> tuple[str | None, int | None]:
        info = client.get_collection(collection_name)
        config = getattr(getattr(info, "config", None), "params", None)
        vectors_config: Any = getattr(config, "vectors", None)

        if isinstance(vectors_config, dict) or hasattr(vectors_config, "keys"):
            available = [name for name in vectors_config.keys() if name]
            if "dense" in available:
                return "dense", _vector_config_size(vectors_config.get("dense"))
            if available:
                names = ", ".join(sorted(available))
                raise ValueError(
                    f"Collection '{collection_name}' uses named vectors ({names}). "
                    "Expected a vector named 'dense'."
                )
            return None, None

        return None, _vector_config_size(vectors_config)


def _vector_config_size(vector_config: Any) -> int | None:
    size = getattr(vector_config, "size", None)
    try:
        return int(size) if size is not None else None
    except (TypeError, ValueError):
        return None


def _cached_qdrant_client(url: str, api_key: str) -> QdrantClient:
    return QdrantClient(
        url=url,
        api_key=api_key or None,
        timeout=30,
        check_compatibility=False,
        trust_env=False,
    )
