"""Dump the raw View Data window text from the unfiltered Fiber Penetration
by Zip view, so we can fix _parse_view_data_text's column-sliding bug AND
see how owner-subtotal rows are tagged.

Run: .venv/bin/python -m automations.recruiting_report._probe_fiber_raw
"""
from __future__ import annotations

from pathlib import Path

from automations.recruiting_report.opt_phase import (
    FIBER_VIEW_URL,
    FIBER_OVERVIEW_XY,
    _wait_viz_loaded,
)
from automations.shared.tableau_patchright import tableau_session


WORKSPACE = Path(__file__).resolve().parent.parent.parent
OUT_RAW = WORKSPACE / "output" / "fiber_view_data_raw.txt"


def main() -> int:
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    print(f"-> Loading unfiltered Fiber view + opening View Data", flush=True)
    with tableau_session(verbose=True) as page:
        ctx = page.context
        # Mirror the front of _scrape_one_view_data so we drive the same flow.
        page.goto(FIBER_VIEW_URL, wait_until="domcontentloaded")
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        dl = viz.locator('[data-tb-test-id="viz-viewer-toolbar-button-download"]')
        dl.wait_for(state="visible", timeout=40_000)
        _wait_viz_loaded(page)
        for _ in range(3):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

        # Activate via clicking the by-zip table area (use one of the working
        # XYs from probe v2). Then press Escape AFTER to attempt to clear any
        # mark selection — that's the new bit.
        box = page.query_selector('iframe[title="Data Visualization"]').bounding_box()
        cx = box["x"] + box["width"] * 0.50
        cy = box["y"] + box["height"] * 0.65
        page.mouse.click(cx, cy)
        page.wait_for_timeout(1100)
        # KEY: Escape AFTER click — should clear mark selection while leaving
        # the worksheet "active" for Download->Data.
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)

        # Open Download → Data
        before = set(ctx.pages)
        for _ in range(8):
            try:
                dl.click(timeout=8000)
                break
            except Exception:
                page.wait_for_timeout(2000)
        page.wait_for_timeout(1400)
        data_item = viz.locator(
            '[data-tb-test-id="download-flyout-download-data-MenuItem"]')
        if data_item.get_attribute("aria-disabled") == "true":
            print("FAIL: Download->Data still disabled after Escape — "
                  "the activate-click was needed to enable it. Try again "
                  "without the Escape.", flush=True)
            return 1
        data_item.click()
        page.wait_for_timeout(8000)
        win = next((pg for pg in ctx.pages if pg not in before), None)
        if win is None:
            print("FAIL: View Data window didn't open", flush=True)
            return 1
        # Scroll the data window to load more rows
        for _ in range(15):
            win.evaluate("""() => {
              const cands = [];
              document.querySelectorAll('*').forEach(e => {
                const d = e.scrollHeight - e.clientHeight;
                if (d > 0 && e.clientHeight > 120) cands.push([d, e]);
              });
              cands.sort((a, b) => b[0] - a[0]);
              cands.slice(0, 3).forEach(([d, e]) => {
                e.scrollTop += Math.round(e.clientHeight * 0.5);
              });
            }""")
            win.wait_for_timeout(700)
        raw = win.evaluate("() => document.body ? document.body.innerText : ''")
        try:
            win.close()
        except Exception:
            pass

    print(f"-> raw text length: {len(raw)} chars", flush=True)
    OUT_RAW.write_text(raw, encoding="utf-8")
    print(f"-> saved to {OUT_RAW}", flush=True)

    # Print the first 80 lines so we can see the structure
    print("\n--- first 80 lines ---", flush=True)
    for i, line in enumerate(raw.splitlines()[:80]):
        print(f"  {i:3}: {line[:140]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
