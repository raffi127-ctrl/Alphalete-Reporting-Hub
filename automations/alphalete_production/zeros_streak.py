"""Zero Streak — the escalating 'zeros in a row' callout for the Alphalete
Production post (Raf 2026-07-25). Mirrors the B2B Sales-Boards version
(`automations/sales_boards/zeros.py`): instead of ONE 'Back-to-Back Zeros'
image, post one image per streak depth — 1 Day / 2 Days / 3 Days … — each
listing every rep on a run of that length.

WHAT COUNTS AS A ZERO: a literal numeric 0 for that day ('0'/'0.00'). An 'X'/'F'/
'T' (absent / terminated) or a blank is NOT a zero — you can't roll a zero on a
day you didn't sell.

NON-MANDATORY DAYS = SUNDAY **and MONDAY** (Raf 2026-07-25: "Monday isn't
mandatory, keeping the same rules"). Neither is ever the anchor, never counts as
a zero, and never shows as a column — BUT a SALE on either still breaks the run
(same rule the B2B build uses for Sunday). So walking back from the anchor, a
Sunday/Monday is transparent unless the rep put up a positive number on it, in
which case the streak stops there. Mandatory selling days are Tue–Sat.

STREAKS CROSS WEEKS — up to MAX_DAYS mandatory days back. The board holds ONE
week per tab, so earlier days come from the PRIOR-week tabs ('Sales Board WE m.d'),
which is this sheet's history (there is no WeekData tab like B2B has). Reps are
matched across tabs by NORMALIZED name — the '(Wk N)'/'(NC)' suffix increments
every week, so raw names don't match across tabs (`_norm_name` strips it). A rep
with no row in a past week (a new hire) simply can't extend past it, which
truncates the streak rather than overstating it.

FOLDING: levels are nested (everyone at n+1 is also at n). A level whose roster
is identical to the next-deeper one says strictly less, so we post only the
deeper — one rep on a 4-day run ships ONE image, not four. Same as B2B / the VA.

RENDER: we build a clean, self-contained table on a throwaway tab and export it
(PDF -> PNG, same engine as the rest of the post). We do NOT reshape the live
board — a cross-week window can't be shown on a single week's tab anyway. The
live sheet is never touched.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path

from automations.alphalete_production.capture import (
    SHEET_ID, _access_token, _cell, _campaign_col, _day_block, _export_png,
    _field_status_col, _norm_name, _sun_apps_col, _totals_row, col_letter,
    find_week_tab,
)

TMP_TAB = "_zeros_streak_tmp"
MAX_DAYS = 7                 # go past 2, up to a week-plus of mandatory selling days
LOOKBACK_CAL_DAYS = 18       # calendar reach that safely contains MAX_DAYS + Sun/Mon
NON_MANDATORY = (0, 6)       # Monday (0) + Sunday (6): never a zero, never a column
IDENTITY_HEADERS = ["#", "Rep", "Team", "Trainer", "Field Status", "Campaign"]
ZERO_TINT = {"red": 0.97, "green": 0.80, "blue": 0.80}      # light red for zero cells
HEADER_BG = {"red": 0.18, "green": 0.33, "blue": 0.59}      # sheet header blue


def is_zero(v) -> bool:
    """A literal numeric zero — '0', '0.0', '0.00'. Not X / F / T / blank."""
    return bool(re.fullmatch(r"0(\.0+)?", str(v).strip()))


def is_sale(v) -> bool:
    """A positive number — the only thing that breaks a run on a non-mandatory day."""
    try:
        return float(str(v).strip()) > 0
    except (TypeError, ValueError):
        return False


def anchor_day(yday: dt.date) -> dt.date:
    """The most recent day a zero can be rolled on. Sunday and Monday aren't
    mandatory, so we walk back past them (a Tuesday run anchors on Saturday)."""
    d = yday
    while d.weekday() in NON_MANDATORY:
        d -= dt.timedelta(days=1)
    return d


def mandatory_days(anchor: dt.date, n: int) -> list:
    """The n most recent MANDATORY days ending on `anchor`, OLDEST FIRST, skipping
    Sundays + Mondays. Walks straight through week boundaries — that's the point."""
    out, d = [], anchor
    while len(out) < n:
        if d.weekday() not in NON_MANDATORY:
            out.append(d)
        d -= dt.timedelta(days=1)
    return list(reversed(out))


def level_label(n: int) -> str:
    """'1 Day' / '2 Days' / '3 Days' … — one consistent series (Megan 7/23 on the
    B2B twin: not '1 day 0'), so the thread reads as one escalating set."""
    return f"{n} Day" if n == 1 else f"{n} Days"


def title_for(n: int, days: list) -> str:
    """days = the shown window, oldest first; level n uses its last n."""
    span = days[-n:]
    end = span[-1]
    if n == 1:
        where = f"{end.strftime('%A')} {end.month}/{end.day}"
    else:
        start = span[0]
        where = (f"{start.strftime('%a')} {start.month}/{start.day} → "
                 f"{end.strftime('%a')} {end.month}/{end.day}")
    return f"Zero Streak: {level_label(n)}  ({where})"


def _load_day_values(ss, dates, cur_ws, cur_grid) -> dict:
    """{date: {norm_name: apps_value}} over a span of CALENDAR dates (Sundays and
    Mondays included, because a sale on either has to be visible to the walk).

    Current-week days come off the tab we already loaded; earlier days come from
    the prior-week tab that CONTAINS that date. Each tab is read once."""
    cache = {cur_ws.title: cur_grid}
    out = {}
    for d in dates:
        tab = find_week_tab(ss, d)
        grid = cache.get(tab.title)
        if grid is None:
            grid = tab.get_all_values()
            cache[tab.title] = grid
        try:
            c = _day_block(grid, d)[0]
        except RuntimeError:
            out[d] = {}                    # this tab has no block for d -> no data
            continue
        m = {}
        for r in range(3, len(grid)):
            nm = _cell(grid, r, 2).strip()
            if nm:
                m[_norm_name(nm)] = _cell(grid, r, c).strip()
        out[d] = m
    return out


def _walk_streak(nm: str, anchor: dt.date, values: dict) -> int:
    """Consecutive zeros ending on the anchor, walking back day by day.

    Sunday/Monday are transparent — they add nothing to the count, but a SALE on
    one stops the walk. Any other non-zero (a sale, an X, an F/T, or a day we have
    no data for) stops it too."""
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


def _sweep_temp(ss):
    for w in ss.worksheets():
        if w.title == TMP_TAB:
            try:
                ss.batch_update({"requests": [{"deleteSheet": {"sheetId": w.id}}]})
            except Exception:              # noqa: BLE001
                pass


def _format_requests(gid: int, nrow: int, ncol: int) -> list:
    """Bold blue header, thin borders throughout, day cells tinted light red
    (every shown day is a zero), columns auto-sized."""
    grid_rng = {"sheetId": gid, "startRowIndex": 0, "endRowIndex": nrow,
                "startColumnIndex": 0, "endColumnIndex": ncol}
    day_rng = {"sheetId": gid, "startRowIndex": 1, "endRowIndex": nrow,
               "startColumnIndex": len(IDENTITY_HEADERS), "endColumnIndex": ncol}
    hdr_rng = {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
               "startColumnIndex": 0, "endColumnIndex": ncol}
    thin = {"style": "SOLID", "width": 1, "color": {"red": .7, "green": .7, "blue": .7}}
    return [
        {"repeatCell": {"range": hdr_rng, "cell": {"userEnteredFormat": {
            "backgroundColor": HEADER_BG, "horizontalAlignment": "CENTER",
            "textFormat": {"bold": True, "foregroundColor": {
                "red": 1, "green": 1, "blue": 1}}}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"repeatCell": {"range": day_rng, "cell": {"userEnteredFormat": {
            "backgroundColor": ZERO_TINT, "horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat(backgroundColor,horizontalAlignment)"}},
        {"updateBorders": {"range": grid_rng, "top": thin, "bottom": thin,
                           "left": thin, "right": thin,
                           "innerHorizontal": thin, "innerVertical": thin}},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": gid, "dimension": "COLUMNS",
            "startIndex": 0, "endIndex": ncol}}},
    ]


def render_streaks(ss, cur_ws, grid, spec, today, out_dir: Path, token=None) -> list:
    """Build one image per streak depth. Returns [(meta, png)] in ascending depth
    (1 Day, 2 Days, …), empty if nobody rolled a zero on the anchor day.

    `meta` carries the caption title + the section's emoji/react for slack_post.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    token = token or _access_token()
    yday = today - dt.timedelta(days=1)
    anchor = anchor_day(yday)
    window = mandatory_days(anchor, MAX_DAYS)              # candidate columns, oldest first
    span = [anchor - dt.timedelta(days=i) for i in range(LOOKBACK_CAL_DAYS)]  # incl. Sun/Mon

    tot = _totals_row(grid)
    camp_c = _campaign_col(grid)
    fs_c = _field_status_col(grid)
    sun_c = _sun_apps_col(grid)
    team_c = next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Team")
    trainer_c = next(c for c in range(len(grid[0])) if _cell(grid, 0, c).strip() == "Trainer")

    values = _load_day_values(ss, span, cur_ws, grid)
    print(f"  zeros: window {window[0]:%a %m/%d} → {window[-1]:%a %m/%d} "
          f"({len(window)} mandatory days, Sun+Mon skipped)")

    streaks, info = {}, {}
    for r in range(3, tot - 1):
        name = _cell(grid, r, 2).strip()
        if not name:
            continue
        campaign = _cell(grid, r, camp_c).strip()
        if not campaign:                   # trainer-only staff (e.g. Bas) aren't selling
            continue
        if _cell(grid, r, sun_c).strip().upper() in ("F", "T"):
            continue                       # terminated — off the board
        nm = _norm_name(name)
        s = _walk_streak(nm, anchor, values)
        if s >= 1:
            streaks[nm] = s
            info[nm] = {"name": name, "team": _cell(grid, r, team_c).strip(),
                        "trainer": _cell(grid, r, trainer_c).strip(),
                        "fs": _cell(grid, r, fs_c).strip(), "campaign": campaign}

    if not streaks:
        print("  zeros: nobody rolled a zero on the anchor day — no images")
        return []

    # nested rosters -> emit only the levels that add someone
    rosters = {}
    for n in range(1, MAX_DAYS + 1):
        keep = {nm for nm, s in streaks.items() if s >= n}
        if not keep:
            break
        rosters[n] = keep
    emit = [n for n in sorted(rosters) if rosters.get(n + 1) != rosters[n]]
    folded = [n for n in sorted(rosters) if n not in emit]
    if folded:
        print(f"  zeros: level(s) {', '.join(map(str, folded))} have the same reps as a "
              f"deeper level — folded in, not posted twice")

    _sweep_temp(ss)
    out = []
    for n in emit:
        days = window[-n:]
        rows = sorted(rosters[n],
                      key=lambda k: (info[k]["team"].lower(), info[k]["name"].lower()))
        header = IDENTITY_HEADERS + [f"{d.strftime('%a')} {d.month}/{d.day}" for d in days]
        table = [header]
        for rank, nm in enumerate(rows, 1):
            it = info[nm]
            table.append([rank, it["name"], it["team"], it["trainer"], it["fs"],
                          it["campaign"]] + ["0"] * n)
        nrow, ncol = len(table), len(header)

        ws = ss.add_worksheet(title=TMP_TAB, rows=nrow + 4, cols=ncol + 2)
        try:
            ws.batch_update([{"range": "A1", "values": table}],
                            value_input_option="RAW")
            ss.batch_update({"requests": _format_requests(ws.id, nrow, ncol)})
            time.sleep(0.8)
            rng = f"A1:{col_letter(ncol - 1)}{nrow}"
            name = f"{spec['id']}_{n}day"
            png = _export_png(ws.id, rng, out_dir / f"{name}.png", token)
        finally:
            ss.batch_update({"requests": [{"deleteSheet": {"sheetId": ws.id}}]})
        meta = dict(spec, id=f"{spec['id']}_{n}",
                    title=f"Zero Streak — {level_label(n)}", level=n)
        out.append((meta, png))
        camps = sorted({info[nm]["campaign"] for nm in rows})
        print(f"  zeros L{n}: {len(rows):2} reps ({', '.join(camps)}) -> {png.name}")
        time.sleep(1.0)
    return out
