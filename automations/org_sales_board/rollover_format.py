"""FORMATTING repair for the Alphalete ORG Sales Board rollover.

The rollover (rollover.py) writes VALUES only — every call is
`ws.batch_update([{range, values}])`. Formatting is never carried along, so
three cosmetic defects accumulate week after week. Measured on the sandbox tab
2026-07-21:

  1. BORDERS — the leaderboard history GROWS one column per week
     (plan_leaderboard_rollover writes old C..last into D..last+1), and
     `last_col+1` is a virgin column with no borders. Confirmed: DH/DI/DJ carry
     TLR (header) / TBLR (data) while DK — last week's growth column — has none
     at all. Col D (the just-frozen week) is fine; the gap is at the RIGHT edge.

  2. COLUMN GROUPS — a group already exists (COLUMNS AC..DE, depth 1,
     collapsed) but it is stale on both ends: it leaves C..AB (26 weeks)
     expanded and the post-DE growth columns ungrouped. It has to be re-anchored
     to E..last_col+1 every rollover so only C (live week) + D (last frozen
     week) stay visible.

  3. MERGES / WE-stack row format — each captainship Product-Summary week-log
     row is an `A{r}:B{r}` merge (589 of them on the board, all 1 row x 2 cols;
     e.g. A258:B258 = 'WE 7.12'). `_roll_one_product_summary` inserts a row and
     writes A{top}, but an insertDimension does not reproduce the merge, and the
     inserted row loses the data-cell borders: row 257 ('WE 7.19', inserted by
     the last rollover) has NO borders on C..I while rows 258/259 below carry
     TBLR.

NOTE the leaderboard itself has ZERO merged cells — the merges live only in the
captainship WE-stacks. So the value shift needs no unmerge/re-merge dance.

Everything here is idempotent and SANDBOX-SCOPED (see _assert_sandbox). Run
standalone to repair the defects already on the board, or let run_rollover call
apply_all() as its final step so they never reopen.

    python -m automations.org_sales_board.rollover_format --dry-run
    python -m automations.org_sales_board.rollover_format --apply
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List, Optional, Tuple

from automations.org_sales_board import rollover as ro

SANDBOX_PREFIX = "Copy of Alphalete ORG Sales Board"

# Column offsets inside a leaderboard block, relative to first_col (col C):
#   +0 = the live current week   (formula — never a format source)
#   +1 = the just-frozen week    (col D)
#   +2 = an older frozen week    (col E) — the format TEMPLATE
_FORMAT_SRC_OFFSET = 2      # col E: a settled historical week


def _assert_sandbox(ws) -> None:
    """Refuse to format anything but the sandbox tab. Mirrors the guard in
    roster_sync.py:223 — the production tab is the VAs' and is never written
    by this module."""
    if not ws.title.startswith(SANDBOX_PREFIX):
        raise RuntimeError(
            f"rollover_format is sandbox-only: refusing to touch {ws.title!r} "
            f"(expected a tab starting with {SANDBOX_PREFIX!r})")


# --------------------------------------------------------------- discovery

def _leaderboard_blocks(grid: List[List[str]]) -> List[dict]:
    """Every leaderboard box that carries a weekly history: the ALPHALETE ORG
    block plus each captainship box (both boxes for fiber captains, the same
    pair the daily fill and the rollover write).

    Returned dicts are {title, header_row, first_row, last_row, last_col} —
    all 1-based, all discovered by label so a template change can't stale
    them ([[feedback_no_hardcoded_columns]])."""
    from automations.org_sales_board import captainship as cap

    out: List[dict] = []
    org = ro.find_org_block(grid)
    out.append({"title": "ALPHALETE ORG", "header_row": org.header_row,
                "first_row": org.data_rows[0], "last_row": org.data_rows[-1],
                "first_col": org.first_col, "last_col": org.last_col})

    for title, _tkey in cap.discover_captainships(grid):
        try:
            boxes = cap.find_captainship_boxes(grid, title)
        except Exception:      # a box that can't be found is not a format problem
            continue
        for variant, a in boxes:
            if not a.leaderboard:
                continue
            hdr_row = a.leaderboard[0][0] - 2
            rows = [r for r, _ in a.leaderboard]
            # Same last-col scan the rollover uses (rollover.py:366-367): the
            # last header cell that carries a WE label.
            hdr = grid[hdr_row - 1] if 0 < hdr_row <= len(grid) else []
            last_col = max((c + 1 for c in range(2, len(hdr))
                            if (hdr[c] or "").strip()), default=16)
            out.append({"title": f"{title} [{variant}]", "header_row": hdr_row,
                        "first_row": rows[0], "last_row": rows[-1],
                        "first_col": 3, "last_col": last_col})
    return out


# ------------------------------------------------------- (1) borders

def _paste_format_request(sheet_id: int, src_col: int, dst_col: int,
                          row0: int, row1: int) -> dict:
    """copyPaste PASTE_FORMAT of one whole column slice. Carries borders,
    background, font and number format in a single request — more faithful
    than hand-building updateBorders, and it matches whatever the historical
    columns already look like instead of hardcoding a border style."""
    return {"copyPaste": {
        "source": {"sheetId": sheet_id,
                   "startRowIndex": row0 - 1, "endRowIndex": row1,
                   "startColumnIndex": src_col - 1, "endColumnIndex": src_col},
        "destination": {"sheetId": sheet_id,
                        "startRowIndex": row0 - 1, "endRowIndex": row1,
                        "startColumnIndex": dst_col - 1, "endColumnIndex": dst_col},
        "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}}


def plan_border_requests(ws, grid, blocks: Optional[List[dict]] = None
                         ) -> Tuple[List[dict], List[str]]:
    """Re-format the growth column of every leaderboard box from a settled
    historical column (col E).

    Covers the header row THROUGH the last data row, so the per-rep history
    rows get the same treatment as the header — not just the top line.

    Two destination columns per box:
      • last_col + 1 — next week's growth column (pre-formatted so the NEXT
        rollover lands on a bordered column);
      • last_col     — the column the PREVIOUS rollover already grew into and
        left bare (DK on the ORG block today).
    Both are idempotent: pasting format twice is a no-op."""
    blocks = blocks if blocks is not None else _leaderboard_blocks(grid)
    reqs: List[dict] = []
    notes: List[str] = []
    for b in blocks:
        src = b["first_col"] + _FORMAT_SRC_OFFSET
        if src >= b["last_col"]:
            notes.append(f"    [{b['title']}] SKIP — history too narrow "
                         f"(first_col={b['first_col']} last_col={b['last_col']})")
            continue
        for dst in (b["last_col"], b["last_col"] + 1):
            reqs.append(_paste_format_request(
                ws.id, src, dst, b["header_row"], b["last_row"]))
        notes.append(
            f"    [{b['title']}] rows {b['header_row']}..{b['last_row']}: "
            f"format {ro.a1col(src)} -> {ro.a1col(b['last_col'])} + "
            f"{ro.a1col(b['last_col'] + 1)}")
    return reqs, notes


# --------------------------------------------------- (2) column groups

def _existing_column_groups(sh, sheet_id: int) -> List[dict]:
    md = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId),columnGroups)"})
    for s in md.get("sheets", []):
        if s.get("properties", {}).get("sheetId") == sheet_id:
            return s.get("columnGroups", []) or []
    return []


def _existing_row_groups(sh, sheet_id: int) -> List[dict]:
    md = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId),rowGroups)"})
    for s in md.get("sheets", []):
        if s.get("properties", {}).get("sheetId") == sheet_id:
            return s.get("rowGroups", []) or []
    return []


def stack_extent(grid: List[List[str]], top_row: int) -> int:
    """Last row (1-based) of a Product-Summary WE-stack that begins at
    `top_row` — walk down while col A keeps matching 'WE <digit>'."""
    end = top_row
    while end + 1 <= len(grid):
        nxt = (grid[end][0] or "").strip() if grid[end] else ""
        if not ro._WE_ROW_RE.match(nxt):
            break
        end += 1
    return end


def plan_row_group_requests(ws, grid) -> Tuple[List[dict], List[str]]:
    """Collapse each captainship Product-Summary WE-stack so only its NEWEST
    week row stays visible.

    ROW groups, not column groups: the weekly history here is a vertical stack
    of 'WE m.d' rows owned by one block, so grouping rows hides exactly that
    block's old weeks and nothing else. (A COLUMN group cannot express this —
    it would hide the same columns on the daily sections, whose Mon..Sun/
    running-total columns are physically the same C..J.)

    Per block: group rows top+1 .. stack_end at depth 1, collapsed. The top row
    is left OUT of the group, so the newest week is always the one on screen.

    Existing groups that overlap a stack are deleted first. They have drifted
    badly — measured 2026-07-22: the row INSERT that each rollover performs
    pushes a group's startIndex down with it, so a group that used to begin at
    top+1 now begins at top+2 and a second week row leaks into view; others
    spill dozens of rows past the end of their stack, and almost all read
    collapsed=None (expanded), so the grouping was doing nothing. Rebuilding
    from the discovered stack bounds is what makes this self-correcting.

    Groups that do NOT overlap a WE-stack are left alone — notably the eight
    'Prior Week'/'3 Weeks Prior' campaign-history groups (rows 96..202), which
    are a separate, legitimate grouping."""
    blocks = ro.find_captainship_product_summaries(grid)
    stacks = []
    for b in blocks:
        top = b["top_row"]
        end = stack_extent(grid, top)
        if end <= top:               # single-row stack: nothing to collapse
            continue
        stacks.append((top, end, ro._captain_for_row(grid, b["totals_row"])))

    reqs: List[dict] = []
    notes: List[str] = []

    # delete every existing row group that overlaps a stack (0-based half-open)
    for g in _existing_row_groups(ws.spreadsheet, ws.id):
        rng = g.get("range", {}) or {}
        if rng.get("dimension") != "ROWS":
            continue
        s, e = rng.get("startIndex", 0), rng.get("endIndex", 0)
        hit = next(((t, en, c) for t, en, c in stacks
                    if s < en and e > t - 1), None)
        if hit is None:
            continue                 # campaign-history / unrelated group — keep
        reqs.append({"deleteDimensionGroup": {"range": {
            "sheetId": ws.id, "dimension": "ROWS",
            "startIndex": s, "endIndex": e}}})
        notes.append(f"    delete stale group rows {s + 1}..{e} "
                     f"(collapsed={g.get('collapsed')}) overlapping "
                     f"[{hit[2]}] stack {hit[0]}..{hit[1]}")

    for top, end, cap in stacks:
        grp = {"sheetId": ws.id, "dimension": "ROWS",
               "startIndex": top, "endIndex": end}      # rows top+1..end
        reqs.append({"addDimensionGroup": {"range": grp}})
        reqs.append({"updateDimensionGroup": {
            "dimensionGroup": {"range": grp, "depth": 1, "collapsed": True},
            "fields": "collapsed"}})
        label = ro._cell(grid, top - 1, 0)
        notes.append(f"    [{cap}] group rows {top + 1}..{end} collapsed "
                     f"({end - top} week row(s) hidden); row {top} "
                     f"({label!r}) stays visible")
    return reqs, notes


# ------------------------------------- (3) WE-stack merges + row format

def _merged_row_anchors(sh, sheet_id: int) -> set:
    """{(row1, col1)} of every existing merge — so re-merging an already-merged
    WE row is skipped instead of erroring."""
    md = sh.fetch_sheet_metadata(params={
        "fields": "sheets(properties(sheetId),merges)"})
    out = set()
    for s in md.get("sheets", []):
        if s.get("properties", {}).get("sheetId") != sheet_id:
            continue
        for m in s.get("merges", []) or []:
            out.add((m.get("startRowIndex", 0) + 1,
                     m.get("startColumnIndex", 0) + 1))
    return out


def plan_we_stack_requests(ws, grid, merged: Optional[set] = None
                           ) -> Tuple[List[dict], List[str]]:
    """Repair the TOP row of every captainship Product-Summary WE-stack — the
    row the last rollover inserted:

      • merge A{top}:B{top} (MERGE_ALL) to match the 588 historical WE rows,
        skipped when the merge is already there;
      • PASTE_FORMAT from the row BELOW (top+1, a settled history row) across
        A..gt_col, restoring the data-cell borders the insert dropped.

    The format paste is row-oriented here (not column-oriented like the
    leaderboard) because a WE-stack grows DOWN, one row per week."""
    blocks = ro.find_captainship_product_summaries(grid)
    merged = merged if merged is not None else _merged_row_anchors(
        ws.spreadsheet, ws.id)
    reqs: List[dict] = []
    notes: List[str] = []
    for b in blocks:
        top = b["top_row"]
        gt = b["gt_col"]
        label = ro._cell(grid, top - 1, 0)
        cap = ro._captain_for_row(grid, b["totals_row"])
        if (top, 1) in merged:
            notes.append(f"    [{cap}] A{top} ({label!r}): already merged — "
                         f"merge skipped")
        else:
            reqs.append({"mergeCells": {"range": {
                "sheetId": ws.id,
                "startRowIndex": top - 1, "endRowIndex": top,
                "startColumnIndex": 0, "endColumnIndex": 2},
                "mergeType": "MERGE_ALL"}})
            notes.append(f"    [{cap}] A{top} ({label!r}): merge A:B")
        # borders/format from the settled row directly below
        reqs.append({"copyPaste": {
            "source": {"sheetId": ws.id,
                       "startRowIndex": top, "endRowIndex": top + 1,
                       "startColumnIndex": 0, "endColumnIndex": gt},
            "destination": {"sheetId": ws.id,
                            "startRowIndex": top - 1, "endRowIndex": top,
                            "startColumnIndex": 0, "endColumnIndex": gt},
            "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
        notes.append(f"    [{cap}] row {top}: format <- row {top + 1} "
                     f"(A..{ro.a1col(gt)})")
    return reqs, notes


# ------------------------------------------------------------ entrypoint

def apply_all(ws, *, dry_run: bool = True, logfn: Callable[[str], None] = print
              ) -> Dict[str, int]:
    """Plan (and optionally send) every formatting repair. Safe to call on any
    run: all three steps are idempotent.

    Returns counts per step. Sends ONE batch_update so the sheet never sits in
    a half-formatted state."""
    _assert_sandbox(ws)
    grid = ws.get_all_values()
    blocks = _leaderboard_blocks(grid)

    logfn(f"=== ORG board formatting — {ws.title!r} (dry_run={dry_run}) ===")
    logfn(f"  {len(blocks)} leaderboard box(es) discovered")

    b_reqs, b_notes = plan_border_requests(ws, grid, blocks)
    logfn(f"  1/3 borders — {len(b_reqs)} request(s)")
    for n in b_notes:
        logfn(n)

    g_reqs, g_notes = plan_row_group_requests(ws, grid)
    logfn(f"  2/3 WE-stack row groups — {len(g_reqs)} request(s)")
    for n in g_notes:
        logfn(n)

    w_reqs, w_notes = plan_we_stack_requests(ws, grid)
    logfn(f"  3/3 WE-stack merges + row format — {len(w_reqs)} request(s)")
    for n in w_notes:
        logfn(n)

    reqs = b_reqs + g_reqs + w_reqs
    counts = {"borders": len(b_reqs), "groups": len(g_reqs),
              "we_stack": len(w_reqs), "total": len(reqs)}
    if dry_run:
        logfn(f"  (dry-run — {len(reqs)} request(s) planned, nothing sent)")
        return counts
    if reqs:
        ws.spreadsheet.batch_update({"requests": reqs})
    logfn(f"  sent {len(reqs)} request(s) ✓")
    return counts


def main(argv=None) -> int:
    from automations.org_sales_board.run import SANDBOX_TAB, SHEET_ID
    from automations.recruiting_report.fill import open_by_key

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="send the requests (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", default=False)
    ap.add_argument("--tab", default=SANDBOX_TAB)
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ws = open_by_key(SHEET_ID).worksheet(args.tab)
    apply_all(ws, dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
