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
from k9overwatch.web.routers import admin as admin_router
from k9overwatch.web.routers import auth as auth_router
from k9overwatch.web.routers import image_proxy as image_proxy_router
from k9overwatch.web.routers import map as map_router
from k9overwatch.web.routers import matches as matches_router
from k9overwatch.web.routers import pets as pets_router

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


class UserContextMiddleware(BaseHTTPMiddleware):
    """Resolve the session cookie and set request.state.current_user on every request."""

    _SKIP_PREFIXES = ("/static", "/proxy", "/api/")

    async def dispatch(self, request: Request, call_next):
        request.state.current_user = None
        path = request.url.path
        if not any(path.startswith(p) for p in self._SKIP_PREFIXES):
            session_id = request.cookies.get("session_id")
            if session_id:
                try:
                    from k9overwatch.db.connection import get_session
                    from k9overwatch.db.repository import UserRepository
                    async with get_session() as db:
                        repo = UserRepository(db)
                        session = await repo.get_session(session_id)
                        if session is not None:
                            request.state.current_user = await repo.get_user_by_id(session.user_id)
                except Exception:
                    pass  # session lookup failure is non-fatal
        return await call_next(request)


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
app.add_middleware(UserContextMiddleware)

_WEB_DIR = Path(__file__).parent

# Static files
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

# Routers
app.include_router(map_router.router)
app.include_router(pets_router.router)
app.include_router(matches_router.router)
app.include_router(admin_router.router)
app.include_router(image_proxy_router.router)
app.include_router(auth_router.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    from k9overwatch.web.templates_config import templates
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "errors/404.html", status_code=404)
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
