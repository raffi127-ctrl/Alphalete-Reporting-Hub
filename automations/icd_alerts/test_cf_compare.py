"""Office-computer comparison of Indeed's check (Megan 2026-11-04)."""
import unittest

from automations.icd_alerts import resume_push as RP
from automations.oat_processing import run as OAT


class CfCompare(unittest.TestCase):
    def test_etime(self):
        self.assertEqual(RP._etime_min("05:09"), 5)
        self.assertEqual(RP._etime_min("02:05:09"), 125)
        self.assertEqual(RP._etime_min("1-02:05:09"), 1565)
        self.assertIsNone(RP._etime_min("junk"))

    def test_cf_stats_reset_with_the_session(self):
        OAT.CF_STATS.update({"opens": 3, "first": "auto"})
        OAT.reset_cf_session()
        self.assertEqual(OAT.CF_STATS, {})


class StuckChrome(unittest.TestCase):
    def test_raf_1105_errors_count_as_stuck(self):
        self.assertTrue(RP._is_stuck_chrome(TimeoutError(
            "BrowserType.connect_over_cdp: Timeout 180000ms exceeded.")))
        self.assertTrue(RP._is_stuck_chrome(RuntimeError(
            "Protocol error (Network.setCacheDisabled): Internal server "
            "error, session closed.")))

    def test_other_crashes_do_not_kill_chrome(self):
        self.assertFalse(RP._is_stuck_chrome(ValueError("bad office id")))
        self.assertFalse(RP._is_stuck_chrome(KeyError("start")))


class ChromeAge(unittest.TestCase):
    """Raf 11/5: the age read ~41h after a fresh Chrome took over."""
    PARENT = {500: 400, 400: 1, 777: 1, 501: 400}   # 400 = live Chrome

    def setUp(self):
        from unittest import mock
        self.mock = mock
        self.p = [mock.patch.object(RP, "_ppid", lambda pid: self.PARENT.get(pid, 0)),
                  mock.patch.object(RP, "_port_owner_pid", lambda: 400),
                  mock.patch.object(RP, "_lucy_pids", lambda: [400, 500, 501, 777])]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_helpers_belong_to_the_live_chrome(self):
        self.assertTrue(RP._belongs_to(500, 400))
        self.assertTrue(RP._belongs_to(400, 400))
        self.assertFalse(RP._belongs_to(777, 400))

    def test_only_the_leftover_is_quit(self):
        killed = []
        with self.mock.patch.object(RP.os, "kill", lambda pid, sig: killed.append(pid)):
            self.assertEqual(RP._reap_stray_chrome(), 1)
        self.assertEqual(killed, [777])

    def test_nothing_quit_when_the_live_chrome_is_unknown(self):
        with self.mock.patch.object(RP, "_port_owner_pid", lambda: None), \
             self.mock.patch.object(RP.os, "kill") as k:
            self.assertEqual(RP._reap_stray_chrome(), 0)
            k.assert_not_called()


if __name__ == "__main__":
    unittest.main()
