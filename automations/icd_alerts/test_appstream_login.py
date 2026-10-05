"""Resume pushing on the office's own machine needs THEIR AppStream login.

Carlos 2026-10-05: on Lucy 2 the push takes up the screen and is slow across
that many offices. These pin what the installer must do for it.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import tempfile
import time
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
SETUP = (HERE / "dist" / "setup.py").read_text()
from automations.icd_alerts.test_install_completeness import _install_problems


class TheInstallerAsksForAppStream(unittest.TestCase):

    def test_it_asks_only_offices_that_push(self):
        self.assertIn("if ask_about_resume_pushing():", SETUP)
        self.assertIn("as_ok = appstream_until_it_works()", SETUP)

    def test_the_login_is_verified_not_just_saved(self):
        # A wrong AppStream username does not error; only the console is proof.
        self.assertIn('"automations.icd_alerts.as_signin"', SETUP)

    def test_a_failed_check_is_reported(self):
        self.assertIn("resume pushing did not verify during setup", SETUP)

    def test_the_sign_in_ships_to_the_office(self):
        files = (HERE / "agent_files.txt").read_text().split()
        self.assertIn("automations/icd_alerts/as_signin.py", files)
        from automations.icd_alerts import package
        self.assertIn("automations/icd_alerts/as_signin.py", package.AGENT_FILES)

    def test_the_cloudflare_waits_are_not_shortened(self):
        from automations.shared import ownerville_knocks as K
        self.assertGreaterEqual(K.CLOUDFLARE_WAIT_MS, 20_000)
        self.assertGreaterEqual(K.PRE_SUBMIT_PAUSE_MS, 20_000)


class AMissingLoginIsSaid(unittest.TestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def _write(self, push):
        (self.tmp / "install.json").write_text(
            json.dumps([{"office_key": "x", "push_resumes": push}]))

    def test_wants_push_without_login_is_a_note_not_a_block(self):
        self._write(True)
        blocking, notes = _install_problems(
            self.tmp, sara=True,
            files=["saraplus-creds.json", "ownerville-creds.json"])
        self.assertFalse(blocking)
        self.assertTrue(any("AppStream" in n for n in notes))

    def test_no_push_no_note(self):
        self._write(False)
        _, notes = _install_problems(
            self.tmp, sara=True,
            files=["saraplus-creds.json", "ownerville-creds.json"])
        self.assertFalse(any("AppStream" in n for n in notes))

    def test_login_saved_no_note(self):
        self._write(True)
        _, notes = _install_problems(
            self.tmp, sara=True,
            files=["saraplus-creds.json", "ownerville-creds.json",
                   "appstream-creds.json"])
        self.assertFalse(any("AppStream" in n for n in notes))


class TheCredsReader(unittest.TestCase):

    def test_none_saved_is_empty_not_an_error(self):
        from automations.icd_alerts import config as C
        with mock.patch.object(C, "AS_CREDS_PATH",
                               pathlib.Path(tempfile.mkdtemp()) / "nope.json"):
            self.assertEqual(C.appstream_creds(), {})


class TheBackgroundPusher(unittest.TestCase):

    def setUp(self):
        from automations.icd_alerts import resume_push as RP
        self.RP = RP
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(RP, "STATE_PATH", self.tmp / "s.json"),
                  mock.patch.object(RP, "LOCK_PATH", self.tmp / "l.lock")]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_hours_are_7am_to_10pm(self):
        at = lambda h, m=0: dt.datetime(2026, 10, 5, h, m)
        self.assertFalse(self.RP.in_window(at(6, 59)))
        self.assertTrue(self.RP.in_window(at(7)))
        self.assertTrue(self.RP.in_window(at(21, 59)))
        self.assertFalse(self.RP.in_window(at(22)))

    def test_every_ten_minutes(self):
        now = dt.datetime(2026, 10, 5, 12, 0)
        self.assertTrue(self.RP.due(now))
        self.RP._save_state({"last_start": "2026-10-05T11:55:00"})
        self.assertFalse(self.RP.due(now))
        self.RP._save_state({"last_start": "2026-10-05T11:50:00"})
        self.assertTrue(self.RP.due(now))

    def test_a_running_push_is_not_doubled(self):
        now = dt.datetime.now().replace(hour=12)
        self.RP.LOCK_PATH.write_text(str(now.timestamp() - 60))
        self.assertFalse(self.RP.due(now))
        # ...but a lock left by a push that died does not block forever.
        self.RP.LOCK_PATH.write_text(str(now.timestamp() - 2 * 3600))
        self.assertTrue(self.RP.due(now))

    def test_an_office_that_did_not_ask_never_pushes(self):
        with mock.patch.object(self.RP.C, "enrollments",
                               return_value=[{"office_key": "x"}]), \
             mock.patch.object(self.RP.subprocess, "Popen") as po:
            self.assertFalse(self.RP.maybe_kick(log=lambda *_: None))
            po.assert_not_called()

    def test_the_tick_runs_it_in_the_background(self):
        with mock.patch.object(self.RP, "enabled", return_value=True), \
             mock.patch.object(self.RP, "due", return_value=True), \
             mock.patch.object(self.RP.C, "APP_DIR", self.tmp), \
             mock.patch.object(self.RP, "LOG_PATH", self.tmp / "x.log"), \
             mock.patch.object(self.RP.subprocess, "Popen") as po:
            self.assertTrue(self.RP.maybe_kick(log=lambda *_: None))
            args = po.call_args[0][0]
            self.assertIn("--live", args)
            self.assertIn("--scheduled", args)

    def test_background_chrome_is_not_throttled_or_focused(self):
        src = (HERE / "resume_push.py").read_text()
        for flag in ("--disable-backgrounding-occluded-windows",
                     "--disable-renderer-backgrounding",
                     "--disable-background-timer-throttling"):
            self.assertIn(flag, src)
        self.assertIn('["-g", "-j"] if background', src)   # hidden at start
        self.assertIn('"minimized"', src)                    # Windows
        self.assertIn("_FocusGuard().start() if scheduled", src)

    def test_the_guard_hides_lucy_and_hands_focus_back(self):
        RP = self.RP
        g = RP._FocusGuard()
        fronts = iter([111, 222, 0])           # theirs, then Lucy, then idle
        calls = []
        with mock.patch.object(RP, "_front_pid", lambda: next(fronts, 0)), \
             mock.patch.object(RP, "_lucy_pids", lambda: [222]), \
             mock.patch.object(RP, "_hide_app", lambda pid: calls.append(("hide", pid))), \
             mock.patch.object(RP, "_activate_app", lambda pid: calls.append(("back", pid))), \
             mock.patch.object(RP, "IS_MAC", True):
            g.POLL_SECONDS = 0.01
            g.expect(0.5)
            g.start()
            time.sleep(0.2)
            g.stop()
        self.assertEqual(calls[:2], [("hide", 222), ("back", 111)])

    def test_the_guard_leaves_a_person_watching_alone(self):
        # Outside the few seconds after Lucy opened something, a Lucy window
        # in front is somebody who clicked it on purpose.
        RP = self.RP
        g = RP._FocusGuard()
        calls = []
        with mock.patch.object(RP, "_front_pid", lambda: 222), \
             mock.patch.object(RP, "_lucy_pids", lambda: [222]), \
             mock.patch.object(RP, "_hide_app", lambda pid: calls.append(pid)), \
             mock.patch.object(RP, "IS_MAC", True):
            g.POLL_SECONDS = 0.01
            g.start()
            time.sleep(0.1)
            g.stop()
        self.assertEqual(calls, [])

    def test_it_never_uses_the_lucy_pushers_ports(self):
        self.assertNotIn(self.RP.PORT, (9245, 9334))

    def test_the_agent_tick_kicks_it(self):
        self.assertIn("resume_push.maybe_kick", (HERE / "run.py").read_text())

    def test_finish_setup_carries_it(self):
        self.assertIn('("Resume pushing", _resume_push)',
                      (HERE / "finish_setup.py").read_text())


class ADryRunSendsNothing(unittest.TestCase):

    def test_dry_run_never_clicks(self):
        from automations.icd_alerts import push_batch as B

        def boom(*a, **k):
            raise AssertionError("a dry run clicked %r" % (a[1:],))
        with mock.patch.object(B, "_click_if_present", boom), \
             mock.patch.object(B, "_select_all", boom), \
             mock.patch.object(B, "render_all_rows", return_value=12), \
             mock.patch.object(B, "ready_for_extraction", return_value=4), \
             mock.patch.object(B, "run_extract_once", boom):
            self.assertEqual(B.send_loop(object(), dry_run=True), 0)
            self.assertEqual(B.extract_loop(object(), dry_run=True), 4)

    def test_the_cli_is_a_dry_run_unless_live(self):
        from automations.icd_alerts import resume_push as RP
        with mock.patch.object(RP, "push", return_value=0) as pu:
            RP.main([])
            self.assertEqual(pu.call_args.kwargs["live"], False)


if __name__ == "__main__":
    unittest.main()
