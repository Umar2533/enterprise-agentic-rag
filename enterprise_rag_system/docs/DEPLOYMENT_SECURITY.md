# Deployment Security

## HTTPS Termination

Run the FastAPI backend behind a production reverse proxy or managed platform that provides HTTPS, such as Nginx, Caddy, Traefik, Render, Railway, or Fly.io.

Do not expose the backend over plain HTTP in production. Terminate TLS at the reverse proxy or platform edge, forward only trusted internal traffic to FastAPI, and redirect all public HTTP traffic to HTTPS at the proxy layer.

## CORS

Use explicit frontend origins in production:

```env
FRONTEND_ORIGINS=https://your-domain.com
```

The backend also accepts `BACKEND_CORS_ORIGINS` and `CORS_ORIGINS` for compatibility. Production configuration must not use `*`, localhost, or plain HTTP origins.

Development can use localhost origins for Streamlit or local web clients.

## Secrets

Use secure environment variables or your platform secret manager for server-level defaults such as `OPENAI_API_KEY`, `TAVILY_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `JWT_SECRET_KEY`, `BACKEND_API_KEY`, database credentials, and SMTP credentials.

Runtime user-entered API keys are per-request credentials. They must not be written to `.env`, database rows, local files, caches, long-lived globals, or logs.

Do not log `Authorization`, `X-API-Key`, `X-Runtime-Qdrant-Api-Key`, form fields, request bodies, or headers that may contain credentials.

## Reverse Proxy Hardening

Enforce HTTPS at the reverse proxy. Optional HSTS example:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

Only enable HSTS after HTTPS is confirmed for every production subdomain that must be covered.
