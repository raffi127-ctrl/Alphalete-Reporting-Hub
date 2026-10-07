"""What this watcher must never get wrong.

  python -m unittest automations.atef_nds_watch.test_watch
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.atef_nds_watch import run as R

OWNERS_NOW = (
    "Measure Names,Owner & Office ,Rep Name,Measure Values\n"
    "Next Up %-,COLTEN WRIGHT[south shore specialized marketing, inc.],All,0.4\n"
    "Next Up %-,KHALIL MANSOUR[alphalete management group, inc. dba hab],All,0.5\n"
)
TEAMS_NOW = (
    "NDS Captain Teams,Measure Names,Owner Name,Measure Values\n"
    "Colten's Team,CRU,COLTEN WRIGHT,0.8\n"
    "Khalil's Team,CRU,KHALIL MANSOUR,0.7\n"
)


class Find(unittest.TestCase):
    def test_today_nobody_is_there(self):
        f = R.find(OWNERS_NOW, TEAMS_NOW)
        self.assertEqual(f["people"], {})
        self.assertEqual(f["team"], [])
        self.assertEqual(f["owner_count"], 2)

    def test_atef_appears_with_tableau_spelling(self):
        owners = OWNERS_NOW + (
            "Next Up %-,ATEF CHOUDHURY[domin8 acquisitions, inc.],All,0.3\n")
        f = R.find(owners, TEAMS_NOW)
        self.assertEqual(list(f["people"]), ["Atef Choudhury"])

    def test_team_and_dhyey_via_captain_teams(self):
        teams = TEAMS_NOW + "Atef's Team,CRU,DHYEY PATEL,0.6\n"
        f = R.find(OWNERS_NOW, teams)
        self.assertEqual(f["team"], ["Atef's Team"])
        self.assertIn("Dhyey Patel", f["people"])

    def test_blank_read_is_an_error_not_not_there(self):
        with self.assertRaises(ValueError):
            R.find("Measure Names,Owner & Office ,Rep Name,Measure Values\n",
                   TEAMS_NOW)

    def test_message_says_where_it_came_from(self):
        f = R.find(OWNERS_NOW + "x,SABRINA ALICEA[x],All,1\n", TEAMS_NOW)
        txt = R.message(f, R.dt.date(2026, 10, 6))
        self.assertIn("Sabrina Alicea: SI", txt)
        self.assertIn("NDSWeeklyMetricsRep", txt)

    def test_only_atef_is_not_complete_and_says_wait(self):
        # 2026-10-07: Atef showed up alone — switching then blanks everything.
        owners = OWNERS_NOW + (
            "Next Up %-,ATEF CHOUDHURY[domin8 acquisitions, inc.],All,0.3\n")
        f = R.find(owners, TEAMS_NOW)
        self.assertFalse(R.complete(f))
        txt = R.message(f, R.dt.date(2026, 10, 7))
        self.assertIn("NO pases", txt)
        self.assertNotIn("Cesar Castillo", txt)

    def test_all_three_plus_team_is_complete_and_says_go(self):
        owners = OWNERS_NOW + (
            "x,ATEF CHOUDHURY[domin8 acquisitions, inc.],All,0.3\n"
            "x,SABRINA ALICEA[x],All,1\n")
        teams = TEAMS_NOW + "Atef's Team,CRU,DHYEY PATEL,0.6\n"
        f = R.find(owners, teams)
        self.assertTrue(R.complete(f))
        txt = R.message(f, R.dt.date(2026, 10, 9))
        self.assertIn("COMPLETA", txt)
        self.assertIn("Cesar Castillo", txt)


class Stages(unittest.TestCase):
    """The 10/7 first-sighting DM must not swallow the 'complete' DM."""

    def _run(self, owners, teams, state):
        saved, sent = {}, []
        with mock.patch.object(R, "pull", return_value={
                R.VIEW_OWNERS: owners, R.VIEW_TEAMS: teams}), \
             mock.patch.object(R, "load_state", return_value=dict(state)), \
             mock.patch.object(R, "save_state", side_effect=saved.update), \
             mock.patch.object(R, "send", side_effect=lambda t: sent.append(t) or True):
            R.main(["--post"])
        return sent, saved

    def test_complete_dm_goes_out_after_first_sighting(self):
        owners = OWNERS_NOW + ("x,ATEF CHOUDHURY[d],All,1\n"
                               "x,SABRINA ALICEA[x],All,1\n")
        teams = TEAMS_NOW + "Atef's Team,CRU,DHYEY PATEL,0.6\n"
        sent, saved = self._run(owners, teams, {"sent": "2026-10-07"})
        self.assertEqual(len(sent), 1)
        self.assertIn("COMPLETA", sent[0])
        self.assertEqual(saved["sent"], "2026-10-07")
        self.assertIn("complete_sent", saved)

    def test_partial_again_stays_quiet(self):
        owners = OWNERS_NOW + "x,ATEF CHOUDHURY[d],All,1\n"
        sent, _ = self._run(owners, TEAMS_NOW, {"sent": "2026-10-07"})
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
