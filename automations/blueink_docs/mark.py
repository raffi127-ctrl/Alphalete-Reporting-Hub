"""Tint a sent person's "Blue Ink" cell light green on the OBCL tab.

Megan moved this off the first name on 2026-08-24, when she added a dedicated
"Blue Ink" column: green there means "we sent it", and the checkbox in the same
cell gets ticked separately once Blue Ink shows the packet signed. So the one
cell carries both halves of the story -- sent, and done.

This is the one place we write into the recruiting team's own tab, and it only
ever sets a BACKGROUND COLOR -- the cell's text is never touched, so a name we
mis-read can't overwrite what somebody typed.

The whole batch goes up in ONE request: a per-cell format loop burns the Sheets
write quota and 429s the next report as well as this one.
"""
from __future__ import annotations

from typing import List

from automations.blueink_docs.roster import NewStart

# Google Sheets' "light green 3" (#D9EAD3) -- the tint already used by hand on
# these tabs, so an automated mark is indistinguishable from a manual one.
LIGHT_GREEN = {"red": 0xD9 / 255, "green": 0xEA / 255, "blue": 0xD3 / 255}


def highlight(worksheet, people: List[NewStart]) -> int:
    """Light-green the "Blue Ink" cell of everyone in `people`. Returns the
    number of cells tinted. Best-effort: a formatting failure must never make a
    send that already went out look like it didn't."""
    cells = [p for p in people if p.row and p.blueink_col]
    missing = [p for p in people if p.row and not p.blueink_col]
    if missing:
        print("     (no %r column on this tab -- %d send(s) not tinted)"
              % (__import__("automations.blueink_docs.config",
                            fromlist=["config"]).COL_BLUEINK, len(missing)))
    if not cells:
        return 0
    sheet_id = worksheet.id
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": p.row - 1, "endRowIndex": p.row,
                "startColumnIndex": p.blueink_col - 1,
                "endColumnIndex": p.blueink_col,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": LIGHT_GREEN}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    } for p in cells]
    worksheet.spreadsheet.batch_update({"requests": requests})
    return len(cells)
