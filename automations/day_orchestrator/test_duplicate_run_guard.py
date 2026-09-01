"""The orchestrator's DUPLICATE-RUN guard (`run._attempt_report_inner`) and the
shared pid probe behind it (`proc_guard.running_pids`).

WHAT THESE GUARD (2026-08-24). captainship_drafts — a ~2h browser report — ran
THREE times at once: Eve's manual `lucy rerun` at 09:11, then the day
orchestrator launching its own copies at 09:14 and 09:18. They fought over the
shared Chrome profile, the build took ~2.5h, and the mini's serial control queue
was blocked all morning.

Both launchers already had a guard, and BOTH were dead: they ran
`pgrep -f "-m automations.x"`, and BSD pgrep reads that leading `-m` as an
option ("illegal option -- m", exit 2, empty stdout), so every check answered
"nothing is running". Hence two things are pinned here:

  • the probe: the pattern can never start with a dash again, a pgrep that
    fails to SEARCH is never read as "nothing running", and a shell that merely
    mentions the module isn't mistaken for the run;
  • the guard: a report that is already running is DEFERRED, not failed — no
    subprocess, no Hub pill, no alert, no attempt spent — and it stays in the
    loop so a later pass runs it, or the noon backstop retires it as a report
    that NEVER RAN (never a silently green day).

    PYTHONPATH=. .venv/bin/python -m unittest \
        automations.day_orchestrator.test_duplicate_run_guard
"""
from __future__ import annotations

import datetime as dt
import types
import unittest
from unittest import mock

from automations.day_orchestrator import notify, proc_guard, reconcile
from automations.day_orchestrator import run as R
from automations.day_orchestrator import state

TARGET = dt.date(2026, 8, 24)
MODULE = "automations.captainship_drafts.run"


class _Report:
    def __init__(self, report_id="captainship_drafts", source_type="tableau",
                 duplicate_guard=True, command=None, base_args=None):
        self.report_id = report_id
        self.display_name = "Captainship Reports"
        self.source_type = source_type
        self.command = command or [MODULE]
        self.base_args = ["--dry-run"] if base_args is None else base_args
        self.timeout_minutes = 120
        self.verify = {}
        self.depends_on = []
        self.after = []
        self.not_before = None
        self.duplicate_guard = duplicate_guard


class _Hub:
    """Stand-in for hub_publish that records every pill it is asked to write."""

    def __init__(self):
        self.running, self.done, self.beats = [], [], []

    def hub_card_id(self, report_id):
        return "card-" + report_id

    def publish_running(self, report_id, display_name):
        self.running.append(report_id)
        return "run-1"

    def publish_done(self, report_id, display_name, **kw):
        self.done.append((report_id, kw.get("status")))
        return True

    def publish_heartbeat(self, run_id):
        self.beats.append(run_id)

    def final_status(self, report_id, ok=True):
        return "success" if ok else "failed"

    def incomplete_status(self, report_id):
        return "success"


class _GuardBase(unittest.TestCase):
    def setUp(self):
        # Never touch output/day_state/<date>.json from a test.
        self._p(mock.patch.object(state, "save", lambda ds: None))
        self.hub = _Hub()
        # run.py imports hub_publish lazily INSIDE the functions, and
        # `from pkg import mod` reads the package ATTRIBUTE when the real module
        # has already been imported (which another test in the same run may well
        # have done) — so patching sys.modules alone leaves the real Hub wired in
        # under `unittest discover` while passing in isolation. Patch both.
        import automations.day_orchestrator as _pkg
        self._p(mock.patch.object(_pkg, "hub_publish", self.hub, create=True))
        self._p(mock.patch.dict(
            "sys.modules",
            {"automations.day_orchestrator.hub_publish": self.hub}))
        self.runs = []
        self.alerts = []

        def _fake_run_report(r, target, **kw):
            self.runs.append(r.report_id)
            return True, "exit 0"

        self._p(mock.patch.object(R, "_run_report", _fake_run_report))
        self._p(mock.patch.object(R, "_guard_chrome", lambda r, **kw: None))
        self._p(mock.patch.object(
            notify, "post_alert",
            lambda title, body, **kw: self.alerts.append(title) or "1.0"))
        self._p(mock.patch.object(
            reconcile, "verify",
            lambda r, target, dry_run=False: reconcile.ReconResult(
                ok=True, unknown=False, note="manifest clean")))

    def _p(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def _busy(self, pids):
        self._p(mock.patch.object(R, "_already_running", lambda module: list(pids)))

    def _fresh(self, r):
        ds = state.DayState(date=TARGET.isoformat())
        rs = state.ReportState(report_id=r.report_id,
                               display_name=r.display_name)
        ds.reports[r.report_id] = rs
        return ds, rs


class DuplicateRunGuard(_GuardBase):
    # ---- a copy is already running -------------------------------------
    def test_busy_defers_and_launches_nothing(self):
        self._busy(["1234"])
        r = _Report()
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=False, simulate=False)
        self.assertEqual(outcome, "deferred")
        self.assertEqual(self.runs, [])            # no second subprocess
        self.assertEqual(self.hub.running, [])     # no 'started' row
        self.assertEqual(self.hub.done, [])        # and nothing closed
        self.assertEqual(self.alerts, [])          # a rerun in flight isn't a failure
        self.assertIsNone(rs.hub_run_id)

    def test_busy_does_not_burn_an_attempt(self):
        """A deferral must not spend the retry budget — nothing ran."""
        self._busy(["1234"])
        r = _Report()
        ds, rs = self._fresh(r)
        for _ in range(R.MAX_RUN_RETRIES + 2):
            R._attempt_report(ds, r, rs, TARGET, dry_run=False, simulate=False)
        self.assertEqual(rs.attempts, 0)
        self.assertIsNone(rs.last_attempt_ts)
        self.assertFalse(rs.is_terminal())

    def test_busy_state_is_the_retry_later_one(self):
        self._busy(["1234", "1235"])
        r = _Report()
        ds, rs = self._fresh(r)
        R._attempt_report(ds, r, rs, TARGET, dry_run=False, simulate=False)
        self.assertEqual(rs.status, state.STILL_TRYING)
        self.assertEqual(rs.waiting_on, R.DUPLICATE_WAITING_ON)
        self.assertIn("1234", rs.last_reason)
        # _apply_backstop reads waiting_on for 'session' to decide BLOCKED_SESSION.
        self.assertNotIn("session", R.DUPLICATE_WAITING_ON.lower())

    # ---- nothing running: the normal path is untouched -------------------
    def test_free_runs_exactly_as_before(self):
        self._busy([])
        r = _Report()
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=False, simulate=False)
        self.assertEqual(outcome, "done")
        self.assertEqual(self.runs, [r.report_id])
        self.assertEqual(self.hub.running, [r.report_id])
        self.assertEqual(rs.status, state.DONE)
        self.assertEqual(rs.attempts, 1)

    # ---- dry-run / simulate never look at real processes ------------------
    def test_dry_run_bypasses_the_guard(self):
        self._busy(["1234"])
        r = _Report()
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=True, simulate=False)
        self.assertEqual(outcome, "done")
        self.assertEqual(self.runs, [r.report_id])

    def test_simulate_bypasses_the_guard(self):
        self._busy(["1234"])
        r = _Report()
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=False, simulate=True)
        self.assertEqual(outcome, "done")
        self.assertEqual(self.runs, [r.report_id])

    # ---- it comes back for the report ------------------------------------
    def test_service_tick_reattempts_a_deferred_report(self):
        """The moment the other copy ends, the next tick starts ours — without a
        Tableau re-probe (it had already passed readiness)."""
        self._busy([])
        launched = []
        self._p(mock.patch.object(
            R, "_attempt_report",
            lambda ds, r, rs, target, **kw: launched.append(r.report_id)))
        r = _Report()
        ds, rs = self._fresh(r)
        ds.set(r.report_id, state.STILL_TRYING, reason="already running here",
               waiting_on=R.DUPLICATE_WAITING_ON)

        class _Cache:
            probes = 0

            def report_ready(self, rpt):
                self.probes += 1
                raise AssertionError("a deferred report must not be re-probed")

        cache = _Cache()
        R._service_owed(ds, [(r, rs)], TARGET, cache, {},
                        dry_run=False, simulate=False)
        self.assertEqual(launched, [r.report_id])
        self.assertEqual(cache.probes, 0)

    # ---- the Hub is not told a run happened -------------------------------
    def test_pill_sync_opens_no_row_for_a_deferred_report(self):
        r = _Report()
        ds, rs = self._fresh(r)
        ds.set(r.report_id, state.STILL_TRYING, reason="already running here",
               waiting_on=R.DUPLICATE_WAITING_ON)
        R._sync_hub_pills(ds, dry_run=False, simulate=False)
        self.assertEqual(self.hub.running, [])
        self.assertEqual(self.hub.done, [])

    def test_pill_sync_still_opens_a_row_for_an_ordinary_wait(self):
        r = _Report()
        ds, rs = self._fresh(r)
        ds.set(r.report_id, state.STILL_TRYING, reason="extract not refreshed",
               waiting_on="extract not refreshed")
        R._sync_hub_pills(ds, dry_run=False, simulate=False)
        self.assertEqual(self.hub.running, [r.report_id])


class DeferredAtEndOfDay(_GuardBase):
    """A report that never launched must never end the day counted as clean."""

    def _deferred_state(self):
        r = _Report()
        ds, rs = self._fresh(r)
        ds.set(r.report_id, state.STILL_TRYING,
               reason="not launched — already running here (pid 1234)",
               waiting_on=R.DUPLICATE_WAITING_ON)
        return ds, rs

    def test_still_deferred_is_not_terminal_so_the_day_keeps_trying(self):
        ds, rs = self._deferred_state()
        self.assertFalse(ds.all_terminal())

    def test_backstop_retires_it_as_never_ran(self):
        ds, rs = self._deferred_state()
        with mock.patch.object(R.readiness, "session_status",
                               lambda stale_after: (True, "", "")):
            R._apply_backstop(ds, 20)
        self.assertEqual(rs.status, state.MISSED_NOT_READY)
        self.assertIn("never launched", rs.last_reason)
        # NOT blamed on late data / a stale ownerville session.
        self.assertNotEqual(rs.status, state.BLOCKED_SESSION)
        self.assertNotIn("data never ready", rs.last_reason)

    def test_it_reaches_the_alert_sweep(self):
        """MISSED is what fires the per-report #claudecorrections alert."""
        ds, rs = self._deferred_state()
        with mock.patch.object(R.readiness, "session_status",
                               lambda stale_after: (True, "", "")):
            R._apply_backstop(ds, 20)
        alerted = []
        with mock.patch.object(
                R, "_maybe_failure_alert",
                lambda cfg, ds_, rs_, ch, dry: alerted.append(rs_.report_id)):
            R._alert_new_failures(None, ds, {}, "slack", True)
        self.assertEqual(alerted, [rs.report_id])

    def test_final_summary_lists_it_under_needs_attention(self):
        ds, rs = self._deferred_state()
        with mock.patch.object(R.readiness, "session_status",
                               lambda stale_after: (True, "", "")):
            R._apply_backstop(ds, 20)
        cfg = types.SimpleNamespace(reports={}, settings={})
        _html, text = notify._build_body(cfg, ds, checkpoint=False)
        self.assertIn("NEEDS ATTENTION", text)
        self.assertIn("Captainship Reports", text)
        self.assertNotIn("Everything ran clean", text)


class PidProbe(unittest.TestCase):
    """proc_guard.running_pids — the probe both launchers now share."""

    def _fake_subprocess(self, pgrep_out, pgrep_rc=0, ps_map=None):
        """subprocess stand-in: first call is pgrep, later calls are `ps -p`."""
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == "pgrep":
                return types.SimpleNamespace(returncode=pgrep_rc,
                                             stdout=pgrep_out, stderr="")
            pid = cmd[-1]
            return types.SimpleNamespace(
                returncode=0, stdout=(ps_map or {}).get(pid, ""), stderr="")

        return types.SimpleNamespace(run=run), calls

    def _patch(self, fake):
        p = mock.patch.object(proc_guard, "subprocess", fake)
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(proc_guard.sys, "platform", "darwin")
        p2.start()
        self.addCleanup(p2.stop)

    # ---- the 2026-08-24 root cause, pinned -------------------------------
    def test_the_pattern_never_starts_with_a_dash(self):
        """`pgrep -f "-m mod"` is parsed as an OPTION by BSD pgrep — the bug that
        made both guards answer 'nothing is running' every single time."""
        pat = proc_guard._pattern(MODULE)
        self.assertFalse(pat.startswith("-"), pat)
        self.assertTrue(pat.startswith("[-]m "), pat)

    def test_pgrep_is_called_with_a_dash_free_pattern(self):
        fake, calls = self._fake_subprocess("", pgrep_rc=1)
        self._patch(fake)
        proc_guard.running_pids(MODULE)
        self.assertEqual(calls[0][:2], ["pgrep", "-f"])
        self.assertFalse(calls[0][2].startswith("-"), calls[0])

    def test_a_pgrep_that_could_not_search_is_not_read_as_idle(self):
        """Exit >= 2 means the search never happened. It returns [] (best-effort)
        but must SAY so, instead of silently green-lighting a second copy."""
        fake, _calls = self._fake_subprocess("", pgrep_rc=2)
        self._patch(fake)
        with mock.patch.object(proc_guard.sys, "stderr") as err:
            self.assertEqual(proc_guard.running_pids(MODULE), [])
        self.assertTrue(err.write.called)

    # ---- precision -------------------------------------------------------
    def test_the_python_run_counts(self):
        fake, _ = self._fake_subprocess(
            "4321\n", ps_map={"4321": "/repo/.venv/bin/python -u -m " + MODULE})
        self._patch(fake)
        self.assertEqual(proc_guard.running_pids(MODULE), ["4321"])

    def test_a_shell_that_merely_mentions_the_module_does_not(self):
        fake, _ = self._fake_subprocess(
            "4321\n", ps_map={"4321": "/bin/zsh -c lucy rerun -m " + MODULE})
        self._patch(fake)
        self.assertEqual(proc_guard.running_pids(MODULE), [])

    def test_a_pid_that_exited_between_pgrep_and_ps_does_not(self):
        fake, _ = self._fake_subprocess("4321\n", ps_map={})
        self._patch(fake)
        self.assertEqual(proc_guard.running_pids(MODULE), [])

    def test_module_dots_are_escaped_and_the_end_anchored(self):
        pat = proc_guard._pattern("automations.a.b")
        self.assertIn(r"automations\.a\.b", pat)
        self.assertTrue(pat.endswith("( |$)"), pat)

    def test_windows_is_a_no_op(self):
        with mock.patch.object(proc_guard.sys, "platform", "win32"):
            self.assertEqual(proc_guard.running_pids(MODULE), [])

    def test_a_broken_probe_never_raises(self):
        boom = types.SimpleNamespace(
            run=lambda *a, **kw: (_ for _ in ()).throw(OSError("no pgrep")))
        self._patch(boom)
        self.assertEqual(proc_guard.running_pids(MODULE), [])

    def test_both_launchers_share_one_implementation(self):
        """mini_control's rerun guard and the orchestrator's must not drift."""
        from automations.day_orchestrator import mini_control
        with mock.patch.object(proc_guard, "running_pids",
                               lambda module: ["999"]) as _:
            self.assertEqual(mini_control._running_pids(MODULE), ["999"])
            self.assertEqual(R._already_running(MODULE), ["999"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class SharedModuleOptOut(_GuardBase):
    """`duplicate_guard: false` — a report whose MODULE is shared with another
    job on the same box and that holds no browser profile.

    WHY (Eve 2026-09-01). country_sales_board_email runs
    `automations.board_emails.review_gate --post --board country`. The SAME
    module is what deploy/org_board_email_review.sh runs every 15 minutes, all
    day, to poll for the approval checkmark. proc_guard builds its pgrep
    pattern from command[0] and anchors it right after the module name, so the
    arguments — the only thing telling a --post from a --check — are invisible
    to it: the two jobs are one process to the guard.

    That morning the daily post lost a 3-second race to a checker tick. The
    pre-launch guard cleared at 08:54:53; the LAST-LINE-OF-DEFENCE guard inside
    _run_report failed the report at 08:54:56. That path returns a hard FAILURE
    rather than the pre-launch deferral, so the attempt burned, the incident
    fired, no log was written at all, and the review link never went up — on a
    board that had filled perfectly. review_gate opens no browser (it reads the
    Sheet over OAuth and exports PDFs), so the Chrome-profile collision the
    guard exists to prevent cannot happen to it.

    Both guards must be off for such a report, and ONLY for it.
    """

    def _opted_out(self):
        return _Report(report_id="country_sales_board_email",
                       source_type="local", duplicate_guard=False,
                       command=["automations.board_emails.review_gate"],
                       base_args=["--post", "--board", "country"])

    def test_a_busy_module_does_not_defer_the_opted_out_report(self):
        self._busy(["64070"])                      # the 15-minute checker
        r = self._opted_out()
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=False,
                                    simulate=False)
        self.assertEqual(outcome, "done")
        self.assertEqual(self.runs, [r.report_id])
        self.assertEqual(rs.status, state.DONE)

    def test_the_last_line_of_defence_is_skipped_too(self):
        """The pre-launch check is not enough on its own: the 2026-09-01 kill
        came from the second guard, inside _run_report."""
        import tempfile
        from pathlib import Path

        class _Proc:
            def wait(self, timeout=None):
                return 0

        r = self._opted_out()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(R, "_already_running",
                                   lambda module: ["64070"]),                  mock.patch.object(R, "LOG_DIR", Path(tmp)),                  mock.patch.object(R.subprocess, "Popen",
                                   lambda *a, **kw: _Proc()):
                ok, detail = R._run_report(r, TARGET, dry_run=False,
                                           simulate=False)
        self.assertTrue(ok, detail)
        self.assertNotIn("already running", detail)

    def test_an_ordinary_report_still_defers(self):
        """The opt-out is per report — it must not weaken the default."""
        self._busy(["1234"])
        r = _Report()                              # duplicate_guard defaults True
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=False,
                                    simulate=False)
        self.assertEqual(outcome, "deferred")
        self.assertEqual(self.runs, [])

    def test_a_report_object_without_the_field_is_guarded(self):
        """getattr default: an older/stub report is guarded, not exempt."""
        r = _Report()
        del r.duplicate_guard
        self._busy(["1234"])
        ds, rs = self._fresh(r)
        outcome = R._attempt_report(ds, r, rs, TARGET, dry_run=False,
                                    simulate=False)
        self.assertEqual(outcome, "deferred")

    def test_the_live_config_opts_out_exactly_one_report(self):
        """A blanket opt-out would put the fleet back where 2026-08-24 started."""
        from automations.day_orchestrator import registry
        cfg = registry.load_config()
        off = sorted(rid for rid, rep in cfg.reports.items()
                     if not rep.duplicate_guard)
        self.assertEqual(off, ["country_sales_board_email"])
