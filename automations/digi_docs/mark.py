"""Tint the Digi Docs cell — and nothing else on that tab.

Megan 2026-08-25: the tint goes on the **Digi Docs CELL**, not the name, and the
CHECKBOX is never written — a person hand-marks that once the docs are done.

Worth stating because blueink_docs/mark.py, the file this is modelled on, does
the opposite on both counts: it tints the first name in column D, and it ticks
its own checkbox. It can, because it reads Blue Ink's "signed" list to back the
tick up. There is no equivalent source here, so a tick from us would assert a
completion nobody verified. The tint means "I sent it"; the tick means "this is
complete"; only the first is ours to make.

ONE batch_update, not a write per cell: per-cell loops 429 the NEXT report too
(the Sheets write-quota trap this repo has already paid for once).
"""
from __future__ import annotations

from typing import List

from automations.digi_docs import config

# Google Sheets' "light green 3" (#D9EAD3) — the tint used by hand on these
# tabs, so an automated mark is indistinguishable from a manual one.
LIGHT_GREEN = {"red": 0xD9 / 255, "green": 0xEA / 255, "blue": 0xD3 / 255}


def tint(worksheet, cands: List, *, dry_run: bool = True) -> int:
    """Light-green the Digi Docs cell for each candidate. Returns cells tinted.

    Best-effort by design: a formatting failure must never make a bundle that
    already went out look like it didn't. The documents are the thing that
    matters; the marking is bookkeeping.
    """
    cells = [c for c in cands if c.row and c.digi_col]
    missing = [c for c in cands if c.row and not c.digi_col]
    if missing:
        # Paperwork beats a marking — they were still sent to.
        print(f"     (no {config.COL_DIGI_DOCS!r} column for "
              f"{len(missing)} of them — sent, not tinted)")
    if not cells:
        return 0
    if dry_run:
        print(f"     (dry run: would tint {len(cells)} "
              f"{config.COL_DIGI_DOCS} cell(s))")
        return 0

    assert config.TINT_CELL_ONLY and not config.TINT_THE_NAME
    assert config.NEVER_WRITE_CHECKBOX
    requests = [{
        "repeatCell": {
            "range": {
                "sheetId": worksheet.id,
                "startRowIndex": c.row - 1, "endRowIndex": c.row,
                "startColumnIndex": c.digi_col - 1, "endColumnIndex": c.digi_col,
            },
            # backgroundColor ONLY. Not userEnteredValue -- writing a value here
            # is what would tick the checkbox somebody else owns.
            "cell": {"userEnteredFormat": {"backgroundColor": LIGHT_GREEN}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    } for c in cells]
    worksheet.spreadsheet.batch_update({"requests": requests})
    return len(cells)
