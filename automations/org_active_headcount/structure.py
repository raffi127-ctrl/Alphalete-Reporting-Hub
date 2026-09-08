"""Where everything sits on the Active Headcount tab — found by LABEL, never row.

THE TAB. One box per campaign, in the ORG Sales Board's own campaign order, each
carrying that campaign's ICD roster (the same roster, in the same order, as the
ORG board's weekly-history section). A box looks like this:

    row H     A='ATT Fiber Team'   C='Total for week'   F..L='WE 08.30' … 'WE 07.19'
    row H+1                        C='Total this week'  D='Last week'  E='Delta'
    rows      A=rank  B=<ICD>      C=<the week's headcount — what the fill writes>
                                   D==F   E==Iferror((C-D)/D,0)
    total     A='Captainship'      C==SUM(reps)  D==F  E=delta  F..L==SUM(reps)

So C is the LIVE week, D mirrors F (the last closed week), and F..L are the seven
weeks of history that roll one column right every Monday.

WHY LABEL-DRIVEN. Same reason as the rest of the board: a campaign gains an ICD
and every row below it moves. Boxes are found by their 'Total this week' row and
their col-A campaign label; the week columns by their 'WE mm.dd' headers; the
roster by col B. Nothing here may be a typed row or column number.
[[feedback_no_hardcoded_columns]]

TWO THINGS THE FINDERS TOLERATE, because the hand-built tab already does them:
  • the totals row of the BOX and Retail Internet boxes has NO 'Captainship'
    label in col A (the other five do). The totals row is therefore identified
    structurally — the first row after the roster — not by its label.
  • the rank gutter in col A is literal ('1','2','3') in some boxes and a
    '=A45+1' chain in others. Nothing reads col A for meaning, so both pass.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

SHEET_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
# The live tab. It began as a sandbox copy while the report was built and
# took the real name on 2026-09-07, when Eve deleted the hand-built original
# ("Active Headcout Alphalete Org Board", gid 134766444) and renamed this one.
BOARD_TAB = "Org Active Headcount Board"
# Opt-in copy for testing a change before it touches the live tab. It does
# not exist unless somebody duplicates the board tab under this name.
SANDBOX_TAB = "Org Active Headcount Board SANDBOX"

# The box header's col-C label, and the triplet row directly beneath it.
BOX_HEADER_C = "total for week"
TRIPLET = ("total this week", "last week", "delta")

# Summary block at the top.
SUMMARY_TITLE = "headcount summary"
SUMMARY_GRAND_TOTAL = "grand total"

_WE_RE = re.compile(r"^WE\s+(\d{1,2})\.(\d{1,2})$", re.I)


def a1col(c: int) -> str:
    """1-based column number -> letter(s)."""
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def we_label(week_ending: dt.date) -> str:
    """'WE MM.DD', zero-padded — the format the board's headers already use."""
    return f"WE {week_ending.month:02d}.{week_ending.day:02d}"


def parse_we(label: str, year: int) -> Optional[dt.date]:
    """'WE 08.30' -> date(year, 8, 30). The headers carry no year, so the
    caller supplies the one the label belongs to."""
    m = _WE_RE.match((label or "").strip())
    if not m:
        return None
    try:
        return dt.date(year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def cell(grid: List[List], r1: int, c1: int) -> str:
    """1-based (row, col) -> stripped string; '' off the end of the grid."""
    row = grid[r1 - 1] if 0 < r1 <= len(grid) else []
    return str(row[c1 - 1]).strip() if 0 < c1 <= len(row) else ""


def find_boxes(grid: List[List]) -> List[dict]:
    """Every campaign box on the tab, top to bottom.

    Returns one dict per box:
      campaign    col-A label on the header row ('ATT Fiber Team')
      header_row  the row carrying that label + 'Total for week' + WE headers
      triplet_row header_row + 1 ('Total this week' / 'Last week' / 'Delta')
      rows        [(row, icd_name)] — the roster, in sheet order
      total_row   the SUM row under the roster
      this_col    column of 'Total this week'  (C)
      last_col    column of 'Last week'        (D)
      delta_col   column of 'Delta'            (E)
      week_cols   [(col, 'WE mm.dd')] newest-first, left to right (F..L)
    """
    out: List[dict] = []
    n = len(grid)
    for i in range(1, n + 1):
        if cell(grid, i, 3).lower() != BOX_HEADER_C:
            continue
        t = i + 1
        if tuple(cell(grid, t, c).lower() for c in (3, 4, 5)) != TRIPLET:
            continue                      # not a box — just a stray label
        campaign = cell(grid, i, 1)
        if not campaign:
            continue
        week_cols = []
        width = max((len(grid[r - 1]) for r in (i, t) if r <= n), default=0)
        for c in range(6, width + 1):
            lbl = cell(grid, i, c)
            if _WE_RE.match(lbl):
                week_cols.append((c, lbl))
        rows = []
        r = t + 1
        while r <= n and cell(grid, r, 2):
            rows.append((r, cell(grid, r, 2)))
            r += 1
        if not rows:
            continue
        out.append({
            "campaign": campaign,
            "header_row": i,
            "triplet_row": t,
            "rows": rows,
            "total_row": r,            # first row past the roster = the SUM row
            "this_col": 3, "last_col": 4, "delta_col": 5,
            "week_cols": week_cols,
        })
    return out


def find_summary(grid: List[List]) -> Optional[dict]:
    """The 'Headcount Summary' block at the top.

    Returns {title_row, header_row, rows: {campaign: row}, grand_total_row,
    cols: {label: col}} — the per-campaign rows of the summary are matched to
    the boxes by their col-B campaign name, so a renamed campaign fails loudly
    instead of pointing the summary at the wrong box.
    """
    n = len(grid)
    title = next((i for i in range(1, n + 1)
                  if cell(grid, i, 2).lower() == SUMMARY_TITLE), None)
    if title is None:
        return None
    header = title + 1
    width = len(grid[header - 1]) if header <= n else 0
    cols = {cell(grid, header, c): c for c in range(3, width + 1)
            if cell(grid, header, c)}
    rows: Dict[str, int] = {}
    grand = None
    r = header + 1
    while r <= n and cell(grid, r, 2):
        label = cell(grid, r, 2)
        if label.lower() == SUMMARY_GRAND_TOTAL:
            grand = r
            break
        rows[label] = r
        r += 1
    return {"title_row": title, "header_row": header, "rows": rows,
            "grand_total_row": grand, "cols": cols}


def match_box(key: str, box_label: str) -> bool:
    """Does `box_label` on the sheet name the campaign `key` in the code?

    NOT an equality test, and that matters. Eve renames these boxes as the
    report settles: on 2026-09-07 every one of them gained a ' Headcount'
    suffix and the two Retail boxes merged into 'Retail NL / Internet
    Headcount'. Exact matching found nothing that morning and the fill reported
    "0 cells" without an error - a silent no-op is the worst failure this report
    can have, because the tab keeps last week's numbers and looks filled.

    So the CODE's name only has to be a prefix of the SHEET's label. Her wording
    wins, the join survives a rename, and a genuinely different campaign still
    fails to match [[feedback_no_hardcoded_columns]].
    """
    k, b = key.strip().lower(), box_label.strip().lower()
    return b == k or b.startswith(k)


def find_box(boxes: List[dict], key: str) -> Optional[dict]:
    """The box for this campaign key, or None."""
    return next((b for b in boxes if match_box(key, b["campaign"])), None)


def board_week(grid: List[List]) -> Optional[str]:
    """The week the tab's history currently starts on — the FIRST week column's
    label ('WE 08.30'), read off the first box. That is the last CLOSED week, so
    the live 'Total this week' column is the week after it."""
    boxes = find_boxes(grid)
    if not boxes or not boxes[0]["week_cols"]:
        return None
    return boxes[0]["week_cols"][0][1]
