"""Raf's removal rules, as pure functions (see config for the clocks)."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from automations.second_round_contacts import config as C

KEEP, WAIT, DELETE, HIRED = "keep", "wait", "delete", "hired"

# Stamped on the state entry as `removed_by` when the EVENING rule is what took
# somebody out. It is the only removal that can be undone, so it has to be
# tellable apart from the standing ones -- a not-hired or never-badged removal
# stays removed. Matching on the reason prose would do it today and break the
# first time somebody rewords a message.
EVENING = "evening"


def in_evening_window(sr: dt.date, today: dt.date) -> bool:
    """Is this second round today, or recent enough for the 7pm pass to still
    be looking at it? Never the future: a second round booked for tomorrow has
    not happened, so there is nothing to judge."""
    return 0 <= (today - sr).days <= C.EVENING_LOOKBACK_DAYS


def evening_removal(entry: dict, facts: dict,
                    today: dt.date) -> Optional[str]:
    """Why the 7pm pass takes somebody out, or None.

    THE KEEPER IS THE BOB MARK, nothing else (Megan, 2026-11-17: "anyone that
    isn't marked BOB should be removed"). Showed up is not enough and neither
    is an offer -- plenty of people are marked both and never start, and those
    are exactly the names that fill reception's group with nobody.

    Kept as its own function because `run` needs the same answer to stamp
    `removed_by`, and two copies of this test would drift."""
    sr = dt.date.fromisoformat(entry["second_round"])
    if not in_evening_window(sr, today):
        return None
    if facts.get("bob"):
        return None
    return "second round %s: not marked BOB by the end of the day" % sr


def restorable(entry: dict, today: dt.date) -> bool:
    """Could the 7pm pass still put this person back? Only its own removals,
    and only inside its window -- so it never argues with a standing rule."""
    if entry.get("status") != "removed" or entry.get("removed_by") != EVENING:
        return False
    try:
        sr = dt.date.fromisoformat(entry["second_round"])
    except (KeyError, ValueError):
        return False
    return in_evening_window(sr, today)


def restore(entry: dict, facts: dict, today: dt.date) -> Tuple[bool, str]:
    """(put them back?, reason). The other half of the look-back: somebody
    marked after 7pm, or the next morning, was marked into a contact that had
    already gone. The mark is the evidence; the removal was a guess made when
    the box was still blank."""
    if not restorable(entry, today):
        return False, ""
    if facts.get("bob"):
        return True, ("marked BOB on %s, after the 7pm pass had taken them "
                      "out" % facts["bob"])
    return False, ""


def decide(entry: dict, facts: dict, today: dt.date,
           evening: bool = False) -> Tuple[str, str]:
    """(verdict, reason) for one tracked contact.

    facts: showed / offered / bob / ns_sched / ns_showed -> the date that list
    first named the person (or None); progress -> OwnerVille View Progress %
    (int) or None when it could not be read. `showed` is the SECOND ROUND
    showing up, which is what the evening rule reads; `ns_showed` is the new
    start's first day, weeks later.
    """
    if entry.get("status") == "hired":
        return KEEP, "hired and badged -- kept for good (rehires)"
    sr = dt.date.fromisoformat(entry["second_round"])
    # THE EVENING PASS. Their second round has been and gone and nobody
    # marked them showed up or offered, so they are not coming. Only ever on
    # the evening run -- earlier in the day a blank means "nobody has said
    # yet" (Raf, 2026-11-17). The window is today AND yesterday, because
    # recruiters mark late; `restore` is the same window read the other way.
    # The keeper is the BOB mark alone (Megan, 2026-11-17).
    if evening:
        why = evening_removal(entry, facts, today)
        if why:
            return DELETE, why
    showed = facts.get("ns_showed")
    if showed:
        prog = facts.get("progress")
        if prog is not None and prog >= 100:
            return HIRED, "new start showed and OwnerVille progress is 100%"
        if (today - showed).days >= C.BADGE_DAYS:
            if prog is None:
                return WAIT, "showed %s but OwnerVille progress could not be read" % showed
            return DELETE, "never fully badged: %d%% on View Progress %d days after showing up" % (prog, (today - showed).days)
        return WAIT, "new start showed %s, badging in progress" % showed
    sched = facts.get("bob") or facts.get("ns_sched") or facts.get("offered")
    if sched:
        if (today - sched).days >= C.NO_SHOW_DAYS:
            return DELETE, "new start never showed: scheduled %s, %d days ago" % (sched, (today - sched).days)
        return WAIT, "new start scheduled %s, waiting for the start" % sched
    if (today - sr).days >= C.NOT_HIRED_DAYS:
        return DELETE, "not hired / left as a message: second round %s, %d days ago" % (sr, (today - sr).days)
    return WAIT, "second round %s, under a week" % sr
