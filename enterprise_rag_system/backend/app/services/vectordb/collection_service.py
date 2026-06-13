from app.core.config import get_settings
from app.core.vector_db_registry import SUPPORTED_VECTOR_DBS
from app.services.vectordb.collection_registry import (
    collection_exists as registry_collection_exists,
    list_registered_collections,
    remove_collection,
    sync_collection_registry,
)
from app.services.vectordb.factory import get_vector_db


def vector_provider_info() -> dict:
    settings = get_settings()
    return {
        "active_provider": settings.vector_db_provider,
        "supported_providers": list(SUPPORTED_VECTOR_DBS.keys()),
    }


def list_qdrant_collections() -> list[str]:
    return [item["collection_name"] for item in list_registered_collections(refresh=True)]


def collection_exists(collection_name: str) -> bool:
    return registry_collection_exists(collection_name)


def ingestion_collection_exists(collection_name: str) -> bool:
    provider = get_vector_db()
    if hasattr(provider, "ingestion_collection_exists"):
        return provider.ingestion_collection_exists(collection_name)
    return registry_collection_exists(collection_name)


def document_hash_exists(collection_name: str, document_hash: str) -> bool:
    provider = get_vector_db()
    if hasattr(provider, "document_hash_exists"):
        return provider.document_hash_exists(collection_name, document_hash)
    return False


def delete_qdrant_collection(collection_name: str) -> bool:
    provider = get_vector_db()
    if hasattr(provider, "delete_collection"):
        deleted = provider.delete_collection(collection_name)
        if deleted:
            remove_collection(collection_name)
        return deleted
    return False


def sync_qdrant_registry() -> list[dict]:
    return sync_collection_registry()
