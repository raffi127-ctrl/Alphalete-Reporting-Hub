"""Least-loaded routing for hand-queued reruns (routing.py).

Pure — no Sheets, no network. Run:
    python -m unittest automations.day_orchestrator.test_routing
"""
import datetime as dt
import json
import unittest
from pathlib import Path

from automations.day_orchestrator import routing
from automations.shared import fleet

CONFIG = Path(__file__).with_name("schedule_config.json")
UTC = dt.timezone.utc
AFTERNOON = dt.datetime(2026, 10, 21, 14, 0, tzinfo=UTC)


def _parse(s):
    try:
        return dt.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _rows(n_busy, n_done=0, report="x", by="Megan"):
    when = (AFTERNOON - dt.timedelta(days=2)).isoformat()
    return ([[when, "rerun", report, by, "queued", "", ""]] * n_busy
            + [[when, "rerun", report, by, "done exit 0", "ok", when]] * n_done)


def _beats(**states):
    """_beats(lucy_3='idle') → heartbeat rows with a fresh note."""
    return {"mini_control_" + k: {"note": routing.batch_note(
        {"idle": False, "running": True}.get(v), AFTERNOON - dt.timedelta(minutes=3))}
        for k, v in states.items()}


ALL_IDLE = _beats(lucy_1="idle", lucy_2="idle", lucy_3="idle", lucy_4="idle")


#: Stand-in for deploy/*: one LaunchAgent wrapper that starts leaders_call.
DEPLOY = "PYTHONPATH=. .venv/bin/python -m automations.leaders_call.run --live\n"


def _pick(raw, rid, history, beats=ALL_IDLE, by="Megan", now=AFTERNOON):
    return routing.pick(raw, rid, by, history, beats, _parse, now=now,
                        deploy_text=DEPLOY)


class Heartbeat(unittest.TestCase):
    def test_round_trip(self):
        n = routing.batch_note(True, AFTERNOON)
        self.assertEqual(routing.batch_state(n, AFTERNOON), "running")
        self.assertEqual(routing.batch_state(routing.batch_note(False, AFTERNOON),
                                             AFTERNOON), "idle")

    def test_stale_or_junk_is_unknown(self):
        old = routing.batch_note(False, AFTERNOON - dt.timedelta(hours=1))
        self.assertIsNone(routing.batch_state(old, AFTERNOON))
        self.assertIsNone(routing.batch_state("", AFTERNOON))
        self.assertIsNone(routing.batch_state("whatever", AFTERNOON))
        self.assertIsNone(routing.batch_state(routing.batch_note(None, AFTERNOON),
                                              AFTERNOON))


class Choose(unittest.TestCase):
    def test_moves_off_a_backed_up_home(self):
        self.assertEqual(routing.choose(["Lucy 2", "Lucy 1", "Lucy 3"],
                                        {"Lucy 2": 17, "Lucy 1": 1, "Lucy 3": 0}),
                         "Lucy 3")

    def test_small_gap_or_tie_stays_home(self):
        self.assertEqual(routing.choose(["Lucy 2", "Lucy 3"],
                                        {"Lucy 2": 1, "Lucy 3": 0}), "Lucy 2")
        self.assertEqual(routing.choose(["Lucy 2", "Lucy 3"],
                                        {"Lucy 2": 4, "Lucy 3": 4}), "Lucy 2")

    def test_unknown_loads(self):
        self.assertEqual(routing.choose(["Lucy 2", "Lucy 3"], {"Lucy 3": 0}), "Lucy 2")
        self.assertEqual(routing.choose(["Lucy 2", "Lucy 3"], {"Lucy 2": 9}), "Lucy 2")


class Eligibility(unittest.TestCase):
    def _c(self, raw, rid="r", history=None):
        return routing.candidates(raw, rid, history or {}, _parse, AFTERNOON,
                                  deploy_text=DEPLOY)

    def test_a_launch_agent_makes_it_scheduled(self):
        """leaders_call is off the 4am batch but has its own Monday timer."""
        raw = {"source_type": "tableau", "command": ["automations.leaders_call.run"]}
        self.assertEqual(self._c(raw, rid="leaders_call"), ["Lucy 1"])
        self.assertTrue(routing.has_launch_agent(
            {"command": ["automations.x.run"]}, "x", "lucy rerun x --live"))
        self.assertFalse(routing.has_launch_agent(
            {"command": ["automations.x.run"]}, "x", "automations.x.run_other"))
        self.assertTrue(routing.has_launch_agent({}, "x", ""))   # can't tell → stays

    # --- scope: scheduled work never moves -----------------------------------
    def test_scheduled_reports_never_move(self):
        """Megan: "nothing that we have scheduled to run is what i'm talking
        about" — even a hand rerun of a 4am report stays on its box."""
        hist = {m: _rows(0, 3, "r") for m in fleet.RUNNERS}
        self.assertEqual(self._c({"machine": "Lucy 3", "source_type": "tableau",
                                  "on_scheduler": True}, history=hist), ["Lucy 3"])

    def test_reports_with_their_own_timer_never_move(self):
        for key in routing.TIMER_KEYS:
            with self.subTest(key=key):
                self.assertEqual(self._c({"machine": "Lucy 3", "source_type": "tableau",
                                          key: [0]}), ["Lucy 3"])

    def test_install_jobs_and_stay_home_never_move(self):
        raw = {"machine": "Lucy 3", "source_type": "local"}
        self.assertEqual(self._c(raw, rid="install_wifi_selfheal_agent"), ["Lucy 3"])
        self.assertEqual(self._c(dict(raw, stay_home=True)), ["Lucy 3"])

    # --- logins -----------------------------------------------------------------
    def test_carlos_report_never_leaves_lucy_2(self):
        """chidalgo is on Lucy 2 only — Raf's login reads the wrong offices,
        even if it once 'finished' there."""
        hist = {"Lucy 1": _rows(0, 3, "r")}
        self.assertEqual(self._c({"machine": "Lucy 2", "source_type": "tableau"},
                                 history=hist), ["Lucy 2"])

    def test_appstream_only_ignores_ownerville_but_needs_appstream(self):
        got = self._c({"machine": "Lucy 2", "source_type": "appstream"})
        self.assertIn("Lucy 3", got)            # same Google, has AppStream
        self.assertNotIn("Lucy 4", got)         # no AppStream on Lucy 4

    def test_texting_home_never_goes_to_a_box_that_cannot_text(self):
        raw = {"machine": "Lucy 3", "source_type": "appstream", "can_run_on": ["Lucy 2"]}
        self.assertNotIn("Lucy 2", self._c(raw))

    # --- pinned vs not ------------------------------------------------------------
    def test_unpinned_build_job_can_go_to_any_box_with_the_logins(self):
        """No machine key = it only defaulted to Lucy 1 because nobody chose."""
        self.assertEqual(self._c({"source_type": "tableau"}),
                         ["Lucy 1", "Lucy 3", "Lucy 4"])

    def test_pinned_needs_same_google_or_proof(self):
        raw = {"machine": "Lucy 1", "source_type": "tableau"}
        self.assertEqual(self._c(raw), ["Lucy 1"])          # raffi127 is unique
        self.assertEqual(self._c(raw, history={"Lucy 4": _rows(0, 1, "r")}),
                         ["Lucy 1", "Lucy 4"])
        self.assertEqual(self._c({"machine": "Lucy 3", "source_type": "tableau"}),
                         ["Lucy 3", "Lucy 4"])               # same Google

    def test_proof_must_be_a_clean_recent_hand_run_of_this_report(self):
        raw = {"machine": "Lucy 1", "source_type": "tableau"}
        old = (AFTERNOON - dt.timedelta(days=routing.PROVEN_DAYS + 1)).isoformat()
        for rows in ([[AFTERNOON.isoformat(), "rerun", "r", "Megan", "failed", "", ""]],
                     _rows(0, 2, "other_report"),
                     _rows(0, 2, "r", by="auto:watch"),
                     [[old, "rerun", "r", "Megan", "done", "", old]]):
            self.assertEqual(self._c(raw, history={"Lucy 4": rows}), ["Lucy 1"])


class Pick(unittest.TestCase):
    SMS = {"machine": "Lucy 2", "source_type": "appstream",
           "can_run_on": ["Lucy 1", "Lucy 3"]}

    def _hist(self, **busy):
        return {m: _rows(busy.get(m.replace(" ", "_").lower(), 0))
                for m in fleet.RUNNERS}

    def test_tonights_backlog_goes_to_lucy_3(self):
        self.assertEqual(_pick(self.SMS, "sms_log", self._hist(lucy_2=17, lucy_1=1)),
                         "Lucy 3")

    def test_never_onto_a_box_mid_batch(self):
        beats = _beats(lucy_1="idle", lucy_2="idle", lucy_3="running")
        self.assertEqual(_pick(self.SMS, "sms_log", self._hist(lucy_2=17, lucy_1=4),
                               beats=beats), "Lucy 1")

    def test_no_or_stale_heartbeat_is_not_a_target(self):
        self.assertIsNone(_pick(self.SMS, "sms_log", self._hist(lucy_2=17), beats={}))
        stale = {"mini_control_lucy_3": {"note": routing.batch_note(
            False, AFTERNOON - dt.timedelta(hours=2))}}
        self.assertIsNone(_pick(self.SMS, "sms_log", self._hist(lucy_2=17), beats=stale))

    def test_home_mid_batch_counts_as_busier(self):
        beats = _beats(lucy_2="running", lucy_3="idle")
        self.assertEqual(_pick(self.SMS, "sms_log", self._hist(lucy_2=1, lucy_3=0),
                               beats=beats), "Lucy 3")

    def test_quiet_hours(self):
        for hour in range(routing.QUIET_HOURS[0], routing.QUIET_HOURS[1]):
            when = AFTERNOON.replace(hour=hour, minute=30)
            beats = {"mini_control_lucy_3": {"note": routing.batch_note(False, when)}}
            self.assertIsNone(_pick(self.SMS, "sms_log", self._hist(lucy_2=17),
                                    beats=beats, now=when))

    def test_watchdog_jobs_stay_put(self):
        self.assertIsNone(_pick(self.SMS, "sms_log", self._hist(lucy_2=17),
                                by="auto:appstream_watch"))

    def test_no_room_to_move_returns_none(self):
        self.assertIsNone(_pick({"machine": "Lucy 2", "source_type": "tableau"},
                                "carlos_focus", self._hist(lucy_2=17)))

    def test_a_scheduled_report_stays_even_when_home_is_swamped(self):
        raw = dict(self.SMS, on_scheduler=True)
        self.assertIsNone(_pick(raw, "sms_log", self._hist(lucy_2=40)))

    def test_unpinned_probe_leaves_a_busy_lucy_1(self):
        self.assertEqual(_pick({"source_type": "tableau"}, "raf_special_probe",
                               self._hist(lucy_1=9, lucy_3=3, lucy_4=1)), "Lucy 4")


class ConfigGuard(unittest.TestCase):
    """Every hand-written `can_run_on` must name boxes that can do the job.
    (candidates() re-checks identity at run time; this catches it at commit.)"""

    def setUp(self):
        self.reports = json.loads(CONFIG.read_text(encoding="utf-8"))["reports"]

    def test_lists_pass_the_identity_rules(self):
        for rid, r in self.reports.items():
            home = fleet.get(r.get("machine") or fleet.RUNNERS[0])
            for m in r.get("can_run_on") or []:
                box = fleet.get(m)
                self.assertIsNotNone(box, "{}: '{}' is not a Lucy".format(rid, m))
                self.assertTrue(routing.identity_ok(r, home, box),
                                "{}: {} lacks a login it needs".format(rid, m))

    def test_every_machine_has_a_google_account(self):
        for m in fleet.MACHINES:
            self.assertIn("@", m.google_account, m.name)


if __name__ == "__main__":
    unittest.main()
