"""Backfill ONE past week of NDS sales from the tracker's `(LW)` twin sheet.

The NDS tracker has no date control, so opt_nds can only ever fill the week it
is run in — which is why the Focus Report is a Monday job. But the Crosstab
dialog lists a `(LW)` twin of every sheet, and that twin holds the week BEFORE
the one on screen (found 2026-09-07, see org_active_headcount.backfill
.nds_last_week, where it was cross-checked owner by owner against the focus
tabs). So on any day of week W, this reaches week W-1.

That is the only route to a past week for the owners Sara Plus does not carry
(14 of the 47 tracker owners are ours; the rest have no Sara row at all), which
is what Eve asked for on 2026-09-22: "completemos las ventas con el tracker de
NDS ... ese contiene todas las ventas de la semana porque va de lunes a
domingo".

WHAT IT WRITES, per owner tab, into the target week's column only:
    New Lines          <- tracker 'Phone'      (its New/Port line count)
    AIR                <- tracker 'Air Sold'
    Active Selling Heads <- 'Rep Count'
    Scorecard Ranking  <- 'Ranking'

ONLY INTO EMPTY CELLS. An owner Sara Plus does carry keeps the Sara number:
the two sources do not agree to the cell (Drew Tepper WE 9/6 — Sara 176 new
lines / 19 AIR, tracker 195 / 7), so overwriting one with the other would
silently change what a filled week means.

    python -m automations.alphalete_org_report.nds_lastweek_fill \
        --sheet-id <id> [--week YYYY-MM-DD] [--dry-run]

The week is read OUT OF THE EXPORT (its 'Currently Viewing' caption minus a
week), never computed from today's date. --week is an optional safety check:
pass the week you expect and the run writes nothing if the export disagrees.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from gspread.utils import rowcol_to_a1 as _a1

from automations.alphalete_org_report import opt_nds
from automations.recruiting_report import fill as rfill
from automations.shared.tableau_patchright import (
    tableau_session,
    download_crosstab_patchright,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, same guard as opt_nds
    pass

TRACKER_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
               "NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1")
LW_SHEET = "TT-LineN/P Detail (LW)"
OUT_NAME = "opt_nds_tt_detail_lw.csv"

# sheet row label -> key in parse_tt_detail's record
ROWS = {
    "New Lines": "phone",
    "AIR": "air_sold",
    "Active Selling Heads": "rep_count",
    "Scorecard Ranking": "ranking",
}


def week_from_export(path: Path) -> dt.date | None:
    """The WE Sunday the `(LW)` export actually holds, read out of the export.

    NEVER computed from today's date. The tracker's own week does not flip at
    midnight Sunday — on Monday 2026-09-07 the main sheet was still showing
    08/31-09/06 — so "today minus N days" gets the week wrong on exactly the
    days this is most likely to be run. Every row instead carries a
    'Currently Viewing' caption with the MAIN sheet's range (e.g.
    '08/31 - 09/06'), and the (LW) twin's data is the week BEFORE that one:
    verified 2026-09-07, when the file captioned 08/31-09/06 matched the
    08/24-08/30 tracker owner for owner (Aiden Atoori 484 lines / 4 AIR).

    Returns None when the caption is missing or unparseable — the caller then
    writes nothing rather than guessing a column.
    """
    rows = opt_nds._read_tab_csv(path)
    if not rows:
        return None
    header = rows[0]
    try:
        cap_i = next(i for i, h in enumerate(header)
                     if (h or "").strip().lower() == "currently viewing")
    except StopIteration:
        return None
    for r in rows[1:]:
        caption = (r[cap_i] if cap_i < len(r) else "").strip()
        m = re.search(r"(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})", caption)
        if not m:
            continue
        month, day = int(m.group(3)), int(m.group(4))
        # The caption carries no year. Anchor it to the year whose <month>/<day>
        # is nearest today, so a December/January run can't land 12 months off.
        today = dt.date.today()
        best = min((dt.date(y, month, day) for y in
                    (today.year - 1, today.year, today.year + 1)),
                   key=lambda d: abs((d - today).days))
        main_week_end = best
        if main_week_end.weekday() != 6:      # caption ends on the Sunday
            return None
        return main_week_end - dt.timedelta(days=7)
    return None


def run(sheet_id: str, week: dt.date | None = None, dry_run: bool = False,
        skip_download: bool = False, logfn=print) -> dict:
    out_path = opt_nds.OUTPUT_DIR / OUT_NAME
    if not skip_download:
        with tableau_session(verbose=False) as page:
            download_crosstab_patchright(TRACKER_URL, LW_SHEET, out_path,
                                         page=page)
    found = week_from_export(out_path)
    if found is None:
        logfn("NDS (LW): the export has no readable 'Currently Viewing' week - "
              "nothing written (a column guessed from today's date would be "
              "the one thing this must never do)")
        _describe_export(out_path, logfn)
        return {"filled": [], "skipped": [], "cells": 0, "week": None}
    if week and week != found:
        logfn(f"NDS (LW): asked for WE {week} but the export holds WE {found} - "
              f"nothing written")
        return {"filled": [], "skipped": [], "cells": 0, "week": found}
    week = found
    detail = opt_nds.parse_tt_detail(out_path)
    if not detail:
        logfn(f"NDS (LW): {out_path} parsed 0 owners - nothing written")
        return {"filled": [], "skipped": [], "cells": 0}
    logfn(f"NDS (LW): {len(detail)} owner(s) for WE {week}")

    sh = rfill.open_by_key(sheet_id)
    tabs = [w for w in sh.worksheets() if w.title.endswith(" - NDS")]
    filled, skipped, data = [], [], []
    for ws in tabs:
        owner = opt_nds._norm_owner(ws.title[: -len(" - NDS")])
        rec = detail.get(owner)
        if rec is None:
            skipped.append(f"{ws.title}: not on the tracker")
            continue
        grid = rfill._retry(ws.get_all_values)
        cols = rfill.find_sunday_columns(grid, header_row_idx=0)
        col = cols.get(week)
        if col is None:
            skipped.append(f"{ws.title}: no {week} column")
            continue
        wrote = []
        for label, key in ROWS.items():
            value = str(rec.get(key, "")).strip()
            if not value:
                continue
            row = _row_for_label(grid, label)
            if row is None:
                continue
            current = grid[row - 1][col - 1] if len(grid[row - 1]) >= col else ""
            if str(current).strip():
                continue          # already filled - never overwrite
            data.append({"range": f"'{ws.title}'!{_a1(row, col)}",
                         "values": [[value]]})
            wrote.append(f"{label}={value}")
        if wrote:
            filled.append(ws.title)
            logfn(f"  [{'DRY' if dry_run else 'OK'}] {ws.title}: {', '.join(wrote)}")
        else:
            skipped.append(f"{ws.title}: nothing empty to fill")
    if data and not dry_run:
        sh.values_batch_update({"valueInputOption": "RAW", "data": data})
    logfn(f"NDS (LW): {len(data)} cell(s) on {len(filled)} tab(s); "
          f"{len(skipped)} tab(s) untouched")
    return {"filled": filled, "skipped": skipped, "cells": len(data),
            "week": week}


def _describe_export(path: Path, logfn=print) -> None:
    """Print enough of the export to tell WHY its week could not be read:
    size, header, and the first data row. Diagnosis only — reads nothing else
    and changes nothing."""
    try:
        size = path.stat().st_size
    except OSError as e:
        logfn(f"NDS (LW): cannot stat {path}: {e}")
        return
    rows = opt_nds._read_tab_csv(path)
    logfn(f"NDS (LW): {path.name} is {size:,} bytes, parsed {len(rows)} row(s)")
    if rows:
        logfn(f"NDS (LW): header = {rows[0][:12]}")
        if len(rows) > 1:
            logfn(f"NDS (LW): first row = {rows[1][:12]}")
        header = [(h or "").strip().lower() for h in rows[0]]
        if "currently viewing" in header:
            cap_i = header.index("currently viewing")
            seen = []
            for r in rows[1:]:
                cap = (r[cap_i] if cap_i < len(r) else "").strip()
                if cap and cap.lower() != "total" and cap not in seen:
                    seen.append(cap)
                if len(seen) >= 3:
                    break
            logfn(f"NDS (LW): 'Currently Viewing' values = {seen or '(none)'}")


def _row_for_label(grid, label: str):
    """1-indexed row whose column B is exactly `label` (never a fixed index —
    the templates move)."""
    want = label.strip().lower()
    for i, row in enumerate(grid, start=1):
        if len(row) > 1 and str(row[1]).strip().lower() == want:
            return i
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", required=True)
    ap.add_argument("--week", metavar="YYYY-MM-DD",
                    help="The WE Sunday the (LW) twin holds. Default: the "
                         "Sunday before the most recent one.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the crosstab already in output/.")
    args = ap.parse_args()
    wk = dt.date.fromisoformat(args.week) if args.week else None
    if wk and wk.weekday() != 6:
        raise SystemExit(f"--week {wk} is not a Sunday; the sheet's columns "
                         f"are WE Sundays.")
    res = run(args.sheet_id, wk, dry_run=args.dry_run,
              skip_download=args.skip_download)
    print(f"\nWeek in the export: {res['week']}; "
          f"tabs filled: {len(res['filled'])}; cells: {res['cells']}")
    if not res["cells"]:
        raise SystemExit(1)
