"""Pins the bulletins' auto-approval on no-review days (Eve 2026-10-13 trip).

A gap does NOT hold (Eve backfills it on the manual tab the week after): it
sends and is named once in the thread. Only the wrong week or a hard_block
holds, with ONE note. Slack and the data layer are faked — nothing here
touches the network.

Run:  python -m unittest automations.override_bulletin.test_no_review_auto_approval
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.override_bulletin import override_gate as OG
from automations.override_bulletin import review_gate as RG
from automations.shared import weekend_release as wr

THU = dt.date(2026, 10, 15)
NEXT_THU = dt.date(2026, 10, 22)
POST = {"ts": "1.0", "text": "post"}


class Notes(unittest.TestCase):
    """Both thread notes faked, so a test can never reach Slack."""

    def notes(self):
        self.held, self.sent_with = [], []
        return (
            mock.patch.object(RG, "held_note_once",
                              side_effect=lambda m, r, c=None:
                              self.held.append(r)),
            mock.patch.object(RG, "overlooked_note_once",
                              side_effect=lambda m, r, c=None:
                              self.sent_with.append(r)),
        )


class DD(Notes):
    def go(self, day, d, post=POST):
        a, b = self.notes()
        with a, b, \
                mock.patch.object(RG, "_find_post", return_value=post), \
                mock.patch.object(RG, "build_preview", return_value=([], d)):
            return RG.auto_approval(day)

    def data(self, **kw):
        d = {"weeks": [RG.week_label(THU)], "hard_block": [], "blocking": []}
        d.update(kw)
        return d

    def test_complete_week_sends_itself(self):
        self.assertEqual(self.go(THU, self.data()), (wr.AUTO_ID, RG.AUTO_WHO))
        self.assertEqual((self.held, self.sent_with), ([], []))

    def test_a_gap_sends_anyway_and_is_named(self):
        who = self.go(THU, self.data(blocking=["Credico missing"]))
        self.assertEqual(who, (wr.AUTO_ID, RG.AUTO_WHO))
        self.assertEqual(self.held, [])
        self.assertIn("Credico missing", self.sent_with[0])

    def test_a_hard_block_holds_with_a_note(self):
        self.assertIsNone(self.go(THU, self.data(hard_block=["week empty"])))
        self.assertIn("week empty", self.held[0])

    def test_wrong_week_holds(self):
        self.assertIsNone(self.go(THU, self.data(weeks=["10.4.26"])))
        self.assertIn("newest week", self.held[0])

    def test_nothing_posted_yet_waits_quietly(self):
        self.assertIsNone(self.go(THU, self.data(), post=None))
        self.assertEqual(self.held, [])

    def test_a_normal_thursday_never_auto_approves(self):
        self.assertIsNone(self.go(NEXT_THU, self.data()))


class Override(Notes):
    def go(self, wk_now, gaps, today=dt.date(2026, 10, 16)):
        a, b = self.notes()
        fake_dt = mock.Mock(wraps=dt.datetime)
        fake_dt.now.return_value = dt.datetime.combine(today, dt.time(10))
        with a, b, \
                mock.patch.object(OG.dt, "datetime", fake_dt), \
                mock.patch.object(OG, "_find_post", return_value=POST), \
                mock.patch.object(OG, "build_preview",
                                  return_value=(None, wk_now, gaps)):
            return OG.auto_approval("10.11.26")

    def test_complete_week_sends_itself(self):
        self.assertEqual(self.go("10.11.26", []), (wr.AUTO_ID, RG.AUTO_WHO))

    def test_a_gap_sends_anyway_and_is_named(self):
        self.assertEqual(self.go("10.11.26", ["Carlos"]),
                         (wr.AUTO_ID, RG.AUTO_WHO))
        self.assertIn("Carlos", self.sent_with[0])

    def test_the_wrong_week_holds(self):
        self.assertIsNone(self.go("10.4.26", []))
        self.assertIn("newest week", self.held[0])

    def test_a_normal_friday_never_auto_approves(self):
        self.assertIsNone(self.go("10.11.26", [], today=dt.date(2026, 10, 23)))


if __name__ == "__main__":
    unittest.main()
