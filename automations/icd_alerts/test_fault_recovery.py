"""A fault thread gets its ✅ from the code when the office reads clean again
(Colten 2026-09-24: marked by hand until now)."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from automations.icd_alerts import post as P, offices as O

DAY = dt.date(2026, 9, 24)
NOW = dt.datetime(2026, 9, 24, 9, 40)


class RecoveredStagesTest(unittest.TestCase):
    def test_a_clean_read_after_the_fault_recovers_it(self):
        v = P.recovered_stages([{"stage": "sweep", "last": "9/24/2026 9:10:54"}],
                               {"relay": dt.datetime(2026, 9, 24, 9, 29), "knocks": None}, now=NOW)
        self.assertEqual(v, {"sweep": True})

    def test_a_read_before_the_fault_does_not(self):
        v = P.recovered_stages([{"stage": "sweep", "last": "9/24/2026 9:10:54"}],
                               {"relay": dt.datetime(2026, 9, 24, 9, 5), "knocks": None}, now=NOW)
        self.assertEqual(v, {"sweep": False})

    def test_too_soon_after_the_last_occurrence_waits(self):
        v = P.recovered_stages([{"stage": "sweep", "last": "9/24/2026 9:38:00"}],
                               {"relay": dt.datetime(2026, 9, 24, 9, 39), "knocks": None}, now=NOW)
        self.assertEqual(v, {"sweep": False})

    def test_knocks_faults_need_the_knocks_relay(self):
        v = P.recovered_stages([{"stage": "knocks-slow", "last": "9/24/2026 9:10:54"}],
                               {"relay": dt.datetime(2026, 9, 24, 9, 29), "knocks": None}, now=NOW)
        self.assertEqual(v, {"knocks-slow": False})
        v = P.recovered_stages([{"stage": "knocks-slow", "last": "9/24/2026 9:10:54"}],
                               {"relay": None, "knocks": dt.datetime(2026, 9, 24, 9, 29)}, now=NOW)
        self.assertEqual(v, {"knocks-slow": True})


class CloseRecoveredFaultsTest(unittest.TestCase):
    HEAD_F = ["Office", "Day", "Stage", "Summary", "Detail", "Count", "First At", "Last At",
              "Local Time", "Agent", "Platform", "Last Posted At"]

    def _book(self, fault_last="9/24/2026 9:10:54", relay_at="9/24/2026 9:29:06", posted="x"):
        faults = [self.HEAD_F, ["colten", "2026-09-24", "sweep", "TimeoutError", "", "2",
                                "9/24/2026 9:10:34", fault_last, "", "icd_alerts/5", "Darwin", posted]]
        relay = [["Office", "Day", "Records JSON", "Received At"], ["colten", "2026-09-24", "{}", relay_at]]
        knocks = [["Office", "Day", "a", "b", "c", "Received At"], ["colten", "2026-09-24", "", "", "", relay_at]]
        tabs = {P.FAULTS_TAB: faults, P.RELAY_TAB: relay, P.KNOCKS_TAB: knocks}
        book = mock.MagicMock()
        def ws(name):
            t = mock.MagicMock(); t.get_all_values.return_value = tabs[name]; return t
        book.worksheet.side_effect = ws
        return book

    def _run(self, book, threads, send=True):
        tmp = pathlib.Path(tempfile.mkdtemp()) / "threads.json"
        tmp.write_text(json.dumps(threads))
        posts, reacts = [], []
        client = mock.MagicMock(); client.reactions_add.side_effect = lambda **k: reacts.append(k)
        office = O.AlertOffice(key="colten", owner="Colten Wright", label="Colten's Local Office",
                               channels=(), timezone="America/New_York")
        with mock.patch.object(P, "FAULT_THREADS_PATH", tmp), \
             mock.patch.object(P, "_slack", lambda ch, text, thread_ts=None: posts.append((text, thread_ts)) or "t2"), \
             mock.patch("automations.shared.slack_metrics_post._client", return_value=client), \
             mock.patch.object(P.O, "get", lambda k: office):
            closed = P.close_recovered_faults(DAY, send=send, book=book, log=lambda *a, **k: None, now=NOW)
        return closed, posts, reacts, json.loads(tmp.read_text())

    def test_a_recovered_office_gets_a_tick_and_a_thread_reply(self):
        closed, posts, reacts, threads = self._run(self._book(), {"2026-09-24|colten": "1790259090.377869"})
        self.assertEqual(closed, ["colten"])
        self.assertEqual(reacts[0]["timestamp"], "1790259090.377869")
        self.assertEqual(reacts[0]["name"], "white_check_mark")
        self.assertEqual(posts[0][1], "1790259090.377869")
        self.assertIn("reading fine again", posts[0][0])
        self.assertIn("9:29", posts[0][0])
        self.assertIn("2026-09-24|colten|recovered", threads)

    def test_only_once(self):
        closed, posts, _r, _t = self._run(self._book(), {"2026-09-24|colten": "ts", "2026-09-24|colten|recovered": "done"})
        self.assertEqual(closed, [])
        self.assertEqual(posts, [])

    def test_still_failing_stays_red(self):
        closed, posts, _r, _t = self._run(self._book(fault_last="9/24/2026 9:38:00", relay_at="9/24/2026 9:20:00"),
                                          {"2026-09-24|colten": "ts"})
        self.assertEqual(closed, [])
        self.assertEqual(posts, [])

    def test_dry_run_sends_nothing(self):
        closed, posts, reacts, threads = self._run(self._book(), {"2026-09-24|colten": "ts"}, send=False)
        self.assertEqual(posts, [])
        self.assertEqual(reacts, [])
        self.assertNotIn("2026-09-24|colten|recovered", threads)


if __name__ == "__main__":
    unittest.main()
