"""B2B Churn for Carlos — fills 'Lucy New INT Churn' + 'Lucy Wireless Churn'.

Megan 2026-07-19: the two churn tabs "should act like the metrics report one we
do for the fiber d2d offices". So this reuses that machinery wholesale rather
than reimplementing it — new_internet_churn.fill is a 1,890-line, label-driven,
four-section filler that already inserts a dated column pair each morning,
adds missing reps, sorts, colours, and hides dark reps. None of that is
rewritten here.

WHAT IS ACTUALLY B2B-SPECIFIC, and all of it is config or the header adapter:

  * the views      — ATTTRACKER-B2B/CHURNRATES custom views CarloWireless and
                     CarlosNewINT (Megan-supplied). They must be pulled through
                     the CROSSTAB DIALOG: the direct .csv ignores custom views
                     entirely, and since the export carries no product column,
                     the wireless/new-internet split exists ONLY in the view's
                     own filter.
  * the header     — churn_shape.adapt(); see that module. A rename, not a
                     reshape.
  * the tabs       — CHURN_NI_TAB / CHURN_WL_TAB
  * the workbook   — CHURN_SHEET_ID (the Vantura Master Sales Board)
  * the owner      — CHURN_SLICE_OWNER=CARLOS HIDALGO

RUNS ON LUCY 2 (Carlos's Tableau identity — these are his custom views).

DRY-RUN BY DEFAULT. --fill writes the tabs. Slack posting is deliberately NOT
wired here: the B2B thread is assembled separately and stays gated.

    python -m automations.att_order_log.churn_run                # pull + report
    python -m automations.att_order_log.churn_run --fill         # write tabs
    python -m automations.att_order_log.churn_run --only wireless
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master Sales Board
OWNER = "CARLOS HIDALGO"
CROSSTAB_SHEET = "ICD Churn"

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = REPO_ROOT / "output" / "att_churn"

# One row per feed. Mirrors office_metrics/offices.py: everything that differs
# between the two lives here and nowhere else.
FEEDS = {
    "new_int": {
        "label": "New Internet Churn",
        "tab": "Lucy New INT Churn",
        "tab_env": "CHURN_NI_TAB",
        "url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER-B2B/CHURNRATES/"
                "ae1e808c-0fa1-4385-8657-9d59c3c02813/CarlosNewINT?:iid=1"),
    },
    "wireless": {
        "label": "Wireless Churn",
        "tab": "Lucy Wireless Churn",
        "tab_env": "CHURN_WL_TAB",
        # NB "CarloWireless" — no 's'. Upstream spelling; it is a URL path
        # segment, so "fixing" it 404s.
        "url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER-B2B/CHURNRATES/"
                "1767636f-875a-40ac-ad39-a42cb894e428/CarloWireless?:iid=1"),
    },
    # AIR added 2026-07-20. Carlos: "INT and AIR are looked at as separate
    # products on B2B" and "yes" to a dedicated AIR churn tab. He saved the
    # CarlosAIREXP view (Megan supplied the URL); scaffold tab "Lucy AIR Churn"
    # already exists with AIR CHURN section labels, which find_sections matches
    # the same as the other two (it keys off "CHURN" + "DAY", not the product).
    "air": {
        "label": "AIR Churn",
        "tab": "Lucy AIR Churn",
        "tab_env": "CHURN_AIR_TAB",
        "url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                "ATTTRACKER-B2B/CHURNRATES/"
                "ff3a70e2-872e-47cc-847b-6222f87bba26/CarlosAIREXP?:iid=1"),
    },
}


def _pull_and_adapt(page, key: str, spec: dict, log=print) -> Path:
    """Crosstab-download one view and rename its header to D2D naming."""
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    from . import churn_shape

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    raw = WORK_DIR / "{}_raw.csv".format(key)
    adapted = WORK_DIR / "{}_adapted.csv".format(key)

    log("  [{}] crosstab download…".format(key))
    drive_crosstab_dialog(page, spec["url"], CROSSTAB_SHEET, raw, verbose=False)
    info = churn_shape.adapt(raw, adapted)
    log("  [{}] {} rows; periods {}".format(
        key, info["rows"], info["periods"]))
    return adapted


def _parse(adapted: Path, log=print) -> dict:
    """Parse via the D2D parser, sliced to Carlos.

    CHURN_SLICE_OWNER is set around the call rather than globally so this can
    never leak into another module's environment mid-process.
    """
    from automations.new_internet_churn import pull as ni_pull

    prev = os.environ.get("CHURN_SLICE_OWNER")
    os.environ["CHURN_SLICE_OWNER"] = OWNER
    try:
        parsed = ni_pull.parse(adapted)
    finally:
        if prev is None:
            os.environ.pop("CHURN_SLICE_OWNER", None)
        else:
            os.environ["CHURN_SLICE_OWNER"] = prev

    reps = parsed.get("reps") or {}
    if not reps:
        # The D2D parser returns an empty dict rather than raising when it
        # cannot find its columns. Left alone that fills nothing and reports
        # success, so turn it into a hard failure here.
        raise RuntimeError(
            "parsed 0 reps for {!r} — the crosstab schema moved, or the owner "
            "slice matched nothing.".format(OWNER))
    log("  parsed {} reps; office total periods {}".format(
        len(reps), sorted((parsed.get("office_total") or {}).keys())))
    return parsed


def _fill(key: str, spec: dict, parsed: dict, today: dt.date, log=print) -> None:
    """Write one tab through the D2D fill, pointed at Carlos's board.

    Targets the board by SETTING THE MODULE'S CONSTANTS DIRECTLY rather than via
    env-then-reload. The old path set os.environ + importlib.reload and trusted
    the module to re-read at reload time; that is exactly the kind of implicit
    coupling that fails silently, and all three feeds sat unfilled through
    several runs. Setting the two attributes the fill actually reads
    (SHEET_ID, TAB_LOCAL_OFFICE) leaves no room for a reload to be skipped or
    for import order to matter. One shared fill module serves all three feeds —
    wireless_churn.fill only re-exports new_internet_churn.fill, so there is no
    per-product code to pick.
    """
    from automations.new_internet_churn import fill as fill_mod

    fill_mod.SHEET_ID = SHEET_ID
    fill_mod.TAB_LOCAL_OFFICE = spec["tab"]

    ws = fill_mod.open_ws()
    sections = fill_mod.find_sections(ws)
    log("  [{}] tab {!r}: {} sections {}".format(
        key, spec["tab"], len(sections), sorted(sections)))
    if not sections:
        raise RuntimeError(
            "no churn sections found in {!r} — the scaffold's column-A labels "
            "do not match (expected '... 0-30 DAYS' etc.)".format(spec["tab"]))

    if fill_mod.today_already_filled(ws, sections, today):
        log("  [{}] today's column is already present — skipping".format(key))
        return
    fill_mod.insert_two_cols_at_b(ws, sections)
    sections = fill_mod.find_sections(ws)
    fill_mod.insert_missing_reps(ws, sections, parsed)
    sections = fill_mod.find_sections(ws)
    fill_mod.write_today(ws, sections, parsed, today)
    log("  [{}] wrote {}".format(key, fill_mod._date_label(today)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log.churn_run")
    ap.add_argument("--fill", action="store_true",
                    help="write the tabs (default: pull + report only)")
    ap.add_argument("--only", choices=sorted(FEEDS), default=None)
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    args = ap.parse_args(argv)

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    feeds = {args.only: FEEDS[args.only]} if args.only else FEEDS
    log = print
    log("B2B Churn (Carlos) — {}".format(today))

    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    rc = 0
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

            for key, spec in feeds.items():
                log("")
                log("--- {} ---".format(spec["label"]))
                try:
                    adapted = _pull_and_adapt(page, key, spec, log=log)
                    parsed = _parse(adapted, log=log)
                    if args.fill:
                        _fill(key, spec, parsed, today, log=log)
                    else:
                        log("  DRY RUN — not writing {!r}".format(spec["tab"]))
                except Exception:  # noqa: BLE001 — one feed must not kill the other
                    rc = 1
                    log("  FAILED:")
                    for ln in traceback.format_exc().splitlines()[-12:]:
                        log("    " + ln[:200])
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
