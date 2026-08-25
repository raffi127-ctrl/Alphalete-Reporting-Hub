"""What the duplicate check makes of Blue Ink's list.

The strings below are the REAL page text captured off the live app on
2026-08-24 (the two full cases) plus variants built to the same shape. Sending
cannot be undone, so this is the piece that most needs to keep working: run it
after any change to recent_ui.verdict.

    python -m automations.blueink_docs.test_recent_ui
"""
from __future__ import annotations

import datetime as dt
import sys

from automations.blueink_docs.recent_ui import verdict

TODAY = dt.date(2026, 8, 24)

# Captured live: Angelica Pedroza, the one person known to have been sent twice.
HAS = ("Owner Sender Template Origin Status Tag Custom Filter Refresh Draft "
       "No Envelopes Sent Sort:Sent Showing 2 of 2 Sent8/24/26 Raf Documents AP "
       "Sent8/24/26 Angelica Pedroza")
# Captured live: an address with nothing on the account.
NONE = ("Owner Sender Template Origin Status Tag Custom Filter Refresh Draft "
        "No Envelopes Sent Sort:Sent No Envelopes Completed Sort:Sent")

CASES = [
    # (name, page text, should this person be blocked?)
    ("a live packet", HAS, True),
    ("nothing at all", NONE, False),
    # A draft was never delivered, so it isn't a packet anyone received.
    ("only a draft", "Draft Sort:Sent Showing 1 of 1 Draft8/24/26 Raf Documents "
                     "Sent No Envelopes", False),
    # Older than the lookback: a rehire months later still gets docs.
    ("sent 12 weeks ago", "Sent Sort:Sent Showing 1 of 1 Sent6/01/26 Raf Docs",
     False),
    ("cancelled", "Showing 1 of 1 Cancelled8/22/26 Raf Documents", False),
    ("declined", "Showing 1 of 1 Declined8/21/26 Raf Documents", False),
    ("completed 4 days ago", "Showing 1 of 1 Completed8/20/26 Raf Docs", True),
    ("sent today", "Showing 1 of 1 Sent8/24/26 Raf Documents", True),
    ("exactly at the lookback edge",
     "Showing 1 of 1 Sent8/10/26 Raf Documents", True),
    # Results the parser can't read must block: over-blocking costs one person
    # a same-day auto-send, under-blocking mails a second packet that cannot be
    # recalled.
    ("counted but unreadable", "Showing 3 of 3 shapes never seen before", True),
    ("empty page", "", False),
]


def main() -> int:
    bad = 0
    for name, text, want_blocked in CASES:
        got = verdict(text, TODAY)
        ok = bool(got) == want_blocked
        bad += not ok
        print(("  ok  " if ok else "FAIL  ") + name.ljust(30)
              + ("blocked: " + got if got else "clear"))
    bad += canaries()
    print()
    print("all good" if not bad else str(bad) + " FAILURE(S)")
    return 1 if bad else 0



# --- the canaries -----------------------------------------------------------
# The check reads a screen nobody versions, and it can break in two directions
# that both LOOK like a clean run. These prove each one is caught.

_HAS = "Showing 2 of 2 Sent8/24/26 Raf Documents AP Sent8/24/26 Angelica"
_NONE = "Draft No Envelopes Sent Sort:Sent No Envelopes Completed Sort:Sent"
_WHOLE_LIST = "Showing 40 of 436 Sent8/24/26 Employee Sent8/17/26 Employee"


class _FakePage(object):
    def __init__(self, mode):
        self.mode = mode

    def reply(self, term):
        if self.mode == "healthy":
            return _HAS if term == "known@x.com" else _NONE
        if self.mode == "not_filtering":       # every search returns everything
            return _WHOLE_LIST
        return _NONE                           # every search returns nothing


CANARY_CASES = [
    # (name, mode, known-sent address, should it stop the run?)
    ("search working", "healthy", "known@x.com", False),
    # Everyone would read already-sent and nobody would be mailed.
    ("search stopped filtering", "not_filtering", "known@x.com", True),
    # Everyone would read clear and the batch would send SECOND packets.
    ("search finds nothing", "finds_nothing", "known@x.com", True),
    # First ever run: nothing logged, so there is no positive canary to use.
    ("nothing logged yet", "finds_nothing", "", False),
]


def canaries() -> int:
    import automations.blueink_docs.recent_ui as R
    real = R._search
    bad = 0
    try:
        R._search = lambda page, term: page.reply(term)
        for name, mode, known, want_stop in CANARY_CASES:
            try:
                R._canaries(_FakePage(mode), known, TODAY)
                stopped, detail = False, "ran"
            except RuntimeError as exc:
                stopped, detail = True, str(exc).split(" -- ")[0]
            ok = stopped == want_stop
            bad += not ok
            print(("  ok  " if ok else "FAIL  ") + name.ljust(30) + detail[:70])
    finally:
        R._search = real
    return bad

if __name__ == "__main__":
    sys.exit(main())
