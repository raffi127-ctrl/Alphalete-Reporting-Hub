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
    m = (row_machine or "").strip()
    if exact:
        return m == host
    return host.lower() in m.lower()  # substring, tolerant of .local/.attlocal


def _collect(rows: list[dict], host: str, day: str, exact: bool = True) -> list[dict]:
    """One entry per REPORT for the target machine + day (latest status + run
    count), newest-run first. Mirrors Lucy 1's summary: a report that retried 8×
    is one line showing its final outcome, not eight. `exact=False` matches the
    hostname as a substring (for --host, tolerant of .local vs .attlocal.net)."""
    # 1) Reduce each run's start+end pair (same RunID) to the end row.
    by_run = {}
    for r in rows:
        if not _machine_matches(str(r.get("Machine") or ""), host, exact):
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
        reports.append({
            "name": str(last.get("Report Name") or last.get("Report ID") or "?"),
            "status": str(last.get("Status") or "").strip(),
            "count": len(runs),
            "started": str(last.get("Started At") or ""),
            "ended": str(last.get("Ended At") or ""),
            "user": str(last.get("User") or "").strip(),
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
        status = (r["status"] or "—") + (f"  (ran {r['count']}×)" if r["count"] > 1 else "")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--host", default=None,
                    help="summarize ANOTHER machine by hostname substring "
                         "(default: this machine's own hostname)")
    ap.add_argument("--label", default=None,
                    help="name for the subject, e.g. 'Lucy 2' (default: this "
                         "machine's orchestrator prefix)")
    args = ap.parse_args(argv)

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
