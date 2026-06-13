def dedupe_documents(documents, limit: int):
    seen = set()
    merged = []
    for doc in documents:
        key = doc.page_content[:120]
        if key not in seen:
            seen.add(key)
            merged.append(doc)
    return merged[:limit]

