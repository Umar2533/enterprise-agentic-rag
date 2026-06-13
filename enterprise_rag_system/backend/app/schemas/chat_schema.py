from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer_length: str = "Medium: 180-250 words"
    allow_web_search: bool = False
    collection_name: str | None = None
    openai_api_key: str = ""
    tavily_api_key: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    use_openai: bool = False
    force_local_stub: bool = False


class TraceStep(BaseModel):
    message: str
    kind: str = "info"


class ChatResponse(BaseModel):
    success: bool
    answer: str
    search_type: str
    evaluation: Optional[str] = None
    iteration_count: int = 1
    retrieved_docs_count: int = 0
    web_results_count: int = 0
    confidence_level: str = "unknown"
    retrieval_mode: str = "unknown"
    retrieval_warning: str = ""
    llm_provider: str = "unknown"
    llm_model: str = "unknown"
    runtime_openai_active: bool = False
    llm_fallback_warning: str = ""
    llm_fallback_status: str = ""
    error_reason: str = ""
    web_search_used: bool = False
    web_search_available: bool = False
    web_search_requires_approval: bool = False
    trace_steps: List[Dict[str, Any]] = []
    trace: List[TraceStep] = []
    sources: List[Dict[str, Any]] = []
