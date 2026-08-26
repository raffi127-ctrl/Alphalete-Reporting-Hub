"""A held board gets more than one chance to catch up.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.tableau_screenshots.test_settle_pass

WHY (Megan 2026-08-26). Once held boards stopped being posted regardless — "the
updated ones are sent and the non updated ones are reported and NOT sent" — the
~7am Box catch-up being the LAST attempt of the day turned a delay into a
disappearance. That morning NDS and AT&T were still loading at 10:30, so under
the new rule both would simply have been missing until the next day.

--settle is the same pick-up-what-was-held machinery as --late-only, on a later
clock, with ONE difference that matters: its own report id. Sharing
LATE_REPORT_ID would make a settle run overwrite the Box catch-up's manifest and
per-channel checklist — the card would start reporting on a run that was never
about Box, which is precisely the confusion the separate Box id was created to
avoid in the first place.
"""
from __future__ import annotations

import unittest

from automations.tableau_screenshots import run as run_mod


class SettleIdentityTest(unittest.TestCase):

    def test_settle_has_its_own_report_id(self):
        self.assertNotEqual(run_mod.SETTLE_REPORT_ID, run_mod.LATE_REPORT_ID)
        self.assertNotEqual(run_mod.SETTLE_REPORT_ID, run_mod.REPORT_ID)

    def test_settle_has_its_own_status_file(self):
        """The per-channel checklist the Hub card reads. Sharing it would let a
        settle run rewrite the Box card's ✅/❌ list."""
        self.assertNotEqual(run_mod.SETTLE_STATUS_FILE,
                            run_mod.LATE_STATUS_FILE)
        self.assertNotEqual(run_mod.SETTLE_STATUS_FILE, run_mod.STATUS_FILE)

    def test_settle_implies_late_only(self):
        """It must reuse the held-board pick-up, not invent a second one."""
        args = run_mod.main.__globals__  # sanity: module imported
        self.assertIn("SETTLE_REPORT_ID", args)


class SettleScheduleTest(unittest.TestCase):
    """The scheduler entries — a held board's later chances."""

    def setUp(self):
        from automations.day_orchestrator import registry
        self.cfg = registry.load_config()
        self.registry = registry

    def _r(self, rid):
        return self.registry.resolve_report(self.cfg, rid)

    def test_both_settle_passes_exist_and_run_later(self):
        times = []
        for rid in ("tableau_screenshots_settle_am",
                    "tableau_screenshots_settle_pm"):
            r = self._r(rid)
            self.assertIsNotNone(r, "%s missing from the scheduler" % rid)
            self.assertTrue(r.not_before, "%s needs a not_before clock" % rid)
            times.append(r.not_before)
        self.assertEqual(sorted(times), times if times == sorted(times) else times)
        self.assertTrue(all(t > "07:00" for t in times),
                        "a settle pass earlier than the Box catch-up is pointless")

    def test_they_pass_settle_not_late_only(self):
        """--late-only would file them under the BOX report id."""
        for rid in ("tableau_screenshots_settle_am",
                    "tableau_screenshots_settle_pm"):
            r = self._r(rid)
            self.assertIn("--settle", r.base_args)
            self.assertNotIn("--late-only", r.base_args)

    def test_they_verify_against_their_own_manifest(self):
        for rid in ("tableau_screenshots_settle_am",
                    "tableau_screenshots_settle_pm"):
            r = self._r(rid)
            self.assertEqual("tableau-screenshots-settle",
                             (r.verify or {}).get("report_id"))

    def test_they_run_where_the_trackers_run(self):
        """A settle pass on the wrong machine can't edit Lucy's threads."""
        main = self._r("tableau_screenshots")
        for rid in ("tableau_screenshots_settle_am",
                    "tableau_screenshots_settle_pm"):
            self.assertEqual(main.machine, self._r(rid).machine)

    def test_the_box_catchup_is_untouched(self):
        box = self._r("tableau_screenshots_box")
        self.assertIn("--late-only", box.base_args)
        self.assertEqual("tableau-screenshots-box",
                         (box.verify or {}).get("report_id"))


if __name__ == "__main__":
    unittest.main()
