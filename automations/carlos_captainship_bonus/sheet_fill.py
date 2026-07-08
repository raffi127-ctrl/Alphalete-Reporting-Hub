"""Weekly fill of the "Carlos B2B Captainship" tab — the automated Loom.

Layout (resolved by column-A labels + hidden-row state, never hardcoded):
  header row     : A == "CAPTAIN OVERRIDES";  B.. = week labels 'WE M.D',
                   NEWEST in col B, older weeks to the right.
  subheader      : A == "Owners"  (B.. = product type, "Internet" for the
                   single-column recent weeks) — cloned, not filled.
  rep rows       : subheader+1 .. (Total Activations - 1). VISIBLE = active
                   team; hidden = departed reps (kept, left blank).
  Total Activations : A == "Total Activations"  =SUM(B<first>:B<last>)
  Money Made     : A == "Money Made"  (override-tier IFS)
  Total - All Units : A == "Total - All Units"  (=Total Activations; the CHART
                   series row)
  0-30 churn team / personal, Higher Churn (=MAX), Decelerator (IFS),
  31-60 Days Activation %, Money Made (IFS), Non Pmt %, TOTAL AMOUNT.

Weekly op (Loom): "insert cells, shift right" over the weekly block (header ..
TOTAL AMOUNT), col B; clone last week (now col C) back into B for its format +
formulas; repurpose B as the new week — fill each active rep's Total
Activations, set the four metric cells (team 0-30 churn %, personal 0-30
churn %, 31-60 activation %, non-payment %), let the formulas recompute, and
re-point the chart's series at the Total - All Units row. Idempotent.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill as rfill
from automations.shared import captainship_roster as roster

SPREADSHEET_ID = os.environ.get(
    "CCB_SHEET_ID", "1xQQLzE8mU-a4lpk1IK3WolTPlFxavuMzdK3jA7NGga8")
# Real tab; override CCB_TAB="Copy of Carlos B2B Captainship" to test.
TAB = os.environ.get("CCB_TAB", "Carlos B2B Captainship")

# sheet short-name -> exact Tableau ICD Owner Name, for pairs a first-name
# match can't get. Extend if a run flags an AMBIGUOUS/unmatched active rep.
ALIASES: Dict[str, str] = {}

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
    def __init__(self, header, total_act, total_units, churn_team, churn_pers,
                 activ, nonpmt, total_amount, rep_first, rep_last, active,
                 last_week_col):
        self.header = header               # 0-based header row
        self.total_act = total_act         # 0-based 'Total Activations' row
        self.total_units = total_units     # 0-based 'Total - All Units' (chart)
        self.churn_team = churn_team       # 0-based metric rows (inputs)
        self.churn_pers = churn_pers
        self.activ = activ
        self.nonpmt = nonpmt
        self.total_amount = total_amount   # 0-based 'TOTAL AMOUNT' (block end)
        self.rep_first = rep_first
        self.rep_last = rep_last
        self.active = active               # 0-based ACTIVE (visible) rep rows
        self.last_week_col = last_week_col


def _find_row(grid, label) -> Optional[int]:
    want = _norm(label)
    return next((i for i, r in enumerate(grid)
                 if r and _norm(r[0]) == want), None)


def _find_prefix(grid, prefix) -> Optional[int]:
    want = _norm(prefix)
    return next((i for i, r in enumerate(grid)
                 if r and _norm(r[0]).startswith(want)), None)


def resolve_layout(grid: List[List[str]], hidden: set) -> Layout:
    header = _find_row(grid, "captain overrides")
    owners = _find_row(grid, "owners")
    total_act = _find_row(grid, "total activations")
    total_units = _find_row(grid, "total - all units")
    churn_team = _find_prefix(grid, "0-30 day churn % - team")
    churn_pers = _find_prefix(grid, "0-30 day churn % - perso")
    activ = _find_prefix(grid, "31-60 days activation %")
    nonpmt = _find_row(grid, "non pmt %")
    total_amount = _find_row(grid, "total amount")
    need = {"CAPTAIN OVERRIDES": header, "Owners": owners,
            "Total Activations": total_act, "Total - All Units": total_units,
            "0-30 churn Team": churn_team, "0-30 churn Personal": churn_pers,
            "31-60 Activation": activ, "Non Pmt %": nonpmt,
            "TOTAL AMOUNT": total_amount}
    for nm, idx in need.items():
        if idx is None:
            raise ValueError(f"could not locate the {nm!r} row in column A")
    rep_first, rep_last = owners + 1, total_act - 1
    active = [i for i in range(rep_first, rep_last + 1)
              if i not in hidden and grid[i] and (grid[i][0] or "").strip()]
    if not active:
        raise ValueError("no active (visible, named) rep rows found")
    hdr = grid[header]
    last_week_col = max((j for j, c in enumerate(hdr) if _LABEL_RE.match(c or "")),
                        default=1)
    return Layout(header, total_act, total_units, churn_team, churn_pers,
                  activ, nonpmt, total_amount, rep_first, rep_last, active,
                  last_week_col)


def match_rep(sheet_name: str, reps: Dict[str, int]
              ) -> Tuple[Optional[int], Optional[str], List[str]]:
    """sheet name -> Total Activations. ALIAS -> exact full -> unique first
    name. Returns (value, matched_full, candidates)."""
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
            lines.append(f"  {name:<20} = {val:>4}   ({full})")
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
                   f"matched, Total Activations {total_val} (Tableau {pull.grand_total})"
                   f" · churn team {pull.churn_team} · churn Carlos {pull.churn_personal}"
                   f" · activation {pull.activation} · non-pmt {pull.nonpmt} — "
                   + ("column exists -> refresh in place" if refresh
                      else "insert NEW leftmost column")))
    if auto_roster and new_full:
        log.append("  ➕ ADD rows: " + ", ".join(roster._title(f) for f in new_full))
    if auto_roster and returning:
        log.append("  ♻ UNHIDE (back on team): " + ", ".join(returning.values()))
    if auto_roster and departed_names:
        log.append("  ➖ HIDE (left team): " + ", ".join(departed_names))

    rep = dict(label=label, total=total_val, matched=matched, unmatched=unmatched,
               ambiguous=ambiguous,
               new_reps=[(f, pull.reps.get(f, 0)) for f in new_full],
               hidden_departed=departed_names, churn_team=pull.churn_team,
               churn_personal=pull.churn_personal, activation=pull.activation,
               nonpmt=pull.nonpmt, log=log, layout=lay, wrote=False)
    if dry_run:
        return rep

    # ---------------- WRITE ----------------
    # 1) roster structural changes first (hide/unhide before any insert), then
    #    re-resolve the (now shifted) layout + re-match.
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

    metrics = {lay.churn_team: pull.churn_team, lay.churn_pers: pull.churn_personal,
               lay.activ: pull.activation, lay.nonpmt: pull.nonpmt}
    if not refresh:
        # "insert cells, shift right" over the weekly block only (header ..
        # TOTAL AMOUNT), col B — preserves the top reference tables. Old B is
        # now C; clone it back into B (format + formulas), then repurpose B.
        hdr0, last_row = lay.header, lay.total_amount
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [
            {"insertRange": {"range": {
                "sheetId": gid, "startRowIndex": hdr0, "endRowIndex": last_row + 1,
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
        updates = [{"range": f"B{lay.header + 1}", "values": [[label]]}]
        for ri in range(lay.rep_first, lay.rep_last + 1):   # clear + set matched
            updates.append({"range": f"B{ri + 1}", "values": [[matched.get(ri, "")]]})
        for ri, v in metrics.items():
            updates.append({"range": f"B{ri + 1}", "values": [[v or ""]]})
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
    else:
        updates = [{"range": f"B{ri + 1}", "values": [[v]]}
                   for ri, v in matched.items()]
        # blank this week for any hidden (departed) rep so they don't keep a
        # stale value in the Total on a same-week re-run.
        for ri in range(lay.rep_first, lay.rep_last + 1):
            if ri in hidden:
                updates.append({"range": f"B{ri + 1}", "values": [[""]]})
        for ri, v in metrics.items():
            updates.append({"range": f"B{ri + 1}", "values": [[v or ""]]})
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")

    # Black out each newly-added rep's PRIOR week cells (C .. last week) — they
    # weren't on the team those weeks (the Loom's manual black-out).
    for r0 in new_rows:
        roster.blackout(ws, gid, r0, 2, lay.last_week_col + 2)

    _repoint_chart(ws, sh, gid, lay)
    rep["wrote"] = True
    log.append(f"chart series -> row {lay.total_units + 1} (Total - All Units), "
               f"domain row {lay.header + 1}")
    return rep


def _repoint_chart(ws, sh, gid: int, lay: Layout) -> None:
    """Point the chart's series at the Total - All Units row and its domain at
    the header week labels, spanning B .. rightmost week. Mutates the existing
    source ranges IN PLACE so the series color / chart type are preserved."""
    meta = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId),charts(chartId,spec,position))"})
    chart = None
    for s in meta.get("sheets", []):
        if s.get("properties", {}).get("sheetId") != gid:
            continue
        if s.get("charts"):
            chart = s["charts"][0]
        break
    if not chart:
        return
    bc = chart["spec"].get("basicChart")
    if not bc or not bc.get("domains") or not bc.get("series"):
        return
    c1, c2 = 1, lay.last_week_col + 2          # B .. (last week + inserted col)

    def _point(container, row0):
        src = container["sourceRange"]["sources"][0]
        src["sheetId"] = gid
        src["startRowIndex"], src["endRowIndex"] = row0, row0 + 1
        src["startColumnIndex"], src["endColumnIndex"] = c1, c2

    _point(bc["domains"][0]["domain"], lay.header)
    _point(bc["series"][0]["series"], lay.total_units)
    # Green fill (Carlos brand green #6AA84F) — set only when the series has no
    # color, so a color picked later in the UI is preserved.
    if not bc["series"][0].get("colorStyle") and not bc["series"][0].get("color"):
        bc["series"][0]["colorStyle"] = {"rgbColor": _GREEN}
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
        "updateChartSpec": {"chartId": chart["chartId"], "spec": chart["spec"]}}]})


# Carlos brand green (#6AA84F) for the performance chart's area/series.
_GREEN = {"red": 106 / 255, "green": 168 / 255, "blue": 79 / 255}
