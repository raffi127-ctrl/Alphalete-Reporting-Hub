"""📸 B2B AT&T Sales Metrics — Carlos's Tableau screenshot.

Carlos (Loom 3:39-5:48): "this Tableau metrics, if I can get mine posted. Mine
is up here. It's called the B2B AT&T sales metrics… if that could just get
screenshotted just so we could also see the activation rate and the churn rate
all in one screenshot."

An IMAGE metric, like the D2D office_metrics.metrics_shot: no crosstab parse,
capture the view and post the picture. Uses the same Download → Image machinery
as tableau_screenshots / b2b_quality (NOT a page screenshot, which drags in
browser chrome and clips).

SCOPED TWO WAYS, both needed (proven 2026-07-20, Megan: "It's perfect"):
  1. Carlos's saved custom view (Carlos-ExpandedMetrics) scopes the LEFT metrics
     table to his team.
  2. A URL filter ?Owner Name=Carlos Hidalgo scopes the RIGHT Activation & Churn
     panel, which groups by Owner Name and ignores the custom view's team
     filter. This is NOT a Tableau edit — nothing is saved, it is only how the
     view is requested — so it stays within Megan's "can't adjust Tableau".
Together, both panels show only Carlos's ~9 reps in one frame — exactly his
Loom ask ("activation rate and churn rate all in one screenshot"), with no
positional crop (which would break the week his tracker rank moves).

RUNS ON LUCY 2 — Carlos's Tableau identity; his custom views only carry his
sort/filters under his login (the lesson b2b_quality records at length).

    python -m automations.att_order_log.metrics_shot            # capture only
    python -m automations.att_order_log.metrics_shot --open     # + reveal path
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"

# Carlos's OWN custom view of the metrics dashboard (Megan-supplied 2026-07-20),
# scoped to his team. This is the real fix for his Loom ask, not a workaround:
# he wanted "activation rate and churn rate all in one screenshot" and his row
# "lined up with the third row" because the all-teams view ranks him ~21st, far
# from the Activation & Churn panel. Filtered to his team the dashboard drops to
# ~9 reps, so the metrics table and the Activation & Churn panel sit together in
# one frame — no positional crop (which would break the week his rank moves),
# no dependence on an owner filter that doesn't exist yet.
#
# CUSTOM VIEW => LUCY 2 ONLY: it carries its owner's filters/sort under its
# owner's (Carlos's) login; under Raf's it renders as a different slice.
VIEW_URL = os.environ.get("ATT_METRICS_VIEW_URL") or (
    _BASE + "ATTTRACKER-B2B/B2BATTSalesMetrics/"
    "eed37ad3-2bde-430e-9126-b1def96be8d3/Carlos-ExpandedMetrics?:iid=1")

# PROVEN 2026-07-20 (Megan: "It's perfect"). The saved custom view scopes only
# the LEFT metrics table to Carlos's team; the right Activation & Churn panel
# groups by "Owner Name" and ignores that team filter. Appending
# ?Owner Name=Carlos Hidalgo as a URL filter scopes the WHOLE dashboard — both
# panels — with no Tableau edit (nothing saved; just how the view is requested).
# So this is now the DEFAULT, not a fallback. Value is the person-name form the
# panel's Owner Name filter uses (verified live). Override via env if the view's
# filter caption or the owner string ever changes.
FILTER_FIELD = os.environ.get("ATT_METRICS_FILTER_FIELD", "Owner Name")
OWNER = os.environ.get("ATT_METRICS_OWNER", "Carlos Hidalgo")

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "att_metrics_shot"

# Per-run URL, set by main() (default view, or a --filter-field experiment).
_RUN_URL = None


def view_url_with(field: str, owner: str) -> str:
    """The view URL with an EXPLICIT owner filter appended — used to try
    scoping the Activation & Churn panel (which the saved custom view does NOT
    scope) via a URL filter, no Tableau edit needed. Tableau URL-filters on the
    filter's DISPLAY CAPTION, so `field` is that caption."""
    base = VIEW_URL.split("?")[0]
    if not field.strip():
        return VIEW_URL
    return "{}?{}={}".format(base, quote(field.strip()), quote(owner))


def view_url() -> str:
    """The view, plus an owner filter IF one has been configured.

    Empty FILTER_FIELD => no filter appended, i.e. the all-teams view. That is
    the current state and it is intentional: an unfiltered-but-complete shot is
    correct, where a filter on a guessed caption would silently return an EMPTY
    view (Tableau ignores unknown filter fields rather than erroring), and an
    empty screenshot posted daily is exactly the kind of quiet wrong this build
    keeps running into.
    """
    if not FILTER_FIELD.strip():
        return VIEW_URL
    base = VIEW_URL.split("?")[0]
    return "{}?{}={}".format(base, quote(FILTER_FIELD.strip()),
                             quote(OWNER))


def capture(page, out_dir: Path = OUT_DIR, verbose: bool = True) -> Path:
    """Download → Image of the metrics view."""
    from automations.tableau_screenshots.capture import capture_page

    out_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "id": "b2b_att_sales_metrics",
        "title": "B2B ATT Sales Metrics {}".format(
            dt.date.today().strftime("%-m.%-d") if os.name != "nt"
            else dt.date.today().strftime("%m.%d")),
        "url": _RUN_URL or view_url(),
    }
    return capture_page(page, spec, out_dir, verbose=verbose)


def _dm_preview(png: Path, user: str, log=print) -> None:
    """DM the captured image to ONE person for review. Rejects channel ids so a
    preview can never become a channel post (same guard as thread.dm_preview)."""
    from automations.shared import slack_metrics_post as smp
    u = (user or "").strip()
    if not u.upper().startswith("U"):
        raise ValueError(
            "refusing: {!r} is not a user id — preview DMs an individual, "
            "channel ids (C…/G…) are rejected".format(u))
    smp.dm_user_with_file(
        png, user=u, file_name=png.name,
        comment="B2B AT&T Sales Metrics — Carlos-ExpandedMetrics view. "
                "Preview, not posted anywhere.")
    log("  DM'd preview to {}".format(u))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log.metrics_shot")
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--dm", default=None, metavar="USER_ID",
                    help="DM the captured image to ONE user (U…) for review")
    ap.add_argument("--filter-field", default=None, metavar="CAPTION",
                    help="append ?<CAPTION>=<owner> to scope the whole "
                         "dashboard (incl. the Activation & Churn panel) via a "
                         "URL filter — no Tableau edit. Experimental.")
    ap.add_argument("--owner", default=OWNER,
                    help="owner value for --filter-field (default: {})".format(
                        OWNER))
    args = ap.parse_args(argv)
    out_dir = Path(args.out) if args.out else OUT_DIR

    # Override the module URL for this run if a filter caption is being tried.
    global _RUN_URL
    _RUN_URL = (view_url_with(args.filter_field, args.owner)
                if args.filter_field else view_url())

    log = print
    log("B2B AT&T Sales Metrics shot — {}".format(dt.date.today()))
    log("  view: {}".format(_RUN_URL))
    log("  scope: custom view (left) + Owner Name URL filter (right panel)")

    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    log("  [cdp] real Chrome pid={}; waiting 20s".format(proc.pid))
    time.sleep(20)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            log("  [cdp] auth OK")
            png = capture(page, out_dir=out_dir, verbose=True)
        size_kb = png.stat().st_size // 1024
        log("  wrote {} ({} KB)".format(png, size_kb))
        if size_kb < 20:
            # A near-empty PNG is the signature of a filter that matched
            # nothing or a viz that never hydrated. Say so rather than hand a
            # blank image to the thread builder.
            log("  !! image is suspiciously small — the view may not have "
                "rendered, or a filter matched nothing")
            return 1
        if args.dm:
            _dm_preview(png, args.dm, log=log)
        return 0
    except Exception:  # noqa: BLE001
        log("")
        log("FAILED:")
        for ln in traceback.format_exc().splitlines()[-14:]:
            log("  " + ln[:200])
        return 1
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()


if __name__ == "__main__":
    raise SystemExit(main())
