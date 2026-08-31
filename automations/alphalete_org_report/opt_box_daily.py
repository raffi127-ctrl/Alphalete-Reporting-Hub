"""BOX OPT fill for the ICDs that only the **Box Daily Tracker** carries.

WHY THIS EXISTS, and why it is not just another owner in `opt_box.py`.

`opt_box` reads `B2BBOXEnergyTracker` -> view `BoxSalesMetrics` -> worksheet
'Sales Metrics'. That view is scoped: on 2026-08-31 it returned THREE owners
(Carlos 15, Roshan 78, Ryan 53). The workbook has ELEVEN published views and
each one's `Owner Name` list is its own — `BoxOrderLog/ALLEXPORDERLOG` and
`BoxTierBonus-RepLevel` show four owners, while **`BoxDailyTracker` shows ten**:

    Abel Draper, Alexander Badawi, Calvin Ribera, Carlos Hidalgo,
    Demetrius Pruitt, Helen Assefaw, Joy Gray, Roshan Ahmad,
    Ryan McSpadden, William Fritz

Calvin Ribera (Vernon, Inc., ownerville office 22162, Chicago IL) is in the
second list and not the first, so `opt_box` could never fill him: it would look
him up in a view he is not in and write nothing, silently. That is exactly what
happened for a month while his tab was (wrongly) treated as B2B.

TWO TRAPS ON THIS VIEW — both cost a day, both are load-bearing here:

  * `Owner Name` is an **Exclusive** quick filter. `?Owner Name=Calvin Ribera`
    in the URL REMOVES him from the export (the pull came back with the other
    nine owners and a total exactly 27 short — his week). So we never slice by
    URL: pull the whole grid, match the owner in Python.
  * `Sale Date Weekending` cannot be pinned — not by URL, not by clicking a
    member (which lands the control on `(All)`). So this fill is a CURRENT-WEEK
    fill, like `opt_box`, and the target week comes from the export's own day
    columns, never from today's date.

Sources, per run, one Tableau session:
  * 'Daily Tracker Sales'   — Owner x day. The day headers give the week we
    are filling, and the week's Total Box CX's is SUMMED from that week's day
    columns — never read off 'Grand Total', which is the owner's all-time
    number whenever the week filter is sitting on `(All)`.
  * 'Daily Tracker Metrics' — Owner x metric, plus a Grand Total row that is
    the National AVG for every tab.

Mapping (sheet row label -> source), looked up BY LABEL, never by index:
  Active Selling Heads           <- 'Selling Rep Count'
  Total Box CX's                 <- that week's day columns, summed
  AVG Kwh Usage Per CX           <- 'Avg kWH/Sale'
  AVG Sales per Leader           =  Total Box CX's / Active Selling Heads (formula)
  National AVG for sales         <- Grand Total 'Sales/ Rep'      (SHARED)
  National AVG kwH Usage per CX  <- Grand Total 'Avg kWH/Sale'    (SHARED)

NOT filled: Accepted %, Completed %, WTD KwH, Scorecard Ranking, Personal
Production, the churn/cancel block and the financial block — no source in this
view. They stay blank rather than being estimated.

    python -m automations.alphalete_org_report.opt_box_daily            # dry-run
    python -m automations.alphalete_org_report.opt_box_daily --write
    python -m automations.alphalete_org_report.opt_box_daily --from-file out.csv
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread

from automations.recruiting_report import fill as rfill

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "B2BBOXEnergyTracker/BoxDailyTracker?:refresh=yes")
SALES_SHEET = "Daily Tracker Sales"
METRICS_SHEET = "Daily Tracker Metrics"

# ICDs filled from this view: (tracker owner, spreadsheet id, tab).
# Calvin's tab lives on Raf's ATT Program - Focus Report, not the Org sheet —
# same cross-sheet arrangement opt_b2b uses, and for the same reason.
ATT_FOCUS_SHEET_ID = "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE"
TARGETS: List[Tuple[str, str, str]] = [
    # The tab was renamed 2026-08-31: it was cut from the B2B template and
    # carried a "(B2B)" suffix and the "Ribero" spelling; both were wrong. It
    # is a BOX tab now and ownerville spells him "Ribera".
    ("Calvin Ribera", ATT_FOCUS_SHEET_ID, "Calvin Ribera (BOX)"),
]

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
DAY_HDR = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*\((\d{2})-(\d{2})\)$")
GRAND = ("grand total", "total", "total general")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def _num(v):
    v = str(v or "").strip().replace(",", "").replace("%", "")
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _read(path: Path):
    from automations.alphalete_org_report.opt_nds import _read_tab_csv
    return _read_tab_csv(Path(path))


def target_week(header, today: Optional[dt.date] = None) -> Optional[dt.date]:
    """The Sunday the export covers, read off its own day columns.

    Headers are 'Mon (08-24)' — weekday + M-D, no year — so the year comes from
    `today` and is stepped back a year if that would put the week in the
    future (a January export carrying December days).
    """
    today = today or dt.date.today()
    days = []
    for h in header:
        m = DAY_HDR.match(str(h or "").strip())
        if not m:
            continue
        wd, mm, dd = m.group(1), int(m.group(2)), int(m.group(3))
        for year in (today.year, today.year - 1):
            try:
                d = dt.date(year, mm, dd)
            except ValueError:
                continue
            if d.weekday() == WEEKDAYS[wd] and d <= today + dt.timedelta(days=1):
                days.append(d)
                break
    if not days:
        return None
    last = max(days)
    return last + dt.timedelta(days=6 - last.weekday())


def _day_columns(header, week: dt.date) -> List[int]:
    """Indices of the day columns that fall inside `week` (its Mon..Sun)."""
    monday = week - dt.timedelta(days=6)
    out = []
    for i, h in enumerate(header):
        m = DAY_HDR.match(str(h or "").strip())
        if not m:
            continue
        wd, mm, dd = m.group(1), int(m.group(2)), int(m.group(3))
        for year in (week.year, week.year - 1, week.year + 1):
            try:
                d = dt.date(year, mm, dd)
            except ValueError:
                continue
            if d.weekday() == WEEKDAYS[wd] and monday <= d <= week:
                out.append(i)
                break
    return out


def parse_sales(rows) -> Tuple[Dict[str, int], Optional[dt.date]]:
    """{owner -> week total} off 'Daily Tracker Sales', plus the week it covers.

    The week total is SUMMED from the day columns that belong to that week —
    never read off the 'Grand Total' column. They agree on a normal one-week
    export, but if the `Sale Date Weekending` filter is ever left on `(All)`
    (which is easy: clicking any member of it lands there), Grand Total is the
    owner's ALL-TIME number — 622 instead of 27 for Calvin on 2026-08-31 — and
    a fill that trusted it would write two years of sales into one week.
    """
    if not rows:
        return {}, None
    header = [str(h or "").strip().lstrip("﻿") for h in rows[0]]
    week = target_week(header)
    if week is None:
        return {}, None
    cols = _day_columns(header, week)
    out: Dict[str, int] = {}
    for r in rows[1:]:
        owner = str(r[0] or "").strip()
        if not owner or _norm(owner) in GRAND:
            continue
        vals = [_num(r[i]) for i in cols if i < len(r)]
        vals = [v for v in vals if v is not None]
        if vals:
            out[_norm(owner)] = int(sum(vals))
    return out, week


def parse_metrics(rows) -> Tuple[Dict[str, Dict], Dict]:
    """({owner -> metrics}, national) off 'Daily Tracker Metrics'."""
    if not rows:
        return {}, {}
    header = [_norm(h) for h in rows[0]]

    def col(name):
        n = _norm(name)
        return header.index(n) if n in header else None

    c_owner = col("Owner Name")
    c_sell = col("Selling Rep Count")
    c_spr = col("Sales/ Rep")
    c_kwh = col("Avg kWH/Sale")
    per, national = {}, {}
    for r in rows[1:]:
        owner = str(r[c_owner] or "").strip() if c_owner is not None else ""
        vals = {
            "selling_reps": _num(r[c_sell]) if c_sell is not None else None,
            "sales_per_rep": _num(r[c_spr]) if c_spr is not None else None,
            "kwh_per_sale": _num(r[c_kwh]) if c_kwh is not None else None,
        }
        if _norm(owner) in GRAND:
            national = vals
        elif owner:
            per[_norm(owner)] = vals
    return per, national


def _find_row(grid, label) -> Optional[int]:
    want = _norm(label)
    for i, r in enumerate(grid):
        if len(r) > 1 and _norm(r[1]) == want:
            return i
    return None


def _find_week_col(grid, week: dt.date) -> Optional[int]:
    """Column whose header row 1 holds this Sunday — by DATE, never by index."""
    for j, v in enumerate(grid[0]):
        v = str(v or "").strip()
        if not re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", v):
            continue
        m, d, y = (int(x) for x in v.split("/"))
        if dt.date(y + 2000 if y < 100 else y, m, d) == week:
            return j
    return None


def fill_tab(ws, total_cx: Optional[int], metrics: Dict, national: Dict,
             week: dt.date, dry_run: bool = True, logfn=print) -> List[str]:
    """Write the BOX metrics this view can answer into `week`'s column."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return ["[skip-boxdaily] {}: empty tab".format(ws.title)]
    col = _find_week_col(grid, week)
    if col is None:
        return ["[skip-boxdaily] {}: no column for week {}".format(
            ws.title, week)]
    a1c = gspread.utils.rowcol_to_a1(1, col + 1).rstrip("1")

    cx_row = _find_row(grid, "Total Box CX's")
    ash_row = _find_row(grid, "Active Selling Heads")
    updates: List[Dict] = []

    def put(row, val, label):
        if row is None:
            log.append("  [miss-row] no {!r} row".format(label))
            return
        if val is None or val == "":
            return
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        a1 = "{}{}".format(a1c, row + 1)
        updates.append({"range": a1, "values": [[val]]})
        log.append("  {} {} <- {}".format(a1, label, val))

    put(cx_row, total_cx, "Total Box CX's")
    put(ash_row, metrics.get("selling_reps"), "Active Selling Heads")
    put(_find_row(grid, "AVG Kwh Usage Per CX"), metrics.get("kwh_per_sale"),
        "AVG Kwh Usage Per CX")
    put(_find_row(grid, "National AVG for sales"), national.get("sales_per_rep"),
        "National AVG for sales")
    put(_find_row(grid, "National AVG kwH Usage per CX"),
        national.get("kwh_per_sale"), "National AVG kwH Usage per CX")
    aspl = _find_row(grid, "AVG Sales per Leader")
    if aspl is not None and cx_row is not None and ash_row is not None:
        put(aspl, "=IFERROR({c}{cx}/{c}{ash},0)".format(
            c=a1c, cx=cx_row + 1, ash=ash_row + 1), "AVG Sales per Leader")

    if dry_run:
        return ["[DRY-RUN boxdaily] {}: would write {} cell(s) into {} ({})"
                .format(ws.title, len(updates), a1c, week)] + log
    if not updates:
        return ["[skip-boxdaily] {}: nothing to write".format(ws.title)]
    rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    return ["[OK boxdaily] {}: wrote {} cell(s) into {} ({})".format(
        ws.title, len(updates), a1c, week)] + log


def pull(dest_dir: Path, verbose: bool = True) -> Tuple[Path, Path]:
    """Download both worksheets in ONE session. Never slices by owner: the
    `Owner Name` filter on this view is Exclusive and a URL slice would drop
    exactly the owner we want."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.recruiting_report.opt_phase import drive_crosstab_dialog
    dest_dir.mkdir(parents=True, exist_ok=True)
    sales = dest_dir / "box_daily_sales.csv"
    metrics = dest_dir / "box_daily_metrics.csv"
    with tableau_session(verbose=verbose) as page:
        drive_crosstab_dialog(page, VIEW_URL, SALES_SHEET, sales,
                              verbose=verbose)
        drive_crosstab_dialog(page, VIEW_URL, METRICS_SHEET, metrics,
                              verbose=verbose)
    return sales, metrics


def run(dry_run: bool = True, from_sales: str = "", from_metrics: str = "",
        targets: Optional[List[Tuple[str, str, str]]] = None,
        logfn=print) -> int:
    targets = targets if targets is not None else TARGETS
    out_dir = Path(__file__).resolve().parents[2] / "output" / "_box_daily"
    if from_sales and from_metrics:
        sales_csv, metrics_csv = Path(from_sales), Path(from_metrics)
        logfn("OPT BOX-daily: reading {} + {}".format(
            sales_csv.name, metrics_csv.name))
    else:
        logfn("OPT BOX-daily: pulling {} + {}...".format(
            SALES_SHEET, METRICS_SHEET))
        sales_csv, metrics_csv = pull(out_dir, verbose=True)

    totals, week = parse_sales(_read(sales_csv))
    per, national = parse_metrics(_read(metrics_csv))
    if week is None:
        logfn("OPT BOX-daily: x could not read the week off the day columns")
        return 1
    logfn("OPT BOX-daily: week = {}; {} owner(s) with sales, national={}"
          .format(week, len(totals), national))

    rc = 0
    client = rfill._client()
    for owner, sheet_id, tab in targets:
        key = _norm(owner)
        if key not in totals and key not in per:
            logfn("OPT BOX-daily: {!r} not in the tracker this week — "
                  "left untouched".format(owner))
            continue
        try:
            ws = rfill.open_by_key(sheet_id, client).worksheet(tab)
        except Exception as exc:                             # noqa: BLE001
            logfn("OPT BOX-daily: x {!r}: {}".format(tab, exc))
            rc = 1
            continue
        for ln in fill_tab(ws, totals.get(key), per.get(key, {}), national,
                           week, dry_run=dry_run, logfn=logfn):
            logfn("OPT BOX-daily: {}".format(ln))
    return rc


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="opt_box_daily")
    ap.add_argument("--write", action="store_true",
                    help="actually write (default is a dry run)")
    ap.add_argument("--from-sales", default="",
                    help="skip the pull; read this 'Daily Tracker Sales' csv")
    ap.add_argument("--from-metrics", default="",
                    help="skip the pull; read this 'Daily Tracker Metrics' csv")
    args = ap.parse_args(argv)
    return run(dry_run=not args.write, from_sales=args.from_sales,
               from_metrics=args.from_metrics)


if __name__ == "__main__":
    raise SystemExit(main())
