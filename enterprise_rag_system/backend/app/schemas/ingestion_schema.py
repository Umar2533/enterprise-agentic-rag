from pydantic import BaseModel

from app.core.constants import DEFAULT_EMBEDDING_PROVIDER
from app.schemas.collection_build_summary_schema import CollectionBuildSummaryResponse


class IngestionResponse(BaseModel):
    success: bool
    session_id: str
    collection_name: str
    display_name: str | None = None
    filename: str
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    retrieval_mode: str = "Qdrant"
    retrieval_warning: str = ""
    message: str
    skipped: bool = False
    summary: CollectionBuildSummaryResponse | None = None
