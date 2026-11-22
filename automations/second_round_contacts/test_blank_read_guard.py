"""A read that found nobody must never be read as "nobody qualifies".

2026-11-22, on Raf's own office -- which certainly marks BOB, with 5 hired
on his list and the 6pm nudge running off those marks:

    lists with anybody on them: NONE — the read found nobody at all,
    on any list, for any day

His list carried 155 removals and Cyrus's 91, almost all of them the 7-day
"not hired / left as a message" rule, bunched on a few days (57 on 11/19,
53 on 11/20). That is the shape of a blank read, not of a fortnight of
candidates saying no.

The guard for this existed and covered the EVENING pass only.
"""
from __future__ import annotations

import datetime as dt

from automations.second_round_contacts import config as C
from automations.second_round_contacts import rules


TODAY = dt.date(2026, 11, 22)


def _tracked(second_round="2026-11-11"):
    return {"status": "tracked", "second_round": second_round,
            "display": "Ada Fournier (2R 11/11)"}


def test_blank_facts_delete_somebody_on_the_daytime_pass():
    """The rule itself is right -- this is what it does with no facts, and
    why a blank read must never reach it."""
    verdict, why = rules.decide(_tracked(), {}, TODAY, evening=False)
    assert verdict == rules.DELETE
    assert "not hired" in why


def test_a_week_old_second_round_is_still_safe():
    """The rule waits 7 days, so the damage is to everybody OLDER than
    that -- which on a weekly cycle is most of the list."""
    recent = _tracked(second_round=(TODAY - dt.timedelta(days=2)).isoformat())
    verdict, _why = rules.decide(recent, {}, TODAY, evening=False)
    assert verdict != rules.DELETE


def test_the_evening_keeper_is_not_the_whole_read():
    """Why the old guard did not catch this: it asked whether ONE label came
    back, and only on the evening pass. The daytime rule reads the others."""
    assert C.EVENING_KEEPER in C.AUDIT_LABELS
    assert len(C.AUDIT_LABELS) > 1, (
        "the daytime rule reads offered / scheduled / showed too, so a guard "
        "on the keeper alone cannot speak for the read")


def test_the_lookback_is_wide_enough_that_blank_means_blank():
    """35 days back: a second round inside the 7-day rule's reach is always
    inside the window, so an empty read is never just a short window."""
    assert C.AUDIT_LOOKBACK_DAYS > C.NOT_HIRED_DAYS * 2
