"""The relay script is deployed by hand, so a missing function is a live bug.

`resources/icd-alerts-relay.gs` is pasted into Apps Script. Nothing compiles
it here and nothing imports it, so the usual safety net does not apply: a call
to a function that does not exist is perfectly valid JavaScript and only fails
when an admin presses the button.

That is not hypothetical. On 2026-11-06 `_admApexWeek` was added, the dispatch
line calling it was added, and the function body was then lost -- a concurrent
session rewrote the file between the edit and the commit (the hazard CLAUDE.md
warns about, and [[reference_generated_files_eat_hand_edits]]). It was COMMITTED
that way. A syntax check with `new Function()` passed, because an undefined
function is a runtime error, not a syntax error.

So this walks the script and checks that every one of its own functions that
gets called is also defined. Cheap, and it would have caught that in a second.
"""
from __future__ import annotations

import re
from pathlib import Path

RELAY = (Path(__file__).resolve().parents[2]
         / "resources" / "icd-alerts-relay.gs")

# The relay names its own internals with a leading underscore (_admSend,
# _officeJobEnqueue, _book). Those are what this checks; anything else is a
# built-in or a method on an object and is none of our business.
DEFINED = re.compile(r"\bfunction\s+(_[A-Za-z0-9_]*)\s*\(")
#  `_foo(` not preceded by a dot -- so `x._foo(` (a method) does not count.
CALLED = re.compile(r"(?<![.\w])(_[A-Za-z0-9_]*)\s*\(")


def _source() -> str:
    return RELAY.read_text(encoding="utf-8")


def test_the_relay_script_is_still_there():
    assert RELAY.exists(), "resources/icd-alerts-relay.gs has gone missing"
    assert len(_source()) > 10000


def test_every_function_the_relay_calls_is_one_it_defines():
    """The check that would have caught the lost _admApexWeek."""
    src = _source()
    defined = set(DEFINED.findall(src))
    called = set(CALLED.findall(src))
    missing = sorted(called - defined - {"_"})
    assert not missing, (
        "the relay calls %d function(s) it never defines: %s. Something was "
        "edited away -- check git log for resources/icd-alerts-relay.gs."
        % (len(missing), ", ".join(missing)))


def test_the_apex_week_job_is_wired_end_to_end():
    """All three pieces, named. Any one of them alone is a broken deploy:
    the kind without the call does nothing, the call without the function
    throws for the admin who presses the button."""
    src = _source()
    assert "apex_week: true" in src, "apex_week is not an allowed job kind"
    assert "_admApexWeek(sess, office, a)" in src, "nothing dispatches apex_week"
    assert "function _admApexWeek(" in src, "apex_week's handler is missing"


def test_apex_week_will_not_queue_two_runs_for_one_week():
    """This job creates payroll records. Two queued runs would read the same
    calendar and try to create the same people."""
    src = _source()
    body = src[src.index("function _admApexWeek("):]
    body = body[:body.index("\nfunction ")]
    assert "already_running" in body
    assert "OJ.RESULT_AT" in body, "it must ignore FINISHED runs when checking"


def test_a_week_that_is_not_a_date_is_refused():
    src = _source()
    body = src[src.index("function _admApexWeek("):]
    assert r"^\d{4}-\d{2}-\d{2}$" in body[:1200]


def test_the_board_calls_are_wired_end_to_end():
    """Three pieces each: the dispatch line and the function behind it. A
    dispatch with no function is valid JavaScript that throws for whoever
    presses the button — which is how 2f9d48d shipped broken."""
    src = _source()
    for call, fn in (("board_week", "_boardWeek"),
                     ("board_mark", "_boardMark"),
                     ("board_classroom", "_boardClassroom")):
        assert "what === '%s'" % call in src, "nothing dispatches %s" % call
        assert "function %s(" % fn in src, "%s has no handler" % fn


def test_the_board_is_read_from_the_offices_own_workbook():
    """Each office sees its own people and nobody else's. The sheet id comes
    from the office's settings row, never from the caller."""
    src = _source()
    assert "'Onboarding Sheet'" in src
    body = src[src.index("function _boardTab("):]
    body = body[:body.index("\nfunction ")]
    assert "_admSettings(office)" in body
    assert "a.sheet" not in body, "the caller does not get to name the workbook"


def test_marking_somebody_off_never_deletes_their_row():
    src = _source()
    body = src[src.index("function _boardMark("):]
    body = body[:body.index("\nfunction ")]
    for bad in ("deleteRow", "deleteRows", "clearContent"):
        assert bad not in body, "a terminated row is hidden, never deleted"
    assert "restore" in body, "and it can be undone"


def test_the_settings_tab_is_read_by_header_not_by_position():
    """Two columns were added to that tab on the same day — 'Onboarding Sheet'
    and 'Owner' — and whichever landed second shifted the other's index. A read
    by number returns the wrong cell SILENTLY, which is the worst kind."""
    src = _source()
    body = src[src.index("function _admSettings("):]
    body = body[:body.index("\n\n// One office")] if "\n\n// One office" in body else body[:2000]
    import re
    numeric = re.findall(r"rows\[i\]\[([1-9])\]", body)
    assert not numeric, "reads column %s by position" % ", ".join(numeric)
    for name in ("'State'", "'City'", "'AppStream'", "'Onboarding Sheet'"):
        assert name in body, "%s should be looked up by header" % name


def test_saving_an_office_never_writes_over_the_newer_columns():
    """Approved Accounts is the guard, Onboarding Sheet points at the board.
    A fixed span of columns would take both out the moment the order moved."""
    src = _source()
    body = src[src.index("function _admSetOffice("):]
    body = body[:body.index("\nfunction ")]
    assert "cur.cols[name]" in body, "it should place each value under its own header"
    assert "1, 1, row.length" not in body, "no fixed column span"
