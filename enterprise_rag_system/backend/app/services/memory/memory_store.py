import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import get_settings


_SESSION_MEMORY: Dict[str, List[dict]] = {}


def append_memory(
    session_id: str,
    collection_name: str,
    question: str,
    answer: str,
    sources: List[dict],
) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "collection_name": collection_name,
        "question": question,
        "answer": answer,
        "retrieved_chunks_metadata": [
            {
                "score": source.get("score"),
                "metadata": source.get("metadata", {}),
            }
            for source in sources
        ],
    }
    _SESSION_MEMORY.setdefault(session_id, []).append(record)
    try:
        _memory_path(collection_name).open("a", encoding="utf-8").write(
            json.dumps(record, ensure_ascii=True) + "\n"
        )
    except Exception:
        return


def get_session_memory(session_id: str) -> List[dict]:
    return list(_SESSION_MEMORY.get(session_id, []))


def get_collection_memory(collection_name: str, limit: int = 100) -> List[dict]:
    path = _memory_path(collection_name)
    if not path.exists():
        return []
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return []
    return rows[-limit:]


def memory_stats(collection_names: List[str] | None = None) -> dict:
    memory_dir = get_settings().memory_dir
    try:
        files = (
            [_memory_path(name) for name in collection_names]
            if collection_names is not None
            else list(memory_dir.glob("*.jsonl"))
        )
    except Exception:
        return {"collections_with_memory": 0, "records": 0}
    records = 0
    collections_with_memory = 0
    for path in files:
        if not path.exists():
            continue
        try:
            records += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            collections_with_memory += 1
        except Exception:
            continue
    return {"collections_with_memory": collections_with_memory, "records": records}


def _memory_path(collection_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", collection_name or "default")
    return get_settings().memory_dir / f"{safe_name}.jsonl"
