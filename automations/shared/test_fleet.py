"""The roster is ONE list, and every consumer must agree with it.

Run:  PYTHONPATH=. .venv/bin/python -m unittest automations.shared.test_fleet

WHAT THIS GUARDS. Before 2026-09-17 the fleet roster was eleven hand-maintained
literals scattered across nine files. Every one fails SILENTLY when a machine is
missing from it, and four had gone stale without anyone noticing:

  * `hub_schedule_status._LUCY` stopped at Lucy 2 — every Lucy 3 card reported
    "no schedule" in the change-notification email for four weeks;
  * `office_onboarding.schema.MACHINES` stopped at Lucy 2;
  * `card_scheduler._LUCY` was stale AND unused;
  * `gap_alerts.config.MACHINE_OWNER` had no Lucy 3, so the "who is logged in
    here" line fell back to "this machine's owner" on the box most likely to be
    mid-rerun.

Nothing errored in any of those cases. That is the whole problem: a missing name
is invisible, so only a test can see it. These asserts are what let Lucy 5 be
added by editing ONE file.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from automations.shared import fleet


class ConsumersAgreeWithTheRoster(unittest.TestCase):
    """Each of these used to be its own hand-kept literal."""

    def test_session_holder_appstream_rosters(self):
        from automations.shared import session_holder as sh
        self.assertEqual(sh.APPSTREAM_HOLD_MACHINES,
                         fleet.APPSTREAM_HOLD_MACHINES)
        self.assertEqual(sh.APPSTREAM_FLEET_MACHINES,
                         fleet.APPSTREAM_FLEET_MACHINES)

    def test_login_check_ownerville_map(self):
        from automations.shared import login_check as lc
        self.assertEqual(lc.EXPECTED_OWNERVILLE_ACCOUNT,
                         fleet.EXPECTED_OWNERVILLE_ACCOUNT)

    def test_mini_control_known_runners(self):
        from automations.day_orchestrator import mini_control as mc
        self.assertEqual(mc._KNOWN_RUNNERS, fleet.RUNNERS)

    def test_hub_schedule_status_knows_every_runner(self):
        from automations.shared import hub_schedule_status as hs
        self.assertEqual(hs._LUCY, set(fleet.RUNNERS))

    def test_office_onboarding_machine_picker(self):
        from automations.office_onboarding import schema
        self.assertEqual(schema.MACHINES, fleet.OFFICE_ONBOARDING_MACHINES)

    def test_gap_alerts_texting_and_owner(self):
        from automations.gap_alerts import config as C
        self.assertEqual(set(C.TEXTING_MACHINES), set(fleet.TEXTING_MACHINES))
        self.assertEqual(C.MACHINE_OWNER, fleet.MACHINE_OWNER)


class TheHeartbeatFollowsTheClock(unittest.TestCase):

    def test_only_morning_clock_machines_get_a_heartbeat(self):
        """A watchdog armed on a box that was never given a 4am batch pages
        every morning about nothing — which is how a watchdog gets muted, and
        then ignored on the morning it is finally right."""
        from automations.shared import silent_job_watch as sjw
        watched = {v["machine"] for k, v in sjw.JOBS.items()
                   if k.startswith("orchestrator_heartbeat_")}
        self.assertEqual(watched, set(fleet.MORNING_CLOCK_MACHINES))

    def test_each_heartbeat_uses_its_own_arm_date(self):
        """A machine added later must get its own grace window, not the date the
        first three were armed on."""
        from automations.shared import silent_job_watch as sjw
        for key, job in sjw.JOBS.items():
            if not key.startswith("orchestrator_heartbeat_"):
                continue
            with self.subTest(job=key):
                self.assertEqual(
                    job["watch_from"],
                    fleet.heartbeat_watch_from(job["machine"]))

    def test_a_machine_off_the_clock_has_no_heartbeat(self):
        from automations.shared import silent_job_watch as sjw
        off = [m.name for m in fleet.MACHINES if not m.morning_clock_since]
        watched = {v["machine"] for k, v in sjw.JOBS.items()
                   if k.startswith("orchestrator_heartbeat_")}
        for name in off:
            with self.subTest(machine=name):
                self.assertNotIn(name, watched)


class TheHubShowsEveryMachine(unittest.TestCase):
    """dashboard.MEMBERS is DISPLAY data (colour, badge), so it stays in
    dashboard.py — but it must not silently omit a machine, which is exactly
    what the old hand-listed Pack top row did."""

    def _members(self):
        import ast
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "dashboard.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", "") == "MEMBERS"):
                return ast.literal_eval(node.value)
        self.fail("MEMBERS not found in dashboard.py")

    def test_every_runner_has_a_profile_card(self):
        names = {m["name"] for m in self._members()}
        for r in fleet.RUNNERS:
            with self.subTest(machine=r):
                self.assertIn(
                    r, names,
                    f"{r} is in the fleet roster but has no dashboard.MEMBERS "
                    f"entry — it would have no profile card on the Hub")

    def test_the_lucy_cards_are_visually_distinguishable(self):
        lucys = [m for m in self._members() if m["name"] in set(fleet.RUNNERS)]
        colors = [m.get("color") for m in lucys]
        badges = [m.get("badge") for m in lucys]
        self.assertEqual(len(set(colors)), len(lucys), "two Lucys share a ring colour")
        self.assertEqual(len(set(badges)), len(lucys), "two Lucys share a badge")

    def test_badges_match_the_roster(self):
        by_name = {m["name"]: m for m in self._members()}
        for m in fleet.MACHINES:
            with self.subTest(machine=m.name):
                self.assertEqual(by_name[m.name].get("badge"), m.badge)


class NobodyRewritesTheRosterByHand(unittest.TestCase):
    """The actual guard. Everything above checks the consumers we KNOW about;
    this catches the next one somebody adds."""

    #: Lines that legitimately name two machines without being a roster. Each is
    #: a campaign-family DEFAULT ("which box does a B2B office render on"), not a
    #: statement about which machines exist — adding Lucy 5 does not change them.
    ALLOWED = {
        'FAMILY_MACHINE = {"D2D": "Lucy 1", "B2B": "Lucy 2"}',
        'FAMILY_DEFAULT_MACHINE = {"d2d": "Lucy 1", "b2b": "Lucy 2"}',
        'return "Lucy 2" if "Lucy 2" in machines else "Lucy 1"',
    }

    def test_no_new_hand_maintained_machine_list(self):
        pat = re.compile(r'"Lucy \d"')
        root = pathlib.Path(__file__).resolve().parents[1]
        offenders = []
        for f in sorted(root.rglob("*.py")):
            if f.name == "fleet.py" or f.name.startswith("test_"):
                continue
            for i, line in enumerate(
                    f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]          # comments are free to explain
                if len(set(pat.findall(code))) < 2:
                    continue
                if code.strip() in self.ALLOWED:
                    continue
                offenders.append(
                    "%s:%d  %s" % (f.relative_to(root.parent), i, code.strip()))
        self.assertEqual(
            offenders, [],
            "a machine list is being maintained by hand again. Import it from "
            "automations/shared/fleet.py instead — a literal like this is "
            "invisible when it goes stale, which cost four weeks of wrong Hub "
            "schedules. If the line really is a campaign default rather than a "
            "roster, add it to ALLOWED with a reason.\n  " + "\n  ".join(offenders))


class TheRosterItselfIsSane(unittest.TestCase):

    def test_names_and_badges_are_unique(self):
        names = [m.name for m in fleet.MACHINES]
        self.assertEqual(len(set(names)), len(names))
        badges = [m.badge for m in fleet.MACHINES]
        self.assertEqual(len(set(badges)), len(badges))

    def test_every_machine_declares_an_ownerville_account(self):
        """OwnerVille decides whether numbers are RIGHT, not merely whether a
        report runs. A machine with no declared account is one `login_check`
        cannot assert, which is the 2026-09-01 failure with the check removed."""
        for m in fleet.MACHINES:
            with self.subTest(machine=m.name):
                self.assertTrue(m.ownerville_account)

    def test_a_holder_also_runs_appstream(self):
        """Holding a console you never read is pure token churn against the
        machines that do read one."""
        for m in fleet.MACHINES:
            if m.holds_appstream:
                with self.subTest(machine=m.name):
                    self.assertTrue(m.runs_appstream)

    def test_arm_dates_are_iso(self):
        for m in fleet.MACHINES:
            if m.morning_clock_since:
                with self.subTest(machine=m.name):
                    self.assertRegex(m.morning_clock_since, r"^\d{4}-\d{2}-\d{2}$")

    def test_lucy_4_is_provisioned_but_not_yet_live(self):
        """Pins the 2026-09-17 decision: every capability OFF until go-live.

        DELETE THIS TEST as Lucy 4's flags are flipped — it describes a state
        that is meant to end, and a test nobody is allowed to change is how a
        machine stays half-built."""
        m = fleet.get("Lucy 4")
        self.assertIsNotNone(m)
        self.assertIn("Lucy 4", fleet.RUNNERS)
        self.assertFalse(m.holds_appstream)
        self.assertFalse(m.runs_appstream)
        self.assertFalse(m.can_text)
        self.assertIsNone(m.morning_clock_since)


if __name__ == "__main__":
    unittest.main()
