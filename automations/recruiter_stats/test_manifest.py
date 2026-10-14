"""Recruiter Stats: the ticket closes only when every office and week this
run was meant to refresh actually got refreshed.

    python -m unittest automations.recruiter_stats.test_manifest

AppStream, the dashboard and write_manifest are all mocked: a real clean
manifest closes the report's incident thread in Slack, and a test must never
speak in the channel.
"""
import contextlib
import datetime as dt
import unittest
from unittest import mock

from automations.recruiter_stats import run as R
from automations.shared import run_manifest

OLD = dt.date(2026, 9, 20)       # a finished week
NOW = dt.date.today() - dt.timedelta(days=(dt.date.today().weekday() + 1) % 7)
ADMINS = {"Booked": {"cells": [], "admins": {"Ana": ["1"] * 8}}}


class _Page:
    def wait_for_timeout(self, _ms):
        pass

    def wait_for_selector(self, *_a, **_k):
        pass


@contextlib.contextmanager
def _session(**_kw):
    yield _Page()


def _pull(weeks, reach=True, week_ok=True, parsed=ADMINS):
    misses = []
    with mock.patch("automations.shared.tableau_patchright."
                    "appstream_direct_session", _session), \
            mock.patch.object(R.fo, "_switch_office",
                              **({"side_effect": reach}
                                 if isinstance(reach, Exception)
                                 else {"return_value": reach})), \
            mock.patch.object(R, "_load_week", return_value=week_ok), \
            mock.patch.object(R, "_parse", return_value=parsed), \
            mock.patch.object(R.Path, "write_text"), \
            mock.patch("builtins.print"):
        raw = R.pull(weeks, [("11580", "Carlos Hidalgo")], misses=misses,
                     base={"11580": {OLD.isoformat(): {"cached": 1}}})
    return raw, misses


class PullMisses(unittest.TestCase):
    def test_clean_pull_has_no_misses(self):
        _raw, misses = _pull([OLD])
        self.assertEqual(misses, [])

    def test_unreachable_office_is_a_miss(self):
        raw, misses = _pull([OLD], reach=False)
        self.assertIn("could not be reached", misses[0][1])
        self.assertEqual(raw["11580"][OLD.isoformat()], {"cached": 1})

    def test_week_that_would_not_switch_keeps_cache_and_is_a_miss(self):
        raw, misses = _pull([OLD], week_ok=False)
        self.assertIn("could not be set", misses[0][1])
        self.assertEqual(raw["11580"][OLD.isoformat()], {"cached": 1})

    def test_finished_week_with_no_admins_is_a_miss(self):
        _raw, misses = _pull([OLD], parsed={})
        self.assertIn("0 admin rows", misses[0][1])

    def test_week_in_progress_with_no_admins_is_fine(self):
        _raw, misses = _pull([NOW], parsed={})
        self.assertEqual(misses, [])

    def test_page_that_never_loads_skips_office_not_the_run(self):
        # 10/14: '#weekStart' timed out and the raise killed every office.
        offices = [("11580", "Carlos Hidalgo"), ("23467", "Atef Choudhury")]
        calls = []

        def load(_page, sun):
            calls.append(sun)
            if len(calls) == 1:
                raise TimeoutError("waiting for locator('#weekStart')")
            return True
        misses = []
        with mock.patch("automations.shared.tableau_patchright."
                        "appstream_direct_session", _session), \
                mock.patch.object(R.fo, "_switch_office", return_value=True), \
                mock.patch.object(R, "_load_week", side_effect=load), \
                mock.patch.object(R, "_parse", return_value=ADMINS), \
                mock.patch.object(R.Path, "write_text"), \
                mock.patch("builtins.print"):
            raw = R.pull([OLD, NOW], offices, misses=misses,
                         base={"11580": {OLD.isoformat(): {"cached": 1}}})
        self.assertEqual([m[0] for m in misses], ["Carlos Hidalgo"] * 2)
        self.assertEqual(raw["11580"][OLD.isoformat()], {"cached": 1})
        self.assertEqual(raw["23467"][NOW.isoformat()], ADMINS)

    def test_switch_that_times_out_is_a_miss_not_a_crash(self):
        raw, misses = _pull([OLD], reach=TimeoutError("Locator.click"))
        self.assertIn("could not be reached", misses[0][1])
        self.assertEqual(raw["11580"][OLD.isoformat()], {"cached": 1})


def _main(misses, extra=()):
    def pull(weeks, offices, base=None, misses=None):
        misses.extend(MISSES)
        return {}
    MISSES = misses
    with mock.patch.object(R, "pull", side_effect=pull), \
            mock.patch.object(R, "build"), \
            mock.patch.object(R.RAW_PATH.__class__, "exists", return_value=False), \
            mock.patch.object(run_manifest, "write_manifest") as wm, \
            mock.patch("builtins.print"):
        R.main(list(extra))
    return wm


class Manifest(unittest.TestCase):
    def test_full_refresh_is_delivered(self):
        wm = _main([])
        self.assertEqual(wm.call_args.args[0], "recruiter_stats")
        self.assertEqual(len(wm.call_args.kwargs["succeeded"]), 3)
        self.assertEqual(list(wm.call_args.kwargs["failed"]), [])

    def test_a_miss_names_the_office(self):
        wm = _main([("Atef Choudhury", "office could not be reached")])
        self.assertIn("Atef Choudhury", wm.call_args.kwargs["failed"][0])
        self.assertNotIn("Atef Choudhury", wm.call_args.kwargs["succeeded"])

    def test_dry_run_writes_no_manifest(self):
        wm = _main([], extra=["--dry-run"])
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
