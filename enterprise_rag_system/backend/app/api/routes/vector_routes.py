from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_api_key
from app.core.config import get_settings
from app.core.rag_mode import require_rag_runtime
from app.core.vector_db_registry import SUPPORTED_VECTOR_DBS
from app.core.runtime_credentials import RuntimeCredentials
from app.db.database import get_db
from app.models.user import User
from app.services.collections.user_collection_service import user_owns_session

router = APIRouter(tags=["vectors"])


class VectorSearchRequest(BaseModel):
    session_id: str
    query: str
    openai_api_key: str = ""


@router.get("/vectors/provider")
def provider_info():
    settings = get_settings()
    return {
        "success": True,
        "active_provider": settings.vector_db_provider,
        "supported_providers": list(SUPPORTED_VECTOR_DBS.keys()),
    }


@router.post("/vector/search", dependencies=[Depends(require_api_key), Depends(get_current_user)])
def vector_search(
    request: VectorSearchRequest,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_rag_runtime()

    from app.services.rag_runtime import retrieve_session_sources
    from app.services.vectordb.qdrant_service import qdrant_runtime_credentials

    if not request.session_id or (
        not (current_user.is_superuser or current_user.role == "admin")
        and not user_owns_session(db, current_user.id, request.session_id)
    ):
        raise HTTPException(status_code=403, detail="You do not have access to this collection.")
    credentials = RuntimeCredentials.from_values(
        openai_api_key=openai_api_key or request.openai_api_key,
        tavily_api_key=tavily_api_key,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
    )
    try:
        with qdrant_runtime_credentials(
            credentials.effective_qdrant_url,
            credentials.effective_qdrant_api_key,
        ):
            sources = retrieve_session_sources(request.session_id, request.query, credentials)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {credentials.redact(exc)}") from exc
    return {
        "success": True,
        "sources": [source.as_source() for source in sources],
    }
