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
LIVE_TAB = "Org Overrides Ongoing Report"
# Sandbox is a COPY TAB in the SAME workbook (the org-board sandbox pattern), so
# the write-guard keys on the TAB NAME, not the workbook id: --write is refused
# against LIVE_TAB and allowed on any other tab (e.g. "Copy of …") until approved.
SANDBOX_TAB = "Copy of Org Overrides Ongoing Report"

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
    keep, clear, relabel = [], [], []
    for r, row in enumerate(formulas, start=1):
        val = row[0] if row else ""
        if r == 1:
            continue                      # header handled separately
        if not str(val).strip():
            continue                      # already empty
        if str(val).strip() == newest_label:
            # A SECOND header row carrying the same week label — section 2
            # ("CAPTAIN/SPECIAL OVERRIDES ONLY") repeats the week headers over its
            # own block. It looks like a typed value, so it used to be CLEARED,
            # leaving section 2's newest column unlabelled while section 1 was
            # labelled — every downstream lookup that finds section-2 columns by
            # week header then silently missed the new week. Found by row, never
            # hardcoded: any row repeating the newest label gets the new one.
            relabel.append((r, val))
            continue
        (keep if _keep_formula(val) else clear).append((r, val))
    return {
        "newest_idx": newest_idx, "col": col,
        "newest_label": newest_label, "new_label": new_label,
        "keep": keep, "clear": clear, "relabel": relabel,
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
    print(f"  RELABEL {len(p.get('relabel') or [])} repeated week-header row(s) "
          f"-> {p['new_label']!r}:")
    for r, v in (p.get("relabel") or []):
        print(f"      {p['col']}{r}: {v} -> {p['new_label']}")


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
    # 4) stamp the new week-ending label — in row 1 AND in every other header row
    #    that repeats it (section 2 has its own week-header row).
    ws.batch_update([{"range": f"{p['col']}1", "values": [[p["new_label"]]]}]
                    + [{"range": f"{p['col']}{r}", "values": [[p["new_label"]]]}
                       for r, _v in (p.get("relabel") or [])],
                    value_input_option="USER_ENTERED")
    # 5) fix the Total-2026 (col D) sums. Inserting at the START of =SUM(E:AF)
    #    shifts it to =SUM(F:AG) — EXCLUDING the new week. Force the start back to
    #    the new newest-week column so the new week counts in the total (the live
    #    sheet keeps the newest week in the total).
    dcol = _col_letter(idx - 1)
    dvals = ws.get(f"{dcol}1:{dcol}{ws.row_count}", value_render_option="FORMULA")
    fixes = []
    for r, row in enumerate(dvals, start=1):
        m = re.match(r"^=SUM\([A-Z]+\d+:([A-Z]+\d+)\)$", str(row[0] if row else ""))
        if m:
            fixes.append({"range": f"{dcol}{r}",
                          "values": [[f"=SUM({p['col']}{r}:{m.group(1)})"]]})
    if fixes:
        ws.batch_update(fixes, value_input_option="USER_ENTERED")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", default=WORKBOOK_ID, help="workbook id")
    ap.add_argument("--tab", default=LIVE_TAB,
                    help=f"tab to operate on (default {LIVE_TAB!r}; --write refuses it, "
                         f"use {SANDBOX_TAB!r} to test)")
    ap.add_argument("--write", action="store_true",
                    help="ACTUALLY insert the column (default: dry-run, no writes)")
    args = ap.parse_args(argv)

    from automations.recruiting_report import fill as _fill
    ws = _fill._client().open_by_key(args.sheet_id).worksheet(args.tab)
    p = plan(ws)
    print(f"[{args.tab}]")
    print_plan(p)
    if not args.write:
        print("\ndry-run — nothing written. Re-run with --write on the sandbox tab to apply.")
        return 0
    if args.tab == LIVE_TAB:
        print(f"\nREFUSING --write against the live tab {LIVE_TAB!r}. Pass "
              f"--tab {SANDBOX_TAB!r} until Megan approves the live tab.", file=sys.stderr)
        return 2
    apply_plan(ws, p)
    print(f"\nwrote: new column {p['col']} = {p['new_label']!r} on tab {args.tab!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
