"""Offline tests for the Sun+Mon PDF post into the #alphalete-sales Metrics
thread (Raf 2026-09-07).

No Slack, no PNGs: a fake client and a stubbed weekly_pdf.build.

PATCHING THE REAL MODULE, NOT sys.modules (2026-09-07, the hard way). The first
version of this file stubbed Slack with
`mock.patch.dict("sys.modules", {"automations.shared.slack_metrics_post": …})`.
That does NOT intercept `from automations.shared import slack_metrics_post`
once the package attribute is set: the import binds the REAL submodule off the
package, the mock is never consulted, and the run posted a 13-byte fake PDF
into the live #alphalete-sales threads (three times, plus mirrors). Patch the
attributes ON the module object — `_client`, `find_metrics_thread_ts`,
`post_reply_with_file` — so there is no path from a test to the network.

    python -m unittest automations.captainship_drafts.test_weekly_pdf_slack
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.captainship_drafts import weekly_pdf_slack as S
from automations.shared import slack_metrics_post as SMP


_KEEP_TOKEN: object = None


def setUpModule():
    """Belt AND braces. The patches below are the real guard; this makes a
    patch that ever stops working harmless instead of expensive — with a
    junk token in the environment (_load_token prefers the env var over the
    file), a leaked call gets invalid_auth from Slack and posts nothing."""
    global _KEEP_TOKEN
    _KEEP_TOKEN = os.environ.get("SLACK_USER_TOKEN")
    os.environ["SLACK_USER_TOKEN"] = "xoxp-not-a-real-token-unit-test"


def tearDownModule():
    if _KEEP_TOKEN is None:
        os.environ.pop("SLACK_USER_TOKEN", None)
    else:
        os.environ["SLACK_USER_TOKEN"] = _KEEP_TOKEN


class _Client:
    """conversations_replies over a fixed list of reply texts."""

    def __init__(self, texts):
        self.texts = texts

    def conversations_replies(self, **kw):
        return {"messages": [{"text": t} for t in self.texts]}


class TheDayGate(unittest.TestCase):

    def test_only_sunday_and_monday(self):
        # Sun 9/6 … Sat 9/12
        want = {6: True, 7: True, 8: False, 9: False,
                10: False, 11: False, 12: False}
        for day, expected in want.items():
            d = dt.date(2026, 9, day)
            self.assertEqual(S.runs_today(d), expected, f"{d} ({d:%a})")

    def test_it_reads_the_captainship_table_not_its_own_list(self):
        """Si algún día cambian los días del bloque semanal en el correo, este
        post los sigue solo."""
        from automations.captainship_drafts import config
        with mock.patch.dict(config.SECTION_DAYS,
                             {"knock_dispo": (2,)}, clear=False):
            self.assertTrue(S.runs_today(dt.date(2026, 9, 9)))    # Wednesday
            self.assertFalse(S.runs_today(dt.date(2026, 9, 6)))   # Sunday


class TheDedupeMarker(unittest.TestCase):
    """El marcador NO puede coincidir con el board que weekly_knock_dispositions
    postea en ESTE mismo hilo los domingos: si coincidiera, este reporte se
    saltearía todos los domingos creyendo que ya posteó."""

    WKD_BOARD = ":clipboard: Weekly Knock Dispositions — Aug 31–5"

    def test_the_sunday_board_is_not_mistaken_for_the_pdf(self):
        self.assertNotIn(S.MARKER, self.WKD_BOARD)
        self.assertFalse(S.already_posted(_Client([self.WKD_BOARD]), "1.1"))

    def test_our_own_post_is_recognised(self):
        ours = (f":page_facing_up: {S.MARKER} — Rafael's Captainship — "
                "Aug 31 - Sep 5, 2026")
        self.assertTrue(S.already_posted(_Client([self.WKD_BOARD, ours]), "1.1"))

    def test_an_unreadable_thread_is_not_read_as_already_posted(self):
        class Boom:
            def conversations_replies(self, **kw):
                raise RuntimeError("missing scope")
        self.assertFalse(S.already_posted(Boom(), "1.1"))


class TheCaptainLookup(unittest.TestCase):

    def test_rafael_is_the_default_and_has_the_section(self):
        self.assertEqual(S._captain(S.DEFAULT_CAPTAIN).key, "rafael")

    def test_a_captainship_without_the_section_is_a_loud_error(self):
        with self.assertRaises(SystemExit):
            S._captain("carlos")        # b2b: no knock_dispo section

    def test_an_unknown_key_is_a_loud_error(self):
        with self.assertRaises(SystemExit):
            S._captain("nobody")


class TheRun(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self._tmp.name) / "weekly.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.addCleanup(self._tmp.cleanup)

    def _stub_slack(self, *, replies=()):
        """Patch the three Slack entry points run() uses, ON the real module.
        Returns the list every attempted post is recorded in."""
        posted: list = []
        self.enterContext(mock.patch.object(
            SMP, "_client", return_value=_Client(list(replies))))
        self.enterContext(mock.patch.object(
            SMP, "find_metrics_thread_ts", return_value="1.1"))
        self.enterContext(mock.patch.object(
            SMP, "post_reply_with_file",
            side_effect=lambda p, **kw: (posted.append((p, kw))
                                         or {"ok": True, "landed": True})))
        return posted

    def _stub_pdf(self, built="default"):
        if built == "default":
            built = (self.pdf, "Weekly Knock Dispositions - Rafael - "
                               "Aug 31 - Sep 5, 2026.pdf")
        self.enterContext(mock.patch.object(S.WP, "build", return_value=built))

    def test_it_posts_once_on_sunday(self):
        posted = self._stub_slack()
        self._stub_pdf()
        self.assertEqual(S.run(dt.date(2026, 9, 6), dry_run=False), 0)
        self.assertEqual(len(posted), 1)
        self.assertIn(S.MARKER, posted[0][1]["comment"])
        self.assertIn("Aug 31 - Sep 5", posted[0][1]["comment"])

    def test_a_rerun_the_same_day_does_not_stack_a_second_copy(self):
        already = f":page_facing_up: {S.MARKER} — Rafael's Captainship — x"
        posted = self._stub_slack(replies=[already])
        self._stub_pdf()
        self.assertEqual(S.run(dt.date(2026, 9, 7), dry_run=False), 0)
        self.assertEqual(posted, [])

    def test_force_reposts_over_the_dedupe(self):
        already = f":page_facing_up: {S.MARKER} — Rafael's Captainship — x"
        posted = self._stub_slack(replies=[already])
        self._stub_pdf()
        self.assertEqual(S.run(dt.date(2026, 9, 7), dry_run=False, force=True),
                         0)
        self.assertEqual(len(posted), 1)

    def test_a_tuesday_posts_nothing_and_is_not_a_failure(self):
        posted = self._stub_slack()
        self._stub_pdf()
        self.assertEqual(S.run(dt.date(2026, 9, 8), dry_run=False), 0)
        self.assertEqual(posted, [])

    def test_dry_run_posts_nothing(self):
        posted = self._stub_slack()
        self._stub_pdf()
        self.assertEqual(S.run(dt.date(2026, 9, 6), dry_run=True), 0)
        self.assertEqual(posted, [])

    def test_no_pdf_on_disk_is_a_visible_failure(self):
        """Un hueco mudo sería peor: si no hay PDF, la corrida falla y el
        orquestador lo dice."""
        posted = self._stub_slack()
        self._stub_pdf(built=None)
        self.assertEqual(S.run(dt.date(2026, 9, 6), dry_run=False), 1)
        self.assertEqual(posted, [])


if __name__ == "__main__":
    unittest.main()
