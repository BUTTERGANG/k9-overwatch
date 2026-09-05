"""Production secret guard: rejects short/placeholder SESSION_SECRET and default ADMIN_PASSWORD."""
from __future__ import annotations

import importlib

import pytest

_PLACEHOLDERS = (
    "change-me-to-a-random-64-char-string",
    "dev-insecure-secret-change-me",
)


def _reload_auth(monkeypatch, environment: str, secret: str | None):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", secret)
    import k9overwatch.web.auth as auth

    try:
        return importlib.reload(auth), None
    except RuntimeError as exc:
        # Restore module state for subsequent tests.
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.setenv("SESSION_SECRET", "unit-test-secret-0123456789abcdef")
        importlib.reload(auth)
        return None, exc


def _reload_deps(monkeypatch, environment: str, password: str | None):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if password is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", password)
    import k9overwatch.web.dependencies as deps

    try:
        return importlib.reload(deps), None
    except RuntimeError as exc:
        monkeypatch.setenv("ENVIRONMENT", "test")
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        importlib.reload(deps)
        return None, exc


@pytest.mark.parametrize("secret", [None, *_PLACEHOLDERS, "short"])
def test_production_rejects_weak_session_secret(monkeypatch, secret):
    """Missing, placeholder, or <32-char secrets are rejected in production."""
    _, exc = _reload_auth(monkeypatch, "production", secret)
    assert exc is not None
    assert "SESSION_SECRET" in str(exc)


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_accepts_strong_session_secret(monkeypatch, environment):
    auth, exc = _reload_auth(
        monkeypatch, environment, "0123456789abcdef0123456789abcdef-strong"
    )
    assert exc is None
    assert auth is not None


@pytest.mark.parametrize("password", [None, "changeme"])
def test_production_rejects_missing_or_default_admin_password(monkeypatch, password):
    _, exc = _reload_deps(monkeypatch, "production", password)
    assert exc is not None
    assert "ADMIN_PASSWORD" in str(exc)


def test_production_accepts_real_admin_password(monkeypatch):
    deps, exc = _reload_deps(monkeypatch, "production", "a-real-long-admin-password")
    assert exc is None
    assert deps is not None
