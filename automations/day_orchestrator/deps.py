"""Dependency classification for the day orchestrator — `depends_on` / `after`.

WHY THIS EXISTS (2026-08-24). The gate in run.py used to be:

    unmet = [d for d in r.depends_on
             if d in ds.reports
             and ds.reports[d].status not in (DONE, INCOMPLETE)]

`ds.reports` only holds reports seeded for THIS machine today (run.py seeds from
`registry.scheduled_today(cfg, target, machine=registry.this_machine())`). So any
dependency pointing at another runner's report — or at a typo, or at an
`on_scheduler: false` report — failed the `d in ds.reports` test and was dropped
ENTIRELY: the dependent ran immediately, out of order, with no log line, no
alert, nothing. A report on Lucy 3 declaring `depends_on` a Lucy 1 report was
simply unordered, and nothing anywhere said so.

A declared dependency that is not honored must never be invisible. Every dep is
classified here into exactly one kind, and run.py has to do something visible
with each one — wait on it, log why it is not in play, or alert.

Pure config/state logic: no I/O, no state mutation, no network. Unit-testable
offline, same shape as registry.py.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set

from automations.day_orchestrator.registry import DEFAULT_MACHINE

DEPENDS_ON = "depends_on"
AFTER = "after"
RELATIONS = (DEPENDS_ON, AFTER)

# ---- edge kinds -------------------------------------------------------------
KIND_LOCAL = "local"                  # in today's state on this machine — enforceable
KIND_NOT_TODAY = "not_today"          # ours, but its cadence doesn't include today
KIND_NARROWED = "narrowed"            # ours + scheduled today, excluded by --only
KIND_OTHER_MACHINE = "other_machine"  # assigned to a DIFFERENT runner
KIND_OFF_SCHEDULER = "off_scheduler"  # on_scheduler:false — the batch never runs it
KIND_UNKNOWN = "unknown"              # not in schedule_config.json at all

# The dep is in today's state, so its status is the truth and we can wait on it.
ENFORCEABLE = {KIND_LOCAL}
# The dep is deliberately not in play today. Nothing is wrong; still logged, so a
# skipped ordering constraint is never inferred from silence.
EXPECTED = {KIND_NOT_TODAY, KIND_NARROWED}
# The author asked for ordering this runner CANNOT provide. Always surfaced.
UNENFORCEABLE = {KIND_OTHER_MACHINE, KIND_OFF_SCHEDULER, KIND_UNKNOWN}

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


def _days(weekdays: Iterable[int]) -> str:
    return "/".join(_DAYS[d] for d in sorted(set(weekdays)) if 0 <= d <= 6) or "never"


def _raw(cfg, report_id: str) -> Optional[dict]:
    return cfg.raw.get("reports", {}).get(report_id)


def _machine_of(raw_report: dict) -> str:
    return raw_report.get("machine", DEFAULT_MACHINE)


def _weekdays_of(raw_report: dict) -> List[int]:
    return raw_report.get("cadence", {}).get("weekdays", _ALL_DAYS)


@dataclass(frozen=True)
class DepEdge:
    """One declared dependency, classified."""
    dependent: str
    dep: str
    relation: str      # depends_on | after
    kind: str
    detail: str        # human sentence — why it is (or isn't) in play

    @property
    def enforceable(self) -> bool:
        return self.kind in ENFORCEABLE

    @property
    def expected(self) -> bool:
        return self.kind in EXPECTED

    @property
    def unenforceable(self) -> bool:
        return self.kind in UNENFORCEABLE

    @property
    def blocks(self) -> bool:
        """A HARD `depends_on` we cannot verify must not be run straight through.

        `depends_on` means "do not run until that one has run" — running anyway
        publishes output built on inputs that may not exist yet (a board email
        off an unfilled board). Blocking is visible: the report stays PENDING
        with this dep named in `waiting_on`, the noon backstop retires it
        MISSED_NOT_READY, and it lands in the summary + corrections sweep.

        `after` is SOFT by design ("wait your turn, but never get stranded"), so
        an unenforceable `after` runs — loudly — rather than blocking.
        """
        return self.relation == DEPENDS_ON and self.unenforceable

    def describe(self) -> str:
        return f"{self.relation} {self.dep} — {self.detail}"


def classify(cfg, dependent: str, dep: str, relation: str, *,
             seeded: Set[str], date: dt.date, machine: str) -> DepEdge:
    """Classify ONE declared dependency.

    `seeded` is the set of report_ids in today's day-state (what the old
    `d in ds.reports` test looked at). Everything not in it gets an explicit
    reason instead of being dropped.
    """
    def edge(kind: str, detail: str) -> DepEdge:
        return DepEdge(dependent=dependent, dep=dep, relation=relation,
                       kind=kind, detail=detail)

    if dep in seeded:
        return edge(KIND_LOCAL, "scheduled on this runner today")

    raw = _raw(cfg, dep)
    if raw is None:
        return edge(KIND_UNKNOWN,
                    "no such report in schedule_config.json (typo, or the "
                    "report was removed and this reference was left behind)")

    if not raw.get("on_scheduler", False):
        return edge(KIND_OFF_SCHEDULER,
                    "on_scheduler:false — the morning batch never runs it, so "
                    "this dependency can never be satisfied by a batch run")

    dep_machine = _machine_of(raw)
    if dep_machine != machine:
        # THE BUG THIS MODULE EXISTS FOR. Day state is per machine
        # (output/day_state/<date>.json is local), so this runner has no way to
        # see whether the other runner's report has run.
        return edge(KIND_OTHER_MACHINE,
                    f"assigned to {dep_machine}, this runner is {machine} — "
                    "day state is per machine, so its status is not visible here")

    wd = _weekdays_of(raw)
    if date.weekday() not in wd:
        return edge(KIND_NOT_TODAY,
                    f"not scheduled today ({_DAYS[date.weekday()]}); it runs "
                    f"{_days(wd)}")

    # Ours, on the scheduler, scheduled today — but absent from today's state:
    # this run was narrowed with --only.
    return edge(KIND_NARROWED,
                "excluded from this run (--only), so it is not in today's state")


def classify_all(cfg, report, *, seeded: Set[str], date: dt.date,
                 machine: str) -> List[DepEdge]:
    """Classify every `depends_on` + `after` edge declared by `report`."""
    out: List[DepEdge] = []
    for relation, declared in ((DEPENDS_ON, report.depends_on), (AFTER, report.after)):
        for dep in declared:
            out.append(classify(cfg, report.report_id, dep, relation,
                                seeded=seeded, date=date, machine=machine))
    return out


# ---- whole-graph validation (startup) ---------------------------------------

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    dependent: str
    dep: str
    relation: str
    severity: str          # error | warning
    message: str
    dependent_machine: str = DEFAULT_MACHINE


def _cycles(edges: Dict[str, Set[str]]) -> List[List[str]]:
    """Every simple cycle reachable in the dependency graph (depends_on + after
    both deadlock: each side waits for the other to reach a state it can only
    reach after us). registry.run_order's depth() silently returns 0 on a cycle,
    so nothing else in the system would ever mention one."""
    found: List[List[str]] = []
    seen_keys: Set[str] = set()

    def walk(node: str, path: List[str], on_path: Set[str]) -> None:
        for nxt in sorted(edges.get(node, ())):
            if nxt in on_path:
                cycle = path[path.index(nxt):] + [nxt]
                if len(set(cycle)) == 1:
                    continue   # self-loop — already reported on its own
                key = "|".join(sorted(set(cycle)))
                if key not in seen_keys:
                    seen_keys.add(key)
                    found.append(cycle)
                continue
            walk(nxt, path + [nxt], on_path | {nxt})

    for start in sorted(edges):
        walk(start, [start], {start})
    return found


def validate(cfg) -> List[Finding]:
    """Check the WHOLE depends_on/after graph — every report, every machine,
    date-independent. Run once at startup so a dependency that can never be
    honored is announced before the batch begins, not discovered (or not) from
    one report's gate hours later.

    Returns findings; the caller logs them and alerts on the errors.
    """
    reports = cfg.raw.get("reports", {})
    findings: List[Finding] = []
    graph: Dict[str, Set[str]] = {}

    for rid, raw in reports.items():
        my_machine = _machine_of(raw)
        my_days = set(_weekdays_of(raw))
        my_scheduled = bool(raw.get("on_scheduler", False))
        for relation in RELATIONS:
            for dep in raw.get(relation, []) or []:
                graph.setdefault(rid, set()).add(dep)
                hard = relation == DEPENDS_ON

                if dep == rid:
                    findings.append(Finding(
                        rid, dep, relation, ERROR,
                        f"{rid}: {relation} lists ITSELF — it can never run.",
                        my_machine))
                    continue

                dep_raw = reports.get(dep)
                if dep_raw is None:
                    findings.append(Finding(
                        rid, dep, relation, ERROR,
                        f"{rid}: {relation} '{dep}' — no such report in "
                        f"schedule_config.json.", my_machine))
                    continue

                dep_machine = _machine_of(dep_raw)
                if dep_machine != my_machine:
                    findings.append(Finding(
                        rid, dep, relation, ERROR if hard else WARNING,
                        f"{rid} ({my_machine}): {relation} '{dep}' runs on "
                        f"{dep_machine}. Day state is per machine, so "
                        f"{my_machine} cannot see it."
                        + (f" {rid} will BLOCK rather than run out of order — "
                           f"put both on one runner, or make this an `after`."
                           if hard else
                           f" The ordering is NOT enforced; {rid} runs whenever "
                           f"it is ready."),
                        my_machine))
                    continue

                if not dep_raw.get("on_scheduler", False):
                    findings.append(Finding(
                        rid, dep, relation, ERROR if (hard and my_scheduled) else WARNING,
                        f"{rid}: {relation} '{dep}' is on_scheduler:false — the "
                        f"batch never runs it, so this can never be satisfied.",
                        my_machine))
                    continue

                if not my_scheduled:
                    continue   # dependent isn't in the batch either; cadence moot

                gaps = sorted(my_days - set(_weekdays_of(dep_raw)))
                if gaps and hard:
                    sev = ERROR if len(gaps) == len(my_days) else WARNING
                    findings.append(Finding(
                        rid, dep, relation, sev,
                        f"{rid}: {relation} '{dep}' does not run on "
                        f"{_days(gaps)}, but {rid} does — on those days the "
                        f"dependency is not in play.", my_machine))

    for cycle in _cycles(graph):
        head = cycle[0]
        findings.append(Finding(
            head, cycle[1] if len(cycle) > 1 else head, DEPENDS_ON, ERROR,
            "dependency cycle — these wait on each other forever: "
            + " → ".join(cycle),
            _machine_of(reports.get(head, {}))))

    return findings
