"""The week-3 ping: a button nobody is reminded of is a button nobody presses.

Megan, 2026-11-25: "for the drug test send we should 'ping' on sending them".
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from unittest import mock

from automations.office_admin import drug_nudge as DN, config as C


def _row(action, office, people=None, at="2026-11-25 09:00:00"):
    return {"Action": action, "Office Key": office, "Requested At": at,
            "Details": json.dumps({"people": people or []})}


class ItRespectsThePress(unittest.TestCase):
    WEEK = dt.date(2026, 11, 8)

    def test_a_send_for_this_cohort_counts(self):
        rows = [_row("send_drug", "raf",
                     [{"first_name": "A", "last_name": "B",
                       "start_week": "2026-11-08"}])]
        self.assertTrue(DN.already_sent("raf", self.WEEK, rows))

    def test_a_send_for_another_cohort_does_not(self):
        rows = [_row("send_drug", "raf",
                     [{"first_name": "A", "last_name": "B",
                       "start_week": "2026-11-01"}],
                     at="2026-11-18 09:00:00")]
        self.assertFalse(DN.already_sent("raf", self.WEEK, rows))

    def test_another_office_does_not_count(self):
        rows = [_row("send_drug", "omar",
                     [{"first_name": "A", "last_name": "B",
                       "start_week": "2026-11-08"}])]
        self.assertFalse(DN.already_sent("raf", self.WEEK, rows))

    def test_a_press_with_no_start_week_does_NOT_count(self):
        """This asserted the opposite until 2026-11-25, when the dry run
        showed the date rule reading a hand-picked two-person send as the
        whole cohort. A row that does not name the cohort is no evidence
        about it, and the safe error here is an extra reminder -- the admin
        sees the list before sending, and Sterling refuses a true duplicate
        invite anyway."""
        rows = [_row("send_drug", "raf", [{"first_name": "A", "last_name": "B"}],
                     at="2026-11-25 09:00:00")]
        self.assertFalse(DN.already_sent("raf", self.WEEK, rows))

    def test_a_background_check_is_not_a_drug_send(self):
        rows = [_row("send_bgc", "raf",
                     [{"first_name": "A", "last_name": "B",
                       "start_week": "2026-11-08"}])]
        self.assertFalse(DN.already_sent("raf", self.WEEK, rows))

    def test_an_unreadable_sheet_says_yes(self):
        """A DM claiming nothing has been sent is the one message that makes
        somebody press Send twice and bill the owner twice."""
        with mock.patch("automations.office_admin.sheets.requests_tab",
                        side_effect=RuntimeError("no sheets")):
            self.assertTrue(DN.already_sent("raf", self.WEEK))


class WhoGetsNudged(unittest.TestCase):

    def _run(self, people, drug_mode="live", sent=False, **kw):
        o = C.Office(key="raf", owner="Rafael Hidalgo", appstream_id="11280",
                     drug_mode=drug_mode)
        said = []
        with mock.patch.object(C, "OFFICES", {"raf": o}), \
             mock.patch.object(DN, "already_sent", return_value=sent), \
             mock.patch("automations.office_admin.wk3.find", return_value=people):
            n = DN.run(send=False, today=dt.date(2026, 11, 25),
                       log=said.append, **kw)
        return n, " ".join(said)

    def test_a_live_office_with_people_is_nudged(self):
        n, said = self._run([{"first_name": "Kip", "last_name": "Wilson"}])
        self.assertEqual(n, 1)
        self.assertIn("Kip Wilson", said)

    def test_a_dry_office_is_not(self):
        """Nudging somebody to press a button that orders nothing teaches
        them the nudge is noise."""
        n, said = self._run([{"first_name": "Kip", "last_name": "Wilson"}],
                            drug_mode="dry")
        self.assertEqual(n, 0)
        self.assertIn("would order nothing", said)

    def test_nobody_left_on_the_board_is_not_nudged(self):
        n, said = self._run([{"first_name": "Kip", "last_name": "Wilson",
                              "gone": "Terminated"}])
        self.assertEqual(n, 0)
        self.assertIn("nobody", said)

    def test_an_already_queued_send_is_not_nudged(self):
        n, said = self._run([{"first_name": "Kip", "last_name": "Wilson"}],
                            sent=True)
        self.assertEqual(n, 0)
        self.assertIn("already been queued", said)

    def test_a_calendar_that_cannot_be_read_says_so_and_nudges_nobody(self):
        """A week that could not be READ is not an empty one."""
        o = C.Office(key="raf", owner="Raf", appstream_id="11280",
                     drug_mode="live")
        said = []
        with mock.patch.object(C, "OFFICES", {"raf": o}), \
             mock.patch("automations.office_admin.wk3.find",
                        side_effect=RuntimeError("calendar down")):
            n = DN.run(send=False, today=dt.date(2026, 11, 25), log=said.append)
        self.assertEqual(n, 0)
        self.assertIn("rather than", " ".join(said))
        self.assertNotIn("nothing owed'", " ".join(said).replace("'nothing owed'", ""))


class TheMessage(unittest.TestCase):

    def test_it_leads_with_the_count_and_names_everybody(self):
        txt = DN.message("Rafael Hidalgo",
                         [{"first_name": "Kip", "last_name": "Wilson"},
                          {"first_name": "Ada", "last_name": "Fournier"}],
                         dt.date(2026, 11, 8))
        self.assertIn("2 people", txt)
        self.assertIn("Nov 8", txt)
        self.assertIn("Kip Wilson", txt)
        self.assertIn("Ada Fournier", txt)

    def test_one_person_reads_as_one_person(self):
        txt = DN.message("Raf", [{"first_name": "Kip", "last_name": "Wilson"}],
                         dt.date(2026, 11, 8))
        self.assertIn("1 person is", txt)
        self.assertNotIn("1 people", txt)


if __name__ == "__main__":
    unittest.main()


class APressIsEvidenceAboutTheCohortItNamed(unittest.TestCase):
    """Found by dry-running against Raf's real week on 2026-11-25: a
    two-person hand-picked send read as "the whole cohort is done", and the
    nudge went quiet for 22 people nobody had touched."""

    WEEK = dt.date(2026, 11, 8)

    def test_a_handpicked_send_in_the_same_week_does_not_count(self):
        rows = [_row("send_drug", "raf",
                     [{"first_name": "Jade", "last_name": "Starkes"},
                      {"first_name": "Mason", "last_name": "Odonnell"}],
                     at="2026-11-25 12:34:00")]
        self.assertFalse(DN.already_sent("raf", self.WEEK, rows))

    def test_the_send_list_keeps_the_start_week(self):
        """valid_people used to drop it, so the row recorded WHO and never
        WHICH WEEK -- which is what left the date as the only thing to match
        on."""
        from automations.office_admin.actions import valid_people
        got = valid_people([{"first_name": "Kip", "last_name": "Wilson",
                             "email": "k@gmail.com",
                             "start_week": "2026-11-08"}])
        self.assertEqual(got[0]["start_week"], "2026-11-08")
