#!/usr/bin/env python3
"""
Live pipeline audit: run every registered scraper in dry-run mode (no DB
writes), report per-source fetch status, record counts, field fill-rates,
and a 5-record sample of normalized output. Writes a markdown report to
docs/audits/pipeline-audit-<date>.md.

Usage:
    .venv/bin/python scripts/pipeline_audit.py [--max-records 60] [--timeout 90]
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from k9overwatch.models.pet_record import PetRecord  # noqa: E402
from k9overwatch.scrapers.base import ScraperConfig, StructuralChangeError  # noqa: E402

FILL_FIELDS = [
    ("breed", "breed%"),
    ("color_primary", "color%"),
    ("lat", "geocode%"),   # lat set ⇒ coordinates present (native or geocoded)
    ("photos", "photo%"),
    ("date_event", "date%"),
    ("description", "desc%"),
]


def _build_scrapers(config: ScraperConfig) -> list:
    """Instantiate every registered scraper (HTTP first, then browser)."""
    from k9overwatch.scrapers.browser.lostmydoggie import LostMyDoggieScraper
    from k9overwatch.scrapers.browser.pawboost import PawBoostScraper
    from k9overwatch.scrapers.browser.petfbi import PetFBIScraper
    from k9overwatch.scrapers.http.indy_lost_pet_alert import IndyLostPetAlertScraper
    from k9overwatch.scrapers.http.petconnect24 import PetConnect24Scraper
    from k9overwatch.scrapers.http.petfinder import PetfinderScraper

    classes = [
        IndyLostPetAlertScraper,
        PetConnect24Scraper,
        PetfinderScraper,
        PawBoostScraper,
        PetFBIScraper,
        LostMyDoggieScraper,
    ]
    out = []
    for cls in classes:
        try:
            out.append(cls(config))
        except Exception as exc:  # e.g. missing API key
            print(f"  [setup-fail] {cls.SOURCE_NAME}: {exc}", file=sys.stderr)
    return out


def _fill_rates(records: list[PetRecord]) -> dict[str, float]:
    n = len(records) or 1
    rates = {}
    for attr, label in FILL_FIELDS:
        filled = sum(
            1 for r in records
            if getattr(r, attr, None) not in (None, "", [])
        )
        rates[label] = round(100.0 * filled / n)
    return rates


def _sample(records: list[PetRecord], n: int = 5) -> str:
    return json.dumps(
        [dataclasses.asdict(r) if dataclasses.is_dataclass(r) else r.model_dump(mode="json")
         for r in records[:n]],
        indent=2, default=str,
    )


async def audit_source(scraper, max_records: int, timeout_s: float) -> dict:
    source = scraper.SOURCE_NAME
    result: dict = {"source": source, "status": "ERROR", "count": 0, "rates": {}, "error": None}
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
        result["rates"] = _fill_rates(records)
        result["sample"] = _sample(records)
        types: dict[str, int] = {}
        for r in records:
            rt = str(getattr(r.record_type, "value", r.record_type))
            types[rt] = types.get(rt, 0) + 1
        result["record_types"] = types
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


def _render(results: list[dict], args) -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        f"# Pipeline Audit — {today}",
        "",
        "Dry-run of every registered scraper against live sites. No DB writes.",
        f"Per-source record cap: {args.max_records}; timeout: {args.timeout}s.",
        "",
        "| Source | Status | Records | breed% | color% | geocode% | photo% | date% | desc% | record_type mix |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rates = r.get("rates", {})
        mix = ", ".join(f"{k}:{v}" for k, v in sorted(r.get("record_types", {}).items())) or "—"
        err = f" ({r['error'][:60]})" if r.get("error") else ""
        lines.append(
            f"| {r['source']} | {r['status']}{err} | {r['count']} "
            f"| {rates.get('breed%', '—')} | {rates.get('color%', '—')} "
            f"| {rates.get('geocode%', '—')} | {rates.get('photo%', '—')} "
            f"| {rates.get('date%', '—')} | {rates.get('desc%', '—')} | {mix} |"
        )
    ok = sum(1 for r in results if r["status"].startswith("OK"))
    lines.append("")
    lines.append(
        f"**Verdict:** {ok}/{len(results)} sources fetched successfully "
        f"(BLOCKED = site unreachable/anti-bot/headless limitation; recorded honestly)."
    )
    lines += ["", "## Samples (5 normalized records per OK source)", ""]
    for r in results:
        lines.append(f"### {r['source']} — {r['status']}")
        if r.get("error"):
            lines.append(f"\n> Error: {r['error']}\n")
        if r.get("sample"):
            lines.append(f"\n```json\n{r['sample']}\n```\n")
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
    print(f"Auditing {len(scrapers)} sources...", file=sys.stderr)

    # Run HTTP sources and browser sources concurrently is unsafe for Playwright
    # startup on small VPSes; run sequentially, browser sources last.
    results = []
    for scraper in sorted(scrapers, key=lambda s: s.__class__.__module__.endswith(("http",))):
        print(f"→ {scraper.SOURCE_NAME} ...", file=sys.stderr)
        res = await audit_source(scraper, args.max_records, args.timeout)
        print(f"  {res['status']} count={res['count']}", file=sys.stderr)
        results.append(res)

    report = _render(results, args)
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out_path = out_dir / f"pipeline-audit-{today}.md"
    out_path.write_text(report + "\n")
    print(report)
    print(f"\nReport written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
