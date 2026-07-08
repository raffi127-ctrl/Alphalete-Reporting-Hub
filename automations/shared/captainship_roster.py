"""Shared roster reconciliation for the captainship-bonus reports (Raf + Carlos).

Keeps the sheet's rep list in sync with Tableau's team membership automatically:
  * HIDE a rep whose name is no longer in the Tableau team roster (they left).
  * ADD a rep who is on the Tableau roster but has no sheet row (new hire) —
    or UNHIDE their row if they had one hidden from a prior departure.

The "roster" is the set of current SFDC team members, passed in by the caller
(Raf: everyone in CB Activations incl 0-activation reps; Carlos: everyone in
CB-Owner Metrics). It is deliberately NOT the this-week activation list — a rep
with a 0-activation week is still on the roster and must NOT be hidden.

Row inserts go in the MIDDLE of the rep block so the Total's SUM range and the
chart series (re-resolved by label each run) expand to include them.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from automations.recruiting_report import fill as rfill

BLACK = {"red": 0.0, "green": 0.0, "blue": 0.0}


def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def match_name(sheet_name: str, full_names: Set[str], aliases: Dict[str, str]
               ) -> Optional[str]:
    """Resolve a sheet short-name to a roster full-name: alias -> exact ->
    unique first-name. Returns the matched full name or None."""
    key = _norm(sheet_name)
    if not key:
        return None
    if key in aliases:
        f = _norm(aliases[key])
        return f if f in full_names else None
    if key in full_names:
        return key
    first = key.split()[0]
    cands = [f for f in full_names if f.split() and f.split()[0] == first]
    return cands[0] if len(cands) == 1 else None


def _title(full: str) -> str:
    """Tableau ALL-CAPS name -> display case for a new sheet row."""
    return " ".join(w.capitalize() if w.isupper() or w.islower() else w
                    for w in full.split())


def plan(grid: List[List[str]], active_rows: List[int], hidden_rows: Set[int],
         rep_first: int, rep_last: int, roster: Set[str],
         aliases: Dict[str, str], name_col: int = 0
         ) -> Tuple[List[int], Dict[int, str], List[str]]:
    """Compute roster changes WITHOUT applying them.

    Returns (departed_rows, returning{row: full}, new_full_names):
      departed_rows  : visible rep rows whose name isn't in the roster -> hide.
      returning      : hidden rep rows whose name is back in the roster -> unhide.
      new_full_names : roster members with no sheet row at all -> insert.
    """
    covered: Set[str] = set()
    departed: List[int] = []
    for r in active_rows:
        nm = grid[r][name_col] if len(grid[r]) > name_col else ""
        m = match_name(nm, roster, aliases)
        if m:
            covered.add(m)
        else:
            departed.append(r)
    returning: Dict[int, str] = {}
    for r in range(rep_first, rep_last + 1):
        if r in hidden_rows and r not in active_rows:
            nm = grid[r][name_col] if len(grid[r]) > name_col else ""
            m = match_name(nm, roster, aliases) if nm else None
            if m and m not in covered:
                returning[r] = m
                covered.add(m)
    new_full = sorted(f for f in roster if f not in covered)
    return departed, returning, new_full


def set_hidden(ws, gid: int, rows0: List[int], hidden: bool = True) -> None:
    if not rows0:
        return
    reqs = [{"updateDimensionProperties": {
        "range": {"sheetId": gid, "dimension": "ROWS",
                  "startIndex": r, "endIndex": r + 1},
        "properties": {"hiddenByUser": hidden}, "fields": "hiddenByUser"}}
        for r in rows0]
    rfill._retry(ws.spreadsheet.batch_update, {"requests": reqs})


def insert_rows(ws, gid: int, at_row0: int, n: int) -> None:
    """Insert n blank rows at at_row0 (inheriting format from the row above)."""
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
        "insertDimension": {"range": {
            "sheetId": gid, "dimension": "ROWS",
            "startIndex": at_row0, "endIndex": at_row0 + n},
            "inheritFromBefore": True}}]})


def blackout(ws, gid: int, row0: int, c_start: int, c_end: int) -> None:
    """Paint a row's historical week cells black (a new rep wasn't on the team
    those weeks) — the Loom's manual black-out."""
    rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
        "repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": row0, "endRowIndex": row0 + 1,
                      "startColumnIndex": c_start, "endColumnIndex": c_end},
            "cell": {"userEnteredFormat": {"backgroundColor": BLACK}},
            "fields": "userEnteredFormat.backgroundColor"}}]})
