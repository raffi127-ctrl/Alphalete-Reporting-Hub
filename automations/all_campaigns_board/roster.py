"""Keep the All Campaigns board's people list in sync with the Copy tab.

Eve, 2026-07-30: when someone is added to a CAMPAIGN section of 'Copy of
Alphalete ORG Sales Board', they must appear in EVERY people block of the
'All Campaigns Org Sales Board' tab — automatically, without waiting for them
to sell. (Captainship sections on the Copy tab are NOT a source; a rep's
campaign sales are already in their captainship box, so reading both would
double-count. aggregate.CAMPAIGN_SECTIONS is the same eight-section list.)

Why this exists at all: the fill was sheet-driven and only FLAGGED a missing
person, and only when they had production this week. Someone onboarded on a
Monday with no sales yet was silently absent from the ranking — today that is
Kevin Driggs and Selena Powers, neither of whom the flag ever mentioned.

THE THREE PEOPLE BLOCKS (found by label, never by row number):

  1. weekly leaderboard   col-A 'AT&T FIBER TEAM', col-C 'WE ..'   rows 18-55
       A =A{above}+1 · B name · C =SUMIF(daily B, B{r}, daily J) · D.. frozen
  2. daily section        col-A 'All Units' + 'RUNNING WEEK TOTALS'  rows 61-98
       A =A{above}+1 · B name · C..I day values · J =SUM(C:I) · K/L frozen
  3. bottom ranking       col-B 'All Units - All Campaigns'          rows 111-148
       B name · C/D/K formulas · every day column a SUMIF that hardcodes the
       name AS A STRING — which is why this block is copied from a neighbour
       row and then has that literal swapped, rather than rebuilt by hand.

All three blocks are RANKED BY PRODUCTION (org_sales_board.sort re-ranks them),
so a new person is appended at the BOTTOM of each — which is where someone
starting at 0 belongs, and the next sort moves them on their numbers.

FROZEN HISTORY IS NEVER COPIED. A new row's past-week cells are left blank on
purpose: inheriting the neighbour's history would invent sales that never
happened, and those columns feed the vs-Prior-Week and 4-week-average boxes.

Never removes anyone. A rep who leaves a campaign keeps their row and their
history [[feedback_fill_but_flag]].
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.org_sales_board import fill_section as fs
from automations.all_campaigns_board import aggregate as agg
from automations.all_campaigns_board import rollover as rj

RANKING_LABEL = "All Units - All Campaigns"   # col-B header of block 3

# People who are on a campaign but must NOT get a row on this board. Without
# this the auto-add is a resurrection machine: Eve deleted these two by hand on
# 2026-07-31 and the very next run would have put them straight back, every
# run, forever. A hand deletion is a decision — it has to outlive the sync.
# Matched on the normalized name, so spelling variants are covered.
EXCLUDE: set = {
    "kevin driggs",
    "selena powers",
}


def _cell(grid, r0: int, c0: int) -> str:
    if r0 < 0 or r0 >= len(grid):
        return ""
    row = grid[r0]
    return str(row[c0]).strip() if c0 < len(row) else ""


def find_ranking_block(grid: List[List[str]]) -> dict:
    """Block 3 by its col-B header. Data rows are the col-B non-empty rows
    below the header's sub-header row, stopping at the first gap."""
    hr = None
    for i in range(len(grid)):
        if _cell(grid, i, 1).lower() == RANKING_LABEL.lower():
            hr = i + 1
            break
    if hr is None:
        raise ValueError(f"Ranking block {RANKING_LABEL!r} (col-B header) not found.")
    rows: List[int] = []
    started = False
    for i in range(hr, len(grid)):
        b = _cell(grid, i, 1)
        if not b:
            if started:
                break            # trailing gap ends the block
            continue             # the 'Total this week' sub-header row
        if b.lower().startswith("total"):
            continue
        started = True
        rows.append(i + 1)
    return {"header_row": hr, "data_rows": rows}


@dataclass
class RosterPlan:
    """What would be added, and where. Rows are PRE-INSERT 1-indexed."""
    names: List[str] = field(default_factory=list)
    weekly_at: Dict[str, int] = field(default_factory=dict)
    daily_at: Dict[str, int] = field(default_factory=dict)
    ranking_at: Dict[str, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.names)


def missing_from_board(copy_grid, tgt_grid, today, *, raw_aliases=None,
                       logfn=print) -> List[str]:
    """Names present in a Copy-tab campaign section with NO row on the board.

    Production is deliberately NOT a condition — being on a campaign is what
    earns a line on this board."""
    raw_aliases = raw_aliases if raw_aliases is not None else fs.load_aliases()
    pull, name_index = agg.build_pull(copy_grid, today, logfn=lambda *_: None)
    anchor = fs.find_daily_section(tgt_grid, agg_target_label())

    board_keys = set()
    for name in anchor.icd_rows:
        board_keys |= fs._candidates_for(name, raw_aliases)

    out: List[str] = []
    for key in pull:
        raw = name_index.get(key, [key])[0]
        if fs._candidates_for(raw, raw_aliases) & board_keys:
            continue
        if raw.strip().lower() in EXCLUDE or key in EXCLUDE:
            logfn(f"  roster: {raw!r} is on a campaign but EXCLUDED "
                  f"(deleted by hand) — not adding")
            continue
        out.append(raw)
    return sorted(out)


def agg_target_label() -> str:
    """The daily section's label on the board. Imported lazily from run to
    avoid a circular import at module load."""
    from automations.all_campaigns_board.run import TARGET_SECTION
    return TARGET_SECTION


def _insert_position(rows: List[int]) -> int:
    """The 1-indexed row to INSERT AT: the BOTTOM of the block.

    Not alphabetical. These blocks are RANKED BY PRODUCTION — the board looked
    alphabetical in a snapshot taken between sorts, and inserting on that
    assumption put a 0-sales rep at rank 4 on the live board (2026-07-31).
    org_sales_board.sort re-ranks the blocks anyway, so the only position that
    is right in both worlds is last: a rep who starts at 0 belongs at the
    bottom, and the next sort moves them to wherever their numbers say."""
    return (rows[-1] + 1) if rows else 0


def plan(copy_grid, tgt_grid, today, *, raw_aliases=None, logfn=print) -> RosterPlan:
    """Where each missing person would go in all three blocks."""
    names = missing_from_board(copy_grid, tgt_grid, today,
                               raw_aliases=raw_aliases, logfn=logfn)
    p = RosterPlan(names=names)
    if not names:
        return p
    wk = rj.find_leaderboard_block(tgt_grid)
    daily = fs.find_daily_section(tgt_grid, agg_target_label())
    rank = find_ranking_block(tgt_grid)
    daily_rows = sorted(daily.icd_rows.values())
    for n in names:
        p.weekly_at[n] = _insert_position(wk["data_rows"])
        p.daily_at[n] = _insert_position(daily_rows)
        p.ranking_at[n] = rank["data_rows"][-1] + 1     # 0 sales -> bottom
    return p


# --------------------------------------------------------------------- apply
def _rank_col_a(ws, at: int, *, first_row: int, last_row: int) -> List[dict]:
    """Col-A rank cells for a row just inserted at `at`, AND the repair of the
    row below it.

    The blocks number themselves with `=A{above}+1`. Inserting a row does not
    re-point the row that used to sit there: its formula still names the cell
    ABOVE the insert (that cell did not move), so the new row's number gets
    repeated and every number below is one short — '…26, 27, 27, 28…' on the
    first live test. Rewriting the NEXT row's formula re-links the chain, and
    everything below it follows automatically.

    `last_row` is the block's totals row: `at + 1` is a data row only while it
    is above that. Pass the PRE-INSERT totals row — after the insert it sits one
    lower, which is exactly the bound we want to compare against.
    """
    out = [{"range": f"{ws.title}!A{at}",
            "values": [[1 if at == first_row else f"=A{at - 1}+1"]]}]
    if at + 1 <= last_row:                      # a data row follows this one
        out.append({"range": f"{ws.title}!A{at + 1}",
                    "values": [[f"=A{at}+1"]]})
    return out


def _insert_row(ws, row: int) -> None:
    """One row at `row` (1-indexed), inheriting the row above's formatting."""
    ws.spreadsheet.batch_update({"requests": [{
        "insertDimension": {
            "range": {"sheetId": ws.id, "dimension": "ROWS",
                      "startIndex": row - 1, "endIndex": row},
            "inheritFromBefore": True}}]})


def _copy_row_formulas(ws, src_row: int, dst_row: int, c0: int, c1: int) -> None:
    """Copy src_row's [c0, c1) columns onto dst_row so Sheets rewrites the
    relative references for the new position."""
    ws.spreadsheet.batch_update({"requests": [{
        "copyPaste": {
            "source": {"sheetId": ws.id, "startRowIndex": src_row - 1,
                       "endRowIndex": src_row, "startColumnIndex": c0,
                       "endColumnIndex": c1},
            "destination": {"sheetId": ws.id, "startRowIndex": dst_row - 1,
                            "endRowIndex": dst_row, "startColumnIndex": c0,
                            "endColumnIndex": c1},
            "pasteType": "PASTE_NORMAL"}}]})


def add_one(ws, name: str, *, logfn=print) -> dict:
    """Add ONE person to all three blocks. Re-reads the grid each time, so
    every insert works off true row numbers rather than a stale plan.

    Order matters: the ranking block sits BELOW the daily block, and the daily
    block below the weekly one, so inserting bottom-up would still be shifted
    by the later inserts. Each block is therefore re-located after the previous
    insert instead of being adjusted arithmetically."""
    done = {}

    # ---- 3. bottom ranking (do it first: it is the lowest block, and its
    # SUMIFs name the person as a literal string, so it is copied then patched)
    grid = ws.get_all_values()
    rank = find_ranking_block(grid)
    src = rank["data_rows"][-1]
    at = src + 1
    _insert_row(ws, at)
    time.sleep(1)
    _copy_row_formulas(ws, src, at, 1, 40)      # B.. across the whole block
    time.sleep(1)
    formulas = ws.get_all_values(value_render_option="FORMULA")
    old_name = _cell(ws.get_all_values(), src - 1, 1) or ""
    updates = [{"range": f"{ws.title}!B{at}", "values": [[name]]}]
    row_f = formulas[at - 1] if at - 1 < len(formulas) else []
    for c0, val in enumerate(row_f):
        v = str(val)
        if c0 == 1:
            continue                                    # col B handled above
        if old_name and old_name in v:                  # the literal SUMIF name
            updates.append({"range": f"{ws.title}!{fs._col(c0 + 1)}{at}",
                            "values": [[v.replace(old_name, name)]]})
        elif v and not v.startswith("="):               # frozen history value
            updates.append({"range": f"{ws.title}!{fs._col(c0 + 1)}{at}",
                            "values": [[""]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": updates})
    done["ranking_row"] = at
    logfn(f"    ranking block: row {at} (copied from {src}, name swapped in "
          f"{len(updates) - 1} formula/value cell(s))")

    # ---- 2. daily section
    grid = ws.get_all_values()
    daily = fs.find_daily_section(grid, agg_target_label())
    rows = sorted(daily.icd_rows.values())
    at = _insert_position(rows)
    src = rows[-1]
    _insert_row(ws, at)
    time.sleep(1)
    _copy_row_formulas(ws, src, at, 0, daily.running_total_col)
    time.sleep(1)
    day_cols = sorted(daily.day_col_by_daynum.values())
    data = [{"range": f"{ws.title}!B{at}", "values": [[name]]},
            {"range": f"{ws.title}!{fs._col(daily.running_total_col)}{at}",
             "values": [[f"=SUM({fs._col(day_cols[0])}{at}:"
                         f"{fs._col(day_cols[-1])}{at})"]]}]
    data += _rank_col_a(ws, at, first_row=rows[0], last_row=daily.totals_row)
    for c in day_cols:
        data.append({"range": f"{ws.title}!{fs._col(c)}{at}", "values": [[0]]})
    # K/L are last week / previous week — blank, not the neighbour's history.
    for c in (daily.running_total_col + 1, daily.running_total_col + 2):
        data.append({"range": f"{ws.title}!{fs._col(c)}{at}", "values": [[""]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})
    done["daily_row"] = at
    logfn(f"    daily section: row {at} (0 for each day, J re-summed, "
          f"K/L left blank)")

    # ---- 1. weekly leaderboard
    grid = ws.get_all_values()
    wk = rj.find_leaderboard_block(grid)
    at = _insert_position(wk["data_rows"])
    src = wk["data_rows"][-1]
    _insert_row(ws, at)
    time.sleep(1)
    _copy_row_formulas(ws, src, at, 0, wk["last_col"])
    time.sleep(1)
    grid = ws.get_all_values()
    daily = fs.find_daily_section(grid, agg_target_label())
    drows = sorted(daily.icd_rows.values())
    jcol = fs._col(daily.running_total_col)
    data = [{"range": f"{ws.title}!B{at}", "values": [[name]]},
            {"range": f"{ws.title}!C{at}",
             "values": [[f"=SUMIF($B${drows[0]}:$B${drows[-1]},B{at},"
                         f"${jcol}${drows[0]}:${jcol}${drows[-1]})"]]}]
    data += _rank_col_a(ws, at, first_row=wk["data_rows"][0],
                        last_row=wk["totals_row"])
    for c in range(4, wk["last_col"] + 1):          # D.. = frozen history
        data.append({"range": f"{ws.title}!{fs._col(c)}{at}", "values": [[""]]})
    ws.spreadsheet.values_batch_update(
        {"valueInputOption": "USER_ENTERED", "data": data})
    done["weekly_row"] = at
    logfn(f"    weekly leaderboard: row {at} (C re-pointed at the daily block, "
          f"history columns blank)")
    return done


def sync(ws, copy_grid, today, *, dry_run: bool = True, raw_aliases=None,
         logfn=print) -> dict:
    """Add every campaign rep missing from the board. Returns a summary."""
    tgt_grid = ws.get_all_values()
    p = plan(copy_grid, tgt_grid, today, raw_aliases=raw_aliases, logfn=logfn)
    if not p:
        logfn("  roster: every campaign rep already has a row on the board")
        return {"added": [], "dry_run": dry_run}
    logfn(f"  roster: {len(p.names)} campaign rep(s) with NO row on the board: "
          f"{', '.join(p.names)}")
    if dry_run:
        for n in p.names:
            logfn(f"    (dry-run) would add {n!r} -> weekly row "
                  f"{p.weekly_at[n]}, daily row {p.daily_at[n]}, ranking row "
                  f"{p.ranking_at[n]}")
        return {"added": [], "would_add": p.names, "dry_run": True}
    added = []
    for n in p.names:
        logfn(f"  + adding {n!r} to all three blocks")
        add_one(ws, n, logfn=logfn)
        added.append(n)
    return {"added": added, "dry_run": False}
