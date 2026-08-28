"""Refusing to work a queue that is not the office we were told to work.

WHY (2026-08-27): the office switch happens once, when the session opens.
`run_walk` — the thing that SENDS, REMOVES and TEXTS — never checked which office
it had landed on. The standalone `run()` path aborts on a failed switch; the
applicant_push path we actually run does not. So a switch that silently did not
take would have the walk process someone else's applicants, irreversibly, every
ten minutes. Harmless while only one office was ever worked; not harmless from
the day a second office was added and the session began switching between them.
Megan: "It looks like lucy 2 is processing apps for other offices right now?????"

FAILS CLOSED — a mismatch aborts, and so does a header we cannot read.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_office_guard
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

from automations.oat_processing import run as oat
from automations.oat_processing import config

_passed = 0
_failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


# The real header, as the screenshots show it.
ATEF = ("office id: 23467     owner: atef choudhury\ndomin8 acquisitions, inc.\n"
        "time: aug, 27 02:25 pm - mountain standard time (utc-6)\n"
        "process email applications\napplicant details:")
CARLOS = ("office id: 11580   owner: carlos hidalgo\nalphalete specialized marketing\n"
          "process email applications")


class _Page:
    def __init__(self, body):
        self.body = body
        self.waits = 0

    def inner_text(self, _sel):
        return self.body

    def wait_for_timeout(self, _ms):
        self.waits += 1


print("reading the office off the page:")
check("Atef's header", oat.office_on_page(_Page(ATEF)), "23467")
check("Carlos's header", oat.office_on_page(_Page(CARLOS)), "11580")
check("no header at all", oat.office_on_page(_Page("some other page")), None)

_orig = config.OFFICE_ID
try:
    config.OFFICE_ID = "23467"
    print("working Atef's office:")
    check("on Atef's page -> proceed",
          oat.assert_on_expected_office(_Page(ATEF)), True)
    # THE REPORTED FEAR: told to work Atef, landed on someone else's queue.
    check("on Carlos's page -> ABORT",
          oat.assert_on_expected_office(_Page(CARLOS), tries=1), False)
    check("on an unrelated office -> ABORT",
          oat.assert_on_expected_office(_Page("office id: 22524 owner: haytham"),
                                        tries=1), False)

    print("fails CLOSED when it cannot tell:")
    p = _Page("a page with no office header")
    check("unreadable header -> ABORT", oat.assert_on_expected_office(p, tries=2), False)
    check("it retried before giving up (header may still render)", p.waits, 2)

    print("a late-rendering header is not a mismatch:")

    class _Late(_Page):
        def __init__(self):
            _Page.__init__(self, "")
            self.n = 0

        def inner_text(self, _sel):
            self.n += 1
            return ATEF if self.n >= 3 else ""

    check("header arrives on the 3rd look -> proceed",
          oat.assert_on_expected_office(_Late(), tries=4), True)

    config.OFFICE_ID = "11580"
    print("and the same guard protects Carlos from Atef's queue:")
    check("told Carlos, shown Atef -> ABORT",
          oat.assert_on_expected_office(_Page(ATEF), tries=1), False)
    check("told Carlos, shown Carlos -> proceed",
          oat.assert_on_expected_office(_Page(CARLOS)), True)
finally:
    config.OFFICE_ID = _orig

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
