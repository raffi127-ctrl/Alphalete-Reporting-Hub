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

# Raf's local office — the main #alphalete-sales report's owner (its module is
# separate, but its shot is captured in the same shared session as the rest).
MAIN_OWNER = "Rafael Hidalgo"

# Per-DAY shot cache. The first office to run captures EVERY office's shot in one
# logged-in session; the others just post their PNG from here (seconds, no
# browser). Keyed by date so a stale shot can never be posted as today's.
SHOT_CACHE = Path(__file__).resolve().parents[2] / "output" / "office_metrics" / "shots"


def build_view_url(owner: str | None, *, filter_field: str,
                   no_filter: bool = False) -> str:
    """The Metrics view — ALL TEAMS if no_filter, else scoped to one owner via a
    Tableau URL filter.

    Tableau reads the filter's caption + a URL-encoded value; a space in the
    caption or value must be %20. NO :embed / :showVizHome — capture_page drives
    Tableau's own Download→Image TOOLBAR, and embed mode hides that toolbar (the
    capture hung until it timed out). Match the working trackers: bare `?:iid=1`
    plus the filter."""
    base = BASE_VIEW_URL.split("?", 1)[0]
    params = []
    if not no_filter:
        params.append(f"{quote(filter_field)}={quote(owner or '')}")
    params.append(":iid=1")
    return f"{base}?{'&'.join(params)}"


def all_owners() -> list[str]:
    """Every owner that gets a shot: Raf's local office + the registry offices."""
    from automations.office_metrics import offices as _off
    owners = [MAIN_OWNER]
    owners += [_off.OFFICES[k].owner for k in _off.ORDER]
    # de-dupe, keep order
    seen, out = set(), []
    for o in owners:
        if o.lower() not in seen:
            seen.add(o.lower()); out.append(o)
    return out


def _cache_dir(today: "dt.date | None" = None) -> Path:
    import datetime as _dt
    today = today or _dt.date.today()
    return SHOT_CACHE / today.isoformat()


def cached_shot(owner: str) -> Path | None:
    """Today's already-captured PNG for this owner, or None."""
    p = _cache_dir() / f"{_slug(owner)}.png"
    return p if p.exists() and p.stat().st_size > 0 else None


def _slug(owner: str) -> str:
    return owner.lower().replace(" ", "_").replace("/", "-")


def capture_all(owners: list[str], *, filter_field: str, headless: bool = False,
                verbose: bool = True) -> dict:
    """Capture EVERY owner's filtered Metrics view inside ONE Tableau session.

    Why: the per-office capture used to open its own browser and do a full
    ownerville→Tableau SSO handshake for each office — eight logins for eight
    pictures of the same board (Megan 2026-07-16: "why is it so long if there's
    an all teams view?"). Logging in once and only re-filtering per office drops
    7 of the 8 logins; each office then costs just a re-render + export.

    Writes into a per-DAY cache so whichever office runs first pays the capture
    and the rest just post the PNG (same idea as METRICS_XTAB_CACHE)."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture as _cap
    out_dir = _cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    got: dict = {}
    with tableau_session(headless=headless, allow_form_login=False,
                         verbose=verbose) as page:
        for owner in owners:
            dest = out_dir / f"{_slug(owner)}.png"
            if dest.exists() and dest.stat().st_size > 0:
                got[owner] = dest
                if verbose:
                    print(f"  ↺ cached: {owner}", flush=True)
                continue
            url = build_view_url(owner, filter_field=filter_field)
            try:
                png = _cap.capture_page(page, _spec(owner, url), out_dir,
                                        verbose=verbose)
                Path(png).replace(dest)
                got[owner] = dest
                if verbose:
                    print(f"  ✓ {owner}: {dest.name} "
                          f"({dest.stat().st_size // 1024} KB)", flush=True)
            except Exception as e:  # noqa: BLE001 — one office must not kill the rest
                print(f"  ⚠ {owner}: capture failed — {type(e).__name__}: {e}",
                      flush=True)
    return got


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


def capture(owner: str | None, *, out_dir: Path, filter_field: str,
            no_filter: bool = False, headless: bool = False,
            verbose: bool = True) -> Path:
    """Log in to Tableau once, navigate to the Metrics view (owner-filtered, or
    all-teams if no_filter), and save the board as a PNG. Returns the image path."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture as _cap
    url = build_view_url(owner, filter_field=filter_field, no_filter=no_filter)
    if verbose:
        print(f"  view: {url}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = owner or "all_teams"
    with tableau_session(headless=headless, allow_form_login=False,
                         verbose=verbose) as page:
        return _cap.capture_page(page, _spec(tag, url), out_dir, verbose=verbose)


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
    ap.add_argument("--no-filter", action="store_true",
                    help="capture the ALL-TEAMS view (no per-office filter) — "
                         "for Raf's #alphalete-sales / previewing the raw board.")
    ap.add_argument("--dm", default=None, metavar="USER",
                    help="preview: DM the captured PNG to this Slack user (id / "
                         "email / name) instead of posting to the office thread. "
                         "Overrides --live/--dry-run — nothing hits a channel.")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore today's cached shot and re-capture this office "
                         "on its own (use if a cached capture went bad).")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args(argv)

    # --no-filter needs no owner; a filtered shot does.
    if not args.no_filter and not args.owner:
        print("--owner (or METRICS_SHOT_OWNER) is required (or use --no-filter "
              "for the all-teams view).")
        return 2
    live = args.live and not args.dry_run and not args.dm

    scope = "ALL TEAMS" if args.no_filter else args.owner
    mode = f"DM→{args.dm}" if args.dm else ("LIVE" if live else "DRY-RUN")
    out_dir = (Path.home() / "Downloads") if live else Path(tempfile.gettempdir())
    label = "Tableau Metrics — All Teams" if args.no_filter else \
            f"Tableau Metrics — {args.owner}"
    print(f"=== 📸 {label} — {mode} ===", flush=True)
    try:
        png = None
        # Shared-session path (the normal per-office run): reuse today's cached
        # shot if another office already captured it, else capture EVERY office
        # in ONE login and take mine from that. Turns 8 logins into 1.
        if not args.no_filter and not args.fresh:
            png = cached_shot(args.owner)
            if png:
                print(f"  ↺ using today's cached shot: {png.name}", flush=True)
            else:
                print("  no cached shot — capturing ALL offices in one session "
                      "(subsequent offices reuse these)", flush=True)
                got = capture_all(all_owners(), filter_field=args.filter_field,
                                  headless=args.headless, verbose=True)
                png = got.get(args.owner) or cached_shot(args.owner)
        if png is None:
            png = capture(args.owner, out_dir=out_dir,
                          filter_field=args.filter_field,
                          no_filter=args.no_filter, headless=args.headless,
                          verbose=True)
    except Exception as e:  # noqa: BLE001
        print(f"✗ capture failed: {type(e).__name__}: {e}")
        return 1
    if png is None:
        print(f"✗ no shot produced for {args.owner!r}")
        return 1
    print(f"✓ captured: {png}  ({png.stat().st_size // 1024} KB)", flush=True)

    # Preview DM — image goes to one person, never a channel.
    if args.dm:
        from automations.shared.slack_metrics_post import (
            dm_user_with_file, SlackPostError)
        try:
            # as_bot=False → the per-user metrics token (SLACK_USER_TOKEN, the
            # xoxp Lucy token every metric already posts with). The bot token
            # isn't configured on the mini, so the default as_bot=True failed.
            dm_user_with_file(png, user=args.dm, as_bot=False,
                              comment=f"📸 Preview — {label} (scope: {scope})",
                              file_name=f"{label}.png")
            print(f"  ✓ Slack: DM'd preview to {args.dm}")
        except SlackPostError as e:
            print(f"✗ preview DM failed: {e}")
            return 1
        print("=== done ===")
        return 0

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
            react_emoji="camera_with_flash", file_name=f"{label}.png")
        print("  ✓ Slack: posted Tableau Metrics screenshot")
    except SlackPostError as e:
        print(f"✗ Slack post failed: {e}")
        return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
