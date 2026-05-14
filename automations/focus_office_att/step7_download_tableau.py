"""Phase 3 — Step 7: Download the per-rep Tableau crosstab via Playwright.

VA-assisted workflow. The VA gets the view to the correct state by hand,
because two pieces are unreliable / impossible to automate:

  (a) Tableau filters are flaky — programmatic clicks frequently leave the
      view in a partially-applied state.
  (b) The Rep-dimension expander on the Owner Name column header is
      canvas-rendered (not DOM), so Playwright can't click it.

What the VA does (see VA_RUNBOOK):
  1. Open debug-port Chrome, log in to ownerville master/admin.
  2. Click 'Login to Tableau' on the ownerville Tableau page (SSO).
  3. Navigate to PRODUCT SALES SUMMARY 4WK (RafRepsDropDown custom view).
  4. Set Sale Date Week Ending filter to current week's Sunday.
  5. Set Product Type filter to NEW INTERNET / UPGRADE INTERNET / VIDEO / WIRELESS.
  6. Leave Owner Name filter on 'All' — step6_fill_tableau skips owners that
     don't have a matching tab in the Sheet, so picking 30 manually is wasted
     work.
  7. Click the `+` next to 'Owner Name' header to expand rep drilldown.
  8. Verify the visible table shows per-rep rows.
  9. Trigger this script.

What this script does:
  - Attaches to the existing Tableau tab (no goto — that resets filters).
  - Clicks Download → Crosstab → picks 'Sales By ICD (Weekly View)' sheet
    (NOT the default 'Product Sales Summary by ORG', which lacks Rep).
  - Confirms Excel format, clicks Download.
  - Captures the download, saves to a known path.
  - Validates the downloaded crosstab has the 'Rep' column. If not, the VA
    forgot to expand the rep drilldown — error loudly instead of silently
    filling the Sheet with owner-level data.

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

# RafRepsDropDown custom view of ATT Tracker 2.1 D2D / PRODUCT SALES SUMMARY 4WK.
# The UUID + view name are stable across weeks; only the filter state changes.
TABLEAU_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
    "73c65041-1966-4047-ad1e-f4cc4e8a2f05/RafRepsDropDown"
)

# How long to wait for the viz iframe to fully render after navigation.
# Tableau is heavy JS; under-waiting causes the Crosstab to export the base
# 'Product Sales Summary by ORG' sheet instead of the per-rep one.
VIZ_RENDER_WAIT_MS = 10_000

# Defaults if --out not passed.
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _find_tableau_tab(browser):
    """Return the existing Tableau tab. Errors if missing — VA must set up
    the view by hand first (see docstring)."""
    all_pages = [pg for ctx in browser.contexts for pg in ctx.pages]
    tableau_pages = [pg for pg in all_pages if "tableau.com" in pg.url.lower()]
    if not tableau_pages:
        raise RuntimeError(
            "No Tableau tab is open in the debug-port Chrome. The VA needs to "
            "open ownerville → Login to Tableau → navigate to the view + apply "
            "filters + expand rep before triggering this script."
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


def download_crosstab(out_path: Path, verbose: bool = True) -> Path:
    """Download the per-rep crosstab Excel; save to out_path. Returns out_path.

    Reuses the existing Tableau tab — does NOT goto() any URL. The VA is
    responsible for getting the view into the right state (filters applied,
    rep dimension expanded). This function only handles the click sequence
    that exports + saves the file.

    Uses page.frame_locator() rather than a cached Frame handle: Tableau
    sometimes re-attaches the viz iframe during interactions, invalidating
    a cached handle. frame_locator re-resolves on every use.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page = _find_tableau_tab(browser)
        print(f"Reusing Tableau tab: {page.url}", flush=True)

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
