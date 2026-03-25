from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from k9overwatch.db.connection import init_db
from k9overwatch.utils.logging_config import configure_logging
from k9overwatch.web.routers import map as map_router
from k9overwatch.web.routers import pets as pets_router
from k9overwatch.web.routers import matches as matches_router
from k9overwatch.web.routers import admin as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await init_db()
    yield


app = FastAPI(title="K9-Overwatch", lifespan=lifespan)

_WEB_DIR = Path(__file__).parent

# Static files
app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

# Routers
app.include_router(map_router.router)
app.include_router(pets_router.router)
app.include_router(matches_router.router)
app.include_router(admin_router.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    from k9overwatch.web.templates_config import templates
    if exc.status_code == 404:
        return templates.TemplateResponse("errors/404.html", {"request": request}, status_code=404)
    return templates.TemplateResponse(
        "errors/500.html", {"request": request, "detail": exc.detail}, status_code=exc.status_code
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
