from datetime import datetime
from io import BytesIO
from typing import Iterable


def export_chat_to_pdf(chat_history: Iterable[dict], metadata: dict) -> tuple[bytes | None, str | None]:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return None, "PDF export requires reportlab. Run: pip install reportlab"

    try:
        buffer = BytesIO()
        document = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Agentic RAG Chat Export", styles["Title"]),
            Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), styles["Normal"]),
            Paragraph(f"Active collection: {_escape(str(metadata.get('active_collection') or 'None'))}", styles["Normal"]),
            Spacer(1, 14),
        ]

        for message in chat_history:
            role = str(message.get("role", "message")).title()
            content = _escape(str(message.get("content", ""))).replace("\n", "<br/>")
            story.append(Paragraph(f"<b>{_escape(role)}</b>", styles["Heading3"]))
            story.append(Paragraph(content or "(empty)", styles["BodyText"]))
            meta = message.get("meta") or message.get("tags") or {}
            if meta:
                tags = " | ".join(
                    [
                        str(meta.get("search_type", "hybrid")),
                        str(meta.get("evaluation", "good")),
                        f"{meta.get('iteration_count', 1)} iteration",
                        f"{meta.get('retrieved_docs_count', 'n/a')} docs",
                        f"{meta.get('confidence_level', 'unknown')} confidence",
                    ]
                )
                story.append(Paragraph(_escape(tags), styles["Italic"]))
            sources = message.get("sources") or []
            if sources:
                story.append(Paragraph("<b>Used References</b>", styles["Heading4"]))
                for index, source in enumerate(sources, start=1):
                    source_meta = source.get("metadata", {}) or {}
                    source_line = " | ".join(
                        [
                            f"Ref {index}",
                            f"File: {source.get('file_name') or source_meta.get('file_name') or source_meta.get('source') or 'Unknown document'}",
                            f"Chunk: {source.get('chunk_id') or source_meta.get('chunk_id') or source_meta.get('chunk_index') or 'Unknown'}",
                            f"Page: {source.get('page_number') or source_meta.get('page_number') or source_meta.get('page') or 'n/a'}",
                            f"Score: {source.get('retrieval_score', source.get('score', source_meta.get('score', 'n/a')))}",
                            f"Retrieval: {source.get('retrieval_type') or source_meta.get('retrieval_type') or 'hybrid'}",
                        ]
                    )
                    story.append(Paragraph(_escape(source_line), styles["Normal"]))
                    chunk_text = _source_content(source)
                    if chunk_text:
                        story.append(Paragraph(_escape(chunk_text[:1200]).replace("\n", "<br/>"), styles["BodyText"]))
            story.append(Spacer(1, 10))

        document.build(story)
        pdf_bytes = buffer.getvalue()
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            return None, "PDF export failed: no PDF data was generated."
        return pdf_bytes, None
    except Exception as exc:
        return None, f"PDF export failed: {exc}"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _source_content(source: dict) -> str:
    return str(
        source.get("content")
        or source.get("page_content")
        or source.get("text")
        or source.get("chunk")
        or source.get("snippet")
        or source.get("summary")
        or ""
    )
