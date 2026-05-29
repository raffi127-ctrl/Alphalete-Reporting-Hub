"""Step 4: scrape one day's Time Tracker data for the currently-
impersonated owner. Prints structured data — no Sheet writes yet —
so we can verify the columns/values look right before committing.

Prereq: Chrome session is impersonating an owner (run step2 first).

Run:
  .venv/bin/python -m automations.focus_office_att.step4_scrape_one_day
  .venv/bin/python -m automations.focus_office_att.step4_scrape_one_day --date 2026-05-12
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
TIME_TRACKER_PAGE = "p=510"

# Column indices in the source table (timeTrackingTable)
SRC_NAME = 1
SRC_FIRST_KNOCK = 2
SRC_LAST_KNOCK = 3
SRC_GAPS = 5
SRC_TOTAL_GAPS = 6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="MM/DD/YYYY or YYYY-MM-DD; defaults to today")
    args = ap.parse_args()

    # Parse target date → MM/DD/YYYY (the format the picker expects)
    if args.date:
        try:
            d = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            d = dt.datetime.strptime(args.date, "%m/%d/%Y").date()
    else:
        d = dt.date.today()
    target_mdy = d.strftime("%m/%d/%Y")
    print(f"Target date: {target_mdy} ({d.strftime('%A')})")

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
        print(f"✓ Connected. Title: {page.title()}")

        # If not on Time Tracker, navigate there
        if TIME_TRACKER_PAGE not in page.url:
            rqst = page.evaluate("typeof rqstValue !== 'undefined' ? rqstValue : null")
            if not rqst:
                print("❌ No rqstValue — not logged in / impersonating?")
                return 1
            print(f"  → Navigating to Time Tracker…")
            page.goto(f"https://v2.ownerville.com/index.cfm?p=510&rqst={rqst}",
                      wait_until="networkidle", timeout=20000)
            print(f"  ✓ Now on {page.url}")

        # Set date picker. The input is a jQuery datepicker; setting it can
        # trigger a full page navigation (not just a DataTables refresh) on
        # this site, so we treat it as such.
        print(f"  → Setting date to {target_mdy}…")
        try:
            page.evaluate(
                """(targetDate) => {
                    const el = $('#datepicker');
                    if (!el.length) throw new Error('datepicker input not found');
                    if (el.datepicker && typeof el.datepicker === 'function') {
                        try { el.datepicker('setDate', targetDate); } catch(e) {}
                    }
                    el.val(targetDate).trigger('change').trigger('blur');
                }""",
                target_mdy,
            )
        except Exception as e:
            # 'Execution context was destroyed' means the page navigated —
            # that's actually what we want here. Wait it out below.
            if "context was destroyed" not in str(e).lower():
                raise
            print(f"  → (page navigated as expected after date change)")

        # Wait for the page to settle after the date change (could be a full
        # reload OR just a DataTables AJAX refresh).
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Verify the picker now shows the target date — but tolerate a
        # navigation if the context is still settling.
        try:
            actual = page.evaluate("typeof $ !== 'undefined' ? $('#datepicker').val() : null")
            if actual is None:
                print(f"  ⚠ jQuery not yet available; the page may still be loading")
            else:
                print(f"  ✓ Date picker now shows: {actual!r}")
                if actual != target_mdy:
                    print(f"  ⚠ Date didn't update — picker shows {actual!r}, expected {target_mdy!r}")
        except Exception as e:
            print(f"  ⚠ Couldn't re-read date picker ({type(e).__name__}); continuing")

        # NOW set "Show 100" — after the date-change navigation, the page
        # has reset to default 10 rows.
        print(f"  → Setting Show entries to 100…")
        try:
            page.locator("select[name='timeTrackingTable_length']").select_option("100")
            page.wait_for_load_state("networkidle", timeout=8000)
            print(f"  ✓ Page size set to 100")
        except Exception as e:
            print(f"  ⚠ Couldn't set page size to 100: {type(e).__name__}: {str(e)[:80]} (will continue with default)")

        # Scrape the rep table — paginate via DataTables "Next" button
        # for owners with more than 100 reps.
        print(f"  → Reading rep rows…")
        table = page.locator("table#timeTrackingTable")
        page.wait_for_function(
            """() => {
                const rows = document.querySelectorAll('#timeTrackingTable tbody tr');
                return rows.length >= 1;
            }""",
            timeout=10000,
        )

        def scrape_visible_page() -> list[dict]:
            out = []
            for tr in table.locator("tbody tr").all():
                try:
                    cells = tr.locator("td").all()
                    if len(cells) < 7:
                        continue
                    if cells[0].inner_text().strip().lower().startswith("no data"):
                        continue
                    out.append({
                        "name": cells[SRC_NAME].inner_text().strip(),
                        "first_knock": cells[SRC_FIRST_KNOCK].inner_text().strip(),
                        "last_knock": cells[SRC_LAST_KNOCK].inner_text().strip(),
                        "gaps": cells[SRC_GAPS].inner_text().strip(),
                        "total_gaps": cells[SRC_TOTAL_GAPS].inner_text().strip().split("\n")[0],
                    })
                except Exception:
                    continue
            return out

        scraped = []
        page_num = 1
        max_pages = 20  # safety cap — 100 reps × 20 pages = 2,000 reps
        while page_num <= max_pages:
            chunk = scrape_visible_page()
            scraped.extend(chunk)
            print(f"    page {page_num}: +{len(chunk)} rep(s) (total {len(scraped)})")
            # Check if there's a next-page button that's not disabled
            next_btn = page.locator("#timeTrackingTable_next").first
            if next_btn.count() == 0:
                break
            klass = next_btn.get_attribute("class") or ""
            if "disabled" in klass:
                break  # last page
            # Click next, wait for table to refresh, repeat
            next_btn.click()
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page_num += 1
        if page_num > max_pages:
            print(f"  ⚠ Hit safety cap of {max_pages} pages — there may be more reps "
                  f"that didn't get scraped.")

        print()
        print(f"=== Scraped {len(scraped)} rep(s) for {target_mdy} ===")
        if not scraped:
            print("(no rep rows — did the date have any activity?)")
        else:
            print(f"{'Rep':30s}  {'1st Knock':10s}  {'Last Knock':10s}  {'Gaps':>5s}  {'Gap Time':>10s}")
            print("-" * 75)
            for r in scraped:
                print(f"{r['name'][:30]:30s}  "
                      f"{r['first_knock'][:10]:10s}  "
                      f"{r['last_knock'][:10]:10s}  "
                      f"{r['gaps'][:5]:>5s}  "
                      f"{r['total_gaps'][:10]:>10s}")

        # Save the scraped data alongside the probes for reference
        out = Path(__file__).resolve().parent.parent.parent / "output" / "probes"
        out.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%H%M%S")
        out_path = out / f"step4-scrape-{d.isoformat()}-{ts}.json"
        out_path.write_text(json.dumps({
            "title": page.title(),
            "url": page.url,
            "target_date": target_mdy,
            "row_count": len(scraped),
            "reps": scraped,
        }, indent=2))
        print(f"\n  ✓ Saved → {out_path}")
    finally:
        p.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
