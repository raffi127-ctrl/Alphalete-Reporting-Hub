"""approve prints the office's machine faults, so a channel sign-off can't
pass for a working office (Eveliz, 2026-10-05)."""
import datetime as dt
import unittest

from automations.icd_alerts import approve as A

HEAD = ["Office", "Day", "Stage", "Summary", "Detail", "Count",
        "First At", "Last At", "Local", "Agent", "Platform", "Posted"]
TODAY = dt.date(2026, 10, 5)


def fault(office, day, stage, summary, count):
    return [office, day, stage, summary, "", str(count), "", "x", "", "", "", ""]


class MachineHealth(unittest.TestCase):
    def test_eveliz_shape_is_loud(self):
        faults = [HEAD,
                  fault("eveliz", "2026-10-03", "sweep",
                        "AccountProblem: SaraPlus wants a code\nmore", 25),
                  fault("eveliz", "2026-10-05", "sweep",
                        "AccountProblem: SaraPlus wants a code", 11),
                  fault("kash", "2026-10-05", "sweep", "other office", 9)]
        out = "\n".join(A.health_lines("Eveliz", faults, [["Office"]], TODAY))
        self.assertIn("FAILING", out)
        self.assertIn("sweep: 36x since 2026-10-03", out)
        self.assertIn("no credit checks EVER relayed", out)
        self.assertNotIn("other office", out)

    def test_old_faults_and_relaying_office_are_quiet(self):
        faults = [HEAD, fault("kash", "2026-09-20", "sweep", "old", 3)]
        relay = [["Office"], ["kash", "2026-10-05"]]
        self.assertEqual(A.health_lines("kash", faults, relay, TODAY), [])


def fault_at(office, day, stage, summary, count, last):
    """A fault row with a real 'Last At', the way Sheets hands it back."""
    return [office, day, stage, summary, "", str(count), "", last, "", "", "", ""]


def relay_at(office, day, received):
    return [office, day, "{}", received]


def knocks_at(office, day, received):
    return [office, day, "[]", "[]", "5", received]


class NotDoneIsOnlySaidWhenItIsTrue(unittest.TestCase):
    """2026-11-12: Milly (boards posting) and George (signed in twenty minutes
    earlier) were both reported as "setup is still unfinished, so each still
    needs the setup link", because ANY row in three days read as failing."""

    DAY = dt.date(2026, 11, 12)
    D = "2026-11-12"

    def test_a_working_office_with_slow_reads_and_notes_is_not_failing(self):
        # Milly: got past the code screen, set up the forward, slow SaraPlus.
        faults = [HEAD,
                  fault_at("emiliano", self.D, "probe-sara-trust",
                           "SaraPlus trust code-wall 14:45", 1, "11/12/2026 16:45:20"),
                  fault_at("emiliano", self.D, "probe-code-forward-step",
                           "Code forward 14:52: lucy's filter: made", 3, "11/12/2026 16:52:40"),
                  fault_at("emiliano", self.D, "sweep-slow",
                           "RuntimeError: this read took 310 seconds", 4, "11/12/2026 17:15:00"),
                  fault_at("emiliano", self.D, "sweep-timeout",
                           "SweepTimeout: this run passed 300 seconds", 4, "11/12/2026 17:15:10")]
        relay = [["Office"], relay_at("emiliano", self.D, "11/12/2026 18:07:29")]
        out = "\n".join(A.health_lines("emiliano", faults, relay, self.DAY))
        self.assertNotIn("FAILING", out)
        self.assertNotIn("not done", out)
        self.assertNotIn("setup link", out)
        self.assertIn("No sign-in problem is open", out)
        self.assertIn("sweep-slow: 4x", out)
        self.assertNotIn("probe", out)              # notes are not faults

    def test_a_sign_in_problem_that_was_fixed_is_called_cleared(self):
        # George: code screen at 5:25, signed in 5:46, relaying by 5:55.
        faults = [HEAD,
                  fault_at("george", self.D, "signin-saraplus",
                           "AccountProblem: SaraPlus wants to confirm this computer "
                           "with a code it emails you.", 1, "11/12/2026 17:25:50")]
        relay = [["Office"], relay_at("george", self.D, "11/12/2026 17:55:46")]
        out = "\n".join(A.health_lines("george", faults, relay, self.DAY))
        self.assertNotIn("FAILING", out)
        self.assertNotIn("setup link", out)
        self.assertIn("cleared: its computer got through again at 17:55", out)

    def test_a_sign_in_problem_newer_than_the_last_relay_is_still_failing(self):
        faults = [HEAD,
                  fault_at("george", self.D, "signin-saraplus",
                           "AccountProblem: SaraPlus wants to confirm this computer",
                           3, "11/12/2026 17:40:41")]
        relay = [["Office"], relay_at("george", "2026-11-11", "11/11/2026 20:10:00")]
        out = "\n".join(A.health_lines("george", faults, relay, self.DAY))
        self.assertIn("FAILING", out)
        self.assertIn("signin-saraplus: 3x", out)
        self.assertIn("Send them the setup link", out)

    def test_an_ownerville_sign_in_is_judged_on_knocks_not_credit_checks(self):
        faults = [HEAD,
                  fault_at("aiden", self.D, "knocks",
                           "KnocksProblem: The last OwnerVille sign-in failed", 1,
                           "11/12/2026 11:58:19")]
        relay = [["Office"], relay_at("aiden", self.D, "11/12/2026 12:09:01")]
        # Credit checks kept coming, which says nothing about OwnerVille.
        still = "\n".join(A.health_lines("aiden", faults, relay, self.DAY,
                                         knocks=[["Office"]]))
        self.assertIn("FAILING", still)
        fixed = "\n".join(A.health_lines(
            "aiden", faults, relay, self.DAY,
            knocks=[["Office"], knocks_at("aiden", self.D, "11/12/2026 12:13:12")]))
        self.assertNotIn("FAILING", fixed)
        self.assertIn("cleared", fixed)

    def test_never_relayed_still_says_so_even_with_only_slow_reads(self):
        faults = [HEAD, fault_at("newbie", self.D, "sweep-timeout",
                                 "SweepTimeout: this run passed 300 seconds", 4,
                                 "11/12/2026 14:11:44")]
        out = "\n".join(A.health_lines("newbie", faults, [["Office"]], self.DAY))
        self.assertIn("no credit checks EVER relayed", out)
        self.assertIn("not done", out)
        self.assertIn("not what is holding it up", out)

    def test_an_office_with_nothing_but_notes_prints_nothing(self):
        faults = [HEAD, fault_at("zaid", self.D, "probe-sara-trust",
                                 "SaraPlus trust fresh-login-ok", 1,
                                 "11/12/2026 13:54:59")]
        relay = [["Office"], relay_at("zaid", self.D, "11/12/2026 14:19:43")]
        self.assertEqual(A.health_lines("zaid", faults, relay, self.DAY), [])


if __name__ == "__main__":
    unittest.main()
