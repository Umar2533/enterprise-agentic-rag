import json
import re
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from app.services.vectordb.qdrant_service import current_qdrant_scope_key


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
BM25_DIR = DATA_DIR / "bm25_indexes"
QUERY_LOG_DIR = DATA_DIR / "query_logs"


def ensure_retrieval_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BM25_DIR.mkdir(parents=True, exist_ok=True)
    QUERY_LOG_DIR.mkdir(parents=True, exist_ok=True)


def bm25_index_path(collection_name: str) -> Path:
    ensure_retrieval_dirs()
    scope_dir = BM25_DIR / _safe_name(current_qdrant_scope_key())
    scope_dir.mkdir(parents=True, exist_ok=True)
    return scope_dir / f"{_safe_name(collection_name)}.jsonl"


def save_bm25_index(collection_name: str, documents: List[Document]) -> Path:
    path = bm25_index_path(collection_name)
    with path.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(
                json.dumps(
                    {
                        "page_content": document.page_content,
                        "metadata": document.metadata or {},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


def load_bm25_index(collection_name: str) -> List[Document]:
    path = bm25_index_path(collection_name)
    if not path.exists():
        return []

    documents: List[Document] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = row.get("page_content") or ""
            if not content:
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            documents.append(Document(page_content=str(content), metadata=metadata))
    return documents


def bm25_index_exists(collection_name: str) -> bool:
    return bm25_index_path(collection_name).exists()


def _safe_name(collection_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", collection_name.strip())
    return safe.strip("._") or "default_collection"
