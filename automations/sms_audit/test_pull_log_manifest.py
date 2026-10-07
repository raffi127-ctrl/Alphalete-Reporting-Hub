"""SMS log pull: the ticket closes only when every office's tab holds EVERY
text the page says exists.

    python -m unittest automations.sms_audit.test_pull_log_manifest

AppStream, the sheet and write_manifest are all mocked: a real clean manifest
closes the report's incident thread in Slack, and a test must never speak in
the channel.
"""
import contextlib
import unittest
from unittest import mock

from automations.sms_audit import pull_log as pl
from automations.shared import run_manifest


class _Page:
    url = "https://x/index.cfm?rqst=TOK"

    def wait_for_timeout(self, _ms):
        pass


@contextlib.contextmanager
def _session(**_kw):
    yield _Page()


def _main(pulls, extra=(), write=None):
    """pulls: {office: (rows, total) or an Exception}."""
    def pull(page, tok, office, *a, **k):
        got = pulls[office]
        if isinstance(got, Exception):
            raise got
        rows, total = got
        return rows, (total, None, None)

    with mock.patch.object(pl, "appstream_direct_session", _session), \
            mock.patch.object(pl, "pull_office", side_effect=pull), \
            mock.patch.object(pl, "_write_tab",
                              side_effect=write or (lambda r, m, o: ("t", len(r) + 2))), \
            mock.patch.object(pl.Path, "write_text"), \
            mock.patch.object(run_manifest, "write_manifest") as wm, \
            mock.patch("builtins.print"):
        rc = pl.main(["--office", ",".join(pulls), "--dates",
                      "09-26-2026,10-02-2026", *extra])
    return rc, wm


ROWS = [{"body": "hi"}] * 3


class Complete(unittest.TestCase):
    def test_full_read_on_every_office_is_delivered(self):
        rc, wm = _main({"11280": (ROWS, 3), "23965": (ROWS, 3)})
        self.assertEqual(rc, 0)
        kw = wm.call_args.kwargs
        self.assertEqual(wm.call_args.args[0], "sms_log")
        self.assertEqual(list(kw["succeeded"]), ["11280", "23965"])
        self.assertEqual(list(kw["failed"]), [])
        self.assertEqual(list(kw["retry_args"]), [])


class Incomplete(unittest.TestCase):
    def test_short_read_is_a_failed_part(self):
        rc, wm = _main({"11280": (ROWS, 5)})
        failed = wm.call_args.kwargs["failed"]
        self.assertIn("scraped 3 of the page's 5", failed[0])

    def test_no_page_total_is_a_failed_part(self):
        _rc, wm = _main({"11280": (ROWS, None)})
        self.assertIn("no Total", wm.call_args.kwargs["failed"][0])

    def test_failed_office_is_named_and_retried_alone(self):
        rc, wm = _main({"11280": (ROWS, 3), "23965": RuntimeError("boom")})
        self.assertEqual(rc, 1)
        kw = wm.call_args.kwargs
        self.assertEqual(list(kw["succeeded"]), ["11280"])
        self.assertIn("23965", kw["failed"][0])
        self.assertEqual(kw["retry_args"][:2], ["--office", "23965"])

    def test_empty_office_is_a_failed_part(self):
        rc, wm = _main({"11280": ([], 0)})
        self.assertEqual(rc, 1)
        self.assertIn("nothing scraped", wm.call_args.kwargs["failed"][0])

    def test_sheet_write_error_is_a_failed_part_and_next_office_runs(self):
        def write(rows, meta, office):
            if office == "11280":
                raise OSError("timeout")
            return "t", len(rows) + 2
        rc, wm = _main({"11280": (ROWS, 3), "23965": (ROWS, 3)}, write=write)
        kw = wm.call_args.kwargs
        self.assertEqual(rc, 1)
        self.assertEqual(list(kw["succeeded"]), ["23965"])
        self.assertIn("sheet write failed", kw["failed"][0])


class NoProof(unittest.TestCase):
    def test_dry_run_writes_no_manifest(self):
        _rc, wm = _main({"11280": (ROWS, 3)}, extra=["--dry-run"])
        wm.assert_not_called()

    def test_manifest_error_never_raises(self):
        with mock.patch.object(run_manifest, "write_manifest",
                               side_effect=OSError("disk")), \
                mock.patch("builtins.print"):
            pl.record_delivery([], ["x"], [])

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(pl.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(pl.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()
