"""Gap 3: petfinder registration is credential-gated, not an hourly error."""
from __future__ import annotations

import logging

import pytest

from k9overwatch.scheduler.runner import build_scraper_jobs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PETFINDER_API_KEY", raising=False)
    monkeypatch.delenv("PETFINDER_API_SECRET", raising=False)


def test_petfinder_skipped_without_credentials(caplog):
    with caplog.at_level(logging.WARNING, logger="k9overwatch.scheduler.runner"):
        jobs = build_scraper_jobs()
    ids = [job_id for job_id, *_ in jobs]
    assert "petfinder" not in ids
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "petfinder" in r.getMessage().lower() and "disabled" in r.getMessage().lower()
        for r in warnings
    )


def test_petfinder_included_with_credentials(monkeypatch):
    monkeypatch.setenv("PETFINDER_API_KEY", "key")
    monkeypatch.setenv("PETFINDER_API_SECRET", "secret")
    jobs = build_scraper_jobs()
    assert "petfinder" in [job_id for job_id, *_ in jobs]


def test_other_jobs_unaffected_by_credential_absence():
    ids = [job_id for job_id, *_ in build_scraper_jobs()]
    assert {"indy_lost_pet_alert", "petconnect24", "pawboost", "petfbi",
            "lostmydoggie"} <= set(ids)
