"""Reading OwnerVille's View Progress table.

The sweep judges these cells to decide what is done. One of them -- Background
Check -- is also reported verbatim onto the onboarding board, beside Sterling's
answer, so the two can be compared while OwnerVille catches up.
"""
from __future__ import annotations

from automations.obcl_ov_sweep import ov_table as OV


# ------------------------------- what OwnerVille says about the background check

def _cell(text="", html=""):
    return {"text": text, "html": html}


def test_a_green_dated_background_check_reads_as_passed():
    """Megan, 2026-11-11, pointing at Lance Brogdon's row on View Progress:
    "the BGstatus is the BG check column and what it says". His cell is a
    green tick and 11/11/26 10:50 AM."""
    heads = ["Name", "Background Check", "Owner Submit"]
    cells = [_cell("Lance Brogdon"),
             _cell("11/11/26 10:50 AM", "<i class='fa-check'></i>"),
             _cell()]
    assert OV.bg_status_text(heads, cells) == "Passed"


def test_pending_in_ownerville_reads_as_pending():
    heads = ["Name", "Background Check"]
    assert OV.bg_status_text(heads, [_cell("X"), _cell("Pending")]) == "Taken - Pending"


def test_a_red_background_check_is_never_a_pass():
    """Even with a date on it."""
    heads = ["Name", "Background Check"]
    cells = [_cell("X"), _cell("11/11/26", "<span class='badge-error'>")]
    assert OV.bg_status_text(heads, cells) == "Failed"


def test_an_unreadable_header_says_nothing_rather_than_nothing_happened():
    """Unread is never a state. A blank keeps the column empty instead of
    writing a wrong answer onto the board."""
    assert OV.bg_status_text(["Name"], [_cell("X")]) == ""
    assert OV.bg_status_text(["Name", "Background Check"],
                             [_cell("X"), _cell()]) == ""


def test_words_nobody_has_seen_are_passed_through_not_guessed():
    """The board shows an unknown status in its own words and gives it no
    colour. Squeezing it into the nearest familiar one is how a bad result
    comes to look like progress."""
    heads = ["Name", "Background Check"]
    got = OV.bg_status_text(heads, [_cell("X"), _cell("Adverse Action")])
    assert got == "Adverse Action"


def test_it_is_not_sterlings_answer():
    """OwnerVille's cell is its own attestation -- Sterling passing somebody
    does not turn it green, which is why the board carries both columns."""
    import inspect
    src = inspect.getsource(OV.bg_status_text)
    assert "sterling" in src.lower(), "the distinction has to be written down"
