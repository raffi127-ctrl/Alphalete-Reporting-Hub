import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.shared import rep_asides as RA


class EveryThirdMention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(RA, "STATE_PATH", Path(self.tmp.name) / "s.json")
        self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def test_third_mention_fires_then_sixth(self):
        hits = [bool(RA.due("ao-board", "Pranish Shrestha")) for _ in range(7)]
        self.assertEqual(hits, [False, False, True, False, False, True, False])

    def test_other_reps_and_rooms_never(self):
        for _ in range(6):
            self.assertIsNone(RA.due("ao-board", "Aaron Corona"))
            self.assertIsNone(RA.due("some-other-room", "Pranish Shrestha"))

    def test_rooms_count_separately_and_dry_runs_do_not_spend(self):
        RA.due("ao-board", "Pranish Shrestha"); RA.due("ao-board", "Pranish Shrestha")
        self.assertIsNone(RA.due("rafael-gaps", "PRANISH SHRESTHA"))      # its own count
        # A dry run previews the NEXT mention without spending it: twice.
        self.assertTrue(RA.due("ao-board", "Pranish Shrestha", remember=False))
        self.assertTrue(RA.due("ao-board", "Pranish Shrestha", remember=False))
        self.assertTrue(RA.due("ao-board", "Pranish Shrestha"))           # the real third
        self.assertIsNone(RA.due("ao-board", "Pranish Shrestha"))         # the fourth

    def test_rule_carries_the_tag_and_the_aside(self):
        RA.due("ao-board", "pranish shrestha"); RA.due("ao-board", "pranish shrestha")
        rule = RA.due("ao-board", "pranish shrestha")
        self.assertEqual(rule["tag"], "YN")
        self.assertEqual(rule["aside"], "Don't Tell Megan 🤫")


class TheTagFollowsTheName(unittest.TestCase):
    def test_name_stays_tag_follows(self):
        self.assertEqual(RA.tag_name("Pranish is on the board :fire:", "Pranish", "YN"),
                         "Pranish YN is on the board :fire:")
        self.assertEqual(RA.tag_name("SOMEBODY STOP PRANISH", "Pranish", "YN"),
                         "SOMEBODY STOP PRANISH YN")
        self.assertEqual(RA.tag_name("Pranish Shrestha - 36 min", "Pranish Shrestha", "YN"),
                         "Pranish Shrestha YN - 36 min")

    def test_no_name_no_change(self):
        self.assertEqual(RA.tag_name("Aaron is on the board", "Pranish", "YN"), "Aaron is on the board")


if __name__ == "__main__":
    unittest.main()
