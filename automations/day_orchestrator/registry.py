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


@dataclass
class Config:
    settings: dict
    sources: Dict[str, dict]
    reports: Dict[str, Report]
    raw: dict


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = json.loads(Path(path).read_text())
    reports: Dict[str, Report] = {}
    for rid, r in raw.get("reports", {}).items():
        if not r.get("on_scheduler", False):
            continue
        cad = r.get("cadence", {})
        reports[rid] = Report(
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
            verify=r.get("verify", {}),
            timeout_minutes=int(r.get("timeout_minutes", 45)),
            idempotency=r.get("idempotency", {}),
        )
    return Config(
        settings=raw.get("settings", {}),
        sources=raw.get("sources", {}),
        reports=reports,
        raw=raw,
    )


def scheduled_today(cfg: Config, date: dt.date) -> List[Report]:
    """Reports whose weekday matches `date`."""
    wd = date.weekday()
    return [r for r in cfg.reports.values() if wd in r.weekdays]


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

    return sorted(
        reports,
        key=lambda r: (flow_rank(r), effective_priority_rank(r, date),
                       dep_depth[r.report_id], r.report_id),
    )
