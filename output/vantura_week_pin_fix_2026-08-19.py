"""Vantura Master Sales Board — restore the gold WE selector to the current week.

2026-08-19: the board's gold week cell (row 2, right of the 'WE' label) was
sitting on '8.9' while the tab's live week is 8.23 (Mon 8/17-Sun 8/23). Every
Wed..Sun day cell is a formula keyed on that selector
(`=INDEX(WeekData!D:D, MATCH($B5&"|"&$B$2, WeekData!A:A,0))`), so the board was
showing the Aug 3-9 ARCHIVE under headers MON(3)..SUN(9), while Mon/Tue were
hand-typed CURRENT-week numbers — a mixed-week board.

It also broke three vantura-board-audit checks at once: the Stations row-2 week
label (S2 = 8.23) no longer matched the board's selector, so `week_ref` came out
empty and the two roll-call new-start FILTERs (X5/Z5), which compare `$S$2`,
were reported as "no longer compares the current week cell".

Nothing else is touched: the typed day cells are static, and no report writes
this cell (sales_boards.check_we / vantura_slack_sales.week_ok deliberately HOLD
instead of rolling it, because rolling it mid-week would repopulate the formula
cells and leave the typed ones behind).

    python -m output.vantura_week_pin_fix_2026_08_19            # dry run
    python output/vantura_week_pin_fix_2026-08-19.py --apply    # write
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
TAB = "Sales Board"
WE_LABEL = "we"          # col A row 2 label that names the gold cell


def _a1col(j: int) -> str:
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def find_we_cell(grid):
    """(row, col, current) of the gold selector — the cell just right of the
    'WE' label. Found by LABEL, never by address: this tab has already slid a
    column once (2026-07-21)."""
    for i, row in enumerate(grid[:6], start=1):
        for j, c in enumerate(row):
            if str(c).strip().lower() == WE_LABEL:
                nxt = str(row[j + 1]).strip() if len(row) > j + 1 else ""
                return i, j + 2, nxt
    return None, None, None



# --- second half: the CAPTION next to the gold cell ------------------------
# C2 spells the week out in prose (" Week Ending 8.16     |     B2B + BOX …").
# It is hand-typed, so it drifts from the gold cell on its own — it read 8.16 on
# 2026-08-19 with the board on 8.23 and the gold cell on 8.9: three different
# answers to "what week is this board?" in two adjacent cells. No audit checks
# it, so it only ever misleads a human. Rebuilding it as a formula off the gold
# cell keeps the exact same words and makes the drift impossible.
CAPTION_RE = re.compile(r"^(.*?Week Ending )(\d+(?:\.\d+)?)(.*)$", re.S)


def caption_formula(text: str, we_a1: str) -> str:
    """The caption rebuilt as a formula, or "" if it doesn't look like one we
    recognise. Same words, week token swapped for a reference to the gold cell —
    TEXT(…,"0.##") is the format the tab already uses for this (see AS3)."""
    m = CAPTION_RE.match(text or "")
    if not m:
        return ""
    head, _, tail = m.groups()
    q = lambda t: '"%s"' % t.replace('"', '""')
    return '=%s&TEXT(%s,"0.##")&%s' % (q(head), we_a1, q(tail))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--today", help="YYYY-MM-DD override, for testing")
    ap.add_argument("--caption", action="store_true",
                    help="also rebuild the prose caption beside the gold cell "
                         "as a formula, so it can't drift from it again")
    args = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key
    from automations.sales_boards.run import expected_we

    today = (dt.date.fromisoformat(args.today) if args.today else dt.date.today())
    _, want = expected_we(today - dt.timedelta(days=1))

    sh = open_by_key(SHEET_ID)
    sb = sh.worksheet(TAB)
    grid = sb.get("A1:D6")
    r, c, shown = find_we_cell(grid)
    if not r:
        print("could not find the 'WE' label in the first rows — aborting")
        return 2
    at = f"{_a1col(c - 1)}{r}"
    print(f"gold WE cell {at}: shows {shown!r}, current week is {want!r}")

    weeks = {str(x).strip() for x in sh.worksheet("WeekData").col_values(10)}
    if want not in weeks:
        print(f"{want!r} is not in the WeekData week list — refusing to write")
        return 2

    # the Stations week label has to end up agreeing; that agreement IS the
    # audit check that fired.
    stn2 = [str(x).strip() for x in sh.worksheet("Stations").get("A2:CL2")[0]]
    print("Stations row-2 week label:", [x for x in stn2 if x == want] or "NOT FOUND")

    if args.caption:
        cap_at = f"{_a1col(c)}{r}"          # the cell just right of the gold one
        cur = sb.acell(cap_at, value_render_option="FORMULA").value or ""
        if str(cur).startswith("="):
            print(f"caption {cap_at} is already a formula — leaving it")
        else:
            f = caption_formula(str(cur), f"${_a1col(c - 1)}${r}")
            if not f:
                print(f"caption {cap_at} doesn't match the expected wording — "
                      "leaving it alone")
            elif not args.apply:
                print(f"DRY RUN — would rewrite caption {cap_at} as: {f}")
            else:
                sb.update_acell(cap_at, f)
                print(f"WROTE caption {cap_at} — now reads: "
                      f"{sb.acell(cap_at).value!r}")

    if shown == want:
        print("already on the current week — nothing to do")
        return 0
    if not args.apply:
        print(f"DRY RUN — would set {at} to {want}")
        return 0

    sb.update_acell(at, want)
    print(f"WROTE {at} = {want}")
    print("after:", sb.acell(at).value,
          "| day headers:", sh.worksheet(TAB).get("E3:K3"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
