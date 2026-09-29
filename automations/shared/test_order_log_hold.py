"""Raf 2026-09-29: an Order Log two days behind must HOLD its sections with a
notice, never post understated numbers -- and the rest of the report posts."""
import datetime as dt
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.shared import order_log_hold as H
from automations.shared import tableau_freshness as TF

TODAY = dt.date(2026, 9, 29)


def _export(newest: dt.date) -> pathlib.Path:
    """A tiny ALLREPS-shaped crosstab (UTF-16, tab) whose newest event is `newest`."""
    d = pathlib.Path(tempfile.mkdtemp()) / "order_log_allreps.csv"
    rows = [["Owner Name", "Rep", "sp.Order Date (copy)", "Status Date"],
            ["Jacob Dover", "Nick Smith", "9/20/2026", "9/21/2026"],
            ["Jacob Dover", "Ana Ruiz", "%d/%d/%d" % (newest.month, newest.day, newest.year),
             "%d/%d/%d" % (newest.month, newest.day, newest.year)]]
    d.write_text("\n".join("\t".join(r) for r in rows), encoding="utf-16")
    return d


class _Quiet(unittest.TestCase):
    """No real Slack, no real state: the freshness guard's own alert/clear are
    stubbed, the notice poster is a list, the marker dir is a temp dir."""

    def setUp(self):
        self.posted = []
        self.poster = lambda text, **kw: (self.posted.append(text) or {"ok": True})
        tmp = pathlib.Path(tempfile.mkdtemp())
        for p in (mock.patch.object(TF, "alert_stale", return_value=False),
                  mock.patch.object(TF, "clear_stale", return_value=False),
                  mock.patch.object(TF, "STATE_DIR", tmp / "fresh"),
                  mock.patch.object(H, "MARK_DIR", tmp / "hold"),
                  mock.patch.dict(os.environ, {H.ENV: "1", "METRICS_CHANNEL_ID": "C0BMX2V2XRT"})):
            p.start()
            self.addCleanup(p.stop)


class TheHold(_Quiet):
    def test_stale_export_is_held_with_the_notice(self):
        rc = H.hold_if_stale(_export(dt.date(2026, 9, 27)), "📋 Order Log", post=True,
                             today=TODAY, poster=self.poster)
        self.assertEqual(rc, H.HELD_EXIT)
        self.assertEqual(len(self.posted), 1)
        self.assertIn("⏳ 📋 Order Log: Order Log data is behind", self.posted[0])
        self.assertIn("newest 9/27, needs 9/28", self.posted[0])
        self.assertIn("will post once the data lands", self.posted[0])

    def test_fresh_export_posts_normally(self):
        rc = H.hold_if_stale(_export(dt.date(2026, 9, 28)), "📋 Order Log", post=True,
                             today=TODAY, poster=self.poster)
        self.assertIsNone(rc)
        self.assertEqual(self.posted, [])

    def test_the_notice_goes_out_once_a_day_however_many_retries(self):
        for _ in range(4):   # first run + part-retries + a hand rerun
            self.assertEqual(H.hold_if_stale(_export(dt.date(2026, 9, 27)), "🚫 Canceled Orders",
                                             post=True, today=TODAY, poster=self.poster), 75)
        self.assertEqual(len(self.posted), 1)

    def test_each_section_gets_its_own_notice(self):
        for label in ("📋 Order Log", "🚫 Canceled Orders"):
            H.hold_if_stale(_export(dt.date(2026, 9, 27)), label, post=True,
                            today=TODAY, poster=self.poster)
        self.assertEqual(len(self.posted), 2)

    def test_dry_run_posts_nothing(self):
        rc = H.hold_if_stale(_export(dt.date(2026, 9, 27)), "📋 Order Log", post=False,
                             today=TODAY, poster=self.poster)
        self.assertEqual((rc, self.posted), (75, []))

    def test_an_appointment_dated_today_does_not_make_it_fresh(self):
        # The 2026-09-29 8:54 export: no orders after 9/26, one install
        # appointment ('first available') dated today.
        d = pathlib.Path(tempfile.mkdtemp()) / "x.csv"
        rows = [["Owner Name", "sp.Order Date (copy)", "Status Date", "spe.dtr First Available Date"],
                ["A", "9/26/2026", "9/27/2026", "9/29/2026"]]
        d.write_text("\n".join("\t".join(r) for r in rows), encoding="utf-16")
        self.assertEqual(H.verdict(d, today=TODAY)["verdict"], "stale")
        self.assertEqual(H.hold_if_stale(d, "📋 Order Log", post=True, today=TODAY,
                                         poster=self.poster), 75)

    def test_an_export_with_no_order_dates_is_not_judged(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "x.csv"
        d.write_text("Owner Name\tRep\nA\tB", encoding="utf-16")
        self.assertIsNone(H.hold_if_stale(d, "x", post=True, today=TODAY, poster=self.poster))

    def test_off_unless_the_runner_turns_it_on(self):
        with mock.patch.dict(os.environ, {H.ENV: ""}):
            self.assertIsNone(H.hold_if_stale(_export(dt.date(2026, 9, 20)), "x", post=True,
                                              today=TODAY, poster=self.poster))

    def test_a_broken_check_never_costs_the_post(self):
        with mock.patch.object(H, "verdict", side_effect=RuntimeError("boom")):
            self.assertIsNone(H.hold_if_stale("nope.csv", "x", post=True, today=TODAY))

    def test_the_empty_day_error_is_recognised(self):
        e = RuntimeError("Couldn't find the 'A.Order Log' sheet in the Crosstab dialog — "
                         "saw 1 thumb(s): ['Last Refresh']. The view may have changed.")
        self.assertTrue(H.empty_day_error(e))
        self.assertFalse(H.empty_day_error(RuntimeError("timeout")))


class ASectionEndToEnd(_Quiet):
    """Canceled Orders' real single-owner path: stale -> held, fresh -> posts."""

    def _run(self, newest):
        from automations.canceled_orders import run as CO
        img, txt = [], []
        with mock.patch.object(CO.pull, "fetch_crosstab", return_value=_export(newest)), \
                mock.patch.object(CO.pull, "parse_and_filter", return_value=[]), \
                mock.patch.object(CO.single_owner_dedup, "filter_new", return_value=[]), \
                mock.patch.object(CO.slack_metrics_post, "post_reply_with_image",
                                  side_effect=lambda *a, **k: img.append(a) or {"ok": True}), \
                mock.patch.object(CO.slack_metrics_post, "post_reply_text_only",
                                  side_effect=lambda t, **k: txt.append(t) or {"ok": True}), \
                mock.patch.object(H.dt, "date", wraps=dt.date) as _d, \
                mock.patch.object(TF.dt, "date", wraps=dt.date) as _d2:
            _d.today.return_value = TODAY
            _d2.today.return_value = TODAY
            rc = CO._run_single_owner("Jacob Dover", dt.date(2026, 7, 31), dt.date(2026, 9, 28),
                                      dt.date(2026, 8, 30), dry_run=False)
        return rc, img, txt

    def test_stale_holds_with_the_notice_and_no_numbers(self):
        rc, img, txt = self._run(dt.date(2026, 9, 27))
        self.assertEqual(rc, 75)
        self.assertEqual(img, [])
        self.assertEqual(len(txt), 1)
        self.assertTrue(txt[0].startswith("⏳ 🚫 Canceled Orders: Order Log data is behind"))

    def test_fresh_posts_the_section_as_always(self):
        rc, img, txt = self._run(dt.date(2026, 9, 28))
        self.assertEqual(rc, 0)
        self.assertEqual(txt, ["🚫 No New Canceled Orders"])


class SixPlusEmptyDay(_Quiet):
    def test_last_refresh_only_is_held_not_failed(self):
        from automations.scheduled_6_days_out import run as S
        boom = RuntimeError("Couldn't find the 'A.Order Log' sheet in the Crosstab dialog — "
                            "saw 1 thumb(s): ['Last Refresh']. The view may have changed.")
        txt = []
        with mock.patch.object(S.pull, "fetch_crosstab_allreps", side_effect=boom), \
                mock.patch.object(S.slack_metrics_post, "post_reply_text_only",
                                  side_effect=lambda t, **k: txt.append(t) or {"ok": True}):
            rc = S._run_single_owner("Jacob Dover", dt.date(2026, 9, 28),
                                     post_slack=True, dry_run=False)
        self.assertEqual(rc, 75)
        self.assertEqual(len(txt), 1)
        self.assertIn("📅 Sales Scheduled 6+ Days Out", txt[0])

    def test_any_other_error_still_fails_loudly(self):
        from automations.scheduled_6_days_out import run as S
        with mock.patch.object(S.pull, "fetch_crosstab_allreps", side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError):
                S._run_single_owner("Jacob Dover", dt.date(2026, 9, 28), post_slack=True, dry_run=False)


class TheRunnerOnlyHoldsTheHeldSection(unittest.TestCase):
    def test_exit_75_reads_as_held_and_others_as_posted(self):
        from automations.office_metrics import runner as R
        rcs = {"order_log": 75, "cancels": 75, "churn": 0, "knocks": 0}
        def fake_run(cmd, **kw):
            return mock.Mock(returncode=rcs[cmd[-1]])
        with mock.patch.object(R.subprocess, "run", side_effect=fake_run):
            out = {slug: R._run_one(slug, ["python", slug], {}) for slug in rcs}
        self.assertEqual(out["churn"][0], True)
        self.assertEqual(out["knocks"][0], True)
        self.assertEqual(out["order_log"][0], False)
        self.assertIn("HELD — Order Log data behind", out["order_log"][1])

    def test_the_runner_switches_the_hold_on(self):
        import inspect
        from automations.office_metrics import runner as R
        self.assertIn("base_env[_olh.ENV] = \"1\"", inspect.getsource(R))


if __name__ == "__main__":
    unittest.main()
