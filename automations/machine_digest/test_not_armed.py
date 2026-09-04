"""A report still being BUILT must not page the channel.

Run:  PYTHONPATH=. .venv/bin/python -m unittest \
          automations.machine_digest.test_not_armed

WHAT THIS GUARDS (2026-09-04). Three half-built reports made noise in
#claudecorrections-and-requests in one morning, and every one of those tickets
sent whoever picked it up somewhere useless:

  * `rc_contact_sync` (B2B Customer Contacts) — built 2026-09-02, still waiting
    on two credentials. It failed 17:33-17:37 on 9/3 and opened
    `failure-rc_contact_sync`, whose thread said to go read "its own log on
    Lucy 2 (standalone launchd agent)" for a report nobody has armed.
  * `apex_new_starts` — sat red and unclaimed for a day (covered separately by
    the hand-run fix, c1cb0b1).

TWO PRODUCERS alert for one failure and both had to be shut: hub_publish's
`_alert_failure` (":x: … closed a run with status FAILED on <host>") and the
machine_digest watcher ("didn't run clean on …"). Closing one door only would
have halved the noise and left the ticket.

THE TWO DESIGN CHOICES THIS PINS:

  1. `skip`, not `offday`. offday suppresses only the "didn't run" GUESS and
     still reports a real FAILED — right for a live report on its day off,
     wrong here, where the FAILED *is* the expected state of a thing under
     construction. Same shape as _retired_ids, opposite direction in time.
  2. An explicit flag, never inferred from on_scheduler. Plenty of FINISHED
     reports are off-scheduler and run by hand or on their own agent; inferring
     would mute all of them.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from automations.machine_digest import run as md
from automations.day_orchestrator import hub_publish


class _both:
    """Enter/exit several context managers as one."""

    def __init__(self, *ctxs):
        self._ctxs = ctxs

    def __enter__(self):
        for c in self._ctxs:
            c.__enter__()
        return self

    def __exit__(self, *exc):
        for c in reversed(self._ctxs):
            c.__exit__(*exc)
        return False

CONFIG = Path(md.__file__).resolve().parents[1] / "day_orchestrator" / "schedule_config.json"


class _Cfg:
    def __init__(self, reports):
        self.raw = {"reports": reports}


class TheFlagIsReadFromTheRegistry(unittest.TestCase):

    def test_a_declared_report_is_skipped(self):
        ids = md._not_armed_ids(_Cfg({"rc_contact_sync": {"not_armed": True}}))
        self.assertIn("rc_contact_sync", ids)

    def test_the_hyphenated_card_id_is_matched_too(self):
        """The Activity log writes the CARD id. Matching only the registry key
        is how a skip set silently does nothing — the sci_campaigns bug."""
        ids = md._not_armed_ids(_Cfg({"rc_contact_sync": {"not_armed": True}}))
        self.assertIn("rc-contact-sync", ids)

    def test_off_scheduler_alone_does_NOT_mute_a_report(self):
        """Finished reports are off-scheduler all the time; they must keep
        alerting. Only the explicit flag counts."""
        ids = md._not_armed_ids(_Cfg({"some_finished_report":
                                      {"on_scheduler": False}}))
        self.assertEqual(ids, set())

    def test_an_unreadable_config_mutes_nothing(self):
        class _Broken:
            @property
            def raw(self):
                raise RuntimeError("config unreadable")
        self.assertEqual(md._not_armed_ids(_Broken()), set())


class TheSecondDoorIsShutToo(unittest.TestCase):
    """hub_publish alerts independently of the watcher — rc_contact_sync's
    thread carried BOTH messages."""

    def _raw(self, reports, *, raises=False):
        """Stub the registry on BOTH resolution paths.

        `_is_not_armed` does `from automations.day_orchestrator import registry`,
        which resolves through the PACKAGE ATTRIBUTE once anything in the
        process has genuinely imported that submodule — so a sys.modules-only
        patch holds when this file runs alone and is silently bypassed in a
        full-suite run. These two tests caught it the honest way: green solo,
        red in the suite, because the REAL config (where rc_contact_sync really
        is not_armed) answered instead of the stub.

        The same trap as automations/day_orchestrator/test_probe_reason, which
        leaked a live 🚨 into #claudecorrections on 2026-09-03. Patch both."""
        import automations.day_orchestrator as _pkg
        cfg = mock.Mock()
        cfg.raw = {"reports": reports}
        reg = mock.Mock()
        if raises:
            reg.load_config.side_effect = RuntimeError("config unreadable")
        else:
            reg.load_config.return_value = cfg
        return _both(
            mock.patch.dict("sys.modules",
                            {"automations.day_orchestrator.registry": reg}),
            mock.patch.object(_pkg, "registry", reg, create=True))

    def _alert(self, reports, report_id):
        """Drive _alert_failure with the UNDER-TEST guard stood down.

        That guard (shared/live_effects) refuses every outward effect while a
        unittest frame is on the stack, and it runs BEFORE the not_armed check
        — so leaving it in place makes this test pass whether or not not_armed
        works at all.

        STANDING IT DOWN REMOVES THE ONLY BACKSTOP, so the notify stub has to be
        genuinely unbypassable — package attribute AND sys.modules, like the
        registry above. The first draft patched sys.modules alone and the REAL
        notify was reached; nothing posted only because it happened to raise and
        `_alert_failure` swallows. On a machine where it works, this test would
        have posted a live 🚨. The marker cooldown is neutralised too, so a
        stale stamp can't fake a pass.

        Also pins `posted` as the assertion surface: the control below proves the
        path really does reach notify when the flag is absent, so a silent
        regression in the alert path can't masquerade as not_armed working."""
        import automations.day_orchestrator as _pkg
        posted = []
        fake_notify = mock.Mock()
        fake_notify.post_alert = lambda *a, **k: posted.append((a, k))
        from automations.shared import live_effects
        with self._raw(reports), \
             mock.patch.object(live_effects, "refuse_if_under_test",
                               lambda *a, **k: False), \
             mock.patch.object(hub_publish, "_fail_marker",
                               lambda rid: Path("/nonexistent/.failalert-%s" % rid)), \
             mock.patch.object(_pkg, "notify", fake_notify, create=True), \
             mock.patch.dict("sys.modules",
                             {"automations.day_orchestrator.notify": fake_notify}):
            hub_publish._alert_failure(report_id, "B2B Customer Contacts")
        return posted

    def test_a_declared_report_posts_no_failure_alert(self):
        self.assertEqual(
            self._alert({"rc_contact_sync": {"not_armed": True}},
                        "rc_contact_sync"), [])

    def test_the_SAME_call_without_the_flag_does_alert(self):
        """The control. Without it the test above could pass because the alert
        path is broken rather than because not_armed shut it."""
        self.assertTrue(
            self._alert({"rc_contact_sync": {}}, "rc_contact_sync"),
            "the alert path itself is dead — this suite would prove nothing")

    def test_the_card_id_spelling_is_recognised(self):
        with self._raw({"rc_contact_sync": {"not_armed": True}}):
            self.assertTrue(hub_publish._is_not_armed("rc-contact-sync"))

    def test_an_ordinary_report_is_untouched(self):
        with self._raw({"rc_contact_sync": {"not_armed": True}}):
            self.assertFalse(hub_publish._is_not_armed("b2b_metrics"))

    def test_it_fails_OPEN_when_the_registry_cannot_be_read(self):
        """Silence is the expensive direction — a config hiccup must make a
        report noisy, never quiet."""
        with self._raw({}, raises=True):
            self.assertFalse(hub_publish._is_not_armed("rc_contact_sync"))


class TheLiveRegistryAgrees(unittest.TestCase):

    def test_rc_contact_sync_is_declared_and_is_the_only_one(self):
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))["reports"]
        flagged = sorted(k for k, v in raw.items() if v.get("not_armed"))
        self.assertEqual(flagged, ["rc_contact_sync"])

    def test_the_flag_carries_its_removal_instruction(self):
        """A flag left on a live report is a report that has gone quiet, so the
        note has to say that deleting it is part of arming."""
        raw = json.loads(CONFIG.read_text(encoding="utf-8"))["reports"]
        note = raw["rc_contact_sync"].get("_not_armed_note", "")
        self.assertIn("DELETE THIS LINE", note)


if __name__ == "__main__":
    unittest.main()
