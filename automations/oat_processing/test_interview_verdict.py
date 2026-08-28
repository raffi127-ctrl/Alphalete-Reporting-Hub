"""The interview-history verdicts Carlos gave on 2026-08-28.

The whole point is that "no show / rejected / not qualified" and "delay
disqualified" are opposite calls, and that anything else stays UNDECIDED rather
than being guessed at.
"""
from automations.oat_processing.classify import (
    interview_verdict, verdict_for_history)


def test_no_show_is_a_retext():
    assert interview_verdict(
        "Interview Assigned (NO SHOW) (1st Interview - No Show)") == "retext"


def test_rejected_or_not_qualified_is_a_retext():
    assert interview_verdict("Rejected - Not Qualified") == "retext"
    assert interview_verdict("rejected") == "retext"


def test_delay_disqualified_is_a_removal():
    """We interviewed them and chose not to advance them — never text again."""
    assert interview_verdict("Delay Disqualified") == "remove_duplicate"
    assert interview_verdict("delay  disqualified (1st Interview)") == "remove_duplicate"


def test_showed_up_alone_is_undecided():
    """'Show Up' with no other signal is a human call, not a guess."""
    assert interview_verdict(
        "Interview Assigned (View Last Activity) (1st Interview - Show Up)") is None


def test_disqualification_beats_an_older_no_show():
    assert verdict_for_history([
        "Interview Assigned (NO SHOW) (1st Interview - No Show)",
        "Delay Disqualified"]) == "remove_duplicate"


def test_empty_history_is_no_verdict():
    assert verdict_for_history([]) == ""
    assert verdict_for_history(["Sent to Call List"]) == ""


if __name__ == "__main__":
    for fn in (test_no_show_is_a_retext, test_rejected_or_not_qualified_is_a_retext,
               test_delay_disqualified_is_a_removal, test_showed_up_alone_is_undecided,
               test_disqualification_beats_an_older_no_show,
               test_empty_history_is_no_verdict):
        fn(); print(f"  ok  {fn.__name__}")
    print("6/6 passed")
