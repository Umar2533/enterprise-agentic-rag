from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CollectionBuildSummaryResponse(BaseModel):
    id: int
    user_id: int | None = None
    collection_name: str
    document_name: str
    file_type: str
    document_units_label: str
    document_units_value: int | None = None
    chunks_created: int
    vectors_stored: int
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    last_built_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CollectionBuildSummaryEnvelope(BaseModel):
    success: bool = True
    summary: CollectionBuildSummaryResponse | None = None
    message: str = ""
