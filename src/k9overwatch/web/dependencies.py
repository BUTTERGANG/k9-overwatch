import os
import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.connection import get_session_factory
from k9overwatch.web.auth import COOKIE_NAME, read_session_token

_basic_security = HTTPBasic()
_ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()
_IS_PRODUCTION = _ENVIRONMENT in {"production", "prod"}
_DEFAULT_ADMIN_PASSWORD = "changeme"
_ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if _IS_PRODUCTION and (not _ADMIN_PASSWORD or _ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD):
    raise RuntimeError("ADMIN_PASSWORD must be explicitly configured in production")
if not _ADMIN_PASSWORD:
    _ADMIN_PASSWORD = _DEFAULT_ADMIN_PASSWORD


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def verify_admin(credentials: HTTPBasicCredentials = Depends(_basic_security)) -> None:
    """Verify HTTP Basic credentials against ADMIN_USER / ADMIN_PASSWORD env vars."""
    expected_user = os.getenv("ADMIN_USER", "admin")
    expected_password = os.getenv("ADMIN_PASSWORD", _ADMIN_PASSWORD)
    user_ok = secrets.compare_digest(credentials.username.encode(), expected_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected_password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


async def get_current_user_id(request) -> str | None:
    """Return the logged-in user's id from the signed session cookie, or None."""
    token = request.cookies.get(COOKIE_NAME)
    return read_session_token(token)
