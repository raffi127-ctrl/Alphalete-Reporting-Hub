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
    prior_day: bool = False        # True = the run happens LATE (e.g. 23:00), so
                                   # this morning we check YESTERDAY's marker. The
                                   # weekday gate + marker date both use run-day
                                   # (target_date - 1). Deadline is a morning time.
    wrapper: str = ""              # repo-relative wrapper that TOUCHES the marker
    agent: str = ""                # launchd label suffix (com.alphalete.<agent>)
                                   # that fires `wrapper`. Both are checked by
                                   # config_problem() so a retired agent reads as
                                   # MISCONFIGURED, never as a report failure.
    wrapper_text: str = ""         # what config_problem() greps for in `wrapper`
                                   # when the wrapper BUILDS the marker name from
                                   # a shell variable, so the literal marker_stem
                                   # never appears in the file. Default (empty) =
                                   # grep for marker_stem, the common case.

    @property
    def watch_id(self) -> str:
        return self.report_id + WATCH_SUFFIX

    @property
    def marker_stem(self) -> str:
        """The dateless part of the marker filename, e.g. '.box-order-log-posted-'
        — what the wrapper's `touch` line must contain."""
        return Path(self.marker_glob.replace("{date}", "")).name

    @property
    def wrapper_needle(self) -> str:
        """The string that must appear in `wrapper` for it to still be writing
        this marker (see wrapper_text)."""
        return self.wrapper_text or self.marker_stem


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
        report_id="slack_skool_email",
        display_name="Slack / Skool email (post watch)",
        machine="Lucy 1",
        deadline="08:25",
        marker_glob="output/logs/.slack-skool-email-sent-{date}",
        weekdays=[0],
        note="the 8:00 Slack/Skool email left no sent-marker by 8:25 -- this "
             "week's new starts may have walked in with no Slack, no Skool "
             "and no TeleMapper. Check whether this week's D2D OBCL tab was "
             "built: the run refuses a tab that isn't dated for today rather "
             "than emailing LAST week's cohort",
        rerun_hint="on Lucy 1: bash deploy/slack_skool_email.sh   "
                   "(sends once; refuses if it already went today)",
        wrapper="deploy/slack_skool_email.sh",
        agent="slack-skool-email",
    ),
    WatchTarget(
        report_id="box_order_log",
        display_name="BOX Order Log (post watch)",
        machine="Lucy 2",
        deadline="08:45",
        marker_glob="output/logs/.box-order-log-posted-{date}",
        note="no BOX Order Log post to #alphalete-gp-sales detected by 8:45 "
             "(the 7:00 + 8:30 LaunchAgent passes both left no posted-marker)",
        rerun_hint="on Lucy 2: bash deploy/box_order_log.sh   (re-posts once)",
        wrapper="deploy/box_order_log.sh",
        agent="box-order-log",
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
        wrapper="deploy/vantura_slack_sales.sh",
        agent="vantura-slack-sales",
    ),
    # NOTE (2026-07-30): att_churn, carlos_captainship_headcount and
    # carlos_captainship_bonus USED to be watched here (added 2026-07-27 as
    # standalone Lucy 2 LaunchAgents). All three were MIGRATED into the Lucy 2 4am
    # orchestrator flow on 2026-07-28 (on_scheduler true in schedule_config.json)
    # and their standalone agents were retired via the disable_*_agent handles — so
    # nothing touches their done-markers any more. The orchestrator RUNS them now,
    # which means its own missed/failed alerting already covers them; leaving the
    # watches in place made att_churn alert "no done-marker by 8:30" every single
    # day even on a clean 4am fill. RULE: a watch target belongs here ONLY while its
    # report is on_scheduler:false — the moment a report joins the 4am flow, delete
    # its watch.
    # Lucy 1 standalone posters. org-board / pnl are CONDITIONAL (exit 75 = held,
    # a no-post is legit) — their wrappers drop the marker whenever the agent FIRES
    # (exit 0 or 75), so a missing marker means launchd never ran it, never a held
    # day. stf runs 23:00 (outside the day window) → prior_day checks last night's
    # marker this morning. (2026-07-28)
    WatchTarget(
        report_id="org_board_slack",
        display_name="Org Board → Slack (post watch)",
        machine="Lucy 1",
        deadline="11:45",   # last retry pass is 11:25
        marker_glob="output/logs/.org-board-slack-ran-{date}",
        note="the org-board Slack agent left no ran-marker by 11:45 — its launchd "
             "entry may have stopped firing (none of the 07:15–11:25 passes ran). "
             "NB this catches a TOTAL no-show only: the marker is dropped on any "
             "fire, so an agent still running the OLD 08:30-first schedule (i.e. "
             "a plist change that was never re-installed on the mini) looks clean "
             "here — check the post's actual time in #top-leaders for that",
        rerun_hint="on Lucy 1: bash deploy/org_board_slack.sh",
        wrapper="deploy/org_board_slack.sh",
        agent="org-board-slack",
    ),
    WatchTarget(
        report_id="pnl_office",
        display_name="PNL for the Office (post watch)",
        machine="Lucy 1",
        deadline="13:15",   # Friday, last retry pass 12:55
        marker_glob="output/logs/.pnl-office-ran-{date}",
        weekdays=[4],       # Fridays only
        note="the Friday PNL agent left no ran-marker by 13:15 — its launchd entry "
             "may have stopped firing",
        rerun_hint="on Lucy 1: bash deploy/pnl_office_fri.sh",
        wrapper="deploy/pnl_office_fri.sh",
        agent="pnl-office-fri",
    ),
    # --- the scheduler mini (Alphaletes-Mac-mini.local) --------------------------
    # Its machine string is "Lucy 1", NOT "the mini". registry.this_machine() only
    # ever returns what `.machine-profile` says, defaulting to "Lucy 1" (the
    # original mini) — and that default IS this box: it polls the plain "Mini
    # Control" tab, which _control_tab_for() hands out only to "Lucy 1", and
    # `lucy rerun list_agents` there lists com.alphalete.box-order-log-owners,
    # stf-field-check-11pm and org-board-slack side by side (2026-08-17).
    # So machine="the mini" matched NO runner and stf_field_check has been
    # un-watched since the day it was added (2026-07-28) — the same class of
    # silence as the owner emails below, which had no target at all.
    WatchTarget(
        report_id="box_order_log_owners",
        display_name="BOX Order Log per-owner emails (post watch)",
        machine="Lucy 1",
        deadline="09:30",   # 8:30 pass = two org-wide pulls back to back
        marker_glob="output/logs/.box-order-log-owners-ran-{date}",
        note="the 8:30 per-owner BOX Order Log pass left no ran-marker by 9:30 — "
             "Abel and Roshan were not emailed and nothing else would have said "
             "so. The marker is dropped whenever the 8:30 pass FINISHES (sent, "
             "deferred or capped alike), so a no-show here means the pass never "
             "completed: launchd didn't fire it, or the 7:00 run was still alive "
             "and the wrapper's pgrep guard skipped the whole 8:30 pass. A capped "
             "/ blocked pull is NOT this — that path alerts on its own",
        rerun_hint="on the mini: bash deploy/box_order_log_owners.sh   "
                   "(emails each owner once; already-sent owners are skipped)",
        wrapper="deploy/box_order_log_owners.sh",
        # The wrapper builds the marker per owner from $KEY, so the literal stem
        # never appears in the file — grep for the touch line's fixed prefix.
        wrapper_text=".box-order-log-owners-ran-",
        agent="box-order-log-owners",
    ),
    WatchTarget(
        report_id="stf_field_check",
        display_name="STF Field Check (post watch)",
        machine="Lucy 1",   # ownerville is single-session → runs on the scheduler mini, not a Lucy box
        deadline="07:00",   # last night's 23:00 run should have left its marker
        marker_glob="output/logs/.stf-field-check-done-{date}",
        prior_day=True,     # runs 23:00 → check YESTERDAY's marker this morning
        note="last night's 23:00 STF Field Check left no done-marker — its launchd "
             "entry may have stopped firing",
        rerun_hint="on the mini: bash deploy/stf_field_check_11pm.sh",
        wrapper="deploy/stf_field_check_11pm.sh",
        agent="stf-field-check-11pm",
    ),
]


def _orchestrator_run_ids() -> set:
    """Report ids the orchestrator RUNS itself (on_scheduler true). Best-effort —
    a config it can't read must never silently disarm the watch, so a read failure
    returns an empty set (nothing is treated as migrated)."""
    import json
    try:
        cfg = json.loads((Path(__file__).resolve().parent / "schedule_config.json")
                         .read_text(encoding="utf-8"))
        return {rid for rid, r in (cfg.get("reports") or {}).items()
                if isinstance(r, dict) and r.get("on_scheduler")}
    except Exception:  # noqa: BLE001
        return set()


# --- misconfiguration guard (2026-07-30) -------------------------------------
# A watch only means something while SOMETHING still writes its done-marker. When
# att_churn moved into the Lucy 2 4am flow (2026-07-28) its standalone 7:15 agent
# was retired, so `.att-churn-done-<date>` stopped being written — and the watch
# dutifully reported "B2B Churn FAILED, no done-marker by 8:30" every single day
# while the 4am fill was completing perfectly. A stale watch must read as OUR
# wiring being broken, not as the report being broken.
#
# config_problem() answers "can this target still be satisfied at all today?" and
# is checked BEFORE the deadline. A target with a problem is never seeded, so it
# can never flip to MISSED_NOT_READY and never pages anyone; the orchestrator logs
# it as MISCONFIGURED instead, which is a code fix, not a rerun.

def config_problem(w: WatchTarget) -> Optional[str]:
    """Why `w` can no longer be satisfied (None = the watch is sound).

    Checked in escalating order of certainty. Every check is fail-OPEN: anything
    it can't determine returns None (keep watching), so a filesystem hiccup can
    never silently delete real coverage."""
    # 1. The orchestrator now RUNS this report itself, which means its standalone
    #    wrapper was retired — the marker will never appear again. The 4am flow's
    #    own FAILED / MISSED-at-backstop alerting already covers the report.
    if w.report_id in _orchestrator_run_ids():
        return (f"{w.report_id} is on_scheduler:true — it moved into the 4am flow "
                "and its standalone agent was retired, so nothing writes "
                f"{w.marker_stem}<date> any more. The flow's own missed/failed "
                "alerting covers it; delete this watch target.")
    # 2. The wrapper that touches the marker is gone from the repo.
    if w.wrapper:
        wp = REPO_ROOT / w.wrapper
        if not wp.exists():
            return f"wrapper {w.wrapper} no longer exists — nothing writes {w.marker_stem}<date>"
        # 3. The wrapper survives but no longer touches THIS marker (renamed or
        #    the touch line was dropped in a refactor).
        try:
            if w.wrapper_needle not in wp.read_text(encoding="utf-8", errors="replace"):
                return (f"{w.wrapper} no longer writes {w.marker_stem}<date> — the "
                        "marker name changed or the touch was dropped")
        except Exception:  # noqa: BLE001 — unreadable file: keep watching
            pass
    # 4. The LaunchAgent that fires the wrapper was RETIRED on this machine.
    #    disable_agent.py moves the plist aside to <label>.plist.disabled*, so that
    #    stashed file is POSITIVE proof of retirement. A merely-absent plist is NOT
    #    proof (wrong machine, a hand-installed label, an agent dir we can't read),
    #    and treating absence as retirement would silently disarm every real watch —
    #    so only the stash counts. "Installed but never fired" stays the watch's job.
    if w.agent:
        try:
            stashed = sorted((Path.home() / "Library" / "LaunchAgents")
                             .glob(f"com.alphalete.{w.agent}.plist.disabled*"))
            if stashed:
                return (f"LaunchAgent com.alphalete.{w.agent} is RETIRED on this "
                        f"machine ({stashed[0].name}) — it can't write "
                        f"{w.marker_stem}<date>")
        except Exception:  # noqa: BLE001 — can't read LaunchAgents: keep watching
            pass
    return None


def misconfigured_for(machine: str, target_date: dt.date) -> List[tuple]:
    """[(target, reason)] for `machine`'s targets that are scheduled today but can
    no longer be satisfied. The orchestrator logs these as MISCONFIGURED — they are
    a wiring bug for us to fix, never a report failure to alert Megan about."""
    return [(w, config_problem(w)) for w in _scheduled_for(machine, target_date)
            if config_problem(w)]


def _scheduled_for(machine: str, target_date: dt.date) -> List[WatchTarget]:
    """Machine + weekday gates only (no health check) — the raw 'should this have
    run today' set that both targets_for() and misconfigured_for() start from."""
    return [w for w in WATCH_TARGETS
            if w.machine == machine and _run_date(w, target_date).weekday() in w.weekdays]


def targets_for(machine: str, target_date: dt.date) -> List[WatchTarget]:
    """Watch targets owned by `machine`, scheduled on `target_date`'s weekday, and
    still SOUND (see config_problem). All three gates are applied here so an
    off-machine / off-day / stale target is never even seeded — it can't
    false-alarm."""
    return [w for w in _scheduled_for(machine, target_date) if not config_problem(w)]


def _run_date(w: WatchTarget, target_date: dt.date) -> dt.date:
    """The date the run actually happened — yesterday for prior_day targets (a
    23:00 run checked the next morning), else today."""
    return target_date - dt.timedelta(days=1) if w.prior_day else target_date


def _marker_path(w: WatchTarget, target_date: dt.date) -> Path:
    return REPO_ROOT / w.marker_glob.format(date=_run_date(w, target_date).isoformat())


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
