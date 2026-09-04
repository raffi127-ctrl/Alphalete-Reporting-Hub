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

Which makes it destructive by design, and only correct as the FIRST thing done
to a new copy.

Three things this does that dragging by hand does not:

  1. SEEDS FROM A PINNED COPY, not from whatever is in row 5. Dragging by hand
     propagates whatever that row happens to hold — so one subtly edited or
     overtyped formula there quietly rewrites all ~1000 rows wrong, and the
     sheet still looks fine. The canonical row lives in
     reference/confirm_4a_row.json; it is written to row 5 first, and the drag
     goes from that. A corrupt seed cannot spread.

  2. SNAPSHOTS WHAT IT DESTROYS. The hand-typed 4a amounts and the 4b bonus
     block are the only irreplaceable things in the workbook, and the manual
     process has no undo. Both are written to output/ before anything is
     cleared.

  3. VERIFIES AFTERWARDS. `--check` asserts the end state rather than trusting
     that the run did not error: source tabs empty, bonuses empty, and every
     4a row carrying the canonical formula out to the full extent.

    python -m automations.commission_sheet.prepare            # dry run
    python -m automations.commission_sheet.prepare --write
    python -m automations.commission_sheet.prepare --check    # verify only
    python -m automations.commission_sheet.prepare --capture  # re-pin row 5

The pinned row is a snapshot of a formula JD owns, so improving that formula
means re-pinning it — otherwise the next reset quietly reverts his change.
`--capture` is that step, and it refuses to pin a row carrying a literal, since
pinning an overtyped cell would bake the corruption in permanently.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.commission_sheet import config as C

#: The known-good 4a formula row. Seeding from this instead of from the
#: workbook is what stops a corrupted formula propagating down the tab.
REFERENCE_ROW = (Path(__file__).resolve().parent
                 / "reference" / "confirm_4a_row.json")
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def canonical_row() -> List[str]:
    data = json.loads(REFERENCE_ROW.read_text())
    row = list(data["formulas"])
    return (row + [""] * CONFIRM_LAST_COL)[:CONFIRM_LAST_COL]


def _norm(formula) -> str:
    """Formulas differ only in whitespace between a hand-drag and an API write."""
    return " ".join(str(formula or "").split())

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

    want = canonical_row()
    drift = [c for c, a, b in zip("ABCDEFGHIJ", first_row + [""] * 10, want)
             if _norm(a) != _norm(b)]

    return {"sh": sh, "dd": dd, "ol": ol, "cf": cf,
            "dd_rows": dd_rows, "ol_rows": ol_rows,
            "bonus_rows": bonus_rows,
            "extent": _formula_extent(cf),
            "seed_ok": seed_ok,
            "seed": first_row[:1],
            "drift": drift,
            "bonus_block": bonus}


def report(s: Dict) -> str:
    out = ["\nWILL CLEAR",
           f"  {C.TAB_DD!r}          {s['dd_rows']} row(s) of pasted data",
           f"  {C.TAB_ORDER_LOG!r}  {s['ol_rows']} row(s) of pasted data",
           f"  4b bonus block          {s['bonus_rows']} row(s)",
           "\nWILL RE-DRAG",
           f"  4a formulas A:J from row {CONFIRM_FIRST_DATA_ROW} "
           f"down to row {s['extent']}"]
    if s["drift"]:
        out.append(f"\n  row {CONFIRM_FIRST_DATA_ROW} differs from the pinned copy in "
                   f"column(s) {', '.join(s['drift'])} — the pinned one will be "
                   f"written first,\n  so the drift does NOT spread.")
    else:
        out.append(f"\n  row {CONFIRM_FIRST_DATA_ROW} matches the pinned copy.")
    out.append("\n  Hand-typed 4a amounts and the 4b block are saved to output/ first.")
    out.append("  NOTE: re-dragging wipes any amount typed over the 4a formula. "
               "That is the point,\n        but only as the FIRST thing done to a new copy.")
    return "\n".join(out)


def snapshot(s: Dict) -> Path:
    """Save the only irreplaceable things here — the amounts typed over the 4a
    formula, and the 4b bonus block — before either is cleared. The manual
    process has no undo; this is it."""
    cf = s["cf"]
    grid = cf.get(f"A{CONFIRM_FIRST_DATA_ROW}:J{s['extent']}",
                  value_render_option="FORMULA")
    overrides = []
    for offset, row in enumerate(grid):
        for col, cell in enumerate(list(row)):
            text = str(cell).strip()
            if text and not text.startswith("="):
                overrides.append({
                    "cell": f"{chr(65 + col)}{CONFIRM_FIRST_DATA_ROW + offset}",
                    "value": text})
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / (f"commission-reset-{dt.date.today().isoformat()}-"
                         f"{s['sh'].title.replace(' ', '_')}.json")
    path.write_text(json.dumps(
        {"workbook": s["sh"].title, "taken": dt.datetime.now().isoformat(timespec="seconds"),
         "manual_4a_overrides": overrides,
         "bonus_block_L_to_P": s["bonus_block"]}, indent=2), encoding="utf-8")
    return path


def apply(s: Dict) -> Dict:
    if not s["extent"] or s["extent"] <= CONFIRM_FIRST_DATA_ROW:
        raise RuntimeError("No 4a formula extent found — nothing to re-drag.")

    saved = snapshot(s)

    # Write the PINNED row first, so the drag can only ever spread a known-good
    # formula — never whatever the workbook happened to be carrying.
    s["cf"].update(f"A{CONFIRM_FIRST_DATA_ROW}:J{CONFIRM_FIRST_DATA_ROW}",
                   [canonical_row()], value_input_option="USER_ENTERED")

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
            "redragged_to": s["extent"], "snapshot": saved}


def capture(workbook_id: str = C.WORKBOOK_ID) -> int:
    """Re-pin row 5 as the canonical 4a formula row.

    Run after deliberately improving a 4a formula. Refuses a row containing a
    literal — pinning an overtyped cell would bake that mistake in for good,
    which is the exact failure the pinned copy exists to prevent."""
    sh = _sheet(workbook_id)
    cf = sh.worksheet(C.TAB_CONFIRM)
    got = cf.get(f"A{CONFIRM_FIRST_DATA_ROW}:J{CONFIRM_FIRST_DATA_ROW}",
                 value_render_option="FORMULA")
    row = (list(got[0]) if got else []) + [""] * CONFIRM_LAST_COL
    row = row[:CONFIRM_LAST_COL]

    literals = [f"{chr(65 + i)}={cell!r}" for i, cell in enumerate(row)
                if str(cell).strip() and not str(cell).strip().startswith("=")]
    if literals:
        print(f"\nRefusing to pin row {CONFIRM_FIRST_DATA_ROW} of "
              f"{sh.title!r} — these hold a literal, not a formula:")
        for lit in literals:
            print(f"  ✗ {lit}")
        print("\nFix those cells first; pinning them would make the mistake "
              "permanent.")
        return 1

    current = canonical_row()
    changed = [c for c, a, b in zip("ABCDEFGHIJ", row, current)
               if _norm(a) != _norm(b)]
    if not changed:
        print(f"\nRow {CONFIRM_FIRST_DATA_ROW} already matches the pinned copy — "
              "nothing to re-pin.")
        return 0

    REFERENCE_ROW.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_ROW.write_text(json.dumps(
        {"source": sh.title,
         "captured": dt.datetime.now().isoformat(timespec="seconds"),
         "row": CONFIRM_FIRST_DATA_ROW,
         "columns": list("ABCDEFGHIJ"),
         "formulas": row}, indent=2), encoding="utf-8")
    print(f"\nRe-pinned row {CONFIRM_FIRST_DATA_ROW} from {sh.title!r}.")
    print(f"  changed column(s): {', '.join(changed)}")
    for col in changed:
        i = ord(col) - 65
        print(f"\n  {col} was: {_norm(current[i])[:100] or '(blank)'}")
        print(f"  {col} now: {_norm(row[i])[:100] or '(blank)'}")
    print(f"\n  -> {REFERENCE_ROW}")
    print("  Commit that file so every machine resets to the same formula.")
    return 0


def check(workbook_id: str = C.WORKBOOK_ID) -> int:
    """Assert the END STATE, rather than trusting that the run didn't error.

    Every 4a row must carry the canonical formula with its row references
    stepped by one — the exact thing a bad drag gets wrong, and the exact thing
    that is invisible in the sheet because a wrong formula still shows a value."""
    s = survey(workbook_id)
    cf = s["cf"]
    failures: List[str] = []

    if s["dd_rows"]:
        failures.append(f"{C.TAB_DD!r} still holds {s['dd_rows']} row(s)")
    if s["ol_rows"]:
        failures.append(f"{C.TAB_ORDER_LOG!r} still holds {s['ol_rows']} row(s)")
    if s["bonus_rows"]:
        failures.append(f"4b still holds {s['bonus_rows']} row(s)")
    if s["drift"]:
        failures.append(f"row {CONFIRM_FIRST_DATA_ROW} differs from the pinned "
                        f"copy in {', '.join(s['drift'])}")

    grid = cf.get(f"A{CONFIRM_FIRST_DATA_ROW}:J{s['extent']}",
                  value_render_option="FORMULA")
    want = canonical_row()
    literals = blanks = stepped = 0
    bad_step: List[str] = []
    for offset, row in enumerate(grid):
        cells = (list(row) + [""] * CONFIRM_LAST_COL)[:CONFIRM_LAST_COL]
        rownum = CONFIRM_FIRST_DATA_ROW + offset
        for col, (got, base) in enumerate(zip(cells, want)):
            if not str(base).strip():
                continue
            text = str(got).strip()
            if not text:
                blanks += 1
            elif not text.startswith("="):
                literals += 1
        # Column A's reference must advance one row per row — the drag's whole job.
        expect = f"'{C.TAB_DD}'!A{rownum - 2}:AJ{rownum - 2}"
        if _norm(expect) in _norm(cells[0]):
            stepped += 1
        elif len(bad_step) < 5:
            bad_step.append(f"row {rownum}")

    if literals:
        failures.append(f"{literals} 4a cell(s) hold a literal instead of a formula")
    if blanks:
        failures.append(f"{blanks} 4a cell(s) are empty where a formula belongs")
    if stepped != len(grid):
        failures.append(f"only {stepped}/{len(grid)} rows step their DD reference "
                        f"correctly (first bad: {', '.join(bad_step) or '?'})")

    print(f"\nChecked {s['sh'].title!r}")
    print(f"  4a rows verified : {len(grid)} (rows {CONFIRM_FIRST_DATA_ROW}"
          f"–{s['extent']})")
    print(f"  DD reference steps correctly : {stepped}/{len(grid)}")
    if failures:
        print("\nNOT READY:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\n  ✓ source tabs empty, bonuses empty, every 4a row carries the "
          "pinned formula")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workbook", default=C.WORKBOOK_ID)
    ap.add_argument("--write", action="store_true", help="do it")
    ap.add_argument("--check", action="store_true",
                    help="verify the reset end state; change nothing")
    ap.add_argument("--capture", action="store_true",
                    help="re-pin row 5 as the canonical 4a formula row")
    args = ap.parse_args(argv)

    if args.capture:
        return capture(args.workbook)
    if args.check:
        return check(args.workbook)

    s = survey(args.workbook)
    print(report(s))
    if not args.write:
        print("\n(dry run — nothing cleared; add --write to reset the workbook)")
        return 0
    done = apply(s)
    print(f"\nCleared DD ({done['dd_cleared']} rows), order log "
          f"({done['ol_cleared']} rows), {done['bonus_cleared']} bonus row(s).")
    print(f"Re-dragged 4a formulas to row {done['redragged_to']}.")
    print(f"Snapshot saved: {done['snapshot']}")
    return check(args.workbook)


if __name__ == "__main__":
    raise SystemExit(main())
