"""Phase 1 of the override-bulletin fill — roll the sheet forward one week.

The mechanical half of the VA's Friday process (Loom 2026-07-22): insert a fresh
dated week column at the newest-week position, carry the structural formulas, and
zero the typed numbers so the new column starts empty — ready for the Tableau
pulls (Phase 2+) or a human to drop figures in.

WHAT IS KEPT vs CLEARED
  The newest week is the LEFTMOST week column (col E). We insert a new column
  there and reproduce the previous week's column, then clear its data:
    • KEEP  — formulas that REFERENCE other cells: the section-2 leader rows
              (=SUM(E52:E53), =SUM(E61)) and the Total-2026 (=SUM(E:AF)) totals.
    • CLEAR — the hand-typed override amounts. These include literal-only
              "formulas" like =21006.49+57589 or =2576+540, which are just typed
              numbers, NOT structure. The tell is whether a cell reference (a
              column-letter+row like E52) appears; SUM/literal math alone doesn't.

SAFETY
  DRY-RUN by default — reads the sheet and prints the exact plan, writes nothing.
  --write performs the insert; point it at a SANDBOX copy with --sheet-id until
  Megan approves it on production. Never writes to the live sheet unattended.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
TAB = "Org Overrides Ongoing Report"

_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")
# A cell reference like E52 / AF2 — the signal a formula is STRUCTURE (keep), not
# a typed number dressed up as math (=2576+540). Function names (SUM) have no digit.
_CELLREF_RE = re.compile(r"[A-Z]{1,3}\d+")


def _col_letter(idx0: int) -> str:
    """0-based column index -> A1 letter(s)."""
    s = ""
    n = idx0
    while True:
        s = chr(65 + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def _next_week_label(label: str) -> str:
    """'7.12.26' -> '7.19.26' (add 7 days; no leading zeros; 2-digit year)."""
    m, d, y = (int(x) for x in label.split("."))
    y += 2000 if y < 100 else 0
    nxt = dt.date(y, m, d) + dt.timedelta(days=7)
    return f"{nxt.month}.{nxt.day}.{nxt.year % 100}"


def _keep_formula(cell: str) -> bool:
    """True if this formula is STRUCTURE to preserve — it references a cell."""
    return isinstance(cell, str) and cell.startswith("=") and bool(_CELLREF_RE.search(cell))


def plan(ws):
    """Read the sheet and return the roll-forward plan (no writes)."""
    header = ws.row_values(1)
    # Newest week = first cell of the contiguous dated run (col E). Not a blanket
    # scan — the tab carries a long historical weekly block far to the right.
    newest_idx = None
    for i, h in enumerate(header):
        if _WEEK_RE.match((h or "").strip()):
            newest_idx = i
            break
    if newest_idx is None:
        raise RuntimeError("no dated week column found in row 1")
    newest_label = header[newest_idx].strip()
    new_label = _next_week_label(newest_label)

    col = _col_letter(newest_idx)
    formulas = ws.get(f"{col}1:{col}{ws.row_count}", value_render_option="FORMULA")
    keep, clear = [], []
    for r, row in enumerate(formulas, start=1):
        val = row[0] if row else ""
        if r == 1:
            continue                      # header handled separately
        if not str(val).strip():
            continue                      # already empty
        (keep if _keep_formula(val) else clear).append((r, val))
    return {
        "newest_idx": newest_idx, "col": col,
        "newest_label": newest_label, "new_label": new_label,
        "keep": keep, "clear": clear,
    }


def print_plan(p) -> None:
    print(f"ROLL FORWARD  {p['newest_label']}  ->  {p['new_label']}")
    print(f"  insert a new week column at {p['col']} (newest position); "
          f"existing weeks shift right one.")
    print(f"  set {p['col']}1 = {p['new_label']!r}")
    print(f"  KEEP {len(p['keep'])} structural formula(s) (carry into the new column):")
    for r, v in p["keep"][:12]:
        print(f"      {p['col']}{r}: {v}")
    if len(p["keep"]) > 12:
        print(f"      … +{len(p['keep']) - 12} more")
    print(f"  CLEAR {len(p['clear'])} typed number(s) -> blank (starts at zero):")
    for r, v in p["clear"][:8]:
        print(f"      {p['col']}{r}: {v}")
    if len(p["clear"]) > 8:
        print(f"      … +{len(p['clear']) - 8} more")


def apply_plan(ws, p) -> None:
    """Perform the insert. SANDBOX/approved use only — guarded by --write."""
    sid = ws.id
    idx = p["newest_idx"]
    reqs = [
        # 1) insert a blank column at the newest-week position
        {"insertDimension": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                       "startIndex": idx, "endIndex": idx + 1},
                             "inheritFromBefore": False}},
        # 2) duplicate the previous week's column (now shifted to idx+1) into it —
        #    format + formulas + values — so the new column matches exactly
        {"copyPaste": {
            "source": {"sheetId": sid, "startColumnIndex": idx + 1, "endColumnIndex": idx + 2,
                       "startRowIndex": 0, "endRowIndex": ws.row_count},
            "destination": {"sheetId": sid, "startColumnIndex": idx, "endColumnIndex": idx + 1,
                            "startRowIndex": 0, "endRowIndex": ws.row_count},
            "pasteType": "PASTE_NORMAL"}},
    ]
    ws.spreadsheet.batch_update({"requests": reqs})
    # 3) clear the typed numbers in the new column (keep the structural formulas)
    if p["clear"]:
        ws.batch_clear([f"{p['col']}{r}" for r, _v in p["clear"]])
    # 4) stamp the new week-ending label
    ws.update_acell(f"{p['col']}1", p["new_label"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", default=WORKBOOK_ID,
                    help="override the workbook id (use a SANDBOX copy while testing)")
    ap.add_argument("--write", action="store_true",
                    help="ACTUALLY insert the column (default: dry-run, no writes)")
    args = ap.parse_args(argv)

    from automations.recruiting_report import fill as _fill
    ws = _fill._client().open_by_key(args.sheet_id).worksheet(TAB)
    p = plan(ws)
    print_plan(p)
    if not args.write:
        print("\ndry-run — nothing written. Re-run with --write (SANDBOX first) to apply.")
        return 0
    if args.sheet_id == WORKBOOK_ID:
        print("\nREFUSING --write against the production workbook. Pass --sheet-id "
              "<sandbox copy> until Megan approves production.", file=sys.stderr)
        return 2
    apply_plan(ws, p)
    print(f"\nwrote: new column {p['col']} = {p['new_label']!r} on {args.sheet_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
