import asyncio
import logging
import sys
from threading import Thread
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException

from app.api.routes import (
    admin_routes,
    auth_routes,
    chat_routes,
    collection_routes,
    health_routes,
    ingestion_routes,
    vector_routes,
)
from app.core.config import limiter, settings, validate_production_settings
from app.core.runtime_credentials import redact_secrets_text


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
validate_production_settings()


def _is_safe_client_disconnect(exc: object) -> bool:
    current = exc
    seen = set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionResetError, BrokenPipeError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_safe_disconnect_context(context: dict) -> bool:
    exc = context.get("exception")
    if _is_safe_client_disconnect(exc):
        return True
    if sys.platform != "win32":
        return False
    details = f"{context.get('message', '')} {context.get('handle', '')}"
    return "_ProactorBasePipeTransport._call_connection_lost" in details


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="FastAPI backend for Agentic RAG with Qdrant and table-aware chunking.",
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
if settings.enable_https_redirect:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
if settings.rate_limit_enabled:
    app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": "Rate limit exceeded. Please try again later.",
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if 400 <= exc.status_code < 500:
        logger.warning(
            "http_exception method=%s path=%s status=%s detail=%r",
            request.method,
            request.url.path,
            exc.status_code,
            redact_secrets_text(exc.detail),
        )
    else:
        logger.error(
            "http_exception method=%s path=%s status=%s detail=%r",
            request.method,
            request.url.path,
            exc.status_code,
            redact_secrets_text(exc.detail),
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    message = redact_secrets_text(exc.detail) if isinstance(exc.detail, str) else "HTTP error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": message},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    logger.error(
        "request_validation_error method=%s path=%s errors=%r",
        request.method,
        request.url.path,
        redact_secrets_text(exc.errors()),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=422,
        content={"success": False, "error": "Invalid request."},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    if _is_safe_client_disconnect(exc):
        logger.warning(
            "client_disconnected method=%s path=%s reason=%s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(status_code=499, content={"success": False, "error": "Client disconnected."})
    logger.error(
        "unhandled_exception method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error. Please check backend logs.",
        },
    )


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    if settings.security_headers_enabled:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "0"
        if settings.environment.lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def log_request_timing(request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = round(time.perf_counter() - start_time, 4)

    response.headers["X-Process-Time"] = str(process_time)
    logger.info(
        "http_request method=%s path=%s status=%s process_time=%ss",
        request.method,
        request.url.path,
        response.status_code,
        process_time,
    )
    return response


app.include_router(health_routes.router, prefix=settings.api_prefix)
app.include_router(ingestion_routes.router, prefix=settings.api_prefix)
app.include_router(chat_routes.router, prefix=settings.api_prefix)
app.include_router(vector_routes.router, prefix=settings.api_prefix)
app.include_router(collection_routes.router, prefix=settings.api_prefix)
app.include_router(collection_routes.router)
app.include_router(auth_routes.router, prefix=settings.api_prefix)
app.include_router(admin_routes.router, prefix=settings.api_prefix)


@app.on_event("startup")
def startup_sync_collections():
    if settings.render_free_mvp:
        logger.info("Startup Qdrant registry sync disabled for Render Free MVP.")
        return
    Thread(target=_sync_collections_best_effort, name="qdrant-registry-sync", daemon=True).start()


@app.on_event("startup")
async def install_windows_disconnect_handler():
    if sys.platform != "win32":
        return
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handle_loop_exception(event_loop, context):
        if _is_safe_disconnect_context(context):
            exc = context.get("exception")
            reason = type(exc).__name__ if exc is not None else "proactor_connection_lost"
            logger.debug("Windows client connection closed: %s", reason)
            return
        if previous_handler is not None:
            previous_handler(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)


def _sync_collections_best_effort() -> None:
    try:
        from app.services.vectordb.collection_service import sync_qdrant_registry

        sync_qdrant_registry()
    except Exception as exc:
        # Registry sync is best-effort; collection routes refresh it when needed.
        logger.warning("Startup Qdrant registry sync skipped: %s", redact_secrets_text(exc))


@app.get("/")
def root():
    return {
        "success": True,
        "message": "Enterprise Agentic RAG backend is running.",
        "docs": "/docs",
    }
