"""One-off repair of the ORG Sales Board's prior-week columns (K/L).

Background — the rollover never seeded the TOP of each block's week stack, so
"LAST WEEK'S TOTALS" / "PREVIOUS WEEK'S TOTALS" on the 'Totals' row went stale
(2 weeks behind by 2026-07-28) and the captainship week-log rows were left
blank by the automated insert. rollover.apply_prior_week_totals now re-derives
them every Tuesday; this script fixes the accumulated state ONCE.

Rule (see rollover.py): for any row of a block's week stack,
  K = col-J total of the row ONE week older, L = col-J of TWO weeks older.

Two things this script adds on top of the recurring pass:
  • the 8 daily-section blocks only keep 4 history rows, so their bottom cells
    need weeks that already fell off. WE 6.28 is recovered from the VA tab
    ('Alphalete ORG Sales Board'), which runs exactly one week behind the copy,
    so its '3 Weeks Prior' row IS WE 6.28.
  • '3 Weeks Prior'!L needs WE 6.21, which exists on neither tab — it is
    BLANKED rather than left showing a number from the wrong week (Eve
    2026-07-28: "nada es irrelevante, todos miramos los históricos").

Usage:
    python output/org_board_prior_week_repair.py            # preview only
    python output/org_board_prior_week_repair.py --apply    # write
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board import rollover as rl
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB, PROD_TAB

HIST = rl._HIST_ROW_LABELS


def _is_campaign(block) -> bool:
    """A daily-section block — its stack is the 4 'Last Week'…'3 Weeks Prior'
    rows (the captainship blocks carry dated 'WE m.d' rows instead)."""
    return any(lab.lower() in HIST for _r, lab in block["stack"])


def build_extra(copy_blocks, va_grid, logfn=print):
    """{header_row: [WE 6.28 total]} for each daily-section block, taken from
    the VA tab's own '3 Weeks Prior' row for the SAME named section."""
    va = {b["name"]: b for b in rl.find_week_stacks(va_grid)}
    extra, missing = {}, []
    for b in copy_blocks:
        if not _is_campaign(b):
            continue
        vb = va.get(b["name"])
        if not vb:
            missing.append(b["name"])
            continue
        row = next((r for r, lab in vb["stack"]
                    if lab.lower() == "3 weeks prior"), None)
        if row is None:
            missing.append(b["name"])
            continue
        val = rl._cell(va_grid, row - 1, vb["j"] - 1).replace(",", "")
        try:
            extra[b["header_row"]] = [float(val) if "." in val else int(val)]
        except ValueError:
            missing.append(f"{b['name']} (unparsable {val!r})")
        else:
            logfn(f"    {b['name']:<18} WE 6.28 = {extra[b['header_row']][0]} "
                  f"(VA tab '3 Weeks Prior', row {row})")
    if missing:
        logfn(f"    ! no VA WE 6.28 for: {', '.join(missing)}")
    return extra


def blanks_for_lost_week(copy_blocks):
    """'3 Weeks Prior'!L on each daily-section block — its source week (WE 6.21)
    is on neither tab, so blank it instead of showing the wrong week."""
    out = []
    for b in copy_blocks:
        if not _is_campaign(b):
            continue
        row = next((r for r, lab in b["stack"]
                    if lab.lower() == "3 weeks prior"), None)
        if row is not None:
            out.append({"range": f"{rl.a1col(b['l'])}{row}", "values": [[""]]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default: preview only)")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    args = ap.parse_args()

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(args.tab)
    grid = ws.get_all_values()
    va_grid = sh.worksheet(PROD_TAB).get_all_values()

    blocks = rl.find_week_stacks(grid)
    print(f"{len(blocks)} block(s) on {args.tab!r} "
          f"({sum(1 for b in blocks if _is_campaign(b))} daily-section, "
          f"{sum(1 for b in blocks if not _is_campaign(b))} captainship)")
    print("  recovering the week that fell off the daily-section blocks:")
    extra = build_extra(blocks, va_grid)

    updates = rl.plan_prior_week_totals(ws, blocks, extra=extra)
    updates += blanks_for_lost_week(blocks)

    # report only the cells that actually change
    by_range = {u["range"]: u for u in updates}
    changed = []
    for b in blocks:
        for row, lab in b["stack"]:
            for col, which in ((b["k"], "K"), (b["l"], "L")):
                rng = f"{rl.a1col(col)}{row}"
                if rng not in by_range:
                    continue
                cur = rl._cell(grid, row - 1, col - 1).replace(",", "")
                new = str(by_range[rng]["values"][0][0])
                if cur != new:
                    changed.append((b["name"], rng, lab, which, cur, new))
    print(f"\n{len(updates)} cell(s) derived, {len(changed)} differ from the sheet\n")
    name = None
    for nm, rng, lab, which, cur, new in changed:
        if nm != name:
            print(f"  [{nm}]")
            name = nm
        print(f"     {rng:<8} {lab:<14} {which}  {cur or '(blank)':>10}"
              f"  ->  {new or '(blank)'}")

    if not args.apply:
        print("\npreview only — re-run with --apply to write")
        return 0

    # Precise undo: every cell about to change, with the value it holds now.
    # The rollover's own backup tab only covers the pre-ROLLOVER state, which is
    # not the state this script is about to overwrite.
    undo = Path(__file__).with_name("org_board_prior_week_repair_undo.csv")
    with undo.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tab", "range", "block", "row_label", "col", "old_value"])
        for nm, rng, lab, which, cur, _new in changed:
            w.writerow([args.tab, rng, nm, lab, which, cur])
    print(f"\nundo written to {undo}")

    ws.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"wrote {len(updates)} cell(s) to {args.tab!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
