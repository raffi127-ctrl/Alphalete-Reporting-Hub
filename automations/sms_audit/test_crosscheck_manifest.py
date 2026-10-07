"""SMS cross-check: the ticket closes only when every office was COMPARED and
agrees with AppStream's own count.

    python -m unittest automations.sms_audit.test_crosscheck_manifest

AppStream and write_manifest are mocked: a real clean manifest closes the
report's incident thread in Slack, and a test must never speak in the channel.
"""
import contextlib
import unittest
from unittest import mock

from automations.sms_audit import crosscheck as C
from automations.shared import run_manifest


class _Page:
    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, *_a, **_k):
        pass


@contextlib.contextmanager
def _session(**_kw):
    yield _Page()


def _main(ours, appstream=(10, 8), switch=True, offices="11280,11580"):
    """ours: {office: (booked, shown) or None}. AppStream splits its totals
    across the two week slices, so each slice returns half."""
    half = (appstream[0] // 2, appstream[1] // 2)

    def mine(office, lo, hi, suffix=""):
        got = ours[office]
        return (got[0], got[1], "file") if got else (None, None, "no file")

    with mock.patch.object(C, "appstream_direct_session", _session), \
            mock.patch.object(C.fo, "_switch_office", return_value=switch), \
            mock.patch.object(C, "_load_as_week"), \
            mock.patch.object(C, "_parse", return_value={}), \
            mock.patch.object(C, "totals", return_value=half), \
            mock.patch.object(C, "ours", side_effect=mine), \
            mock.patch.object(run_manifest, "write_manifest") as wm, \
            mock.patch("builtins.print"):
        rc = C.main(["--office", offices])
    return rc, wm


class Verdicts(unittest.TestCase):
    def test_every_office_agrees_is_delivered(self):
        rc, wm = _main({"11280": (10, 8), "11580": (11, 8)})
        self.assertEqual(rc, 0)
        self.assertEqual(wm.call_args.args[0], "sms_crosscheck")
        self.assertEqual(list(wm.call_args.kwargs["succeeded"]), ["11280", "11580"])
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_skipped_office_is_a_failed_part_even_when_rc_is_0(self):
        rc, wm = _main({"11280": (10, 8), "11580": None})
        self.assertEqual(rc, 0)                       # exit code unchanged
        self.assertIn("11580: not compared", wm.call_args.kwargs["failed"][0])
        self.assertEqual(wm.call_args.kwargs["retry_args"][:2],
                         ["--office", "11580"])

    def test_mismatch_is_a_failed_part(self):
        rc, wm = _main({"11280": (30, 8), "11580": (10, 8)})
        self.assertEqual(rc, 1)
        self.assertIn("11280: booked 10 vs 30", wm.call_args.kwargs["failed"][0])
        self.assertEqual(list(wm.call_args.kwargs["succeeded"]), ["11580"])

    def test_failed_office_switch_is_never_compared(self):
        rc, wm = _main({"11280": (10, 8)}, switch=False, offices="11280")
        self.assertEqual(rc, 1)
        self.assertIn("could not switch", wm.call_args.kwargs["failed"][0])

    def test_manifest_error_never_raises(self):
        with mock.patch.object(run_manifest, "write_manifest",
                               side_effect=OSError("disk")), \
                mock.patch("builtins.print"):
            C.record_delivery([], ["x"], [])

    def test_report_id_matches_schedule_config(self):
        import json
        from pathlib import Path
        cfg = json.loads((Path(C.__file__).resolve().parents[1]
                          / "day_orchestrator" / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        self.assertIn(C.REPORT_ID, cfg.get("reports", cfg))


if __name__ == "__main__":
    unittest.main()
