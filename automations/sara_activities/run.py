"""SARA+ CC -- Raf's SaraPlus Activities onto the 'SARA+ CC' tab.

WHAT (Raf Loom 2026-11-23): every record keyed into the tablet -- in practice
every credit check, pending or not -- lands on the 'SARA+ CC' tab of 'All in
One Local Office - Raf', with the SPM/NG Order ID, so the office can give
AT&T/SCI feedback on the SARA+ site even for orders that never went through.

WHEN: every ~15 minutes of the selling day, as a step at the end of the
Alphalete Sales Board sweep on Lucy 1 (`maybe_run`). It has to ride that
sweep: it is the SAME SaraPlus login, and SaraPlus allows "only one login at
a time" -- a second job on its own clock (or on another Lucy) would bounce the
board's session. Inside the sweep's lock they take turns.

By hand (on Lucy 1 -- never from a laptop, for the same reason):
    python -m automations.sara_activities.run --dry-run        # read, print, write nothing
    python -m automations.sara_activities.run --sandbox        # write the SANDBOX tab
    python -m automations.sara_activities.run --live           # write 'SARA+ CC'
    python -m automations.sara_activities.run --probe --dry-run   # + dump the page

Writes: inserts new Order IDs at row 2 (newest first) and fills BLANK TIME
cells. Never deletes, never overwrites a filled cell, never touches NOTES.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from typing import Optional

from automations.sara_activities import config as C
from automations.sara_activities import read as R
from automations.sara_activities import sheet as SH


def _log(msg: str = "") -> None:
    print("[sara_activities] %s" % msg, flush=True)


# --- state: when did the last pull happen -----------------------------------
def _load_state() -> dict:
    try:
        return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(data: dict) -> None:
    try:
        C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        C.STATE_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def due(now: Optional[float] = None, state: Optional[dict] = None) -> bool:
    now = time.time() if now is None else now
    st = _load_state() if state is None else state
    last = float(st.get("last_try_ts") or 0)
    # 30s of slack so a 15-minute interval on a 5-minute tick lands every
    # third tick instead of every fourth.
    return now - last >= C.INTERVAL_MIN * 60 - 30


# --- the pieces --------------------------------------------------------------
def pull(start: dt.date, end: dt.date, *, headless: bool = True,
         probe: bool = False, log=_log):
    """Log in (Raf's SaraPlus, the Sales Board's profile) and read Activities."""
    from patchright.sync_api import sync_playwright
    from automations.alphalete_sales_board import sara as BOARD_SARA

    with sync_playwright() as p:
        ctx, page, base = BOARD_SARA._open_and_login(p, headless=headless, log=log)
        try:
            headers, rows, how = R.read_range(page, base, start, end,
                                              log=log, probe=probe)
        finally:
            ctx.close()
    recs = SH.records_from_table(headers, rows)
    log("read %d record(s) %s..%s from the %s" % (len(recs), start, end, how))
    return recs


def _open_tab(tab: str, *, create_sandbox: bool):
    from automations.recruiting_report.fill import _client
    book = _client().open_by_key(C.WORKBOOK_ID)
    titles = {ws.title: ws for ws in book.worksheets()}
    if tab in titles:
        return titles[tab]
    if tab == C.SANDBOX_TAB and create_sandbox and C.LIVE_TAB in titles:
        live = titles[C.LIVE_TAB]
        _log("creating %r as a copy of %r" % (tab, C.LIVE_TAB))
        return book.duplicate_sheet(live.id, new_sheet_name=tab,
                                    insert_sheet_index=len(titles))
    raise RuntimeError("no %r tab on 'All in One Local Office - Raf' -- "
                       "nothing written" % tab)


def write(records, tab: str, *, apply_writes: bool, log=_log) -> int:
    ws = _open_tab(tab, create_sandbox=apply_writes)
    existing = ws.get_all_values()
    new_rows, fills = SH.plan(existing, records, C.COLUMN_SOURCE,
                              C.TIME_HEADER, C.KEY_HEADER)
    log("%r: %d row(s) on the tab, %d new order(s), %d blank TIME cell(s) to fill"
        % (tab, len(existing) - 1, len(new_rows), len(fills)))
    for r in new_rows[:8]:
        log("   + %s" % " | ".join(c for c in r if c))
    if len(new_rows) > 8:
        log("   + ... %d more" % (len(new_rows) - 8))
    if not apply_writes:
        log("PREVIEW -- nothing written")
        return len(new_rows)
    if new_rows:
        ws.insert_rows(new_rows, row=2, value_input_option="RAW")
    if fills:
        from gspread.utils import rowcol_to_a1
        shift = len(new_rows)
        ws.batch_update([{"range": rowcol_to_a1(r + shift, c), "values": [[v]]}
                         for r, c, v in fills], value_input_option="RAW")
    log("wrote %d new row(s), %d TIME cell(s)" % (len(new_rows), len(fills)))
    return len(new_rows)


def run_once(*, tab: str, apply_writes: bool, headless: bool = True,
             probe: bool = False, day: Optional[dt.date] = None,
             log=_log) -> int:
    end = day or dt.date.today()
    start = end - dt.timedelta(days=C.DAYS_BACK)
    st = _load_state()
    st["last_try_ts"] = time.time()
    _save_state(st)
    recs = pull(start, end, headless=headless, probe=probe, log=log)
    n = write(recs, tab, apply_writes=apply_writes, log=log)
    if apply_writes:
        st = _load_state()
        st["last_ok_ts"] = time.time()
        st["last_ok_new"] = n
        _save_state(st)
    return n


def maybe_run(*, headless: bool = True, log=_log) -> None:
    """The Sales Board sweep's step. Called INSIDE its lock, after the board
    is written, so a SaraPlus hiccup here can never cost the board its tick.
    Never raises."""
    if not due():
        return
    try:
        run_once(tab=C.TARGET_TAB, apply_writes=True, headless=headless, log=log)
    except Exception as e:  # noqa: BLE001
        log("FAILED (board unaffected): %s: %s" % (type(e).__name__, str(e)[:300]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--sandbox", action="store_true",
                       help="write %r (created from the real tab if missing)" % C.SANDBOX_TAB)
    where.add_argument("--live", action="store_true", help="write %r" % C.LIVE_TAB)
    ap.add_argument("--dry-run", action="store_true",
                    help="read and print, write nothing (the default without --sandbox/--live)")
    ap.add_argument("--probe", action="store_true",
                    help="also dump the page's controls at each step")
    ap.add_argument("--date", help="YYYY-MM-DD end of the range (default today)")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)

    tab = C.LIVE_TAB if args.live else C.SANDBOX_TAB
    apply_writes = (args.sandbox or args.live) and not args.dry_run
    day = dt.datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None

    # Same lock as the Sales Board sweep: one SaraPlus login at a time.
    from automations.alphalete_sales_board.run import Lock
    with Lock() as lock:
        if not lock.held:
            _log("the Sales Board sweep is running -- try again in a minute")
            return 75
        try:
            run_once(tab=tab, apply_writes=apply_writes, headless=not args.headed,
                     probe=args.probe, day=day)
        except Exception as e:  # noqa: BLE001
            _log("FAILED: %s: %s" % (type(e).__name__, str(e)[:500]))
            return 1
    _log("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
