"""The half-hour team snapshot: today vs. yesterday at the same minute.

    Times of Sales tab, 'Alphalete SALES BOARD 2025'  (same workbook as the board)

WHAT IT IS. Every :00 and :30 of the selling afternoon, the org's running
totals are stamped into one row of the 'Times of Sales' tab -- New Internet,
Total Units, and the difference against YESTERDAY at that same clock time --
and the same three numbers go to the chat. The point is not the total; the
board already carries that. The point is the PACE: 12 units at 4pm means
something different on a day that had 8 at 4pm than on one that had 20.

IT DOES NOT SCRAPE. It is handed the `agents` list the sweep already pulled,
so a snapshot costs one Sheets read and one Sheets write, not a second SaraPlus
login. That is the whole reason it lives inside this module instead of being
its own report: a separate job would double the logins on a site that already
sees ~130 of ours a day, to read numbers we are holding in memory.

THE SLOT IS CLAIMED BEFORE THE SCRAPE, in run.py, and this is not
cosmetic. A sweep takes 30-60 seconds; a 3:59:50 tick that asked the clock
afterwards would find 4:00 and stamp the 4:00 column with numbers read at
3:59 -- or, worse, a 4:00:20 tick would find 4:00 gone and skip the slot
entirely. The label is decided while the tick is still the tick.

ARITHMETIC, verified against the live sheet (2026-08-26, 7:00 PM: the tab reads
New Internet 19 / Total Units 21, and the leaderboard that evening read
INT: 19 / Upgrades: 2 / DTV: 2 / NL's: 0):

    New Internet = Int                  (upgrades and AIA already taken out)
    Total Units  = Int + DTV + NL       (upgrades NOT counted)

So Total Units is deliberately SMALLER than the leaderboard's TOTALS line,
which does count upgrades. Two different questions -- "how many units went
up" vs "what did the floor put on the board" -- and both go to the same chat,
so the labels here say exactly which one this is.

COLUMNS ARE FOUND BY HEADER, never by index: row 1 carries the time labels
('4:00 PM'), row 2 the three sub-headers ('New Internet', 'Total Units',
'Delta to the day Prior prior'). The porting brief supplied a fixed B..AZ map
and it is correct TODAY -- the live tab matches it column for column -- but the
tab also already carries 9:30 PM and 10:00 PM headers that the map does not
mention, which is what a hardcoded map looks like the day after somebody adds a
slot. [[feedback_no_hardcoded_columns]]

Python 3.9-safe (Lucy runtime). No Mac-only strftime: the date string is built
by hand, because '%-d' is not portable and this file has to import on Windows.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence, Tuple

from automations.alphalete_sales_board import calc
from automations.alphalete_sales_board import config as C

TAB = "Times of Sales"

# Row 1 holds the time label, row 2 the sub-header, and the dates start at
# row 3. Read live on every run all the same -- these three are the only
# geometry assumed, and each one is checked before anything is written.
LABEL_ROW = 1
SUBHEAD_ROW = 2
FIRST_DATE_ROW = 3

NEW_INTERNET = "new internet"
TOTAL_UNITS = "total units"
DELTA = "delta"          # the live header reads 'Delta to the day Prior prior'

# --- the day's checkpoints --------------------------------------------------
# Every :00 and :30 from the first to the last, inclusive. Mon-Fri the field
# is out until 9; Saturday stops at 6:30. Sunday is not a selling day.
#
# SATURDAY STARTS AT NOON and the tab has NO 12:00/12:30 columns -- confirmed
# against three months of history: every Saturday row starts filling at 1:00 PM
# (B) and ends at 6:30 PM (AI), 12 slots. The two noon slots are TEXT ONLY, and
# that is the brief's rule, not an oversight: the chat wants to hear the day has
# started, the tab has nowhere to put it.
WEEKDAY_WINDOW = ((13, 0), (21, 0))     # 1:00 PM - 9:00 PM
SATURDAY_WINDOW = ((12, 0), (18, 30))   # 12:00 PM - 6:30 PM

# Emoji as literal characters, never ':shortcodes:'. iMessage renders a
# shortcode as the seven letters you typed. (notify.py learned this first.)
CHART = "\U0001F4CA"     # bar chart
GLOBE = "\U0001F310"     # new internet
TV = "\U0001F4FA"        # DTV
BOX = "\U0001F4E6"       # total units
UP = "\U0001F7E2"        # green circle
DOWN = "\U0001F534"      # red circle


def _label(hour: int, minute: int) -> str:
    """(16, 30) -> '4:30 PM'. Built by hand: '%-I' is not portable."""
    ampm = "AM" if hour < 12 else "PM"
    h12 = hour % 12 or 12
    return "%d:%02d %s" % (h12, minute, ampm)


def slots_for(weekday: int) -> List[str]:
    """Every checkpoint label for this weekday, in clock order. [] on Sunday."""
    if weekday == 6:
        return []
    (sh, sm), (eh, em) = SATURDAY_WINDOW if weekday == 5 else WEEKDAY_WINDOW
    out, h, m = [], sh, sm
    while (h, m) <= (eh, em):
        out.append(_label(h, m))
        h, m = (h + 1, 0) if m == 30 else (h, 30)
    return out


def _hhmm(label: str) -> Tuple[int, int]:
    """'4:30 PM' -> (16, 30)."""
    hm, ampm = label.split()
    hour, minute = [int(x) for x in hm.split(":")]
    if ampm == "PM" and hour != 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    return hour, minute


# HOW LATE A SLOT IS STILL WORTH CLAIMING. Under 30, so a slot can never reach
# into the next one's territory: at 4:29 the 4:00 column is 29 minutes stale
# and stamping it with numbers read now would put the 4:25 reading in the 4:00
# cell -- which is exactly the lie this report exists to avoid, since the whole
# value of the tab is that a column means that minute.
CATCH_UP_MINUTES = 25


def due(now: Optional[dt.datetime] = None,
        sent: Sequence[str] = ()) -> Optional[str]:
    """The slot this tick should stamp, or None. `sent` is today's stamped
    labels, and it -- not the width of the window -- is what stops a double.

    THE SCHEDULER DOES NOT TICK ON THE HALF HOUR, and this is the whole reason
    the function is shaped like this. The LaunchAgent is StartInterval 300,
    which counts 300 seconds from whenever launchd loaded the job, not from the
    top of the hour: in practice the ticks land at :02, :07, :12, :17 ... and a
    check for `minute in (0, 30)` would have matched on NO tick of any day and
    the snapshot would simply never have fired. It would have failed silently
    too -- an empty column looks exactly like a quiet afternoon.

    So a tick claims the most recent slot that has PASSED, provided it is not
    already stamped and is fresher than CATCH_UP_MINUTES. That is the pattern
    config.LVL1_WINDOW_MINUTES already uses for the daily scoreboard, and for
    the same reason: a window generous enough to survive drift, plus a marker
    that makes a second send impossible. It also gets the runner-was-down case
    right for free -- when the box comes back at 4:07, the 4:00 slot is claimed
    and the older ones are left to back-fill, which is where they belong.
    """
    now = now or dt.datetime.now()
    already = set(sent)
    claim = None
    for label in slots_for(now.weekday()):
        hour, minute = _hhmm(label)
        when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if when > now:
            break
        if label in already:
            continue
        if (now - when).total_seconds() / 60.0 <= CATCH_UP_MINUTES:
            claim = label          # keep going: we want the LATEST due slot
    return claim


def latest_slot(now: Optional[dt.datetime] = None) -> Optional[str]:
    """The most recent slot that has passed today, ignoring what's been sent.

    For the HUB BUTTON, not the schedule: somebody clicking "Snapshot now" at
    4:12 means the 4:00 column, and at 9:15am on a Monday means the day's first
    slot (they are early; the 1:00 PM cell is the one they'll fill). due() is
    deliberately not used here -- it refuses a slot already stamped, which is
    exactly the case where a person is clicking the button to redo it.
    """
    slots = slots_for((now or dt.datetime.now()).weekday())
    if not slots:
        return None
    now = now or dt.datetime.now()
    passed = [s for s in slots
              if now.replace(hour=_hhmm(s)[0], minute=_hhmm(s)[1],
                             second=0, microsecond=0) <= now]
    return passed[-1] if passed else slots[0]


# --- the numbers ------------------------------------------------------------
def totals(agents: Sequence[Dict]) -> Dict[str, int]:
    """Team-wide {new_internet, dtv, total_units} for the day so far.

    EVERY rep who sold, including the ones with no row on the board. This is an
    org time-series, not a roster view: a sale that happened is part of the
    day's pace whether or not the person has a line on the board yet. (The
    leaderboard makes the opposite call for the missing reps, and says so out
    loud -- there it is a paperwork problem somebody can fix.)

    Reuses calc.metrics_for so the flooring and the upgrade subtraction can
    never drift from the board's. If the board's reading of a sale changes,
    this changes with it.
    """
    new_internet = dtv = total = 0
    for a in agents:
        m = calc.metrics_for(a)
        new_internet += m["Int"]
        dtv += m["DTV"]
        total += m["Int"] + m["DTV"] + m["NL"]
    return {"new_internet": new_internet, "dtv": dtv, "total_units": total}


def date_label(day: dt.date) -> str:
    """'Thursday, August 27, 26' -- col A's own spelling, built by hand."""
    return "%s, %s %d, %s" % (day.strftime("%A"), day.strftime("%B"),
                              day.day, day.strftime("%y"))


# --- geometry ---------------------------------------------------------------
def _cell(grid, row: int, col: int) -> str:
    """1-based, and blank for anything off the end of the grid."""
    if 1 <= row <= len(grid):
        line = grid[row - 1]
        if 1 <= col <= len(line):
            return str(line[col - 1] or "")
    return ""


def slot_columns(grid) -> Dict[str, Dict[str, int]]:
    """{'4:00 PM': {'new internet': 20, 'total units': 21, 'delta': 22}}.

    Read off rows 1-2 every run. A slot missing one of the three sub-headers is
    returned with only what it has, and the writer refuses it -- better a slot
    that says it cannot be written than three numbers landing one column left.
    """
    out: Dict[str, Dict[str, int]] = {}
    width = max((len(r) for r in grid[:SUBHEAD_ROW]), default=0)
    current = None
    for col in range(1, width + 1):
        label = _cell(grid, LABEL_ROW, col).strip()
        if label:
            current = label
            out.setdefault(current, {})
        if not current:
            continue
        sub = _cell(grid, SUBHEAD_ROW, col).strip().lower()
        if sub.startswith(NEW_INTERNET):
            out[current][NEW_INTERNET] = col
        elif sub.startswith(TOTAL_UNITS):
            out[current][TOTAL_UNITS] = col
        elif sub.startswith(DELTA):
            out[current][DELTA] = col
    return out


def find_row(grid, day: dt.date) -> Optional[int]:
    """The 1-based sheet row whose col A is `day`, or None."""
    want = date_label(day)
    for r in range(FIRST_DATE_ROW, len(grid) + 1):
        if _cell(grid, r, 1).strip() == want:
            return r
    return None


# HOW FAR THE DATE COLUMN IS KEPT AHEAD OF TODAY. Column A is a pre-typed
# calendar somebody filled in by hand; it ran to 2026-09-16, and the day it
# ran out this report would have gone quiet in the one way that is hard to
# notice -- the texts keep arriving, correct, and only the tab stops filling.
# So the calendar extends itself, and 90 days means the first person to look
# is looking at a problem that is three months away rather than one that has
# already happened.
CALENDAR_AHEAD_DAYS = 90


def last_calendar_date(grid) -> Optional[Tuple[int, dt.date]]:
    """(row, date) of the last parseable date in col A, or None.

    Walks up from the bottom, because a stray note under the calendar should
    not be mistaken for the end of it.
    """
    for r in range(len(grid), FIRST_DATE_ROW - 1, -1):
        raw = _cell(grid, r, 1).strip()
        if not raw:
            continue
        try:
            return r, dt.datetime.strptime(raw, "%A, %B %d, %y").date()
        except ValueError:
            continue
    return None


def ensure_calendar(worksheet, grid, day: dt.date,
                    ahead: int = CALENDAR_AHEAD_DAYS,
                    apply_writes: bool = False) -> Tuple[int, List[str]]:
    """Append date rows to col A until it reaches `day` + `ahead`.

    APPEND ONLY, and column A only -- never a rewrite of what is there. The
    dates run consecutively INCLUDING Sundays (the tab carries a Sunday row
    even though nothing sells), so the sequence simply continues from the last
    one; a gap would put every later row's data on the wrong date.

    Refuses rather than guesses if the bottom of col A does not parse: a
    calendar we cannot read the end of is one we must not append to, because
    the append would land in the wrong place.
    """
    found = last_calendar_date(grid)
    if not found:
        return 0, ["could not read the end of column A on %r -- not extending "
                   "it; the dates need a person" % TAB]
    last_row, last_day = found
    want_through = day + dt.timedelta(days=ahead)
    if last_day >= want_through:
        return 0, []

    missing = []
    d = last_day + dt.timedelta(days=1)
    while d <= want_through:
        missing.append(d)
        d += dt.timedelta(days=1)

    notes = ["column A ran to %s; extending it by %d day(s) to %s"
             % (date_label(last_day), len(missing), date_label(missing[-1]))]
    if not apply_writes:
        return 0, notes + ["(preview: nothing written)"]

    end_row = last_row + len(missing)
    # get_all_values() stops at the last non-empty row, so the sheet may simply
    # not have the rows yet. Grow it before writing off the end.
    if end_row > worksheet.row_count:
        worksheet.add_rows(end_row - worksheet.row_count + 50)
    worksheet.update("A%d:A%d" % (last_row + 1, end_row),
                     [[date_label(d)] for d in missing],
                     value_input_option="RAW")
    # Keep the in-memory grid in step so find_row() sees the new rows without
    # a second read of the whole tab.
    while len(grid) < last_row:
        grid.append([])
    for d in missing:
        grid.append([date_label(d)])
    return len(missing), notes


def _a1(row: int, col: int) -> str:
    letters, c = "", col
    while c > 0:
        c, rem = divmod(c - 1, 26)
        letters = chr(65 + rem) + letters
    return "%s%d" % (letters, row)


def _num(raw: str) -> Optional[int]:
    raw = str(raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def read_slot(grid, row: Optional[int], cols: Dict[str, int]) -> Dict[str, Optional[int]]:
    """{'new_internet', 'total_units'} for one row/slot; None where blank."""
    if not row:
        return {"new_internet": None, "total_units": None}
    return {
        "new_internet": _num(_cell(grid, row, cols.get(NEW_INTERNET, 0))),
        "total_units": _num(_cell(grid, row, cols.get(TOTAL_UNITS, 0))),
    }


# --- back-fill --------------------------------------------------------------
# HOW MANY MISSED SLOTS ARE STILL WORTH GUESSING AT. Four is two hours.
#
# Beyond that it is not a gap, it is a COLD START, and the two want opposite
# treatment. A runner down from 2:30 to 3:30 really did have a total close to
# the one standing now, so a flat line there is roughly true and gives tomorrow
# its comparison. But the first run of a new deployment stamps the CURRENT
# total backwards across the whole afternoon -- on 2026-08-27 the 7:00 PM
# reading (18/25) was written into all twelve slots from 1:00 PM, and tomorrow
# would have read them as "yesterday at 1:00 PM: 25" and told the room it was
# 23 units down at lunchtime, twelve times, against a number that never
# happened. A blank cell costs tomorrow one comparison line; a fabricated one
# costs it a false alarm, and the false alarm is worse.
MAX_BACKFILL_SLOTS = 4


def backfill_plan(grid, row: int, slot_cols: Dict[str, Dict[str, int]],
                  slots: List[str], upto: str,
                  now_totals: Dict[str, int]) -> Tuple[List[Dict], List[str]]:
    """Fill the blank slots immediately BEFORE `upto` with today's numbers.

    WHY A FLAT LINE IS THE RIGHT ANSWER. If the runner was down from 2 to 4, the
    2:30 and 3:00 columns are blank and cannot be recovered -- nobody recorded
    what the total was at 2:30. Writing the CURRENT total into them is
    knowingly wrong about the shape of that afternoon, and knowingly right
    about the thing those cells are actually for: tomorrow's row reads them to
    say "yesterday at 2:30". A blank there costs tomorrow its 2:30 comparison
    as well, so one bad afternoon silently becomes two.

    It stops at the first slot that already HAS a number -- back-fill fills a
    gap at the end, never paints over the middle of a day that was recorded --
    and it fills at most MAX_BACKFILL_SLOTS of them, naming the rest in a note.
    The Delta column is never back-filled: a delta computed against the wrong
    minute is a made-up number that looks exactly like a real one.
    """
    updates: List[Dict] = []
    skipped: List[str] = []
    try:
        idx = slots.index(upto)
    except ValueError:
        return updates, []
    filled = 0
    for label in reversed(slots[:idx]):
        cols = slot_cols.get(label) or {}
        if NEW_INTERNET not in cols or TOTAL_UNITS not in cols:
            continue                      # a text-only slot (Saturday noon)
        if read_slot(grid, row, cols)["new_internet"] is not None:
            break                         # real data -- stop, don't overwrite
        if filled >= MAX_BACKFILL_SLOTS:
            # Keep walking so the note can name the whole run left blank --
            # a cap nobody is told about reads as "covered everything".
            skipped.append(label)
            continue
        updates.append({"range": _a1(row, cols[NEW_INTERNET]),
                        "values": [[now_totals["new_internet"]]]})
        updates.append({"range": _a1(row, cols[TOTAL_UNITS]),
                        "values": [[now_totals["total_units"]]]})
        filled += 1
    notes = []
    if skipped:
        notes.append(
            "left %d earlier slot(s) BLANK (%s back to %s): more than %d blank "
            "slots in a row is a cold start, not a gap, and stamping the "
            "current total that far back would have tomorrow comparing "
            "against a number that never happened"
            % (len(skipped), skipped[0], skipped[-1], MAX_BACKFILL_SLOTS))
    return updates, notes


def last_week_close(grid, day: dt.date,
                    slot_cols: Dict[str, Dict[str, int]],
                    slots: List[str]) -> Optional[Dict[str, int]]:
    """Same weekday last week, at its LAST recorded slot -- the day's close.

    Scanned backwards from the end of the day rather than read from a fixed
    'end of day' column, because the last slot that got written varies: a
    Saturday closes at 6:30, a Friday the runner lost at 8:15 closes at 8:00.
    The last number present IS that day's final total.
    """
    row = find_row(grid, day - dt.timedelta(days=7))
    if not row:
        return None
    for label in reversed(slots):
        cols = slot_cols.get(label) or {}
        if NEW_INTERNET not in cols:
            continue
        got = read_slot(grid, row, cols)
        if got["new_internet"] is not None:
            return {"new_internet": got["new_internet"],
                    "total_units": got["total_units"] or 0}
    return None


# --- the message ------------------------------------------------------------
def _diff_line(today: int, prior: Optional[int], label: str) -> List[str]:
    """The 'Today / Yesterday / Difference' block for one metric.

    No prior reading -> today's number only. The old system dropped the two
    lines entirely rather than printing 'Yesterday: 0', which is the right
    call: 0 is a claim about yesterday, and a blank cell is not one.
    """
    out = ["Today: %d" % today]
    if prior is None:
        return out
    out.append("Yesterday at %s: %d" % (label, prior))
    delta = today - prior
    if delta > 0:
        out.append("Difference: %s +%d" % (UP, delta))
    elif delta < 0:
        out.append("Difference: %s %d" % (DOWN, delta))
    else:
        out.append("Difference: 0")
    return out


def message(label: str, now: Dict[str, int], prior: Dict[str, Optional[int]],
            last_week: Optional[Dict[str, int]], day: dt.date) -> str:
    """The chat text, laid out exactly as the old system's (screenshot,
    2026-08-11 4:00 PM in the A-Team chat). Kept line for line on purpose --
    the field has read this shape twice an hour for months, and a port is not
    the moment to redesign it."""
    lines = ["%s Sales Update - %s" % (CHART, label), ""]
    lines.append("%s New Internet" % GLOBE)
    lines += _diff_line(now["new_internet"], prior.get("new_internet"), label)
    lines += ["", "%s DTV Streaming: %d" % (TV, now["dtv"]), ""]
    lines.append("%s Total Units" % BOX)
    lines += _diff_line(now["total_units"], prior.get("total_units"), label)
    if last_week:
        lines += ["", "Last %s's Sales:" % day.strftime("%A"),
                  "%s New Internet: %d" % (GLOBE, last_week["new_internet"]),
                  "%s Total Units: %d" % (BOX, last_week["total_units"])]
    return "\n".join(lines)


# --- one snapshot -----------------------------------------------------------
def open_tab(client=None):
    from automations.recruiting_report.fill import _client
    gc = client or _client()
    book = gc.open_by_key(C.SPREADSHEET_ID)
    for ws in book.worksheets():
        if ws.title.strip().lower() == TAB.lower():
            return ws
    raise RuntimeError("no %r tab on the sales board workbook" % TAB)


def snapshot(agents: Sequence[Dict], label: str, day: dt.date, *,
             apply_writes: bool = False, send: bool = False,
             worksheet=None, log=print) -> Dict:
    """Stamp `label`'s column and text the chat. Returns what it did.

    BEST EFFORT, IN THIS ORDER: the sheet write is attempted first and its
    failure is caught, because the text is the half people are waiting on and a
    Sheets 429 must not cost them the update. The reverse -- letting a failed
    send skip the write -- would lose the cell permanently, since the slot is
    gone in thirty minutes.
    """
    result = {"label": label, "wrote": 0, "texted": False,
              "totals": totals(agents), "notes": []}
    now = result["totals"]
    log("Times of Sales %s: New Internet %d, DTV %d, Total Units %d"
        % (label, now["new_internet"], now["dtv"], now["total_units"]))

    prior: Dict[str, Optional[int]] = {"new_internet": None, "total_units": None}
    last_week = None
    slots = slots_for(day.weekday())

    try:
        ws = worksheet or open_tab()
        grid = ws.get_all_values()
        slot_cols = slot_columns(grid)
        cols = slot_cols.get(label) or {}

        # Keep the date column ahead of today BEFORE looking for today's row,
        # so the day the calendar runs out is a row that gets appended rather
        # than a snapshot that quietly writes nothing.
        added, cal_notes = ensure_calendar(ws, grid, day,
                                           apply_writes=apply_writes)
        result["notes"].extend(cal_notes)
        if added:
            log("  extended column A by %d date row(s)" % added)

        row = find_row(grid, day)

        if row is None:
            # Col A is a pre-typed calendar running months ahead, so a missing
            # date means it ran out -- a person has to extend it. Said out
            # loud, and the text still goes.
            result["notes"].append(
                "no %r row on the %r tab -- col A needs extending; nothing "
                "written, the text still went" % (date_label(day), TAB))
        prev_row = find_row(grid, day - dt.timedelta(days=1))
        if row is not None and cols:
            prior = read_slot(grid, prev_row, cols)
        last_week = last_week_close(grid, day, slot_cols, slots)

        if row is not None and NEW_INTERNET in cols and TOTAL_UNITS in cols:
            updates, back_notes = backfill_plan(grid, row, slot_cols, slots,
                                                label, now)
            if updates:
                result["notes"].append(
                    "back-filled %d missed slot(s) with the current totals so "
                    "tomorrow has a reference" % (len(updates) // 2))
            result["notes"].extend(back_notes)
            updates.append({"range": _a1(row, cols[NEW_INTERNET]),
                            "values": [[now["new_internet"]]]})
            updates.append({"range": _a1(row, cols[TOTAL_UNITS]),
                            "values": [[now["total_units"]]]})
            if prior["total_units"] is not None and DELTA in cols:
                updates.append({"range": _a1(row, cols[DELTA]),
                                "values": [[now["total_units"]
                                            - prior["total_units"]]]})
            if apply_writes:
                # RAW, and ONE batch. These are plain integers -- USER_ENTERED
                # would let Sheets reinterpret them -- and a per-cell loop here
                # runs 34 times a day against a workbook six other reports
                # write. [[reference_sheets_write_quota_429]]
                ws.batch_update(updates, value_input_option="RAW")
                result["wrote"] = len(updates)
                log("  wrote %d cell(s) to row %d of %r" % (len(updates), row, TAB))
            else:
                log("  %d cell(s) would change (preview): %s"
                    % (len(updates), ", ".join(u["range"] for u in updates)))
        elif row is not None and not cols:
            result["notes"].append(
                "%r has no column on the %r tab -- text only" % (label, TAB))
    except Exception as e:  # noqa: BLE001 — the text must survive a Sheets failure
        result["notes"].append("sheet step failed: %s: %s"
                               % (type(e).__name__, str(e)[:200]))
        log("  SHEET STEP FAILED (the text still goes): %s: %s"
            % (type(e).__name__, str(e)[:200]))

    body = message(label, now, prior, last_week, day)
    result["body"] = body
    for group in C.TIMES_GROUPS:
        try:
            from automations.alphalete_sales_board import notify as N
            N.text_group(group, body, dry_run=not send, log=log)
            result["texted"] = result["texted"] or send
        except Exception as e:  # noqa: BLE001 — one room must not cost the others
            result["notes"].append("%s: %s: %s" % (group, type(e).__name__,
                                                   str(e)[:160]))
            log("  %s FAILED: %s: %s" % (group, type(e).__name__, str(e)[:160]))
    for n in result["notes"]:
        log("  note: %s" % n)
    return result
