from __future__ import annotations

import importlib

import pytest
from starlette.responses import Response


@pytest.mark.parametrize("environment", ["production", "prod"])
@pytest.mark.parametrize("secret", [None, "dev-insecure-secret-change-me"])
def test_production_rejects_missing_or_default_session_secret(monkeypatch, environment, secret):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", secret)

    import k9overwatch.web.auth as auth

    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        importlib.reload(auth)

    # Restore the module for the rest of the test process after the expected failure.
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    importlib.reload(auth)


def test_production_session_cookies_are_secure(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET", "a-real-production-secret-0123456789abcdef")

    import k9overwatch.web.auth as auth
    import k9overwatch.web.routers.accounts as accounts

    importlib.reload(auth)
    importlib.reload(accounts)
    response = Response()
    accounts._set_session(response, type("User", (), {"id": "user-1"})())

    set_cookie = response.headers["set-cookie"]
    assert "Secure" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    importlib.reload(auth)
    importlib.reload(accounts)
