"""Run Carlos's B2B Ongoing Cancels -> the 'Lucy Cancel Rates' tab.

    python -m automations.att_order_log.cancels_run            # pull + report
    python -m automations.att_order_log.cancels_run --sheet    # write the tab

DRY-RUN BY DEFAULT. RUNS ON LUCY 2 (Carlos's Tableau identity — CarlosLOExpCancels
is his custom view). Posts nothing.

WEEKLY, not daily — see cancels.py. Carlos pointed at Raf's DAILY ongoing-cancel
screenshot, but his own view reports by week ending. Megan 2026-07-20: build it
weekly, she will check with Carlos.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = REPO_ROOT / "output" / "att_cancels"


def _pull(page, log=print) -> Path:
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog

    from . import cancels

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    out = WORK_DIR / "cancels_{}.csv".format(dt.date.today().isoformat())
    log("  crosstab download ({})…".format(cancels.CROSSTAB_SHEET))
    drive_crosstab_dialog(page, cancels.VIEW_URL, cancels.CROSSTAB_SHEET, out,
                          verbose=False)
    return out


def _write(parsed, generated: str, log=print) -> dict:
    """Write the tab. Creates it if absent — unlike the churn scaffolds and the
    order-log tab, Megan has not pre-made this one."""
    from automations.recruiting_report.fill import _retry

    from . import cancels, sheet as _sheet

    if cancels.TAB in _sheet.PROTECTED_TABS:
        raise RuntimeError("refusing to write: {!r} is protected".format(
            cancels.TAB))

    grid = cancels.build_grid(parsed, generated)
    ncol = max(len(r) for r in grid)
    grid = [list(r) + [""] * (ncol - len(r)) for r in grid]

    sh = _sheet._open()
    ws = _sheet._ensure_tab(sh, cancels.TAB, rows=max(200, len(grid) + 40),
                            cols=max(12, ncol + 2))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(
        grid, "A1:{}{}".format(_sheet._col_letter(ncol - 1), len(grid)),
        value_input_option="USER_ENTERED"))

    # Same palette as the order log so Carlos's tabs read as one family.
    reqs = [
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _sheet._rgb(_sheet.NAVY),
                "textFormat": {"bold": True, "fontSize": 13,
                               "foregroundColor": _sheet._rgb("#FFFFFF")}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.textFormat")}},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": 2,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "textFormat": {"italic": True, "fontSize": 9,
                               "foregroundColor": _sheet._rgb(_sheet.MUTED)}}},
            "fields": "userEnteredFormat.textFormat"}},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 2, "endRowIndex": 4,
                      "startColumnIndex": 0, "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _sheet._rgb(_sheet.SLATE),
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "fontSize": 10,
                               "foregroundColor": _sheet._rgb(_sheet.INK)}}},
            "fields": ("userEnteredFormat.backgroundColor,"
                       "userEnteredFormat.horizontalAlignment,"
                       "userEnteredFormat.textFormat")}},
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id,
                           "gridProperties": {"frozenRowCount": 4,
                                              "frozenColumnCount": 1}},
            "fields": ("gridProperties.frozenRowCount,"
                       "gridProperties.frozenColumnCount")}},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": ws.id, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": ncol}}},
    ]
    _retry(lambda: sh.batch_update({"requests": reqs}))
    return {"tab": cancels.TAB, "rows": len(grid), "cols": ncol}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log.cancels_run")
    ap.add_argument("--sheet", action="store_true",
                    help="write the tab (default: pull + report only)")
    ap.add_argument("--from-file", default=None, metavar="CSV")
    args = ap.parse_args(argv)

    log = print
    generated = dt.datetime.now().strftime("%m/%d/%Y %I:%M %p").lstrip("0")
    log("B2B Ongoing Cancels (Carlos) — weekly — {}".format(dt.date.today()))

    from . import cancels, churn_shape

    try:
        if args.from_file:
            path = Path(args.from_file)
            log("  reading {}".format(path))
            grid = churn_shape.read_crosstab(path)
        else:
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
                    ctx = (browser.contexts[0] if browser.contexts
                           else browser.new_context())
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    tp._ensure_tableau_authenticated(page, verbose=False,
                                                     allow_form_login=True)
                    log("  [cdp] auth OK")
                    path = _pull(page, log=log)
                grid = churn_shape.read_crosstab(path)
            finally:
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                cdp_pull._kill_ours()

        parsed = cancels.parse(grid)
        s = cancels.summary(parsed)
        log("  {} reps across {} weeks; newest {}".format(
            s["reps"], s["weeks"], s["newest_week"]))
        log("  {} rep(s) with cancels in the newest week".format(
            s["with_cancels"]))
        for rep, v in s["worst"]:
            log("    {:>6.1%}  {}".format(v, rep))

        if not args.sheet:
            log("")
            log("  DRY RUN — not writing {!r}".format(cancels.TAB))
            return 0
        res = _write(parsed, generated, log=log)
        log("  wrote {tab}: {rows} rows x {cols} cols".format(**res))
        return 0
    except Exception:  # noqa: BLE001
        log("")
        log("FAILED:")
        for ln in traceback.format_exc().splitlines()[-14:]:
            log("  " + ln[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
