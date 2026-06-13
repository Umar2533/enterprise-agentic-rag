# Enterprise Agentic RAG System

Runnable FastAPI + Streamlit RAG system based on your existing `rag_agent.py` logic.

## What is included

- FastAPI backend with upload, chat, health, vector-provider, and starter collection routes.
- Streamlit frontend with professional upload/chat UI.
- Qdrant as the current vector DB provider.
- Vector DB abstraction so Pinecone, Weaviate, Chroma, Milvus, or FAISS can be added later.
- Markdown-based table chunking: Markdown tables are kept as complete chunks.
- CSV files are converted to Markdown tables before chunking.
- Your original LangGraph flow is preserved: retrieve, grade, generate, evaluate, web fallback.

## Setup

```bash
cd enterprise_rag_system
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy backend\.env.example backend\.env
```

Fill `backend/.env`:

```env
OPENAI_API_KEY=your_openai_key
TAVILY_API_KEY=your_tavily_key
VECTOR_DB_PROVIDER=qdrant
QDRANT_URL=your_qdrant_url
QDRANT_API_KEY=your_qdrant_key
```

## Security & Authentication

Keep `.env` private and do not commit it. Use `.env.example` as the safe template for local setup and deployment. Never expose API keys, JWT secrets, database passwords, access tokens, refresh tokens, or token hashes in logs, UI, client-side storage, screenshots, commits, or documentation.

### Level 1: Backend API Key

The backend supports shared API-key protection through:

```env
BACKEND_API_KEY=your_backend_api_key
```

Protected backend requests must include:

```http
X-API-Key: your_backend_api_key
```

This header remains required for protected RAG and admin-facing API routes. The Streamlit frontend can send it from runtime session secrets or environment configuration.

### Level 2: JWT User Authentication

User authentication is handled with JWT access tokens plus refresh tokens. Auth endpoints are:

```text
POST /api/v1/auth/signup
POST /api/v1/auth/login
GET  /api/v1/auth/me
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
```

Token flow:

- `/auth/login` returns an `access_token`, `refresh_token`, `token_type`, and `user`.
- Auth cookie issuance is disabled by default. The Streamlit frontend uses Bearer access tokens and sends refresh tokens in JSON request bodies.
- Send the access token on protected requests:

```http
Authorization: Bearer your_access_token
```

- Use the `refresh_token` with `/auth/refresh` to renew the session when the access token expires.
- `/auth/refresh` accepts the refresh token from the JSON body, returns a new access token, and rotates the refresh token.
- `/auth/logout` revokes the refresh token supplied in the JSON body.
- Refresh tokens are stored in the database as hashes only. Raw refresh tokens are returned only to the client at issue/rotation time.

### Email Verification And Password Reset

Signup and forgot-password flows can send real emails when SMTP is configured:

```env
MAIL_ENABLED=true
MAIL_FROM=your-address@gmail.com
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-address@gmail.com
MAIL_PASSWORD=replace_with_google_app_password
MAIL_USE_TLS=true
FRONTEND_BASE_URL=http://localhost:8501
```

For Gmail, `MAIL_PASSWORD` must be a Google App Password, not your normal Google account password. `MAIL_ENABLED=true` is required for real verification and reset emails to be sent. `FRONTEND_BASE_URL` controls the domain used in email verification and password reset links.

### Auth Database

Authentication uses a SQLAlchemy/PostgreSQL-ready database foundation configured by:

```env
DATABASE_URL=postgresql://user:password@host:5432/database_name
JWT_SECRET_KEY=replace_with_a_strong_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
AUTH_COOKIE_ENABLED=false
ACCESS_COOKIE_NAME=access_token
REFRESH_COOKIE_NAME=refresh_token
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_SECURE=false
```

Auth tables:

- `users`: stores user account records, password hashes, role, active state, and superuser flag.
- `refresh_tokens`: stores hashed refresh tokens, user ownership, expiry, revocation time, user agent, and IP address metadata.

Do not hardcode database credentials or JWT secrets. Use environment variables or deployment secret management.

### Roles And Route Protection

Supported role fields:

- `role="user"`: standard authenticated user.
- `role="admin"`: admin role.
- `is_superuser=True`: superuser override for admin-only access.

Protected user-facing routes require both:

```http
X-API-Key: your_backend_api_key
Authorization: Bearer your_access_token
```

Admin/destructive routes require all of the following:

- valid `X-API-Key`
- valid JWT bearer token
- `role == "admin"` or `is_superuser == True`

Primary admin accounts can be protected from accidental demotion or deactivation with either the legacy single-email setting or the comma-separated multi-email setting:

```env
PRIMARY_ADMIN_EMAIL=owner@example.com
PRIMARY_ADMIN_EMAILS=admin@example.com,backup@example.com
```

Emails are normalized to lowercase and spaces are ignored. Any matching account is treated as a primary admin even if the database flag is not set.

Public routes such as health checks and vector provider metadata remain available without JWT where configured. Protected routes include chat, chat streaming, upload/ingestion, collection select/rebuild/delete, vector search, and admin routes. Collection deletion and all `/admin` routes are admin-only.

Allowed upload file types are `.pdf`, `.docx`, `.txt`, `.csv`, and `.md`.

## Run Backend

```bash
cd backend
uvicorn app.main:app --reload
```

Backend docs:

```text
http://localhost:8000/docs
```

## Run Frontend

Open another terminal:

```bash
cd enterprise_rag_system
streamlit run frontend/app.py
```

## Table Chunking Strategy

Markdown tables are detected by a header row plus separator row:

```markdown
| Name | Value |
| --- | --- |
| A | 10 |
| B | 20 |
```

Each complete table becomes one chunk, even if the table is larger than the normal text chunk size. This prevents retrieval from separating table headers from rows.

## Future Vector DB Providers

Current provider:

```text
backend/app/services/vectordb/qdrant_service.py
```

Future providers can follow the same interface:

```text
backend/app/services/vectordb/base.py
```

Then register them in:

```text
backend/app/core/vector_db_registry.py
backend/app/services/vectordb/factory.py
```

New project/                                      # Main workspace folder
├── enterprise_rag_system/                       # Recent main project: Enterprise Agentic RAG System
│   ├── README.md                                # Project setup, run commands, feature overview
│   ├── requirements.txt                         # Root Python dependencies for backend/frontend
│   ├── LICENSE                                  # Project license file
│   │
│   ├── backend/
        ├── .env                                 
│   │   ├── Dockerfile                           # Backend container build file
│   │   ├── requirements.txt                     # Backend-specific Python dependencies
│   │   ├── app/                                 # Main backend application package
│   │   │   ├── main.py                          # FastAPI app entry point, routes include hotay hain
│   │   │   ├── __init__.py                      # Python package marker
│   │   │   │
│   │   │   ├── api/                             # API layer: dependencies and route registration
│   │   │   │   ├── dependencies.py              # Shared FastAPI dependencies
│   │   │   │   ├── __init__.py                  # API package marker
│   │   │   │   └── routes/                      # Endpoint files grouped by feature
│   │   │   │       ├── admin_routes.py          # Admin-related API endpoints
│   │   │   │       ├── auth_routes.py           # Auth/API-key/session related endpoints
│   │   │   │       ├── chat_routes.py           # Chat/RAG question-answer endpoints
│   │   │   │       ├── collection_routes.py     # Knowledge-base collection CRUD/list endpoints
│   │   │   │       ├── health_routes.py         # Health check/status endpoints
│   │   │   │       ├── ingestion_routes.py      # File upload and document ingestion endpoints
│   │   │   │       ├── vector_routes.py         # Vector search/provider endpoints
│   │   │   │       └── __init__.py              # Routes package marker
│   │   │   │
│   │   │   ├── core/                            # Core config/constants/prompts
│   │   │   │   ├── config.py                    # Environment variables and app settings
│   │   │   │   ├── constants.py                 # Shared constant values
│   │   │   │   ├── prompts.py                   # RAG/LLM prompt templates
│   │   │   │   ├── vector_db_registry.py        # Vector DB provider registry
│   │   │   │   └── __init__.py                  # Core package marker
│   │   │   │
│   │   │   ├── loaders/                         # Document loading/parsing layer
│   │   │   │   ├── document_loader.py           # PDF/DOCX/TXT/CSV etc. load karne ka logic
│   │   │   │   └── __init__.py                  # Loaders package marker
│   │   │   │
│   │   │   ├── schemas/                         # Pydantic request/response models
│   │   │   │   ├── chat_schema.py               # Chat request/response models
│   │   │   │   ├── collection_schema.py         # Collection models
│   │   │   │   ├── ingestion_schema.py          # Upload/ingestion models
│   │   │   │   ├── response_schema.py           # Common API response models
│   │   │   │   ├── vector_schema.py             # Vector search/provider models
│   │   │   │   └── __init__.py                  # Schemas package marker
│   │   │   │
│   │   │   ├── services/                        # Business logic layer
│   │   │   │   ├── rag_runtime.py               # RAG runtime orchestration/helper logic
│   │   │   │   ├── __init__.py                  # Services package marker
│   │   │   │   │
│   │   │   │   ├── graph/                       # Agentic/LangGraph-style RAG workflow
│   │   │   │   │   ├── graph_builder.py         # Workflow graph build karta hai
│   │   │   │   │   ├── nodes.py                 # Retrieve/generate/evaluate nodes
│   │   │   │   │   ├── edges.py                 # Graph transitions/edges
│   │   │   │   │   ├── conditions.py            # Conditional routing logic
│   │   │   │   │   ├── state.py                 # Graph state structure
│   │   │   │   │   └── __init__.py              # Graph package marker
│   │   │   │   │
│   │   │   │   ├── ingestion/                   # File processing and chunking pipeline
│   │   │   │   │   ├── pipeline.py              # Upload se chunks/vector index tak main pipeline
│   │   │   │   │   ├── document_validator.py    # File validation rules
│   │   │   │   │   ├── markdown_table_chunker.py# Markdown tables ko intact chunks banata hai
│   │   │   │   │   └── __init__.py              # Ingestion package marker
│   │   │   │   │
│   │   │   │   ├── llm/                         # LLM and embeddings abstraction
│   │   │   │   │   ├── generation_service.py    # Answer generation via LLM
│   │   │   │   │   ├── embeddings_service.py    # Text embeddings creation
│   │   │   │   │   └── __init__.py              # LLM package marker
│   │   │   │   │
│   │   │   │   ├── memory/                      # Conversation/session memory
│   │   │   │   │   ├── memory_store.py          # Chat memory persistence/helper
│   │   │   │   │   └── __init__.py              # Memory package marker
│   │   │   │   │
│   │   │   │   ├── retrieval/                   # Search, ranking, context building
│   │   │   │   │   ├── bm25_store.py            # Keyword/BM25 index storage
│   │   │   │   │   ├── context_builder.py       # Retrieved chunks ko final context banata hai
│   │   │   │   │   ├── hybrid_search.py         # Vector + BM25 hybrid retrieval
│   │   │   │   │   ├── relevance_grader.py      # Retrieved docs ki relevance grade karta hai
│   │   │   │   │   ├── reranker_service.py      # Results ko better order mein rerank karta hai
│   │   │   │   │   ├── web_fallback.py          # Local docs fail hon to web fallback
│   │   │   │   │   └── __init__.py              # Retrieval package marker
│   │   │   │   │
│   │   │   │   └── vectordb/                    # Vector database abstraction
│   │   │   │       ├── base.py                  # Common vector DB interface/base class
│   │   │   │       ├── factory.py               # Provider instance create karta hai
│   │   │   │       ├── qdrant_service.py        # Qdrant implementation
│   │   │   │       ├── collection_service.py    # Collection create/list/delete helpers
│   │   │   │       ├── collection_registry.py   # Collections metadata registry
│   │   │   │       ├── vector_search.py         # Vector search functions
│   │   │   │       ├── vector_delete.py         # Vector/chunk delete functions
│   │   │   │       └── __init__.py              # Vector DB package marker
│   │   │   │
│   │   │   └── utils/                           # Shared helper utilities
│   │   │       ├── file_helpers.py              # File path/save/read helper functions
│   │   │       ├── response_helpers.py          # API response formatting helpers
│   │   │       └── __init__.py                  # Utils package marker
│   │   │
│   │   └── data/                                # Runtime data storage
│   │       ├── uploads/                         # Uploaded original files
│   │       ├── processed/                       # Processed/cleaned documents
│   │       ├── chunks/                          # Chunked document data
│   │       ├── bm25_indexes/                    # BM25 keyword indexes per collection
│   │       ├── memory/                          # Chat/session memory files
│   │       ├── query_logs/                      # Query logs and analytics source
│   │       └── temp/                            # Temporary files during processing
│   │
│   ├── frontend/                                # Streamlit web frontend
│   │   ├── app.py                               # Streamlit app entry point
│   │   ├── requirements.txt                     # Frontend dependencies
│   │   ├── __init__.py                          # Frontend package marker
│   │   ├── assets/                              # Static frontend assets if needed
│   │   ├── styles/
│   │   │   └── style.css                        # Custom UI styling
│   │   ├── services/
│   │   │   ├── api_client.py                    # Frontend se backend API calls
│   │   │   └── __init__.py                      # Services package marker
│   │   ├── pages/
│   │   │   ├── chat.py                          # Chat page UI
│   │   │   ├── upload.py                        # Upload/ingestion page UI
│   │   │   ├── collections.py                   # Collections management page
│   │   │   ├── analytics.py                     # Analytics/status page
│   │   │   ├── settings.py                      # Settings/provider configuration page
│   │   │   └── __init__.py                      # Pages package marker
│   │   └── components/
│   │       ├── api_key_input.py                 # API key input component
│   │       ├── collection_table.py              # Collections table component
│   │       ├── document_validator.py            # Frontend validation UI/helper
│   │       ├── export_utils.py                  # Export/download helpers
│   │       ├── layout.py                        # Shared layout wrapper
│   │       ├── provider_selector.py             # Vector/LLM provider selector
│   │       ├── runtime_secrets.py               # Runtime secret handling UI/helper
│   │       ├── sidebar.py                       # Main sidebar navigation
│   │       ├── source_viewer.py                 # Answer sources display
│   │       ├── uploaded_files.py                # Uploaded files list
│   │       ├── upload_status.py                 # Upload progress/status component
│   │       └── __init__.py                      # Components package marker
│   │
│   ├── mobile/                                  # Flutter mobile app
│   │   ├── pubspec.yaml                         # Flutter dependencies and app metadata
│   │   ├── pubspec.lock                         # Locked dependency versions
│   │   ├── analysis_options.yaml                # Dart analyzer/lint settings
│   │   ├── README.md                            # Mobile app notes
│   │   ├── lib/                                 # Main Flutter source code
│   │   │   ├── main.dart                        # Flutter app entry point
│   │   │   ├── app.dart                         # App widget/routing/theme setup
│   │   │   ├── core/                            # Shared app infrastructure
│   │   │   │   ├── constants/api_constants.dart # Backend API URLs/constants
│   │   │   │   ├── errors/api_exception.dart    # API error model
│   │   │   │   ├── network/api_client.dart      # Dart API client
│   │   │   │   ├── storage/app_session.dart     # Session/local state storage
│   │   │   │   ├── theme/app_theme.dart         # App theme/colors/text styles
│   │   │   │   └── utils/responsive.dart        # Responsive layout helpers
│   │   │   ├── features/                        # Feature-based mobile screens
│   │   │   │   ├── splash/                      # Splash/startup screen
│   │   │   │   ├── home/                        # Home/dashboard screen
│   │   │   │   ├── chat/                        # Mobile chat feature
│   │   │   │   ├── upload/                      # Mobile upload feature
│   │   │   │   ├── knowledge_base/              # Knowledge base browser screen
│   │   │   │   └── settings/                    # Mobile settings screen
│   │   │   └── shared/widgets/                  # Reusable Flutter widgets
│   │   ├── test/                                # Flutter tests
│   │   ├── android/                             # Android platform project
│   │   ├── ios/                                 # iOS platform project
│   │   ├── web/                                 # Flutter web platform files
│   │   ├── windows/                             # Windows desktop platform files
│   │   ├── macos/                               # macOS desktop platform files
│   │   └── linux/                               # Linux desktop platform files
│   │
│   ├── docs/                                    # Technical documentation
│   │   ├── architecture.md                      # Overall system architecture
│   │   ├── api_reference.md                     # API documentation
│   │   ├── chunking_strategy.md                 # Chunking rules and rationale
│   │   ├── ingestion_flow.md                    # Upload-to-index pipeline explanation
│   │   └── vector_db_strategy.md                # Vector DB design/provider strategy
│   │
│   ├── scripts/                                 # Admin/maintenance scripts
│   │   ├── create_collection.py                 # New vector collection create karne ke liye
│   │   ├── delete_collection.py                 # Collection delete karne ke liye
│   │   ├── reindex_collection.py                # Existing collection reindex karne ke liye
│   │   └── backup_vectors.py                    # Vector data backup helper
│   │
|   ├── .env 
│   └── deployment/                              # Deployment and ops config
│       ├── docker-compose.yml                   # Multi-service local/deploy setup
│       ├── nginx.conf                           # Nginx reverse proxy config
│       ├── render.yaml                          # Render deployment config
│       ├── monitoring.yml                       # Monitoring service/config placeholder
│       └── startup.sh                           # Deployment startup script
│
