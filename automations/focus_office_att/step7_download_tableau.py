"""Phase 3 — Step 7: Download the per-rep Tableau crosstab via Playwright.

Zero-touch flow:
  - The 'AUTOMATION PULL' custom view (saved by Megan) holds the things
    we can't easily script: rep dimension expanded (canvas-rendered) +
    Product Type filter (the 4 types we care about).
  - Sale Date Week Ending rolls every week, so we override it via URL
    parameter at runtime. Tableau applies URL filter params on page load.

What this script does:
  1. Compute current week's Sunday.
  2. Navigate the existing Tableau tab to:
       .../AUTOMATIONPULL?Sale Date Week Ending (mon-sun)=YYYY-MM-DD
  3. Wait for the viz to render fully.
  4. Click Download → Crosstab → 'Sales By ICD (Weekly View)' → Excel.
  5. Capture the download, save to a known path.
  6. Validate the file has the 'Rep' column. If not, the saved custom view
     is broken or Tableau didn't restore the rep expansion — fail loudly.

VA workflow: just log into ownerville master/admin and have the Tableau
tab open (SSO'd via 'Login to Tableau' on the ownerville Tableau page).
Then trigger this script. No filter clicking, no rep expansion — the
custom view handles those.

Run:
    .venv/bin/python -m automations.focus_office_att.step7_download_tableau
    .venv/bin/python -m automations.focus_office_att.step7_download_tableau --fill

The optional --fill flag chains to step6_fill_tableau to write the Sheet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 'AUTOMATION PULL' custom view of ATT Tracker 2.1 D2D / PRODUCT SALES SUMMARY 4WK.
# Saved by Megan 2026-05-14 with rep dimension expanded + 4 product types selected.
# The UUID + name are stable; we override Sale Date Week Ending via URL param.
TABLEAU_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
    "b2da26b8-8971-4a45-9e42-bd04af46f0fa/AUTOMATIONPULL"
)


def _current_week_sunday() -> "dt.date":
    """Sunday at the end of the current Mon-Sun week. If today is Sunday,
    returns today. Otherwise returns the next upcoming Sunday."""
    today = dt.date.today()
    days_until_sun = (6 - today.weekday()) % 7
    return today + dt.timedelta(days=days_until_sun)


def _build_view_url(week_ending: "dt.date | None" = None) -> str:
    """Return the AUTOMATION PULL custom view URL with Sale Date Week Ending
    filter set to week_ending (defaults to current week's Sunday)."""
    from urllib.parse import quote
    if week_ending is None:
        week_ending = _current_week_sunday()
    qs = f"{quote('Sale Date Week Ending (mon-sun)')}={quote(str(week_ending))}"
    return f"{TABLEAU_VIEW_URL}?{qs}"

# How long to wait for the viz iframe to fully render after navigation.
# Tableau is heavy JS; under-waiting causes the Crosstab to export the base
# 'Product Sales Summary by ORG' sheet instead of the per-rep one.
VIZ_RENDER_WAIT_MS = 10_000

# Defaults if --out not passed.
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _find_tableau_tab(browser):
    """Return the existing Tableau tab. Errors if missing — VA must have
    SSO'd in by clicking 'Login to Tableau' on the ownerville Tableau page."""
    all_pages = [pg for ctx in browser.contexts for pg in ctx.pages]
    tableau_pages = [pg for pg in all_pages if "tableau.com" in pg.url.lower()]
    if not tableau_pages:
        raise RuntimeError(
            "No Tableau tab is open in the debug-port Chrome. Open ownerville, "
            "click 'Login to Tableau' on the Tableau index page to do the SSO "
            "dance, then rerun. The Tableau tab needs to stay open."
        )
    return tableau_pages[0]


def _validate_per_rep_file(path: Path) -> None:
    """Raise if the downloaded file is owner-level (missing Rep column).

    Caught early so we don't quietly fill the Sheet with wrong-granularity data.
    """
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    if "Rep" not in headers:
        raise RuntimeError(
            f"Downloaded file is owner-level (no 'Rep' column). Headers: {headers}. "
            "The VA must click the `+` next to 'Owner Name' in the Tableau view to "
            "expand the rep drilldown BEFORE triggering this script."
        )


def download_crosstab(out_path: Path, verbose: bool = True,
                      week_ending: "dt.date | None" = None) -> Path:
    """Download the per-rep crosstab Excel; save to out_path. Returns out_path.

    Navigates to the AUTOMATION PULL custom view with Sale Date Week Ending
    overridden via URL param (defaults to current week's Sunday). The custom
    view restores rep expansion + Product Type filter.

    Uses page.frame_locator() rather than a cached Frame handle: Tableau
    sometimes re-attaches the viz iframe during interactions, invalidating
    a cached handle. frame_locator re-resolves on every use.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page = _find_tableau_tab(browser)
        url = _build_view_url(week_ending)
        if verbose:
            print(f"Navigating Tableau tab to: {url}", flush=True)
        page.goto(url, wait_until="domcontentloaded")

        # Viz iframe has title="Data Visualization" (verified via DOM dump).
        viz = page.frame_locator('iframe[title="Data Visualization"]')

        # Wait for the Download button to exist + extra time for Tableau to
        # hydrate the data behind the viz. Under-waiting → wrong sheet picked.
        if verbose:
            print(f"Waiting for viz Download button to be visible...", flush=True)
        viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]').wait_for(
            state="visible", timeout=30_000,
        )
        if verbose:
            print(f"Download button visible. Waiting {VIZ_RENDER_WAIT_MS/1000:.0f}s for data hydration...", flush=True)
        page.wait_for_timeout(VIZ_RENDER_WAIT_MS)

        if verbose:
            print("Clicking Download → Crosstab → Sales By ICD (Weekly View) → Excel...", flush=True)

        debug_dir = out_path.parent / "_phase3_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        with page.expect_download(timeout=60_000) as dl_info:
            # Open Download menu (in viz toolbar)
            viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]').click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(debug_dir / "01_download_menu.png"), full_page=True)

            # Click Crosstab option
            viz.locator('[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]').click()
            # Modal takes 2-3s to fully render thumbnails. Wait for the title
            # text 'Sales By ICD (Weekly View)' to actually appear before clicking it.
            viz.locator(
                '[data-tb-test-id^="sheet-thumbnail-"]:has-text("Sales By ICD (Weekly View)")'
            ).first.wait_for(state="visible", timeout=10_000)
            page.screenshot(path=str(debug_dir / "02_modal_open.png"), full_page=True)

            # Click the right sheet thumbnail
            target_thumb = viz.locator(
                '[data-tb-test-id^="sheet-thumbnail-"]:has-text("Sales By ICD (Weekly View)")'
            ).first
            if verbose:
                tid = target_thumb.get_attribute("data-tb-test-id")
                print(f"Target thumbnail data-tb-test-id: {tid}", flush=True)
            target_thumb.click()
            page.wait_for_timeout(800)
            page.screenshot(path=str(debug_dir / "03_after_thumb_click.png"), full_page=True)

            # Ensure Excel format selected (it's default, but be defensive)
            excel_radio = viz.locator(
                '[data-tb-test-id="crosstab-options-dialog-radio-excel-RadioButton"]'
            )
            if not excel_radio.is_checked():
                excel_radio.check()
            page.screenshot(path=str(debug_dir / "04_before_download_click.png"), full_page=True)

            # Click final Download button in modal
            viz.locator('[data-tb-test-id="export-crosstab-export-Button"]').click()

        dl = dl_info.value
        if verbose:
            print(f"Download fired: {dl.suggested_filename}", flush=True)
        dl.save_as(str(out_path))
        if verbose:
            print(f"Saved: {out_path} ({out_path.stat().st_size:,} bytes)", flush=True)

    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "tableau_phase3_download.xlsx",
        help="Where to save the downloaded crosstab",
    )
    ap.add_argument(
        "--fill",
        action="store_true",
        help="After download, also run step6_fill_tableau to fill the Sheet",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="With --fill: don't actually write to the Sheet",
    )
    args = ap.parse_args()

    try:
        out = download_crosstab(args.out)
        _validate_per_rep_file(out)
    except PlaywrightTimeoutError as e:
        print(f"FAIL: timed out — {e}", flush=True)
        return 2
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", flush=True)
        return 1

    print(f"\nDownloaded crosstab: {out}")

    if args.fill:
        print("\nHanding off to step6_fill_tableau...", flush=True)
        # Import here so step7 can be used standalone without dragging in
        # gspread / Sheet auth when you only want the download.
        from automations.focus_office_att import step6_fill_tableau
        sys.argv = [
            "step6_fill_tableau",
            "--file", str(out),
            *(["--dry-run"] if args.dry_run else []),
        ]
        return step6_fill_tableau.main()

    return 0


if __name__ == "__main__":
    sys.exit(main())
