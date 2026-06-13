def build_context(documents) -> str:
    blocks = []
    for index, item in enumerate(documents, start=1):
        if hasattr(item, "document"):
            doc = item.document
            score = item.final_score
        else:
            doc = item
            score = 0.0
        metadata = getattr(doc, "metadata", {}) or {}
        content = getattr(doc, "page_content", str(doc))
        retrieval_type = getattr(item, "retrieval_type", metadata.get("retrieval_type") or metadata.get("source_type") or "hybrid")
        blocks.append(
            "\n".join(
                [
                    f"[Source {index}]",
                    f"source_type: {metadata.get('source_type', retrieval_type)}",
                    f"file_name: {metadata.get('file_name', 'unknown')}",
                    f"url: {metadata.get('url', '')}",
                    f"chunk_id: {metadata.get('chunk_id', 'unknown')}",
                    f"page_number: {metadata.get('page_number', 'n/a')}",
                    f"section_title: {metadata.get('section_title', 'Document')}",
                    f"collection_name: {metadata.get('collection_name', 'unknown')}",
                    f"retrieval_type: {retrieval_type}",
                    f"similarity_score: {score:.4f}",
                    "content:",
                    content,
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)
