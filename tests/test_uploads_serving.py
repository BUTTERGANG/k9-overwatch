"""Hardened /uploads serving: strict filename validation, no directory traversal."""
from __future__ import annotations

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from k9overwatch.web.main import app

UPLOADS_DIR = os.path.join("data", "uploads")


def _write_upload(ext: str = ".jpg", content: bytes = b"fakejpeg") -> str:
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOADS_DIR, name), "wb") as f:
        f.write(content)
    return name


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_valid_file_serves_with_hardened_headers():
    name = _write_upload(".jpg", b"\xff\xd8\xff\xe0jpegbytes")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/uploads/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["content-disposition"] == f'inline; filename="{name}"'
    assert r.content == b"\xff\xd8\xff\xe0jpegbytes"


@pytest.mark.anyio
async def test_content_type_mapped_from_extension():
    cases = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".jpeg": "image/jpeg"}
    for ext, ctype in cases.items():
        name = _write_upload(ext, b"x")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/uploads/{name}")
        assert r.status_code == 200, ext
        assert r.headers["content-type"] == ctype, ext


@pytest.mark.parametrize(
    "path",
    [
        "..%2f..%2fetc%2fpasswd",
        "../../pyproject.toml",
        f"{uuid.uuid4().hex}.jpg/../../pyproject.toml",
        f"{uuid.uuid4().hex}.txt",       # disallowed extension
        f"{uuid.uuid4().hex}",           # no extension
        f"{uuid.uuid4().hex}.php",
        "subdir/" + f"{uuid.uuid4().hex}.jpg",
        f"{uuid.uuid4().hex}.jpg",       # nonexistent but well-formed
    ],
)
@pytest.mark.anyio
async def test_rejected_paths_return_404(path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/uploads/{path}")
    assert r.status_code == 404
