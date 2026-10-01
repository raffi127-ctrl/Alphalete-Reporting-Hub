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

ONLY THE WEEK COLUMNS ARE TOUCHED. Col A and col B carry Raf's section colours
and labels; recolouring those would fight the layout he built. This writes
background colour and nothing else — no values, no borders, no fonts.
"""
from __future__ import annotations

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


def requests_for(grid: List[List[str]], sheet_id: int,
                 first_week_col: int = 3, last_week_col: int = 44) -> List[Dict]:
    """copyPaste requests spreading each manual row's LABEL colour across its
    week columns — a brighter version of whatever section it sits in."""
    return [{"copyPaste": {
        "source": {"sheetId": sheet_id, "startRowIndex": r - 1, "endRowIndex": r,
                   "startColumnIndex": LABEL_COL_IDX,
                   "endColumnIndex": LABEL_COL_IDX + 1},
        "destination": {"sheetId": sheet_id, "startRowIndex": r - 1, "endRowIndex": r,
                        "startColumnIndex": first_week_col - 1,
                        "endColumnIndex": last_week_col},
        "pasteType": "PASTE_FORMAT"}}
        for r in manual_rows(grid)]


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
