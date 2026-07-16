"""Roster sync — catch reps that exist on the VA captainship roster but have NO
row on the copy tab.

The captainship fill (`captainship.fill_captainship`) iterates the rows already
on the COPY tab and fills them; it NEVER creates a row for a rep that lives only
on the VA. So when a captain adds a new rep on the real board, the automation's
copy silently sums one rep short — every leaderboard total, product summary,
"Sales - This Week", grand total, and Delta % below it reads low, in the same
direction, until a human notices. (Diagnosed 2026-07-15: Starr's captainship was
short Fiber Tuesday 83/104 vs the VA's 89/117 — the entire gap was one missing
rep, Blue Mendoza, with no copy row.)

`missing_va_reps` is the READ-ONLY detector: it diffs each captainship's VA
roster against its copy roster (by normalized name + ICD aliases) and returns the
reps present on the VA but absent from the copy. The daily run gates on this
(loud INCOMPLETE flag) so a missing rep can never again be a SILENT undercount —
a non-match is surfaced up top, not buried. [[feedback_flag_nonmatched_icds]]
[[feedback_captainship_roster_truth]]

The auto-INSERT that clones a sibling row into every one of a captainship's
per-rep tables (leaderboard + daily for each box, plus the bottom delta tables)
is a separate, structural step — built and previewed before it writes. Read-only
here; writes nothing. [[project_org_sales_board]]
"""
from __future__ import annotations

from typing import List, Dict

from automations.org_sales_board import captainship as cap, fill_section as fs
from automations.alphalete_org_report.tableau_http import _norm_owner


def _cands(name: str, aliases) -> set:
    """Every alias-expanded, normalized key a roster name can match on — the same
    matcher the fill/compare use, so 'missing' here means the fill would also miss
    it (not a spelling drift the alias sheet already reconciles)."""
    return {k for k in fs._candidates_for(name, aliases) if k}


def missing_va_reps(copy_grid: List[List[str]], va_grid: List[List[str]],
                    aliases) -> List[Dict]:
    """Reps on a VA captainship roster with NO row on the copy tab.

    For each captainship discovered on the COPY board, gather the copy roster
    (every daily + leaderboard name across all of that captain's boxes) and the
    VA roster the same way, then return each VA rep whose alias-expanded name
    matches nothing on the copy. Position/table wiring is left to the inserter —
    this only answers WHO is missing, which is all the gate/flag needs.

    Read-only. Returns [{'captain': title, 'name': va_name}] deduped per
    (captain, normalized-name)."""
    out: List[Dict] = []
    seen_out: set = set()
    try:
        caps = [t for t, _hint in cap.discover_captainships(copy_grid)]
    except Exception:
        return out
    for t in caps:
        try:
            c_boxes = cap.find_captainship_boxes(copy_grid, t)
            v_boxes = cap.find_captainship_boxes(va_grid, t)
        except Exception:
            continue
        copy_keys: set = set()
        for _variant, anc in c_boxes:
            for _r, nm in anc.daily + anc.leaderboard:
                copy_keys |= _cands(nm, aliases)
        seen_va: set = set()
        for _variant, anc in v_boxes:
            for _r, nm in anc.daily + anc.leaderboard:
                keys = _cands(nm, aliases)
                if not keys:
                    continue
                norm = _norm_owner(nm)
                if norm in seen_va:
                    continue                 # same rep across boxes -> once
                seen_va.add(norm)
                if keys & copy_keys:
                    continue                 # has a copy row somewhere -> fine
                dedupe = (t, norm)
                if dedupe in seen_out:
                    continue
                seen_out.add(dedupe)
                out.append({"captain": t, "name": nm})
    return out


import re

# Column letters we CLONE as formulas from the sibling (running-total =SUM,
# leaderboard =SUMIF, delta =F+I / iferror / SUMIF); day/value + frozen-history
# cells are cleared so the pull + rollover fill them. Any sibling cell that is a
# formula is cloned; any non-formula cell is left blank/0 by table role.
def _is_formula(x) -> bool:
    return isinstance(x, str) and x.startswith("=")


def _rebase(formula: str, sib_row: int, new_row: int,
            sib_name: str, rep_name: str) -> str:
    """Clone a sibling formula onto the inserted row: relative self-references
    (the sibling's OWN row number, e.g. C862 / =SUM(C862:I862)) rebase to the new
    row; ABSOLUTE table ranges ($B$856:$B$864) are left for Google's insertDimension
    to auto-expand; a hard-coded sibling NAME literal in a delta =SUMIF
    ("William Sassenberg") swaps to the rep's name. Non-self row refs are left
    alone (they don't occur in these rows, but leaving them is safe)."""
    # self-row refs: a column letter (no $) immediately followed by the sibling's
    # exact row number, not part of a larger number ($ABS or a 4-digit share).
    out = re.sub(rf"(?<![\$\d])([A-Z]{{1,2}}){sib_row}(?!\d)",
                 lambda m: f"{m.group(1)}{new_row}", formula)
    if sib_name and sib_name in out:
        out = out.replace(f'"{sib_name}"', f'"{rep_name}"')
    return out


def plan_insert_ops(copy_grid: List[List[str]], copy_formulas: List[List[str]],
                    va_grid: List[List[str]], name: str, aliases) -> List[Dict]:
    """Plan every row-insert needed to give `name` a row in each per-rep table it
    occupies on the VA — using the VA as the structural template.

    For each VA row whose col-B is `name`, the rep's VA-PREDECESSOR (the nearest
    named row directly above, in the same table) is located on the COPY by name;
    the insert goes right after that copy row, cloning its formulas (row rebased,
    name-literal swapped). This is table-agnostic — leaderboards, daily tables and
    the bottom delta tables all resolve the same way. Read-only: returns the plan,
    writes nothing. Each op: {va_row, after_copy_row, sibling_name, new_cells}."""
    def bcell(g, r):
        return (g[r - 1][1] if r - 1 < len(g) and len(g[r - 1]) > 1 else "").strip()

    # copy: normalized name -> its row (first occurrence per table is enough since
    # we anchor on the immediate predecessor, which is unique within a table).
    copy_rows_by_key: Dict[str, List[int]] = {}
    for r in range(1, len(copy_grid) + 1):
        for k in _cands(bcell(copy_grid, r), aliases):
            copy_rows_by_key.setdefault(k, []).append(r)

    ops: List[Dict] = []
    target = _cands(name, aliases)
    for vr in range(1, len(va_grid) + 1):
        if not (_cands(bcell(va_grid, vr), aliases) & target):
            continue
        # predecessor = nearest named row above vr (same table; stop at a blank-B
        # header gap of >1 so we don't cross into another table).
        pred_row, gap = None, 0
        for up in range(vr - 1, max(vr - 15, 0), -1):
            if bcell(va_grid, up):
                pred_row = up
                break
            gap += 1
            if gap > 1:
                break
        if pred_row is None:
            ops.append({"va_row": vr, "after_copy_row": None,
                        "sibling_name": None, "note": "rep is first in its table "
                        "(no predecessor) — anchor to the table header on apply"})
            continue
        pred_keys = _cands(bcell(va_grid, pred_row), aliases)
        cand = sorted({r for k in pred_keys for r in copy_rows_by_key.get(k, [])})
        if not cand:
            ops.append({"va_row": vr, "after_copy_row": None,
                        "sibling_name": bcell(va_grid, pred_row),
                        "note": "predecessor has no copy row either — resolve after "
                        "earlier inserts"})
            continue
        # The predecessor name can recur across tables (a rep sits in the NI
        # leaderboard, the NI daily AND a delta table). Both tabs list the tables
        # in the same order, so the Kth occurrence of the pred on the VA pairs with
        # the Kth on the copy — pick THAT copy row, not a positional guess.
        pred_occ = sum(1 for up in range(1, pred_row + 1)
                       if _cands(bcell(va_grid, up), aliases) & pred_keys)
        after = cand[pred_occ - 1] if 0 < pred_occ <= len(cand) else cand[-1]
        sib_name = bcell(va_grid, pred_row)
        rep_name = bcell(va_grid, vr)
        width = max(len(copy_formulas[after - 1]) if after - 1 < len(copy_formulas)
                    else 0, 2)
        new_cells = {}
        for c in range(width):
            sib = (copy_formulas[after - 1][c]
                   if after - 1 < len(copy_formulas)
                   and c < len(copy_formulas[after - 1]) else "")
            col = _colletter(c + 1)
            if c == 1:                                  # col B = the rep's name
                new_cells[col] = rep_name
            elif _is_formula(sib):
                new_cells[col] = _rebase(sib, after, after + 1, sib_name, rep_name)
            # else: leave blank — day cells (pull fills), frozen history (rollover)
        ops.append({"va_row": vr, "after_copy_row": after,
                    "sibling_name": sib_name, "new_cells": new_cells})
    return ops


def _colletter(c: int) -> str:
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


_CLONE_WIDTH = 30   # cols A..AD — covers the widest delta table (through Z)


def auto_insert_missing(ws, va_grid: List[List[str]], aliases,
                        dry_run: bool = True, logfn=print) -> List[Dict]:
    """Give every VA-only captainship rep a row on the COPY tab so the very next
    fill can populate it. For each missing rep, plan_insert_ops locates the row it
    occupies in each per-rep table (leaderboards, dailies, both delta tables) via
    the VA template; each is inserted RIGHT AFTER its predecessor's copy row.

    Mechanics per row (leans on Google's own adjustment so nothing is hand-rebased
    wrong): insertDimension shifts the rows down AND auto-expands every SUMIF/SUM
    range that spans the insert point; copyPaste clones the sibling row's formulas
    with relative refs re-pointed; then a targeted override sets col B = the rep,
    swaps the sibling NAME literal in the delta =SUMIFs to the rep, and BLANKS the
    copied values (day cells + frozen history) so the pull/rollover fill real
    numbers rather than the sibling's. Inserts run BOTTOM-UP so earlier row indices
    never shift under a later insert.

    WORKSHEET-SCOPED — only ever the sandbox COPY tab (never the VA/real tab).
    Returns the reps added [{'captain','name','rows':[...]}]. dry_run: plan only,
    no writes. [[project_org_board_roster_sync]] [[feedback_captainship_roster_truth]]"""
    # HARD GUARD: only the copy tab or a "Copy of …"-prefixed test duplicate — the
    # VA/real tab ("Alphalete ORG Sales Board", no prefix) can never match.
    assert ws.title.startswith("Copy of Alphalete ORG Sales Board"), ws.title
    copy_grid = ws.get_all_values()
    copy_formulas = [[str(x) for x in row] for row in
                     ws.get_all_values(value_render_option="FORMULA")]
    missing = missing_va_reps(copy_grid, va_grid, aliases)
    if not missing:
        return []
    # Gather EVERY insert op across all missing reps, then apply bottom-up.
    all_ops = []
    for m in missing:
        for op in plan_insert_ops(copy_grid, copy_formulas, va_grid,
                                  m["name"], aliases):
            if op.get("after_copy_row"):
                all_ops.append({**op, "rep": m["name"], "captain": m["captain"]})
            else:
                logfn(f"  ⚠ roster: can't anchor {m['name']} @ VA row "
                      f"{op['va_row']} ({op.get('note','')}) — skipped, still gated")
    all_ops.sort(key=lambda o: o["after_copy_row"], reverse=True)
    if dry_run:
        logfn(f"  [dry-run] would insert {len(all_ops)} row(s) for "
              f"{len(missing)} rep(s): "
              + ", ".join(f"{o['rep']}@{o['after_copy_row']+1}" for o in all_ops))
        return [{"captain": m["captain"], "name": m["name"]} for m in missing]
    sid = ws.id
    for o in all_ops:
        after = o["after_copy_row"]          # 1-based row to insert AFTER
        new_row = after + 1
        ws.spreadsheet.batch_update({"requests": [
            {"insertDimension": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": after, "endIndex": after + 1},
                "inheritFromBefore": True}},
            {"copyPaste": {
                "source": {"sheetId": sid, "startRowIndex": after - 1,
                           "endRowIndex": after, "startColumnIndex": 0,
                           "endColumnIndex": _CLONE_WIDTH},
                "destination": {"sheetId": sid, "startRowIndex": after,
                                "endRowIndex": after + 1, "startColumnIndex": 0,
                                "endColumnIndex": _CLONE_WIDTH},
                "pasteType": "PASTE_NORMAL"}},
        ]})
        pasted = ws.get(f"A{new_row}:{_colletter(_CLONE_WIDTH)}{new_row}",
                        value_render_option="FORMULA")
        pasted = pasted[0] if pasted else []
        sib = o["sibling_name"] or ""
        upd = [{"range": f"B{new_row}", "values": [[o["rep"]]]}]
        for c, val in enumerate(pasted):
            if c == 1:
                continue                                  # col B handled above
            col = _colletter(c + 1)
            if _is_formula(val):
                if sib and f'"{sib}"' in val:             # delta name-literal swap
                    upd.append({"range": f"{col}{new_row}",
                                "values": [[val.replace(f'"{sib}"',
                                                        f'"{o["rep"]}"')]]})
                # other formulas: copyPaste already re-pointed them — keep
            elif str(val).strip():                        # copied value -> blank
                upd.append({"range": f"{col}{new_row}", "values": [[""]]})
        ws.batch_update(upd, value_input_option="USER_ENTERED")
        logfn(f"  + inserted {o['rep']} row at {new_row} "
              f"(cloned {sib or 'sibling'})")
    return [{"captain": m["captain"], "name": m["name"]} for m in missing]


def format_missing(missing: List[Dict]) -> str:
    """One-line-per-rep summary for the completion email / log."""
    if not missing:
        return "✅ every VA captainship rep has a row on the copy board."
    by: Dict[str, List[str]] = {}
    for m in missing:
        by.setdefault(m["captain"], []).append(m["name"])
    lines = [f"⚠ {len(missing)} rep(s) on the VA roster are MISSING a row on the "
             f"copy board (their sales never land — the total reads low):"]
    for capt, names in by.items():
        lines.append(f"   [{capt} captainship] {', '.join(sorted(names))}")
    return "\n".join(lines)
