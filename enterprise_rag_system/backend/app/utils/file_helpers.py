import re
import uuid
from pathlib import Path


def safe_filename(filename: str) -> str:
    stem = Path(filename).stem.strip() or "document"
    suffix = Path(filename).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)[:80]
    return f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def file_size_mb(size_bytes: int) -> float:
    return round(size_bytes / (1024 * 1024), 2)

