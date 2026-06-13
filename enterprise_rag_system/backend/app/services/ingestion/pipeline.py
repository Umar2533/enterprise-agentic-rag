from pathlib import Path
import hashlib
import re
from datetime import datetime, timezone
from typing import List

from langchain_core.documents import Document

from app.loaders.document_loader import load_document
from app.services.ingestion.document_validator import validate_saved_file
from app.services.ingestion.markdown_table_chunker import split_documents_preserving_markdown_tables


def load_and_chunk_document(
    file_path: str,
    chunk_size: int,
    chunk_overlap: int,
    collection_name: str,
    embedding_provider: str,
) -> List[Document]:
    path = Path(file_path)
    validate_saved_file(path)
    document_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    raw_docs = load_document(str(path))
    chunks = split_documents_preserving_markdown_tables(
        raw_docs,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunks:
        raise ValueError("Document is empty or could not be parsed.")

    current_section = "Document"
    created_at = datetime.now(timezone.utc).isoformat()
    for idx, chunk in enumerate(chunks):
        heading = _extract_section_title(chunk.page_content)
        if heading:
            current_section = heading
        source_page = chunk.metadata.get("page") or chunk.metadata.get("page_number") or 0
        chunk.metadata.update(
            {
                "file_name": path.name,
                "chunk_id": f"{path.stem}-{idx:05d}",
                "page_number": int(source_page) + 1 if str(source_page).isdigit() else source_page,
                "section_title": current_section,
                "document_hash": document_hash,
                "collection_name": collection_name,
                "embedding_provider": embedding_provider,
                "chunk_index": idx,
                "created_at": created_at,
            }
        )

    return chunks


def compute_document_hash(file_path: str) -> str:
    return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()


def _extract_section_title(text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    return ""
