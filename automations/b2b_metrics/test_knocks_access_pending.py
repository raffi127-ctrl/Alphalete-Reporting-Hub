"""Knocks for an office whose ownerville access is still "Request Sent".

2026-11-13: knocks went into every B2B thread; Sabrina's pull raised "ov access
request pending" and the section filed as a MISS -> a red incident every
morning for something only the owner approving the request can fix. It is a
"no data yet" section until access lands, then it posts by itself.
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from automations.b2b_metrics import runner as r


def _office():
    return SimpleNamespace(key="sabrina", label="Sabrina", knocks_office="Sabrina Alicea",
                           channel_id="C1", mirror_channels=(), channel_plans=())


class KnocksAccessPending(unittest.TestCase):
    def _run(self, exc):
        def boom(*a, **k):
            raise exc
        item = dict(id="knocks", emoji="", title="Total Knocks", capture=boom)
        with mock.patch.object(r, "expected_items", return_value=[item]), \
             mock.patch.object(r, "_out_dir", return_value=None), \
             mock.patch.object(r, "header_title", return_value="t"):
            return r.run(_office(), post=False, log=lambda *a, **k: None)

    def test_access_pending_is_no_data_not_a_miss(self):
        res = self._run(RuntimeError(
            "Couldn't impersonate 'Sabrina Alicea' in ownerville: ov access "
            "request pending (request sent in office access table)"))
        self.assertIn("knocks", res.get("no_data") or [])

    def test_any_other_knocks_failure_is_still_not_no_data(self):
        res = self._run(RuntimeError("impersonation landed on someone else"))
        self.assertNotIn("knocks", res.get("no_data") or [])


if __name__ == "__main__":
    unittest.main()
