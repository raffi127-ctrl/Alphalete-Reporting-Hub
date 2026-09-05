"""By-rep Activation + Churn boards for the B2B Metrics thread (Carlos
2026-09-05).

THE ASK, in Carlos's words: the Activation-by-Rep screenshot gains the 31-60
day rate next to 0-30, both with a TOTAL column for the office; and a NEW
churn screenshot in the same style — one column per churn bucket (0-30 / 30 /
60 / 90 / 120 day), rows = ACTIVE reps only, with the office total row being
the TRUE office total (every rep, gone ones included), never just the sum of
the active rows shown.

BUILD ORDER (same discipline as activation_rates.py 2026-07-19: real exports
before parsers): `--probe` opens the CHURNRATES rep view under Carlos's
identity, enumerates its worksheets, downloads each and reports columns +
row shapes into the 'B2B Diag' tab for the mini to read. The parser and the
HTML->PNG renderer get written against that output, not against a guess.

  lucy rerun b2b_rep_boards -- --probe          # geometry probe (read-only)
"""
from __future__ import annotations

import argparse
import sys
import time

# Carlos's EXPANDED churn view — the one whose 'Churn Rates Owner (+/-) Rep'
# table the thread screenshots; its crosstab should carry the Rep dimension.
CHURN_VIEW = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "ATTTRACKER-B2B/CHURNRATES/7419b960-0fb1-41d5-a11e-76f0e81c0547/"
    "CarlosLocalOfficeEXPANDEDCHURN")
DIAG_TAB = "B2B Diag"


def _upload_diag(lines) -> None:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(
        "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
    try:
        t = sh.worksheet(DIAG_TAB)
    except Exception:  # noqa: BLE001
        t = sh.add_worksheet(title=DIAG_TAB, rows=400, cols=1)
    t.clear()
    t.update([[ln[:4900]] for ln in lines][:400], "A1")


def probe(argv_url: str = "") -> int:
    from patchright.sync_api import sync_playwright
    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull
    from automations.vantura_churn import activation_rates as ar

    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(str(msg))

    url = argv_url or CHURN_VIEW
    with cdp_pull._cdp_lock(label="b2b rep_boards probe", log=log):
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
                    except Exception:  # noqa: BLE001
                        if attempt == 9:
                            raise
                ctx = (browser.contexts[0] if browser.contexts
                       else browser.new_context())
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                ar.probe_view(page, url, log=log)
        finally:
            cdp_pull._kill_ours()
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
    _upload_diag(lines)
    print("probe output -> sheet tab {!r} ({} line(s))".format(
        DIAG_TAB, len(lines)), flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_metrics.rep_boards")
    ap.add_argument("--probe", action="store_true",
                    help="enumerate + download the churn view's worksheets; "
                         "geometry to the B2B Diag tab (read-only)")
    ap.add_argument("--url", default="",
                    help="probe a different view URL")
    args = ap.parse_args(argv)
    if args.probe:
        return probe(args.url)
    ap.error("only --probe is implemented so far — the render modes get "
             "written against the probe's output")
    return 2


if __name__ == "__main__":
    sys.exit(main())
