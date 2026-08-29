"""Write the day's four columns onto this week's Sales Board tab.

TARGET, spelled out:
  workbook  'Alphalete SALES BOARD 2025' (1MC9pf…N2CmHc)
  tab       'Sales Board WE <m>.<d>'  -- the week's SUNDAY
  row       the rep's row in col C
  cols      TODAY's block -> Int | Int Up | DTV | NL

Geometry comes from rep_sales_fill.board, which reads the day banners and
sub-headers live on every run. Nothing here remembers a row or a column: the
board is re-sorted through the day (alphabetical in the morning, by production
later) and columns are inserted all week. [[feedback_no_hardcoded_columns]]

FOUR THINGS IT WILL NOT DO, and they are the whole safety story for a job that
writes 150 times a day unattended:
  * never touch Apps (a formula) or Roll Call;
  * never overwrite a roll-call status ('X', 'T', 'RT', 'STF' …) -- those share
    the same cells as the counts, so a write would erase the attendance record;
  * never blank a cell that holds a number. A sale that reached the board is
    evidence; an empty grid cell is not evidence of its absence, and a short
    SaraPlus export is a normal event;
  * never write a day that is not today. Yesterday is closed and belongs to
    rep_sales_fill, which fills it once from Tableau.

Writes go out as ONE batch_update. A per-cell loop across 60 reps would burn
the Sheets write quota inside a minute and 429 the next report to touch the
workbook, not just this one. [[reference_sheets_write_quota_429]]
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import config as C
from automations.rep_sales_fill import board as B

TAB_PREFIX = "Sales Board WE"


def tab_title(day: dt.date) -> str:
    sunday = C.week_ending(day)
    return "%s %d.%d" % (TAB_PREFIX, sunday.month, sunday.day)


def open_tab(day: dt.date, client=None):
    """This week's worksheet, or a clear error naming the tab we looked for."""
    from automations.recruiting_report.fill import _client
    gc = client or _client()
    book = gc.open_by_key(C.SPREADSHEET_ID)
    want = tab_title(day).lower()
    for ws in book.worksheets():
        if ws.title.strip().lower() == want:
            return ws
    raise RuntimeError(
        "no %r tab on the sales board -- the week's tab is usually rolled over "
        "on Sunday. Nothing was written." % tab_title(day))


def board_names(grid) -> List[str]:
    """Col C, roster block only (down to TOTALS)."""
    last = B.last_rep_row(grid)
    out = []
    for r in range(B.SUB_ROW + 1, last + 1):
        name = B.cell(grid, r, B.NAME_COL).strip()
        if name:
            out.append(name)
    return out


def _a1(row: int, col: int) -> str:
    letters = ""
    c = col
    while c > 0:
        c, rem = divmod(c - 1, 26)
        letters = chr(65 + rem) + letters
    return "%s%d" % (letters, row)


def plan(grid, day: dt.date, rows: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """([{range, values}], notes) for TODAY's block only.

    overwrite=True on purpose: this is the live day, and the count grows all
    afternoon, so today's cells are meant to track SaraPlus. plan_day still
    refuses a day carrying a roll-call status and still refuses to blank a
    number, which is where the actual protection lives -- not in the flag.
    """
    # day_blocks() keys are full weekday names ("Monday"), which is what it
    # maps the board's own banners ("MON", "TUES") onto.
    weekday = day.strftime("%A")
    blocks = B.day_blocks(grid)
    cols = blocks.get(weekday)
    if not cols:
        return [], ["no %s block on %r -- the tab's day banners may have "
                    "changed" % (weekday, tab_title(day))]

    updates, notes = [], []
    for item in rows:
        row, note = B.find_rep_row(grid, item["board_name"])
        if row is None:
            notes.append(note)
            continue
        writes, day_notes = B.plan_day(grid, row, cols, item["metrics"],
                                       overwrite=True)
        notes.extend("%s: %s" % (item["board_name"], n) for n in day_notes)
        for _metric, col, _cur, new in writes:
            updates.append({"range": _a1(row, col), "values": [[new]]})
    return updates, notes


def apply(worksheet, updates: List[Dict]) -> int:
    """One batch write. Returns the number of cells changed."""
    if not updates:
        return 0
    worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    return len(updates)


# --- adding a rep who sold but has no row -----------------------------------
# THE PRE-BUILT BLANK ROWS ARE THE WHOLE MECHANISM. This week's tab carries 15
# blank roster rows (65-79) that already hold every formula a rep row needs --
# the =B64+1 numbering, the seven running-week SUMs, and each day's
# ARRAYFORMULA(IFS(...)) Apps cell. Typing a name into col C activates one.
#
# WHAT MUST NEVER HAPPEN: appending BELOW the roster. The TOTALS row is
#   =SUMIF($CG$4:$CG$79,"<>RT",Z4:Z79)
# pinned to rows 4:79, so a name at row 80 looks perfectly fine and is silently
# left out of every total on the board. If the blank rows ever run out, the
# correct move is to INSERT inside 4:79 (Sheets then widens those ranges) and
# copy a neighbour's formulas -- which is a structural edit, so this refuses and
# says so rather than guessing.

def free_roster_row(grid) -> Optional[int]:
    """The first pre-built blank roster row, or None if they are used up."""
    last = B.last_rep_row(grid)
    for r in range(B.SUB_ROW + 1, last + 1):
        if not B.cell(grid, r, B.NAME_COL).strip():
            return r
    return None


def near_matches(name: str, board_names: List[str],
                 cutoff: float = 0.85) -> List[str]:
    """Board rows close enough that adding `name` might DUPLICATE somebody.

    DEFAULT TO "NEW PERSON" (Megan 2026-08-27). This started at a 0.6 difflib
    ratio and refused to add "Aaron Corona" because it scored 0.62 against
    "Milagros Colon" — coincidental letters ("aron coron" / "agros colon"),
    two entirely different people. A real rep then sold all day with no row
    while the chat was told he "could be" somebody else.

    The two mistakes are not symmetrical any more:
      * refusing wrongly leaves a rep off the board, with nothing anyone can
        do but notice and act;
      * adding wrongly makes a duplicate row, which is now recoverable —
        somebody types "Bo=Kelvinton" and remove_rep takes it back.
    So the bar to refuse is deliberately high: a shared LAST NAME (Mike vs
    Michael Ortiz), or near-identical spelling (0.85 — a typo or a missing
    letter). Anything else is treated as a new person and gets a row.
    """
    import difflib
    want = _norm_name_raw(name)
    w = want.split()
    if not w:
        return []
    out = []
    for b in board_names:
        n = _norm_name_raw(b)
        toks = n.split()
        if not toks:
            continue
        same_last = w[-1] == toks[-1]
        ratio = difflib.SequenceMatcher(None, want, n).ratio()
        if same_last or ratio >= cutoff:
            out.append(b)
    return out


def _norm_name_raw(s: str) -> str:
    return B._norm_name(s)


def add_rep(worksheet, grid, name: str) -> Tuple[Optional[int], str]:
    """Put `name` in the first blank roster row. (row, note)."""
    row = free_roster_row(grid)
    if row is None:
        return None, ("no blank roster row left on %r -- a new rep now needs a "
                      "row INSERTED inside the totals range by hand; appending "
                      "below it would leave them out of every total"
                      % worksheet.title)
    worksheet.update_acell("%s%d" % ("C", row), name)
    return row, ""


def board_goal(grid) -> Optional[int]:
    """The week's goal, read off the board -- the row labelled 'Goal' in col C,
    value in the cell beside it (350 as of 2026-08-26).

    NOT a constant. The first version carried WEEKLY_GOAL = 80, copied from the
    example message in the porting brief, and posted "GOAL FOR THE WEEK:
    106/80" to the Partners chat -- a target already beaten by Tuesday, which
    tells a reader nothing except that the number is made up. The board has
    carried the real one all along. [[feedback_no_hardcoded_columns]]
    """
    last = len(grid)
    for r in range(1, last + 1):
        if B.cell(grid, r, 3).strip().lower() == "goal":
            raw = B.cell(grid, r, 4).strip().replace(",", "")
            try:
                return int(float(raw))
            except ValueError:
                return None
    return None


def board_only_reps(grid, day, accounted: List[str]) -> List[str]:
    """Reps whose row carries NUMBERS today that our SaraPlus pull does not
    account for.

    THE ONE THING A SINGLE-SOURCE FILL CANNOT SEE. While the old system was
    also writing, a rep we never returned still got filled and nobody noticed.
    Once we are the only writer, that same rep goes blank all day and the only
    signal is a person spotting an empty row. So every sweep compares the two:
    a row with digits today whose rep our scrape did not produce is either
    somebody's hand entry or a sale reaching the board by a route we do not
    read -- and both are worth saying out loud.

    Not an error. Hand entries are legitimate and common; this only names them
    so a PATTERN (the same rep, every day) becomes visible.
    """
    cols = day_blocks_for(grid, day)
    if not cols:
        return []
    seen = {B._norm_name(n) for n in accounted}
    out = []
    for r in range(B.SUB_ROW + 1, B.last_rep_row(grid) + 1):
        name = B.cell(grid, r, B.NAME_COL).strip()
        if not name or B._norm_name(name) in seen:
            continue
        if any(B.cell(grid, r, c).strip().isdigit() for c in cols.values()):
            out.append(name)
    return out


def day_blocks_for(grid, day):
    """Today's metric columns, or {} if the banner is missing."""
    return B.day_blocks(grid).get(day.strftime("%A")) or {}


def remove_rep(worksheet, grid, row: int, expected_name: str,
               day) -> Tuple[bool, str]:
    """Undo a row THIS code added, and say what was on it.

    ONLY for a row we recorded adding (state._added), and only while col C
    still holds the name we put there. Both guards matter: an alias confirmed
    the next morning must not clear a row somebody has since typed into, and a
    re-sorted board means a row number alone proves nothing.

    WHERE THE SALES GO. Today's move themselves: SaraPlus is cumulative, so
    once the alias exists the next sweep computes the rep's whole day and
    writes it to the row they really have (Bo's line). Nothing to copy.

    EARLIER DAYS DO NOT. This sweep only ever writes today, so a number sitting
    on Monday of a duplicate row would simply vanish when the row is cleared.
    So the WHOLE WEEK is cleared -- leaving them would leave phantom units in
    the column totals, which SUMIF adds up by column and never looks at the
    name -- and every day's numbers are RETURNED in the note, so a person can
    put the older ones on the right row. Silent is the one thing it must not
    be. (Megan 2026-08-26.)
    """
    actual = B.cell(grid, row, B.NAME_COL).strip()
    if B._norm_name(actual) != B._norm_name(expected_name):
        return False, ("row %d now reads %r, not %r -- left alone (somebody "
                       "has edited it)" % (row, actual, expected_name))

    blocks = B.day_blocks(grid)
    for day_name, cols in blocks.items():
        for c in cols.values():
            if B.is_status(B.cell(grid, row, c)):
                return False, ("row %d carries a roll-call status on %s -- "
                               "left alone" % (row, day_name))

    carried, updates = [], [{"range": _a1(row, B.NAME_COL), "values": [[""]]}]
    today_name = day.strftime("%A")
    for day_name, cols in blocks.items():
        had = {m: B.cell(grid, row, c).strip()
               for m, c in cols.items() if B.cell(grid, row, c).strip().isdigit()}
        if had and day_name != today_name:
            carried.append("%s: %s" % (day_name,
                                       ", ".join("%s %s" % (v, m)
                                                 for m, v in sorted(had.items()))))
        updates += [{"range": _a1(row, c), "values": [[""]]} for c in cols.values()]

    worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    note = ("cleared row %d (%s) -- today's numbers land on their real row on "
            "the next sweep" % (row, actual))
    if carried:
        note += (". EARLIER DAYS were on that row and are NOT moved "
                 "automatically: " + "; ".join(carried)
                 + " -- put these on their real row by hand")
    return True, note


# --- filling in a new rep's details (Raf, 2026-08-27) -----------------------
# A row with only a name in it still needs a person to finish it. Raf asked for
# the rest to be filled the same way he would:
#   Trainer          the trainer's FIRST AND LAST name, though the classroom
#                    block below the roster lists only a first name
#   Field Status     "1st Wk" — they are, by definition
#   Campaign         "Fiber"
#   Team             the TRAINER'S team. "New start will always be on the same
#                    team as their trainer" (Megan). Checked against the live
#                    board: true for 34 of the 38 reps whose trainer is also on
#                    the roster, and all four exceptions are Wk 3+ reps who have
#                    since moved — so it is right at the moment it is written.
#   Leadership Status "In Training", left EMPTY if it can't be established
#   Start Date       the Monday of the board's own week
#
# Every column is found by its ROW-1 LABEL, never by index: row 3 says "REP"
# over four different columns, so position here is meaningless.
NEW_REP_FIELDS = ("Trainer", "Field Status", "Campaign", "Team",
                  "Leadership Status", "Start Date", "Location")
FIELD_STATUS_NEW = "1st Wk"
CAMPAIGN_NEW = "Fiber"
LEADERSHIP_NEW = "In Training"


def meta_columns(grid) -> Dict[str, int]:
    """{row-1 label: column} for the roster's detail columns."""
    width = max(len(r) for r in grid[:3]) if grid else 0
    out = {}
    for c in range(1, width + 1):
        label = " ".join(B.cell(grid, 1, c).split())
        if label in NEW_REP_FIELDS:
            out[label] = c
    return out


def classroom_trainer(grid, name: str) -> Tuple[str, str, str]:
    """(trainer, location, note) from the classroom block under the roster.

    MATCHED ON THE LAST NAME when the full name misses. The block is written by
    hand and uses whatever people are called: SaraPlus said "SHUMINIQUE
    VALENTINE" and the block says "Nikki Valentine", so an exact match found
    nothing and she was added with no trainer, no team and no location
    (2026-08-27). A surname is the part that survives a nickname. Only when it
    is UNIQUE in the block -- two Valentines is a question for a person, not a
    guess.
    """
    header = None
    for r in range(B.last_rep_row(grid) + 1, len(grid) + 1):
        cells = [" ".join(B.cell(grid, r, c).split()).lower() for c in range(1, 16)]
        if "classroom" in cells and "trainers" in cells:
            header = (r, cells.index("classroom") + 1, cells.index("trainers") + 1,
                      (cells.index("location") + 1) if "location" in cells else 0)
            break
    if not header:
        return "", "", "no classroom block on this tab"
    hrow, name_col, trainer_col, loc_col = header

    entries = []
    for r in range(hrow + 1, len(grid) + 1):
        who = B.cell(grid, r, name_col).strip()
        if who:
            entries.append((who, r))
    if not entries:
        return "", "", "the classroom block is empty"

    want = B._norm_name(name)
    hit = [r for who, r in entries if B._norm_name(who) == want]
    how = "by name"
    if not hit:
        last = want.split()[-1] if want.split() else ""
        by_last = [r for who, r in entries
                   if last and B._norm_name(who).split()[-1:] == [last]]
        if len(by_last) == 1:
            other = next(w for w, r in entries if r == by_last[0])
            # A UNIQUE SURNAME IS STILL NOT PROOF (Megan 2026-08-27: "last name
            # won't always be 100% true if they have a common last name"). If
            # the classroom entry is ITSELF somebody on the roster, it is a
            # different person who happens to share the name -- attaching their
            # trainer to this rep would be quietly wrong.
            claimed, crow, _why = roster_match(grid, other)
            if claimed and B._norm_name(claimed) != B._norm_name(name):
                return "", "", ("%r looked like %r in the classroom block, but "
                                "%r is their own rep on the board -- different "
                                "people sharing a surname, so Trainer and Team "
                                "are left blank"
                                % (name, other, claimed))
            hit, how = by_last, "matched on surname (the block calls them %r)" % other
        elif len(by_last) > 1:
            return "", "", ("%r shares a surname with %d classroom entries -- "
                            "left for a person" % (name, len(by_last)))
    if not hit:
        return "", "", "%r is not in the classroom block, so no trainer to read" % name

    row = hit[0]
    trainer = B.cell(grid, row, trainer_col).strip()
    location = B.cell(grid, row, loc_col).strip() if loc_col else ""
    return trainer, location, ("" if how == "by name" else how)


def roster_match(grid, partial: str) -> Tuple[str, int, str]:
    """(full name, row, note) for a trainer given as 'Pranish'."""
    want = B._norm_name(partial)
    if not want:
        return "", 0, "no trainer name"
    last = B.last_rep_row(grid)
    hits = []
    for r in range(B.SUB_ROW + 1, last + 1):
        full = B.cell(grid, r, B.NAME_COL).strip()
        if not full:
            continue
        toks = B._norm_name(full).split()
        if B._norm_name(full) == want or (toks and want in toks) \
                or B._norm_name(full).startswith(want + " "):
            hits.append((full, r))
    if len(hits) == 1:
        return hits[0][0], hits[0][1], ""
    if not hits:
        return "", 0, "trainer %r matches nobody on the roster" % partial
    return "", 0, ("trainer %r matches %d reps (%s) -- left blank"
                   % (partial, len(hits), ", ".join(h[0] for h in hits[:3])))


def new_rep_details(grid, name: str, day) -> Tuple[List[Dict], List[str]]:
    """([{range,values}], notes) — the detail cells for a freshly added rep."""
    cols = meta_columns(grid)
    missing = [f for f in NEW_REP_FIELDS if f not in cols]
    if missing:
        return [], ["can't fill new-rep details: no %s column on this tab"
                    % ", ".join(missing)]
    row, note = B.find_rep_row(grid, name)
    if row is None:
        return [], [note]

    monday = day - dt.timedelta(days=day.weekday())
    values = {"Field Status": FIELD_STATUS_NEW,
              "Campaign": CAMPAIGN_NEW,
              "Leadership Status": LEADERSHIP_NEW,
              "Start Date": "%d/%d/%d" % (monday.month, monday.day, monday.year)}
    notes = []

    first, location, why = classroom_trainer(grid, name)
    if location and "Location" in cols:
        values["Location"] = location
    if why:
        notes.append(why)
    if not first:
        notes.append("no trainer found -- Trainer and Team left blank")
    else:
        full, trow, why2 = roster_match(grid, first)
        if not full:
            notes.append(why2 + " -- Trainer and Team left blank")
        else:
            values["Trainer"] = full
            team = B.cell(grid, trow, cols["Team"]).strip()
            if team:
                values["Team"] = team
            else:
                notes.append("%s has no team on their own row -- Team left blank"
                             % full)

    updates = [{"range": _a1(row, cols[f]), "values": [[v]]}
               for f, v in values.items()]
    notes.append("filled %s" % ", ".join("%s=%s" % (k, v)
                                         for k, v in sorted(values.items())))
    return updates, notes
