"""The Chrome-profile wait must never outlive the run's own budget.

WHY THIS TEST EXISTS: with a flat 1800s wait, `mobrium_list` (12m timeout) spent
BOTH its attempts on 2026-08-28 sitting in the profile wait and was killed
mid-wait each time — nothing written, nothing posted, and no error in the log,
because the kill lands before the launch that would have raised. Any report
whose timeout is under 30 minutes had the same silent death waiting for it.
"""
import os
import unittest

from automations.shared import tableau_patchright as tp


class ProfileWaitBudget(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("HUB_REPORT_TIMEOUT_S")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("HUB_REPORT_TIMEOUT_S", None)
        else:
            os.environ["HUB_REPORT_TIMEOUT_S"] = self._saved

    def _budget(self, value):
        if value is None:
            os.environ.pop("HUB_REPORT_TIMEOUT_S", None)
        else:
            os.environ["HUB_REPORT_TIMEOUT_S"] = value
        return tp._profile_wait_budget()

    def test_unset_keeps_the_old_ceiling(self):
        """A hand run, or a module driven directly, behaves exactly as before."""
        self.assertEqual(self._budget(None), tp._PROFILE_LOCK_WAIT_S)

    def test_short_report_waits_a_fraction_of_its_own_budget(self):
        """mobrium_list's 12m: it must give up long before the 12m kill."""
        self.assertLess(self._budget("720"), 720)

    def test_leaves_room_to_do_the_work(self):
        """Waiting the WHOLE budget is the bug — winning the lock on the last
        second is as useless as never winning it."""
        for total in ("600", "720", "1200", "1800"):
            self.assertLessEqual(self._budget(total), float(total) * 0.5,
                                 f"budget {total}s")

    def test_never_exceeds_the_ceiling(self):
        """A very long report still waits at most the old 30 minutes."""
        self.assertEqual(self._budget("99999"), tp._PROFILE_LOCK_WAIT_S)

    def test_floor_survives_a_tiny_budget(self):
        """A 30-second budget shouldn't collapse the wait to zero — that turns
        every ordinary launch race into a failure."""
        self.assertGreaterEqual(self._budget("30"), tp._PROFILE_WAIT_FLOOR_S)

    def test_garbage_falls_back_to_the_ceiling(self):
        """An unparseable or absurd value must never shorten the wait silently."""
        for bad in ("", "abc", "0", "-5"):
            self.assertEqual(self._budget(bad), tp._PROFILE_LOCK_WAIT_S, repr(bad))


if __name__ == "__main__":
    unittest.main()
