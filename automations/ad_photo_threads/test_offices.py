"""Every office on its own clock and its own channels (Eve 2026-09-23).

    python -m unittest automations.ad_photo_threads.test_offices
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from automations.ad_photo_threads import config, run


def _office(key, tz, live=True):
    return {"key": key, "owner": key.title(), "tz": tz, "live": live,
            "sheet_id": f"sheet-{key}", "source_channel": f"SRC-{key}",
            "live_channel": f"LIVE-{key}", "paused_before": "", "sources": []}


class OfficesTest(unittest.TestCase):
    def setUp(self):
        self._saved = (config.SHEET_ID, config.SOURCE_CHANNEL_ID,
                       config.LIVE_CHANNEL_ID, config.NIGHTLY_PAUSED_BEFORE,
                       config.SOURCES)

    def tearDown(self):
        (config.SHEET_ID, config.SOURCE_CHANNEL_ID, config.LIVE_CHANNEL_ID,
         config.NIGHTLY_PAUSED_BEFORE, config.SOURCES) = self._saved

    def test_rafael_entry_is_the_old_globals(self):
        raf = config.office("rafael")
        self.assertEqual(raf["live_channel"], "C0C3LCLKZTN")
        self.assertEqual(raf["source_channel"], "C0AUAS88FGW")
        self.assertIs(raf["sources"], config.SOURCES)

    def test_every_office_has_its_own_channels(self):
        live = [o["live_channel"] for o in config.OFFICES]
        self.assertEqual(len(live), len(set(live)))
        for o in config.OFFICES:
            self.assertNotEqual(o["live_channel"], o["source_channel"], o["key"])

    def test_use_points_the_globals_at_the_office(self):
        config.use(config.office("carlos"))
        self.assertEqual(config.LIVE_CHANNEL_ID, "C0C3XGN541G")
        self.assertEqual(config.SOURCE_CHANNEL_ID, "C09L1S3MQ1E")
        self.assertEqual(config.SOURCES[0]["tab"], "Carlos Hidalgo")

    def test_eastern_offices_are_not_on_central(self):
        for key, zone in [("salik", "America/Detroit"), ("samuel", "America/New_York"),
                          ("aya", "America/Indiana/Indianapolis")]:
            self.assertEqual(config.office_zone(config.office(key)), zone, key)

    def test_carlos_thread_wording(self):
        rx = config.office("carlos")["sources"][0]["thread_re"]
        self.assertTrue(rx.search(":wolf:*ALPHALETE MARKETING - 1st ROUNDS - SEPTEMBER 23rd*:wolf:"))
        self.assertFalse(rx.search(":wolf:*EOD: 09/22- Interviewer's Daily Report - Alphalete*:wolf:"))

    def _tick(self, offices, now_utc):
        ran = []

        class _Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return now_utc.astimezone(tz)

        with mock.patch.object(config, "OFFICES", offices), \
                mock.patch.object(run.dt, "datetime", _Clock), \
                mock.patch("automations.ad_photo_threads.post.day_done",
                           side_effect=lambda ch, day: ran.append((ch, day)) or True):
            run.nightly()
        return ran

    def test_each_office_waits_for_its_own_430(self):
        # Wed 9/23 4:45 PM Central = 5:45 PM Eastern = 2:45 PM Pacific.
        now = dt.datetime(2026, 9, 23, 16, 45, tzinfo=ZoneInfo("America/Chicago"))
        ran = self._tick([_office("east", "America/New_York"),
                          _office("central", "America/Chicago"),
                          _office("west", "America/Los_Angeles")], now)
        self.assertEqual([ch for ch, _ in ran], ["LIVE-east", "LIVE-central"])
        self.assertEqual(ran[0][1], dt.date(2026, 9, 23))

    def test_offices_not_live_are_skipped(self):
        now = dt.datetime(2026, 9, 23, 18, 0, tzinfo=ZoneInfo("America/Chicago"))
        ran = self._tick([_office("on", "America/Chicago"),
                          _office("off", "America/Chicago", live=False)], now)
        self.assertEqual([ch for ch, _ in ran], ["LIVE-on"])

    def test_one_office_failing_does_not_stop_the_next(self):
        now = dt.datetime(2026, 9, 23, 18, 0, tzinfo=ZoneInfo("America/Chicago"))
        seen = []

        def done(ch, day):
            seen.append(ch)
            if ch == "LIVE-a":
                raise RuntimeError("boom")
            return True

        class _Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz)

        with mock.patch.object(config, "OFFICES", [_office("a", "America/Chicago"),
                                                   _office("b", "America/Chicago")]), \
                mock.patch.object(run.dt, "datetime", _Clock), \
                mock.patch("automations.ad_photo_threads.post.day_done", side_effect=done):
            rc = run.nightly()
        self.assertEqual(seen, ["LIVE-a", "LIVE-b"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
