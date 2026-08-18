import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

load_dotenv()

from k9overwatch.db.connection import get_engine, init_db
from k9overwatch.utils.logging_config import configure_logging
from k9overwatch.web.routers import accounts as accounts_router
from k9overwatch.web.routers import admin as admin_router
from k9overwatch.web.routers import images as images_router
from k9overwatch.web.routers import map as map_router
from k9overwatch.web.routers import matches as matches_router
from k9overwatch.web.routers import pets as pets_router
from k9overwatch.web.routers import reports as reports_router
from k9overwatch.web.templates_config import templates

logger = logging.getLogger(__name__)

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' "
    "https://cdn.tailwindcss.com https://unpkg.com; "
    "img-src 'self' data: blob: "
    "https://tile.openstreetmap.org https://*.tile.openstreetmap.org "
    "https://*.basemaps.cartocdn.com; "
    "font-src 'self' https://unpkg.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none';"
)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": _CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers and a request-ID to every response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        for header, value in _SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_db()
    # Warm the connection pool so the first real request doesn't pay the cold-start penalty
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))

    # Optionally start the scraper scheduler in-process
    scheduler = None
    if os.getenv("RUN_SCHEDULER", "false").lower() == "true":
        from k9overwatch.scheduler.runner import ScraperScheduler
        scheduler = ScraperScheduler().build()
        scheduler.start()
        logger.info("Scraper scheduler started")

    yield

    if scheduler is not None:
        scheduler.shutdown()
        logger.info("Scraper scheduler shut down")


app = FastAPI(title="K9-Overwatch", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)

_WEB_DIR = Path(__file__).parent


@app.middleware("http")
async def auth_context(request: Request, call_next):
    """Resolve login state once per request and expose it on request.state."""
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import (
        COOKIE_NAME,
        csrf_token_for,
        read_session_token,
        validate_csrf_token,
    )

    user_id = read_session_token(request.cookies.get(COOKIE_NAME))
    request.state.is_logged_in = bool(user_id)
    request.state.csrf_token = csrf_token_for(user_id or "anonymous")
    request.state.current_user_name = None
    if user_id:
        from k9overwatch.db.connection import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await UserRepository(session).get_by_id(user_id)
            if user:
                request.state.current_user_name = user.display_name

    # Login and registration are intentionally usable without a prior session
    # token. All cookie-authenticated mutations still require a user-bound token.
    auth_path = request.url.path in {"/login", "/register"}
    if user_id and not auth_path and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        token = request.headers.get("X-CSRF-Token")
        if not token:
            await request.body()
            form = await request.form()
            token = form.get("csrf_token")
        if not isinstance(token, str) or not validate_csrf_token(token, user_id):
            return Response("CSRF validation failed", status_code=403, media_type="text/plain")
    return await call_next(request)


def _inject_user_state(request: Request):
    """Expose login state to every template via request.state (set by middleware)."""
    is_logged_in = bool(getattr(getattr(request, "state", None), "is_logged_in", False))
    name = getattr(getattr(request, "state", None), "current_user_name", None)
    csrf_token = getattr(getattr(request, "state", None), "csrf_token", "")
    return {"is_logged_in": is_logged_in, "current_user_name": name, "csrf_token": csrf_token}


templates.context_processors.append(_inject_user_state)

# Static files
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
# Uploaded owner photos (served as-is; gated by being unguessable UUID filenames)
_uploads_dir = _WEB_DIR.parent.parent.parent / "data" / "uploads"
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

# Routers
app.include_router(accounts_router.router)
app.include_router(reports_router.router)
app.include_router(images_router.router)
app.include_router(map_router.router)
app.include_router(pets_router.router)
app.include_router(matches_router.router)
app.include_router(admin_router.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    from k9overwatch.web.templates_config import templates
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "errors/404.html", {}, status_code=404)
    return templates.TemplateResponse(
        request, "errors/500.html", {"detail": exc.detail}, status_code=exc.status_code
    )


@app.get("/api/health")
async def health_check():
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    payload = {"status": "ok", "db": db_status}
    if db_status != "ok":
        return JSONResponse(content=payload, status_code=503)
    return payload


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/")
async def root():
    return RedirectResponse(url="/map")


if __name__ == "__main__":
    uvicorn.run("k9overwatch.web.main:app", host="0.0.0.0", port=8080, reload=True)
