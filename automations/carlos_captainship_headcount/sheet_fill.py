"""Weekly fill of the "Captainship Head count" tab — the automated Loom.

Layout (discovered by label + hidden-row state, never hardcoded indices):
  row 1              A = blank; B = newest week ('M.D'), older weeks to the right
  rows 2..K          ACTIVE owners  (visible)
  rows K+1..T-1      DEPARTED owners (hidden via hiddenByUser) — left untouched
  row T              'Total'  =SUM(B2:B{T-1})

Weekly op (Loom method): reconcile the owner rows against the captainship
roster, insert a fresh leftmost week column (B) by cloning last week's column
into C for its format + total formula, then fill each ACTIVE owner's Rep Count
matched by name, let the SUM formula retotal, and sort the active block
high->low. Idempotent: if this week's column already exists it refreshes the
active cells in place instead of inserting again.

THE ROSTER IS NOT THIS TAB (2026-08-25). Whoever had a visible row used to get
counted, so a captainship change only landed if a person remembered to add or
hide a row — and WE 8.23 went out with Atef's group still inside Carlos' total
and Carlos' four new owners missing. `roster.board_roster()` reads the Org Sales
Board block instead (the ✅-gated list of record) and this module makes the tab
match it: new owner -> row inserted + history blacked out, owner who left ->
blanked from this week on, sorted to the bottom, hidden. History to the RIGHT is
never touched — a departed owner's past weeks stay exactly as they were, which
is how every earlier departure on this tab reads.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional, Set, Tuple

from automations.recruiting_report import fill as rfill
from automations.shared import captainship_roster as croster

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

# Sheet short name -> the board's spelling, for the ONE case a first name can't
# resolve (two owners sharing one). Empty on purpose: a spelling difference
# between the board and TABLEAU belongs in the 'ICD Aliases' tab, not here —
# this dict is only for the tab's own shorthand.
ROSTER_ALIASES: Dict[str, str] = {}


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


def match_rep_full(full_name: str, counts: Dict[str, int],
                   alias_table: Optional[dict] = None
                   ) -> Tuple[Optional[int], Optional[str], List[str]]:
    """Resolve a ROSTER full name to a Tableau Rep Count.

    Board spelling first, then every spelling the 'ICD Aliases' tab bridges it
    to ('Jeff Starr' -> 'Jeffrey Starr'), then the generic first-name match as a
    last resort. Aliases live in the Sheet, never in this file — per CLAUDE.md a
    name-spelling mismatch is an ICD Aliases row, not a per-report patch."""
    cands = [full_name]
    if alias_table:
        try:
            from automations.focus_office_att.aliases import get_search_candidates
            cands = get_search_candidates(full_name, alias_table) or cands
        except Exception:  # noqa: BLE001 — a bad alias read must not stop a fill
            pass
    for c in cands:
        k = _norm(c)
        if k in counts:
            return counts[k], k, [k]
    return match_rep(full_name, counts)


def _short_name(full: str, taken: Set[str]) -> str:
    """Board full name -> the tab's shorthand ('Gary Whitaker II' -> 'Gary').
    Falls back to 'First L' (the tab's own 'Ryan K' convention) when the first
    name is already on the tab, and to the full name if even that collides."""
    toks = (full or "").split()
    first = toks[0] if toks else (full or "")
    if first and _norm(first) not in taken:
        return first
    if len(toks) > 1:
        cand = f"{first} {toks[1][:1].upper()}"
        if _norm(cand) not in taken:
            return cand
    return full


class RosterPlan:
    """What the tab has to change to match the captainship roster."""

    def __init__(self, on_roster: Dict[int, str], departed: List[Tuple[int, str]],
                 returning: Dict[int, str], new: List[str]):
        self.on_roster = on_roster    # active row -> roster full name
        self.departed = departed      # (active row, sheet name) no longer on it
        self.returning = returning    # hidden row -> roster full name (unhide)
        self.new = new                # roster names with no row at all

    def empty(self) -> bool:
        return not (self.departed or self.returning or self.new)


def roster_plan(grid: List[List[str]], lay: "Layout", hidden: set,
                roster: List[str]) -> RosterPlan:
    """Reconcile the tab's owner rows against the roster. Read-only."""
    full_names = {_norm(n) for n in roster}
    display = {_norm(n): n for n in roster}
    on_roster: Dict[int, str] = {}
    departed: List[Tuple[int, str]] = []
    covered: Set[str] = set()
    for ri in lay.active:
        nm = (grid[ri][0] or "").strip()
        m = croster.match_name(nm, full_names, ROSTER_ALIASES)
        if m and m not in covered:
            on_roster[ri] = display[m]
            covered.add(m)
        else:
            departed.append((ri, nm))
    returning: Dict[int, str] = {}
    for ri in range(lay.header + 1, lay.total):
        if ri not in hidden or ri in lay.active:
            continue
        nm = (grid[ri][0] or "").strip() if ri < len(grid) and grid[ri] else ""
        m = croster.match_name(nm, full_names, ROSTER_ALIASES) if nm else None
        if m and m not in covered:
            returning[ri] = display[m]
            covered.add(m)
    new = [display[k] for k in full_names if k not in covered]
    new.sort(key=lambda n: roster.index(n))
    return RosterPlan(on_roster, departed, returning, new)


def n_week_cols(grid: List[List[str]], lay: "Layout") -> int:
    """How many week columns the tab actually has (consecutive filled headers
    from B). Used to black out a new owner's history — never a fixed width."""
    hdr = grid[lay.header] if lay.header < len(grid) else []
    n, c = 0, lay.first_week_col
    while c < len(hdr) and str(hdr[c]).strip():
        n += 1
        c += 1
    return n


def new_row_names(grid: List[List[str]], plan: RosterPlan) -> List[str]:
    """The col-A label for each new owner — the tab writes first names."""
    taken = {_norm(r[0]) for r in grid if r and (r[0] or "").strip()}
    out: List[str] = []
    for full in plan.new:
        short = _short_name(full, taken)
        taken.add(_norm(short))
        out.append(short)
    return out


def apply_roster_rows(ws, grid: List[List[str]], plan: RosterPlan,
                      lay: "Layout") -> Tuple[List[str], List[str]]:
    """Unhide returning owners and insert a row for each new one. Structural
    only — the week cells are filled by the normal pass that follows, and the
    new rows' history is blacked out after the sort (the column insert clones
    B's format into C, so painting before it would paint the wrong column).

    Returns (col-A labels of the rows added, log lines)."""
    log: List[str] = []
    if plan.returning:
        croster.set_hidden(ws, ws.id, sorted(plan.returning), hidden=False)
        log.append("  unhid (back on the captainship): "
                   + ", ".join(plan.returning[r] for r in sorted(plan.returning)))
    shorts: List[str] = []
    if plan.new:
        shorts = new_row_names(grid, plan)
        at = max(lay.active) + 1          # bottom of the ACTIVE block
        croster.insert_rows(ws, ws.id, at, len(shorts))
        rfill._retry(ws.update, range_name=f"A{at + 1}:A{at + len(shorts)}",
                     values=[[n] for n in shorts], value_input_option="RAW")
        log.append(f"  inserted {len(shorts)} new owner row(s) at {at + 1}: "
                   + ", ".join(f"{s} ({f})" for s, f in zip(shorts, plan.new)))
    return shorts, log


def _report(label, total, matched, unmatched, ambiguous, log, wrote,
            departed=(), added=()):
    return {"label": label, "total": total, "matched": matched,
            "unmatched": unmatched, "ambiguous": ambiguous, "log": log,
            "wrote": wrote,
            # Roster movement this run — what run.py reports back to the human.
            "departed": [nm for _r, nm in departed], "added": list(added)}


def run_fill(ws, sh, counts: Dict[str, int], we_sunday: dt.date,
             dry_run: bool = True, force_insert: bool = False,
             roster: Optional[List[str]] = None,
             alias_table: Optional[dict] = None) -> dict:
    gid = ws.id
    grid = rfill._retry(ws.get_all_values)
    hidden = hidden_rows(sh, gid, len(grid))
    lay = resolve_layout(grid, hidden)
    label = week_label(we_sunday)
    log: List[str] = []
    plan: Optional[RosterPlan] = None
    left: List[Tuple[int, str]] = []
    added: List[str] = []                      # col-A labels of rows just added

    # --- 0) reconcile the owner rows against the captainship roster ---
    if roster:
        plan = roster_plan(grid, lay, hidden, roster)
        for ri, nm in plan.departed:
            log.append(f"  OFF the captainship: {nm} (row {ri + 1}) — blanked "
                       f"from {label} on, then hidden; history kept")
        for full in plan.new:
            log.append(f"  NEW on the captainship: {full} — row inserted")
        if len(plan.departed) * 2 > len(lay.active):
            raise RuntimeError(
                f"the roster would drop {len(plan.departed)} of "
                f"{len(lay.active)} owners ({', '.join(n for _r, n in plan.departed)})"
                f" — that reads as a bad board read, not a captainship change. "
                f"Nothing written; re-run once the board looks right, or pass "
                f"--no-roster to fill the tab as-is.")
        if not dry_run and not plan.empty():
            added, rows_log = apply_roster_rows(ws, grid, plan, lay)
            log.extend(rows_log)
            # Re-read: the inserted rows shift every index below them, and the
            # new owners have to come back as ACTIVE rows to be filled at all.
            grid = rfill._retry(ws.get_all_values)
            hidden = hidden_rows(sh, gid, len(grid))
            lay = resolve_layout(grid, hidden)
            plan = roster_plan(grid, lay, hidden, roster)
        left = list(plan.departed)

    wk = lay.first_week_col                    # 1 (col B)
    total_last = lay.total                     # 0-based total idx == 1-based last data row
    left_rows = {ri for ri, _nm in left}

    # --- match each ACTIVE owner to a Rep Count ---
    matched: Dict[int, int] = {}
    unmatched: List[str] = []
    ambiguous: List[str] = []
    for ri in lay.active:
        if ri in left_rows:
            continue                           # off the captainship — stays blank
        name = (grid[ri][0] or "").strip()
        # With a roster we know the owner's FULL name, so the Tableau lookup goes
        # through the ICD Aliases bridge instead of guessing from a first name.
        if plan is not None and ri in plan.on_roster:
            rep, full, cands = match_rep_full(plan.on_roster[ri], counts,
                                              alias_table)
        else:
            rep, full, cands = match_rep(name, counts)
        if rep is None:
            (ambiguous if len(cands) > 1 else unmatched).append(
                f"{name} -> {cands}" if len(cands) > 1 else name)
        else:
            matched[ri] = rep
            log.append(f"  {name:<12} = {rep:>3}   ({full})")

    total_val = sum(matched.values())
    if dry_run and plan is not None and plan.new:
        # The new owners have no row to fill yet, so show what they WOULD add —
        # a plan whose total doesn't match the live run's is worse than no plan.
        for full in plan.new:
            rep, hit, _c = match_rep_full(full, counts, alias_table)
            total_val += rep or 0
            log.append(f"  {full:<12} = {rep if rep is not None else '?':>3}   "
                       f"({hit or 'NOT FOUND in Tableau'})  [new row]")
    cur_hdr = (grid[lay.header][wk]
               if len(grid[lay.header]) > wk else "").strip()
    already = (cur_hdr == label)
    refresh = already and not force_insert

    log.insert(0, (f"week {label}: {len(matched)}/"
                   f"{len(lay.active) - len(left_rows)} owners "
                   f"matched, total {total_val} — "
                   + ("column exists -> refresh in place" if refresh
                      else "insert NEW leftmost column")))

    if dry_run:
        return _report(label, total_val, matched, unmatched, ambiguous,
                       log, wrote=False, departed=left,
                       added=(plan.new if plan else ()))

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
        # blank anything), and re-assert the Total formula. An owner who left
        # the captainship IS blanked — that is the whole point of the roster
        # pass, and leaving their number would keep them in the total.
        updates = [{"range": f"B{ri + 1}", "values": [[v]]}
                   for ri, v in matched.items()]
        updates += [{"range": f"B{ri + 1}", "values": [[""]]} for ri in left_rows]
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

    if added or left:
        log.extend(_finish_roster(ws, sh, added, left))
    return _report(label, total_val, matched, unmatched, ambiguous,
                   log, wrote=True, departed=left, added=added)


def _finish_roster(ws, sh, added: List[str],
                   left: List[Tuple[int, str]]) -> List[str]:
    """Post-sort roster housekeeping, in the only order that is safe.

    Both jobs need the rows to have STOPPED moving: a new owner's history is
    blacked out where they landed, and a departed owner is hidden where they
    landed. Hiding BEFORE the sort would be the bug — `hiddenByUser` belongs to
    the row INDEX, not to the row's contents, so a hidden row in the middle of
    the sorted block ends up hiding whoever sorts into it.

    Departed owners have a blank week cell, so the sort drops them to the bottom
    of the active block. If one didn't land there we leave every row visible and
    say so: a visible owner with a blank week is harmless and self-evident, a
    wrongly hidden one is neither."""
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    hidden = hidden_rows(sh, ws.id, len(grid))
    lay = resolve_layout(grid, hidden)
    nweeks = n_week_cols(grid, lay)
    row_of = {_norm(grid[ri][0] if grid[ri] else ""): ri for ri in lay.active}

    # A new owner wasn't on the team for the weeks to the right — black them out,
    # the way the manual Loom does. Column B (this week) is theirs and stays.
    for short in added:
        ri = row_of.get(_norm(short))
        if ri is None or nweeks < 2:
            continue
        croster.blackout(ws, ws.id, ri, lay.first_week_col + 1,
                         lay.first_week_col + nweeks)
        log.append(f"  blacked out {short}'s history "
                   f"(row {ri + 1}, {nweeks - 1} past weeks)")

    if not left:
        return log
    want = {_norm(nm) for _r, nm in left}
    rows = sorted(ri for ri in lay.active
                  if _norm(grid[ri][0] if grid[ri] else "") in want)
    tail = list(range(max(lay.active) - len(rows) + 1, max(lay.active) + 1))
    if rows and rows == tail:
        croster.set_hidden(ws, ws.id, rows, hidden=True)
        log.append("  hid (off the captainship, history kept): "
                   + ", ".join(grid[r][0] for r in rows))
    elif rows:
        log.append("  ⚠ left the captainship but did NOT sort to the bottom "
                   f"({', '.join(grid[r][0] for r in rows)}) — rows left "
                   f"VISIBLE with a blank week; hide them by hand.")
    return log
