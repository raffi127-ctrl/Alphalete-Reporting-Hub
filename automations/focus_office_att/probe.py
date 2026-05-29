"""Read-only probe: connects to Chrome via CDP, finds the ownerville.com
tab, and dumps the current page's structure (HTML + key element snippets)
to output/probes/ for me to design selectors against.

Usage:
  1. In your debug Chrome (port 9222), navigate to wherever you want
     dumped (landing page, Cody Cannon's portal, Time Tracker, etc.)
  2. Run this script. It saves a snapshot of the current page.
  3. Repeat for each step of the flow.

It does NOT click anything, log in, fill forms, or modify data — pure observation.

Run:
  .venv/bin/python -m automations.focus_office_att.probe
  .venv/bin/python -m automations.focus_office_att.probe --label landing
  .venv/bin/python -m automations.focus_office_att.probe --label cody-time-tracker
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
PROBE_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "probes"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="ownerville",
                    help="Label for the saved files (e.g. 'landing', 'cody-time-tracker')")
    args = ap.parse_args()

    PROBE_DIR.mkdir(parents=True, exist_ok=True)

    p = sync_playwright().start()
    try:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"❌ Couldn't connect to Chrome at {CDP_URL}.")
            print("   Is Chrome running with --remote-debugging-port=9222?")
            print(f"   ({e})")
            return 1

        # Find the ownerville tab
        target_page = None
        all_pages = []
        for ctx in browser.contexts:
            for pg in ctx.pages:
                all_pages.append(pg.url)
                if "ownerville" in pg.url:
                    target_page = pg
                    break
            if target_page:
                break

        if not target_page:
            print("❌ No ownerville.com tab found in Chrome.")
            print(f"   Open tabs: {all_pages}")
            print("   Open https://v2.ownerville.com in the debug Chrome and log in first.")
            return 1

        url = target_page.url
        title = target_page.title()
        print(f"✓ Found ownerville tab")
        print(f"  URL:   {url}")
        print(f"  Title: {title}")

        ts = dt.datetime.now().strftime("%H%M%S")
        slug = f"{args.label}-{ts}"

        # 1. Save full HTML
        html_path = PROBE_DIR / f"{slug}.html"
        html_path.write_text(target_page.content())
        print(f"  ✓ HTML  → {html_path}")

        # 2. Save structured summary (counts of common elements + page metadata)
        summary = {
            "url": url,
            "title": title,
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "tables": [],
            "modals": [],
            "left_nav": [],
            "buttons_with_text": [],
            "date_inputs": [],
            "selects": [],
        }

        # All tables — id/class + first 3 rows of headers/cells
        for i, t in enumerate(target_page.locator("table").all()):
            try:
                table_id = t.get_attribute("id") or ""
                table_class = t.get_attribute("class") or ""
                # First header row
                headers = [h.inner_text().strip()[:40]
                           for h in t.locator("thead tr th").all()[:20]]
                # First 2 body rows (cells)
                body_rows = []
                for tr in t.locator("tbody tr").all()[:2]:
                    cells = [td.inner_text().strip()[:30]
                             for td in tr.locator("td").all()[:20]]
                    body_rows.append(cells)
                row_count = t.locator("tbody tr").count()
                summary["tables"].append({
                    "index": i, "id": table_id, "class": table_class,
                    "headers": headers, "first_rows": body_rows,
                    "total_body_rows": row_count,
                })
            except Exception as e:
                summary["tables"].append({"index": i, "error": str(e)})

        # Buttons / links with visible text (helps find "view", "Yes", sidebar items)
        # Cap to 100 to avoid massive dumps
        for btn in target_page.locator("button, a, input[type=button], input[type=submit]").all()[:100]:
            try:
                text = (btn.inner_text() or btn.get_attribute("value") or "").strip()
                if not text or len(text) > 60:
                    continue
                summary["buttons_with_text"].append({
                    "tag": btn.evaluate("el => el.tagName"),
                    "text": text[:60],
                    "id": btn.get_attribute("id") or "",
                    "class": (btn.get_attribute("class") or "")[:80],
                    "href": (btn.get_attribute("href") or "")[:120],
                })
            except Exception:
                pass

        # Modal candidates — visible dialogs
        for m in target_page.locator("[role=dialog], .modal, .ui-dialog, .swal2-popup").all()[:5]:
            try:
                if m.is_visible():
                    summary["modals"].append({
                        "id": m.get_attribute("id") or "",
                        "class": (m.get_attribute("class") or "")[:80],
                        "text": m.inner_text()[:200],
                    })
            except Exception:
                pass

        # Left nav items (common patterns: ul.nav, .sidebar, etc.)
        for nav in target_page.locator("nav, .sidebar, .left-menu, ul.nav, .nav-menu").all()[:3]:
            try:
                items = [li.inner_text().strip()[:50]
                         for li in nav.locator("li, a").all()[:30]]
                summary["left_nav"].append({
                    "id": nav.get_attribute("id") or "",
                    "class": (nav.get_attribute("class") or "")[:80],
                    "items": [i for i in items if i],
                })
            except Exception:
                pass

        # Date inputs
        for inp in target_page.locator("input[type=date], input.datepicker, input[name*=date], input[name*=Date]").all()[:5]:
            try:
                summary["date_inputs"].append({
                    "id": inp.get_attribute("id") or "",
                    "name": inp.get_attribute("name") or "",
                    "class": (inp.get_attribute("class") or "")[:80],
                    "value": (inp.get_attribute("value") or "")[:30],
                })
            except Exception:
                pass

        # Select dropdowns (might include "show N entries", date range pickers)
        for sel in target_page.locator("select").all()[:10]:
            try:
                options = [o.inner_text().strip()[:30]
                           for o in sel.locator("option").all()[:10]]
                summary["selects"].append({
                    "id": sel.get_attribute("id") or "",
                    "name": sel.get_attribute("name") or "",
                    "class": (sel.get_attribute("class") or "")[:80],
                    "options": options,
                })
            except Exception:
                pass

        json_path = PROBE_DIR / f"{slug}-summary.json"
        json_path.write_text(json.dumps(summary, indent=2))
        print(f"  ✓ Summary → {json_path}")

        print()
        print(f"Found: {len(summary['tables'])} table(s), "
              f"{len(summary['buttons_with_text'])} button(s)/link(s), "
              f"{len(summary['modals'])} visible modal(s), "
              f"{len(summary['left_nav'])} nav block(s), "
              f"{len(summary['date_inputs'])} date input(s), "
              f"{len(summary['selects'])} select(s)")
    finally:
        p.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
