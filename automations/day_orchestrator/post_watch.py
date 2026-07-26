"""Post-watch — verify SELF-SCHEDULED Slack posters actually posted, WITHOUT
running them.

Some reports post to Slack on their OWN LaunchAgents, not through the
orchestrator's run scheduler (box_order_log posts one thread/day at 7:00+8:30;
vantura_slack_sales fills the board off the channel at 5:00 + hourly). The
orchestrator must NOT run these — a second run would double-post — but it should
still notice when one of them silently didn't fire and alert, same as any report
it does run.

This module is VERIFY-ONLY. It never launches a command. Each watch target names
the evidence a successful run leaves on THIS machine (a dated done-marker the
wrapper touches only on a clean post) plus the deadline by which that evidence
must exist. The orchestrator seeds each target as a pseudo-report in the day
state; once the deadline passes with no evidence, the pseudo-report flips to
MISSED_NOT_READY and rides the EXISTING "didn't run" alert path — no new alert
wording or routing.

False-alarm guards (mirroring the rest of the orchestrator):
  • MACHINE-scoped: a target is only evaluated on the machine that owns it, so a
    runner that never sees the marker file can't false-alarm. Seeding itself is
    machine-gated, so an off-machine target is never even created.
  • WEEKDAY-scoped: a target not scheduled today is never seeded.
  • DEADLINE + grace: evidence is only required AFTER the last scheduled attempt
    could have finished — never before, so a slow-but-fine run isn't flagged.
  • A target that legitimately no-ops (nothing to post) must leave its done-marker
    ANYWAY on the "ran, nothing to post" path — same principle as an empty Zero
    Streak section: "ran and had nothing" is success, not a miss. The marker means
    "the run completed", not "N images posted".
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

# Pseudo-report ids carry this suffix so the day-state's "not scheduled today ->
# SKIPPED" sweep skips them and they never collide with a real report id.
WATCH_SUFFIX = "__watch"


@dataclass
class WatchTarget:
    report_id: str                 # the real report this watches (for the marker/name)
    display_name: str
    machine: str                   # only this runner evaluates it
    deadline: str                  # "HH:MM" local (CST on the minis)
    marker_glob: str               # repo-relative; "{date}" -> YYYY-MM-DD
    weekdays: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    note: str = ""                 # shown in the miss reason (what to check)
    rerun_hint: str = ""           # the REAL command to re-post (a LaunchAgent
                                   # wrapper, not `lucy rerun`), shown as Re-run

    @property
    def watch_id(self) -> str:
        return self.report_id + WATCH_SUFFIX


def rerun_hint_for(watch_id: str) -> Optional[str]:
    """The real re-post command for a `__watch` pseudo-report, so the alert's
    Re-run line names the LaunchAgent wrapper (these post OUTSIDE `lucy rerun`)."""
    for w in WATCH_TARGETS:
        if w.watch_id == watch_id:
            return w.rerun_hint or None
    return None


# --- the watch list (declarative; add a target here, nothing else changes) ----
# box_order_log: deploy/box_order_log.sh touches
#   output/logs/.box-order-log-posted-<date> ONLY after a clean --post (exit 0),
#   at 7:00 or (fallback) 8:30. Last real chance 8:30 -> require it by 8:45.
# vantura_slack_sales: deploy/vantura_slack_sales.sh touches
#   output/logs/.vantura-slack-sales-done-<date> on a clean fill (exit 0); the
#   critical pass is 5:00 (it feeds the 5:10 Sales Boards post), so require it by
#   6:15 — a no-show by then means the morning board ran on stale data.
WATCH_TARGETS: List[WatchTarget] = [
    WatchTarget(
        report_id="box_order_log",
        display_name="BOX Order Log (post watch)",
        machine="Lucy 2",
        deadline="08:45",
        marker_glob="output/logs/.box-order-log-posted-{date}",
        note="no BOX Order Log post to #alphalete-gp-sales detected by 8:45 "
             "(the 7:00 + 8:30 LaunchAgent passes both left no posted-marker)",
        rerun_hint="on Lucy 2: bash deploy/box_order_log.sh   (re-posts once)",
    ),
    WatchTarget(
        report_id="vantura_slack_sales",
        display_name="Vantura Slack Sales fill (post watch)",
        machine="Lucy 2",
        deadline="06:15",
        marker_glob="output/logs/.vantura-slack-sales-done-{date}",
        note="the 5:00 Vantura Slack-sales fill left no done-marker by 6:15 "
             "(the 5:10 Sales Boards post may have used stale counts)",
        rerun_hint="on Lucy 2: bash deploy/vantura_slack_sales.sh",
    ),
]


def targets_for(machine: str, target_date: dt.date) -> List[WatchTarget]:
    """Watch targets owned by `machine` and scheduled on `target_date`'s weekday.
    Both gates are applied here so an off-machine / off-day target is never even
    seeded — it can't false-alarm."""
    wd = target_date.weekday()
    return [w for w in WATCH_TARGETS
            if w.machine == machine and wd in w.weekdays]


def _marker_path(w: WatchTarget, target_date: dt.date) -> Path:
    return REPO_ROOT / w.marker_glob.format(date=target_date.isoformat())


def _parse_deadline(hhmm: str, target_date: dt.date) -> dt.datetime:
    h, m = hhmm.split(":")
    return dt.datetime.combine(target_date, dt.time(int(h), int(m)))


def evaluate(w: WatchTarget, target_date: dt.date, now: dt.datetime) -> str:
    """Current verdict for a watch target:
      'ok'      — the done-marker for today exists (the run posted / completed).
      'missed'  — no marker AND we're past the deadline (alert-worthy no-show).
      'pending' — no marker yet, but still before the deadline (leave it alone).
    Marker presence is the ONLY positive signal — its absence before the deadline
    is never a miss, so a slow run is never flagged early."""
    if _marker_path(w, target_date).exists():
        return "ok"
    if now >= _parse_deadline(w.deadline, target_date):
        return "missed"
    return "pending"
