"""The quiet nudge has to actually reach the owner, and only a silent machine
is quiet.

2026-09-21, 11:00: "Khalil's Local Office -- the alerts computer last checked
in at 10:07, 52 min ago. No Slack id on file." Both halves were wrong:

  * his computer sent knocks at 11:08 and a SaraPlus fault at 11:07 -- it was
    failing a sign-in (already alerted), not silent. Only the SALES clock was
    read, and a machine that cannot sign in never writes it.
  * he HAS a Slack id. The nudge loop used `key` without binding it, so every
    nudge since 2026-09-18 died on UnboundLocalError and was swallowed.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.icd_alerts import post as P


class TheNudgeIsSentTest(unittest.TestCase):
    def _run(self, quiet, helpers=None):
        dms, logs = [], []
        with mock.patch.object(P, "quiet_offices", return_value=quiet), \
             mock.patch.object(P, "_warned", return_value={}), \
             mock.patch.object(P, "laptop_keys", return_value=set()), \
             mock.patch.object(P, "restart_risks", return_value=[]), \
             mock.patch.object(P, "_dm", side_effect=lambda u, t: dms.append(u)), \
             mock.patch.object(P, "_group_dm",
                               side_effect=lambda us, t: dms.extend(us)), \
             mock.patch.object(P, "_slack", return_value="1.1"), \
             mock.patch.object(P.O, "helpers_for",
                               side_effect=lambda k: (helpers or {}).get(k, ())), \
             mock.patch.object(P.O, "office_now",
                               return_value=dt.datetime(2026, 9, 21, 11, 30)):
            P.warn_quiet(dt.date(2026, 9, 21), send=True,
                         now=dt.datetime(2026, 9, 21, 11, 30), log=logs.append)
        return dms, logs

    def test_an_office_with_an_id_is_actually_dmd(self):
        q = {"office": "khalil-nds", "label": "Khalil's Local Office",
             "last": "9/21/2026 10:07:51", "reason": "last checked in"}
        dms, logs = self._run([q])
        self.assertIn("U045F9JCPJT", dms, logs)
        self.assertFalse([l for l in logs if "UnboundLocalError" in l])

    def test_the_helper_is_the_quiet_offices_own(self):
        q = {"office": "khalil-nds", "label": "K", "last": "9/21/2026 10:07:51",
             "reason": "last checked in"}
        dms, _ = self._run([q], helpers={"khalil-nds": ("UFRANCIA",),
                                         "roshan": ("UWRONG",)})
        self.assertIn("UFRANCIA", dms)
        self.assertNotIn("UWRONG", dms)


class AnySignOfLifeCountsTest(unittest.TestCase):
    def _book(self, relay, knocks, faults):
        tabs = {P.RELAY_TAB: relay, P.KNOCKS_TAB: knocks, P.FAULTS_TAB: faults}
        ws = lambda name: mock.Mock(**{"get_all_values.return_value": tabs[name]})
        return mock.Mock(**{"worksheet.side_effect": ws})

    def _relay_row(self, office, received):
        r = [""] * 12
        r[P.COL_OFFICE], r[P.COL_DAY], r[P.COL_RECEIVED] = office, "2026-09-21", received
        return r

    def test_knocks_and_faults_keep_a_machine_alive(self):
        relay = [["h"] * 12, self._relay_row("khalil-nds", "9/21/2026 10:07:51")]
        knocks = [["Office", "Day", "Rows JSON", "Tracker JSON", "Rep Count",
                   "Received At"],
                  ["khalil-nds", "2026-09-21", "[]", "[]", "0", "9/21/2026 11:08:24"]]
        fault = [""] * 12
        fault[P.F_OFFICE], fault[P.F_DAY], fault[P.F_LAST] = (
            "khalil-nds", "2026-09-21", "9/21/2026 11:07:54")
        seen, ever = P.check_ins(dt.date(2026, 9, 21),
                                 book=self._book(relay, knocks, [["h"] * 12, fault]))
        self.assertEqual(seen["khalil-nds"], "9/21/2026 11:08:24")

    def test_a_truly_silent_machine_is_still_caught(self):
        relay = [["h"] * 12, self._relay_row("roshan", "9/21/2026 10:07:51")]
        seen, _ = P.check_ins(dt.date(2026, 9, 21),
                              book=self._book(relay, [["Office"]], [["h"] * 12]))
        self.assertEqual(seen["roshan"], "9/21/2026 10:07:51")


class SaturdayEveningIsNotQuietTest(unittest.TestCase):
    """2026-10-17: six offices stopped at 16:58 local -- the agent's Saturday
    end -- and were posted as quiet until 21:30. Each checked in again at its
    midnight close-out. Saturday after 17:00 local is not a watch window."""

    SAT, MON = dt.date(2026, 10, 17), dt.date(2026, 10, 12)

    def _at(self, day, h, m):
        return dt.datetime(day.year, day.month, day.day, h, m)

    def test_saturday_closes_at_the_agents_own_end(self):
        self.assertTrue(P.quiet_watch_open(self._at(self.SAT, 16, 59)))
        self.assertFalse(P.quiet_watch_open(self._at(self.SAT, 17, 0)))
        self.assertFalse(P.quiet_watch_open(self._at(self.SAT, 17, 45)))
        self.assertFalse(P.quiet_watch_open(self._at(self.SAT, 21, 30)))

    def test_weekdays_unchanged(self):
        self.assertFalse(P.quiet_watch_open(self._at(self.MON, 10, 59)))
        self.assertTrue(P.quiet_watch_open(self._at(self.MON, 11, 0)))
        self.assertTrue(P.quiet_watch_open(self._at(self.MON, 17, 45)))
        self.assertTrue(P.quiet_watch_open(self._at(self.MON, 21, 59)))
        self.assertFalse(P.quiet_watch_open(self._at(self.MON, 22, 0)))

    def test_no_post_for_a_saturday_1658_stop(self):
        q = {"office": "rashad", "label": "Rashad's Local Office",
             "last": "10/17/2026 16:59:57", "reason": "last checked in"}
        now = self._at(self.SAT, 17, 45)
        posts = []
        with mock.patch.object(P, "quiet_offices", return_value=[q]), \
             mock.patch.object(P, "_warned", return_value={}), \
             mock.patch.object(P, "_save_warned", lambda *a, **k: None), \
             mock.patch.object(P, "laptop_keys", return_value=set()), \
             mock.patch.object(P, "restart_risks", return_value=[]), \
             mock.patch.object(P, "_dm", side_effect=lambda *a: posts.append(a)), \
             mock.patch.object(P, "_slack",
                               side_effect=lambda *a, **k: posts.append(a)), \
             mock.patch.object(P.O, "office_now", return_value=now):
            got = P.warn_quiet(self.SAT, send=True, now=now,
                               log=lambda *a, **k: None)
        self.assertEqual(got, [])
        self.assertEqual(posts, [])


if __name__ == "__main__":
    unittest.main()
