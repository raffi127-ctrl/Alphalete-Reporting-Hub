"""Step 2: from the Office Access page (?p=901), find a specific owner's
row in the DataTables-powered owner list, click the action link in that
row, handle the SweetAlert 'Are you sure?' modal by clicking Yes, then
wait for the page to switch to that owner's portal.

Then dumps the resulting portal page so we can design step 3 (sidebar
navigation: Telemapper Leads → Reports → Time Tracker).

Run (after you're logged in + on Office Access page; the script can
also click Office Access itself if needed):
  .venv/bin/python -m automations.focus_office_att.step2_view_owner
  .venv/bin/python -m automations.focus_office_att.step2_view_owner --owner "Cody Cannon"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
PROBE_DIR = Path(__file__).resolve().parent.parent.parent / "output" / "probes"
OFFICE_ACCESS_FRAGMENT = "p=901"
# When set, step2 navigates to Office Access via direct URL instead of clicking
# the side-nav "Office Access" link (which is only visible on master pages —
# not on impersonated owner portals). Set by run_all_owners before each
# subprocess invocation.
MASTER_RQST_ENV = "FOCUS_OFFICE_MASTER_RQST"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default="Cody Cannon",
                    help="Owner name to find + view")
    args = ap.parse_args()
    target_owner = args.owner

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    p = sync_playwright().start()
    try:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"❌ Couldn't connect to Chrome at {CDP_URL}: {e}")
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
            print("❌ No ownerville.com tab found. Open + log in first.")
            return 1
        print(f"✓ Connected. Current URL: {page.url}")

        # Navigate to Office Access. Robust strategy that handles all 3 cases
        # (already there / on master Welcome / on impersonated owner portal):
        #   1. If env var MASTER_RQST set: navigate to ?p=2&rqst=MASTER first
        #      (forces back to master Welcome, even from impersonation).
        #   2. From whatever Welcome-equivalent page we land on, click the
        #      side-nav "Office Access" link to land at ?p=901&rqst=...
        if OFFICE_ACCESS_FRAGMENT not in page.url:
            master_rqst = os.environ.get(MASTER_RQST_ENV)
            if master_rqst and "p=2" not in page.url:
                # Force back to master Welcome via direct URL.
                url = f"https://v2.ownerville.com/index.cfm?p=2&rqst={master_rqst}"
                print(f"  → Resetting to master Welcome via master rqst…")
                page.goto(url, wait_until="networkidle", timeout=15000)
            print(f"  → Clicking 'Office Access' nav link from {page.url}")
            page.get_by_role("link", name="Office Access").first.click(timeout=8000)
            page.wait_for_url(f"**{OFFICE_ACCESS_FRAGMENT}*", timeout=10000)
            print(f"  ✓ Now on {page.url}")

        # Wait for the DataTables-powered owner table to finish loading.
        # 'Loading...' is the placeholder row shown while fetching; we wait
        # for it to disappear AND for at least 2 real rows.
        print(f"  → Waiting for owner table (DataTables AJAX load)…")
        owner_table = page.locator("table#promotingOffices")
        owner_table.wait_for(state="visible", timeout=10000)
        # Wait until tbody has rows that aren't 'Loading...'
        page.wait_for_function(
            """() => {
                const rows = document.querySelectorAll('table#promotingOffices tbody tr');
                if (rows.length < 2) return false;
                const firstCellText = rows[0].textContent || '';
                return !firstCellText.toLowerCase().includes('loading');
            }""",
            timeout=20000,
        )
        # Use the DataTables search box to filter down to just rows matching
        # the target owner's name. Much more reliable than paginating: with
        # the default page size of 50, owners past row 50 are simply not in
        # the DOM and our row-scan loop misses them.
        try:
            search_input = page.locator("#promotingOffices_filter input").first
            search_input.fill("")           # clear any prior search
            search_input.type(target_owner, delay=20)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            # Wait briefly for DataTables client-side filter to apply.
            page.wait_for_timeout(400)
        except Exception as e:
            print(f"  ⚠ Search box not usable ({e}); falling back to full-table scan.")
        row_count = owner_table.locator("tbody tr").count()
        print(f"  ✓ Owner table filtered ({row_count} row(s) after search)")

        # Find the row matching the target owner. Columns per headers:
        # 0=Account#, 1=Office Name, 2=Owner Name, 3=Sales Reps, 4=Modules, 5=Action
        owner_row = None
        for i, tr in enumerate(owner_table.locator("tbody tr").all()):
            try:
                cells = tr.locator("td").all()
                if len(cells) < 3:
                    continue
                name_cell = cells[2].inner_text().strip()
                if name_cell.lower() == target_owner.lower():
                    owner_row = tr
                    print(f"  ✓ Found '{target_owner}' at row {i}")
                    break
            except Exception:
                continue
        if owner_row is None:
            print(f"❌ Couldn't find owner '{target_owner}' in the table.")
            print("   Available owners (first 5):")
            for i, tr in enumerate(owner_table.locator("tbody tr").all()[:5]):
                cells = tr.locator("td").all()
                if len(cells) >= 3:
                    print(f"     {i}: {cells[2].inner_text().strip()}")
            return 1

        # Find the action button (last cell in row) and extract its officeId.
        # Bypassing the SweetAlert modal entirely — SweetAlert v1's callback
        # doesn't reliably fire on Playwright clicks. Instead we read the
        # office id off the data attribute and call the impersonate AJAX
        # endpoint directly via page.evaluate (using jQuery which is already
        # loaded on the page).
        action_cell = owner_row.locator("td").last
        action_btn = action_cell.locator("button, a").first
        office_id = action_btn.get_attribute("data-officeid") or ""
        if not office_id:
            print(f"❌ Action button has no data-officeid attribute. "
                  f"outerHTML: {action_btn.evaluate('el => el.outerHTML')[:200]}")
            return 1
        print(f"  ✓ '{target_owner}' → office id {office_id}")

        # Run the impersonate AJAX call directly. The page already has jQuery
        # loaded and the rqstValue var defined. This is the same code that
        # SweetAlert's confirm callback would have run.
        print(f"  → Calling confirmImpersonate({office_id}) directly…")
        before_title = page.title()
        result = page.evaluate(
            """(officeId) => new Promise((resolve, reject) => {
                if (typeof $ === 'undefined' || typeof rqstValue === 'undefined') {
                    reject('jQuery or rqstValue not available on page');
                    return;
                }
                $.ajax({
                    url: "components/promotions/promotions.cfc",
                    method: "POST",
                    data: {rqst: rqstValue, officeid: officeId, method: "confirmImpersonate"}
                })
                .done(r => {
                    // The endpoint returns a JSON-encoded string instead of
                    // a parsed object; handle both shapes.
                    const parsed = (typeof r === 'string') ? JSON.parse(r) : r;
                    if (parsed && parsed.data && parsed.data.success) {
                        resolve({ok: true, redirect: 'index.cfm?p=2&rqst=' + rqstValue});
                    } else {
                        resolve({ok: false, response: JSON.stringify(parsed).slice(0, 200)});
                    }
                })
                .fail((xhr, status, err) => {
                    resolve({ok: false, error: status + ': ' + err});
                });
            })""",
            office_id,
        )
        if not result.get("ok"):
            print(f"❌ confirmImpersonate failed: {result}")
            return 1
        print(f"  ✓ Impersonate succeeded, navigating to {result['redirect']}")

        # Navigate to the post-impersonate landing page
        page.goto(f"https://v2.ownerville.com/{result['redirect']}")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        print(f"  ✓ Now on {page.url}")
        print(f"  ✓ Page title: {page.title()}")
        if page.title() == before_title:
            print(f"  ⚠ Title didn't change — impersonate may not have switched session.")

        # Dump the resulting portal page so we can design step 3 (sidebar nav)
        ts = dt.datetime.now().strftime("%H%M%S")
        slug = f"step2-{target_owner.lower().replace(' ', '-')}-portal-{ts}"
        (PROBE_DIR / f"{slug}.html").write_text(page.content())
        print(f"  ✓ HTML  → {PROBE_DIR / (slug + '.html')}")

        # Pull a digest of the sidebar nav so I can find Telemapper Leads → Reports → Time Tracker
        summary = {
            "url": page.url,
            "title": page.title(),
            "nav_items": [],
            "telemapper_links": [],
        }
        # Common sidebar containers
        for nav in page.locator("nav, .sidebar, .left-menu, ul.nav, .nav-menu, #sidebar, .side-nav").all()[:5]:
            try:
                items = []
                for el in nav.locator("a, span, li").all()[:50]:
                    try:
                        t = el.inner_text().strip()[:40]
                        if t and len(t) < 50:
                            items.append(t)
                    except Exception:
                        pass
                summary["nav_items"].append({
                    "id": nav.get_attribute("id") or "",
                    "class": (nav.get_attribute("class") or "")[:80],
                    "items": items,
                })
            except Exception:
                pass

        # Specifically look for telemapper-related links/text
        for el in page.locator("a, button, span").all()[:200]:
            try:
                t = el.inner_text().strip().lower()
                if "telemapper" in t or "time tracker" in t or "reports" in t:
                    summary["telemapper_links"].append({
                        "tag": el.evaluate("el => el.tagName"),
                        "text": el.inner_text().strip()[:50],
                        "id": el.get_attribute("id") or "",
                        "class": (el.get_attribute("class") or "")[:60],
                        "href": (el.get_attribute("href") or "")[:120],
                    })
            except Exception:
                pass

        json_path = PROBE_DIR / f"{slug}-summary.json"
        json_path.write_text(json.dumps(summary, indent=2))
        print(f"  ✓ Summary → {json_path}")

        print()
        print(f"Found {len(summary['nav_items'])} nav block(s)")
        print(f"Found {len(summary['telemapper_links'])} telemapper/reports/time-tracker link(s)")
        for tl in summary["telemapper_links"][:10]:
            print(f"  {tl['tag']}: {tl['text']!r} (class={tl['class'][:30]!r})")
    finally:
        p.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
