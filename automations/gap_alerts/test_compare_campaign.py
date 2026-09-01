"""Chan's comparison line has to pin its OWN campaign.

The ownerville campaign is a sticky session GLOBAL. The compare job used to be
appended with no campaign at all, on the reasoning that Chan "keeps his own" —
but no pin does not mean his own, it means whatever the office before him in
the batch pinned. Chan is fiber, so:

  * batched behind Raf   (campaign 3, fiber)        -> rows, line drawn
  * batched behind Calvin (campaign 40, EnergyWell) -> EMPTY, line silently gone

Which is exactly what Megan saw on 2026-09-01: "calvin is still missing the chan
comparison row" while Raf's board carried it. An empty compare pull raises
nothing, so there was no error to find either.

Offline: pull_offices_days is stubbed; the jobs list is the whole assertion.
"""
import datetime as dt
import unittest

from automations.gap_alerts import run as R
from automations.gap_alerts import config as C


class ComparePinsItsOwnCampaign(unittest.TestCase):
    def setUp(self):
        self.jobs = None
        self.day = dt.date(2026, 9, 1)

    def _capture(self, jobs, verbose=True, profile_dir=None):
        self.jobs = list(jobs)
        return [(j[0], {}, None) for j in jobs]

    def _run(self, cfg):
        import automations.rashad_metrics.knocks_pull as KP
        real = KP.pull_offices_days
        KP.pull_offices_days = self._capture
        try:
            R.pull_boards_many([(cfg, "6:00 PM")], self.day, R.Path("/tmp"))
        finally:
            KP.pull_offices_days = real

    def test_the_compare_job_carries_a_campaign(self):
        """Three elements, not two — the third is the pin."""
        self._run(C.CALVIN)
        compare_jobs = [j for j in self.jobs
                        if j[0].strip().lower() != C.CALVIN["name"].lower()]
        self.assertEqual(len(compare_jobs), 1)
        self.assertEqual(len(compare_jobs[0]), 3,
                         "compare job must pin a campaign, not inherit one")
        self.assertTrue(compare_jobs[0][2], "campaign must not be empty")

    def test_compare_campaign_does_not_follow_the_board_it_rides_on(self):
        """Chan's pin is the same whether he is batched behind an Energy Wells
        office or a fiber one. That independence IS the fix."""
        self._run(C.CALVIN)
        behind_ew = [j for j in self.jobs
                     if j[0].strip().lower() != C.CALVIN["name"].lower()][0][2]
        self._run(C.RAF)
        behind_fiber = [j for j in self.jobs
                        if j[0].strip().lower() != C.RAF["name"].lower()][0][2]
        self.assertEqual(behind_ew, behind_fiber)
        self.assertNotEqual(behind_ew, C.CALVIN["campaign_id"],
                            "Chan is fiber; he must not inherit Energy Wells")


if __name__ == "__main__":
    unittest.main()
