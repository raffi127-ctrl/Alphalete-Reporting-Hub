"""Which address the pre-send duplicate check uses as its positive canary.

This is a whole Monday's docs, so it gets its own tests. The canary asks Blue
Ink "can you still find a packet we sent ourselves?", and the answer is only
worth anything if the address it names is one Blue Ink is certainly still
listing. `_a_logged_send` used to take the first key containing "@" out of
`already_sent` -- a dict built oldest-row-first, so it always named the first
person this report ever sent (Angelica Pedroza, 2026-08-24) and that address
only ever got older. On 2026-09-14 it was 21 days old, the canary read the
staleness as a broken search, and 40 new starts got nothing.

    python -m automations.blueink_docs.test_ledger
"""
from __future__ import annotations

import datetime as dt
import sys

from automations.blueink_docs import ledger

TODAY = dt.date(2026, 9, 14)
WITHIN = 14


def _row(sent_at, name, email, bundle="B-1"):
    """A ledger row in the shape record()/row_for() writes."""
    return [sent_at, "D2D OBCL 9.7", name, email, bundle, "sent", sent_at, ""]


OLDEST = _row("2026-08-24 07:41", "Angelica Pedroza", "angiep8k@gmail.com")
LAST_WEEK = _row("2026-09-07 07:52", "Cale Mckenna", "cale@example.com")
YESTERDAY = _row("2026-09-13 09:10", "Dana Reyes", "dana@example.com")


CASES = [
    # (name, rows, the address it should pick)
    # The whole bug: oldest first in the tab, newest wanted.
    ("prefers a recent send over the first one ever",
     [OLDEST, LAST_WEEK], "cale@example.com"),
    ("newest wins among several recent",
     [OLDEST, LAST_WEEK, YESTERDAY], "dana@example.com"),
    # No canary at all is the dangerous answer -- a search that has stopped
    # finding anything would sail through and mail everyone a second packet.
    # So an out-of-window address is still better than nothing.
    ("falls back to the newest logged send when none is recent",
     [OLDEST], "angiep8k@gmail.com"),
    ("first ever run has nothing to offer", [], ""),
    # A row with no bundle id was a failed send, not a send: Blue Ink has
    # nothing to find for it, so it would fail the canary every time.
    ("skips rows that never produced a bundle",
     [_row("2026-09-13 09:10", "No Bundle", "nb@example.com", bundle=""),
      LAST_WEEK], "cale@example.com"),
    ("skips rows with no email",
     [_row("2026-09-13 09:10", "No Email", ""), LAST_WEEK],
     "cale@example.com"),
    # An unreadable stamp can't prove recency, so it only ever serves as the
    # fallback -- never as the preferred pick over a dated row.
    ("an unreadable date does not beat a dated recent row",
     [LAST_WEEK, _row("who knows", "Odd Stamp", "odd@example.com")],
     "cale@example.com"),
    # Ragged rows are normal in a hand-touched Sheet and must not raise.
    ("a short row is padded, not fatal",
     [["2026-09-07 07:52", "D2D OBCL 9.7", "Cale Mckenna",
       "cale@example.com", "B-1"]], "cale@example.com"),
]


def main() -> int:
    bad = 0
    for name, rows, want in CASES:
        got = ledger.a_recent_send(rows, WITHIN, TODAY)
        ok = got == want
        bad += not ok
        print(("  ok  " if ok else "FAIL  ") + name.ljust(46)
              + (got or "(none)") + ("" if ok else "   want " + (want or "(none)")))

    # already_sent must answer the same either way -- run.py now hands it the
    # rows it already read, so that one Sheets read covers both questions.
    from_rows = ledger.already_sent(None, rows=[OLDEST, LAST_WEEK])
    ok = (from_rows.get("angiep8k@gmail.com") == "B-1"
          and from_rows.get("mckenna|cale") == "B-1")
    bad += not ok
    print(("  ok  " if ok else "FAIL  ")
          + "already_sent reads handed-in rows".ljust(46) + str(len(from_rows))
          + " keys")

    print()
    print("all good" if not bad else str(bad) + " FAILURE(S)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
