"""Gap 3: pipeline audit reports petfinder DISABLED_NO_CREDS instead of ERROR."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pipeline_audit  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PETFINDER_API_KEY", raising=False)
    monkeypatch.delenv("PETFINDER_API_SECRET", raising=False)


def test_missing_creds_reported_as_disabled_no_creds():
    config = pipeline_audit.ScraperConfig(search_lat=39.76, search_lon=-86.15)
    scrapers, disabled = pipeline_audit._build_scrapers(config)
    names = {s.SOURCE_NAME for s in scrapers}
    assert "petfinder" not in names
    entry = next(d for d in disabled if d["source"] == "petfinder")
    assert entry["status"] == "DISABLED_NO_CREDS"


def test_creds_present_keeps_petfinder_active(monkeypatch):
    monkeypatch.setenv("PETFINDER_API_KEY", "key")
    monkeypatch.setenv("PETFINDER_API_SECRET", "secret")
    config = pipeline_audit.ScraperConfig(search_lat=39.76, search_lon=-86.15)
    scrapers, _disabled = pipeline_audit._build_scrapers(config)
    assert "petfinder" in {s.SOURCE_NAME for s in scrapers}
