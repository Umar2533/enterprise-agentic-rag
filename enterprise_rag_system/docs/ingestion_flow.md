# Ingestion Flow

```text
Upload document
  -> frontend validation
  -> FastAPI validation
  -> save to backend/data/uploads
  -> load document
  -> preserve Markdown tables
  -> chunk text
  -> embed chunks
  -> index in Qdrant
  -> create in-memory chat session
```

