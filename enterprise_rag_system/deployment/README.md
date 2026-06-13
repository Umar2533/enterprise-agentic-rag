# Deployment Notes

This folder contains a production-oriented Nginx reverse proxy template for the FastAPI backend and Streamlit frontend.

## Local Production Compose

Copy the root `.env.example` to `.env`, fill only placeholder values with deployment secrets, then validate and start the stack:

```bash
docker compose -f deployment/docker-compose.yml config
docker compose -f deployment/docker-compose.yml up -d --build
```

The compose stack includes FastAPI, Streamlit, and PostgreSQL with a persistent `postgres_data` volume. Qdrant is intentionally not included as a local container; set `QDRANT_URL` and `QDRANT_API_KEY` to your external Qdrant Cloud cluster.

Backend health check through the HTTPS proxy:

```text
https://yourdomain.com/api/v1/health
```

Frontend:

```text
http://localhost:8501
```

## Nginx HTTPS Proxy

Replace every `your-domain.com` placeholder in `nginx.conf` with your real domain.

The HTTPS block expects certificates at:

```text
/etc/letsencrypt/live/your-domain.com/fullchain.pem
/etc/letsencrypt/live/your-domain.com/privkey.pem
```

Create certificates with Certbot or your hosting provider's managed TLS. If Nginx handles HTTP-to-HTTPS redirects, keep the backend setting:

```env
ENABLE_HTTPS_REDIRECT=false
```

## Required Production Env

Set at least:

```env
ENVIRONMENT=production
APP_NAME=Enterprise Documents Agentic RAG System
DATABASE_URL=postgresql+psycopg2://rag_user:rag_password@postgres:5432/rag_db
OPENAI_API_KEY=
TAVILY_API_KEY=
QDRANT_URL=
QDRANT_API_KEY=
QDRANT_COLLECTION_PREFIX=agentic_rag_enterprise
RAG_API_BASE_URL=http://backend:8000/api/v1
BACKEND_CORS_ORIGINS=https://yourdomain.com
FRONTEND_BASE_URL=https://yourdomain.com
TRUSTED_HOSTS=yourdomain.com
ENABLE_HTTPS_REDIRECT=false
BACKEND_API_KEY=
JWT_SECRET_KEY=
```

Also configure SMTP settings if email verification or password reset is enabled. Keep `.env`, `backend/.env`, and `frontend/.env` out of git.

## Database Migrations

Run migrations after PostgreSQL is healthy and before serving traffic:

```bash
docker compose -f deployment/docker-compose.yml run --rm backend alembic upgrade head
```

## Network Exposure

Do not expose the backend port publicly. FastAPI is only exposed to the private Docker network as `http://backend:8000`; Nginx should be attached to that network and proxy requests internally. Streamlit remains the public app surface.

The Nginx template routes:

- `/api/` to FastAPI
- `/docs`, `/redoc`, and `/openapi.json` blocked publicly
- `/` to Streamlit
