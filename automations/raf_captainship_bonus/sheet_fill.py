"""Weekly fill of the "Captainship Bonuses" tab — the automated Loom.

Layout (resolved by column-A labels + hidden-row state, never hardcoded):
  header row   : A == "CAPTAIN OVERRIDES";  B.. = week labels 'WE M.D',
                 NEWEST in col B, older weeks to the right.
  rep rows     : header+1 .. (Total Sales - 1). VISIBLE rows are the active
                 team; hidden rows are departed reps (kept, left blank).
  Total Sales  : A == "Total Sales"  =SUM(B<first_rep>:B<last_rep>)
  Money Made   : A == "Money Made"   (override-tier IFS; 3 such rows)
  churn %      : A == "New Internet 60 day Churn %"
  activation % : A == "New Internet Activation %"
  TOTAL        : A == "TOTAL MONEY MADE"  =SUM of the three Money Made rows

Weekly op (Loom): insert a fresh leftmost week column (B) by cloning last
week's column into C for its format + all its formulas, repurpose B as the
new week, fill each ACTIVE rep's Total Activations (matched by name), set the
team churn % + activation %, let the Total Sales / Money Made / TOTAL formulas
recompute, and re-point the performance chart's series at the Total Sales row.
Idempotent: if this week's column already exists it refreshes in place.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill as rfill
from automations.shared import captainship_roster as roster

SPREADSHEET_ID = os.environ.get(
    "RCB_SHEET_ID", "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E")
# Real tab; override RCB_TAB="Copy of Captainship Bonuses" to test on the copy.
TAB = os.environ.get("RCB_TAB", "Captainship Bonuses")

# sheet short-name -> exact Tableau ICD Owner Name, for pairs a first-name
# match can't get (different surnames / spellings). Extend if a run flags an
# AMBIGUOUS or unmatched active rep.
ALIASES: Dict[str, str] = {
    # sheet spells these differently than Tableau; first-name match already
    # resolves them, listed here for the record:
    # "edgar munoz ii": "edgar muniz ii",
    # "haytham haque": "haytham nagi",
}

_LABEL_RE = re.compile(r"^\s*WE\s+\d")


def open_tab():
    sh = rfill.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(TAB), sh


def week_label(sunday: dt.date) -> str:
    """WE Sunday -> 'WE M.D' (no leading zeros, e.g. 'WE 7.5')."""
    return f"WE {sunday.month}.{sunday.day}"


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def hidden_rows(sh, gid: int, n_rows: int) -> set:
    meta = sh.fetch_sheet_metadata(params={
        "ranges": [f"{TAB}!A1:A{max(n_rows, 1)}"],
        "includeGridData": True,
        "fields": "sheets(properties(sheetId),data(rowMetadata(hiddenByUser)))",
    })
    out = set()
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") != gid:
            continue
        for d in s.get("data", []):
            for i, m in enumerate(d.get("rowMetadata", [])):
                if m.get("hiddenByUser"):
                    out.add(i)
    return out


class Layout:
    def __init__(self, header: int, total_sales: int, churn: int, activ: int,
                 grand_total: int, rep_first: int, rep_last: int,
                 active: List[int], last_week_col: int):
        self.header = header             # 0-based header row
        self.total_sales = total_sales   # 0-based 'Total Sales' row
        self.churn = churn               # 0-based churn % row
        self.activ = activ               # 0-based activation % row
        self.grand_total = grand_total   # 0-based 'TOTAL MONEY MADE' row
        self.rep_first = rep_first       # 0-based first rep row (header+1)
        self.rep_last = rep_last         # 0-based last rep row (total_sales-1)
        self.active = active             # 0-based ACTIVE (visible, named) rows
        self.last_week_col = last_week_col  # 0-based rightmost 'WE ' column


def _find_row(grid, label) -> Optional[int]:
    want = _norm(label)
    return next((i for i, r in enumerate(grid)
                 if r and _norm(r[0]) == want), None)


def resolve_layout(grid: List[List[str]], hidden: set) -> Layout:
    header = _find_row(grid, "captain overrides")
    total_sales = _find_row(grid, "total sales")
    churn = _find_row(grid, "new internet 60 day churn %")
    activ = _find_row(grid, "new internet activation %")
    gtot = _find_row(grid, "total money made")
    for nm, idx in [("CAPTAIN OVERRIDES header", header),
                    ("Total Sales", total_sales),
                    ("New Internet 60 day Churn %", churn),
                    ("New Internet Activation %", activ),
                    ("TOTAL MONEY MADE", gtot)]:
        if idx is None:
            raise ValueError(f"could not locate the {nm!r} row in column A")
    rep_first, rep_last = header + 1, total_sales - 1
    active = [i for i in range(rep_first, rep_last + 1)
              if i not in hidden and grid[i] and (grid[i][0] or "").strip()]
    if not active:
        raise ValueError("no active (visible, named) rep rows found")
    # rightmost week column = last 'WE ' label in the header row.
    hdr = grid[header]
    last_week_col = max((j for j, c in enumerate(hdr) if _LABEL_RE.match(c or "")),
                        default=1)
    return Layout(header, total_sales, churn, activ, gtot,
                  rep_first, rep_last, active, last_week_col)


def match_rep(sheet_name: str, reps: Dict[str, int]
              ) -> Tuple[Optional[int], Optional[str], List[str]]:
    """Resolve a sheet name to a Tableau Total Activations value.

    Order: explicit ALIAS -> exact full-name -> unique first-name. Returns
    (value, matched_full_name, candidates); value/full are None when there's
    no unique match (candidates lists ambiguous names to pin via ALIASES)."""
    key = _norm(sheet_name)
    if not key:
        return None, None, []
    if key in ALIASES:
        full = _norm(ALIASES[key])
        return (reps[full], full, [full]) if full in reps else (None, None, [])
    if key in reps:
        return reps[key], key, [key]
    first = key.split()[0]
    cands = [full for full in reps if full.split() and full.split()[0] == first]
    if len(cands) == 1:
        return reps[cands[0]], cands[0], cands
    return None, None, sorted(cands)


def _report(**kw):
    return kw


def _match_active(grid, active, reps):
    matched: Dict[int, int] = {}
    unmatched: List[str] = []
    ambiguous: List[str] = []
    lines: List[str] = []
    for ri in active:
        name = (grid[ri][0] or "").strip()
        val, full, cands = match_rep(name, reps)
        if val is None:
            (ambiguous if len(cands) > 1 else unmatched).append(
                f"{name} -> {cands}" if len(cands) > 1 else name)
        else:
            matched[ri] = val
            lines.append(f"  {name:<22} = {val:>4}   ({full})")
    return matched, unmatched, ambiguous, lines


def run_fill(ws, sh, pull, we_sunday: dt.date, dry_run: bool = True,
             force_insert: bool = False, auto_roster: bool = True) -> dict:
    gid = ws.id
    label = week_label(we_sunday)
    grid = rfill._retry(ws.get_all_values)
    hidden = hidden_rows(sh, gid, len(grid))
    lay = resolve_layout(grid, hidden)
    matched, unmatched, ambiguous, mlines = _match_active(grid, lay.active, pull.reps)

    # --- roster reconciliation plan (auto add/hide vs Tableau team membership) ---
    departed, returning, new_full = roster.plan(
        grid, lay.active, hidden, lay.rep_first, lay.rep_last, pull.roster, ALIASES)
    departed_names = [(grid[r][0] or "").strip() for r in departed]

    total_val = sum(matched.values())
    hdr = grid[lay.header]
    already = ((hdr[1] if len(hdr) > 1 else "").strip() == label)
    refresh = already and not force_insert

    log = list(mlines)
    log.insert(0, (f"{label}: {len(matched)}/{len(lay.active)} active reps "
                   f"matched, Total Sales {total_val} "
                   f"(Tableau Grand Total {pull.grand_total}) · churn "
                   f"{pull.churn} · activation {pull.rolling} — "
                   + ("column exists -> refresh in place" if refresh
                      else "insert NEW leftmost column")))
    if auto_roster and new_full:
        log.append("  ➕ ADD rows: " + ", ".join(roster._title(f) for f in new_full))
    if auto_roster and returning:
        log.append("  ♻ UNHIDE (back on team): " + ", ".join(returning.values()))
    if auto_roster and departed_names:
        log.append("  ➖ HIDE (left team): " + ", ".join(departed_names))

    rep = _report(label=label, total=total_val, matched=matched,
                  unmatched=unmatched, ambiguous=ambiguous,
                  new_reps=[(f, pull.reps.get(f, 0)) for f in new_full],
                  hidden_departed=departed_names, churn=pull.churn,
                  rolling=pull.rolling, log=log, layout=lay, wrote=False)
    if dry_run:
        return rep

    # ---------------- WRITE ----------------
    # 1) roster structural changes first (hide/unhide before any insert so indices
    #    stay valid), then re-resolve the (now shifted) layout + re-match.
    new_rows: List[int] = []
    if auto_roster and (departed or returning or new_full):
        roster.set_hidden(ws, gid, departed, True)
        roster.set_hidden(ws, gid, list(returning.keys()), False)
        if new_full:
            at = lay.rep_first + 1              # middle of the block -> SUM expands
            roster.insert_rows(ws, gid, at, len(new_full))
            rfill._retry(ws.batch_update,
                         [{"range": f"A{at + i + 1}", "values": [[roster._title(f)]]}
                          for i, f in enumerate(new_full)],
                         value_input_option="USER_ENTERED")
            new_rows = list(range(at, at + len(new_full)))
        grid = rfill._retry(ws.get_all_values)
        hidden = hidden_rows(sh, gid, len(grid))
        lay = resolve_layout(grid, hidden)
        matched, unmatched, ambiguous, _ = _match_active(grid, lay.active, pull.reps)

    b_churn = pull.churn or ""
    b_activ = pull.rolling or ""
    if not refresh:
        # Loom "insert cells, shift right" — NOT a full-column insert. Insert a
        # blank cell block only over the WEEKLY table (header row .. TOTAL row),
        # column B, shifting existing weekly cells right. This preserves the top
        # tier-reference tables in rows 1-21 (and their B4:D4 / B8:D8 / B12:E12
        # merges — a full-column insert would grow those merges every week and a
        # copyPaste across them errors). Old B is now C; clone it back into B for
        # its format + every formula (relative refs re-point to B), then
        # repurpose B as this week.
        hdr0, last_row = lay.header, lay.grand_total
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [
            {"insertRange": {"range": {
                "sheetId": gid, "startRowIndex": hdr0,
                "endRowIndex": last_row + 1,
                "startColumnIndex": 1, "endColumnIndex": 2},
                "shiftDimension": "COLUMNS"}},
            {"copyPaste": {
                "source": {"sheetId": gid, "startRowIndex": hdr0,
                           "endRowIndex": last_row + 1,
                           "startColumnIndex": 2, "endColumnIndex": 3},
                "destination": {"sheetId": gid, "startRowIndex": hdr0,
                                "endRowIndex": last_row + 1,
                                "startColumnIndex": 1, "endColumnIndex": 2},
                "pasteType": "PASTE_NORMAL"}},
        ]})
        # header + reps + percentages via USER_ENTERED; the cloned formula rows
        # (Total Sales / Money Made / TOTAL) are left alone to recompute.
        updates = [{"range": f"B{lay.header + 1}", "values": [[label]]}]
        for ri in range(lay.rep_first, lay.rep_last + 1):  # clear + set matched
            updates.append({"range": f"B{ri + 1}", "values": [[matched.get(ri, "")]]})
        updates.append({"range": f"B{lay.churn + 1}", "values": [[b_churn]]})
        updates.append({"range": f"B{lay.activ + 1}", "values": [[b_activ]]})
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    else:
        updates = [{"range": f"B{ri + 1}", "values": [[v]]}
                   for ri, v in matched.items()]
        # blank this week for any hidden (departed) rep so they don't keep a
        # stale value in the Total on a same-week re-run.
        for ri in range(lay.rep_first, lay.rep_last + 1):
            if ri in hidden:
                updates.append({"range": f"B{ri + 1}", "values": [[""]]})
        updates.append({"range": f"B{lay.churn + 1}", "values": [[b_churn]]})
        updates.append({"range": f"B{lay.activ + 1}", "values": [[b_activ]]})
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")

    # Black out each newly-added rep's PRIOR week cells (C .. last week) — they
    # weren't on the team those weeks (the Loom's manual black-out). Their new
    # week cell (B) keeps the activation value.
    for r0 in new_rows:
        roster.blackout(ws, gid, r0, 2, lay.last_week_col + 2)

    # Re-point the performance chart: domain = header week labels, series =
    # the Total Sales row, both spanning B .. rightmost week column.
    _repoint_chart(ws, sh, gid, lay)

    rep["wrote"] = True
    log.append(f"chart series -> row {lay.total_sales + 1} (Total Sales), "
               f"domain row {lay.header + 1}, cols B:{_col(lay.last_week_col + 1)}")
    return rep


def _col(j0: int) -> str:
    s = ""
    j = j0
    while True:
        s = chr(65 + j % 26) + s
        j = j // 26 - 1
        if j < 0:
            break
    return s


# Original series/area color (Google Sheets "cyan" teal, #76A5AF). Set only
# when the chart has no series color, so a color the user later picks in the UI
# is preserved. Restores the turquoise my earlier full-series rewrite dropped.
_TURQUOISE = {"red": 118 / 255, "green": 165 / 255, "blue": 175 / 255}


def _repoint_chart(ws, sh, gid: int, lay: Layout) -> None:
    """Point the sheet's basic chart's single series at the Total Sales row
    (the Loom's weekly 'set the series to total sales' fix) and its domain at
    the header week labels, spanning B .. rightmost week. Mutates the existing
    domain/series source ranges IN PLACE so all other styling (series color,
    target axis, chart type) is preserved."""
    meta = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId),charts(chartId,spec,position))"})
    chart = None
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") != gid:
            continue
        charts = s.get("charts", [])
        if charts:
            chart = charts[0]
        break
    if not chart:
        return
    spec = chart["spec"]
    bc = spec.get("basicChart")
    if not bc or not bc.get("domains") or not bc.get("series"):
        return
    c1, c2 = 1, lay.last_week_col + 2          # B .. (last week + inserted col)

    def _point(container, row0):
        src = container["sourceRange"]["sources"][0]
        src["sheetId"] = gid
        src["startRowIndex"], src["endRowIndex"] = row0, row0 + 1
        src["startColumnIndex"], src["endColumnIndex"] = c1, c2

    _point(bc["domains"][0]["domain"], lay.header)
    _point(bc["series"][0]["series"], lay.total_sales)
    # Restore the turquoise fill if the series lost its color.
    if not bc["series"][0].get("colorStyle") and not bc["series"][0].get("color"):
        bc["series"][0]["colorStyle"] = {"rgbColor": _TURQUOISE}
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
        "updateChartSpec": {"chartId": chart["chartId"], "spec": spec}}]})
