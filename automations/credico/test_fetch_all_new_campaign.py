"""A login whose campaign just started (no Fee Reports yet) must not fail the
Thursday credico_fetch; a real miss on any other login still does."""
import unittest
from unittest import mock

from automations.credico import report as R
from automations.credico import session as S


def _fake_fetch(fail_for):
    def f(week_label, verbose=True, account="carlos", results=None, manifest=True):
        if account in fail_for:
            raise RuntimeError("week 2026-11-14 not listed on Credico. Available: none")
        results[account] = "ok"
        return [account]
    return f


class FetchAllNewCampaign(unittest.TestCase):
    def setUp(self):
        self.manifest = mock.patch.object(R, "_write_fetch_manifest").start()
        self.addCleanup(mock.patch.stopall)

    def test_raf_with_no_files_is_not_a_failure(self):
        self.assertTrue(S.ACCOUNTS["raf"].get("new_campaign"))
        with mock.patch.object(R, "fetch_week", _fake_fetch({"raf"})):
            got = R.fetch_all("11.8.26", verbose=False)
        self.assertNotIn("raf", got)
        results = self.manifest.call_args[0][2]
        self.assertFalse(any("raf" in k.lower() for k in results))

    def test_established_login_with_no_week_still_fails(self):
        with mock.patch.object(R, "fetch_week", _fake_fetch({"carlos"})):
            with self.assertRaises(RuntimeError):
                R.fetch_all("11.8.26", verbose=False)


if __name__ == "__main__":
    unittest.main()
