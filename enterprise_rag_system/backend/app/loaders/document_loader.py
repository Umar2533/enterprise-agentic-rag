import csv
from pathlib import Path
from typing import List

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document


def _csv_to_markdown(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:]

    def row_to_md(row: list[str]) -> str:
        return "| " + " | ".join(cell.strip().replace("\n", " ") for cell in row) + " |"

    lines = [row_to_md(header), "| " + " | ".join(["---"] * width) + " |"]
    lines.extend(row_to_md(row) for row in body)
    return "\n".join(lines)


def load_document(path: str) -> List[Document]:
    file_path = Path(path)
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return PyPDFLoader(str(file_path)).load()
    if ext in {".docx", ".doc"}:
        return Docx2txtLoader(str(file_path)).load()
    if ext == ".csv":
        return [Document(page_content=_csv_to_markdown(file_path), metadata={"source": str(file_path)})]

    return TextLoader(str(file_path), encoding="utf-8").load()

