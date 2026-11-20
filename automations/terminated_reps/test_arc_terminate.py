"""python -m unittest automations.terminated_reps.test_arc_terminate"""
import datetime as dt
import unittest

from automations.terminated_reps import arc_terminate as arc
from automations.terminated_reps import slack_post

TODAY = dt.date(2026, 11, 20)


def _agent(first, last, email="", start="2026-11-16", end="5000-12-31", aid=1):
    return {"AgentID": aid, "FirstName": first, "LastName": last,
            "EmailAddress": email,
            "Offices": [{"OfficeID": arc.OFFICE_ID, "StartDate": start + "T00:00:00",
                         "EndDate": end + "T00:00:00"}]}


def _rep(name, day=dt.date(2026, 11, 19), email=""):
    return arc.Rep(name, day, 5, email)


class Match(unittest.TestCase):
    def test_email_match_wins(self):
        a = _agent("Hayden", "Wilson", "hay@x.com")
        got, why = arc.match(_rep("H. Wilson", email="HAY@x.com"), [a], TODAY)
        self.assertIs(got, a)
        self.assertEqual(why, "")

    def test_name_match_without_email(self):
        a = _agent("Leo", "Buholtz")
        self.assertIs(arc.match(_rep("leo  buholtz"), [a], TODAY)[0], a)

    def test_board_parenthetical_still_matches(self):
        a = _agent("Leo", "Buholtz")
        self.assertIs(arc.match(_rep("Leo Buholtz (Wk 1)"), [a], TODAY)[0], a)

    def test_not_in_arc_is_silent(self):
        self.assertEqual(arc.match(_rep("Ana Lopez"), [_agent("Leo", "Buholtz")], TODAY),
                         (None, ""))

    def test_two_hits_go_to_eve(self):
        a, b = _agent("Chloe", "Johnson", aid=1), _agent("Chloe", "Johnson", aid=2)
        got, why = arc.match(_rep("Chloe Johnson"), [a, b], TODAY)
        self.assertIsNone(got)
        self.assertIn("2 active ARC agents", why)

    def test_already_terminated_is_not_a_match(self):
        a = _agent("Leo", "Buholtz", end="2026-11-19")
        self.assertEqual(arc.match(_rep("Leo Buholtz"), [a], TODAY), (None, ""))

    def test_rehire_after_termination_is_vetoed(self):
        a = _agent("Leo", "Buholtz", start="2026-11-20")
        got, why = arc.match(_rep("Leo Buholtz", day=dt.date(2026, 11, 10)), [a], TODAY)
        self.assertIsNone(got)
        self.assertIn("rehired", why)

    def test_raf_is_never_matched(self):
        a = _agent("Rafael", "Hidalgo")
        self.assertEqual(arc.match(_rep("Rafael Hidalgo"), [a], TODAY), (None, ""))


class Grid(unittest.TestCase):
    def _reps(self, rows):
        from automations.terminated_reps.board import to_date, week_sunday
        grid = [["Rep Name", "Lead", "Days", "Date", "", "", "Notes"]] + rows
        return arc.reps_from_grid(grid, {week_sunday(TODAY)},
                                  week_sunday=week_sunday, to_date=to_date)

    def test_ffp_owner_and_old_weeks_are_skipped(self):
        reps = self._reps([
            ["Leo Buholtz", "Raf", 3, "2026-11-19", True, True, ""],
            ["Ana Lopez", "Raf", 3, "2026-11-18", False, False, "FFP"],
            ["Rafael Hidalgo", "Raf", 3, "2026-11-18", False, False, ""],
            ["Old Guy", "Raf", 3, "2026-10-01", False, False, ""],
        ])
        self.assertEqual([r.name for r in reps], ["Leo Buholtz"])


class StatusLine(unittest.TestCase):
    class O:
        ov, slack, arc = "done", "done", ""

    def test_no_arc_part_for_reps_not_in_arc(self):
        self.assertNotIn("ARC", slack_post.render_status(self.O()))

    def test_arc_done_shows(self):
        o = self.O(); o.arc = "done"
        self.assertTrue(slack_post.render_status(o).endswith("✅ ARC"))

    def test_arc_tick_survives_a_later_run(self):
        self.assertEqual(slack_post._keep_arc(" · ✅ OwnerVille · ✅ Slack · ✅ ARC",
                                              " · ✅ OwnerVille · ✅ Slack"),
                         " · ✅ OwnerVille · ✅ Slack · ✅ ARC")


if __name__ == "__main__":
    unittest.main()
