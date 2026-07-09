"""Weekly fill of the "Captainship Head count" tab — the automated Loom.

Layout (discovered by label + hidden-row state, never hardcoded indices):
  row 1              A = blank; B = newest week ('M.D'), older weeks to the right
  rows 2..K          ACTIVE owners  (visible)
  rows K+1..T-1      DEPARTED owners (hidden via hiddenByUser) — left untouched
  row T              'Total'  =SUM(B2:B{T-1})

Weekly op (Loom method): insert a fresh leftmost week column (B) by cloning
last week's column into C for its format + total formula, then fill each
ACTIVE owner's Rep Count matched by name, let the SUM formula retotal, and
sort the active block high->low. Idempotent: if this week's column already
exists it refreshes the active cells in place instead of inserting again.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill as rfill

SPREADSHEET_ID = "1xQQLzE8mU-a4lpk1IK3WolTPlFxavuMzdK3jA7NGga8"
# Real tab name; override with CCH_TAB=... to target a sandbox copy for testing.
TAB = os.environ.get("CCH_TAB", "Captainship Head count")

# Sheet uses short names; Tableau uses FULL "ICD Owner Name"s. Most resolve by
# first name (+ last initial when the sheet disambiguates, e.g. 'Ryan K').
# ALIASES pins the ones a generic match can't get right — 'Joe' is JOSEPH
# ECKHART, but the B2B roster also has a JOE SHIPMAN, so first-name alone is
# ambiguous. Add a sheet-name -> exact-Tableau-name entry here if the run
# flags a new AMBIGUOUS owner.
ALIASES: Dict[str, str] = {
    "joe": "joseph eckhart",
}
# First-name nicknames for generic matching (kept minimal; extend as needed).
NICKNAMES: Dict[str, List[str]] = {}


def open_tab():
    sh = rfill.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(TAB), sh


def week_label(sunday: dt.date) -> str:
    """WE Sunday -> 'M.D' (no leading zeros, e.g. 7.5 / 6.28)."""
    return f"{sunday.month}.{sunday.day}"


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def hidden_rows(sh, gid: int, n_rows: int) -> set:
    """0-based indices of rows hidden by the user (departed owners)."""
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
    def __init__(self, header: int, total: int, active: List[int],
                 first_week_col: int):
        self.header = header                  # 0-based header row (0)
        self.total = total                    # 0-based 'Total' row
        self.active = active                  # 0-based ACTIVE (visible) rows
        self.first_week_col = first_week_col  # 0-based newest-week col (1 = B)


def resolve_layout(grid: List[List[str]], hidden: set) -> Layout:
    header = 0
    total = next((i for i, r in enumerate(grid)
                  if r and _norm(r[0]) == "total"), None)
    if total is None:
        raise ValueError("no 'Total' row found in column A")
    active = [i for i in range(header + 1, total)
              if i not in hidden and grid[i] and (grid[i][0] or "").strip()]
    if not active:
        raise ValueError("no active (visible, named) owner rows found")
    return Layout(header, total, active, first_week_col=1)


def _col_a1(idx0: int) -> str:
    """0-based column index -> A1 letter (0->A, 4->E, 26->AA…)."""
    s, n = "", idx0
    while True:
        n, r = divmod(n, 26)
        s = chr(65 + r) + s
        if n == 0:
            break
        n -= 1
    return s


def screenshot_range(grid: List[List[str]], lay: "Layout",
                     n_weeks: int = 4) -> str:
    """A1 range for the Monday DM screenshot: owner names (col A) + the
    `n_weeks` NEWEST week columns (B onward) + through the Total row. Clamps
    n_weeks to however many week columns actually exist. Derived from the
    live layout — never hardcoded indices."""
    hdr = grid[lay.header] if lay.header < len(grid) else []
    avail, c = 0, lay.first_week_col
    while c < len(hdr) and str(hdr[c]).strip():
        avail += 1
        c += 1
    n = max(1, min(n_weeks, avail or n_weeks))
    end_col = lay.first_week_col + n - 1        # 0-based last week column
    return f"A1:{_col_a1(end_col)}{lay.total + 1}"


def load_layout(ws, sh) -> Tuple[List[List[str]], "Layout"]:
    """Fresh (grid, Layout) read — used post-fill to compute the DM range."""
    grid = rfill._retry(ws.get_all_values)
    hidden = hidden_rows(sh, ws.id, len(grid))
    return grid, resolve_layout(grid, hidden)


def match_rep(sheet_name: str, counts: Dict[str, int]
              ) -> Tuple[Optional[int], Optional[str], List[str]]:
    """Resolve a sheet short-name to a Tableau Rep Count.

    Returns (rep_count, matched_full_name, candidates). rep_count/full are
    None when there is no unique match; `candidates` lists the ambiguous
    full names so the operator can pin one via ALIASES."""
    key = _norm(sheet_name)
    if not key:
        return None, None, []
    if key in ALIASES:
        full = ALIASES[key]
        if full in counts:
            return counts[full], full, [full]
        return None, None, []          # pinned name not in Tableau -> flag

    toks = key.split()
    first = toks[0]
    last_init = toks[1][0] if len(toks) > 1 and toks[1] else None
    firsts = set(NICKNAMES.get(first, [first]))
    cands = [full for full in counts
             if full.split() and full.split()[0] in firsts
             and (last_init is None
                  or (len(full.split()) > 1 and full.split()[1][:1] == last_init))]
    if len(cands) == 1:
        return counts[cands[0]], cands[0], cands
    return None, None, sorted(cands)


def _report(label, total, matched, unmatched, ambiguous, log, wrote):
    return {"label": label, "total": total, "matched": matched,
            "unmatched": unmatched, "ambiguous": ambiguous, "log": log,
            "wrote": wrote}


def run_fill(ws, sh, counts: Dict[str, int], we_sunday: dt.date,
             dry_run: bool = True, force_insert: bool = False) -> dict:
    gid = ws.id
    grid = rfill._retry(ws.get_all_values)
    hidden = hidden_rows(sh, gid, len(grid))
    lay = resolve_layout(grid, hidden)
    label = week_label(we_sunday)
    wk = lay.first_week_col                    # 1 (col B)
    total_last = lay.total                     # 0-based total idx == 1-based last data row
    log: List[str] = []

    # --- match each ACTIVE owner to a Rep Count ---
    matched: Dict[int, int] = {}
    unmatched: List[str] = []
    ambiguous: List[str] = []
    for ri in lay.active:
        name = (grid[ri][0] or "").strip()
        rep, full, cands = match_rep(name, counts)
        if rep is None:
            (ambiguous if len(cands) > 1 else unmatched).append(
                f"{name} -> {cands}" if len(cands) > 1 else name)
        else:
            matched[ri] = rep
            log.append(f"  {name:<12} = {rep:>3}   ({full})")

    total_val = sum(matched.values())
    cur_hdr = (grid[lay.header][wk]
               if len(grid[lay.header]) > wk else "").strip()
    already = (cur_hdr == label)
    refresh = already and not force_insert

    log.insert(0, (f"week {label}: {len(matched)}/{len(lay.active)} owners "
                   f"matched, total {total_val} — "
                   + ("column exists -> refresh in place" if refresh
                      else "insert NEW leftmost column")))

    if dry_run:
        return _report(label, total_val, matched, unmatched, ambiguous,
                       log, wrote=False)

    if not refresh:
        # Loom insert: new empty col C (index 2), clone old B (index 1) into it
        # (carries format + the SUM formula), then repurpose B as this week.
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [
            {"insertDimension": {"range": {
                "sheetId": gid, "dimension": "COLUMNS",
                "startIndex": 2, "endIndex": 3}, "inheritFromBefore": True}},
            {"copyPaste": {
                "source": {"sheetId": gid, "startRowIndex": 0,
                           "endRowIndex": lay.total + 1,
                           "startColumnIndex": 1, "endColumnIndex": 2},
                "destination": {"sheetId": gid, "startRowIndex": 0,
                                "endRowIndex": lay.total + 1,
                                "startColumnIndex": 2, "endColumnIndex": 3},
                "pasteType": "PASTE_NORMAL"}},
        ]})
        # Header as text (matches '6.28' style), then clear+fill the B body.
        rfill._retry(ws.update, range_name="B1", values=[[label]],
                     value_input_option="RAW")
        body: List[list] = []
        for ri in range(1, lay.total + 1):        # rows 2..Total
            if ri == lay.total:
                body.append([f"=SUM(B2:B{total_last})"])
            elif ri in matched:
                body.append([matched[ri]])
            else:
                body.append([""])                 # clears departed + unmatched
        rfill._retry(ws.update, range_name=f"B2:B{lay.total + 1}",
                     values=body, value_input_option="USER_ENTERED")
    else:
        # Column already present: refresh matched active cells only (don't
        # blank anything), and re-assert the Total formula.
        updates = [{"range": f"B{ri + 1}", "values": [[v]]}
                   for ri, v in matched.items()]
        updates.append({"range": f"B{lay.total + 1}",
                        "values": [[f"=SUM(B2:B{total_last})"]]})
        rfill._retry(ws.batch_update, updates,
                     value_input_option="USER_ENTERED")

    # Sort the ACTIVE block high->low by the new week column (B). sortRange
    # leaves the hidden departed rows (outside this range) untouched.
    a_first, a_last = min(lay.active), max(lay.active)
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
        "sortRange": {
            "range": {"sheetId": gid, "startRowIndex": a_first,
                      "endRowIndex": a_last + 1, "startColumnIndex": 0,
                      "endColumnIndex": ws.col_count},
            "sortSpecs": [{"dimensionIndex": wk, "sortOrder": "DESCENDING"}]}}]})
    log.append(f"sorted active rows {a_first + 1}-{a_last + 1} "
               f"high->low by '{label}'")
    return _report(label, total_val, matched, unmatched, ambiguous,
                   log, wrote=True)
