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
    """The sweep fires every 2h. A deadline alone would call it healthy all
    afternoon on the strength of one 08:15 beat."""

    def test_one_skipped_pass_is_tolerated(self):
        """The wrapper skips a pass on purpose when blueink_docs is running."""
        late = sjw.overdue(_at(DAY, "12:30"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "08:16")}))   # 4h 14m quiet
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])

    def test_two_missed_passes_in_a_row_is_a_stall(self):
        late = sjw.overdue(_at(DAY, "14:30"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "08:16")}))   # 6h 14m quiet
        hit = [j for j in late if j["job_id"] == SWEEP]
        self.assertEqual(len(hit), 1)
        self.assertIn("allowed 300", hit[0]["why"])

    def test_the_overnight_gap_is_not_a_stall(self):
        """20:15 to 08:15 is twelve quiet hours BY DESIGN. Checked at 22:00 —
        past active_until — the gap rule must not fire."""
        late = sjw.overdue(_at(DAY, "22:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(DAY, "20:16")}))
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])

    def test_the_gap_rule_stays_quiet_before_the_first_pass(self):
        """At 08:00 the last beat is yesterday's 20:15 — 11h 45m quiet, way over
        the 5h gap, and entirely correct. Firing here would page every single
        morning."""
        late = sjw.overdue(_at(DAY, "08:00"),
                           _beats(**{BOX: _at(DAY, "06:59"),
                                     SWEEP: _at(YDAY, "20:16")}))
        self.assertNotIn(SWEEP, [j["job_id"] for j in late])


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
        self.assertEqual(bad | good, set(sjw.JOBS))

    def test_a_job_that_never_beat_is_never_called_healthy(self):
        """healthy() closes incident threads — it must not close one for a job
        we have simply never heard from."""
        now = _at(DAY, "07:00")          # before BOX's deadline, so not overdue
        self.assertNotIn(BOX, sjw.healthy(now, _beats(**{BOX: None, SWEEP: None})))


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
