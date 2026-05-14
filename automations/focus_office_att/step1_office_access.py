"""Step 1 of the ownerville automation: from a logged-in state, find and
click 'Office Access' in the left nav. Lands on the owner-table page
(?p=901). Then dumps the resulting page so we can design step 2 (clicking
'view' on a specific owner).

Tries a few selector strategies for the 'Office Access' link in case
the markup isn't exactly what I'd expect — verbose logging tells us
which one worked.

Run (after you're logged into ownerville.com in the debug Chrome):
  .venv/bin/python -m automations.focus_office_att.step1_office_access
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
            print(f"❌ Couldn't connect to Chrome at {CDP_URL}: {e}")
            print("   Open Chrome with --remote-debugging-port=9222 first.")
            return 1

        # Find the ownerville tab (must already be logged in)
        target = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "ownerville" in pg.url:
                    target = pg
                    break
            if target:
                break
        if not target:
            print("❌ No ownerville.com tab found. Open + log in first.")
            return 1

        print(f"✓ Connected. Current URL: {target.url}")

        # Try multiple ways to find 'Office Access' — log which one works
        candidates = [
            ("role=link name=Office Access",
             lambda: target.get_by_role("link", name="Office Access").first),
            ("text=Office Access (any element)",
             lambda: target.get_by_text("Office Access", exact=True).first),
            ("a:has-text('Office Access')",
             lambda: target.locator("a:has-text('Office Access')").first),
        ]
        clicked = False
        for label, get_loc in candidates:
            try:
                loc = get_loc()
                count = loc.count() if hasattr(loc, 'count') else 1
                if count == 0:
                    print(f"  – tried '{label}': 0 matches")
                    continue
                print(f"  ✓ found via '{label}'")
                # Capture pre-click URL for verification
                before_url = target.url
                loc.click(timeout=5000)
                # Wait for navigation OR a network response
                try:
                    target.wait_for_url("**/index.cfm?p=901*", timeout=8000)
                except Exception:
                    target.wait_for_load_state("networkidle", timeout=8000)
                if target.url != before_url:
                    print(f"  ✓ clicked → navigated to {target.url}")
                else:
                    print(f"  ⚠ URL didn't change (still {target.url}); page may have updated in place")
                clicked = True
                break
            except Exception as e:
                print(f"  – tried '{label}': {type(e).__name__}: {str(e)[:80]}")

        if not clicked:
            print("❌ Couldn't find or click 'Office Access' link.")
            print("   Saving current page for debugging.")
            html = PROBE_DIR / "step1-failed-source.html"
            html.write_text(target.content())
            print(f"   → {html}")
            return 1

        # Confirm we're on the owner-table page (p=901)
        if "p=901" not in target.url:
            print(f"⚠ URL is {target.url} — expected ?p=901. Continuing anyway.")

        # Dump the owner-table page so we can write step 2 (click view on owner)
        ts = dt.datetime.now().strftime("%H%M%S")
        slug = f"step1-office-access-{ts}"
        (PROBE_DIR / f"{slug}.html").write_text(target.content())
        print(f"  ✓ HTML  → {PROBE_DIR / (slug + '.html')}")

        # Pull a quick structured digest of the owner table
        summary = {
            "url": target.url,
            "title": target.title(),
            "tables": [],
            "view_buttons": [],
        }
        for i, t in enumerate(target.locator("table").all()):
            try:
                headers = [h.inner_text().strip()[:40]
                           for h in t.locator("thead tr th").all()[:15]]
                # First 3 body rows
                body_rows = []
                for tr in t.locator("tbody tr").all()[:3]:
                    cells = [td.inner_text().strip()[:40]
                             for td in tr.locator("td").all()[:15]]
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

        # Look for 'view' buttons specifically
        for btn in target.locator(
            "button:has-text('view'), a:has-text('view'), input[value*='view' i]"
        ).all()[:20]:
            try:
                summary["view_buttons"].append({
                    "tag": btn.evaluate("el => el.tagName"),
                    "text": (btn.inner_text() or btn.get_attribute("value") or "")[:40],
                    "id": btn.get_attribute("id") or "",
                    "class": (btn.get_attribute("class") or "")[:80],
                    "onclick": (btn.get_attribute("onclick") or "")[:120],
                })
            except Exception:
                pass

        json_path = PROBE_DIR / f"{slug}-summary.json"
        json_path.write_text(json.dumps(summary, indent=2))
        print(f"  ✓ Summary → {json_path}")

        print()
        print(f"Tables found: {len(summary['tables'])}")
        for t in summary['tables']:
            if 'headers' in t:
                print(f"  table {t['index']} ({t.get('total_body_rows', '?')} rows): "
                      f"headers = {t['headers'][:5]}")
        print(f"View-like buttons: {len(summary['view_buttons'])}")
        for b in summary['view_buttons'][:5]:
            print(f"  {b['tag']} text={b['text']!r} class={b['class'][:40]!r}")
    finally:
        p.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
