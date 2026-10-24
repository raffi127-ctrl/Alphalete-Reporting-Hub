"""'% on the Board' screenshot (Carlos 2026-10-24: "every morning after the
sales board gets filled out can you include this screenshot of the % of the
reps on the board. do the same for verizon on their thread").

The block lives on each board tab directly under the totals: a '% on the
Board' header row (Mon..Sat in C..H — NOT the rep table's E..K geometry) and
five stat rows (All Reps / Reps Worked / Rolled a Zero / On the Board /
% On Board), closed by the 'Worked = …' footnote. Rows are found by label,
never by index — the NDS block sits at 22, Verizon's at 29, and both move
whenever the roster above them grows.

Shot straight off the LIVE tab: the VA's basic filter only covers the rep
rows, and this block is below it, so no temp copy is needed.
"""
from __future__ import annotations

import os
from pathlib import Path

# Same PROD-by-default / env-override pair as sales_boards.run — repeated here
# so rendering one block doesn't import the whole Slack posting module.
_PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", _PROD_SHEET_ID)

HEADER_LABEL = "% on the board"
FIRST_COL, LAST_COL = "B", "H"          # label col .. Saturday


def render_pct_block(tab_name: str, out_path, log=print) -> Path:
    """Export the tab's '% on the Board' block as a PNG at `out_path`."""
    from automations.pnl_office.run import _token
    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.sales_boards import render as R

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(tab_name)
    g = _retry(ws.get_all_values)
    hdr = next((r for r in range(1, len(g) + 1)
                if R.cell(g, r, 2).strip().lower() == HEADER_LABEL), None)
    if hdr is None:
        raise RuntimeError(f"{tab_name}: no '% on the Board' row found")
    end = hdr
    while end < len(g):
        nxt = R.cell(g, end + 1, 2).strip()
        if not nxt or nxt.lower().startswith("worked"):
            break
        end += 1
    if end == hdr:
        raise RuntimeError(f"{tab_name}: '% on the Board' block is empty")
    img = R.export(SHEET_ID, ws.id,
                   f"{FIRST_COL}{hdr}:{LAST_COL}{end}", _token())
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    log(f"[pct] {tab_name}: rows {hdr}..{end} -> {out_path.name}")
    return out_path
