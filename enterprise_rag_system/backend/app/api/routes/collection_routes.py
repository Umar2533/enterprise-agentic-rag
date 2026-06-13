import uuid
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_admin, require_api_key
from app.core.constants import DEFAULT_COLLECTION, DEFAULT_EMBEDDING_PROVIDER
from app.core.runtime_credentials import RuntimeCredentials
from app.db.database import get_db
from app.models.user import User
from app.models.user_collection import UserCollection
from app.schemas.collection_build_summary_schema import CollectionBuildSummaryEnvelope
from app.services.collections.collection_build_summary_service import (
    get_collection_build_summary,
    get_collection_build_summary_for_collection,
)
from app.services.collections.user_collection_service import (
    deactivate_user_collection,
    get_all_active_user_collections,
    get_user_collection_by_name,
    get_user_collections,
    update_user_collection_session,
    user_owns_session,
)
from app.services.llm.embeddings_service import UnsupportedEmbeddingProviderError, normalize_embedding_provider
from app.services.memory.memory_store import get_collection_memory, memory_stats
from app.services.vectordb.collection_service import delete_qdrant_collection, sync_qdrant_registry
from app.services.vectordb.qdrant_service import (
    QdrantConfigurationError,
    QdrantHostResolutionError,
    qdrant_runtime_credentials,
    sanitized_qdrant_host,
)

router = APIRouter(prefix="/collections", tags=["collections"])
logger = logging.getLogger(__name__)


def _rag_runtime():
    from app.services import rag_runtime

    return rag_runtime


class SelectCollectionRequest(BaseModel):
    collection_name: str
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER


def _runtime_credentials_from_headers(
    openai_api_key: str = "",
    tavily_api_key: str = "",
    qdrant_url: str = "",
    qdrant_api_key: str = "",
) -> RuntimeCredentials:
    return RuntimeCredentials.from_values(
        openai_api_key=openai_api_key,
        tavily_api_key=tavily_api_key,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
    )


def _collection_item(
    user_collection: UserCollection,
    runtime_by_name: dict[str, dict],
    registry_by_name: dict[str, dict],
    include_owner: bool = False,
) -> dict:
    collection_name = user_collection.collection_name
    display_name = user_collection.display_name or collection_name
    runtime_item = runtime_by_name.get(collection_name, {})
    registry_item = registry_by_name.get(collection_name, {})
    item = {
        "session_id": user_collection.session_id or runtime_item.get("session_id", ""),
        "collection_name": collection_name,
        "display_name": display_name,
        "name": display_name,
        "filename": user_collection.filename
        or runtime_item.get("filename")
        or "existing_qdrant_collection",
        "embedding_provider": normalize_embedding_provider(
            user_collection.embedding_provider
            or runtime_item.get("embedding_provider")
            or registry_item.get("embedding_provider")
        ),
        "source": user_collection.source or runtime_item.get("source") or "upload",
        "chunk_count": registry_item.get("chunk_count", 0),
        "bm25_ready": registry_item.get("bm25_ready", False),
    }
    if runtime_item.get("retrieval_mode"):
        item["retrieval_mode"] = runtime_item["retrieval_mode"]
    if runtime_item.get("retrieval_warning"):
        item["retrieval_warning"] = runtime_item["retrieval_warning"]
    if include_owner:
        item["owner_user_id"] = user_collection.user_id
    return item


@router.get("", dependencies=[Depends(require_api_key)])
@router.get("/list", dependencies=[Depends(require_api_key)])
def list_collections(
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    credentials = _runtime_credentials_from_headers(openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    with qdrant_runtime_credentials(
        credentials.effective_qdrant_url,
        credentials.effective_qdrant_api_key,
    ):
        registered_collections = sync_qdrant_registry()
        sessions = _rag_runtime().list_sessions()
        runtime_by_name = {session["collection_name"]: session for session in sessions}
        registry_by_name = {
            item["collection_name"]: item
            for item in registered_collections
            if item.get("collection_name")
        }
        is_admin = current_user.is_superuser or current_user.role == "admin"
        user_collections = (
            get_all_active_user_collections(db)
            if is_admin
            else get_user_collections(db, current_user.id)
        )
        collection_items = [
            _collection_item(
                user_collection,
                runtime_by_name,
                registry_by_name,
                include_owner=is_admin,
            )
            for user_collection in user_collections
        ]
        return {
            "success": True,
            "collections": collection_items,
            "default_collection": DEFAULT_COLLECTION,
            "message": "User collections listed.",
        }


@router.post("/select", dependencies=[Depends(require_api_key)])
def select_collection(
    request: SelectCollectionRequest,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not request.collection_name.strip():
        raise HTTPException(status_code=400, detail="Collection name is required.")
    requested_collection = request.collection_name.strip()
    user_collection = get_user_collection_by_name(db, current_user.id, requested_collection)
    if user_collection is None and not (current_user.is_superuser or current_user.role == "admin"):
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    credentials = _runtime_credentials_from_headers(openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    started = time.monotonic()
    try:
        embedding_provider = normalize_embedding_provider(request.embedding_provider)
        logger.info(
            "Collection select payload collection=%s embedding_provider=%s qdrant_host=%s",
            requested_collection,
            embedding_provider,
            sanitized_qdrant_host(credentials.effective_qdrant_url),
        )
        with qdrant_runtime_credentials(
            credentials.effective_qdrant_url,
            credentials.effective_qdrant_api_key,
        ):
            qdrant_started = time.monotonic()
            session = _rag_runtime().select_existing_collection(
                session_id=uuid.uuid4().hex,
                collection_name=requested_collection,
                embedding_provider=embedding_provider,
                credentials=credentials,
            )
            logger.info(
                "Collection select qdrant_attach_elapsed_seconds=%.3f collection=%s",
                time.monotonic() - qdrant_started,
                requested_collection,
            )
    except QdrantHostResolutionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except QdrantConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedEmbeddingProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Collection selection failed: {credentials.redact(exc)}") from exc
    if user_collection is not None:
        user_collection = update_user_collection_session(
            db,
            user_collection_id=user_collection.id,
            session_id=session.session_id,
        )
    display_name = (
        user_collection.display_name
        if user_collection is not None and user_collection.display_name
        else session.collection_name
    )
    cleared_sessions = 0
    for owned_collection in get_user_collections(db, current_user.id):
        previous_session_id = owned_collection.session_id
        if (
            previous_session_id
            and previous_session_id != session.session_id
            and owned_collection.collection_name != session.collection_name
        ):
            cleared_sessions += int(_rag_runtime().delete_session(previous_session_id))
    logger.info(
        "Collection selected session_id=%s collection=%s cleared_old_runtime_sessions=%s elapsed_seconds=%.3f",
        session.session_id,
        session.collection_name,
        cleared_sessions,
        time.monotonic() - started,
    )
    return {
        "success": True,
        "session_id": session.session_id,
        "collection_name": session.collection_name,
        "display_name": display_name,
        "filename": session.filename,
        "embedding_provider": session.embedding_provider,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "retrieval_mode": session.retrieval_mode,
        "retrieval_warning": session.retrieval_warning,
    }


@router.get("/active/{collection_name}", dependencies=[Depends(require_api_key)])
def active_collection_session(
    collection_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested_collection = collection_name.strip()
    if not requested_collection:
        raise HTTPException(status_code=400, detail="Collection name is required.")
    user_collection = get_user_collection_by_name(db, current_user.id, requested_collection)
    if user_collection is None and not (current_user.is_superuser or current_user.role == "admin"):
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    if user_collection is None:
        return {"success": True, "active": False, "collection_name": requested_collection, "session_id": ""}
    session = _rag_runtime().get_runtime_session(user_collection.session_id or "") if user_collection.session_id else None
    active = bool(session and session.collection_name == requested_collection)
    return {
        "success": True,
        "active": active,
        "session_id": user_collection.session_id or "",
        "collection_name": user_collection.collection_name,
        "display_name": user_collection.display_name or user_collection.collection_name,
        "filename": user_collection.filename or "existing_qdrant_collection",
        "embedding_provider": normalize_embedding_provider(user_collection.embedding_provider),
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "retrieval_mode": session.retrieval_mode if session else "",
        "retrieval_warning": session.retrieval_warning if session else "",
    }


@router.get(
    "/{collection_name}/summary",
    response_model=CollectionBuildSummaryEnvelope,
    dependencies=[Depends(require_api_key)],
)
def collection_build_summary(
    collection_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested_collection = collection_name.strip()
    user_collection = get_user_collection_by_name(db, current_user.id, requested_collection)
    is_admin = current_user.is_superuser or current_user.role == "admin"
    if user_collection is None and not is_admin:
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")

    summary = get_collection_build_summary(db, requested_collection, current_user.id)
    if summary is None and is_admin:
        summary = get_collection_build_summary_for_collection(db, requested_collection)
    if summary is None:
        return {
            "success": True,
            "summary": None,
            "message": "No build summary available for this collection yet.",
        }
    return {
        "success": True,
        "summary": summary,
        "message": "Collection build summary loaded.",
    }


@router.post("/bm25/rebuild/{collection_name}", dependencies=[Depends(require_api_key), Depends(get_current_user)])
def rebuild_collection_bm25(
    collection_name: str,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested_collection = collection_name.strip()
    user_collection = get_user_collection_by_name(db, current_user.id, requested_collection)
    if user_collection is None and not (current_user.is_superuser or current_user.role == "admin"):
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    credentials = _runtime_credentials_from_headers(openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    with qdrant_runtime_credentials(
        credentials.effective_qdrant_url,
        credentials.effective_qdrant_api_key,
    ):
        result = _rag_runtime().rebuild_bm25_index(requested_collection)
        sync_qdrant_registry()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "BM25 rebuild failed."))
    return result


@router.get("/memory/stats", dependencies=[Depends(require_api_key)])
def collection_memory_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin = current_user.is_superuser or current_user.role == "admin"
    collection_names = None if is_admin else [item.collection_name for item in get_user_collections(db, current_user.id)]
    return {"success": True, **memory_stats(collection_names)}


@router.get("/memory/{collection_name}", dependencies=[Depends(require_api_key)])
def collection_memory(
    collection_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested_collection = collection_name.strip()
    is_admin = current_user.is_superuser or current_user.role == "admin"
    user_collection = get_user_collection_by_name(db, current_user.id, requested_collection)
    if user_collection is None and not is_admin:
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    return {
        "success": True,
        "collection_name": requested_collection,
        "memory": get_collection_memory(requested_collection),
    }


@router.delete("/{session_id}", dependencies=[Depends(require_api_key)])
@router.delete("/delete/{session_id}", dependencies=[Depends(require_api_key)])
def delete_collection(
    session_id: str,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_admin = current_user.is_superuser or current_user.role == "admin"
    if not is_admin and not user_owns_session(db, current_user.id, session_id):
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    credentials = _runtime_credentials_from_headers(openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    with qdrant_runtime_credentials(
        credentials.effective_qdrant_url,
        credentials.effective_qdrant_api_key,
    ):
        collection_name = ""
        session = _rag_runtime().get_runtime_session(session_id)
        if session:
            collection_name = session.collection_name

        deleted_runtime = _rag_runtime().delete_session(session_id)
        deleted_qdrant = False
        if collection_name:
            deleted_qdrant = delete_qdrant_collection(collection_name)
            _rag_runtime().delete_sessions_for_collection(collection_name)

        if not deleted_runtime and not deleted_qdrant:
            raise HTTPException(status_code=404, detail="Collection session not found.")
        return {
            "success": True,
            "message": "Collection deleted." if deleted_qdrant else "Collection removed from active runtime.",
        }


@router.delete("/delete/by-name/{collection_name}", dependencies=[Depends(require_api_key)])
def delete_collection_by_name(
    collection_name: str,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    requested_collection = collection_name.strip()
    is_admin = current_user.is_superuser or current_user.role == "admin"
    user_collection = get_user_collection_by_name(db, current_user.id, requested_collection)
    if not is_admin and user_collection is None:
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    credentials = _runtime_credentials_from_headers(openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    with qdrant_runtime_credentials(
        credentials.effective_qdrant_url,
        credentials.effective_qdrant_api_key,
    ):
        deleted_qdrant = delete_qdrant_collection(requested_collection)
        _rag_runtime().delete_sessions_for_collection(requested_collection)
        if not deleted_qdrant:
            raise HTTPException(status_code=404, detail="Qdrant collection not found.")
        if user_collection is not None:
            deactivate_user_collection(db, user_collection.id)
        elif is_admin:
            for owned_collection in db.query(UserCollection).filter(
                UserCollection.collection_name == requested_collection,
                UserCollection.is_active.is_(True),
            ).all():
                deactivate_user_collection(db, owned_collection.id)
        return {"success": True, "message": "Collection deleted."}
