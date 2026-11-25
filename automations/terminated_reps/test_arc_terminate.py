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


class Gate(unittest.TestCase):
    """Eve 11/25: nothing is terminated in ARC without her ✅."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._dir = tempfile.TemporaryDirectory()
        self._old = (arc.GATE, arc.SEEN, arc._lucy_client)
        arc.GATE = Path(self._dir.name) / "arc_gate.json"
        arc.SEEN = Path(self._dir.name) / "arc_shadow_seen.json"
        self.client = _FakeSlack()
        arc._lucy_client = lambda: self.client

    def tearDown(self):
        arc.GATE, arc.SEEN, arc._lucy_client = self._old
        self._dir.cleanup()

    def _res(self, status="would"):
        return arc.ArcResult("Roderick Evans", dt.date(2026, 11, 24), status,
                             "Roderick Evans <r@x.com> #514758")

    def test_only_eves_tick_counts(self):
        self.assertTrue(arc.approved({"reactions": [
            {"name": "white_check_mark", "users": [arc.EVE_ID]}]}))
        self.assertFalse(arc.approved({"reactions": [
            {"name": "white_check_mark", "users": ["U045Z8N0ZQC"]}]}))
        self.assertFalse(arc.approved({"reactions": [
            {"name": "eyes", "users": [arc.EVE_ID]}]}))
        self.assertFalse(arc.approved(None))

    def test_ask_goes_to_eve_once_and_says_how_to_approve(self):
        g = arc.load_gate()
        arc._ask_eve([self._res()], g, print)
        arc._ask_eve([self._res()], arc.load_gate(), print)
        self.assertEqual(len(self.client.posted), 1)
        users, text = self.client.posted[0]
        self.assertEqual(users, arc.EVE_ID)
        self.assertIn("Roderick Evans", text)
        self.assertIn("react ✅", text)

    def test_no_tick_no_approval_then_tick_approves(self):
        arc._ask_eve([self._res()], arc.load_gate(), print)
        key = arc.gate_key("Roderick Evans", dt.date(2026, 11, 24))
        self.assertEqual(arc.approved_keys(arc.load_gate(), dt.date(2026, 11, 25), print), set())
        self.client.reactions = [{"name": "white_check_mark", "users": [arc.EVE_ID]}]
        self.assertEqual(arc.approved_keys(arc.load_gate(), dt.date(2026, 11, 25), print), {key})

    def test_read_failure_keeps_gate_shut(self):
        arc._ask_eve([self._res()], arc.load_gate(), print)
        self.client.reactions = [{"name": "white_check_mark", "users": [arc.EVE_ID]}]
        self.client.fail_read = True
        old = arc._once_a_day
        arc._once_a_day = lambda *a, **k: None
        try:
            self.assertEqual(arc.approved_keys(arc.load_gate(), dt.date(2026, 11, 25), print), set())
        finally:
            arc._once_a_day = old

    def test_problem_rows_are_told_but_never_approvable(self):
        arc._ask_eve([self._res("2 active ARC agents match (a, b)")], arc.load_gate(), print)
        self.assertEqual(len(self.client.posted), 1)
        self.assertNotIn("react ✅", self.client.posted[0][1])
        self.assertEqual(arc.load_gate()["asks"], [])


class _FakeSlack:
    def __init__(self):
        self.posted, self.reactions, self.fail_read = [], [], False
        self._users = None

    def conversations_open(self, users):
        self._users = users
        return {"channel": {"id": "D1"}}

    def chat_postMessage(self, channel, text):
        self.posted.append((self._users, text))
        return {"ts": "111.222"}

    def conversations_history(self, **kw):
        if self.fail_read:
            raise RuntimeError("missing_scope")
        return {"messages": [{"ts": kw["latest"], "reactions": self.reactions}]}


if __name__ == "__main__":
    unittest.main()
