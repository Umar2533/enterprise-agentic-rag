from app.core.config import get_settings
from app.services.vectordb.qdrant_service import QdrantVectorDB


def get_vector_db():
    settings = get_settings()
    provider = settings.vector_db_provider.lower().strip()

    if provider == "qdrant":
        return QdrantVectorDB()

    raise ValueError(f"Unsupported vector DB provider: {settings.vector_db_provider}")

