# Architecture

```text
Streamlit frontend
  -> FastAPI upload/chat routes
  -> ingestion validation and table-aware chunking
  -> embeddings service
  -> vector DB factory
  -> Qdrant retriever + BM25 retriever
  -> LangGraph agent
  -> OpenAI generation and Tavily fallback
```

The backend keeps active RAG sessions in memory for this starter. For production,
replace the runtime session store with Redis, a database, or persistent job state.

