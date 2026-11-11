"""The board's Google Sheet — ONE TAB in each ICD's own metrics workbook.

`board.py` holds the rules and never touches a network. This is the half that
reads and writes, kept apart so the rules can be tested without a sheet and so
there is exactly one place to look when asking what this writes.

Megan, 2026-11-08: *"We can build it where it lives on a live Google sheet for
them. They just don't need to go to that sheet."* The sheet is the record — it
can be opened, shared and fixed by hand — but the ICD works in the extension.

**Which sheet: their own.** All 36 offices already have a metrics workbook
(`office_metrics.offices`, each with its `sheet_id`), so this adds one
`Onboarding` tab to the book they already have rather than making a new one.
Nothing new to create or share, and — the part that matters — an office sees
its own people and nobody else's. One workbook holding all 52 ICDs would have
shown each of them everyone.

Weeks are stacked as ROWS, with a `Week of` column, because tabs-per-week would
put 52 a year into somebody's own workbook. The extension's week picker reads
that column.

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

# Row 1 is the header, then people. No week banner row: the week is a column,
# so one tab carries every week this office has had.
HEADER_ROW = 1
FIRST_DATA_ROW = 2


def _values(ws) -> List[List[str]]:
    """One tab's grid, retried through the per-user read quota.

    Google counts 60 reads a MINUTE per user across everything that user's
    credentials are doing ([[reference_sheets_per_user_read_cap]]), and this
    board is read by an hourly job on every ICD machine beside whatever else is
    running. A 429 here is transient and reads like a dead board, so it is
    waited out rather than raised: 6 tries spans ~31s, most of a quota window.
    """
    from automations.shared import sheets_retry
    return sheets_retry.call(ws.get_all_values, tries=6)


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


def _header_block() -> List[List[str]]:
    return [list(B.COLUMNS) + [B.TERMINATED_AT, B.REMOVED_WHY]]


def ensure_columns(ws, log=print) -> List[str]:
    """Append any column this code knows about that the tab has not got.

    APPEND ONLY, to the right of whatever is already there. Nothing is moved,
    renamed or removed: somebody may have added a column of their own, and
    `layout()` finds everything by label so position never mattered anyway.

    Without this a column added to `B.COLUMNS` only ever reaches boards created
    afterwards -- `open_board` deliberately does not re-lay an existing tab --
    so every office already running would silently lack it (`Gender`, added
    2026-11-10, is the case that showed this up).
    """
    from automations.shared import sheets_retry
    grid = sheets_retry.call(ws.get_all_values, tries=6)
    head = [str(h).strip() for h in (grid[HEADER_ROW - 1] if grid else [])]
    if not head:
        return []
    missing = [c for c in list(B.COLUMNS) + [B.TERMINATED_AT] if c not in head]
    if not missing:
        return []
    at = len(head) + 1
    ws.update(values=[missing],
              range_name="%s%d" % (_a1(at), HEADER_ROW))
    log("  board: added the %s column(s)" % ", ".join(missing))
    return missing


def open_board(workbook, *, create: bool = True):
    """This office's Onboarding tab, made with its headers if it is new.

    Never re-lays an existing tab: somebody may have added a column of their
    own, and this has no business tidying it away. A column this code knows
    about and the tab lacks is APPENDED -- see `ensure_columns`.
    """
    from automations.shared import sheets_retry
    for ws in sheets_retry.call(workbook.worksheets, tries=6):
        if ws.title == B.TAB:
            return ws
    if not create:
        return None
    ws = workbook.add_worksheet(title=B.TAB, rows=1000,
                                cols=len(B.COLUMNS) + 4)
    ws.update(values=_header_block(), range_name="A1")
    ws.freeze(rows=HEADER_ROW)
    return ws


# Older name, kept so nothing breaks mid-change.
def open_week(workbook, week_start=None, *, create: bool = True):
    return open_board(workbook, create=create)


def seed(workbook, week_start: dt.date, people: List[Dict],
         *, dry_run: bool = False, log=print) -> Dict:
    """Put this week's training-calendar people on the board.

    Idempotent on purpose. Running it twice, or every day, adds whoever the
    calendar has gained and touches nothing else — someone's hand-set Classroom
    and every tick an automation has earned survive untouched, and a person the
    ICD marked off does not reappear.
    """
    ws = open_board(workbook, create=not dry_run)
    if ws is None:
        log("  (dry run — no %s tab on this workbook yet)" % B.TAB)
        all_rows, existing = [], []
    else:
        all_rows = rows_of(_values(ws))
        existing = B.for_week(all_rows, week_start)
    fresh = B.seed_rows(people, started=week_start)
    plan = B.merge(existing, fresh)
    log("  week of %s: %d already there, %d to add%s"
        % (B.week_label(week_start), plan["keep"], len(plan["add"]),
           ", %d marked off" % len(plan["left"]) if plan["left"] else ""))
    if dry_run or not plan["add"]:
        return plan
    cols = layout(_values(ws)) or {n: i for i, n in enumerate(B.COLUMNS)}
    width = max(cols.values()) + 1
    block = []
    for r in plan["add"]:
        line = [""] * width
        for name, value in r.items():
            if name in cols:
                line[cols[name]] = value
        block.append(line)
    # Appended to the END of the tab, after every week already on it.
    start = FIRST_DATA_ROW + len(all_rows)
    ws.update(values=block,
              range_name="A%d:%s%d" % (start, _a1(width), start + len(block) - 1))
    return plan


def tick(workbook, week_start: dt.date, column: str, names: Sequence[str],
         *, dry_run: bool = False, log=print) -> int:
    """Tick `column` for `names`. ON ONLY — see board.tick_plan.

    Every filler calls this rather than writing cells itself, so there is one
    place that decides what a tick is allowed to do.
    """
    ws = open_board(workbook, create=False)
    if ws is None:
        log("  no %s tab on this workbook yet" % B.TAB)
        return 0
    grid = _values(ws)
    cols = layout(grid)
    if column not in cols:
        raise RuntimeError(
            "the board has no %r column. If it was renamed, rename it here too "
            "— this never guesses at a position." % column)
    all_rows = rows_of(grid)
    mine = B.for_week(all_rows, week_start)
    want = [all_rows.index(mine[i]) for i in B.tick_plan(mine, column, names)]
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
              *, reason: str = "", dry_run: bool = False, log=print) -> int:
    """Take people off the board for the week — the panel's 'remove'.

    Writes the date into the row-state column and WHY beside it. The row
    STAYS: hidden from the board and the printout, still there to answer what
    happened to somebody.

    `reason` is one of B.REMOVAL_REASONS. An unrecognised one is still written
    -- refusing the removal because the word was odd would leave somebody on
    the board who is not coming -- but it is logged loudly, because a reason
    nobody can count is the thing the pick list exists to prevent.
    """
    ws = open_board(workbook, create=False)
    if ws is None:
        return 0
    grid = _values(ws)
    cols = layout(grid)
    if B.TERMINATED_AT not in cols:
        raise RuntimeError("the board has no %r column." % B.TERMINATED_AT)
    all_rows = rows_of(grid)
    mine = B.for_week(all_rows, week_start)
    want = {B._fold(n) for n in names}
    hit = [all_rows.index(r) for r in mine
           if B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", ""))) in want
           and not str(r.get(B.TERMINATED_AT) or "").strip()]
    log("  marking off %d" % len(hit))
    if dry_run or not hit:
        return 0
    why = (reason or "").strip()
    if why and why not in B.REMOVAL_REASONS:
        log("  ! %r is not one of %s -- writing it anyway"
            % (why, ", ".join(B.REMOVAL_REASONS)))
    a1 = _a1(cols[B.TERMINATED_AT] + 1)
    stamp = dt.date.today().strftime("%m/%d/%Y")
    writes = [{"range": "%s%d" % (a1, FIRST_DATA_ROW + i),
               "values": [[stamp]]} for i in hit]
    # The reason goes in only if the column is there. An older tab that has not
    # had ensure_columns run on it still records the removal; it just cannot
    # say why yet, and that is better than refusing to remove anybody.
    if why and B.REMOVED_WHY in cols:
        w1 = _a1(cols[B.REMOVED_WHY] + 1)
        writes += [{"range": "%s%d" % (w1, FIRST_DATA_ROW + i),
                    "values": [[why]]} for i in hit]
    elif why:
        log("  (no %r column on this tab yet -- reason not written)"
            % B.REMOVED_WHY)
    ws.batch_update(writes)
    return len(hit)


def set_classroom(workbook, week_start: dt.date, assignments: Dict[str, str],
                  *, dry_run: bool = False, log=print) -> int:
    """{name: classroom} — the one column the ICD sets, and the one that
    decides which printed sheet somebody lands on."""
    ws = open_board(workbook, create=False)
    if ws is None:
        return 0
    grid = _values(ws)
    cols = layout(grid)
    if B.CLASSROOM not in cols:
        raise RuntimeError("the board has no %r column." % B.CLASSROOM)
    all_rows = rows_of(grid)
    mine = B.for_week(all_rows, week_start)
    want = {B._fold(k): v for k, v in assignments.items()}
    writes = []
    a1 = _a1(cols[B.CLASSROOM] + 1)
    for r in mine:
        i = all_rows.index(r)
        key = B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))
        if key in want and str(r.get(B.CLASSROOM) or "").strip() != want[key]:
            writes.append({"range": "%s%d" % (a1, FIRST_DATA_ROW + i),
                           "values": [[want[key]]]})
    log("  %d classroom change(s)" % len(writes))
    if dry_run or not writes:
        return 0
    ws.batch_update(writes)
    return len(writes)


def write_step(workbook, week_start: dt.date, column: str,
               people: Dict[str, str], *, dry_run: bool = False,
               log=print, ws=None) -> int:
    """Put a VALUE in a step's cell for each named person.

    `tick` writes today's date, which proves something happened. Some steps
    want to say WHICH answer came back instead — BG Status carries Passed /
    Failed / Unperformable (Megan, 2026-11-09). Same rules either way: only
    this week's rows, only cells that are still empty, never a column a machine
    does not own, and nothing is ever cleared.
    """
    # `ws` lets a caller that has already opened the tab hand it over.
    # Applying a source's five columns used to re-open and re-read the board
    # five times, which is five of the sixty reads a minute this account gets
    # across every job it runs -- and it ran out mid-apply on 2026-11-09.
    ws = ws or open_board(workbook, create=False)
    if ws is None:
        log("  no %s tab on this workbook yet" % B.TAB)
        return 0
    grid = _values(ws)
    cols = layout(grid)
    if column not in cols:
        raise RuntimeError(
            "the board has no %r column. If it was renamed, rename it here too "
            "— this never guesses at a position." % column)
    if column not in B.TICKS:
        raise ValueError("%r is not a column a machine may write." % column)
    all_rows = rows_of(grid)
    mine = B.for_week(all_rows, week_start)
    want = {B._fold(k): v for k, v in (people or {}).items()}
    a1 = _a1(cols[column] + 1)
    writes, greens = [], []
    status_col = column in B.STATUS_STEPS
    for r in mine:
        key = B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))
        if key not in want:
            continue
        have = str(r.get(column) or "").strip()
        if have:
            # A tick is written once. A STATUS may advance -- and only advance,
            # so a late "Sent" email can never pull somebody back from Passed.
            if not status_col:
                continue
            if B.status_rank(want[key]) <= B.status_rank(have):
                continue
        row_no = FIRST_DATA_ROW + all_rows.index(r)
        writes.append({"range": "%s%d" % (a1, row_no), "values": [[want[key]]]})
        greens.append("%s%d" % (a1, row_no))
    log("  %s: %d to write" % (column, len(writes)))
    if dry_run or not writes:
        return 0
    ws.batch_update(writes)
    ws.format(greens, {"backgroundColor": B.GREEN})
    return len(writes)
