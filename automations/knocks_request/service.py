"""The engine behind `/knocks`: one office + one day (or a range of days) ->
the knock board PNG.

CACHE FIRST, AND THAT IS THE WHOLE DESIGN. Not because ownerville is
one-session-per-account — it is NOT, sessions parallelise fine and impersonation
is scoped to the session (Megan 2026-08-24) — but because a pull that opens a
browser on the SHARED Chrome profile fights the morning build for that profile,
and because the answer is usually already on disk anyway. The build leaves what
it pulled on
disk: `captainship_drafts.knock_dispo_images` writes each owner's board PNG
plus a `rows_*.json` sidecar of the very records it scraped. So for the day
people actually ask about — today's board, i.e. yesterday's knocks — this
module answers from those rows and never opens ownerville at all.

Order of attempts, first hit wins:
  1. our own cache        output/knocks_request/<office>/<date>.json
  2. the build's sidecar  <RENDER_DIR>/daily_knocks_*/<office>/rows_total_knocks_<date>.json
  3. a live pull          rashad_metrics.knocks_pull.pull_office_knocks

A RANGE runs that same ladder ONCE PER DAY and folds the results
(`total_knocks.aggregate`). That is why it isn't an ownerville date range:
day-by-day keeps every day individually cacheable, so a week overlapping the
mornings we already pulled is answered from disk with no session at all — and
it keeps 'Avg. Hrs Knocking', which is single-day clock arithmetic, correct.
Only the days we're missing reach step 3, and they share ONE session.

Only step 3 opens a browser, and it refuses to start while another module on
this machine is holding the SHARED profile (proc_guard) — `wait_for_ownerville`
polls instead, so a request during the 07:15 build lands when the build is done
rather than losing the profile race. A caller that passes its own `profile_dir`
to `pull_offices_knocks` does not need this wait at all: the constraint is one
browser per profile directory, not one session per ownerville account.

NOTHING HERE IS A NEW SCRAPE OR A NEW DRAWING. The pull is the same
`pull_office_knocks` the Rashad/other-office reports use (impersonate by name,
Disposition by Rep + Time Tracker, exit impersonation), and the image is the
same `total_knocks.render.render_total_knocks` board Raf gets every morning —
rendered from rows in memory, so no Sheet is read or written by a request.

No Slack in this module on purpose: `run.py` exercises the whole path offline.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

OUT_DIR = Path("output") / "knocks_request"

# Modules that hold the SHARED Chrome profile while they run. A live pull on
# that profile waits for all of them (a run on its own profile_dir need not). Names are `python -m` module paths, which is what
# proc_guard matches on.
OWNERVILLE_MODULES = (
    "automations.captainship_drafts.run",
    "automations.captainship_drafts.knocks_capture",
    "automations.weekly_knock_dispositions.run",
    "automations.total_knocks.run",
    "automations.other_office_knocks.run",
    "automations.rashad_metrics.knocks_run",
    "automations.focus_office_att.run_all_owners",
)

# How long a request is willing to wait for the session before giving up. The
# 07:15 captainship build can run ~2h, so the default covers a request sent
# while it works; the caller is told it is waiting, never left silent.
WAIT_TIMEOUT_S = 150 * 60
WAIT_POLL_S = 45


@dataclass
class Board:
    """What a request produced. `png` is None only when the span is a real
    zero — an office that recorded no knocks — which is an answer, not a
    failure, and `note` says so."""
    office: str                  # the canonical office/owner name
    asked_as: str                # what the requester typed
    target: dt.date              # first day of the span
    end: Optional[dt.date] = None   # last day; None/== target = a single day
    png: Optional[Path] = None   # the knocks board — pngs[0]
    pngs: List[Path] = field(default_factory=list)   # NDS shapes add Time Gaps
    shape: str = ""              # house | wireless | gaps_only
    rows: List[dict] = field(default_factory=list)
    source: str = ""             # "cache" | "build" | "live" | "mixed"
    note: str = ""
    partial: bool = False        # the span runs to today: it isn't over yet
    compared_to: str = ""        # office whose teal TOTAL line rides the board
    days: int = 1                # how many days were folded into it

    @property
    def is_range(self) -> bool:
        return self.end is not None and self.end != self.target


def central_today() -> dt.date:
    from automations.total_knocks.pull import central_today as _ct
    return _ct()


def default_target() -> dt.date:
    """Yesterday, Central — the day this morning's board covers."""
    return central_today() - dt.timedelta(days=1)


def span_days(start: dt.date, end: Optional[dt.date] = None) -> List[dt.date]:
    """Every day the request covers. `end` None means a single day."""
    from automations.total_knocks.aggregate import daterange
    return daterange(start, end or start)


def check_span(start: dt.date, end: Optional[dt.date] = None) -> Optional[str]:
    """The reason this span can't be served, in words a requester can act on —
    or None when it's fine. Returned rather than raised so the Slack handler
    can say it before doing any work, and the CLI can print the same sentence.

    A span is refused, never silently repaired: swapping a backwards range
    would hand back a board for dates nobody asked for, and the requester would
    have no way to tell."""
    from automations.total_knocks.aggregate import MAX_RANGE_DAYS
    end = end or start
    today = central_today()
    if end < start:
        return (f"{pretty_day(end)} comes before {pretty_day(start)} — I didn't "
                "want to guess which way round you meant, so nothing was "
                "pulled. Send them the other way and I'll get it.")
    if end > today:
        which = "that day hasn't" if end == start else "those days haven't"
        return (f"{pretty_day(end)} hasn't happened yet — {which} finished, so "
                "there's nothing to pull. Ask me for today or any day that's "
                "already gone by.")
    days = len(span_days(start, end))
    if days > MAX_RANGE_DAYS:
        return (f"That's {days} days. I cap a request at {MAX_RANGE_DAYS} so "
                "nobody ends up waiting on a month of scraping — ask me for a "
                "shorter stretch and I'll get it.")
    return None


def pretty_day(d: dt.date) -> str:
    """'August 23, 2026' — %-d is glibc/BSD only, so build it by hand."""
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def pretty_span(start: dt.date, end: Optional[dt.date] = None) -> str:
    """How a span reads in a Slack line: 'August 23, 2026' for one day,
    'August 18–23, 2026' for a range. Mirrors the board's own title so the
    message and the image agree."""
    from automations.total_knocks.render import _title_span
    return _title_span(start, end)


def _slug(name: str) -> str:
    from automations.captainship_drafts.knock_dispo_images import _slug as s
    return s(name)


def resolve_office(office: str) -> str:
    """The canonical ICD spelling for whatever the requester typed. A miss
    here is not fatal — the impersonation search tries the aliases too — so a
    broken alias sheet returns the input rather than raising."""
    try:
        from automations.focus_office_att.aliases import (
            alias_to_canonical, load_aliases,
        )
        return alias_to_canonical(office, load_aliases())
    except Exception:  # noqa: BLE001 — a name we can't canonicalise still pulls
        return office


# --------------------------------------------------------------- cache ----
def _cache_path(canonical: str, target: dt.date) -> Path:
    return OUT_DIR / _slug(canonical) / f"{target.isoformat()}.json"


def _build_render_dir() -> Path:
    """Where the captainship build parks the day's boards. Imported from its
    config so the two can't drift; the literal is only the fallback for a
    machine where that import pulls in something mid-refactor."""
    try:
        from automations.captainship_drafts import config as C
        return Path(C.RENDER_DIR)
    except Exception:  # noqa: BLE001
        return Path(tempfile.gettempdir()) / "captainship_drafts_render"


def cached_rows(canonical: str, target: dt.date) -> tuple[Optional[list], str]:
    """(rows, source) from disk, or (None, "") — see the module docstring for
    the order. Empty rows are NOT a cache hit: the build stores an empty pull
    for a real zero-knock day, but so does a failed impersonation, and a
    request should retry rather than freeze a maybe-wrong zero."""
    own = _cache_path(canonical, target)
    if own.exists():
        try:
            rows = json.loads(own.read_text(encoding="utf-8"))
            if rows:
                return rows, "cache"
        except Exception:  # noqa: BLE001 — a bad cache file just misses
            pass

    from automations.captainship_drafts.knock_dispo_images import (
        _owner_png, _read_rows,
    )
    root = _build_render_dir()
    slug = _slug(canonical)
    for daily_root in sorted(root.glob("daily_knocks_*")):
        # The build's dirs are per CAPTAIN; the owner subdir is what we match.
        if not (daily_root / slug).is_dir():
            continue
        png = _owner_png(daily_root, canonical, "total_knocks", target)
        rows = _read_rows(png)
        if rows:
            return rows, "build"
    return None, ""


def save_rows(canonical: str, target: dt.date, rows: list) -> None:
    """Park a live pull so the second person asking the same thing is free.

    TODAY IS NEVER CACHED. A mid-day pull is a snapshot of a day still being
    knocked; storing it would hand the next person this morning's half-numbers
    as if they were the day's, hours later. Only a finished day is frozen."""
    if not rows or target >= central_today():
        return
    p = _cache_path(canonical, target)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows), encoding="utf-8")
    except Exception:  # noqa: BLE001 — a cache that won't write is not an error
        pass


# ----------------------------------------------------------- ownerville ----
def ownerville_busy() -> List[str]:
    """Modules currently holding the ownerville session on this machine.

    [] on Windows and anywhere pgrep is missing (proc_guard's documented
    limit) — there the request just goes, which is what a laptop test wants."""
    from automations.day_orchestrator import proc_guard
    busy = []
    for mod in OWNERVILLE_MODULES:
        try:
            if proc_guard.running_pids(mod):
                busy.append(mod.rsplit(".", 2)[-2])
        except Exception:  # noqa: BLE001 — a guard must never raise
            pass
    return sorted(set(busy))


def wait_for_ownerville(*, timeout_s: int = WAIT_TIMEOUT_S,
                        poll_s: int = WAIT_POLL_S,
                        logfn: Callable[[str], None] = print) -> bool:
    """Block until nothing else holds the session. False = still busy at the
    timeout, and the caller reports that instead of pulling anyway."""
    deadline = time.monotonic() + timeout_s
    told = False
    while True:
        busy = ownerville_busy()
        if not busy:
            return True
        if not told:
            logfn(f"ownerville is busy ({', '.join(busy)}) — waiting for it "
                  "to finish before pulling")
            told = True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)



# ------------------------------------------------------------- compare ----
# Raf 2026-08-23 ("add Chan's totals above ours daily") put a teal CHAN PARK
# TOTAL line on the morning board; a board pulled on demand is the same board,
# so it carries the same line. render_total_knocks already takes `extra_totals`
# for exactly this — nothing is drawn here.
def compare_office() -> str:
    """Whose totals ride every board as the comparison line."""
    from automations.weekly_knock_dispositions.offices import CHAN
    return resolve_office(CHAN["name"])


def compare_rows(canonical: str, target: dt.date, *, allow_live: bool,
                 logfn: Callable[[str], None] = print
                 ) -> Optional[list]:
    """The comparison office's rows for `target`, or None to omit the line.

    NEVER opens an ownerville session of its own: a comparison is a nicety and
    a second session would fight the one the real pull needs. `allow_live` is
    True only when the caller is already inside a live pull and can afford the
    extra office in the SAME session."""
    compare = compare_office()
    if _norm(compare) == _norm(canonical):
        return None                     # asking for Chan: nothing to compare to
    rows, source = cached_rows(compare, target)
    if rows:
        logfn(f"comparison: {compare} from the {source}")
        return rows
    if not allow_live:
        logfn(f"comparison: no stored {compare} rows for {target} — board "
              "goes out without the teal line")
        return None
    return None                         # live path fills this in; see board_for


def missing_days(canonical: str, start: dt.date,
                 end: Optional[dt.date] = None) -> List[dt.date]:
    """Which days of the span are NOT already on disk for this office."""
    return [d for d in span_days(start, end) if not cached_rows(canonical, d)[0]]


def pull_plan(canonical: str, start: dt.date, end: Optional[dt.date] = None
              ) -> "tuple[List[dt.date], List[dt.date]]":
    """(our missing days, the comparison office's missing days) — everything a
    request would open ownerville for, BEFORE it opens it.

    The Slack handler asks this so it can promise "one second" or "about a
    minute" and be right. The comparison office counts: its days are pulled to
    match the span, so a request can be a minute's work even when every one of
    our own days is already on disk."""
    ours = missing_days(canonical, start, end)
    compare = compare_office()
    if _norm(compare) == _norm(canonical):
        return ours, []
    return ours, missing_days(compare, start, end)


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


# ---------------------------------------------------------------- board ----
def board_for(office: str, target: Optional[dt.date] = None,
              end: Optional[dt.date] = None, *,
              allow_live: bool = True,
              campaign: Optional[str] = None,
              wait_timeout_s: int = WAIT_TIMEOUT_S,
              logfn: Callable[[str], None] = print) -> Board:
    """The whole request: cache, else pull, then draw. Raises only on a real
    failure (no such office, a bad span, ownerville still busy, a broken pull)
    — a span with genuinely no knocks comes back as a Board with png=None and
    a note.

    `campaign` (optional): pin this invD2DClientId for OUR office instead of
    letting the per-office map choose. For an owner who runs more than one
    campaign the map cannot answer — it holds one value per office — so the
    requester says which (Raf 2026-09-01: "we might have to have a dropdown
    for what campaign they're in. Unless it can just tell what campaign the
    owner is from" — it can, for everyone who runs exactly one, and that stays
    the default).

    `end` (optional) makes it a RANGE, start and end inclusive. Every day is
    fetched on its own — from the cache where we have it, in one shared
    ownerville session where we don't — and folded by total_knocks.aggregate.
    `end` None, or equal to `target`, is the original single-day request and
    takes the original code path: one day gathered, `aggregate_days` hands the
    rows straight back, and the board renders byte-identically.
    """
    target = target or default_target()
    end = end or target
    # A day that hasn't happened is not an empty day. Ownerville answers a
    # future date with an empty grid — exactly what a real zero looks like —
    # so it has to be refused HERE, or the requester is told "no knocks
    # recorded" about tomorrow. Same for a backwards or oversized span.
    problem = check_span(target, end)
    if problem:
        raise ValueError(problem)
    today = central_today()
    days = span_days(target, end)
    canonical = resolve_office(office)
    b = Board(office=canonical, asked_as=office, target=target, end=end,
              partial=(end == today), days=len(days))
    if canonical.lower() != office.strip().lower():
        logfn(f"'{office}' resolves to '{canonical}'")

    compare = compare_office()
    want_compare_office = _norm(compare) != _norm(canonical)

    # ---- what's already on disk -------------------------------------------
    # Cache-first for the comparison too, so a cached board stays a
    # zero-session answer. allow_live=False here: the live branch below pulls
    # it in the session it is already opening.
    ours: dict = {}
    theirs: dict = {}
    sources: set = set()
    for d in days:
        rows, src = cached_rows(canonical, d)
        if rows:
            ours[d] = rows
            sources.add(src)
        if want_compare_office:
            c_rows = compare_rows(canonical, d, allow_live=False,
                                  logfn=lambda m: None)
            if c_rows:
                theirs[d] = c_rows
    need = [d for d in days if d not in ours]
    # The comparison is pulled to the SAME span, not merely topped up when we
    # happen to be opening a session for our own days (Megan 2026-08-25: "we
    # want exact comparison of the same date range at chan's to show"). So a
    # request whose own days are entirely cached still opens a session when the
    # comparison office is short a day — that line is part of the board, not a
    # bonus. In practice it rarely fires: the morning build pulls the
    # comparison office every day too, so both are usually on disk.
    compare_need = [d for d in days if want_compare_office and d not in theirs]
    if not need and not compare_need:
        logfn(f"{canonical} {target}..{end}: {len(days)} day(s) from the "
              f"{'/'.join(sorted(sources)) or 'cache'} "
              "(no ownerville session needed)")

    # ---- everything else, in ONE session ----------------------------------
    if need or compare_need:
        if not allow_live:
            if need:
                raise RuntimeError(
                    f"No stored knocks for {canonical} on "
                    f"{', '.join(d.isoformat() for d in need)} and live pulls "
                    "are off for this run.")
            # Only the comparison is short. That costs one line, never the
            # board — failing the whole request over it would be worse.
            logfn(f"comparison: {compare} is missing "
                  f"{len(compare_need)} day(s) and live pulls are off — board "
                  "goes out without the teal line")
            compare_need = []
        else:
            if not wait_for_ownerville(timeout_s=wait_timeout_s, logfn=logfn):
                raise RuntimeError(
                    "Ownerville is still busy with the scheduled reports — "
                    "nothing was pulled. Ask again once they finish.")
            # ONE session for both offices: a second session for the comparison
            # would race the first for the same Chrome profile.
            # ALWAYS the multi-office helper, even for one office: it is the
            # path that routes the MASTER office (Raf) around impersonation.
            # pull_office_knocks impersonates unconditionally, so asking it for
            # Raf reports his own office as an access gap.
            from automations.rashad_metrics.knocks_pull import pull_offices_days
            # The campaign rides WITH our job. None = let the per-office map
            # decide, which is right for every office that runs one campaign;
            # an explicit pick is for an owner who runs more than one (Jay
            # Turnage knocks AT&T and Energy Wells) or an office whose campaign
            # the map does not know yet.
            jobs = ([(canonical, need, campaign)] if need else [])
            if compare_need:
                # The comparison office keeps its OWN campaign — it is a
                # different office and the pick was about ours.
                jobs.append((compare, compare_need))
            # job is (name, days) or (name, days, campaign) — index, don't
            # unpack, or adding the campaign silently crashes the pull here.
            logfn("pulling " + ", ".join(
                f"{j[0]} ({len(j[1])} day{'s' if len(j[1]) != 1 else ''})"
                for j in jobs) + " from ownerville…")
            # Indexed by name, not by position: `jobs` may hold the comparison
            # office ALONE when our own days were all cached.
            got = {n: (rows_by_day, err) for n, rows_by_day, err in
                   pull_offices_days(jobs, verbose=True)}

            if need:
                rows_by_day, err = got[canonical]
                if err is not None:
                    raise err                  # THIS office failing is fatal
                for d, rows in rows_by_day.items():
                    if rows:
                        ours[d] = rows
                        save_rows(canonical, d, rows)
                sources.add("live")
            if compare_need:
                c_by_day, c_err = got[compare]
                if c_err is not None:
                    # A missing comparison costs one line, never the board.
                    logfn(f"⚠ {compare} comparison pull failed "
                          f"({type(c_err).__name__}) — board goes out without "
                          "it")
                else:
                    for d, c_rows in c_by_day.items():
                        if c_rows:
                            theirs[d] = c_rows
                            save_rows(compare, d, c_rows)

    # ---- fold the days ----------------------------------------------------
    from automations.total_knocks.aggregate import aggregate_days
    rows = aggregate_days([ours[d] for d in days if d in ours])
    b.rows = rows
    b.source = ("live" if sources == {"live"}
                else "mixed" if len(sources) > 1
                else (next(iter(sources), "")))
    if not rows:
        # An empty grid is genuinely ambiguous: a day nobody knocked and a day
        # the office has no data for at all look identical coming back. Say
        # both possibilities rather than asserting the flattering one.
        what = "that day" if b.end == b.target else "any of those days"
        b.note = (f"Ownerville returned no rows for {what} — either nobody "
                  "knocked, or that office has no data that far back")
        return b

    # The teal comparison line covers the SAME days as ours — that is the whole
    # point of it, and the branch above pulls the comparison office to the span
    # so it does. It is dropped ONLY when those days genuinely couldn't be
    # fetched (a failed pull, or --cache-only): a line summing 3 days beside our
    # 6 reads as the comparison office falling behind, when really we're just
    # holding fewer of their days. A wrong comparison is worse than none.
    chan_rows = None
    if want_compare_office:
        have = [d for d in days if d in theirs]
        if len(have) == len(days):
            chan_rows = aggregate_days([theirs[d] for d in days])
        elif have:
            logfn(f"comparison: only {len(have)}/{len(days)} day(s) of "
                  f"{compare} could be fetched — board goes out without the "
                  "teal line rather than comparing different spans")

    from automations.total_knocks import render as knocks_render
    extra = [(compare, chan_rows)] if chan_rows else []
    apps = _apps_for(canonical, days, logfn=logfn)
    # An NDS office gets a PAIR of boards and no comparison line; the shape
    # decides, so a fiber office that goes wireless needs no config change.
    b.pngs, b.shape = knocks_render.render_knocks_boards(
        target, rows=rows, out_dir=OUT_DIR / _slug(canonical),
        title_suffix=canonical, end=end, extra_totals=extra, apps=apps)
    b.png = b.pngs[0]
    if extra and b.shape == knocks_render.SHAPE_HOUSE:
        b.compared_to = compare
    logfn(f"board -> {b.png}")
    return b


def _apps_for(canonical: str, days: "list", *, logfn=print):
    """{rep: apps} for this office over `days`, or None to leave the columns off.

    READS THE SAVED CROSSTAB. NEVER DOWNLOADS. Raf 2026-09-01: "have it where
    Lucy pulls the product sales summary for everybody for last week … it's
    just checking the saved report that it pulled for everybody."

    The first version pulled Tableau per request. That is one Tableau hit every
    time somebody types /knocks — the access budget Grant flagged — and Megan
    measured it at 5-7 minutes added to the reply. The weekly board already
    downloads this exact org-wide crosstab once a week for every owner, so the
    file is sitting there; the request just reads it.

    NO APPS FOR TODAY, by Raf's own reasoning: "if I'm checking for today only,
    then it doesn't need to pull the product sales summary because obviously
    it's not updated for today." A today-shaped span gets the board without the
    columns rather than three columns of stale or empty numbers.

    None on anything unexpected — a missing file, a week not yet pulled, a
    parse failure. Apps are an enrichment; the knock board is the answer.
    """
    from automations.weekly_knock_dispositions import apps as A
    from automations.focus_office_att.aliases import load_aliases
    from automations.shared.report_week import week_ending
    try:
        weeks = {week_ending(d) for d in days}
        if len(weeks) != 1:
            logfn("apps: the span crosses a week boundary — columns left off "
                  "rather than counting part of one week")
            return None
        we_sunday = weeks.pop()
        # A COMPLETED WEEK ONLY. That is the actual rule (Megan 2026-09-01):
        # "if the date isn't from the current week, then it doesn't need to be
        # a fresh pull … it could be from a predone harvest, from a fully
        # completed week." A finished week is final, so the saved crosstab is
        # as good as a live pull and costs nothing. The CURRENT week is still
        # moving — its harvest either does not exist yet or is already stale —
        # and re-pulling it per request is the Tableau cost this was rewritten
        # to remove, so those days get the board without the apps columns.
        #
        # This also covers Raf's own case ("if I'm checking for today only, it
        # doesn't need to pull … it's not updated for today") without treating
        # today as a special case: today is in the current week by definition.
        if we_sunday >= week_ending(central_today()):
            logfn(f"apps: week ending {we_sunday} is the CURRENT week — not "
                  "final, and nothing is pulled fresh on a request, so the "
                  "apps columns stay off")
            return None
        # The path apps.download writes; we only ever READ it.
        pss_path = A.OUT_DIR / f"pss_rep_{we_sunday.isoformat()}.csv"
        if not pss_path.exists():
            logfn(f"apps: no saved crosstab for the week ending {we_sunday} "
                  f"— columns left off (nothing is downloaded on a request)")
            return None
        got = A.rep_apps_for_owner(pss_path, canonical, load_aliases(),
                                   days=[A.day_name(d) for d in days])
        logfn(f"apps: {len(got)} rep(s) from the saved crosstab "
              f"(week ending {we_sunday})")
        return got or None
    except Exception as e:  # noqa: BLE001 — apps never cost the board
        logfn(f"apps: unavailable ({type(e).__name__}: {str(e)[:160]}) — "
              "board goes out without the apps columns")
        return None


def access_gap(exc: BaseException) -> bool:
    """True when the failure is 'this office isn't on our ownerville account'
    rather than a run problem — the same test the captainship section uses, so
    both places call an access gap by the same name.

    NOTE: ownerville answers a MISSPELLED name and an un-granted office with
    the identical "not found in ownerville", so this alone cannot tell them
    apart — ask `unknown_office` before promising the requester it isn't a typo
    ("Frank Castillo", 2026-08-31).
    """
    from automations.captainship_drafts.knock_dispo_images import (
        _NO_OFFICE_MARKERS,
    )
    return any(m in str(exc).lower() for m in _NO_OFFICE_MARKERS)


def known_office_names() -> list:
    """Every ICD name the reports know: the recruiting roster plus every
    spelling on the ICD Aliases sheet. Best-effort — a source that won't load
    just narrows the list, it never raises (this only powers a hint)."""
    names: list = []
    try:
        roster = json.loads(
            (Path(__file__).resolve().parents[1] / "recruiting_report"
             / "offices.json").read_text(encoding="utf-8"))
        names += [o.get("name", "") for o in roster.get("offices", [])]
    except Exception:  # noqa: BLE001 — a hint is never worth an exception
        pass
    try:
        from automations.focus_office_att.aliases import load_aliases
        raw = load_aliases()
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            names += [str(k), str(v)]
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for n in names:
        n = (n or "").strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def unknown_office(typed: str) -> bool:
    """True when `typed` matches NO name we know — so the failure is a name
    problem, not an Office Access one. Unknowable (empty roster) reads False:
    the old permissions answer stays the default."""
    known = {n.lower() for n in known_office_names()}
    if not known:
        return False
    t = (typed or "").strip().lower()
    return bool(t) and t not in known and resolve_office(typed).lower() not in known


def suggest_office(typed: str) -> Optional[str]:
    """The roster name a mistyped or nicknamed request most likely meant, or
    None. Two passes: a SHARED LAST NAME with exactly one roster match (how
    'Frank Castillo' finds 'Francisco Castillo' — a nickname is nowhere near
    its legal spelling by character ratio, but the surname is exact), then a
    close overall match. Returns nothing when it would have to guess between
    two people: a wrong name sends someone another office's numbers."""
    import difflib

    t = " ".join((typed or "").split()).lower()
    if not t:
        return None
    known = known_office_names()
    last = t.rsplit(" ", 1)[-1]
    if len(last) > 2:
        same_last = [n for n in known
                     if n.lower().rsplit(" ", 1)[-1] == last
                     and n.lower() != t]
        # De-dupe on the name itself: the alias sheet lists the same person
        # under several spellings and that must not read as two candidates.
        if len({n.lower() for n in same_last}) == 1:
            return same_last[0]
        if same_last:
            return None
    close = difflib.get_close_matches(t, [n.lower() for n in known], n=1,
                                      cutoff=0.85)
    if not close:
        return None
    return next(n for n in known if n.lower() == close[0])
