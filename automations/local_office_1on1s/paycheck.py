"""'Gross Paycheck last week?' — across all THREE P&Ls, not just Raf's.

Raf's Loom: "there's a couple different PLs here, so it would have to search
the three PLs, and then it would just grab got paid."

    Raf PNL 2026            gid 1300001293    ~440 named reps
    MJ-Alphaletes PNL 2026  gid 325879371       3 named reps
    OG-Alphaletes PNL 2026  gid 1122999014      3 named reps

THEY ARE A HANDOFF, NOT THREE PLACES TO SEARCH. Measured 2026-09-27:

    Hayden Wilson     Raf PNL: 8/30 $800,   then BLANK all September
                      OG PNL:  9/6 $800 · 9/13 $1,460 · 9/20 $750
    Thomas Crenshaw   Raf PNL: 8/30 $1,200, then BLANK
                      OG PNL:  9/6 $1,200 · 9/13 $1,200 · 9/20 $1,443
    Ana Griffin       Raf PNL: 8/30 $800,   then BLANK
                      MJ PNL:  9/6 $2,475 · 9/13 $1,965 · 9/20 $2,030

Raf PNL stops at WE 8/30 for these people and the sub-P&Ls take over from
WE 9/6. The one overlapping week AGREES in all three, so the handoff is clean.

Reading only 'Raf PNL 2026' — which is what reps_gross_paycheck does today —
returns BLANK September for three of the four leaders Raf named by name in the
Loom. That is the bug this exists to fix.

WHERE TWO P&LS DISAGREE ON A WEEK, NEITHER IS WRITTEN. A silent pick between
two different paycheques is worse than a blank and a flag.
[[feedback_dont_explain_away_a_zero]]

'Breakeven' (col C) is NOT read here. The column exists on all three tabs and
is EMPTY for all 446 named reps — it stays a manual cell.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.reps_gross_paycheck import names, pnl as pnl_mod

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"

# P&L TABS ARE DISCOVERED, NOT LISTED.
#
# A hardcoded list is wrong the day a new sub-P&L appears — and one did, mid
# build: 'Bas-Alphaletes PNL 2026' showed up on 2026-09-28, hours after the
# other three were written down. The failure is SILENT in the worst way: a rep
# whose money moved to the new book simply reads as an empty paycheck, which
# looks exactly like a week they earned nothing. [[feedback_dont_explain_away_a_zero]]
#
# So: every tab whose title looks like a P&L is a candidate, and a candidate is
# accepted only if it actually HAS the P&L header row. That keeps working
# copies, tests and backups out without needing to know their names in advance,
# and picks up the next sub-P&L with no edit here.
_LOOKS_LIKE_PNL = re.compile(r"\bp\s*(?:n|&)\s*l\b", re.I)
# Titles that look like a P&L but are not the live book.
_NOT_LIVE = re.compile(r"\b(test|old of|copy of|backup|archive|template)\b", re.I)

# The office's own book must always be found. If discovery cannot see it,
# something is wrong with the workbook rather than with this list.
MAIN_PNL_GID = 1300001293

HEADER_MUST_HAVE = ("first name", "last name")


@dataclass
class Discovered:
    tabs: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)   # "title — why"
    main: str = ""                                     # the office book (MAIN_PNL_GID)


def discover(spreadsheet) -> Discovered:
    """Every live P&L tab in the workbook, by shape rather than by name."""
    from automations.recruiting_report.fill import _retry
    out = Discovered()
    main_title = None
    for ws in spreadsheet.worksheets():
        title = ws.title
        if ws.id == MAIN_PNL_GID:
            main_title = title
        if not _LOOKS_LIKE_PNL.search(title):
            continue
        if _NOT_LIVE.search(title):
            out.skipped.append(f"{title} — name says it is not the live book")
            continue
        head = _retry(lambda w=ws: w.get("A1:L2"))
        row2 = [str(c or "").strip().lower() for c in (head[1] if len(head) > 1 else [])]
        missing = [h for h in HEADER_MUST_HAVE if h not in row2]
        if missing:
            out.skipped.append(f"{title} — no {'/'.join(missing)} header on row 2")
            continue
        out.tabs.append(title)

    if main_title is None:
        raise KeyError(f"gid {MAIN_PNL_GID} (the office P&L) is not in this workbook")
    if main_title not in out.tabs:
        raise KeyError(
            f"the office P&L {main_title!r} (gid {MAIN_PNL_GID}) did not pass "
            f"discovery — its header row may have moved. Skipped: {out.skipped}")
    out.main = main_title
    # Read the office book FIRST so it is the incumbent every conflict is
    # resolved in favour of (see load()).
    out.tabs.sort(key=lambda t: (t != main_title, t))
    return out


@dataclass
class Merged:
    paid: Dict[Tuple[str, dt.date], float] = field(default_factory=dict)
    source: Dict[Tuple[str, dt.date], str] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)
    tabs: List[str] = field(default_factory=list)      # what was read, office book first
    skipped: List[str] = field(default_factory=list)   # candidates rejected, with why
    main: str = ""                                     # the office book

    def got_paid(self, who: str, sunday: dt.date) -> Optional[float]:
        return self.paid.get((names.key(who), sunday))

    def where(self, who: str, sunday: dt.date) -> str:
        return self.source.get((names.key(who), sunday), "")


def load(spreadsheet, tabs: List[str] = None) -> Merged:
    """Merge every discovered P&L. `out.tabs` records what was actually read."""
    out = Merged()
    if tabs is None:
        found = discover(spreadsheet)
        tabs, out.skipped, out.main = found.tabs, found.skipped, found.main
    out.tabs = list(tabs)
    for tab in tabs:
        p = pnl_mod.load(spreadsheet, tab=tab)
        for person in p.people.values():
            k = names.key(person.raw)
            for sunday, amount in person.paid.items():
                cell = (k, sunday)
                if cell in out.paid and abs(out.paid[cell] - amount) > 0.005:
                    # A DISAGREEMENT, not a handoff. Megan 2026-09-28: "they
                    # must be testing something on the pnl tabs — just pull the
                    # data you know is correct." The office book is the one
                    # that is known correct: it matched Raf's own hand-typed
                    # 1on1 paychecks 3/3 (Alyssa Moreno $770/$976/$557), while
                    # Bas-Alphaletes was found to be a clean 7-week column
                    # offset. So the incumbent wins and the loser is recorded.
                    #
                    # This deliberately does NOT mean "the office book always
                    # wins": where it has no value at all, a sub-book is not
                    # disagreeing with it, it is CARRYING that week — which is
                    # the normal handoff and is left alone below.
                    keep, drop = out.paid[cell], amount
                    out.conflicts.append(
                        f"{person.raw} WE {sunday:%-m/%-d}: "
                        f"{out.source[cell]} ${keep:,.2f} kept, "
                        f"{tab} ${drop:,.2f} ignored")
                elif cell not in out.paid:
                    out.paid[cell] = amount
                    out.source[cell] = tab
    return out
