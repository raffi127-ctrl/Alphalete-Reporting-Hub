"""Who is allowed to receive a birthday text -- and why the default is NO.

Megan, 2026-09-13: *"we will want to be sure we only send reminders for reps
that are not terminated."* Wishing a happy birthday to somebody we let go last
month is the failure this whole module is built around, so the rule here is the
opposite of the one the rest of the Hub uses.

EVERY OTHER REPORT FLAGS AND LETS A HUMAN PRUNE. `shared/terminated_icds.py`
says it outright -- "this list FLAGS, it never removes" -- because an automation
deleting somebody's filled-in row is worse than a stale row. That trade runs the
other way here: an unsent birthday reminder costs nothing and nobody notices,
a sent one costs a real apology. So this FAILS CLOSED. Anything we cannot prove
is a currently-working rep is skipped, and the skip is reported.

WHY THE BOARD, NOT THE TERMINATED LIST, IS THE PRIMARY TEST
A terminated list is negative evidence and it goes stale: absence from it means
"nobody has filed a termination", which is also what a missed filing looks like.
The current week's sales board is POSITIVE evidence -- `board.marked_names()`
returns `active`, the names on this week's tab carrying no termination mark at
all, which its own docstring calls "the board's own statement that somebody is
working THIS WEEK". Requiring presence there means a rep who quietly disappeared
stops getting texts even if nobody ever filed the paperwork.

It also solves REHIRES for free, which a list lookup cannot. 64 names on
'Terminated Reps' hold more than one row (Myra Singleton terminated 7/31/2026
and again 8/3/2026; Miles Williams three times) -- so `name in terminated` would
mute all 64 forever. A rehired rep is back on the board, so `active` has them.

THE SUPPRESSION LIST IS READ WHOLE, NEVER FILTERED TO RAF. The roster side of
this report is Raf-only, but col B of 'Terminated Reps' carries compound and
shifting labels -- 'Raf/Hogue' (311 rows), 'Raf/RT' (109) -- so narrowing the
suppression list by office is the fail-OPEN direction: a termination filed under
another label would be missed and the text would go out. Any name match vetoes.

TWO SOURCES, ONE SEAM -- BECAUSE THE SHEET IS GOING AWAY
Megan, 2026-09-13: *"the sales board is going away soon with what we're building
online."* So the week-tab read below is the LEGACY path, not the destination.
`read()` picks a source and everything downstream only ever sees a `Liveness`,
which means the migration is one function, not a rewrite.

The site's answer is strictly better and already exists:
`icd_sales_board/roster.py` keeps a PERSISTENT roster, deliberately separate
from the weekly sales tabs "because those get regenerated every week and
rewritten every day". Its `Rep` carries `status` (with 'Terminated' among
`STATUSES`), `terminated_on`, `is_terminated` and `gone_by(day)` -- a direct,
typed answer instead of hunting bare 'T' marks across day blocks. It also holds
`start_date`, so nothing depends on a week tab existing at all.

So: prefer the site roster whenever the office has one, fall back to the week
tabs while it doesn't, and when the Sheet finally goes, delete `_from_sheet`.
Nothing else in this module or in run.py changes.

ONLY 'TERMINATED' DISQUALIFIES -- FFP INCLUDED, CONFIRMED BY MEGAN.
The site's `NOT_IN_FIELD` also covers OFF, O-NA and FFP, which is right for "did
they roll a zero" and wrong here: being scheduled off on a Tuesday does not mean
you don't have a birthday. Megan's ask was literal -- *"only send reminders for
reps that are not terminated"* -- and she settled the FFP case directly on
2026-09-13, asked after Raf marked Kelvinton Scarbough FFP: *"moving forward you
will just get the DOB and won't have FFP so they can have a birthday alert."*
FFP means still in the business, so they still get one. Do not "tighten" this
later: it was decided, not defaulted.

The fail-closed half runs the OTHER direction -- somebody who is not on the
roster or board at all is still refused.

NAMES ARE COMPARED FOLDED, NEVER RAW. 122 of 2527 rows on that tab carry a
literal TAB inside the name ('Christian\tWilliams') and 310 carry parentheses or
slashes -- '(NC)' suffixes, nicknames ('Oluwafeyisayo (Faye) Akinrinola'), runs
of double spaces ('Madison  (Mae)      Collis'). `board.base_name()` already
folds all of that (it exists to match one person across two week tabs), so this
reuses it rather than growing a second, subtly different matcher.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from automations.terminated_reps import board as B


def _day(when) -> str:
    """A termination date for a human-readable reason line.

    ISO, and never '%-m/%-d' -- that strftime flag is a no-op on Windows and
    these reports run on both. [[cross-platform]]
    """
    return when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else "(no date)"


@dataclass
class Verdict:
    """Whether one person may be texted, and the sentence explaining it."""
    name: str
    allowed: bool
    why: str


@dataclass
class Liveness:
    """One read of the board + tracker, reusable for every candidate."""
    active: set = field(default_factory=set)      # folded names working THIS week
    contradicted: set = field(default_factory=set)  # board argues with itself
    terminated: dict = field(default_factory=dict)  # folded name -> latest date
    tab: str = ""
    degraded: str = ""      # non-empty => the read failed; allow nothing
    week_start: dt.date = dt.date.min

    def verdict(self, name: str) -> Verdict:
        key = B.base_name(name)
        if self.degraded:
            return Verdict(name, False, "couldn't verify (%s)" % self.degraded)
        if not key:
            return Verdict(name, False, "blank name")
        if key in self.contradicted:
            # A Check means the board says both things at once. That is exactly
            # the case where guessing is expensive, so we don't.
            return Verdict(name, False,
                           "the board contradicts itself about them this week")
        if key not in self.active:
            if key in self.terminated:
                return Verdict(name, False, "not on the current board; "
                                            "terminated %s" % _day(self.terminated[key]))
            return Verdict(name, False, "not on the current week's board")
        # On the board unmarked. A termination dated in the CURRENT week means
        # the tracker and the board disagree about right now -- fail closed.
        when = self.terminated.get(key)
        if when and when >= self.week_start:
            return Verdict(name, False, "on the board, but a termination was "
                                        "filed %s" % _day(when))
        return Verdict(name, True, "working this week (%s)" % self.tab)


def _tracker_latest() -> dict:
    """{folded name: latest termination date} from the 'Terminated Reps' tab.

    LATEST, not first: the same person legitimately holds several rows, and only
    the most recent one describes where they stand now. Rows with a blank date
    (12 of them, all 2025) can't be compared, so they are recorded as a date of
    None -- which `verdict` treats as "terminated at some point", enough to veto
    somebody who is also absent from the board.
    """
    from automations.terminated_reps import tracker as T
    _sh, ws = T._open()
    grid = ws.get_all_values()
    if not grid:
        return {}
    header = [str(h).strip().lower() for h in grid[0]]
    try:
        i_name = header.index("rep name")
        i_date = header.index("termination date we")
    except ValueError as e:  # noqa: BLE001
        raise RuntimeError("'Terminated Reps' headers moved: %r" % (grid[0],)) from e

    out: dict = {}
    for row in grid[1:]:
        name = row[i_name] if i_name < len(row) else ""
        key = B.base_name(name)
        if not key:
            continue
        when = B.to_date(row[i_date]) if i_date < len(row) else None
        if key not in out or (when and (out[key] is None or when > out[key])):
            out[key] = when
    return out


# The office this report covers, as the site keys its rosters. Raf only --
# see config.py. Kept here rather than in config because it is meaningless to
# anything but the source seam.
SITE_OFFICE_KEY = "rafael_hidalgo"


def site_roster(office_key: str = SITE_OFFICE_KEY):
    """The site's persistent roster for this office, or [] if it has none yet."""
    try:
        from automations.icd_sales_board import roster as R
        return R.load(office_key)
    except Exception:  # noqa: BLE001
        return []


def is_maintained(reps) -> bool:
    """Is this roster actually being kept up, or just seeded?

    THE TRAP THIS EXISTS FOR. Read live 2026-09-13, the site roster for Raf held
    61 reps and EVERY ONE was 'Active' -- not a single Terminated among them,
    while the sales board knew of 2,453 terminations. A roster nobody has ever
    marked somebody Terminated in cannot suppress anybody: switching to it that
    day would have texted the exact people this report exists to skip, and it
    would have looked like it was working.

    So 'auto' needs positive evidence that the status field is in use, not just
    that rows exist. One Terminated rep is that evidence. Until then it keeps
    reading the Sheet -- which is the uglier source and the correct one.
    `--source site` overrides this deliberately, for testing the new path.
    """
    return any(getattr(r, "is_terminated", False) for r in reps)


def _from_site(reps, today: dt.date) -> Liveness:
    """The site roster -> Liveness. The path this report should end up on.

    'Active' is not required: a rep who is OFF today, on a roadtrip or marked
    STF is still employed and still has a birthday. Only 'Terminated' vetoes.
    """
    live = Liveness(tab="site roster (%d reps)" % len(reps),
                    week_start=B.week_sunday(today) - dt.timedelta(days=6))
    for rep in reps:
        key = B.base_name(rep.name)
        if not key:
            continue
        if rep.is_terminated:
            when = None
            if rep.terminated_on:
                try:
                    when = dt.date.fromisoformat(rep.terminated_on)
                except ValueError:
                    when = None
            live.terminated[key] = when
        else:
            live.active.add(key)
    return live


def read(today: dt.date, *, logfn=print, source: str = "auto") -> Liveness:
    """One read of whichever source can answer. A failure returns a DEGRADED
    result, which allows nobody -- see the fail-closed note above.

    `source`: 'auto' (site if it has a roster, else the sheet), 'site', 'sheet'.
    """
    if source in ("auto", "site"):
        reps = site_roster()
        if reps and (source == "site" or is_maintained(reps)):
            logfn("  source: site roster (%d reps) -- the sheet is being retired"
                  % len(reps))
            return _from_site(reps, today)
        if source == "site":
            return Liveness(degraded="the site has no roster for this office yet")
        if reps:
            logfn("  source: sales board -- the site roster has %d reps but has "
                  "never recorded a termination, so it can't suppress yet" % len(reps))
    return _from_sheet(today, logfn=logfn)


def _from_sheet(today: dt.date, *, logfn=print) -> Liveness:
    """LEGACY: the weekly sales-board tabs. Delete when the Sheet goes away."""
    live = Liveness()
    live.week_start = B.week_sunday(today) - dt.timedelta(days=6)
    try:
        marked = B.marked_names(today, logfn=logfn)
    except Exception as e:  # noqa: BLE001
        live.degraded = "sales board unreadable: %s: %s" % (type(e).__name__,
                                                            str(e)[:120])
        return live
    live.tab = marked.title
    live.active = {B.base_name(n) for n in marked.active if B.base_name(n)}
    live.contradicted = {B.base_name(c.name) for c in marked.checks
                         if B.base_name(c.name)}
    for t in marked.terminated:
        key = B.base_name(t.name)
        if key and (key not in live.terminated
                    or live.terminated[key] is None
                    or t.term_date > live.terminated[key]):
            live.terminated[key] = t.term_date

    try:
        for key, when in _tracker_latest().items():
            if key not in live.terminated:
                live.terminated[key] = when
            elif when and (live.terminated[key] is None
                           or when > live.terminated[key]):
                live.terminated[key] = when
    except Exception as e:  # noqa: BLE001
        # The board alone still gives a positive signal, but the tracker is half
        # the check. Refuse rather than send on a partial read.
        live.degraded = "terminated list unreadable: %s: %s" % (type(e).__name__,
                                                                str(e)[:120])
    return live
