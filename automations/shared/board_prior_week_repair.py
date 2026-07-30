"""One-off state repair of the prior-week columns (K/L) on the Country Sales
Board and the All Campaigns Org Sales Board.

Same defect Eve caught on the ORG Sales Board 2026-07-28, same rule (see
org_sales_board/rollover.py). On every row of a block's week stack — the
'Totals' row at the top and each 'WE m.d' row below it:

    K ("LAST WEEK'S TOTALS")     = the col-J total of the row ONE week older
    L ("PREVIOUS WEEK'S TOTALS") = the col-J total of the row TWO weeks older

Neither board's rollover maintained those columns. The per-rep J→K→L shift in
the day block never reaches the stack, so the 'Totals' row's K/L sat frozen at
whatever a human last typed and every week row the roll inserts came in with
K/L blank (plus some 8165 / 6884 values copied in from the ORG template).

The rollovers now re-derive the stack every Tuesday
(country_sales_board.rollover step 4b / all_campaigns_board.rollover step 4b).
This script fixes the ALREADY accumulated state once.

A stack row at the very BOTTOM of a block needs weeks that have fallen off it,
so the rule cannot produce a value. Those cells are LEFT ALONE by default — on
the Country board the oldest rows carry real totals from weeks the board no
longer lists, and blanking them would destroy history. `--blank-unsourced`
blanks them instead; use it only where the values are known to be wrong (the All
Campaigns tab's oldest row carries 8165 / 6884, which are Country-board totals
copied in with the template — the whole tab runs at ~4,000 a week).

Usage (undo CSVs land in output/):
    python -m automations.shared.board_prior_week_repair                 # preview both
    python -m automations.shared.board_prior_week_repair --board country # preview one
    python -m automations.shared.board_prior_week_repair --apply         # write
    python -m automations.shared.board_prior_week_repair --board allcamp --blank-unsourced --apply
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board import rollover as rl

OUT_DIR = Path(__file__).resolve().parents[2] / "output"

BOARDS = {
    "country": ("Country Sales Board",
                "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE",
                "Country Sales Board"),
    "allcamp": ("All Campaigns Org Sales Board",
                "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E",
                "All Campaigns Org Sales Board"),
}


def unsourced(grid, blocks) -> list:
    """(a1, row_label, current_value) for the cells at the BOTTOM of a stack
    whose source week is off the block — the rule cannot produce a value for
    them. Left alone unless --blank-unsourced says otherwise."""
    out = []
    for b in blocks:
        st = b["stack"]
        for i, (row, lab) in enumerate(st):
            for col, step in ((b["k"], 1), (b["l"], 2)):
                if i + step < len(st):
                    continue                      # derivable — the rule handles it
                cur = rl._cell(grid, row - 1, col - 1)
                if cur:
                    out.append((f"{rl.a1col(col)}{row}", lab, cur))
    return out


def repair(key: str, apply: bool, blank_unsourced: bool = False) -> list:
    name, sheet_id, tab = BOARDS[key]
    print("=" * 74)
    print(f"{name}  —  tab {tab!r}")
    sh = open_by_key(sheet_id)
    ws = next((w for w in sh.worksheets() if w.title.strip() == tab.strip()), None)
    if ws is None:
        print(f"  ❌ tab {tab!r} not found")
        return []
    grid = _retry(ws.get_all_values)
    blocks = rl.find_week_stacks(grid)
    if not blocks:
        print("  no block carries the prior-week columns — nothing to do")
        return []
    for b in blocks:
        print(f"  block {b['name']!r}: header row {b['header_row']}, "
              f"J={rl.a1col(b['j'])} K={rl.a1col(b['k'])} L={rl.a1col(b['l'])}, "
              f"{len(b['stack'])} stack row(s) "
              f"({b['stack'][0][1]} … {b['stack'][-1][1]})")

    updates = rl.plan_prior_week_totals(ws, blocks)
    orphans = unsourced(grid, blocks)
    if orphans:
        verb = "BLANKING" if blank_unsourced else "leaving alone"
        print(f"  {len(orphans)} cell(s) whose source week is off the block — "
              f"{verb}: " + ", ".join(f"{a1}({lab})={cur}"
                                      for a1, lab, cur in orphans))
    if blank_unsourced:
        updates += [{"range": a1, "values": [[""]]} for a1, _l, _c in orphans]

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
                    changed.append((tab, b["name"], rng, lab, which, cur, new))

    print(f"\n  {len(updates)} cell(s) derived, {len(changed)} differ from the tab")
    for _t, nm, rng, lab, which, cur, new in changed:
        print(f"     {rng:<8} {lab:<12} {which}  {cur or '(blank)':>10}  ->  "
              f"{new or '(blank)'}")

    if apply and updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        print(f"  ✅ wrote {len(updates)} cell(s) to {tab!r}")
        after = rl.check_prior_week_totals(_retry(ws.get_all_values))
        print(f"  self-check: {len(after)} residual violation(s)"
              + (f" — {after[:3]}" if after else ""))
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=sorted(BOARDS) + ["both"], default="both")
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheets (default: preview only)")
    ap.add_argument("--blank-unsourced", action="store_true",
                    help="also blank the bottom-of-stack cells the rule cannot "
                         "derive (only where their current values are known to "
                         "be wrong — see the module docstring)")
    args = ap.parse_args()

    keys = sorted(BOARDS) if args.board == "both" else [args.board]
    changed = []
    for k in keys:
        changed += repair(k, args.apply, args.blank_unsourced)

    if not args.apply:
        print("\npreview only — re-run with --apply to write")
        return 0
    # Precise undo: every cell that changed, with the value it held before.
    # The rollover backup tabs only cover the pre-ROLLOVER state, which is not
    # the state this script overwrites.
    OUT_DIR.mkdir(exist_ok=True)
    undo = OUT_DIR / f"board_prior_week_repair_undo_{args.board}.csv"
    with undo.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tab", "block", "range", "row_label", "col", "old_value"])
        for tab, nm, rng, lab, which, cur, _new in changed:
            w.writerow([tab, nm, rng, lab, which, cur])
    print(f"\nundo written to {undo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
