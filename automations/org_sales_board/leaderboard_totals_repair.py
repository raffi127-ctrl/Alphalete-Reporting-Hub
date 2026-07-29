"""One-off repair: re-align each captainship leaderboard's 'TOTALS' row.

CaptainAnchor.leaderboard stops AT the box's 'TOTALS' row, so the rollover's
step 2 shifted every rep row right but left the totals line standing still. Its
col-C '=SUM' kept the open week correct, so nothing looked wrong — but its
frozen D.. history fell one column further behind every week. By 2026-07-28 it
was 2 columns off on 17 of 18 boxes: the column labelled 'WE 07.26' was showing
WE 07.12's total (Eve). rollover.py now includes the TOTALS row in the shift;
this fixes the accumulated offset ONCE.

The repair is a pure right-shift of the existing static history — NOT a
re-derivation from the rep rows. Roster churn means a departed rep's numbers are
gone from the leaderboard, so old rep sums no longer reproduce the frozen
totals; shifting preserves them exactly. Only the two columns freed at the front
are re-seeded, from the rep sums of the weeks they now represent.

The offset is MEASURED per box against the daily block's WE stack (week-labelled
and authoritative), never assumed — a box already aligned is skipped.

Usage:
    python -m automations.org_sales_board.leaderboard_totals_repair
    python -m automations.org_sales_board.leaderboard_totals_repair --apply
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board import captainship as cap
from automations.org_sales_board import rollover as rl
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB

_WE = re.compile(r"WE\s*0?(\d+)\.0?(\d+)", re.I)
MAX_OFFSET = 4


def _week(label):
    m = _WE.match(str(label).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _num(unf, r, c):
    v = unf[r][c] if r < len(unf) and c < len(unf[r]) else ""
    return v if isinstance(v, (int, float)) else None


def find_boxes(grid, unf):
    """Every captainship leaderboard box with its TOTALS row, the header's last
    week column, and the MEASURED offset of the TOTALS row (0 = aligned)."""
    stacks = {b["header_row"]: b for b in rl.find_week_stacks(grid)}
    out = []
    for title, _t in cap.discover_captainships(grid):
        try:
            boxes = cap.find_captainship_boxes(grid, title)
        except Exception:                                    # noqa: BLE001
            continue
        for variant, a in boxes:
            hdr = a.leaderboard[0][0] - 2
            reps = [r for r, _ in a.leaderboard]
            tot = next((r for r in range(max(reps) + 1, max(reps) + 5)
                        if rl._cell(grid, r - 1, 0).upper().startswith("TOTAL")),
                       None)
            st = next((stacks[h] for h in sorted(stacks) if h > hdr), None)
            if not (tot and st):
                continue
            last_col = max((c + 1 for c in range(2, len(grid[hdr - 1]))
                            if (grid[hdr - 1][c] or "").strip()), default=16)
            weeks = {_week(lab): _num(unf, r - 1, st["j"] - 1)
                     for r, lab in st["stack"] if _week(lab)}
            best, best_hit = 0, -1
            for off in range(MAX_OFFSET + 1):
                hit = 0
                for col in range(4, min(last_col, 16) + 1):
                    w = _week(rl._cell(grid, hdr - 1, col - 1))
                    tv = _num(unf, tot - 1, col - 1 - off)
                    if w in weeks and tv is not None and weeks[w] is not None \
                            and abs(weeks[w] - tv) < 0.5:
                        hit += 1
                if hit > best_hit:
                    best, best_hit = off, hit
            out.append({"title": f"{title}/{variant}", "hdr": hdr, "reps": reps,
                        "totals_row": tot, "last_col": last_col,
                        "offset": best, "matched": best_hit})
    return out


def plan(grid, unf, boxes):
    """Right-shift each mis-aligned TOTALS row by its offset, then re-seed the
    columns freed at the front from the rep sums of those weeks."""
    updates, notes = [], []
    for b in boxes:
        off, tot, last = b["offset"], b["totals_row"], b["last_col"]
        if off == 0:
            continue
        old = [_num(unf, tot - 1, c - 1) for c in range(4, last + 1)]  # D..last
        old = ["" if v is None else v for v in old]
        updates.append({"range": f"{rl.a1col(4 + off)}{tot}:"
                                 f"{rl.a1col(last + off)}{tot}",
                        "values": [old]})
        for i in range(off):                       # the freed front columns
            col = 4 + i
            seed = sum(_num(unf, r - 1, col - 1) or 0 for r in b["reps"])
            updates.append({"range": f"{rl.a1col(col)}{tot}", "values": [[seed]]})
            notes.append((b["title"], f"{rl.a1col(col)}{tot}",
                          rl._cell(grid, b["hdr"] - 1, col - 1),
                          rl._cell(grid, tot - 1, col - 1), seed))
    return updates, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    args = ap.parse_args()

    ws = open_by_key(SHEET_ID).worksheet(args.tab)
    grid = ws.get_all_values()
    unf = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    boxes = find_boxes(grid, unf)
    bad = [b for b in boxes if b["offset"]]
    print(f"{len(boxes)} leaderboard box(es) on {args.tab!r}; "
          f"{len(bad)} mis-aligned\n")
    for b in boxes:
        tag = "aligned" if not b["offset"] else f"OFFSET {b['offset']}"
        print(f"  {b['title']:<28} TOTALS r{b['totals_row']:<6} {tag:<10} "
              f"({b['matched']} week col(s) confirm)")

    updates, notes = plan(grid, unf, boxes)
    print(f"\nre-seeded front columns ({len(notes)}):")
    for title, a1, hdr, was, now in notes:
        print(f"  {title:<28} {a1:<8} {hdr:<10} {was or '(blank)':>8} -> {now}")

    if not args.apply:
        print(f"\n{len(updates)} write(s) planned — preview only, "
              f"re-run with --apply")
        return 0

    undo = Path("output") / "leaderboard_totals_repair_undo.csv"
    undo.parent.mkdir(exist_ok=True)
    with undo.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tab", "box", "totals_row", "col", "old_value"])
        for b in bad:
            for c in range(3, b["last_col"] + 1):
                w.writerow([args.tab, b["title"], b["totals_row"],
                            rl.a1col(c), rl._cell(grid, b["totals_row"] - 1, c - 1)])
    print(f"\nundo written to {undo}")

    ws.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"wrote {len(updates)} range(s) to {args.tab!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
