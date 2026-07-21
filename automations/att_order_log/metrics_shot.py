"""📸 B2B AT&T Sales Metrics — Carlos's Tableau screenshot.

Carlos (Loom 3:39-5:48): "this Tableau metrics, if I can get mine posted. Mine
is up here. It's called the B2B AT&T sales metrics… if that could just get
screenshotted just so we could also see the activation rate and the churn rate
all in one screenshot."

An IMAGE metric, like the D2D office_metrics.metrics_shot: no crosstab parse,
capture the view and post the picture. Uses the same Download → Image machinery
as tableau_screenshots / b2b_quality (NOT a page screenshot, which drags in
browser chrome and clips).

SCOPED VIA CARLOS'S OWN CUSTOM VIEW (Carlos-ExpandedMetrics), not a URL filter.
Carlos (Loom 5:00) said the all-teams view has "no filter for it, or by the
owner" and his workaround was POSITIONAL — "I'm like 21… my name would need to
get lined up with the third row." We never implemented that: a fixed-row crop
breaks the week his rank moves, since the view is ranked. Instead Megan saved a
team-scoped custom view (2026-07-20); filtered to his team it is ~9 reps, so his
metrics row and the Activation & Churn panel land in one frame naturally. The
URL-FILTER path (FILTER_FIELD below) stays wired but unused — a fallback if the
custom view is ever unavailable and a real owner filter has appeared by then.

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

# Wired but UNUSED until the field exists. Tableau URL-filters on a filter's
# DISPLAY CAPTION, so this is a guess at the caption the B2B view will use once
# the owner filter is added; confirm live before switching it on.
FILTER_FIELD = os.environ.get("ATT_METRICS_FILTER_FIELD", "")
OWNER = os.environ.get("ATT_METRICS_OWNER", "CARLOS HIDALGO")

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "att_metrics_shot"


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
        "url": view_url(),
    }
    return capture_page(page, spec, out_dir, verbose=verbose)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log.metrics_shot")
    ap.add_argument("--out", default=None, help="output directory")
    args = ap.parse_args(argv)
    out_dir = Path(args.out) if args.out else OUT_DIR

    log = print
    log("B2B AT&T Sales Metrics shot — {}".format(dt.date.today()))
    log("  view: {}".format(view_url()))
    if not FILTER_FIELD.strip():
        log("  NOTE: no owner filter applied — the field does not exist yet "
            "(Carlos, Loom 5:00). Capturing the full all-teams view, which "
            "does contain his row and the Activation & Churn panel.")

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
