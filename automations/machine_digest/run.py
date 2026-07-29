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
    wd = target_date.weekday()
    ids = set()
    raw = cfg.raw.get("reports", {})

    def _add(rid):
        ids.add(rid)
        card = _HUB_CARD.get(rid)
        if card:
            ids.add(card)

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


def _machine_label(row_machine: str, lucy2_hosts: str) -> str:
    """'Lucy 2' when the row's machine matches the Lucy-2 hostname substrings,
    else 'Lucy 1' — so a both-machine alert says which box it ran on."""
    if lucy2_hosts and _machine_matches(row_machine, lucy2_hosts, exact=False):
        return "Lucy 2"
    return "Lucy 1"


_DIDNT_RUN_GRACE_HOURS = 2   # how long past a report's usual start before "didn't run"
# How long a standalone report's live 'running' pill (publish_running) may stay
# OPEN before we treat it as stuck/crashed. Longer than any standalone report's
# real runtime (the longest instrumented, vantura_payroll incl. its one retry,
# is ~60m) and shorter than the Hub pill's 2h staleness fade, so a crash is
# alerted before it silently disappears. Orchestrator reports are skipped (they
# heartbeat their pill + self-alert), so this only fires on standalone reports.
_STUCK_AFTER_MIN = 90


def _historical_expected(rows, target_date, lookback_weeks: int = 3, min_days: int = 2):
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
        rec = seen.setdefault(cid, {"days": set(), "hours": [], "machine": "", "name": cid})
        rec["days"].add(d)
        try:
            rec["hours"].append(_dt.datetime.fromisoformat(started).hour)
        except Exception:
            pass
        rec["machine"] = str(r.get("Machine") or "") or rec["machine"]
        rec["name"] = str(r.get("Report Name") or cid) or rec["name"]
    out = {}
    for cid, rec in seen.items():
        if last_week in rec["days"] and len(rec["days"]) >= min_days:
            out[cid] = {"start_hour": min(rec["hours"]) if rec["hours"] else 0,
                        "machine": rec["machine"], "name": rec["name"]}
    return out


def _run_watch(day: str, day_human: str, lucy2_hosts: str, dry_run: bool, ts: str) -> int:
    """Intraday BOTH-MACHINE error watcher: scan the shared Hub Activity log and
    post a deduped, real-time corrections alert for any STANDALONE report (either
    machine) that errored / ran partial today. Orchestrator-managed reports are
    skipped — they already self-alert in real time. Silent when nothing new is
    wrong. No email, ever (Megan 2026-07-25: know all day which reports errored on
    both Lucy 1 and Lucy 2)."""
    from automations.day_orchestrator import notify, registry as _reg
    cfg = _reg.load_config()
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
    skip = _orchestrator_ids(cfg, target_date)
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
        if cid in ran_ids or cid in skip or cid in already:
            continue
        if now.hour < info["start_hour"] + _DIDNT_RUN_GRACE_HOURS:
            continue   # too early to call it missing
        try:
            notify.send_standalone_alert(
                cfg, name=info["name"], report_id=cid, kind="MISSED",
                status="did not run today",
                when=f"usually starts ~{info['start_hour']}:00", day=day_human,
                machine_label=_machine_label(info["machine"], lucy2_hosts),
                dry_run=dry_run)
            newly.add(cid)
            posted += 1
        except Exception as e:  # noqa: BLE001
            print(f"[{ts}] watch: didn't-run alert failed for {cid}: "
                  f"{type(e).__name__}: {e}", flush=True)

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
