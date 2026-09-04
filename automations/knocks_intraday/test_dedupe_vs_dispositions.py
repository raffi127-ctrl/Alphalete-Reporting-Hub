"""An office already getting a dispositions board must not get one from here.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.knocks_intraday.test_dedupe_vs_dispositions

WHY (Megan 2026-09-04). #alphalete-lvl1-chat was getting Raf's knock board
TWICE every weeknight, minutes apart — 2026-09-03 at 21:04 "Knocks &
Dispositions — 9:00 PM" (gap_alerts) and 21:08 "Total Knocks — End of Day —
Rafael" (this module). The de-dupe that was supposed to prevent exactly that
missed it twice over:

  1. It read the sign-up JSON alone, so it could only see offices that enrolled
     through the link. gap_alerts' only live office is Raf, a HARDCODED row in
     gap_alerts/config.py, and the JSON does not exist at all — so the guard
     returned an empty set and dropped nobody.
  2. It compared bare channel ids. Raf's board here goes to #alphalete-sales
     and gap_alerts' goes to #alphalete-lvl1-chat, which are two different
     rooms until you remember everything in #alphalete-sales is mirrored into
     lvl1. The duplicate lands in the MIRROR, so the mirror is what has to be
     checked.

Both halves are asserted here because either one alone still ships the bug.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.knocks_intraday import roster as R

SALES = "C068PH3RFSM"      # #alphalete-sales
LVL1 = "C09JG28CD27"       # #alphalete-lvl1-chat — the mirror of #alphalete-sales


class DedupeSeesBothHalves(unittest.TestCase):

    def test_hardcoded_gap_alerts_offices_count_as_enrolled(self):
        """Raf never came through the sign-up link, and he still owns lvl1."""
        with mock.patch.object(R, "_ONBOARDED_JSON") as p:
            p.read_text.side_effect = FileNotFoundError()   # the real state today
            self.assertIn(LVL1, R.disposition_channels())

    def test_a_disabled_office_does_not_claim_its_channel(self):
        """Calvin and Jay are wired but enabled=False — not posting, so this
        module must keep covering their rooms until someone switches them on."""
        from automations.gap_alerts import config as gap
        off = [c for c in gap.OFFICES if not c.get("enabled", True)]
        self.assertTrue(off, "expected at least one disabled office to exist")
        for cfg in off:
            for d in gap.destinations(cfg):
                if d.get("kind") == "slack" and d.get("channel_id"):
                    self.assertNotIn(d["channel_id"], R.disposition_channels())

    def test_a_mirror_collision_is_reported_but_never_dropped(self):
        """Raf's board goes to #alphalete-sales and gap_alerts' to lvl1, which
        mirrors from it — so lvl1 gets two and #alphalete-sales gets one.
        Dropping him would empty the room that is NOT duplicated, so the
        collision is surfaced and left alone. See mirror_collisions()."""
        o = R.RAF_OFFICE
        self.assertEqual(o.channel_id, SALES)
        with mock.patch.object(R, "disposition_channels", return_value={LVL1}):
            self.assertEqual(R._drop_enrolled([o]), [o])       # kept
            self.assertEqual(R.mirror_collisions([o]), [o])    # and flagged

    def test_an_office_whose_own_channel_is_taken_is_dropped(self):
        """The case the guard is actually for: a sign-up enrollment posting
        into the very channel this module posts into."""
        o = R.RAF_OFFICE
        with mock.patch.object(R, "disposition_channels", return_value={SALES}):
            self.assertEqual(R._drop_enrolled([o]), [])
            self.assertEqual(R.mirror_collisions([o]), [])

    def test_an_unrelated_office_is_never_dropped(self):
        keep = [o for o in R.enrolled("eod") if o.channel_id not in (SALES, LVL1)]
        self.assertTrue(keep, "every office was dropped — the guard is too wide")
        with mock.patch.object(R, "disposition_channels", return_value={LVL1}):
            self.assertEqual(R._drop_enrolled(keep), keep)

    def test_raf_keeps_his_9pm_board(self):
        """Megan put him in this slot on 2026-08-25 and #alphalete-sales is
        where every office's nightly board lands. De-duplicating lvl1 must not
        cost the primary room its only copy."""
        self.assertIn("raf", [o.key for o in R.enrolled("eod")])

    def test_an_unreadable_file_drops_nobody_extra(self):
        """A read that fails must not silently stop a night of boards — a
        duplicate is noise, a board that vanishes is a report nobody notices."""
        with mock.patch.object(R, "disposition_channels", return_value=set()):
            offs = [R.RAF_OFFICE]
            self.assertEqual(R._drop_enrolled(offs), offs)


if __name__ == "__main__":
    unittest.main()
