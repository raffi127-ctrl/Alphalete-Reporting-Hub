"""A job that publishes nothing must still be missed when it stops.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.shared.test_silent_job_watch

org_board_box_repull and blueink_completed_sweep exit 0 unconditionally and
write no manifest and no Activity row — for good reasons the module documents.
The cost was that nothing anywhere could tell they had stopped firing: the Hub
showed them via phantom cards that always read "no run logged", and Slack's
didn't-run watcher was structurally blind because it builds its baseline from
Activity rows and neither has ever written one.

These tests drive `overdue()` with an injected clock and an injected heartbeat
table — no Sheets, no Slack, nothing sent. `beat()` and `read_beats()` are the
only functions that touch the network and neither is exercised here.
"""
from __future__ import annotations

import datetime as dt
import re
import unittest

from automations.shared import silent_job_watch as sjw

BOX = "org_board_box_repull"
SWEEP = "blueink_completed_sweep"


def _at(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}:00")


def _beats(**seen) -> dict:
    """{job_id: {...}} from job_id=datetime|None kwargs."""
    return {k: {"last_seen": v, "machine": "m", "status": "ok"}
            for k, v in seen.items()}


# A Thursday, comfortably after every job's watch_from.
DAY = "2026-09-03"
YDAY = "2026-09-02"


class TheDeadlineCatchesAMorningStall(unittest.TestCase):

    def test_box_is_fine_once_it_has_beaten_today(self):
        late = sjw.overdue(_at(DAY, "07:20"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "08:16")}))
        self.assertNotIn(BOX, [j["job_id"] for j in late])

    def test_box_is_overdue_when_today_produced_nothing(self):
        late = sjw.overdue(_at(DAY, "07:20"),
                           _beats(**{BOX: _at(YDAY, "06:59"),
                                     SWEEP: _at(DAY, "08:16")}))
        hit = [j for j in late if j["job_id"] == BOX]
        self.assertEqual(len(hit), 1)
        self.assertIn("07:15", hit[0]["why"])

    def test_box_is_not_called_late_before_its_deadline(self):
        """06:52 and 06:58 with a real grace — at 07:00 nothing is wrong yet."""
        late = sjw.overdue(_at(DAY, "07:00"),
                           _beats(**{BOX: _at(YDAY, "06:59"),
                                     SWEEP: _at(YDAY, "20:16")}))
        self.assertNotIn(BOX, [j["job_id"] for j in late])

    def test_a_job_that_has_never_beaten_is_overdue_not_invisible(self):
        """The whole blind spot in one line: never-run must not read as fine."""
        late = sjw.overdue(_at(DAY, "07:20"), _beats(**{BOX: None, SWEEP: None}))
        self.assertIn(BOX, [j["job_id"] for j in late])


class TheGapCatchesAMidDayStall(unittest.TestCase):
    """The sweep fires 15 min ahead of every OBCL <- OwnerVille pass: 07:45
    Tue-Fri, then hourly 13:45-18:45 (2026-09-22). A deadline alone would
    call it healthy all afternoon on the strength of one beat; the gap rule
    is what notices it stopped. The watch keys on the 13:45 start, so the
    morning pass and the by-design morning-to-afternoon quiet are never read
    as a stall."""

    def test_one_skipped_pass_is_tolerated(self):
        """The wrapper skips a pass on purpose when blueink_docs is running."""
        late = sjw.overdue(_at(DAY, "16:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "13:46")}))   # 2h 14m quiet
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])

    def test_two_missed_passes_in_a_row_is_a_stall(self):
        late = sjw.overdue(_at(DAY, "17:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "13:46")}))   # 3h 14m quiet
        hit = [j for j in late if j["job_id"] == SWEEP]
        self.assertEqual(len(hit), 1)
        self.assertIn("allowed 150", hit[0]["why"])

    def test_the_overnight_gap_is_not_a_stall(self):
        """18:45 to the next morning is many quiet hours BY DESIGN. Checked at
        21:30 -- past active_until -- the gap rule must not fire."""
        late = sjw.overdue(_at(DAY, "21:30"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "18:46")}))
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])

    def test_the_gap_rule_stays_quiet_before_the_first_pass(self):
        """At 08:00 the last beat is yesterday's 18:45 -- 13h quiet, way over
        the gap, and entirely correct. Firing here would page every single
        morning."""
        late = sjw.overdue(_at(DAY, "08:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(YDAY, "18:46")}))
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])

    def test_the_morning_to_afternoon_gap_is_by_design(self):
        """The 07:45 pass ran; nothing is due again until 13:45. At 13:00
        that is 5h quiet and nothing is wrong."""
        late = sjw.overdue(_at(DAY, "13:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "07:46")}))
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])

    def test_a_missing_afternoon_start_is_caught(self):
        """07:45 ran, 13:45 never came. By 15:00 the sweep is overdue."""
        late = sjw.overdue(_at(DAY, "15:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "07:46")}))
        self.assertIn(SWEEP, [j["job_id"] for j in late])


class DeploymentAndRecovery(unittest.TestCase):

    def test_nothing_is_watched_before_its_watch_from(self):
        """Shipping the heartbeat must not alert about the passes that ran
        before it existed."""
        early = dt.date.fromisoformat(sjw.JOBS[BOX]["watch_from"]) - dt.timedelta(days=1)
        late = sjw.overdue(dt.datetime.combine(early, dt.time(23, 0)),
                           _beats(**{BOX: None, SWEEP: None}))
        self.assertEqual(late, [])

    def test_healthy_lists_exactly_what_is_not_overdue(self):
        beats = _beats(**{BOX: _at(DAY, "06:59"), SWEEP: _at(YDAY, "20:16")})
        now = _at(DAY, "09:30")
        bad = {j["job_id"] for j in sjw.overdue(now, beats)}
        good = set(sjw.healthy(now, beats))
        self.assertEqual(bad & good, set())
        # Every job that is ARMED at `now` must land in exactly one of the two
        # sets. Scoped to armed jobs on purpose: a job still inside its
        # deployment grace is deliberately neither — overdue() skips it and
        # healthy() will not vouch for a job it has never heard from. Comparing
        # against all of JOBS made adding any new job with a future watch_from
        # fail this test for the one reason that is not a bug.
        armed = {j for j, spec in sjw.JOBS.items()
                 if dt.date.fromisoformat(spec["watch_from"]) <= now.date()}
        self.assertEqual(bad | good, armed)

    def test_a_job_that_never_beat_is_never_called_healthy(self):
        """healthy() closes incident threads — it must not close one for a job
        we have simply never heard from."""
        now = _at(DAY, "07:00")          # before BOX's deadline, so not overdue
        self.assertNotIn(BOX, sjw.healthy(now, _beats(**{BOX: None, SWEEP: None})))


class AJobThatIsHeldOnPurpose(unittest.TestCase):
    """The applicant push is HELD Fri 1pm -> Sun 1pm (Carlos 2026-09-04) and exits
    75 on every tick in between. From the outside that is indistinguishable from a
    dead agent — on 2026-09-13 the walk-diag tab showed nothing since Friday 12:52
    and read exactly like an outage. An alert that cannot tell those apart fires
    every weekend and trains you to ignore the one that matters."""

    JID = "applicant_push_lucy_2"
    MON = dt.date(2026, 9, 14)          # a Monday

    def _at(self, wd, h, m=0):
        return dt.datetime.combine(self.MON + dt.timedelta(days=wd), dt.time(h, m))

    def _late(self, now, seen):
        beats = {self.JID: {"last_seen": seen}} if seen else {}
        return self.JID in {j["job_id"] for j in sjw.overdue(now, beats)}

    def test_a_normal_weekday_gap_still_alerts(self):
        self.assertTrue(self._late(self._at(2, 16), self._at(2, 14, 30)))

    def test_friday_afternoon_is_held_not_broken(self):
        # Last pass 12:52, the window shuts at 13:00. Silence after that is the
        # job obeying its own gate.
        self.assertFalse(self._late(self._at(4, 14), self._at(4, 12, 52)))

    def test_saturday_is_silent_all_day_and_that_is_correct(self):
        self.assertFalse(self._late(self._at(5, 10), self._at(4, 12, 52)))
        self.assertFalse(self._late(self._at(6, 12), self._at(4, 12, 52)))

    def test_the_grace_covers_the_moment_the_window_lifts(self):
        # 13:00 Sunday: the window is open but the push has not taken a pass yet,
        # and first_by (07:30) is hours gone. Without the grace this fires one
        # false alert at 1pm every single Sunday.
        self.assertFalse(self._late(self._at(6, 13, 30), self._at(4, 12, 52)))

    def test_but_a_push_that_never_comes_back_does_alert(self):
        # Grace over, still nothing since Friday — now it is a real outage.
        self.assertTrue(self._late(self._at(6, 14, 30), self._at(4, 12, 52)))

    def test_a_push_that_resumed_after_the_hold_is_quiet(self):
        self.assertFalse(self._late(self._at(6, 14, 30), self._at(6, 14, 10)))


class TheRegistryStaysHonest(unittest.TestCase):

    def test_every_job_declares_what_silence_means(self):
        for jid, spec in sjw.JOBS.items():
            with self.subTest(job=jid):
                for field in ("name", "machine", "first_by", "watch_from",
                              "means", "fix"):
                    self.assertTrue(spec.get(field), f"{jid} is missing {field}")

    def test_the_wrappers_actually_beat(self):
        """A registry entry with no wrapper calling it is a job we THINK is
        watched and isn't — worse than not listing it.

        Two ways a wrapper can stamp a job. `--beat <jid>` names it outright.
        `--beat-machine <base>` is for one wrapper deployed to several runners:
        it appends the machine slug at run time, so the id it stamps on the box
        declared in this job's `machine` field must come back as exactly `jid`.
        Deriving it from the registry's OWN machine field is what keeps the
        second form honest — a key whose slug doesn't match the machine it
        claims to run on still fails here."""
        from pathlib import Path
        deploy = Path(sjw.__file__).resolve().parents[2] / "deploy"
        blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in deploy.glob("*.sh"))
        for jid, spec in sjw.JOBS.items():
            with self.subTest(job=jid):
                if "--beat %s" % jid in blob:
                    continue
                bases = re.findall(r"--beat-machine\s+([A-Za-z0-9_]+)", blob)
                derived = {sjw.job_id_for_machine(b, spec["machine"])
                           for b in bases}
                self.assertIn(
                    jid, derived,
                    f"no deploy wrapper stamps a heartbeat for {jid} — no "
                    f"`--beat {jid}`, and no --beat-machine base in deploy/*.sh "
                    f"({sorted(bases) or 'none found'}) resolves to it on "
                    f"{spec['machine']!r}")


if __name__ == "__main__":
    unittest.main()
