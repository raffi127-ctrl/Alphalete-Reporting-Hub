"""Daily NDS Sales Board shots for the NDS Metrics thread (Carlos 2026-10-28).

Two images every morning, both off a temp copy of the NDS Sales Board:

  * DAY   — REP + yesterday's day column only. Reps whose day cell is X
            (didn't work), F or T (terminated) or blank are filtered OUT;
            everyone with a number stays, zeros included. Sorted highest
            to lowest. ("the people marked 'X' are filtered out. if anyone
            is marked 'f' or 't' they would also be filtered out")
  * WEEK  — REP | Current Week | Last Wk | Monday..yesterday ("the whole
            week up until the day prior. so if today was friday it would
            show up until thursday"), same filtered roster, sorted by
            Current Week highest to lowest.

Both end on the campaign totals row. Monday runs before the 8:20 week
roll, so Monday's shots show the closing week through Sunday — which is
exactly "the day prior".
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

TEMP_TAB = "_nds_shots_tmp"
_MEMO: dict = {}


def render(today: dt.date, out_dir: Path, log=print) -> dict:
    """{'day': Path, 'week': Path} for `today`, built once per process."""
    if _MEMO.get("day") == today.isoformat():
        return _MEMO["paths"]
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R
    from automations.sales_boards.run import SHEET_ID

    yday = today - dt.timedelta(days=1)
    sh = open_by_key(SHEET_ID)
    src = sh.worksheet("NDS Sales Board")
    token = _token()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = sh.duplicate_sheet(src.id, new_sheet_name=TEMP_TAB)
    try:
        sh.batch_update({"requests": [
            {"clearBasicFilter": {"sheetId": tmp.id}}]})
        g = _retry(tmp.get_all_values)
        ts, _te = R.totals_range(g)
        first, last = R.rep_region(g, ts)
        dayname = yday.strftime("%A")
        dcol = R.day_column(g, dayname)
        if dcol is None:
            raise RuntimeError(f"no {dayname!r} column on the board")
        gid, width = tmp.id, tmp.col_count

        def keep_rows(grid):
            return {r for r in range(first, last + 1)
                    if R.as_int(R.cell(grid, r, dcol)) is not None}

        # ---------- DAY: REP + yesterday, day desc --------------------
        R.sort_region(sh, gid, first, last,
                      [(dcol, False), (R.NAME_COL, True)], width)
        g = _retry(tmp.get_all_values)
        keep = keep_rows(g)
        if not keep:
            raise RuntimeError(f"no numeric {dayname} cells — board not "
                               "filled yet")
        hide_r = [r for r in range(first, last + 1) if r not in keep]
        R.set_rows_hidden(sh, gid, hide_r, True)
        day_letter = __import__("gspread").utils.rowcol_to_a1(1, dcol)[:-1]
        hide_c = [c for c in range(R.CURRENT_WEEK_COL, R.LAST_DAY_COL + 1)
                  if c != dcol]
        R.set_cols_hidden(sh, gid, hide_c, True)
        img = R.export(SHEET_ID, gid,
                       f"B{R.DAY_HEADER_ROW}:{day_letter}{ts}", token)
        day_png = out_dir / f"nds_day_board_{today.isoformat()}.png"
        R.stitch([R.title_bar(
            img.width, f"NDS — {dayname} {yday.month}/{yday.day}"),
            img]).save(day_png)
        log(f"[nds] day board: {len(keep)} rep(s), {dayname} {yday}")
        R.set_cols_hidden(sh, gid, hide_c, False)
        R.set_rows_hidden(sh, gid, hide_r, False)
        time.sleep(1.2)

        # ---------- WEEK: through yesterday, Current Week desc --------
        R.sort_region(sh, gid, first, last,
                      [(R.CURRENT_WEEK_COL, False), (R.NAME_COL, True)],
                      width)
        g = _retry(tmp.get_all_values)
        keep = keep_rows(g)
        hide_r = [r for r in range(first, last + 1) if r not in keep]
        R.set_rows_hidden(sh, gid, hide_r, True)
        hide_c = [c for c in range(dcol + 1, R.LAST_DAY_COL + 1)]
        R.set_cols_hidden(sh, gid, hide_c, True)
        img = R.export(SHEET_ID, gid,
                       f"B{R.DAY_HEADER_ROW}:{day_letter}{ts}", token)
        week_png = out_dir / f"nds_week_board_{today.isoformat()}.png"
        R.stitch([R.title_bar(
            img.width, f"NDS — Week to Date (through {dayname})"),
            img]).save(week_png)
        log(f"[nds] week board: {len(keep)} rep(s), Mon..{dayname}")
    finally:
        sh.del_worksheet(tmp)
    paths = {"day": day_png, "week": week_png}
    _MEMO.update(day=today.isoformat(), paths=paths)
    return paths
