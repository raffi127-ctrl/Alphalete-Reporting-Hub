"""Add Rafael's 2026-10-08 columns to the board's TEMPLATE tab.

The board copies its headers, banners, colours and widths from the TEMPLATE
tab, so a new column on the board is a new column THERE. This inserts, each
found by the header it follows (no column letters):

    Qualified Retention  -> + Qualified Retention Goal   (looks like 'Goal')
    Qualified (ANSWERED) -> + Answered                   (looks like that Qualified)
    Not Contacted        -> + Answer Retention           (looks like 'Booked Retention')
    Answer Retention     -> + Answer Retention Goal      (looks like 'Goal')

Inserted inside each group, so the QUALIFIED / ANSWERED banners stretch over
them. A column already there is skipped -- safe to run twice.

    python -m automations.first_to_second_below_mark.template_columns --copy-to "1st to 2nd below the mark TEMPLATE PREVIEW"
    python -m automations.first_to_second_below_mark.template_columns              # the real TEMPLATE
"""
from __future__ import annotations

import argparse
import sys
from typing import List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import board as b
from automations.first_to_second_below_mark import columns as cols
from automations.first_to_second_below_mark import run as rep

FORMAT_ROWS = 6          # the header row and the sample rows under it


def _headers(ws) -> tuple:
    top = ws.get("A1:AZ25")
    hrow = rep.find_header_row(top)
    if hrow is None:
        raise SystemExit(f"{ws.title!r}: no {rep.OWNER_HEADER!r} header row")
    return hrow, list(top[hrow - 1])


def plan(headers: List[str]) -> List[tuple]:
    """[(after field, new header, field whose look it copies), ...] still missing."""
    want = [("qualified_ret", "Qualified Retention\nGoal", "goal"),
            ("ab_qualified", "Answered", "ab_qualified"),
            ("not_contacted", "Answer\nRetention", "booked_ret"),
            ("answer_ret", "Answer Retention\nGoal", "goal")]
    have = {cols.norm(h) for h in headers}
    return [w for w in want if cols.norm(w[1]) not in have]


def add_columns(sh, tab: str, logfn=print) -> int:
    ws = fill.worksheet_ci(sh, tab)
    added = 0
    # One column at a time, re-reading the headers after each, so every position
    # comes from the tab as it is now.
    while True:
        hrow, headers = _headers(ws)
        todo = plan(headers)
        if not todo:
            break
        after, label, look = todo[0]
        col = cols.resolve(headers)
        if after not in col or look not in col:
            raise SystemExit(f"{tab!r}: cannot place {label!r} (no {after!r} / {look!r} column)")
        at = col[after] + 1
        src = col[look] + (1 if col[look] >= at else 0)
        sh.batch_update({"requests": [
            {"insertDimension": {"range": {"sheetId": ws.id, "dimension": "COLUMNS",
                                           "startIndex": at, "endIndex": at + 1},
                                 "inheritFromBefore": True}},
            {"copyPaste": {
                "source": b._rng(ws.id, hrow - 1, hrow - 1 + FORMAT_ROWS, src, src + 1),
                "destination": b._rng(ws.id, hrow - 1, hrow - 1 + FORMAT_ROWS, at, at + 1),
                "pasteType": "PASTE_FORMAT"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": at, "endIndex": at + 1},
                "properties": {"pixelSize": 90}, "fields": "pixelSize"}},
            {"updateCells": {"range": b._rng(ws.id, hrow - 1, hrow, at, at + 1),
                             "rows": [{"values": [{"userEnteredValue": {"stringValue": label}}]}],
                             "fields": "userEnteredValue"}},
        ]})
        logfn(f"  {tab!r}: + {label!r} at column {at + 1}")
        added += 1
    return added


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.template_columns")
    ap.add_argument("--tab", default=b.TEMPLATE_TAB)
    ap.add_argument("--copy-to", default=None,
                    help="duplicate --tab under this name first and change only the copy")
    args = ap.parse_args(argv)
    sh = fill.open_by_key(rep.SHEET_ID)
    tab = args.tab
    if args.copy_to:
        titles = {w.title for w in sh.worksheets()}
        if args.copy_to not in titles:
            sh.duplicate_sheet(fill.worksheet_ci(sh, args.tab).id, new_sheet_name=args.copy_to)
            print(f"  copied {args.tab!r} -> {args.copy_to!r}")
        tab = args.copy_to
    n = add_columns(sh, tab)
    print(f"OK - {n} column(s) added to {tab!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
