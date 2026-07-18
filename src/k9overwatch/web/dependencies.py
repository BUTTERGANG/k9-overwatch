from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from k9overwatch.db.connection import get_session_factory
from k9overwatch.web.auth import COOKIE_NAME, read_session_token


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_current_user_id(request) -> str | None:
    """Return the logged-in user's id from the signed session cookie, or None."""
    token = request.cookies.get(COOKIE_NAME)
    return read_session_token(token)
