"""SHOWED TO DAY 1 (column K) on Raf's Daily Update — filled in afterwards.

The daily run cannot write this column. A row is about an INTERVIEW day; the
question is about the person's START day, a week or so later ("11/2/26 ...
BOB ... 11/9"). On interview evening the answer does not exist, so the daily
run leaves K alone (`layout.WRITE_KEYS`) and this sweep comes back for it
once the start date has passed.

It matters because the '2nd Rds' tab counts its "New starts showed" KPI as
`K = "YES"` and nothing else — so an unfilled K reads as a 0% show rate for
every leader, which is what the live tab shows today: not one K filled on
the whole November tab, 11/9 starts included.

WHO TURNED UP is not ours to judge. Megan already set the rule on
2026-10-01 and `local_office_1on1s.obcl` holds it, so we reuse it rather
than restate it — and in HER order, because the two signals are not equal:

  1. THE SALES BOARD'S NEW STARTS BLOCK IS THE ATTENDANCE REGISTER. "If they
     make it on the sales board in this section, even if they aren't marked
     CR they attended day 1 of orientation." Somebody scheduled who never
     turned up never gets a row there, so presence IS the answer.
  2. The OBCL's Final Status, second: SHOWED_STATUSES -> YES ("owner
     submitted and terminated both showed - count those"), NOT_SHOWED -> NO.

The order is not a preference, it is what the live data forced. On 2026-11-20
the OBCL carried all 39 of Raf's started BOBs and gave a status for 2 of
them: Final Status is a LIFECYCLE field somebody fills in later, not an
attendance flag. Reading it alone answered 2 of 41 rows.

An unanswered person stays BLANK and is logged by name. A blank here means
"neither source has said yet", never "did not show" — guessing NO would
quietly invent the very KPI this exists to report. The sweep is re-runnable
for exactly that reason: it only ever fills an empty cell, and a later run
picks up whoever the board or the OBCL has decided since.

Both the current month tab and the PREVIOUS one are swept, because a person
interviewed on 10/30 starts in November while their row stays on October's
tab — sweeping only this month would miss them for good.

    python -m automations.raf_daily_update.day1                   # dry
    python -m automations.raf_daily_update.day1 --write
    python -m automations.raf_daily_update.day1 --write --test-sheet
    python -m automations.raf_daily_update.day1 --month 2026-10 --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from typing import Dict, List, Optional, Tuple

from automations.local_office_1on1s import obcl as OBCL
from automations.raf_daily_update import layout as L
from automations.raf_daily_update import offices as OFF

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

YES, NO = "YES", "NO"


def log(msg: str) -> None:
    print(msg, flush=True)


def _fold(s) -> str:
    """ONE key for all three sides, or the match is theatre.

    `shared.names.base_name` because it is the one built for "recognising the
    SAME PERSON across two week tabs": it drops the board's own '(Wk 2)' tag,
    which the Daily Update never writes, and it folds the non-breaking spaces
    that pasted names carry. The OBCL's own `_fold` leaves parentheticals on,
    so using it here would miss every new start the board has re-labelled.
    """
    from automations.shared.names import base_name
    return base_name(s)


def short_key(name: str) -> str:
    """'mirsha ruiz gomez' -> 'mirsha|ruiz': first name + FIRST surname token.

    The board and the Daily Update write the same person's name to different
    lengths. On WE 11.15 the board has 'Mirsha Ruiz Gómez' where the sheet
    has 'Mirsha Ruiz', and the same split shows up for every recruit with two
    surnames -- which in this office is a lot of them. Comparing the full
    strings scored those as strangers.

    Accents are folded too ('Gómez' -> 'gomez'), since only one of the two
    sheets types them.

    It is deliberately NOT fuzzy. 'Trevor Wooda' on the board and 'Trevor
    Woods' on the sheet are plainly one person, and this still calls them two
    -- an edit-distance match would also merge real siblings, and a wrong YES
    here is a number Megan would have to un-believe later. A miss stays a
    logged blank; a guess would not.
    """
    import unicodedata
    flat = unicodedata.normalize("NFKD", _fold(name))
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    parts = [p for p in flat.replace("-", " ").split() if p]
    if len(parts) < 2:
        return ""
    return "%s|%s" % (parts[0], parts[1])


def index(answers: Dict[str, str]) -> Dict[str, str]:
    """A by-name answer map -> the same answers also reachable by short key.

    A short key two DIFFERENT people share is dropped, not guessed at: two
    'maria|garcia' rows mean the short key has stopped identifying anybody.
    """
    short: Dict[str, List[str]] = {}
    for name in answers:
        k = short_key(name)
        if k:
            short.setdefault(k, []).append(name)
    out = dict(answers)
    for k, names in short.items():
        verdicts = {answers[n] for n in names}
        if k not in out and len(verdicts) == 1:
            out[k] = verdicts.pop()
    return out


def look_up(answers: Dict[str, str], name: str) -> str:
    """The verdict for one person: by full name, else by short key."""
    return answers.get(_fold(name)) or answers.get(short_key(name)) or ""


# ------------------------------------------------------------------ the OBCL

def showed_map(grid: List[List[str]]) -> Dict[str, str]:
    """The OBCL grid -> {folded name: 'YES'|'NO'}.

    Pure, so the rule is testable without a Sheet. A name the OBCL carries
    twice (two class weeks) keeps the DECIDED answer: somebody who no-showed
    one week and turned up the next did show to day 1, and that is the
    question the column asks.
    """
    out: Dict[str, str] = {}
    for _week, leaders in OBCL.read(grid).items():
        for rows in leaders.values():
            for r in rows:
                name = _fold(r.get("name"))
                if not name:
                    continue
                st = r.get("status") or ""
                if st in OBCL.SHOWED_STATUSES:
                    out[name] = YES
                elif st in OBCL.NOT_SHOWED:
                    out.setdefault(name, NO)
    return out


# --------------------------------------------------------- the sales board

def classroom_names(grid) -> List[str]:
    """Every name in one week's board 'Classroom / Trainers' block.

    NOT `sales_board_mind_map.classroom_trainers`, which keeps only the rows
    whose Trainer cell is filled, because it is answering a different
    question (whose team is this person on). Here a blank Trainer is
    irrelevant: the row's EXISTENCE is the attendance, so every name counts.
    """
    from automations.sales_board_mind_map.run import _base, _classroom_cols
    from automations.terminated_reps import board as BD
    header = _classroom_cols(grid)
    if not header:
        return []
    hrow, name_col, _trainer_col = header
    out = []
    for r in range(hrow + 1, len(grid) + 1):
        who = str(BD._cell(grid, r, name_col) or "").strip()
        if who:
            out.append(_base(who))
    return out


def read_board(starts: List[dt.date]) -> Dict[str, str]:
    """{folded name: 'YES'} for everyone on the New Starts block of the weeks
    those start dates fall in. Only the weeks we need are opened."""
    from automations.local_office_1on1s import sales as SA
    from automations.recruiting_report.fill import open_by_key
    from automations.terminated_reps import board as BD
    sh = open_by_key(BD.SHEET_ID)
    tabs = SA.week_tabs([w.title for w in sh.worksheets()],
                        max(s.year for s in starts) if starts else
                        dt.date.today().year)
    # a start date -> the week-ending Sunday of the tab that holds it
    want = {}
    for wk, title in tabs.items():
        for s in starts:
            if 0 <= (wk - s).days <= 6:
                want[wk] = title
    out: Dict[str, str] = {}
    for wk in sorted(want):
        names = classroom_names(sh.worksheet(want[wk]).get_values())
        for n in names:
            out[_fold(n)] = YES
        log("  board %r: %d on the New Starts block" % (want[wk], len(names)))
    if not want:
        log("  no sales board tab covers %s"
            % ", ".join(sorted({"%s" % s for s in starts})))
    return out


def read_obcl() -> Dict[str, str]:
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(OBCL.SHEET_ID)
    grid = sh.worksheet(OBCL.TAB).get_values()
    m = showed_map(grid)
    log("  OBCL %r: %d names decided (%d showed, %d didn't)"
        % (OBCL.TAB, len(m), sum(v == YES for v in m.values()),
           sum(v == NO for v in m.values())))
    return m


# ------------------------------------------------------------- the month tab

def start_date(bob_cell: str, interviewed: dt.date) -> Optional[dt.date]:
    """The BOB Date cell ('11/9', no year) as a real date.

    IT CAN BE NEXT YEAR. The sheet writes the start day without a year and
    the row lives on the month of the INTERVIEW, so a 12/28 interview with a
    BOB Date of '1/4' starts in January. Read against the tab's own year that
    is 1/4 of the SAME year -- ten months in the past -- and the sweep would
    call an unstarted person overdue, then blank-flag them forever. A start
    that lands before its own interview is therefore next year's.
    """
    d = L.parse_sheet_date(bob_cell, interviewed.year)
    if d and d < interviewed:
        try:
            d = d.replace(year=d.year + 1)
        except ValueError:                 # 2/29 of a non-leap year
            d = d.replace(year=d.year + 1, day=28)
    return d


def pending(grid: List[List[str]], lay: Dict[str, int], year: int,
            today: dt.date) -> List[Tuple[int, str, dt.date]]:
    """[(1-based row, 'First Last', start date)] for every row this sweep owes
    an answer: a BOB whose start day has passed and whose K is empty.

    A row with K already filled is never touched — the recruiters type in
    this column too, and theirs wins.
    """
    out = []
    for n, raw in enumerate(grid[1:], 2):
        raw = list(raw) + [""] * 20
        r = {k: str(raw[i]).strip() for k, i in lay.items()}
        if r.get("day1"):
            continue
        if L.status_rank(r["status"]) != L.ORDER.index(L.BOB):
            continue           # only a BOB has a start day to show up to
        interviewed = L.parse_sheet_date(r.get("date", ""), year)
        start = start_date(r.get("bob_date", ""),
                           interviewed or dt.date(year, 1, 1))
        if not start or start > today:
            continue
        name = ("%s %s" % (r["first"], r["last"])).strip()
        if name:
            out.append((n, name, start))
    return out


def _months(month: dt.date) -> List[dt.date]:
    prev = (month.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    return [prev, month.replace(day=1)]


def sweep(sheet_id: str, month: dt.date, write: bool, tab: str = "",
          today: Optional[dt.date] = None,
          answers: Optional[Dict[str, str]] = None) -> int:
    """Fill K on the month's tab and the one before it. Returns cells written
    (or that would be, on a dry run)."""
    from automations.raf_daily_update.run import read_tab
    today = today or dt.date.today()

    # The month tabs first, so the board is asked only about the weeks
    # somebody actually started in.
    tabs = []
    for m in _months(month):
        try:
            ws, lay, grid = read_tab(sheet_id, m, tab)
        except RuntimeError as e:          # no tab for that month yet
            log("  %s" % e)
            continue
        if "day1" not in lay:
            log("  %r has no SHOWED TO DAY 1 column - skipped" % ws.title)
            continue
        tabs.append((ws, lay, pending(grid, lay, m.year, today)))

    if answers is None:
        starts = sorted({st for _ws, _l, owed in tabs for _n, _nm, st in owed})
        answers = {}
        if starts:
            answers.update(read_obcl())            # the fallback, first in
            answers.update(read_board(starts))     # the register, and it wins
            answers = index(answers)

    total = 0
    for ws, lay, owed in tabs:
        data, unknown = [], []
        for n, name, start in owed:
            verdict = look_up(answers, name)
            if not verdict:
                unknown.append("%s (started %s)" % (name, L.sheet_date(start)))
                continue
            data.append({"range": "'%s'!%s%d" % (ws.title,
                                                 L.col_letter(lay["day1"]), n),
                         "values": [[verdict]]})
        log("  %r: %d started and still blank, %d answered, %d not on the "
            "board or the OBCL yet%s"
            % (ws.title, len(owed), len(data), len(unknown),
               "" if write else "  (dry-run)"))
        for u in unknown:
            log("    no answer yet: %s" % u)
        if write and data:
            ws.spreadsheet.values_batch_update(
                body={"valueInputOption": "USER_ENTERED", "data": data})
        total += len(data)
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--office", default="raf", help="office key (offices.py)")
    ap.add_argument("--month", default=None, help="YYYY-MM (default this one)")
    ap.add_argument("--write", action="store_true",
                    help="actually fill the cells (default dry-run)")
    ap.add_argument("--test-sheet", action="store_true",
                    help="write the office's test copy")
    ap.add_argument("--dry-run", action="store_true", help="never write")
    args = ap.parse_args(argv)
    try:
        office = OFF.get(args.office)
    except KeyError as e:
        ap.error(str(e))
    if args.dry_run:
        args.write = False
    sheet = office.test_sheet if args.test_sheet else office.sheet
    if not sheet:
        ap.error("office %s has no %ssheet in offices.py"
                 % (office.key, "test " if args.test_sheet else ""))
    month = (dt.date(*[int(x) for x in args.month.split("-")], 1)
             if args.month else dt.date.today())
    log("=== SHOWED TO DAY 1 · %s · %s · %s ==="
        % (office.key, month.strftime("%B %Y"),
           "WRITE" if args.write else "DRY-RUN"))
    n = sweep_riding_quota(sheet, month, args.write, office.tab)
    log("filled %d cell(s)" % n)
    return 0


# Extra waits, in seconds, when Sheets says the per-minute read quota is used
# up. They come after fill._retry's own ~3 minutes of 30s+ waits have already
# run out.
QUOTA_WAITS_S = (120, 240)


def _is_quota(exc: BaseException) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status == 429 or "[429]" in str(exc) or "Quota exceeded" in str(exc)


def sweep_riding_quota(sheet_id: str, month: dt.date, write: bool,
                       tab: str = "", waits=QUOTA_WAITS_S, sleep=time.sleep
                       ) -> int:
    """sweep(), tried again after a longer pause when Sheets answers 429.

    WHY (2026-11-21): the 5pm run died on "Quota exceeded for 'Read requests
    per minute per user'" reading the Sales Board. This sweep runs straight
    after Raf's Daily Update, on the same Lucy 2 account, so it starts inside
    the minute that run just spent. fill._retry waited ~3 minutes and gave up,
    and a standalone job is never retried, so the column stayed blank until
    a person re-ran it. Running the whole sweep again is safe: it only fills a
    cell that is still EMPTY, so a second pass can't overwrite or double
    anything. Anything that is not a quota error still fails at once."""
    for i, wait in enumerate((0,) + tuple(waits)):
        if wait:
            log("  Sheets read quota is used up for this account - waiting "
                "%ds, then trying again (%d of %d)" % (wait, i, len(waits)))
            sleep(wait)
        try:
            return sweep(sheet_id, month, write, tab)
        except Exception as exc:                            # noqa: BLE001
            if not _is_quota(exc) or i == len(waits):
                raise
    return 0  # unreachable: the last attempt returns or raises


if __name__ == "__main__":
    raise SystemExit(main())
