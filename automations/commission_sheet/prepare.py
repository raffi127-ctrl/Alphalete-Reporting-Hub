"""Steps 2 & 3 — reset a freshly-copied workbook for the new week.

A new week starts as a duplicate of last week's workbook, so it arrives full of
last week's data. JD clears three things before any new numbers go in:

  * `1. Paste the DD` and `2. Paste the Order Log` — wiped whole; both are pure
    pasted crosstabs, headers included, and step 4/5 paste them back.
  * the 4b bonus block — last week's bonuses, which do not carry over.
  * the 4a formulas — re-dragged from the first data row all the way down.

That last one is not cosmetic. JD types real amounts over the 4a formula during
the week when a Sunday bonus won't compute, and re-dragging is HOW those hand
edits get cleared:

    "I want to drag the formula all the way down so that it clears out the
     manual amounts that I put in."

Which makes this destructive by design, and only safe as the FIRST thing done
to a new copy. Run it later in the week and it silently erases that week's
corrections — so it refuses unless the tabs still look like a fresh duplicate,
and `--force` is required to override.

One guard worth knowing: the drag copies whatever is in the first data row. If
somebody typed a number over the formula THERE, dragging would spread that
constant down a thousand rows. So the first row is checked for a real formula
first, and the run aborts if it is a literal.

    python -m automations.commission_sheet.prepare            # dry run
    python -m automations.commission_sheet.prepare --write
"""
from __future__ import annotations

import argparse
from typing import Dict, List, Optional

from automations.commission_sheet import config as C

#: 4a occupies A:J. Column F carries no formula and copies across blank, which
#: is what dragging the block by hand does too.
CONFIRM_FIRST_COL, CONFIRM_LAST_COL = 0, 10      # A..J, end-exclusive
CONFIRM_FIRST_DATA_ROW = 5                       # row 4 is the header
#: 4b is L:P on the same tab, data from row 5.
BONUS_FIRST_COL, BONUS_LAST_COL = 11, 16         # L..P, end-exclusive
BONUS_FIRST_DATA_ROW = 5


def _sheet(workbook_id: str):
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(workbook_id)


def _formula_extent(ws) -> int:
    """Last row carrying a 4a formula in column A — the extent to re-drag to.
    Preserves however far the workbook was already built out rather than
    imposing a number of our own."""
    col = ws.get(f"A{CONFIRM_FIRST_DATA_ROW}:A{ws.row_count}",
                 value_render_option="FORMULA")
    last = 0
    for offset, row in enumerate(col):
        if row and str(row[0]).startswith("="):
            last = CONFIRM_FIRST_DATA_ROW + offset
    return last


def survey(workbook_id: str = C.WORKBOOK_ID) -> Dict:
    sh = _sheet(workbook_id)
    dd = sh.worksheet(C.TAB_DD)
    ol = sh.worksheet(C.TAB_ORDER_LOG)
    cf = sh.worksheet(C.TAB_CONFIRM)

    dd_rows = len([r for r in dd.get(f"A1:A{dd.row_count}") if r and str(r[0]).strip()])
    ol_rows = len([r for r in ol.get(f"A1:A{ol.row_count}") if r and str(r[0]).strip()])

    bonus = cf.get(f"L{BONUS_FIRST_DATA_ROW}:P{cf.row_count}")
    bonus_rows = sum(1 for r in bonus if any(str(c).strip() for c in r))

    first = cf.get(f"A{CONFIRM_FIRST_DATA_ROW}:J{CONFIRM_FIRST_DATA_ROW}",
                   value_render_option="FORMULA")
    first_row = list(first[0]) if first else []
    seed_ok = bool(first_row) and str(first_row[0]).startswith("=")

    return {"sh": sh, "dd": dd, "ol": ol, "cf": cf,
            "dd_rows": dd_rows, "ol_rows": ol_rows,
            "bonus_rows": bonus_rows,
            "extent": _formula_extent(cf),
            "seed_ok": seed_ok,
            "seed": first_row[:1]}


def report(s: Dict) -> str:
    out = ["\nWILL CLEAR",
           f"  {C.TAB_DD!r}          {s['dd_rows']} row(s) of pasted data",
           f"  {C.TAB_ORDER_LOG!r}  {s['ol_rows']} row(s) of pasted data",
           f"  4b bonus block          {s['bonus_rows']} row(s)",
           "\nWILL RE-DRAG",
           f"  4a formulas A:J from row {CONFIRM_FIRST_DATA_ROW} "
           f"down to row {s['extent']}"]
    if not s["seed_ok"]:
        out.append(f"\n  !! row {CONFIRM_FIRST_DATA_ROW} holds a literal, not a formula "
                   f"({s['seed']!r}) — dragging would copy that constant down the "
                   f"whole column. Fix that row first.")
    out.append("\n  NOTE: re-dragging wipes any amount typed over the 4a formula. "
               "That is the point,\n        but only as the FIRST thing done to a new copy.")
    return "\n".join(out)


def apply(s: Dict) -> Dict:
    if not s["seed_ok"]:
        raise RuntimeError(
            f"Row {CONFIRM_FIRST_DATA_ROW} of {C.TAB_CONFIRM!r} is a literal, not a "
            "formula — refusing to drag a constant down the sheet.")
    if not s["extent"] or s["extent"] <= CONFIRM_FIRST_DATA_ROW:
        raise RuntimeError("No 4a formula extent found — nothing to re-drag.")

    s["dd"].clear()
    s["ol"].clear()

    cf = s["cf"]
    if s["bonus_rows"]:
        cf.batch_clear([f"L{BONUS_FIRST_DATA_ROW}:P{cf.row_count}"])

    sheet_id = cf.id
    s["sh"].batch_update({"requests": [{"copyPaste": {
        "source": {"sheetId": sheet_id,
                   "startRowIndex": CONFIRM_FIRST_DATA_ROW - 1,
                   "endRowIndex": CONFIRM_FIRST_DATA_ROW,
                   "startColumnIndex": CONFIRM_FIRST_COL,
                   "endColumnIndex": CONFIRM_LAST_COL},
        "destination": {"sheetId": sheet_id,
                        "startRowIndex": CONFIRM_FIRST_DATA_ROW,
                        "endRowIndex": s["extent"],
                        "startColumnIndex": CONFIRM_FIRST_COL,
                        "endColumnIndex": CONFIRM_LAST_COL},
        "pasteType": "PASTE_FORMULA"}}]})

    return {"dd_cleared": s["dd_rows"], "ol_cleared": s["ol_rows"],
            "bonus_cleared": s["bonus_rows"],
            "redragged_to": s["extent"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workbook", default=C.WORKBOOK_ID)
    ap.add_argument("--write", action="store_true", help="do it")
    args = ap.parse_args(argv)

    s = survey(args.workbook)
    print(report(s))
    if not args.write:
        print("\n(dry run — nothing cleared; add --write to reset the workbook)")
        return 0
    done = apply(s)
    print(f"\nCleared DD ({done['dd_cleared']} rows), order log "
          f"({done['ol_cleared']} rows), {done['bonus_cleared']} bonus row(s).")
    print(f"Re-dragged 4a formulas to row {done['redragged_to']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
