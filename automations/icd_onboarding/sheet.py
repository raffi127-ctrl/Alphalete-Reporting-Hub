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


# The columns past the chart: row state, not steps. ONE list, because having
# two is what broke `Removed Because` -- a new board was laid out with it and
# `ensure_columns` was not told about it, so every board that already existed
# silently lacked the column and every removal logged "reason not written"
# instead. The 15 removals on the week of 11/08 have no reason recorded for
# exactly that reason (2026-11-15).
PAST_THE_CHART = (B.TERMINATED_AT, B.REMOVED_WHY)


def _header_block() -> List[List[str]]:
    return [list(B.COLUMNS) + list(PAST_THE_CHART)]


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
    missing = [c for c in list(B.COLUMNS) + list(PAST_THE_CHART)
               if c not in head]
    if not missing:
        return []
    at = len(head) + 1
    # WIDEN THE GRID FIRST. A Sheet has a fixed column count, and writing one
    # cell past it is refused outright -- "Range (Onboarding!W1) exceeds grid
    # limits. Max columns: 22". Both callers wrap this in a try/except that
    # logs the exception TYPE and carries on, so the failure looked like
    # nothing at all: every run said it was adding the column, every run was
    # refused, and the column never appeared (2026-11-20, `Funnel`).
    have = int(getattr(ws, "col_count", 0) or 0)
    need = (at + len(missing) - 1) - have
    # Only when the sheet both reports its width and can grow. A worksheet
    # that does not say how wide it is cannot be widened on a guess -- and
    # the write below is what finds out, loudly, rather than this inventing
    # a number.
    if have and need > 0 and hasattr(ws, "add_cols"):
        sheets_retry.call(lambda: ws.add_cols(need), tries=4)
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


def backfill_funnels(ws, week_start: dt.date, fresh: List[Dict],
                     log=print) -> int:
    """Write `Funnel` onto rows that are ALREADY on the board.

    WITHOUT THIS THE LABEL ONLY EVER REACHES NEW PEOPLE. The dividers are
    drawn above a block of rows the seed is appending, so a week whose people
    were all seeded before the funnel was known -- which is every week that
    already existed on 2026-11-20 -- keeps a blank Funnel column and no
    dividers at all, for good.

    Only ever fills an EMPTY cell, by the same rule as every tick: a value
    somebody typed, or an earlier run wrote, is never overwritten.
    """
    cols = layout(_values(ws))
    if not cols or B.FUNNEL not in cols:
        return 0
    want = {}
    for r in fresh:
        label = str(r.get(B.FUNNEL) or "").strip()
        if label:
            want[B._fold("%s%s" % (r.get("Name", ""), r.get("Last Name", "")))] = label
    if not want:
        return 0
    grid = _values(ws)
    data = []
    for n, raw in enumerate(grid[HEADER_ROW:], HEADER_ROW + 1):
        raw = list(raw) + [""] * (max(cols.values()) + 1)
        if str(raw[cols[B.WEEK]]).strip() != B.week_label(week_start):
            continue
        if str(raw[cols[B.FUNNEL]]).strip():
            continue                       # already said; never overwritten
        key = B._fold("%s%s" % (raw[cols["Name"]], raw[cols["Last Name"]]))
        if key in want:
            data.append({"range": "%s%d" % (_a1(cols[B.FUNNEL] + 1), n),
                         "values": [[want[key]]]})
    if data:
        ws.batch_update(data, value_input_option="USER_ENTERED")
        log("  board: labelled %d row(s) with the funnel they came from"
            % len(data))
    return len(data)


def ensure_dividers(ws, week_start: dt.date, log=print) -> int:
    """Put a labelled divider above each funnel's rows, on ANY week.

    The seed draws dividers above the block it is appending, which only ever
    reaches people added that run. Every week seeded before the funnel was
    known -- and every week where the new people arrive in a later pass than
    the first -- would keep its labels and never get a line (Megan
    2026-11-20: "we need it correct for every week").

    INSERTS, never reorders. Rows are found by label and week everywhere, so
    a row shifting down costs nothing; moving somebody's row to group them
    would mean rewriting cells a person typed, which is the one thing this
    board does not do.

    A funnel whose rows are NOT contiguous is reported rather than divided:
    one line above the first of them would silently claim the people in
    between. That is a sort, and a sort is the caller's decision, not this
    function's.
    """
    cols = layout(_values(ws))
    if not cols or B.FUNNEL not in cols:
        return 0
    want = B.week_label(week_start)
    grid = _values(ws)
    width = max(cols.values()) + 1

    seen: Dict[str, List[int]] = {}
    have: set = set()
    for n, raw in enumerate(grid[HEADER_ROW:], HEADER_ROW + 1):
        raw = list(raw) + [""] * width
        if str(raw[cols[B.WEEK]]).strip() != want:
            continue
        row = {name: raw[i] for name, i in cols.items()}
        if B.is_divider(row):
            have.add(str(raw[cols[B.DIVIDER_AT]]).strip())
            continue
        label = str(raw[cols[B.FUNNEL]]).strip()
        if label:
            seen.setdefault(label, []).append(n)

    added = 0
    for label in sorted(seen):
        rows = seen[label]
        text = B.divider_row(want, label)[B.DIVIDER_AT]
        if text in have:
            continue                      # this week already has its line
        if rows != list(range(rows[0], rows[0] + len(rows))):
            log("  board: %r sits on scattered rows %s — no divider drawn, a "
                "line above the first would claim the people between them"
                % (label, rows))
            continue
        line = [""] * width
        line[cols[B.WEEK]] = want
        line[cols[B.DIVIDER_AT]] = text
        ws.insert_row(line, rows[0])
        log("  board: divider for %r above row %d" % (label, rows[0]))
        added += 1
        if added:
            grid = _values(ws)            # rows below just shifted
    return added


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
    if dry_run:
        return plan
    # THE SEED CREATES ITS OWN COLUMNS. It used to rely on `fillers.apply`
    # running later and calling this -- so a column the seed itself writes
    # (`Funnel`, 2026-11-20) never appeared on a board whose people were all
    # already there, because `apply` had nothing to tick and the seed returned
    # before laying a single cell. The value was then silently dropped: `_line`
    # skips any key the layout has no column for.
    try:
        ensure_columns(ws, log=log)
    except Exception as e:   # noqa: BLE001 — never fail a seed over a header
        log("  (could not add missing columns: %s)" % type(e).__name__)
    backfill_funnels(ws, week_start, fresh, log=log)
    if not plan["add"]:
        # Nobody new, but the week may still be owed its lines -- that is
        # every week seeded before the funnel was known.
        try:
            ensure_dividers(ws, week_start, log=log)
        except Exception as e:            # noqa: BLE001 — never fail a seed
            log("  (dividers not drawn: %s)" % type(e).__name__)
        return plan
    cols = layout(_values(ws)) or {n: i for i, n in enumerate(B.COLUMNS)}
    width = max(cols.values()) + 1
    def _line(r):
        line = [""] * width
        for name, value in r.items():
            if name in cols:
                line[cols[name]] = value
        return line

    # ONE DIVIDER PER FUNNEL, above its people. They all land in one
    # OwnerVille, so without the label a leader cannot tell whose new start is
    # whose (Megan 2026-11-20). Only drawn when the block actually carries
    # somebody from that funnel -- a divider over nobody is noise -- and never
    # for the office's own account, whose people are the board's default.
    week_text = B.week_label(week_start)
    by_funnel = {}
    for r in plan["add"]:
        by_funnel.setdefault(str(r.get(B.FUNNEL) or "").strip(), []).append(r)
    block = []
    for r in by_funnel.pop("", []):          # the office's own, first and bare
        block.append(_line(r))
    for label in sorted(by_funnel):
        block.append(_line(B.divider_row(week_text, label)))
        for r in by_funnel[label]:
            block.append(_line(r))
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
        # Expected: the panel's "Other" lets somebody type the reason nobody
        # thought of. Still said out loud, because a typed reason is one
        # nothing can count later -- if the same words keep appearing here,
        # that is a sixth reason asking to join the pick list.
        log("  typed reason (not one of the %d offered): %r"
            % (len(B.REMOVAL_REASONS), why))
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
            if (B.status_rank(want[key], column)
                    <= B.status_rank(have, column)):
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
