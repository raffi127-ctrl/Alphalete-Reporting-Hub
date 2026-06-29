"""BOX (Box Energy) OPT fill for the Alphalete Org sheet.

Per-campaign OPT pull for the ' - BOX' tabs (Ryan Mcspadden, Roshan Amin
Ahmad, Benjamin Burden). Source + mapping from Eve's walkthrough +
Megan's column mapping (2026-05-24), documented in
resources/opt-section/alphalete-org-campaign-sources.md.

Source: Tableau workbook `B2BBOXEnergyTracker` → view `BoxSalesMetrics`,
Crosstab worksheet **'Sales Metrics'** (one download covers every metric).
(Renamed 2026-06-29 from `B2BBOXEnergy`/`B2BBOXEnergyDailyTracker` with
worksheet `WTD Metrics` — the old path now 404s with "la vista no existe";
the Crosstab dialog now lists 'Sales Metrics' + 'Latest Update (2)'.)
The tracker is a current-week snapshot (not date-pinnable, like the NDS
daily trackers), so a run fills the current target week column.

The 'Sales Metrics' crosstab is Owner x Rep: an ICD's team total is the
row where Rep Name == 'Total'; the org total is Owner Name == 'Grand Total';
individual rep rows (Rep Name != 'Total') give per-rep Complete Sales.

Mapping (sheet row label → 'Sales Metrics' column), looked up by LABEL —
never by index (the BOX tabs are NOT identically laid out). Columns were
RENAMED in the 2026-06-29 workbook rebuild (old name in parens):
  - Active Selling Heads          ← 'Selling Rep Count'  (was Rep Count)
  - Total Box CX's                ← 'Complete Sales'     (was ELE Sales)
  - AVG Kwh Usage Per CX          ← 'Sales (All) kWH' ÷ 'Complete Sales'
                                    (DERIVED — the pre-computed 'kWh per Sale'
                                    column is gone; Eve confirmed derive 6/29)
  - AVG Sales per Leader          = Total Box CX's / Active Selling Heads
                                    (sheet FORMULA, cells by label)
  - National AVG for sales        ← Grand Total 'Sales/ Rep'  (SHARED)
  - National AVG kwH Usage per CX ← Grand Total derived kWh-per-CX (SHARED)
  - Accepted %                    ← NO source in the new workbook — left blank
                                    (Eve 6/29; 'Selling Rep Count %' is a
                                    different concept, not acceptance)

National AVGs are the same on every BOX tab (they're the office-wide
"total general"/Grand Total row). A rep absent from the tracker this week
(not actively selling) is LEFT UNTOUCHED, not zeroed.

Personal Production (the ICD's OWN box sales) comes from the SAME 'Sales
Metrics' crosstab now — the individual rep row whose name matches the ICD
(the separate 'WoW Metrics by Rep' view was deleted in the 6/29 rebuild;
Eve confirmed everything lives in this one view). 0 when the ICD ran a team
but didn't personally sell (Megan 2026-06-03).

Direct Deposit is pulled from Tableau's org-wide DD view (ORG_DD_URL,
shared with every campaign — see opt_nds.parse_direct_deposit), keyed by
ICD owner name. Standardized 2026-05-25 (Megan): DD = Tableau for every
campaign on all 3 reports.

NOT filled here (other sources / manual): WTD KwH, Completed %, New Lines,
AVG Apps Per Active Headcount, Scorecard Ranking, churn/activation rows,
and the CO/TX financial blocks (those come from the financial pull — Ryan
has 2 payrolls → 2 financial sets).
"""

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import gspread

from automations.shared import sheet_flags as _sheet_flags

from automations.recruiting_report import fill as rfill
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID,
    OUTPUT_DIR,
    ORG_DD_URL,
    ORG_DD_SHEET,
    parse_direct_deposit,
    match_dd_owner,
    _read_tab_csv,
    _norm_owner,
    _find_week_col,
    _find_row_by_label,
    _current_target_week_end,
)
from automations.shared.tableau_patchright import (
    tableau_session,
    download_crosstab_patchright,
)


BOX_TRACKER_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "B2BBOXEnergyTracker/BoxSalesMetrics?:iid=1"
)
BOX_WTD_SHEET = "Sales Metrics"
BOX_WTD_FILENAME = "opt_box_sales_metrics.csv"
BOX_DD_FILENAME = "opt_box_direct_deposit.csv"


def _match_key(keys, name: str) -> Optional[str]:
    """Match a sheet tab owner name to a crosstab key, tolerant of middle
    names ('Roshan Amin Ahmad' → 'roshan ahmad') — mirrors match_dd_owner's
    order: exact, then first+last, then a UNIQUE last-name match. Returns the
    matched key (so callers can index either the reps or the PP dict)."""
    key = _norm_owner(name)
    if key in keys:
        return key
    parts = key.split()
    if len(parts) >= 2:
        fl = f"{parts[0]} {parts[-1]}"
        if fl in keys:
            return fl
        last = parts[-1]
        cands = [k for k in keys if k.split() and k.split()[-1] == last]
        if len(cands) == 1:
            return cands[0]
    return None


def _box_week_label(today: Optional[dt.date] = None) -> str:
    """Sheet week label (M/D/YY) for the week we're filling = the most recent
    Sunday on-or-before today (shared _current_target_week_end). Sun 5/24 and
    Mon 5/25 both → 5/24, so a Sunday-evening or Monday-morning run fills the
    just-ended week and never the prior column. The BOX tracker is a current-
    week snapshot whose just-completed week the Monday-morning view shows."""
    d = _current_target_week_end(today)
    return f"{d.month}/{d.day}/{d.year % 100}"


def _num(s: str) -> Optional[float]:
    s = (s or "").strip().replace(",", "").replace("$", "")
    if not s or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(s: str) -> Optional[int]:
    v = _num(s)
    return int(round(v)) if v is not None else None


def _col(header: List[str], *needles: str) -> Optional[int]:
    """First column whose header contains all `needles` (case-insensitive)."""
    for j, h in enumerate(header):
        low = (h or "").strip().lower()
        if all(n in low for n in needles):
            return j
    return None


def parse_box_sales_metrics(path: Path) -> Tuple[Dict[str, Optional[float]],
                                                 Dict[str, Dict],
                                                 Dict[str, int]]:
    """Parse the 'Sales Metrics' crosstab → (national, reps, personal_production).

    The crosstab is Owner x Rep (renamed/rebuilt 2026-06-29):
      - org total   = Owner Name 'Grand Total'    (Rep Name 'Total')
      - ICD total   = Rep Name 'Total'            (one per owner)
      - rep row     = Rep Name != 'Total'         → per-rep Complete Sales

    national = {'sales_per_rep': float, 'kwh_per_sale': int}  (Grand Total row;
        kwh_per_sale is DERIVED = total kWH / Complete Sales — the old
        pre-computed column is gone, Eve confirmed derive 2026-06-29).
    reps = {owner_norm: {'rep_count','ele','kwh_per_sale','accepted'}} from the
        ICD-total rows. 'accepted' is always '' (no source in the new workbook;
        fill leaves the Accepted % cell untouched).
    pp = {rep_norm: complete_sales} from the individual rep rows — an ICD's OWN
        box sales (matched to the tab by name in the fill loop).
    """
    rows = _read_tab_csv(path)
    empty = ({"sales_per_rep": None, "kwh_per_sale": None}, {}, {})
    if not rows:
        return empty
    header = rows[0]
    c_owner = _col(header, "owner", "name")
    c_rep = _col(header, "rep", "name")
    c_complete = _col(header, "complete", "sales")   # Total Box CX's
    c_spr = _col(header, "sales", "rep")             # 'Sales/ Rep' (avg/leader)
    c_selling = _col(header, "selling", "rep", "count")  # Active Selling Heads
    c_kwh = _col(header, "kwh")                       # 'Sales (All) kWH' (total)
    if c_owner is None or c_rep is None or c_complete is None:
        return empty

    def _per_cx_kwh(total_kwh: Optional[float], sales: Optional[int]) -> Optional[int]:
        # AVG kWh usage per CX = total kWh / box CX count (Eve 2026-06-29).
        if total_kwh is None or not sales:
            return None
        return int(round(total_kwh / sales))

    national: Dict[str, Optional[float]] = {"sales_per_rep": None,
                                            "kwh_per_sale": None}
    reps: Dict[str, Dict] = {}
    pp: Dict[str, int] = {}
    for r in rows[1:]:
        if c_owner >= len(r) or c_rep >= len(r):
            continue
        owner = (r[c_owner] or "").strip()
        rep = (r[c_rep] or "").strip()
        if not owner:
            continue
        complete = _int(r[c_complete]) if c_complete < len(r) else None
        total_kwh = _num(r[c_kwh]) if c_kwh is not None and c_kwh < len(r) else None

        if rep.lower() in ("total", "total general"):
            if owner.lower() in ("grand total", "total general", "total"):
                national["sales_per_rep"] = (_num(r[c_spr])
                                             if c_spr is not None and c_spr < len(r) else None)
                national["kwh_per_sale"] = _per_cx_kwh(total_kwh, complete)
            else:
                reps[_norm_owner(owner)] = {
                    "rep_count": (_int(r[c_selling])
                                  if c_selling is not None and c_selling < len(r) else None),
                    "ele": complete,
                    "kwh_per_sale": _per_cx_kwh(total_kwh, complete),
                    "accepted": "",   # no source in the new workbook (Eve 6/29)
                }
        elif complete is not None:
            # individual rep row → personal-production candidate (ICD's self-row)
            pp[_norm_owner(rep)] = complete
    return national, reps, pp


def fill_box_tab(ws: gspread.Worksheet, rep: Dict, national: Dict,
                 week_col_label: str, dry_run: bool = False,
                 logfn=print, direct_deposit: Optional[str] = None,
                 personal_production: Optional[int] = None) -> List[str]:
    """Fill the 7 BOX tracker metrics (+ Direct Deposit) into the target week
    column for one rep. Rows are looked up by label (tabs differ in layout)."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-box] {ws.title}: empty tab"]
    week_col = _find_week_col(grid, week_col_label)
    if week_col is None:
        return [f"[skip-box] {ws.title}: no column for week {week_col_label}"]
    col_a1 = gspread.utils.rowcol_to_a1(1, week_col + 1).rstrip("1")

    def _row_any(*labels):
        for lab in labels:
            r = _find_row_by_label(grid, lab)
            if r is not None:
                return r
        return None

    # The "active selling heads" slot is labelled inconsistently across the
    # BOX tabs: Ryan/Benjamin use "Active Selling Heads", Roshan uses
    # "Active Headcount on Tableau". Both take the tracker Rep Count.
    ash_row = _row_any("Active Selling Heads", "Active Headcount on Tableau")
    cx_row = _find_row_by_label(grid, "Total Box CX's")
    kwh_row = _find_row_by_label(grid, "AVG Kwh Usage Per CX")
    aspl_row = _find_row_by_label(grid, "AVG Sales per Leader")
    natsales_row = _find_row_by_label(grid, "National AVG for sales")
    natkwh_row = _find_row_by_label(grid, "National AVG kwH Usage per CX")
    acc_row = _find_row_by_label(grid, "Accepted %")

    updates: List[Dict] = []

    def put(row, val, label):
        if row is None or val is None or val == "":
            if row is None:
                log.append(f"  [miss-row] no '{label}' row")
            return
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        a1 = gspread.utils.rowcol_to_a1(row + 1, week_col + 1)
        updates.append({"range": a1, "values": [[val]]})
        log.append(f"  {a1} {label} <- {val}")

    put(ash_row, rep.get("rep_count"), "Active Selling Heads")
    put(cx_row, rep.get("ele"), "Total Box CX's")
    put(kwh_row, rep.get("kwh_per_sale"), "AVG Kwh Usage Per CX")
    # AVG Sales per Leader = Total Box CX's / Active Selling Heads (formula).
    if aspl_row is not None and cx_row is not None and ash_row is not None:
        cx_ref = f"{col_a1}{cx_row + 1}"
        ash_ref = f"{col_a1}{ash_row + 1}"
        put(aspl_row, f"=IFERROR({cx_ref}/{ash_ref},0)", "AVG Sales per Leader")
    put(natsales_row, national.get("sales_per_rep"), "National AVG for sales")
    put(natkwh_row, national.get("kwh_per_sale"), "National AVG kwH Usage per CX")
    acc = rep.get("accepted")
    put(acc_row, acc if acc else None, "Accepted %")
    # Direct Deposit — Tableau org-wide DD view, per ICD owner (Megan 2026-05-25).
    if direct_deposit:
        put(_find_row_by_label(grid, "Direct Deposit"), direct_deposit,
            "Direct Deposit")
    # Personal Production — the ICD's OWN box sales (self-row). 0 when they ran
    # a team but didn't personally sell (Megan 2026-06-03).
    if personal_production is not None:
        put(_find_row_by_label(grid, "Personal Production"),
            personal_production, "Personal Production")

    if dry_run:
        return [f"[DRY-RUN box] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        _red = _sheet_flags.weird_ranges(updates)   # fill-but-flag weird %s
        if _red:
            _sheet_flags.apply_red_font(ws, _red, retry=rfill._retry)
        return [f"[OK box] {ws.title}: wrote {len(updates)} cells"
                + (f" ({len(_red)} flagged)" if _red else "")] + log
    return [f"[skip-box] {ws.title}: nothing to write"]


def run_box_opt(dry_run: bool = False, only_rep: Optional[str] = None,
                logfn=print) -> dict:
    """Pull the BOX 'WTD Metrics' tracker once and fill every ' - BOX' tab."""
    errors: List[str] = []
    week_col_label = _box_week_label()
    logfn(f"OPT BOX: target week = {week_col_label!r} (tracker current week)")

    out = OUTPUT_DIR / BOX_WTD_FILENAME
    dd_out = OUTPUT_DIR / BOX_DD_FILENAME
    direct_deposit: Dict[str, float] = {}
    try:
        with tableau_session(verbose=False) as page:
            logfn("OPT BOX: Crosstab → 'Sales Metrics'...")
            download_crosstab_patchright(BOX_TRACKER_URL, BOX_WTD_SHEET,
                                         out, verbose=False, page=page)
            # Direct Deposit — org-wide DD view (same source every campaign uses).
            try:
                logfn("OPT BOX: Crosstab → org-wide Direct Deposit...")
                download_crosstab_patchright(ORG_DD_URL, ORG_DD_SHEET,
                                             dd_out, verbose=False, page=page)
                direct_deposit = parse_direct_deposit(dd_out)
            except Exception as e:
                logfn(f"OPT BOX: ⚠ Direct Deposit pull failed "
                      f"({type(e).__name__}) — DD left as-is this run")
    except Exception as e:
        msg = f"Sales Metrics download: {type(e).__name__}: {str(e)[:120]}"
        logfn(f"OPT BOX: ✗ {msg}")
        return {"filled": [], "skipped": [], "errors": [msg]}

    # Personal Production now comes from the SAME 'Sales Metrics' crosstab (the
    # standalone 'WoW Metrics by Rep' view was deleted in the 6/29 rebuild).
    national, reps, box_pp = parse_box_sales_metrics(out)
    logfn(f"OPT BOX: national={national}; parsed {len(reps)} ICD total(s), "
          f"{len(box_pp)} rep PP row(s), {len(direct_deposit)} DD")

    client = rfill._client()
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, client)
    resp = sh.client.request(
        "get", f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"fields": "sheets(properties(title,hidden))"})
    hidden = {s["properties"]["title"] for s in resp.json().get("sheets", [])
              if s["properties"].get("hidden")}

    filled, skipped = [], []
    for ws in rfill._retry(sh.worksheets):
        title = ws.title
        if not title.endswith(" - BOX") or title in hidden or title.startswith("x"):
            continue
        rep_name = title[: -len(" - BOX")].strip()
        if only_rep and only_rep.lower() not in rep_name.lower():
            continue
        rk = _match_key(reps, rep_name)
        rep = reps.get(rk) if rk else None
        if rep is None:
            logfn(f"OPT BOX: {rep_name} not in tracker this week — left untouched")
            skipped.append(title)
            continue
        dd_val = match_dd_owner(direct_deposit, rep_name)
        dd_str = f"${dd_val:,.2f}" if dd_val is not None else None
        # Personal Production = the ICD's own self-row Complete Sales; 0 when
        # they ran a team but didn't personally sell (Megan 2026-06-03).
        pk = _match_key(box_pp, rep_name)
        pp_val = box_pp.get(pk, 0) if pk else 0
        for ln in fill_box_tab(ws, rep, national, week_col_label, dry_run, logfn,
                               direct_deposit=dd_str, personal_production=pp_val):
            logfn(f"OPT BOX: {ln}")
            if ln.startswith(("[OK", "[DRY-RUN")):
                filled.append(title)

    return {"filled": filled, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Only this rep (substring match).")
    args = ap.parse_args()
    result = run_box_opt(dry_run=args.dry_run, only_rep=args.only)
    print(f"\nFilled: {len(result['filled'])}; Skipped: {len(result['skipped'])}; "
          f"Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")
