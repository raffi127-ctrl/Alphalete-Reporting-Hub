"""Per-office Slack tokens for the ECO poster (Trang / FRESH SUCCESS, 2026-10-21)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.icd_alerts import office_slack as OS, post as P, approve as A


class OfficeSlackTest(unittest.TestCase):
    def test_unmapped_office_uses_the_default(self):
        with mock.patch.object(OS, "_registry", return_value={}):
            self.assertIsNone(OS.token_file("kash"))
            self.assertIsNone(OS.token_for("kash"))
            self.assertEqual(OS.lucy_id_for("kash"), OS.LUCY_REPORTING)
            self.assertFalse(OS.is_cross_workspace("kash"))

    def test_mapped_office_reads_its_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tok").write_text("﻿xoxb-fresh\n")
            with mock.patch.object(OS, "_registry", return_value={"trang": "tok"}), \
                 mock.patch.object(OS.Path, "home", return_value=Path(d)), \
                 mock.patch.object(OS, "token_file", return_value=Path(d) / "tok"):
                self.assertEqual(OS.token_for("trang"), "xoxb-fresh")
                self.assertTrue(OS.is_cross_workspace("trang"))

    def test_mapped_office_without_the_file_refuses_loudly(self):
        with mock.patch.object(OS, "token_file", return_value=Path("/nonexistent/tok")):
            with self.assertRaises(RuntimeError):
                OS.token_for("trang")

    def test_client_for_passes_the_token_through(self):
        with mock.patch.object(OS, "token_for", return_value="xoxb-fresh"), \
             mock.patch("automations.shared.slack_metrics_post._client") as c:
            OS.client_for("trang")
        c.assert_called_once_with(token="xoxb-fresh")

    def test_post_slack_routes_by_office_and_ops_posts_stay_default(self):
        calls = []
        def fake_client_for(office):
            calls.append(office)
            m = mock.Mock(); m.chat_postMessage.return_value = {"ts": "1.2"}; return m
        with mock.patch.object(OS, "client_for", side_effect=fake_client_for):
            P._slack("C1", "hi", office="trang")
            P._slack("C2", "ops note")
        self.assertEqual(calls, ["trang", None])

    def test_approve_checks_membership_by_the_office_identity(self):
        with mock.patch.object(OS, "lucy_id_for", return_value="UBOT"):
            self.assertEqual(A._lucy_id("trang"), "UBOT")
        self.assertEqual(A._lucy_id(None), OS.LUCY_REPORTING)


if __name__ == "__main__":
    unittest.main()
