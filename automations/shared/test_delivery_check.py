"""Green means DELIVERED, and "we can't tell" is not green (Megan 2026-09-09).

The standing rule for #claudecorrections is that a ticket goes green only when
the thing is actually fixed. It did not hold because "ran" and "delivered" were
the same word: `verify: not_configured` (112 reports) made reconcile answer
`unknown`, the orchestrator turned that into DONE, DONE published `success`, and
`success` posted "RESOLVED. It just ran clean."

The guard on the guard (Megan, same day): "make sure verdict correctly returns
DELIVERED for the normal daily reports that genuinely do post … I don't want the
channel to flip into a wall of false-red the same way it had false-green." So
these tests are as much about the reports that MUST still go green as about the
ones that must not.

    python -m unittest automations.shared.test_delivery_check
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.shared import delivery_check as dc

DAY = dt.date(2026, 9, 8)


def _quiet(**over):
    """Patch every evidence probe off, then switch back on the ones a test wants.
    Keeps each case about ONE source instead of the whole ladder."""
    probes = {"_from_phases": None, "_from_verifier": None,
              "_from_manifest": None, "_from_post_watch": None}
    probes.update(over)
    return [mock.patch.object(dc, name, return_value=val)
            for name, val in probes.items()]


class _Base(unittest.TestCase):
    def _verdict(self, report_id="r", **over):
        patches = _quiet(**over)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return dc.verdict(report_id, DAY)


class NormalReportsStillGoGreen(_Base):
    """The half that matters most. Every ordinary daily report keeps closing its
    ticket the moment it genuinely delivers — from whichever evidence it leaves."""

    def test_a_clean_manifest_is_delivered(self):
        v, why = self._verdict(_from_manifest=(dc.DELIVERED, "manifest: nothing failed"))
        self.assertEqual(v, dc.DELIVERED)

    def test_a_passing_verifier_is_delivered(self):
        v, _ = self._verdict(_from_verifier=(dc.DELIVERED, "verify(manifest): ok"))
        self.assertEqual(v, dc.DELIVERED)

    def test_a_post_watch_marker_is_delivered(self):
        v, _ = self._verdict(_from_post_watch=(dc.DELIVERED, "marker present"))
        self.assertEqual(v, dc.DELIVERED)

    def test_a_report_that_watched_its_own_post_land_outranks_everything(self):
        """Nothing here can see more than the code that did the sending."""
        v, _ = dc.verdict("r", DAY, delivered=True)
        self.assertEqual(v, dc.DELIVERED)

    def test_a_findings_run_delivered(self):
        """The audit did its WHOLE job and is reporting what it saw. That is a
        delivery; the finding is a separate ticket a re-run cannot close."""
        m = {"run_ts": DAY.isoformat() + "T04:01:00", "kind": "finding",
             "failed": ["3 open board findings"], "ok": False}
        with mock.patch("automations.shared.run_manifest.read_manifest",
                        return_value=m):
            v, why = dc._from_manifest("vantura_board_audit", DAY)
        self.assertEqual(v, dc.DELIVERED)
        self.assertIn("findings", why)


class TheManifestIsFiledUnderADifferentName(unittest.TestCase):
    """The bug that almost shipped, caught by running the sample against the
    mini (2026-09-09).

    A manifest is written under the id the report's OWN code uses, which is
    usually not its schedule_config key. The mini's manifests today are
    `captainship-abp-6days`, `org-sales-board`, `daily-focus`,
    `recruiter-retention-daily`; the config keys are the underscore forms, and
    `_clear_failure` is called with the config key.

    Asking only for the config key finds nothing for nearly every report that
    writes a manifest — and "no manifest" is UNKNOWN, which HOLDS THE TICKET
    OPEN. That is the wall of false red this module is under orders not to
    build, and it would have looked like a design flaw rather than a lookup bug.
    """

    def test_the_dashed_spelling_is_tried(self):
        self.assertIn("org-sales-board", dc.manifest_ids("org_sales_board"))
        self.assertIn("captainship-abp-6days",
                      dc.manifest_ids("captainship_abp_6days"))

    def test_the_config_key_is_tried_first(self):
        self.assertEqual(dc.manifest_ids("daily_focus")[0], "daily_focus")

    def test_a_declared_verify_report_id_is_tried_too(self):
        """schedule_config's `verify: {report_id: …}` names it outright for the
        reports that bothered — carlos_focus -> carlos-1on1s-run."""
        with mock.patch.object(dc, "_reports", return_value={
                "carlos_focus": {"verify": {"type": "manifest",
                                            "report_id": "carlos-1on1s-run"}}}):
            ids = dc.manifest_ids("carlos_focus")
        self.assertIn("carlos-1on1s-run", ids)
        self.assertLess(ids.index("carlos-1on1s-run"), ids.index("carlos-focus"),
                        "a declared id is the more specific statement")

    def test_a_dashed_manifest_actually_answers_delivered(self):
        seen = []

        def _read(mid):
            seen.append(mid)
            if mid != "org-sales-board":
                return None
            return {"run_ts": DAY.isoformat() + "T04:35:00", "failed": [],
                    "ok": True, "kind": "part"}

        with mock.patch("automations.shared.run_manifest.read_manifest", _read):
            got = dc._from_manifest("org_sales_board", DAY)
        self.assertEqual(got[0], dc.DELIVERED)
        self.assertIn("org_sales_board", seen)
        self.assertIn("org-sales-board", seen)


class ItRefusesToGuessGreen(_Base):

    def test_nothing_to_go_on_is_unknown_not_delivered(self):
        v, why = self._verdict()
        self.assertEqual(v, dc.UNKNOWN)
        self.assertIn("verify", why)

    def test_unknown_does_not_let_a_ticket_close(self):
        with mock.patch.object(dc, "verdict", return_value=(dc.UNKNOWN, "…")):
            ok, v, _ = dc.may_close("r", DAY)
        self.assertFalse(ok)
        self.assertEqual(v, dc.UNKNOWN)

    def test_a_failed_part_is_not_delivered(self):
        v, _ = self._verdict(_from_manifest=(dc.NOT_DELIVERED, "1 part failed"))
        self.assertEqual(v, dc.NOT_DELIVERED)

    def test_leaders_call_phase_one_is_not_delivered(self):
        """The reference case: the 2pm tab fill writes a perfectly good manifest
        and has sent nothing. The phase check has to run BEFORE the manifest, or
        every other signal says delivered."""
        v, why = self._verdict(
            _from_phases=(dc.NOT_DELIVERED, "pass 1 of 2 for today"),
            _from_manifest=(dc.DELIVERED, "manifest: nothing failed"))
        self.assertEqual(v, dc.NOT_DELIVERED)
        self.assertIn("1 of 2", why)

    def test_a_stale_manifest_is_not_evidence_about_today(self):
        m = {"run_ts": "2026-09-01T04:00:00", "failed": [], "ok": True}
        with mock.patch("automations.shared.run_manifest.read_manifest",
                        return_value=m):
            self.assertIsNone(dc._from_manifest("r", DAY))

    def test_an_errored_check_is_unknown_never_green(self):
        with mock.patch.object(dc, "_from_phases", side_effect=RuntimeError("x")), \
             mock.patch.object(dc, "declared_exit_zero", return_value=False):
            v, why = dc.verdict("r", DAY)
        self.assertEqual(v, dc.UNKNOWN)
        self.assertIn("errored", why)


class TheDeclaredEscapeHatch(unittest.TestCase):
    """For the classes where delivery genuinely is not observable — a probe, an
    installer, a one-shot utility whose whole job IS exiting 0. Declared per
    report in schedule_config, never guessed: same rule as hand_run_only."""

    def test_a_declared_report_closes_on_exit_zero(self):
        with mock.patch.object(dc, "_reports",
                               return_value={"probe_b2b_views":
                                             {"close_on": "exit_zero"}}):
            v, why = dc.verdict("probe_b2b_views", DAY)
        self.assertEqual(v, dc.DELIVERED)
        self.assertIn("declared", why)

    def test_an_undeclared_report_gets_no_such_pass(self):
        with mock.patch.object(dc, "_reports",
                               return_value={"daily_metrics": {}}):
            self.assertFalse(dc.declared_exit_zero("daily_metrics"))

    def test_the_declaration_is_read_through_the_dashed_spelling_too(self):
        """Producers use both `vantura_board_audit` and `vantura-board-audit`."""
        with mock.patch.object(dc, "_reports",
                               return_value={"vantura_board_audit":
                                             {"close_on": "exit_zero"}}):
            self.assertTrue(dc.declared_exit_zero("vantura-board-audit"))

    def test_a_report_cannot_declare_itself_delivered_by_accident(self):
        """Only the exact token counts — a typo must fail closed, not open."""
        with mock.patch.object(dc, "_reports",
                               return_value={"r": {"close_on": "exit0"}}):
            self.assertFalse(dc.declared_exit_zero("r"))


class TheCloseSitesActuallyAskIt(unittest.TestCase):
    """A gate nothing calls is a comment. These are the four paths that could
    put a check on a ticket off "the run exited 0"."""

    def test_hub_publish_clear_failure_asks_before_closing(self):
        from automations.day_orchestrator import hub_publish as hp
        with mock.patch("automations.shared.live_effects.refuse_if_under_test",
                        return_value=False), \
             mock.patch.object(dc, "may_close",
                               return_value=(False, dc.UNKNOWN, "no verify")), \
             mock.patch("automations.shared.incident_thread.resolve_report") as res, \
             mock.patch("automations.shared.incident_thread"
                        ".note_delivery_unverified") as noted:
            hp._clear_failure("leaders_call", "Leader's Call")
        res.assert_not_called()
        noted.assert_called_once()

    def test_hub_publish_still_closes_a_delivered_run(self):
        from automations.day_orchestrator import hub_publish as hp
        with mock.patch("automations.shared.live_effects.refuse_if_under_test",
                        return_value=False), \
             mock.patch.object(dc, "may_close",
                               return_value=(True, dc.DELIVERED, "manifest")), \
             mock.patch("automations.shared.incident_thread.resolve_report") as res:
            hp._clear_failure("daily_metrics", "Daily Metrics")
        res.assert_called_once()

    def test_a_not_delivered_run_is_not_even_noted_as_unverified(self):
        """It is not a wiring gap — the run genuinely did not deliver, and the
        original alert already says what is wrong."""
        from automations.day_orchestrator import hub_publish as hp
        with mock.patch("automations.shared.live_effects.refuse_if_under_test",
                        return_value=False), \
             mock.patch.object(dc, "may_close",
                               return_value=(False, dc.NOT_DELIVERED,
                                             "pass 1 of 2")), \
             mock.patch("automations.shared.incident_thread.resolve_report") as res, \
             mock.patch("automations.shared.incident_thread"
                        ".note_delivery_unverified") as noted:
            hp._clear_failure("leaders_call", "Leader's Call")
        res.assert_not_called()
        noted.assert_not_called()

    def test_the_orchestrators_two_close_paths_go_through_the_gate(self):
        from pathlib import Path
        run_py = (Path(dc.__file__).resolve().parents[1]
                  / "day_orchestrator" / "run.py").read_text(encoding="utf-8")
        self.assertIn("def _delivered_enough(", run_py)
        # …the failure-alert edit
        body = run_py[run_py.index("def _resolve_failure_alerts"):]
        body = body[:body.index("def _close_carryover_incidents")]
        self.assertIn("_delivered_enough(", body)
        # …and the carry-over close
        body = run_py[run_py.index("def _close_carryover_incidents"):]
        body = body[:body.index("def _check_post_watch")]
        self.assertIn("_delivered_enough(", body)

    def test_the_standalone_watcher_goes_through_it_too(self):
        from pathlib import Path
        src = (Path(dc.__file__).resolve().parents[1]
               / "machine_digest" / "run.py").read_text(encoding="utf-8")
        body = src[src.index("def _close_recovered_incidents"):]
        body = body[:body.index("def _close_silent_job_incidents")]
        self.assertIn("delivery_check", body)
        self.assertIn("may_close(", body)

    def test_a_broken_gate_closes_as_before_rather_than_going_quiet(self):
        """This gate exists to stop a confident false green, not to invent a new
        way for the batch to say nothing at all."""
        with mock.patch.object(dc, "_from_phases", side_effect=RuntimeError):
            v, _ = dc.verdict("r")
        self.assertEqual(v, dc.UNKNOWN)   # never DELIVERED off an error…
        from pathlib import Path
        run_py = (Path(dc.__file__).resolve().parents[1]
                  / "day_orchestrator" / "run.py").read_text(encoding="utf-8")
        body = run_py[run_py.index("def _delivered_enough("):]
        body = body[:body.index("def _resolve_failure_alerts")]
        self.assertIn("closing as before", body)   # …but an EXCEPTION is not a hold


class TheUnverifiedNoteIsSaidOnceADay(unittest.TestCase):

    def setUp(self):
        import tempfile
        from pathlib import Path
        from automations.shared import incident_thread as inc
        self.inc = inc
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, sub in (("STATE_PATH", "idx.json"),
                          ("_UNVERIFIED_DIR", "unverified")):
            old = getattr(inc, name)
            setattr(inc, name, Path(self.tmp.name) / sub)
            self.addCleanup(lambda n=name, o=old: setattr(inc, n, o))
        inc._save_index({"failure-r": {"ts": "1.0", "channel": "C1",
                                       "opened": "2026-09-08",
                                       "resolved": False}})

    def _note(self, client):
        return self.inc.note_delivery_unverified(
            "r", what="R", why="its `verify` is not wired", channel="C1",
            day=DAY, client=client)

    def test_it_says_it_in_the_open_thread(self):
        c = mock.MagicMock()
        c.chat_postMessage.return_value = {"ok": True, "ts": "9.0"}
        self.assertTrue(self._note(c))
        said = c.chat_postMessage.call_args.kwargs
        self.assertEqual(said["thread_ts"], "1.0")
        self.assertIn("nothing can confirm it DELIVERED", said["text"])
        self.assertIn("close_on", said["text"], "name the way out, not just the "
                                                "problem")

    def test_a_second_clean_run_the_same_day_says_nothing(self):
        c = mock.MagicMock()
        c.chat_postMessage.return_value = {"ok": True, "ts": "9.0"}
        self._note(c)
        c.chat_postMessage.reset_mock()
        self.assertFalse(self._note(c))
        c.chat_postMessage.assert_not_called()

    def test_with_nothing_open_it_is_free_and_silent(self):
        self.inc._save_index({"failure-r": {"ts": "1.0", "resolved": True}})
        c = mock.MagicMock()
        self.assertFalse(self._note(c))
        c.chat_postMessage.assert_not_called()

    def test_it_never_touches_a_findings_thread(self):
        self.inc._save_index({"finding-r": {"ts": "1.0", "channel": "C1",
                                            "opened": "2026-09-08",
                                            "resolved": False}})
        c = mock.MagicMock()
        self.assertFalse(self._note(c))


class TheRealScheduleStillWorks(unittest.TestCase):
    """The sample Megan asked for, as an assertion rather than a printout: the
    declared escape hatches have to be READABLE and the reports that carry real
    verifiers have to be recognised as such."""

    def test_every_close_on_value_in_the_config_is_one_we_understand(self):
        bad = {rid: rec.get("close_on") for rid, rec in dc._reports().items()
               if rec.get("close_on")
               and rec.get("close_on") != dc.CLOSE_ON_EXIT_ZERO}
        self.assertEqual(bad, {}, "an unrecognised close_on fails closed and "
                                  "would strand that report red forever")

    def test_reports_with_a_manifest_verifier_can_answer_from_it(self):
        wired = [rid for rid, rec in dc._reports().items()
                 if (rec.get("verify") or {}).get("type") == "manifest"]
        self.assertGreater(len(wired), 40,
                           "the manifest verifier is the main evidence source; "
                           "if this collapses, so does the green path")

    def test_leaders_call_is_no_longer_unverifiable(self):
        v = (dc._reports().get("leaders_call") or {}).get("verify") or {}
        self.assertNotEqual(v.get("type"), "not_configured")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
