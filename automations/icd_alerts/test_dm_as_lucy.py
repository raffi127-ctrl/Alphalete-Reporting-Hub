"""Owner DMs go out as Lucy or not at all (2026-10-20: the 13:31 quiet-computer
nudge to Khalil + Eve went out as Megan from a laptop run).

    python -m unittest automations.icd_alerts.test_dm_as_lucy
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.icd_alerts import post as P
from automations.shared import slack_metrics_post as smp


class _Client:
    def __init__(self, uid):
        self.uid, self.sent = uid, []

    def auth_test(self):
        return {"user_id": self.uid, "user": "x"}

    def conversations_open(self, users):
        return {"channel": {"id": "G1"}}

    def chat_postMessage(self, **kw):
        self.sent.append(kw)
        return {"ok": True}


class DmAsLucy(unittest.TestCase):

    def setUp(self):
        P._AS_LUCY = None
        self.addCleanup(setattr, P, "_AS_LUCY", None)

    def test_laptop_identity_refuses(self):
        c = _Client("U04G5HJBGFN")          # Megan
        with mock.patch.object(smp, "_client", return_value=c):
            with self.assertRaises(SystemExit):
                P._group_dm(["U1", "U2"], "hi")
        self.assertEqual(c.sent, [])

    def test_lucy_sends(self):
        c = _Client(P.LUCY_REPORTING)
        with mock.patch.object(smp, "_client", return_value=c):
            P._group_dm(["U1", "U2"], "hi")
            P._dm("U1", "hi")
        self.assertEqual(len(c.sent), 2)


if __name__ == "__main__":
    unittest.main()
