"""Who the day's KNOCKS & DISPOSITIONS post tags, and who it must not.

    python -m unittest automations.gap_alerts.test_leader_tags

The rules these pin are the ones with a cost attached: a terminated rep must
never be @-pinged in front of the room, an ambiguous name must never resolve to
the wrong person, and a leader with no Slack account must be NAMED rather than
silently dropped.
"""
import unittest
from unittest import mock

from automations.gap_alerts import leaders as L

# A week tab in miniature. Every anchor terminated_reps.board.find_layout needs
# is here and NOTHING is at a hardcoded index — the columns are found by their
# row-1 titles, exactly as they are on the real board.
#                 1          2                  3                    4
GRID = [
    ["",        "",                 "Leadership Status", "# Days Worked",
     "Termination Date", "Start Date", "MON", "TUES", "WED", "THU", "FRI",
     "SAT", "SUN"],
    ["#",       "WE 9/15- 9/21",    "",                  "", "", ""],
    ["1",       "Rafael Hidalgo",   "Mastermind",        "", "", ""],
    ["2",       "Dylan Twaddle",    "Level 2",           "", "", ""],
    ["3",       "Ivan Soto (Wk 2)", "Level 1",           "", "", ""],
    # terminated by a filled Termination Date (serial 45920 = 2025-09-17)
    ["4",       "Zoria Johnson",    "Level 1",           "", 45920, ""],
    # terminated by a bare 'T' in a day block, no date anywhere
    ["5",       "Edgar Camunez",    "Level 1",           "", "", "",
     "", "", "T"],
    ["6",       "Hayden Wilson",    "Entry Level",       "", "", ""],
    ["7",       "Chris Rivera",     "In Training",       "", "", ""],
    [""],
    ["New Starts/Raf"],
    ["Classroom", "Monday", "Tuesday", "Wednesday"],
    ["Nikki Valentine", "Here", "Here", "Terminated"],
]


class BoardReadTests(unittest.TestCase):
    def test_only_non_terminated_leaders(self):
        got = [l.name for l in L.leaders_from_grid(GRID)]
        self.assertEqual(got, ["Rafael Hidalgo", "Dylan Twaddle", "Ivan Soto"])

    def test_a_termination_date_drops_a_leader(self):
        self.assertNotIn("Zoria Johnson",
                         [l.name for l in L.leaders_from_grid(GRID)])

    def test_a_bare_T_in_a_day_block_drops_a_leader(self):
        """The roster's usual signal: nobody fills the date column in. Reading
        only 'Termination Date' missed 15 of 15 on WE 8.23."""
        self.assertNotIn("Edgar Camunez",
                         [l.name for l in L.leaders_from_grid(GRID)])

    def test_entry_level_and_in_training_are_not_leaders(self):
        got = [l.name for l in L.leaders_from_grid(GRID)]
        self.assertNotIn("Hayden Wilson", got)
        self.assertNotIn("Chris Rivera", got)

    def test_the_new_starts_box_is_never_read(self):
        """It has no Leadership Status column and everyone in it is In
        Training — a name from it in the tag line would be a layout bug."""
        self.assertNotIn("Nikki Valentine",
                         [l.name for l in L.leaders_from_grid(GRID)])

    def test_tenure_markers_come_off_the_display_name(self):
        self.assertEqual(L.display_name("Ivan Soto (Wk 3)"), "Ivan Soto")
        self.assertEqual(L.display_name("Jaylen (Ash) Walker"),
                         "Jaylen (Ash) Walker")

    def test_a_missing_leadership_column_raises(self):
        """Empty and 'the column moved' look identical in the post (no tags)
        and only one of them is a bug."""
        grid = [list(r) for r in GRID]
        grid[0][2] = "Level"
        with self.assertRaises(Exception):
            L.leaders_from_grid(grid)


def _member(uid, real, display=""):
    return {"id": uid, "real_name": real,
            "profile": {"real_name": real, "display_name": display}}


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            mock.patch("automations.shared.slack_tag_learning.lookup",
                       lambda n: None),
            mock.patch("automations.shared.slack_tag_learning.remember",
                       lambda *a, **k: None),
            mock.patch("automations.shared.slack_suppression.is_suppressed",
                       lambda n, r=None: False),
            # The real roster would resolve half of these for real; these tests
            # are about the fallbacks under it.
            mock.patch.object(L, "_new_start_roster", lambda: None),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def _client(self, members):
        cli = mock.Mock()
        cli.users_list.return_value = {"members": members,
                                       "response_metadata": {"next_cursor": ""}}
        return cli

    def test_the_new_start_roster_wins_over_a_name_match(self):
        """Megan: tag them "like it does in the new start text function". That
        roster carries the aliases no matcher can derive — the board says
        'Noemi (Ivette) Ontiveros' and Slack says 'Noemi Rivera'."""
        import types
        hit = types.SimpleNamespace(slack_id="UROSTER", name="Noemi Rivera")
        cli = self._client([_member("UWRONG", "Noemi Ontiveros")])
        with mock.patch.object(L, "_new_start_roster",
                               lambda: types.SimpleNamespace(
                                   by_obcl_name=lambda n: hit)):
            ids, missing = L.resolve_tags(["Noemi (Ivette) Ontiveros"],
                                          client=cli, logfn=lambda *_: None)
        self.assertEqual((ids, missing), (["UROSTER"], []))
        cli.users_list.assert_not_called()

    def test_a_missing_roster_falls_through_to_the_workspace(self):
        cli = self._client([_member("U1", "Rafael Hidalgo")])
        with mock.patch.object(L, "_new_start_roster", lambda: None):
            ids, _ = L.resolve_tags(["Rafael Hidalgo"], client=cli,
                                    logfn=lambda *_: None)
        self.assertEqual(ids, ["U1"])

    def test_resolves_off_the_workspace(self):
        cli = self._client([_member("U1", "Rafael Hidalgo"),
                            _member("U2", "Dylan Twaddle")])
        ids, missing = L.resolve_tags(["Rafael Hidalgo", "Dylan Twaddle"],
                                      client=cli, logfn=lambda *_: None)
        self.assertEqual(ids, ["U1", "U2"])
        self.assertEqual(missing, [])

    def test_two_people_with_one_name_are_never_guessed(self):
        """The workspace really has two live 'Miguel Vargas'. A wrong tag
        @-pings a stranger every day until somebody notices."""
        cli = self._client([_member("U1", "Miguel Vargas"),
                            _member("U2", "Miguel Vargas")])
        ids, missing = L.resolve_tags(["Miguel Vargas"], client=cli,
                                      logfn=lambda *_: None)
        self.assertEqual(ids, [])
        self.assertEqual(missing, ["Miguel Vargas"])

    def test_a_learned_id_skips_the_workspace_page_through(self):
        cli = self._client([])
        with mock.patch("automations.shared.slack_tag_learning.lookup",
                        lambda n: "U9"):
            ids, missing = L.resolve_tags(["Rafael Hidalgo"], client=cli,
                                          logfn=lambda *_: None)
        self.assertEqual((ids, missing), (["U9"], []))
        cli.users_list.assert_not_called()

    def test_suppressed_people_are_dropped_and_not_reported(self):
        """Suppression beats learning, and it is SILENT — naming them would
        move the nagging from the person to the room."""
        cli = self._client([_member("U1", "Rafael Hidalgo"),
                            _member("U2", "Giovanna Santos")])
        with mock.patch("automations.shared.slack_suppression.is_suppressed",
                        lambda n, r=None: n == "Giovanna Santos"):
            ids, missing = L.resolve_tags(["Rafael Hidalgo", "Giovanna Santos"],
                                          client=cli, logfn=lambda *_: None)
        self.assertEqual(ids, ["U1"])
        self.assertEqual(missing, [])

    def test_a_token_without_users_read_still_posts(self):
        cli = mock.Mock()
        cli.users_list.side_effect = RuntimeError("missing_scope: users:read")
        ids, missing = L.resolve_tags(["Rafael Hidalgo"], client=cli,
                                      logfn=lambda *_: None)
        self.assertEqual(ids, [])
        self.assertEqual(missing, ["Rafael Hidalgo"])

    def test_an_accent_on_one_side_still_matches(self):
        """The board writes 'Lemsy Vazquez', Slack writes 'Lemsy V\u00e1zquez'.
        Stripping the accented letter instead of folding it left 'v zquez',
        which shares no word with 'vazquez' — she read as having no Slack
        account at all (Megan's screenshot, 2026-09-20)."""
        cli = self._client([_member("ULEMSY", "Lemsy V\u00e1zquez")])
        ids, missing = L.resolve_tags(["Lemsy Vazquez"], client=cli,
                                      logfn=lambda *_: None)
        self.assertEqual((ids, missing), (["ULEMSY"], []))

    def test_the_board_spelling_is_what_gets_named_when_unreachable(self):
        cli = self._client([])
        _ids, missing = L.resolve_tags(["Lemsy Vazquez"], client=cli,
                                       logfn=lambda *_: None)
        self.assertEqual(missing, ["Lemsy Vazquez"])

    def test_one_person_is_tagged_once(self):
        cli = self._client([_member("U1", "Rafael Hidalgo")])
        ids, _ = L.resolve_tags(["Rafael Hidalgo", "Rafael Hidalgo"],
                                client=cli, logfn=lambda *_: None)
        self.assertEqual(ids, ["U1"])


class RateLimitTests(unittest.TestCase):
    """users.list is Tier 2 and this walks it. A 429 that is not waited out
    loses everyone the curated sources did not already cover — silently, since
    they just read as 'no Slack account'."""

    def _err(self, retry_after="1"):
        from slack_sdk.errors import SlackApiError
        resp = mock.Mock()
        resp.get.side_effect = lambda k, d=None: (
            "ratelimited" if k == "error" else d)
        resp.headers = {"Retry-After": retry_after}
        return SlackApiError("ratelimited", resp)

    def test_it_waits_slacks_own_retry_after_and_finishes(self):
        cli = mock.Mock()
        page = {"members": [_member("U1", "Rafael Hidalgo")],
                "response_metadata": {"next_cursor": ""}}
        cli.users_list.side_effect = [self._err("7"), page]
        slept = []
        got = L._workspace(cli, logfn=lambda *_: None, sleeper=slept.append)
        self.assertEqual([u["id"] for u in got], ["U1"])
        self.assertEqual(slept, [7.0])

    def test_a_non_ratelimit_error_is_not_retried(self):
        cli = mock.Mock()
        cli.users_list.side_effect = RuntimeError("missing_scope")
        with self.assertRaises(RuntimeError):
            L._workspace(cli, logfn=lambda *_: None, sleeper=lambda _: None)
        self.assertEqual(cli.users_list.call_count, 1)


class TagLineTests(unittest.TestCase):
    def test_mentions_then_the_unreachable(self):
        line = L.tag_line(["U1", "U2"], ["Chris Rivera"])
        self.assertIn("<@U1> <@U2>", line)
        self.assertIn("Chris Rivera", line)

    def test_nobody_to_tag_is_an_empty_line_not_a_stray_label(self):
        self.assertEqual(L.tag_line([], []), "")


if __name__ == "__main__":
    unittest.main()
