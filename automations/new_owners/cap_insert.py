"""Give a captainship rep a row in EVERY table that captainship owns.

Until now this was `roster_sync.auto_insert_missing`, which read the VA's own
board to learn which tables a rep sits in and cloned those rows onto the copy.
The VA board has not been maintained for weeks (Eve, 2026-08-10), so that
template is gone. This module builds the same rows from the COPY TAB ITSELF:
each of the captainship's tables is found structurally and the new row is cloned
from the table's own last rep.

A fiber captain owns SIX tables, and a rep missing from any one of them is a
silent undercount somewhere:

    box 📶 New Internet   leaderboard (name + =SUMIF over the daily block)
                          daily       (Mon-Sun + =SUM + frozen K/L)
    box 🛜 All Units      leaderboard
                          daily
    bottom delta table    one per box ('NEW INTERNET UNITS' / 'ALL UNITS'):
                          per-day THIS WEEK / LAST WEEK / DELTA triplets, where
                          THIS WEEK is a =SUMIF that hardcodes the rep's NAME as
                          a string — which is why rows are cloned and patched,
                          never written from scratch.

Every captain with one box owns three of them. The delta tables are matched to a
captain by the '<NAME> CAPTAINSHIP' label above their header, so a table nobody
claims (RAF SPECIAL) is left alone.

WHERE THE ROW GOES: before the table's LAST rep row, for the same reason as the
campaign blocks — Google only auto-expands a range when the insert lands inside
it, and these tables are enclosed by TOTALS sums, leaderboard =SUMIFs and the
delta table's 'Captainship' row. Inserts run BOTTOM-UP so an earlier row number
never shifts under a later insert.

WHAT IS KEPT AND WHAT IS BLANKED: every formula on the sibling row is kept
(copyPaste re-points its relative refs) with the sibling's name literal swapped
for the new rep's; every static value is blanked. Static means history, so
keeping it would invent sales that never happened; the day cells are static too
and the captainship fill writes the real ones in this same run.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

from automations.recruiting_report.fill import _retry
from automations.org_sales_board import captainship as cap
from automations.org_sales_board import rollover as ro
from automations.org_sales_board import fill_section as fs
from automations.new_owners.board_add import _guard, _a1, _cell

MAX_WIDTH = 120           # cols A..DP — past the widest leaderboard history
CAPTAINSHIP_LABEL = re.compile(r"^(.*?)\s+captainship\b", re.I)


def _table_width(grid: List[List[str]], rows: List[int]) -> int:
    """Widest used column across a table's rows (capped). The leaderboards carry
    two years of week columns, the delta tables ~26 — cloning per table instead
    of one fixed width keeps a copyPaste from dragging a neighbour's cells."""
    w = 2
    for r in rows:
        row = grid[r - 1] if r - 1 < len(grid) else []
        for c in range(len(row), 0, -1):
            if str(row[c - 1]).strip():
                w = max(w, c)
                break
    return min(w, MAX_WIDTH)


def _delta_captain(grid: List[List[str]], header_row: int) -> str:
    """Which captainship a delta table belongs to, from the '<NAME> CAPTAINSHIP'
    label sitting just above its header. Empty when nothing claims it.

    Read from col B **or col A**. The title bar of a delta box spans A:B, so the
    label lives in whichever of the two is the merge's top-left — col A on the
    boxes that carry a rank gutter (all of them since 2026-08-25,
    `org_sales_board/delta_ranks.py`), col B on any that still don't. Scanning
    col B alone left Raf's, Carlos' and Eveliz' boxes claimed by nobody, so a
    rep added to those captainships got a leaderboard and a daily row but no
    delta row."""
    for r in range(header_row - 1, max(header_row - 4, 0), -1):
        for c in (2, 1):
            m = CAPTAINSHIP_LABEL.match(_cell(grid, r, c))
            if m and m.group(1).strip():
                return m.group(1).strip()
    return ""


def _owns_box(anc, want_first: str) -> bool:
    """Does this box belong to the captain we asked for?

    A box's span ends at the NEXT captain's title row, so a block that carries
    no title at all is swallowed by the captain above it — on this board the NDS
    box at row ~1314 (Khalil's reps, no 'CAPTAIN TEAM' title) sits inside
    Sahil's span and would otherwise get a row every time someone joined Sahil's
    captainship. Every captainship on this board lists its own captain among its
    reps, so that is the test."""
    for _r, nm in list(anc.leaderboard) + list(anc.daily):
        toks = (nm or "").split()
        if toks and toks[0].strip().lower() == want_first:
            return True
    return False


def tables_for(grid: List[List[str]], captain_title: str) -> List[dict]:
    """Every per-rep table of one captainship: [{kind, rows, width, ranked}]."""
    from automations.new_owners.captain_watch import captain_name
    want = captain_name(captain_title).lower()
    out: List[dict] = []
    try:
        boxes = cap.find_captainship_boxes(grid, captain_title)
    except Exception:
        boxes = []          # no titled block on the board — delta tables only
    # Keep only the boxes that actually name this captain — but if NONE do (a
    # captain who doesn't sell), keep them all rather than return nothing.
    owned = [(v, a) for v, a in boxes if _owns_box(a, want)]
    for variant, anc in (owned or boxes):
        box = variant or "single"
        for kind, pairs in (("leaderboard", anc.leaderboard), ("daily", anc.daily)):
            rows = [r for r, _n in pairs]
            if rows:
                out.append({"kind": f"{kind}/{box}", "rows": rows,
                            "width": _table_width(grid, rows),
                            "ranked": _cell(grid, rows[0], 1).isdigit()})
    for t in ro.find_delta_tables(grid):
        if captain_name(_delta_captain(grid, t["header_row"])).lower() != want:
            continue
        rows = t["data_rows"]
        if not rows:
            continue
        # col B or col A — see _delta_captain. Without the col-A fallback a
        # captain's two boxes both come back as 'delta/delta' and the log stops
        # saying which one a rep landed in.
        label = (_cell(grid, t["header_row"], 2)
                 or _cell(grid, t["header_row"], 1) or "delta")
        out.append({"kind": f"delta/{label.lower()}", "rows": rows,
                    "width": _table_width(grid, rows),
                    "ranked": _cell(grid, rows[0], 1).isdigit()})
    return out


def has_rep(grid: List[List[str]], tables: List[dict], name: str,
            aliases) -> Optional[str]:
    """The first table this rep is already in, or None. Alias-aware, so a
    spelling variant counts as present and never gets a second row."""
    want = fs._candidates_for(name, aliases)
    for t in tables:
        for r in t["rows"]:
            if fs._candidates_for(_cell(grid, r, 2), aliases) & want:
                return t["kind"]
    return None


def add_rep(ws, captain_title: str, name: str, *, aliases=None,
            dry_run: bool = False, logfn=print) -> dict:
    """Insert `name` into every table of `captain_title`. Returns
    {'rows': {kind: row}, 'already': kind|None}."""
    from automations.focus_office_att.aliases import load_aliases
    _guard(ws)
    aliases = aliases if aliases is not None else load_aliases()
    grid = _retry(ws.get_all_values)
    tables = tables_for(grid, captain_title)
    # A delta table alone is not enough: a rep with a delta row and no
    # leaderboard/daily row is worse than absent (they'd show a week total that
    # no daily block feeds). Refuse rather than half-place them — the gate keeps
    # the rep pending and says so, which is a fixable state.
    if not any(t["kind"].startswith(("leaderboard", "daily")) for t in tables):
        raise ValueError(
            f"no leaderboard/daily block found for {captain_title!r} on the "
            f"board (found: {[t['kind'] for t in tables] or 'nothing'}). Its "
            f"block may be missing the '<NAME> CAPTAIN TEAM' title row.")
    where = has_rep(grid, tables, name, aliases)
    if where:
        logfn(f"    {name} already has a row in {captain_title} ({where}) — "
              f"nothing to insert")
        return {"rows": {}, "already": where}

    ops = []
    for t in tables:
        rows = t["rows"]
        interior = len(rows) >= 2
        at = rows[-1] if interior else rows[-1] + 1
        ops.append({**t, "at": at, "interior": interior,
                    "sibling": _cell(grid, at - 1, 2)})
    ops.sort(key=lambda o: o["at"], reverse=True)   # bottom-up: rows stay valid

    if dry_run:
        for o in ops:
            logfn(f"    (dry-run) {captain_title}: would insert {name!r} at row "
                  f"{o['at']} in {o['kind']} (clone of {o['sibling']!r})")
        return {"rows": {o["kind"]: o["at"] for o in ops}, "already": None,
                "dry_run": True}

    placed: Dict[str, int] = {}
    for o in ops:
        at, w = o["at"], o["width"]
        _retry(ws.spreadsheet.batch_update, {"requests": [
            {"insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": at - 1, "endIndex": at},
                "inheritFromBefore": True}},
            {"copyPaste": {
                "source": {"sheetId": ws.id, "startRowIndex": at - 2,
                           "endRowIndex": at - 1, "startColumnIndex": 0,
                           "endColumnIndex": w},
                "destination": {"sheetId": ws.id, "startRowIndex": at - 1,
                                "endRowIndex": at, "startColumnIndex": 0,
                                "endColumnIndex": w},
                "pasteType": "PASTE_NORMAL"}}]})
        time.sleep(1)
        pasted = _retry(ws.get, f"A{at}:{_a1(w)}{at}",
                        value_render_option="FORMULA")
        pasted = pasted[0] if pasted else []
        sib = o["sibling"]
        upd = [{"range": f"{ws.title}!B{at}", "values": [[name]]}]
        for c, val in enumerate(pasted, start=1):
            if c == 2:
                continue                                  # col B set above
            s = str(val)
            if s.startswith("="):
                if sib and f'"{sib}"' in s:                # =SUMIF(…,"NAME",…)
                    upd.append({"range": f"{ws.title}!{_a1(c)}{at}",
                                "values": [[s.replace(f'"{sib}"', f'"{name}"')]]})
            elif s.strip():                                # history / day value
                upd.append({"range": f"{ws.title}!{_a1(c)}{at}", "values": [[""]]})
        _retry(ws.spreadsheet.values_batch_update,
               {"valueInputOption": "USER_ENTERED", "data": upd})
        placed[o["kind"]] = at
        logfn(f"    + {o['kind']}: row {at} (cloned {sib or 'the row above'}, "
              f"{len(upd) - 1} cell(s) cleared/patched"
              + ("" if o["interior"] else ", appended — check the block totals")
              + ")")

    # Ranks (col A) are a plain 1..N sequence on the leaderboard/daily tables;
    # an insert leaves the displaced number repeated. The delta tables have no
    # rank column, so they're skipped by the `ranked` flag.
    grid = _retry(ws.get_all_values)
    fixes = []
    for t in tables_for(grid, captain_title):
        if not t["ranked"]:
            continue
        rows = t["rows"]
        fixes.append({"range": f"{ws.title}!A{rows[0]}:A{rows[-1]}",
                      "values": [[i + 1] for i in range(len(rows))]})
    if fixes:
        _retry(ws.spreadsheet.values_batch_update,
               {"valueInputOption": "USER_ENTERED", "data": fixes})
    logfn(f"    {name} added to {len(placed)} table(s) of {captain_title}")
    return {"rows": placed, "already": None}
