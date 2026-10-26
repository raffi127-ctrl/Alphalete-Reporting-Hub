"""Next week's sales board tab on an owner's board, made by Lucy (Raf 2026-10-25,
Omar: "automatically give him a new one every Monday at 1 am").

Owners in owners.json with "new_week_tab": true keep one tab per week named by
its SUNDAY ('10/25' = 10/19-10/25, "week_end"). Every Monday this copies the
newest week tab, names the copy by the new Sunday ('11/01') and puts it LEFT of
the old one -- where Omar's people put '11/01' by hand on 10/25. On the copy:

  * the typed day cells (Int, Int Up, DTV, NL, Cx, Roll Call) go blank --
    Apps and the week totals are formulas and stay;
  * LAST WEEK'S TOTALS = the old tab's RUNNING WEEK TOTALS, PRIOR WEEK'S TOTALS
    = its LAST WEEK'S (they are typed numbers, nobody else fills them);
  * Field Status one week further ('1st Wk' -> '2nd Wk' ... '4th Wk' ->
    '5th Wk+'; Eve 2026-10-25), anything else ('RT') as it was;
  * the Monday date under MON and the 'WE m/d-m/d' label move to the new week;
  * the week that just closed goes on top of the WEEKLY HISTORY table under
    the board's stats (made the first time; --seed-history for a board whose
    current tab was made by hand).

Names, trainers, statuses, formats and formulas come over as they are. The
Lanes / Line Up formulas still read the old tab: the owners' fixer moves them
(sales_board_fixer --owners, "lanes_roll").

Writes only with --apply. Real schedule = com.alphalete.owner-week-tab on
LUCY 4, Monday 00:00 CT = 1 AM in Dearborn. Safe to run again: the tab of this
week already there = nothing to do.

    python -m automations.sales_board_fixer.week_tab                  # preview
    python -m automations.sales_board_fixer.week_tab --apply
    python -m automations.sales_board_fixer.week_tab --sheet <sandbox id> --today 2026-11-02 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.sales_board_fixer import checks as K
from automations.sales_board_fixer import run as R

TYPED_DAY_COLS = {"int", "int up", "dtv", "nl", "cx", "roll call"}
RUNNING, LAST, PRIOR = "RUNNING WEEK TOTALS", "LAST WEEK'S TOTALS", "PRIOR WEEK'S TOTALS"
WE_LABEL = re.compile(r"^\s*WE\s*\d", re.I)
FIELD_STATUS = "FIELD STATUS"
WEEK_N = re.compile(r"^\s*([1-4])(?:st|nd|rd|th)\s+(w(?:ee)?k)\s*$", re.I)
ORDINAL = {2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def next_week_status(s: str) -> Optional[str]:
    """'1st Wk' -> '2nd Wk', '4th Wk' -> '5th Wk+' (the board's last bucket);
    None = not a week count, leave it."""
    m = WEEK_N.match(s)
    if not m:
        return None
    n = int(m.group(1)) + 1
    return "%s %s%s" % (ORDINAL[n], m.group(2), "+" if n == 5 else "")


def tab_date(title: str, today: dt.date) -> Optional[dt.date]:
    """'11/01' -> the Sunday it names; a December tab read in January is last year's."""
    m = R.DATED_TAB.match(title)
    if not m:
        return None
    try:
        d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    if d > today + dt.timedelta(days=13):
        d = d.replace(year=today.year - 1)
    return d


def tab_name(sunday: dt.date) -> str:
    return "%02d/%02d" % (sunday.month, sunday.day)


def newest_week(sheets, today: dt.date) -> Optional[Tuple[dt.date, dict]]:
    """(Sunday, sheet properties) of the newest visible dated week tab."""
    best = None
    for s in sheets:
        p = s["properties"]
        d = None if p.get("hidden") else tab_date(p["title"], today)
        if d and (best is None or d > best[0]):
            best = (d, p)
    return best


def _label_cols(row, label: str) -> List[int]:
    """1-based columns under a banner like LAST WEEK'S TOTALS: from it up to
    the next filled cell of the banner row."""
    start = next((i + 1 for i, x in enumerate(row) if " ".join(str(x).split()).upper() == label), 0)
    if not start:
        return []
    end = next((i for i in range(start, len(row)) if str(row[i]).strip()), len(row))
    return list(range(start, end + 1))


def _cell(grid, r: int, c: int):
    return grid[r - 1][c - 1] if r - 1 < len(grid) and c - 1 < len(grid[r - 1]) else ""


def _typed(formulas, r: int, c: int) -> bool:
    return not str(_cell(formulas, r, c)).startswith("=")


def plan(values, formulas, raw, monday: dt.date) -> Dict[str, object]:
    """{A1: new value} for the copy of last week's tab. values/formulas/raw =
    the old tab (formatted / FORMULA / UNFORMATTED_VALUE)."""
    lay = K.layout(values)
    first, last = K.block_rows(values)
    out: Dict[str, object] = {}

    # the typed day cells start blank
    for day, cols in K.day_blocks(values).items():
        for h, c in cols.items():
            if h not in TYPED_DAY_COLS:
                continue
            for r in range(first, last + 1):
                if _typed(formulas, r, c) and str(_cell(formulas, r, c)).strip():
                    out[K.col_letter(c) + str(r)] = ""

    # last week's totals <- running, prior <- last (rep rows + TOTALS row)
    banner = values[lay.day_row - 1] if lay.day_row - 1 < len(values) else []
    run_c, last_c, prior_c = (_label_cols(banner, x) for x in (RUNNING, LAST, PRIOR))
    for src, dst in ((run_c, last_c), (last_c, prior_c)):
        for s, d in zip(src, dst):
            for r in range(first, last + 2):
                v = _cell(raw, r, s)
                v = 0 if v in ("", None) else v
                if _typed(formulas, r, d) and v != _cell(raw, r, d):
                    out[K.col_letter(d) + str(r)] = v

    # the Monday date number under MON, and the 'WE 9/7-9/13' label
    mon_c = next((c for c in range(1, len(banner) + 1)
                  if str(_cell(values, lay.day_row, c)).strip().upper() == "MON"), 0)
    date_r = lay.day_row + 1
    if mon_c and date_r < lay.sub_row and _typed(formulas, date_r, mon_c) \
            and re.fullmatch(r"\d{1,2}(\.0)?", str(_cell(raw, date_r, mon_c)).strip()):
        out[K.col_letter(mon_c) + str(date_r)] = monday.day
    # Field Status: everybody is one week further in ('1st Wk' -> '2nd Wk' ...
    # '4th Wk' -> '5th Wk+'); anything else ('RT', '5th Wk+') stays
    fs_c = next((i + 1 for i, x in enumerate(banner)
                 if " ".join(str(x).split()).upper() == FIELD_STATUS), 0)
    for r in range(first, last + 1) if fs_c else ():
        if _typed(formulas, r, fs_c):
            nxt = next_week_status(str(_cell(raw, r, fs_c)))
            if nxt:
                out[K.col_letter(fs_c) + str(r)] = nxt

    label = str(_cell(formulas, lay.sub_row, lay.name_col))
    if WE_LABEL.match(label):
        sun = monday + dt.timedelta(days=6)
        out[K.col_letter(lay.name_col) + str(lay.sub_row)] = "WE%d/%d-%d/%d" % (
            monday.month, monday.day, sun.month, sun.day)
    return out


# --- weekly history (Eve 2026-10-25: "sumás los históricos semanales a medida
# que pasan las semanas?") -----------------------------------------------------
# A table under the board's own stats ('% of Reps on the Board'), newest week
# on top, one row per closed week: its TOTALS (Apps..Cx) plus Reps in the Field
# and % on the Board. Each Monday's copy carries the table and gets the week
# that just closed inserted on top. Found by its title, never by row number.

HISTORY = "WEEKLY HISTORY"
HISTORY_HEAD = ["Week", "Apps", "INT", "INT UP", "DTV", "NL", "Cx",
                "Reps in the Field", "% on the Board"]
STATS_LAST = "% OF REPS ON THE BOARD"      # the history goes 3 rows under it
IN_FIELD = "REPS IN THE FIELD"


def _row_of(values, col: int, label: str, start: int = 1) -> int:
    return next((r for r in range(start, len(values) + 1)
                 if " ".join(str(_cell(values, r, col)).split()).upper() == label), 0)


def week_label(sunday: dt.date) -> str:
    mon = sunday - dt.timedelta(days=6)
    return "WE %d/%d - %d/%d" % (mon.month, mon.day, sunday.month, sunday.day)


def history_row(values, raw, sunday: dt.date) -> list:
    """The closed week's line, read off ITS tab: TOTALS Apps..Cx + stats."""
    lay = K.layout(values)
    tot = lay.last + 1
    nums = [_cell(raw, tot, c) for c in range(lay.name_col + 1, lay.name_col + 7)]
    field = _cell(raw, _row_of(values, lay.name_col, IN_FIELD, tot), lay.name_col + 1)
    pct = _cell(raw, _row_of(values, lay.name_col, STATS_LAST, tot), lay.name_col + 1)
    return [week_label(sunday)] + [0 if x in ("", None) else x for x in nums + [field, pct]]


def add_history(sh, ws, values, line: list) -> str:
    """Put `line` on top of the tab's history table, making the table first if
    the tab has none. Returns what it did, for the log. Every row takes the
    TOTALS row's look: it sits outside the board's filter (a filtered-out rep
    row can't be a copyPaste source, 2026-10-25)."""
    lay = K.layout(values)
    nc = lay.name_col
    width = len(HISTORY_HEAD)
    c2 = nc + width - 1
    tot = lay.last + 1
    title = _row_of(values, nc, HISTORY, tot)
    sid = ws.id
    rows = []
    if not title:
        stats = _row_of(values, nc, STATS_LAST, tot)
        if not stats:
            return "no '% of Reps on the Board' row -- no history table"
        title = stats + 3
        for r in (title, title + 1):
            if any(str(_cell(values, r, c)).strip() for c in range(nc, c2 + 1)):
                return "rows %d-%d are not empty -- no history table" % (title, title + 1)
        rows = [[HISTORY] + [""] * (width - 1), HISTORY_HEAD]
        made = "made the history table at row %d, " % title
    else:
        made = ""
    at = title + 2
    reqs = [{"insertDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                           "startIndex": at - 1, "endIndex": at},
                                 "inheritFromBefore": False}}]
    tot_now = tot + 1 if tot >= at else tot    # the insert pushed it down
    for r1 in ((title, title + 1, at) if rows else (at,)):
        reqs.append({"copyPaste": {"source": _grid(sid, tot_now, tot_now, nc, c2),
                                   "destination": _grid(sid, r1, r1, nc, c2),
                                   "pasteType": "PASTE_FORMAT"}})
    for c, pattern in ((c2 - 1, "0"), (c2, "0.0%")):   # Reps in the Field, % on the Board
        reqs.append({"repeatCell": {"range": _grid(sid, at, at, c, c),
                                    "cell": {"userEnteredFormat": {"numberFormat": {
                                        "type": "NUMBER" if pattern == "0" else "PERCENT",
                                        "pattern": pattern}}},
                                    "fields": "userEnteredFormat.numberFormat"}})
    sh.batch_update({"requests": reqs})
    ws.update(range_name="%s%d:%s%d" % (K.col_letter(nc), at - len(rows), K.col_letter(c2), at),
              values=rows + [line], value_input_option="RAW")
    return made + "added %s on row %d" % (line[0], at)


def _grid(sid: int, r1: int, r2: int, c1: int, c2: int) -> dict:
    return {"sheetId": sid, "startRowIndex": r1 - 1, "endRowIndex": r2,
            "startColumnIndex": c1 - 1, "endColumnIndex": c2}


def seed_history(sh, today: dt.date, apply: bool) -> int:
    """One time, for a board that already has this week's tab: give it the
    history table with the week before it (the table then grows on Mondays)."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,index,hidden))"})
    weeks = sorted(((tab_date(s["properties"]["title"], today), s["properties"]["title"])
                    for s in meta["sheets"] if not s["properties"].get("hidden")
                    and tab_date(s["properties"]["title"], today)), reverse=True)
    if len(weeks) < 2:
        print("  needs this week's tab and last week's -- nothing to seed")
        return 2
    (_, cur), (sun, prev) = weeks[0], weeks[1]
    ws = sh.worksheet(cur)
    values = ws.get_all_values()
    if _row_of(values, K.layout(values).name_col, HISTORY, K.layout(values).last + 1):
        print("  '%s' already has its history table" % cur)
        return 0
    pv = sh.worksheet(prev)
    line = history_row(pv.get_all_values(), pv.get_all_values(value_render_option="UNFORMATTED_VALUE"), sun)
    print("  '%s' history <- %s" % (cur, line))
    if apply:
        print("  " + add_history(sh, ws, values, line))
    return 0


def roll(sh, today: dt.date, apply: bool) -> int:
    """0 made or already there, 2 refused (no board / a week missing)."""
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,title,index,hidden))"})
    want = R.week_sunday(today)
    found = newest_week(meta["sheets"], today)
    if not found:
        print("  no dated week tab ('10/25') -- nothing to copy")
        return 2
    sunday, src = found
    if sunday >= want:
        print("  '%s' is already there -- nothing to do" % src["title"])
        return 0
    if (want - sunday).days != 7:
        print("  newest week tab is '%s' but this week is %s: a week is missing, not guessing"
              % (src["title"], tab_name(want)))
        return 2
    ws = sh.worksheet(src["title"])
    values = ws.get_all_values()
    formulas = ws.get_all_values(value_render_option="FORMULA")
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not K.is_board(values):
        print("  '%s' does not read as a sales board -- not copying it" % src["title"])
        return 2
    monday = want - dt.timedelta(days=6)
    cells = plan(values, formulas, raw, monday)
    name = tab_name(want)
    print("  '%s' -> new tab '%s' (left of it), %d cells: %d day cells blank, Monday = %d"
          % (src["title"], name, len(cells), sum(1 for v in cells.values() if v == ""), monday.day))
    if not apply:
        for a1 in list(cells)[:15]:
            print("    %s = %r" % (a1, cells[a1]))
        print("  PREVIEW -- nothing written (--apply writes)")
        return 0
    sh.batch_update({"requests": [{"duplicateSheet": {
        "sourceSheetId": src["sheetId"], "insertSheetIndex": src["index"], "newSheetName": name}}]})
    new = sh.worksheet(name)
    if cells:
        new.batch_update([{"range": a1, "values": [[v]]} for a1, v in cells.items()],
                         value_input_option="RAW")
    print("  made '%s'" % name)
    # the copy still holds last week's grid, so last week's layout finds its table
    print("  " + add_history(sh, new, values, history_row(values, raw, sunday)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="make the tab (default: preview)")
    ap.add_argument("--owner", help="only this owner (name in owners.json)")
    ap.add_argument("--sheet", help="test copy: use this sheet id instead of the owner's")
    ap.add_argument("--today", help="YYYY-MM-DD, for a test (default: the owner's today)")
    ap.add_argument("--seed-history", action="store_true",
                    help="one time: history table on this week's tab, with last week")
    a = ap.parse_args(argv)
    owners = [o for o in json.loads(R.OWNERS_FILE.read_text(encoding="utf-8"))["owners"]
              if o.get("new_week_tab") and (not a.owner or o["name"].lower() == a.owner.lower())]
    if not owners:
        print("no owner with \"new_week_tab\" in owners.json")
        return 2
    worst, failed = 0, []
    for o in owners:
        if a.today:
            today = dt.date.fromisoformat(a.today)
        else:
            from zoneinfo import ZoneInfo
            today = dt.datetime.now(ZoneInfo(o.get("tz", "America/Chicago"))).date()
        sheet = a.sheet or o["sheet_id"]
        print("%s (%s), today %s:" % (o["name"], "TEST COPY " + sheet if a.sheet else sheet, today))
        try:
            rc = (seed_history if a.seed_history else roll)(R._book(sheet), today, a.apply)
        except Exception as e:  # noqa: BLE001 -- one owner's board never stops the next
            print("  FAILED: %s: %s" % (type(e).__name__, e))
            rc = 1
        if rc:
            failed.append(o["name"])
        worst = max(worst, rc)
    if failed and a.apply and not a.sheet:
        tell_eve(failed)
    return worst


def tell_eve(names) -> None:
    """A Monday with no new tab means the owner starts the week on last week's
    board: DM Eve instead of failing quietly (the agent has no Hub card)."""
    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        if "lucy" not in client.auth_test().get("user", "").lower():
            print("! this machine does not post as Lucy -- no DM")
            return
        text = ("New week tab: Lucy could not make this week's sales board tab for %s. "
                "Log: output/logs/owner-week-tab-*.log on Lucy 4." % ", ".join(names))
        ch = client.conversations_open(users=R.EVE_USER_ID)["channel"]["id"]
        client.chat_postMessage(channel=ch, text=text)
        print("  DM to Eve: %s" % ", ".join(names))
    except Exception as e:  # noqa: BLE001 -- the DM never hides the real exit code
        print("! DM to Eve failed: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
