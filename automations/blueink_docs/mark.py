"""Tint a sent person's first name light green on the OBCL tab.

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
    """Light-green the first-name cell of everyone in `people`. Returns the
    number of cells tinted. Best-effort: a formatting failure must never make a
    send that already went out look like it didn't."""
    cells = [p for p in people if p.row and p.first_col]
    if not cells:
        return 0
    sheet_id = worksheet.id
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": p.row - 1, "endRowIndex": p.row,
                "startColumnIndex": p.first_col - 1, "endColumnIndex": p.first_col,
            },
            "cell": {"userEnteredFormat": {"backgroundColor": LIGHT_GREEN}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    } for p in cells]
    worksheet.spreadsheet.batch_update({"requests": requests})
    return len(cells)
