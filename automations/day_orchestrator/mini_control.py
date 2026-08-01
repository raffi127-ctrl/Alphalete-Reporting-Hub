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
  git_status            READ-ONLY: branch, HEAD, local edits, what blocks a pull
  git_diff [path]       READ-ONLY: the CONTENT of this machine's uncommitted
                        edits (git_status gives names only). Use before pulling
                        machine-only code back into the repo.
  git_stash [label]     park uncommitted TRACKED edits so a blocked update can
                        run. Recoverable (git stash pop); never discards.
  set_meta_token <tok>  install/refresh the brand-audit Meta page token in keys.json
  set_slack_token <tok> install/refresh the 'Lucy' Slack BOT token (xoxb-…) on this machine
  set_slack_user_token <tok>  install the 'Lucy' USER token (xoxp-…) — the one
                        channel/thread posts actually use
  set_dd_bot_token <tok>  install Jiraiya's BOT token (xoxb-…) — the always-on
                        listener that serves /dd + the Promotion Check-In buttons
  set_dd_app_token <tok>  install Jiraiya's APP-LEVEL token (xapp-…) for Socket Mode
  set_gbp_token <json>  install the Google Business Profile OAuth token (gbp-token.json contents)
  set_gmail_token <json>  install the gmail.compose token (gmail-token.json contents)
                        so draft-creating reports (captainship_drafts) can run
                        unattended. Verifies the mailbox is alphaletereporting@.
  applicant_key [remove]  is the Applicant Tracker service-account key on THIS
                        machine? `remove` deletes it + every .bak copy. Never
                        prints key material. Re-push with
                        set_applicant_service_account.
  restart_holder        relaunch the ownerville session-holder LaunchAgent
  reseed_appstream      open the AppStream login (a human clears Cloudflare)
  sheets_login [check]  the Sales Board screenshot profile: 'check' probes it
                        headlessly; bare opens the Google login for a human
  set_sheets_cookies <json>  replay an exported Google session into that
                        profile, for a runner nobody can sit at. Source it with
                        `sheet_shot export-cookies` on a signed-in machine.

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
PLUMBING_ACTIONS = {"ping", "screendrive", "update", "restart_poller", "restart_holder",
                    "pip_install", "playwright_install", "set_applicant_service_account",
                    "applicant_key", "watch_test", "diag", "set_sleep",
                    "set_slack_token", "set_gbp_token", "set_gmail_token",
                    "set_dd_bot_token", "set_dd_app_token", "install_jiraiya",
                    "set_contacts_token", "set_contacts_ro_token",
                    "sheets_login", "set_sheets_cookies", "sheets_whoami",
                    "clear_untracked"}
# Generous default — daily_rep_breakdown alone budgets ~130m. `rerun` overrides
# this with the report's own timeout_minutes.
DEFAULT_TIMEOUT_S = 130 * 60
SESSION_HOLDER_LABEL = "com.alphalete.session-holder"
MINI_CONTROL_LABEL = "com.alphalete.mini-control"   # this poller's own launchd label
HUB_WATCH_LABEL = "com.alphalete.hub-watch"          # the Hub change-watcher

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


def _action_onboard_apply(args: str) -> tuple[bool, str]:
    """onboard_apply <kind> <key> [--post] [--dry-run]: materialize a pending
    enrollment from the onboarding Sheet into the working tree (apply --write) so
    the office joins the morning run — and, with --post, immediately run its
    report so it posts to its channel.

    <kind> = 'metrics' (D2D/B2B office metrics) | 'tracker' (Tableau trackers).
    The onboarding forms enqueue this on submit (wire only) and from their 'Post
    now' button (--post). apply reads the 'Office/Tracker Onboarding' tab (the
    source of truth), so the office need not be committed yet — this is the same
    apply Megan runs by hand, on the mini where the Tableau/Slack sessions live.
    Durability (commit to origin) stays a laptop step; the working-tree apply is
    enough for the mini's own morning run, and `update` autostashes it."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    post = "--post" in parts
    dry = "--dry-run" in parts
    parts = [p for p in parts if not p.startswith("--")]
    if len(parts) < 2:
        return False, "onboard_apply needs '<kind> <key>' (kind=metrics|tracker)"
    kind, key = parts[0].strip().lower(), parts[1].strip()

    try:
        from automations.recruiting_report.fill import _client
        gc = _client()
    except Exception as e:  # noqa: BLE001
        return False, f"no Sheets client: {type(e).__name__}: {str(e)[:120]}"

    if kind in ("metrics", "office", "d2d", "b2b"):
        from automations.office_onboarding import store as _st, apply as _ap
        _st.set_client(gc)
    elif kind in ("tracker", "trackers"):
        from automations.tracker_onboarding import store as _st, apply as _ap
        _st.set_client(gc)
    else:
        return False, f"unknown kind {kind!r} (expected metrics|tracker)"

    rc = _ap.main(["--only", key, "--write"])
    if rc != 0:
        return False, f"apply({kind}) failed for {key!r} (rc={rc}) — not posting"
    if not post:
        return True, f"wired {key} ({kind}) into the working tree — joins the next run"

    # Build the post command. Metrics resolves the freshly-written schedule entry
    # so D2D (office_metrics.runner) AND B2B (its own runner) each post exactly as
    # the 4am flow would. Trackers post via the org filter (no per-office entry).
    if kind in ("tracker", "trackers"):
        run_cmd = [sys.executable, "-u", "-m",
                   "automations.tableau_screenshots.run", "--orgs", key]
        if dry:
            run_cmd.append("--dry-run")
    else:
        report_id = f"{key}_metrics"
        r = registry.resolve_report(registry.load_config(), report_id)
        if not r:
            return False, (f"wired {key}, but no schedule entry {report_id!r} to "
                           "post from — run it from the office's card")
        run_cmd = ([sys.executable, "-m", r.command[0]] + list(r.command[1:])
                   + list(r.base_args))
        if dry:
            run_cmd = [a for a in run_cmd if a != "--live"] + ["--dry-run"]

    # --post: run the office's report now so it lands in its channel. Close a
    # stray human Chrome first (same guard as rerun) so a browser report doesn't
    # collide. [[reference_chrome_collision_guard]]
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome()
    except Exception:  # noqa: BLE001 — a guard must never crash the run
        pass
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    ok, result = _run_cmd(run_cmd, 60 * 60,
                          log_name=f"onboard-{stamp}-{kind}-{key}.log")
    verb = "dry-ran" if dry else ("posted" if ok else "post FAILED for")
    return ok, f"wired + {verb} {key} → {result}"


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


def _action_restart_hub(args: str) -> tuple[bool, str]:
    """Bounce the Streamlit Hub so freshly-pulled card/code changes actually
    load — the Hub caches code in memory with the file watcher OFF, and the
    post-merge hook that normally bounces it is a LOCAL git hook not every
    clone has (bit us 2026-07-18: new card pulled, Hub kept serving the old
    code). Runs deploy/restart_hub_if_running.sh, which is a no-op when no
    Hub holds :8501 and never starts one that wasn't already running."""
    script = REPO_ROOT / "deploy" / "restart_hub_if_running.sh"
    if not script.exists():
        return False, f"missing {script.name}"
    try:
        proc = subprocess.run(["/bin/bash", str(script)], timeout=120,
                              cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
    except Exception as e:  # noqa: BLE001
        return False, f"restart_hub error: {str(e)[:140]}"
    out = (proc.stdout or "").strip()[-200:]
    return proc.returncode == 0, (f"exit {proc.returncode}"
                                  + (f": {out}" if out else " — hub bounced"
                                     " (or no hub was running)"))


def _action_install_hub_watch(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the Hub change-watcher LaunchAgent on THIS machine
    — deploy the on-every-Hub-change email notifier remotely, no human at the
    mini. Steps, in order:
      1. Regenerate deploy/com.alphalete.hub-watch.plist with the mini's repo
         path → ~/Library/LaunchAgents, and plutil-lint it.
      2. Send ONE live confirmation email — proves SMTP works from here
         end-to-end; if it fails we DON'T go live (a broken credential is caught
         at install, not silently on the first real change).
      3. `--init` both watchers so the first live poll doesn't email a backlog.
      4. bootout (if loaded) + enable + bootstrap; report the loaded state.
    Run `update` (git pull) + `restart_poller` first so this action exists in the
    running poller. Idempotent — safe to re-run to redeploy after a plist change."""
    uid = os.getuid()
    label = HUB_WATCH_LABEL
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "hub_watch_10min.sh"
    dst_plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not src_plist.exists() or not wrapper.exists():
        return False, (f"missing {src_plist.name} or {wrapper.name} — run "
                       "`update` first to pull them")

    # 1) plist with THIS machine's path (same replace trick as the other agents).
    try:
        text = src_plist.read_text().replace(
            "/Users/megan/1st Claude Folder", str(REPO_ROOT))
        dst_plist.parent.mkdir(parents=True, exist_ok=True)
        dst_plist.write_text(text)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write plist: {str(e).splitlines()[0][:140]}"
    lint = subprocess.run(["plutil", "-lint", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if lint.returncode != 0:
        return False, f"plist lint failed: {(lint.stdout or '')[:160]}"
    try:
        os.chmod(wrapper, 0o755)
    except Exception:  # noqa: BLE001
        pass

    # 2) live confirmation email — end-to-end SMTP proof from this machine.
    try:
        from automations.shared import hub_notify_email, hub_identity
        host = hub_identity.machine_name()   # friendly runner name, e.g. "Lucy 1"
        hub_notify_email.send_html(
            "✅ Hub change-watcher installed",
            f'<p>The Hub change-watcher is now installed on <b>{host}</b>. '
            "You'll get an email whenever Hub code or a card changes — a commit "
            "pushed to the repo, or a card published/edited through the Hub. "
            "This is a one-time install confirmation.</p>",
            f"Hub change-watcher installed on {host} — you'll be emailed on "
            "every Hub code/card change (git push or Hub upload).",
            tag="hub-watch-installed")
    except Exception as e:  # noqa: BLE001
        return False, ("plist OK but the confirmation email FAILED — SMTP/creds "
                       "broken here, NOT going live: "
                       f"{type(e).__name__}: {str(e).splitlines()[0][:120]}")

    # 3) snapshot current state BEFORE going live (no backlog blast).
    p_ok, _ = _run_cmd([sys.executable, "-m", "automations.hub_push_watch.run",
                        "--init"], timeout_s=120)
    l_ok, _ = _run_cmd([sys.executable, "-m", "automations.hub_library_watch.run",
                        "--init"], timeout_s=120)

    # 4) (re)bootstrap the agent.
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if boot.returncode != 0:
        return False, (f"snapshots push={'ok' if p_ok else 'FAIL'} "
                       f"lib={'ok' if l_ok else 'FAIL'}; bootstrap FAILED: "
                       f"{(boot.stdout or '').strip()[:150]}")
    pr = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    state = next((ln.strip() for ln in (pr.stdout or "").splitlines()
                  if "state =" in ln), "loaded")
    return True, (f"installed {label} · {state} · confirmation email sent · "
                  f"snapshots push={'ok' if p_ok else 'FAIL'} "
                  f"lib={'ok' if l_ok else 'FAIL'}")


def _action_install_lucy2_digest(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the Lucy 2 daily summary LaunchAgent
    (com.alphalete.lucy2-digest) on THIS machine — meant for LUCY 1, which
    generates Lucy 2's 'what ran' summary from the shared Hub Activity log (so
    Lucy 2 is never touched). Regenerates the plist for the mini's path, runs a
    --dry-run smoke test (proves the read + render work, no email), then
    bootstraps it (noon daily). Run `update` + `restart_poller` first so this
    action exists in the running poller."""
    uid = os.getuid()
    label = "com.alphalete.lucy2-digest"
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "lucy2_digest_daily.sh"
    dst_plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not src_plist.exists() or not wrapper.exists():
        return False, (f"missing {src_plist.name} or {wrapper.name} — run "
                       "`update` first to pull them")
    try:
        text = src_plist.read_text().replace(
            "/Users/megan/1st Claude Folder", str(REPO_ROOT))
        dst_plist.parent.mkdir(parents=True, exist_ok=True)
        dst_plist.write_text(text)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write plist: {str(e).splitlines()[0][:140]}"
    lint = subprocess.run(["plutil", "-lint", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if lint.returncode != 0:
        return False, f"plist lint failed: {(lint.stdout or '')[:160]}"
    try:
        os.chmod(wrapper, 0o755)
    except Exception:  # noqa: BLE001
        pass

    # Smoke test — build the email to an .eml without sending, proving the Hub
    # Activity read + render + Lucy 2 hostname filter work here.
    smoke_ok, smoke = _run_cmd(
        [sys.executable, "-m", "automations.machine_digest.run", "--dry-run",
         "--host", "Carloss-Mac-mini-2", "--label", "Lucy 2"],
        timeout_s=120, log_name="lucy2-digest-install-smoke.log")
    if not smoke_ok:
        return False, f"smoke test failed — NOT going live: {smoke[:150]}"

    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if boot.returncode != 0:
        return False, f"smoke ok; bootstrap FAILED: {(boot.stdout or '').strip()[:150]}"
    return True, (f"installed {label} (noon daily, reports Lucy 2 from here) · "
                  f"smoke test ok · {smoke[:80]}")


def _action_install_card_scheduler(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the card scheduler on THIS machine — auto-runs the
    uploaded Hub cards assigned to this runner (Lucy 1 / Lucy 2) at their
    scheduled time.

    Defaults to OBSERVE mode (logs "WOULD run X", executes nothing). Pass `live`
    as the args to actually run due cards:  `lucy install_card_scheduler live`.
    Re-run with/without `live` to flip modes. Run `update` + `restart_poller`
    first so this action exists in the running poller."""
    uid = os.getuid()
    label = "com.alphalete.card-scheduler"
    live = (args or "").strip().lower() == "live"
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "card_scheduler_10min.sh"
    dst_plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not src_plist.exists() or not wrapper.exists():
        return False, (f"missing {src_plist.name} or {wrapper.name} — run "
                       "`update` first to pull them")
    try:
        text = src_plist.read_text().replace(
            "/Users/megan/1st Claude Folder", str(REPO_ROOT))
        if live:
            # flip the committed CARD_SCHEDULER_LIVE 0 -> 1
            text = text.replace(
                "<key>CARD_SCHEDULER_LIVE</key>\n        <string>0</string>",
                "<key>CARD_SCHEDULER_LIVE</key>\n        <string>1</string>")
        dst_plist.parent.mkdir(parents=True, exist_ok=True)
        dst_plist.write_text(text)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write plist: {str(e).splitlines()[0][:140]}"
    lint = subprocess.run(["plutil", "-lint", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if lint.returncode != 0:
        return False, f"plist lint failed: {(lint.stdout or '')[:160]}"
    try:
        os.chmod(wrapper, 0o755)
    except Exception:  # noqa: BLE001
        pass

    # Smoke test in OBSERVE mode regardless of live — proves the library read +
    # due-logic work here and reports which cards are assigned to this machine.
    smoke_ok, smoke = _run_cmd(
        [sys.executable, "-m", "automations.card_scheduler.run"],
        timeout_s=180, log_name="card-scheduler-install-smoke.log")
    if not smoke_ok:
        return False, f"smoke test failed — NOT going live: {smoke[:150]}"

    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if boot.returncode != 0:
        return False, f"smoke ok; bootstrap FAILED: {(boot.stdout or '').strip()[:150]}"
    return True, (f"installed {label} · mode={'LIVE' if live else 'OBSERVE'} · "
                  f"{smoke[:110]}")


def _action_install_jiraiya(args: str) -> tuple[bool, str]:
    """Install 'Jiraiya' on THIS machine: the always-on /dd Socket Mode listener
    (com.alphalete.jiraiya-bot, KeepAlive) + the 3am nightly DD pre-harvest
    (com.alphalete.due-diligence-harvest). Run `update` + `restart_poller` first
    so this action exists in the running poller.

    Refuses to bootstrap the KeepAlive listener unless BOTH Slack tokens are
    already on the machine (~/.config/recruiting-report/dd-bot-token = xoxb,
    dd-app-token = xapp) — otherwise it would just crash-loop. Tokens are secrets
    and can't ride the control sheet, so a human places them once by hand; this
    only wires the launchd jobs around them. Smoke-tests the import first so a
    Python-3.9-incompatible line fails loud here instead of silently.

    Pass `bot-only` to (re)install just the listener, `harvest-only` for just the
    3am job; default installs both."""
    uid = os.getuid()
    mode = (args or "").strip().lower() or "both"
    cfg = Path.home() / ".config" / "recruiting-report"
    bot_tok, app_tok = cfg / "dd-bot-token", cfg / "dd-app-token"

    want_bot = mode in ("both", "bot-only")
    want_harvest = mode in ("both", "harvest-only")
    if mode not in ("both", "bot-only", "harvest-only"):
        return False, "args must be blank, 'bot-only', or 'harvest-only'"

    # 1) Tokens must exist before we bootstrap a KeepAlive listener.
    if want_bot:
        missing = [p.name for p in (bot_tok, app_tok) if not p.exists()]
        if missing:
            return False, (f"NOT installing the listener — missing token(s) on "
                           f"{__import__('socket').gethostname()}: {', '.join(missing)} "
                           f"in {cfg}. A human must place them by hand (secrets can't "
                           f"ride the control sheet), then re-queue install_jiraiya.")

    # 2) Smoke-test the import — catches a 3.9-incompatible line loudly.
    ok, out = _run_cmd([sys.executable, "-c",
                        "import automations.due_diligence.bot, "
                        "automations.due_diligence.run"],
                       timeout_s=120, log_name="jiraiya-install-smoke.log")
    if not ok:
        return False, f"import smoke test FAILED — not installing: {out[:200]}"

    jobs = []
    if want_bot:
        jobs.append(("com.alphalete.jiraiya-bot", "jiraiya_bot.sh"))
    if want_harvest:
        jobs.append(("com.alphalete.due-diligence-harvest", "due_diligence_harvest.sh"))

    done = []
    for label, wrapper_name in jobs:
        src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
        wrapper = REPO_ROOT / "deploy" / wrapper_name
        dst_plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        if not src_plist.exists() or not wrapper.exists():
            return False, (f"missing {src_plist.name} or {wrapper.name} — run "
                           "`update` first to pull them")
        try:
            text = src_plist.read_text().replace(
                "/Users/megan/1st Claude Folder", str(REPO_ROOT))
            dst_plist.parent.mkdir(parents=True, exist_ok=True)
            dst_plist.write_text(text)
            os.chmod(wrapper, 0o755)
        except Exception as e:  # noqa: BLE001
            return False, f"{label}: couldn't write plist/chmod: {str(e).splitlines()[0][:140]}"
        lint = subprocess.run(["plutil", "-lint", str(dst_plist)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if lint.returncode != 0:
            return False, f"{label}: plist lint failed: {(lint.stdout or '')[:160]}"
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if boot.returncode != 0:
            return False, f"{label}: bootstrap FAILED: {(boot.stdout or '').strip()[:150]}"
        done.append(label)

    tail = " · listener is KeepAlive (starts now); harvest runs 3am CST." \
        if want_bot else " · harvest runs 3am CST."
    return True, (f"installed: {', '.join(done)}{tail} "
                  "Stop the laptop's jiraiya-bot so only one Socket Mode listener runs.")


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


def _action_sheets_login(args: str) -> tuple[bool, str]:
    """The Sales Board SCREENSHOT profile — check it, or open its Google login.

      sheets_login check   headless probe: can the saved profile open the sheet?
      sheets_login         open the headed login so a HUMAN finishes the Google
                           sign-in (2FA) on the mini's screen

    Why: captainship_drafts §1 (Product Summary + Captainship Units) is a real
    browser screenshot of the Sales Board, driven by a dedicated Chrome profile
    logged in as alphaletereporting@. On 2026-07-25 that profile was signed out
    and 9 of 12 captains lost §1. It can't be fixed by shipping a file the way
    set_gmail_token does — Chrome seals its cookies with an OS-level key
    (macOS Keychain / Windows DPAPI), so a profile copied off another machine is
    unreadable. Same shape as reseed_appstream: this only launches the
    legitimate human-cleared flow.

    `check` is read-only and safe to run any time; prefer it before queueing the
    interactive form, which ties up the poller until someone acts."""
    mode = (args or "").strip().lower() or "login"
    if mode not in ("login", "check"):
        return False, ("sheets_login takes 'check' (headless probe) or nothing "
                       "(open the login for a human)")
    cmd = [sys.executable, "-m", "automations.captainship_drafts.sheet_shot", mode]
    ok, res = _run_cmd(cmd, timeout_s=(3 * 60 if mode == "check" else 8 * 60),
                       log_name=f"sheets_login-{mode}.log")
    if mode == "check":
        return ok, res + (" — profile is signed in" if ok
                          else " — SIGNED OUT: queue `sheets_login` and finish "
                               "the Google sign-in on the mini's screen")
    return ok, res + " (needs a human to finish the Google sign-in on the mini)"


def _action_set_sheets_cookies(args: str) -> tuple[bool, str]:
    """Replay an exported Google session into THIS machine's screenshot profile.

    The escape hatch from sheets_login's one hard requirement: a human at the
    screen for 2FA. Nobody sits at Lucy 1, so the captainship drafts have been
    building on Eve's laptop instead — which only works when her laptop is on,
    and the whole point of a scheduled runner is that it isn't conditional on
    that.

    This is NOT the profile copy _action_sheets_login rules out. That fails
    because Chrome seals its cookie store with an OS-level key, so the files are
    unreadable elsewhere. Here Playwright reads the cookies out through Chrome's
    own API on the source machine — already decrypted — and hands them to this
    machine's Chrome, which re-seals them with ITS key. The OS key never travels.

    Args is the JSON produced by `sheet_shot export-cookies` on a machine where
    the profile IS signed in. It is a live Google session: CLEAR THE ARGS CELL
    once this shows done, same as the token actions.

    Google may refuse a session replayed onto different hardware and a different
    OS. A failure here is expected-ish and costs nothing — it just means the
    human login is still the only way in."""
    import json

    blob = (args or "").strip()
    if not blob.startswith("["):
        return False, ("set_sheets_cookies needs the JSON array from "
                       "`sheet_shot export-cookies` as the Args")
    try:
        cookies = json.loads(blob)
    except Exception as e:  # noqa: BLE001
        return False, f"Args is not valid JSON: {str(e)[:120]}"
    if not cookies:
        return False, "no cookies in the Args"
    path = (Path.home() / ".config" / "recruiting-report" / "sheets-cookies.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blob, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    cmd = [sys.executable, "-m", "automations.captainship_drafts.sheet_shot",
           "seed-cookies", str(path)]
    ok, res = _run_cmd(cmd, timeout_s=5 * 60, log_name="sheets-seed-cookies.log")
    # The session is spent either way — don't leave it lying on disk.
    try:
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return ok, (f"{len(cookies)} cookie(s) replayed · " + res +
                (" — profile is signed in" if ok else
                 " — Google rejected it; the human sheets_login is still needed"))


def _action_ping(args: str) -> tuple[bool, str]:
    """Liveness check — proves the mini's poller is alive and processing the
    queue. No side effects; used to verify the deploy."""
    import socket
    return True, f"pong from {socket.gethostname()} @ {_now()}"


# Paths that a materializing action (onboard_apply) writes into the working tree
# as UNTRACKED, and that are ALSO committed upstream. That exact combination is
# what makes `git pull --ff-only` abort with "untracked working tree files would
# be overwritten by merge" — which silently STRANDS a runner: every deploy fails,
# the machine drifts further behind, and no whitelisted action could fix it
# (git_stash skips untracked files by design). Lucy 2 sat 15 commits behind for
# 11 hours on exactly this, 2026-08-01.
#
# An ALLOWLIST, deliberately — not a path argument and emphatically not
# `git clean -fdx`, which would also wipe the browser-profile and extractor-cache
# directories that live untracked next to these and take a login to rebuild.
CLEARABLE_STRAYS = (
    "automations/b2b_metrics/onboarded_offices.json",
    "automations/office_metrics/onboarded_offices.json",
)


def _action_clear_untracked(args: str) -> tuple[bool, str]:
    """Move ONE known stray untracked file aside so a blocked `update` can pull.

    Safe by construction, in four ways:
      * allowlist only — CLEARABLE_STRAYS, nothing else, no wildcards
      * refuses directories (the caches/profiles next door are directories)
      * refuses anything git reports as TRACKED — that's git_stash's job
      * MOVES to output/stray-backups/ rather than deleting, so it's recoverable
        the same way git_stash is

    The file is committed upstream, so the very next `update` restores it.
    """
    import shutil
    from pathlib import Path as _P

    rel = (args or "").strip()
    allowed = ", ".join(CLEARABLE_STRAYS)
    if not rel:
        return False, f"clear_untracked needs a path. allowed: {allowed}"
    if rel not in CLEARABLE_STRAYS:
        return False, (f"{rel!r} is not clearable — this action is an ALLOWLIST, "
                       f"not a git clean. allowed: {allowed}")

    target = _P(REPO_ROOT) / rel
    if not target.exists():
        return True, f"{rel} already absent — nothing to clear"
    if target.is_dir():
        return False, (f"{rel} is a DIRECTORY — refusing (single files only; a "
                       "directory here would be a profile/cache, not a stray)")

    p = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--short", "--", rel],
                       capture_output=True, text=True, timeout=60)
    line = (p.stdout or "").strip()
    if not line.startswith("??"):
        return False, (f"{rel} is NOT untracked (git says {line or 'clean'!r}) — "
                       "refusing. Tracked edits belong in git_stash.")

    backup_dir = _P(REPO_ROOT) / "output" / "stray-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / "{}.{}.bak".format(target.name, _now().replace(":", "-"))
    shutil.move(str(target), str(dest))
    return True, ("moved {} -> output/stray-backups/{} (RECOVERABLE — moved, not "
                  "deleted). `update` will now restore it as a tracked file."
                  .format(rel, dest.name))


def _action_sheets_whoami(args: str) -> tuple[bool, str]:
    """READ-ONLY: what Google identity does THIS machine's Sheets token use, and
    which office boards can it actually open?

    Why this exists (2026-08-01): Jamis's B2B board 403'd on Lucy 2 while other
    boards opened, and there was no way to answer 'which account IS Lucy 2?'
    without a person at the machine. A spreadsheets-scoped OAuth token can NOT
    self-report its email — Google's tokeninfo returns no `sub`/`email` for that
    grant and userinfo 401s — so the answer has to be triangulated: the token's
    own recorded account (when the flow saved one), plus a per-board open test
    whose FULL error body is printed rather than swallowed.

    Prints NO secrets: client-id tail only, never the token or refresh token.

    A per-board 403 means 'this identity isn't on that file'. A failure at
    REFRESH instead means the token itself is dead — a different fix (re-auth)
    than adding a share. This tells the two apart in one run.
    """
    import json as _json
    from pathlib import Path as _P

    tok = _P.home() / ".config" / "recruiting-report" / "oauth-token.json"
    out = [f"sheets token: {tok}"]
    if not tok.exists():
        return False, "\n".join(out + ["MISSING — run sheets_auth on this machine"])
    try:
        j = _json.loads(tok.read_text())
    except Exception as e:  # noqa: BLE001
        return False, "\n".join(out + [f"unreadable: {e}"])
    cid = str(j.get("client_id") or "")
    # Project number (the leading segment), not the trailing '…googleusercontent
    # .com' every client shares — that tail distinguishes nothing.
    out.append("recorded account: {!r}   oauth client: {}".format(
        j.get("account") or "(none — the auth flow didn't save one)",
        cid.split("-")[0] or "?"))
    out.append(f"scopes: {j.get('scopes')}   expiry: {j.get('expiry')}")

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file(
            str(tok), ["https://www.googleapis.com/auth/spreadsheets"])
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                out.append("refresh: OK (token was expired, refreshed cleanly)")
            else:
                return False, "\n".join(out + [
                    "refresh: IMPOSSIBLE (no refresh token) — TOKEN IS DEAD, "
                    "re-auth with sheets_auth on this machine"])
        else:
            out.append("refresh: not needed (token still valid)")
        import gspread
        gc = gspread.authorize(creds)
    except Exception as e:  # noqa: BLE001
        return False, "\n".join(out + [
            f"AUTH FAILED: {type(e).__name__}: {e} — the token itself is the "
            "problem (re-auth), NOT sheet sharing"])

    # Per-board open test. Names are the B2B office boards; a 403 here is a
    # per-FILE denial for whatever identity the token carries.
    boards = [
        ("carlos", "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"),
        ("atef", "15YUHkAcG2AfiF6KRhCiOBKGDdS9nnjxdfvIXr7oRX30"),
        ("jamis", "1lDm-ZmV4OjAPipx-lbqQUrd1VifpULzRNP3klGqEZhU"),
    ]
    for name, key in boards:
        try:
            out.append(f"  {name:7} OPEN OK — {gc.open_by_key(key).title!r}")
        except Exception as e:  # noqa: BLE001
            cause = getattr(e, "__cause__", None)
            resp = getattr(cause, "response", None)
            code = getattr(resp, "status_code", None)
            body = (getattr(resp, "text", "") or "")[:300].replace("\n", " ")
            out.append(f"  {name:7} {type(e).__name__} http={code} {body}")
    out.append("READ-ONLY probe — nothing was written or posted.")
    return True, "\n".join(out)


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
                        "day-orchestrator", "box-order-log")
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
PIP_ALLOWLIST = {"reportlab", "playwright", "gspread"}


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


def _action_playwright_install(args: str) -> tuple[bool, str]:
    """Download the Playwright browser binary into the report venv — the
    non-pip step `playwright install <browser>` (default: chromium). Needed by
    the applicant_tracker reports, which drive a real headless Chromium. Safe +
    idempotent: re-running is a no-op once the browser is present."""
    browser = (args or "chromium").strip() or "chromium"
    if browser not in {"chromium", "firefox", "webkit"}:
        return False, f"playwright_install refused {browser!r}; allowed: chromium, firefox, webkit"
    return _run_cmd([sys.executable, "-m", "playwright", "install", browser],
                    timeout_s=10 * 60)


def _action_set_applicant_service_account(args: str) -> tuple[bool, str]:
    """Install the Applicant Tracker Google service-account key on THIS runner,
    so the applicant_tracker reports can reach the Sheet with no human at the
    machine. The key is gitignored (the repo is public), so it can't ride a
    git pull — it's passed here as BASE64 of the JSON key file (base64 so the
    multi-line JSON survives the single Args cell + the CLI cleanly).

    Writes to <repo>/applicant-tracker-service-account.json (backs up any
    existing file first — never clobbers blindly), then verifies by loading the
    creds and opening the tracker's 2R tab. NEVER echoes key material.

    SECURITY: the base64 key transits the control Sheet's Args cell to get here.
    REDACT that cell once this shows 'done' (same as set_meta_token)."""
    import base64
    import json
    import shutil

    blob = (args or "").strip()
    if not blob:
        return False, "set_applicant_service_account needs the key as BASE64 in the Args"
    try:
        raw = base64.b64decode(blob, validate=True)
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return False, f"Args isn't valid base64-of-JSON: {str(e).splitlines()[0][:100]}"
    if data.get("type") != "service_account" or not data.get("client_email"):
        return False, "decoded JSON isn't a Google service_account key"

    dest = REPO_ROOT / "applicant-tracker-service-account.json"
    if dest.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(dest, dest.parent / f"{dest.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block
            pass
    try:
        dest.write_text(raw.decode("utf-8"))
        os.chmod(dest, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write the key: {str(e).splitlines()[0][:120]}"

    # Verify it actually authenticates against the tracker (proof in `lucy status`).
    try:
        from automations.applicant_tracker import config as _cfg, sheets as _sh
        ws = _sh.open_tab(_cfg.TAB_2R)
        _ = ws.acell("A1").value
    except Exception as e:  # noqa: BLE001
        return True, (f"key written for {data.get('client_email')}, but the Sheet "
                      f"check failed (share the sheet with that email?): "
                      f"{str(e).splitlines()[0][:110]}")
    return True, f"key installed + verified against the tracker ({data.get('client_email')})"


def _applicant_key_files() -> list[Path]:
    """The service-account key and EVERY backup copy of it. `.bak.<stamp>` files
    are made by set_applicant_service_account on each install — they hold the
    same private key, so any 'is the key here / get it off this box' answer that
    ignores them is wrong."""
    out = []
    dest = REPO_ROOT / "applicant-tracker-service-account.json"
    if dest.exists():
        out.append(dest)
    out.extend(sorted(REPO_ROOT.glob("applicant-tracker-service-account.json.bak.*")))
    return out


def _action_applicant_key(args: str) -> tuple[bool, str]:
    """Report or REMOVE the Applicant Tracker service-account key on THIS runner.

        applicant_key            (or `status`) read-only: is the key here?
        applicant_key remove     delete the key AND every .bak copy

    Why: the reports run on Lucy 1 as rcaptain, but the key was also pushed to
    Lucy 2 while they were first built there. A credential should not outlive the
    machine that needs it, and there was no way to even ASK a runner whether it
    still had one.

    NEVER echoes key material — only the service-account email, size and mtime.
    `remove` is a real delete, not a rename: leaving a backup on the same box is
    leaving the key on the box. It is recoverable — re-push with
    set_applicant_service_account — so this is safe to run on a machine you are
    not sure about.
    """
    import json

    mode = (args or "status").strip().lower() or "status"
    if mode not in ("status", "remove"):
        return False, "applicant_key takes 'status' (default) or 'remove'"

    files = _applicant_key_files()
    if not files:
        return True, "no Applicant Tracker key on this machine (nothing to remove)"

    # Identify the key WITHOUT revealing it: the client_email is the useful bit.
    who = "unknown"
    try:
        who = json.loads(files[0].read_text()).get("client_email") or "unknown"
    except Exception:  # noqa: BLE001 — a corrupt/unreadable key still counts as present
        pass
    desc = ", ".join(
        f"{f.name} ({f.stat().st_size}b, {dt.datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d})"
        for f in files)

    if mode == "status":
        return True, f"key PRESENT for {who} — {len(files)} file(s): {desc}"

    removed, failed = [], []
    for f in files:
        try:
            f.unlink()
            removed.append(f.name)
        except Exception as e:  # noqa: BLE001
            failed.append(f"{f.name}: {str(e).splitlines()[0][:60]}")
    if failed:
        return False, (f"removed {len(removed)}, FAILED {len(failed)}: "
                       f"{'; '.join(failed)}")
    return True, (f"removed {len(removed)} key file(s) for {who}: "
                  f"{', '.join(removed)} — re-push with "
                  "set_applicant_service_account if this machine needs it back")


def _action_update(args: str) -> tuple[bool, str]:
    """Deploy new code onto a runner AND keep it locked to `main`.

    Production runners must always be on main — a stray dev-branch checkout is
    how Lucy 2 got stranded on resume-pushing-v2 (2026-07-15), silently missing
    every deploy. So `update` now switches to main FIRST, then pulls. This
    re-locks the runner to main on every update, so drift self-heals.

    Both steps are safe: `git checkout main` refuses if there are uncommitted
    changes (never discards them), and the pull is --ff-only (never a merge, no
    force). `--autostash` parks any working-tree edits (e.g. onboard_apply's
    Sheet-materialized onboarded_offices.json before the laptop commits it) around
    the pull and re-applies them after, so an unpushed enrollment never blocks a
    deploy. A poller-code change still needs a restart_poller after. Read the
    result with `lucy status`."""
    co = subprocess.run(["git", "-C", str(REPO_ROOT), "checkout", "main"],
                        capture_output=True, text=True)
    if co.returncode != 0:
        return False, ("couldn't switch to main (uncommitted changes on the "
                       f"current branch?): {(co.stderr or co.stdout).strip()[:150]}")
    return _run_cmd(["git", "-C", str(REPO_ROOT), "pull", "--ff-only",
                     "--autostash"], timeout_s=120)


def _action_git_status(args: str) -> tuple[bool, str]:
    """Read-only: what is this runner's git state, and is anything blocking a
    pull? It never touches the working tree or the index — nothing is staged,
    reverted, or discarded. It does fetch remote-tracking refs (so "behind by
    N" is current) and write its own log.

    Exists because `update` fails with git's TAIL ("Please commit your changes
    or stash them before you merge"), and the file list git prints ABOVE that
    line is exactly what gets truncated out of the result cell. On 2026-07-21
    that left a blocked deploy with no way to see the cause from the laptop:
    there is no SSH, and every other action is fixed-purpose. Full output also
    goes to a log so `lucy logtail git-status` can read past the cell limit.
    """
    def _git(*a):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a],
                           capture_output=True, text=True, timeout=30)
        return (p.stdout or p.stderr).strip()

    try:
        head = _git("log", "-1", "--format=%h %ad %s", "--date=short")
        branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        dirty = _git("status", "--short")
        # What a pull would bring — names only, so the cell stays readable.
        _git("fetch", "origin", "--quiet")
        behind = _git("rev-list", "--count", "HEAD..origin/main")
        incoming = _git("diff", "--name-only", "HEAD", "origin/main")
    except Exception as e:  # noqa: BLE001
        return False, f"git_status failed: {type(e).__name__}: {str(e)[:120]}"

    inc = [l for l in incoming.splitlines() if l.strip()]
    mod = [l for l in dirty.splitlines() if l.strip()]
    # The blockers are the intersection: locally-modified files a pull would
    # also touch. That is precisely what makes `git pull --ff-only` abort.
    inc_set = {l.strip() for l in inc}
    blockers = [m for m in mod
                if m[3:].strip() in inc_set and not m.startswith("??")]

    lines = [f"branch {branch} · HEAD {head}",
             f"behind origin/main by {behind} commit(s)",
             f"locally modified: {len(mod)} · incoming files: {len(inc)}"]
    if blockers:
        lines.append("⚠ BLOCKS THE PULL (modified AND incoming):")
        lines += [f"    {b}" for b in blockers]
    elif mod:
        lines.append("no pull blockers — local edits don't overlap incoming")
    lines.append("--- git status --short ---")
    lines += mod or ["(clean)"]
    lines.append("--- incoming files ---")
    lines += inc or ["(none)"]

    full = "\n".join(lines)
    try:
        log_dir = REPO_ROOT / "output" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "git-status.log").write_text(full, encoding="utf-8")
    except Exception:  # noqa: BLE001 — logging must never fail a read-only probe
        pass
    # Lead with the blockers: that is the answer the caller came for, and the
    # result cell truncates.
    head_lines = lines[:3] + ([l for l in lines if l.startswith(("⚠", "    "))]
                              or ["(nothing blocking a pull)"])
    return True, "\n".join(head_lines) + "\n· full: lucy logtail git-status"


def _action_git_diff(args: str) -> tuple[bool, str]:
    """Read-only: the CONTENT of this runner's uncommitted edits, to a log.

    `git_status` answers "which files are dirty"; it deliberately prints names
    only so the result cell stays readable. That is not enough when a machine is
    running code that exists NOWHERE ELSE — on 2026-07-29 the mini turned out to
    be the only copy of an 11th tracker org (#horizon-edge-sales), and the laptop
    could see that the file was modified but not what the edit said, so the fix
    would have had to be guessed at. Guessing at someone's channel config is how
    an office silently stops getting its report.

    Optional path argument scopes the diff (e.g. `lucy git_diff
    automations/tableau_screenshots/slack_post.py`); no argument diffs the whole
    working tree. Never touches the index or the working tree — no add, no
    stash, no checkout. Full output goes to output/logs/git-diff.log because a
    diff never fits a result cell; read it with `lucy logtail git-diff`.
    """
    def _git(*a):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a],
                           capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr).strip()

    # shlex so a path with spaces survives; a caller passing several paths still
    # works because they land as separate pathspec args.
    try:
        paths = shlex.split(args or "")
    except ValueError:
        paths = (args or "").split()
    spec = ["--", *paths] if paths else []
    try:
        stat = _git("diff", "--stat", *spec)
        body = _git("diff", *spec)
        untracked = _git("ls-files", "--others", "--exclude-standard", *paths)
    except Exception as e:  # noqa: BLE001
        return False, f"git_diff failed: {type(e).__name__}: {str(e)[:120]}"

    scope = " ".join(paths) if paths else "(whole working tree)"
    lines = [f"--- git diff {scope} ---", stat or "(no tracked edits)", "",
             body or "(empty diff)"]
    if untracked:
        lines += ["", "--- untracked (NOT in the diff above) ---", untracked]
    full = "\n".join(lines)
    try:
        log_dir = REPO_ROOT / "output" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "git-diff.log").write_text(full, encoding="utf-8")
    except Exception:  # noqa: BLE001 — logging must never fail a read-only probe
        pass
    n = len([l for l in body.splitlines() if l.startswith(("+", "-"))])
    return True, (f"{scope}: {n} changed line(s)\n{stat or '(no tracked edits)'}"
                  "\n· full: lucy logtail git-diff")


def _action_git_stash(args: str) -> tuple[bool, str]:
    """Park uncommitted TRACKED changes so a blocked `update` can proceed.

    Recoverable by design — `git stash push`, never `checkout --` / `reset
    --hard`. The stash stays on the machine and `git stash pop` restores it, so
    this is safe to run remotely on someone else's work-in-progress. Untracked
    files are deliberately NOT stashed: they don't cause the "local changes
    would be overwritten by merge" abort, and sweeping up another session's new
    files is exactly the kind of surprise this queue should not create.

    Reports what it parked, so the audit row says whose work moved and where.
    """
    def _git(*a):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a],
                           capture_output=True, text=True, timeout=60)
        return p.returncode == 0, (p.stdout or p.stderr).strip()

    ok, dirty = _git("status", "--short")
    tracked = [l for l in dirty.splitlines()
               if l.strip() and not l.startswith("??")]
    if not tracked:
        return True, ("nothing to stash — no modified tracked files "
                      "(a blocked pull is NOT caused by untracked files)")
    label = (args or "").strip() or f"lucy git_stash {_now()}"
    ok, out = _git("stash", "push", "-m", label)
    if not ok:
        return False, f"stash failed: {out[:200]}"
    _, listing = _git("stash", "list")
    n = len([l for l in listing.splitlines() if l.strip()])
    return True, ("parked " + str(len(tracked)) + " file(s) as "
                  + repr(label) + f" (stash entries now: {n})\n"
                  + "\n".join("    " + t for t in tracked[:12])
                  + "\nrestore on the machine with: git stash pop")


def _action_set_payroll_webapp(args: str) -> tuple[bool, str]:
    """Install/refresh the payroll headless-refresh Web App URL (runbook §1)
    into vantura-payroll-webapp.json at the repo root (gitignored), so the
    Wednesday vantura_payroll run can trigger the board's Commission rebuild
    itself instead of skipping it. Args = the script.google.com …/exec URL.
    Verifies with a live no-op GET before writing. The URL transits the
    control Sheet's Args cell — redact after 'done'."""
    url = (args or "").strip()
    if not (url.startswith("https://script.google.com/macros/s/")
            and url.endswith("/exec")):
        return False, "set_payroll_webapp needs the script.google.com …/exec URL as Args"
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=60) as r:  # follows redirects
            body = r.read(300).decode("utf-8", "replace")
        if '"ok"' not in body:
            return False, f"URL responded without the expected JSON: {body[:80]}"
    except Exception as e:  # noqa: BLE001 — report, don't crash the poller
        return False, f"URL check failed: {type(e).__name__}: {e}"
    (REPO_ROOT / "vantura-payroll-webapp.json").write_text(
        json.dumps({"webapp_url": url}) + "\n")
    return True, "payroll web-app URL installed + verified (no-op GET ok)"


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


def _action_set_slack_user_token(args: str) -> tuple[bool, str]:
    """Install/refresh the 'Lucy' Slack USER token (xoxp-) on THIS machine.

    Distinct from set_slack_token, which installs the BOT token (xoxb-) at
    slack-bot-token. Channel/thread posts made AS Lucy go through
    slack_metrics_post._client(), which reads the USER token from
    ~/.config/recruiting-report/slack-user-token — so a runner without this file
    renders fine and then dies the moment it uploads (that's exactly how the
    sales-boards --dm test failed on Lucy 2, 2026-07-18).

    Being signed into the Slack desktop app as Lucy does NOT create this file;
    it's an API token, not an app session.

    Backs up any existing token, verifies by reading the file back through the
    same client the reports use, and NEVER echoes the token into the result.

    Note: the token transits the control Sheet's Args cell to get here — clear
    that cell once this shows 'done'."""
    import shutil
    token = (args or "").strip()
    if not token.startswith("xoxp-"):
        return False, ("set_slack_user_token needs a Slack USER token (starts with "
                       "'xoxp-') as the Args — use set_slack_token for a bot token")
    path = Path.home() / ".config" / "recruiting-report" / "slack-user-token"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"slack-user-token.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(token, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    try:
        from automations.shared import slack_metrics_post as smp
        who = smp._client().auth_test()
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but auth_test errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    if not who.get("ok"):
        return False, f"token written but auth_test not ok: {str(who)[:120]}"
    return True, (f"Lucy Slack USER token installed + verified: authed as "
                  f"{who.get('user')} ({who.get('user_id')}) in team {who.get('team')}")


def _action_screendrive(args: str) -> tuple[bool, str]:
    """Drive the on-screen ApplicantStream extractor via real clicks/screenshots
    (resume_pushing.run --snap / --click / --extract-smart). Unlike `rerun`, it
    does NOT close Chrome — it operates the EXISTING logged-in browser where the
    plugin is alive. Needs Accessibility + Screen-Recording granted to THIS poller's
    python (System Settings → Privacy). shlex so quoted coords survive."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    cmd = [sys.executable, "-m", "automations.resume_pushing.run"] + parts
    return _run_cmd(cmd, timeout_s=1500)


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


def _safe_shlex_first(raw: str) -> bool:
    """True if `raw` shlex-splits into at least one token (so callers can try the
    un-shlexed form without wrapping every use in its own try/except)."""
    import shlex as _shlex
    try:
        return bool(_shlex.split(raw))
    except Exception:  # noqa: BLE001 — unbalanced quotes
        return False


def _action_set_gmail_token(args: str) -> tuple[bool, str]:
    """Install the gmail.compose OAuth token on THIS machine so reports that
    create Gmail DRAFTS (captainship_drafts) can run unattended. Args is the
    CONTENTS of ~/.config/recruiting-report/gmail-token.json (self-contained:
    refresh_token + client_id/secret, so no oauth-client.json is needed here).

    Why this exists: on 2026-07-25 captainship_drafts died on its FIRST draft
    with "No Gmail token at ~/.config/recruiting-report/gmail-token.json" — the
    one-time `python -m automations.shared.gmail_auth` had never been run on the
    mini, and that authorization is interactive (browser + consent), so it can't
    be done over the queue. Shipping the already-authorized token is the only
    unattended path. Backs up any existing token, writes it, then verifies by
    resolving the mailbox. NEVER echoes the token.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell after this shows 'done' (the queuer does this from the laptop)."""
    import json
    import shlex
    import shutil
    # Two delivery paths reach here: `lucy` shlex-JOINS multi-char args before
    # the Sheet round-trip, while enqueue() writes the cell verbatim. shlex.split
    # on already-raw JSON eats the quotes ('{"a":1}' -> '{a:1}'), so try the raw
    # text FIRST and only fall back to un-shlexing. Handles both without guessing.
    raw = (args or "").strip()
    parsed = None
    for cand in (raw, *( [shlex.split(raw)[0]] if _safe_shlex_first(raw) else [] )):
        cand = (cand or "").strip()
        if not cand.startswith("{"):
            continue
        try:
            parsed = json.loads(cand)
            break
        except Exception:  # noqa: BLE001 — try the next candidate
            continue
    if parsed is None:
        if not raw.startswith("{") and not raw.startswith('"{'):
            return False, ("set_gmail_token needs the gmail-token.json CONTENTS "
                           "(a JSON object) as Args")
        return False, "Args isn't valid JSON (neither raw nor shlex-unwrapped)"
    if not parsed.get("refresh_token"):
        return False, "token JSON has no refresh_token — re-authorize and pass the whole file"
    if not (parsed.get("client_id") and parsed.get("client_secret")):
        return False, ("token JSON has no client_id/client_secret — it must be "
                       "self-contained to refresh on this machine")

    from automations.shared.gmail_auth import GMAIL_ACCOUNT, GMAIL_TOKEN_PATH
    path = GMAIL_TOKEN_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"gmail-token.json.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify through the SAME loader the reports use — proof it refreshes here
    # AND lands in the right mailbox (a token for the wrong account would file
    # every draft where nobody looks). Never echo the token.
    try:
        from googleapiclient.discovery import build

        from automations.shared.gmail_auth import load_credentials
        svc = build("gmail", "v1", credentials=load_credentials(),
                    cache_discovery=False)
        who = svc.users().getProfile(userId="me").execute().get("emailAddress", "")
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but verify errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    if who.lower() != GMAIL_ACCOUNT.lower():
        return False, (f"token written but it authorizes {who!r}, not "
                       f"{GMAIL_ACCOUNT!r} — drafts would land in the wrong mailbox")
    return True, f"Gmail token installed + verified: mailbox {who}"


def _action_set_contacts_ro_token(args: str) -> tuple[bool, str]:
    """Install the alphaletereporting READ-ONLY Contacts token on THIS machine —
    the one `shared.contacts_auth` uses to expand the distro groups that address
    the Org Sales Board email.

    WHY THIS EXISTS. That token died on 2026-07-31 and took the Org board email
    with it: `expand_groups` raised RefreshError('invalid_grant: Token has been
    expired or revoked'), the send exited 1, and the gate reported "Could not
    send" every 15 minutes. Re-authorizing is a BROWSER flow, and nobody can sit
    at the mini — but the flow does not have to run there. Eve authorizes on her
    own machine (the redirect is to HER localhost), and the refresh token that
    comes out works from anywhere. This ships it.

    `set_contacts_token` (the neighbour above) writes the raffi127 read-WRITE
    token that fiber_owners_distro uses — a DIFFERENT file for a different job.
    Pointing this at the same path would have quietly left contacts_auth broken.

    Args is the contents of ~/.config/recruiting-report/contacts-token.json.
    Backs up any existing token, writes it 0600, then verifies by expanding a
    group through the very loader the report uses. NEVER echoes the token.

    The token transits the control Sheet's Args cell — redact that cell once
    this shows 'done'."""
    import json
    import shlex
    import shutil
    raw = (args or "").strip()
    parsed = None
    for cand in (raw, *([shlex.split(raw)[0]] if _safe_shlex_first(raw) else [])):
        cand = (cand or "").strip()
        if not cand.startswith("{"):
            continue
        try:
            parsed = json.loads(cand)
            break
        except Exception:  # noqa: BLE001
            continue
    if parsed is None:
        return False, ("set_contacts_ro_token needs the contacts-token.json "
                       "contents as Args")
    if not parsed.get("refresh_token"):
        return False, "token JSON has no refresh_token — re-authorize and pass the whole file"
    if not (parsed.get("client_id") and parsed.get("client_secret")):
        return False, "token JSON has no client_id/client_secret — must be self-contained"

    from automations.shared import contacts_auth as ca
    path = ca.CONTACTS_TOKEN_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{path.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001
            pass
    try:
        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify the way the report does — a token that writes but won't refresh
    # here is the failure we are trying to end, so prove it before saying done.
    try:
        to, missing = ca.expand_groups(["Alphalete Org Owners"])
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but verify FAILED "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    if missing:
        return True, f"token written + refreshes, but group(s) not found: {missing}"
    return True, (f"Contacts read-only token installed + verified — "
                  f"'Alphalete Org Owners' expands to {len(to)} address(es)")


def _action_set_contacts_token(args: str) -> tuple[bool, str]:
    """Install the raffi127 read-WRITE Google Contacts token on THIS machine so
    fiber_owners_distro can sync the "ATT Fiber Owners" group unattended. Args is
    the CONTENTS of contacts-rw-token-raffi127.json (self-contained: refresh_token
    + client_id/secret). That authorization is interactive (browser consent), so
    it can't be done over the queue — shipping the already-authorized token is the
    only unattended path. Backs up any existing token, writes it, verifies by
    listing contact groups. NEVER echoes the token.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell after this shows 'done' (the queuer does this from the laptop)."""
    import json
    import shlex
    import shutil
    raw = (args or "").strip()
    # Optional leading "<account> <json>" (for alphaletereporting); bare JSON →
    # raffi127 (back-compat with the first install).
    account = "raffi127@gmail.com"
    head = raw.split(None, 1)
    if head and "@" in head[0] and "{" not in head[0]:
        account = head[0].strip()
        raw = head[1].strip() if len(head) > 1 else ""
    parsed = None
    for cand in (raw, *([shlex.split(raw)[0]] if _safe_shlex_first(raw) else [])):
        cand = (cand or "").strip()
        if not cand.startswith("{"):
            continue
        try:
            parsed = json.loads(cand)
            break
        except Exception:  # noqa: BLE001
            continue
    if parsed is None:
        return False, ("set_contacts_token needs the contacts-rw token JSON as Args "
                       "(optionally prefixed with the account email)")
    if not parsed.get("refresh_token"):
        return False, "token JSON has no refresh_token — re-authorize and pass the whole file"
    if not (parsed.get("client_id") and parsed.get("client_secret")):
        return False, "token JSON has no client_id/client_secret — must be self-contained"

    from automations.fiber_owners_distro import contacts_write as cw
    path = cw.token_path(account)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{path.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001
            pass
    try:
        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify through the same loader the report uses — proves it refreshes here.
    try:
        from googleapiclient.discovery import build
        svc = build("people", "v1", credentials=cw.load_credentials(account),
                    cache_discovery=False)
        n = len(svc.contactGroups().list(pageSize=5).execute().get("contactGroups", []))
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but verify errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    return True, f"Contacts ({account}) read-write token installed + verified (People API OK, {n}+ groups)"


def _action_set_raffi_app_password(args: str) -> tuple[bool, str]:
    """Install the raffi127 Gmail APP PASSWORD on THIS machine so bg_check_sync
    can read the First Advantage / Sterling emails over IMAP unattended. Args is
    the 16-char app password (spaces ok). Writes it to
    ~/.config/recruiting-report/gmail-app-password-raffi127 (chmod 600), then
    verifies by logging into IMAP. NEVER echoes the password.

    Note: the password transits the control Sheet's Args cell to get here —
    redact that cell after this shows 'done' (the queuer does this from the
    laptop)."""
    import shlex
    raw = (args or "").strip()
    try:
        parts = shlex.split(raw)
        pw = parts[0].strip() if parts else raw
    except Exception:  # noqa: BLE001
        pw = raw
    if len(pw.replace(" ", "")) < 12:
        return False, "set_raffi_app_password needs the 16-char app password as Args"
    path = Path.home() / ".config" / "recruiting-report" / "gmail-app-password-raffi127"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pw + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify: log into IMAP with the SAME code path the report uses. No echo.
    try:
        from automations.bg_check_sync import email_source
        M = email_source._connect()
        M.logout()
    except Exception as e:  # noqa: BLE001
        return True, (f"password written to {path} but IMAP login FAILED "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:100]}) — check the code")
    return True, f"raffi127 app password installed + IMAP login verified ({path.name})"


def _action_install_bg_check_sync(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the BG-check sync LaunchAgent
    (com.alphalete.bg-check-sync) on THIS machine — 3x/day (8:00/11:30/16:00),
    Monday 11:30 the must-run. Regenerates the plist for the mini's path, runs a
    --dry-run smoke test (reads IMAP + the sheet, NO writes, NO Slack — proves the
    app password + sheet access work), then bootstraps it. Run `update` +
    `restart_poller` + `set_raffi_app_password` first."""
    uid = os.getuid()
    label = "com.alphalete.bg-check-sync"
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "bg_check_sync.sh"
    dst_plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not src_plist.exists() or not wrapper.exists():
        return False, (f"missing {src_plist.name} or {wrapper.name} — run "
                       "`update` first to pull them")
    try:
        text = src_plist.read_text().replace(
            "/Users/megan/1st Claude Folder", str(REPO_ROOT))
        dst_plist.parent.mkdir(parents=True, exist_ok=True)
        dst_plist.write_text(text)
        os.chmod(wrapper, 0o755)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write plist/wrapper: {str(e).splitlines()[0][:140]}"
    lint = subprocess.run(["plutil", "-lint", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if lint.returncode != 0:
        return False, f"plist lint failed: {(lint.stdout or '')[:160]}"
    # Smoke test — real IMAP + sheet read, NO writes, NO Slack post.
    smoke_ok, smoke = _run_cmd(
        [sys.executable, "-m", "automations.bg_check_sync.run", "--dry-run",
         "--since-days", "5"],
        timeout_s=180, log_name="bg-check-sync-install-smoke.log")
    if not smoke_ok:
        return False, f"smoke test failed — NOT going live: {smoke[:150]}"
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if boot.returncode != 0:
        return False, f"smoke ok; bootstrap FAILED: {(boot.stdout or '').strip()[:150]}"
    return True, (f"installed {label} (8:00/11:30/16:00 daily) · smoke ok · {smoke[:80]}")


def _action_install_bg_check_watchdog(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the bg_check_sync WATCHDOG LaunchAgent
    (com.alphalete.bg-check-watchdog) on THIS machine — 12:45 + 17:00 daily. It
    DMs Raf via Lucy if bg_check_sync's heartbeat goes stale (scheduler stall).
    Regenerates the plist for the mini path, runs a --dry-run smoke test (checks
    the heartbeat, never DMs), then bootstraps it. Run `update`+`restart_poller` first."""
    uid = os.getuid()
    label = "com.alphalete.bg-check-watchdog"
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "bg_check_watchdog.sh"
    dst_plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if not src_plist.exists() or not wrapper.exists():
        return False, (f"missing {src_plist.name} or {wrapper.name} — run `update` first")
    try:
        text = src_plist.read_text().replace(
            "/Users/megan/1st Claude Folder", str(REPO_ROOT))
        dst_plist.parent.mkdir(parents=True, exist_ok=True)
        dst_plist.write_text(text)
        os.chmod(wrapper, 0o755)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write plist/wrapper: {str(e).splitlines()[0][:140]}"
    lint = subprocess.run(["plutil", "-lint", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if lint.returncode != 0:
        return False, f"plist lint failed: {(lint.stdout or '')[:160]}"
    smoke_ok, smoke = _run_cmd(
        [sys.executable, "-m", "automations.bg_check_sync.watchdog", "--dry-run"],
        timeout_s=60, log_name="bg-check-watchdog-install-smoke.log")
    if not smoke_ok:
        return False, f"smoke test failed — NOT going live: {smoke[:150]}"
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if boot.returncode != 0:
        return False, f"smoke ok; bootstrap FAILED: {(boot.stdout or '').strip()[:150]}"
    return True, f"installed {label} (12:45 + 17:00 daily) · smoke ok"


def _action_run_bg_check_sync(args: str) -> tuple[bool, str]:
    """Run bg_check_sync NOW on THIS machine. Default = LIVE (writes col K + posts
    the weekly #rafs-office-recruiting thread as Lucy). Pass extra args to override,
    e.g. `--dry-run` (no writes/post) or `--week 7/27/2026`."""
    import shlex
    extra = shlex.split(args) if (args or "").strip() else []
    if not extra:
        extra = ["--post", "--since-days", "30"]
    ok, out = _run_cmd([sys.executable, "-m", "automations.bg_check_sync.run", *extra],
                       timeout_s=300, log_name="bg-check-sync-run.log")
    lines = [ln for ln in (out or "").splitlines()
             if ("| roster" in ln or "[writes]" in ln or "[slack" in ln
                 or "POST new" in ln or "EDIT existing" in ln or "fuzzy-match" in ln
                 or ln.strip() == "=== done ===")]
    return ok, (" · ".join(lines)[:400] or (out or "")[-300:])


def _action_focus_owner(args: str) -> tuple[bool, str]:
    """Re-scrape ONE (or a few) Focus Office ATT owner tab(s) from ownerville —
    the surgical fix for when the full daily_rep_breakdown finished but a single
    owner's ownerville scrape stalled (e.g. the Office-Access DataTables AJAX
    stall). Runs `run_all_owners --only "<names>" --daily-window`, which is:
      • --only         → MERGE semantics: ONLY the named tab(s) are touched; every
                         other owner tab AND their scrape_results status are
                         preserved (no checkpoint, always scrapes fresh).
      • --daily-window → weekday-safe incremental (re-scrape yesterday + today
                         only); NEVER a full-week wipe.
    Does NOT run daily.py — no Tableau/freeze/cosmetic pass, none of the
    ~90-130m job. Pass the owner tab name(s) exactly as they appear in the Sheet,
    e.g. `focus_owner "Carissa Ng"` (space or comma-separate a few: "A" "B")."""
    import shlex
    try:
        names = shlex.split(args or "")
    except ValueError:
        names = (args or "").split()
    only = ",".join(n for n in names if n.strip())
    if not only:
        return False, 'focus_owner needs an owner tab name, e.g. focus_owner "Carissa Ng"'
    # A stray HUMAN Chrome open on the mini single-instances with our patchright
    # Chrome and breaks the browser scrape. Close it first, like the orchestrator
    # (and rerun) do for browser reports. [[reference_chrome_collision_guard]]
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome()
    except Exception:  # noqa: BLE001 — a guard must never crash the run
        pass
    cmd = [sys.executable, "-m", "automations.focus_office_att.run_all_owners",
           "--only", only, "--daily-window"]
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    ok, res = _run_cmd(cmd, timeout_s=20 * 60,
                       log_name=f"focus-owner-{stamp}.log")
    return ok, res


def _action_set_dd_bot_token(args: str) -> tuple[bool, str]:
    """Install/refresh Jiraiya's Slack BOT token (xoxb-) on THIS machine at
    ~/.config/recruiting-report/dd-bot-token — the file due_diligence.watch._client()
    reads. Jiraiya is the always-on Socket Mode listener that serves BOTH the /dd
    popup AND the Weekly Promotion Check-In buttons, so the mini needs this token to
    run the listener at all. Backs up any existing token, verifies via auth_test,
    NEVER echoes the token.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell once this shows 'done'."""
    import shutil
    token = (args or "").strip()
    if not token.startswith("xoxb-"):
        return False, "set_dd_bot_token needs Jiraiya's BOT token (starts with 'xoxb-') as the Args"
    path = Path.home() / ".config" / "recruiting-report" / "dd-bot-token"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"dd-bot-token.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(token, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    try:
        from automations.due_diligence.watch import _client
        who = _client().auth_test()
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but auth_test errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    if not who.get("ok"):
        return False, f"token written but auth_test not ok: {str(who)[:120]}"
    return True, (f"Jiraiya bot token installed + verified: authed as "
                  f"{who.get('user')} ({who.get('user_id')}) in team {who.get('team')}")


def _action_set_dd_app_token(args: str) -> tuple[bool, str]:
    """Install/refresh Jiraiya's Slack APP-LEVEL token (xapp-) on THIS machine at
    ~/.config/recruiting-report/dd-app-token — needed for Socket Mode. App tokens
    open the socket rather than call Web API, so this validates the prefix + writes
    (no auth_test). Backs up any existing token, NEVER echoes it.

    Note: the token transits the control Sheet's Args cell to get here — redact
    that cell once this shows 'done'."""
    import shutil
    token = (args or "").strip()
    if not token.startswith("xapp-"):
        return False, "set_dd_app_token needs Jiraiya's APP-LEVEL token (starts with 'xapp-') as the Args"
    path = Path.home() / ".config" / "recruiting-report" / "dd-app-token"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"dd-app-token.bak.{stamp}")
        except Exception:  # noqa: BLE001
            pass
    try:
        path.write_text(token, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    return True, (f"Jiraiya app-level token installed at {path} ({len(token)} chars) "
                  "— Socket Mode ready. Reload the listener: "
                  "`lucy rerun install_jiraiya_bot_agent`.")


def _action_run_b2b_dispositions(args: str) -> tuple[bool, str]:
    """Run the B2B Dispositions capture on THIS machine (Lucy 2 — where Carlos's
    OwnerVille B2B campaigns live). Default = --preview (DM the shots to Megan,
    post nothing) so a bare enqueue is always safe; pass args to override:
      run_b2b_dispositions --which all --dry-run   # capture only, no Slack
      run_b2b_dispositions --which hourly --preview # DM Megan the 2 hourly shots
      run_b2b_dispositions --which all --final --send  # LIVE to the channels
    A stray human Chrome on the mini breaks the patchright scrape, so close it
    first like the orchestrator does for browser reports."""
    import shlex
    extra = shlex.split(args) if (args or "").strip() else []
    if not extra:
        extra = ["--which", "all", "--preview"]
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome()
    except Exception:  # noqa: BLE001 — a guard must never crash the run
        pass
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    ok, out = _run_cmd([sys.executable, "-m", "automations.b2b_dispositions.run",
                        *extra], timeout_s=25 * 60,
                       log_name=f"b2b-dispositions-{stamp}.log")
    # Surface the per-shot summary lines (capture path + any full-page/campaign
    # flags) and the final status, trimmed to fit the result cell.
    lines = [ln for ln in (out or "").splitlines()
             if (ln.strip().startswith("[") or "⚠" in ln
                 or "territories" in ln or "PREVIEW" in ln or "DRY-RUN" in ln
                 or ln.startswith("Posted"))]
    return ok, (" · ".join(lines)[:450] or (out or "")[-300:])


def _action_install_b2b_dispositions(args: str) -> tuple[bool, str]:
    """Install the two B2B Dispositions launchd agents on THIS machine (Lucy 2):
    the hourly (12-6pm) and the 6:30 final. Idempotent — reinstalling re-locks the
    plist. `git pull` (update) must have landed the plists first."""
    from automations.day_orchestrator import install_agent
    out = []
    ok_all = True
    for label in ("b2b-dispositions-hourly", "b2b-dispositions-final"):
        try:
            ok, msg = install_agent.install(label)
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"{type(e).__name__}: {str(e)[:80]}"
        ok_all = ok_all and ok
        out.append(f"{label}: {'OK' if ok else 'FAIL'} {msg[:80]}")
    return ok_all, " · ".join(out)


ACTIONS = {
    "ping": _action_ping,
    "run_b2b_dispositions": _action_run_b2b_dispositions,
    "install_b2b_dispositions": _action_install_b2b_dispositions,
    "focus_owner": _action_focus_owner,
    "screendrive": _action_screendrive,
    "logtail": _action_logtail,
    "pip_install": _action_pip_install,
    "playwright_install": _action_playwright_install,
    "set_applicant_service_account": _action_set_applicant_service_account,
    "applicant_key": _action_applicant_key,
    "rerun": _action_rerun,
    "onboard_apply": _action_onboard_apply,
    "update": _action_update,
    "git_status": _action_git_status,
    "git_diff": _action_git_diff,
    "git_stash": _action_git_stash,
    "set_meta_token": _action_set_meta_token,
    "set_payroll_webapp": _action_set_payroll_webapp,
    "set_slack_token": _action_set_slack_token,
    "set_slack_user_token": _action_set_slack_user_token,
    "set_dd_bot_token": _action_set_dd_bot_token,
    "set_dd_app_token": _action_set_dd_app_token,
    "set_gbp_token": _action_set_gbp_token,
    "set_gmail_token": _action_set_gmail_token,
    "set_contacts_token": _action_set_contacts_token,
    "set_contacts_ro_token": _action_set_contacts_ro_token,
    "restart_holder": _action_restart_holder,
    "restart_poller": _action_restart_poller,
    "restart_hub": _action_restart_hub,
    "install_hub_watch": _action_install_hub_watch,
    "install_lucy2_digest": _action_install_lucy2_digest,
    "install_card_scheduler": _action_install_card_scheduler,
    "install_jiraiya": _action_install_jiraiya,
    "set_raffi_app_password": _action_set_raffi_app_password,
    "install_bg_check_sync": _action_install_bg_check_sync,
    "install_bg_check_watchdog": _action_install_bg_check_watchdog,
    "run_bg_check_sync": _action_run_bg_check_sync,
    "reseed_appstream": _action_reseed_appstream,
    "sheets_login": _action_sheets_login,
    "set_sheets_cookies": _action_set_sheets_cookies,
    "watch_test": _action_watch_test,
    "diag": _action_diag,
    "sheets_whoami": _action_sheets_whoami,
    "clear_untracked": _action_clear_untracked,
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
        # The cap bounds runaway REPORT churn only. PLUMBING actions (update,
        # restart_poller, ping, …) must ALWAYS run — else a cap-hit freezes the
        # deploy/recovery channel itself (incl. the very command that clears it).
        if (action.strip().lower() not in PLUMBING_ACTIONS
                and cap_used >= DAILY_AUTORUN_CAP):
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
        "  lucy git_status           branch, HEAD, and what's blocking a pull\n"
        "  lucy git_diff [path]      what this machine's uncommitted edits SAY\n"
        "  lucy git_stash            park uncommitted edits so update can run\n"
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
