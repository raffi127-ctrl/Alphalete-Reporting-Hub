"""Write the three boxes into an ARS tab as plain VALUES (card steps 3.3, 3.12).

Megan 2026-11-27: "I really don't like hardcoded formulas - we should take over
so that we're right each time and nothing breaks." So for every week we own,
the box cells (interviewer names, every day group, the week total) get the
numbers boxes.py worked out, and the COUNTIFS that were there are gone.

Found by label, never by a fixed cell (check.layout / check.read_box): the
week by the date in the box's label cell, a day group by its day name, a
number by its sub-header. A box's slots are the rows under its header that
carry anything (formulas included); more interviewers than slots is refused
rather than spilling into the next box.

Never touched: the typed interview rows on the left (A..P) and anything
outside the three boxes of the weeks asked for.

    # rebuild 6 weeks on the TEST COPY from the tab's own typed rows (dry first)
    python -m automations.interviewer_retention.write --sheet <test id> --weeks 6 --dry-run
    python -m automations.interviewer_retention.write --sheet <test id> --weeks 6
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.interviewer_retention import boxes as bx
from automations.interviewer_retention import check as ck

TEST_COPY = "1dUUbyM6_cCfuR4y0jRCYEIEgNQNwjcJIC-6t7LzFKDY"   # owned by alphaletereporting@


def _a1(row: int, col: int) -> str:                 # 0-based -> A1
    s, n = "", col + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return f"{s}{row + 1}"


def _groups(grid, label_row: int, c0: int, c_end: int) -> List[Tuple[str, List[Tuple[int, str]]]]:
    """[(day name | 'total', [(col, sub-header)])] for one box, left to right."""
    out, cur = [], None
    days, sub = grid[label_row], grid[label_row + 1]
    for j in range(c0 + 1, c_end):
        name = ck._norm(days[j]) if j < len(days) else ""
        if name:
            cur = ("total" if name.startswith("total") else name, [])
            out.append(cur)
        head = ck._txt(sub[j]).strip() if j < len(sub) else ""
        if cur is not None and head:
            cur[1].append((j, head))
    return out


def _slots(formulas, label_row: int, c0: int, c_end: int) -> List[int]:
    """Rows of this box's interviewer slots: under the header, while the row
    carries anything (a formula, a value) inside the box."""
    rows = []
    for r in range(label_row + 2, len(formulas)):
        row = formulas[r]
        if not any(ck._txt(row[j]).strip() for j in range(c0, min(c_end, len(row)))):
            break
        if c0 < len(row) and ck._date(row[c0]):      # the next box's label
            break
        rows.append(r)
    return rows


def plan_week(grid, formulas, anchor: dt.date, computed: Dict[str, List[Dict]]) -> List[Dict]:
    """[{range, values}] that write one week's three boxes. Raises when a box
    is missing or has fewer slots than interviewers."""
    cols, labels, nxt = ck.layout(grid)
    k = next((r for r in labels if ck._date(grid[r][cols[0]]) == anchor), None)
    if k is None:
        raise LookupError(f"no week box labelled {anchor:%m/%d} on this tab")
    data = []
    for b, block in enumerate(ck.BLOCKS):
        c0, c_end = cols[b], nxt[cols[b]] or len(grid[k])
        if not ck._date(grid[k][c0] if c0 < len(grid[k]) else None):
            raise LookupError(f"{anchor:%m/%d}: the {block} box has no week label on row {k + 1}")
        groups = _groups(grid, k, c0, c_end)
        slots = _slots(formulas, k, c0, c_end)
        people = computed[block]
        if len(people) > len(slots):
            raise ValueError(f"{anchor:%m/%d} {block}: {len(people)} interviewers, "
                             f"only {len(slots)} rows in the box")
        last = max(j for _, cs in groups for j, _ in cs)
        for i, r in enumerate(slots):
            row = [""] * (last - c0 + 1)
            rec = people[i] if i < len(people) else None
            row[0] = rec["interviewer"] if rec else ""
            day_i = 0
            for name, cs in groups:
                if name == "total":
                    keys, vals = ck.TOTAL_KEYS[block], (rec["total"] if rec else {})
                    pick = lambda h: keys.get(ck._norm(h))            # noqa: E731
                else:
                    keys = ck.DAY_KEYS[block]
                    vals = rec["days"][day_i] if rec and day_i < len(rec["days"]) else {}
                    day_i += 1
                    pick = lambda h: keys.get(h)                      # noqa: E731
                for j, h in cs:
                    key = pick(h)
                    if key:
                        row[j - c0] = vals.get(key, 0) if rec else 0
            data.append({"range": f"{_a1(r, c0)}:{_a1(r, last)}", "values": [row]})
    return data


def plan_total_move(grid, formulas, sheet_id: int, anchor: dt.date, temp_col: int) -> List[Dict]:
    """Card step 3.4 (Raf 11/24: "Move total week to be next to recruiter
    name"): batch_update requests that put each box's TOTAL group right after
    the Interviewer column, days shifted right. Cells move with their formats
    (cut + paste), only the rows of this one week's boxes. Already moved -> no
    requests. `temp_col`: an empty column far right used as a parking spot."""
    cols, labels, nxt = ck.layout(grid)
    k = next((r for r in labels if ck._date(grid[r][cols[0]]) == anchor), None)
    if k is None:
        raise LookupError(f"no week box labelled {anchor:%m/%d} on this tab")
    reqs = []

    def cut(r0, r1, c0, c1, to_c):
        return {"cutPaste": {
            "source": {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1 + 1,
                       "startColumnIndex": c0, "endColumnIndex": c1 + 1},
            "destination": {"sheetId": sheet_id, "rowIndex": r0, "columnIndex": to_c},
            "pasteType": "PASTE_NORMAL"}}

    for b, block in enumerate(ck.BLOCKS):
        c0, c_end = cols[b], nxt[cols[b]] or len(grid[k])
        groups = _groups(grid, k, c0, c_end)
        if not groups or groups[0][0] == "total":
            continue                                   # already next to the name
        tot = next((cs for name, cs in groups if name == "total"), None)
        if not tot:
            raise LookupError(f"{anchor:%m/%d} {block}: no TOTAL for the WEEK group")
        t0 = min(j for name, cs in groups if name == "total" for j, _ in cs)
        # the TOTAL label is merged across its group; take the label cell itself
        t0 = min(t0, next(j for j in range(c0 + 1, c_end) if ck._norm(grid[k][j]).startswith("total")))
        t1 = max(j for j, _ in tot)
        d0 = c0 + 1
        last = max(_slots(formulas, k, c0, c_end) or [k + 1])
        w = t1 - t0 + 1
        reqs += [cut(k, last, t0, t1, temp_col),          # park the total
                 cut(k, last, d0, t0 - 1, d0 + w),        # days slide right
                 cut(k, last, temp_col, temp_col + w - 1, d0)]   # total next to the name
    return reqs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.write")
    ap.add_argument("--sheet", default=TEST_COPY)
    ap.add_argument("--tab", default="Rafael Hidalgo")
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--move-total", action="store_true",
                    help="also put each owned week's TOTAL next to the interviewer name")
    ap.add_argument("--from-appstream", default="", metavar="OFFICE",
                    help="build the boxes from AppStream (read.py's cached days for this "
                         "office) instead of the tab's typed rows")
    a = ap.parse_args(argv)
    if a.sheet == ck.ARS_R_TO_Z:
        raise SystemExit("refusing the REAL ARS workbook: test copy only until Megan says go")
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(a.sheet).worksheet(a.tab)
    grid = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    formulas = ws.get_all_values(value_render_option="FORMULA")
    if a.from_appstream:
        from automations.interviewer_retention import from_calendar as fc
        from automations.interviewer_retention import read as rd
        rows, unknown, _ = rd.build(rd.load_cache(a.from_appstream), fc.load_names(a.from_appstream))
        if unknown:
            print(f"FLAG: Done By names not in interviewer_names.json, shown under their "
                  f"AppStream name: {dict(unknown)}")
    else:
        rows = ck.interviews(grid)
    cols, labels, _ = ck.layout(grid)
    today = dt.date.today()
    last_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    weeks = [ck._date(grid[k][cols[0]]) for k in labels if ck._date(grid[k][cols[0]]) <= last_sunday][-a.weeks:]
    data = []
    for anchor in weeks:
        data += plan_week(grid, formulas, anchor, bx.week(rows, anchor))
    cells = sum(len(d["values"][0]) for d in data)
    print(f"{a.tab}: {len(weeks)} weeks ({weeks[0]:%m/%d}-{weeks[-1]:%m/%d}), {len(data)} box rows, {cells} cells")
    if a.dry_run:
        print("dry run: nothing written")
        return 0
    ws.batch_update(data, value_input_option="RAW")
    print("written as plain values")
    if a.move_total:
        width = max(len(r) for r in grid)
        temp = width + 2
        if ws.col_count < temp + 10:
            ws.add_cols(temp + 10 - ws.col_count)
        reqs = []
        for anchor in weeks:
            reqs += plan_total_move(grid, formulas, ws.id, anchor, temp)
        if reqs:
            ws.spreadsheet.batch_update({"requests": reqs})
        print(f"week total moved next to the name: {len(reqs) // 3} boxes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
