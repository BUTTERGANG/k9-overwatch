import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
import uvicorn

from k9overwatch.db.connection import get_engine, init_db
from k9overwatch.utils.logging_config import configure_logging
from k9overwatch.web.routers import map as map_router
from k9overwatch.web.routers import pets as pets_router
from k9overwatch.web.routers import matches as matches_router
from k9overwatch.web.routers import admin as admin_router

logger = logging.getLogger(__name__)


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
