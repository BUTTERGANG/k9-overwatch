import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from k9overwatch.db.connection import init_db
from k9overwatch.utils.logging_config import configure_logging
from k9overwatch.web.routers import accounts as accounts_router
from k9overwatch.web.routers import admin as admin_router
from k9overwatch.web.routers import images as images_router
from k9overwatch.web.routers import map as map_router
from k9overwatch.web.routers import matches as matches_router
from k9overwatch.web.routers import pets as pets_router
from k9overwatch.web.routers import reports as reports_router
from k9overwatch.web.templates_config import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_db()
    yield


app = FastAPI(title="K9-Overwatch", lifespan=lifespan)

_WEB_DIR = Path(__file__).parent


@app.middleware("http")
async def auth_context(request: Request, call_next):
    """Resolve login state once per request and expose it on request.state."""
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, read_session_token

    user_id = read_session_token(request.cookies.get(COOKIE_NAME))
    request.state.is_logged_in = bool(user_id)
    request.state.current_user_name = None
    if user_id:
        from k9overwatch.db.connection import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            user = await UserRepository(session).get_by_id(user_id)
            if user:
                request.state.current_user_name = user.display_name
    response = await call_next(request)
    return response


def _inject_user_state(request: Request):
    """Expose login state to every template via request.state (set by middleware)."""
    is_logged_in = bool(getattr(getattr(request, "state", None), "is_logged_in", False))
    name = getattr(getattr(request, "state", None), "current_user_name", None)
    return {"is_logged_in": is_logged_in, "current_user_name": name}


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
    from k9overwatch.db.connection import get_engine
    try:
        async with get_engine().connect() as conn:
            await conn.execute(__import__('sqlalchemy').text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "ok", "db": db_status}


@app.get("/")
async def root():
    return RedirectResponse(url="/map")


if __name__ == "__main__":
    uvicorn.run("k9overwatch.web.main:app", host="0.0.0.0", port=8080, reload=True)
