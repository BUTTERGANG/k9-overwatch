"""Shared Jinja2 templates instance — import from here to avoid circular imports."""
from pathlib import Path
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
