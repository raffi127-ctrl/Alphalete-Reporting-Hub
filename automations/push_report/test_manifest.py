"""Hourly push report: proof of delivery only after Slack took the post,
and an unreadable office tab is a named failed part.

    python -m unittest automations.push_report.test_manifest

Sheets, Slack and write_manifest are all mocked: a real clean manifest closes
the report's incident thread in Slack, and a test must never speak there.
"""
import unittest
from unittest import mock

from automations.push_report import run as R
from automations.shared import run_manifest


class _Client:
    def __init__(self, ok=True):
        self.ok, self.posts = ok, []

    def conversations_open(self, users):
        return {"channel": {"id": "D1"}}

    def chat_postMessage(self, channel, text):
        self.posts.append(text)
        return {"ok": self.ok, "error": None if self.ok else "not_in_channel"}


def _main(unreadable=(), ok=True, extra=()):
    def build(collect=None):
        if collect is not None:
            collect.extend(unreadable)
        return "*Push report*"

    client = _Client(ok)
    with mock.patch.object(R, "build_report", side_effect=build), \
            mock.patch("automations.shared.slack_metrics_post._client",
                       return_value=client), \
            mock.patch.object(run_manifest, "write_manifest") as wm, \
            mock.patch("builtins.print"):
        rc = R.main(list(extra))
    return rc, wm, client


class Delivery(unittest.TestCase):
    def test_posted_with_every_office_is_delivered(self):
        rc, wm, client = _main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(wm.call_args.args[0], "push_hourly_report")
        self.assertEqual(len(wm.call_args.kwargs["succeeded"]), len(R.OFFICES))
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_unreadable_tab_is_a_failed_part(self):
        _rc, wm, _c = _main(unreadable=["Atef 23467"])
        self.assertEqual(list(wm.call_args.kwargs["failed"]),
                         ["Atef 23467: diag tab unreadable"])
        self.assertNotIn("Atef 23467", wm.call_args.kwargs["succeeded"])

    def test_slack_refusal_writes_no_proof(self):
        rc, wm, _c = _main(ok=False)
        self.assertEqual(rc, 1)
        wm.assert_not_called()

    def test_dry_run_writes_no_proof(self):
        _rc, wm, client = _main(extra=["--dry-run"])
        wm.assert_not_called()
        self.assertEqual(client.posts, [])

    def test_manifest_error_never_raises(self):
        with mock.patch.object(run_manifest, "write_manifest",
                               side_effect=OSError("disk")), \
                mock.patch("builtins.print"):
            R.record_delivery([], "D1")

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(R.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(R.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()
