"""The office guard says WHICH condition it refused on. Run:

    python -m automations.oat_processing.test_office_guard_reason

WHY THIS EXISTS (2026-09-13). Khalil's office logged `office_guard_refused=14`
in a single walk, while another session was hand-running a live push on that same
office. The one flat tag could not answer the only question that mattered:

  * WRONG OFFICE — the banner names a different office, so something really did
    switch this session underneath the walk. That is the irreversible-send
    hazard the guard was written for (Carlos, 2026-08-30, sends landing in
    office 23318 that nobody could account for).
  * UNREADABLE — no "Office ID:" on the page at all. Refusing is still correct,
    but it is NOT evidence of a crossed session; it means the page is not what we
    think it is.

Answering it took log archaeology across three files, and the line was never
found. The diag tab should say it. Both still refuse — that is pinned here too,
because a guard that reports better but protects less would be a bad trade.

Touches nothing: no browser, no Sheet, no sends.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

from . import config
from . import run

_passed = 0
_failed = 0


def check(label, got, want) -> None:
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


class _Page:
    """Only what _body() reads: frames with text."""

    def __init__(self, text):
        self._t = text

    @property
    def frames(self):
        return [self]

    def inner_text(self, _sel="body"):
        return self._t

    def evaluate(self, *_a, **_k):
        return self._t

    def wait_for_timeout(self, _ms):
        pass


_WANT = "11901"
config.OFFICE_ID = _WANT

print("the right office is allowed through, and clears the reason:")
ok = run._guard_office_now(_Page("Office ID: 11901   Owner: Khalil Mansour"), "Send to AI")
check("allowed", ok, True)
check("no reason left set", run._LAST_OFFICE_GUARD, "")

print("a DIFFERENT office refuses, and is named as a crossed session:")
ok = run._guard_office_now(_Page("Office ID: 23318   Owner: Someone Else"), "Send to AI")
check("refused", ok, False)
check("reason", run._LAST_OFFICE_GUARD, "wrong_office")
check("outcome tag", run._office_guard_outcome(), "office_guard_wrong_office")

print("an UNREADABLE header refuses too, but is NOT called a crossed session:")
ok = run._guard_office_now(_Page("some error page with no banner at all"), "Send to AI")
check("refused", ok, False)
check("reason", run._LAST_OFFICE_GUARD, "unreadable")
check("outcome tag", run._office_guard_outcome(), "office_guard_unreadable")

print("the two are distinguishable, which is the whole point:")
check("tags differ",
      run._office_guard_outcome() != "office_guard_wrong_office", True)

print("an unset reason still records a REFUSAL, never a success:")
run._LAST_OFFICE_GUARD = ""
check("falls back to the old flat tag",
      run._office_guard_outcome(), "office_guard_refused")

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
