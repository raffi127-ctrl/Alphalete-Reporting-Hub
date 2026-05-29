"""Reconnaissance helper: attach to debug-port Chrome and snapshot state.

Used during the Phase 3 download-automation build to inspect what each click
in the ownerville → Tableau flow does (URL, DOM, screenshot). Not part of the
production scraper — safe to delete after Phase 3 ships.

Run:
    .venv/bin/python -m automations.focus_office_att._explore
    .venv/bin/python -m automations.focus_office_att._explore --label step0_landing
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "_phase3_explore"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=dt.datetime.now().strftime("%H%M%S"),
                    help="Name suffix for the screenshot + DOM dump")
    ap.add_argument("--match", default="ownerville",
                    help="URL substring to find the page (default: ownerville)")
    ap.add_argument("--goto",
                    help="If set, navigate the matched page to this URL before snapshotting")
    ap.add_argument("--new-tab",
                    help="If set, open this URL in a new tab in the same context (instead of navigating)")
    ap.add_argument("--wait", type=float, default=2.0,
                    help="Seconds to wait after --goto/--new-tab before snapshotting (default 2)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
        except Exception as e:
            print(f"FAIL: could not connect to Chrome on :9222 — {e}")
            print("Is debug-port Chrome running?")
            return 1

        all_pages = []
        for ctx in browser.contexts:
            all_pages.extend(ctx.pages)

        print(f"Found {len(all_pages)} page(s) in the browser:")
        for i, pg in enumerate(all_pages):
            print(f"  [{i}] {pg.url}")

        # Pick by substring match
        matches = [pg for pg in all_pages if args.match.lower() in pg.url.lower()]
        if not matches:
            print(f"\nNo page matches '{args.match}'. Open the right tab and rerun.")
            return 2

        page = matches[0]
        print(f"\nUsing: {page.url}")

        if args.new_tab:
            ctx = page.context
            new_page = ctx.new_page()
            print(f"Opening new tab: {args.new_tab}")
            new_page.goto(args.new_tab, wait_until="domcontentloaded")
            new_page.wait_for_timeout(int(args.wait * 1000))
            page = new_page
            print(f"Settled at: {page.url}")
        elif args.goto:
            print(f"Navigating to: {args.goto}")
            page.goto(args.goto, wait_until="domcontentloaded")
            page.wait_for_timeout(int(args.wait * 1000))
            print(f"Settled at: {page.url}")

        print(f"Title: {page.title()}")

        shot = OUT_DIR / f"{args.label}.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"Screenshot: {shot}")

        html = OUT_DIR / f"{args.label}.html"
        html.write_text(page.content(), encoding="utf-8")
        print(f"HTML: {html} ({html.stat().st_size:,} bytes)")

        # Also dump iframe contents — Tableau wraps the viz toolbar in an
        # iframe so the parent HTML alone misses the Download button etc.
        frames = [f for f in page.frames if f != page.main_frame]
        for i, frame in enumerate(frames):
            try:
                frame_html = frame.content()
            except Exception as e:
                print(f"  frame[{i}] ({frame.url}): could not read ({e})")
                continue
            frame_path = OUT_DIR / f"{args.label}.frame{i}.html"
            frame_path.write_text(frame_html, encoding="utf-8")
            print(f"  frame[{i}]: {frame.url}")
            print(f"  frame[{i}] HTML: {frame_path} ({frame_path.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
