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

import datetime as dt
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


class _R:
    """Just the fields _backstop_covering reads off a registry.Report."""

    def __init__(self, report_id, not_before, timeout_minutes):
        self.report_id = report_id
        self.not_before = not_before
        self.timeout_minutes = timeout_minutes


class BackstopCoversTheScheduleTest(unittest.TestCase):
    """A report cannot be scheduled after the day gives up on it.

    THE SAME SHAPE AS THE BUG ABOVE — a report that never fires and complains
    about it. `_apply_backstop` retires everything non-terminal at the backstop
    (noon by default), so a `not_before` at or after that time is retired
    MISSED_NOT_READY, "data never ready by noon", before its start time has even
    arrived. Every day, with the #claudecorrections alert and the red Hub card.

    FOUND 2026-08-26: tableau_screenshots_settle_pm, not_before 13:00, backstop
    12:00. It had not bitten yet only because Lucy 3's 4am batch started before
    the entry was pulled. run._backstop_covering now moves the backstop out on
    the machine that has the late report; these tests hold both halves — that the
    extension really covers the config, and that it is not silently swallowing a
    time nobody meant to set.
    """

    def _settings(self) -> dict:
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
        return d.get("settings") or {}

    def _scheduled_start_times(self):
        for rid, rep in _reports().items():
            if not isinstance(rep, dict) or not rep.get("on_scheduler"):
                continue
            cad = rep.get("cadence") or {}
            if cad.get("not_before") and cad.get("weekdays"):
                yield rid, cad["not_before"], int(rep.get("timeout_minutes", 45))

    def test_the_backstop_is_extended_to_cover_every_late_report(self):
        from automations.day_orchestrator import run as orun
        day = dt.date(2026, 8, 26)
        backstop = self._settings().get("backstop_time", "12:00")
        base = orun._parse_hhmm(backstop, day)

        for rid, nb, timeout in self._scheduled_start_times():
            with self.subTest(rid):
                covered = orun._backstop_covering(base, [_R(rid, nb, timeout)], day)
                runs_until = (orun._parse_hhmm(nb, day)
                              + dt.timedelta(minutes=timeout))
                self.assertGreaterEqual(
                    covered, runs_until,
                    f"{rid} starts at {nb} and may run {timeout}m, but the day "
                    f"gives up at {covered.time()}")

    def test_a_report_that_starts_late_does_not_stretch_the_day_absurdly(self):
        """The extension is a safety net, not a licence. A `not_before` of 22:00
        would keep every machine's orchestrator alive till 11pm and delay every
        stuck-report alert with it — that is a typo to catch here, not to absorb."""
        late = [(rid, nb) for rid, nb, _t in self._scheduled_start_times()
                if nb >= "16:00"]
        self.assertEqual(late, [], "an evening not_before belongs on its own "
                                   "LaunchAgent, not in the 4am batch")

    def test_the_grace_alone_still_leaves_room_for_an_ordinary_report(self):
        """Per-report timeouts do the heavy lifting above; the flat grace is the
        floor for anything that does not declare one."""
        from automations.day_orchestrator import run as orun
        self.assertGreaterEqual(orun.BACKSTOP_GRACE_MIN, 20)

    def test_nothing_changes_when_no_report_starts_late(self):
        from automations.day_orchestrator import run as orun
        day = dt.date(2026, 8, 26)
        base = orun._parse_hhmm("12:00", day)

        self.assertEqual(base, orun._backstop_covering(
            base, [_R("early", "04:31", 45)], day))
        self.assertEqual(base, orun._backstop_covering(base, [], day))


if __name__ == "__main__":
    unittest.main()
