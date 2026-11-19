"""'Teams — Current Week' screenshot off a board tab (Carlos 2026-11-19: "Send a
screenshot of the teams board on the NDS metrics thread and as text message to
the Aplayer and leaders chat").

The box sits under the '% on the Board' block: a header row whose first cell
starts with 'Teams' (labels in column B, the stats to its right), the campaign
total row, one row per team -- ranked by Apps by the sheet's own formulas --
and 'Unaccounted For'. Rows are found by label, never by index: the box moves
whenever the roster above it grows, and gets a row longer or shorter whenever
a team is added or emptied (the board's script, _refreshTeamsBoxOn).

Shot straight off the LIVE tab, like pct_block: the VA's basic filter only
covers the rep rows, and this box is below it, so no temp copy is needed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

_PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", _PROD_SHEET_ID)

LABEL_COL = 2                      # column B holds the box's labels
HEADER_MARK = "total head count"   # the header row carries this column title
LAST_LABEL = "unaccounted for"     # the box's closing row
MAX_ROWS = 40                      # the script never lets the box run longer
READ_RANGE = "A1:T220"             # the reps and the box; never the whole tab


def _norm(v) -> str:
    return " ".join(str(v or "").split()).lower()


def _letter(c: int) -> str:
    out = ""
    while c:
        c, r = divmod(c - 1, 26)
        out = chr(65 + r) + out
    return out


def box_rows(g: List[List[str]]) -> Tuple[int, int, int]:
    """(header row, last row, last column), all 1-based, of the Teams box in
    grid `g`. The header is the row whose column-B cell starts with 'teams'
    and that names 'Total Head Count'; the box ends on its 'Unaccounted For'
    row (a team that just lost its last rep leaves a blank row above it until
    the script rebuilds, so look for the label, not for the first blank).
    Raises when the tab has no such box."""
    hdr = None
    for r, row in enumerate(g, start=1):
        cells = [_norm(c) for c in row]
        if len(cells) >= LABEL_COL and cells[LABEL_COL - 1].startswith("teams") \
                and HEADER_MARK in cells:
            hdr = r
            last_col = max(i for i, c in enumerate(cells, start=1) if c)
            break
    if hdr is None:
        raise RuntimeError("no 'Teams' box header (a row naming Total Head Count)")
    last = run_end = hdr
    in_run = True
    for r in range(hdr + 1, min(len(g), hdr + MAX_ROWS) + 1):
        row = g[r - 1]
        label = _norm(row[LABEL_COL - 1]) if len(row) >= LABEL_COL else ""
        if label == LAST_LABEL:
            last = r
            break
        if not label:
            in_run = False
        elif in_run:
            run_end = r
    if last == hdr:
        last = run_end
    if last == hdr:
        raise RuntimeError("the Teams box has no rows under its header")
    return hdr, last, last_col


def render_teams_box(tab_name: str, out_path, log=print) -> Path:
    """Export the tab's Teams box as a PNG at `out_path`."""
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(tab_name)
    g = _retry(lambda: ws.get(READ_RANGE))
    try:
        hdr, last, last_col = box_rows(g)
    except RuntimeError as e:
        raise RuntimeError(f"{tab_name}: {e}") from None
    rng = f"{_letter(LABEL_COL)}{hdr}:{_letter(last_col)}{last}"
    img = R.export(SHEET_ID, ws.id, rng, _token())
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    log(f"[teams] {tab_name}: {rng} ({last - hdr - 1} row(s) under the header) "
        f"-> {out_path.name}")
    return out_path
