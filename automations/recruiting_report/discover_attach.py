"""Attach-mode discovery — bypasses Cloudflare bot detection.

Strategy: you launch Chrome manually with a debugging port, log into
ApplicantStream like a normal human (Cloudflare passes), navigate to the
report. Then this script attaches to that running Chrome via CDP and
inspects the page — Cloudflare never sees Playwright launching anything.

How to use:
  1. In Terminal, launch Chrome with debugging enabled:
       "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
         --remote-debugging-port=9222 \\
         --user-data-dir="$HOME/.config/recruiting-report/chrome-attach"
  2. In that Chrome window, log into applicantstream.com manually.
  3. Navigate to the Raf Hidalgo recruiting funnel report.
  4. THEN run this script:
       .venv/bin/python -m automations.recruiting_report.discover_attach
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

SELECTORS_PATH = Path(__file__).resolve().parent / "selectors.json"
SNAPSHOT_PATH = SELECTORS_PATH.parent / "discovery-snapshot.json"
CDP_URL = "http://localhost:9222"


def main() -> int:
    print(f"connecting to Chrome at {CDP_URL}…")
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"\n❌ Could not connect to Chrome at {CDP_URL}.")
            print("   Did you launch Chrome with --remote-debugging-port=9222?")
            print(f"   Error: {e}")
            return 1

        contexts = browser.contexts
        if not contexts:
            print("❌ Chrome has no open contexts.")
            return 2

        # Find the tab that's on applicantstream.com
        target_page = None
        for ctx in contexts:
            for page in ctx.pages:
                if "applicantstream" in page.url:
                    target_page = page
                    break
            if target_page:
                break

        if not target_page:
            all_urls = [page.url for ctx in contexts for page in ctx.pages]
            print(f"❌ No tab open on applicantstream.com. Open tabs: {all_urls}")
            return 3

        print(f"✓ Found ApplicantStream tab: {target_page.url}")
        print(f"  Title: {target_page.title()}")

        snapshot = {
            "current_url": target_page.url,
            "title": target_page.title(),
            "buttons_seen": [b.text_content() for b in target_page.locator("button").all()[:30]],
            "links_seen": [
                {"text": a.text_content(), "href": a.get_attribute("href")}
                for a in target_page.locator("a").all()[:50]
            ],
            "inputs_seen": [
                {
                    "name": i.get_attribute("name"),
                    "id": i.get_attribute("id"),
                    "type": i.get_attribute("type"),
                    "placeholder": i.get_attribute("placeholder"),
                }
                for i in target_page.locator("input").all()[:30]
            ],
            "select_elements": [
                {
                    "name": s.get_attribute("name"),
                    "id": s.get_attribute("id"),
                    "options": [
                        {"value": o.get_attribute("value"), "text": o.text_content()}
                        for o in s.locator("option").all()[:60]
                    ],
                }
                for s in target_page.locator("select").all()[:10]
            ],
            "tables_seen": target_page.locator("table").count(),
            "page_text_first_2000_chars": (target_page.locator("body").inner_text())[:2000],
        }

        SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))
        print(f"\n✓ Wrote snapshot to {SNAPSHOT_PATH}")
        print("  (Includes URL, title, buttons, links, form inputs, selects, table count, and visible text.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
