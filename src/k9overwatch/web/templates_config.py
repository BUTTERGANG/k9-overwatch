"""Shared Jinja2 templates instance — import from here to avoid circular imports."""
from pathlib import Path
from urllib.parse import quote

from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def proxied(url: str | None) -> str | None:
    """
    Route a remote image URL through our own /img proxy so browsers don't block
    cross-origin/large source images and the bytes get cached locally.
    Local /uploads and /static paths are returned unchanged.
    """
    if not url:
        return url
    if url.startswith(("/uploads/", "/static/", "data:")):
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return f"/img?url={quote(url, safe='')}"
    return url


templates.env.filters["proxied"] = proxied
