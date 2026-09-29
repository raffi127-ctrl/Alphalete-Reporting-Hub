"""One sign-up announcement per person, not per click (Jairo, 2026-09-29)."""
import datetime as dt
import unittest
from types import SimpleNamespace as R

from automations.icd_alerts import post as P

NOW = dt.datetime(2026, 9, 29, 19, 20)


def _r(key, at, contact="jairoruizpmg@gmail.com and 3054928175"):
    return R(office_key=key, submitted_at=at, owner="Jairo Ruiz", contact=contact)


class CollapseSignupsTest(unittest.TestCase):
    def test_the_same_row_twice_in_one_tick_is_one(self):
        seen = {}
        go, skip = P.collapse_signups([_r("jairo7", "2026-09-29T19:15:24"), _r("jairo7", "2026-09-29T19:15:24")], seen, NOW)
        self.assertEqual([r.office_key for r in go], ["jairo7"])
        self.assertEqual(len(skip), 1)

    def test_fifteen_clicks_from_one_person_is_one_post(self):
        seen = {}
        rows = [_r("jairo", "2026-09-29T19:00:21")] + [_r("jairo%d" % i, "2026-09-29T19:%02d:00" % (i + 1)) for i in range(2, 16)]
        go, skip = P.collapse_signups(rows, seen, NOW)
        self.assertEqual(len(go), 1)
        self.assertEqual(len(skip), 14)
        self.assertIn("contact|jairoruizpmg@gmail.com", seen)

    def test_a_different_person_still_announces(self):
        seen = {}
        go, _ = P.collapse_signups([_r("jairo", "2026-09-29T19:00:21"), _r("max", "2026-09-29T19:01:00", "max@x.com")], seen, NOW)
        self.assertEqual([r.office_key for r in go], ["jairo", "max"])

    def test_the_same_person_an_hour_later_announces_again(self):
        seen = {"contact|jairoruizpmg@gmail.com": (NOW - dt.timedelta(minutes=61)).isoformat(timespec="seconds")}
        go, skip = P.collapse_signups([_r("jairo2", "2026-09-29T19:19:00")], seen, NOW)
        self.assertEqual(len(go), 1)
        self.assertEqual(skip, [])

    def test_no_contact_means_no_collapse(self):
        go, skip = P.collapse_signups([_r("a", "t1", ""), _r("b", "t2", "")], {}, NOW)
        self.assertEqual(len(go), 2)
