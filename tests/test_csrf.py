from k9overwatch.web.auth import (
    csrf_token_for,
    make_csrf_token,
    validate_csrf_token,
)


def test_csrf_tokens_are_signed_and_bound_to_subject():
    token = make_csrf_token("user-1")

    assert validate_csrf_token(token, "user-1") is True
    assert validate_csrf_token(token, "user-2") is False
    assert validate_csrf_token(token + "x", "user-1") is False
    assert csrf_token_for("user-1") == token


async def test_anonymous_auth_endpoints_are_exempt_from_csrf(client, db_session):
    registered = await client.post(
        "/register",
        data={"email": "missing-token@example.com", "password": "password123"},
    )
    assert registered.status_code in (302, 303)

    logged_in = await client.post(
        "/login",
        data={"email": "missing-token@example.com", "password": "password123"},
    )
    assert logged_in.status_code in (302, 303)


async def test_authenticated_state_change_requires_csrf_token(client, db_session):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create("csrf@example.com", "password123")
    await db_session.commit()
    headers = {"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"}

    missing = await client.post("/account/preferences", data={}, headers=headers)
    assert missing.status_code == 403
    assert "CSRF" in missing.text

    valid = await client.post(
        "/account/preferences",
        data={"csrf_token": csrf_token_for(user.id)},
        headers=headers,
    )
    assert valid.status_code in (302, 303)


async def test_authenticated_template_includes_csrf_token(client, db_session):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create("csrf-page@example.com", "password123")
    await db_session.commit()
    response = await client.get(
        "/account", headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"}
    )

    assert response.status_code == 200
    assert f'name="csrf_token" value="{csrf_token_for(user.id)}"' in response.text


async def test_csrf_header_supports_htmx_requests(client, db_session):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create("csrf-header@example.com", "password123")
    await db_session.commit()
    response = await client.post(
        "/account/preferences",
        headers={
            "Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}",
            "X-CSRF-Token": csrf_token_for(user.id),
        },
        data={},
    )

    assert response.status_code in (302, 303)


async def test_authenticated_state_change_rejects_another_users_token(client, db_session):
    from k9overwatch.db.repository import UserRepository
    from k9overwatch.web.auth import COOKIE_NAME, make_session_token

    user = await UserRepository(db_session).create("csrf-owner@example.com", "password123")
    other = await UserRepository(db_session).create("csrf-other@example.com", "password123")
    await db_session.commit()
    response = await client.post(
        "/account/preferences",
        data={"csrf_token": csrf_token_for(other.id)},
        headers={"Cookie": f"{COOKIE_NAME}={make_session_token(user.id)}"},
    )

    assert response.status_code == 403
    assert "CSRF" in response.text


def test_csrf_token_is_exposed_in_html_forms():
    from pathlib import Path

    templates = Path("src/k9overwatch/web/templates")
    for form in [
        "accounts/login.html",
        "accounts/register.html",
        "accounts/account.html",
        "accounts/report.html",
        "pets/detail.html",
    ]:
        assert "csrf_token" in (templates / form).read_text()
    assert "X-CSRF-Token" in (templates / "matches/list.html").read_text()
