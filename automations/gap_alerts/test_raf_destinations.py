"""Raf's boards come from HIS OWN MACHINE since 2026-11-03 — Lucy 1 posts none.

Megan 2026-11-03: "do the switch so Raf's is now running on his own machine"
and, before it, "CHANGE NOTHING for how raf's things are posted". The three
rooms this file used to pin (Knocking Chat A-Players every 30, #alphalete-lvl1-
chat every 30 in one thread a day, #alphalete-sales every 30 loose — Raf
2026-09-01 / 09-18 / 09-28 / 10-24) moved unchanged onto his Office Channels
row for the Lucy ECO poster (see project_raf_eco_enrollment). What this file
pins now is the other half of that move: nothing here may post for Raf, or
every board lands twice.

The history of those three rooms stays as a comment beside RAF["destinations"]
in config.py, so undoing the cutover is one edit.
"""
import unittest

from automations.gap_alerts import config as C


class RafsDestinations(unittest.TestCase):
    def test_lucy_1_runs_nothing_for_raf(self):
        self.assertIs(C.RAF.get("enabled"), False,
                      "Raf's boards come from his own machine now; enabled "
                      "here posts every board twice")
        self.assertEqual(C.RAF["destinations"], [])
        live = [o["key"] for o in C.OFFICES if o.get("enabled", True)]
        self.assertNotIn("rafael", live,
                         "an empty destinations list still falls back to the "
                         "group at the tick cadence; only enabled=False stops it")

    def test_the_old_rooms_are_kept_as_a_comment_for_the_undo(self):
        import inspect
        src = inspect.getsource(C)
        for room in ("Knocking Chat A-Players", "SLACK_HOURLY_CHANNEL",
                     "C068PH3RFSM"):
            self.assertIn(room, src)


if __name__ == "__main__":
    unittest.main()
