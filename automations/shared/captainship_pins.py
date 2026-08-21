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
NOT_ON_TEAM: Dict[str, tuple] = {
    "Raf": ("Steve McElwee",),
    "Colten": ("Milan Godbolt",),
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
