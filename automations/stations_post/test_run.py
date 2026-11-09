import datetime as dt
import unittest

from automations.stations_post import run as R

# Same shape as the live tab on 2026-11-05: a labeled block, a station with no
# names, titled rooms with no names past it, then an unrelated table on the
# right sharing the same rows, and reference lists underneath.
GRID = [
    ["", "Trainers", "Week 1's", "", "Late Obj", "", "", "", "Leaders Meetings"],
    ["Where? ", "Fishbowl", "Fishbowl", "Fishbowl", "Fishbowl", "Chicago", "CF Room", "", "Monday"],
    ["Timing", "10:30", "10:30", "10:30", "10:30", "10:30", "10:30", "", "Tuesday"],
    ["Running it ", "", "", "", "", "", "", "", "Wednesday"],
    ["1", "Ana", "Bryson", "", "", "", "", "", "Thursday"],
    ["3", "", "", "", "", "", "", "", "WK2"],
    ["4", "Willie", "", "", "", "", "", "", ""],
    ["5", "", "", "", "", "", "", "", ""],
    ["", "Shift+Command+V = Paste without Formula"],
    ["", "Rep names from \nSales Board", "FFP", "New Starts", "Roadtrips"],
    ["", "Andrew", "", "Laiza", "Aniyah"],
]


class FindBoxTest(unittest.TestCase):
    def test_stops_at_last_name_not_at_titles_or_side_tables(self):
        self.assertEqual(R.find_box(GRID), (7, 3))

    def test_empty_numbered_row_inside_the_block_stays(self):
        grid = [list(r) for r in GRID]
        grid[7][1] = "Jacari"      # row 8 gets a name; row 6 is empty in the middle
        self.assertEqual(R.find_box(grid), (8, 3))

    def test_leader_with_no_reps_keeps_the_station(self):
        grid = [list(r) for r in GRID]
        grid[3][4] = "Aundre"      # 'Running it' in col E
        self.assertEqual(R.find_box(grid), (7, 5))

    def test_road_trip_station_is_cut_leader_included(self):
        grid = [list(r) for r in GRID]
        grid[3][4] = "Lakeaih"     # leader of the road-trip station
        grid[4][4] = "aniyah "     # on the Roadtrips list, spacing/case aside
        self.assertEqual(R.find_box(grid), (7, 3))

    def test_one_office_rep_keeps_the_station(self):
        grid = [list(r) for r in GRID]
        grid[4][4] = "Aniyah"
        grid[5][4] = "Wendy"
        self.assertEqual(R.find_box(grid), (7, 5))

    def test_no_roadtrips_list_raises_instead_of_leaking(self):
        grid = [list(r) for r in GRID]
        grid[9] = ["", "Rep names", "FFP", "New Starts", "Off"]
        with self.assertRaises(SystemExit) as e:
            R.find_box(grid)
        self.assertIn("Roadtrips", str(e.exception))

    def test_no_rep_names_never_posts(self):
        grid = ([list(r) for r in GRID[:4]] + [["1", "", ""], ["3", "", ""]]
                + [["", "Roadtrips"], ["", "Aniyah"]])
        grid[3][1] = "Leader Only"
        with self.assertRaises(SystemExit) as e:
            R.find_box(grid)
        self.assertIn("no rep names", str(e.exception))

    def test_template_change_raises_instead_of_guessing(self):
        with self.assertRaises(SystemExit):
            R.find_box([r for r in GRID if r[0] != "Where? "])

    def test_caption(self):
        self.assertEqual(R.caption(dt.date(2026, 11, 5)), "Stations - Thursday 11/5")



class _FakeSmp:
    """Stand-in for slack_metrics_post: upload always 'ok', landing scripted."""
    def __init__(self, landings):
        self.landings = list(landings)
        self.uploads = 0

    def post_reply_with_image(self, png, **kw):
        self.uploads += 1
        return {"ok": True, "file": "F%d" % self.uploads}

    def _client(self):
        return None

    def file_landed_in_channel(self, client, file_id, channel_id, comment=""):
        return self.landings.pop(0)


class SlackLandingTest(unittest.TestCase):
    def test_seen_first_time_uploads_once(self):
        smp = _FakeSmp([True])
        self.assertTrue(R._post_slack(smp, R.Path("x.png"), "c", send=True))
        self.assertEqual(smp.uploads, 1)

    def test_missing_ok_upload_is_retried_once(self):
        # 2026-11-09: ok + file id, never in the channel
        smp = _FakeSmp([False, True])
        self.assertTrue(R._post_slack(smp, R.Path("x.png"), "c", send=True))
        self.assertEqual(smp.uploads, 2)

    def test_missing_twice_is_a_miss(self):
        smp = _FakeSmp([False, False])
        self.assertIs(R._post_slack(smp, R.Path("x.png"), "c", send=True), False)
        self.assertEqual(smp.uploads, 2)

    def test_cant_read_channel_is_not_a_miss_and_no_double_post(self):
        smp = _FakeSmp([None])
        self.assertIsNone(R._post_slack(smp, R.Path("x.png"), "c", send=True))
        self.assertEqual(smp.uploads, 1)


class ChannelLandedTest(unittest.TestCase):
    class _C:
        def __init__(self, msgs=None, boom=False):
            self.msgs, self.boom = msgs or [], boom
        def conversations_history(self, **kw):
            if self.boom:
                raise RuntimeError("no scope")
            return {"messages": self.msgs}

    def test_found_by_file_id(self):
        from automations.shared import slack_metrics_post as smp
        c = self._C([{"text": "", "files": [{"id": "F1"}]}])
        self.assertTrue(smp.file_landed_in_channel(c, "F1", "C", tries=1))

    def test_absent_is_false(self):
        from automations.shared import slack_metrics_post as smp
        c = self._C([{"text": "other", "files": [{"id": "F9"}]}])
        self.assertIs(smp.file_landed_in_channel(c, "F1", "C", tries=2, delay=0), False)

    def test_unreadable_is_none(self):
        from automations.shared import slack_metrics_post as smp
        self.assertIsNone(smp.file_landed_in_channel(self._C(boom=True), "F1", "C",
                                                     tries=2, delay=0))

if __name__ == "__main__":
    unittest.main()
