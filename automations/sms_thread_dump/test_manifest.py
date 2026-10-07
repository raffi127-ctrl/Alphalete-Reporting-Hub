"""SMS thread dump: the ticket closes only when every booking the calendar
lists is in the tab with a readable chat.

    python -m unittest automations.sms_thread_dump.test_manifest

AppStream, the sheet and write_manifest are all mocked: a real clean manifest
closes the report's incident thread in Slack, and a test must never speak in
the channel.
"""
import contextlib
import unittest
from unittest import mock

from automations.sms_thread_dump import run as R
from automations.shared import run_manifest


class _Page:
    url = "https://x/index.cfm?rqst=TOK"


@contextlib.contextmanager
def _session(**_kw):
    yield _Page()


def _rec(name, **kw):
    r = {"date": "10-02-2026", "time": "9", "name": name, "phone": "",
         "board": "", "booked_by": "", "status": "", "thread": [["in"]]}
    r.update(kw)
    return r


def _main(scraped, extra=(), write=None):
    """scraped: {office: (records, [day misses])}."""
    def scrape(page, tok, office, *a, misses=None, **k):
        recs, miss = scraped[office]
        if misses is not None:
            misses.extend(miss)
        return recs

    with mock.patch.object(R, "appstream_direct_session", _session), \
            mock.patch.object(R, "_scrape_office", side_effect=scrape), \
            mock.patch.object(R, "_write_tab",
                              side_effect=write or (lambda r, m, o: ("t", len(r) + 2))), \
            mock.patch.object(R.Path, "write_text"), \
            mock.patch.object(run_manifest, "write_manifest") as wm, \
            mock.patch("builtins.print"):
        rc = R.main(["--office", ",".join(scraped), "--dates",
                     "10-02-2026", *extra])
    return rc, wm


class Complete(unittest.TestCase):
    def test_every_booking_read_is_delivered(self):
        rc, wm = _main({"11580": ([_rec("A"), _rec("B")], [])})
        self.assertEqual(rc, 0)
        self.assertEqual(wm.call_args.args[0], "sms_thread_dump")
        self.assertEqual(list(wm.call_args.kwargs["succeeded"]), ["11580"])
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_applicant_with_no_texts_is_not_a_hole(self):
        _rc, wm = _main({"11580": ([_rec("A", thread=[], error="no chat table")], [])})
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])


class Incomplete(unittest.TestCase):
    def test_short_day_table_is_a_failed_part(self):
        _rc, wm = _main({"11580": ([_rec("A")],
                                   ["10-02-2026: table showed 1 of 4 applicants"])})
        failed = wm.call_args.kwargs["failed"]
        self.assertIn("1 of 4", failed[0])
        self.assertEqual(wm.call_args.kwargs["retry_args"][:2], ["--office", "11580"])

    def test_unreadable_chat_is_a_failed_part(self):
        _rc, wm = _main({"11580": ([_rec("A", thread=[],
                                         error="TimeoutError: x")], [])})
        self.assertIn("could not be read: A", wm.call_args.kwargs["failed"][0])

    def test_unreadable_chat_is_fine_in_bookings_only(self):
        _rc, wm = _main({"11580": ([_rec("A", thread=[], error="x")], [])},
                        extra=["--bookings-only"])
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_empty_office_and_write_error_are_named(self):
        def write(rows, meta, office):
            raise OSError("timeout")
        rc, wm = _main({"11280": ([], []), "11580": ([_rec("A")], [])},
                       write=write)
        failed = wm.call_args.kwargs["failed"]
        self.assertEqual(rc, 1)
        self.assertIn("11280: nothing scraped", failed[0])
        self.assertIn("11580: sheet write failed", failed[1])


class NoProof(unittest.TestCase):
    def test_dry_run_writes_no_manifest(self):
        _rc, wm = _main({"11580": ([_rec("A")], [])}, extra=["--dry-run"])
        wm.assert_not_called()

    def test_limit_probe_writes_no_manifest(self):
        _rc, wm = _main({"11580": ([_rec("A")], [])}, extra=["--limit", "1"])
        wm.assert_not_called()

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(R.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(R.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()
