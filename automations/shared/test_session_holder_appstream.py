"""Which machines keep the AppStream console warm.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_session_holder_appstream

WHY (Megan 2026-08-24: "it should always be able to heal itself", "I need to be
able to not ever touch the lucys").

The holder's whole premise is that a fresh login can never be done unattended —
Cloudflare's Turnstile has no headless path — so the ONLY durable strategy is to
never let the session die: hold it open 24/7 and it is never re-challenged.

That only works on machines the holder actually warms. AppStream warming was
gated to a single machine (Lucy 2), so Lucy 1 and Lucy 3 held ownerville only
and their AppStream token simply aged out — seeded ~06:00 on 8/24, dead by
14:05. On Lucy 1 that took out daily_focus, applicant_sync_morning and both
recruiter_retention reports; on Lucy 3 it took the Recruiting pull of
alphalete_org_focus. The recovery was a human clearing a Turnstile, twice in
one day.

Both halves of the gate still matter and are tested here: a machine needs its
OWN seed file, and it must be a declared hold machine — the second half is what
stops a box with a STALE state file from re-activating warming on its own.
"""
from __future__ import annotations

import unittest

from automations.shared import session_holder as sh


class HoldMachines(unittest.TestCase):

    def test_every_lucy_that_runs_appstream_holds_it(self):
        for m in ("Lucy 1", "Lucy 2", "Lucy 3"):
            with self.subTest(machine=m):
                self.assertIn(m, sh.APPSTREAM_HOLD_MACHINES)

    def test_it_is_a_declared_list_not_open_to_any_machine(self):
        """The machine check is the guard against a stale seed file
        re-activating warming somewhere nobody intended."""
        self.assertIsInstance(sh.APPSTREAM_HOLD_MACHINES, tuple)
        self.assertNotIn("", sh.APPSTREAM_HOLD_MACHINES)
        self.assertNotIn(None, sh.APPSTREAM_HOLD_MACHINES)

    def test_a_laptop_or_unknown_box_does_not_hold(self):
        for m in ("Megan laptop", "Lucy 4", "unknown"):
            with self.subTest(machine=m):
                self.assertNotIn(m, sh.APPSTREAM_HOLD_MACHINES)

    def test_the_old_singular_name_still_resolves(self):
        """Back-compat: anything importing APPSTREAM_HOLD_MACHINE keeps working
        and still points at a machine that really holds."""
        self.assertIn(sh.APPSTREAM_HOLD_MACHINE, sh.APPSTREAM_HOLD_MACHINES)


if __name__ == "__main__":
    unittest.main()
