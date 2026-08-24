"""Invariants the schedule config itself has to hold.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.day_orchestrator.test_schedule_config

WHY THIS EXISTS (Megan 2026-08-24, "this should have been caught way before
now"). Owner Chat Texts went live 2026-08-23 — trackers 7:30am, WOW board
7:45am, both `on_scheduler: true`. Neither has EVER fired on schedule. The four
runs in the Activity log are all hand-run `lucy rerun`s from the afternoon it
was wired.

The cause is one missing field. `registry.load` reads
`cad.get("weekdays", [0..6])` — the all-days default applies only when the key
is ABSENT, and `scheduled_today` selects with `wd in r.weekdays`, so an explicit
`"weekdays": []` means NEVER, on any day. Both entries had a `not_before` time
and an empty weekday list: the time gate was set, the days were not, so the gate
was never consulted.

Nothing caught it, and the reason matters more than the bug. The "didn't run
today" watcher derives what to expect FROM THE ACTIVITY LOG — so it only ever
flags reports it has seen run before. A report that never fires even once has no
history, so it is invisible to the very thing built to notice missing runs. It
took Megan spotting a gap on the Hub, a day later.

`"weekdays": []` is NOT wrong by itself — 67 other entries use it deliberately
as "a `lucy rerun` handle that never auto-fires" (install_*, previews,
on-demand re-runs). What makes it a bug is pairing it with a `not_before`: a
start time only means something for a report that runs on some day.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

CONFIG = (Path(__file__).resolve().parents[2]
          / "automations" / "day_orchestrator" / "schedule_config.json")


def _reports() -> dict:
    d = json.loads(CONFIG.read_text(encoding="utf-8"))
    return d.get("reports") or d


class ScheduleConfigInvariants(unittest.TestCase):

    def test_a_scheduled_report_with_a_start_time_has_run_days(self):
        """on_scheduler + not_before + no weekdays = a report that can never
        fire, and that nothing downstream will ever report as missing."""
        broken = []
        for rid, rep in _reports().items():
            if not isinstance(rep, dict) or rep.get("on_scheduler") is not True:
                continue
            cad = rep.get("cadence") or {}
            if cad.get("not_before") and not cad.get("weekdays"):
                broken.append(f"{rid} (not_before={cad['not_before']})")
        self.assertEqual(
            broken, [],
            "these are on the scheduler with a start time but NO run days, so "
            "they never fire and nothing flags them: " + ", ".join(broken))

    def test_the_two_owner_chat_reports_run_daily(self):
        """The regression itself — both were [] and silently never ran."""
        reps = _reports()
        for rid in ("owner_chat_texts_trackers", "owner_chat_texts_board"):
            cad = (reps[rid].get("cadence") or {})
            self.assertEqual(sorted(cad.get("weekdays") or []), [0, 1, 2, 3, 4, 5, 6],
                             f"{rid} must run every day")
            self.assertTrue(cad.get("not_before"), f"{rid} lost its start time")

    def test_empty_weekdays_alone_is_still_allowed(self):
        """The manual-handle idiom must keep working — this guard is narrow on
        purpose. 67 entries are legitimately 'never auto-fires'."""
        reps = _reports()
        manual = [rid for rid, rep in reps.items()
                  if isinstance(rep, dict)
                  and not (rep.get("cadence") or {}).get("weekdays")
                  and not (rep.get("cadence") or {}).get("not_before")]
        self.assertGreater(len(manual), 20,
                           "expected many on-demand handles with empty weekdays")

    def test_every_cadence_weekday_is_a_real_weekday(self):
        bad = []
        for rid, rep in _reports().items():
            if not isinstance(rep, dict):
                continue
            for wd in ((rep.get("cadence") or {}).get("weekdays") or []):
                if not isinstance(wd, int) or not 0 <= wd <= 6:
                    bad.append(f"{rid}:{wd!r}")
        self.assertEqual(bad, [], "weekdays must be ints 0(Mon)..6(Sun)")


if __name__ == "__main__":
    unittest.main()
