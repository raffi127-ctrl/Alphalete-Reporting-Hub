"""The scrape-results prune drops terminated owners, not just removed tabs.

2026-09-11: Eric Martinez (terminated 2026-09-10) was skipped by the scrape, but
his 'name not found' from the day before stayed in the merged results file, so
the Daily Rep Breakdown opened INCOMPLETE for an owner nobody can fix.

Run: python -m unittest automations.focus_office_att.test_scrape_results_prune
"""
import unittest

from automations.focus_office_att.run_all_owners import _prune_results


class PruneResults(unittest.TestCase):
    TABS = {"Template", "Eric Martinez", "Sam Park", "Melik El Jaiez"}

    def _term(self, name):
        return name == "Eric Martinez"

    def test_terminated_owner_stale_miss_is_dropped(self):
        merged = {"Eric Martinez": "name not found in ownerville — it lists: 'david martinez'",
                  "Sam Park": "ok"}
        self.assertEqual(_prune_results(merged, self.TABS, self._term),
                         {"Sam Park": "ok"})

    def test_real_miss_on_active_owner_is_kept(self):
        merged = {"Melik El Jaiez": "exception: TimeoutError", "Eric Martinez": "ok"}
        self.assertEqual(_prune_results(merged, self.TABS, self._term),
                         {"Melik El Jaiez": "exception: TimeoutError"})

    def test_owner_without_tab_is_still_dropped(self):
        merged = {"Edgar Muniz II": "name not found in ownerville", "Sam Park": "ok"}
        self.assertEqual(_prune_results(merged, self.TABS, lambda _o: False),
                         {"Sam Park": "ok"})


if __name__ == "__main__":
    unittest.main()
