"""What the 4am heartbeat must and must NOT page about.

The bar here is set by the watchers that came before it: a "didn't run today"
that fires on a legitimately-idle machine gets muted by a human within a week,
and then it is no longer a watchdog. So the false-alarm cases are tested as
carefully as the real one.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from automations.orchestrator_heartbeat import run as hb


class CheckDayState(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._patch = mock.patch.object(hb, "STATE_DIR", self.dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_missing_file_is_the_2026_08_27_outage(self):
        ok, detail = hb.check_day_state("2026-08-27")
        self.assertFalse(ok)
        self.assertIn("never wrote one", detail)

    def test_zero_reports_is_not_healthy(self):
        """The orchestrator started but loaded no schedule — reads as 'ran' to
        anything that only checks the file exists."""
        (self.dir / "2026-08-27.json").write_text(json.dumps({"reports": {}}))
        ok, detail = hb.check_day_state("2026-08-27")
        self.assertFalse(ok)
        self.assertIn("ZERO reports", detail)

    def test_unparseable_state_is_reported_apart_from_missing(self):
        (self.dir / "2026-08-27.json").write_text("{not json")
        ok, detail = hb.check_day_state("2026-08-27")
        self.assertFalse(ok)
        self.assertIn("unreadable", detail)

    def test_a_normal_morning_is_silent(self):
        (self.dir / "2026-08-27.json").write_text(
            json.dumps({"reports": {"b2b_metrics": {"status": "DONE"}}}))
        ok, detail = hb.check_day_state("2026-08-27")
        self.assertTrue(ok)
        self.assertIn("1 report", detail)


class ConfigDiagnosis(unittest.TestCase):
    """The alert has to NAME the cause, or it is just another 'something broke'."""

    def _with_config(self, text):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "schedule_config.json"
        p.write_text(text)
        return mock.patch.object(hb, "CONFIG_PATH", p)

    def test_conflict_markers_are_caught_before_json_parse(self):
        with self._with_config('{"a": 1}\n<<<<<<< HEAD\n'):
            ok, detail = hb._config_is_valid()
        self.assertFalse(ok)
        self.assertIn("conflict markers", detail)

    def test_valid_config_says_so(self):
        with self._with_config('{"reports": {}}'):
            ok, detail = hb._config_is_valid()
        self.assertTrue(ok)

    def test_alert_names_git_recover_when_config_is_the_cause(self):
        text = hb.build_alert("no day_state file", False, "contains git conflict markers")
        self.assertIn("git_recover", text)
        self.assertIn("schedule_config.json", text)

    def test_alert_does_not_blame_config_when_config_is_fine(self):
        """Otherwise every future outage gets 'fixed' by a git_recover that was
        never the problem — the exact misdiagnosis loop this replaces."""
        text = hb.build_alert("no day_state file", True, "valid")
        self.assertNotIn("git_recover", text)
        self.assertIn("logtail", text)


class NoFalseAlarms(unittest.TestCase):
    def test_quiet_when_the_orchestrator_agent_is_not_installed(self):
        """Megan's laptop, or a runner whose agent was booted out on purpose,
        must never page — it is not supposed to run the 4am batch."""
        with mock.patch.object(hb, "_orchestrator_installed", return_value=False), \
             mock.patch.object(hb, "post") as posted:
            rc = hb.main([])
        self.assertEqual(rc, 0)
        posted.assert_not_called()

    def test_pages_once_per_day_not_once_per_pass(self):
        """The plist fires at 04:20 AND 06:00; a real outage is one page."""
        with mock.patch.object(hb, "_orchestrator_installed", return_value=True), \
             mock.patch.object(hb, "check_day_state", return_value=(False, "no day_state")), \
             mock.patch.object(hb, "_already_alerted", return_value=True), \
             mock.patch.object(hb, "post") as posted:
            rc = hb.main([])
        self.assertEqual(rc, 1)
        posted.assert_not_called()

    def test_dry_run_never_posts_and_never_marks(self):
        with mock.patch.object(hb, "_orchestrator_installed", return_value=True), \
             mock.patch.object(hb, "check_day_state", return_value=(False, "no day_state")), \
             mock.patch.object(hb, "post") as posted, \
             mock.patch.object(hb, "_mark_alerted") as marked:
            hb.main(["--dry-run"])
        posted.assert_not_called()
        marked.assert_not_called()

    def test_marker_only_written_when_the_post_succeeded(self):
        """A Slack outage must not consume the day's single alert — otherwise the
        06:00 backstop stays silent about a real 04:00 failure."""
        with mock.patch.object(hb, "_orchestrator_installed", return_value=True), \
             mock.patch.object(hb, "check_day_state", return_value=(False, "no day_state")), \
             mock.patch.object(hb, "_already_alerted", return_value=False), \
             mock.patch.object(hb, "post", return_value=False), \
             mock.patch.object(hb, "_mark_alerted") as marked:
            hb.main([])
        marked.assert_not_called()


class NoSharedFuse(unittest.TestCase):
    def test_imports_nothing_from_day_orchestrator(self):
        """THE design constraint. A watchdog that imports the package it watches
        dies with it — which is exactly why machine_digest._run_watch could not
        report the 2026-08-27 outage."""
        src = Path(hb.__file__).read_text()
        self.assertNotIn("from automations.day_orchestrator", src)
        self.assertNotIn("import automations.day_orchestrator", src)


if __name__ == "__main__":
    unittest.main()
