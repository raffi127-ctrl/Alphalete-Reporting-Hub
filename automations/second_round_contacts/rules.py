"""Raf's removal rules, as pure functions (see config for the clocks)."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from automations.second_round_contacts import config as C

KEEP, WAIT, DELETE, HIRED = "keep", "wait", "delete", "hired"

# Stamped on the state entry as `removed_by` when the EVENING rule is what took
# somebody out. Every removal can be undone now (restore), but each by its own
# mark, so the rule behind it has to be on record -- see `removed_rule`.
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


# WHAT TOOK THEM OUT, stamped as `removed_rule` on every removal so the way
# back can be read off it. Older removals carry only the reason text, so
# rule_of() falls back to it -- once, here, next to the messages it reads.
NOT_HIRED, NO_SHOW, NOT_BADGED = "not_hired", "no_show", "not_badged"
_REASON_PREFIX = {NOT_HIRED: "not hired", NO_SHOW: "new start never showed",
                  NOT_BADGED: "never fully badged"}

# How long a removal stays up for review. Past this the mark that would bring
# them back is older than the audit re-reads anyway.
COMEBACK_DAYS = 60


def rule_of(entry: dict) -> Optional[str]:
    """Which rule took this person out, or None if it cannot be told."""
    if entry.get("removed_by") == EVENING:
        return EVENING
    if entry.get("removed_rule"):
        return entry["removed_rule"]
    reason = (entry.get("reason") or "").lower()
    if "not marked bob" in reason:
        return EVENING
    for rule, prefix in _REASON_PREFIX.items():
        if reason.startswith(prefix):
            return rule
    return None


def removal_rule(verdict_reason: str, evening_why: Optional[str]) -> Optional[str]:
    """The rule behind a DELETE that decide() just returned."""
    if evening_why:
        return EVENING
    return rule_of({"reason": verdict_reason})


def restorable(entry: dict, today: dt.date) -> bool:
    """Is this removal still up for review? ANY rule's removal now (Eve,
    2026-11-19: "what if they get marked BOB later, or end up hired?"), for
    COMEBACK_DAYS after it was made."""
    if entry.get("status") != "removed" or rule_of(entry) is None:
        return False
    try:
        sr = dt.date.fromisoformat(entry["second_round"])
    except (KeyError, ValueError):
        return False
    try:
        when = dt.date.fromisoformat(entry.get("removed") or "")
    except ValueError:
        when = sr
    return 0 <= (today - when).days <= COMEBACK_DAYS and sr <= today


def restore(entry: dict, facts: dict, today: dt.date) -> Tuple[bool, str]:
    """(put them back?, reason). Somebody taken out who has SINCE got the mark
    the removal was waiting for comes back in (Eve, 2026-11-19):

      not marked BOB (the 7pm rule)              -> BOB
      not hired in 7 days                        -> BOB, new start booked,
                                                    or new start showed
      new start never showed                     -> new start showed
      never fully badged                         -> 100% on View Progress

    "Showed up" or "offered" alone never brings anyone back -- the keeper is
    BOB (Megan, 2026-11-17). And nobody comes back only to be taken straight
    out again by the standing rules: if decide() would remove them today, they
    stay out."""
    if not restorable(entry, today):
        return False, ""
    rule = rule_of(entry)
    why = ""
    # The 7pm rule takes out anyone without BOB even when a start is booked,
    # so only BOB can undo it -- a booked start would bring them back at 6am
    # for the 7pm pass to take out again, every day of its window.
    marks = ((("bob", "marked BOB"),) if rule == EVENING else
             (("ns_showed", "new start showed"),
              ("ns_sched", "new start booked"), ("bob", "marked BOB")))
    if rule in (EVENING, NOT_HIRED):
        for f, label in marks:
            if facts.get(f):
                why = "%s on %s, after being taken out" % (label, facts[f])
                break
    elif rule == NO_SHOW and facts.get("ns_showed"):
        why = "new start showed on %s, after being taken out" % facts["ns_showed"]
    elif rule == NOT_BADGED and (facts.get("progress") or 0) >= 100:
        why = "reached 100% on View Progress, after being taken out"
    if not why:
        return False, ""
    verdict, _ = decide(dict(entry, status="tracked"), facts, today)
    if verdict == DELETE:
        return False, ""
    return True, why


# OFFICES WHOSE REMOVALS ARE HELD, and why (2026-11-23).
#
# Every removal rule reads the SAME shape: ApplicantStream shows no BOB, no
# offer and no scheduled start, so the person was not brought on board. That
# is only true where the office MARKS its outcomes. Where it does not, an
# unmarked hire looks exactly like a candidate who said no, and the cards come
# off the owner's phone either way.
#
# How an office lands here: the restore pass put NOBODY back while the same
# pass, on the same day, with the same reader, put 27 back for one office and
# 19 for another. On 2026-11-23 Cyrus's account restored 0 of 91 and held 23,
# against 0 hired and 0 kept out of 111 on --check-marks. One account reading
# empty while others read full is not proof the office hires nobody; it is the
# question this list refuses to answer by deleting.
#
# Holding costs nothing and loses nothing: the person stays on the phone, the
# state file keeps tracking them, and the day they are marked they graduate
# normally. Removing is the move that cannot be checked afterwards, because
# what it leaves behind is an absence.
#
# TAKE AN OFFICE OFF THIS LIST once --check-marks shows it marking, or once
# somebody has asked them. Do not take one off because the list looks long.
HOLD_REMOVALS = {
    "Cyrus Wade": "restored 0 of 91 on 2026-11-23 while other offices "
                  "restored 27 and 19 -- check whether the office marks BOB "
                  "in ApplicantStream before taking 23 cards off the phone",
}


def removals_held(owner: str) -> str:
    """Why this owner's removals are held, or "" when they are not."""
    return HOLD_REMOVALS.get((owner or "").strip(), "")


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
