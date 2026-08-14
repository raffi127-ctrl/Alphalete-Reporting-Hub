"""Vantura Master Sales Board — daily data-quality audit (mini, 4am batch).

Grew out of the 2026-07-19 deep audit (see memory/vantura-board-data-quality
notes and automations/vantura_payroll/PAYROLL_RUNBOOK.md for the board map).
Two invariants, both broken silently in the past:

1. OFF-MENU ADDS: every Sales Board rep must have a Roll Call
   row (the roll cohort week is the tenure anchor; a rep without one gets a
   FROZEN week tag and dodges the stats). People are supposed to add reps
   ONLY via the Alphalete menu — name columns are hard-protected since
   2026-07-19, but protection-list editors can still bypass.
2. STATS-RANGE DRIFT: the summary boxes' fixed ranges (rows 5:<last rep>)
   silently exclude reps when rows are added/removed (menu adds insert at
   row 5, pushing range starts down).

Findings are appended to the board's "Report an Issue" tab, deduped against
rows already there. The tab is the only thing this writes, with ONE deliberate
exception since 2026-08-14: when the Sales Board marks a rep 'T' (terminated,
on the day it happens), it flips that rep's Roll Call Status to 'Terminated'
instead of asking a human to chase the same cell every few weeks. See the
auto-close block below for how narrow that write is and what it refuses to
touch.

  python -m automations.vantura_board_audit.run                  # audit + fix + report
  python -m automations.vantura_board_audit.run --dry-run        # print only
  python -m automations.vantura_board_audit.run --no-auto-close  # report, don't fix
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

REPORT_ID = "vantura-board-audit"
SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
WK_TAG = re.compile(r"^\d+(st|nd|rd|th) Wk$")
RANGE_TOK = re.compile(r"\$?[A-Z]{1,2}\$?(\d+):\$?[A-Z]{1,2}\$?(\d+)\b")

# Campaigns the Sales Board actually scoreboards. The reverse check below
# ("Active on the roll => must have a board row") ONLY holds for these: a
# campaign with no board section cannot have board rows, so every active person
# in it gets reported missing every morning, forever, and the report never goes
# green again.
#
# 'Base' was dropped 2026-08-13 (Carlos, via Eve). The board keeps a Base
# campaign row (r43) with zero rep rows under it on purpose — Base is simply not
# tracked here any more. Until this constant existed the audit reported all 13
# active Base reps as MISSING FROM BOARD / STALLED TRAINEE every day; that pile
# is what surfaced the question. Their sales still land in RAW and still get
# paid off the Commission tab — they just no longer roll up into the board's
# campaign totals, which is the intended behaviour, not a gap.
#
# A BLANK campaign deliberately still gets checked: blank is ambiguous, and
# silently skipping it would be the same class of coverage hole this audit
# exists to catch.
#
# 'JE' is LISTED ON PURPOSE even though the board has no JE rep rows today
# (17 Roll Call rows, none currently Active). Only Base was dropped; nobody
# has ruled on JE, and dropping a campaign is a business call, not a tidy-up.
# Leaving it in means a JE person who goes Active with no board row still gets
# reported — noisy if JE is in fact dead, silent if it isn't. Noisy is the
# right failure here: it asks the question instead of burying it. Take JE out
# only once Carlos says JE is off the board too.
BOARD_CAMPAIGNS = {"B2B", "BOX", "JE"}
ROLL_CAMPAIGN_COL = 2                  # Roll Call col C, header 'Campaign'

# --- auto-close of open terminations (2026-08-14, Eve) ---------------------
# WHERE A VANTURA TERMINATION IS ACTUALLY RECORDED: the SALES BOARD. On the day
# a rep is let go, their remaining day cells (Monday..Sunday) are filled with
# 'T' (Eve 2026-08-14, with a screenshot of WE 8.16). That mark is the event;
# the Roll Call's col B 'Status' and col M 'Date Gone' are bookkeeping that
# trails it and gets forgotten — 15 rows still Active on 2026-07-31, 8 on
# 2026-08-11, Samantha Rodriguez on 2026-08-14. Every time, the audit reported
# it, a human flipped the same cell, and the report went green again.
#
# So this syncs the Roll Call FROM the board's 'T', and as a second net also
# closes a row whose Date Gone is already set and in the past.
#
# The first design of this read New DU col A instead, on the theory that
# 'Not Active' meant terminated. It does NOT: New DU is the RECRUITING funnel
# (col A is the stage — '1 - Orientation Scheduled', '3 - In Training',
# '5 - Leader'), and 'Not Active' is its default parking bucket holding 2170 of
# 2243 rows, every applicant who never started included. Three Roll Call reps
# sat in it while selling — Jayden Luna had 32 sales the week before and was
# marked 'Here' Mon-Fri, and is a Trainer. Wiring that up would have terminated
# the campaign's best seller overnight. Do not use New DU as a status source.
#
# This is the ONE place the audit writes outside 'Report an Issue', and it is
# deliberately narrow:
#   - a 'T' run must not be followed by a SALE. A number after the mark means
#     it was wrong or the rep came back; that is not a termination to copy.
#   - never touches a row already 'Terminated', and never writes any status
#     other than 'Terminated'.
#   - the Date-Gone net only fires on a date that PARSES and is not in the
#     future. Someone working out their notice has a future Date Gone and is
#     still on the board; closing them early drops them out of headcount.
#   - only when the columns were found BY HEADER (Roll Call Status/Roll Call/
#     Date Gone, board Monday..Sunday). A write to a guessed index after a
#     re-layout is the expensive kind of wrong.
#   - only up to MAX_AUTO_CLOSE rows at once. A sudden pile is far more likely
#     to be a shifted column than 40 people quitting overnight, so past the cap
#     it refuses to write and reports instead — the old behaviour.
# Anything it declines to close still comes out as the usual finding, with the
# reason attached, so declining is never silent.
#
# It writes col B ONLY. Date Gone is left to a human even when the 'T' implies
# it: col N 'Days Lasted' and col O 'Reason Lost' hang off that date, and
# inventing it would be writing a second hand-kept column nobody asked for.
TERMINATED = "Terminated"
TERM_MARK = "T"
MAX_AUTO_CLOSE = 25
ROLL_HEADERS = {"status": "status", "name": "roll call", "gone": "date gone"}
ROLL_FALLBACK = {"status": 1, "name": 3, "gone": 12}   # cols B / D / M today
BOARD_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday"]


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _norm(n: str) -> str:
    return " ".join(str(n).lower().split())


def _cohort_weeks_old(week_tag: str):
    """Roll Call col A is an 'M.D' week-ending tag ('6.21', '4.26'). Return how
    many weeks ago that was, or None if it doesn't parse. Assumes the tag is in
    the past — a month ahead of today means it belongs to last year."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\s*$", str(week_tag))
    if not m:
        return None
    today = dt.date.today()
    mo, day = int(m.group(1)), int(m.group(2))
    for year in (today.year, today.year - 1):
        try:
            d = dt.date(year, mo, day)
        except ValueError:
            return None
        if d <= today:
            return (today - d).days // 7
    return None


def _a1col(j: int) -> str:
    """0-based column index -> A1 letter. Findings are read by a human who then
    has to FIND the cell; 'r71c17' sends them counting columns, 'Q71' doesn't."""
    s, j = "", j + 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def _alias_map(sh, log=_log):
    """The hidden 'Name Aliases' tab, both directions: col A is the board
    spelling, col B the paid/real one. Read ONCE per run and passed around —
    every caller used to open the tab itself, and Sheets' 60-reads/min ceiling
    is the thing that silently empties sections of these reports."""
    pairs = {}
    try:
        for r in sh.worksheet("Name Aliases").get_all_values()[1:]:
            if len(r) > 1 and str(r[0]).strip() and str(r[1]).strip():
                a, b = _norm(r[0]), _norm(r[1])
                pairs.setdefault(a, set()).add(b)
                pairs.setdefault(b, set()).add(a)
    except Exception as e:  # noqa: BLE001
        log(f"(no Name Aliases tab: {type(e).__name__}) — matching on exact names")
    return pairs


def _with_aliases(names, alias):
    """Every known spelling PLUS whatever Name Aliases says is the same person.

    Without this the aliases tab only bridged the sales/status evidence, never
    the name checks themselves — so the one mechanism Eve has for "the board
    calls her X, payroll calls her Y" did nothing for the two findings that
    actually fire on a spelling mismatch (OFF-MENU ADD and the Stations name
    hygiene). Adding the alias row is now the fix, per the repo rule: spelling
    mismatches go in the aliases sheet, not in per-report patches."""
    out = set(names)
    for n in names:
        out |= alias.get(n, set())
    return out


def _load_activity(sh, log=_log, alias=None):
    """Evidence used to explain WHY someone has no board row:
      - New DU col A status ('Not Active', '3 - In Training', '5 - Leader')
        keyed by the col-I name
      - RAW sale counts, last sale date AND a per-week-ending breakdown, keyed
        by col-B rep name
      - the RAW week tags themselves, most-recent-closed first

    The per-week breakdown exists because a lifetime count answers the wrong
    question (2026-07-31): Olivia Dittmer's 80 sales read as "actively selling"
    while her weeks were 32/15/18/10/2 — she was on her way out. RAW col C
    'Sale Date' is NOT a reliable recency signal either: her whole 7.26 week
    carries a blank Sale Date, so a max-of-col-C put her last sale at 7/15 and
    ranked her STALER than someone who genuinely stopped two weeks earlier.
    Recency comes off the col-A week tag, which is always populated.

    All three are name-keyed, so fold in the hidden 'Name Aliases' tab (col A
    is the board spelling, col B the paid/real one). Any tab going missing
    degrades to 'no evidence' — the caller then just reports the plain
    missing-row finding rather than crashing the whole audit."""
    alias = _alias_map(sh, log) if alias is None else alias

    def _spread(d):
        """copy each entry onto its aliases so either spelling resolves"""
        for key in list(d):
            for other in alias.get(key, ()):
                d.setdefault(other, d[key])
        return d

    du = {}
    try:
        for r in sh.worksheet("New DU").get_all_values()[1:]:
            if len(r) > 8 and str(r[8]).strip():
                du.setdefault(_norm(r[8]), str(r[0]).strip())
    except Exception as e:  # noqa: BLE001
        log(f"(no New DU tab: {type(e).__name__}) — status evidence unavailable")

    sales, weeks = {}, set()
    try:
        for r in sh.worksheet("RAW").get_all_values()[1:]:
            if len(r) > 1 and str(r[1]).strip():
                k = _norm(r[1])
                cnt, last, by_wk = sales.get(k, (0, "", None))
                by_wk = dict(by_wk or {})
                wk = str(r[0]).strip()
                if _cohort_weeks_old(wk) is not None:
                    weeks.add(wk)
                    by_wk[wk] = by_wk.get(wk, 0) + 1
                when = str(r[2]).strip() if len(r) > 2 else ""
                sales[k] = (cnt + 1, _later(last, when), by_wk)
    except Exception as e:  # noqa: BLE001
        log(f"(no RAW tab: {type(e).__name__}) — sales evidence unavailable")

    # most-recent closed week first; _cohort_weeks_old handles the year rollover
    # so 12.27 sorts before 1.3 instead of after it.
    order = sorted(weeks, key=_cohort_weeks_old)
    return _spread(du), _spread(sales), order


def _later(a: str, b: str) -> str:
    """max of two M/D/YYYY strings, compared as dates not text (7/9 vs 7/26)"""
    def p(s):
        for f in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return dt.datetime.strptime(str(s).strip(), f).date()
            except ValueError:
                pass
        return None
    da, db = p(a), p(b)
    if da and db:
        return a if da >= db else b
    return a or b


def _parse_mdy(s):
    """'8/13/2026' -> date, or None. Roll Call dates are typed by hand, so the
    cell can hold anything at all — treat 'unparseable' as 'don't touch it'."""
    for f in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(str(s).strip(), f).date()
        except ValueError:
            pass
    return None


def _tag_date(tag):
    """'8.16' -> date. Same year rule as _cohort_weeks_old, except this one is
    used on the CURRENT week-ending tag, which is in the FUTURE for most of the
    week — so allow a week of lead before deciding the tag means last year."""
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\s*$", str(tag))
    if not m:
        return None
    today = dt.date.today()
    mo, day = int(m.group(1)), int(m.group(2))
    for year in (today.year, today.year - 1):
        try:
            d = dt.date(year, mo, day)
        except ValueError:
            return None
        if d <= today + dt.timedelta(days=7):
            return d
    return None


def _board_day_cols(board, log=_log):
    """Sales Board Monday..Sunday column indexes, in week order, BY HEADER.
    Empty list when the header row isn't found — the 'T' sync then stays off
    rather than reading whatever sits at E..K today."""
    for r in board[:8]:
        low = {str(c).strip().lower(): j for j, c in enumerate(r)}
        if all(d in low for d in BOARD_DAYS):
            return [low[d] for d in BOARD_DAYS]
    log("Sales Board: no Monday..Sunday header row — 'T' termination sync OFF")
    return []


def _board_terminations(board, day_cols, week_end, log=_log):
    """{normalised name: (board row, termination date or None)} for every rep
    whose day cells carry the 'T' termination mark.

    The date is derived from the week-ending tag and WHICH day the run starts
    on — Samantha Rodriguez sold Mon-Wed and went 'T' from Thursday, and
    week_end (Sunday 8.16) minus 3 days is 8/13, exactly her Date Gone. That
    derivation was checked against all six 'T' rows on WE 8.16 and matched
    every one, so it is reported in the log but NOT written (see the block at
    the top of this file).

    A 'T' followed by a SALE is skipped: the mark was wrong or the rep came
    back, and either way it is not a termination to copy into the roll."""
    out = {}
    if not day_cols:
        return out
    for i, r in enumerate(board, start=1):
        name = str(r[1]).strip() if len(r) > 1 else ""
        if not name:
            continue
        marks = [str(r[j]).strip().upper() if len(r) > j else "" for j in day_cols]
        first = next((k for k, m in enumerate(marks) if m == TERM_MARK), None)
        if first is None:
            continue
        rest = marks[first:]
        if any(m not in (TERM_MARK, "") for m in rest):
            log(f"board r{i} {name}: {TERM_MARK!r} followed by {rest!r} — not a "
                "clean termination, leaving the roll alone")
            continue
        when = (week_end - dt.timedelta(days=len(marks) - 1 - first)
                if week_end else None)
        out[_norm(name)] = (i, when)
    return out


def _roll_cols(roll, log=_log):
    """Roll Call's Status / name / Date Gone column indexes, found BY HEADER.

    Returns (cols, resolved). `resolved` False means the header row wasn't
    found: reads fall back to today's positions (cols B/D/M) so the audit still
    runs, but auto-close refuses to write — the repo rule is label lookup over
    indexes, and that matters far more when writing than when reading."""
    for r in roll[:5]:
        hdr = {str(c).strip().lower(): j for j, c in enumerate(r)}
        got = {k: hdr.get(v) for k, v in ROLL_HEADERS.items()}
        if all(v is not None for v in got.values()):
            return got, True
    log("Roll Call header row not found (Status / Roll Call / Date Gone) — "
        "reading at today's positions, auto-close OFF this run")
    return dict(ROLL_FALLBACK), False


def _close_terminations(ws, roll, cols, resolved, write, log=_log,
                        board_terms=None, alias=None):
    """Flip Roll Call Status -> 'Terminated' for anyone already recorded as gone.

    TWO signals, in priority order:
      1. the SALES BOARD 'T' mark (board_terms) — this is where a termination is
         recorded on the day it happens, so it is the one that closes the loop.
      2. a Roll Call Date Gone already set and in the past — the backstop for a
         leaver who never had a board row to mark.

    Mutates `roll` in place for the rows it closes, so the checks further down
    stop counting them as active headcount in the same run — otherwise the very
    rows just closed would come straight back as MISSING FROM BOARD findings.

    Returns (closed, still_open):
      closed     [(row, name, why_closed)] actually written and read back
      still_open [(row, name, date_gone, why)] left alone — `why` is "" when it
                 was simply not this run's job (dry-run / --no-auto-close), and
                 a real explanation when the row was REFUSED. The caller only
                 spells out non-empty reasons, so the plain finding text stays
                 exactly what it always was."""
    st, nm, gn = cols["status"], cols["name"], cols["gone"]
    board_terms, alias = board_terms or {}, alias or {}
    today = dt.date.today()

    def _board_mark(n):
        """The board's 'T' for this roll name, through Name Aliases — the board
        and the roll spell people differently often enough that this is the
        whole reason that tab exists."""
        if n in board_terms:
            return board_terms[n]
        for other in alias.get(n, ()):
            if other in board_terms:
                return board_terms[other]
        return None

    ready, held = [], []
    for ri, r in enumerate(roll, start=1):
        if len(r) <= max(st, nm, gn):
            continue
        status = str(r[st]).strip()
        if status == TERMINATED:
            continue
        who, gone = str(r[nm]).strip(), str(r[gn]).strip()
        if not who:
            continue

        # 1. the board says T
        mark = _board_mark(_norm(who))
        if mark:
            brow, when = mark
            why = f"Sales Board r{brow} marks {TERM_MARK!r}"
            if when:
                why += f" from {when.month}/{when.day}/{when.year}"
                if not gone:
                    why += " (Roll Call Date Gone is still empty)"
            ready.append((ri, who, gone, why))
            continue

        # 2. Date Gone already set. Only from 'Active': a New Start carries one
        #    all week as part of the wash-out flow and rolls over on its own.
        if status != "Active" or not gone:
            continue
        d = _parse_mdy(gone)
        if d is None:
            held.append((ri, who, gone, f"Date Gone {gone!r} isn't a date"))
        elif d > today:
            held.append((ri, who, gone, "Date Gone is in the future — they may "
                                        "still be working their notice"))
        else:
            ready.append((ri, who, gone, f"Date Gone {gone}"))

    if ready and not resolved:
        held += [(ri, w, g, "Roll Call headers moved — refusing to write a "
                  "guessed column") for ri, w, g, _ in ready]
        ready = []
    elif len(ready) > MAX_AUTO_CLOSE:
        held += [(ri, w, g, f"{len(ready)} rows at once is over the "
                  f"{MAX_AUTO_CLOSE}-row auto-close cap — that looks like a "
                  "shifted column, not a leaver batch") for ri, w, g, _ in ready]
        ready = []
    elif ready and not write:
        for ri, w, _g, why in ready:
            log(f"(no write) would close {_a1col(st)}{ri}: {w} -> "
                f"{TERMINATED} ({why})")
        held += [(ri, w, g, "") for ri, w, g, _ in ready]
        ready = []

    if not ready:
        return [], held

    ws.batch_update([{"range": "%s%d" % (_a1col(st), ri),
                      "values": [[TERMINATED]]} for ri, _, _, _ in ready],
                    value_input_option="RAW")

    # Read back before believing it. A silent no-op write here would leave the
    # row Active AND drop its finding — the worst of both.
    back = ws.get_all_values()
    closed, missed = [], []
    for ri, who, gone, why in ready:
        got = (str(back[ri - 1][st]).strip()
               if len(back) >= ri and len(back[ri - 1]) > st else "")
        if got == TERMINATED:
            roll[ri - 1][st] = TERMINATED
            closed.append((ri, who, why))
            log(f"auto-closed {_a1col(st)}{ri}: {who} -> {TERMINATED} ({why})")
        else:
            missed.append((ri, who, gone,
                           f"auto-close wrote {TERMINATED!r} but the cell reads "
                           f"{got!r} — protected range?"))
    return closed, held + missed


def audit(write: bool, log=_log, auto_close: bool = True) -> int:
    from automations.recruiting_report.fill import open_by_key
    sh = open_by_key(SHEET_ID)
    # Sheets TRIMS trailing empty cells, so a rep row that stops at col L comes
    # back 12 wide and every `len(r) > j` guard downstream reads it as "no such
    # column". That silently dropped Kyara (r50) and Tara Ecklof (r51) out of
    # the rep list on 2026-08-06 — which then made the Stations tab report her
    # as "matches nobody on the board" when she is sitting right there on it.
    # Pad to the requested width; a real blank and a trimmed blank are the same
    # thing everywhere in this file.
    def _pad(rows, width=43):          # A1:AQ = 43 columns
        return [list(r) + [""] * (width - len(r)) for r in rows]

    board = _pad(sh.worksheet("Sales Board").get("A1:AQ110"))
    board_form = _pad(sh.worksheet("Sales Board").get(
        "A1:AQ110", value_render_option="FORMULA"))
    roll_ws = sh.worksheet("Roll Call")
    roll = roll_ws.get_all_values()
    # One column resolution for the whole run, by header — the roll's Status /
    # name / Date Gone were three separate hardcoded indexes before, and the
    # auto-close below WRITES one of them.
    roll_cols, roll_hdr_ok = _roll_cols(roll, log=log)
    R_STATUS, R_NAME = roll_cols["status"], roll_cols["name"]
    alias = _alias_map(sh, log=log)

    # rep block = rows >=5 with a name and a week tag, or (for tag-less manual
    # strays like the old 'Nico M' row) a campaign — but never the campaign
    # TOTAL rows, which carry a SUMIFS in col C.
    def _is_rep(i, r):
        if i < 5 or len(r) < 14 or not str(r[1]).strip():
            return False
        cf = str(board_form[i - 1][2]) if len(board_form[i - 1]) > 2 else ""
        if "SUMIFS" in cf.upper():
            return False
        return bool(WK_TAG.match(str(r[13]).strip())
                    or str(r[11]).strip() in ("B2B", "BOX", "JE", "Base"))

    reps = [(i, str(r[1]).strip()) for i, r in enumerate(board, start=1)
            if _is_rep(i, r)]
    if not reps:
        log("no rep rows found — layout changed? aborting without report")
        return 2
    last_rep = max(i for i, _ in reps)

    findings = []

    # 1. off-menu adds: board rep with no roll-call row (script's prefix rule)
    roll_names = _with_aliases(
        {_norm(r[R_NAME]) for r in roll
         if len(r) > R_NAME and str(r[R_NAME]).strip()}, alias)
    for i, name in reps:
        n = _norm(name)
        hit = n in roll_names or any(
            k.startswith(n + " ") or n.startswith(k + " ") for k in roll_names)
        if not hit:
            findings.append(
                f"OFF-MENU ADD? '{name}' (board r{i}) has no Roll Call row — "
                "tenure tag is frozen and stats may miss them. Re-add via "
                "Alphalete menu > Add (or add their Roll Call row).")

    # 1a2. TERMINATION BATCH NOT CLOSED (added 2026-07-31). Roll Call col M
    #      "Date Gone" and col B "Status" must agree: a row with a leave date is
    #      not Active. On 2026-07-31 fifteen rows carried a 7/21-7/30 Date Gone
    #      and were still Active — a whole termination batch where the dates got
    #      entered and the statuses never flipped. That one contradiction
    #      explained EVERY "missing from the board" name the audit was chasing
    #      through sales history, so check it before inferring anything.
    #      Reported as one grouped finding: 15 separate lines would blow past
    #      the per-run cap and bury the typos this tab exists to surface.
    #      Since 2026-08-14 the audit CLOSES these itself rather than asking a
    #      human to flip the same cell every few weeks (see the auto-close block
    #      at the top of this file for exactly how narrow that write is). What
    #      it declines to close still reports here, with the reason.
    def _gone_date(r):
        j = roll_cols["gone"]
        return str(r[j]).strip() if len(r) > j else ""

    board_terms = _board_terminations(
        board, _board_day_cols(board, log=log),
        _tag_date(str(sh.worksheet("Sales Board").acell("B2").value or "")),
        log=log)
    closed, still_open = _close_terminations(
        roll_ws, roll, roll_cols, roll_hdr_ok, write and auto_close, log=log,
        board_terms=board_terms, alias=alias)
    if still_open:
        who = "; ".join(f"{nm} (r{ri}, gone {g})" for ri, nm, g, _ in still_open)
        why = sorted({w for _, _, _, w in still_open if w})
        extra = (" Auto-close left them alone: " + "; ".join(why) + ".") if why else ""
        findings.append(
            f"TERMINATION BATCH NOT CLOSED: {len(still_open)} Roll Call row(s) "
            f"still say Active but carry a Date Gone — {who}. Set col B to "
            "'Terminated'. Until then they count as active headcount and the "
            f"audit reports them as missing from the Sales Board.{extra}")

    # 1b. reverse direction (added 2026-07-20 after Edgar's board row vanished
    #     mid-morning with no alert): every roll person whose status shows
    #     "Active" must have a board row. "New Start" status is exempt (they
    #     join the board at the week roll); Terminated/blank are irrelevant.
    board_names = _with_aliases({_norm(n) for _, n in reps}, alias)
    du_status, sales_by_rep, raw_weeks = _load_activity(sh, log=log, alias=alias)
    # "still selling" = sold in either of the last two CLOSED weeks. One week is
    # too tight (a rep can miss a week and be fine); the current week is never
    # in RAW yet, so it can't be the yardstick.
    recent_weeks, shown_weeks = raw_weeks[:2], raw_weeks[:3]
    # managers sell occasionally but aren't board reps (Carlos, 2026-07-20)
    EXEMPT = {"carlos hidalgo", "nico murrugarra"}
    def _on_board(n):
        return n in board_names or any(
            k.startswith(n + " ") or n.startswith(k + " ") for k in board_names)
    for ri, r in enumerate(roll, start=1):
        if len(r) <= R_NAME or not str(r[R_NAME]).strip():
            continue
        # rows auto-closed a moment ago read 'Terminated' here (roll was mutated
        # in place), so they drop out of this loop exactly as they should
        if str(r[R_STATUS]).strip() != "Active":
            continue
        n = _norm(r[R_NAME])
        if n in EXEMPT:
            continue
        # not scoreboarded here at all -> "missing from the board" is meaningless
        camp = (str(r[ROLL_CAMPAIGN_COL]).strip()
                if len(r) > ROLL_CAMPAIGN_COL else "")
        if camp and camp not in BOARD_CAMPAIGNS:
            log(f"campaign {camp!r} is not on this board — skipping "
                f"{str(r[R_NAME]).strip()} (roll r{ri})")
            continue
        if _on_board(n):
            continue
        if _gone_date(r):
            # already named in the grouped termination finding above; the
            # missing board row is a SYMPTOM of the open status, not a
            # separate problem, and re-listing it here doubled the noise.
            continue
        # Not on the board. WHY matters — this used to fire one identical
        # "deleted by accident?" line for everyone, and on 2026-07-30 that was
        # 8 people of whom only 2 were really missing: 2 had already been closed
        # out in New DU and 4 were still in training. Split by evidence.
        who = str(r[R_NAME]).strip()
        cohort = _cohort_weeks_old(str(r[0]) if r else "")
        du = du_status.get(n, "")
        sales, last_sale, by_wk = sales_by_rep.get(n, (0, "", {}))
        recent = sum(by_wk.get(w, 0) for w in recent_weeks)
        trace = ", ".join("%s=%d" % (w, by_wk.get(w, 0)) for w in shown_weeks)
        if recent:
            findings.append(
                f"MISSING FROM BOARD (SELLING): '{who}' (roll r{ri}) has "
                f"{sales} sale(s) in RAW ({trace}) but no Sales Board row — "
                "the campaign totals SUMIFS over board rows only, so these "
                "sales are missing from the totals. Re-add via Alphalete menu "
                "(their WeekData history re-links by name).")
        elif sales:
            findings.append(
                f"STOPPED SELLING: '{who}' (roll r{ri}) is Active on Roll Call "
                f"with {sales} lifetime sale(s) but none in the last "
                f"{len(recent_weeks)} closed weeks ({trace}) and no board row — "
                f"New DU says {du or 'nothing'}. Confirm they are gone and "
                "close the Roll Call status; do NOT add a board row.")
        elif "not active" in du.lower():
            findings.append(
                f"ROLL CALL STALE: '{who}' (roll r{ri}) is Active on Roll Call "
                f"but New DU says {du!r} and they have no sales — close the "
                "Roll Call status instead of adding a board row.")
        elif cohort is not None and cohort >= 4:
            findings.append(
                f"STALLED TRAINEE: '{who}' (roll r{ri}) is Active, no board row "
                f"and no sales {cohort} weeks after their roll week — New DU "
                f"says {du or 'nothing'}. Chase or close them out.")
        else:
            # recent cohort, still ramping: expected, nothing to do
            log(f"not on board (no sales yet, {cohort}w old, New DU "
                f"{du or 'blank'}): {who}")

    # 2. stats-range drift: summary formulas whose rep-block range ends off
    for i, row in enumerate(board_form, start=1):
        for c in row:
            c = str(c)
            if not c.startswith("="):
                continue
            for m in RANGE_TOK.finditer(c):
                a, b = int(m.group(1)), int(m.group(2))
                # start-drift (top-inserted rows push 5 -> 6/7/...) is just as
                # real as end-drift — 2026-07-20 the whole % box read 7:68
                if 5 <= a <= 20 and 40 <= b <= 100 and (a != 5
                                                        or b != last_rep):
                    findings.append(
                        f"STATS-RANGE DRIFT: formula on board r{i} covers rows "
                        f"{a}:{b} but the rep block is 5:{last_rep} — "
                        "summary counts are excluding reps again. Run "
                        "Alphalete > Realign / Health Check.")
                    break
            else:
                continue
            break
        else:
            continue
        break  # one drift finding is enough — it's systemic

    # 2b. cross-sheet anchor drift (added 2026-07-21): board formulas that
    #     reference BOUNDED Roll Call ranges shift when rows are inserted at
    #     the roll top (the New-Starts box read $B$22:$B$491 and showed 0).
    #     Everything should use full-column refs ('Roll Call'!$B:$B).
    #     Reported as ONE grouped finding that COUNTS the cells and names them
    #     in A1. It used to stop at the first hit ("one finding is enough; they
    #     come in batches") and print it as r71c17 — which read as a single
    #     stray cell. It is the whole New-Starts box: 15 cells, Q71:Q88. Eve
    #     fairly pushed back that nobody inserts roll rows by hand (they come
    #     from the board's own button), so spell out the OTHER half of the risk
    #     that actually applies here — a bounded range also misses rows appended
    #     past its END, and the roll has already grown past row 400.
    BOUNDED_ROLL = re.compile(
        r"'Roll Call'!\$[A-Z]{1,2}\$(\d+):\$?[A-Z]{1,2}\$(\d+)")
    hits, bound_end = [], None
    for i, row in enumerate(board_form, start=1):
        for j, c in enumerate(row):
            c = str(c)
            if not c.startswith("=") or "INDIRECT" in c.upper():
                continue
            m = BOUNDED_ROLL.search(c)
            if m:
                hits.append("%s%d" % (_a1col(j), i))
                end = int(m.group(2))
                bound_end = end if bound_end is None else min(bound_end, end)
    if hits:
        roll_last = max((k for k, r in enumerate(roll, start=1)
                         if len(r) > R_NAME and str(r[R_NAME]).strip()),
                        default=0)
        over = ""
        if bound_end and roll_last > bound_end:
            over = (f" The Roll Call already carries names down to r{roll_last}, "
                    f"past the r{bound_end} these stop at — anyone added below "
                    "that counts as 0 with no error.")
        shown = ", ".join(hits[:8]) + (" …" if len(hits) > 8 else "")
        findings.append(
            f"ROLL-REF DRIFT RISK: {len(hits)} board cell(s) reference a bounded "
            f"Roll Call range ({shown}). Rewrite with full-column refs "
            "('Roll Call'!$B:$B): a bounded range misses rows appended past its "
            f"end AND shifts when rows go in above its start.{over}")

    findings += audit_stations(sh, last_rep, reps, roll, log=log, alias=alias,
                               name_col=R_NAME)

    from automations.shared import run_manifest

    # What auto-close DID has to leave a trace. A run that quietly rewrote four
    # Roll Call statuses and then said "clean" is indistinguishable from a run
    # that found nothing — and the second one is the only one that's true.
    closed_note = ""
    if closed:
        closed_note = (
            f"auto-closed {len(closed)} Roll Call status(es) -> {TERMINATED}: "
            + "; ".join(f"{nm} (roll r{ri} — {why})" for ri, nm, why in closed))
        log(closed_note)

    if not findings:
        log(f"audit clean: {len(reps)} reps checked, block ends r{last_rep}, "
            "stations OK" + (f"; {len(closed)} termination(s) auto-closed"
                             if closed else ""))
        if write:
            # mark_clean() can't carry a note, and the closures are worth one:
            # ok=True keeps the Hub card green and clears any prior finding,
            # exactly as mark_clean would.
            if closed_note:
                run_manifest.write_manifest(REPORT_ID, ok=True, kind="finding",
                                            failed=[], retry_args=[],
                                            note=closed_note)
            else:
                run_manifest.mark_clean(REPORT_ID, kind="finding")
        return 0

    ri = sh.worksheet("Report an Issue")
    # Dedupe on the FULL finding text, matched per-cell against the "What's
    # wrong" column — NOT a 60-char prefix searched inside a joined blob of the
    # last 40 rows. Every finding here opens with a fixed sentence and only
    # names the rep well past char 60, so the prefix could never distinguish two
    # findings of the same KIND: on 2026-08-12 Yesenia Zuniga's "TERMINATION
    # BATCH NOT CLOSED: 1 Roll Call row(s) still say A[ctive]" was swallowed by
    # an 8/4 row about Aaron Tovar that shared that exact opening, so the
    # finding never reached this tab at all while the run still reported
    # "logged to the tab". A swallowed finding reads as a clean day.
    def _dedupe_key(s: str) -> str:
        return " ".join(str(s).split())

    ISSUE_COL = 3                      # col D, "What's wrong" (header row r4)
    existing = {_dedupe_key(r[ISSUE_COL]) for r in ri.get_all_values()[-40:]
                if len(r) > ISSUE_COL and str(r[ISSUE_COL]).strip()}
    new = [f for f in findings if _dedupe_key(f) not in existing]
    for f in findings:
        log(("NEW: " if f in new else "already reported: ") + f)
    if not write:
        log("(dry-run: nothing appended, no manifest written)")
        return 0
    # NOT strftime("%-m/%-d/%Y") — the %- flag is glibc/BSD-only and raises
    # ValueError on Windows, so a real (non-dry-run) audit crashed off the mini.
    _t = dt.date.today()
    today = "%d/%d/%d" % (_t.month, _t.day, _t.year)
    if new:
        ri.append_rows([[today, "board-audit (mini 4am)", "Sales Board", f, ""]
                        for f in new], value_input_option="RAW")
        log(f"appended {len(new)} finding(s) to Report an Issue")

    # FINDINGS ARE THE JOB, NOT A FAILURE. Exit 0 and record the findings in a
    # run-manifest as ok=False so the orchestrator marks this a SOFT INCOMPLETE
    # (with the finding text as its note) instead of a hard exit-1 FAILED that
    # fires the immediate "needs attention" page (Megan/Carlos 2026-07-21, same
    # class as the tableau_screenshots false-fail). No retry_args: a human fixes
    # the board — there is nothing to auto-re-run. A GENUINE crash (scrape/auth/
    # IO) still exits non-zero from main(); a layout break still returns 2 above.
    note = (f"{len(findings)} board data-quality finding(s) logged to the "
            "board's 'Report an Issue' tab: " + " | ".join(f[:140] for f in findings))
    if closed_note:
        note += " | " + closed_note
    run_manifest.write_manifest(REPORT_ID, ok=False, kind="finding",
                                failed=findings, note=note, retry_args=[])
    return 0


def audit_stations(sh, last_rep: int, reps, roll, log=_log, alias=None,
                   name_col: int = 3) -> list[str]:
    """Stations-tab invariants (added 2026-07-19 after the audit that found
    all of these broken at once):
      1. no formula-error cells (#REF!/#N/A/... — e.g. the deleted week-label
         ref that silently emptied the new-start lists for months)
      2. checklist formulas V5/X5/Z5 filter the board from $B$5 (they had
         drifted to B10/B15, hiding the top reps) and W5/Y5/AA5 read roll
         $D$3 and compare $R$2 (not a stale range / literal #REF!)
      3. Rep List FILTERs (F col, all sections + Mon-Fri lineup blocks) start
         at $B$5 — top-inserted board rows push these ranges down over time
      4. Stations week label R2 == Sales Board B2
      5. name hygiene: every human name in the car-ride / skill / lineup /
         OFF-list cells must match a board rep or a roll-call person (catches
         'aracely'-style typos and stale identities that break matching)
    """
    out = []
    stn = sh.worksheet("Stations")
    vals = stn.get("A1:CL135")
    form = stn.get("A1:CL135", value_render_option="FORMULA")

    for i, row in enumerate(vals, start=1):
        for j, c in enumerate(row):
            if any(e in str(c) for e in ("#REF!", "#N/A", "#VALUE!", "#NAME?")):
                out.append(f"STATIONS: error value {c!r} at r{i}c{j+1} — a "
                           "formula reference broke (deleted row/col?).")

    # The checklist / new-start / Rep List cells used to be PINNED here by
    # address (V5,X5,Z5 / W5,Y5,AA5 / F6..F120). On 2026-07-21 Stations gained a
    # column and the whole cluster slid one right (week label R2 -> S2, board
    # filters -> W5/Y5, roll filters -> X5/Z5) while the Rep List moved off col F
    # to G+J entirely. Every assertion then fired against the WRONG cell: four
    # bogus findings every single day, and the col-F loop silently checked empty
    # cells. Locate them BY FORMULA CONTENT instead — same rule as the rest of
    # the repo: labels/shape survive a re-layout, indices don't. (2026-07-30)
    week_board = str(sh.worksheet("Sales Board").acell("B2").value or "").strip()
    week_ref = ""   # local row-2 week cell, e.g. "$S$2"
    row2 = vals[1] if len(vals) > 1 else []
    for j, c in enumerate(row2):
        if week_board and str(c).strip() == week_board:
            week_ref = "$%s$2" % _a1col(j)
            break
    if week_board and not week_ref:
        out.append("STATIONS: no row-2 cell carries the Sales Board week "
                   f"{week_board!r} — the week label moved or went stale.")

    # a roll filter may compare the week either via the local row-2 cell or
    # straight across to 'Sales Board'!$B$2 — both are in use and both are fine.
    week_ok = [w for w in (week_ref, "'Sales Board'!$B$2") if w]
    # a board *list* is a RANGE over the name column ($B$5:$B$56). Matching the
    # bare prefix '$B$' also caught the roll filters' week comparison
    # ('Sales Board'!$B$2), reporting three healthy formulas as drifted.
    BOARD_RANGE = re.compile(r"'Sales Board'!\$B\$(\d+):")
    n_board = n_roll = n_formula = 0
    for i, row in enumerate(form, start=1):
        for j, c in enumerate(row):
            c = str(c)
            if not c.startswith("="):
                continue
            n_formula += 1
            at = "%s%d" % (_a1col(j), i)
            starts = BOARD_RANGE.findall(c)
            if starts:
                n_board += 1
                bad = sorted({s for s in starts if s != "5"})
                if bad:
                    out.append(f"STATIONS: board list {at} starts at row "
                               f"{'/'.join(bad)} instead of 5 — top reps are "
                               "being dropped again.")
            if "'Roll Call'!$D$" in c:
                n_roll += 1
                if "$D$3:" not in c or "#REF" in c:
                    out.append(f"STATIONS: new-start list {at} formula drifted "
                               "(needs the roll $D$3 range; no #REF).")
                elif week_ok and not any(w in c for w in week_ok):
                    out.append(f"STATIONS: new-start list {at} no longer "
                               "compares the current week cell.")
    # a re-layout that WIPES the filters would otherwise read as clean. Only
    # meaningful once the tab has formulas at all (an empty grid is a fixture).
    if n_formula and (not n_board or not n_roll):
        out.append(f"STATIONS: expected board+roll filter formulas, found "
                   f"{n_board} board / {n_roll} roll — the tab was re-laid out "
                   "and these checks are no longer looking at anything.")

    known = _with_aliases(
        {_n(n) for _, n in reps} | {
            _n(r[name_col]) for r in roll
            if len(r) > name_col and str(r[name_col]).strip()},
        alias or {})
    def matches(name):
        n = _n(name)
        return (n in known or any(k.startswith(n + " ") or n.startswith(k + " ")
                                  for k in known))
    # 't extended' is a Territory Status VALUE, not a person: col A of a station
    # block is 'Territory Status' over 'good'/'T Extended' cells, and the two
    # capitalised tokens sail through _person_shaped. Reported every day since
    # the status was first set (2026-08-06).
    LABELS = re.compile(r"^(\d|rep #|rep list|store|territory|t extended|"
                        r"car rides|"
                        r"stations|legend|off|terminated|new starts|monday|"
                        r"tuesday|wednesday|thursday|friday|in a |in both|"
                        r"roadtrip|pitch|closing|transition|running|day 0|"
                        r"pk$|qq|intro |saturday|sunday|early objection|"
                        r"je 9|station )", re.I)
    name_cols = list(range(0, 7)) + list(range(8, 15)) + [89]  # 2026-07-21: +col O (new BOX station col)

    # Only PERSON-SHAPED text is a candidate. The station grid keeps free-text
    # notes in the same columns as names ('Getting Bills/Closing', 'New T given',
    # 'need new t'), and every one of them was being reported as a bad name —
    # three junk entries per day crowding the [:8] cap that real typos need.
    # A person name here is >=2 tokens, all alphabetic, all capitalised.
    def _person_shaped(s):
        toks = s.split()
        if len(toks) < 2:
            return False
        return all(t[:1].isupper() and t.replace("-", "").replace("'", "").isalpha()
                   for t in toks)

    # Every station block repeats a header row ("Territory Leader | Rep #1 |
    # ... | <station names>"), and the station/pitch labels sitting in it are
    # person-shaped: 'Garden Theory' (r28, 2026-08-03), 'Early Objection'
    # (r28, 2026-07-21), 'Intro-Close' (r41). Whitelisting them one at a time
    # in LABELS is a losing game — those labels change whenever the pitch
    # does. Skip the header rows themselves; no rep name lives on one.
    def _header_row(row):
        return bool({str(c).strip().lower() for c in row[:8]}
                    & {"territory leader", "rep #1", "rep list"})

    unknown = set()
    for i, row in enumerate(vals, start=1):
        if i < 4 or _header_row(row):
            continue
        for j in name_cols:
            c = str(row[j]).strip() if len(row) > j else ""
            if (c and _person_shaped(c) and not LABELS.match(c)
                    and not matches(c)):
                unknown.add((c, i))
    # ONE finding per name, name FIRST. These used to be one grouped line, and
    # 'Report an Issue' dedupes on a finding's first 60 chars — which for a
    # grouped line is the boilerplate prefix, identical every time. So the
    # 'Garden Theory' finding of 2026-08-03 was silently swallowed by a
    # 'Early Objection' row from 7/21 still sitting in the last 40 rows: the
    # run logged "1 finding logged" and appended nothing. Leading with the
    # name puts the distinguishing text inside the dedupe key.
    for c, i in sorted(unknown)[:8]:
        out.append(f"STATIONS: {c!r} (r{i}) matches nobody on the board or the "
                   "roll — typo or stale identity.")
    return out


def _n(s) -> str:
    return " ".join(str(s).lower().split())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vantura board daily audit.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print findings; don't write to Report an Issue")
    ap.add_argument("--no-auto-close", action="store_true",
                    help="don't flip Roll Call statuses; just report open "
                         "terminations the way the audit did before 2026-08-14")
    args = ap.parse_args(argv)
    try:
        return audit(write=not args.dry_run,
                     auto_close=not args.no_auto_close)
    except Exception as e:  # noqa: BLE001 — audit must fail loud in the log
        _log(f"AUDIT ERROR: {type(e).__name__}: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
