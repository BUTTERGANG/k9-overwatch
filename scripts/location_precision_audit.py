#!/usr/bin/env python3
"""
Location-precision audit: for each scraped source, fetch a live sample of
records (no DB writes) and classify how precise the source's location data is:
full street address vs intersection vs city-only vs zip-only vs missing.

Heuristics run on location_text shape:
- full address   : starts with a house number ("4521 N. Keystone Ave ...")
- intersection   : contains "&" / " and " between two street-ish tokens
- city-only      : looks like "Indianapolis, IN 46205" or "Indianapolis, IN"
                   with no house number — geocodes to city center level
- zip-only       : bare 5-digit ZIP (or empty text with a ZIP field)
- missing        : nothing usable

Writes docs/audits/location-precision-<date>.md with per-source breakdowns and
flags the sources that systematically produce city-center-level geocodes
(the map-accuracy offenders).

Usage:
    .venv/bin/python scripts/location_precision_audit.py [--max-records 60] [--timeout 90]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from k9overwatch.models.pet_record import PetRecord  # noqa: E402
from k9overwatch.scrapers.base import ScraperConfig, StructuralChangeError  # noqa: E402


def _load_pipeline_audit():
    """Import scripts/pipeline_audit.py (no package __init__) by path."""
    import importlib.util

    path = Path(__file__).resolve().parent / "pipeline_audit.py"
    spec = importlib.util.spec_from_file_location("pipeline_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_build_scrapers = _load_pipeline_audit()._build_scrapers

CATEGORIES = ["full_address", "intersection", "city_only", "zip_only", "missing"]

_HOUSE_NUMBER = re.compile(r"^\s*\d{1,6}\s+\S")
_ZIP_ONLY = re.compile(r"^\s*\d{5}(\s*(-|–)\s*\d{4})?\s*$")
# "Indianapolis, IN" / "Carmel, Indiana" possibly with ZIP, no street.
_CITY_STATE = re.compile(r"^[A-Za-z .'-]+,\s*(IN|Indiana)(\s+\d{5})?$", re.IGNORECASE)
_INTERSECTION = re.compile(r"\b\w+(\.\w+)*\s*(&|\band\b)\s*\w+", re.IGNORECASE)


def classify_location(r: PetRecord) -> str:
    """Bucket one record's location precision from its raw text shape."""
    text = (r.location_text or "").strip()
    if not text or len(text) < 4:
        return "zip_only" if (r.zip or "").strip() else "missing"
    if _ZIP_ONLY.match(text):
        return "zip_only"
    if _HOUSE_NUMBER.match(text):
        return "full_address"
    if _INTERSECTION.search(text):
        return "intersection"
    if _CITY_STATE.match(text):
        return "city_only"
    if "," not in text:
        # A bare neighborhood / area name ("Broad Ripple") — city-center level.
        return "city_only"
    return "city_only"


def audit_records(records: list[PetRecord]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for r in records:
        counts[classify_location(r)] += 1
    return dict(counts)


async def fetch_source(scraper, max_records: int, timeout_s: float) -> dict:
    result: dict = {"source": scraper.SOURCE_NAME, "status": "ERROR",
                    "count": 0, "counts": {}, "error": None}
    records: list[PetRecord] = []
    try:
        async def _collect():
            async for rec in scraper.scrape(after=None):
                records.append(rec)
                if len(records) >= max_records:
                    break

        await asyncio.wait_for(_collect(), timeout=timeout_s)
        result["status"] = "OK" if records else "OK_EMPTY"
        result["count"] = len(records)
        result["counts"] = audit_records(records)
    except TimeoutError:
        result["status"] = "BLOCKED"
        result["error"] = f"timeout after {timeout_s}s"
    except StructuralChangeError as exc:
        result["status"] = "BLOCKED"
        result["error"] = f"site structure changed: {exc}"
    except Exception as exc:
        result["status"] = "BLOCKED" if "playwright" in str(exc).lower() else "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "—"


def _render(results: list[dict]) -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        f"# Location Precision Audit — {today}",
        "",
        "Live-fetched sample per scraped source (no DB writes). Location",
        "precision classified from `location_text` shape: full street address >",
        "intersection > city-only / zip-only (geocode to city/ZIP-center level)",
        "> missing. BLOCKED sources are marked honestly.",
        "",
        "| Source | Status | Sampled | full addr | intersection | city-only | zip-only | missing | coarse% |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    offenders: list[tuple[str, int, int]] = []
    for r in results:
        c = r.get("counts", {})
        n = r.get("count", 0)
        coarse = c.get("city_only", 0) + c.get("zip_only", 0)
        err = f" ({r['error'][:60]})" if r.get("error") else ""
        lines.append(
            f"| {r['source']} | {r['status']}{err} | {n} "
            f"| {_pct(c.get('full_address', 0), n)} "
            f"| {_pct(c.get('intersection', 0), n)} "
            f"| {_pct(c.get('city_only', 0), n)} "
            f"| {_pct(c.get('zip_only', 0), n)} "
            f"| {_pct(c.get('missing', 0), n)} "
            f"| {_pct(coarse, n)} |"
        )
        if n >= 10 and coarse / n >= 0.5:
            offenders.append((r["source"], coarse, n))

    lines += ["", "## Map-accuracy offenders", ""]
    if offenders:
        lines += [
            f"- **{src}**: {coarse}/{n} sampled records ({_pct(coarse, n)}) carry only"
            " city- or ZIP-level location text → their pins land on city/ZIP"
            " centroids. These records are display-fuzzed on the map (see"
            " `src/k9overwatch/geocoding/display_fuzz.py`) and flagged with the"
            ' "ZIP code area" badge.'
            for src, coarse, n in offenders
        ]
    else:
        lines.append("- None above threshold in this sample.")

    lines += [
        "",
        "**Verdict:** coarse% = city-only + zip-only share of the sample.",
        "Sources ≥50% coarse (with n≥10) systematically produce city-center-level",
        "geocodes.",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-records", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    config = ScraperConfig(
        search_lat=float(os.getenv("SEARCH_LAT", "39.7684")),
        search_lon=float(os.getenv("SEARCH_LON", "-86.1581")),
        max_pages=1,
    )
    scrapers = _build_scrapers(config)
    print(f"Auditing location precision for {len(scrapers)} sources...", file=sys.stderr)

    results = []
    for scraper in sorted(scrapers, key=lambda s: s.__class__.__module__.endswith(("http",))):
        print(f"→ {scraper.SOURCE_NAME} ...", file=sys.stderr)
        res = await fetch_source(scraper, args.max_records, args.timeout)
        print(f"  {res['status']} count={res['count']}", file=sys.stderr)
        results.append(res)

    report = _render(results)
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = out_dir / f"location-precision-{today}.md"
    out_path.write_text(report + "\n")
    print(report)
    print(f"\nReport written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
