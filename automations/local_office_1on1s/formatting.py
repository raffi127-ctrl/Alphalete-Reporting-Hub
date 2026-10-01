"""Say on the sheet which cells the report fills and which a human does.

Raf's box mixes two kinds of row and they look identical today, so a blank
automated cell ("the source had nothing") is indistinguishable from a blank
manual one ("nobody has typed it yet"). Megan, 2026-10-01: "maybe goals/manual
fills are a different color?"

    AUTOMATED   left exactly as Raf styled it — the report writes these
    MANUAL      bright lavender, every week column: all of 4. Culture / Atmo /
                HTP, 'What are we going to do better?', 'BreakEven',
                'Money Saved?', 'Goal / Focus for the week'
    GOALS       the same lavender — 'New INT Goal', 'Wireless Goal',
                'App Goal', 'New / App Goal'. A goal is a target somebody sets,
                which makes it manual in the only sense that matters here.

NO NEW PALETTE — EACH ROW BORROWS ITS OWN SECTION'S COLOUR, BRIGHT.
Megan 2026-10-01: "so maybe the goal line in the orange 1st section is just a
brighter orange". The box is already built that way: col B carries the strong
version of the section colour (vivid orange on 'New INT', vivid pink on
'Networking?') while the week columns carry a pale tint of it. So a manual
row's week columns simply take the colour that is already on its own label.

That means no palette lives here at all. Raf restyles a section and the manual
rows inside it follow on the next run, because the colour is read off the sheet
rather than written down in code — the same reason everything else in this
report is found by label. Grey (rejected) and then a single lavender (replaced)
both had the same flaw: they were a colour chosen HERE, competing with his.

ONLY THE WEEK COLUMNS ARE TOUCHED, AND ONLY AS FAR AS THE CHART GOES. Col A
and col B carry Raf's section colours and labels, so recolouring those would
fight the layout he built. The right edge is the LAST DATED COLUMN in the
section's own header — painting a fixed width ran the bands far past 12/27
into empty space (Megan 2026-10-01: "colors need cleaned up to only be to the
end of the chart"), so everything beyond that edge is cleared back to plain.

This writes background colour and nothing else — no values, no borders, no
fonts.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.local_office_1on1s import fill as F, layout as LO

# Nothing hardcoded: the colour comes from each row's own label cell.
LABEL_COL_IDX = 1          # col B, 0-based — the strong section colour

# Rows a human fills. MANUAL comes from fill.py so the two cannot drift: a row
# the fill refuses to write is exactly a row that should look manual.
GOAL_ROWS = ["New INT Goal", "Wireless Goal", "App Goal", "New / App Goal"]


def _is_manual(label: str) -> bool:
    f = LO.fold(label)
    if any(f.startswith(LO.fold(g)) for g in GOAL_ROWS):
        return True
    return any(f.startswith(m) or m.startswith(f) for m in F.MANUAL)


def manual_rows(grid: List[List[str]]) -> List[int]:
    """Every row a human fills, across every section on the tab."""
    out: List[int] = []
    for sec in LO.find_sections(grid):
        for r in range(sec.start + 1, sec.end + 1):
            label = LO._cell(grid, r, LO.LABEL_COL).strip()
            if label and _is_manual(label):
                out.append(r)
    return out


WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
HARD_RIGHT = 44            # col AR — nothing on these tabs goes beyond it


def last_week_col(grid: List[List[str]], sec) -> int:
    """The rightmost DATED column in this section's header row.

    Read per section rather than assumed: a tab that gains a week should gain
    a column of colour with it, and one that has fewer must not be painted
    into empty space.
    """
    from automations.local_office_1on1s import weeks as W
    cols = [w.col for w in W.read_header(sec.header, year=dt.date.today().year)
            if w.sunday is not None]
    return max(cols) if cols else LO.FIRST_WEEK_COL - 1


def requests_for(grid: List[List[str]], sheet_id: int,
                 first_week_col: int = 3) -> List[Dict]:
    """Spread each manual row's LABEL colour across its week columns — and
    clear anything already painted to the right of the chart."""
    out: List[Dict] = []
    for sec in LO.find_sections(grid):
        right = last_week_col(grid, sec)
        for r in range(sec.start + 1, sec.end + 1):
            label = LO._cell(grid, r, LO.LABEL_COL).strip()
            if not label or not _is_manual(label):
                continue
            if right >= first_week_col:
                out.append({"copyPaste": {
                    "source": {"sheetId": sheet_id,
                               "startRowIndex": r - 1, "endRowIndex": r,
                               "startColumnIndex": LABEL_COL_IDX,
                               "endColumnIndex": LABEL_COL_IDX + 1},
                    "destination": {"sheetId": sheet_id,
                                    "startRowIndex": r - 1, "endRowIndex": r,
                                    "startColumnIndex": first_week_col - 1,
                                    "endColumnIndex": right},
                    "pasteType": "PASTE_FORMAT"}})
            # everything past the last dated column goes back to plain
            if right < HARD_RIGHT:
                out.append({"repeatCell": {
                    "range": {"sheetId": sheet_id,
                              "startRowIndex": r - 1, "endRowIndex": r,
                              "startColumnIndex": right,
                              "endColumnIndex": HARD_RIGHT},
                    "cell": {"userEnteredFormat": {"backgroundColor": WHITE}},
                    "fields": "userEnteredFormat.backgroundColor"}})
    return out


def apply(spreadsheet, tab: str, *, logfn=print) -> int:
    ws = spreadsheet.worksheet(tab)
    reqs = requests_for(ws.get_all_values(), ws.id)
    if not reqs:
        logfn(f"  {tab}: no manual rows found — nothing recoloured")
        return 0
    for i in range(0, len(reqs), 200):
        spreadsheet.batch_update({"requests": reqs[i:i + 200]})
    logfn(f"  {tab}: {len(reqs)} manual/goal row(s) greyed")
    return len(reqs)


def ensure_week_columns(spreadsheet, tab: str, needed: List, *, logfn=print) -> int:
    """Append week columns so every week in `needed` has one, on every section.

    Megan 2026-10-01: "we also need to add columns to the chart as we run out
    of them." The tabs were built out to 12/27 by hand; without this the fill
    would silently stop having anywhere to put January.

    EVERY SECTION GETS THE SAME COLUMN. Each box carries its own header row, so
    a week added to one and not another would put the same date in two
    different columns on one tab — and every lookup here is by date, so the
    two would disagree about which column is which. The new date is therefore
    written into the header row of EVERY section at the same column index.

    Dates are written in the tabs' own format — zero-padded MM/DD, which is
    what the rebuilt templates use ('08/02', not 'WE 8/2').
    """
    ws = spreadsheet.worksheet(tab)
    grid = ws.get_all_values()
    secs = LO.find_sections(grid)
    if not secs:
        return 0

    from automations.local_office_1on1s import weeks as W
    year = max(d.year for d in needed)
    have, right = set(), LO.FIRST_WEEK_COL - 1
    for w in W.read_header(secs[0].header, year=year):
        if w.sunday is not None:
            have.add(w.sunday)
            right = max(right, w.col)

    missing = sorted(d for d in needed if d not in have)
    if not missing:
        return 0

    updates = []
    for n, when in enumerate(missing):
        col = right + 1 + n
        if col > HARD_RIGHT:
            logfn(f"  {tab}: no room for WE {when:%m/%d} past col {HARD_RIGHT}")
            break
        a1 = ""
        c = col
        while c > 0:
            c, rem = divmod(c - 1, 26)
            a1 = chr(65 + rem) + a1
        for sec in secs:
            updates.append({"range": f"{a1}{sec.start}",
                            "values": [[f"{when:%m/%d}"]]})
    if updates:
        for i in range(0, len(updates), 400):
            ws.batch_update(updates[i:i + 400])
        logfn(f"  {tab}: added {len(missing)} week column(s) "
              f"({', '.join(f'{d:%m/%d}' for d in missing)}) to {len(secs)} section(s)")
    return len(missing)
