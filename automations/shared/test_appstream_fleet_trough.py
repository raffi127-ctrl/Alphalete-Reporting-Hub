"""The trough between fleet handoffs is not an outage.

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

    def test_the_0301_trough_does_not_page(self):
        """The real one: last handoff 49m ago (02:12), next due at 03:09."""
        self._handoff_landed(49)
        fed, why = w.fleet_is_feeding_us()
        self.assertTrue(fed, why)
        self.assertIn("49m ago", why)

    def test_a_stopped_holder_still_pages(self):
        """The case a human ACTUALLY fixes — nothing has arrived in hours."""
        self._handoff_landed(260)
        fed, why = w.fleet_is_feeding_us()
        self.assertFalse(fed)
        self.assertIn("the holder has stopped", why)

    def test_the_holder_itself_is_never_fleet_fed(self):
        """Lucy 2 mints its own; a dead session THERE is the real page."""
        self._be("Lucy 2")
        self._handoff_landed(1)
        fed, why = w.fleet_is_feeding_us()
        self.assertFalse(fed)
        self.assertIn("IS the AppStream holder", why)

    def test_a_machine_no_handoff_ever_reached_is_not_covered(self):
        """Fail CLOSED: never having been fed is not the same as being fed."""
        self.assertFalse(self.marker.exists())
        fed, why = w.fleet_is_feeding_us()
        self.assertFalse(fed)
        self.assertIn("has ever landed here", why)

    def test_the_grace_is_longer_than_the_handoff_interval(self):
        """Handoffs ran hourly on 2026-08-31; a grace under that would page in
        every single trough, which is the bug this file exists for."""
        self.assertGreater(w.FLEET_HANDOFF_GRACE_MIN, 60.0)


if __name__ == "__main__":
    unittest.main()
