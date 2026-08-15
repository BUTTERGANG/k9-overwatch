import os
import secrets
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.connection import get_session_factory
from k9overwatch.db.models import User
from k9overwatch.db.repository import UserRepository

_basic_security = HTTPBasic()


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
    expected_password = os.getenv("ADMIN_PASSWORD", "changeme")
    user_ok = secrets.compare_digest(credentials.username.encode(), expected_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected_password.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the authenticated User from the session cookie, or None."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    repo = UserRepository(db)
    session = await repo.get_session(session_id)
    if session is None:
        return None
    return await repo.get_user_by_id(session.user_id)


async def require_user(
    user: User | None = Depends(get_current_user),
) -> User:
    """Like get_current_user but raises 401 if not authenticated."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    return user
