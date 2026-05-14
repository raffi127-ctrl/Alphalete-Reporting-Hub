"""Step 3: with the session already impersonating an owner, navigate to
Time Tracker (?p=510), then dump the page structure (date picker, rep
table, 'show 100 entries' dropdown) so we can design the actual scraper.

Prereq: run step1 + step2 first so the Chrome session is impersonating
the target owner. Once we've designed the full pipeline this becomes
part of one orchestrated script.

Run:
  .venv/bin/python -m automations.focus_office_att.step3_time_tracker
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
PROBE_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "probes"


def main() -> int:
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    p = sync_playwright().start()
    try:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"❌ Couldn't connect to Chrome: {e}")
            return 1

        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "ownerville" in pg.url:
                    page = pg
                    break
            if page:
                break
        if not page:
            print("❌ No ownerville tab found.")
            return 1
        print(f"✓ Connected. Current URL: {page.url}")
        print(f"  Page title: {page.title()}")

        # Read the current rqst token from the page (it changes per session
        # AND when we impersonate, so always pull from the live page).
        rqst = page.evaluate("typeof rqstValue !== 'undefined' ? rqstValue : null")
        if not rqst:
            print("❌ Couldn't read rqstValue from page. Are you logged in?")
            return 1
        print(f"  ✓ rqst token: {rqst[:20]}…")

        # Navigate to Time Tracker
        time_tracker_url = f"https://v2.ownerville.com/index.cfm?p=510&rqst={rqst}"
        print(f"  → Navigating to Time Tracker…")
        page.goto(time_tracker_url, wait_until="networkidle", timeout=20000)
        print(f"  ✓ Now on {page.url}")
        print(f"  ✓ Title: {page.title()}")

        # Save full page HTML
        ts = dt.datetime.now().strftime("%H%M%S")
        slug = f"step3-time-tracker-{ts}"
        (PROBE_DIR / f"{slug}.html").write_text(page.content())
        print(f"  ✓ HTML  → {PROBE_DIR / (slug + '.html')}")

        # Pull a structured digest specific to Time Tracker
        summary = {
            "url": page.url,
            "title": page.title(),
            "date_inputs": [],
            "selects": [],
            "tables": [],
            "show_entries": [],
            "headings": [],
        }

        # Date inputs (the date picker for selecting which day to view)
        for inp in page.locator(
            "input[type=date], input.datepicker, input[name*=date], input[name*=Date], "
            "input[id*=date], input[id*=Date]"
        ).all()[:10]:
            try:
                summary["date_inputs"].append({
                    "id": inp.get_attribute("id") or "",
                    "name": inp.get_attribute("name") or "",
                    "class": (inp.get_attribute("class") or "")[:80],
                    "value": (inp.get_attribute("value") or "")[:30],
                    "placeholder": (inp.get_attribute("placeholder") or "")[:40],
                })
            except Exception:
                pass

        # Select dropdowns ("show N entries" and any other filters)
        for sel in page.locator("select").all()[:15]:
            try:
                options = [o.inner_text().strip()[:30]
                           for o in sel.locator("option").all()[:15]]
                summary["selects"].append({
                    "id": sel.get_attribute("id") or "",
                    "name": sel.get_attribute("name") or "",
                    "class": (sel.get_attribute("class") or "")[:80],
                    "options": options,
                })
            except Exception:
                pass

        # DataTables 'show entries' often uses a label wrapping a select
        for label in page.locator("label").all()[:30]:
            try:
                text = label.inner_text().strip()
                if "entries" in text.lower() or "show" in text.lower():
                    summary["show_entries"].append({
                        "text": text[:80],
                        "html": label.evaluate("el => el.outerHTML")[:200],
                    })
            except Exception:
                pass

        # Tables — full info on each one we find (the rep table is the prize)
        for i, t in enumerate(page.locator("table").all()):
            try:
                headers = [h.inner_text().strip()[:40]
                           for h in t.locator("thead tr th").all()[:20]]
                # First 3 body rows
                body_rows = []
                for tr in t.locator("tbody tr").all()[:3]:
                    cells = [td.inner_text().strip()[:40]
                             for td in tr.locator("td").all()[:20]]
                    body_rows.append(cells)
                summary["tables"].append({
                    "index": i,
                    "id": t.get_attribute("id") or "",
                    "class": (t.get_attribute("class") or "")[:80],
                    "headers": headers,
                    "first_3_rows": body_rows,
                    "total_body_rows": t.locator("tbody tr").count(),
                })
            except Exception as ex:
                summary["tables"].append({"index": i, "error": str(ex)})

        # Page headings (h1/h2/h3) for context
        for h in page.locator("h1, h2, h3, h4").all()[:10]:
            try:
                summary["headings"].append({
                    "tag": h.evaluate("el => el.tagName"),
                    "text": h.inner_text().strip()[:80],
                })
            except Exception:
                pass

        json_path = PROBE_DIR / f"{slug}-summary.json"
        json_path.write_text(json.dumps(summary, indent=2))
        print(f"  ✓ Summary → {json_path}")

        print()
        print(f"Date inputs: {len(summary['date_inputs'])}")
        for d in summary["date_inputs"][:5]:
            print(f"  id={d['id']!r:20s} name={d['name']!r:20s} value={d['value']!r}")
        print(f"Selects: {len(summary['selects'])}")
        for s in summary["selects"][:5]:
            print(f"  id={s['id']!r:30s} options={s['options'][:5]}")
        print(f"Tables: {len(summary['tables'])}")
        for t in summary["tables"]:
            if "headers" in t:
                print(f"  table {t['index']} ({t.get('total_body_rows', '?')} rows): "
                      f"headers = {t['headers'][:6]}")
        print(f"Show-entries labels: {len(summary['show_entries'])}")
    finally:
        p.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
