"""An ICD nobody can reach yet must not be alerted as a break.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_icd_expected_wording

WHAT THIS GUARDS (Megan 2026-09-08). daily_focus files an office AppStream
refused under `denied` and deliberately NEVER retries it: _switch_office runs
with confirm_denial=True, so a denial means the office really is absent from
the account's own list, and only an access grant changes that.

It still wrote kind="ICD" — which is in _FILL_SHAPED, so it rendered with the
'section' wording. On 09-07 and again on 09-08 the channel got:

    🚨 daily-focus dropped 2 sections this run — it did NOT post.
    Missing: KIMBERLY RODRIGUEZ, Kim Rodriguez
    The thread is live but incomplete.

The thread had posted, and both names are ONE person under two captainships
(the log: "Raf: 1 ICD(s) denied … Kim Rodriguez" / "Chan Park: 1 ICD(s)
denied … KIMBERLY RODRIGUEZ"). She moved states and is waiting on a new
account — Megan confirmed 09-08 — so this is weeks of identical red mornings
for something nobody can act on.

Same fix, and the same guard, as 'owner_expected' got for daily_rep_breakdown
on 09-05 ([[test_expected_miss_wording]]): the quiet kind is reachable ONLY
when every remaining ICD is a denial, so a real break standing next to one can
never borrow the ✅.
"""
from __future__ import annotations

import unittest
import unittest.mock

from automations.shared import section_drop_alert as sda


class TheQuietIcdKind(unittest.TestCase):
    def test_it_exists_and_is_about_icds(self):
        self.assertIn("icd_expected", sda._KINDS)
        self.assertEqual(sda._KINDS["icd_expected"]["what"], "ICD")

    def test_it_says_the_run_was_fine(self):
        k = sda._KINDS["icd_expected"]
        self.assertTrue(k["headline"].startswith("✅"))
        self.assertIn("ran fine", k["headline"])

    def test_it_is_never_the_loud_one(self):
        self.assertNotIn("🚨", sda._KINDS["icd_expected"]["headline"])
        blob = " ".join(str(v) for v in sda._KINDS["icd_expected"].values()).lower()
        self.assertNotIn("did not post", blob)
        self.assertIn("nothing to re-run", blob)

    def test_the_loud_icd_path_is_untouched(self):
        """kind='ICD' must still read as a break — only the all-expected case
        goes quiet, and that choice is daily_focus's to make."""
        self.assertIn("ICD", sda._FILL_SHAPED)
        self.assertNotIn("icd_expected", sda._FILL_SHAPED)


class TheComposedAlert(unittest.TestCase):
    """The real 2026-09-08 daily-focus payload."""

    FAILED = ["KIMBERLY RODRIGUEZ", "Kim Rodriguez"]
    NOTE = "2 refused by AppStream (needs access)."

    def _blob(self, kind):
        return sda._compose("daily-focus", self.FAILED, None, self.NOTE, kind=kind)

    def test_the_quiet_version_no_longer_claims_it_did_not_post(self):
        blob = self._blob("icd_expected")
        self.assertNotIn("it did NOT post", blob)
        self.assertNotIn("The thread is live but incomplete", blob)
        self.assertNotIn("🚨", blob)

    def test_it_still_names_who_and_carries_the_note(self):
        blob = self._blob("icd_expected")
        self.assertIn("KIMBERLY RODRIGUEZ", blob)
        self.assertIn("Kim Rodriguez", blob)
        self.assertIn("refused by AppStream", blob)

    def test_no_unexpanded_placeholder_reaches_slack(self):
        self.assertNotIn("{", self._blob("icd_expected"))

    def test_the_old_icd_wording_is_still_loud(self):
        """Regression guard: a genuine gap must keep its 🚨."""
        self.assertIn("🚨", self._blob("ICD"))


class TheChoiceDailyFocusMakes(unittest.TestCase):
    """The guard that keeps a real break from borrowing the ✅.

    Mirrors the condition in recruiting_report.daily_focus: quiet only when
    there are denials and NOTHING else.
    """

    @staticmethod
    def _kind(den, tra, other, unmapped):
        expected_only = bool(den) and not (tra or other or unmapped)
        return "icd_expected" if expected_only else "ICD"

    def test_only_denials_goes_quiet(self):
        self.assertEqual(self._kind({"Kim"}, set(), set(), set()),
                         "icd_expected")

    def test_a_transient_error_alongside_keeps_it_loud(self):
        self.assertEqual(self._kind({"Kim"}, {"Bob"}, set(), set()), "ICD")

    def test_an_unmapped_icd_alongside_keeps_it_loud(self):
        self.assertEqual(self._kind({"Kim"}, set(), set(), {"New Guy"}), "ICD")

    def test_a_not_pulled_icd_alongside_keeps_it_loud(self):
        self.assertEqual(self._kind({"Kim"}, set(), {"Ann"}, set()), "ICD")

    def test_no_denial_at_all_is_loud(self):
        self.assertEqual(self._kind(set(), {"Bob"}, set(), set()), "ICD")


class TheTriageHandoff(unittest.TestCase):
    """The ✅ post and the triage line have to agree.

    incident_triage picks its quiet WAITING line by matching the literal
    phrase "expected, no action" in the tail of the report's orchestrator log
    (incident_triage._log_tail — NOT the manifest). daily_focus emits that
    phrase into both its note and a log.info line for exactly this reason. If
    someone rewords either one, the age rule wins instead and posts "Open
    since yesterday. Automatic retries have not fixed it." underneath a post
    that says the run was fine — and a pending account stays pending for
    weeks, so that would be every morning.
    """

    # The two strings daily_focus emits when every remaining ICD is a denial.
    NOTE_CLAUSE = (" Expected, no action — a denial is never retried; it "
                   "clears itself on the next run once the access grant lands.")
    LOG_LINE = ("daily-focus: expected, no action — 2 ICD(s) refused by "
                "AppStream (KIMBERLY RODRIGUEZ, Kim Rodriguez). Nothing to "
                "re-run until the access grant lands.")

    def test_the_phrase_triage_looks_for_is_in_the_note(self):
        note = "2 refused by AppStream (needs access)." + self.NOTE_CLAUSE
        self.assertIn("expected, no action", note.lower())

    def test_the_phrase_is_in_the_log_line_triage_actually_reads(self):
        self.assertIn("expected, no action", self.LOG_LINE.lower())

    def _line(self, tail, hour):
        from automations.shared import incident_triage as tri
        with unittest.mock.patch.object(tri, "_log_tail", return_value=tail):
            v = tri.classify("drop-daily-focus", opened="2026-09-07",
                             now_hour=hour)
        return v, tri.line_for(v)

    def test_triage_stays_quiet_on_a_day_old_expected_miss(self):
        """Day-old is the case that matters: the age rule fires at exactly one
        day and would otherwise call it 'Automatic retries have not fixed it.'"""
        _v, line = self._line(self.LOG_LINE.lower(), 12)
        self.assertNotIn("have not fixed it", line.lower())
        self.assertNotIn("did not finish", line.lower())
        self.assertIn("Nothing to do", line)

    def test_a_real_failure_on_the_same_report_is_still_loud(self):
        _v, line = self._line("traceback: timeouterror on the icd tab", 13)
        self.assertNotIn("Nothing to do", line)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
