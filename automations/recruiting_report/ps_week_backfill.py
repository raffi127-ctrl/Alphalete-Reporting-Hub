"""Backfill ONE ICD tab's weekly sale rows for old weeks, from the week-pinned
PRODUCT SALES crosstab — run ON A LUCY.

    lucy rerun ps_week_backfill --tab "Nuri Burgos" --week 2026-09-06          # dry run
    lucy rerun ps_week_backfill --tab "Nuri Burgos" --week 2026-09-06 --write

WHY THIS IS A MODULE AND NOT output/att_backfill_sales_2026-08-17.py. That
script reads crosstabs somebody already downloaded. Downloading one means a
Tableau session, and Tableau's SSO goes through ownerville — which allows ONE
session per account, so a download from Eve's Windows box evicts the Lucy
session holders (2026-09-02). Nuri Burgos's WE 9/6 was the first week nobody
had on disk (Eve 2026-09-14), so the download has to happen where the session
lives. Same arithmetic, same rules:

  * PRODUCT SALES SUMMARY is the only ICD-level sales view that accepts a week
    filter; the ATT/INT ICD Summary views only serve the latest closed week.
  * Summing the office's own rep rows reproduces the official ATT numbers.
  * Writes New Internets · Upgrades · DTV · New Lines · Active Headcount on
    Tableau · Personal Production. Total Apps and the AVG rows are formulas.
  * NEVER overwrites: a cell that already holds anything is kept and logged.
  * Rows by column-B label, weeks by the date header.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

PRODUCT_TO_ROW = {
    "NEW INTERNET":     "New Internets",
    "UPGRADE INTERNET": "Upgrades",
    "VIDEO":            "DTV",
    "WIRELESS":         "New Lines",
}
PP_ORDER = [("NEW INTERNET", "NI"), ("VIDEO", "DTV"),
            ("WIRELESS", "NL"), ("UPGRADE INTERNET", "UG")]

OUT_DIR = Path("output") / "ps_weeks"


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def read_crosstab(path: Path) -> List[List[str]]:
    """Tableau crosstabs are UTF-16, tab-delimited."""
    raw = Path(path).read_text(encoding="utf-16")
    return [ln.split("\t") for ln in raw.splitlines() if ln.strip()]


def office_week(rows: List[List[str]], owner: str) -> dict:
    """One office's totals for the week the crosstab is pinned to. Pure.

    Adds the seven weekday columns only — the trailing total column already
    holds the week's sum, so including it would double every count."""
    headers = [h.strip().lower() for h in rows[0]]
    day_cols = [i for i in range(3, len(headers)) if "total" not in headers[i]]
    target = _norm(owner)
    totals = {label: 0 for label in PRODUCT_TO_ROW.values()}
    sold = set()
    personal: Dict[str, int] = {}
    for r in rows[1:]:
        if len(r) < 4 or _norm(r[0]) != target:
            continue
        rep = (r[1] or "").strip()
        ptype = (r[2] or "").strip().upper()
        if not rep or rep.lower() == "total" or ptype not in PRODUCT_TO_ROW:
            continue
        week = 0
        for i in day_cols:
            cell = r[i].strip().replace(",", "") if i < len(r) else ""
            if cell.isdigit():
                week += int(cell)
        if not week:
            continue
        totals[PRODUCT_TO_ROW[ptype]] += week
        sold.add(rep)
        if _norm(rep) == target:
            personal[ptype] = personal.get(ptype, 0) + week
    pp = " / ".join("%d %s" % (personal[k], lbl) for k, lbl in PP_ORDER
                    if personal.get(k))
    return {"values": totals, "total_apps": sum(totals.values()),
            "headcount": len(sold), "personal_production": pp}


def plan_week(grid: List[List[str]], label_rows: Dict[str, int], col: int,
              res: dict) -> Tuple[List[dict], List[str], List[str]]:
    """(updates, wrote, kept) for one week's column. Never overwrites. Pure."""
    from gspread.utils import rowcol_to_a1
    cells = list(res["values"].items())
    cells.append(("Active Headcount on Tableau", res["headcount"]))
    if res["personal_production"]:
        cells.append(("Personal Production", res["personal_production"]))
    updates, wrote, kept = [], [], []
    for label, value in cells:
        r = label_rows.get(_norm(label))
        if r is None:
            kept.append("%s=NO ROW" % label)
            continue
        existing = (grid[r - 1][col - 1]
                    if r - 1 < len(grid) and col - 1 < len(grid[r - 1]) else "")
        if str(existing).strip():
            kept.append("%s already %r" % (label, existing))
            continue
        updates.append({"range": rowcol_to_a1(r, col), "values": [[value]]})
        wrote.append("%s=%s" % (label, value))
    return updates, wrote, kept


def download_weeks(weeks: List[dt.date], *, logfn=print) -> Dict[dt.date, Path]:
    """Week-pinned PRODUCT SALES crosstabs, one Tableau session, cached."""
    from automations.recruiting_report import opt_phase as OP
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {w: OUT_DIR / ("ps_%s.csv" % w.isoformat()) for w in weeks}
    todo = [w for w, p in paths.items() if not p.exists()]
    if todo:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=False) as page:
            for we in todo:
                OP.download_crosstab(OP._week_url(OP.PRODUCT_SALES_VIEW_URL, we),
                                     OP.PRODUCT_SALES_SHEET, paths[we],
                                     verbose=False, page=page)
                logfn("[ps-backfill] downloaded WE %s (%s bytes)"
                      % (we, "{:,}".format(paths[we].stat().st_size)))
    return paths


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tab", required=True, help="Sheet tab (ICD owner).")
    ap.add_argument("--owner", help="Owner name in the crosstab, if it differs.")
    ap.add_argument("--week", action="append", required=True,
                    help="WE Sunday YYYY-MM-DD; repeatable.")
    ap.add_argument("--write", action="store_true",
                    help="Actually write. Default is a dry run.")
    args = ap.parse_args(argv)

    weeks = sorted({dt.date.fromisoformat(w) for w in args.week})
    bad = [w for w in weeks if w.weekday() != 6]
    if bad:
        print("[ps-backfill] not a Sunday: %s" % ", ".join(map(str, bad)))
        return 2
    owner = args.owner or args.tab

    from automations.recruiting_report import fill
    from automations.recruiting_report.opt_phase import _opt_block_rows
    paths = download_weeks(weeks)

    sh = fill.open_sheet()
    ws = fill._retry(sh.worksheet, args.tab)
    grid = fill._retry(ws.get_all_values)
    sunday_to_col = fill.find_sunday_columns(grid, header_row_idx=0)
    label_rows = _opt_block_rows([r[1] if len(r) > 1 else "" for r in grid])
    if not label_rows:
        print("[ps-backfill] %s: no OPT section anchor in column B" % args.tab)
        return 1
    label_rows = {_norm(k): v for k, v in label_rows.items()}

    updates: List[dict] = []
    print("%s — %s (crosstab owner %r)"
          % ("WRITE" if args.write else "DRY RUN", args.tab, owner))
    for we in weeks:
        col = sunday_to_col.get(we)
        if col is None:
            print("  %s  no column on the tab — skipped" % we)
            continue
        res = office_week(read_crosstab(paths[we]), owner)
        if not res["total_apps"] and not res["headcount"]:
            print("  %s  no rows for %r — skipped" % (we, owner))
            continue
        ups, wrote, kept = plan_week(grid, label_rows, col, res)
        updates += ups
        print("  %s  col %d  %s%s" % (we, col, ", ".join(wrote) or "(nothing new)",
                                     ("   [kept: %s]" % "; ".join(kept)) if kept else ""))
    print("%d cell(s) to fill" % len(updates))
    if updates and args.write:
        fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
