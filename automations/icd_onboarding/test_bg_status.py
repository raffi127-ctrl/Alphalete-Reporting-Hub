"""BG Status: whose check is it, and is it actually finished?

The two questions that can go wrong here both end the same way — a background
check recorded against the wrong person, or a check that has not come back
showing as done on somebody's board and printed sheet.
"""
from __future__ import annotations

import datetime as dt

from automations.icd_onboarding import bg_status as BG

MONDAY = dt.date(2026, 11, 2)


class Ev:
    def __init__(self, first, last, status):
        self.first, self.last, self.status = first, last, status


def _row(name):
    return {"Name": name.split()[0], "Last Name": " ".join(name.split()[1:])}


# ------------------------------------------------- only a finished check

def test_a_check_still_in_flight_shows_where_it_got_to():
    """Megan, 2026-11-09: "a status could also be Sent but not taken". Somebody
    chasing needs to tell "nobody sent it" from "it is out and we are waiting"
    — those are different jobs for different people."""
    boards = {"raf": [_row("Ada Fournier")]}
    for status in ("Sent", "Taken - Pending", "Review"):
        routed, _ = BG.route([Ev("Ada", "Fournier", status)], boards)
        assert routed == {"raf": {"Ada Fournier": status}}


def test_the_furthest_along_status_wins():
    """The inbox carries every mail in the window, so one person has a Sent
    AND a Passed. The board should say Passed."""
    boards = {"raf": [_row("Ada Fournier")]}
    routed, _ = BG.route([Ev("Ada", "Fournier", "Sent"),
                          Ev("Ada", "Fournier", "Passed")], boards)
    assert routed == {"raf": {"Ada Fournier": "Passed"}}
    routed, _ = BG.route([Ev("Ada", "Fournier", "Passed"),
                          Ev("Ada", "Fournier", "Sent")], boards)
    assert routed == {"raf": {"Ada Fournier": "Passed"}}, "order must not matter"


def test_not_sent_is_left_blank_so_it_still_counts_as_outstanding():
    from automations.icd_onboarding import board as B
    assert B.status_rank("") == 0 and B.status_rank(B.NOT_SENT) == 0


def test_a_status_never_goes_backwards():
    """A late Sent email must not pull somebody back from Passed."""
    from automations.icd_onboarding import board as B
    assert B.status_rank("Passed") > B.status_rank("Sent")
    assert B.status_rank("Sent") > B.status_rank("")


def test_every_finished_outcome_ticks_not_just_a_pass():
    """The box means 'there is an answer', not 'they passed' — a Failed check
    is just as finished, and leaving it blank would keep chasing somebody."""
    boards = {"raf": [_row("Ada Fournier")]}
    for status in BG.DONE_STATUSES:
        routed, _ = BG.route([Ev("Ada", "Fournier", status)], boards)
        assert routed == {"raf": {"Ada Fournier": status}}


def test_it_never_invents_a_pass():
    """bg_check_sync's compliance rule, which this inherits by reusing its
    parser rather than reading the mail itself."""
    import inspect
    from automations.bg_check_sync import parse
    assert "Score PASS" in inspect.getsource(parse)


# -------------------------------------------------- whose check is it

def test_a_result_goes_to_the_one_board_the_person_is_on():
    boards = {"raf": [_row("Ada Fournier")], "omar": [_row("Bruno Castell")]}
    routed, amb = BG.route([Ev("Bruno", "Castell", "Passed")], boards)
    assert routed == {"omar": {"Bruno Castell": "Passed"}}
    assert amb == []


def test_somebody_on_two_boards_is_ticked_on_NEITHER():
    """A check recorded against the wrong person at the wrong office is worse
    than one a human has to place."""
    boards = {"raf": [_row("Ada Fournier")], "omar": [_row("Ada Fournier")]}
    routed, amb = BG.route([Ev("Ada", "Fournier", "Passed")], boards)
    assert routed == {}
    assert amb and amb[0]["offices"] == ["omar", "raf"]


def test_a_result_for_nobody_on_any_board_is_dropped_quietly():
    """The inbox carries every ICD's mail, including weeks we are not looking
    at."""
    routed, amb = BG.route([Ev("Someone", "Else", "Passed")],
                           {"raf": [_row("Ada Fournier")]})
    assert routed == {} and amb == []


def test_names_match_past_spelling():
    boards = {"raf": [_row("Esme Vance Hale")]}
    routed, _ = BG.route([Ev("Esmé", "Vance-Hale", "Passed")], boards)
    assert routed == {"raf": {"Esmé Vance-Hale": "Passed"}}


# ------------------------------------------------------------ the inbox

def test_it_reads_the_icds_own_inbox_not_the_reporting_one():
    """Sterling results are kept out of the reporting inbox on purpose, and
    there is an alarm watching for them arriving there."""
    assert BG.INBOX == "lucysterlingreports@gmail.com"
    assert "raffi127" not in BG.INBOX


def test_a_run_is_dry_by_default():
    import inspect
    assert inspect.signature(BG.run).parameters["dry_run"].default is True
