"""TK -- the per-day Total Knocks column on the Alphalete SALES BOARD 2025.

An ADD-ON to the production batch, not a report of its own (Eve 2026-08-31):
no Hub card, no Slack post, no PDF. It writes ONE cell per rep per day.

WHERE THE COLUMN IS. Each day's block on 'Sales Board WE m.d' runs
Apps / Int / Int Up / DTV / NL / TK / Cx / Roll Call. That 'TK' sub-header
replaced 'EN' on the WE 9.6 tab -- so the column is found the way every other
fill on this board finds one: the weekday label in row 1, then the 'TK'
sub-header in row 3 UNDER it. Never an index; the blocks move every week and
the sub-headers get renamed (this one just was).

WHERE THE NUMBER COMES FROM. Ownerville -> TeleMapper Leads -> Disposition by
Rep (p=89) for RAF'S LOCAL OFFICE, column 'Total Knocks', for TODAY in Central
Time. Same scrape the daily Total Knocks board uses -- `total_knocks.pull` --
asked for today instead of yesterday.

TODAY IS A PARTIAL DAY, WHICH IS THE WHOLE POINT: reps knock all day and this
runs every 15 minutes, so every pass sees a bigger number than the last.

  * IT ONLY EVER RAISES. Same rule as the Energy fill and the Vantura board:
    a cell is written only when ownerville says MORE than it already holds.
    Knocks cannot go down within a day, so a pull that comes back short (a
    half-drawn table, a rep briefly missing) can never eat a real number.
  * A CELL SOMEBODY TYPED IN BY HAND IS NEVER TOUCHED. A non-numeric value in
    a TK cell is a human's mark, not our data -- it is left alone and named in
    the log.
  * A REP OWNERVILLE DOESN'T LIST IS LEFT BLANK, not zeroed. The page lists
    reps who knocked; absence at 9 AM means "not out yet", and writing 0 to
    sixty rows every quarter hour would bury the reps who are out.

THIS WRITES NOTHING ANY OTHER JOB READS. It touches only the TK cells of the
current week's tab -- not the Total Knocks Sheet, not the /knocks cache, not
the captainship sidecar. Tomorrow morning's boards re-collect the day from
ownerville the way they always did.

WHERE IT RUNS. Lucy 3, from com.alphalete.production-tk (StartInterval 900).
Ownerville allows ONE session per account, so a pass that finds a knocks pull
or a captainship build already holding it SKIPS rather than fighting for it --
the next tick is 15 minutes away. On a machine with no session holder (a
laptop) the pull fails by design; run it through `lucy` instead.

  python -m automations.alphalete_production.tk_fill              # preview today
  python -m automations.alphalete_production.tk_fill --apply      # write
  python -m automations.alphalete_production.tk_fill --date 2026-08-31
  python -m automations.alphalete_production.tk_fill --sheet-id <sandbox>
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

# Board GEOMETRY is shared with the Energy fill on purpose: same workbook, same
# three header rows, same '(Wk 2)' / '(NC)' name tags. One place to fix when the
# template drifts. Only the sub-header we look for differs.
from automations.energy_slack_fill.run import (
    DAY_LABELS,
    DAY_ROW,
    PROD_SHEET_ID,
    SUB_ROW,
    _cell,
    _norm,
    last_rep_row,
    name_col,
    week_of,
)
from automations.total_knocks.pull import (
    COL_REP,
    COL_TOTAL_KNOCKS,
    KnocksPullFailed,
    central_today,
    pull_disposition_day,
)

CENTRAL = ZoneInfo("America/Chicago")

SHEET_ID = os.environ.get("TK_FILL_SHEET_ID", PROD_SHEET_ID)
METRIC = "TK"          # the per-day sub-column Total Knocks lands in

# Quiet hours, Central. Every pass costs an ownerville browser session, and the
# fleet's heavy overnight jobs (the 4am wave, the 07:15 captainship build) share
# that one session per account. Between these hours nobody is knocking, so the
# tick would rewrite the same number at the price of a session. --force ignores
# the window; TK_FILL_HOURS="5-23" moves it.
ACTIVE_HOURS = os.environ.get("TK_FILL_HOURS", "6-23")


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def _md(d: dt.date) -> str:
    """'Monday 8/31' -- %-m is glibc-only and this runs on Windows too."""
    return f"{d.strftime('%A')} {d.month}/{d.day}"


def in_active_window(now: dt.datetime) -> bool:
    try:
        lo, hi = (int(x) for x in ACTIVE_HOURS.split("-", 1))
    except Exception:  # noqa: BLE001 -- a bad override must not stop the fill
        return True
    return lo <= now.hour <= hi


# --------------------------------------------------------------- sheet ---
def day_block(g, day: dt.date):
    """(Apps column, TK column) for `day`'s block: the weekday's group in row
    1, then its sub-headers in row 3. Apps is the block's first column. Either
    may be None -- a tab still labelled 'EN' has no TK column, and stopping is
    the only safe answer there (guessing a neighbour writes knocks into
    somebody's DTV)."""
    for c in range(1, 120):
        lab = _cell(g, DAY_ROW, c).strip().upper()
        if lab in DAY_LABELS and DAY_LABELS[lab] == day.weekday():
            tk = next((cc for cc in range(c, c + 10)
                       if _cell(g, SUB_ROW, cc).strip().upper() == METRIC), None)
            return c, tk
    return None, None


def tk_col(g, day: dt.date):
    """Just the TK column -- see day_block."""
    return day_block(g, day)[1]


def _a1_col(n: int) -> str:
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def apps_counts_tk(ws, apps_c: int, tk_c: int, row: int) -> bool:
    """Does that day's Apps formula ADD the TK cell into the rep's app count?

    THIS IS THE CHECK THIS MODULE EXISTS TO NOT NEED TWICE. The per-day Apps
    cell is =ARRAYFORMULA(IFS(..., (<Int>+<DTV>+<NL>+<6th>))) and that 6th term
    used to be EN -- an Energy SALE, rightly an app. When the sub-header was
    renamed to TK on 2026-08-31 the formula kept pointing at the same column,
    so the first knocks written landed in Apps: the board re-sorted itself by
    knocks and 'Reps that got on the Board' counted people who had sold
    nothing. A knock is not a sale. If the formula still adds us, we write
    NOTHING -- an empty TK column is a missing number, a poisoned Apps column
    is a wrong one, and only one of those is recoverable by the next tick.
    """
    a1 = f"{_a1_col(apps_c)}{row}"
    try:
        f = ws.acell(a1, value_render_option="FORMULA").value or ""
    except Exception:  # noqa: BLE001 -- a guard that crashes is worse than none
        return False
    return f"+{_a1_col(tk_c)}{row})" in str(f)


def roster(g) -> dict:
    """{row: board name} for EVERY rep on the tab -- the board carries two
    numbered sections (the '#' counter restarts partway down) and knocks are
    owed to both, so nothing here filters by Campaign or Team."""
    nc, last = name_col(g), last_rep_row(g)
    return {r: _cell(g, r, nc).strip()
            for r in range(SUB_ROW + 1, last + 1)
            if _cell(g, r, nc).strip()}


def _as_int(raw):
    """The cell as an int, or None when it holds something a human typed."""
    s = str(raw).strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return None


# --------------------------------------------------------------- match ---
def _ends(name: str) -> str:
    """First and last word of a normalised name -- 'justin carlos avila' and
    'justin avila' both collapse to 'justin avila'."""
    parts = _norm(name).split()
    return f"{parts[0]} {parts[-1]}" if len(parts) > 1 else _norm(name)


def match_rows(knocks: dict, rows: dict):
    """Ownerville rep -> board row. Returns (matched, unmatched_ov, ambiguous).

    Matched on the normalised full name first; a nickname in parentheses
    ('Noemi (Ivette) Ontiveros') is stripped by _norm, which is why the board's
    own tags survive.

    THE MIDDLE NAME IS THE ORDINARY CASE, not an exception. Ownerville carries
    the legal name and the board carries what people are called: 'Justin Carlos
    Avila' vs 'Justin Avila' (2026-08-31, the first name this fill missed). So
    a full-name miss falls back to FIRST + LAST word, which reads the two as
    the same person from either direction -- the board is just as likely to be
    the longer one ('Charley Alan Perez').

    A name that lands on TWO rows either way is never guessed: it is reported,
    the same way the Energy fill leaves the doubt blank. That is also why the
    fallback is a second pass and not a looser first pass -- an exact full-name
    hit must never be lost to a first+last collision.
    """
    by_norm: dict = {}
    by_ends: dict = {}
    for r, nm in rows.items():
        by_norm.setdefault(_norm(nm), []).append(r)
        by_ends.setdefault(_ends(nm), []).append(r)

    matched: dict = {}
    unmatched: list = []
    ambiguous: list = []
    for ov_name, count in knocks.items():
        hits = by_norm.get(_norm(ov_name), [])
        if not hits:
            hits = by_ends.get(_ends(ov_name), [])
        if len(hits) == 1:
            matched[hits[0]] = max(matched.get(hits[0], 0), count)
        elif not hits:
            unmatched.append(ov_name)
        else:
            ambiguous.append(ov_name)
    return matched, sorted(unmatched), sorted(ambiguous)


# ----------------------------------------------------------------- run ---
def build_plan(g, col: int, matched: dict, rows: dict):
    """[(rep, a1, current, new)] for the cells that would actually change,
    plus the ones held back because a human had written in them."""
    from gspread.utils import rowcol_to_a1

    plan, protected = [], []
    for r, count in sorted(matched.items()):
        cur_raw = _cell(g, r, col)
        cur = _as_int(cur_raw)
        if cur is None:
            protected.append((rows[r], rowcol_to_a1(r, col), cur_raw))
            continue
        if count > cur:
            plan.append((rows[r], rowcol_to_a1(r, col), cur, count))
    return plan, protected


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="the day to fill (YYYY-MM-DD); default today CT")
    ap.add_argument("--apply", action="store_true",
                    help="write to the Sheet (default is a preview)")
    ap.add_argument("--sheet-id", default=SHEET_ID,
                    help="override the workbook (point at a sandbox copy)")
    ap.add_argument("--force", action="store_true",
                    help="run outside the active hours, and don't defer to "
                         "another job holding the ownerville session")
    a = ap.parse_args(argv)

    day = dt.date.fromisoformat(a.date) if a.date else central_today()
    now = dt.datetime.now(CENTRAL)
    _log(f"TK fill -- {_md(day)}   (now {now:%H:%M} CT)")

    if not a.date and not a.force and not in_active_window(now):
        _log(f"outside the active window ({ACTIVE_HOURS} CT) -- nothing to do")
        return 0

    # ONE ownerville session per account. A pass that would fight the morning
    # knocks pull or the captainship build steps aside; the next tick is 15
    # minutes out and knocks only ever accumulate, so nothing is lost.
    if not a.force:
        from automations.knocks_request.service import ownerville_busy
        busy = ownerville_busy()
        if busy:
            _log(f"ownerville is held by {', '.join(busy)} -- skipping this pass")
            return 0

    try:
        pulled_day, records = pull_disposition_day(day, verbose=True)
    except KnocksPullFailed as e:
        _log(f"ownerville pull FAILED: {e}")
        return 75
    if pulled_day != day:
        _log(f"ownerville answered for {pulled_day}, not {day} -- writing nothing")
        return 75

    knocks = {}
    for rec in records:
        nm = str(rec.get(COL_REP, "")).strip()
        raw = rec.get(COL_TOTAL_KNOCKS, "")
        if not nm:
            continue
        try:
            knocks[nm] = int(float(str(raw).replace(",", "") or 0))
        except ValueError:
            continue
    _log(f"ownerville: {len(knocks)} rep(s) with knocks so far today "
         f"({sum(knocks.values())} total)")

    from automations.recruiting_report.fill import open_by_key, _retry
    from automations.alphalete_production.capture import find_week_tab
    ss = open_by_key(a.sheet_id)
    ws = find_week_tab(ss, day)
    g = ws.get_all_values()
    _log(f"sheet: {ss.title!r}  tab: {ws.title!r}"
         f"{'' if a.sheet_id == PROD_SHEET_ID else '   (NOT the prod workbook)'}")

    if not week_of(g, day):
        _log(f"{_md(day)} is not inside {ws.title!r}'s week -- writing nothing")
        return 75

    apps_c, col = day_block(g, day)
    if col is None:
        _log(f"no 'TK' sub-header under {day.strftime('%A').upper()} in row 3 of "
             f"{ws.title!r} -- the column was renamed or the block moved. "
             "Nothing written.")
        return 75

    rows = roster(g)
    if rows and apps_counts_tk(ws, apps_c, col, min(rows)):
        _log(f"REFUSING TO WRITE: {ws.title!r}'s {day.strftime('%A')} Apps "
             f"formula still ADDS column {_a1_col(col)} (TK) into the rep's app "
             "count -- every knock would be counted as a sale and the board "
             "would re-sort on knocks. Take the '+TK' term out of the Apps "
             "formula on all seven day blocks first (it is a leftover from when "
             "that column was EN).")
        return 75
    matched, unmatched, ambiguous = match_rows(knocks, rows)
    _log(f"board roster: {len(rows)} rep(s) - matched {len(matched)} - "
         f"TK column {col}")

    plan, protected = build_plan(g, col, matched, rows)
    if not plan:
        _log("nothing to write -- the board already holds today's knocks")
    for rep, a1, cur, new in plan:
        _log(f"  {a1}  {rep:<36} {cur} -> {new}")
    if protected:
        _log("")
        _log(f"LEFT ALONE -- {len(protected)} cell(s) hold something a human typed:")
        for rep, a1, raw in protected:
            _log(f"  {a1}  {rep:<36} {raw!r}")
    if unmatched:
        _log("")
        _log(f"NOT ON THE BOARD -- {len(unmatched)} ownerville rep(s) with knocks "
             "and no row (their knocks are not on the board):")
        for nm in unmatched:
            _log(f"  {nm}  ({knocks[nm]} knocks)")
        _log("  fix: add the rep to the tab, or the spelling to the ICD Aliases "
             "sheet -- never a patch here")
    if ambiguous:
        _log("")
        _log(f"AMBIGUOUS -- {len(ambiguous)} name(s) match TWO rows, left blank:")
        for nm in ambiguous:
            _log(f"  {nm}")

    if plan and a.apply:
        _retry(ws.batch_update,
               [{"range": a1, "values": [[new]]} for _rep, a1, _cur, new in plan])
        _log("")
        _log(f"wrote {len(plan)} TK cell(s) to {ws.title!r}")
    elif plan:
        _log("")
        _log("PREVIEW -- re-run with --apply to write")

    # 75 = EX_TEMPFAIL, the boards' hold code: the day is INCOMPLETE (a rep with
    # knocks has no row, or a name is ambiguous). What was sure went in, and the
    # next tick fills the rest -- the fill only ever raises.
    return 75 if (unmatched or ambiguous) else 0


if __name__ == "__main__":
    sys.exit(main())
