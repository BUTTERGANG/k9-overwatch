"""
Hardened serving of uploaded owner photos.

Replaces the previous StaticFiles mount for /uploads. Filenames are strictly
validated against ^[a-f0-9]{32}\\.(jpg|jpeg|png|webp|gif)$ (content-addressed
UUID-hex names produced by reports._store_stripped), so there is no directory
traversal surface: anything else is a plain 404.
"""
from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

# uuid4().hex + a known image extension, nothing else is ever written.
_UPLOAD_NAME_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|jpeg|png|webp)$")

_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.get("/uploads/{filename}")
async def serve_upload(filename: str) -> Response:
    if not _UPLOAD_NAME_RE.match(filename):
        return Response(status_code=404)
    import os

    from k9overwatch.web.routers.reports import UPLOAD_DIR

    path = os.path.join(UPLOAD_DIR, filename)
    try:
        with open(path, "rb") as f:
            content = f.read()
    except OSError:
        return Response(status_code=404)
    ext = filename.rsplit(".", 1)[1]
    return Response(
        content=content,
        media_type=_CONTENT_TYPES[f".{ext}"],
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
