"""Stall DM (Megan 2026-11-25: "I need alerted when apps aren't getting pushed")."""
import datetime as dt
import unittest

from automations.push_report import stall_alert as SA

NOW = dt.datetime(2026, 11, 25, 11, 0)          # a Wednesday
OFF = [("raf", "24065", "Raf 24065"), ("raf", "11280", "Raf main 11280")]


def H(**k):
    base = {"in_window": True, "due": True, "lock_min": None, "last_result": "ok"}
    base.update(k)
    return {"raf": base}


class Stall(unittest.TestCase):
    def test_no_run_for_an_hour_alerts_once_then_recovers(self):
        st = {}
        stats = {("raf", "24065"): {"last": NOW - dt.timedelta(minutes=70),
                                    "sent": 0, "end": None, "walled": False},
                 ("raf", "11280"): {"last": NOW - dt.timedelta(minutes=5),
                                    "sent": 39, "end": 4, "walled": False}}
        m = SA.check(NOW, OFF, stats, H(last_result="no_queue_page"), st)
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0][0], "raf"); self.assertIn("Raf 24065", m[0][1]); self.assertIn("no_queue_page", m[0][1])
        self.assertEqual(SA.check(NOW, OFF, stats, H(), st), [])   # once
        stats[("raf", "24065")] = {"last": NOW, "sent": 5, "end": 3, "walled": False}
        stats[("raf", "11280")] = {"last": NOW + dt.timedelta(minutes=50),
                                   "sent": 50, "end": 2, "walled": False}
        m = SA.check(NOW + dt.timedelta(hours=1), OFF, stats, H(), st)
        self.assertEqual(len(m), 1); self.assertIn("pushing again", m[0][1])

    def test_waiting_and_nothing_sent_for_an_hour(self):
        st = {}
        stats = {("raf", "24065"): {"last": NOW, "sent": 4, "end": 92, "walled": True}}
        self.assertEqual(SA.check(NOW, OFF[:1], stats, H(), st), [])  # first look
        m = SA.check(NOW + dt.timedelta(hours=1), OFF[:1],
                     {("raf", "24065"): dict(stats[("raf", "24065")],
                                             last=NOW + dt.timedelta(minutes=55))},
                     H(), st)
        self.assertEqual(len(m), 1); self.assertIn("92 waiting", m[0][1])
        self.assertIn("Indeed", m[0][1])

    def test_quiet_outside_push_hours(self):
        sat = dt.datetime(2026, 11, 28, 11, 0)
        self.assertEqual(SA.check(sat, OFF, {}, H(), {}), [])
        self.assertEqual(SA.check(NOW.replace(hour=5), OFF, {}, H(), {}), [])

    def test_not_due_and_no_stuck_lock_is_fine(self):
        # past its stop for the day: the computer does not want to run
        self.assertEqual(SA.check(NOW, OFF, {}, H(due=False), {}), [])

    def test_stuck_lock_alerts(self):
        m = SA.check(NOW, OFF[:1], {}, H(due=False, lock_min=45), {})
        self.assertEqual(len(m), 1)


class GoesToTheOfficeGroup(unittest.TestCase):
    def test_raf_stall_goes_to_rafs_group_dm(self):
        from unittest import mock
        import tempfile, pathlib
        sent = []
        book = mock.MagicMock()
        with mock.patch.object(SA, "collect", lambda rows, day: ({}, H())), \
             mock.patch.object(SA, "check", lambda *a, **k: [("raf", "STALL")]), \
             mock.patch.object(SA, "state_path",
                               lambda: pathlib.Path(tempfile.mkdtemp()) / "s.json"), \
             mock.patch("automations.icd_alerts.post.dm_office_people",
                        lambda key, text, log=print: sent.append((key, text))):
            self.assertEqual(SA.run(mock.MagicMock(), "U04G5HJBGFN", OFF, book,
                                    log=lambda *_: None), 1)
        self.assertEqual(sent, [("raf", "STALL")])


if __name__ == "__main__":
    unittest.main()
