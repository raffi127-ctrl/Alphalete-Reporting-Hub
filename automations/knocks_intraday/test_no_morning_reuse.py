"""Tonight's 9 PM pull must never become tomorrow morning's answer.

Run:  PYTHONPATH=. python -m unittest \
          automations.knocks_intraday.test_no_morning_reuse

WHAT THIS GUARDS (Raf 2026-08-25): "the next morning it'll have to recollect the
data because extra knocks could come in after 9:00 CEN".

He is describing a real failure, not a preference. The 9 PM board covers the
CURRENT day. Tomorrow morning that same calendar date is "yesterday" — the day
the morning board reports. Both readers key their caches by DATE:

  · `knocks_request.service.cached_rows` looks in the `/knocks` cache, then in
    the captainship build's `daily_knocks_*` sidecar tree
  · the captainship manifest keys on (captain, target date)

So anything this module leaves behind under those names is indistinguishable
from a finished day's pull, and tomorrow's board would quietly serve numbers
that stopped counting at 9 PM. Nothing raises. The board just reads low, on the
one metric the whole thread exists to compare.

The protection is that this module writes ONLY under `output/knocks_intraday/`
and never calls `save_rows`. That is easy to undo by accident — "render into the
build's folder so the morning can reuse it" is a natural-sounding optimisation
and exactly the bug. Hence these tests.

No browser and no Slack: the pull and the renderer are stubbed, and `post` runs
in dry-run so an accidental real post is impossible even if the wiring breaks.
"""
from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from automations.knocks_intraday import roster, run as intraday
from automations.knocks_request import service

TODAY = dt.date(2026, 8, 25)


def rows_for(rep="Ana Diaz", knocks=10) -> list:
    return [{
        "ID": "101", "Rep": rep,
        "Total Leads Knocked": knocks, "Total Knocks": knocks,
        "Total Talk to": 2, "First Knock": "9:00 AM", "Last Knock": "8:45 PM",
        "Gaps": 1, "Total Gaps (min)": 30, "No answer": 1,
        "Talk To - Not Interested": 1, "Presentation – Not Interested": 1,
        "Come Back": 1, "Sale": 1, "Inaccessible": 0, "Do Not Knock": 0,
    }]


class NoMorningReuse(unittest.TestCase):
    """The point of the whole module: leave nothing tomorrow could pick up."""

    def setUp(self):
        self.wrote = []          # every path the renderer was asked to write

        def fake_render(day, *, rows, out_dir, title_suffix="", end=None,
                        extra_totals=None):
            self.wrote.append(Path(out_dir))
            return ([Path(out_dir) / f"total_knocks_{day}.png"], "house")

        def fake_pull(jobs, verbose=True, profile_dir=None):
            return [(n, {d: rows_for() for d in days}, None) for n, days in jobs]

        for dotted, new in (
            ("automations.total_knocks.render.render_knocks_boards",
             fake_render),
            ("automations.rashad_metrics.knocks_pull.pull_offices_days",
             fake_pull),
        ):
            p = mock.patch(dotted, new)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(intraday, "central_today", lambda: TODAY)
        p.start()
        self.addCleanup(p.stop)

    def test_it_never_writes_into_the_captainship_sidecar_tree(self):
        """`service.cached_rows` globs that tree for `daily_knocks_*`. A PNG of
        ours landing there would be read tomorrow as a finished pull."""
        from automations.knocks_request.service import _build_render_dir
        build_tree = _build_render_dir().resolve()
        intraday.build(TODAY, only="cody", logfn=lambda m: None)
        self.assertTrue(self.wrote, "the renderer was never called")
        for path in self.wrote:
            self.assertNotIn(build_tree, path.resolve().parents,
                             f"{path} is inside the captainship build tree")
            self.assertNotIn("daily_knocks", path.name)

    def test_it_writes_under_its_own_output_dir(self):
        intraday.build(TODAY, only="cody", logfn=lambda m: None)
        for path in self.wrote:
            self.assertIn(intraday.OUT_DIR.resolve(), path.resolve().parents)

    def test_it_never_reaches_the_knocks_cache(self):
        """save_rows is the only writer of the /knocks cache. This module must
        not call it — not even for a finished day passed via --date."""
        with mock.patch.object(service, "save_rows") as never:
            intraday.build(TODAY, only="cody", logfn=lambda m: None)
            intraday.build(dt.date(2026, 8, 20), only="cody",
                           logfn=lambda m: None)
        never.assert_not_called()

    def test_the_cache_would_refuse_todays_rows_anyway(self):
        """Belt and braces: even if something did try, `save_rows` stores only
        finished days — that guard is what keeps a partial day off disk."""
        with mock.patch.object(service, "central_today", lambda: TODAY), \
             mock.patch.object(service, "_cache_path") as path:
            service.save_rows("Cody Cannon", TODAY, rows_for())
        path.assert_not_called()


class NeverPostsBlank(unittest.TestCase):
    """Standing rule: an office with nothing to show gets no post at all."""

    def _results(self, **over):
        rec = {"office": "Cody Cannon", "key": "cody", "label": "Cody Cannon",
               "channel_id": "C1", "channel_name": "#aeon-sales",
               "token_file": "", "png": None, "rows": [], "error": None}
        rec.update(over)
        return [rec]

    def test_no_rows_means_no_post(self):
        with mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image") as never:
            code = intraday.post(self._results(), TODAY, dry_run=False,
                                 logfn=lambda m: None)
        never.assert_not_called()
        self.assertEqual(code, 0)     # a quiet office is not a failed run

    def test_a_failed_office_does_not_post_either(self):
        with mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image") as never:
            intraday.post(self._results(error=RuntimeError("boom")), TODAY,
                          dry_run=False, logfn=lambda m: None)
        never.assert_not_called()

    def test_dry_run_never_touches_slack(self):
        with mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image") as never:
            intraday.post(self._results(png=Path("/tmp/x.png"),
                                        rows=rows_for()),
                          TODAY, dry_run=True, logfn=lambda m: None)
        never.assert_not_called()

    def test_one_channel_failing_does_not_stop_the_others(self):
        recs = (self._results(key="a", png=Path("/tmp/a.png"), rows=rows_for())
                + self._results(key="b", png=Path("/tmp/b.png"),
                                rows=rows_for()))
        calls = []

        def flaky(path, **kw):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("slack said no")
            return {}

        with mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image", flaky):
            code = intraday.post(recs, TODAY, dry_run=False,
                                 logfn=lambda m: None)
        self.assertEqual(len(calls), 2)      # the second office still went
        self.assertEqual(code, 1)            # and the run reports the failure


class CrossWorkspacePostsWithItsOwnToken(unittest.TestCase):
    """Trang's channel is in the FRESH SUCCESS workspace, not AO. Posting her
    board on Lucy's token would either fail or land a channel id that means
    something else entirely over there — the wrong-recipient failure."""

    def _rec(self, **over):
        rec = {"office": "Trang Le Nguyen Canavan", "key": "trang",
               "label": "trang canavan", "channel_id": "C9",
               "channel_name": "#freshsuccess-all-leaders", "header_label": "",
               "token_file": "fs-bot-token.txt", "png": Path("/tmp/t.png"),
               "rows": rows_for(), "error": None}
        rec.update(over)
        return rec

    def test_a_missing_token_skips_rather_than_posting_as_lucy(self):
        with mock.patch.object(intraday, "token_path",
                               lambda r: Path("/nope/absent-token.txt")), \
             mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image") as never:
            code = intraday.post([self._rec()], TODAY, dry_run=False,
                                 logfn=lambda m: None)
        never.assert_not_called()
        self.assertEqual(code, 0)     # structural skip, not a red run

    def test_the_offices_own_token_is_used_and_then_restored(self):
        import os
        seen = {}
        tok = Path(__file__).with_name("_fake_token.txt")
        tok.write_text("xoxb-fresh-success\n", encoding="utf-8")
        self.addCleanup(tok.unlink)
        os.environ["SLACK_USER_TOKEN"] = "xoxp-lucy"
        self.addCleanup(os.environ.pop, "SLACK_USER_TOKEN", None)

        def capture(path, **kw):
            seen["token"] = os.environ.get("SLACK_USER_TOKEN")
            return {}

        with mock.patch.object(intraday, "token_path", lambda r: tok), \
             mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image", capture):
            intraday.post([self._rec()], TODAY, dry_run=False,
                          logfn=lambda m: None)
        self.assertEqual(seen["token"], "xoxb-fresh-success")
        # Lucy's token is back the moment that office is done, or the NEXT
        # office would post into the wrong workspace.
        self.assertEqual(os.environ["SLACK_USER_TOKEN"], "xoxp-lucy")

    def test_an_ao_office_leaves_the_default_token_alone(self):
        import os
        seen = {}
        os.environ["SLACK_USER_TOKEN"] = "xoxp-lucy"
        self.addCleanup(os.environ.pop, "SLACK_USER_TOKEN", None)

        def capture(path, **kw):
            seen["token"] = os.environ.get("SLACK_USER_TOKEN")
            return {}

        with mock.patch("automations.shared.slack_metrics_post"
                        ".post_reply_with_image", capture):
            intraday.post([self._rec(token_file="", key="cody")], TODAY,
                          dry_run=False, logfn=lambda m: None)
        self.assertEqual(seen["token"], "xoxp-lucy")


class TheCaptionSaysItIsPartial(unittest.TestCase):
    """A screenshot of a 9 PM board outlives the message under it, so the
    board still carries the time it was taken — just the stamp, though."""

    def test_todays_board_carries_the_time_it_was_taken(self):
        with mock.patch.object(intraday, "central_today", lambda: TODAY):
            cap = intraday._caption("Cody Cannon", TODAY, True)
        self.assertIn("As of 9:00 PM Central", cap)

    def test_it_does_not_explain_the_morning_re_pull(self):
        # Megan 2026-08-25: the stamp stays, the explanation goes — how the
        # morning re-pulls is plumbing, not nightly reading for the channel.
        cap = intraday._caption("Cody Cannon", TODAY, True)
        for phrase in ("re-pulls", "read higher", "still knock", "tomorrow"):
            self.assertNotIn(phrase, cap)

    def test_a_finished_day_carries_no_partial_note(self):
        cap = intraday._caption("Cody Cannon", dt.date(2026, 8, 20), False)
        self.assertNotIn("As of", cap)


class TheRoster(unittest.TestCase):

    def test_exclusions_are_explained_not_silent(self):
        # An office left out has to say why, in the run log, every night.
        for key in roster.EXCLUDED:
            self.assertTrue(roster.EXCLUDED[key].strip(),
                            f"{key} is excluded with no reason given")
        self.assertTrue(any("isaiah" in l for l in roster.excluded_lines()))

    def test_excluded_offices_are_not_enrolled(self):
        keys = {o.key for o in roster.enrolled()}
        self.assertFalse(keys & set(roster.EXCLUDED))

    def test_enrolment_comes_from_the_metrics_registry(self):
        from automations.office_metrics.offices import OFFICES
        self.assertEqual({o.key for o in roster.enrolled()},
                         set(OFFICES) - set(roster.EXCLUDED))

    def test_every_enrolled_office_has_somewhere_to_post(self):
        for o in roster.enrolled():
            self.assertTrue(o.channel_id, f"{o.key} has no channel_id")
            self.assertTrue(o.knocks_office, f"{o.key} has no knocks_office")


if __name__ == "__main__":
    unittest.main()
