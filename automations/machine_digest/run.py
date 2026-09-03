"""Daily 'what ran on a machine' summary email — Lucy 2's version of Lucy 1's
daily report summary.

Lucy 1's day_orchestrator emails a daily FINAL of its batch reports. Lucy 2's
headline work is STANDALONE launchd agents (Carlos's captainship reports, resume
pushing), which the orchestrator never sees — so it would stay silent on those
days. This reads the shared "Hub Activity" tab (where every run, batch AND
standalone, is logged via publish_done) and emails a summary.

It can summarize EITHER the machine it runs on (default: match its own hostname)
OR another machine by hostname (`--host`). That second mode is how Lucy 2's
summary is produced FROM Lucy 1 — the activity log is shared, so Lucy 1 can
report Lucy 2's day without touching Lucy 2 at all (robust even if Lucy 2 is
down or on a different branch). `--label` sets the name in the subject.

Quiet by design: nothing ran → no email (mirrors Lucy 1 on empty days).
Recipients + sender are the orchestrator's, so it lands exactly like Lucy 1's.

Usage:
  python -m automations.machine_digest.run [--dry-run] [--date YYYY-MM-DD]
      [--host <hostname substring>] [--label "Lucy 2"]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import socket
import sys

HUB_ACTIVITY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
HUB_ACTIVITY_TAB = "Hub Activity"

# Status → (icon, bucket). Unknown statuses pass through as-is / neutral.
_OK = {"success", "done", "ok", "complete", "completed"}
_BAD = {"failed", "error", "fail"}
_PARTIAL = {"partial", "incomplete"}


def _read_activity() -> list[dict]:
    from automations.recruiting_report import fill as _fill
    sh = _fill.open_by_key(HUB_ACTIVITY_SHEET_ID)
    ws = sh.worksheet(HUB_ACTIVITY_TAB)
    return ws.get_all_records()


def _stat(row: dict) -> str:
    """Lower-cased Status of an activity row (for _OK / _BAD membership tests)."""
    return str(row.get("Status") or "").strip().lower()


def _classify(status: str) -> tuple[str, str]:
    s = (status or "").strip().lower()
    if s in _OK:
        return "✅", "ok"
    if s in _BAD:
        return "❌", "failed"
    if s in _PARTIAL:
        return "⚠️", "partial"
    if s in ("started", "running"):
        return "…", "running"
    return "•", "other"


def _time_only(iso: str) -> str:
    # "2026-07-15T18:50:06" → "6:50 PM" (Unix %-I is fine — mini only).
    try:
        t = dt.datetime.fromisoformat(iso)
        return t.strftime("%-I:%M %p")
    except Exception:
        return ""


def _machine_matches(row_machine: str, host: str, exact: bool) -> bool:
    """`host` may be a COMMA-SEPARATED list of hostname substrings — a runner can
    answer to more than one name over its life (Lucy 2 has logged runs as both
    Carloss-Mac-mini-2.attlocal.net and Mac.attlocal.net), and a summary that
    silently matches neither is worse than one that matches both."""
    m = (row_machine or "").strip()
    if exact:
        return m == host
    return any(h.strip().lower() in m.lower()
               for h in host.split(",") if h.strip())


def _collect(rows: list[dict], host: str, day: str, exact: bool = True) -> list[dict]:
    """One entry per REPORT for the target machine + day (latest status + run
    count), newest-run first. Mirrors Lucy 1's summary: a report that retried 8×
    is one line showing its final outcome, not eight. `exact=False` matches the
    hostname as a substring (for --host, tolerant of .local vs .attlocal.net).
    `host=None`/'' scans EVERY machine (the intraday both-machine error watcher)."""
    all_machines = not (host and str(host).strip())
    # 1) Reduce each run's start+end pair (same RunID) to the end row.
    by_run = {}
    for r in rows:
        if not all_machines and not _machine_matches(str(r.get("Machine") or ""), host, exact):
            continue
        started = str(r.get("Started At") or "").strip()
        if started[:10] != day:
            continue
        run_id = str(r.get("RunID") or "").strip() or f"{r.get('Report ID')}-{started}"
        prev = by_run.get(run_id)
        if prev is None or (r.get("Ended At") and not prev.get("Ended At")):
            by_run[run_id] = r
    # 2) Group runs by report; keep the latest run's status + a count.
    by_report: dict[str, list[dict]] = {}
    for r in by_run.values():
        key = str(r.get("Report ID") or r.get("Report Name") or "?").strip()
        by_report.setdefault(key, []).append(r)
    reports = []
    for runs in by_report.values():
        runs.sort(key=lambda r: str(r.get("Started At") or ""))
        last = runs[-1]
        # A same-day SUCCESS is the report's real outcome. A later FAILED run for
        # the same report_id is almost always a manual rerun / debug run / cold-
        # session retry (e.g. 2026-07-21 vantura_churn: 7:13 scheduled success +
        # a 7:37 hand-queued rerun that crashed on a cold Tableau session). Taking
        # only the latest run flipped the card to ❌ and buried the success. So
        # represent the report by its latest SUCCESSFUL run when one exists, and
        # just note how many other runs failed. Only when nothing succeeded do we
        # surface the failure as the headline.
        ok_runs = [r for r in runs if _stat(r) in _OK]
        rep = last if (_stat(last) in _OK or not ok_runs) else ok_runs[-1]
        failed_count = sum(1 for r in runs if _stat(r) in _BAD) if ok_runs else 0
        reports.append({
            "name": str(rep.get("Report Name") or rep.get("Report ID") or "?"),
            "report_id": str(rep.get("Report ID") or "").strip(),
            "status": str(rep.get("Status") or "").strip(),
            "count": len(runs),
            "failed_count": failed_count,
            "started": str(rep.get("Started At") or ""),
            "ended": str(rep.get("Ended At") or ""),
            "user": str(rep.get("User") or "").strip(),
            "machine": str(rep.get("Machine") or "").strip(),
        })
    reports.sort(key=lambda x: x["started"], reverse=True)
    return reports


def _render(reports: list[dict], machine_label: str, day_human: str) -> tuple[str, str, str]:
    rows = []
    ok = bad = 0
    for r in reports:
        icon, bucket = _classify(r["status"])
        ok += bucket == "ok"
        bad += bucket in ("failed", "partial")
        when = _time_only(r["started"]) + (f"–{_time_only(r['ended'])}" if r["ended"] else "")
        status = r["status"] or "—"
        if r["count"] > 1:
            fc = r.get("failed_count", 0)
            status += f"  (ran {r['count']}×, {fc} failed)" if fc else f"  (ran {r['count']}×)"
        rows.append((icon, r["name"], status, when, r["user"]))

    tally = f"{len(reports)} report{'s' if len(reports) != 1 else ''} · {ok} ok" + (
        f" · {bad} need a look" if bad else "")
    subject = f"{machine_label}What ran {day_human} — {tally}"

    trs = ""
    for icon, name, status, when, user in rows:
        trs += (f'<tr><td style="padding:3px 10px 3px 0">{icon}</td>'
                f'<td style="padding:3px 14px 3px 0"><b>{html.escape(name)}</b></td>'
                f'<td style="padding:3px 14px 3px 0;color:#555">{html.escape(status)}</td>'
                f'<td style="padding:3px 14px 3px 0;color:#555">{html.escape(when)}</td>'
                f'<td style="padding:3px 0;color:#888">{html.escape(user)}</td></tr>')
    h = ('<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#111;max-width:820px">'
         f'<h2 style="margin:0 0 2px">🗓️ What ran {html.escape(day_human)}</h2>'
         f'<p style="margin:0 0 12px;color:#666">{html.escape(machine_label.strip() or "Lucy 1")} · {html.escape(tally)}</p>'
         f'<table style="border-collapse:collapse;font-size:14px">{trs}</table></div>')
    t = [f"What ran {day_human} — {tally}", ""]
    for icon, name, status, when, user in rows:
        t.append(f"{icon} {name} — {status}" + (f" · {when}" if when else "")
                 + (f" · {user}" if user else ""))
    return subject, h, "\n".join(t)


import json as _json
from pathlib import Path as _Path

_STATE_DIR = _Path(__file__).resolve().parents[2] / "output" / "state"


def _watch_state_path(day: str) -> _Path:
    return _STATE_DIR / f"error_watch_{day}.json"


def _load_alerted(day: str) -> set:
    """report_ids already alerted today (so a 30-min sweep posts each ONCE)."""
    try:
        return set(_json.loads(_watch_state_path(day).read_text()))
    except Exception:
        return set()


def _save_alerted(day: str, ids: set) -> None:
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _watch_state_path(day).write_text(_json.dumps(sorted(ids)))
    except Exception as e:  # noqa: BLE001 — losing dedup state is better than crashing
        print(f"[watch] could not save dedup state: {e}", flush=True)


def _orchestrator_ids(cfg, target_date) -> set:
    """The set of Hub Activity report-ids the day orchestrator TRACKS AND ALERTS
    today — so the watcher skips them (no double-post). That's a registry report
    the orchestrator actually SCHEDULES today, i.e. on_scheduler + today is in its
    weekdays. Reports with weekdays [] (weather, new-start-followup: on_scheduler
    but run on their OWN launchd, never the loop) are NOT excluded — the watcher is
    their only alert. Matched by BOTH the registry key AND its hyphenated Hub CARD
    id (the Activity log uses the card id, e.g. daily-rep-breakdown), via the
    canonical hub_publish map. `standalone_watch: true` force-includes a report;
    `standalone_watch: false` force-EXCLUDES it — that's how a report PAUSED on
    purpose (on_scheduler flipped false, e.g. org_sales_board_email handed to Eve
    2026-07-28) stops alerting. Without it a paused report is invisible to
    load_config, so it falls through to the historical-expected baseline and
    posts "didn't run today" every day for a week — a deliberate pause read as a
    breakage."""
    try:
        from automations.day_orchestrator.hub_publish import _HUB_CARD
    except Exception:  # noqa: BLE001
        _HUB_CARD = {}
    try:
        from automations.day_orchestrator.hub_coverage import CURATED_ALIAS, slug
    except Exception:  # noqa: BLE001
        CURATED_ALIAS, slug = {}, lambda r: r.replace("_", "-").strip("-")
    wd = target_date.weekday()
    ids = set()
    raw = cfg.raw.get("reports", {})

    def _add(rid):
        ids.add(rid)
        # Every id this report could appear under in Hub Activity. _HUB_CARD only
        # covers the HAND-mapped reports; most orchestrator reports get their card
        # from hub_coverage's slug rule (underscores -> hyphens) or CURATED_ALIAS,
        # and those were missing here — so the Activity row (written under the CARD
        # id) never matched the skip set. sci_campaigns then got alerted as a
        # STANDALONE report on 2026-07-31, with a paste-block insisting it "runs on
        # its OWN agent, not the day-orchestrator loop" when it does exactly the
        # opposite (Eve 2026-07-31).
        for cand in (_HUB_CARD.get(rid), CURATED_ALIAS.get(rid), slug(rid)):
            if cand:
                ids.add(cand)

    # Paused-on-purpose reports: read from RAW, since load_config drops every
    # on_scheduler:false entry before cfg.reports is built.
    for rid, rep_raw in raw.items():
        if rep_raw.get("standalone_watch") is False:
            _add(rid)
    for rid, rep in cfg.reports.items():
        if raw.get(rid, {}).get("standalone_watch"):
            continue
        if wd not in (getattr(rep, "weekdays", None) or []):
            continue   # not orchestrator-scheduled today → the watcher must cover it
        _add(rid)
    return ids


# Modules that are ONLY ever run by a human asking for them. Matched on the
# MODULE, never on the id, because an id is a name someone chose and a module is
# what actually runs.
#
# The installers/disablers came first (see the docstring below). READ-ONLY
# DIAGNOSTICS joined them 2026-08-24: `list_agents` ("List loaded LaunchAgents
# (read-only)") opened a "didn't run today on the mini · usually starts ~8:00"
# thread, because a week of hand-running it while debugging — Eve's, mine, and
# other sessions' — is indistinguishable in the Activity log from an 8am daily
# report. It has no cadence, no machine and no LaunchAgent; nothing was ever
# going to run it. Exactly the `disable_oat_processing_agent` shape.
#
# NOTE the tempting rule that does NOT work: "on_scheduler false + no weekdays
# + no machine" describes list_agents perfectly and ALSO describes 40 real
# reports — stf_field_check, org_board_slack, sara_down, pnl_office among them —
# which run from their own LaunchAgents. Exempting on that shape would have gone
# silent on all of them. Measured against the live config before writing this.
_ONESHOT_UTILITY_MODULES = (
    "day_orchestrator.install_agent",
    "day_orchestrator.disable_agent",
    "day_orchestrator.list_agents",          # read-only agent lister
    "day_orchestrator.imessage_thread_probe",  # read-only iMessage probe
)


def _oneshot_utility_ids(cfg) -> set:
    """Registry ids that are ONE-SHOT UTILITIES, not reports: the LaunchAgent
    installers / disablers (`day_orchestrator.install_agent` / `.disable_agent`).
    They only ever run when a human asks for them, so they must never enter the
    historical-expected baseline — but the baseline is derived from the Activity
    log alone, and a utility run by hand on two same-weekdays looks exactly like a
    daily 7am report. That's how `disable_oat_processing_agent` (run 2026-08-05
    07:30 to pause OAT after it folded into Applicant Push) started posting
    "Disable/Pause: OAT Processing LaunchAgent — did not run today" every
    Wednesday (Eve 2026-08-12). Matched by the same id/card-alias fan-out as
    _orchestrator_ids, since Activity rows are written under the CARD id."""
    try:
        from automations.day_orchestrator.hub_publish import _HUB_CARD
    except Exception:  # noqa: BLE001
        _HUB_CARD = {}
    try:
        from automations.day_orchestrator.hub_coverage import CURATED_ALIAS, slug
    except Exception:  # noqa: BLE001
        CURATED_ALIAS, slug = {}, lambda r: r.replace("_", "-").strip("-")
    ids = set()
    for rid, rep_raw in (cfg.raw.get("reports", {}) or {}).items():
        cmd = " ".join(str(c) for c in (rep_raw.get("command") or []))
        if not cmd.endswith(_ONESHOT_UTILITY_MODULES):
            continue
        ids.add(rid)
        for cand in (_HUB_CARD.get(rid), CURATED_ALIAS.get(rid), slug(rid)):
            if cand:
                ids.add(cand)
    return ids


def _handrun_only_ids(cfg) -> set:
    """Registry ids DECLARED hand-run-only (`hand_run_only: true`): a handle that
    exists purely so a person can re-run one step of a bigger report by hand, via
    `lucy rerun <id>`. Nothing on any clock ever fires them, so "didn't run today"
    is meaningless for them — but the baseline is derived from the Activity log
    alone, and a sub-step someone re-ran on two same-weekdays looks exactly like a
    weekly report. That's how `alphalete_org_b2b` posted "didn't run today on
    Lucy 2 · usually starts ~16:00" on 2026-08-24, off two Monday hand-reruns
    (8/10, 8/17), when nothing was ever going to run it (Megan 2026-08-25).

    WHY A DECLARATION AND NOT A GUESS (measured 2026-08-25, do not re-derive):

      * The Activity log's User column cannot tell the two apart. `lucy rerun`
        publishes through hub_publish.publish_running, which stamps "Mini (auto)"
        — the SAME marker a 4am scheduled run gets. Of 876 Activity rows provably
        produced by a human-queued rerun, 867 read "Mini (auto)".
      * Subtracting hand-queued reruns (Mini Control queue) blinds real reports:
        day-level matching dropped att-churn and owner-showdown on 6 of 21 days,
        office-metrics and org-sales-board-slack on 5. The two logs' clocks also
        disagree by ~2h across machines, so a time window can't be trusted either.
      * `on_scheduler:true + cadence.weekdays []` matches 67 entries including
        office-metrics, lucy-weather-forecast, texas_de_brazil and
        owners-metrics-churn — all real, all running daily from their own
        LaunchAgents. It is rejected approach #2 in a different shape.
      * Inferring "no LaunchAgent runs this module" from deploy/*.sh gets
        texas_de_brazil wrong: its launcher invokes `$MODULE` through a shell
        variable, so a static parser cannot see it — and it fails SILENTLY, in
        the direction that stops watching a live report.

    So the schedule_config declares it, the same way `standalone_weekdays` and
    `standalone_monthdays` pin the two other schedules the watcher can't read.

    DELIBERATELY NARROW, two ways:

      * The flag is honoured ONLY when `cadence.weekdays` is empty. A stray
        `hand_run_only` on something the orchestrator really does fire is
        ignored, so the flag can never silence a scheduled report.
      * The caller applies this to the "didn't run" check ONLY. A hand-run that
        FAILS, runs PARTIAL or hangs still alerts exactly as it does today —
        being un-scheduled is not being un-watched.

    NOT every sub-step handle qualifies. `alphalete_org_je` looks identical to
    its _b2b / _box / _retail siblings in the config, but
    com.alphalete.je-opt-monday-catchup.plist really does run it every Monday —
    so it must NOT carry the flag. Check for a plist in deploy/ before adding one.
    Matched by the same id/card-alias fan-out as _orchestrator_ids, since
    Activity rows are written under the CARD id."""
    try:
        from automations.day_orchestrator.hub_publish import _HUB_CARD
    except Exception:  # noqa: BLE001
        _HUB_CARD = {}
    try:
        from automations.day_orchestrator.hub_coverage import CURATED_ALIAS, slug
    except Exception:  # noqa: BLE001
        CURATED_ALIAS, slug = {}, lambda r: r.replace("_", "-").strip("-")
    ids = set()
    for rid, rep_raw in (cfg.raw.get("reports", {}) or {}).items():
        if not rep_raw.get("hand_run_only"):
            continue
        wdays = ((rep_raw.get("cadence") or {}).get("weekdays"))
        if not (isinstance(wdays, list) and not wdays):
            continue   # the orchestrator CAN fire it → the flag doesn't apply
        ids.add(rid)
        for cand in (_HUB_CARD.get(rid), CURATED_ALIAS.get(rid), slug(rid)):
            if cand:
                ids.add(cand)
    return ids


def _event_logged_ids(cfg) -> set:
    """Registry ids DECLARED `logs_on_event_only: true` — a report whose clock ticks
    constantly but which only writes an Activity row when it actually DID something.

    WHY (Megan 2026-09-01). `sara_down` polls #saraplus-issues every 5 minutes,
    24/7, from com.alphalete.sara-down (StartInterval 300), and calls publish_done
    ONLY on a real escalation — deliberately, so the log records issues escalated
    instead of 288 heartbeats a day. But _historical_expected reads that same log as
    the cadence: escalations landed on Tue 8/11 and Tue 8/25 at 17:42, which is two
    of the last three Tuesdays WITH the recency gate satisfied, so the watcher
    concluded "Tuesday ~17:00 report" and posted "didn't run today on the mini ·
    usually starts ~17:00" on Tue 9/1 — while the poller had in fact run every 5
    minutes all day, exit 0, last tick 20:45 (verified in the mini's own
    output/logs/sara-down-2026-09-01.log). Nobody had posted a Sara+ screenshot,
    which is the card's documented healthy state: "a quiet card is the normal,
    healthy state".

    This is the same class of bug as `standalone_weekdays` and `hand_run_only` fix —
    the log is not the schedule — but a DIFFERENT shape, and neither existing flag
    covers it: the report is neither weekday-pinned (it runs today, and every day)
    nor hand-run-only (a real clock fires it constantly). What is untrue for it is
    narrower: an ABSENT row is not evidence of a miss, because a present row was
    never evidence of a tick.

    WHY A DECLARATION AND NOT A GUESS. Nothing in the Activity log distinguishes
    "logged once per event" from "logged once per run" — an event-logged report with
    a busy week looks exactly like a healthy daily one, and a genuinely dead daily
    report looks exactly like a quiet event-logged one. Row COUNT can't separate
    them either: sara_down wrote 8 rows in six weeks, but so would a weekly report.
    Only the module knows, so the module's registry entry says so.

    DELIBERATELY NARROW, the same two ways as _handrun_only_ids:

      * Honoured ONLY when `cadence.weekdays` is empty, so the flag can never
        silence something the 4am orchestrator really does fire.
      * The caller applies it to the "didn't run" check ONLY (it goes in `offday`,
        not `skip`). A tick that FAILS, runs PARTIAL or hangs still alerts exactly
        as it does today — logging on events is not a reason to stop watching for
        errors, and sara_down's 8/11 failures are precisely what must keep coming
        through.

    The cost of the flag is real and worth stating: a report carrying it can go
    silently dead and this watcher will not say so. That is acceptable only for a
    module whose own failures alert loudly through the ERRORED path above, which is
    why it is opt-in per report and not inferred. Matched by the same
    id/card-alias fan-out as _orchestrator_ids, since Activity rows are written
    under the CARD id."""
    try:
        from automations.day_orchestrator.hub_publish import _HUB_CARD
    except Exception:  # noqa: BLE001
        _HUB_CARD = {}
    try:
        from automations.day_orchestrator.hub_coverage import CURATED_ALIAS, slug
    except Exception:  # noqa: BLE001
        CURATED_ALIAS, slug = {}, lambda r: r.replace("_", "-").strip("-")
    ids = set()
    for rid, rep_raw in (cfg.raw.get("reports", {}) or {}).items():
        if not rep_raw.get("logs_on_event_only"):
            continue
        wdays = ((rep_raw.get("cadence") or {}).get("weekdays"))
        if not (isinstance(wdays, list) and not wdays):
            continue   # the orchestrator CAN fire it → the flag doesn't apply
        ids.add(rid)
        for cand in (_HUB_CARD.get(rid), CURATED_ALIAS.get(rid), slug(rid)):
            if cand:
                ids.add(cand)
    return ids

def _retired_ids() -> set:
    """Ids hub_coverage._RETIRED declares dead. A name in that set is a promise
    the report DOES NOT RUN, so it must not alert either.

    Goes in `skip`, not `offday`: off-day only suppresses the "didn't run" GUESS
    and still reports a real FAILED, which is right for a live report on its day
    off and wrong for a retired one. att_cancels, 2026-08-30 — retired at 13:5x
    because its Tableau view was deleted, and at 14:06 this watcher opened
    "didn't run clean on Lucy 2" off the morning's genuine 04:10 failure. The
    failure was real; the report is gone. Without this it would reopen every
    time the Activity log still holds a failed row for a retired id.

    Best-effort: if hub_coverage can't be read, skip nothing and behave exactly
    as before — a retired report alerting is far better than a live one going
    quiet.
    """
    try:
        from automations.day_orchestrator import hub_coverage
        return set(hub_coverage._RETIRED)
    except Exception:  # noqa: BLE001
        return set()


def _offday_standalone_ids(cfg, target_date) -> set:
    """Registry ids of STANDALONE (LaunchAgent) reports that are NOT supposed to run
    on `target_date`, per an explicit `standalone_weekdays` list (Python weekday():
    Mon=0 … Sun=6) and/or `standalone_monthdays` list (calendar day-of-month 1–31)
    in schedule_config.

    on_scheduler:false reports have no usable `cadence.weekdays` — their real
    schedule lives in a plist the watcher can't read — so the "didn't run today"
    baseline has to guess from the Activity log alone. That guess breaks on a
    WEEKDAY-PINNED report the moment it's hand-rerun on the same off-weekday a few
    times: vantura_payroll fires Wednesday 11:00 (com.alphalete.vantura-payroll-wed,
    Weekday 3), but manual Thursday reruns on 7/23, 7/30 and 8/6 taught
    _historical_expected that it's a Thursday 11:00 report, so it posted "Vantura
    Weekly Payroll (prep) — did not run today" every Thursday from 13:00 on, while
    the real Wednesday run had succeeded the day before (Eve 2026-08-13).

    Declaring `standalone_weekdays` pins the truth: on any other weekday the report
    is exempt from the "didn't run" check ONLY. It stays fully watched for FAILED /
    INCOMPLETE / STUCK on every day — an off-day hand-rerun that crashes (as
    vantura_payroll's did on 2026-08-06) must still alert. Undeclared reports keep
    the historical guess, so this changes nothing for anyone who doesn't opt in.

    `standalone_monthdays` is the same pin for a DAY-OF-MONTH schedule, which
    weekdays can't express: dd_gross_revenue fires the 1st & 15th at noon
    (com.alphalete.dd-gross-revenue, StartCalendarInterval Day 1/15), but in
    August 2026 the 1st and the 15th were BOTH Saturdays, so its two real runs
    taught _historical_expected it was a weekly Saturday-noon report and it
    posted "didn't run today" on Sat 8/22 while nothing was wrong (Megan
    2026-08-22). When both lists are declared, today must match BOTH to be a
    run day — same AND rule as launchd's Day+Weekday. Matched by the same
    id/card-alias fan-out as _orchestrator_ids, since Activity rows are written
    under the CARD id."""
    try:
        from automations.day_orchestrator.hub_publish import _HUB_CARD
    except Exception:  # noqa: BLE001
        _HUB_CARD = {}
    try:
        from automations.day_orchestrator.hub_coverage import CURATED_ALIAS, slug
    except Exception:  # noqa: BLE001
        CURATED_ALIAS, slug = {}, lambda r: r.replace("_", "-").strip("-")
    wd = target_date.weekday()
    ids = set()
    for rid, rep_raw in (cfg.raw.get("reports", {}) or {}).items():
        wdays = rep_raw.get("standalone_weekdays")
        mdays = rep_raw.get("standalone_monthdays")
        wdays = wdays if isinstance(wdays, list) and wdays else None
        mdays = mdays if isinstance(mdays, list) and mdays else None
        if wdays is None and mdays is None:
            continue   # not declared → keep the historical-expected guess
        if (wdays is None or wd in wdays) and (mdays is None or target_date.day in mdays):
            continue   # it IS supposed to run today → a missing run is a real miss
        ids.add(rid)
        for cand in (_HUB_CARD.get(rid), CURATED_ALIAS.get(rid), slug(rid)):
            if cand:
                ids.add(cand)
    return ids


def _machine_label(row_machine: str, lucy2_hosts: str) -> str:
    """'Lucy 2' when the row's machine matches the Lucy-2 hostname substrings,
    'the mini' for the scheduler Mac mini, else 'Lucy 1' — so an alert names the
    box it actually ran on. The scheduler mini runs the single-session ownerville
    reports (STF Field Check, etc.); defaulting those to 'Lucy 1' sent people to
    the wrong machine to diagnose them. Lucy-2 check stays first so Carlos's own
    Mac mini (a lucy2_host) is still labeled 'Lucy 2'."""
    if lucy2_hosts and _machine_matches(row_machine, lucy2_hosts, exact=False):
        return "Lucy 2"
    if "alphaletes-mac-mini" in (row_machine or "").lower():
        return "the mini"
    return "Lucy 1"


_DIDNT_RUN_GRACE_HOURS = 2   # how long past a report's usual start before "didn't run"
# How long a standalone report's live 'running' pill (publish_running) may stay
# OPEN before we treat it as stuck/crashed. Longer than any standalone report's
# real runtime (the longest instrumented, vantura_payroll incl. its one retry,
# is ~60m) and shorter than the Hub pill's 2h staleness fade, so a crash is
# alerted before it silently disappears. Orchestrator reports are skipped (they
# heartbeat their pill + self-alert), so this only fires on standalone reports.
_STUCK_AFTER_MIN = 90


def _bg_check_has_new_emails():
    """True/False if we can tell whether any background-check emails arrived in the
    last day; None if the source can't be reached (no Gmail app password on this
    machine, IMAP hiccup, etc.). Used to distinguish bg_check_sync's benign
    'nothing to sync' day from a real 'didn't run' miss. Best-effort — never raises."""
    try:
        from automations.bg_check_sync import email_source
        return len(email_source.fetch_events(since_days=1)) > 0
    except Exception:  # noqa: BLE001
        return None


def _historical_expected(rows, target_date, lookback_weeks: int = 3, min_days: int = 2,
                         daily_window: int = 7, daily_min_days: int = 5):
    """Which reports NORMALLY run on this weekday — the baseline for 'didn't run at
    all' (no Activity row today). Derived from the shared log itself, so it needs no
    schedule config and self-maintains: a card that produced a row on at least
    `min_days` of the last `lookback_weeks` SAME-weekday dates is 'expected today'.
    MUST have run on the MOST RECENT same-weekday (last week) — this recency gate
    self-corrects when a report is renamed or consolidated: an old id (e.g.
    daily-metrics, now folded into office-metrics) stops appearing and drops out
    within a week, instead of false-flagging 'didn't run' for three.
    Returns {card_id: {'start_hour', 'machine', 'name'}} where start_hour is the
    earliest it usually starts (so we only flag it missing AFTER its usual time)."""
    import datetime as _dt
    last_week = (target_date - _dt.timedelta(days=7)).isoformat()
    dates = {(target_date - _dt.timedelta(days=7 * w)).isoformat()
             for w in range(1, lookback_weeks + 1)}
    seen = {}
    for r in rows:
        started = str(r.get("Started At") or "").strip()
        d = started[:10]
        if d not in dates:
            continue
        cid = str(r.get("Report ID") or r.get("Report Name") or "").strip()
        if not cid:
            continue
        rec = seen.setdefault(cid, {"days": set(), "hour_by_day": {}, "machine": "", "name": cid})
        rec["days"].add(d)
        try:
            h = _dt.datetime.fromisoformat(started).hour
            # keep the EARLIEST start on each day (a day may hold several runs)
            rec["hour_by_day"][d] = min(h, rec["hour_by_day"].get(d, h))
        except Exception:
            pass
        rec["machine"] = str(r.get("Machine") or "") or rec["machine"]
        rec["name"] = str(r.get("Report Name") or cid) or rec["name"]
    out = {}
    for cid, rec in seen.items():
        if last_week in rec["days"] and len(rec["days"]) >= min_days:
            # Anchor "usual start" to the MOST RECENT same-weekday, NOT min() across
            # the whole window. A one-off cluster of early/test runs on some past
            # same-weekday (e.g. STF's install day 2026-07-17 had 19:xx test runs on
            # top of its real 23:00 run) would otherwise drag start_hour hours earlier
            # for weeks and fire a bogus "didn't run" alert every same-weekday before
            # the report's real nightly time. last_week is guaranteed present by the
            # gate above; fall back to the window min only if its hour didn't parse.
            start_hour = rec["hour_by_day"].get(last_week)
            if start_hour is None:
                start_hour = min(rec["hour_by_day"].values()) if rec["hour_by_day"] else 0
            out[cid] = {"start_hour": start_hour,
                        "machine": rec["machine"], "name": rec["name"]}

    # ---- DAILY cadence (Megan 2026-08-18) -----------------------------------
    # The same-weekday baseline above is built for WEEKLY reports, and it leaves a
    # hole for a report that runs EVERY day: each weekday only becomes watched on
    # its 3rd occurrence, so a young daily report is invisible on the weekdays it
    # hasn't hit twice yet. Applicant Push went live 8/4 and died on Mon 8/17 with
    # exactly ONE prior Monday (8/10) in the window — one short of min_days — so
    # nothing alerted for its whole first dead day; the miss was only caught 8/18,
    # when Tuesday finally had two. A daily report doesn't need a weekday argument:
    # if it produced a row on most of the last `daily_window` CONSECUTIVE days it
    # runs today too, whatever weekday today is.
    #
    # The "most of" slack (5 of 7, not 7 of 7) is what keeps this alive ACROSS an
    # outage: requiring yesterday would make the watcher go quiet on day 2 of the
    # very failure it's meant to report. It degrades the same way the weekday gate
    # does — a report genuinely retired drops out within about a week — and every
    # downstream exemption still applies (orchestrator ids, one-shot installers,
    # standalone_weekdays off-days are all subtracted by the caller).
    #
    # DENSITY ALONE IS NOT ENOUGH: a Mon-Fri report also hits 5 of the last 7 days,
    # so density by itself would have posted "didn't run today" for daily-focus and
    # the 1st-round-recruiter % every Saturday and Sunday, plus car_rides and the
    # applicant-tracker sync every Sunday (measured against the real Activity log
    # before shipping this). So today's weekday must ALSO be proven: the report has
    # to have run on the LAST occurrence of this weekday. That's one same-weekday
    # hit instead of the weekday path's two — which is trustworthy here precisely
    # because the daily density is backing it, and it's what closes the young-daily-
    # report hole without inventing weekend runs that never existed.
    daily_dates = {(target_date - _dt.timedelta(days=n)).isoformat()
                   for n in range(1, daily_window + 1)}
    dseen = {}
    for r in rows:
        started = str(r.get("Started At") or "").strip()
        d = started[:10]
        if d not in daily_dates:
            continue
        cid = str(r.get("Report ID") or r.get("Report Name") or "").strip()
        if not cid:
            continue
        rec = dseen.setdefault(cid, {"days": set(), "hour_by_day": {},
                                     "machine": "", "name": cid})
        rec["days"].add(d)
        try:
            h = _dt.datetime.fromisoformat(started).hour
            rec["hour_by_day"][d] = min(h, rec["hour_by_day"].get(d, h))
        except Exception:
            pass
        rec["machine"] = str(r.get("Machine") or "") or rec["machine"]
        rec["name"] = str(r.get("Report Name") or cid) or rec["name"]
    same_wd = (target_date - _dt.timedelta(days=7)).isoformat()
    for cid, rec in dseen.items():
        if len(rec["days"]) < daily_min_days:
            continue
        if same_wd not in rec["days"]:
            continue   # never ran on this weekday → it isn't a report of today's
        # Anchor "usual start" to the MOST RECENT day it ran, same reasoning as the
        # weekday path: a past day's one-off early test run must not drag the alert
        # time hours earlier for a week.
        #
        # ...BUT THE NEWEST DAY IS A SAMPLE OF ONE (Megan 2026-09-03). One odd day
        # is enough to poison the next one. Rep Gap Alerts publishes exactly one
        # Activity row a day (_publish_hub_once, at its first good tick ~13:30).
        # On 2026-09-01 three `gap_alerts --send --force` jobs sat behind a long
        # job in Lucy 1's serial queue and drained at 00:00, 00:03 and 00:07 the
        # NEXT morning ([[reference-lucy-machines]]), so 9/2's only row reads
        # 00:00. The daily anchor took that single row as the schedule and posted
        # "Rep Gap Alerts — didn't run today on the mini · usually starts ~0:00"
        # at 4am on 9/3, for a report whose window does not open until 1:30pm.
        # Megan: "Gap alerts only run like 1-10 so not sure why there's a 4am
        # error."
        #
        # So the newest day no longer decides alone: take the LATER of it and the
        # MEDIAN of the window's per-day earliest hours. A real schedule MOVE —
        # the case the newest anchor exists for — is a run of days, so it still
        # wins as soon as it is later than the old hour (enrollment_pending_check
        # 04:00 -> 09:00: median 4, newest 9, max 9, correct on day one). A ONE-DAY
        # outlier cannot win, because a single day never moves the median.
        #
        # Erring later is the cheap direction here for the same reason it is at
        # the merge below: a late alert delays a true report by an hour, an early
        # one is pure noise in the channel this watcher exists to keep readable.
        newest = max(rec["days"])
        start_hour = rec["hour_by_day"].get(newest)
        if start_hour is None:
            start_hour = min(rec["hour_by_day"].values()) if rec["hour_by_day"] else 0
        elif rec["hour_by_day"]:
            _hrs = sorted(rec["hour_by_day"].values())
            start_hour = max(start_hour, _hrs[len(_hrs) // 2])
        if cid in out:
            # A SCHEDULE CHANGE MUST NOT COST A WEEK OF FALSE ALARMS (Megan
            # 2026-08-24). The weekday path got here first and anchored the hour
            # to the same weekday SEVEN DAYS AGO. For a daily report that is
            # always the stalest reading available, and the day a report moves it
            # is simply wrong: enrollment_pending_check left the 4am pass for its
            # own 09:00-22:00 hourly agent on 8/19, and the watcher went on
            # expecting it at 4:00 — posting "didn't run today on the mini ·
            # usually starts ~4:00" on 8/20, 8/21, 8/22 and 8/23, each one
            # resolved a few hours later by the 9:00 run that was never late.
            # Four mornings of noise in the channel Megan is trying to de-clutter,
            # for a report that was working the whole time.
            #
            # This report also clears the DAILY bar, and the daily anchor is the
            # most recent day it actually ran — so it is both fresher and, after
            # a move, correct. Take the hour (and the machine, stale for the same
            # reason: that agent moved to Lucy 1) and leave membership alone.
            # ...but take the LATER of the two, not the daily one outright
            # (Megan 2026-08-30: "this shouldn't be flagging if it isn't even
            # scheduled to run yet"). The daily anchor is the newest day the
            # report ran REGARDLESS OF WEEKDAY, which is only "correct after a
            # move" for a report that runs at ONE time. For a report whose hour
            # varies BY WEEKDAY it imports yesterday's clock into today:
            # new_start_followup runs Sat 08:00 (roll call) and Sun 13:00
            # (checklist), so on Sunday this read Saturday's 8 and posted
            # "didn't run today on the mini" at 10:03 — nearly three hours
            # before the job was due to start.
            #
            # max() still fixes the case this branch was written for. The
            # enrollment_pending_check move was 04:00 -> 09:00: weekday path 4,
            # daily path 9, max 9 — the same answer. It only differs when the
            # weekday reading is LATER, which is exactly the varies-by-weekday
            # shape above.
            #
            # Erring later is the cheap direction on purpose: a late alert
            # delays a true report by an hour, an early one is pure noise in the
            # channel this watcher exists to keep readable.
            out[cid]["start_hour"] = max(start_hour, out[cid]["start_hour"])
            if rec["machine"]:
                out[cid]["machine"] = rec["machine"]
            continue
        out[cid] = {"start_hour": start_hour,
                    "machine": rec["machine"], "name": rec["name"]}
    return out


def _close_recovered_incidents(cfg, reports, dry_run: bool, ts: str) -> int:
    """Close the incident thread of any standalone report whose latest run today
    is clean. Returns how many were closed.

    The watcher only ever OPENED threads; nothing closed them, so a report fixed
    on Wednesday left Tuesday's alert reading as open work — which is what made
    the channel impossible to skim (Eve 2026-08-14)."""
    from automations.day_orchestrator import notify
    try:
        from automations.shared import incident_thread as inc
        ch = notify._corrections_channel(cfg)
        open_keys = set(inc.open_keys()) if ch else set()
    except Exception as e:  # noqa: BLE001 — closing is a nicety, never fatal
        print(f"[{ts}] watch: incident index unreadable: {e}", flush=True)
        return 0
    if not open_keys:
        return 0
    closed = 0
    for r in reports:
        if _classify(r["status"])[1] != "ok":
            continue
        rid = r.get("report_id") or r.get("name") or "?"
        for key in (f"standalone-{rid}", f"nonew-{rid}"):
            if key not in open_keys:
                continue
            lines = [
                f":white_check_mark: *{r['name']}* — RESOLVED. It ran clean today "
                f"({_time_only(r['started'])}), so this is closed.",
                "_If it breaks again it'll open a fresh post, not revive this one._",
            ]
            try:
                if inc.resolve(key=key, lines=lines, channel=ch, dry_run=dry_run):
                    closed += 1
                    print(f"[{ts}] watch: closed incident {key} — ran clean today",
                          flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[{ts}] watch: incident close failed for {key}: {e}",
                      flush=True)
    return closed


def _close_silent_job_incidents(cfg, job_ids, dry_run: bool, ts: str) -> int:
    """Close the incident thread of a silent job whose heartbeat is current.

    _close_recovered_incidents can't do this one: it decides "recovered" from a
    clean Activity row, and the entire point of these jobs is that they never
    write one. Same incident key (`standalone-<id>`), same wording, so the thread
    behaves exactly like every other alert in the channel."""
    from automations.day_orchestrator import notify
    try:
        from automations.shared import incident_thread as inc
        from automations.shared import silent_job_watch as _sjw
        ch = notify._corrections_channel(cfg)
        open_keys = set(inc.open_keys()) if ch else set()
    except Exception as e:  # noqa: BLE001
        print(f"[{ts}] watch: incident index unreadable: {e}", flush=True)
        return 0
    closed = 0
    for jid in job_ids:
        key = f"standalone-{jid}"
        if key not in open_keys:
            continue
        name = (_sjw.JOBS.get(jid) or {}).get("name", jid)
        lines = [
            f":white_check_mark: *{name}* — RESOLVED. It is checking in on "
            "schedule again, so this is closed.",
            "_If it stops again it'll open a fresh post, not revive this one._",
        ]
        try:
            if inc.resolve(key=key, lines=lines, channel=ch, dry_run=dry_run):
                closed += 1
                print(f"[{ts}] watch: closed incident {key} — heartbeat current",
                      flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{ts}] watch: incident close failed for {key}: {e}", flush=True)
    return closed


# Wording the RETRACTION check keys on. A didn't-run alert says one of these in
# its parent line; a failure alert never does. See _retract_false_alarms for why
# prose is the honest discriminator here.
_DIDNT_RUN_WORDING = ("didn't run today", "did not run today",
                      "didn\u2019t run today")


def _retract_false_alarms(cfg, target_date, dry_run: bool, ts: str) -> int:
    """Take back a "didn't run today" this watcher should never have posted.

    WHY (Megan 2026-08-26). The watcher infers a report's cadence from its own
    Activity history, so ONE hand-run teaches it a schedule that does not exist —
    `alphalete_org_b2b` ran by hand once on 8/17 at 16:00 and it began posting
    "didn't run today on Lucy 2 · usually starts ~16:00" every day after. The
    cure for that is a DECLARATION (`hand_run_only`, `standalone_weekdays`,
    `standalone_monthdays`, `logs_on_event_only`), and adding one does stop the
    next alert — but
    nothing ever went back for the one already on the board. Worse, this class
    can't self-close: _close_recovered_incidents closes a thread when the report
    RUNS CLEAN, and a hand-run-only handle may simply never run again. So
    b2b's thread sat open from 8/24 to 8/26 describing a problem that had never
    existed and could not resolve itself. Megan: "teach the watcher to retract
    its own false alarms."

    A retraction is only ever safe when we can prove BOTH halves:

      1) The report is now DECLARED exempt from the didn't-run check — either
         structurally (nothing on a clock runs it at all, or its clock ticks but
         only writes a row when it had work — `logs_on_event_only`) or for the
         specific day the alert was raised. Today's off-day list can't answer
         for an alert raised last Thursday, so the off-day case is asked against
         the incident's OWN opened date and skipped when we can't date it.
      2) The open thread is actually a DIDN'T-RUN alert. This is the sharp edge:
         `standalone-<id>` is the key for every standalone alert kind — ERROR,
         INCOMPLETE and STUCK share it with MISSED (notify.send_standalone_alert
         builds it from the id alone). Retracting on the exemption by itself would
         close a REAL failure thread for a hand-run-only report, which is the
         worst thing this module could do: the failure is still true, and being
         un-scheduled was never a reason to stop watching for it. So the parent's
         own wording decides, and anything we can't read is left alone.

    Never touches `failure-` or `drop-` keys, and never retracts a NO_NEW note
    (`nonew-`) — that one is a real observation about a real source.
    """
    from automations.day_orchestrator import notify
    try:
        from automations.shared import incident_thread as inc
        ch = notify._corrections_channel(cfg)
        open_keys = set(inc.open_keys()) if ch else set()
    except Exception as e:  # noqa: BLE001 — retracting is a nicety, never fatal
        print(f"[{ts}] watch: incident index unreadable: {e}", flush=True)
        return 0
    if not open_keys:
        return 0

    try:
        structural = _handrun_only_ids(cfg) | _oneshot_utility_ids(cfg)
    except Exception:  # noqa: BLE001
        structural = set()
    # Kept SEPARATE from `structural` on purpose: both are permanent exemptions
    # from the didn't-run check, but they are exempt for opposite reasons, and the
    # retraction says WHY out loud in the channel. "Nothing on a clock runs this
    # one" is simply false about sara_down — its clock ticks every 5 minutes — and
    # a retraction that misdescribes a live poller as hand-run-only teaches the
    # team the wrong thing about a report they rely on.
    try:
        event_logged = _event_logged_ids(cfg)
    except Exception:  # noqa: BLE001
        event_logged = set()
    idx = {}
    try:
        idx = inc._load_index() or {}
    except Exception:  # noqa: BLE001
        pass

    retracted = 0
    for key in sorted(open_keys):
        if not key.startswith("standalone-"):
            continue
        rid = key[len("standalone-"):]

        why = ""
        if rid in structural:
            why = ("Nothing on a clock runs this one — it only runs when "
                   "somebody starts it by hand.")
        elif rid in event_logged:
            why = ("This one runs constantly and only logs when it actually has "
                   "something to do — a quiet day is it working normally, not a "
                   "missed run.")
        else:
            # Off-day, asked against the day the alert was RAISED.
            opened = (idx.get(key) or {}).get("opened") if isinstance(
                idx.get(key), dict) else None
            if not opened:
                continue
            try:
                opened_date = dt.date.fromisoformat(opened)
            except Exception:  # noqa: BLE001
                continue
            try:
                if rid not in _offday_standalone_ids(cfg, opened_date):
                    continue
            except Exception:  # noqa: BLE001
                continue
            why = ("It isn't scheduled to run on a {}."
                   .format(opened_date.strftime("%A")))

        # Half 2: prove it is a didn't-run thread and not a real failure.
        try:
            client = inc._client()
            parent = inc._find_any_state(key, channel=ch, client=client)
            text = (parent or {}).get("text") or ""
        except Exception as e:  # noqa: BLE001
            print(f"[{ts}] watch: can't read {key} to retract it ({e})",
                  flush=True)
            continue
        if not text:
            continue
        low = text.lower()
        if not any(w in low for w in _DIDNT_RUN_WORDING):
            # A real failure on a hand-run report. Being un-scheduled is not
            # being un-watched — leave it exactly where it is.
            continue

        lines = [
            "*Retracted — this alert was wrong.* {} So \"didn't run today\" "
            "was never true.".format(why),
            "Nothing was broken and nothing needs re-running. It is declared "
            "now, so it won't be asked again.",
        ]
        try:
            if inc.resolve(key=key, lines=lines, channel=ch, dry_run=dry_run):
                retracted += 1
                print(f"[{ts}] watch: retracted false alarm {key} — {why}",
                      flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{ts}] watch: retraction failed for {key}: {e}", flush=True)
    return retracted


def _alert_config_unparseable(day: str, err: Exception, *, dry_run: bool, ts: str) -> None:
    """Say — ONCE a day — that schedule_config can't be read.

    Routed through orchestrator_heartbeat on purpose: it resolves the corrections
    channel from the id cache / a raw settings read / a literal fallback, none of
    which need a parsed config. Reaching for notify._corrections_channel(cfg) here
    would need the very object we just failed to build.

    Best-effort throughout — this runs on the failure path of a watcher, and a
    watcher that raises while reporting a failure is the bug being fixed."""
    try:
        from automations.orchestrator_heartbeat import run as _hb
        marker = _hb.MARKER_DIR / f"{day}.config-unparseable"
        if marker.exists():
            return
        text = (":rotating_light: *schedule_config.json is unparseable on {}* — {}\n"
                "`{}: {}`\nThe error watcher cannot run: every skip-list it needs "
                "comes from that file, so it would alert on every orchestrator "
                "report at once. The 04:00 batch reads the same file FIRST, so "
                "tomorrow's run dies here too unless this is cleared.\n"
                "Fix: `lucy git_recover --machine \"{}\"`."
                .format(_hb._machine_name(), day, type(err).__name__,
                        str(err)[:120], _hb._machine_name()))
        if dry_run:
            print(f"[{ts}] watch: [dry-run] would alert: {text}", flush=True)
            return
        if _hb.post(text):
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(ts)
    except Exception as e:  # noqa: BLE001
        print(f"[{ts}] watch: could not raise the config alarm: "
              f"{type(e).__name__}: {e}", flush=True)


def _run_watch(day: str, day_human: str, lucy2_hosts: str, dry_run: bool, ts: str) -> int:
    """Intraday BOTH-MACHINE error watcher: scan the shared Hub Activity log and
    post a deduped, real-time corrections alert for any STANDALONE report (either
    machine) that errored / ran partial today. Orchestrator-managed reports are
    skipped — they already self-alert in real time. Silent when nothing new is
    wrong. No email, ever (Megan 2026-07-25: know all day which reports errored on
    both Lucy 1 and Lucy 2)."""
    from automations.day_orchestrator import notify, registry as _reg
    # GUARDED since 2026-08-27. This call used to be bare, and that is how the
    # watcher died alongside the thing it watches: an unmerged schedule_config
    # (conflict markers, invalid JSON) killed the 04:00 orchestrator AND every
    # 10-minute pass of this watcher, so a batch that ran ZERO reports went
    # unreported for 2h45m. Two other load_config calls in this file were already
    # wrapped; this one was missed.
    #
    # We STOP rather than continue with cfg=None on purpose. Every skip-list below
    # (_orchestrator_ids, _oneshot_utility_ids, _offday_standalone_ids,
    # _handrun_only_ids) is derived from cfg, so a pass without it would treat
    # every orchestrator-managed report as a standalone and alert on all of them
    # at once — a false-alarm storm during an outage, which is precisely when the
    # channel has to stay readable.
    try:
        cfg = _reg.load_config()
    except Exception as e:  # noqa: BLE001 — a corrupt config must not kill the watcher
        print(f"[{ts}] watch: schedule_config UNPARSEABLE "
              f"({type(e).__name__}: {str(e)[:120]}) — skipping this pass.",
              flush=True)
        _alert_config_unparseable(day, e, dry_run=dry_run, ts=ts)
        return 1
    if not notify._corrections_channel(cfg):
        print(f"[{ts}] watch: no corrections channel set — nothing to do.", flush=True)
        return 0
    try:
        rows = _read_activity()
    except Exception as e:
        print(f"[{ts}] watch: Hub Activity read failed: {type(e).__name__}: {e}",
              flush=True)
        return 1
    target_date = dt.date.fromisoformat(day)
    reports = _collect(rows, None, day, exact=False)   # host=None → all machines
    skip = (_orchestrator_ids(cfg, target_date) | _oneshot_utility_ids(cfg)
            | _retired_ids())
    # Off-day exemption for weekday-pinned standalone reports. Deliberately NOT
    # folded into `skip`: it must suppress the "didn't run" guess only, never a
    # real FAILED / INCOMPLETE / STUCK on an off-day hand-rerun.
    offday = _offday_standalone_ids(cfg, target_date)
    # Same treatment, same reason, for handles nothing on a clock ever fires:
    # exempt from the "didn't run" GUESS only, still fully watched for a failed /
    # partial / stuck hand-run. See _handrun_only_ids.
    offday = offday | _handrun_only_ids(cfg)
    # And for reports that only WRITE a row when they had something to do: a
    # missing row is not a missing run. Same narrow treatment — the "didn't run"
    # guess only, never a real failure. See _event_logged_ids.
    offday = offday | _event_logged_ids(cfg)
    already = _load_alerted(day)
    ran_ids = {(r.get("report_id") or r.get("name") or "?") for r in reports}
    newly = set()
    posted = 0

    # 1) ERRORED — a standalone report on either machine whose latest run today is
    #    failed / partial (orchestrator reports self-alert, so they're skipped).
    for r in reports:
        if _classify(r["status"])[1] not in ("failed", "partial"):
            continue
        rid = r.get("report_id") or r.get("name") or "?"
        if rid in skip or rid in already:
            continue
        kind = "INCOMPLETE" if _classify(r["status"])[1] == "partial" else "FAILED"
        when = _time_only(r["started"]) + (f"–{_time_only(r['ended'])}" if r["ended"] else "")
        try:
            notify.send_standalone_alert(
                cfg, name=r["name"], report_id=rid, kind=kind,
                status=r["status"] or kind, when=when, day=day_human,
                machine_label=_machine_label(r.get("machine", ""), lucy2_hosts),
                dry_run=dry_run)
            newly.add(rid)
            posted += 1
        except Exception as e:  # noqa: BLE001 — one bad alert must not sink the rest
            print(f"[{ts}] watch: alert failed for {r['name']}: "
                  f"{type(e).__name__}: {e}", flush=True)

    # 2) DIDN'T RUN AT ALL — a report that NORMALLY runs today (same-weekday
    #    history) but has NO row today, once its usual start time + grace has passed.
    #    Orchestrator reports are skipped: the day orchestrator fires its own
    #    "didn't run today" (MISSED) alert at the noon backstop.
    now = dt.datetime.now()
    for cid, info in _historical_expected(rows, target_date).items():
        if cid in ran_ids or cid in skip or cid in already or cid in offday:
            continue
        if now.hour < info["start_hour"] + _DIDNT_RUN_GRACE_HOURS:
            continue   # too early to call it missing
        # An event-driven report (bg_check_sync) with no run today usually just
        # means nothing arrived to process — not a stall. Peek at its source before
        # crying "didn't run": no new emails → a benign NO_NEW note; new emails
        # waiting but unsynced → keep the real MISSED (a genuine miss worth fixing).
        # Megan 2026-08-01. Probe is best-effort — if we can't tell, alert as MISSED.
        kind = "MISSED"
        status = "did not run today"
        if cid == "bg_check_sync" and _bg_check_has_new_emails() is False:
            kind = "NO_NEW"
            status = "no new emails"
        # An APPROVAL PHASE with no run isn't a stall — it runs the moment a
        # human ✅'s the day's review post, and until then "didn't run today on
        # the mini" points people at a machine that is doing exactly what it
        # should (Megan 2026-08-18: "shouldn't this one just say 'waiting for
        # approval to send email'?"). Every gate publishes its release row as
        # "<card>-approved" (review_gate.py / dashboard approval_phase), so the
        # suffix IS the declaration — no list to maintain.
        elif cid.endswith("-approved"):
            kind = "WAITING"
            status = "waiting for approval"
        try:
            notify.send_standalone_alert(
                cfg, name=info["name"], report_id=cid, kind=kind,
                status=status,
                when=f"usually starts ~{info['start_hour']}:00", day=day_human,
                machine_label=_machine_label(info["machine"], lucy2_hosts),
                dry_run=dry_run)
            newly.add(cid)
            posted += 1
        except Exception as e:  # noqa: BLE001
            print(f"[{ts}] watch: didn't-run alert failed for {cid}: "
                  f"{type(e).__name__}: {e}", flush=True)

    # 2b) SILENT JOBS — the handful that publish nothing on purpose, so steps 1
    #    and 2 are structurally blind to them (no Activity row means no error to
    #    read and no history to expect). They stamp a heartbeat instead; this
    #    asks whether it is current. Alerts as MISSED through the same path, so
    #    it dedupes with `already` and closes itself in step 4 like anything else.
    #    See shared/silent_job_watch.py for why these jobs cannot simply publish.
    try:
        from automations.shared import silent_job_watch as _sjw
        _beats = _sjw.read_beats()
        for _job in _sjw.overdue(now, _beats):
            _jid = _job["job_id"]
            if _jid in skip or _jid in already or _jid in newly:
                continue
            notify.send_standalone_alert(
                cfg, name=_job["name"], report_id=_jid, kind="MISSED",
                status=_job["why"],
                when="last check-in %s" % (
                    _job["last_seen"].strftime("%a %H:%M")
                    if _job["last_seen"] else "never"),
                day=day_human, machine_label=_job["machine"], dry_run=dry_run)
            newly.add(_jid)
            posted += 1
        _healthy_jobs = set(_sjw.healthy(now, _beats))
    except Exception as e:  # noqa: BLE001 — a blind spot is bad, a crash is worse
        print(f"[{ts}] watch: silent-job check failed: {type(e).__name__}: {e}",
              flush=True)
        _healthy_jobs = set()

    # 3) STUCK — a standalone report opened a live 'running' pill (publish_running)
    #    and never closed it: the run crashed, was killed, or hung between open and
    #    close. Nothing else catches this — _classify('started')=='running' so step
    #    1 skips it, and because a row EXISTS step 2 skips it too. The pill would sit
    #    yellow until the Hub's 2h fade, then vanish silently. Flag any still-open
    #    'started' row older than _STUCK_AFTER_MIN. (Orchestrator reports are in
    #    `skip` — they heartbeat their pill + self-alert, so no false positives.)
    for r in reports:
        if _classify(r["status"])[1] != "running" or r.get("ended"):
            continue
        rid = r.get("report_id") or r.get("name") or "?"
        if rid in skip or rid in already or rid in newly:
            continue
        try:
            age = now - dt.datetime.fromisoformat(str(r["started"]))
        except Exception:
            continue
        if age < dt.timedelta(minutes=_STUCK_AFTER_MIN):
            continue
        try:
            notify.send_standalone_alert(
                cfg, name=r["name"], report_id=rid, kind="STUCK",
                status="stuck (running pill never closed)",
                when=f"running since {_time_only(r['started'])}", day=day_human,
                machine_label=_machine_label(r.get("machine", ""), lucy2_hosts),
                dry_run=dry_run)
            newly.add(rid)
            posted += 1
        except Exception as e:  # noqa: BLE001 — one bad alert must not sink the rest
            print(f"[{ts}] watch: stuck alert failed for {rid}: "
                  f"{type(e).__name__}: {e}", flush=True)

    # 4) RECOVERED — a report that ran clean today but still has an OPEN incident
    #    thread from an earlier day. Say so IN that thread and close it, so the
    #    channel never leaves a fixed problem sitting there looking open (Eve
    #    2026-08-14). Free when nothing is open: open_keys reads a local index.
    _close_recovered_incidents(cfg, reports, dry_run, ts)
    # A false alarm has no clean run coming to close it — see _retract_false_alarms.
    _retract_false_alarms(cfg, target_date, dry_run, ts)
    # A silent job has no Activity row for the step above to read as "clean", so
    # it closes its own thread the moment its heartbeat is current again.
    if _healthy_jobs:
        _close_silent_job_incidents(cfg, _healthy_jobs, dry_run, ts)

    if newly and not dry_run:
        _save_alerted(day, already | newly)
    print(f"[{ts}] watch: {posted} new alert(s) across both machines on "
          f"{day}{' (dry-run)' if dry_run else ''}; {len(already)} already alerted "
          "earlier today.", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--host", default=None,
                    help="summarize ANOTHER machine by hostname substring "
                         "(default: this machine's own hostname). In --watch, this "
                         "is the Lucy-2 hostname list used only to LABEL rows.")
    ap.add_argument("--label", default=None,
                    help="name for the subject, e.g. 'Lucy 2' (default: this "
                         "machine's orchestrator prefix)")
    ap.add_argument("--watch", action="store_true",
                    help="intraday BOTH-MACHINE error watcher: post deduped, "
                         "real-time corrections alerts for standalone reports that "
                         "errored today; no summary email. Run it every ~10 min.")
    args = ap.parse_args(argv)

    if args.watch:
        _day = args.date or dt.date.today().isoformat()
        _day_h = dt.date.fromisoformat(_day).strftime("%a %b %d")
        _ts = dt.datetime.now().isoformat(timespec="seconds")
        return _run_watch(_day, _day_h, args.host or "", args.dry_run, _ts)

    day = args.date or dt.date.today().isoformat()
    day_human = dt.date.fromisoformat(day).strftime("%a %b %d")
    target = args.host or socket.gethostname()
    exact = args.host is None   # own hostname → exact; --host → substring
    ts = dt.datetime.now().isoformat(timespec="seconds")

    try:
        rows = _read_activity()
    except Exception as e:
        print(f"[{ts}] machine-digest: Hub Activity read failed: "
              f"{type(e).__name__}: {e}", flush=True)
        return 1

    reports = _collect(rows, target, day, exact=exact)

    # Machine label ("[Lucy 2] ") + recipients from the orchestrator config, so
    # this lands exactly like Lucy 1's daily summary. --label wins (used when
    # reporting another machine from Lucy 1).
    try:
        from automations.day_orchestrator import notify, registry
        recipients = registry.load_config().settings.get("recipients", [])
        machine_label = f"[{args.label}] " if args.label else notify._machine_prefix()
    except Exception:
        machine_label = f"[{args.label}] " if args.label else ""
        recipients = ["Alphaletereporting@gmail.com"]

    if not reports:
        print(f"[{ts}] machine-digest: nothing ran for '{target}' on {day} "
              "— staying quiet (no email).", flush=True)
        return 0

    # Corrections channel ON → NO summary email. Post a per-report Slack alert for
    # anything that errored / ran partial (silent if everything ran clean), so
    # Lucy 2 gets the same problem-only Slack notifications as Lucy 1 instead of a
    # daily digest email (Megan 2026-07-25).
    try:
        from automations.day_orchestrator import notify, registry as _reg
        cfg = _reg.load_config()
    except Exception:
        cfg, notify = None, None
    if cfg is not None and notify is not None and notify._corrections_channel(cfg):
        label = (args.label or "Lucy 2").strip()
        problems = [r for r in reports if _classify(r["status"])[1] in ("failed", "partial")]
        for r in problems:
            kind = "INCOMPLETE" if _classify(r["status"])[1] == "partial" else "FAILED"
            when = _time_only(r["started"]) + (f"–{_time_only(r['ended'])}" if r["ended"] else "")
            rid = r.get("report_id") or r.get("name") or "?"
            try:
                notify.send_standalone_alert(
                    cfg, name=r["name"], report_id=rid, kind=kind,
                    status=r["status"] or kind, when=when, day=day_human,
                    machine_label=label, dry_run=args.dry_run)
            except Exception as e:  # noqa: BLE001 — one bad alert must not sink the rest
                print(f"[{ts}] machine-digest: alert failed for {r['name']}: "
                      f"{type(e).__name__}: {e}", flush=True)
        print(f"[{ts}] machine-digest: corrections mode — {len(problems)} problem "
              f"alert(s) of {len(reports)} report(s) for '{target}' on {day}"
              f"{' (dry-run)' if args.dry_run else ''}; no summary email.", flush=True)
        return 0

    subject, h, t = _render(reports, machine_label, day_human)

    try:
        from automations.day_orchestrator import notify
        notify._send_email(subject, h, t, recipients, args.dry_run, "machine-digest")
    except Exception as e:
        print(f"[{ts}] machine-digest: send failed: {type(e).__name__}: {e}",
              flush=True)
        return 1
    print(f"[{ts}] machine-digest: reported {len(reports)} report(s) for "
          f"'{target}' on {day}{' (dry-run)' if args.dry_run else ''}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
