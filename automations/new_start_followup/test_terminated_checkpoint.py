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


class StillActiveTests(unittest.TestCase):
    def test_rehired_row_does_not_block(self):
        self.assertTrue(_rep("Someone Back", notes="Rehired 9/1").still_active)
        self.assertFalse(_rep("Someone Gone", notes="").still_active)

    def test_rehire_note_is_case_insensitive(self):
        self.assertTrue(_rep("X Y", notes="REHIRED").still_active)

    def test_ffp_is_not_terminated(self):
        """Megan 2026-09-05: FFP = Field Forever Program — he isn't in the
        OFFICE, he isn't gone. Kaleb Muvunyi's real row. Fine to text, and Raf
        is in every text now anyway."""
        self.assertTrue(_rep("Kaleb Muvunyi", notes="FFP").still_active)
        self.assertTrue(_rep("Kaleb Muvunyi", notes="ffp").still_active)

    def test_ffp_row_is_left_out_of_the_blocking_table(self):
        leader = roster_mod.Leader("U0B4RUR83J9", "Kaleb Muvunyi",
                                   obcl_names=["Kaleb Muvunyi"])
        table = {roster_mod._norm(r.raw_name): r
                 for r in [_rep("Kaleb Muvunyi", notes="FFP")]
                 if not r.still_active}
        self.assertIsNone(terminated.find(leader, table))

    def test_a_substring_does_not_accidentally_unblock(self):
        """Word-boundary matched, so 'offp'/'preffpay' can't un-block."""
        self.assertFalse(_rep("X Y", notes="stuffpile").still_active)


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


class LearnOnceTests(unittest.TestCase):
    """Megan 2026-09-05: "learn though each week the users and not ask again
    other weeks." The same 20 names must not be re-listed every Saturday."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._orig = terminated.SEEN_PATH
        terminated.SEEN_PATH = Path(tempfile.mkdtemp()) / "seen.json"

    def tearDown(self):
        terminated.SEEN_PATH = self._orig

    def test_everyone_is_new_the_first_week(self):
        self.assertEqual(terminated.unseen(["Olivia Turner", "Shen Mitchell"]),
                         ["Olivia Turner", "Shen Mitchell"])

    def test_named_once_then_never_again(self):
        terminated.mark_seen(["Olivia Turner"], "2026-09-05")
        self.assertEqual(terminated.unseen(["Olivia Turner", "Shen Mitchell"]),
                         ["Shen Mitchell"])

    def test_matching_survives_spelling_and_tab_separators(self):
        """The sheet writes 'First\\tLast'; the roster may differ in accents."""
        terminated.mark_seen(["Anh\tDinh"], "2026-09-05")
        self.assertEqual(terminated.unseen(["Anh Đinh"]), [])

    def test_first_seen_date_is_not_overwritten(self):
        terminated.mark_seen(["Olivia Turner"], "2026-09-05")
        terminated.mark_seen(["Olivia Turner"], "2026-09-12")
        self.assertEqual(terminated.load_seen()[
            terminated._norm_name("Olivia Turner")], "2026-09-05")

    def test_a_missing_store_just_means_nobody_has_been_told(self):
        self.assertFalse(terminated.SEEN_PATH.exists())
        self.assertEqual(terminated.load_seen(), {})

    def test_marking_nothing_writes_nothing(self):
        terminated.mark_seen([], "2026-09-05")
        self.assertFalse(terminated.SEEN_PATH.exists())


class SeenPathTests(unittest.TestCase):
    def test_real_store_lives_under_gitignored_output(self):
        """It lists who was terminated and the repo is PUBLIC, so it must sit
        under output/ — never committed. (Not in LearnOnceTests, whose setUp
        patches SEEN_PATH to a temp dir.)"""
        self.assertEqual(terminated.SEEN_PATH.parent.name, "output")


if __name__ == "__main__":
    unittest.main()
