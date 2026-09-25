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

    def _render(self, now: dt.datetime, paused=frozenset(),
                skip_rows=()) -> str:
        """`paused` is STUBBED, never read from applicant_push.

        It has to be. The real _paused_offices() reads ROTATION_BY_MACHINE,
        which Carlos edits as he turns offices on and off — twice on
        2026-09-25 alone. A render test that consulted it would assert on his
        current rotation and start failing the next time he flips one, having
        caught no bug at all. `skip_rows` drops an office's diag rows, for the
        paused-and-nothing-logged-today case.
        """
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
                if self.tab in skip_rows:
                    return []
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
        real_paused = pr._paused_offices

        class _DT:
            datetime = type("D", (), {
                "now": staticmethod(lambda: now),
                "strptime": staticmethod(dt.datetime.strptime),
            })
            date = dt.date

        _fill._client = lambda: _Client()
        pr.dt = _DT
        pr._paused_offices = lambda: set(paused)
        try:
            return pr.build_report()
        finally:
            _fill._client, pr.dt = real_client, real_dt
            pr._paused_offices = real_paused

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


class PausedOffices(unittest.TestCase):
    """23965 + 24065 were pulled from every rotation on 2026-09-25 (Carlos).

    Their lines used to read `0 pushed`, which is true and reads as broken —
    the exact zero-with-a-story the house rule warns about. They say `paused`
    now, and the label is DERIVED from ROTATION_BY_MACHINE so it cannot rot.
    """

    def test_paused_office_says_paused_not_zero(self):
        got = TheLine()._render(dt.datetime(2026, 9, 25, 9, 20),
                                paused={"23965", "24065"})
        self.assertIn("Raf 2nd funnel 23965: paused · 33 left @ 8:28 PM", got)
        self.assertIn("Raf 24065: paused · 36 left @ 8:34 PM", got)
        self.assertNotIn("23965: 0 pushed", got)

    def test_live_offices_untouched(self):
        got = TheLine()._render(dt.datetime(2026, 9, 25, 9, 20),
                                paused={"23965", "24065"})
        self.assertIn("Carlos 11580: 30 pushed · 7 left @ 8:33 PM", got)
        self.assertIn("Raf main 11280: 34 pushed · 114 left @ 8:21 PM", got)

    def test_paused_and_nothing_logged_is_not_a_worry_line(self):
        """'no runs yet today' means the walk should have run. Paused ≠ that."""
        got = TheLine()._render(dt.datetime(2026, 9, 25, 9, 20),
                                paused={"24065"},
                                skip_rows=("OAT Walk Diag 24065",))
        self.assertIn("Raf 24065: paused", got)
        self.assertNotIn("Raf 24065: no runs yet today", got)

    def test_whole_machine_paused_does_not_page(self):
        """Lucy 4 sat with an EMPTY rotation for 4 minutes on 2026-09-25."""
        got = TheLine()._render(
            dt.datetime(2026, 9, 25, 9, 20),
            paused={"11280", "23965", "24065"},
            skip_rows=("OAT Walk Diag 11280", "OAT Walk Diag 23965",
                       "OAT Walk Diag 24065"))
        self.assertIn("Lucy 4: all offices paused", got)
        self.assertNotIn(":warning: Lucy 4 has posted NO runs today", got)

    def test_a_genuinely_silent_machine_still_pages(self):
        """The guard must not swallow a real outage."""
        got = TheLine()._render(
            dt.datetime(2026, 9, 25, 9, 20), paused=set(),
            skip_rows=("OAT Walk Diag 11280", "OAT Walk Diag 23965",
                       "OAT Walk Diag 24065"))
        self.assertIn(":warning: Lucy 4 has posted NO runs today", got)


class PausedIsDerived(unittest.TestCase):
    def test_no_hardcoded_office_list(self):
        """A literal paused list here would have been stale within the hour."""
        import inspect
        src = inspect.getsource(pr._paused_offices)
        self.assertIn("ROTATION_BY_MACHINE", src)
        for literal in ("23965", "24065"):
            self.assertNotIn('"%s"' % literal, src)

    def test_import_failure_marks_nothing(self):
        """Guessing 'paused' for a live office would hide a real outage."""
        import builtins
        real_import = builtins.__import__

        def boom(name, *a, **k):
            if "applicant_push" in name:
                raise ImportError("no applicant_push here")
            return real_import(name, *a, **k)
        builtins.__import__ = boom
        try:
            self.assertEqual(pr._paused_offices(), set())
        finally:
            builtins.__import__ = real_import

    def test_no_browser_dependency(self):
        """This report is Sheets + Slack only; PUSH_ALLOWED drags in patchright."""
        import inspect
        src = inspect.getsource(pr._paused_offices)
        self.assertNotIn("PUSH_ALLOWED", src.split('"""')[-1])

    def test_office_id_from_tab(self):
        self.assertEqual(pr._office_id("OAT Walk Diag"), "11580")
        self.assertEqual(pr._office_id("OAT Walk Diag 23965"), "23965")


if __name__ == "__main__":
    unittest.main()
