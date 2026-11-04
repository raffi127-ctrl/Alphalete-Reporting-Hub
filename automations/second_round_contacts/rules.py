"""Raf's removal rules, as pure functions (see config for the clocks)."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from automations.second_round_contacts import config as C

KEEP, WAIT, DELETE, HIRED = "keep", "wait", "delete", "hired"


def decide(entry: dict, facts: dict, today: dt.date) -> Tuple[str, str]:
    """(verdict, reason) for one tracked contact.

    facts: offered / bob / ns_sched / ns_showed -> the date that list first
    named the person (or None); progress -> OwnerVille View Progress % (int)
    or None when it could not be read.
    """
    if entry.get("status") == "hired":
        return KEEP, "hired and badged -- kept for good (rehires)"
    sr = dt.date.fromisoformat(entry["second_round"])
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
