"""The push-report DM says times the way a person says them, and says them short.

Run:  PYTHONPATH=. python3 -m unittest \
          automations.push_report.test_line_format

WHAT THIS GUARDS (Raf, 2026-09-25: "this dm needs to not be military time and
shortened up"). Every line of the hourly DM ended in a 24-hour as-of:

    Carlos 11580: 30 pushed today | 7 left in OAT (as of 20:33)

The header right above it already read "Push report 8:37 PM", so the military
time was not a house-style choice — it was an accident of plumbing. `at` was a
RAW SLICE of the diag tab's timestamp cell, `rows[-1][0][11:16]` on
'2026-09-24 20:33:12'. It was never a datetime, so nothing ever formatted it,
and it simply inherited however the Sheet stored it. `_hm12` formats it now.

The same pass took the two other clocks in the file, both easy to miss because
neither shows up in a healthy run: the ":warning: walk may be down" line was
also 24-hour, and the header reached 12-hour via the no-pad hour flag, which is
glibc/BSD-only and which `report_validation._chk_windows` rejects on sight
(CLAUDE.md: every report runs on macOS AND Windows). Both go through `_hm12`.

Note `_chk_windows` scans RAW TEXT, so this file and run.py both avoid writing
that flag literally, even inside a comment — it would trip the gate from a
docstring just as happily as from code.
"""
from __future__ import annotations

import datetime as dt
import re
import unittest
from pathlib import Path

from automations.push_report import run as pr


class TheClock(unittest.TestCase):
    def test_afternoon_drops_to_twelve_hour(self):
        self.assertEqual(pr._hm12("20:33"), "8:33 PM")

    def test_midnight_and_noon(self):
        """The two hours a `% 12` gets wrong if you forget the `or 12`."""
        self.assertEqual(pr._hm12("00:05"), "12:05 AM")
        self.assertEqual(pr._hm12("12:00"), "12:00 PM")

    def test_hour_is_unpadded_and_minute_is_padded(self):
        self.assertEqual(pr._hm12("08:15"), "8:15 AM")

    def test_garbage_passes_through(self):
        """A diag row with a malformed stamp must not take the DM down."""
        self.assertEqual(pr._hm12("not a time"), "not a time")


class TheLine(unittest.TestCase):
    """Render the real thing against a stub Sheet — no network, no Slack."""

    def _render(self, now: dt.datetime) -> str:
        stamp = now.strftime("%Y-%m-%d")
        rows = {
            "OAT Walk Diag":       ("20:33", "120 -> 7",   30),
            "OAT Walk Diag 23467": ("20:36", "29 -> 2",    27),
            "OAT Walk Diag 11901": ("20:29", "111 -> 2",  109),
            "OAT Walk Diag 11280": ("20:21", "148 -> 114", 34),
            "OAT Walk Diag 23965": ("20:28", "33 -> 33",    0),
            "OAT Walk Diag 24065": ("20:34", "60 -> 36",   24),
        }

        class _WS:
            def __init__(self, tab):
                self.tab = tab

            def get_all_values(self):
                at, queue, sent = rows[self.tab]
                return [["%s %s:00" % (stamp, at), queue, "", "",
                         "sent=%d" % sent]]

        class _SH:
            def worksheet(self, tab):
                return _WS(tab)

        class _Client:
            def open_by_key(self, key):
                return _SH()

        from automations.recruiting_report import fill as _fill
        real_client, real_dt = _fill._client, pr.dt

        class _DT:
            datetime = type("D", (), {
                "now": staticmethod(lambda: now),
                "strptime": staticmethod(dt.datetime.strptime),
            })
            date = dt.date

        _fill._client = lambda: _Client()
        pr.dt = _DT
        try:
            return pr.build_report()
        finally:
            _fill._client, pr.dt = real_client, real_dt

    def test_exact_message(self):
        got = self._render(dt.datetime(2026, 9, 24, 20, 37))
        self.assertEqual(got, "\n".join([
            "*Push report 8:37 PM*",
            "Carlos 11580: 30 pushed · 7 left @ 8:33 PM",
            "Atef 23467: 27 pushed · 2 left @ 8:36 PM",
            "Khalil 11901: 109 pushed · 2 left @ 8:29 PM",
            "Raf main 11280: 34 pushed · 114 left @ 8:21 PM",
            "Raf 2nd funnel 23965: 0 pushed · 33 left @ 8:28 PM",
            "Raf 24065: 24 pushed · 36 left @ 8:34 PM",
        ]))

    def test_no_military_time_anywhere_in_the_message(self):
        """'20:33' style must not survive in ANY line, header included."""
        got = self._render(dt.datetime(2026, 9, 24, 20, 37))
        self.assertNotRegex(got, r"\b([01]\d|2[0-3]):[0-5]\d\b(?!\s*[AP]M)")
        self.assertNotIn("(as of", got)

    def test_the_words_raf_asked_us_to_drop(self):
        got = self._render(dt.datetime(2026, 9, 24, 20, 37))
        for gone in ("pushed today", "left in OAT", "as of"):
            self.assertNotIn(gone, got)
        self.assertIn("30 pushed · 7 left @", got)


class TheWindowsGate(unittest.TestCase):
    def test_module_passes_the_repo_validation_gate(self):
        """_chk_windows scans raw text — a comment trips it too."""
        from automations.shared import report_validation as rv
        src = Path(pr.__file__).read_text()
        ok, why = rv._chk_windows(src, {})
        self.assertTrue(ok, why)

    def test_no_nopad_hour_flag_in_source(self):
        """Built by hand instead; this is the thing that breaks on Windows."""
        src = Path(pr.__file__).read_text()
        self.assertIsNone(re.search(r"%-[IdmHejlpSMy]", src))


if __name__ == "__main__":
    unittest.main()
