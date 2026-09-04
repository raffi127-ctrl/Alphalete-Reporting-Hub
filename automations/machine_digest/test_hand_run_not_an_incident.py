"""A report a PERSON ran themselves must not open an incident.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.machine_digest.test_hand_run_not_an_incident

WHAT THIS GUARDS (2026-09-04). `standalone-apex-new-starts` — "*apex_new_starts*
— didn't run clean on Lucy 1" — sat red and unclaimed in
#claudecorrections-and-requests for a day. There was nothing to fix. Megan
hand-ran apex_new_starts from her own laptop at 19:35 on Thu 9/3 and watched it
fail; `hub_autopublish` wrote the Activity row and DELIBERATELY passed
`alert_on_fail=False` ("the person is sitting there watching it fail"). Three
minutes later this watcher read that same row and paged anyway.

Two independent defects made it worse than a stray ping:

  1. it alerted at all — the two halves of the system disagreed about whether a
     hand-run failure is news, and the noisy half won;
  2. it said **Lucy 1**. `_machine_label` treated "not Lucy 2 and not the mini"
     as Lucy 1, but the row's own Machine column said MacBook-Pro-3.local. The
     thread then told whoever picked it up to go read a launchd agent's log on
     Lucy 1 — for a Hub card with no agent at all, whose real flow is a person
     typing `--assist` in a Terminal. Every instruction in it pointed somewhere
     that does not exist.

The direction of the hand-run test is the subtle part and is spelled out in
`_handrun_only_ids`: the ABSENCE of the marker proves nothing (`lucy rerun`
stamps "Mini (auto)", same as a 4am run — 867 of 876 measured rows). Only its
PRESENCE is exact, and only hub_autopublish writes it.
"""
from __future__ import annotations

import unittest

from automations.machine_digest import run as md


class TheHandRunMarker(unittest.TestCase):

    def test_it_recognises_what_hub_autopublish_writes(self):
        # shared/hub_autopublish._who() -> "%s (hand-run)" % who
        self.assertTrue(md._is_hand_run("megan (hand-run)"))
        self.assertTrue(md._is_hand_run("hand-run"))

    def test_a_queued_rerun_is_NOT_read_as_a_hand_run(self):
        """The trap. A human-queued `lucy rerun` stamps the same marker a
        scheduled run does, so it must keep alerting — treating it as a hand run
        would blind the watcher to real failures."""
        for user in ("Mini (auto)", "", "Eve", "auto:Thread Scan"):
            self.assertFalse(md._is_hand_run(user), user)


class TheMachineLabelNamesTheRealBox(unittest.TestCase):

    def test_a_laptop_is_not_called_Lucy_1(self):
        """THE ONE THAT SENT PEOPLE TO THE WRONG MACHINE."""
        self.assertEqual(md._machine_label("MacBook-Pro-3.local", ""),
                         "MacBook-Pro-3.local")

    def test_the_known_boxes_are_unchanged(self):
        self.assertEqual(
            md._machine_label("Lucys-MacBook-Neo.local", "MacBook-Neo"), "Lucy 2")
        self.assertEqual(md._machine_label("alphaletes-mac-mini.local", ""),
                         "the mini")
        self.assertEqual(md._machine_label("Lucys-Mac-mini.local", ""), "Lucy 1")

    def test_a_blank_hostname_keeps_the_old_default(self):
        """No hostname recorded = no new information; don't regress old rows."""
        self.assertEqual(md._machine_label("", ""), "Lucy 1")


class TheErroredBranchSkipsHandRuns(unittest.TestCase):
    """Reproduces the exact Activity row that opened the ticket:

    a3f6780dfc73 | 2026-09-03T19:35:02 | apex-new-starts | apex_new_starts |
    megan (hand-run) | MacBook-Pro-3.local | | failed | 2026-09-03T19:35:02
    """

    APEX_ROW = {"name": "apex_new_starts", "report_id": "apex-new-starts",
                "status": "failed", "count": 1, "failed_count": 0,
                "started": "2026-09-03T19:35:02", "ended": "2026-09-03T19:35:02",
                "user": "megan (hand-run)", "machine": "MacBook-Pro-3.local"}

    def _alerts_for(self, row):
        """Run the ERRORED branch's decision over one row."""
        sent = []
        if md._classify(row["status"])[1] not in ("failed", "partial"):
            return sent
        if md._is_hand_run(row.get("user", "")):
            return sent
        sent.append((row["report_id"],
                     md._machine_label(row.get("machine", ""), "")))
        return sent

    def test_megans_hand_run_pages_nobody(self):
        self.assertEqual(self._alerts_for(self.APEX_ROW), [])

    def test_the_same_failure_on_a_schedule_still_pages(self):
        """The watcher's whole reason to exist — do not over-suppress."""
        scheduled = dict(self.APEX_ROW, user="Mini (auto)",
                         machine="Lucys-Mac-mini.local")
        self.assertEqual(self._alerts_for(scheduled),
                         [("apex-new-starts", "Lucy 1")])

    def test_a_scheduled_failure_on_an_unknown_box_names_that_box(self):
        odd = dict(self.APEX_ROW, user="Mini (auto)", machine="some-new-box.local")
        self.assertEqual(self._alerts_for(odd),
                         [("apex-new-starts", "some-new-box.local")])


if __name__ == "__main__":
    unittest.main()
