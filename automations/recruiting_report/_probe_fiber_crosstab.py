"""Probe the Fiber Lead Performance / AUTOMATIONPULL-NICHURNVIEW Crosstab
dialog to discover worksheet names — per `Later thoughts/fiber-per-icd-
totals-view.md`, a per-ICD totals worksheet was added 2026-05-22.

Run: .venv/bin/python -m automations.recruiting_report._probe_fiber_crosstab
"""
from __future__ import annotations
from pathlib import Path
from automations.shared.tableau_patchright import tableau_session


URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER2_1-D2D/FiberLeadPerformance/"
    "a79fd021-3606-4aa2-bf55-bc3856cdac99/AUTOMATIONPULL-NICHURNVIEW"
)


def main() -> int:
    print(f"-> Loading {URL}", flush=True)
    with tableau_session(verbose=True) as page:
        page.goto(URL, wait_until="domcontentloaded")
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        dl_btn = viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]')
        dl_btn.wait_for(state="visible", timeout=35_000)
        print("-> viz toolbar visible, waiting 25s for hydration…", flush=True)
        page.wait_for_timeout(25_000)
        print("-> clicking Download…", flush=True)
        dl_btn.click()
        page.wait_for_timeout(1800)
        print("-> clicking Crosstab menu item…", flush=True)
        viz.locator(
            '[data-tb-test-id="download-flyout-download-crosstab-MenuItem"]'
        ).click()
        # Wait for thumbnails to populate
        thumbs = viz.locator('[data-tb-test-id^="sheet-thumbnail-"]')
        for i in range(30):
            page.wait_for_timeout(1000)
            n = thumbs.count()
            if n > 0:
                print(f"-> {n} thumbnails appeared after {i+1}s", flush=True)
                break
        else:
            print("-> WARN: no thumbnails appeared after 30s", flush=True)

        n = thumbs.count()
        print(f"\n=== {n} worksheets available in Crosstab dialog ===")
        for i in range(n):
            try:
                txt = thumbs.nth(i).inner_text().strip()
                print(f"  [{i}] {txt!r}")
            except Exception as e:
                print(f"  [{i}] (failed read: {e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
