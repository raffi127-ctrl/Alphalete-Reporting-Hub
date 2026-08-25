"""Cross-machine (and other unresolvable) dependencies are never dropped silently.

WHY IT'S TESTED (2026-08-24). The gate in run.py was

    unmet = [d for d in r.depends_on
             if d in ds.reports and ds.reports[d].status not in (DONE, INCOMPLETE)]

and `ds.reports` only holds reports seeded for THIS machine today. A report on
Lucy 3 declaring `depends_on` a Lucy 1 report failed the `d in ds.reports` test,
so the dependency was dropped ENTIRELY — the dependent ran immediately, out of
order, with no log line and no alert. Nothing anywhere said the ordering had
stopped happening.

What has to stay true:
  • a dep on this machine, today, still gates exactly as before;
  • a dep on ANOTHER machine is classified, never silently skipped — hard
    `depends_on` blocks, soft `after` runs but is surfaced;
  • so are a typo'd dep, an on_scheduler:false dep, a self-reference, a cycle;
  • a dep that simply isn't scheduled today is benign but still explained;
  • validate() catches all of that before the batch starts.

    python -m unittest automations.day_orchestrator.test_dep_resolution
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from automations.day_orchestrator import deps, registry

MON = dt.date(2026, 8, 24)      # weekday() == 0
FRI = dt.date(2026, 8, 28)      # weekday() == 4
DAILY = [0, 1, 2, 3, 4, 5, 6]


def _cfg(**reports) -> registry.Config:
    raw = {"settings": {}, "sources": {}, "reports": reports}
    return registry.Config(
        settings={}, sources={},
        reports={rid: registry._build_report(rid, r) for rid, r in reports.items()
                 if r.get("on_scheduler")},
        raw=raw)


def _report(machine="Lucy 1", weekdays=DAILY, on_scheduler=True, **extra):
    r = {"machine": machine, "on_scheduler": on_scheduler,
         "cadence": {"weekdays": list(weekdays)}}
    r.update(extra)
    return r


class ClassifyTests(unittest.TestCase):
    def _classify(self, cfg, dependent, dep, relation=deps.DEPENDS_ON,
                  seeded=(), date=MON, machine="Lucy 1"):
        return deps.classify(cfg, dependent, dep, relation,
                             seeded=set(seeded), date=date, machine=machine)

    def test_same_machine_today_is_enforceable(self):
        cfg = _cfg(a=_report(depends_on=["b"]), b=_report())
        e = self._classify(cfg, "a", "b", seeded={"a", "b"})
        self.assertEqual(e.kind, deps.KIND_LOCAL)
        self.assertTrue(e.enforceable)
        self.assertFalse(e.blocks)

    def test_other_machine_is_never_dropped(self):
        """THE BUG: a Lucy 3 report depending on a Lucy 1 report."""
        cfg = _cfg(a=_report(machine="Lucy 3", depends_on=["b"]),
                   b=_report(machine="Lucy 1"))
        e = self._classify(cfg, "a", "b", seeded={"a"}, machine="Lucy 3")
        self.assertEqual(e.kind, deps.KIND_OTHER_MACHINE)
        self.assertFalse(e.enforceable)
        self.assertTrue(e.unenforceable)
        self.assertTrue(e.blocks)                    # hard dep must not run through
        self.assertIn("Lucy 1", e.detail)
        self.assertIn("Lucy 3", e.detail)

    def test_other_machine_after_is_surfaced_but_does_not_block(self):
        """`after` is soft ordering — it runs, but it is still announced."""
        cfg = _cfg(a=_report(machine="Lucy 3", after=["b"]),
                   b=_report(machine="Lucy 1"))
        e = self._classify(cfg, "a", "b", relation=deps.AFTER,
                           seeded={"a"}, machine="Lucy 3")
        self.assertEqual(e.kind, deps.KIND_OTHER_MACHINE)
        self.assertTrue(e.unenforceable)
        self.assertFalse(e.blocks)

    def test_unknown_dep(self):
        cfg = _cfg(a=_report(depends_on=["nope"]))
        e = self._classify(cfg, "a", "nope", seeded={"a"})
        self.assertEqual(e.kind, deps.KIND_UNKNOWN)
        self.assertTrue(e.blocks)

    def test_off_scheduler_dep(self):
        cfg = _cfg(a=_report(depends_on=["b"]), b=_report(on_scheduler=False))
        e = self._classify(cfg, "a", "b", seeded={"a"})
        self.assertEqual(e.kind, deps.KIND_OFF_SCHEDULER)
        self.assertTrue(e.blocks)

    def test_not_scheduled_today_is_expected_not_a_problem(self):
        cfg = _cfg(a=_report(depends_on=["b"]), b=_report(weekdays=[4]))
        e = self._classify(cfg, "a", "b", seeded={"a"}, date=MON)
        self.assertEqual(e.kind, deps.KIND_NOT_TODAY)
        self.assertTrue(e.expected)
        self.assertFalse(e.blocks)
        self.assertIn("Fri", e.detail)

    def test_narrowed_by_only(self):
        """--only excluded it: intended, so it doesn't block — but it is logged."""
        cfg = _cfg(a=_report(depends_on=["b"]), b=_report())
        e = self._classify(cfg, "a", "b", seeded={"a"})
        self.assertEqual(e.kind, deps.KIND_NARROWED)
        self.assertTrue(e.expected)
        self.assertFalse(e.blocks)

    def test_every_declared_edge_is_accounted_for(self):
        """classify_all returns one edge per declaration — nothing falls through."""
        cfg = _cfg(a=_report(depends_on=["b", "c"], after=["d"]),
                   b=_report(), c=_report(machine="Lucy 2"), d=_report(weekdays=[4]))
        edges = deps.classify_all(cfg, cfg.reports["a"], seeded={"a", "b"},
                                  date=MON, machine="Lucy 1")
        self.assertEqual(len(edges), 3)
        self.assertEqual({(e.dep, e.kind) for e in edges},
                         {("b", deps.KIND_LOCAL),
                          ("c", deps.KIND_OTHER_MACHINE),
                          ("d", deps.KIND_NOT_TODAY)})


class ValidateTests(unittest.TestCase):
    def _by_dep(self, findings):
        return {(f.dependent, f.dep): f for f in findings}

    def test_clean_graph_has_no_findings(self):
        cfg = _cfg(a=_report(depends_on=["b"]), b=_report())
        self.assertEqual(deps.validate(cfg), [])

    def test_cross_machine_depends_on_is_an_error(self):
        cfg = _cfg(a=_report(machine="Lucy 3", depends_on=["b"]),
                   b=_report(machine="Lucy 1"))
        f = self._by_dep(deps.validate(cfg))[("a", "b")]
        self.assertEqual(f.severity, deps.ERROR)
        self.assertEqual(f.dependent_machine, "Lucy 3")
        self.assertIn("BLOCK", f.message)

    def test_cross_machine_after_is_a_warning(self):
        """daily_rep_breakdown (Lucy 3) `after` org_sales_board (Lucy 1) — real,
        and fine to keep running; it just must not be invisible."""
        cfg = _cfg(a=_report(machine="Lucy 3", after=["b"]),
                   b=_report(machine="Lucy 1"))
        f = self._by_dep(deps.validate(cfg))[("a", "b")]
        self.assertEqual(f.severity, deps.WARNING)
        self.assertIn("NOT enforced", f.message)

    def test_missing_dep_is_an_error(self):
        cfg = _cfg(a=_report(depends_on=["ghost"]))
        f = self._by_dep(deps.validate(cfg))[("a", "ghost")]
        self.assertEqual(f.severity, deps.ERROR)

    def test_self_dependency(self):
        cfg = _cfg(a=_report(depends_on=["a"]))
        f = self._by_dep(deps.validate(cfg))[("a", "a")]
        self.assertEqual(f.severity, deps.ERROR)
        self.assertIn("ITSELF", f.message)

    def test_cycle_is_reported(self):
        cfg = _cfg(a=_report(depends_on=["b"]), b=_report(depends_on=["c"]),
                   c=_report(depends_on=["a"]))
        msgs = [f.message for f in deps.validate(cfg) if "cycle" in f.message]
        self.assertEqual(len(msgs), 1, msgs)
        for rid in ("a", "b", "c"):
            self.assertIn(rid, msgs[0])

    def test_weekday_gap_on_a_hard_dep(self):
        cfg = _cfg(a=_report(weekdays=DAILY, depends_on=["b"]),
                   b=_report(weekdays=[0]))
        f = self._by_dep(deps.validate(cfg))[("a", "b")]
        self.assertEqual(f.severity, deps.WARNING)
        self.assertIn("Tue", f.message)

    def test_fully_disjoint_weekdays_is_an_error(self):
        cfg = _cfg(a=_report(weekdays=[4], depends_on=["b"]),
                   b=_report(weekdays=[0]))
        f = self._by_dep(deps.validate(cfg))[("a", "b")]
        self.assertEqual(f.severity, deps.ERROR)


class LiveConfigTests(unittest.TestCase):
    """The real schedule_config.json must not carry a dependency that can never
    be honored — validate() is what keeps that true from now on."""

    def test_shipped_config_has_no_dependency_errors(self):
        errors = [f.message for f in deps.validate(registry.load_config())
                  if f.severity == deps.ERROR]
        self.assertEqual(errors, [], "\n".join(errors))


class GateTests(unittest.TestCase):
    """The real gate in run._process_one — not the classifier in isolation."""

    def setUp(self):
        from automations.day_orchestrator import run, state
        self.run, self.state = run, state
        self.posted = []
        self.logged = []
        # Stub the alert path: notify.post_alert reaches Slack, and a test must
        # never post. [[feedback_recheck_state_before_delivering]]
        self._patches = [
            mock.patch("automations.day_orchestrator.notify.post_alert",
                       side_effect=lambda title, body, **kw: self.posted.append((title, body))),
            mock.patch.object(run, "_log", side_effect=self.logged.append),
            mock.patch.object(run.state, "save", lambda ds: None),
            mock.patch.object(run, "_guard_chrome", lambda r, **kw: None),
            mock.patch.object(run, "_attempt_report",
                              side_effect=lambda ds, r, rs, target, **kw: "done"),
            mock.patch.object(registry, "this_machine", lambda: "Lucy 3"),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def _gate(self, cfg, dependent, seeded):
        ds = self.state.DayState(date=MON.isoformat())
        for rid in seeded:
            ds.reports[rid] = self.state.ReportState(report_id=rid, display_name=rid)
        r = cfg.reports[dependent]
        rs = ds.reports[dependent]
        outcome = self.run._process_one(
            cfg, ds, r, rs, cache=None, target=MON,
            now=dt.datetime.combine(MON, dt.time(4, 30)),
            dry_run=True, simulate=True, channel="email", email_dry=True)
        return outcome, ds, rs

    def test_cross_machine_depends_on_blocks_and_alerts(self):
        """Before the fix this returned 'done' — it ran with the dep ignored."""
        cfg = _cfg(a=_report(machine="Lucy 3", depends_on=["b"]),
                   b=_report(machine="Lucy 1"))
        outcome, ds, rs = self._gate(cfg, "a", ["a"])
        self.assertIsNone(outcome, "must NOT run out of order")
        self.assertEqual(rs.status, self.state.PENDING)
        self.assertIn("b", rs.waiting_on)
        self.assertEqual(len(self.posted), 1)
        self.assertIn("cannot enforce", self.posted[0][0])
        self.assertTrue(any("DEPENDENCY NOT ENFORCED" in m for m in self.logged))
        self.assertTrue(ds.dep_notes, "must survive into the summary email")

    def test_cross_machine_after_runs_but_is_surfaced(self):
        cfg = _cfg(a=_report(machine="Lucy 3", after=["b"]),
                   b=_report(machine="Lucy 1"))
        outcome, ds, rs = self._gate(cfg, "a", ["a"])
        self.assertEqual(outcome, "done", "`after` is soft — it still runs")
        self.assertEqual(len(self.posted), 1)
        self.assertTrue(ds.dep_notes)

    def test_alert_fires_once_per_day_not_once_per_pass(self):
        cfg = _cfg(a=_report(machine="Lucy 3", after=["b"]),
                   b=_report(machine="Lucy 1"))
        ds = self.state.DayState(date=MON.isoformat())
        ds.reports["a"] = self.state.ReportState(report_id="a", display_name="a")
        for _ in range(3):
            self.run._process_one(
                cfg, ds, cfg.reports["a"], ds.reports["a"], cache=None, target=MON,
                now=dt.datetime.combine(MON, dt.time(4, 30)),
                dry_run=True, simulate=True, channel="email", email_dry=True)
        self.assertEqual(len(self.posted), 1)
        self.assertEqual(len([m for m in self.logged
                              if "DEPENDENCY NOT ENFORCED" in m]), 3)

    def test_local_dependency_still_gates_exactly_as_before(self):
        cfg = _cfg(a=_report(machine="Lucy 3", depends_on=["b"]),
                   b=_report(machine="Lucy 3"))
        outcome, ds, rs = self._gate(cfg, "a", ["a", "b"])
        self.assertIsNone(outcome)
        self.assertEqual(rs.waiting_on, "b")
        self.assertEqual(self.posted, [], "a normal wait is not an alert")

    def test_local_dependency_satisfied_runs(self):
        cfg = _cfg(a=_report(machine="Lucy 3", depends_on=["b"]),
                   b=_report(machine="Lucy 3"))
        ds = self.state.DayState(date=MON.isoformat())
        for rid in ("a", "b"):
            ds.reports[rid] = self.state.ReportState(report_id=rid, display_name=rid)
        ds.reports["b"].status = self.state.DONE
        outcome = self.run._process_one(
            cfg, ds, cfg.reports["a"], ds.reports["a"], cache=None, target=MON,
            now=dt.datetime.combine(MON, dt.time(4, 30)),
            dry_run=True, simulate=True, channel="email", email_dry=True)
        self.assertEqual(outcome, "done")

    def test_dep_not_scheduled_today_is_logged_not_alerted(self):
        cfg = _cfg(a=_report(machine="Lucy 3", depends_on=["b"]),
                   b=_report(machine="Lucy 3", weekdays=[4]))
        outcome, ds, rs = self._gate(cfg, "a", ["a"])
        self.assertEqual(outcome, "done")
        self.assertEqual(self.posted, [])
        self.assertTrue(any("not waiting on" in m for m in self.logged))


if __name__ == "__main__":
    unittest.main()
