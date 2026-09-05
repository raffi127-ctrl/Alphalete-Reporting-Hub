"""Checkpoint 2 — the master Terminated Reps list.

Megan 2026-09-05: "I'll add this to Lucy as well so that there are 2
checkpoints before texting happens." Checkpoint 1 is the OBCL "Terminated"
marker; this is the master list, and it catches the case checkpoint 1 and the
Slack-membership replay both miss — a leader whose Slack account was merely
DEACTIVATED, which is never observed as a channel "leave".

Run: python -m unittest automations.new_start_followup.test_terminated_checkpoint
"""
import unittest

from automations.new_start_followup import roster as roster_mod
from automations.new_start_followup import terminated, texts


def _rep(name, date="8/1/2026", notes="", deact="TRUE", row=100):
    return terminated.TerminatedRep(name, date, "Raf", notes, "TRUE", deact, row)


def _table(*reps):
    return {roster_mod._norm(r.raw_name): r for r in reps}


class NameCleaningTests(unittest.TestCase):
    def test_rep_name_is_tab_separated_on_the_sheet(self):
        """Real values look like 'Christian\\tWilliams'."""
        self.assertEqual(terminated._clean("Christian\tWilliams"),
                         "Christian Williams")

    def test_collapses_stray_whitespace(self):
        self.assertEqual(terminated._clean("  Ana \t  Griffin \n"),
                         "Ana Griffin")


class MatchingTests(unittest.TestCase):
    def test_matches_on_an_obcl_alias_not_just_the_display_name(self):
        """The real 2026-09-05 case: the sheet says 'Tadana Manyangadze',
        the roster says 'Tadana Jeti'. She was texted that morning."""
        leader = roster_mod.Leader("U0AG43MB1QR", "Tadana Jeti",
                                   obcl_names=["Tadana Jeti",
                                               "Tadana Manyangadze"])
        hit = terminated.find(leader, _table(_rep("Tadana Manyangadze",
                                                 date="5/29/2026")))
        self.assertIsNotNone(hit)
        self.assertIn("5/29/2026", hit.describe())

    def test_folds_accents_so_anh_dinh_matches(self):
        """Sheet 'Anh Dinh' vs roster 'Anh Đinh'."""
        leader = roster_mod.Leader("U07EMBLBN5A", "Anh Đinh",
                                   obcl_names=["Anh Dinh", "Anh Đinh"])
        self.assertIsNotNone(terminated.find(leader, _table(_rep("Anh Dinh"))))

    def test_an_active_leader_does_not_match(self):
        leader = roster_mod.Leader("U0B9924FHCL", "Tiffani Brown",
                                   obcl_names=["Tiffani Brown"])
        self.assertIsNone(terminated.find(leader, _table(_rep("Anh Dinh"))))

    def test_empty_table_never_blocks(self):
        """A failed read must not block everyone."""
        leader = roster_mod.Leader("U1", "Anyone", obcl_names=["Anyone"])
        self.assertIsNone(terminated.find(leader, {}))


class RehireTests(unittest.TestCase):
    def test_rehired_row_does_not_block(self):
        self.assertTrue(_rep("Someone Back", notes="Rehired 9/1").rehired)
        self.assertFalse(_rep("Someone Gone", notes="").rehired)

    def test_rehire_note_is_case_insensitive(self):
        self.assertTrue(_rep("X Y", notes="REHIRED").rehired)


class DescribeTests(unittest.TestCase):
    def test_names_the_date_and_the_sheet_row_for_a_human_to_check(self):
        """A wrong block means new starts go unchased, so the report has to
        carry enough to overturn it."""
        d = _rep("Tadana Manyangadze", date="5/29/2026", row=2097).describe()
        self.assertIn("Tadana Manyangadze", d)
        self.assertIn("5/29/2026", d)
        self.assertIn("Terminated Reps", d)
        self.assertIn("2097", d)
        self.assertIn("Slack deactivated", d)


class _StubLeader:
    def __init__(self):
        self.name = "Tadana Jeti"
        self.slack_id = "U0AG43MB1QR"
        self.phone = "+19726547599"


class _StubStatus:
    label = "Tadana"

    def __init__(self):
        self.leader = _StubLeader()
        self.owed = 1


def _terminated_outcome():
    return texts.Outcome(
        _StubStatus(), "body", False,
        skipped="TERMINATED — {}".format(
            _rep("Tadana Manyangadze", date="5/29/2026", row=2097).describe()))


class RenderTests(unittest.TestCase):
    def test_terminated_is_reported_loudly_and_not_as_a_number_gap(self):
        out = texts.render([_terminated_outcome()], send=True, terminated_note=None)
        self.assertIn("NOT TEXTED", out)
        self.assertIn("Terminated Reps", out)
        self.assertIn("5/29/2026", out)
        # the bug this guards: it must NOT be counted as a missing number,
        # which would put an ex-employee in the Slack numbers-needed post
        self.assertNotIn("have no number", out)

    def test_a_failed_checkpoint_read_says_the_run_was_degraded(self):
        out = texts.render([_terminated_outcome()], send=True,
                           terminated_note="403 forbidden")
        self.assertIn("ran on ONE checkpoint", out)
        self.assertIn("403 forbidden", out)

    def test_clean_run_says_nothing_about_checkpoints(self):
        out = texts.render([_terminated_outcome()], send=True, terminated_note=None)
        self.assertNotIn("ONE checkpoint", out)


if __name__ == "__main__":
    unittest.main()
