"""LeafGuard numbers onto Spencer Brown's tab (ATT Program - Focus Report).

WHY THIS EXISTS (Eve + Maud, 2026-11-25)
----------------------------------------
Spencer Brown sells LeafGuard, a campaign no other Hub source carries. Starr
reads his tab in her Monday 1on1. Maud (thread "Leafguard Workbook", 11/25):
  * sales -> TWO rows, one for Valid sales and one for total sales;
  * LeafGuard does not track doors knocked, so instead -> Leads + Demos.

SOURCE (Tableau site `sci`, workbook "Leaf Guard D2D Reporting.V2", 4359662)
--------------------------------------------------------------------------
All three views take the same week filter, `Weekending Date` (a Sunday):

  * LeadandCloserMetrics -> which Closer Reps belong to Closer ICD
    "Spencer Brown" that week (Luong Lam, Sahil Chand, Spencer himself...).
    Its `Gross Close` per closer = TOTAL sales (every sale whatever its DD
    status; matches the SALES ORDER LOG row count).
  * CloserRepSalesTracker -> per Closer Rep `Valid Sales`, summed over the
    closers above (it has no Closer ICD column, hence the join).
  * LeadGenRepMetricsDDBased -> per Lead Rep under Lead Rep ICD
    "Spencer Brown": `Raw leads` and `Demos`.

`Todo` / `Total` rows are Tableau's subtotals (Spanish UI) and are skipped.
SALES ORDER LOG (the view in Eve's screenshot) can't be used: its .csv export
only returns the "As of Date" sheet.

ROWS (found / created by column-B label, weeks by date header)
-------------------------------------------------------------
  OPT block, right under "Badged %":
      LeafGuard Total Sales | LeafGuard Valid Sales
  WEEKLY KNOCKS DATA block, right under its header:
      LeafGuard Leads | LeafGuard Demos
Rows missing on the tab are inserted once (never deletes anything). A week
with no LeafGuard data is written as 0 only when Tableau answered for that
week; a failed download leaves the cell alone.

Usage:
  python -m automations.recruiting_report.leafguard_fill --dry-run
  python -m automations.recruiting_report.leafguard_fill            # last 2 weeks
  python -m automations.recruiting_report.leafguard_fill --backfill # every week on the tab
  ... --sheet-id <sandbox id> --tab "Spencer Brown"                 # sandbox
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TABLEAU_BASE = "https://us-east-1.online.tableau.com"
WORKBOOK = "LeafGuardD2DReporting_V2"
WEEK_FILTER = "Weekending Date"
ICD = "Spencer Brown"
TAB = "Spencer Brown"
SUBTOTALS = {"todo", "total", "all", "(todo)", "(all)"}

# label on the tab -> (anchor label it goes under, section header label)
ROWS = [
    ("LeafGuard Total Sales", "Badged %"),
    ("LeafGuard Valid Sales", "LeafGuard Total Sales"),
    ("LeafGuard Leads", "WEEKLY KNOCKS DATA"),
    ("LeafGuard Demos", "LeafGuard Leads"),
]


# ---------- Tableau ----------

def _rows(text: str) -> List[List[str]]:
    rdr = csv.reader(io.StringIO(text.lstrip("﻿")))
    out = [[c.strip() for c in r] for r in rdr]
    return out[1:] if out else []


def _num(s: str) -> Optional[float]:
    s = (s or "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_sub(s: str) -> bool:
    return s.strip().lower() in SUBTOTALS


def compute_week(lcm: str, crst: str, lg: str, icd: str = ICD) -> Dict[str, int]:
    """The four numbers for one week, from the three views' CSV text."""
    # LeadandCloserMetrics: Closer Rep, Closer ICD, Market, measure, value
    closers = set()
    total = valid = 0.0
    for r in _rows(lcm):
        if len(r) < 5 or r[1] != icd or not r[0] or _is_sub(r[0]):
            continue
        closers.add(r[0])
        if r[3] == "Gross Close":
            total += _num(r[4]) or 0.0
    # CloserRepSalesTracker: Closer Rep, Market, measure, value. Only Valid
    # comes from here: its Gross Close runs LOWER than LeadandCloserMetrics /
    # SALES ORDER LOG (11/8: 2 vs 3, 11/15: 6 vs 8, 11/22: 3 vs 7), so the
    # total stays on LeadandCloserMetrics, which matches the order log.
    for r in _rows(crst):
        if len(r) < 4 or r[0] not in closers:
            continue
        if r[2] == "Valid Sales":
            valid += _num(r[3]) or 0.0
    leads = demos = 0.0
    # LeadGenRepMetricsDDBased: Lead Rep ICD, Lead Rep Name, measure, value
    for r in _rows(lg):
        if len(r) < 4 or r[0] != icd or _is_sub(r[1]):
            continue
        v = _num(r[3]) or 0.0
        if r[2] == "Raw leads":
            leads += v
        elif r[2] == "Demos":
            demos += v
    return {"LeafGuard Total Sales": int(round(total)),
            "LeafGuard Valid Sales": int(round(valid)),
            "LeafGuard Leads": int(round(leads)),
            "LeafGuard Demos": int(round(demos))}


def fetch_week(session, sunday: dt.date) -> Dict[str, int]:
    def get(view: str) -> str:
        url = f"{TABLEAU_BASE}/t/sci/views/{WORKBOOK}/{view}.csv"
        r = session.get(url, params={WEEK_FILTER: sunday.isoformat()},
                        timeout=120)
        r.raise_for_status()
        if "<html" in r.text[:200].lower():
            raise RuntimeError(f"{view}: got a login page, not a CSV")
        return r.text
    return compute_week(get("LeadandCloserMetrics"),
                        get("CloserRepSalesTracker"),
                        get("LeadGenRepMetricsDDBased"))


# ---------- Sheet ----------

def _label_rows(values: List[List[str]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, r in enumerate(values, start=1):
        lab = (r[1] if len(r) > 1 else "").strip().lower()
        if lab and lab not in out:
            out[lab] = i
    return out


def ensure_rows(ws, dry_run: bool, logfn=print) -> List[List[str]]:
    """Insert any missing LeafGuard row under its anchor. Returns fresh values."""
    from . import fill
    values = fill._retry(ws.get_all_values)
    for label, anchor in ROWS:
        rows = _label_rows(values)
        if label.lower() in rows:
            continue
        at = rows.get(anchor.lower())
        if at is None:
            raise RuntimeError(f"anchor row '{anchor}' not on tab '{ws.title}'")
        logfn(f"  + row '{label}' under '{anchor}' (row {at + 1})"
              + (" [dry-run]" if dry_run else ""))
        if dry_run:
            values.insert(at, ["", label])
            continue
        # inherit_from_before copies the anchor row's formatting.
        fill._retry(ws.insert_row, ["", label], index=at + 1,
                    value_input_option="RAW", inherit_from_before=True)
        values = fill._retry(ws.get_all_values)
    return values


def run(sheet_id: Optional[str], tab: str, weeks: Optional[int],
        dry_run: bool, logfn=print) -> int:
    from gspread.utils import rowcol_to_a1
    from . import fill
    from automations.shared.tableau_patchright import (
        tableau_session, requests_session_from_page)

    sh = fill.open_by_key(sheet_id) if sheet_id else fill.open_sheet()
    ws = fill.worksheet_ci(sh, tab)
    values = ensure_rows(ws, dry_run, logfn)
    cols = fill.find_sunday_columns(values, 0)
    today = dt.date.today()
    last_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    sundays = sorted(d for d in cols if d <= last_sun and d.weekday() == 6)
    if weeks:
        sundays = sundays[-weeks:]
    if not sundays:
        logfn("no week columns to fill")
        return 0
    labels = _label_rows(values)

    with tableau_session(verbose=False) as page:
        session = requests_session_from_page(page)
        updates = []
        started = False   # weeks before his first LeafGuard number stay blank
        for d in sundays:
            try:
                nums = fetch_week(session, d)
            except Exception as e:  # noqa: BLE001 — leave that week alone
                logfn(f"  WE {d}: Tableau failed, week left as is "
                      f"({type(e).__name__}: {str(e)[:120]})")
                continue
            logfn(f"  WE {d}: " + ", ".join(
                f"{k.replace('LeafGuard ', '')} {v}" for k, v in nums.items()),
                flush=True)
            # Backfill: before 2026-06-07 every week is all 0 — he wasn't on
            # LeafGuard yet, so a 0 there would read as "worked, sold nothing".
            started = started or any(nums.values()) or weeks is not None
            if not started:
                continue
            for label, v in nums.items():
                r = labels[label.lower()]
                updates.append({"range": rowcol_to_a1(r, cols[d]),
                                "values": [[v]]})
    logfn(f"{len(updates)} cell(s) on '{ws.title}'"
          + (" — dry-run, nothing written" if dry_run else ""))
    if updates and not dry_run:
        fill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    return len(updates)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true",
                    help="every week column on the tab, not just the last 2")
    ap.add_argument("--weeks", type=int, default=2)
    ap.add_argument("--sheet-id", default=None, help="sandbox Sheet id")
    ap.add_argument("--tab", default=TAB)
    a = ap.parse_args()
    run(a.sheet_id, a.tab, None if a.backfill else a.weeks, a.dry_run)


if __name__ == "__main__":
    main()
