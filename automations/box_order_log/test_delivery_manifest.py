"""The BOX Order Log's delivery is VERIFIED, not assumed.

2026-09-17: `verify` was null and the module wrote no manifest, so
delivery_check answered UNKNOWN every day — "ran clean, but nothing can confirm
it DELIVERED" — and failure-box-order-log could not close itself even on a
morning both threads posted fine. These tests hold the two halves together: the
config declaration and the write that satisfies it.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from unittest import mock

from automations.box_order_log import run as box_run

_CONFIG = (Path(__file__).resolve().parents[1] / "day_orchestrator"
           / "schedule_config.json")


def _report() -> dict:
    return json.loads(_CONFIG.read_text())["reports"]["box_order_log"]


class VerifyDeclaration(unittest.TestCase):

    def test_verify_is_wired_to_the_manifest(self):
        self.assertEqual(_report().get("verify"),
                         {"type": "manifest", "report_id": "box-order-log"})

    def test_the_declared_id_is_the_one_the_module_writes(self):
        """A verify block naming an id nothing files under reads as 'no
        manifest' — which is UNKNOWN, i.e. the very hole this closed."""
        self.assertEqual(_report()["verify"]["report_id"], box_run.MANIFEST_ID)

    def test_not_declared_unverifiable(self):
        """close_on: exit_zero is for probes and installers. This delivers a
        thread in two channels anyone can open, so it gets checked."""
        self.assertNotIn("close_on", _report())


class ManifestWrite(unittest.TestCase):

    def _capture(self, posted, failed=(), note=""):
        seen = {}

        def _write(report_id, **kw):
            seen["id"] = report_id
            seen.update(kw)
            return Path("/dev/null")

        with mock.patch("automations.shared.run_manifest.write_manifest", _write):
            box_run._file_manifest(posted, failed, note=note)
        return seen

    def test_a_clean_post_files_a_clean_manifest(self):
        seen = self._capture(["#alphalete-gp-sales", "#a-players-b2b"])
        self.assertEqual(seen["id"], "box-order-log")
        self.assertEqual(seen["failed"], [])
        self.assertEqual(seen["succeeded"],
                         ["#alphalete-gp-sales", "#a-players-b2b"])
        # write_manifest's own resolved() call is what puts the ✅ on the
        # incident thread, so a clean write must NOT suppress its voice.
        self.assertTrue(seen["alert"])

    def test_a_channel_that_dropped_is_recorded_as_failed(self):
        seen = self._capture(["#alphalete-gp-sales"],
                             ["#a-players-b2b — SlackApiError: channel_not_found"])
        self.assertEqual(seen["failed"],
                         ["#a-players-b2b — SlackApiError: channel_not_found"])
        self.assertEqual(seen["succeeded"], ["#alphalete-gp-sales"])
        # The caller already alerted, naming the channel and the exception.
        # A second, vaguer line in the same incident thread is noise.
        self.assertFalse(seen["alert"])

    def test_the_retry_never_double_posts(self):
        """--post alone: it posts a day that never went out, and the day-marker
        makes it a no-op once a thread is live. A blind --resend would put a
        second copy in the channel that worked."""
        seen = self._capture(["#alphalete-gp-sales"], ["#a-players-b2b — boom"])
        self.assertEqual(seen["retry_args"], ["--post"])
        self.assertNotIn("--resend", seen["retry_args"])

    def test_a_write_failure_never_breaks_the_run(self):
        with mock.patch("automations.shared.run_manifest.write_manifest",
                        side_effect=OSError("disk full")):
            box_run._file_manifest(["#alphalete-gp-sales"])   # must not raise

    def test_todays_clean_manifest_verifies_as_done(self):
        """End to end against the real verifier: what the module writes is what
        reconcile reads back as DONE."""
        from automations.day_orchestrator import reconcile
        today = dt.date.today()
        manifest = {"report_id": "box-order-log",
                    "run_ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "ok": True, "kind": "channel", "failed": [],
                    "succeeded": ["#alphalete-gp-sales", "#a-players-b2b"],
                    "note": "posted to #alphalete-gp-sales + #a-players-b2b"}
        with mock.patch("automations.shared.run_manifest.read_manifest",
                        return_value=manifest):
            res = reconcile.verify(
                mock.Mock(verify=_report()["verify"]), today,
                dry_run=True, verbose=False)
        self.assertTrue(res.ok)
        self.assertFalse(res.unknown)


class MarkerPassNeverClobbersAPartialDay(unittest.TestCase):
    """The day-marker is set when ONE channel has a thread, not when every room
    got it — so a later pass finding the day 'already live' must not overwrite a
    recorded drop with a clean answer. 2026-09-17: the first live run posted to
    #alphalete-gp-sales and lost #a-players-b2b to a Slack upload error."""

    def _run(self, existing):
        wrote = []
        with mock.patch("automations.shared.run_manifest.read_manifest",
                        return_value=existing), \
             mock.patch.object(box_run, "_file_manifest",
                               lambda *a, **k: wrote.append((a, k))):
            box_run._file_marker_manifest(dt.date.today(), "a later pass")
        return wrote

    def _manifest(self, failed, day=None):
        day = day or dt.date.today()
        return {"run_ts": dt.datetime.combine(
                    day, dt.time(7, 1)).isoformat(timespec="seconds"),
                "failed": failed, "ok": not failed}

    def test_a_recorded_drop_from_today_is_left_standing(self):
        self.assertEqual(
            self._run(self._manifest(["#a-players-b2b — SlackApiError"])), [])

    def test_a_clean_day_still_gets_its_confirmation(self):
        self.assertEqual(len(self._run(self._manifest([]))), 1)

    def test_yesterdays_drop_does_not_mute_today(self):
        """The freshness rule cuts both ways: a stale failure is not evidence
        about today, and treating it as one would hold the ticket open forever."""
        stale = self._manifest(["#a-players-b2b — SlackApiError"],
                               dt.date.today() - dt.timedelta(days=1))
        self.assertEqual(len(self._run(stale)), 1)

    def test_no_manifest_at_all_still_files_one(self):
        self.assertEqual(len(self._run(None)), 1)


if __name__ == "__main__":
    unittest.main()
