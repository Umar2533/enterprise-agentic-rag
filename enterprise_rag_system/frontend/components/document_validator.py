from pathlib import Path
from typing import Optional, Tuple


ALLOWED_EXTENSIONS = {"txt", "md", "pdf", "docx", "doc", "csv"}
MAX_UPLOAD_MB = 25


def validate_uploaded_document(uploaded_file) -> Tuple[bool, str]:
    if uploaded_file is None:
        return False, "Upload a TXT, Markdown, PDF, DOCX, DOC, or CSV file."

    extension = Path(uploaded_file.name).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file type: .{extension or 'unknown'}"

    size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
    if size_mb <= 0:
        return False, "The selected document is empty."
    if size_mb > MAX_UPLOAD_MB:
        return False, f"File is {size_mb:.1f} MB. Maximum allowed size is {MAX_UPLOAD_MB} MB."

    return True, f"{uploaded_file.name} is valid ({size_mb:.2f} MB)."

