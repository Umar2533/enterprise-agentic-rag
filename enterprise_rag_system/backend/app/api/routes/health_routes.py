from fastapi import APIRouter, Header

from app.core.constants import DEFAULT_EMBEDDING_PROVIDER, SUPPORTED_EMBEDDING_PROVIDERS
from app.core.config import get_settings
from app.core.runtime_credentials import RuntimeCredentials

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check(
    runtime_openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    use_openai: str = Header("", alias="X-Use-OpenAI"),
    force_local_stub: str = Header("", alias="X-Force-Local-Stub"),
):
    settings = get_settings()
    credentials = RuntimeCredentials.from_values(
        openai_api_key=runtime_openai_api_key,
        use_openai=use_openai.strip().lower() in {"1", "true", "yes", "on"},
        force_local_stub=force_local_stub.strip().lower() in {"1", "true", "yes", "on"},
    )
    effective_llm_provider = credentials.llm_provider
    local_test_mode = bool(settings.local_test_mode or effective_llm_provider == "local_stub")
    return {
        "success": True,
        "app": settings.app_name,
        "vector_db_provider": settings.vector_db_provider,
        "embedding_provider": DEFAULT_EMBEDDING_PROVIDER,
        "supported_embedding_providers": list(SUPPORTED_EMBEDDING_PROVIDERS),
        "openai_configured": bool(settings.openai_api_key),
        "llm_provider": effective_llm_provider,
        "effective_llm_provider": effective_llm_provider,
        "llm_model": credentials.llm_model,
        "local_test_mode": local_test_mode,
        "runtime_openai_active": credentials.runtime_openai_active,
        "qdrant_configured": bool(settings.qdrant_url),
        "qdrant_api_key_configured": bool(settings.qdrant_api_key),
        "tavily_configured": bool(settings.tavily_api_key),
    }
