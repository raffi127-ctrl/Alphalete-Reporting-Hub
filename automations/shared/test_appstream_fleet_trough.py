"""There is no trough, because nothing hands this machine a session.

REVERSED 2026-09-02 — read the original reasoning below, then this.

The suppression this file was written to pin is now OFF. It was correct while
one machine minted and the rest consumed; since every Lucy signs in as its own
account and mints its own token, no copy is old on purpose and a short token is
never somebody else's business. Megan: "one machine CANNOT depend on another, we
don't want 1 taking them all down."

The direction of the risk flipped with it. A suppression that fires on a stale
premise does not fail loudly — it swallows the page on the morning the session
is really dead. So the tests below now pin that NO machine, in any marker state,
is ever reported as fleet-fed.

--- the original reasoning, kept because it is why the code looks like this ---

The trough between fleet handoffs is not an outage.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_appstream_fleet_trough

WHY (2026-08-31). At 03:01 the watch paged Megan: "Session re-seed needed",
rqst valid 0.1h more, "a report cannot open the console". Every word of that was
true about THIS machine's copy of the token. None of it was actionable:

  01:11  Lucy 2 → handed the fresh token to Lucy 1, Lucy 3
  02:12  Lucy 2 → handed the fresh token to Lucy 1, Lucy 3
  03:01  ⚠️  "Session re-seed needed before the 4am batch"
  03:05  the copy Lucy 1 was holding expires
  03:09  Lucy 2 → handed the fresh token to Lucy 1, Lucy 3

The holder never missed a beat. Only the console-using machine can mint, the
handoff runs hourly, the token lives ~2h — so a consumer is ALWAYS minutes from
expiry somewhere in the trough. Worse, the re-seed being asked for is not
harmless: a fresh login invalidates the token the whole fleet is holding, which
session_holder already warns about in its own log.

So the page belongs to the case the module docstring always named — the MINTER
stopped — and not to a copy that is old on purpose.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from automations.shared import appstream_watch as w


class FleetIsFeedingUsTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name) / ".appstream_donated_token"
        real_marker, real_machine = w._donated_token_marker, w._this_machine
        w._donated_token_marker = lambda: self.marker
        self.addCleanup(setattr, w, "_donated_token_marker", real_marker)
        self.addCleanup(setattr, w, "_this_machine", real_machine)
        self._be("Lucy 1")

    def _be(self, machine):
        w._this_machine = lambda: machine

    def _handoff_landed(self, minutes_ago: float):
        self.marker.write_text("6D16EFDF")
        when = time.time() - minutes_ago * 60
        os.utime(self.marker, (when, when))

    def test_no_machine_is_ever_reported_as_fleet_fed(self):
        """The suppression is OFF for every machine and every marker state.

        Whatever the donation marker says — fresh, stale, absent — the answer is
        the same, because nothing donates a session any more. Enumerated rather
        than asserted once, since the old bug was a suppression firing in a state
        nobody had thought about."""
        for machine in ("Lucy 1", "Lucy 2", "Lucy 3", "", "Newbox"):
            for minutes in (1, 49, 260, None):
                with self.subTest(machine=machine, handoff_min_ago=minutes):
                    self._be(machine)
                    if minutes is None:
                        self.marker.unlink(missing_ok=True)
                    else:
                        self._handoff_landed(minutes)
                    fed, why = w.fleet_is_feeding_us()
                    self.assertFalse(fed, why)
                    self.assertTrue(why.strip(), "must say why it did not suppress")

    def test_a_dead_session_is_never_explained_away_by_another_machine(self):
        """The reason names THIS machine, never a donor.

        This is the whole rule (Megan 2026-09-02: "one machine CANNOT depend on
        another"). A page suppressed — or a failure explained — by the health of
        a different box is how one machine takes the fleet down quietly."""
        self._handoff_landed(1)
        _, why = w.fleet_is_feeding_us()
        self.assertIn("this machine", why.lower())
        for donor_word in ("Lucy 1", "Lucy 2", "Lucy 3", "handed", "handoff"):
            self.assertNotIn(donor_word, why)


if __name__ == "__main__":
    unittest.main()
