"""AI settings pull: the ticket closes only when each office's tab holds what
the audit needs — both buffers, the escalation table, most of Office Info.

    python -m unittest automations.sms_audit.test_pull_ai_settings_manifest

AppStream, the sheet and write_manifest are all mocked: a real clean manifest
closes the report's incident thread in Slack, and a test must never speak in
the channel.
"""
import contextlib
import unittest
from unittest import mock

from automations.sms_audit import pull_ai_settings as P
from automations.sms_audit import ai_settings_tab as TAB
from automations.shared import run_manifest

FULL_FIELDS = {label: "x" for label in P.FIELDS}
ROWS = [{"name": "Wrong number", "routing": "Silent", "message": ""}]


class _Page:
    url = "https://x/index.cfm?rqst=TOK"

    def wait_for_timeout(self, _ms):
        pass


@contextlib.contextmanager
def _session(**_kw):
    yield _Page()


def _main(fields=FULL_FIELDS, rows=ROWS, extra=(), write_err=None):
    with mock.patch.object(P, "appstream_direct_session", _session), \
            mock.patch.object(P.fo, "_switch_office"), \
            mock.patch.object(P, "_open"), \
            mock.patch.object(P.time, "sleep"), \
            mock.patch.object(P, "scrape_settings",
                              return_value={"fields": dict(fields)}), \
            mock.patch.object(P, "scrape_escalations", return_value=list(rows)), \
            mock.patch.object(P.Path, "write_text"), \
            mock.patch.object(TAB, "write", side_effect=write_err,
                              return_value=("AI Settings 11280", 20)), \
            mock.patch.object(run_manifest, "write_manifest") as wm, \
            mock.patch("builtins.print"):
        rc = P.main(["--office", "11280", *extra])
    return rc, wm


class Complete(unittest.TestCase):
    def test_full_pull_is_delivered(self):
        rc, wm = _main()
        self.assertEqual(rc, 0)
        self.assertEqual(wm.call_args.args[0], "sms_ai_settings")
        self.assertEqual(list(wm.call_args.kwargs["succeeded"]), ["11280"])
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_a_few_blank_office_fields_are_reported_not_failed(self):
        fields = {k: v for k, v in FULL_FIELDS.items() if k != "office zip"}
        _rc, wm = _main(fields)
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])
        self.assertIn("office_zip", wm.call_args.kwargs["note"])


class Incomplete(unittest.TestCase):
    def test_missing_buffer_is_a_failed_part(self):
        fields = {k: v for k, v in FULL_FIELDS.items()
                  if not k.startswith("timeslot buffer for times offered")}
        _rc, wm = _main(fields)
        self.assertIn("offered_buffer", wm.call_args.kwargs["failed"][0])

    def test_empty_escalations_is_a_failed_part(self):
        _rc, wm = _main(rows=[])
        self.assertIn("escalations", wm.call_args.kwargs["failed"][0])

    def test_most_office_info_missing_is_a_failed_part(self):
        fields = {k: v for k, v in FULL_FIELDS.items()
                  if k.startswith("timeslot") or k.startswith("ghosting")}
        _rc, wm = _main(fields)
        self.assertTrue(any("Office Info" in f
                            for f in wm.call_args.kwargs["failed"]))

    def test_tab_write_error_is_a_failed_part(self):
        _rc, wm = _main(write_err=OSError("quota"))
        self.assertIn("tab write failed", wm.call_args.kwargs["failed"][0])
        self.assertEqual(wm.call_args.kwargs["retry_args"],
                         ["--office", "11280"])

    def test_nothing_scraped_is_a_failed_part(self):
        rc, wm = _main(fields={}, rows=[])
        self.assertEqual(rc, 1)
        self.assertIn("nothing scraped", wm.call_args.kwargs["failed"][0])


class NoProof(unittest.TestCase):
    def test_dry_run_writes_no_manifest(self):
        _rc, wm = _main(extra=["--dry-run"])
        wm.assert_not_called()

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(P.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(P.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()
