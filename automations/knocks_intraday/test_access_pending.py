"""An office whose ownerville access request is still pending is WAITING, not
failed.

2026-10-26: Omar's first 9 PM board died twice — first on a misspelled name,
then (name fixed) on "ov access request pending (request sent in office access
table)": he had not accepted our request yet. Nothing in the code can fix that,
so it must not open a red #claudecorrections ticket every night until he does.
A real broken pull next to it still fails the slot.
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.knocks_intraday import roster
from automations.knocks_intraday import run as RUN
from automations.knocks_intraday import schedule as S

PENDING = RuntimeError("Couldn't impersonate 'Omar Mohamad' in ownerville: "
                       "ov access request pending (request sent in office "
                       "access table)")


def _rec(key, error):
    office = roster.enrolled("eod")[0]
    return {"key": key, "label": key, "day": None, "abbr": "EST",
            "error": error, "png": None, "office": office,
            "channel_id": "C0", "channel_name": "#x"}


class AccessPendingTest(unittest.TestCase):
    def setUp(self):
        self.slot = S.SLOTS_BY_KEY["eod"]
        p = mock.patch.object(RUN, "_caption", lambda *a, **k: "cap")
        p.start()
        self.addCleanup(p.stop)

    def test_pending_alone_is_not_a_failed_slot(self):
        lines = []
        rc = RUN.post([_rec("omar", PENDING)], self.slot, dry_run=True,
                      logfn=lines.append)
        self.assertEqual(rc, 0)
        self.assertTrue(any("failed=0" in l for l in lines), lines)
        self.assertTrue(any("⏳ omar" in l for l in lines), lines)

    def test_a_real_failure_beside_it_still_fails(self):
        lines = []
        rc = RUN.post([_rec("omar", PENDING),
                       _rec("drew", RuntimeError("name not found in ownerville"))],
                      self.slot, dry_run=True, logfn=lines.append)
        self.assertEqual(rc, 1)
        self.assertTrue(any("failed=1" in l for l in lines), lines)

    def test_manifest_lists_it_as_neither(self):
        written = {}
        with mock.patch("automations.shared.run_manifest.read_manifest",
                        return_value={}), \
             mock.patch("automations.shared.run_manifest.write_manifest",
                        side_effect=lambda *a, **k: written.update(k)):
            RUN.record_delivery(self.slot, [_rec("omar", PENDING)])
        self.assertEqual(written["failed"], [])
        self.assertEqual(written["succeeded"], [])


if __name__ == "__main__":
    unittest.main()
