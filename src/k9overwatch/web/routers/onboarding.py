"""Onboarding routes: landing page, how-it-works, help overlay data."""
from __future__ import annotations

from fastapi import APIRouter, Request

from k9overwatch.web.templates_config import templates

router = APIRouter()


@router.get("/")
async def landing_page(request: Request):
    """Render a warm landing/welcome page instead of redirecting to /map."""
    return templates.TemplateResponse(request, "landing.html", {})


@router.get("/how-it-works")
async def how_it_works_page(request: Request):
    """Step-by-step guide for new users."""
    return templates.TemplateResponse(request, "how_it_works.html", {})