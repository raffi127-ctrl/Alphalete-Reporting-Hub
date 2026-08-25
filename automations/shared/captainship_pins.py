"""Reps Tableau still files under a captain they do NOT belong to.

Tableau's `Captain's Bonus Teams` filter is the only roster every captainship
report has. When SmartCircle re-files a rep — or never files them in the first
place — that filter keeps handing us a name that has no business in the
captain's numbers, EVERY DAY:

  * the metrics pulls (cancel rate, activation rate, ABP, 6+ days, churn) read
    the team block and write one row per owner, appending a row for anyone the
    tab doesn't carry yet — so a deleted row grows straight back tomorrow;
  * `new_owners/captain_gate` sees a Tableau team member with no Org Sales
    Board row and offers them to Evelyn for a ✅, every morning, until someone
    absent-mindedly ticks it.

Deleting the rows is therefore only half the job. This list is the other half:
the name is dropped from the pull BEFORE anything is written or proposed, so it
stays gone until Tableau is corrected.

Keyed BY CAPTAIN, because the same name is legitimate elsewhere — a rep pinned
out of Raf's team may be perfectly real on their own.

WHAT THIS LIST IS NOT. It is not the two-week-zero rule
(`captain_gate.EXCLUDE`), which takes a rep who DID belong off a campaign's
boxes after two closed weeks at 0 and leaves their history in place. This list
says the person was never on that team at all, so their numbers must not reach
the report in the first place.

WHAT IT CANNOT FIX. The "Captainship Avg" / "Grand Total" row on every one of
those tabs is Tableau's OWN per-team total, not a mean of the owner rows (an
activation rate is not the average of its owners' rates — see
captainship_activation_rate.pull.parse). A pinned rep is still inside that
total until SmartCircle drops him from the filter. We do not recompute it,
because recomputing a rate over the wrong denominator would be a worse number
than a slightly stale one. The per-owner rows — everything the reader actually
reads names off — are clean.

Remove a name here the day Tableau is corrected: a name that no longer comes
back under that captain is harmless, just dead weight.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, Optional

# captain -> reps Tableau files under them who are NOT on that captainship.
#
# 2026-08-20 (Eve): Steve McElwee is not in Rafael's captainship, whatever
# Tableau says. SmartCircle has not taken him out of the Raf's Team filter, so
# every daily pull would keep calling him. His rows came off the Org Sales
# Board's two Raf captainship blocks + both delta boxes and off the six tabs of
# Rafael's own metrics workbook the same day.
#
# 2026-08-21 (Eve): Milan Godbolt comes off Colten's captainship. Tableau's
# NDS Captain Teams filter still files him under "Colten's Team", so the daily
# roster scan would offer him back to Evelyn every morning and the churn pull
# would re-insert his row. His three rows (leaderboard, daily block and the
# COLTEN CAPTAINSHIP delta box) came off the Org Sales Board the same day, and
# his address left the "Colten's Captainship" distro. He stays an NDS ICD
# everywhere else — this pin is scoped to Colten, which is the whole point of
# the key.
#
# 2026-08-24 (Eve): Lizette Ruiz comes off Eveliz Wright's captainship — only
# the captainship. She stays a B2B ICD of the org everywhere else (office
# 22109, her rows in the board's own 'B2B' section and the 'Alphalete Org
# Owners' distro are untouched), which is exactly what keying the pin by
# captain buys. BOTH spellings are pinned because this name is split across
# sources: the board and the Focus Report tab say "Lizette Ruiz", AppStream and
# Tableau say "Lizette Ruiz-Conejo" (the churn tab fills under the Tableau
# spelling, and drop_reps runs AFTER the alias rename in owners_metrics_churn).
NOT_ON_TEAM: Dict[str, tuple] = {
    "Raf": ("Steve McElwee",),
    "Colten": ("Milan Godbolt",),
    "Eveliz": ("Lizette Ruiz", "Lizette Ruiz-Conejo"),
}


def _k(s) -> str:
    return " ".join(str(s or "").lower().split())


_TEAM_SUFFIX = re.compile(r"['’]?s?\s+team$", re.I)


def captain_key(captain_or_team: str) -> str:
    """Normalize either spelling to one key.

    The reports say "Raf's Team" (the Tableau filter value), the gate says
    "Raf" (the captain). Both have to hit the same entry, so the `'s Team`
    suffix is stripped and the rest lower-cased.
    """
    return _k(_TEAM_SUFFIX.sub("", str(captain_or_team or "").strip()))


def names_for(captain_or_team: str) -> tuple:
    """The pinned names under one captain (empty tuple when there are none)."""
    key = captain_key(captain_or_team)
    for capt, names in NOT_ON_TEAM.items():
        if captain_key(capt) == key:
            return tuple(names)
    return ()


def is_pinned(captain_or_team: str, name: str) -> bool:
    """Is this rep pinned OUT of this captainship, whatever Tableau says?"""
    return _k(name) in {_k(n) for n in names_for(captain_or_team)}


def drop_reps(reps: dict, captain_or_team: str, logfn=None,
              where: str = "") -> dict:
    """Return `reps` without the names pinned out of this captainship.

    `reps` is the {owner name: …} map every metrics pull returns. Matching is
    case/space-insensitive, so the Tableau spelling of the day ('Steve Mcelwee'
    vs 'Steve McElwee') can't slip past.

    Says so in the log when it drops someone: a row that silently stops
    appearing is exactly the kind of change this codebase wants named.
    """
    pinned = {_k(n) for n in names_for(captain_or_team)}
    if not pinned or not reps:
        return reps
    kept = {n: v for n, v in reps.items() if _k(n) not in pinned}
    dropped = [n for n in reps if _k(n) in pinned]
    if dropped and logfn:
        logfn(f"  – pinned out of {captain_or_team}: {', '.join(dropped)} "
              f"— not on this captainship{' (' + where + ')' if where else ''} "
              f"(shared/captainship_pins.NOT_ON_TEAM)")
    return kept


def drop_names(names: Iterable[str], captain_or_team: str,
               logfn=None) -> list:
    """Same, for a plain list of names (the ✅ gate's shape)."""
    pinned = {_k(n) for n in names_for(captain_or_team)}
    out, dropped = [], []
    for n in names or []:
        (dropped if _k(n) in pinned else out).append(n)
    if dropped and logfn:
        logfn(f"  – pinned out of {captain_or_team}: {', '.join(dropped)}")
    return out


# ---------------------------------------------------------------------------
# Reps who legitimately DO NOT APPEAR in one source, though they are really on
# the captainship.
# ---------------------------------------------------------------------------
#
# NOT the same thing as NOT_ON_TEAM above, and the difference matters:
#
#   NOT_ON_TEAM   the person is not on that captainship at all → their numbers
#                 must never reach the report. Applied to the PULL, so every
#                 tab of that captain loses them.
#   NOT_IN_SOURCE the person IS on the captainship and fills normally on their
#                 other tabs — they simply sell nothing that this particular
#                 source measures, so their rows on THIS tab are correctly
#                 blank. Applied only to the WENT-DARK check, so the blanks
#                 stay and the run stops calling them a failure.
#
# Keyed by the report SLUG, not by captain: the whole point is that one of a
# captain's tabs is expected to be blank while their others are not, so the
# fiber-wireless '-wl' suffix must NOT be stripped here.
#
# Why it exists: `detect_went_dark` flags a rep who has recent history on the
# tab but is absent from today's pull. That heuristic is right for a rep
# dropped from a Tableau filter or renamed past their alias, and wrong for a
# rep who genuinely stopped having anything to report. Left alone, the wrong
# case re-fires every morning for as long as the rep's last numbers sit in the
# tab's ~6-day recent window, holding the report INCOMPLETE and — since
# 2026-08-22 — holding that captain's draft back from the send.
#
# 2026-08-23 (Eve): Kobe Cireus and Melik El Jaiez, off Tony Chavez's NEW
# INTERNET churn tab only. Confirmed 2026-08-22 against the ORG-WIDE fiber
# churn view (ATTTRACKER2_1-D2D/CHURN, worksheet 'ICD Churn', all teams,
# pull.FIBER_ALLTEAM_URL): 90 reps, neither of them present under any
# spelling — so it is not a rename (an alias would fix that) and not Tony's
# saved-view filter (they are on nobody's). Both still fill normally on
# 'Wireless Churn - Tony Chavez (ATT Fiber)' under his team: they sell
# wireless only. The blank New Internet rows match the source and are correct.
# Take them out the day either one sells fiber.
NOT_IN_SOURCE: Dict[str, tuple] = {
    "tony": ("Kobe Cireus", "Melik El Jaiez"),
}


def absent_ok(slug: str) -> tuple:
    """Reps whose absence from THIS report's source is expected (not a fault)."""
    key = _k(slug)
    for s, names in NOT_IN_SOURCE.items():
        if _k(s) == key:
            return tuple(names)
    return ()


def drop_expected_absent(went_dark: dict, slug: str, logfn=None) -> dict:
    """Strip the expected-absent reps out of a {period: [name, ...]} went-dark
    map. A period left with nobody in it is dropped, so a map that empties out
    returns {} — i.e. the run reads CLEAN rather than INCOMPLETE.

    Says so in the log: a suppressed finding nobody can see is how a real
    outage later gets mistaken for this one.
    """
    expected = {_k(n) for n in absent_ok(slug)}
    if not expected or not went_dark:
        return went_dark
    out, hushed = {}, []
    for period, names in went_dark.items():
        keep = [n for n in names if _k(n) not in expected]
        hushed.extend(n for n in names if _k(n) in expected)
        if keep:
            out[period] = keep
    if hushed and logfn:
        logfn(f"  – expected absence, not went-dark: "
              f"{', '.join(sorted(set(hushed)))} — they sell nothing this "
              f"source measures (shared/captainship_pins.NOT_IN_SOURCE)")
    return out
