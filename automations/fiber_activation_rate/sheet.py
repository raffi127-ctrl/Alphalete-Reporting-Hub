"""Readable Fiber tabs, drawn from the log — same look as the NDS captain tabs.

TABS  'Activation by Rep - <Captain> (ATT Fiber)' — one per Captain's Bonus
      Team, plus 'Lumen Owners' for OUR owners Tableau files under
      'Unassigned' (see NO_CAPTAIN_OWNERS). Two boxes (0-30 = Rolling 4 Weeks, 30-60): the
      Captainship Avg, then every owner (their office total) with their reps
      folded underneath ('+' opens them), the newest day in column C and older
      days to the right. Redrawn from the log on every run — nobody types here.
      Named 'Activation by Rep' on purpose: the 'Activation Rate - <captain>
      (ATT Fiber)' tabs in the same workbook are per OFFICE, a different report.

The writer is nds_activation_rate.sheet.write_tab (one implementation of the
look); this module only lays out the rows.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List

from automations.nds_activation_rate import sheet as _nds
from automations.fiber_activation_rate import run as _run

CAPTAINSHIP = _run.CAPTAINSHIP
DAYS_SHOWN = 30
PALETTE = {"0-30": _nds.PALETTE["10-19"], "30-60": _nds.PALETTE["30-60"]}
CUTOFFS = {"0-30": _nds.CUTOFFS["10-19"], "30-60": _nds.CUTOFFS["30-60"]}


def short(team: str) -> str:
    """"Raf's Team" -> "Raf"; 'Unassigned' stays."""
    t = team.strip()
    return t[:-len("'s Team")] if t.endswith("'s Team") else t


def tab_name(team: str) -> str:
    return f"Activation by Rep - {short(team)} (ATT Fiber)"


def _title(name: str) -> str:
    from automations.captainship_churn.pull import _smart_title
    return _smart_title(name) if name.isupper() else name


def teams(grid) -> List[str]:
    return sorted({r[1] for r in grid[1:] if len(r) > 3 and r[1]})


def render(team: str, grid):
    """-> (rows, kinds, n_days) for nds write_tab."""
    vals: Dict = {}
    days = set()
    owners: List[str] = []
    for r in grid[1:]:
        if len(r) < 4 or r[1] != team:
            continue
        day, owner, rep = r[0], r[2], r[3]
        days.add(day)
        if owner != CAPTAINSHIP and owner not in owners:
            owners.append(owner)
        vals.setdefault((owner, rep), {})[day] = {
            k: (r[4 + i] if len(r) > 4 + i else "") for i, k in enumerate(_run.WIN_KEYS)}
    days = sorted(days, reverse=True)[:DAYS_SHOWN]
    newest = days[0] if days else ""

    def cells(key, win):
        per = vals.get(key, {})
        return [per.get(d, {}).get(win, "") for d in days]

    def pct(s):
        try:
            return float(s.rstrip("%"))
        except (ValueError, AttributeError):
            return None

    # Owners: best office total on the newest day first (blank last).
    def okey(o):
        v = pct(vals.get((o, _run.TOTAL), {}).get(newest, {}).get("0-30", ""))
        return (v is None, -(v or 0), o)
    owners.sort(key=okey)

    head = (f"{short(team).upper()}'S CAPTAINSHIP" if team.endswith("'s Team")
            else team.upper())
    rows: List[List[str]] = [[head + " - FIBER ACTIVATION BY REP"]]
    kinds: List = [(1, "title", "", -1)]
    for win in _run.WIN_KEYS:
        label = "0-30 DAYS (ROLLING 4 WEEKS)" if win == "0-30" else "30-60 DAYS"
        rows.append([])
        rows.append([f"ACTIVATION {label}", "Rep"] + [_nds._label(d) for d in days])
        kinds.append((len(rows), "box", win, -1))
        if any(cells((CAPTAINSHIP, _run.TOTAL), win)):
            rows.append(["Captainship Avg", ""] + cells((CAPTAINSHIP, _run.TOTAL), win))
            kinds.append((len(rows), "avg", win, -1))
        for i, owner in enumerate(owners):
            rows.append([_title(owner), "Office total"] + cells((owner, _run.TOTAL), win))
            kinds.append((len(rows), "owner", win, i))
            reps = {rep for (o, rep) in vals if o == owner and rep != _run.TOTAL
                    and any(cells((o, rep), win))}

            def rkey(rep, _o=owner, _w=win):
                c = [x for x in cells((_o, rep), _w) if x]
                v = pct(c[0]) if c else None
                return (v is None, -(v or 0), rep.lower())
            for rep in sorted(reps, key=rkey):
                rows.append(["", "   " + rep] + cells((owner, rep), win))
                kinds.append((len(rows), "rep", win, i))
    return rows, kinds, len(days)


# Tableau files owners with no captain under 'Unassigned' — 15 on 11/12, most
# of them not ours. Only OUR captain-less owners get a tab, under this name
# (Eve 11/12: the Lumen Owners group). An owner who gains a captain moves to
# that captain's tab by himself; one who becomes ours without a captain has to
# be added here.
UNASSIGNED = "Unassigned"
NO_CAPTAIN_TAB = "Lumen Owners"
NO_CAPTAIN_OWNERS = ("Lajahnik Valentine", "Nigel Marshall", "Aaron Nimako",
                     "David Pancoast")


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def no_captain_grid(grid):
    """The 'Unassigned' rows of OUR owners only, relabelled as the Lumen tab
    (no captainship avg: Tableau's 'Unassigned' total mixes in other owners)."""
    ours = {_norm(o) for o in NO_CAPTAIN_OWNERS}
    return [grid[0]] + [[r[0], NO_CAPTAIN_TAB] + r[2:] for r in grid[1:]
                        if len(r) > 3 and r[1] == UNASSIGNED and _norm(r[2]) in ours]


def draw(book, grid, only_teams=None, *, logfn=print) -> List[str]:
    done = []
    for team in teams(grid):
        if team == UNASSIGNED:
            if only_teams and NO_CAPTAIN_TAB not in only_teams:
                continue
            sub = no_captain_grid(grid)
            if len(sub) > 1:
                rows, kinds, n_days = render(NO_CAPTAIN_TAB, sub)
                done.append(_nds.write_tab(book, NO_CAPTAIN_TAB, rows, kinds, n_days,
                                           logfn=logfn, title=tab_name(NO_CAPTAIN_TAB),
                                           palette=PALETTE, cutoffs=CUTOFFS))
            continue
        if only_teams and team not in only_teams:
            continue
        rows, kinds, n_days = render(team, grid)
        done.append(_nds.write_tab(book, short(team), rows, kinds, n_days,
                                   logfn=logfn, title=tab_name(team),
                                   palette=PALETTE, cutoffs=CUTOFFS))
    return done


# ------------------------------------------------------------ the log tab --

def style_log(book, ws, n_rows: int) -> None:
    """Make the raw log readable: bold frozen header, % columns, widths,
    filter. Values are untouched."""
    sid = ws.id
    head = {"red": 0.043, "green": 0.239, "blue": 0.569}
    reqs = [
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": head, "horizontalAlignment": "CENTER",
                            "textFormat": {"bold": True, "foregroundColor": _nds.WHITE}}},
                        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"}},
        {"setBasicFilter": {"filter": {"range": {
            "sheetId": sid, "startRowIndex": 0, "endRowIndex": max(n_rows, 2),
            "startColumnIndex": 0, "endColumnIndex": len(_run.LOG_HEADER)}}}},
    ]
    for c0, px in ((0, 95), (1, 120), (2, 200), (3, 220), (4, 150), (5, 150)):
        reqs.append({"updateDimensionProperties": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c0 + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    book.batch_update({"requests": reqs})
