import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import UploadFile

from app.core.config import get_settings


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".md"}
DEFAULT_MAX_UPLOAD_SIZE_MB = 25
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class DocumentValidationError(ValueError):
    pass


def sanitize_filename(filename: str) -> str:
    name = _clean_filename(filename)
    path = Path(name)
    suffix = path.suffix.lower()
    stem = path.stem.strip() or "document"
    safe_stem = SAFE_FILENAME_PATTERN.sub("_", stem).strip("._") or "document"
    return f"{safe_stem[:80]}{suffix}"


def validate_upload(file: UploadFile, size_bytes: int) -> None:
    settings = get_settings()
    filename = _clean_filename(file.filename or "")
    suffix = Path(filename).suffix.lower()
    allowed = _allowed_extensions()

    _validate_safe_filename(filename)
    if suffix not in allowed:
        allowed_list = ", ".join(sorted(allowed))
        raise DocumentValidationError(f"Unsupported file type. Allowed: {allowed_list}.")
    if size_bytes <= 0:
        raise DocumentValidationError("Uploaded document is empty.")

    max_upload_size_mb = getattr(
        settings,
        "max_upload_size_mb",
        getattr(settings, "max_upload_mb", DEFAULT_MAX_UPLOAD_SIZE_MB),
    )
    max_bytes = max_upload_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise DocumentValidationError(
            f"File is too large. Maximum size is {max_upload_size_mb} MB."
        )


def validate_saved_file(path: Path) -> None:
    if not path.exists():
        raise DocumentValidationError("Uploaded file was not saved.")
    if path.stat().st_size == 0:
        raise DocumentValidationError("Saved document is empty.")


def _allowed_extensions() -> set[str]:
    return ALLOWED_EXTENSIONS


def _clean_filename(filename: str) -> str:
    return filename.strip()


def _validate_safe_filename(filename: str) -> None:
    if not filename:
        raise DocumentValidationError("Missing file name.")

    # Reject paths before sanitizing so uploads cannot escape the upload directory.
    if (
        "/" in filename
        or "\\" in filename
        or PurePosixPath(filename).is_absolute()
        or PureWindowsPath(filename).is_absolute()
        or ".." in PurePosixPath(filename).parts
        or ".." in PureWindowsPath(filename).parts
    ):
        raise DocumentValidationError("Unsafe file name.")
