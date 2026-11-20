"""A wave retried every tick must not list (or alert) the same failure again.

11/19: ownerville was dead for the Pacific wave, the wave stayed open and was
retried each 5-minute tick, and the 00:45 notice listed every captain's
"NOT sent" line ~7 times (49 lines for 7 captains)."""
import unittest

from automations.captainship_night_knocks import state as ST

R = "RuntimeError: ownerville session expired or missing"


class Dedupe(unittest.TestCase):
    def test_same_failure_is_one_line_with_a_repeat_count(self):
        data = {}
        for _ in range(7):
            self.assertEqual(ST.is_new_failure(data, captain_key="chan",
                                               label="Pacific", reason=R),
                             not data.get("failures"))
            ST.record_failure(data, captain_key="chan", label="Pacific",
                              reason=R)
        self.assertEqual(len(ST.wave_failures(data)), 1)
        self.assertEqual(ST.wave_failures(data)[0]["repeats"], 6)

    def test_other_captain_or_reason_is_still_its_own_line(self):
        data = {}
        ST.record_failure(data, captain_key="chan", label="Pacific", reason=R)
        ST.record_failure(data, captain_key="pat", label="Pacific", reason=R)
        ST.record_failure(data, captain_key="chan", label="Pacific",
                          reason="Kash Rai — board unavailable", kind="office")
        self.assertEqual(len(ST.failures(data)), 3)


class LateResend(unittest.TestCase):
    def test_a_failed_wave_resends_only_that_zones_unsent_offices(self):
        from automations.captainship_night_knocks import run as R
        z = {"A": "America/Los_Angeles", "B": "America/Chicago",
             "C": "America/Los_Angeles"}
        saved = R.Z.zone_for
        R.Z.zone_for = lambda icd: z.get(icd)
        self.addCleanup(setattr, R.Z, "zone_for", saved)
        label = R.Z.ZONE_LABEL.get("America/Los_Angeles", "America/Los_Angeles")
        data = {}
        ST.record_failure(data, captain_key="chan", label=label, reason=R_)
        self.assertEqual(R.wave_failed_offices(data, {"chan": ["A", "B"],
                                                      "pat": ["C"]}), ["A"])

    def test_the_late_note_is_at_the_top_and_the_subject_is_unchanged(self):
        import datetime as dt
        from automations.captainship_night_knocks import mail, run as R
        msg = mail.build(subject=mail.office_subject("A", dt.date(2026, 11, 19)),
                         label="Pacific", icds=["A"],
                         fire_local=dt.datetime(2026, 11, 19, 21),
                         boards=[("A", None)], first=True,
                         to_addrs=["x@example.com"], lead=R.LATE_LEAD)
        self.assertEqual(msg["Subject"], "Thu 11/19 - Daily Knocks - A")
        self.assertIn("glitch", msg.as_string())


R_ = R


if __name__ == "__main__":
    unittest.main()
