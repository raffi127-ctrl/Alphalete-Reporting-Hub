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
    print()
    print("all good" if not bad else str(bad) + " FAILURE(S)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
