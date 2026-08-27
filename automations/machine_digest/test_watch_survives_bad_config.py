"""The watcher must outlive the file it reads.

2026-08-27: an unmerged schedule_config (conflict markers, invalid JSON) killed
the 04:00 orchestrator, and the same bare `registry.load_config()` in _run_watch
killed every 10-minute pass of the watcher meant to notice. A batch that ran zero
reports went unreported for 2h45m, while the machine passed every liveness check.
"""
import json
import unittest
from unittest import mock

from automations.machine_digest import run as md


def _boom(*a, **k):
    raise json.decoder.JSONDecodeError("Expecting property name", "{", 1)


class WatchSurvivesBadConfig(unittest.TestCase):
    def test_a_corrupt_config_does_not_raise_out_of_the_watcher(self):
        with mock.patch("automations.day_orchestrator.registry.load_config", _boom), \
             mock.patch.object(md, "_alert_config_unparseable") as alerted:
            rc = md._run_watch("2026-08-27", "Aug 27", "", dry_run=True, ts="T")
        self.assertEqual(rc, 1)
        alerted.assert_called_once()

    def test_it_stops_rather_than_running_a_pass_without_skip_lists(self):
        """Continuing with cfg=None would empty every skip-list, so the watcher
        would alert on EVERY orchestrator-managed report at once — a false-alarm
        storm at exactly the moment the channel has to stay readable."""
        with mock.patch("automations.day_orchestrator.registry.load_config", _boom), \
             mock.patch.object(md, "_alert_config_unparseable"), \
             mock.patch.object(md, "_read_activity") as read:
            md._run_watch("2026-08-27", "Aug 27", "", dry_run=True, ts="T")
        read.assert_not_called()

    def test_a_healthy_config_still_reaches_the_normal_pass(self):
        """The guard must not swallow the good path too."""
        with mock.patch("automations.day_orchestrator.registry.load_config",
                        return_value=mock.MagicMock()), \
             mock.patch("automations.day_orchestrator.notify._corrections_channel",
                        return_value=None) as chan:
            rc = md._run_watch("2026-08-27", "Aug 27", "", dry_run=True, ts="T")
        chan.assert_called_once()
        self.assertEqual(rc, 0)


class ConfigAlarm(unittest.TestCase):
    def test_alarm_does_not_need_a_parsed_config(self):
        """It routes through orchestrator_heartbeat, which resolves the channel
        from the id cache / raw read / literal. Asking notify._corrections_channel
        would need the object we just failed to build."""
        from automations.orchestrator_heartbeat import run as hb
        src = __import__("pathlib").Path(md.__file__).read_text()
        fn = src.split("def _alert_config_unparseable")[1].split("\ndef ")[0]
        # Drop the docstring — it NAMES _corrections_channel to explain why the
        # code deliberately doesn't call it, so matching raw text would fail on
        # the very comment documenting the fix.
        body = fn.split('"""')[2] if fn.count('"""') >= 2 else fn
        self.assertIn("orchestrator_heartbeat", body)
        self.assertNotIn("_corrections_channel(", body)
        self.assertTrue(hasattr(hb, "post") and hasattr(hb, "MARKER_DIR"))

    def test_dry_run_posts_nothing(self):
        with mock.patch("automations.orchestrator_heartbeat.run.post") as posted:
            md._alert_config_unparseable("2026-08-27", ValueError("x"),
                                         dry_run=True, ts="T")
        posted.assert_not_called()

    def test_pages_once_a_day_not_every_ten_minutes(self):
        """_run_watch runs every 10 min; a corrupt config lasting all morning
        must not produce ~40 identical pages."""
        from automations.orchestrator_heartbeat import run as hb
        with mock.patch.object(hb, "post", return_value=True) as posted, \
             mock.patch("pathlib.Path.exists", return_value=True):
            md._alert_config_unparseable("2026-08-27", ValueError("x"),
                                         dry_run=False, ts="T")
        posted.assert_not_called()

    def test_alarm_never_raises_even_if_slack_explodes(self):
        """This runs on a watcher's failure path — raising here recreates the
        exact bug being fixed."""
        with mock.patch("automations.orchestrator_heartbeat.run.post",
                        side_effect=RuntimeError("slack down")), \
             mock.patch("pathlib.Path.exists", return_value=False):
            md._alert_config_unparseable("2026-08-27", ValueError("x"),
                                         dry_run=False, ts="T")   # must not raise


if __name__ == "__main__":
    unittest.main()
