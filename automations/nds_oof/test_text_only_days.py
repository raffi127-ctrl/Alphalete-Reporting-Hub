"""config.TEXT_ONLY_DAYS: a normally-off day (Sunday 2026-11-22) runs the
board + 15-min gaps as TEXTS only, inside its own hours."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.nds_oof import config as C
from automations.nds_oof import run as R

SUNDAY = dt.date(2026, 11, 22)
OVER = [{"name": "A B", "minutesSinceLastKnock": 40}]
ROWS = [{"Rep": "A B", "Total Knocks": "12"}]


class Window(unittest.TestCase):
    def test_sunday_opens_only_on_its_date_and_hours(self):
        with mock.patch.object(C, "TEXT_ONLY_DAYS", {"2026-11-22": ((12, 0), (17, 30))}):
            self.assertTrue(R.in_window(dt.datetime(2026, 11, 22, 12, 0)))
            self.assertTrue(R.in_window(dt.datetime(2026, 11, 22, 17, 30, 40)))   # the 5:30 tick
            self.assertFalse(R.in_window(dt.datetime(2026, 11, 22, 17, 31)))
            self.assertFalse(R.in_window(dt.datetime(2026, 11, 22, 11, 59)))
            self.assertFalse(R.in_window(dt.datetime(2026, 11, 29, 14, 0)))        # next Sunday: off
            self.assertTrue(R.text_only(SUNDAY))
            self.assertFalse(R.text_only(dt.date(2026, 11, 23)))
            # A normal day keeps its own hours.
            self.assertTrue(R.in_window(dt.datetime(2026, 11, 23, 13, 30)))
            self.assertFalse(R.in_window(dt.datetime(2026, 11, 23, 13, 29)))


def _tick(now, *, text_only_days):
    """Run one sending tick with every outside call faked; return what went where."""
    sent = {"slack": [], "texts": [], "other": []}
    tmp = Path(tempfile.mkdtemp())

    def fake_render(rows, today, now_, out_dir, extra_columns=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / ("total_knocks_%s.png" % today.isoformat())
        p.write_bytes(b"png")
        return [p]

    def no(name):
        return lambda *a, **k: sent["other"].append(name)

    with mock.patch.object(C, "TEXT_ONLY_DAYS", text_only_days), \
         mock.patch.object(R, "OUTPUT_DIR", tmp), \
         mock.patch.object(R, "_state", lambda: {}), \
         mock.patch.object(R, "_save", lambda st: None), \
         mock.patch.object(R, "_week_due", lambda st, n: True), \
         mock.patch.object(R, "_week_monday_due", lambda st, n: False), \
         mock.patch.object(R, "weekly_board", no("weekly_board")), \
         mock.patch.object(R, "wait_for_fresh_share", lambda *a, **k: None), \
         mock.patch.object(R, "pull", lambda today, **k: (list(OVER), list(ROWS))), \
         mock.patch.object(R, "borrowed_rows", lambda today, own: []), \
         mock.patch.object(R, "render_board", fake_render), \
         mock.patch.object(R, "_post_board", lambda *a, **k: sent["slack"].append("board")), \
         mock.patch.object(R, "_post_gaps", lambda *a, **k: sent["slack"].append("gaps")), \
         mock.patch.object(R, "_queue_text", lambda kind, *a, **k: sent["texts"].append(kind)), \
         mock.patch.object(R, "_callout", lambda *a, **k: (sent["other"].append("callout") or "")), \
         mock.patch.object(R, "_no_dispo_message",
                           lambda *a, **k: (sent["other"].append("no_dispo") or "")), \
         mock.patch.object(R, "gps_check", no("gps")), \
         mock.patch("automations.owner_knocks_hourly.share.share", lambda *a, **k: None), \
         mock.patch.object(R, "_log"):
        rc = R.tick(send=True, force=False, board=False, now=now)
    return rc, sent


class TextOnlyTick(unittest.TestCase):
    def test_sunday_texts_board_and_gaps_and_nothing_else(self):
        rc, sent = _tick(dt.datetime(2026, 11, 22, 13, 15, 5),
                         text_only_days={"2026-11-22": ((12, 0), (17, 30))})
        self.assertEqual(rc, 0)
        self.assertEqual(sent["slack"], [], "a text-only day must not post to Slack")
        self.assertEqual(sent["other"], [], "no call-out / no-dispo / GPS / weekly board")
        want = [C.KIND_BOARD, C.KIND_GAPS] + ([C.KIND_BOARD_30] if C.BOARD_30_TEST else [])
        self.assertEqual(sorted(sent["texts"]), sorted(want))

    def test_a_normal_day_still_posts_to_slack(self):
        rc, sent = _tick(dt.datetime(2026, 11, 23, 14, 0, 5), text_only_days={})
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(sent["slack"]), ["board", "gaps"])
        self.assertIn(C.KIND_GAPS, sent["texts"])
        self.assertIn("callout", sent["other"])


if __name__ == "__main__":
    unittest.main()
