"""The board's Google Sheet — one workbook per ICD, one tab per week.

`board.py` holds the rules and never touches a network. This is the half that
reads and writes, kept apart so the rules can be tested without a sheet and so
there is exactly one place to look when asking what this writes.

Megan, 2026-11-08: *"We can build it where it lives on a live Google sheet for
them. They just don't need to go to that sheet."* The sheet is the record — it
can be opened, shared and fixed by hand — but the ICD works in the extension.

WHAT THIS WILL NOT DO
  * create a tab that already exists, or re-lay one. A re-seed adds the people
    the calendar has gained and leaves every other cell exactly as found.
  * write a column it does not own. Classroom is the ICD's; the steps belong to
    whichever automation fills them; identity is the seed's.
  * clear anything. Ticks go on, never off; terminated rows are hidden by the
    panel, never deleted here.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence

from automations.icd_onboarding import board as B

# Where a week's rows start. Row 1 is the week, row 2 the headers — the same
# shape as the OBCL, so anybody who knows that sheet knows this one.
WEEK_ROW = 1
HEADER_ROW = 2
FIRST_DATA_ROW = 3


def _a1(col: int) -> str:
    out = ""
    while col:
        col, rem = divmod(col - 1, 26)
        out = chr(65 + rem) + out
    return out


def layout(grid: List[List[str]]) -> Dict[str, int]:
    """{column name: 0-based index}, found by reading the header row.

    By label, never by position: this board will gain columns the moment an
    office asks for one ([[feedback_no_hardcoded_columns]]).
    """
    if len(grid) < HEADER_ROW:
        return {}
    head = grid[HEADER_ROW - 1]
    return {str(name).strip(): i for i, name in enumerate(head)
            if str(name).strip()}


def rows_of(grid: List[List[str]]) -> List[Dict]:
    """The week's people as dicts, keyed by column name."""
    cols = layout(grid)
    if not cols:
        return []
    out = []
    for raw in grid[FIRST_DATA_ROW - 1:]:
        row = {name: (raw[i] if i < len(raw) else "") for name, i in cols.items()}
        if str(row.get("Name") or "").strip() or str(row.get("Last Name") or "").strip():
            out.append(row)
    return out


def _header_block(week_start: dt.date) -> List[List[str]]:
    monday = week_start - dt.timedelta(days=week_start.weekday())
    return [
        ["Week of %s" % monday.strftime("%m/%d/%Y")],
        list(B.COLUMNS) + [B.TERMINATED_AT],
    ]


def open_week(workbook, week_start: dt.date, *, create: bool = True):
    """The worksheet for this week, made with its headers if it is new."""
    title = B.tab_name(week_start)
    for ws in workbook.worksheets():
        if ws.title == title:
            return ws
    if not create:
        return None
    ws = workbook.add_worksheet(
        title=title, rows=200, cols=len(B.COLUMNS) + 4)
    ws.update(values=_header_block(week_start), range_name="A1")
    ws.freeze(rows=HEADER_ROW)
    return ws


def seed(workbook, week_start: dt.date, people: List[Dict],
         *, dry_run: bool = False, log=print) -> Dict:
    """Put this week's training-calendar people on the board.

    Idempotent on purpose. Running it twice, or every day, adds whoever the
    calendar has gained and touches nothing else — someone's hand-set Classroom
    and every tick an automation has earned survive untouched, and a person the
    ICD marked off does not reappear.
    """
    ws = open_week(workbook, week_start, create=not dry_run)
    if ws is None:
        log("  (dry run — the tab %s does not exist yet)" % B.tab_name(week_start))
        existing = []
    else:
        existing = rows_of(ws.get_all_values())
    fresh = B.seed_rows(people, started=week_start)
    plan = B.merge(existing, fresh)
    log("  %s: %d already there, %d to add%s"
        % (B.tab_name(week_start), plan["keep"], len(plan["add"]),
           ", %d marked off" % len(plan["left"]) if plan["left"] else ""))
    if dry_run or not plan["add"]:
        return plan
    cols = layout(ws.get_all_values()) or {n: i for i, n in enumerate(B.COLUMNS)}
    width = max(cols.values()) + 1
    block = []
    for r in plan["add"]:
        line = [""] * width
        for name, value in r.items():
            if name in cols:
                line[cols[name]] = value
        block.append(line)
    start = FIRST_DATA_ROW + len(existing)
    ws.update(values=block,
              range_name="A%d:%s%d" % (start, _a1(width), start + len(block) - 1))
    return plan


def tick(workbook, week_start: dt.date, column: str, names: Sequence[str],
         *, dry_run: bool = False, log=print) -> int:
    """Tick `column` for `names`. ON ONLY — see board.tick_plan.

    Every filler calls this rather than writing cells itself, so there is one
    place that decides what a tick is allowed to do.
    """
    ws = open_week(workbook, week_start, create=False)
    if ws is None:
        log("  no board for %s yet" % B.tab_name(week_start))
        return 0
    grid = ws.get_all_values()
    cols = layout(grid)
    if column not in cols:
        raise RuntimeError(
            "the board has no %r column. If it was renamed, rename it here too "
            "— this never guesses at a position." % column)
    rows = rows_of(grid)
    want = B.tick_plan(rows, column, names)
    log("  %s: %d to tick" % (column, len(want)))
    if dry_run or not want:
        return 0
    a1 = _a1(cols[column] + 1)
    stamp = dt.date.today().strftime("%m/%d/%Y")
    ws.batch_update([{"range": "%s%d" % (a1, FIRST_DATA_ROW + i),
                      "values": [[stamp]]} for i in want])
    ws.format(["%s%d" % (a1, FIRST_DATA_ROW + i) for i in want],
              {"backgroundColor": B.GREEN})
    return len(want)


def terminate(workbook, week_start: dt.date, names: Sequence[str],
              *, dry_run: bool = False, log=print) -> int:
    """Mark people off for the week — the panel's 'click them off'.

    Writes the date into the row-state column. The row STAYS: hidden from the
    board and the printout, still there to answer what happened to somebody.
    """
    ws = open_week(workbook, week_start, create=False)
    if ws is None:
        return 0
    grid = ws.get_all_values()
    cols = layout(grid)
    if B.TERMINATED_AT not in cols:
        raise RuntimeError("the board has no %r column." % B.TERMINATED_AT)
    rows = rows_of(grid)
    want = {B._fold(n) for n in names}
    hit = [i for i, r in enumerate(rows)
           if B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", ""))) in want
           and not str(r.get(B.TERMINATED_AT) or "").strip()]
    log("  marking off %d" % len(hit))
    if dry_run or not hit:
        return 0
    a1 = _a1(cols[B.TERMINATED_AT] + 1)
    stamp = dt.date.today().strftime("%m/%d/%Y")
    ws.batch_update([{"range": "%s%d" % (a1, FIRST_DATA_ROW + i),
                      "values": [[stamp]]} for i in hit])
    return len(hit)


def set_classroom(workbook, week_start: dt.date, assignments: Dict[str, str],
                  *, dry_run: bool = False, log=print) -> int:
    """{name: classroom} — the one column the ICD sets, and the one that
    decides which printed sheet somebody lands on."""
    ws = open_week(workbook, week_start, create=False)
    if ws is None:
        return 0
    grid = ws.get_all_values()
    cols = layout(grid)
    if B.CLASSROOM not in cols:
        raise RuntimeError("the board has no %r column." % B.CLASSROOM)
    rows = rows_of(grid)
    want = {B._fold(k): v for k, v in assignments.items()}
    writes = []
    a1 = _a1(cols[B.CLASSROOM] + 1)
    for i, r in enumerate(rows):
        key = B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))
        if key in want and str(r.get(B.CLASSROOM) or "").strip() != want[key]:
            writes.append({"range": "%s%d" % (a1, FIRST_DATA_ROW + i),
                           "values": [[want[key]]]})
    log("  %d classroom change(s)" % len(writes))
    if dry_run or not writes:
        return 0
    ws.batch_update(writes)
    return len(writes)
