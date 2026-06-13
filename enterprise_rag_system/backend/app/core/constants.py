DEFAULT_COLLECTION = "agentic_rag_enterprise"
DEFAULT_CHUNK_SIZE = 300
DEFAULT_CHUNK_OVERLAP = 30
DEFAULT_TOP_K = 5
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_EMBEDDING_PROVIDER = "huggingface"
SUPPORTED_EMBEDDING_PROVIDERS = (
    "huggingface",
    "sentence-transformers",
    "sentence_transformers",
    "openai",
)
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"
DENSE_WEIGHT = 0.7
BM25_WEIGHT = 0.3
SIMILARITY_THRESHOLD = 0.7
RERANK_CANDIDATES = 10
FINAL_CONTEXT_DOCS = 5
