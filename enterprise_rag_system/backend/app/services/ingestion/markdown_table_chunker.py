import re
from typing import List

from langchain_core.documents import Document


TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _looks_like_table_start(lines: List[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and bool(TABLE_SEPARATOR_RE.match(lines[index + 1]))


def _split_markdown_table_blocks(text: str) -> List[tuple[str, str]]:
    lines = text.splitlines()
    blocks: List[tuple[str, str]] = []
    paragraph: List[str] = []
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            content = "\n".join(paragraph).strip()
            if content:
                blocks.append(("text", content))
            paragraph.clear()

    while i < len(lines):
        if _looks_like_table_start(lines, i):
            flush_paragraph()
            table_lines = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            blocks.append(("table", "\n".join(table_lines).strip()))
            continue

        paragraph.append(lines[i])
        i += 1

    flush_paragraph()
    return blocks


def split_documents_preserving_markdown_tables(
    documents: List[Document],
    chunk_size: int,
    chunk_overlap: int,
) -> List[Document]:
    """Split text while keeping each Markdown table as one complete chunk.

    If a table is bigger than chunk_size, it still remains intact because partial
    table chunks usually destroy row/header meaning in RAG retrieval.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks: List[Document] = []

    for doc in documents:
        blocks = _split_markdown_table_blocks(doc.page_content)
        for block_type, content in blocks:
            metadata = {**doc.metadata, "chunk_type": block_type}
            if block_type == "table":
                chunks.append(Document(page_content=content, metadata=metadata))
            else:
                for chunk in splitter.split_text(content):
                    if chunk.strip():
                        chunks.append(Document(page_content=chunk, metadata=metadata))

    return chunks
