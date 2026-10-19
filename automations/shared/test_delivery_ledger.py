"""A report that really delivered closes its own ticket; one that only ran
does not (Raf 2026-10-19: "if they got resolved then they should have marked
green"). 20 of 137 stranded tickets were "ran clean, nothing can confirm".

    python -m unittest automations.shared.test_delivery_ledger
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from automations.shared import delivery_check as dc
from automations.shared import delivery_ledger as L

DAY = dt.date(2026, 10, 19)
T = lambda h, m=0: dt.datetime(2026, 10, 19, h, m)  # noqa: E731


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._p = mock.patch.object(L, "LEDGER_DIR", Path(self._tmp.name))
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()


class WhatCounts(_Base):

    def test_real_channel_counts(self):
        self.assertTrue(L.record("slack", "C0123ABC", report_id="vantura_orderlog_sales",
                                 now=T(7, 15)))

    def test_corrections_review_and_dms_do_not(self):
        for dest in (L.CORRECTIONS_CHANNEL, L.REVIEW_CHANNEL, "D0ABC",
                     "#claudecorrections-and-requests", "#revision-emails"):
            self.assertFalse(L.record("slack", dest, report_id="x", now=T(7)), dest)

    def test_email_counts(self):
        self.assertTrue(L.record("email", "owners@x.com", report_id="x", now=T(7)))

    def test_no_report_id_records_nothing(self):
        with mock.patch.object(L, "current_report_id", return_value=""):
            self.assertFalse(L.record("slack", "C0123ABC", now=T(7)))

    def test_slack_hook_reads_resolved_channel(self):
        # Caller passed "#name"; the response carries the real id.
        with mock.patch.object(L, "current_report_id", return_value="r"), \
                mock.patch.object(L, "record", wraps=L.record) as rec:
            L.record_slack_response("chat.postMessage", {"channel": "#alphalete-sales"},
                                    {"ok": True, "channel": "C0SALES"})
        self.assertEqual(rec.call_args[0][:2], ("slack", "C0SALES"))

    def test_slack_hook_ignores_failures_and_reads(self):
        with mock.patch.object(L, "record") as rec:
            L.record_slack_response("chat.postMessage", {"channel": "C1"}, {"ok": False})
            L.record_slack_response("conversations.history", {"channel": "C1"}, {"ok": True})
        rec.assert_not_called()


class DeliveredSince(_Base):

    def test_only_after_the_failure_counts(self):
        L.record("slack", "C1", report_id="vantura_orderlog_sales", now=T(6))
        self.assertIsNone(L.delivered_since(["vantura_orderlog_sales"], T(7)))
        L.record("slack", "C1", report_id="vantura_orderlog_sales", now=T(8))
        self.assertIsNotNone(L.delivered_since(["vantura_orderlog_sales"], T(7)))

    def test_spellings_match(self):
        L.record("slack", "C1", report_id="vantura-orderlog-sales", now=T(8))
        self.assertIsNotNone(L.delivered_since(["vantura_orderlog_sales"], T(7)))


class TicketCloses(_Base):
    """The end-to-end promise: may_close() says DELIVERED (and so the ✅ goes
    on) exactly when the report delivered after it failed."""

    def _verdict(self, rid):
        with mock.patch.object(dc, "_from_phases", return_value=None), \
                mock.patch.object(dc, "_from_verifier", return_value=None), \
                mock.patch.object(dc, "_from_manifest", return_value=None), \
                mock.patch.object(dc, "_from_post_watch", return_value=None), \
                mock.patch.object(dc, "declared_exit_zero", return_value=False), \
                mock.patch.object(dc, "_last_failed_at", return_value=T(7)):
            return dc.verdict(rid, DAY)

    def test_delivered_after_failure_closes(self):
        L.record("slack", "C1", report_id="vantura_orderlog_sales", now=T(8))
        with mock.patch.object(dc, "LEDGER_CLOSES", True):
            self.assertEqual(self._verdict("vantura_orderlog_sales")[0], dc.DELIVERED)

    def test_switched_off_names_the_delivery_but_stays_open(self):
        L.record("slack", "C1", report_id="vantura_orderlog_sales", now=T(8))
        with mock.patch.object(dc, "LEDGER_CLOSES", False):
            v, why = self._verdict("vantura_orderlog_sales")
        self.assertEqual(v, dc.UNKNOWN)
        self.assertIn("delivered slack to C1", why)
        self.assertIn("✅", why)

    def test_ran_but_delivered_nothing_stays_open(self):
        self.assertEqual(self._verdict("vantura_orderlog_sales")[0], dc.UNKNOWN)

    def test_alert_to_corrections_is_not_delivery(self):
        L.record("slack", L.CORRECTIONS_CHANNEL, report_id="vantura_orderlog_sales",
                 now=T(8))
        self.assertEqual(self._verdict("vantura_orderlog_sales")[0], dc.UNKNOWN)

    def test_failed_manifest_outranks_ledger(self):
        L.record("slack", "C1", report_id="b2b_metrics", now=T(8))
        with mock.patch.object(dc, "_from_phases", return_value=None), \
                mock.patch.object(dc, "_from_verifier", return_value=None), \
                mock.patch.object(dc, "_from_manifest",
                                  return_value=(dc.NOT_DELIVERED, "2 parts failed")), \
                mock.patch.object(dc, "declared_exit_zero", return_value=False):
            self.assertEqual(dc.verdict("b2b_metrics", DAY)[0], dc.NOT_DELIVERED)

    def test_module_name_spelling_found(self):  # noqa: D401
        # A standalone agent with no HUB_REPORT_ID records under its module.
        L.record("slack", "C1", report_id="vantura_orderlog_sales", now=T(8))
        with mock.patch.object(dc, "_report",
                               return_value={"command": ["automations.vantura_orderlog_sales.run"]}):
            self.assertIn("vantura_orderlog_sales", dc._ledger_ids("orderlog_sales_7am"))


class RecordingClient(unittest.TestCase):

    def test_successful_post_is_recorded_and_response_untouched(self):
        from slack_sdk import WebClient
        from automations.shared import slack_metrics_post as smp
        cls = smp._recording_client_class()
        resp = {"ok": True, "channel": "C0SALES"}
        with mock.patch.object(WebClient, "api_call", return_value=resp), \
                mock.patch("automations.shared.delivery_ledger.record_slack_response") as hook:
            out = cls(token="x").api_call("chat.postMessage",
                                          json={"channel": "C0SALES", "text": "hi"})
        self.assertIs(out, resp)
        hook.assert_called_once()
        self.assertEqual(hook.call_args[0][1]["channel"], "C0SALES")

    def test_hook_error_never_breaks_a_send(self):
        from slack_sdk import WebClient
        from automations.shared import slack_metrics_post as smp
        cls = smp._recording_client_class()
        with mock.patch.object(WebClient, "api_call", return_value={"ok": True}), \
                mock.patch("automations.shared.delivery_ledger.record_slack_response",
                           side_effect=RuntimeError("boom")):
            self.assertEqual(cls(token="x").api_call("chat.postMessage", json={})["ok"], True)


if __name__ == "__main__":
    unittest.main()
