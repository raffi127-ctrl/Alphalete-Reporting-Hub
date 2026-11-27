"""Interviewer Retention: one office's week, AppStream -> its ARS tab's boxes.

    # print this week's boxes for Raf's office, write nothing (card step 2.7)
    python -m automations.interviewer_retention.run --office 11280 --dry-run
    # write them into the TEST COPY (adds the week's box if the tab has none)
    python -m automations.interviewer_retention.run --office 11280 --sheet <test copy id>

Each run:
  1. reads the office's Calendar (read.py, read-only, hidden browser) for the
     week so far, plus two weeks before so every 2nd round finds its 1st
     round. This week's days are re-read every run: statuses change all week.
  2. builds the three boxes (boxes.py), interviewer names per
     interviewer_names.json; a blank Done By or an unknown name is FLAGGED.
  3. --dry-run: prints the boxes. Otherwise: adds the week's box if missing
     (write.plan_add_box), writes the numbers as plain values, and puts the
     week total next to the name.

THE REAL ARS WORKBOOKS ARE REFUSED until Megan's go after the parallel week
(card steps 4.2 / 4.3); --sheet must be a test copy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.interviewer_retention import boxes as bx
from automations.interviewer_retention import check as ck
from automations.interviewer_retention import from_calendar as fc
from automations.interviewer_retention import offices as of
from automations.interviewer_retention import read as rd
from automations.interviewer_retention import write as wr

LOOKBACK_DAYS = 14


def week_of(day: dt.date) -> dt.date:
    """The ARS label: the Sunday that ENDS the week holding `day`."""
    return day + dt.timedelta(days=6 - day.weekday())


PERCENTS = {"QR", "DiR", "DR", "AR", "BR", "NCR", "R"}


def table(box: List[Dict], block: str) -> str:
    keys = [k for k in ck.DAY_KEYS[block] if k not in PERCENTS]
    head = f"{'interviewer':24}" + "".join(f"{('TOT ' + k):>8}" for k in keys)
    lines = [head]
    for r in box:
        t = r["total"]
        cells = []
        for k in keys:
            v = t.get(k, t.get({"B": "Booked", "S": "Showed"}.get(k, k), sum(d.get(k, 0) for d in r["days"])))
            cells.append(f"{v:>8}")
        lines.append(f"{r['interviewer'][:24]:24}" + "".join(cells))
    return "\n".join(lines)


def fill_week(office: str, day: dt.date, *, sheet: str = "", tab: str = "",
              dry_run: bool = True, show=print) -> Dict:
    """Read the office's week from AppStream, build the three boxes, and (unless
    dry_run) write them into `sheet` -- a TEST COPY only. Returns
    {owner, tab, wb_id, anchor, rows, boxes, flags}."""
    anchor = week_of(day)
    monday = anchor - dt.timedelta(days=6)
    owner = of.owner_of(office)
    hit = of.ars_tab(owner)
    if not hit:
        raise SystemExit(f"{owner} ({office}) has no ARS tab -- card step 3.2")
    wb_title, wb_id, real_tab = hit
    tab = tab or real_tab
    show(f"{owner} ({office}) -> {wb_title} / {tab}; week {monday:%m/%d}-{min(day, anchor):%m/%d}")

    # 1. AppStream
    want = [monday - dt.timedelta(days=LOOKBACK_DAYS) + dt.timedelta(days=i)
            for i in range((min(day, anchor) - monday).days + LOOKBACK_DAYS + 1)]
    want = [d for d in want if d.weekday() != 6]
    have = rd.load_cache(office)
    todo = [d for d in want if d >= monday or d not in have]
    if todo:
        have.update(rd.read_days(office, todo))
        rd.save_cache(office, have)

    # 2. boxes
    rows, unknown, _ = rd.build({d: have[d] for d in want if d in have}, fc.load_names(office))
    boxes = bx.week(rows, anchor)
    flags = []
    from automations.shared import terminated_icds as ti        # card step 4.6: warns, never blocks
    _, term_flag = ti.alert_terminated([owner], "Interviewer Retention")
    if term_flag:
        flags.append(term_flag)
    if unknown:
        flags.append(f"Done By names not on the list: {dict(unknown)}")
    blank = [r for r in boxes["qualified"] if r["interviewer"] == fc.NOT_MARKED]
    if blank:
        flags.append(f"{sum(blank[0]['total'][k] for k in ('Q', 'Di', 'De'))} interviews with Done By left blank")
    for block in ck.BLOCKS:
        show(f"\n{block.upper()} (week of {anchor:%m/%d})\n{table(boxes[block], block)}")
    for f in flags:
        show("FLAG: " + f)
    out = {"owner": owner, "tab": tab, "wb_id": wb_id, "anchor": anchor, "rows": rows,
           "boxes": boxes, "flags": flags}
    if dry_run:
        show("\ndry run: nothing written")
        return out
    if not sheet or sheet == wb_id or sheet in ck_real_ids():
        raise SystemExit("refusing: the sheet must be a TEST COPY until Megan's go (card 4.2/4.3)")

    # 3. write
    from automations.recruiting_report.fill import open_by_key
    ws = open_by_key(sheet).worksheet(tab)
    grid = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    formulas = ws.get_all_values(value_render_option="FORMULA")
    cols, labels, _ = ck.layout(grid)
    if not any(ck._date(grid[k][cols[0]]) == anchor for k in labels):
        reqs, new_row = wr.plan_add_box(grid, formulas, ws.id, anchor)
        if new_row + 40 > ws.row_count:
            ws.add_rows(new_row + 40 - ws.row_count)
        ws.spreadsheet.batch_update({"requests": reqs})
        show(f"added the {anchor:%m/%d} box at row {new_row + 1}")
        grid = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
        formulas = ws.get_all_values(value_render_option="FORMULA")
    ws.batch_update(wr.plan_week(grid, formulas, anchor, boxes), value_input_option="RAW")
    width = max(len(r) for r in grid)
    if ws.col_count < width + 12:
        ws.add_cols(width + 12 - ws.col_count)
    moves = wr.plan_total_move(grid, formulas, ws.id, anchor, width + 2)
    if moves:
        ws.spreadsheet.batch_update({"requests": moves})
    show(f"wrote the {anchor:%m/%d} boxes as plain values" + (", total moved next to the name" if moves else ""))
    return out


def ck_real_ids():
    from automations.first_to_second_below_mark import ars_reports as ar
    return set(ar.ARS_WORKBOOKS.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="interviewer_retention.run")
    ap.add_argument("--office", required=True, help="AppStream office id")
    ap.add_argument("--date", default="", help="YYYY-MM-DD, a day in the week (default today)")
    ap.add_argument("--sheet", default="", help="the TEST COPY to write (required unless --dry-run)")
    ap.add_argument("--tab", default="", help="default: the office's ARS tab name")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    fill_week(a.office, day, sheet=a.sheet, tab=a.tab, dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
