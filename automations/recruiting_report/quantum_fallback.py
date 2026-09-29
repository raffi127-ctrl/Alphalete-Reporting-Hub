"""Quantum fallback — fill an ATT Focus Report tab from the Quantum (Lumen)
tracker while its ICD is still moving from Quantum Fiber to AT&T Fiber.

    lucy rerun quantum_fallback                      # dry run, last Sunday
    lucy rerun quantum_fallback --write
    lucy rerun quantum_fallback --week 2026-10-04 --write

WHY (Eve, 2026-09-29). Nigel Marshall (VP Executives, Inc.) is coming from
Lumen over to AT&T Fiber. The Monday OPT phase only reads the ATT views, where
he has no fiber sales yet, so his tab would read 0 New Internets while his ~42
reps sell ~200 Quantum fiber a week. Rule, per week:

  * the ATT run already wrote New Internets > 0  -> AT&T fiber has started:
    keep ATT, touch nothing, never download Quantum;
  * otherwise -> write New Internets + Active Headcount on Tableau from the
    Quantum tracker, with a cell NOTE saying so. The note is also how a re-run
    of the same week tells "Quantum wrote this" from "ATT wrote this".

Sources (workbook `AT&T Quantum Fiber Sales Tracker`, RES-LumenSalesTrackervMZ):
  - `RES-Quantum Fiber ICD Week Ending Sales`  -> New Internets
  - `RES-Quantum Fiber Headcount by ICD`       -> Active Headcount on Tableau
Both are weekly (last ~5 weeks), same as the Angel Padilla tab.

It also CHECKS (Eve, 2026-09-29: "anotalo como cola del focus report para
hacerlo solo") that every AppStream office of the tab — the top box and each
sibling box — got its recruiting for the week from the Focus Report run. An
empty box = exit 1, which the orchestrator raises in the corrections channel
by itself; a clean Monday stays quiet.

Total Apps and the AVG rows are formulas: never written. Rows by column-B
label inside the OPT block, weeks by the date header. Runs on a Lucy (Tableau).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "_quantum_fallback"

# Sheet tab -> how the Quantum views name the ICD.
#   sales_key:  the "ICD Owner [Office] (Nest)" cell of the Week Ending view
#   owner/office: "ICD Owner Name" + "ICD Office Name" of the Headcount view
# Take a tab out of here once AT&T fiber has fully taken over.
TABS: Dict[str, dict] = {
    "Nigel Marshall": {
        "sales_key": "nigel marshall [vp executives, inc.]",
        "owner": "nigel marshall",
        "office": "vp executives, inc.",
    },
}

SALES_VIEW = "RES-Quantum Fiber ICD Week Ending Sales"
SALES_SHEET = "RES-Quantum Fiber ICD Week Ending Sales."
HC_VIEW = "RES-Quantum Fiber Headcount by ICD"
HC_SHEET = "RES-Quantum Fiber Headcount by ICD."

NI_LABEL = "new internets"
HC_LABEL = "active headcount on tableau"
NOTE = "Quantum Fiber (Lumen tracker): no AT&T fiber sales this week"


def _fold(s: str) -> str:
    return " ".join(str(s or "").casefold().split())


def _num(s) -> Optional[float]:
    s = str(s or "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(s: str) -> Optional[dt.date]:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _week_col(header: List[str], week: dt.date) -> Optional[int]:
    return next((i for i, h in enumerate(header) if _date(h) == week), None)


def quantum_sales(rows: List[List[str]], key: str, week: dt.date) -> Optional[int]:
    """Week Ending Sales grid -> this ICD's fiber sales for `week`. Pure."""
    if not rows:
        return None
    col = _week_col(rows[0], week)
    if col is None:
        return None
    for r in rows[1:]:
        if r and _fold(r[0]) == _fold(key) and col < len(r):
            v = _num(r[col])
            return None if v is None else int(round(v))
    return None


def quantum_headcount(rows: List[List[str]], owner: str, office: str,
                      week: dt.date) -> Optional[int]:
    """Headcount by ICD grid -> this ICD's headcount for `week`. Pure."""
    if not rows:
        return None
    col = _week_col(rows[0], week)
    if col is None:
        return None
    for r in rows[1:]:
        if (len(r) > max(col, 1) and _fold(r[0]) == _fold(owner)
                and _fold(r[1]) == _fold(office)):
            v = _num(r[col])
            return None if v is None else int(round(v))
    return None


def decide(ni_value: str, ni_note: str) -> str:
    """'att' when the ATT run already put fiber sales in New Internets,
    'quantum' otherwise. A value WE wrote (note present) is not ATT. Pure."""
    v = _num(ni_value)
    if v and v > 0 and not str(ni_note or "").startswith("Quantum"):
        return "att"
    return "quantum"


# Raw AppStream counts the recruiting fill writes as values (the % rows can be
# formulas that read 0% on an empty week, so they prove nothing).
RECRUITING_PROOF = ("pull", "first_booked")


def recruiting_filled(values: List[List[str]], col: int,
                      metric_rows: Dict[str, int]) -> bool:
    """True when this section's raw recruiting counts are there for the week
    (`col` 1-based). A 0 counts as filled — AppStream said zero. Pure."""
    rows = [metric_rows[k] for k in RECRUITING_PROOF if k in metric_rows]
    if not rows:
        return False
    for r in rows:
        row = values[r - 1] if r - 1 < len(values) else []
        if col - 1 >= len(row) or str(row[col - 1]).strip() == "":
            return False
    return True


def check_recruiting(sh, ws, week: dt.date) -> List[str]:
    """Monday self-check (Eve, 2026-09-29): every AppStream office of this tab
    (primary box + siblings) got its recruiting for `week` from the Focus
    Report run. Returns one problem line per empty box; [] = all good."""
    from automations.recruiting_report import fill

    entry = next((c for c in fill.load_mapping().get("confirmed", [])
                  if c.get("sheet_tab") == ws.title), None)
    if not entry:
        return ["%s: not confirmed in office-mapping.json" % ws.title]
    values = fill._retry(ws.get_all_values)
    col = fill.find_sunday_columns(values, header_row_idx=0).get(week)
    if col is None:
        return ["%s: no WE %s column" % (ws.title, week)]
    problems = []
    for oid in [entry["office_id"]] + list(entry.get("siblings", [])):
        if oid == entry["office_id"]:
            anchor = 1
        else:
            anchor = fill.find_office_section_anchor(ws, oid)
            if not anchor:
                problems.append("%s office %s: no box anchor in column A" % (ws.title, oid))
                continue
        rows = fill.find_office_metric_rows(ws, anchor_row=anchor, max_rows=30)
        ok = recruiting_filled(values, col, rows)
        print("RECRUITING | %s | office %s | WE %s | %s"
              % (ws.title, oid, week, "filled" if ok else "EMPTY"))
        if not ok:
            problems.append("%s office %s: recruiting empty for WE %s"
                            % (ws.title, oid, week))
    return problems


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def _tab_cells(sh, ws, week: dt.date) -> Tuple[int, int, int, str, str]:
    """(col, ni_row, hc_row, ni_value, ni_note) for this week on this tab."""
    import gspread
    from automations.recruiting_report import fill
    from automations.recruiting_report.opt_phase import _opt_block_rows

    grid = fill._retry(ws.get_all_values)
    col = fill.find_sunday_columns(grid, header_row_idx=0).get(week)
    if col is None:
        raise RuntimeError("no WE %s column on tab %r" % (week, ws.title))
    rows = _opt_block_rows([r[1] if len(r) > 1 else "" for r in grid])
    ni_row, hc_row = rows.get(NI_LABEL), rows.get(HC_LABEL)
    if not ni_row or not hc_row:
        raise RuntimeError("OPT block rows not found on tab %r" % ws.title)
    ni_val = grid[ni_row - 1][col - 1] if col - 1 < len(grid[ni_row - 1]) else ""
    a1 = gspread.utils.rowcol_to_a1(ni_row, col)
    meta = fill._retry(sh.fetch_sheet_metadata, params={
        "ranges": "'%s'!%s" % (ws.title, a1),
        "fields": "sheets.data.rowData.values.note"})
    try:
        note = meta["sheets"][0]["data"][0]["rowData"][0]["values"][0].get("note", "")
    except (KeyError, IndexError):
        note = ""
    return col, ni_row, hc_row, ni_val, note


def _download(views_needed) -> Dict[str, List[List[str]]]:
    """Pull the two Quantum sheets in one Tableau session."""
    os.environ["ALPHALETE_SKIP_FRESHNESS"] = "1"
    OUT.mkdir(parents=True, exist_ok=True)
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from automations.recruiting_report import probe_quantum_views as PQ

    grids: Dict[str, List[List[str]]] = {}
    with tableau_session(verbose=False, profile_dir=OUT / ".profile") as page:
        page.goto(PQ.BASE + "/#/site/sci/workbooks", wait_until="domcontentloaded")
        page.wait_for_timeout(12_000)
        _, data = PQ._call(page, "getWorkbooks", {
            "filter": {"operator": "and", "clauses": []},
            "order": [{"field": "name", "ascending": True}],
            "page": {"startIndex": 0, "maxItems": 500}})
        wbs = (data.get("result") or {}).get("workbooks") or []
        wb = next((w for w in wbs if any(
            n in (w.get("name", "") + " " + (w.get("repositoryUrl") or "")).casefold()
            for n in PQ.WB_NEEDLES)), None)
        if not wb:
            raise RuntimeError("Quantum workbook not found in Tableau")
        urls = dict(PQ._views(page, wb))
        for view, sheet in views_needed:
            if view not in urls:
                raise RuntimeError("Quantum view %r not found" % view)
            out = OUT / (sheet.strip(". ").replace(" ", "_") + ".csv")
            download_crosstab_patchright(urls[view], sheet, out,
                                         verbose=False, page=page)
            grids[sheet] = PQ._read_grid(out)
            print("[quantum] downloaded %s (%d rows)" % (sheet, len(grids[sheet]) - 1))
    return grids


def _verdict(problems: List[str]) -> int:
    """Exit 1 on any empty recruiting box, so the orchestrator raises it in
    #claudecorrections-and-requests on its own; a clean Monday stays quiet."""
    for p in problems:
        print("PROBLEM | " + p)
    return 1 if problems else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD (default: last Sunday).")
    ap.add_argument("--write", action="store_true",
                    help="Actually write. Default is a dry run.")
    args = ap.parse_args(argv)
    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday()
    if week.weekday() != 6:
        print("[quantum] not a Sunday: %s" % week)
        return 2

    import gspread
    from automations.recruiting_report import fill

    sh = fill.open_sheet()
    print("[quantum] WE %s · write=%s · %d tab(s)" % (week, args.write, len(TABS)))

    problems: List[str] = []
    pending = {}
    for tab in TABS:
        ws = fill._retry(sh.worksheet, tab)
        problems += check_recruiting(sh, ws, week)
        col, ni_row, hc_row, ni_val, note = _tab_cells(sh, ws, week)
        if decide(ni_val, note) == "att":
            print("ATT FIBER | %s | WE %s | New Internets = %s from AT&T -> "
                  "kept, Quantum not used. Transition done for this week."
                  % (tab, week, ni_val))
            continue
        pending[tab] = (ws, col, ni_row, hc_row, ni_val)

    rc = _verdict(problems)
    if not pending:
        return rc

    grids = _download([(SALES_VIEW, SALES_SHEET), (HC_VIEW, HC_SHEET)])
    for tab, (ws, col, ni_row, hc_row, ni_val) in pending.items():
        cfg = TABS[tab]
        ni = quantum_sales(grids[SALES_SHEET], cfg["sales_key"], week)
        hc = quantum_headcount(grids[HC_SHEET], cfg["owner"], cfg["office"], week)
        if ni is None or hc is None:
            print("MISSING | %s | WE %s | Quantum has no row/column yet "
                  "(sales=%s, headcount=%s) — nothing written" % (tab, week, ni, hc))
            rc = 1
            continue
        print("QUANTUM | %s | WE %s | New Internets %s -> %s · Headcount -> %s"
              % (tab, week, ni_val or "(blank)", ni, hc))
        if not args.write:
            continue
        ni_a1 = gspread.utils.rowcol_to_a1(ni_row, col)
        hc_a1 = gspread.utils.rowcol_to_a1(hc_row, col)
        fill._retry(ws.batch_update, [
            {"range": ni_a1, "values": [[ni]]},
            {"range": hc_a1, "values": [[hc]]},
        ], value_input_option="USER_ENTERED")
        fill._retry(sh.batch_update, {"requests": [{"updateCells": {
            "range": {"sheetId": ws.id, "startRowIndex": r - 1, "endRowIndex": r,
                      "startColumnIndex": col - 1, "endColumnIndex": col},
            "rows": [{"values": [{"note": NOTE}]}], "fields": "note"}}
            for r in (ni_row, hc_row)]})
        print("written %s, %s" % (ni_a1, hc_a1))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
