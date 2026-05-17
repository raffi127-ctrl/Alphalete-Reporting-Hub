"""Scrape the AppStream office list and merge it into all-offices.json.

The searchMC input uses jQuery UI autocomplete; its `source` is either a
preloaded array or a server-side function. We try the array first and
fall back to typing each letter/digit to collect the dropdown results.

Merges into all-offices.json (dedup by office_id): {office_id, owner,
company, raw}. Each AppStream account sees only its own offices, so the
file is built up per account (rhidalgo, rcaptain, CarlosNLR, …).

refresh_offices_from_page() is called at the end of each report run, so
new offices land in the file automatically — no manual scrape needed.

Run standalone:
    .venv/bin/python -m automations.recruiting_report.list_all_offices
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from string import ascii_lowercase, digits

from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
OUT_PATH = Path(__file__).resolve().parent / "all-offices.json"


def parse_item(raw: str) -> dict:
    """Parse '11280\\nRafael Hidalgo\\nALPHALETE MARKETING, INC.' into fields."""
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    return {
        "office_id": parts[0] if len(parts) >= 1 else None,
        "owner": parts[1] if len(parts) >= 2 else None,
        "company": parts[2] if len(parts) >= 3 else None,
        "raw": raw,
    }


def scrape_offices(page, verbose: bool = False) -> list[dict]:
    """Scrape the office list from the AppStream autocomplete on `page`.
    Tries the preloaded source array first; falls back to typing each
    letter/digit and collecting the dropdown results."""
    def _say(m: str) -> None:
        if verbose:
            print(m, flush=True)

    source_data = page.evaluate(
        """
        () => {
          if (typeof jQuery === 'undefined') return {error: 'no jQuery'};
          const inst = jQuery('#searchMC').autocomplete('instance');
          if (!inst) return {error: 'no autocomplete instance'};
          const src = inst.options.source;
          if (Array.isArray(src)) {
            return {kind: 'array', length: src.length, data: src};
          }
          return {kind: typeof src};
        }
        """
    )

    offices: list[dict] = []
    if isinstance(source_data, dict) and source_data.get("kind") == "array":
        _say(f"  office scrape: preloaded array, {source_data['length']} items")
        for item in source_data["data"]:
            if isinstance(item, dict):
                offices.append({
                    "office_id": str(item.get("id") or item.get("value") or "").strip(),
                    "owner": item.get("label", "").strip() if isinstance(item.get("label"), str) else "",
                    "company": item.get("company", "") if isinstance(item.get("company"), str) else "",
                    "raw": json.dumps(item),
                })
            else:
                offices.append(parse_item(str(item)))
        return offices

    # Fallback: type each letter/digit, collect the dropdown items.
    _say(f"  office scrape: no preloaded array ({source_data}) — alphabet iteration")
    seen: set = set()
    for ch in list(ascii_lowercase) + list(digits):
        page.locator("#searchMC").click()
        page.locator("#searchMC").fill("")
        page.locator("#searchMC").type(ch, delay=50)
        page.wait_for_timeout(700)
        items = page.evaluate(
            """
            () => {
              const found = [];
              document.querySelectorAll('.ui-autocomplete li, .ui-menu li').forEach(li => {
                const t = (li.innerText || '').trim();
                if (t.length > 0) found.push(t);
              });
              return found;
            }
            """
        )
        for raw in items:
            parsed = parse_item(raw)
            key = parsed["office_id"] or raw
            if key not in seen:
                seen.add(key)
                offices.append(parsed)
    # Leave the search box clean for whatever uses the page next.
    page.locator("#searchMC").fill("")
    page.locator("body").click(position={"x": 50, "y": 50})
    return offices


def merge_offices(scraped: list[dict]) -> tuple[int, int]:
    """Merge `scraped` offices into all-offices.json, dedup by office_id.
    Returns (newly_added, total)."""
    existing = []
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text()).get("offices", [])
        except Exception:
            existing = []
    by_id: dict = {}
    for o in existing:
        oid = str(o.get("office_id") or "").strip()
        if oid:
            by_id[oid] = o
    before = len(by_id)
    for o in scraped:
        oid = str(o.get("office_id") or "").strip()
        if oid:
            by_id[oid] = o
    merged = sorted(by_id.values(), key=lambda o: (o.get("owner") or "").lower())
    OUT_PATH.write_text(json.dumps({"count": len(merged), "offices": merged}, indent=2))
    return len(by_id) - before, len(merged)


def refresh_offices_from_page(page, verbose: bool = False) -> str:
    """Scrape the current AppStream account's offices and merge them into
    all-offices.json. Returns a one-line summary. Safe to call at the end
    of a report run — keeps the office list current per account."""
    scraped = scrape_offices(page, verbose=verbose)
    added, total = merge_offices(scraped)
    return f"AppStream office list refreshed: +{added} new, {total} total"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        target = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "applicantstream" in page.url:
                    target = page
                    break
            if target:
                break
        if not target:
            print("No applicantstream tab open")
            return 1
        print(refresh_offices_from_page(target, verbose=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
