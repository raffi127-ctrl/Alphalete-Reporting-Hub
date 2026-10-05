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


if __name__ == "__main__":
    unittest.main()
