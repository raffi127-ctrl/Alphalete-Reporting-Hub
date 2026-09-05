"""One-off PREVIEW of the consolidated CHURNRATES board (Carlos 2026-09-05).

Tableau restructured churn: the view where wireless churn used to live now
shows BYOD wireless / non-BYOD wireless / AIR / internet churn together, and
the three per-product saved views have been rendering BLANK since 9/03. Carlos:
"if you don't filter when pulling the churn rates and you just have everything
selected, you can see everything and take one screenshot" — and he wants to SEE
that screenshot before the thread capture is rewired.

So this captures the churn view with NOTHING appended — no owner slice, no
product param, no crop — exactly as it opens, and base64-chunks the PNG into
the 'B2B Shot' tab of the Mini Control sheet (the vantura_churn 'Vantura Shot'
channel, different tab) for the mini to decode and hand to Carlos.

READ-ONLY apart from that tab. Runs on Lucy 2 (Carlos's login carries the
views) under the shared CDP-9246 lock like every other ATTTRACKER capture.

  lucy rerun b2b_churn_preview                # default: the old wireless URL
  ... --url <view url>                        # point somewhere else
  ... --owner JAMIS                           # drive the Owner & Office
                                              # dropdown to the one member
                                              # containing this (case-insens)
                                              # substring, logging EVERY member
                                              # spelling on the way — built
                                              # 2026-09-05 because the
                                              # restructured board blanks on
                                              # every URL Owner & Office value
                                              # we know, so the member list
                                              # itself is the ground truth.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_metrics_preview"
SHOT_TAB = "B2B Shot"


def _drive_owner(page, want, log=print):
    """Thin wrapper over the PRODUCTION driver in capture.py — one
    implementation, so the preview always exercises what the thread
    will run."""
    from automations.b2b_metrics.capture import drive_owner
    return drive_owner(page, want, log=log)


def main(argv=None) -> int:
    from automations.b2b_metrics.offices import TEAM
    ap = argparse.ArgumentParser(prog="b2b_metrics.churn_preview")
    ap.add_argument("--url", default=TEAM["churn_wireless"],
                    help="view to capture as-is (default: the churn_wireless "
                         "team view — 'literally where the wireless churn "
                         "used to be')")
    ap.add_argument("--owner", default=None,
                    help="drive the Owner & Office dropdown to the one member "
                         "containing this substring (logs every member)")
    args = ap.parse_args(argv)

    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.tableau_screenshots.capture import capture_page
    from automations.vantura_churn import cdp_pull

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spec = {"id": "churn_preview", "title": "churn_preview", "url": args.url}
    print(f"capturing AS-IS (no slice, no crop): {args.url}", flush=True)

    with cdp_pull._cdp_lock(label="b2b churn_preview", log=print):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        try:
            with sync_playwright() as p:
                browser = None
                for attempt in range(10):
                    time.sleep(5)
                    try:
                        browser = p.chromium.connect_over_cdp(
                            "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
                        break
                    except Exception:  # noqa: BLE001 — port not up yet
                        if attempt == 9:
                            raise
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                after = ((lambda pg: _drive_owner(pg, args.owner, log=print))
                         if args.owner else None)
                capture_page(page, spec, OUT_DIR, after_load=after,
                             verbose=True)
        finally:
            cdp_pull._kill_ours()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    out = OUT_DIR / "churn_preview.png"
    if not out.exists() or out.stat().st_size < 5000:
        print(f"capture FAILED — {out} missing or tiny", flush=True)
        return 1
    cdp_pull._upload_png(out.read_bytes(), tab=SHOT_TAB)
    print(f"OK {out.stat().st_size} bytes -> sheet tab {SHOT_TAB!r}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
