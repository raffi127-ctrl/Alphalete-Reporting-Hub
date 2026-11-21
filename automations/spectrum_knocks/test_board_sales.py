"""#alphalete-sales gets the Spectrum board every 30 min, on Raf's board hours.

Raf 2026-11-21: "Can we also post it in the [Alphalete] Sales channel at
whatever cadence the other Knocking report is posting" -- his ECO Knocks &
Dispositions board, every 30 min inside icd_alerts/offices.py "raf" hours.
No network: pull, render and Slack are all stubbed.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import offices as O
from automations.spectrum_knocks import board as B

WED, SAT, SUN = 18, 21, 22          # November 2026


def at(h, m, day=WED):
    return dt.datetime(2026, 11, day, h, m)


class SalesDue(unittest.TestCase):
    def key(self, now):
        s = B.sales_due(now, set())
        return s and s.key

    def test_weekday_every_30_inside_his_hours(self):
        # Raf's weekday board hours: 1:30 PM - 10:00 PM (end inclusive, like ECO).
        self.assertIsNone(self.key(at(13, 29)))
        self.assertEqual(self.key(at(13, 30)), "s1330")
        self.assertEqual(self.key(at(13, 59)), "s1330")
        self.assertEqual(self.key(at(14, 0)), "s1400")
        self.assertEqual(self.key(at(22, 5)), "s2200")
        self.assertIsNone(self.key(at(22, 30)))

    def test_saturday_stops_at_6pm(self):
        # Sat 10:45 AM start; ECO caps every Saturday board at 6 PM.
        self.assertIsNone(self.key(at(10, 50, SAT)))   # 10:30 anchor is before 10:45
        self.assertEqual(self.key(at(11, 0, SAT)), "s1100")
        self.assertEqual(self.key(at(18, 10, SAT)), "s1800")
        self.assertIsNone(self.key(at(18, 30, SAT)))

    def test_never_sunday(self):
        self.assertIsNone(self.key(at(15, 0, SUN)))

    def test_posted_anchor_is_not_owed_again(self):
        self.assertIsNone(B.sales_due(at(14, 40), {"2026-11-18|sales|1430"}))

    def test_labels(self):
        self.assertEqual(B.sales_due(at(14, 0), set()).label, "First Knocks")
        self.assertEqual(B.sales_due(at(14, 30), set()).label, "Live")
        self.assertEqual(B.sales_due(at(15, 0), set()).label, "Live")

    def test_follows_rafs_office_hours(self):
        later = O.OFFICES["raf"]._replace(day_start="15:00")
        with mock.patch.dict(O.OFFICES, {"raf": later}):
            self.assertIsNone(self.key(at(14, 30)))
            self.assertEqual(self.key(at(15, 0)), "s1500")


ROWS = [{"Rep": "A", "Doors": 30, "Assigned Houses": 50, "Sold": 1, "Mobile Sold": 0,
         "Presentation (No Sale)": 2, "First Door": "11:02 AM"}]


class Tick(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.posts, self.pulls = [], []
        self.rows = ROWS
        self.fail_sales = False

        def fake_post(png, caption, channel):
            if channel == B.SALES_CHANNEL_ID and self.fail_sales:
                raise RuntimeError("not_in_channel")
            self.posts.append((channel, caption, png.name))

        def fake_pull(day):
            self.pulls.append(day)
            return self.rows

        for p in (mock.patch.object(B, "STATE_PATH", self.tmp / "posted.json"),
                  mock.patch.object(B, "OUT_DIR", self.tmp),
                  mock.patch.object(B, "render", lambda rows, sub, out: out),
                  mock.patch.object(B, "post", fake_post),
                  mock.patch.object(B.pull, "run", fake_pull)):
            p.start()
            self.addCleanup(p.stop)

    def tick(self, now, *extra):
        with mock.patch.object(B, "_now", return_value=now):
            return B.main(["--tick", "--send", *extra])

    def channels(self):
        return [c for c, _, _ in self.posts]

    def test_top_of_hour_both_channels_one_pull(self):
        self.tick(at(14, 2))
        self.assertEqual(self.channels(), [B.CHANNEL_ID, B.SALES_CHANNEL_ID])
        self.assertEqual(len(self.pulls), 1)
        knock_cap, sales_cap = self.posts[0][1], self.posts[1][1]
        self.assertIn("Full sheet", knock_cap)
        self.assertNotIn("docs.google.com", sales_cap)     # whole sales floor
        self.assertEqual(self.posts[0][2], self.posts[1][2])  # same First Knocks picture

    def test_half_hour_is_sales_only_and_once(self):
        self.tick(at(14, 2))
        self.posts.clear()
        self.tick(at(14, 31))
        self.assertEqual(self.channels(), [B.SALES_CHANNEL_ID])
        self.assertIn("· Live ·", self.posts[0][1])
        self.posts.clear()
        self.tick(at(14, 36))
        self.assertEqual(self.posts, [])

    def test_before_his_hours_knocking_channel_only(self):
        self.tick(at(11, 0))
        self.assertEqual(self.channels(), [B.CHANNEL_ID])

    def test_test_run_to_a_dm_never_reaches_sales(self):
        self.tick(at(14, 2), "--to", "D087ZGE2B0F")
        self.assertEqual(self.channels(), ["D087ZGE2B0F"])

    def test_no_doors_posts_nothing_anywhere(self):
        self.rows = [{"Rep": "A", "Doors": 0, "Assigned Houses": 50}]
        self.tick(at(14, 2))
        self.assertEqual(self.posts, [])
        self.rows = ROWS
        self.tick(at(14, 7))                 # skipped slot is not retried
        self.assertEqual(self.posts, [])

    def test_sales_failure_retries_only_sales(self):
        self.fail_sales = True
        with self.assertRaises(RuntimeError):
            self.tick(at(14, 2))
        self.assertEqual(self.channels(), [B.CHANNEL_ID])
        self.fail_sales = False
        self.posts.clear()
        self.tick(at(14, 7))
        self.assertEqual(self.channels(), [B.SALES_CHANNEL_ID])


if __name__ == "__main__":
    unittest.main()
