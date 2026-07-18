"""📸 Tableau Metrics — a screenshot of the ATT TRACKER 2.1 "Metrics" view,
FILTERED to one office's owner, posted into that office's Metrics thread.

Raf 2026-07-16 (loom): "a screenshot of essentially this … provide each ICD with
the data for the office slack it's being posted in." It carries a bit of extra
data (5 GIG, etc.) beyond the crosstab metrics, and gets reps used to reading
Tableau. So this is an IMAGE metric — no crosstab parse; capture the view and
post the picture — unlike the other 11 which pull data.

Reuses:
  * tableau_screenshots.capture.capture_page — the same capture that grabs the
    country trackers (Download → Image, crop).
  * slack_metrics_post.post_reply_with_image — the same thread-post Rep
    Activations uses; it reads METRICS_CHANNEL_ID + METRICS_HEADER_LABEL from the
    env the office runner already sets, so the image lands in the right office's
    (labelled) thread with no extra wiring.

Per-office filter: the base view is ALL TEAMS; we scope it to the office by
appending a Tableau URL filter `?<FILTER_FIELD>=<owner>`. The exact filter
CAPTION on the Metrics view is the one thing that must be confirmed live (open
the view, read the filter's caption) — it defaults to "Owner Name" (matches the
other metrics) and is overridable via env METRICS_SHOT_FILTER_FIELD or --filter-
field so it can be corrected without a code change during the preview.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ALL-TEAMS Metrics view (Raf's loom). ?:iid=1 is the interaction id Tableau
# stamps; harmless to keep. We strip any existing query and re-append our own.
BASE_VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                 "ATTTRACKER2_1-D2D/Metrics")

# Tableau URL-filters on the filter's DISPLAY CAPTION, not the field name.
# "Owner Name" is the caption the other AT&T views use; confirm on the live
# Metrics view during preview and override here (or via env) if it differs.
DEFAULT_FILTER_FIELD = os.environ.get("METRICS_SHOT_FILTER_FIELD", "Owner Name")


def build_view_url(owner: str, *, filter_field: str) -> str:
    """All-teams Metrics view scoped to one owner via a Tableau URL filter.

    Tableau reads the filter's caption + a URL-encoded value; a space in the
    caption or value must be %20. `:embed=y` + `:showVizHome=no` give a clean
    canvas (no site chrome) for the screenshot."""
    base = BASE_VIEW_URL.split("?", 1)[0]
    params = [
        f"{quote(filter_field)}={quote(owner)}",
        ":iid=1",
        ":embed=y",
        ":showVizHome=no",
    ]
    return f"{base}?{'&'.join(params)}"


def _spec(owner: str, url: str) -> dict:
    """capture_page spec — full-canvas image of the dashboard (like the country
    trackers' canvas crop). No bar-crop: the Metrics view is one board, not a
    stacked multi-page like the D2D tracker."""
    return {
        "id": f"metrics_shot_{owner.lower().replace(' ', '_')}",
        "title": f"Metrics — {owner}",
        "url": url,
        "crop": "canvas",
    }


def capture(owner: str, *, out_dir: Path, filter_field: str,
            headless: bool = False, verbose: bool = True) -> Path:
    """Log in to Tableau once, navigate to the owner-filtered Metrics view, and
    save the board as a PNG. Returns the image path."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture as _cap
    url = build_view_url(owner, filter_field=filter_field)
    if verbose:
        print(f"  view: {url}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tableau_session(headless=headless, allow_form_login=False,
                         verbose=verbose) as page:
        return _cap.capture_page(page, _spec(owner, url), out_dir, verbose=verbose)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="metrics_shot")
    ap.add_argument("--owner", default=os.environ.get("METRICS_SHOT_OWNER"),
                    help="ICD Owner Name to filter the Metrics view to "
                         "(env METRICS_SHOT_OWNER).")
    ap.add_argument("--filter-field", default=DEFAULT_FILTER_FIELD,
                    help="Tableau filter caption on the Metrics view "
                         "(default 'Owner Name').")
    ap.add_argument("--live", action="store_true",
                    help="capture AND post the image into the office thread.")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture + save the PNG to Downloads, DO NOT post "
                         "(preview the screenshot before wiring it live).")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args(argv)

    if not args.owner:
        print("--owner (or METRICS_SHOT_OWNER) is required.")
        return 2
    live = args.live and not args.dry_run

    out_dir = (Path.home() / "Downloads") if live else Path(tempfile.gettempdir())
    print(f"=== 📸 Tableau Metrics — owner={args.owner!r} — "
          f"{'LIVE' if live else 'DRY-RUN'} ===", flush=True)
    try:
        png = capture(args.owner, out_dir=out_dir, filter_field=args.filter_field,
                      headless=args.headless, verbose=True)
    except Exception as e:  # noqa: BLE001
        print(f"✗ capture failed: {type(e).__name__}: {e}")
        return 1
    print(f"✓ captured: {png}  ({png.stat().st_size // 1024} KB)", flush=True)

    if not live:
        print("  (dry-run — image saved, NOT posted. Open it to check the crop "
              "+ that it shows only this office's data.)")
        print("=== done ===")
        return 0

    from automations.shared.slack_metrics_post import (
        post_reply_with_image, SlackPostError)
    try:
        post_reply_with_image(
            png, comment="📸 Tableau Metrics",
            react_emoji="camera_with_flash",
            file_name=f"Tableau Metrics — {args.owner}.png")
        print("  ✓ Slack: posted Tableau Metrics screenshot")
    except SlackPostError as e:
        print(f"✗ Slack post failed: {e}")
        return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
