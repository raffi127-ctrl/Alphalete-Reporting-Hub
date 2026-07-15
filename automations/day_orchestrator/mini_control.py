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
  update                git pull the latest code onto the mini (remote deploy)
  set_meta_token <tok>  install/refresh the brand-audit Meta page token in keys.json
  set_slack_token <tok> install/refresh the 'Lucy' Slack bot token (xoxb-…) on this machine
  set_gbp_token <json>  install the Google Business Profile OAuth token (gbp-token.json contents)
  restart_holder        relaunch the ownerville session-holder LaunchAgent
  reseed_appstream      open the AppStream login (a human clears Cloudflare)

CLI:
  python -m automations.day_orchestrator.mini_control --loop      # on the mini
  python -m automations.day_orchestrator.mini_control --once
  python -m automations.day_orchestrator.mini_control --enqueue rerun daily_focus

  --dry-run / --sandbox steer THIS tool, and ONLY on the poll side (--loop/--once):
      --dry-run    poll + show what WOULD run, execute nothing
      --sandbox    use the "Mini Control TEST" tab (build/verify safely)

  Everything after `--enqueue <action>` is captured VERBATIM (argparse.REMAINDER)
  and passed through to the report, so a report's OWN flags reach it — crucially
  `--dry-run` there runs the REPORT dry (it is NOT swallowed by the poll-side
  --dry-run above). e.g.
      --enqueue rerun resume_pushing --dry-run   # dry-runs the REPORT (safe probe)
      --enqueue rerun daily_metrics --only churn
  Control flags (--machine/--by/--sandbox) are hoisted out first, so they still
  route mini_control itself even when typed AFTER the action.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shlex
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

# Don't auto-run more than this many SIDE-EFFECTING fixes in one day — a guard
# against a runaway loop (a fix that re-queues itself, a stuck report). Hitting
# the cap pauses auto-run and leaves the rows queued for a human to look at.
# Only the runaway-risk actions count (see PLUMBING_ACTIONS); a hands-on deploy
# day with lots of update/restart/pip_install churn shouldn't trip it.
DAILY_AUTORUN_CAP = 100
# Bounded, idempotent operational actions — NOT runaway risks, so they don't burn
# the daily budget (a multi-person deploy day generates lots of these). The
# budget is meant to bound repeated REPORT runs (rerun), not deploy plumbing.
PLUMBING_ACTIONS = {"ping", "update", "restart_poller", "restart_holder",
                    "pip_install", "watch_test", "diag", "set_sleep",
                    "set_slack_token", "set_gbp_token"}
# Generous default — daily_rep_breakdown alone budgets ~130m. `rerun` overrides
# this with the report's own timeout_minutes.
DEFAULT_TIMEOUT_S = 130 * 60
SESSION_HOLDER_LABEL = "com.alphalete.session-holder"
MINI_CONTROL_LABEL = "com.alphalete.mini-control"   # this poller's own launchd label

# Machine identity — which runner is this? A gitignored `.machine-profile` file
# at the repo root names the profile ("Lucy 1" / "Lucy 2"). Each runner polls its
# OWN control tab so two machines never grab the same queued row. Absent marker →
# "Lucy 1" (the original mini), so its tab + behavior stay exactly as they were.
_MACHINE_MARKER = REPO_ROOT / ".machine-profile"
DEFAULT_MACHINE = "Lucy 1"


def _machine_profile(explicit: str | None = None) -> str:
    """This machine's profile: explicit arg → .machine-profile marker → 'Lucy 1'."""
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        v = _MACHINE_MARKER.read_text().strip()
        if v:
            return v
    except Exception:
        pass
    return DEFAULT_MACHINE


def _control_tab_for(machine: str) -> str:
    """Lucy 1 keeps the original 'Mini Control' tab (backward-compatible); every
    other machine gets its own 'Mini Control - <machine>' tab."""
    machine = (machine or DEFAULT_MACHINE).strip()
    return CONTROL_TAB if machine == DEFAULT_MACHINE else f"{CONTROL_TAB} - {machine}"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _open(sandbox: bool = False, machine: str | None = None):
    """Open (creating if needed) the control worksheet for THIS machine — or the
    shared TEST tab when sandbox."""
    tab = SANDBOX_TAB if sandbox else _control_tab_for(_machine_profile(machine))
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

def _run_cmd(cmd: list[str], timeout_s: int = DEFAULT_TIMEOUT_S,
             log_name: str | None = None) -> tuple[bool, str]:
    """Run a command in the repo root; return (ok, 'exit N · <tail>').

    log_name: write the run's FULL output to output/logs/<log_name> so
    `lucy logtail <log_name>` can read it. The 3-line tail in the result cell is
    routinely useless on a browser report — Playwright's teardown chatter
    ("finished temporary directories cleanup") lands last and buries the actual
    traceback, which cost three blind probes to diagnose a crop bug on
    2026-07-14. The log is the only way to see a mini-only failure from the
    laptop (no SSH), so write it even when the run SUCCEEDS."""
    log_path = None
    if log_name:
        try:
            log_dir = REPO_ROOT / "output" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / log_name
        except Exception:  # noqa: BLE001 — logging must never fail the run
            log_path = None
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), timeout=timeout_s,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True)
    except subprocess.TimeoutExpired as e:
        # A timeout still produced output — persist it, or the slowest failures
        # (the ones most worth debugging) are the ones with no log at all.
        if log_path is not None:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            _write_log(log_path, cmd, out + f"\n\n*** TIMED OUT after {timeout_s}s ***")
        return False, (f"timed out after {timeout_s // 60}m"
                       + (f" · log: {log_path.name}" if log_path else ""))
    except Exception as e:
        return False, f"launch error: {str(e).splitlines()[0][:140]}"
    if log_path is not None:
        _write_log(log_path, cmd, proc.stdout or "")
    tail = "\n".join((proc.stdout or "").splitlines()[-3:])[:280]
    return proc.returncode == 0, (
        f"exit {proc.returncode}"
        + (f" · log: {log_path.name}" if log_path else "")
        + (f" · {tail}" if tail else ""))


def _write_log(path: Path, cmd: list[str], output: str) -> None:
    """Best-effort: full run output to output/logs/, for `lucy logtail`."""
    try:
        path.write_text(f"$ {' '.join(cmd)}\n[{_now()}]\n\n{output}",
                        errors="replace")
    except Exception:  # noqa: BLE001 — logging must never fail the run
        pass


def _action_rerun(args: str) -> tuple[bool, str]:
    """Re-run one orchestrator report by report_id, plus any EXTRA CLI args after
    it — e.g. 'daily_metrics --only churn' re-runs just that one metric, so a
    failure email's fix can rescope the run to only the part that dropped instead
    of re-doing the whole report. shlex so a quoted arg with spaces survives, e.g.
    'opt_phase --only \"Marcellus Butler\"'."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()   # unbalanced quotes → best-effort
    if not parts:
        return False, "rerun needs a report_id (e.g. daily_focus)"
    report_id, extra = parts[0], parts[1:]
    cfg = registry.load_config()
    r = registry.resolve_report(cfg, report_id)   # scheduler OR off-scheduler (e.g. leaders_call)
    if not r:
        known = ", ".join(sorted(cfg.raw.get("reports", {}))[:10])
        return False, f"unknown report_id {report_id!r}. known: {known} …"
    # A stray HUMAN Chrome open on the mini single-instances with our automation
    # Chrome and breaks every browser report ("Opening in existing browser
    # session" — this is what killed daily_rep_breakdown at 4am on 2026-07-05).
    # The orchestrator closes stray Chrome before each browser report, but the
    # manual rerun path bypassed that — so a rerun would just collide again. Run
    # the same guard here for tableau/appstream reports. Best-effort; a guard
    # that crashes the rerun is worse than the collision. [[reference_chrome_collision_guard]]
    if r.source_type in ("tableau", "appstream"):
        try:
            from automations.day_orchestrator import chrome_guard
            chrome_guard.close_stray_chrome()
        except Exception:  # noqa: BLE001 — a guard must never crash the rerun
            pass
    cmd = ([sys.executable, "-m", r.command[0]] + list(r.command[1:])
           + list(r.base_args) + extra)
    timeout_s = int(getattr(r, "timeout_minutes", 45) or 45) * 60

    # Publish the yellow "running" pill BEFORE the run so the Hub shows a manual
    # rerun IN PROGRESS, exactly like the orchestrator does. The rerun path used
    # to only mark DONE at the end, so a report looked idle the whole time it ran
    # (Megan 2026-07-08). Best-effort; publish_running is a no-op (returns None)
    # when the report has no Hub card. [[project_hub_live_running_pill]]
    hub_run_id = None
    try:
        from automations.day_orchestrator import hub_publish
        hub_run_id = hub_publish.publish_running(
            report_id, getattr(r, "display_name", report_id))
    except Exception:  # noqa: BLE001 — Hub publish must never fail the rerun
        hub_run_id = None

    # One log per rerun, timestamped so repeated reruns of the same report don't
    # clobber each other (logtail's newest-match-wins then picks the latest).
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    ok, result = _run_cmd(cmd, timeout_s, log_name=f"rerun-{stamp}-{report_id}.log")

    # Close the pill: flip the SAME running row (via run_id) to success/failed so
    # it never hangs yellow. Mirrors the orchestrator, which marks DONE *and*
    # INCOMPLETE as run (a report that RAN with an acceptable note should show as
    # run, not like it never ran; Megan 2026-07-01) and closes the pill on failure
    # too. Best-effort; a no-op when the report has no Hub card.
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done(
            report_id, getattr(r, "display_name", report_id),
            status=hub_publish.final_status(report_id, ok), run_id=hub_run_id)
    except Exception:  # noqa: BLE001 — Hub publish must never fail the rerun
        pass
    return ok, result


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


def _action_restart_poller(args: str) -> tuple[bool, str]:
    """Kickstart THIS poller (com.alphalete.mini-control) so it reloads its own
    code — deploy a mini_control change with no human at the mini. `kickstart -k`
    SIGKILLs the current process, so run it DETACHED after a short delay: this
    action returns first (poll_once writes its result), THEN the poller is
    replaced with fresh code by launchd. start_new_session so the kickstart child
    isn't in the poller's process group and survives the kill."""
    label = MINI_CONTROL_LABEL
    try:
        subprocess.Popen(
            ["/bin/sh", "-c",
             f"sleep 3; launchctl kickstart -k gui/{os.getuid()}/{label}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't schedule restart: {str(e)[:140]}"
    return True, f"restart scheduled for {label} (~3s) — poller reloads its code"


def _action_watch_test(args: str) -> tuple[bool, str]:
    """Fire appstream_watch's one-off test ping so Megan/Eve can confirm the 6pm
    session-expiry Slack DM actually delivers — WITHOUT waiting for a real lapse
    or being physically at the mini. No side effects beyond the Slack message."""
    cmd = [sys.executable, "-m", "automations.shared.appstream_watch", "--test-ping"]
    return _run_cmd(cmd, timeout_s=120)


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


def _action_diag(args: str) -> tuple[bool, str]:
    """Read-only machine health — diagnose a runner remotely without anyone AT
    the machine (the 'is it asleep / is the poller alive / is the OV session
    fresh' questions we kept hitting). Reports sleep lock, loaded agents, OV
    session age, power, disk. No side effects."""
    import socket
    import shutil
    import time as _t

    def _sh(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=10).stdout
        except Exception as e:  # noqa: BLE001
            return f"(err {type(e).__name__})"

    try:
        prof = _machine_profile()
    except Exception:  # noqa: BLE001
        prof = "?"
    out = [f"{prof} @ {socket.gethostname()} · {_now()}"]
    # macOS shows the `pmset disablesleep 1` lock as `SleepDisabled 1` in
    # `pmset -g`; caffeinate holds sleep off via an idle-sleep assertion. Report
    # whichever is keeping it awake — or warn loudly if NEITHER is.
    sd = next((ln.split()[-1] for ln in _sh(["/usr/bin/pmset", "-g"]).splitlines()
               if "sleepdisabled" in ln.lower()), "0").strip()
    asrt = _sh(["/usr/bin/pmset", "-g", "assertions"]).lower()
    caff = any("systemsleep" in ln and ln.rstrip().endswith("1")
               for ln in asrt.splitlines())
    if sd == "1":
        out.append("sleep: LOCKED OFF (SleepDisabled=1)")
    elif caff:
        out.append("sleep: held off by caffeinate (idle assertion)")
    else:
        out.append("sleep: ⚠️ NOT prevented — this machine may sleep")
    out.append("power: " + " ".join(_sh(["/usr/bin/pmset", "-g", "batt"]).split())[:70])
    ll = _sh(["/bin/launchctl", "list"])
    have = [a for a in ("keep-awake", "session-holder", "mini-control",
                        "day-orchestrator")
            if f"com.alphalete.{a}" in ll]
    out.append("agents: " + (", ".join(have) if have else "NONE loaded"))
    ov = REPO_ROOT / "automations" / "shared" / ".ownerville_storage_state.json"
    if ov.exists():
        out.append(f"OV session: {(_t.time() - ov.stat().st_mtime) / 60:.0f} min old")
    else:
        out.append("OV session: MISSING")
    try:
        out.append(f"disk free: {shutil.disk_usage(str(REPO_ROOT)).free // (1024**3)} GB")
    except Exception:  # noqa: BLE001
        pass
    return True, "\n".join(out)


def _action_set_sleep(args: str) -> tuple[bool, str]:
    """Remotely prevent/allow system sleep via passwordless `sudo pmset` (needs a
    one-time NOPASSWD sudoers entry for pmset on this machine — see
    workflows/setup-new-runner.md). Args: '1'/'off'/'disable' = never sleep
    (default); '0'/'on'/'allow' = allow sleep. Uses `sudo -n` so it fails CLEANLY
    (never hangs on a password prompt) when NOPASSWD isn't configured."""
    v = (args or "1").strip().lower()
    allow = v in ("0", "on", "allow", "enable")
    setting = "0" if allow else "1"
    r = subprocess.run(
        ["/usr/bin/sudo", "-n", "/usr/bin/pmset", "-a", "disablesleep", setting],
        capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return False, (f"sudo pmset failed (exit {r.returncode}): "
                       f"{(r.stdout + r.stderr).strip()[:110]} — set up passwordless "
                       "sudo for pmset (see setup-new-runner.md).")
    return True, f"disablesleep={setting} — sleep {'ALLOWED' if allow else 'PREVENTED'}"


def _action_reboot(args: str) -> tuple[bool, str]:
    """Reboot this machine remotely. The reason it exists: launchd caches the
    timezone at boot and never refreshes it, so after a TZ change every calendar
    job fires at the WRONG time (the mini fired all its jobs +2h — 4am->6am — for
    weeks; 2026-07-10). bootout/bootstrap does NOT clear that; only a reboot does.
    The mini auto-logs-in and reloads its LaunchAgents (poller, holder, keep-awake,
    the 4am orchestrator) on boot, so everything comes back on its own with the
    CORRECT timezone. Detached + delayed a few seconds so this poll writes its
    result to the Sheet BEFORE the box goes down. Tries passwordless `sudo shutdown`
    first (clean, no GUI), then a System Events restart AppleEvent as a fallback."""
    script = (
        "sleep 5; "
        "sudo -n /sbin/shutdown -r now >/dev/null 2>&1 || "
        "sudo -n /sbin/reboot >/dev/null 2>&1 || "
        "osascript -e 'tell application \"System Events\" to restart' >/dev/null 2>&1"
    )
    try:
        subprocess.Popen(["/bin/sh", "-c", script], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't schedule reboot: {str(e)[:140]}"
    return True, ("reboot scheduled (~5s): sudo shutdown -r, else System Events "
                  "restart. Mini auto-logs-in + reloads its agents on boot (fixes "
                  "the cached-timezone +2h drift). Check with `lucy ping` after ~2-3m.")


# Lines worth surfacing when logtail has no explicit grep — the error/failure
# signatures across every report's log (traceback frames, our own ✗/❌ markers,
# HTTP/timeout errors, the opt_all per-step summary).
_LOGTAIL_ERR_RE = re.compile(
    r"traceback|error|exception|failed|timeout|✗|❌|skip-retail|HTTP \d", re.I)


def _action_logtail(args: str) -> tuple[bool, str]:
    """Read a log under output/logs/ and return its most relevant tail — the ONE
    way to see a mini-only log from the laptop (no SSH, no arbitrary shell). READ
    ONLY: it never runs or changes anything.

      logtail <name> [grep] [n]
        name  a bare filename OR substring of one in output/logs (NO path
              separators); newest match wins. '.log' optional. e.g.
              `orch-2026-07-06-alphalete_org_focus`.
        grep  optional case-insensitive substring — only matching lines return.
              Omit to auto-pick error/traceback lines (falls back to plain tail).
        n     max lines to return (default 15, cap 60).

    The result cell holds ~470 chars, so a big log is paged 470 chars at a time:
    re-run with a narrower `grep` (e.g. the exception type) to walk it."""
    import glob
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()   # unbalanced quotes → best-effort
    if not parts:
        return False, "logtail needs a log name (e.g. orch-2026-07-06-alphalete_org_focus)"
    name, grep = parts[0], (parts[1] if len(parts) > 1 else None)
    try:
        n = int(parts[2]) if len(parts) > 2 else 15
    except ValueError:
        n = 15
    n = max(1, min(n, 60))
    # Path safety: bare filename only, and the resolved path MUST stay inside
    # output/logs (defense-in-depth against a crafted glob).
    if "/" in name or "\\" in name or ".." in name:
        return False, "logtail: name must be a bare filename (no path)"
    logs_dir = (REPO_ROOT / "output" / "logs").resolve()
    cands = sorted(glob.glob(str(logs_dir / f"*{name}*")), key=os.path.getmtime)
    cands = [c for c in cands if os.path.isfile(c)]
    if not cands:
        return False, f"no log in output/logs matching {name!r}"
    path = Path(cands[-1])
    try:
        path.resolve().relative_to(logs_dir)
    except ValueError:
        return False, "logtail: refused (path escaped output/logs)"
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception as e:  # noqa: BLE001
        return False, f"read error: {str(e).splitlines()[0][:120]}"
    if grep:
        matched = [l for l in lines if grep.lower() in l.lower()]
    else:
        matched = [l for l in lines if _LOGTAIL_ERR_RE.search(l)]
    if not matched:
        matched = lines   # nothing matched → plain tail so the call still helps
    picked = matched[-n:]
    head = (f"{path.name} · {len(matched)} match/{len(lines)} lines · "
            f"last {len(picked)}:\n")
    body = "\n".join(l.strip()[:200] for l in picked)
    return True, (head + body)[:470]


# Packages the mini may auto-install into the report venv — an ALLOWLIST, never
# arbitrary pip (that would defeat the whole no-arbitrary-shell whitelist). These
# are undeclared deps that can go missing on a venv rebuild; reportlab is the
# Leader's Call PDF library (missing it silently blocks the recognition DM — the
# run still exits 0 because PDF/Slack errors don't fail the pull).
PIP_ALLOWLIST = {"reportlab"}


def _action_pip_install(args: str) -> tuple[bool, str]:
    """Install an ALLOWLISTED package into the report venv (the poller's own
    python). Refuses anything not in PIP_ALLOWLIST."""
    pkg = (args or "").strip()
    if pkg not in PIP_ALLOWLIST:
        allowed = ", ".join(sorted(PIP_ALLOWLIST)) or "(none)"
        return False, f"pip_install refused {pkg!r}; allowed: {allowed}"
    ok, res = _run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", pkg],
                       timeout_s=8 * 60)
    if ok:
        # Confirm it actually imports now (a wheel-build failure can exit 0-ish).
        chk, _ = _run_cmd([sys.executable, "-c", f"import {pkg}"], timeout_s=60)
        res += " · import OK" if chk else " · ⚠ installed but import still fails"
    return ok, res


def _action_update(args: str) -> tuple[bool, str]:
    """git pull the repo on the mini — deploy new code WITHOUT being physically
    at it. --ff-only so it never creates a merge commit (fails cleanly if the
    mini's checkout has diverged, rather than tangling it). The next scheduled
    run / report picks up the new code; a poller-code change needs a
    restart_holder after. Read the result with `lucy status`."""
    return _run_cmd(["git", "-C", str(REPO_ROOT), "pull", "--ff-only"],
                    timeout_s=120)


def _action_set_meta_token(args: str) -> tuple[bool, str]:
    """Install/refresh the Meta (Facebook + Instagram) page access token in the
    mini's ~/.config/brand-audit/keys.json, so the noon brand-audit Social
    section can pull IG data with no human at the mini. The token is passed as
    the Args (a never-expiring system-user token, starts with 'EAA'). Backs up
    keys.json first, rewrites ONLY facebook_page_token (every other key is left
    untouched), then verifies against the IG account already on file and reports
    the follower count as proof. NEVER echoes the token back into the result.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell after this shows 'done' (the queuer does this from the laptop)."""
    token = (args or "").strip()
    if not token.startswith("EAA"):
        return False, "set_meta_token needs a Meta token (starts with 'EAA') as the Args"
    import json
    import shutil
    keys_path = Path.home() / ".config" / "brand-audit" / "keys.json"
    if not keys_path.exists():
        return False, f"keys.json not found at {keys_path} — seed the base keys first"
    try:
        data = json.loads(keys_path.read_text())
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't read keys.json: {str(e).splitlines()[0][:120]}"
    # back up before touching a credential file (never clobber blindly)
    stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
    try:
        shutil.copy2(keys_path, keys_path.parent / f"keys.json.bak.{stamp}")
    except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
        pass
    data["facebook_page_token"] = token
    try:
        keys_path.write_text(json.dumps(data, indent=2))
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write keys.json: {str(e).splitlines()[0][:120]}"
    # verify against the IG business account already on file — proof it works,
    # surfaced in `lucy status`. Best-effort: a verify hiccup doesn't undo a
    # write (the old token was dead anyway), it's just reported.
    ig = data.get("ig_business_account_id")
    if not ig:
        return True, "facebook_page_token written (no ig_business_account_id to verify against)"
    try:
        import requests
        r = requests.get(f"https://graph.facebook.com/v23.0/{ig}",
                         params={"access_token": token,
                                 "fields": "followers_count,username"},
                         timeout=20).json()
    except Exception as e:  # noqa: BLE001
        return True, f"token written; verify call errored: {str(e).splitlines()[0][:100]}"
    if "error" in r:
        return False, ("token written but IG check FAILED: "
                       + str(r["error"].get("message", ""))[:140])
    return True, (f"token installed + verified: @{r.get('username')} "
                  f"{r.get('followers_count')} followers")


def _action_set_slack_token(args: str) -> tuple[bool, str]:
    """Install/refresh the 'Lucy' Slack BOT token on THIS machine so reports that
    DM/post as Lucy run unattended here (e.g. carlos_captainship_bonus DMing the
    PDF to Carlos + Maud from Lucy 2 — the first Slack-posting report on that
    runner). Token is passed as the Args (a bot token, starts 'xoxb-') and written
    to ~/.config/recruiting-report/slack-bot-token — the path slack_metrics_post
    reads. Backs up any existing token first, verifies with auth_test (reading the
    file we just wrote, exactly as the reports will), and NEVER echoes the token
    back into the result.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell after this shows 'done' (the queuer does this from the laptop)."""
    import shutil
    token = (args or "").strip()
    if not token.startswith("xoxb-"):
        return False, "set_slack_token needs a Slack BOT token (starts with 'xoxb-') as the Args"
    path = Path.home() / ".config" / "recruiting-report" / "slack-bot-token"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"slack-bot-token.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(token, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify by reading the file back through the SAME client the reports use —
    # proof it works, surfaced in `lucy status`. Never echo the token itself.
    try:
        from automations.shared import slack_metrics_post as smp
        who = smp._bot_client().auth_test()
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but auth_test errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    if not who.get("ok"):
        return False, f"token written but auth_test not ok: {str(who)[:120]}"
    return True, (f"Lucy Slack token installed + verified: authed as "
                  f"{who.get('user')} ({who.get('user_id')}) in team {who.get('team')}")


def _action_set_gbp_token(args: str) -> tuple[bool, str]:
    """Install the Google Business Profile OAuth token on THIS machine so the
    noon review-replies run can read reviews + post replies unattended. The Args
    is the CONTENTS of ~/.config/brand-audit/gbp-token.json (a JSON object with a
    refresh_token; it self-contains client_id/secret so no oauth-client.json is
    needed here). Backs up any existing token, writes it, then verifies by
    resolving the configured location. NEVER echoes the token.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell after this shows 'done' (the queuer does this from the laptop)."""
    import json
    import shlex
    import shutil
    # `lucy` shlex-joins multi-char args before the Sheet round-trip, so undo it
    # to recover the raw JSON (mirrors _action_rerun's shlex.split pairing).
    raw = (args or "").strip()
    try:
        parts = shlex.split(raw)
        blob = parts[0].strip() if parts else raw
    except Exception:  # noqa: BLE001
        blob = raw
    if not blob.startswith("{"):
        return False, "set_gbp_token needs the gbp-token.json CONTENTS (a JSON object) as Args"
    try:
        parsed = json.loads(blob)
    except Exception as e:  # noqa: BLE001
        return False, f"Args isn't valid JSON: {str(e).splitlines()[0][:120]}"
    if not parsed.get("refresh_token"):
        return False, "token JSON has no refresh_token — re-authorize and pass the whole file"
    path = Path.home() / ".config" / "brand-audit" / "gbp-token.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"gbp-token.json.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify: resolve the configured location through the SAME client the noon
    # job uses — proof it works, surfaced in `lucy status`. Never echo the token.
    try:
        from automations.brand_audit import gbp_api
        from automations.brand_audit.config import GBP_LOCATION_PATH
        if not GBP_LOCATION_PATH:
            return True, "gbp token written (GBP_LOCATION_PATH not set — can't verify a location)"
        sample = gbp_api.list_reviews(GBP_LOCATION_PATH, limit=1)
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but verify errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    return True, (f"GBP token installed + verified: location reachable "
                  f"(fetched {len(sample)} review as a check)")


ACTIONS = {
    "ping": _action_ping,
    "logtail": _action_logtail,
    "pip_install": _action_pip_install,
    "rerun": _action_rerun,
    "update": _action_update,
    "set_meta_token": _action_set_meta_token,
    "set_slack_token": _action_set_slack_token,
    "set_gbp_token": _action_set_gbp_token,
    "restart_holder": _action_restart_holder,
    "restart_poller": _action_restart_poller,
    "reseed_appstream": _action_reseed_appstream,
    "watch_test": _action_watch_test,
    "diag": _action_diag,
    "set_sleep": _action_set_sleep,
    "reboot": _action_reboot,
}


# ---------------------------------------------------------------------------
# Enqueue + poll
# ---------------------------------------------------------------------------

def enqueue(action: str, args: str = "", by: str = "Eve", *, sandbox: bool = False,
            machine: str | None = None) -> None:
    """Add a fix request to the queue (called by Eve / Megan / the orchestrator).
    Targets `machine`'s tab (default 'Lucy 1' → the original 'Mini Control')."""
    ws = _open(sandbox, machine)
    ws.append_row([_now(), action, args, by, "queued", "", ""],
                  value_input_option="RAW")
    print(f"[mini_control] queued: {action} {args} (by {by}) "
          f"→ {_control_tab_for(_machine_profile(machine))}")


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
    """How many SIDE-EFFECTING fixes already ran (or are running) today — for the
    runaway cap. PLUMBING_ACTIONS (ping, update, restart_*, pip_install, …) are
    bounded/idempotent deploy churn, not runaway risks, so they're excluded: a
    hands-on multi-person deploy day shouldn't burn the budget that's meant to
    bound repeated REPORT runs (rerun)."""
    today = dt.date.today().isoformat()
    return sum(
        1 for r in rows
        if str(r.get("Status", "")).strip().lower() in ("done", "failed", "running")
        and str(r.get("Queued At", "")).startswith(today)
        and str(r.get("Action", "")).strip().lower() not in PLUMBING_ACTIONS
    )


def poll_once(*, dry_run: bool = False, sandbox: bool = False,
              machine: str | None = None) -> int:
    """One poll pass: run every 'queued' row's whitelisted action. Returns the
    number of rows acted on."""
    ws = _open(sandbox, machine)
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


def _git_head() -> "str | None":
    """Current repo commit, or None if git can't be read. Used to self-reload the
    poller when `lucy update` advances HEAD."""
    try:
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


# Daily schedule reconcile — the DRIFT-IMMUNE anchor for the 4am start. Every
# timed report is a launchd StartCalendarInterval job that can drift (launchd keeps
# a stale in-memory schedule when a `git pull` updates the plist FILE) — that's the
# 4am->6am recurrence. The com.alphalete.orchestrator-schedule-guard fixes it, but
# it is ITSELF a calendar job that could drift. THIS poller is KeepAlive (no
# calendar → cannot drift; it ran every command all day), so reconciling the
# schedules from HERE is the reliable belt the calendar guard can't be. Runs once
# per day, on the first poll in the 1–2am window (well before the 3am/4am jobs).
_RECONCILE_HOURS = (1, 2)


def _maybe_reconcile_schedules() -> None:
    """Once/day from the always-on poller: re-bootstrap every timed LaunchAgent's
    schedule so launchd can never hold a stale one. Per-date marker (written FIRST
    so a slow/failed run can't loop every 2 min); the 2:45 calendar guard is the
    backup if this ever misses. Best-effort — never raises into the poll loop."""
    now = dt.datetime.now()
    if now.hour not in _RECONCILE_HOURS:
        return
    marker_dir = REPO_ROOT / "output" / "day_state"
    marker = marker_dir / f".schedule_reconciled_{now.date().isoformat()}"
    if marker.exists():
        return
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(now.isoformat())
    print(f"[mini_control] daily schedule reconcile (drift-immune anchor) @ {now.isoformat()}")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "automations.day_orchestrator.schedule_guard"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600)
        print(f"[mini_control]   reconcile exit {r.returncode}: {(r.stdout or '')[-400:]}")
    except Exception as e:  # noqa: BLE001 — a reconcile hiccup must not stall polling
        print(f"[mini_control]   reconcile error: {type(e).__name__}: {str(e)[:160]}")


def poll_loop(interval_s: int = 120, *, dry_run: bool = False, sandbox: bool = False,
              machine: str | None = None) -> None:
    mach = _machine_profile(machine)
    tab = SANDBOX_TAB if sandbox else _control_tab_for(mach)
    print(f"[mini_control] poll loop every {interval_s}s on {tab!r} (machine {mach!r})"
          + (" [DRY-RUN]" if dry_run else ""))
    startup_head = _git_head()
    while True:
        # Self-reload: if `lucy update` advanced the repo, re-exec with the FRESH
        # code at this safe boundary (between polls, nothing in flight) so a
        # mini_control change (a new action, a parsing fix) deploys with no manual
        # poller restart. Guarded so a git hiccup (None) never triggers a spurious
        # reload; os.execv keeps the same PID so launchd KeepAlive is untouched.
        head = _git_head()
        if head and startup_head and head != startup_head:
            print(f"[mini_control] repo advanced {startup_head[:7]}->{head[:7]} — "
                  f"reloading poller with fresh code")
            argv = [sys.executable, "-u", "-m",
                    "automations.day_orchestrator.mini_control",
                    "--loop", "--interval", str(interval_s)]
            if sandbox:
                argv.append("--sandbox")
            if dry_run:
                argv.append("--dry-run")
            os.execv(sys.executable, argv)
        try:
            poll_once(dry_run=dry_run, sandbox=sandbox, machine=mach)
        except Exception as e:
            print(f"[mini_control] poll error (continuing): {type(e).__name__}: {str(e)[:160]}")
        # Drift-immune daily schedule reconcile (no-op except the first poll in the
        # 1-2am window). Kept OUT of the try above so its own guard applies, but it
        # never raises anyway.
        if not (dry_run or sandbox):
            _maybe_reconcile_schedules()
        time.sleep(interval_s)


def print_status(n: int = 10, *, sandbox: bool = False, machine: str | None = None) -> None:
    """Print the last N queue rows + their results to the terminal, so you can
    check what the mini did WITHOUT opening the Sheet. Newest row last (right
    above your prompt)."""
    ws = _open(sandbox, machine)
    rows = ws.get_all_records()
    if not rows:
        print("(no commands on the Mini Control queue yet)")
        return
    recent = rows[-n:]
    icons = {"done": "✓", "failed": "✗", "running": "…", "queued": "•"}
    print(f"Last {len(recent)} Mini Control command(s) — newest last:\n")
    for row in recent:
        status = str(row.get("Status", "")).strip()
        icon = icons.get(status.lower(), "?")
        action = str(row.get("Action", "")).strip()
        args = str(row.get("Args", "")).strip()
        by = str(row.get("By", "")).strip()
        result = str(row.get("Result", "")).strip()
        when = (str(row.get("Finished At", "")).strip()
                or str(row.get("Queued At", "")).strip())
        head = f"{icon} {status.lower():<7} {action} {args}".rstrip()
        if by:
            head += f"  (by {by})"
        print(head)
        if result:
            print(f"      {result}")
        if when:
            print(f"      {when}")
    print()


def print_help() -> None:
    """Friendly terminal cheat-sheet: the actions + the live report list, so the
    name in the daily email maps straight to the `lucy rerun <id>` to type."""
    print(
        "lucy — control the Mac mini from your terminal.\n\n"
        "  lucy ping                 is the mini awake?  (look for 'pong')\n"
        "  lucy status               show the last 10 commands + their results\n"
        "  lucy status 25            show the last 25\n"
        "  lucy rerun <report_id>    re-run a report that failed in the daily email\n"
        "  lucy logtail <name>       show the tail of a mini log in output/logs\n"
        "  lucy update               git pull the latest code onto the mini\n"
        "  lucy restart_holder       restart the session keep-alive\n"
        "  lucy diag                 machine health: sleep, agents, session, disk\n"
        "  lucy set_sleep 1|0        prevent (1) / allow (0) sleep (needs NOPASSWD pmset)\n"
        "  lucy reseed_appstream     open AppStream login (needs a human AT the mini)\n"
        "  lucy watch_test           send a test of the 6pm session-expiry Slack ping\n"
        "  lucy help                 show this\n\n"
        "After any command, run 'lucy status' to see if it worked (done / failed).\n"
    )
    try:
        from automations.day_orchestrator import registry
        reports = list(registry.load_config().reports.items())
    except Exception as e:  # noqa: BLE001
        print(f"(couldn't load the report list: {e})")
        return
    print("Re-run a report — match the name in the email to the id:\n")
    width = max((len(rid) for rid, _ in reports), default=12)
    for rid, r in reports:
        name = getattr(r, "display_name", "") or rid
        print(f"  lucy rerun {rid:<{width}}   {name}")
    print()


# Reserved control flags — they steer mini_control ITSELF (which tab, who queued,
# sandbox), never a report's own args. --enqueue uses argparse.REMAINDER so report
# flags (--dry-run/--only/--week) pass through VERBATIM; the downside of REMAINDER
# is it also swallows these control flags when they TRAIL the action — e.g.
# `lucy rerun X --machine "Lucy 2"` (the lucy fn appends the user's words after
# --enqueue), which would silently queue to Lucy 1 instead of Lucy 2. So hoist any
# control flags to the FRONT before parsing, wherever the user put them, while
# everything else stays in the REMAINDER for the report.
_VALUE_CONTROL_FLAGS = ("--machine", "--by")   # take a value
_BOOL_CONTROL_FLAGS = ("--sandbox",)           # bare toggle


def _hoist_control_flags(argv: List[str]) -> List[str]:
    hoisted: List[str] = []
    rest: List[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in _VALUE_CONTROL_FLAGS and i + 1 < len(argv):
            hoisted += [tok, argv[i + 1]]
            i += 2
            continue
        if any(tok.startswith(f + "=") for f in _VALUE_CONTROL_FLAGS):
            hoisted.append(tok)
            i += 1
            continue
        if tok in _BOOL_CONTROL_FLAGS:
            hoisted.append(tok)
            i += 1
            continue
        rest.append(tok)
        i += 1
    return hoisted + rest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mini remote-control command queue")
    ap.add_argument("--loop", action="store_true", help="poll forever (run on the mini)")
    ap.add_argument("--once", action="store_true", help="poll once and exit")
    ap.add_argument("--enqueue", nargs=argparse.REMAINDER, metavar="ACTION",
                    help="queue an action + its args, e.g. --enqueue rerun "
                         "daily_focus. REMAINDER: everything after --enqueue is "
                         "captured VERBATIM, so report flags (--dry-run, --only, "
                         "--week) pass through to the report instead of being "
                         "eaten by mini_control's own --dry-run/--sandbox. Control "
                         "flags (--machine/--by/--sandbox) are hoisted out first, "
                         "so they still route correctly even after the action.")
    ap.add_argument("--by", default=os.environ.get("MINI_BY", "Eve"),
                    help="who queued this — the audit-log 'By' column (or set "
                         "MINI_BY in the shell). Default: Eve.")
    ap.add_argument("--actions", action="store_true",
                    help="print the cheat-sheet + the live report list and exit")
    ap.add_argument("--status", nargs="?", type=int, const=10, metavar="N",
                    help="print the last N queue rows + their results and exit "
                         "(default 10) — check outcomes without the Sheet")
    ap.add_argument("--interval", type=int, default=120, help="loop interval seconds")
    ap.add_argument("--dry-run", action="store_true", help="poll but execute nothing")
    ap.add_argument("--sandbox", action="store_true", help="use the TEST tab")
    ap.add_argument("--machine", default=None,
                    help="target machine profile, e.g. 'Lucy 2'. Enqueue side: "
                         "which runner's tab to queue to (default 'Lucy 1'). Loop "
                         "side: normally omitted — reads the .machine-profile marker.")
    raw = list(sys.argv[1:] if argv is None else argv)
    a = ap.parse_args(_hoist_control_flags(raw))

    if a.actions:
        print_help()
        return 0
    if a.status is not None:
        print_status(a.status, sandbox=a.sandbox, machine=a.machine)
        return 0
    if a.enqueue:
        # shlex.join (paired with _action_rerun's shlex.split) so a quoted
        # multi-word arg survives the Sheet round-trip, e.g.
        # `lucy rerun opt_phase --only "Marcellus Butler"` stays ONE token.
        enqueue(a.enqueue[0], shlex.join(a.enqueue[1:]), by=a.by,
                sandbox=a.sandbox, machine=a.machine)
        return 0
    if a.loop:
        poll_loop(a.interval, dry_run=a.dry_run, sandbox=a.sandbox, machine=a.machine)
        return 0
    n = poll_once(dry_run=a.dry_run, sandbox=a.sandbox, machine=a.machine)   # default: one pass
    print(f"[mini_control] acted on {n} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
