"""Zero Streak — the escalating 'zeros in a row' callout for the Alphalete
Production post (Raf 2026-07-25), styled + labelled like Carlos's B2B twin
(`automations/sales_boards/zeros.py`): instead of ONE 'Back-to-Back Zeros'
image, post one image per streak depth — 1 Day / 2 Days / 3 Days … — each
listing every rep on a run of that length.

LOOK (Megan 2026-07-25): each image is a reshaped copy of the REAL Sales Board,
so it carries the board's native styling — campaign colouring and the board's
own conditional pink on every `=0` day cell (a NUMBER_EQ 0 rule spanning the day
columns) — with a navy 'Zero Streak: N Days' title bar stitched on top. Columns
mirror the B2B image: # / REP / Current Week / Last Wk / <the N zero days> /
Campaign, grouped by campaign. We do NOT build a synthetic table.

WHAT COUNTS AS A ZERO: a literal numeric 0 for that day ('0'/'0.00'). An 'X'/'F'/
'T' (absent / terminated) or a blank is NOT a zero.

NON-MANDATORY DAYS = SUNDAY **and MONDAY** (Raf 2026-07-25: "Monday isn't
mandatory, keeping the same rules"). Neither is ever the anchor, never counts as
a zero, and never shows as a column — BUT a SALE on either still breaks the run
(same rule the B2B build uses for Sunday). Mandatory selling days are Tue–Sat.

STREAKS CROSS WEEKS — up to MAX_DAYS mandatory days back. The board holds ONE
week per tab, so earlier days come from the PRIOR-week tabs ('Sales Board WE m.d')
— this sheet's history (there is no WeekData tab like B2B has). Reps are matched
across tabs by NORMALIZED name (the '(Wk N)'/'(NC)' suffix increments weekly). A
rep with no row in a past week (a new hire) can't extend past it, which truncates
the streak rather than overstating it.

A cross-week older day is BORROWED onto the copy — its value is written into a
spare day-block column that sits within the board's conditional-format range
(cols 25–80), so a borrowed 0 recolours itself pink exactly like a native cell.

FOLDING: levels are nested (everyone at n+1 is also at n). A level whose roster
is identical to the next-deeper one is folded in — one rep on a 4-day run ships
ONE image, not four. Same as B2B / the VA. The live board is never touched.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

from automations.alphalete_production.capture import (
    SHEET_ID, TMP_TAB as _CAP_TMP, _access_token, _cell, _campaign_col,
    _clean_number_col, _day_block, _hide_cols, _norm_name, _sun_apps_col,
    _totals_row, col_letter, find_week_tab,
)
from automations.recruiting_report.fill import _retry
from automations.sales_boards import render as R   # title_bar / stitch / export

TMP_TAB = "_zeros_streak_tmp"
MAX_DAYS = 7
LOOKBACK_CAL_DAYS = 18
NON_MANDATORY = (0, 6)          # Monday (0) + Sunday (6)
HEADER_ROW = 3                  # 1-based board row we repurpose as the clean header
NAME_COL = 2                    # C
CUR_WEEK_COL = 3                # D — running-week Apps ("Current Week")
NAVY = {"red": 0.18, "green": 0.33, "blue": 0.59}
DAY_ABBR = {0: "MON", 1: "TUES", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}


def is_zero(v) -> bool:
    return bool(re.fullmatch(r"0(\.0+)?", str(v).strip()))


def is_sale(v) -> bool:
    try:
        return float(str(v).strip()) > 0
    except (TypeError, ValueError):
        return False


def anchor_day(yday: dt.date) -> dt.date:
    d = yday
    while d.weekday() in NON_MANDATORY:
        d -= dt.timedelta(days=1)
    return d


def mandatory_days(anchor: dt.date, n: int) -> list:
    out, d = [], anchor
    while len(out) < n:
        if d.weekday() not in NON_MANDATORY:
            out.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(out))


def we_label(d: dt.date) -> str:
    sun = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    return f"{sun.month}.{sun.day}"


def level_label(n: int) -> str:
    return f"{n} Day" if n == 1 else f"{n} Days"


def title_for(n: int, days: list) -> str:
    span = days[-n:]
    end = span[-1]
    if n == 1:
        where = f"{end.strftime('%A')} {end.month}/{end.day}"
    else:
        start = span[0]
        where = (f"{start.strftime('%a')} {start.month}/{start.day} → "
                 f"{end.strftime('%a')} {end.month}/{end.day}")
    return f"Zero Streak: {level_label(n)}  ({where})"


def _lastweek_col(grid) -> int:
    """The Last Week Apps column — the "LAST WEEK'S TOTALS" block-title column IS
    that block's Apps column (mirrors D under "RUNNING WEEK TOTALS"). Found by
    label so a header rename or a column move can't break it."""
    c = next((c for c in range(len(grid[0]))
              if _cell(grid, 0, c).strip().upper().startswith("LAST WEEK")
              and _cell(grid, 2, c).strip().upper() in ("APPS", "TOTAL APPS", "")), None)
    if c is None:
        raise RuntimeError("no LAST WEEK apps column on the board")
    return c


def _first_day_col(grid) -> int:
    return next(c for c in range(len(grid[0]))
                if _cell(grid, 0, c).strip() == "MON"
                and _cell(grid, 2, c).strip().lower() == "apps")


def _load_day_values(ss, dates, cur_ws, cur_grid) -> dict:
    """{date: {norm_name: apps_value}} over a span of CALENDAR dates (Sun+Mon
    included, so a sale on either is visible to the walk). Each week tab read once."""
    cache = {cur_ws.title: cur_grid}
    out = {}
    for d in dates:
        tab = find_week_tab(ss, d)
        grid = cache.get(tab.title)
        if grid is None:
            grid = _retry(tab.get_all_values)
            cache[tab.title] = grid
        try:
            c = _day_block(grid, d)[0]
        except RuntimeError:
            out[d] = {}
            continue
        m = {}
        for r in range(3, len(grid)):
            nm = _cell(grid, r, 2).strip()
            if nm:
                m[_norm_name(nm)] = _cell(grid, r, c).strip()
        out[d] = m
    return out


def _walk_streak(nm: str, anchor: dt.date, values: dict) -> int:
    n, d = 0, anchor
    while n < MAX_DAYS:
        v = values.get(d, {}).get(nm, "")
        if d.weekday() in NON_MANDATORY:
            if is_sale(v):
                break
            d -= dt.timedelta(days=1)
            continue
        if not is_zero(v):
            break
        n += 1
        d -= dt.timedelta(days=1)
    return n


# ---- rendering (reshape the real board, B2B style) -----------------------

def _sweep_temp(ss):
    for w in ss.worksheets():
        if w.title in (TMP_TAB, _CAP_TMP):
            try:
                ss.batch_update({"requests": [{"deleteSheet": {"sheetId": w.id}}]})
            except Exception:      # noqa: BLE001
                pass


def _dup(ss, src_ws):
    rep = ss.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": src_ws.id, "insertSheetIndex": 0,
        "newSheetName": TMP_TAB}}]})
    gid = rep["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
    return next(w for w in ss.worksheets() if w.id == gid), gid


def _hide_rows(ss, gid, rows):
    if rows:
        ss.batch_update({"requests": [{"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "ROWS",
                      "startIndex": r - 1, "endIndex": r},
            "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}}
            for r in rows]})


def _day_positions(grid, days, board_we) -> dict:
    """{date: column} for the shown days. Current-week days use their native day
    column; older (cross-week) days get a spare column just left of the earliest
    current-week day — kept inside the board's 0-pinks-itself range (cols 25–80)."""
    current = {d: _day_block(grid, d)[0] for d in days if we_label(d) == board_we}
    older = [d for d in days if we_label(d) != board_we]        # oldest first
    pos = dict(current)
    if older:
        base = min(current.values()) - len(older) if current else _first_day_col(grid)
        for i, d in enumerate(older):
            pos[d] = base + i
    return pos


def _render_level(ss, cur_ws, grid, values, roster, all_names, n, days,
                  board_we, anchor, token, out_dir: Path) -> tuple:
    """Reshape a fresh board copy to the level-n view, export + stitch title bar.
    Returns (path, reps, campaigns)."""
    tot = _totals_row(grid)
    camp_c = _campaign_col(grid)
    lw_c = _lastweek_col(grid)
    ncols = max(len(grid[0]), 110)
    pos = _day_positions(grid, days, board_we)
    ordered = sorted(days)                          # oldest -> newest, left -> right
    day_cols = [pos[d] for d in ordered]
    show = {1, NAME_COL, CUR_WEEK_COL, lw_c, camp_c} | set(day_cols)

    tmp_ws, gid = _dup(ss, cur_ws)
    try:
        # (1) borrow cross-week day values into their spare columns (pre-sort, so
        #     they travel with the row), matched by normalized name.
        borrow = []
        for d in ordered:
            if we_label(d) == board_we:
                continue
            c = pos[d]
            cl = col_letter(c)
            vals = values.get(d, {})
            col = [[vals.get(_norm_name(_cell(grid, r, NAME_COL)), "")]
                   for r in range(3, tot - 1)]       # rows 4..tot-1
            borrow.append({"range": f"{cl}4:{cl}{tot - 1}", "values": col})
        if borrow:
            _retry(lambda: tmp_ws.batch_update(borrow, value_input_option="USER_ENTERED"))

        # (2) clean single header row (row 3), B2B labels, on the shown columns.
        hdr = {1: "#", NAME_COL: "REP", CUR_WEEK_COL: "Current Week",
               lw_c: "Last Wk", camp_c: "Campaign"}
        for d in ordered:
            hdr[pos[d]] = f"{d.strftime('%a')} {d.month}/{d.day}"
        header_writes = [{"range": f"{col_letter(c)}{HEADER_ROW}", "values": [[t]]}
                         for c, t in hdr.items()]
        _retry(lambda: tmp_ws.batch_update(header_writes, value_input_option="RAW"))

        reqs = []
        # unmerge + navy-style the header cells so nothing native bleeds through
        for c in show:
            reqs.append({"unmergeCells": {"range": {
                "sheetId": gid, "startRowIndex": HEADER_ROW - 1, "endRowIndex": HEADER_ROW,
                "startColumnIndex": c, "endColumnIndex": c + 1}}})
            reqs.append({"repeatCell": {"range": {
                "sheetId": gid, "startRowIndex": HEADER_ROW - 1, "endRowIndex": HEADER_ROW,
                "startColumnIndex": c, "endColumnIndex": c + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": NAVY, "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP",
                    "textFormat": {"bold": True, "foregroundColor": {
                        "red": 1, "green": 1, "blue": 1}}}},
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                          "verticalAlignment,wrapStrategy,textFormat)"}})
        reqs += _hide_cols(gid, show, ncols)
        # (3) group by campaign, then rep name — sort the rep region full-width.
        reqs.append({"sortRange": {
            "range": {"sheetId": gid, "startRowIndex": 3, "endRowIndex": tot - 1,
                      "startColumnIndex": 0, "endColumnIndex": ncols},
            "sortSpecs": [{"dimensionIndex": camp_c, "sortOrder": "ASCENDING"},
                          {"dimensionIndex": NAME_COL, "sortOrder": "ASCENDING"}]}})
        ss.batch_update({"requests": reqs})
        time.sleep(1.0)

        # (4) hide every rep row not on this level; renumber the survivors 1..N.
        g2 = _retry(tmp_ws.get_all_values)
        keep = [r for r in range(4, tot)
                if _norm_name(_cell(g2, r - 1, NAME_COL)) in roster]
        if not keep:
            return None, 0, []
        _hide_rows(ss, gid, [r for r in range(4, tot) if r not in keep])
        _clean_number_col(ss, tmp_ws, tot)
        time.sleep(1.0)

        right = col_letter(max(show))
        body = R.export(SHEET_ID, gid, f"A{HEADER_ROW}:{right}{max(keep)}", token)
        img = R.stitch([R.title_bar(body.width, title_for(n, days)), body])
        mmdd = f"{anchor.month}.{anchor.day}"
        path = out_dir / f"Zero Streak {mmdd} — {level_label(n)}.png"
        img.save(path)
        camps = sorted({_cell(g2, r - 1, camp_c).strip() for r in keep})
        return path, len(keep), camps
    finally:
        ss.batch_update({"requests": [{"deleteSheet": {"sheetId": gid}}]})


def render_streaks(ss, cur_ws, grid, spec, today, out_dir: Path, token=None) -> list:
    """One image per streak depth. Returns [(meta, png)] ascending, [] if nobody
    rolled a zero on the anchor day. Each meta carries the B2B-style caption."""
    out_dir.mkdir(parents=True, exist_ok=True)
    token = token or _access_token()
    yday = today - dt.timedelta(days=1)
    anchor = anchor_day(yday)
    window = mandatory_days(anchor, MAX_DAYS)
    span = [anchor - dt.timedelta(days=i) for i in range(LOOKBACK_CAL_DAYS)]
    board_we = _cell(grid, 2, 2).strip()

    tot = _totals_row(grid)
    camp_c = _campaign_col(grid)
    sun_c = _sun_apps_col(grid)
    values = _load_day_values(ss, span, cur_ws, grid)
    print(f"  zeros: window {window[0]:%a %m/%d} → {window[-1]:%a %m/%d} "
          f"({len(window)} mandatory days, Sun+Mon skipped; board week {board_we})")

    streaks, all_names = {}, []
    for r in range(3, tot - 1):
        name = _cell(grid, r, NAME_COL).strip()
        if not name:
            continue
        all_names.append(name)
        if not _cell(grid, r, camp_c).strip():          # trainer-only staff (Bas)
            continue
        if _cell(grid, r, sun_c).strip().upper() in ("F", "T"):
            continue
        s = _walk_streak(_norm_name(name), anchor, values)
        if s >= 1:
            streaks[_norm_name(name)] = s

    if not streaks:
        print("  zeros: nobody rolled a zero on the anchor day — no images")
        return []

    rosters = {}
    for n in range(1, MAX_DAYS + 1):
        keep = {nm for nm, s in streaks.items() if s >= n}
        if not keep:
            break
        rosters[n] = keep
    emit = [n for n in sorted(rosters) if rosters.get(n + 1) != rosters[n]]
    folded = [n for n in sorted(rosters) if n not in emit]
    if folded:
        print(f"  zeros: level(s) {', '.join(map(str, folded))} folded into a deeper one")

    _sweep_temp(ss)
    out = []
    for n in emit:
        days = window[-n:]
        path, reps, camps = _render_level(
            ss, cur_ws, grid, values, rosters[n], all_names, n, days,
            board_we, anchor, token, out_dir)
        if path is None:
            continue
        mmdd = f"{anchor.month}.{anchor.day}"
        meta = dict(spec, id=f"{spec['id']}_{n}", level=n, reps=reps, no_date=True,
                    title=f"Zero Streak {mmdd} — {level_label(n)}")
        out.append((meta, path))
        print(f"  zeros L{n}: {reps:2} reps ({', '.join(camps)}) -> {path.name}")
        time.sleep(1.0)
    return out
