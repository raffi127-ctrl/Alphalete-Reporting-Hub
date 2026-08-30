"""Per-owner knock boards for the Captainship Report emails — BOTH sections:

  * knock_dispo   (Sun+Mon)  — the Weekly Knock Dispositions board per owner,
                               plus a captainship summary board first.
  * daily_knocks  (every day) — YESTERDAY's combined Total Knocks board per
                               owner (the amber board their metrics threads
                               get daily), plus a daily summary board first
                               with Chan Park's teal comparison row.

Raf's Loom 2026-08-23 brought the weekly section: the SAME per-rep Mon–Sat
board the Sunday Metrics threads get (automations/weekly_knock_dispositions/)
— once per OWNER in the captainship. His Slack ask the same evening added the
daily section ("add the daily knocks to everyones captainship emails … and
have Chan's comparison in there") and gated the weekly one to Sun+Mon
(config.SECTION_DAYS — Monday re-shows Sunday's completed week for
one-on-ones). Nothing here re-derives board logic: pull / compute / render are
the wkd + total_knocks + rashad_metrics modules used as libraries; this module
only decides WHO and hands email_build lists of (title, png-or-None).

WHO comes from the captainship roster on the Org Sales Board — the Sheet
roster is truth. The captain's block is found by its "<NAME> CAPTAIN(SHIP)
TEAM" label via org_sales_board.captainship (never a hardcoded row), against
the SAME tab this report's §1 already screenshots
(captainship_drafts.sales_board._values — one cached read per process, so the
roster costs no extra Sheets quota). Board name cells carry field tags
("(Wk 2)" / "(NC)" / "(BO)"); board_read.clean_name strips the known ones, and
the ownerville / PSS side resolves spelling drift through the ICD alias list
(alias_to_canonical) rather than per-report patches.

SESSION ECONOMY (Raf's captains are 6 of the 12 drafts since 2026-08-23):
capture_sections() does ONE roster lookup and opens ONE ownerville session per
captain, and both sections' pulls run inside that session's owner loop — the
weekly pull only even happens on Sun/Mon. Chan Park's comparison data is
pulled AT MOST ONCE per build: when he's an owner of the captain being built
(his own / Raf's captainship) his loop rows are reused, and either way the
rows land in a per-process cache the other captains' summaries read instead
of re-impersonating him.

The WEEKLY pull goes one step further, through shared/knock_week_cache.py: a
completed Mon–Sat week is frozen, so each (office, week) is pulled from
ownerville at most ONCE across every report and every day. That kills the two
duplications that made this build 1h40m+ on 2026-08-24 — the overlap with
Sunday's weekly_knock_dispositions run (order 36.5, same offices, same week),
and Monday's full re-pull of a week Sunday already fetched. The DAILY pull is
deliberately NOT cached: one day, cheap, and it changes intraday.

Per-owner isolation mirrors weekly_knock_dispositions/run.py: Raf is the
MASTER login (the rhidalgo session IS his office; everyone else is an
impersonation entered and exited around their pull), and one owner failing
records errors["<kind>:<owner>"] and yields (owner, None) — the email shows a
pending note under that owner's sub-heading while the rest still ship. One
owner must never kill a section.

Needs a warm ownerville session (the login is Turnstile-gated, so this can't
run cold on a laptop) — runs on Lucy 1, like the Sunday board itself. The
owner-list extraction, cfg-row building and summary aggregation are pure and
offline-testable; capture_sections() only touches a browser once those are
done.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.shared.report_week import week_ending
# The prefix that tells email_build "the source answered, it had nothing" —
# a grey 'no data available' note instead of the yellow capture-failed one.
from automations.captainship_drafts.email_build import NO_DATA_MARK

# Own Chrome profile — the shared .browser_profile is first-come-first-served
# and a Sunday-morning build overlaps other browser reports. Same escape hatch
# weekly_knock_dispositions/run.py and other_office_knocks use; login comes
# from the shared storage_state, so a fresh dir here needs no new seeding.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_captainship_wkd")

# TeleMapper campaign pin for the pulls (sticky-campaign guard): "3" = RES
# AT&T, right for every captain wired today (rafael + the five fiber captains
# all knock RES AT&T). If a b2b/nds flavor ever joins SECTION_KINDS, its
# owners need "" here (no fiber campaign), same distinction
# weekly_knock_dispositions/offices.py draws.
CAMPAIGN_ID = "3"

# The daily summary board's columns, left→right (Raf's Slack + Megan
# 2026-08-23: "a daily overall and then each ICD broken out below it").
# Display labels only — the data keys stay total_knocks.pull's canonical
# SHEET_COLUMNS names.
#
# "Talk To's per Rep" (Raf, 2026-08-25) sits right after the Total Talk To it
# divides: the ICD rows aggregate different-sized rosters, so the raw total
# says more about headcount than about the day. Per-rep is the comparable
# number — and it is only meaningful HERE, on the summary; the per-owner
# boards below already have one row per rep.
# "Total Apps" (Raf, 2026-08-26) closes the funnel the row already opens —
# leads knocked, knocks, talk-tos, then what came out of them. It is the ICD's
# apps for THAT DAY from the Tableau PRODUCT SALES SUMMARY (every product
# type), the same count and the same source as the weekly board's Total Apps
# and as the per-owner board right below this one, so the two never invite the
# question of which products are in. Blank — never 0 — when the crosstab
# didn't come down: a zero here reads as an ICD that sold nothing.
# "Average App per Rep" (Eve, 2026-08-27) sits right after the Total Apps it
# divides, for the same reason Talk To's per Rep sits after Total Talk To: an
# ICD row aggregates a whole roster, so the raw app count reads as headcount
# unless the comparable per-rep figure is next to it. Same divisor as Talk
# To's per Rep — the reps who WORKED that day, i.e. the rows this board got
# from ownerville — so the two per-rep columns are read against the same
# denominator. Blank (never 0) whenever Total Apps is blank.
# Column names, and the two derived ones added 2026-08-28 (Eve), are the SAME
# strings the per-owner boards under this one use (total_knocks.render) — the
# two land on one email in front of one reader, and a column that means the
# same thing has to be spelled the same way on both.
DAILY_SUMMARY_HEADERS = [
    "ICD", "Total # of Reps Knocking", "Total Leads Knocked", "Total Knocks",
    "Total Talk To", "% Talk To's per Knocks",
    "Talk To's per Rep", "Total Apps", "Average App per Rep",
    "Avg First Knock", "Avg Last Knock", "Gaps", "Total Gaps",
]

# Chan Park's yesterday rows, cached PER PROCESS keyed by the target date's
# ISO string. Six captains build in one run.py process; Chan's teal
# comparison row rides every daily summary, and this cache is what keeps
# that at ONE ownerville pull per build instead of one per captain. Failures
# are deliberately NOT cached, so a later captain's build retries.
_CHAN_DAILY_CACHE: Dict[str, list] = {}

# The same economy for Chan's WEEKLY rows, keyed by the Saturday. Cheaper than
# the daily one usually is: the shared week cache (shared/knock_week_cache.py)
# already holds most completed weeks, so this only ever pays for a live pull
# when captainship_drafts is the first report of the week to want him — and
# then it PUTS what it pulled, so Sunday's weekly_knock_dispositions run reads
# it free. Failures are not cached, so a later captain retries.
_CHAN_WEEKLY_CACHE: Dict[str, tuple] = {}


# An owner on the captainship roster who has NO ownerville office at all —
# not a name-spelling drift an alias could fix (Megan checked Office Access
# on Raf's login for Michael Murphy, 2026-08-24: absent under his name, his
# nickname and his company). There is nothing to pull for that person, so
# the section must say ACCESS GAP, not show what reads as a failed run —
# the standing rule that a review email names the owners we can't scrape.
# Matched on the impersonation failure text rather than a hardcoded name
# list, so the next owner in this position is covered without a patch.
_NO_OFFICE_MARKERS = ("not found in ownerville", "couldn't impersonate",
                      "couldnt impersonate")


def is_access_gap(exc) -> bool:
    """True when this owner's pull failed because the reporting account has no
    Office Access to their office — a permission, not a run failure."""
    return any(m in str(exc).lower() for m in _NO_OFFICE_MARKERS)


def _owner_error_note(exc) -> str:
    """The errors[] note for a failed owner pull — an ACCESS GAP reads as
    one, anything else keeps its exception text for debugging.

    The access-gap note carries NO_DATA_MARK, so it renders as the GREY
    "no data available" box instead of the yellow pending one. That is the
    whole reason these sections can ship while the Office Access requests are
    still being granted (Eve 2026-08-25): the yellow box carries PENDING_MARK,
    and run.py's send guard refuses to mail ANY report that still shows one —
    so a single un-granted ICD used to hold its captain's entire email, and
    with sixteen of them, five captains got no email at all.

    Grey is the honest colour here, not a downgrade: the run did not fail and
    re-running fixes nothing. Someone has to grant Office Access on the
    reporting account. The owner still appears in the email under their own
    sub-heading with the reason spelled out, which is the standing rule — an
    office we cannot see must be VISIBLE, never silently dropped — and the
    summary board's "(N of M ICDs)" label says how many are missing from the
    totals."""
    text = f"{type(exc).__name__}: {str(exc)[:200]}"
    if any(m in str(exc).lower() for m in _NO_OFFICE_MARKERS):
        return (NO_DATA_MARK + "no ownerville office access for this owner on "
                "the reporting account — nothing can be pulled until access "
                "is granted (not a failed run; re-running changes nothing)")
    return text


def week_window(today: dt.date) -> Tuple[dt.date, dt.date, dt.date]:
    """(monday, saturday, we_sunday) — the completed Mon–Sat week for a run on
    `today`. Same math as weekly_knock_dispositions.run._week: the Sunday email
    build reports the week that just ended, and a Monday catch-up rerun still
    resolves to that same week, not the empty new one. This is also what makes
    the SECTION_DAYS Sun+Mon gate coherent: Monday's boards re-show Sunday's
    week (Raf: "Monday should re duplicate sundays post")."""
    sunday = week_ending(today - dt.timedelta(days=1))
    return sunday - dt.timedelta(days=6), sunday - dt.timedelta(days=1), sunday


def daily_target(today: dt.date) -> dt.date:
    """The day the daily_knocks section covers: YESTERDAY — the same today-1
    anchor every other section of this draft uses (email_build.reported_date),
    so a --date override moves the whole draft together. On the scheduled
    Lucy 1 run this equals yesterday-Central (the machine runs on Central
    time), matching the daily metrics-thread boards."""
    return today - dt.timedelta(days=1)


def _slug(name: str) -> str:
    """Filesystem-safe per-owner dir name (each board render's filename is
    fixed per date, so each owner renders into their OWN subdir)."""
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def owner_names(captain_key: str, grid: Optional[List[List[str]]] = None
                ) -> List[str]:
    """The owner names in `captain_key`'s captainship block on the Org Sales
    Board, in board order (leaderboard first, then any daily-only stragglers),
    field tags stripped, de-duped case-insensitively.

    `grid` is injectable for offline tests; None reads the live tab through
    sales_board's process cache. Lazy imports so importing THIS module stays
    light (config.py's _fiber_boxes rationale — a mid-refactor dependency must
    not take the whole drafts run down at import time)."""
    from automations.captainship_drafts import sales_board as sb
    from automations.org_sales_board import captainship as cap
    from automations.icd_sales_board.board_read import clean_name
    if grid is None:
        grid = sb._values()
    token = sb.CAPTAIN_TOKEN[captain_key]
    # discover_captainships reads every block title off the board; match ours
    # by the same captain token §1 anchors on (tolerant containment, like
    # sales_board._is_ps_header — "Raf's" and "RAF'S CAPTAINSHIP" both hit).
    title = next((t for t, _hint in cap.discover_captainships(grid)
                  if token in cap._cap_key(t).lower()), None)
    if title is None:
        raise RuntimeError(
            f"no captainship block for {captain_key!r} (token {token!r}) "
            "found on the Org Sales Board — the roster is the block's "
            "leaderboard, so without it there are no owners to board.")
    anchor = cap.find_captainship(grid, title)
    names: List[str] = []
    seen: set = set()
    # Leaderboard THEN daily: same people normally, but a rep present in only
    # one table still gets a board rather than silently dropping.
    for _row, raw in list(anchor.leaderboard) + list(anchor.daily):
        name, _tags = clean_name(raw)          # "Cody Cannon (Wk 2)" → "Cody Cannon"
        key = " ".join(name.lower().split())
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def owner_cfgs(names: List[str], aliases_raw: Dict[str, list]
               ) -> List[Tuple[str, dict]]:
    """[(display_name, pull cfg), …] — the cfg rows pull_office_week takes.

    display_name keeps the BOARD's spelling (that's what the email sub-heading
    and the image title show — the name the captainship knows the owner by);
    the cfg's "name" is the alias-resolved canonical, which is what the
    ownerville impersonation search and the PSS owner slice both match on.

    Raf is the one MASTER row (the login session IS his office — no
    impersonation); everyone else impersonates. Detected by canonical name
    against the wkd RAF row so the two reports can never disagree on who the
    master is. Pure — offline-testable."""
    from automations.focus_office_att.aliases import alias_to_canonical, _norm_name
    from automations.weekly_knock_dispositions.offices import RAF as _RAF
    out: List[Tuple[str, dict]] = []
    for display in names:
        try:
            canonical = alias_to_canonical(display, aliases_raw)
        except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no boards
            canonical = display
        is_master = _norm_name(canonical) == _norm_name(_RAF["name"])
        out.append((display, {
            "name": canonical,
            "ov": "master" if is_master else "impersonate",
            "campaign_id": CAMPAIGN_ID,
            "pss_owner": canonical,
        }))
    return out


# ---------------------------------------------------------------------------
# daily_knocks — YESTERDAY's boards (Raf's Slack ask, 2026-08-23 evening)
# ---------------------------------------------------------------------------

def _daily_rows_for_owner(page, cfg: dict, aliases_raw, target: dt.date
                          ) -> list:
    """One owner's yesterday knock rows (records keyed by total_knocks.pull
    SHEET_COLUMNS), on the already-open ownerville page.

    Impersonated owners ride rashad_metrics.knocks_pull.pull_office_on_page —
    the exact scrape the daily metrics-thread boards use (impersonate, pin
    campaign, Disposition + Time Tracker merged by badge id, exit
    impersonation). That helper impersonates UNCONDITIONALLY, so the MASTER
    (Raf — the rhidalgo login IS his office) can't go through it and takes
    knocks_pull.pull_master_on_page instead: the same scrape minus the office
    switch. Both live in knocks_pull now, so on-demand `/knocks` routes the
    master exactly the way this build does — the same master-vs-impersonate
    routing owner_cfgs decided for the weekly pull."""
    from automations.rashad_metrics import knocks_pull as KP
    if cfg.get("ov") == "master":
        # Was inline here; now knocks_pull.pull_master_on_page, so the
        # on-demand /knocks path runs the identical master scrape.
        return KP.pull_master_on_page(page, target)
    _t, rows = KP.pull_office_on_page(page, cfg["name"], aliases_raw, target)
    return rows


def daily_apps_for_board(rows: list, office_apps: "dict | None"):
    """(rows to RENDER, {ov rep name: apps}, office total) for one office's
    daily board — Raf's "Total Apps" column, 2026-08-26.

    The two sides spell reps differently (ownerville vs Tableau), so the
    match runs through the weekly board's `match_apps` — the same matcher,
    so a rep who lines up on the weekly board lines up here. A rep who SOLD
    but has no knock row is appended as a row of their own with the knock
    cells blank, exactly as the weekly board does: the column has to add up
    to the office total, and an app that belongs to nobody visible is how a
    reader stops trusting the number.

    office_apps=None (crosstab never came down) returns the rows untouched
    and None, which leaves the column off that board entirely. Pure —
    offline-testable."""
    from automations.total_knocks import pull as knocks
    from automations.weekly_knock_dispositions import board as B
    if office_apps is None:
        return rows, None, None
    ov_names = [str(r.get(knocks.COL_REP, "") or "") for r in rows]
    matched, consumed = B.match_apps(ov_names, office_apps)
    out_rows = list(rows)
    for rep, n in sorted(office_apps.items()):
        if B._norm_name(rep) in consumed or not n:
            continue
        name = B._display_name(rep)
        out_rows.append({knocks.COL_REP: name})
        matched[name] = n
    return out_rows, matched, sum(matched.values())


def daily_summary_row(label: str, rows: list,
                      apps: Optional[int] = None) -> List[str]:
    """One daily-summary board row aggregating `rows` (one owner's reps,
    records keyed by total_knocks.pull SHEET_COLUMNS): the count columns SUM;
    Talk To's per Rep and Average App per Rep divide by the row's reps
    KNOCKING (>= render.KNOCKING_MIN_KNOCKS doors), the count the row prints;
    First/Last Knock are the AVERAGE of the reps' times (the wkd board's
    _avg_knock — reps with a parsable time only); Gaps sums the gap counts;
    Total Gaps sums the minutes and formats 'Xh Ym' like the daily board
    (total_knocks.render._fmt_hm); `apps` is that row's app count, passed in
    because it comes from Tableau, not from these ownerville rows — None
    leaves the cell blank. Pure — offline-testable."""
    from automations.weekly_knock_dispositions.board import _avg_knock
    from automations.total_knocks import pull as knocks
    from automations.total_knocks.render import _fmt_hm

    def _i(rec: dict, col: str) -> int:
        v = rec.get(col)
        return v if isinstance(v, int) else knocks._to_int(str(v or ""))

    from automations.total_knocks.render import (
        KNOCKING_MIN_KNOCKS, _pct)

    talk_to = sum(_i(r, knocks.COL_TOTAL_TALK_TO) for r in rows)
    total_knocks = sum(_i(r, knocks.COL_TOTAL_KNOCKS) for r in rows)
    # Reps KNOCKING: 20 knocks or fewer is a walk-on, not a day of doors (Eve
    # 2026-08-28). It is the ICD's head count AND the divisor of both per-rep
    # columns further right (Rafael approved 2026-08-28) — one number, printed
    # on the same row it divides, so a reader can check the arithmetic without
    # being told what the denominator was. Same rule and same threshold as the
    # per-owner boards' `render._knockers`; the two boards must agree on an
    # office to the decimal.
    knocking = sum(1 for r in rows
                   if _i(r, knocks.COL_TOTAL_KNOCKS) >= KNOCKING_MIN_KNOCKS)
    return [
        label,
        str(knocking),
        str(sum(_i(r, knocks.COL_TOTAL_LEADS_KNOCKED) for r in rows)),
        str(total_knocks),
        str(talk_to),
        # The rate the ICD turned doors into conversations — summed talk-tos
        # over summed knocks, never an average of the reps' rates.
        _pct(talk_to, total_knocks),
        # BLANK, never "0", when nobody cleared the bar: on a washed-out day
        # the ICD still has talk-to's, and a 0.0 beside them says its reps had
        # none. Nothing to divide by is not a zero.
        (f"{talk_to / knocking:.1f}" if knocking else ""),
        # None = the PSS crosstab never came down for this ICD; blank says so.
        ("" if apps is None else str(apps)),
        # Apps per rep — blank when there is nothing to divide (no apps
        # pulled, or nobody knocking), never a 0 the ICD didn't earn.
        ("" if apps is None or not knocking else f"{apps / knocking:.1f}"),
        _avg_knock(rows, knocks.COL_FIRST_KNOCK),
        _avg_knock(rows, knocks.COL_LAST_KNOCK),
        str(sum(_i(r, knocks.COL_GAPS) for r in rows)),
        _fmt_hm(str(sum(_i(r, knocks.COL_TOTAL_GAPS) for r in rows))),
    ]


def totals_label(n_covered: int, roster_n: Optional[int]) -> str:
    """The captainship TOTALS row's name — "(N of M ICDs)" whenever the row
    sums fewer offices than the captainship has.

    Why the count rides the label instead of a footnote (Eve 2026-08-25): the
    board is a PNG that gets forwarded on its own, and a totals row that says
    plain "CAPTAINSHIP TOTALS" while sixteen offices are still waiting on
    Office Access reads as the captainship's real number. It is not — it is
    the number for the offices we can see. Anyone comparing two captainships,
    or this week against last, has to be told that, on the image itself.

    n_covered counts the offices the totals actually SPEAK FOR, which is
    not the same as the offices that contributed rows: an ICD that answered
    with a real zero — nobody knocked — is fully represented by the total and
    must NOT read as missing, or every quiet Sunday would look like an access
    problem. Only an office we could not reach at all comes off the count.

    roster_n=None (or a complete pull) keeps the bare label, so Rafael's
    boards — 13 of 13 accessible — look exactly as they always have. Pure."""
    if roster_n and n_covered < roster_n:
        return f"CAPTAINSHIP TOTALS ({n_covered} of {roster_n} ICDs)"
    return "CAPTAINSHIP TOTALS"


def daily_summary_table(captured: list, chan_rows: Optional[list] = None,
                        roster_n: Optional[int] = None,
                        n_covered: Optional[int] = None,
                        chan_apps: Optional[int] = None
                        ) -> Tuple[List[List[str]], list]:
    """The daily summary board's rows: one row per ICD of THIS captainship in
    roster order, then the trailing highlight block — a teal CHAN PARK
    comparison row (Raf: "have Chan's comparison in there"; teal =
    weekly_knock_dispositions' COMPARE_ROW_BG, so a guest row reads the same
    everywhere) and the plum CAPTAINSHIP TOTALS row.

    `captured` is [(display, cfg, rows), …] per owner that produced daily
    rows — or [(display, cfg, rows, apps), …], where apps is that ICD's app
    count for the day (None when the PSS crosstab failed). A 3-tuple still
    works and renders the Total Apps column blank, which is what an older
    on-disk capture reused from a build before this column existed is. `chan_rows` is Chan Park's rep rows — when None, they're looked up
    IN `captured` (his own / Raf's captainship, where he is an owner); a
    captain whose roster doesn't carry him passes the extra data-only pull
    in. Either way the teal row just re-aggregates his reps, and TOTALS sums
    only the captainship's own owners (a data-only Chan is not one of them).
    No Chan data at all = no teal row, never a crash.

    Returns (table_rows, trailing_bgs) — trailing_bgs colors the trailing
    highlight block for _draw's total_row_bgs, teal row included, so its
    length is also the highlight_last_row count. Pure — offline-testable."""
    from automations.weekly_knock_dispositions.board import COMPARE_ROW_BG
    from automations.total_knocks.render import THEME_AMBER
    from automations.weekly_knock_dispositions.offices import CHAN as _CHAN
    from automations.focus_office_att.aliases import _norm_name
    def _apps_of(item) -> Optional[int]:
        return item[3] if len(item) > 3 else None

    body = [daily_summary_row(it[0], it[2], _apps_of(it)) for it in captured]
    if chan_rows is None:
        chan_norm = _norm_name(_CHAN["name"])
        chan_rows = next((it[2] for it in captured
                          if _norm_name(it[1].get("name", "")) == chan_norm),
                         None)
    tail: List[List[str]] = []
    bgs: list = []
    if chan_rows:
        tail.append(daily_summary_row("CHAN PARK", chan_rows, chan_apps))
        bgs.append(COMPARE_ROW_BG)
    all_rows = [rec for it in captured for rec in it[2]]
    # TOTALS' apps = the sum of the ICD rows above it, so the column always
    # adds up on the image. All-blank (nothing pulled) stays blank rather
    # than becoming a 0 the captainship didn't earn.
    each = [_apps_of(it) for it in captured]
    tot_apps = (sum(a for a in each if a is not None)
                if any(a is not None for a in each) else None)
    # n_covered counts the ICDs that ANSWERED, zeros included; `captured`
    # only holds the ones with rows, so defaulting to it would flag a quiet
    # office as unreachable. See totals_label.
    covered = len(captured) if n_covered is None else n_covered
    tail.append(daily_summary_row(totals_label(covered, roster_n), all_rows,
                                  tot_apps))
    # Burnt orange, the SAME totals colour the per-owner daily boards use —
    # this board is the daily family's summary, not the weekly's.
    bgs.append(THEME_AMBER["total_bg"])
    return body + tail, bgs


def render_daily_summary(captured: list, target: dt.date, out_dir,
                         chan_rows: Optional[list] = None,
                         roster_n: Optional[int] = None,
                         n_covered: Optional[int] = None,
                         chan_apps: Optional[int] = None) -> Path:
    """Draw the daily summary board PNG — AMBER theme, the same one the
    per-owner DAILY TOTAL KNOCKS boards right below it use.

    It was plum until 2026-08-27, matched to the weekly captainship summary so
    the two summaries read as siblings. Eve: that is the confusing pairing, not
    the helpful one. On Sunday and Monday the weekly boards land in the same
    email, and colour is what a reader sorts them by at a glance — plum = the
    WEEK, amber = the DAY. Same reason the per-owner boards carry the
    "DAILY " title prefix: two boards that look alike invite reading a day's
    number as the week's.

    The trailing block (teal Chan row + amber TOTALS) highlights via
    total_row_bgs; note _draw only paints total_row_bgs INSIDE the highlighted
    trailing block, so highlight_last_row must count the teal row too — not
    just the last row."""
    from automations.total_knocks import render as knocks_render
    from automations.total_knocks.render import THEME_AMBER
    table, bgs = daily_summary_table(captured, chan_rows, roster_n,
                                     n_covered, chan_apps)
    # Same date line, weekday and all, as the per-owner boards under it.
    date_s = knocks_render._title_date(target)
    # The ICDs are numbered the way each owner's board numbers its reps (Eve,
    # 2026-08-28). Only the ICD rows: the trailing block is a comparison office
    # and the captainship TOTALS, and a number on those would read as one more
    # ICD in the list. `bgs` is exactly that block, so its length is the count.
    cols = list(DAILY_SUMMARY_HEADERS)
    disp = list(cols)
    knocks_render.number_rows(cols, disp, table, count=len(table) - len(bgs))
    return knocks_render._draw(
        disp, table,
        f"DAILY KNOCKS SUMMARY — {date_s}", THEME_AMBER,
        Path(out_dir) / f"daily_knocks_summary_{target.isoformat()}.png",
        name_col=1, wrap_headers=True,
        highlight_last_row=len(bgs), total_row_bgs=bgs)


def compare_totals_for(display: str, chan_rows, chan_apps=None) -> list:
    """The `extra_totals` a per-owner daily board carries — the teal CHAN PARK
    TOTAL line above the office's own (Raf 2026-08-23, "add Chan's totals above
    ours daily"; Eve 2026-08-25 asked for it on EVERY owner's board in the
    Captainship Reports, the way the metrics-thread and /knocks boards already
    have it).

    Empty for Chan's OWN board: a comparison line identical to the TOTAL right
    under it is noise, and worse, it reads like the office was counted twice.
    Empty when the comparison pull failed too — the board goes out without the
    line rather than with a wrong one."""
    from automations.focus_office_att.aliases import _norm_name
    from automations.weekly_knock_dispositions.offices import CHAN as _CHAN
    if not chan_rows:
        return []
    if _norm_name(display) == _norm_name(_CHAN["name"]):
        return []
    # Third element = Chan's own {rep: apps}; render_total_knocks shows only
    # its SUM, on his comparison line. Left OFF when his apps weren't pulled,
    # so the entry keeps the plain (name, rows) shape every other board that
    # never asked for apps passes — and his cell stays blank rather than
    # showing a 0 he didn't earn.
    if chan_apps is None:
        return [(_CHAN["name"], chan_rows)]
    return [(_CHAN["name"], chan_rows, chan_apps)]


def _chan_weekly_rows(page, captured_weekly: list, aliases_raw,
                      monday: dt.date, saturday: dt.date, *, logfn=print):
    """Chan Park's rows + dispo columns for the WEEK — the captainship
    summary's teal comparison line (Raf 2026-08-30: "make sure Chan's numbers
    are at the top of this weekly disposition summary report. For mine and
    everyone else's").

    Cheapest source first, same ladder as the daily helper: (1) this captain's
    own weekly loop, when Chan is one of its owners; (2) the per-process cache
    an earlier captain in this build filled; (3) the shared week cache, which
    on Monday is always a hit because Sunday paid; (4) ONE data-only
    pull_office_week inside the already-open session, whose result is written
    BACK to the shared cache. None = unavailable, and the summary just goes
    out without the teal row — never a crash, never a fabricated line."""
    from automations.focus_office_att.aliases import (
        _norm_name, alias_to_canonical)
    from automations.weekly_knock_dispositions import pull as P
    from automations.weekly_knock_dispositions.offices import CHAN as _CHAN
    from automations.shared import knock_week_cache as KWC
    key = saturday.isoformat()
    chan_norm = _norm_name(_CHAN["name"])
    for _d, rows, _a, cols in captured_weekly:
        if _norm_name(_d) == chan_norm and rows:
            _CHAN_WEEKLY_CACHE[key] = (rows, cols)
            return rows, cols
    if key in _CHAN_WEEKLY_CACHE:
        return _CHAN_WEEKLY_CACHE[key]
    try:
        canonical = alias_to_canonical(_CHAN["name"], aliases_raw)
    except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no row
        canonical = _CHAN["name"]
    hit = KWC.get(_CHAN["name"], saturday, aliases=aliases_raw)
    if hit is not None:
        _CHAN_WEEKLY_CACHE[key] = hit
        logfn("    Chan weekly comparison: from week cache")
        return hit
    if page is None:
        return None
    try:
        logfn(f"    Chan weekly comparison: extra data-only pull "
              f"({canonical})")
        # _CHAN as-is: pull_office_week resolves the spelling itself through
        # _find_owner_and_impersonate(name, aliases_raw), exactly as
        # weekly_knock_dispositions/run.py hands it over.
        rows, cols = P.pull_office_week(page, _CHAN, aliases_raw,
                                        monday, saturday)
        if not rows:
            return None
        KWC.put(_CHAN["name"], saturday, rows, cols, aliases=aliases_raw)
        _CHAN_WEEKLY_CACHE[key] = (rows, cols)
        return rows, cols
    except Exception as e:  # noqa: BLE001 — a nicety, never the section
        logfn(f"    ⚠ Chan weekly comparison pull failed ({type(e).__name__}: "
              f"{str(e)[:120]}) — summary omits the teal row")
        return None


def _chan_daily_rows(page, captured_daily: list, aliases_raw,
                     target: dt.date, *, logfn=print) -> Optional[list]:
    """Chan Park's yesterday rows for the summary's teal comparison row —
    cheapest source first: (1) this captain's own loop, when Chan is one of
    its owners; (2) the per-process cache, filled by an earlier captain in
    the same build; (3) ONE extra data-only impersonated pull inside the
    already-open session. (1) and (3) both fill the cache, which is what
    holds the whole build to at most one Chan pull. None = unavailable — the
    summary simply omits the teal row (logged, never fatal, never cached so
    the next captain retries)."""
    from automations.focus_office_att.aliases import (
        _norm_name, alias_to_canonical)
    from automations.weekly_knock_dispositions.offices import CHAN as _CHAN
    key = target.isoformat()
    chan_norm = _norm_name(_CHAN["name"])
    for _d, cfg, rows in captured_daily:
        if _norm_name(cfg.get("name", "")) == chan_norm:
            _CHAN_DAILY_CACHE[key] = rows
            return rows
    if key in _CHAN_DAILY_CACHE:
        return _CHAN_DAILY_CACHE[key]
    try:
        from automations.rashad_metrics import knocks_pull as KP
        try:
            canonical = alias_to_canonical(_CHAN["name"], aliases_raw)
        except Exception:  # noqa: BLE001 — a broken alias sheet ≠ no row
            canonical = _CHAN["name"]
        logfn(f"    Chan comparison: extra data-only pull ({canonical})")
        _t, rows = KP.pull_office_on_page(page, canonical, aliases_raw,
                                          target)
        _CHAN_DAILY_CACHE[key] = rows
        return rows
    except Exception as e:  # noqa: BLE001 — a nicety, never the section
        logfn(f"    ⚠ Chan comparison pull failed ({type(e).__name__}: "
              f"{str(e)[:120]}) — daily summary omits the teal row")
        return None


# ---------------------------------------------------------------------------
# capture — both sections, one roster lookup, one ownerville session
# ---------------------------------------------------------------------------

class _ReusedDaily(Exception):
    """This owner's daily board came off disk — skip the pull, keep the loop."""


def _owner_png(root: Path, display: str, stem: str, stamp: dt.date) -> Path:
    """Where one owner's board for `stamp` lands — the SAME path the render
    helpers write to, derived once so reuse and capture can never disagree."""
    return Path(root) / _slug(display) / f"{stem}_{stamp.isoformat()}.png"


def _owner_rows_file(png: Path) -> Path:
    """The pull's rows, parked next to the board they drew.

    The PNG alone is enough to re-show one owner's board, but NOT enough to
    rebuild the captainship SUMMARY, which aggregates every owner's rows. Kept
    as its own file so an older run's PNG (no sidecar) still gets reused — the
    summary just says so instead of quietly dropping that ICD."""
    return png.parent / f"rows_{png.stem}.json"


def _read_rows(png: Path):
    try:
        f = _owner_rows_file(png)
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception:  # noqa: BLE001 — a bad sidecar = pull-quality summary
        return None


def _write_rows(png: Path, payload) -> None:
    try:
        _owner_rows_file(png).write_text(json.dumps(payload), encoding="utf-8")
    except Exception:  # noqa: BLE001 — best effort, never fails a capture
        pass


def _manifest_path(render_dir, captain_key: str, target: dt.date,
                   saturday: dt.date) -> Path:
    """One file per captain per DAY — the daily target and the week's Saturday
    both ride the name, so yesterday's manifest can never satisfy today's run
    and a Monday's can never satisfy a Tuesday's."""
    return (Path(render_dir) / f"knocks_manifest_{captain_key}_"
            f"{target.isoformat()}_{saturday.isoformat()}.json")


def _save_manifest(render_dir, captain_key: str, target: dt.date,
                   saturday: dt.date, wanted, out: dict, errors: dict,
                   logfn=print) -> None:
    """Record what this pull produced so a later build today can skip it.

    Best-effort: a manifest that fails to write costs a re-pull, never a
    wrong board."""
    try:
        payload = {
            "kinds": sorted(wanted),
            "items": {k: [[lab, (str(p) if p else None)]
                          for lab, p in out.get(k, [])] for k in wanted},
            "errors": {k: v for k, v in errors.items()
                       if k.split(":", 1)[0] in wanted},
        }
        p = _manifest_path(render_dir, captain_key, target, saturday)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logfn(f"    ⚠ knocks manifest not saved: {type(e).__name__}: {e}")


def _load_manifest(render_dir, captain_key: str, target: dt.date,
                   saturday: dt.date, wanted):
    """Today's capture for this captain, or None to pull it fresh.

    Refuses the manifest unless it covers EVERY kind this run wants (a
    daily-only Tuesday capture must not satisfy Monday's weekly section) and
    every PNG it names is still on disk — /tmp is swept, and half a section is
    worse than a slow one."""
    p = _manifest_path(render_dir, captain_key, target, saturday)
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if not set(wanted).issubset(set(data.get("kinds") or [])):
            return None
        items = {}
        for kind in wanted:
            pairs = []
            for lab, path in data["items"][kind]:
                if path is None:
                    pairs.append((lab, None))
                    continue
                png = Path(path)
                if not png.exists() or png.stat().st_size == 0:
                    return None
                pairs.append((lab, png))
            items[kind] = pairs
        return {"items": items, "errors": data.get("errors") or {}}
    except Exception:  # noqa: BLE001 — an unreadable manifest = pull fresh
        return None


def capture_sections(captain, today: dt.date, render_dir, *,
                     want_daily: bool = True, want_weekly: bool = True,
                     reuse: bool = True,
                     logfn=print, errors: Optional[dict] = None) -> dict:
    """Both knock sections' images for `captain`, sharing ONE roster lookup
    and ONE ownerville session (run.py passes want_* from sections_on(today),
    so the weekly work simply doesn't happen Tue–Sat).

    Returns {"daily_knocks": […], "knock_dispo": […]} — each the
    [(title, png_path_or_None), …] shape email_build renders, summary board
    first, then the owners in roster order (empty when not wanted). A None
    path means that board could not be built; the reason sits in
    errors["<kind>:<title>"] and renders as that item's pending note. A
    roster/session-level failure records errors["<kind>"] for each wanted
    kind instead. Never raises for a single owner — mirror of the wkd
    runner's per-office try/except."""
    errors = {} if errors is None else errors
    out = {"daily_knocks": [], "knock_dispo": []}
    if not (want_daily or want_weekly):
        return out
    wanted = [k for k, w in (("daily_knocks", want_daily),
                             ("knock_dispo", want_weekly)) if w]

    monday, saturday, we_sunday = week_window(today)
    target = daily_target(today)
    if want_daily:
        logfn(f"  daily knocks boards: {target} ({captain.key})")
    if want_weekly:
        logfn(f"  knock dispo boards: {monday} → {saturday} ({captain.key})")

    try:
        names = owner_names(captain.key)
    except Exception as e:  # noqa: BLE001 — no roster = no section, not no draft
        logfn(f"  ⚠ captainship roster lookup failed: {type(e).__name__}: {e}")
        for k in wanted:
            errors[k] = f"{type(e).__name__}: {e}"
        return out
    if not names:
        for k in wanted:
            errors[k] = ("the captainship's Sales Board block has no "
                         "owner rows")
        return out
    logfn(f"    {len(names)} owner(s): {', '.join(names)}")

    # Already captured today? Then this whole function is a no-op. THE reason
    # this exists (Eve 2026-08-24): the pull is ~2h — one ownerville session,
    # every ICD impersonated, scraped and un-impersonated in single file,
    # because impersonation is per-account server state and cannot be
    # parallelised. On 2026-08-24 that 2h sat between Eve and every other job
    # on the mini, and the day's second build paid it all over again for
    # images that were already on disk.
    #
    # The manifest is what makes reuse honest: labels (INCOMPLETE suffix and
    # all) and the errors map come back exactly as the pull left them, so a
    # reused build renders the same notes as the original — never a blank
    # board wearing a fresh face.
    # reuse=False (run.py --fresh-knocks) skips it: the manifest keys on the
    # DATE alone, so after a board's layout changes a same-day rebuild would
    # otherwise re-ship the morning's PNGs and look like the change never
    # landed (the "Talk To's per Rep" column, 2026-08-25).
    #
    # reuse also gates the PER-OWNER png reuse further down, which it did NOT
    # until 2026-08-25: skipping only the manifest still walked into each
    # owner's already-drawn board and shipped it, so --fresh-knocks re-pulled
    # nothing it could find on disk and a layout change stayed invisible for
    # the rest of the day — the exact symptom the flag exists to cure (the
    # "DAILY TOTAL KNOCKS" title). Same-day only: the filenames carry the
    # date, so tomorrow's run redraws regardless.
    cached = (_load_manifest(render_dir, captain.key, target, saturday, wanted)
              if reuse else None)
    if not reuse:
        logfn("    (--fresh-knocks) re-pulling; today's capture not reused")
    if cached is not None:
        for kind in wanted:
            out[kind] = cached["items"][kind]
        errors.update(cached["errors"])
        logfn(f"    ✓ reusing today's capture from {render_dir} "
              f"(no ownerville session needed)")
        return out

    from automations.focus_office_att.aliases import load_aliases
    aliases_raw = load_aliases()
    try:
        aliases_map = dict(aliases_raw)
    except Exception:  # noqa: BLE001
        aliases_map = {}
    pairs = owner_cfgs(names, aliases_raw)

    # §1's login-free Sales Board renderer holds a LIVE sync playwright in this
    # thread, and a second sync start in the same thread dies with "you are
    # using Playwright Sync API inside the asyncio loop" — the exact failure
    # that silently killed every §2 Tableau shot until _tableau_shots learned
    # to close first. Same medicine here, best-effort: costs one browser
    # relaunch for the next captain's §1, buys a session that can open at all.
    #
    # This has to come BEFORE the PSS crosstab, not just before the ownerville
    # session: the crosstab download starts its own sync playwright too, so
    # closing after it meant the download never got the chance — every weekly
    # board came out with blank apps columns on 2026-08-24, the section's first
    # day, and the error read like a Tableau problem.
    try:
        from automations.captainship_drafts import sheet_render
        sheet_render.close_renderer()
    except Exception:  # noqa: BLE001
        pass

    # The org-wide rep-level PSS crosstab, ONCE for every owner (the download
    # helper dedupes same-day pulls when the cache env is set, but one call per
    # build is the contract either way). BOTH sections read it since Raf's
    # "Total Apps" ask (2026-08-26): the weekly board sums Mon–Sat, the daily
    # board reads the single weekday column for `target`. One download covers
    # both because they are the same Mon–Sun week by construction — week_window
    # and daily_target both hang off yesterday, so week_ending(target) IS
    # we_sunday. Failure = apps columns blank / absent, boards flagged
    # INCOMPLETE in their sub-heading — fill-but-flag, never a dead section.
    from automations.weekly_knock_dispositions import apps as A
    pss_path = None
    try:
        pss_path = A.download(we_sunday)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ PSS crosstab failed ({type(e).__name__}: "
              f"{str(e)[:160]}) — apps columns blank, boards flagged "
              "INCOMPLETE")
    # The daily board wants ONE weekday column out of that crosstab. Read it
    # once per office below; a crosstab that doesn't carry the day at all
    # (a period-boundary week, a view that stops at Saturday) is logged ONCE
    # and turns the column off rather than repeating itself per owner.
    daily_day = A.day_name(target)
    daily_apps_off = False

    from automations.weekly_knock_dispositions import board as B  # noqa: F401
    from automations.weekly_knock_dispositions import pull as P
    from automations.total_knocks import render as knocks_render
    from automations.shared import knock_week_cache as KWC
    from automations.shared.tableau_patchright import ownerville_session

    # SESSION ECONOMY, honestly bounded: the week cache can make every weekly
    # pull free, but it can NOT make the session unnecessary here. want_daily
    # is True on both days this section runs (run.py's sections_on gates the
    # weekly section to Sun+Mon; the daily one runs every day), and the daily
    # knocks pulls are deliberately un-cached — they're one day, cheap, and
    # change intraday. So on every real build there is daily work for the
    # session regardless, and the browser opens either way. Deferring the
    # session open for the weekly-only `capture()` entry point would mean
    # restructuring the loop that owns the per-owner error isolation, for a
    # path nothing schedules — not worth the risk. Left as-is on purpose.

    out_daily: List[Tuple[str, Optional[Path]]] = out["daily_knocks"]
    out_weekly: List[Tuple[str, Optional[Path]]] = out["knock_dispo"]
    # Owners already answered per kind (board OR pending) — what the
    # session-failure sweep below checks, kept separate from the label in
    # `out` because a weekly label can carry an INCOMPLETE suffix.
    done_daily: set = set()
    done_weekly: set = set()
    # Owners the totals SPEAK FOR: a board, a reused board, or a real zero.
    # An office we could not reach (no Office Access yet, a dead session) is
    # absent here, and that gap is what the summary's "(N of M ICDs)" label
    # reports. Kept apart from done_* — that one means "answered per kind,
    # don't sweep it as a session casualty", which a FAILED owner satisfies
    # too.
    answered_daily: set = set()
    answered_weekly: set = set()
    # Owners left OUT of the email entirely because we have no Office Access
    # to them yet. Eve 2026-08-25: "esas 12 oficinas no las vamos a incluir por
    # ahora aunque hayamos pedido los accesos" — the twelve pending requests
    # were turning each captain's knock section into a wall of grey notes about
    # offices nobody can act on from the email. They stay in the LOG and in the
    # summary board's "(N of M ICDs)" label, which is what keeps the totals
    # honest; what they lose is a sub-heading of their own.
    gapped_daily: List[str] = []
    gapped_weekly: List[str] = []
    # Everything each summary needs, kept as pulled.
    captured_daily: List[tuple] = []    # (display, cfg, rows, apps|None)
    captured_weekly: List[tuple] = []   # (display, ov_rows, apps, dispo_cols)
    chan_rows: Optional[list] = None
    chan_apps_by_rep: Optional[dict] = None   # Chan's {rep: apps} for the day
    chan_apps: Optional[int] = None           # …and its total, for the summary
    chan_weekly: Optional[tuple] = None       # (ov_rows, dispo_cols) for the week
    chan_weekly_apps: Optional[dict] = None   # Chan's {rep: apps} for the week
    # Set when a board was reused from disk WITHOUT its rows sidecar (drawn
    # before the sidecar existed). That owner's own board is intact; only the
    # captainship SUMMARY loses their line, and it says so rather than showing
    # a total that silently misses an office.
    daily_partial = False
    weekly_partial = False
    def _day_apps(pss_owner: str):
        """That office's {rep: apps} for `target`, or None when unavailable.
        A missing weekday column is a crosstab-wide fact, so it turns the
        column off for the whole build after ONE log line; a per-owner failure
        (owner absent from the crosstab is NOT one — that's an empty dict)
        only costs that owner's column."""
        nonlocal daily_apps_off
        if pss_path is None or daily_apps_off:
            return None
        try:
            return A.rep_apps_for_owner(pss_path, pss_owner, aliases_map,
                                        days=[daily_day])
        except Exception as e:  # noqa: BLE001
            if "column" in str(e).lower():
                daily_apps_off = True
                logfn(f"  ⚠ PSS crosstab has no {daily_day} column — daily "
                      "boards ship without Total Apps, flagged INCOMPLETE")
            else:
                logfn(f"    ⚠ apps for {pss_owner}: {type(e).__name__}: "
                      f"{str(e)[:120]}")
            return None

    daily_root = Path(render_dir) / f"daily_knocks_{captain.key}"
    weekly_root = Path(render_dir) / f"knock_dispo_{captain.key}"
    try:
        with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
            # Chan's rows FIRST, because every owner's board carries them as
            # its comparison line — they have to exist before the first board
            # is drawn, not after the loop like when only the summary used
            # them. Costs nothing extra across a build: _CHAN_DAILY_CACHE is
            # per-process, so the first captain pays the one pull and the
            # other five read it.
            from automations.weekly_knock_dispositions.offices import (
                CHAN as CHAN_CFG)
            from automations.focus_office_att.aliases import _norm_name as _nn
            _CHAN_CFG = CHAN_CFG
            if want_weekly:
                # Same reasoning as the daily line below — the summary needs
                # it and the ladder inside makes it at most one pull per
                # build, usually none (Sunday's cache / Monday's hit).
                chan_weekly = _chan_weekly_rows(page, [], aliases_raw,
                                                monday, saturday, logfn=logfn)
                if chan_weekly and pss_path is not None:
                    try:
                        chan_weekly_apps = A.rep_apps_for_owner(
                            pss_path, _CHAN_CFG["pss_owner"], aliases_map)
                    except Exception as e:  # noqa: BLE001 — apps ≠ the row
                        logfn(f"    ⚠ Chan weekly apps: {type(e).__name__}: "
                              f"{str(e)[:120]}")
            if want_daily:
                chan_rows = _chan_daily_rows(page, [], aliases_raw, target,
                                             logfn=logfn)
                if chan_rows:
                    from automations.weekly_knock_dispositions.offices import (
                        CHAN as _CHAN)
                    _c_rows, chan_apps_by_rep, chan_apps = daily_apps_for_board(
                        chan_rows, _day_apps(_CHAN["name"]))
            for display, cfg in pairs:
                if want_daily:
                    try:
                        # ALREADY DRAWN TODAY? Reuse it. Per OWNER, not per
                        # captain: on 2026-08-24 a rebuild had to re-pull all
                        # ~50 owner-slots to fix the handful that had failed,
                        # and the run that succeeded for the other forty had
                        # left their boards right here on disk.
                        done_png = _owner_png(daily_root, display,
                                              "total_knocks", target)
                        if (reuse and done_png.exists()
                                and done_png.stat().st_size):
                            out_daily.append((display, done_png))
                            prev = _read_rows(done_png)
                            if prev is not None:
                                # A sidecar written before the Total Apps
                                # column was a plain list of rows; that ICD's
                                # apps cell simply stays blank rather than
                                # forcing a re-pull.
                                p_rows, p_apps = ((prev, None)
                                                  if isinstance(prev, list)
                                                  else (prev.get("rows") or [],
                                                        prev.get("apps")))
                                captured_daily.append((display, cfg, p_rows,
                                                       p_apps))
                            else:
                                daily_partial = True
                            logfn(f"    · daily {display}: reusing "
                                  f"{done_png.name}")
                            done_daily.add(display)
                            answered_daily.add(display)
                            if not want_weekly:
                                continue
                            raise _ReusedDaily
                        rows = _daily_rows_for_owner(page, cfg, aliases_raw,
                                                     target)
                        if not rows:
                            # Visible absence, never a blank board (standing
                            # rule): the email says so under this owner.
                            errors[f"daily_knocks:{display}"] = (
                                NO_DATA_MARK + "no knocks recorded yesterday")
                            out_daily.append((display, None))
                            answered_daily.add(display)
                        else:
                            board_rows, apps_by_rep, apps_n = (
                                daily_apps_for_board(rows,
                                                     _day_apps(cfg["pss_owner"])))
                            png = knocks_render.render_total_knocks(
                                target, rows=board_rows,
                                out_dir=daily_root / _slug(display),
                                title_suffix=display,
                                # "DAILY TOTAL KNOCKS — …" (Eve 2026-08-25).
                                # Sun+Mon the weekly board sits right under
                                # this one, and two boards headed the same way
                                # is how someone reads a day's number as the
                                # week's.
                                title_prefix="DAILY ",
                                extra_totals=compare_totals_for(
                                    display, chan_rows, chan_apps_by_rep),
                                apps=apps_by_rep)
                            # INCOMPLETE rides the sub-heading label, same as
                            # the weekly board's: the board is real, one
                            # column of it is missing, and the reader has to
                            # be told which.
                            out_daily.append((display if apps_by_rep is not None
                                              else f"{display} — ⚠ INCOMPLETE: "
                                                   "apps unavailable", png))
                            # captured_daily keeps the OWNERVILLE rows, not the
                            # rendered ones: the summary divides talk-tos by
                            # rep count, and a sales-only rep who never knocked
                            # must not dilute that denominator.
                            captured_daily.append((display, cfg, rows, apps_n))
                            _write_rows(png, {"rows": rows, "apps": apps_n})
                            answered_daily.add(display)
                            logfn(f"    ✓ daily {display}: {len(rows)} "
                                  f"rep(s) → {png.name}")
                    except _ReusedDaily:
                        pass          # reused above; the weekly half follows
                    except Exception as e:  # noqa: BLE001 — one owner ≠ section
                        logfn(f"    ✗ daily {display}: {type(e).__name__}: "
                              f"{str(e)[:200]}")
                        errors[f"daily_knocks:{display}"] = _owner_error_note(e)
                        if is_access_gap(e):
                            gapped_daily.append(display)
                        else:
                            out_daily.append((display, None))
                    done_daily.add(display)
                if want_weekly:
                    try:
                        # Board already drawn today? Same reuse as the daily
                        # half — and it saves more, because a weekly pull is
                        # ~12 ownerville round-trips against the daily's one.
                        done_png = _owner_png(weekly_root, display,
                                              "weekly_knock_dispositions",
                                              saturday)
                        if (reuse and done_png.exists()
                                and done_png.stat().st_size):
                            out_weekly.append((display, done_png))
                            logfn(f"    · weekly {display}: reusing "
                                  f"{done_png.name}")
                            prev = _read_rows(done_png)
                            if prev is not None:
                                captured_weekly.append(
                                    (display, prev.get("ov_rows") or [],
                                     prev.get("apps"),
                                     prev.get("dispo_cols") or []))
                            else:
                                weekly_partial = True
                            done_weekly.add(display)
                            answered_weekly.add(display)
                            continue
                        # Shared week cache (shared/knock_week_cache.py): the
                        # completed Mon–Sat week is frozen, and Sunday's
                        # weekly_knock_dispositions run + MONDAY's re-build of
                        # this very section ask for the exact same window. A
                        # hit skips the ~12 ownerville round-trips entirely
                        # and is NOT a failure — it falls through to the same
                        # render below with the same (ov_rows, dispo_cols)
                        # shape. A miss just pulls, exactly as before, and the
                        # per-owner try/except around all of it is untouched.
                        # (An EMPTY pull is never cached — see that module:
                        # an owner with no rows is usually a failed
                        # impersonation, and must be retried, not frozen in.)
                        hit = KWC.get(cfg["name"], saturday,
                                      aliases=aliases_raw)
                        if hit is not None:
                            ov_rows, dispo_cols = hit
                            logfn(f"    ↺ weekly {display}: from week cache")
                        else:
                            ov_rows, dispo_cols = P.pull_office_week(
                                page, cfg, aliases_raw, monday, saturday)
                            KWC.put(cfg["name"], saturday, ov_rows,
                                    dispo_cols, aliases=aliases_raw)
                        office_apps = (
                            A.rep_apps_for_owner(pss_path, cfg["pss_owner"],
                                                 aliases_map)
                            if pss_path is not None else None)
                        if not ov_rows and not office_apps:
                            # Visible absence, never a blank board (standing
                            # rule): the email says so under this owner.
                            errors[f"knock_dispo:{display}"] = (
                                NO_DATA_MARK
                                + "no knocks or sales recorded this week")
                            out_weekly.append((display, None))
                            done_weekly.add(display)
                            answered_weekly.add(display)
                            continue
                        gaps_only = B.is_gaps_only(ov_rows)
                        rows = B.compute_rows(ov_rows, office_apps, dispo_cols)
                        # Chan's totals ride the TOP of EVERY owner's weekly
                        # board, not just the captainship summary (Raf
                        # 2026-08-30: "make sure chan's numbers are at the top
                        # of this weekly disposition summary report. For mine
                        # and everyone elses" — everyone else's BOARD, which is
                        # what the metrics-thread copies have carried all along
                        # and these did not). The daily boards next to them
                        # already do it via compare_totals_for; this is the
                        # weekly half catching up.
                        n_top = 0
                        if (chan_weekly and not gaps_only
                                and _nn(display) != _nn(CHAN_CFG["name"])):
                            # index 1: under this owner's own TOTALS row,
                            # which compute_rows now puts first.
                            rows.insert(1, B.totals_row(
                                chan_weekly[0], chan_weekly_apps, dispo_cols,
                                label=f"{CHAN_CFG['name'].upper()} TOTALS"))
                            n_top = 1
                        # office=display puts the owner's name in the image
                        # title — many owners share one email, so every board
                        # must say whose it is (unlike the Metrics-thread
                        # post, where the channel already does).
                        png = B.render(display, monday, saturday, rows,
                                       weekly_root / _slug(display),
                                       dispo_cols, gaps_only=gaps_only,
                                       n_totals=1, n_compare_top=n_top)
                        # INCOMPLETE flag rides the display name so it lands
                        # in the sub-heading next to the board it qualifies.
                        label = (display if pss_path is not None
                                 else f"{display} — ⚠ INCOMPLETE: apps "
                                      "unavailable")
                        out_weekly.append((label, png))
                        captured_weekly.append((display, ov_rows, office_apps,
                                                dispo_cols))
                        # ov_rows only — the office's own reps. The Chan row
                        # is drawn ON the board, it is not this office's data,
                        # and a reuse that folded it in would double-count him
                        # into the captainship totals.
                        _write_rows(png, {"ov_rows": ov_rows,
                                          "apps": office_apps,
                                          "dispo_cols": dispo_cols})
                        answered_weekly.add(display)
                        logfn(f"    ✓ weekly {display}: {len(ov_rows)} "
                              f"rep(s) → {png.name}")
                    except Exception as e:  # noqa: BLE001 — one owner ≠ section
                        logfn(f"    ✗ weekly {display}: {type(e).__name__}: "
                              f"{str(e)[:200]}")
                        errors[f"knock_dispo:{display}"] = _owner_error_note(e)
                        if is_access_gap(e):
                            gapped_weekly.append(display)
                        else:
                            out_weekly.append((display, None))
                    done_weekly.add(display)
    except Exception as e:  # noqa: BLE001 — the session itself never opened
        logfn(f"  ⚠ ownerville session failed: {type(e).__name__}: "
              f"{str(e)[:200]}")
        reason = (f"ownerville session failed: {type(e).__name__}: "
                  f"{str(e)[:200]}")
        for kind, done, out_list in (
                ("daily_knocks", done_daily, out_daily),
                ("knock_dispo", done_weekly, out_weekly)):
            if kind not in wanted:
                continue
            errors[kind] = reason
            for display, _cfg in pairs:
                if display not in done:
                    errors.setdefault(f"{kind}:{display}",
                                      "ownerville session failed before this "
                                      "owner's pull")
                    out_list.append((display, None))

    # Raf's email reply 2026-08-23 ("1 report of each ICD's averages so the
    # captain can look at one report for his whole captainship") + Megan
    # ("put this combined overall view before the individual ones"): ONE
    # summary board FIRST — each owner as a single row of their week's
    # totals/averages (the same totals-row math their own board's bottom row
    # shows), with a CAPTAINSHIP TOTALS row under them. Built from the data
    # already pulled above — zero extra pulls; an owner whose pull failed has
    # no row here (their pending note below says why).
    wsummary_png = (weekly_root / "summary"
                    / f"knock_dispo_summary_{saturday.isoformat()}.png")
    if not captured_weekly and want_weekly and wsummary_png.exists():
        # Same reasoning as the daily summary above: reuse the board
        # the earlier run drew instead of showing none.
        out_weekly.insert(0, ("Captainship Summary", wsummary_png))
    if captured_weekly:
        try:
            from automations.weekly_knock_dispositions.board import (
                COMPARE_ROW_BG, THEME_PLUM, headers_for, totals_row)
            from automations.focus_office_att.aliases import (
                _norm_name as _nn)
            from automations.weekly_knock_dispositions.offices import (
                CHAN as _CHAN)
            common_cols = next(
                (c for _d, _r, _a, c in captured_weekly if c), [])
            sum_rows = [totals_row(r, a, common_cols, label=d)
                        for d, r, a, _c in captured_weekly]
            all_rows = [rec for _d, r, _a, _c in captured_weekly for rec in r]
            merged_apps: dict = {}
            has_apps = False
            for _d, _r, a, _c in captured_weekly:
                if a:
                    has_apps = True
                    merged_apps.update(a)
            # CAPTAINSHIP TOTALS leads the summary, matching the per-owner
            # boards' new order (Megan 2026-08-30).
            sum_rows.insert(0, totals_row(
                all_rows, merged_apps if has_apps else None, common_cols,
                label=totals_label(len(answered_weekly), len(pairs))))
            # Chan Park's line, teal, at the TOP (Raf 2026-08-30: "make sure
            # chan's numbers are at the top of this weekly disposition summary
            # report. For mine and everyone elses"). Skipped on a captainship
            # that already lists him as an owner — a comparison line identical
            # to a row three inches above it reads like he was counted twice.
            n_top = 0
            if chan_weekly and not any(_nn(d) == _nn(_CHAN["name"])
                                       for d, _r, _a, _c in captured_weekly):
                _c_rows, _ = chan_weekly
                # Summed against the HOST board's column list, like every
                # other comparison row: his own live columns could differ and
                # the row has to stay aligned under these headers.
                sum_rows.insert(1, totals_row(
                    _c_rows, chan_weekly_apps, common_cols,
                    label=f"{_CHAN['name'].upper()} TOTALS"))
                n_top = 1
            span = (f"{monday.strftime('%b')} {monday.day} – "
                    f"{saturday.strftime('%b')} {saturday.day}, "
                    f"{saturday.year}")
            png = knocks_render._draw(
                headers_for(common_cols), sum_rows,
                f"CAPTAINSHIP SUMMARY — {span}", THEME_PLUM,
                weekly_root / "summary"
                / f"knock_dispo_summary_{saturday.isoformat()}.png",
                name_col=1, wrap_headers=True,
                # CAPTAINSHIP TOTALS plum, then Chan teal — one block, on top.
                highlight_first_row=1 + n_top,
                top_row_colors=[THEME_PLUM["header_bg"]]
                + [COMPARE_ROW_BG] * n_top,
                highlight_last_row=0)
            out_weekly.insert(0, ("Captainship Summary" + (
                " — ⚠ INCOMPLETE: some ICDs reused from an earlier run"
                if weekly_partial else ""), png))
            logfn(f"    ✓ captainship summary: {len(captured_weekly)} "
                  "owner row(s)")
        except Exception as e:  # noqa: BLE001 — summary ≠ the section
            errors["knock_dispo:Captainship Summary"] = (
                f"{type(e).__name__}: {str(e)[:200]}")
            out_weekly.insert(0, ("Captainship Summary", None))
            logfn(f"    ✗ captainship summary: {type(e).__name__}: "
                  f"{str(e)[:160]}")

    # The daily counterpart (Megan: "a daily overall and then each ICD broken
    # out below it") — one row per ICD, teal Chan comparison row, plum
    # CAPTAINSHIP TOTALS. Same zero-extra-pulls economy (Chan's extra pull,
    # when it happened at all, happened once inside the session above).
    summary_png = (daily_root / "summary"
                   / f"daily_knocks_summary_{target.isoformat()}.png")
    if not captured_daily and want_daily and summary_png.exists():
        # Every owner came off disk and none carried rows, so there is nothing
        # to re-aggregate — but the summary this run would have drawn is
        # already sitting there from the run that drew them. Show that one
        # rather than dropping the board.
        out_daily.insert(0, (f"Daily Summary — {target.strftime('%b')} "
                             f"{target.day}", summary_png))
    if captured_daily:
        summary_label = f"Daily Summary — {target.strftime('%b')} {target.day}"
        try:
            png = render_daily_summary(captured_daily, target,
                                       daily_root / "summary",
                                       chan_rows=chan_rows,
                                       roster_n=len(pairs),
                                       n_covered=len(answered_daily),
                                       chan_apps=chan_apps)
            out_daily.insert(0, (summary_label + (
                " — ⚠ INCOMPLETE: some ICDs reused from an earlier run"
                if daily_partial else ""), png))
            logfn(f"    ✓ daily summary: {len(captured_daily)} ICD row(s)")
        except Exception as e:  # noqa: BLE001 — summary ≠ the section
            errors[f"daily_knocks:{summary_label}"] = (
                f"{type(e).__name__}: {str(e)[:200]}")
            out_daily.insert(0, (summary_label, None))
            logfn(f"    ✗ daily summary: {type(e).__name__}: {str(e)[:160]}")
    # A captainship where EVERY office is still waiting on Office Access ends
    # up with nothing to show. email_build reads an empty list as "the roster or
    # the session died" and renders the yellow pending note — which carries
    # PENDING_MARK and would hold that captain's whole email, the exact trap
    # this partial mode exists to avoid. So say what actually happened, in grey.
    for kind, out_list, gapped in (("daily_knocks", out_daily, gapped_daily),
                                   ("knock_dispo", out_weekly, gapped_weekly)):
        if kind in wanted and not out_list and gapped:
            errors[kind] = (
                NO_DATA_MARK + f"no office in this captainship is reachable yet "
                f"— {len(gapped)} still waiting on ownerville Office Access")

    # Written LAST, so it only ever describes a finished pull: a run that dies
    # mid-session leaves no manifest and the next build pulls properly instead
    # of inheriting half a captainship.
    for kind, gapped in (("daily_knocks", gapped_daily),
                         ("knock_dispo", gapped_weekly)):
        if kind in wanted and gapped:
            logfn(f"    · {kind}: {len(gapped)} owner(s) left OUT of the email "
                  f"(no Office Access): {', '.join(gapped)}")

    _save_manifest(render_dir, captain.key, target, saturday, wanted,
                   out, errors, logfn=logfn)
    return out


def capture(captain, today: dt.date, render_dir,
            *, logfn=print, errors: Optional[dict] = None
            ) -> List[Tuple[str, Optional[Path]]]:
    """The weekly boards alone — the original entry point, kept so a caller
    (or a scoped rerun) can still build just the Sunday section. run.py goes
    through capture_sections instead, which shares the roster lookup and the
    ownerville session between both sections."""
    return capture_sections(captain, today, render_dir, want_daily=False,
                            want_weekly=True, logfn=logfn,
                            errors=errors)["knock_dispo"]
