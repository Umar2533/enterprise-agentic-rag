import uuid
import logging

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_api_key
from app.core.constants import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_COLLECTION,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_TOP_K,
)
from app.core.config import get_settings
from app.core.runtime_credentials import RuntimeCredentials
from app.db.database import get_db
from app.models.user import User
from app.schemas.collection_build_summary_schema import CollectionBuildSummaryResponse
from app.schemas.ingestion_schema import IngestionResponse
from app.services.collections.collection_build_summary_service import (
    document_units,
    file_type_from_path,
    get_collection_build_summary,
    upsert_collection_build_summary,
)
from app.services.collections.user_collection_service import (
    create_user_collection,
    get_user_collection_by_display_name,
    physical_collection_name,
)
from app.services.llm.embeddings_service import UnsupportedEmbeddingProviderError, normalize_embedding_provider
from app.services.ingestion.document_validator import (
    DocumentValidationError,
    sanitize_filename,
    validate_upload,
)
from app.services.vectordb.collection_service import document_hash_exists, ingestion_collection_exists

router = APIRouter(tags=["ingestion"])
logger = logging.getLogger(__name__)


@router.post(
    "/ingestion/upload",
    response_model=IngestionResponse,
    dependencies=[Depends(require_api_key)],
)
@router.post(
    "/upload/document",
    response_model=IngestionResponse,
    dependencies=[Depends(require_api_key)],
)
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form(DEFAULT_COLLECTION),
    chunk_size: int = Form(DEFAULT_CHUNK_SIZE),
    chunk_overlap: int = Form(DEFAULT_CHUNK_OVERLAP),
    k: int = Form(DEFAULT_TOP_K),
    max_iterations: int = Form(DEFAULT_MAX_ITERATIONS),
    enable_grading: bool = Form(True),
    enable_evaluation: bool = Form(True),
    openai_api_key: str = Form(""),
    tavily_api_key: str = Form(""),
    qdrant_url: str = Form(""),
    qdrant_api_key: str = Form(""),
    runtime_openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    runtime_tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    runtime_qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    runtime_qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    embedding_provider: str = Form(DEFAULT_EMBEDDING_PROVIDER),
    use_existing_collection: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.ingestion.pipeline import compute_document_hash
    from app.services.rag_runtime import create_rag_session, select_existing_collection

    settings = get_settings()
    content = await file.read()

    if chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail="Chunk overlap must be less than chunk size.")
    if k < 1:
        raise HTTPException(status_code=400, detail="Top K must be at least 1.")
    if max_iterations < 1:
        raise HTTPException(status_code=400, detail="Max iterations must be at least 1.")

    try:
        validate_upload(file, len(content))
    except DocumentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    saved_name = sanitize_filename(file.filename or "document")
    upload_dir = settings.upload_dir / f"user_{current_user.id}" / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / saved_name
    file_path.write_bytes(content)
    display_name = collection_name.strip() or DEFAULT_COLLECTION
    existing_user_collection = get_user_collection_by_display_name(
        db,
        current_user.id,
        display_name,
    )
    if existing_user_collection and not use_existing_collection:
        raise HTTPException(
            status_code=409,
            detail="Collection already exists. Please choose another name.",
        )
    target_collection = (
        existing_user_collection.collection_name
        if existing_user_collection is not None
        else physical_collection_name(current_user.id, display_name)
    )
    try:
        embedding_provider = normalize_embedding_provider(embedding_provider)
    except UnsupportedEmbeddingProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info(
        "Upload request collection=%s embedding_provider=%s use_existing_collection=%s chunk_size=%s chunk_overlap=%s top_k=%s max_iterations=%s enable_grading=%s enable_evaluation=%s",
        target_collection,
        embedding_provider,
        use_existing_collection,
        chunk_size,
        chunk_overlap,
        k,
        max_iterations,
        enable_grading,
        enable_evaluation,
    )
    document_hash = compute_document_hash(str(file_path))

    from app.services.vectordb.qdrant_service import (
        QdrantIngestionTimeoutError,
        qdrant_ingestion_retries,
        qdrant_runtime_credentials,
    )

    credentials = RuntimeCredentials.from_values(
        openai_api_key=runtime_openai_api_key or openai_api_key,
        tavily_api_key=runtime_tavily_api_key or tavily_api_key,
        qdrant_url=runtime_qdrant_url or qdrant_url,
        qdrant_api_key=runtime_qdrant_api_key or qdrant_api_key,
    )

    with qdrant_runtime_credentials(
        credentials.effective_qdrant_url,
        credentials.effective_qdrant_api_key,
    ), qdrant_ingestion_retries():
        try:
            existing_collection = ingestion_collection_exists(target_collection)
        except QdrantIngestionTimeoutError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if existing_collection and not use_existing_collection:
            raise HTTPException(
                status_code=409,
                detail="Collection already exists. Please choose another name.",
            )

        if existing_collection and document_hash_exists(target_collection, document_hash):
            session = select_existing_collection(
                session_id=uuid.uuid4().hex,
                collection_name=target_collection,
                embedding_provider=embedding_provider,
                credentials=credentials,
            )
            create_user_collection(
                db,
                user_id=current_user.id,
                collection_name=session.collection_name,
                display_name=display_name,
                session_id=session.session_id,
                filename=file.filename or saved_name,
                embedding_provider=session.embedding_provider,
                source="upload",
            )
            summary = get_collection_build_summary(db, session.collection_name, current_user.id)
            return IngestionResponse(
                success=True,
                session_id=session.session_id,
                collection_name=session.collection_name,
                display_name=display_name,
                filename=file.filename or saved_name,
                embedding_provider=session.embedding_provider,
                retrieval_mode=session.retrieval_mode,
                retrieval_warning=session.retrieval_warning,
                message="Document already exists",
                skipped=True,
                summary=CollectionBuildSummaryResponse.model_validate(summary) if summary else None,
            )

        session_id = uuid.uuid4().hex
        try:
            session = create_rag_session(
                session_id=session_id,
                file_path=str(file_path),
                filename=file.filename or saved_name,
                collection_name=target_collection,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                k=k,
                max_iterations=max_iterations,
                enable_grading=enable_grading,
                enable_evaluation=enable_evaluation,
                credentials=credentials,
                embedding_provider=embedding_provider,
                use_existing_collection=use_existing_collection,
            )
        except UnsupportedEmbeddingProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except QdrantIngestionTimeoutError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=credentials.redact(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Knowledge base build failed: {credentials.redact(exc)}") from exc

        create_user_collection(
            db,
            user_id=current_user.id,
            collection_name=session.collection_name,
            display_name=display_name,
            session_id=session_id,
            filename=session.filename,
            embedding_provider=session.embedding_provider,
            source="upload",
        )
        build_documents = session.build_documents or session.documents
        chunks_created = len(build_documents)
        vectors_stored = chunks_created
        file_type = file_type_from_path(file_path)
        document_units_label, document_units_value = document_units(
            file_path,
            file_type,
            build_documents,
        )
        summary = upsert_collection_build_summary(
            db,
            user_id=current_user.id,
            collection_name=session.collection_name,
            document_name=saved_name,
            file_type=file_type,
            document_units_label=document_units_label,
            document_units_value=document_units_value,
            chunks_created=chunks_created,
            vectors_stored=vectors_stored,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_provider=session.embedding_provider,
        )
        logger.info(
            "Knowledge base built: collection=%s, document=%s, file_type=%s, units=%s:%s, chunks=%s, vectors=%s, chunk_size=%s, overlap=%s, embedding_model=%s",
            session.collection_name,
            saved_name,
            summary.file_type,
            summary.document_units_label,
            summary.document_units_value if summary.document_units_value is not None else "N/A",
            summary.chunks_created,
            summary.vectors_stored,
            summary.chunk_size,
            summary.chunk_overlap,
            summary.embedding_model,
        )

        return IngestionResponse(
            success=True,
            session_id=session.session_id,
            collection_name=session.collection_name,
            display_name=display_name,
            filename=session.filename,
            embedding_provider=session.embedding_provider,
            retrieval_mode=session.retrieval_mode,
            retrieval_warning=session.retrieval_warning,
            message="Knowledge base is ready.",
            summary=CollectionBuildSummaryResponse.model_validate(summary),
        )
