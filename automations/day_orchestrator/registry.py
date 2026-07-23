"""Registry — load schedule_config.json and resolve which reports run today,
in what order (priority tier + freshness escalation + dependencies).

Pure config logic, no I/O beyond reading the JSON. Easy to unit-test.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_PATH = Path(__file__).resolve().parent / "schedule_config.json"

_PRIORITY_RANK = {"P1": 0, "P2": 1, "P3": 2}

# Which runner am I? A gitignored `.machine-profile` marker at the repo root
# names the profile ("Lucy 1" / "Lucy 2") — the SAME marker mini_control uses.
# Absent → "Lucy 1" (the original mini). The orchestrator runs only reports
# assigned to its own machine, so a second runner never double-posts.
REPO_ROOT = Path(__file__).resolve().parents[2]
_MACHINE_MARKER = REPO_ROOT / ".machine-profile"
DEFAULT_MACHINE = "Lucy 1"


def this_machine() -> str:
    try:
        v = _MACHINE_MARKER.read_text().strip()
        if v:
            return v
    except Exception:
        pass
    return DEFAULT_MACHINE


@dataclass
class Report:
    report_id: str
    display_name: str
    source_type: str                 # tableau | appstream | api | upload
    data_sources: List[str]
    command: List[str]               # python -m module
    base_args: List[str]
    weekdays: List[int]              # Python weekday() Mon=0..Sun=6
    not_before: Optional[str]        # "HH:MM" CST or None
    priority: str                    # P1|P2|P3
    freshness_target: Optional[str]  # e.g. "monday_am"
    depends_on: List[str]
    verify: dict
    timeout_minutes: int = 45
    idempotency: dict = field(default_factory=dict)
    machine: str = DEFAULT_MACHINE   # which runner (Lucy 1 / Lucy 2) owns this
    order: Optional[int] = None      # explicit run-order (Megan's custom sequence);
                                     # None = fall to the source-type flow ordering
    after: List[str] = field(default_factory=list)
    # SOFT ordering: run only AFTER these reports reach a TERMINAL state (DONE /
    # INCOMPLETE / FAILED / MISSED — any outcome). Unlike depends_on, a FAILED
    # `after` dep does NOT block us — it just means "wait your turn behind it, but
    # never get stranded if it glitches" (daily_rep_breakdown after org_sales_board).
    scoped_rerun_cmd: Optional[str] = None
    # SURGICAL re-run prefix for a report whose INCOMPLETE misses are named UNITS
    # (owners / ICDs) rather than the whole report — e.g. "lucy focus_owner". When
    # set, a problem alert re-run targets JUST the missing units:
    # `<scoped_rerun_cmd> "Unit A" "Unit B"` (built from the manifest's failed[]
    # list). Unset = the alert falls back to manifest retry_args, then a whole
    # `lucy rerun`. Megan 2026-07-23: don't re-run the whole report for a few
    # missing owners.


@dataclass
class Config:
    settings: dict
    sources: Dict[str, dict]
    reports: Dict[str, Report]
    raw: dict


def _build_report(rid: str, r: dict) -> Report:
    cad = r.get("cadence", {})
    return Report(
        report_id=rid,
        display_name=r.get("display_name", rid),
        source_type=r.get("source_type", "tableau"),
        data_sources=r.get("data_sources", []),
        command=r.get("command", []),
        base_args=r.get("base_args", []),
        weekdays=cad.get("weekdays", [0, 1, 2, 3, 4, 5, 6]),
        not_before=cad.get("not_before"),
        priority=r.get("priority", "P2"),
        freshness_target=r.get("freshness_target"),
        depends_on=r.get("depends_on", []),
        after=r.get("after", []),
        verify=r.get("verify", {}),
        timeout_minutes=int(r.get("timeout_minutes", 45)),
        idempotency=r.get("idempotency", {}),
        machine=r.get("machine", DEFAULT_MACHINE),
        order=r.get("order"),
        scoped_rerun_cmd=r.get("scoped_rerun_cmd"),
    )


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = json.loads(Path(path).read_text())
    reports: Dict[str, Report] = {}
    for rid, r in raw.get("reports", {}).items():
        if not r.get("on_scheduler", False):
            continue
        reports[rid] = _build_report(rid, r)
    return Config(
        settings=raw.get("settings", {}),
        sources=raw.get("sources", {}),
        reports=reports,
        raw=raw,
    )


def resolve_report(cfg: Config, report_id: str) -> Optional[Report]:
    """Return a Report for `report_id` whether or not it's on the scheduler.

    load_config intentionally drops on_scheduler:false reports (e.g. leaders_call,
    which runs from its own Mon 2:05pm LaunchAgent, not the morning batch) so they
    never enter the auto-run. But an EXPLICIT `lucy rerun <id>` should still be
    able to fire them — so fall back to building one from the raw config.
    """
    r = cfg.reports.get(report_id)
    if r:
        return r
    raw_r = cfg.raw.get("reports", {}).get(report_id)
    return _build_report(report_id, raw_r) if raw_r else None


def scheduled_today(cfg: Config, date: dt.date,
                    machine: Optional[str] = None) -> List[Report]:
    """Reports whose weekday matches `date`. If `machine` is given, keep only
    reports assigned to that runner (entries with no 'machine' key default to
    'Lucy 1'); machine=None returns all — the Hub display path uses that."""
    wd = date.weekday()
    out = [r for r in cfg.reports.values() if wd in r.weekdays]
    if machine is not None:
        out = [r for r in out if r.machine == machine]
    return out


# --- Run-order flow (optimizes TOTAL runtime, not any single report) ---
# Do the non-Tableau work FIRST (AppStream / ownerville-UI / email / API — their
# data is ready early in the morning) so Tableau, whose data updates SLOWEST,
# gets the most time to finish publishing before we read it. daily_rep_breakdown
# is pinned DEAD LAST (heaviest + flakiest scrape — don't let it block anything).
# New reports auto-map by source_type — no per-report config needed: anything
# that isn't source_type 'tableau' runs in the first wave. (Weekend-safe: this is
# source-type-based, never weekday-based, so an AppStream report scheduled on a
# weekend still runs in the first wave and is never blocked.)
_FLOW_LAST = {"daily_rep_breakdown"}   # always dead last, regardless of source

def flow_rank(report: Report) -> int:
    if report.report_id in _FLOW_LAST:
        return 2
    if report.source_type == "tableau":
        return 1            # Tableau reads last (slowest-updating data)
    return 0                # appstream / api / email / upload — run first


def effective_priority_rank(report: Report, date: dt.date) -> int:
    """Base priority, escalated when a freshness deadline is near.

    Example (Megan's): a P3 report with freshness_target 'monday_am' is
    escalated to top priority on Sunday/Monday so it's current by Monday AM
    even though it's deprioritized midweek.
    """
    base = _PRIORITY_RANK.get(report.priority, 1)
    ft = report.freshness_target
    if ft == "monday_am":
        # Sunday (6) and Monday (0) -> escalate to P1-equivalent.
        if date.weekday() in (6, 0):
            return _PRIORITY_RANK["P1"]
    return base


def run_order(reports: List[Report], date: dt.date) -> List[Report]:
    """Order a pass: effective priority first, then dependencies (a report whose
    deps aren't all DONE is simply skipped that pass by the loop, but we still
    sort dependents after their deps for tidy logs), then stable by id."""
    dep_depth: Dict[str, int] = {}

    def depth(r: Report, seen=None) -> int:
        seen = seen or set()
        if r.report_id in seen:
            return 0
        if not r.depends_on:
            return 0
        seen.add(r.report_id)
        by_id = {x.report_id: x for x in reports}
        return 1 + max((depth(by_id[d], seen) for d in r.depends_on if d in by_id),
                       default=0)

    for r in reports:
        dep_depth[r.report_id] = depth(r)

    # Explicit `order` (Megan's custom sequence) is the PRIMARY key: a report with
    # an order runs in that slot; reports without one fall to 10_000 and keep the
    # source-type flow ordering AFTER the numbered ones. (Readiness still gates each
    # report — a not-ready Tableau report waits + retries regardless of its slot.)
    ordered = sorted(
        reports,
        key=lambda r: (r.order if r.order is not None else 10_000,
                       flow_rank(r), effective_priority_rank(r, date),
                       dep_depth[r.report_id], r.report_id),
    )
    # Pull each dependent to sit IMMEDIATELY AFTER the last of its dependencies,
    # instead of dead-last in its whole flow/priority tier. So the Org Sales Board
    # *email* sends the instant the board fill finishes (Megan 2026-07-05: "send as
    # soon as the board is filled"), not after every other Tableau report in the
    # wave. Only reports that declare depends_on move; every other report keeps its
    # exact sorted position. Iterating `ordered` (sorted by dep_depth) guarantees a
    # dependency is placed before its dependents, so chains land in order too.
    ids = {r.report_id for r in reports}
    result: List[Report] = [r for r in ordered if not r.depends_on]
    for r in ordered:
        if not r.depends_on:
            continue
        deps = [d for d in r.depends_on if d in ids]
        placed = [i for i, x in enumerate(result) if x.report_id in deps]
        pos = max(placed) + 1 if placed else len(result)
        result.insert(pos, r)
    return result
