"""A room never sees the same gif twice in a day (Megan, 2026-09-21: "2 gifs
so far and they've been the exact same one")."""
import datetime as dt
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.shared import sale_hype as H


class NoRepeatGifTest(unittest.TestCase):
    DAY = dt.date(2026, 9, 21)

    def setUp(self):
        self.path = pathlib.Path(tempfile.mkdtemp()) / "gifs.json"
        self.p = mock.patch.object(H, "GIFS_SENT_PATH", self.path)
        self.p.start()
        H._PENDING_GIFS.clear()

    def tearDown(self):
        self.p.stop()

    def _post(self, room, gif):
        out, used = H.within_budget(["WINNER\n" + gif], self.DAY, room)
        H.record_gifs(self.DAY, room, used)
        return out[0].split("\n", 1)[1]

    def test_the_same_pick_twice_comes_out_different(self):
        g = H.HYPE_GIFS[0]
        first, second = self._post("raf", g), self._post("raf", g)
        self.assertEqual(first, g)
        self.assertNotEqual(first, second)

    def test_three_in_one_post_are_all_different(self):
        g = H.HYPE_GIFS[4]
        out, _ = H.within_budget(["A\n" + g, "B\n" + g, "C\n" + g], self.DAY, "raf")
        self.assertEqual(len({l.split("\n")[1] for l in out}), 3)

    def test_another_room_is_not_affected(self):
        g = H.HYPE_GIFS[2]
        self._post("raf", g)
        self.assertEqual(self._post("aya", g), g)

    def test_yesterdays_last_gif_is_not_first_today(self):
        g = H.HYPE_GIFS[1]
        H.within_budget(["A\n" + g], self.DAY - dt.timedelta(days=1), "raf")
        H.record_gifs(self.DAY - dt.timedelta(days=1), "raf", 1)
        self.assertNotEqual(self._post("raf", g), g)

    def test_a_dry_run_spends_nothing(self):
        g = H.HYPE_GIFS[3]
        H.within_budget(["A\n" + g], self.DAY, "raf")   # rendered, never sent
        H._PENDING_GIFS.clear()
        self.assertEqual(self._post("raf", g), g)


if __name__ == "__main__":
    unittest.main()
