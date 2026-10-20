"""--skip-box leaves My Service Cloud for later without counting it as owed."""
import unittest
from unittest import mock

from automations.icd_alerts import finish_setup as F


class SkipBoxTest(unittest.TestCase):
    def _run(self, **kw):
        out = []
        done = lambda log: "done"  # noqa: E731
        with mock.patch.object(F, "_update", done), mock.patch.object(F, "_boot_job", done), \
             mock.patch.object(F, "_never_sleeps", done), mock.patch.object(F, "_saraplus", done), \
             mock.patch.object(F, "_service_cloud", mock.Mock(side_effect=AssertionError("must not run"))), \
             mock.patch.object(F, "_resume_push", done):
            rc = F.run(log=out.append, **kw)
        return rc, "\n".join(out)

    def test_skip_box_does_not_run_service_cloud_and_ends_clean(self):
        rc, text = self._run(skip_box=True)
        self.assertEqual(rc, 0, text)
        self.assertIn("left for later on purpose", text)
        self.assertIn("All set", text)

    def test_without_the_flag_service_cloud_runs(self):
        # the mock raises to prove the step was reached; run() catches it per
        # step and reports it in the summary
        rc, text = self._run(skip_box=False)
        self.assertIn("Box sales sign-in", text)
        self.assertIn("failed", text)        # the mock's AssertionError was caught and reported

    def test_cli_flag(self):
        with mock.patch.object(F, "run", return_value=0) as r:
            F.main(["--skip-box"])
        r.assert_called_once_with(skip_box=True)


if __name__ == "__main__":
    unittest.main()
