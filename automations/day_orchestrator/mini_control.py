"""Remote control for the mini — a Google-Sheet command queue the mini polls.

Instead of emailing Megan a copy-paste fix block when a report glitches, Eve
(or Megan, or the orchestrator) drops a fix request into a "Mini Control" tab;
the mini polls the tab and AUTO-RUNS known-safe actions, writing the result
back. No SSH, no open ports, no network setup — both sides already auth to
Google Sheets, so it works across any network and is fully auditable (Megan
2026-06-26: "Eve should be able to remotely control the mini to fix the
glitches"; chose the easiest / least-likely-to-fail path + auto-run).

SAFETY: only WHITELISTED actions run (ACTIONS below) — NEVER arbitrary shell.
Each action has a timeout; a per-day cap guards against a runaway loop. The tab
is the audit log; every run writes its result back.

Tab columns:  Queued At · Action · Args · By · Status · Result · Finished At
Status flows  queued -> running -> done | failed.  Only 'queued' rows run.

Actions:
  rerun <report_id>     re-run one orchestrator report (today's common fix)
  restart_holder        relaunch the ownerville session-holder LaunchAgent
  reseed_appstream      open the AppStream login (a human clears Cloudflare)

CLI:
  python -m automations.day_orchestrator.mini_control --loop      # on the mini
  python -m automations.day_orchestrator.mini_control --once
  python -m automations.day_orchestrator.mini_control --enqueue rerun daily_focus
      --dry-run    poll + show what WOULD run, execute nothing
      --sandbox    use the "Mini Control TEST" tab (build/verify safely)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

import gspread

from automations.recruiting_report import fill as _fill
from automations.day_orchestrator import registry

REPO_ROOT = Path(__file__).resolve().parents[2]
# The control tab lives on the same workbook as Hub Activity (the orchestrator's
# existing coordination sheet — reuse the auth, one place to look).
CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
CONTROL_TAB = "Mini Control"
SANDBOX_TAB = "Mini Control TEST"
HEADERS = ["Queued At", "Action", "Args", "By", "Status", "Result", "Finished At"]

# Don't auto-run more than this many fixes in one day — a guard against a runaway
# loop (a fix that re-queues itself, a stuck report). Hitting the cap pauses
# auto-run and leaves the rows queued for a human to look at.
DAILY_AUTORUN_CAP = 25
# Generous default — daily_rep_breakdown alone budgets ~130m. `rerun` overrides
# this with the report's own timeout_minutes.
DEFAULT_TIMEOUT_S = 130 * 60
SESSION_HOLDER_LABEL = "com.alphalete.session-holder"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _open(sandbox: bool = False):
    """Open (creating if needed) the control worksheet."""
    tab = SANDBOX_TAB if sandbox else CONTROL_TAB
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=300, cols=len(HEADERS))
        ws.update([HEADERS], "A1")
        return ws


# ---------------------------------------------------------------------------
# Actions — the whitelist. Each takes the row's Args string and returns
# (ok, short_result). Add a new fix = add a function here; nothing else runs.
# ---------------------------------------------------------------------------

def _run_cmd(cmd: list[str], timeout_s: int = DEFAULT_TIMEOUT_S) -> tuple[bool, str]:
    """Run a command in the repo root; return (ok, 'exit N · <tail>')."""
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), timeout=timeout_s,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_s // 60}m"
    except Exception as e:
        return False, f"launch error: {str(e).splitlines()[0][:140]}"
    tail = "\n".join((proc.stdout or "").splitlines()[-3:])[:280]
    return proc.returncode == 0, f"exit {proc.returncode}" + (f" · {tail}" if tail else "")


def _action_rerun(args: str) -> tuple[bool, str]:
    """Re-run one orchestrator report by report_id (e.g. daily_focus)."""
    report_id = (args or "").strip()
    if not report_id:
        return False, "rerun needs a report_id (e.g. daily_focus)"
    cfg = registry.load_config()
    r = cfg.reports.get(report_id)
    if not r:
        known = ", ".join(sorted(cfg.reports)[:10])
        return False, f"unknown report_id {report_id!r}. known: {known} …"
    cmd = [sys.executable, "-m", r.command[0]] + list(r.command[1:]) + list(r.base_args)
    timeout_s = int(getattr(r, "timeout_minutes", 45) or 45) * 60
    return _run_cmd(cmd, timeout_s)


def _action_restart_holder(args: str) -> tuple[bool, str]:
    """Relaunch the ownerville session-holder LaunchAgent on the mini."""
    cmd = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{SESSION_HOLDER_LABEL}"]
    try:
        proc = subprocess.run(cmd, timeout=90, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        return False, f"launch error: {str(e)[:140]}"
    out = (proc.stdout or "").strip()[:160]
    return proc.returncode == 0, f"kickstart exit {proc.returncode}" + (f": {out}" if out else "")


def _action_reseed_appstream(args: str) -> tuple[bool, str]:
    """Open the AppStream login so a HUMAN at the mini clears the Cloudflare
    check. This can't be fully unattended — the Turnstile is bot-detection and
    clearing it automatically is off the table — so this just launches the
    legitimate human-cleared flow."""
    cmd = [sys.executable, "-m", "automations.shared.tableau_patchright",
           "--appstream-login"]
    ok, res = _run_cmd(cmd, timeout_s=12 * 60)
    return ok, res + " (needs a human at the Cloudflare check on the mini)"


def _action_ping(args: str) -> tuple[bool, str]:
    """Liveness check — proves the mini's poller is alive and processing the
    queue. No side effects; used to verify the deploy."""
    import socket
    return True, f"pong from {socket.gethostname()} @ {_now()}"


ACTIONS = {
    "ping": _action_ping,
    "rerun": _action_rerun,
    "restart_holder": _action_restart_holder,
    "reseed_appstream": _action_reseed_appstream,
}


# ---------------------------------------------------------------------------
# Enqueue + poll
# ---------------------------------------------------------------------------

def enqueue(action: str, args: str = "", by: str = "Eve", *, sandbox: bool = False) -> None:
    """Add a fix request to the queue (called by Eve / Megan / the orchestrator)."""
    ws = _open(sandbox)
    ws.append_row([_now(), action, args, by, "queued", "", ""],
                  value_input_option="RAW")
    print(f"[mini_control] queued: {action} {args} (by {by})")


def _set(ws, rownum: int, status: str, result: str = "", finished: bool = False) -> None:
    """Write Status / Result / Finished At (cols E,F,G) for one row, one call."""
    fin = _now() if finished else ""
    ws.update_cells(
        [gspread.Cell(rownum, 5, status),
         gspread.Cell(rownum, 6, (result or "")[:480]),
         gspread.Cell(rownum, 7, fin)],
        value_input_option="RAW",
    )


def _autoruns_today(rows: list[dict]) -> int:
    """How many fixes already ran (or are running) today — for the runaway cap."""
    today = dt.date.today().isoformat()
    return sum(
        1 for r in rows
        if str(r.get("Status", "")).strip().lower() in ("done", "failed", "running")
        and str(r.get("Queued At", "")).startswith(today)
    )


def poll_once(*, dry_run: bool = False, sandbox: bool = False) -> int:
    """One poll pass: run every 'queued' row's whitelisted action. Returns the
    number of rows acted on."""
    ws = _open(sandbox)
    rows = ws.get_all_records()           # list of dicts keyed by header
    cap_used = _autoruns_today(rows)
    acted = 0
    for i, row in enumerate(rows):
        if str(row.get("Status", "")).strip().lower() != "queued":
            continue
        rownum = i + 2                    # +1 header row, +1 for 1-based
        action = str(row.get("Action", "")).strip()
        args = str(row.get("Args", "")).strip()
        handler = ACTIONS.get(action)

        if handler is None:
            _set(ws, rownum, "failed",
                 f"unknown action {action!r}; allowed: {', '.join(ACTIONS)}", finished=True)
            acted += 1
            continue
        if cap_used >= DAILY_AUTORUN_CAP:
            print(f"[mini_control] daily cap ({DAILY_AUTORUN_CAP}) reached — "
                  f"leaving {action} {args} queued for a human")
            continue
        if dry_run:
            print(f"[mini_control] DRY-RUN would run: {action} {args}")
            _set(ws, rownum, "queued", f"[dry-run] would run {action} {args} @ {_now()}")
            continue

        print(f"[mini_control] running: {action} {args}")
        _set(ws, rownum, "running", f"started {_now()}")
        cap_used += 1
        try:
            ok, result = handler(args)
        except Exception as e:
            ok, result = False, f"handler error: {str(e).splitlines()[0][:160]}"
        _set(ws, rownum, "done" if ok else "failed", result, finished=True)
        print(f"[mini_control]   -> {'done' if ok else 'FAILED'}: {result[:160]}")
        acted += 1
    return acted


def poll_loop(interval_s: int = 120, *, dry_run: bool = False, sandbox: bool = False) -> None:
    tab = SANDBOX_TAB if sandbox else CONTROL_TAB
    print(f"[mini_control] poll loop every {interval_s}s on {tab!r}"
          + (" [DRY-RUN]" if dry_run else ""))
    while True:
        try:
            poll_once(dry_run=dry_run, sandbox=sandbox)
        except Exception as e:
            print(f"[mini_control] poll error (continuing): {type(e).__name__}: {str(e)[:160]}")
        time.sleep(interval_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mini remote-control command queue")
    ap.add_argument("--loop", action="store_true", help="poll forever (run on the mini)")
    ap.add_argument("--once", action="store_true", help="poll once and exit")
    ap.add_argument("--enqueue", nargs="+", metavar="ACTION",
                    help="queue an action, e.g. --enqueue rerun daily_focus")
    ap.add_argument("--interval", type=int, default=120, help="loop interval seconds")
    ap.add_argument("--dry-run", action="store_true", help="poll but execute nothing")
    ap.add_argument("--sandbox", action="store_true", help="use the TEST tab")
    a = ap.parse_args(argv)

    if a.enqueue:
        enqueue(a.enqueue[0], " ".join(a.enqueue[1:]), sandbox=a.sandbox)
        return 0
    if a.loop:
        poll_loop(a.interval, dry_run=a.dry_run, sandbox=a.sandbox)
        return 0
    n = poll_once(dry_run=a.dry_run, sandbox=a.sandbox)   # default: one pass
    print(f"[mini_control] acted on {n} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
