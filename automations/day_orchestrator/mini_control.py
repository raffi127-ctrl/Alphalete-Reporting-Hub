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
  set_doubleentry_creds <user> <pass>   install the doubleentry.com financial
                        login into ownerville-creds.json + verify it by signing
                        in. The Args cell is auto-redacted when the row finishes.
  set_appstream_creds <user> <pass>   install the PRIMARY AppStream login into
                        ownerville-creds.json (merged, never clobbering the
                        ownerville pair) + verify by really logging in. Args
                        auto-redacted. The alt-account twin is
                        set_appstream_alt_creds.
  set_slack_token <tok> install/refresh the 'Lucy' Slack BOT token (xoxb-…) on this machine
  set_slack_user_token <tok>  install the 'Lucy' USER token (xoxp-…) — the one
                        channel/thread posts actually use. Args auto-redacted.
  slack_whoami          READ-ONLY: which Slack ACCOUNT this machine's user token
                        belongs to (so you know which app to edit at
                        api.slack.com/apps) + whether it has `users:read`.
                        Prints scopes, never the token.
  set_office_slack_token <office_key> <xoxb>  install a per-office WORKSPACE bot
                        token for an office whose channel is in a non-AO Slack
                        workspace (e.g. trang → FRESH SUCCESS). Args auto-redacted.
  set_dd_bot_token <tok>  install Jiraiya's BOT token (xoxb-…) — the always-on
                        listener that serves /dd + the Promotion Check-In buttons
  set_dd_app_token <tok>  install Jiraiya's APP-LEVEL token (xapp-…) for Socket Mode
  set_gbp_token <json>  install the Google Business Profile OAuth token (gbp-token.json contents)
  set_gdocs_token <json>  install the Google Docs OAuth token (gdocs-token.json
                        contents) so the Sunday rep shout-out can write the
                        Monday ATMO print unattended
  set_gmail_token <json>  install the gmail.compose token (gmail-token.json contents)
                        so draft-creating reports (captainship_drafts) can run
                        unattended. Verifies the mailbox is alphaletereporting@.
  set_alphalete_app_password <pw>  install the alphaletereporting@ Gmail APP
                        PASSWORD — the one credential every emailing report
                        shares (SMTP sends + IMAP inbox reads). Push it here
                        after rotating that account's password, which revokes
                        the old one. Verifies SMTP + IMAP. Args auto-redacted.
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

# The → / ✓ / ⚠ characters this module prints are not encodable in the Windows
# console's cp1252 default, and `enqueue` prints one AFTER it has already
# appended the row. So `--enqueue update` from Windows queued the job and THEN
# died with UnicodeEncodeError — the traceback said the deploy failed when it
# had actually worked, which is the worst possible way to be wrong about a
# deploy (Eve 2026-08-17). Same guard as opt_phase_carlos / run.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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

# WHO QUEUED THE ROW BEING RUN (Megan 2026-08-20). The action handlers all take
# `(args)` and nothing else — forty of them — so rather than re-sign every one,
# poll_once parks the current row's By value here for the duration of the call.
# Only _action_rerun reads it, and only to answer one question: is a person on
# this, or is a watchdog? That decides whether the report's alert thread gets the
# :pending: mark, and marking a thread nobody is working is exactly what made
# #claudecorrections unreadable.
AUTO_BY_PREFIX = "auto:"
# By values code has always written for itself, from before AUTO_BY_PREFIX
# existed. Kept as a literal list because these rows are already in the Sheet;
# new automated callers use enqueue(auto=True) instead of growing this.
_AUTO_BY = {"appstream_watch", "tableau_screenshots", "b2b_dispositions",
            "orchestrator", "day_orchestrator", "mini", "lucy"}
_CURRENT_BY = ""


def is_manual(by: str = "") -> bool:
    """Did a PERSON queue this row? Falls back to the row poll_once is running.

    Unknown / empty answers False. That is the safe direction: the cost of
    guessing wrong toward "auto" is a missing ⏳ on a thread someone is working;
    the cost of guessing wrong toward "manual" is the false ⏳ this whole change
    exists to stop — and incident_thread's own rule is that a missed mark is much
    the cheaper mistake."""
    who = (by or _CURRENT_BY or "").strip()
    if not who or who.lower().startswith(AUTO_BY_PREFIX):
        return False
    return who.lower() not in _AUTO_BY


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
                    "restart_orchestrator",
                    "install_enrollment_pending",
                    "pip_install", "playwright_install", "set_applicant_service_account",
                    "applicant_key", "watch_test", "diag", "set_sleep",
                    "set_slack_token", "set_office_slack_token",
                    "set_gbp_token", "set_gdocs_token", "set_gmail_token",
                    "set_dd_bot_token", "set_dd_app_token", "install_jiraiya",
                    "set_contacts_token", "set_contacts_ro_token",
                    "set_credico_state", "set_alphalete_app_password",
                    "set_appstream_state", "set_appstream_alt_state",
                    "appstream_promote_alt",
                    "post_note",
                    "sheets_login", "set_sheets_cookies", "sheets_whoami",
                    "slack_whoami", "set_slack_user_token",
                    "clear_untracked", "set_doubleentry_creds", "messages_diag",
                    "set_appstream_creds",
                    "fda_check", "stage_img_test", "shortcuts_probe", "reveal_python",
                    "nsf_screenshot_diag", "nsf_status",
                    # Bookkeeping on an alert thread — a reaction and a line in
                    # a thread. Bounded, idempotent, and the laptops hand these
                    # here BECAUSE only the mini is Lucy, so they must not eat
                    # the report budget.
                    "incident_resolve", "incident_working", "incident_unmark",
                    "find_group"}
# READ-ONLY diagnostics. They look at a log, the repo, or Slack and change
# NOTHING, so like plumbing they don't burn the budget — the cap exists to bound
# repeated REPORT runs, and _autoruns_today's own docstring says "side-effecting".
#
# WHY THIS IS SPLIT OUT (2026-08-13): the mini hit 100/100 by mid-afternoon and
# started leaving every rerun queued. 55 of those 100 rows were reads — 39
# logtail, 8 git_status, 3 slack_channel, 3 slack_find, 2 git_diff — i.e. the
# cost of DIAGNOSING the morning's failures was what exhausted the budget for
# FIXING them. Worse, the failure is quiet: the poller keeps running plumbing, so
# `update` still succeeds and the queue looks alive while every rerun sits at
# "queued" for hours. Reading a log should never spend a fix.
READONLY_ACTIONS = {"logtail", "daystate", "git_status", "git_diff",
                    "slack_channel", "slack_find"}
# Actions whose Args carry a SECRET. The poller blanks the Args cell as soon as
# the row finishes and never prints it to the log — `lucy status` dumps the whole
# Args column, so a password left sitting there is a password on screen. Older
# secret actions ask the queuer to redact by hand; these don't rely on memory.
SECRET_ACTIONS = {"set_appstream_alt_creds", "set_appstream_creds",
                  "set_doubleentry_creds",
                  # The applicant_tracker service-account PRIVATE KEY rides the
                  # Args cell as base64. It relied on hand-redaction — and on
                  # 2026-08-22 two old pushes were found still readable in the
                  # Sheet while re-pushing the key to Lucy 2.
                  "set_applicant_service_account",
                  # A live AppStream browser session pushed to this machine —
                  # same class of secret as set_credico_state.
                  "set_appstream_state", "set_appstream_alt_state",
                  "set_office_slack_token",
                  "set_gdocs_token", "set_slack_token", "set_cred_file",
                  # The xoxp- USER token is the one channel posts actually use
                  # and the more sensitive of the two — it was relying on the
                  # queuer clearing the cell by hand (2026-08-08).
                  "set_slack_user_token",
                  # A live Credico browser session — same class of secret as a
                  # token, and it transits the Args cell to reach Lucy 1.
                  "set_credico_state",
                  # The shared reporting mailbox's app password: one paste feeds
                  # every emailing report on the machine (2026-08-13).
                  "set_alphalete_app_password",
                  # A Gmail refresh token for that same mailbox. It was relying
                  # on the queuer blanking the cell by hand, so a token stayed
                  # readable in the Sheet for anyone with the link — noticed
                  # while re-pushing it after the 2026-08-13 password rotation.
                  "set_gmail_token"}
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
             log_name: str | None = None,
             env: dict | None = None) -> tuple[bool, str]:
    """Run a command in the repo root; return (ok, 'exit N · <tail>').

    env: extra environment for the child (MERGED over os.environ, not a
    replacement) — for actions that target a module through an env var, like
    probe_knocks' KNOCKS_OFFICE. None (default) inherits unchanged.

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
    child_env = dict(os.environ, **env) if env else None
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), timeout=timeout_s,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=child_env)
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


def _running_pids(module: str) -> list:
    """PIDs already running `python -m <module>` on this machine ([] on Windows,
    or when pgrep isn't available). Best-effort — a check that raises would take
    down the rerun it is guarding."""
    if sys.platform == "win32":
        return []
    try:
        out = subprocess.run(["pgrep", "-f", "-m {}".format(module)],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:          # noqa: BLE001
        return []
    me = str(os.getpid())
    return [p for p in out.split() if p and p != me]


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
    # NEVER a second copy of the same report. Two runs of one browser report
    # collide on the shared Chrome profile and BOTH lose: each waits in
    # tableau_patchright's profile lock (up to 30m) until its own timeout kills
    # it. 2026-08-19: tableau_screenshots was started five times between 04:52
    # and 07:39 — orchestrator retries and manual reruns overlapping — every one
    # of them died on that wait and the Country Trackers reached no channel all
    # morning. A rerun fired into a run that's already going doesn't heal the
    # morning, it doubles the damage.
    busy = _running_pids(r.command[0])
    if busy:
        return False, (f"{report_id} is ALREADY running here (pid "
                       f"{', '.join(busy)}) — not starting a second copy: two "
                       "runs collide on the shared Chrome profile and both time "
                       "out. Wait for it to finish, or kill that pid first and "
                       "re-queue.")
    if r.source_type in ("tableau", "appstream"):
        try:
            from automations.day_orchestrator import chrome_guard
            chrome_guard.close_stray_chrome()
            # And an ORPHAN automation Chrome still holding the shared profile:
            # its ProcessSingleton makes this rerun wait out the 30m profile lock
            # and die at its timeout — which is what a rerun is trying to escape.
            # On 2026-08-19 Megan had to run `lucy chrome_unstick` by hand
            # between two reruns; do it here so the rerun is self-healing.
            freed = chrome_guard.unstick_profile()
            if freed:
                print(f"  (freed the browser profile: orphan Chrome {freed})",
                      flush=True)
        except Exception:  # noqa: BLE001 — a guard must never crash the rerun
            pass
    # -u (unbuffered) is load-bearing, not tidiness. The child's stdout is a
    # PIPE, so Python block-buffers it; when a rerun hits the timeout below,
    # everything still sitting in that buffer dies with the process and
    # _run_cmd writes a log holding nothing but the stderr warnings. On
    # 2026-08-14 two 20-minute box_order_log_roshan reruns both left a 13-line
    # log with no trace of WHERE they stopped — the timeouts we most need to
    # read are exactly the ones this loses. The LaunchAgents already run their
    # modules with -u for the same reason (deploy/box_order_log_owners.sh:66).
    cmd = ([sys.executable, "-u", "-m", r.command[0]] + list(r.command[1:])
           + list(r.base_args) + extra)
    timeout_s = int(getattr(r, "timeout_minutes", 45) or 45) * 60

    # Publish the yellow "running" pill BEFORE the run so the Hub shows a manual
    # rerun IN PROGRESS, exactly like the orchestrator does. The rerun path used
    # to only mark DONE at the end, so a report looked idle the whole time it ran
    # (Megan 2026-07-08). Best-effort; publish_running is a no-op (returns None)
    # when the report has no Hub card. [[project_hub_live_running_pill]]
    #
    # manual=is_manual(): a rerun a PERSON queued (from the Hub, or `lucy rerun`)
    # also marks the report's alert thread :pending: — "I'm on this, don't both
    # start". A rerun a watchdog queued (appstream_watch) marks nothing: the
    # ticket is still open and still nobody's (Megan 2026-08-20).
    hub_run_id = None
    try:
        from automations.day_orchestrator import hub_publish
        hub_run_id = hub_publish.publish_running(
            report_id, getattr(r, "display_name", report_id),
            manual=is_manual())
    except Exception:  # noqa: BLE001 — Hub publish must never fail the rerun
        hub_run_id = None

    # One log per rerun, timestamped so repeated reruns of the same report don't
    # clobber each other (logtail's newest-match-wins then picks the latest).
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    # HUB_REPORT_ID means "a runner above you owns this run" — the Tableau access
    # ledger blames the pull on it, and a report that logs its OWN Hub pill skips
    # doing so (we publish it above and below). The orchestrator has always set
    # it; the rerun path didn't, so a rerun of a self-logging report wrote two
    # rows for one run — enough to fill a daily_runs>1 pill on a single phase
    # (Megan 2026-08-18). [[reference_phase_pill_id_match]]
    ok, result = _run_cmd(cmd, timeout_s,
                          log_name=f"rerun-{stamp}-{report_id}.log",
                          env={"HUB_REPORT_ID": str(report_id)})

    # A browser report killed at its timeout leaves its Chrome behind, still
    # holding the shared profile — so the NEXT rerun waits out the 30m profile
    # lock and dies the same way, once per attempt. On 2026-08-19 that loop ate
    # four consecutive tableau_screenshots runs (two orchestrator, two rerun) and
    # the trackers reached no channel all morning. Clear it here so a re-run is a
    # real second chance, not a repeat of the same 30 minutes. Orphans only (PPID
    # 1): a run can time out BECAUSE another report legitimately holds the
    # profile, and that one must not be killed.
    if not ok and result.startswith("timed out") \
            and r.source_type in ("tableau", "appstream"):
        try:
            from automations.day_orchestrator import chrome_guard
            freed = chrome_guard.unstick_profile()
            if freed:
                result += f" · freed the browser profile (orphan Chrome {freed})"
        except Exception:  # noqa: BLE001 — cleanup must never mask the result
            pass

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


# --- the restart hold ---------------------------------------------------------
# `restart_poller` SCHEDULES a kill ~3s out and returns immediately, and until
# then this pass keeps claiming rows — which run on the code the poller loaded
# when it BOOTED, not the code `update` just pulled. Deploying is always the
# same three rows (update, restart_poller, the thing you actually wanted), so
# the third one silently ran on the old code every time. On 2026-08-19 that ate
# an incident close two seconds after the restart was scheduled, and it failed
# as "no OPEN incident" — a message about the wrong subject entirely.
#
# So once a restart is scheduled we stop CLAIMING work. Rows stay `queued` with
# a note and the fresh poller takes them seconds later, on the new code.
#
# TIME-BOXED ON PURPOSE: if the kickstart never lands (launchd refuses, the
# label is wrong), an unconditional hold would freeze the queue in silence —
# strictly worse than the bug it fixes, and this queue is how the machine gets
# unstuck. After the window we resume and say so loudly.
_RESTART_HOLD_SECS = 120
_restart_scheduled_at: float | None = None


def _restart_hold_active() -> bool:
    """Are we inside the window where a restart is about to replace this code?"""
    if _restart_scheduled_at is None:
        return False
    if time.time() - _restart_scheduled_at < _RESTART_HOLD_SECS:
        return True
    print("[mini_control] ⚠ a restart was scheduled {}s ago and this process is "
          "STILL alive — the kickstart didn't land. Resuming the queue on the "
          "OLD code; re-run restart_poller or restart it by hand."
          .format(int(time.time() - _restart_scheduled_at)), flush=True)
    return False


def _action_restart_orchestrator(args: str) -> tuple[bool, str]:
    """Kickstart the DAY ORCHESTRATOR (com.alphalete.day-orchestrator) so a
    running batch reloads freshly-pulled code.

    WHY (Megan 2026-08-20): the orchestrator is a SEPARATE launchd job from this
    poller, so `restart_poller` never touched it and there was no remote path to
    it at all — a fix pulled by `update` sat unused until the next 4am. That day
    the per-report day_state save landed at 09:22 and `lucy daystate` stayed an
    hour stale for the rest of the morning because the running process still had
    the old code.

    ⚠️ THIS KILLS WHATEVER REPORT IS RUNNING. `kickstart -k` SIGKILLs the
    process group, so a mid-flight report dies and may leave an orphan Chrome
    holding the shared profile (the post-run unstick cannot fire on an outside
    kill — run `chrome_unstick` after if a browser report was in flight). The
    fresh instance re-reads today's state file and resumes: reports already
    terminal are skipped, the killed one is retried. Prefer waiting for the noon
    backstop unless the new code actually matters today.

    Pass --force to acknowledge that. Without it this refuses while a report is
    running, and only restarts when the orchestrator is idle."""
    label = "com.alphalete.day-orchestrator"
    force = "--force" in (args or "")
    if not force:
        try:
            out = subprocess.run(["pgrep", "-f", "automations\\..*\\.run"],
                                 stdout=subprocess.PIPE, text=True).stdout.strip()
            if out:
                return False, ("a report is RUNNING — restarting would SIGKILL it "
                               "and can orphan its Chrome. Re-queue with --force "
                               "if that is what you want, or wait for the batch.")
        except Exception:  # noqa: BLE001 — probe failure must not block a --force
            pass
    try:
        subprocess.Popen(
            ["/bin/sh", "-c",
             f"sleep 3; launchctl kickstart -k gui/{os.getuid()}/{label}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't schedule restart: {str(e)[:140]}"
    return True, (f"restart scheduled for {label} (~3s)"
                  f"{' (FORCED — a running report was killed)' if force else ''}"
                  f" — it re-reads today's state and resumes; terminal reports "
                  f"are skipped")


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
    global _restart_scheduled_at
    _restart_scheduled_at = time.time()
    return True, (f"restart scheduled for {label} (~3s) — poller reloads its "
                  f"code; the rest of the queue is held until it does")


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


def _action_set_appstream_state(args: str) -> tuple[bool, str]:
    """Install a pushed AppStream session as THIS machine's PRIMARY saved
    session (.appstream_storage_state.json) — the file every AppStream report's
    reuse path reads.

    Why: the rqst token expires ~daily on the server's schedule, and since
    AppStream's 2026-08-20 release the unattended form-login self-heal is dead
    (interactive human-check). One human-cleared login on ANY machine now feeds
    the fleet: --appstream-login there, then --appstream-push-fleet queues this
    everywhere. Backs up the old state file, installs the new one, then
    VERIFIES via the same reuse path the 4am reports use. appstream_watch's
    RECOVER step auto-reruns the morning AppStream reports once this lands
    healthy. In SECRET_ACTIONS — the Args cell is blanked on finish."""
    import json
    import shutil
    blob = (args or "").strip()
    if not blob.startswith("{"):
        return False, ("set_appstream_state needs the storage-state JSON as "
                       "Args — push it with --appstream-push-primary / "
                       "--appstream-push-fleet, don't paste by hand")
    try:
        n_rqst = sum(1 for c in json.loads(blob).get("cookies", [])
                     if str(c.get("name", "")).startswith("rqst_"))
    except Exception as e:  # noqa: BLE001
        return False, f"Args is not valid JSON: {str(e)[:120]}"
    if n_rqst == 0:
        return False, "pushed state has no rqst_ token — it can't restore a console"
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    if APPSTREAM_STORAGE_STATE.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(APPSTREAM_STORAGE_STATE,
                         APPSTREAM_STORAGE_STATE.with_name(
                             APPSTREAM_STORAGE_STATE.name + f".bak.{stamp}"))
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        APPSTREAM_STORAGE_STATE.write_text(blob, encoding="utf-8")
        os.chmod(APPSTREAM_STORAGE_STATE, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, (f"couldn't write {APPSTREAM_STORAGE_STATE.name}: "
                       f"{str(e).splitlines()[0][:120]}")
    ok, res = _run_cmd(
        [sys.executable, "-m", "automations.shared.appstream_whoami"],
        timeout_s=20 * 60, log_name="appstream-whoami.log")
    # whoami exit 4 = LOGGED IN but some probe offices are denied — normal for
    # an account that legitimately can't see them (Lucy 2's CarlosNLR primary).
    # The session itself is live, which is all this action promises.
    if not ok and res.lstrip().startswith("exit 4"):
        return True, (f"primary session installed + live (some probe offices "
                      f"denied to this account — expected) · {res[:280]}")
    if not ok:
        return False, (f"primary session installed ({n_rqst} rqst) but the "
                       f"verify FAILED: {res[:300]}")
    return True, f"primary session installed + verified · {res[:300]}"


def _action_appstream_promote_alt(args: str) -> tuple[bool, str]:
    """Make the ALTERNATE AppStream login this machine's PRIMARY — copy the
    alt credentials (appstream-alt.json, installed by set_appstream_alt_creds)
    into the primary keys of ownerville-creds.json. Runs entirely on THIS
    machine: no password ever transits the queue.

    Why (Megan 2026-08-21): rcaptain sees every office CarlosNLR does plus the
    6 he can't, so Lucy 2's reports should all run as rcaptain — one account,
    one daily re-seed. The alt file stays (funnel_board --account alt keeps
    working). Push the rcaptain SESSION separately with
    --appstream-push-primary; this action only aligns the configured creds so
    nothing ever falls back to the old primary account."""
    import json
    import shutil
    alt_path = Path.home() / ".config" / "recruiting-report" / "appstream-alt.json"
    try:
        alt = json.loads(alt_path.read_text())
    except Exception as e:  # noqa: BLE001
        return False, (f"no readable alt login at {alt_path.name} "
                       f"({str(e)[:80]}) — run set_appstream_alt_creds first")
    user = str(alt.get("appstream_alt_username") or "").strip()
    pw = str(alt.get("appstream_alt_password") or "")
    if not user or not pw:
        return False, f"{alt_path.name} is missing the username or password"
    path = REPO_ROOT / "ownerville-creds.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception as e:  # noqa: BLE001
            return False, f"couldn't read {path.name}: {str(e).splitlines()[0][:120]}"
        old = str(data.get("appstream_username") or "").strip()
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{path.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001
            pass
    else:
        old = ""
    data["appstream_username"] = user
    data["appstream_password"] = pw
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path.name}: {str(e).splitlines()[0][:120]}"
    return True, (f"primary AppStream creds now {user}"
                  + (f" (was {old})" if old and old != user else "")
                  + " — push the matching session with --appstream-push-primary")


def _action_set_appstream_alt_state(args: str) -> tuple[bool, str]:
    """Seed the ALTERNATE AppStream account's live session onto THIS machine
    from a storage-state JSON exported where a human cleared the login.

    Why: AppStream's 2026-08-20 release (v2026.08.20.1) put an interactive
    'Verify you are human' checkbox in front of the login form, so the
    unattended form login is dead on every machine. The only way an account
    reaches a runner nobody sits at is a replayed session — the same pattern
    as set_sheets_cookies / set_credico_state.

    Args is the CONTENTS of .appstream_storage_state.json from the source
    machine. Don't paste it by hand — on the source machine (fresh from
    --appstream-login) run:
        python -m automations.shared.tableau_patchright --appstream-push-alt
    which queues it here directly. Injects the cookies into BOTH alternate
    browser profiles (whoami's and funnel_board's), stamps the identity
    marker so the login guard keeps them, then VERIFIES with appstream_whoami
    --alt against the six offices the primary can't see. In SECRET_ACTIONS —
    the poller blanks the Args cell the moment the row finishes."""
    import json
    blob = (args or "").strip()
    if not blob.startswith("{"):
        return False, ("set_appstream_alt_state needs the storage-state JSON "
                       "as Args — push it with --appstream-push-alt, don't "
                       "paste by hand")
    try:
        n = len(json.loads(blob).get("cookies", []))
    except Exception as e:  # noqa: BLE001
        return False, f"Args is not valid JSON: {str(e)[:120]}"
    tmp = Path.home() / ".config" / "recruiting-report" / "appstream-alt-state.json"
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(blob, encoding="utf-8")
        os.chmod(tmp, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {tmp}: {str(e).splitlines()[0][:120]}"
    ok, res = _run_cmd(
        [sys.executable, "-m", "automations.shared.tableau_patchright",
         "--appstream-seed-alt", str(tmp)],
        timeout_s=5 * 60, log_name="appstream-seed-alt.log")
    # The session is a live secret — never leave it lying on disk.
    try:
        tmp.unlink()
    except Exception:  # noqa: BLE001
        pass
    if not ok:
        return False, f"{n} cookie(s) received but the seed failed: {res[:300]}"
    ok2, res2 = _run_cmd(
        [sys.executable, "-m", "automations.shared.appstream_whoami", "--alt",
         "--offices", "22583,19717,23607,22177,23411,21328"],
        timeout_s=20 * 60, log_name="appstream-whoami.log")
    if not ok2:
        return False, (f"session seeded ({n} cookies) but the verify FAILED: "
                       f"{res2[:300]} — AppStream may refuse a session "
                       "replayed from another machine/IP")
    return True, f"alt session seeded ({n} cookies) + verified · {res2[:300]}"


def _action_ping(args: str) -> tuple[bool, str]:
    """Liveness check — proves the mini's poller is alive and processing the
    queue. No side effects; used to verify the deploy."""
    import socket
    return True, f"pong from {socket.gethostname()} @ {_now()}"


def _osascript(script: str, timeout: int = 60) -> tuple[bool, str]:
    """Run one AppleScript; return (ok, stdout-or-stderr). macOS-only."""
    import platform
    if platform.system() != "Darwin":
        return False, "not macOS — no Messages.app"
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"osascript launch error: {str(e)[:160]}"
    if proc.returncode != 0:
        return False, (proc.stderr or "osascript failed").strip()[:300]
    return True, (proc.stdout or "").strip()


def _action_messages_diag(args: str) -> tuple[bool, str]:
    """READ-ONLY: is Messages signed in on THIS machine, and as WHICH account?

    The whole point of texting 'from Lucy 2' is that Messages here is signed in
    on the intended Apple ID (alphletegp@). This proves that without sending a
    thing: it reports the running state, the active iMessage service + the
    account/handle it's registered to, and whether an SMS service exists (green-
    bubble sends need the Mac paired to an iPhone with Text Message Forwarding).
    No side effects."""
    import socket
    out = [f"host: {socket.gethostname()} · {_now()}"]

    running = subprocess.run(["pgrep", "-x", "Messages"], capture_output=True,
                             text=True).returncode == 0
    out.append(f"Messages running: {running}")

    # Enumerate accounts + their service type / handle. Recent macOS throws
    # -10000 iterating `services`, so read from `accounts` (which worked on the
    # laptop probe) and fall back to the iMessage whose-filter for the handle.
    ok, accts = _osascript(
        'tell application "Messages"\n'
        '  set out to ""\n'
        '  repeat with a in accounts\n'
        '    try\n'
        '      set out to out & (service type of a as text) & " :: " & '
        '(description of a) & " :: enabled=" & (enabled of a as text) & linefeed\n'
        '    end try\n'
        '  end repeat\n'
        '  return out\n'
        'end tell')
    if ok and accts:
        out.append("accounts:")
        for ln in accts.splitlines():
            out.append("  " + ln)
    else:
        out.append(f"accounts: (couldn't read: {accts})")

    # The iMessage handle we'd actually send from (matches swag's send path).
    ok, handle = _osascript(
        'tell application "Messages" to get id of 1st service '
        'whose service type = iMessage')
    out.append(f"iMessage service id (send-from): {handle if ok else '(none: '+handle+')'}")

    has_sms = ok and False  # informational only; SMS shows in the accounts list above
    out.append("note: blue-bubble (iMessage) sends work from a Mac alone; "
               "green-bubble/SMS needs this Mac paired to an iPhone w/ Text "
               "Message Forwarding — look for an 'SMS' line above.")
    return True, "\n".join(out)


def _action_find_group(args: str) -> tuple[bool, str]:
    """READ-ONLY: which iMessage GROUP chats on THIS machine match a name?

    Args:  <name fragment>   e.g.  find_group Box B2B

    The whole point of resolving a group by NAME is that a group's chat GUID is
    NOT stable — adding a member mints a brand-new GUID, so a hardcoded id keeps
    "sending" into a defunct thread that nobody sees and nothing errors. (That is
    exactly how the Texas de Brazil texts went silently missing.) This proves,
    before anything is built on it, that AppleScript can see the group's display
    name on THIS macOS and hand back a live id.

    Reports EVERY match with its participant count so 0-match and 2+-match are
    both visible — an ambiguous name has to fail loudly at send time, never pick
    one at random. Reads names/ids/counts only: no message text, and it sends
    nothing."""
    q = (args or "").strip()
    # --enqueue routes args through shlex.join, so a multi-word name arrives
    # QUOTED ("'Box B2B'"). Searching that literal finds nothing and reads as a
    # real "group not found" — split it back off before matching.
    try:
        parts = shlex.split(q)
        if parts:
            q = " ".join(parts)
    except ValueError:
        pass
    if not q:
        return False, "find_group needs a name fragment (e.g. find_group Box B2B)"
    safe = q.replace("\\", "\\\\").replace('"', '\\"')

    # Primary: a whose-filter (fast). Fallback: walk every chat, tolerating the
    # ones with no display name (1:1 threads), because the whose-filter throws on
    # some macOS builds rather than skipping them.
    ok, out = _osascript(
        'tell application "Messages"\n'
        '  set res to ""\n'
        '  try\n'
        f'    set hits to (chats whose name contains "{safe}")\n'
        '  on error\n'
        '    set hits to {}\n'
        '    repeat with c in chats\n'
        '      set nm to ""\n'
        '      try\n'
        '        set nm to name of c as text\n'
        '      end try\n'
        f'      if nm contains "{safe}" then set end of hits to c\n'
        '    end repeat\n'
        '  end try\n'
        '  repeat with c in hits\n'
        '    set nm to ""\n'
        '    try\n'
        '      set nm to name of c as text\n'
        '    end try\n'
        '    set pc to 0\n'
        '    try\n'
        '      set pc to count of participants of c\n'
        '    end try\n'
        '    set res to res & (id of c) & " || name=" & nm & " || participants=" '
        '& pc & linefeed\n'
        '  end repeat\n'
        '  return res\n'
        'end tell', timeout=120)

    if not ok:
        return False, (f"lookup FAILED for {q!r}: {out} · if this timed out, the "
                       "'… wants to control Messages' consent dialog is waiting "
                       "unanswered on this machine")
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        # A bare "not found" can't tell three very different problems apart:
        # Lucy isn't in the group, the name is spelled differently, or this macOS
        # won't hand group names to AppleScript at all. Listing the names it CAN
        # see separates them in one round trip — a non-empty list proves the
        # lookup mechanism works and points at the real spelling.
        ok2, seen = _osascript(
            'tell application "Messages"\n'
            '  set res to ""\n'
            '  repeat with c in chats\n'
            '    set nm to ""\n'
            '    try\n'
            '      set nm to name of c as text\n'
            '    end try\n'
            '    if nm is not "" then set res to res & nm & " | "\n'
            '  end repeat\n'
            '  return res\n'
            'end tell', timeout=120)
        names = [n.strip() for n in (seen or "").split("|") if n.strip()] if ok2 else []
        if names:
            tail = ("named chats Messages CAN see here (%d): " % len(names)
                    + ", ".join(sorted(set(names))[:14]))
        else:
            tail = ("this machine exposes NO group names to AppleScript at all — "
                    "name lookup is unusable here; the chat.db path (Full Disk "
                    "Access) would be the only option")
        return False, (f"NO chat matches {q!r} by name. " + tail)
    head = f"{len(lines)} match(es) for {q!r}:"
    if len(lines) > 1:
        head += " AMBIGUOUS — a send must refuse to guess."
    return True, head + "\n" + "\n".join("  " + ln for ln in lines)


def _normalize_us_phone(raw: str) -> str:
    """Bare 10-digit US number -> +1XXXXXXXXXX (what iMessage buddy resolution
    wants). Leave anything already +-prefixed or non-10-digit untouched."""
    digits = re.sub(r"\D", "", raw or "")
    if raw.strip().startswith("+"):
        return raw.strip()
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return raw.strip()


def _action_sendtext(args: str) -> tuple[bool, str]:
    """Send ONE iMessage from THIS machine's signed-in iMessage account.

    Args:  <phone> <message…>   (first token = number, the rest = the text)
    e.g.   sendtext 4197697114 Test from Lucy 2 — reply if you got this

    Deliberately SINGLE-recipient and one message per queued row: the queue tab
    is the audit log (By/Queued At), so every send is attributable, and there's
    no bulk/loop path here. Reuses the proven swag AppleScript sender; reports
    the account it sent from so you can confirm it went out as the right Apple
    ID. A launchd poller may need one-time macOS Automation permission to control
    Messages — if it's blocked you'll see the -1743/'not allowed' error here, and
    a human grants it once at the machine (System Settings ▸ Privacy & Security ▸
    Automation)."""
    parts = (args or "").strip().split(None, 1)
    if len(parts) < 2 or not parts[0].strip():
        return False, "sendtext needs '<phone> <message>' (e.g. 4197697114 hi there)"
    phone = _normalize_us_phone(parts[0])
    text = parts[1].strip()

    # Go STRAIGHT to the send with a wide (5-min) timeout — no pre-lookup. The
    # send is itself an Apple Event to Messages, so on a machine that hasn't yet
    # authorized THIS process (the launchd poller) macOS pops the one-time
    # "… wants to control Messages" consent dialog and BLOCKS here until someone
    # clicks it. A short timeout kills osascript (and dismisses the dialog) before
    # a human can react — which is exactly why the 60s attempts failed with nobody
    # watching. 300s keeps the dialog clickable for ~5 min so a person at the
    # machine can Allow it once; after that it's granted for good and every future
    # send returns instantly. (The earlier pre-lookup is dropped: it just added a
    # second identical prompt/timeout.)
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    sent_ok, res = _osascript(
        'tell application "Messages"\n'
        '  set svcId to id of 1st service whose service type = iMessage\n'
        '  set targetService to service id svcId\n'
        f'  set targetBuddy to buddy "{phone}" of targetService\n'
        f'  send "{safe}" to targetBuddy\n'
        'end tell', timeout=300)
    if not sent_ok:
        return False, (f"send to {phone} FAILED: {res} · if this timed out, the "
                       "'… wants to control Messages' dialog went unanswered on the "
                       "machine — a human must click Allow while the send is firing")

    # Permission is granted now — this returns instantly. Confirm the from-account.
    ok, handle = _osascript(
        'tell application "Messages" to get id of 1st service '
        'whose service type = iMessage', timeout=20)
    from_acct = handle if ok and handle else "(sent; account read n/a)"
    return True, f"sent to {phone} from iMessage account {from_acct} · text={text!r}"


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


def _action_slack_whoami(args: str) -> tuple[bool, str]:
    """READ-ONLY: whose Slack account is THIS machine's user token, and which
    scopes does it actually have?

    Why this exists (2026-08-08): the Vantura Sales Board fill can't name a new
    rep because the token has no `users:read`, so their sales land on no row.
    Fixing that means editing the right Slack app — and there was no way to
    answer "which account IS Lucy 2's token?" from the laptop. Each teammate
    installs their OWN app (see ongoing_cancel/SETUP.md), so guessing is wrong
    as often as right.

    Prints NO secrets: the account name and the granted scopes, never the token.
    """
    import ssl as _ssl

    path = Path.home() / ".config" / "recruiting-report" / "slack-user-token"
    out = [f"slack user token: {path}"]
    if not path.exists():
        return False, "\n".join(out + [
            "MISSING — push one with set_slack_user_token <xoxp-…>"])
    try:
        import certifi
        from slack_sdk import WebClient
        from automations.shared.slack_metrics_post import _load_token
        client = WebClient(
            token=_load_token(),
            ssl=_ssl.create_default_context(cafile=certifi.where()))
        who = client.auth_test()
    except Exception as e:  # noqa: BLE001
        return False, "\n".join(out + [
            f"auth.test FAILED: {type(e).__name__} — the token is dead or "
            f"revoked; re-issue it and push with set_slack_user_token"])
    # Slack returns the granted scopes in a response header, which is the only
    # place they can be read without an admin API call.
    scopes = (who.headers.get("x-oauth-scopes") or "").replace(" ", "")
    granted = [s for s in scopes.split(",") if s]
    out += [
        f"account: {who.get('user')}  (user id {who.get('user_id')})",
        f"workspace: {who.get('team')}  {who.get('url')}",
        f"scopes ({len(granted)}): {', '.join(granted) or '(none reported)'}",
        "",
        "^ EDIT THE APP OWNED BY THAT ACCOUNT at https://api.slack.com/apps",
    ]
    # The scope this machine actually needs — probed, not just listed, because
    # a scope can be added to the app and still not be on an un-reinstalled token.
    try:
        client.users_info(user=who["user_id"])
        out.append("users:read — WORKING. New reps get named automatically; "
                   "KNOWN_USERS is now just a cache.")

    except Exception as e:  # noqa: BLE001
        err = getattr(getattr(e, "response", None), "data", {}) or {}
        if err.get("error") == "missing_scope":
            out += [
                "users:read — MISSING. Every new rep's sales land on NO row "
                "until their id is hand-added to KNOWN_USERS.",
                "  Fix: api.slack.com/apps -> that account's app -> OAuth & "
                "Permissions -> User Token Scopes -> add `users:read` -> "
                "Reinstall to Workspace -> copy the new xoxp- token -> "
                "`lucy set_slack_user_token <token> --machine \"<this machine>\"`",
                "  NOTE: reinstalling re-issues the token, which kills it on "
                "EVERY machine using this account — push the new one to all of "
                "them (run slack_whoami on each to see who shares it).",
            ]
        else:
            out.append(f"users:read — probe failed: {type(e).__name__} {err}")
    out.append("READ-ONLY probe — nothing was written or posted.")
    # A probe that ran is a SUCCESS even when the answer is "missing" — a red
    # 'failed' row here would read as a broken machine and, worse, is what the
    # corrections watcher escalates on.
    return True, "\n".join(out)


def _action_slack_channel(args: str) -> tuple[bool, str]:
    """READ-ONLY: can THIS machine's Slack token see one channel — and if not,
    what is the exact Slack error code?

      slack_channel <channel_id>        e.g. slack_channel C0A7871FAUV

    Why this exists (2026-08-13): #precisionmanagement-nds-sales failed the
    tracker run's dedup read with `SlackApiError ... conversations.history` and
    the code that logged it truncated the message before the error CODE, so the
    log couldn't tell membership (`not_in_channel`) from a rate limit
    (`ratelimited`) from a wrong id (`channel_not_found`) — three different fixes.
    Answers it without posting anything: conversations.info, then a 1-message
    conversations.history, reporting each call's raw code."""
    import ssl as _ssl

    cid = (args or "").strip().split()[0] if (args or "").strip() else ""
    if not cid:
        return False, "slack_channel needs a channel id (e.g. C0A7871FAUV)"
    try:
        import certifi
        from slack_sdk import WebClient
        from automations.shared.slack_metrics_post import _load_token
        client = WebClient(token=_load_token(),
                           ssl=_ssl.create_default_context(cafile=certifi.where()))
        who = client.auth_test()
    except Exception as e:  # noqa: BLE001
        return False, f"auth.test FAILED: {type(e).__name__} {str(e)[:120]}"

    def _code(e):
        data = getattr(getattr(e, "response", None), "data", {}) or {}
        return (data.get("error") or f"{type(e).__name__}: {str(e)[:60]}")

    out = [f"as {who.get('user')} ({who.get('user_id')}) in {who.get('team')}",
           f"channel {cid}"]
    try:
        ch = client.conversations_info(channel=cid)["channel"]
        out.append("  info: #{n} private={p} archived={a} member={m} "
                   "members={c}".format(n=ch.get("name"), p=ch.get("is_private"),
                                        a=ch.get("is_archived"),
                                        m=ch.get("is_member"),
                                        c=ch.get("num_members")))
    except Exception as e:  # noqa: BLE001
        out.append(f"  info: FAILED → {_code(e)}")
    try:
        h = client.conversations_history(channel=cid, limit=1)
        msgs = h.get("messages", []) or []
        out.append(f"  history: OK ({len(msgs)} msg read)")
        # WHEN the channel was last used, and by whom. An ARCHIVED channel that
        # was posted in last night is a channel someone archived TODAY — which is
        # a completely different story from "wrong channel id", and the timestamp
        # is the only thing that tells them apart (2026-08-15).
        if msgs:
            ts = float(msgs[0].get("ts") or 0)
            when = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            who = (msgs[0].get("user") or msgs[0].get("username")
                   or msgs[0].get("bot_id") or "?")
            text = (msgs[0].get("text") or "").replace("\n", " ")[:60]
            out.append(f"  last message: {when} by {who} — {text!r}")
    except Exception as e:  # noqa: BLE001
        out.append(f"  history: FAILED → {_code(e)}")
    out.append("READ-ONLY — nothing posted.")
    # A probe that RAN is a success even when the answer is "no access".
    return True, "\n".join(out)


def _action_slack_find(args: str) -> tuple[bool, str]:
    """READ-ONLY: which channels can THIS machine's Slack token see whose name
    contains <text>, and what are their real ids?

      slack_find precisionmanagement

    The question `slack_channel` can't answer. A channel id that returns
    `channel_not_found` is either wrong OR simply one this account isn't in, and
    those need opposite fixes (re-onboard vs. invite). conversations.list settles
    it: it returns every public channel plus the PRIVATE ones this account is a
    member of, so
      • name found, id matches config  -> config is right, membership is right
      • name found, id DIFFERENT       -> the config id is STALE (re-onboard)
      • name not found at all          -> this account isn't in it (invite), or
                                          the name is different than we think
    Built 2026-08-13: two configs disagreed about what C0A7871FAUV is called
    (trackers said #precisionmanagement-nds-sales, office metrics said
    Precision management-att-sales) and nothing on the laptop could adjudicate."""
    import ssl as _ssl

    needle = (args or "").strip().lower()
    try:
        import certifi
        from slack_sdk import WebClient
        from automations.shared.slack_metrics_post import _load_token
        client = WebClient(token=_load_token(),
                           ssl=_ssl.create_default_context(cafile=certifi.where()))
        who = client.auth_test()
    except Exception as e:  # noqa: BLE001
        return False, f"auth.test FAILED: {type(e).__name__} {str(e)[:120]}"

    # SPACE-SEPARATED TERMS = OR. Nobody remembers a channel's exact name ("was it
    # -nds-sales or -att-sales?"), and one call per guess is one queue round-trip
    # per guess. No terms at all = list every channel this account belongs to.
    needles = [n.lstrip("#") for n in needle.split() if n.lstrip("#")]

    # users.conversations = the channels THIS ACCOUNT IS A MEMBER OF. That is the
    # decisive question ("is Lucy in a Precision Management channel under ANY
    # name?"), and its result set is small — dozens, not thousands — so it can be
    # paged to completion. conversations.list cannot: Slack ignores `limit` and
    # returns ~5 channels per page, so a workspace-wide scan silently truncates.
    # That is exactly how a truncated 0-match scan was nearly read as PROOF that a
    # channel id was wrong (2026-08-13). An incomplete scan is now reported as
    # incomplete, and absence is only claimed when the scan actually finished.
    import time as _time
    rows, cursor, pages, ratelimits = [], None, 0, 0
    truncated = ""
    started = _time.monotonic()
    try:
        while True:
            pages += 1
            try:
                resp = client.users_conversations(
                    types="public_channel,private_channel", limit=1000,
                    exclude_archived=False, cursor=cursor)
            except Exception as e:                          # noqa: BLE001
                data = getattr(getattr(e, "response", None), "data", {}) or {}
                if data.get("error") == "ratelimited" and ratelimits < 5:
                    ratelimits += 1
                    hdrs = getattr(getattr(e, "response", None), "headers", {}) or {}
                    try:
                        wait = int(hdrs.get("Retry-After") or 5)
                    except Exception:                       # noqa: BLE001
                        wait = 5
                    _time.sleep(max(1, min(wait, 30)))
                    pages -= 1
                    continue
                raise
            for c in resp.get("channels", []):
                rows.append((c.get("name") or "", c.get("id"),
                             bool(c.get("is_private")), bool(c.get("is_archived"))))
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
            if pages >= 200:
                truncated = "hit the 200-page cap"
                break
            if _time.monotonic() - started > 240:
                truncated = "hit the 4-minute cap"
                break
    except Exception as e:                                  # noqa: BLE001
        data = getattr(getattr(e, "response", None), "data", {}) or {}
        code = data.get("error") or type(e).__name__
        return True, (f"as {who.get('user')} — users.conversations FAILED → {code}"
                      + ("  (the token needs users:read + channels:read + "
                         "groups:read)" if code == "missing_scope" else "")
                      + "\n  NOT an answer about membership — the probe couldn't "
                        "look. Do not treat this as 'the channel isn't there'.")

    n_priv = sum(1 for _n, _i, p, _a in rows if p)
    hits = [r for r in rows if any(n in r[0].lower() for n in needles)] \
        if needles else rows
    head = (f"as {who.get('user')} ({who.get('user_id')}) is a member of "
            f"{len(rows)} channel(s) ({n_priv} private), scanned in {pages} page(s)"
            + (f"  ⚠ INCOMPLETE — {truncated}" if truncated else "  ✓ complete")
            + (f"\n  {len(hits)} match(es) for {needles}" if needles else ""))
    body = ["  #{n}  {i}  private={p} archived={a}".format(n=n, i=i, p=p, a=a)
            for n, i, p, a in sorted(hits)[:14]]
    if needles and not hits and not truncated:
        body = ["  → this account is in NO channel whose name contains any of "
                f"{needles}. The scan was COMPLETE, so that is real — but it only "
                "rules out those NAMES, not a channel called something else. "
                "Re-run with other terms, or with no terms to list all "
                f"{len(rows)}."]
    if len(hits) > 14:
        body.append(f"  … {len(hits) - 14} more (narrow with a search term)")
    return True, "\n".join([head] + body + ["READ-ONLY — nothing posted."])


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
    # List EVERY loaded com.alphalete.* agent, derived from launchctl itself —
    # not a hardcoded subset. A fixed list silently omitted new per-machine
    # agents (e.g. resume-pushing, att-order-log on Lucy 2), so "is its agent
    # loaded?" was unanswerable from diag and every miss looked the same.
    have = sorted({
        tok.split("com.alphalete.", 1)[1]
        for line in ll.splitlines() if "com.alphalete." in line
        for tok in line.split() if tok.startswith("com.alphalete.")
    })
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


def _action_nsf_status(args: str) -> tuple[bool, str]:
    """New-Start Follow-Up `--mode status` on this machine. Reads only — status
    mode has no posting path at all — so it's the safe way to check from the
    laptop that the mini can still build a roster (screenshot, then this week's
    snapshot, then refuse)."""
    ok, out = _run_cmd([sys.executable, "-m", "automations.new_start_followup.run",
                        "--mode", "status"],
                       timeout_s=600, log_name="nsf-status.log")
    keep = [ln for ln in (out or "").splitlines()
            if ln.startswith(("[roster]", "WARNING", "OBCL tab", "Leaders", "INCOMPLETE"))]
    return ok, (" · ".join(keep)[:900] or (out or "")[-300:])


def _action_nsf_fix_rollcall(args: str) -> tuple[bool, str]:
    """Edit THIS week's posted New-Start roll call so it matches Aisha's
    screenshot. Runs here because only the author (Lucy, this machine) can
    chat.update the message — the laptop can read the screenshot but can't edit.

    DRY-RUN by default; pass `--post` to actually edit. Never posts a new
    message: a second list in the thread is what we're avoiding."""
    import shlex
    extra = shlex.split(args) if (args or "").strip() else []
    ok, out = _run_cmd([sys.executable, "-m",
                        "automations.new_start_followup.fix_rollcall", "--apply", *extra],
                       timeout_s=300, log_name="nsf-fix-rollcall.log")
    keep = [ln for ln in (out or "").splitlines()
            if ln.startswith(("[identity]", "[roster]", "[edited]", "[dry-run]",
                              "REFUSING", "No roll call", "Posted roll call",
                              "+", "-")) and not ln.startswith("---")]
    return ok, (" · ".join(keep)[:900] or (out or "")[-300:])


def _action_nsf_screenshot_diag(args: str) -> tuple[bool, str]:
    """Read-only: can THIS machine read Aisha's roster screenshot?

    Prints the Slack identity + scopes, finds the roster image, downloads it and
    reports whether real image bytes came back. No vision call, no writes, and
    the token is never printed. Added 2026-08-08: the read worked on the laptop
    and 400'd on the mini, which silently sent the roll call down the OBCL-sheet
    fallback and mis-tagged Bill Hirwa."""
    ok, out = _run_cmd([sys.executable, "-m",
                        "automations.new_start_followup.screenshot_roster", "--diag"],
                       timeout_s=180, log_name="nsf-screenshot-diag.log")
    keep = [ln for ln in (out or "").splitlines()
            if ln.startswith(("identity", "scopes", "image", "download", "first16",
                              "RESULT", "FAIL", "   OK", "   MISSING"))]
    return ok, (" · ".join(keep)[:900] or (out or "")[-300:])


def _action_chrome_sync_diag(args: str) -> tuple[bool, str]:
    """Read-only: report every REAL Google Chrome profile on this machine, the
    Google account(s) signed into it, and whether "history and tabs" sync is on.
    That single toggle is what broadcasts open report tabs to a person's other
    devices — the leak we chased on the laptop (a profile signed into a personal
    Google account with sync on). No side effects; touches nothing, only reads
    Chrome's Preferences JSON. Flags any profile that is a broadcast source."""
    import glob
    import json
    import socket

    root = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    if not os.path.isdir(root):
        return True, f"{socket.gethostname()}: no real Chrome profile dir — nothing can sync."

    lines, sources = [], 0
    prefs = sorted(glob.glob(os.path.join(root, "Default", "Preferences")) +
                   glob.glob(os.path.join(root, "Profile *", "Preferences")))
    for pref in prefs:
        try:
            p = json.load(open(pref))
        except Exception as e:  # noqa: BLE001
            lines.append(f"  {os.path.basename(os.path.dirname(pref))}: (unreadable: {type(e).__name__})")
            continue
        accts = [a.get("email") for a in p.get("account_info", []) if a.get("email")]
        if not accts:
            continue  # no Google account → cannot sync/broadcast
        # "history and tabs" (the tab-broadcast toggle) lives under the sync
        # data-type selections. Key name has varied across Chrome versions, so
        # check the known ones and fall back to the coarse setup flag.
        sync = p.get("sync", {})
        sel = sync.get("selected_types", {}) if isinstance(sync.get("selected_types"), dict) else {}
        tabs_on = sel.get("tabs")
        if tabs_on is None:
            tabs_on = sel.get("typedUrls", sync.get("has_setup_completed"))
        prof = os.path.basename(os.path.dirname(pref))
        flag = ""
        if tabs_on:
            flag = "  ⚠️ BROADCAST SOURCE (history+tabs sync ON)"
            sources += 1
        lines.append(f"  {prof}: {', '.join(accts)} · tabs-sync={'on' if tabs_on else 'off'}{flag}")

    head = f"{socket.gethostname()} · {sources} broadcast source(s)"
    if not lines:
        return True, head + "\n  (no profile is signed into a Google account — clean)"
    return True, head + "\n" + "\n".join(lines)


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
# pillow_heif lets the Sara+ escalation turn an iPhone .heic screenshot into a
# jpeg — without it that attachment reaches Sara+ support as a .heic almost no
# mail client can open (2026-08-11). Best-effort in the report, so a missing
# wheel degrades rather than fails.
# lxml is pandas.read_html's parser — indeed_source_report failed per-office on
# Lucy 2 without it (2026-08-21: every office FAIL "Missing optional dependency
# 'lxml'"), and any other report that parses an HTML table needs it too.
PIP_ALLOWLIST = {"reportlab", "playwright", "gspread", "pillow_heif", "lxml",
                 # headshot bot (2026-08-23): background removal
                 "rembg", "onnxruntime"}


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


def _action_git_recover(args: str) -> tuple[bool, str]:
    """LAST-RESORT remote recovery from a git CONFLICT that blocks every report.

    A pull that hits a merge conflict leaves `schedule_config.json` UNMERGED (UU)
    with `<<<<<<<` markers — no longer valid JSON, so every report that loads the
    schedule dies. `git_stash` can't touch unmerged paths and `update` refuses to
    run while unmerged, so nothing else here can clear it: THIS can. It force-
    resyncs the runner to origin/main:

        git merge/rebase --abort (if any) ; git fetch origin ; git reset --hard origin/main

    DESTRUCTIVE to UNCOMMITTED tracked edits (e.g. an onboard_apply not yet
    committed) — but those are reproducible (`lucy onboard_apply <kind> <key>`).
    Untracked files (browser profiles, extractor caches) are NOT touched — no
    `git clean`. After recovery: restart_poller if poller code changed, and re-run
    any pending onboard_apply to restore its Sheet-materialized entries.
    """
    def _git(*a, timeout=180):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a],
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or p.stderr).strip()

    _git("merge", "--abort")     # ignore result — may not be mid-merge
    _git("rebase", "--abort")
    okf, outf = _git("fetch", "origin", "main")
    if not okf:
        return False, f"git_recover: fetch failed: {outf[:200]}"
    okr, outr = _git("reset", "--hard", "origin/main")
    if not okr:
        return False, f"git_recover: reset failed: {outr[:200]}"
    _, head = _git("log", "-1", "--format=%h %ad %s", "--date=short")
    return True, ("recovered — hard reset to origin/main.\n"
                  f"HEAD now: {head}\n"
                  "Uncommitted tracked edits were discarded (re-run onboard_apply "
                  "to restore). restart_poller if poller code changed.")


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
    token = (args or "").lstrip("﻿").strip()
    # Accept whatever Slack accepts — 2026-08-21's lesson: the fleet's
    # PRODUCTION posting file on Lucy 1 is xoxb-prefixed yet auth_tests as
    # lucy_reporting with full posting scopes, and three rounds of prefix
    # guessing rejected it. The auth_test below is the only real gate; its
    # result names the authed account so a wrong identity is VISIBLE.
    if not token.startswith("xox"):
        return False, ("set_slack_user_token needs a Slack token "
                       "('xox…') as the Args")
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


def _action_push_slack_tokens(args: str) -> tuple[bool, str]:
    """Copy THIS machine's Slack tokens to another runner, zero-touch.

    Reads ~/.config/recruiting-report/slack-user-token + slack-bot-token and
    enqueues set_slack_user_token / set_slack_token rows on the TARGET
    machine's tab. The secrets ride the queue's Args cell exactly like a
    hand-pasted set_slack_token — both landing actions are in SECRET_ACTIONS,
    so the poller blanks the cell when the row finishes.

    Why (2026-08-21): provisioning Lucy 3 needed Lucy 1's tokens and every
    path required a human screen-share to read a token file. One installed
    token should feed the fleet — same idea as --appstream-push-fleet.

    Args: the target machine name, e.g. 'Lucy 3'."""
    # The CLI passthrough shlex-quotes args with spaces ('Lucy 3' arrives
    # WITH literal quotes) — strip them or the target tab lookup goes loose.
    target = (args or "").strip().strip("'\"").strip()
    if not target:
        return False, ("push_slack_tokens needs the target machine name as "
                       "Args, e.g. 'Lucy 3'")
    if target.lower() == _machine_profile().strip().lower():
        return False, "target is THIS machine — nothing to push"
    base = Path.home() / ".config" / "recruiting-report"
    pushed, skipped = [], []
    for fname, action, prefixes in (
            # Don't enumerate Slack's token formats (classic xoxp-, rotated
            # xoxe.xoxp-, and whatever ships next) — 2026-08-21 the push
            # rejected Lucy 1's REAL working token twice by guessing
            # prefixes. Anything 'xox…' goes; the LANDING action verifies
            # with a live auth_test, which is the test that matters.
            ("slack-user-token", "set_slack_user_token", ("xox",)),
            ("slack-bot-token", "set_slack_token", ("xoxb-", "xoxe.xoxb-"))):
        p = base / fname
        try:
            # utf-8-sig: Windows-written token files carry a BOM that
            # production's _load_token strips — a raw read pushed
            # '﻿xoxp-…' and the target rejected it (2026-08-21).
            token = p.read_text(encoding="utf-8-sig").lstrip("﻿").strip()
        except Exception:  # noqa: BLE001 — missing file just isn't pushed
            continue
        if not token:
            continue
        if not token.startswith(prefixes):
            skipped.append(f"{fname} (doesn't look like a "
                           f"{'/'.join(prefixes)}… token)")
            continue
        enqueue(action, token, by=f"push from {_machine_profile()}",
                machine=target, auto=True)
        pushed.append(fname)
    if not pushed:
        return False, ("nothing pushed — " + ("; ".join(skipped) if skipped
                       else "no Slack token files on this machine"))
    note = f" (skipped: {'; '.join(skipped)})" if skipped else ""
    return True, (f"queued {', '.join(pushed)} onto '{target}' — the target "
                  f"verifies each with auth_test; Args blank on landing{note}")


# Credential FILES the fleet can push machine-to-machine. Whitelisted key ->
# path, so a pushed secret can only ever land at a known location (same
# principle as set_office_slack_token's registered filenames). Extend here as
# new cred files earn fleet distribution.
_CRED_FILES = {
    "gmail-app-password":
        lambda: Path.home() / ".config" / "recruiting-report" / "gmail-app-password",
    "gmail-app-password-raffi127":
        lambda: Path.home() / ".config" / "recruiting-report" / "gmail-app-password-raffi127",
    "ownerville-creds":
        lambda: REPO_ROOT / "ownerville-creds.json",
    # Cross-workspace Slack bot tokens (office_metrics.offices.CROSS_WS_TOKEN_FILES).
    # push_slack_tokens moves only the MAIN workspace pair, so an office whose
    # channel lives in another Slack (trang -> FRESH SUCCESS) was silently left
    # behind on every new machine: Lucy 3 posted the 8/23 trackers to all 15 orgs
    # except trang's, which failed 'channel unreadable' on both runs. Add a key
    # here whenever CROSS_WS_TOKEN_FILES gains one, or the next machine repeats it.
    "slack-token-freshsuccess":
        lambda: Path.home() / ".config" / "recruiting-report" / "slack-token-freshsuccess",
    # Leader phone overlay for the New-Start texts (personal numbers — never
    # in git; the repo is PUBLIC). Filled on the laptop from
    # alphaletereception@'s Google Contacts (new_start_followup.contacts_google
    # --write), then pushed to Lucy 1, the machine whose Messages sends.
    "new-start-leader-phones":
        lambda: Path.home() / ".config" / "recruiting-report" / "new-start-leader-phones.json",
}


def _action_push_cred_file(args: str) -> tuple[bool, str]:
    """Push one whitelisted credential FILE from THIS machine to another
    runner (zero-touch, like push_slack_tokens — born 2026-08-21 when Lucy
    3's first dry tracker run died on a missing gmail-app-password that
    only existed on Lucy 1). Args: '<file-key> <target machine>'."""
    parts = (args or "").strip().strip("'\"").split(None, 1)
    if len(parts) < 2:
        return False, ("push_cred_file needs '<file-key> <target machine>' — "
                       f"known keys: {', '.join(sorted(_CRED_FILES))}")
    key, target = parts[0], parts[1].strip().strip("'\"").strip()
    if key not in _CRED_FILES:
        return False, f"unknown file-key '{key}' — known: {', '.join(sorted(_CRED_FILES))}"
    if target.lower() == _machine_profile().strip().lower():
        return False, "target is THIS machine — nothing to push"
    path = _CRED_FILES[key]()
    try:
        content = path.read_text(encoding="utf-8-sig")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't read {path.name} here: {str(e).splitlines()[0][:100]}"
    if not content.strip():
        return False, f"{path.name} is empty on this machine — not pushing"
    enqueue("set_cred_file", f"{key} {content}",
            by=f"push from {_machine_profile()}", machine=target, auto=True)
    return True, (f"queued {key} ({len(content)} chars) onto '{target}' — "
                  "Args blank on landing")


def _action_set_cred_file(args: str) -> tuple[bool, str]:
    """Install a pushed credential file at its whitelisted path (see
    _CRED_FILES). In SECRET_ACTIONS, so the Args cell blanks on finish.
    Backs up any existing file first; never echoes the contents."""
    parts = (args or "").split(None, 1)
    if len(parts) < 2:
        return False, "set_cred_file needs '<file-key> <contents>'"
    key, content = parts[0], parts[1]
    # UNWRAP shlex quoting. `lucy` shlex-joins Args before the Sheet round-trip,
    # so a JSON payload arrives as '{"a": 1}' — quotes included — and every later
    # reader gets "Expecting value: line 1 column 1 (char 0)". A bare token has no
    # special characters and never showed this, so it went unnoticed until Lucy 3's
    # ownerville-creds.json landed unreadable on 2026-08-23. Only unwrap when the
    # result is actually JSON, so a value that legitimately contains quotes is
    # left exactly as sent.
    _c = content.strip()
    if len(_c) >= 2 and _c[0] == _c[-1] and _c[0] in "'\"" \
            and _c[1:-1].lstrip()[:1] in ("{", "["):
        content = _c[1:-1]
        note = " (unwrapped shlex quoting)"
    else:
        note = ""
    if key not in _CRED_FILES:
        return False, f"unknown file-key '{key}' — known: {', '.join(sorted(_CRED_FILES))}"
    path = _CRED_FILES[key]()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            import shutil
            stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
            shutil.copy2(path, path.with_name(path.name + f".bak.{stamp}"))
        path.write_text(content, encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path.name}: {str(e).splitlines()[0][:120]}"
    return True, f"{path.name} installed ({len(content)} chars, chmod 600){note}"


def _action_set_office_slack_token(args: str) -> tuple[bool, str]:
    """set_office_slack_token <office_key> <xoxb-token>: install the WORKSPACE bot
    token for an office whose Slack channel lives in a non-AO workspace (e.g.
    trang -> FRESH SUCCESS). The office's token filename is registered in
    office_metrics.offices.CROSS_WS_TOKEN_FILES, so the token can only ever land
    at that known path — never an arbitrary file. Writes it, verifies with
    auth_test against the SAME file the runner reads, and NEVER echoes the token.
    In SECRET_ACTIONS, so the poller auto-blanks the Args cell when the row ends."""
    import shutil
    parts = (args or "").split()
    if len(parts) < 2:
        return False, "set_office_slack_token needs '<office_key> <xoxb-token>'"
    key, token = parts[0].strip(), parts[1].strip()
    if not token.startswith("xoxb-"):
        return False, "the token must be a Slack BOT token (starts with 'xoxb-')"
    try:
        from automations.office_metrics import offices as _off
        fname = _off.CROSS_WS_TOKEN_FILES.get(key)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't read office registry: {type(e).__name__}: {str(e)[:100]}"
    if not fname:
        return False, (f"office {key!r} has no cross-workspace token file in "
                       "offices.CROSS_WS_TOKEN_FILES — add it there first")
    path = Path.home() / ".config" / "recruiting-report" / fname
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{fname}.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(token, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify by reading the file back through a bot client — proof the runner will
    # authenticate. Never echo the token itself.
    try:
        import ssl as _ssl
        import certifi
        from slack_sdk import WebClient
        ctx = _ssl.create_default_context(cafile=certifi.where())
        who = WebClient(token=path.read_text(encoding="utf-8-sig").strip(),
                        ssl=ctx).auth_test()
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but auth_test errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    if not who.get("ok"):
        return False, f"token written but auth_test not ok: {str(who)[:120]}"
    return True, (f"{key} workspace Slack token installed + verified: authed as "
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


def _action_set_gdocs_token(args: str) -> tuple[bool, str]:
    """Install the Google Docs OAuth token on THIS machine so the Sunday rep
    shout-out run can write the names onto the Monday ATMO print unattended. Args
    is the CONTENTS of ~/.config/brand-audit/gdocs-token.json (a JSON object with
    a refresh_token). Backs up any existing token, writes it, then verifies by
    fetching the target doc. NEVER echoes the token. In SECRET_ACTIONS, so the
    poller auto-blanks the Args cell the moment the row ends."""
    import json
    import shlex
    import shutil
    raw = (args or "").strip()
    try:
        parts = shlex.split(raw)
        blob = parts[0].strip() if parts else raw
    except Exception:  # noqa: BLE001
        blob = raw
    if not blob.startswith("{"):
        return False, "set_gdocs_token needs the gdocs-token.json CONTENTS (a JSON object) as Args"
    try:
        parsed = json.loads(blob)
    except Exception as e:  # noqa: BLE001
        return False, f"Args isn't valid JSON: {str(e).splitlines()[0][:120]}"
    if not parsed.get("refresh_token"):
        return False, "token JSON has no refresh_token — re-authorize and pass the whole file"
    path = Path.home() / ".config" / "brand-audit" / "gdocs-token.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"gdocs-token.json.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify: fetch the target doc through the SAME service the Sunday job uses.
    try:
        from automations.brand_audit import atmo_doc
        svc = atmo_doc._service()
        doc = svc.documents().get(documentId=atmo_doc.DOC_ID).execute()
        title = doc.get("title", "?")
    except Exception as e:  # noqa: BLE001
        return True, (f"token written to {path} but verify errored "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]})")
    return True, f"Docs token installed + verified: reached {title!r}"


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


def _action_set_credico_state(args: str) -> tuple[bool, str]:
    """Install a Credico browser session on THIS machine so the DD pull can run
    unattended. Args is the CONTENTS of the .credico_storage_state.json produced
    by `python -m automations.credico.session --login` on a machine where a HUMAN
    did the login.

    WHY THIS EXISTS. credico_fetch died on 2026-08-13 with "Credico session
    expired", and session.py's only documented fix is an interactive headed login
    ON LUCY 1 with someone at the screen — but nobody had access to that screen,
    and the Thursday DD Bulletin needs the Credico fold by 10:30 Central. Same
    escape hatch as set_contacts_ro_token: the human step does not have to happen
    on the mini. Eve logs in on her own machine; this ships the RESULT.

    No password travels — a Credico session is cookies + localStorage, and
    session.py never types credentials on either machine.

    This is NOT the Chrome-profile copy _action_sheets_login rules out. That
    fails because Chrome seals its cookie store with an OS key. A Playwright
    storage_state is a plain JSON file with no OS key in it, so it replays
    elsewhere. Credico may still refuse a session presented from a different
    IP — the verify below is what tells us, and a rejection costs only the round
    trip (the saved session is already dead, so there is nothing to lose).

    Backs up any existing state, writes it 0600, then verifies with the REAL
    loader. NEVER echoes the state. In SECRET_ACTIONS, so the poller blanks the
    Args cell the moment the row ends."""
    import json
    import shlex
    import shutil
    # Same two delivery paths as set_gmail_token: `lucy` shlex-JOINS its args,
    # while enqueue() writes the cell verbatim. Try the raw text FIRST — shlex
    # on raw JSON eats the quotes — then fall back to un-shlexing.
    raw = (args or "").strip()
    parsed = None
    for cand in (raw, *([shlex.split(raw)[0]] if _safe_shlex_first(raw) else [])):
        cand = (cand or "").strip()
        if not cand.startswith("{"):
            continue
        try:
            parsed = json.loads(cand)
            break
        except Exception:  # noqa: BLE001 — try the next candidate
            continue
    if parsed is None:
        return False, ("set_credico_state needs the CONTENTS of "
                       ".credico_storage_state.json (a JSON object) as Args")
    # Credico is a hash-router SPA that keeps its auth token in localStorage, NOT
    # in cookies (see session.credico_session). A cookies-only state passes every
    # cheap check and then fails on the NEXT pull, a week later — refuse it here
    # instead, the same way save_login warns about it at the source.
    n_c = len(parsed.get("cookies") or [])
    n_ls = sum(len(o.get("localStorage", []) or [])
               for o in (parsed.get("origins") or []))
    if n_ls == 0:
        return False, ("no localStorage in this state — that's where Credico "
                       "keeps its auth token, so the login never completed. "
                       "Re-run --login and wait for the dashboard to be fully "
                       "on screen before closing it.")

    from automations.credico.session import STATE as path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't create {path.parent}: {str(e).splitlines()[0][:120]}"
    if path.exists():
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{path.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    try:
        path.write_text(json.dumps(parsed, indent=1), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"
    # Verify through the SAME loader every Credico report uses — proof the
    # replayed session authenticates FROM THIS MACHINE, not just from Eve's.
    ok, res = _run_cmd([sys.executable, "-m", "automations.credico.session",
                        "--check"],
                       timeout_s=5 * 60, log_name="credico-set-state.log")
    head = f"{n_c} cookie(s) + {n_ls} localStorage item(s) installed · "
    if ok:
        return True, head + "session VERIFIED here — credico_fetch can run"
    return False, (head + "but Credico REJECTED it on this machine: " +
                   res[:150] + " — the session may be bound to the browser/IP "
                   "that logged in; full log: lucy logtail credico-set-state")


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


def _action_set_alphalete_app_password(args: str) -> tuple[bool, str]:
    """Install the alphaletereporting@ Gmail APP PASSWORD on THIS machine. Args
    is the 16-char app password (spaces ok). Writes it to
    ~/.config/recruiting-report/gmail-app-password (chmod 600), then verifies by
    logging into BOTH Gmail SMTP (the sending half) and IMAP (the reading half).
    NEVER echoes the password.

    This one file is what nearly every emailing report shares: the SMTP sender
    (scheduled_6_days_out.email_send.app_password — captainship, org board, board
    emails, override bulletin, BOX order log, SARA down, the orchestrator's own
    notifications) and the IMAP readers (shared.email_ingest, sci_campaigns,
    residential_rep_count). Changing that account's Gmail password REVOKES the
    app password, so a rotation silently breaks all of them at once until the new
    one lands on every runner. Only raffi127's could be pushed remotely; this one
    had to be typed at each mini, which nobody can sit at (Eve 2026-08-13).

    In SECRET_ACTIONS, so the poller blanks the Args cell the moment the row ends.
    """
    import smtplib
    import ssl

    # Google DISPLAYS the password as 4 groups of 4, and that is how it gets
    # copied, so the whole Args cell is the password — join every whitespace-
    # separated piece instead of taking the first token (shlex.split + parts[0]
    # would keep only 'jlar' out of 'jlar ukpl vlce kfwz' and fail the length
    # check below). Surrounding quotes are dropped for the caller who quotes it.
    raw = (args or "").strip().strip('"').strip("'")
    pw = "".join(raw.split())
    if len(pw) < 12:
        return False, ("set_alphalete_app_password needs the 16-char app password "
                       "as Args (generate it at myaccount.google.com → Security → "
                       "App passwords, signed in as alphaletereporting@)")
    path = Path.home() / ".config" / "recruiting-report" / "gmail-app-password"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pw + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path}: {str(e).splitlines()[0][:120]}"

    # Verify through the SAME loaders the reports use. SMTP first: it is the half
    # with the most consumers, and an auth failure there means the paste is wrong
    # (or belongs to another account) — worth failing the row over, since a
    # written-but-dead credential looks installed while every send still breaks.
    from automations.scheduled_6_days_out.email_send import (
        FROM_ADDR, SMTP_HOST, SMTP_PORT, _APP_PW_ENV, app_password)
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                              context=ssl.create_default_context(),
                              timeout=45) as s:
            s.login(FROM_ADDR, app_password())
    except Exception as e:  # noqa: BLE001
        return False, (f"written to {path} but SMTP login FAILED "
                       f"({type(e).__name__}: {str(e).splitlines()[0][:100]}) — "
                       f"wrong app password, or it belongs to another account. "
                       f"Reports on this machine still can't send.")
    # email_send reads the env var BEFORE the file, so a stale env var on this
    # machine would keep winning over what we just wrote — and the SMTP check
    # above would have tested the env var, not the new paste.
    env_note = ""
    if os.environ.get(_APP_PW_ENV, "").strip():
        env_note = (f" ⚠ {_APP_PW_ENV} is set in this machine's environment and "
                    f"OVERRIDES the file — unset it or the old password keeps "
                    f"being used by the sending half")
    try:
        from automations.shared import email_ingest
        M = email_ingest._connect()
        M.logout()
    except Exception as e:  # noqa: BLE001
        return True, (f"app password installed, SMTP send verified — but IMAP "
                      f"login FAILED ({type(e).__name__}: "
                      f"{str(e).splitlines()[0][:90]}); inbox-reading reports "
                      f"(financial, sci_campaigns, residential_rep_count) are "
                      f"still down{env_note}")
    return True, (f"alphaletereporting app password installed + verified "
                  f"(SMTP send + IMAP read){env_note}")


def _action_set_doubleentry_creds(args: str) -> tuple[bool, str]:
    """Install the Double Entry (doubleentry.com) login on THIS machine, so the
    Thursday financial_report can pull the ORG SUMMARY REPORT unattended now that
    the financials come off the web instead of emailed workbooks.

    Args is `<username> <password>` — quote the password if it contains spaces.
    Merges the two keys into the repo-root ownerville-creds.json (every other
    credential in that file is left untouched), backs the file up first, then
    VERIFIES by actually signing in through the same code path the report uses.
    NEVER echoes the password.

    Nobody can sit at Lucy, so this is the only way the credential reaches it
    (Eve 2026-08-02). The password transits the control Sheet's Args cell — the
    poller BLANKS that cell itself the moment the row finishes (SECRET_ACTIONS),
    rather than trusting a human to remember, because `lucy status` dumps the
    whole Args column."""
    import json
    import shlex
    import shutil
    try:
        parts = shlex.split((args or "").strip())
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't read Args ({str(e)[:80]}) — quote the password"
    if len(parts) != 2:
        return False, ("set_doubleentry_creds needs exactly `<username> "
                       "<password>` as the Args (quote the password if it has "
                       f"spaces) — got {len(parts)} value(s)")
    user, pw = parts[0].strip(), parts[1]
    if len(pw) < 6:
        return False, "that password looks too short — check the Args"
    path = REPO_ROOT / "ownerville-creds.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception as e:  # noqa: BLE001
            return False, f"couldn't read {path.name}: {str(e).splitlines()[0][:120]}"
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{path.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    data["doubleentry_username"] = user
    data["doubleentry_password"] = pw
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path.name}: {str(e).splitlines()[0][:120]}"
    # Verify with a REAL headless sign-in. This is also the answer to "can this
    # run unattended here at all?" — if Double Entry ever puts a second factor in
    # front of the login, it fails HERE, at install time, instead of silently on
    # a Thursday 4am run.
    try:
        from automations.financial_report import web_source
        ok, detail = web_source.check_login()
    except Exception as e:  # noqa: BLE001
        return True, (f"creds written to {path.name} but the verify couldn't run "
                      f"({type(e).__name__}: {str(e).splitlines()[0][:110]}) — "
                      "run `playwright_install` if patchright is missing")
    if not ok:
        return False, f"creds written to {path.name} but SIGN-IN FAILED: {detail}"
    return True, f"Double Entry creds installed for {user} + sign-in verified · {detail}"


def _action_install_enrollment_pending(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the pending-enrollments LaunchAgent
    (com.alphalete.enrollment-pending-hourly) on THIS machine — hourly 09:00
    through 22:00, every day.

    Megan 2026-08-19: the check moved OFF the 4am orchestrator pass onto this
    cadence, so until this agent is bootstrapped it runs NOWHERE. It only speaks
    when an office enrollment is sitting un-applied, so a silent card is the
    healthy state — which is exactly why a missing agent would go unnoticed.

    Regenerates the plist for this machine's path, lints it, runs a real
    smoke test (the module reads the sheet and posts only on a genuine pending
    row), then bootstraps. Run `update` first so the plist and wrapper exist."""
    uid = os.getuid()
    label = "com.alphalete.enrollment-pending-hourly"
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "enrollment_pending_hourly.sh"
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
    smoke_ok, smoke = _run_cmd(
        [sys.executable, "-m", "automations.office_onboarding.pending_alert"],
        timeout_s=180, log_name="enrollment-pending-install-smoke.log")
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
    return True, (f"installed {label} (hourly 09:00-22:00) · smoke ok · {smoke[:70]}")


def _action_git_push_setup(args: str) -> tuple[bool, str]:
    """One-time: give THIS machine push access to the Hub repo via its own SSH
    deploy key — so the enrollment auto-commit can make a confirmed office
    durable from an always-on runner instead of the laptop (Megan 2026-08-20:
    "my laptop won't always be on — that's why we have lucy 1 and 2").

    Generates ~/.ssh/alphalete_hub_deploy (ed25519, no passphrase) if absent,
    configures THE REPO ONLY (ssh push URL + pinned key + committer identity —
    nothing global, fetch URL untouched so `update` keeps working over https),
    and returns the PUBLIC key. Register that on GitHub as a READ-WRITE deploy
    key (repo → Settings → Deploy keys), then verify with `git_push_check`.
    Idempotent — re-running reuses the existing key."""
    def _git(*a):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a],
                           capture_output=True, text=True, timeout=60)
        return p.returncode == 0, (p.stdout or p.stderr).strip()
    key = Path.home() / ".ssh" / "alphalete_hub_deploy"
    try:
        key.parent.mkdir(mode=0o700, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    if not key.exists():
        r = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C",
             "alphalete-hub-auto-commit-" + _machine_profile().replace(" ", ""),
             "-f", str(key)],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return False, f"ssh-keygen failed: {(r.stderr or r.stdout)[:200]}"
    try:
        pub = key.with_suffix(".pub").read_text().strip()
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't read public key: {str(e)[:160]}"
    ssh_cmd = (f'ssh -i "{key}" -o IdentitiesOnly=yes '
               "-o StrictHostKeyChecking=accept-new")
    for k, v in (("core.sshCommand", ssh_cmd),
                 ("user.name", f"Alphalete Runner ({_machine_profile()})"),
                 ("user.email", "alphaletereporting@gmail.com")):
        ok, out = _git("config", k, v)
        if not ok:
            return False, f"git config {k} failed: {out[:160]}"
    ok, out = _git("remote", "set-url", "--push", "origin",
                   "git@github.com:raffi127-ctrl/Alphalete-Reporting-Hub.git")
    if not ok:
        return False, f"set-url --push failed: {out[:160]}"
    return True, f"PUBKEY {pub}"


def _action_git_push_check(args: str) -> tuple[bool, str]:
    """`git push --dry-run origin main` — proves the deploy key + push wiring
    work end to end WITHOUT pushing anything. Run after git_push_setup + the
    key is registered on GitHub."""
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "push", "--dry-run",
                        "origin", "main"],
                       capture_output=True, text=True, timeout=120)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode == 0, (out[:300] or f"exit {p.returncode}")


def _action_install_tracker_auto_commit(args: str) -> tuple[bool, str]:
    """Install (or reinstall) the tracker enrollment auto-commit LaunchAgent
    (com.alphalete.tracker-auto-commit) on THIS machine — daily 03:15 + 17:30.
    It commits confirmed (wired) tracker enrollments to origin/main so the 4am
    self-update can never reset a freshly confirmed office out of the daily
    tracker run. Prereqs, in order: `update`, `restart_poller`,
    `git_push_setup` (+ key registered on GitHub), `git_push_check`.
    Smoke = push --dry-run, then one REAL module pass (idempotent — a quiet
    day prints 'No enrollment changes')."""
    uid = os.getuid()
    label = "com.alphalete.tracker-auto-commit"
    src_plist = REPO_ROOT / "deploy" / f"{label}.plist"
    wrapper = REPO_ROOT / "deploy" / "tracker_auto_commit.sh"
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
    # smoke 1: push auth must already work, else the agent would fail silently
    # at 3am forever.
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "push", "--dry-run",
                        "origin", "main"],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        return False, ("push --dry-run failed — run git_push_setup and "
                       "register the key first: "
                       + ((p.stderr or p.stdout) or "").strip()[:150])
    # smoke 2: one real pass (idempotent).
    smoke_ok, smoke = _run_cmd(
        [sys.executable, "-m", "automations.tracker_onboarding.auto_commit"],
        timeout_s=300, log_name="tracker-auto-commit-install-smoke.log")
    if not smoke_ok:
        return False, f"smoke pass failed — NOT going live: {smoke[:150]}"
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "enable", f"gui/{uid}/{label}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    boot = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dst_plist)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if boot.returncode != 0:
        return False, f"smoke ok; bootstrap FAILED: {(boot.stdout or '').strip()[:150]}"
    return True, f"installed {label} (03:15 + 17:30) · smoke ok · {smoke[:70]}"


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


def _action_post_nsf_correction(args: str) -> tuple[bool, str]:
    """One-off: post the corrected New-Start counts into Aisha's weekly thread as
    Lucy (week of 8/3). Default LIVE; pass --dry-run to just print."""
    import shlex
    extra = shlex.split(args) if (args or "").strip() else ["--post"]
    ok, out = _run_cmd([sys.executable, "-m",
                        "automations.new_start_followup.post_correction", *extra],
                       timeout_s=120, log_name="nsf-correction.log")
    tail = [ln for ln in (out or "").splitlines() if "posted" in ln or "identity" in ln]
    return ok, (" · ".join(tail)[:300] or (out or "")[-200:])


def _action_post_note(args: str) -> tuple[bool, str]:
    """post_note <channel_id> <text>: post a plain message to Slack from THIS
    machine's Slack identity. On a mini that identity is Lucy, which is the whole
    point — a note typed from the laptop would go out as Evelyn, and a reminder
    to the team about the reports should come from the account that runs them
    ([[reference_lucy-slack-identity]], [[project_two-lucy-slack-accounts]]).

    The text is everything after the channel id. Literal '\\n' becomes a newline,
    since the queue carries the whole thing in one Sheet cell. Slack mrkdwn
    works (*bold*, `code`, <@U…> mentions).

    Not a report and not idempotent — it posts once per queued row. Queue it
    again and the channel gets a second copy."""
    raw = (args or "").strip()
    parts = raw.split(None, 1)
    if len(parts) < 2 or not parts[0].upper().startswith("C"):
        return False, ("post_note needs '<channel_id> <text>' (channel id looks "
                       "like C0BK5PRG259 — #claudecorrections-and-requests)")
    channel, text = parts[0].strip(), parts[1].strip().replace("\\n", "\n")
    if not text:
        return False, "post_note got an empty message"
    try:
        from automations.shared import slack_metrics_post as smp
        who = "?"
        try:
            who = smp._client().auth_test().get("user", "?")
        except Exception:  # noqa: BLE001
            pass
        smp._client().chat_postMessage(channel=channel, text=text)
    except Exception as e:  # noqa: BLE001
        return False, (f"couldn't post to {channel} "
                       f"({type(e).__name__}: {str(e).splitlines()[0][:120]})")
    return True, f"posted to {channel} as {who} ({len(text)} chars)"


def _action_incident_resolve(args: str) -> tuple[bool, str]:
    """Close an OPEN incident thread in #claudecorrections-and-requests, from
    THIS machine's Slack identity.

      incident_resolve <key> [note]
        key   the id in the thread's own marker line, e.g.
              `_incident · failure-captainship_cancel_rate · open 2026-08-15_`
        note  optional one-liner appended under the ✅ (say WHY it's closed)

    WHY THIS EXISTS (2026-08-15). Several reports moved to "fill-but-flag": they
    do the whole job, merely NOTE a data gap, exit 0, and land INCOMPLETE via the
    run-manifest (captainship_cancel_rate, owners_metrics_churn e568bf9,
    vantura_board_audit 8fa4e2e). But `_close_carryover_incidents` in run.py only
    closes a thread for a report that reached **DONE**, and a soft INCOMPLETE
    never does while the data gap persists — so its thread stays open forever.
    That is exactly the "which of these is still real?" pile the incident threads
    were built to prevent, and until now nothing could close one by hand.

    RUN IT FROM THE MINI. `incident_thread.resolve` replies in the thread AND
    edits the parent post to ✅ — and chat.update only works on your OWN
    messages. The parents are posted by Lucy, so the same command from a laptop
    leaves the header still reading `open` while the reply says resolved
    ([[reference_lucy-slack-identity]], [[project_two-lucy-slack-accounts]]).

    Idempotent in the way that matters: a key with no OPEN incident returns a
    plain "nothing to close", never a second ✅ on a thread that already has one.
    """
    raw = (args or "").strip()
    if not raw:
        return False, ("incident_resolve needs a key (e.g. "
                       "failure-captainship_cancel_rate); an optional note "
                       "follows it")
    parts = raw.split(None, 1)
    key = parts[0].strip()
    note = parts[1].strip().replace("\\n", " ") if len(parts) > 1 else ""
    try:
        from automations.shared import incident_thread as inc
    except Exception as e:  # noqa: BLE001
        return False, (f"couldn't import incident_thread "
                       f"({type(e).__name__}: {str(e)[:90]})")
    # A REPORT ID is as valid here as an incident key. mark_working already took
    # both; this took only the key, so `incident_thread --resolve-report <id>`
    # handed off from a laptop arrived as a bare id and died on "no OPEN
    # incident for 'vantura-board-audit'" — the id is right, it just isn't the
    # key (`drop-vantura-board-audit`), and the laptop can't translate it: the
    # index that maps id → key lives on the machine that opened the thread.
    # The poller is a LONG-LIVED process and incident_thread caches the channel
    # history in a module global for the life of that process (_HISTORY_CACHE,
    # invalidated only after IT posts something). A thread another machine opened
    # after the poller booted is therefore invisible to the lookup below, which
    # fails as "no OPEN incident" while the post is sitting right there. Drop the
    # cache first — one extra conversations.history call per queued row, nothing
    # next to silently swallowing a :pending: or a ✅.
    #
    # NOT confirmed as the cause of the 2026-08-18 outage: 5 hand-offs failed that
    # day (drop-tableau-screenshots ×2, drop-tableau-screenshots-box,
    # org-sales-board, drop-org-sales-board) and a restart_poller did NOT clear
    # it, so something else is also wrong on that path. This closes a real
    # staleness hole; it is not the whole fix, and that outage is still open.
    inc._forget_history(inc.CHANNEL)
    # A key or a report id — resolve_any() tries the string LITERALLY first and
    # only then expands it. The old test was the prefix alone, which broke every
    # thread filed under a CUSTOM key (vantura-sales-week-hold, org-sales-board,
    # applicant-tracker-gaps): those have no family prefix, so a key copied
    # straight off its own marker line was treated as a report id, expanded to
    # `failure-<key>`, and died on "no OPEN incident" with the post right there.
    # (2026-08-19)
    try:
        if inc.resolve_any(key, note=note):
            told = True
        else:
            told = inc.resolve_report(key, note=note)
    except Exception as e:  # noqa: BLE001 — resolve() swallows its own, but the
        # import-time client build can still raise (no token on this machine).
        return False, (f"resolve failed ({type(e).__name__}: {str(e)[:100]})")
    if not told:
        return False, (f"no OPEN incident for {key!r} — copy the key from the "
                       f"thread's marker line (_incident · <key> · open …_); it "
                       f"may already be closed")
    return True, (f"closed {key} — replied in its own thread and marked the "
                  f"parent post resolved")


def _action_incident_working(args: str) -> tuple[bool, str]:
    """Mark an open incident thread as BEING WORKED ON — a :pending: reaction on
    its post in #claudecorrections-and-requests.

      incident_working <key|report_id> [note]

    WHY FROM THE MINI (Eve 2026-08-17): every message and reaction in that
    channel goes out as Lucy, and the mini is Lucy. A laptop reacting under a
    person's own name is exactly the ambiguity this is meant to remove — two
    people pick tickets off that channel, so ":pending: means someone is on it"
    only works if it always comes from the same place.

    The ✅ that closes the incident clears the :pending: on its own, so nothing
    has to remember to un-mark it."""
    raw = (args or "").strip()
    if not raw:
        return False, ("incident_working needs a key or report id (e.g. "
                       "b2b_metrics)")
    parts = raw.split(None, 1)
    key = parts[0].strip()
    note = parts[1].strip().replace("\\n", " ") if len(parts) > 1 else ""
    try:
        from automations.shared import incident_thread as inc
    except Exception as e:  # noqa: BLE001
        return False, (f"couldn't import incident_thread "
                       f"({type(e).__name__}: {str(e)[:90]})")
    # The poller is a LONG-LIVED process and incident_thread caches the channel
    # history in a module global for the life of that process (_HISTORY_CACHE,
    # invalidated only after IT posts something). A thread another machine opened
    # after the poller booted is therefore invisible to the lookup below, which
    # fails as "no OPEN incident" while the post is sitting right there. Drop the
    # cache first — one extra conversations.history call per queued row, nothing
    # next to silently swallowing a :pending: or a ✅.
    #
    # NOT confirmed as the cause of the 2026-08-18 outage: 5 hand-offs failed that
    # day (drop-tableau-screenshots ×2, drop-tableau-screenshots-box,
    # org-sales-board, drop-org-sales-board) and a restart_poller did NOT clear
    # it, so something else is also wrong on that path. This closes a real
    # staleness hole; it is not the whole fix, and that outage is still open.
    inc._forget_history(inc.CHANNEL)
    try:
        ok = inc.mark_working(key, note=note)
    except Exception as e:  # noqa: BLE001
        return False, f"mark_working failed ({type(e).__name__}: {str(e)[:100]})"
    if not ok:
        return False, (f"no OPEN incident for {key!r} — nothing to mark "
                       f"(it may already be closed)")
    return True, f"{key} marked :pending: — someone is on it"


def _action_incident_unmark(args: str) -> tuple[bool, str]:
    """Take the :pending: / waiting mark back OFF an incident post — nobody is
    on it after all.

      incident_unmark <key|report_id>

    The incident's STATE is untouched: an open ticket stays open, it just stops
    claiming somebody has picked it up. Works on a closed post too.

    WHY IT HAS TO RUN HERE: Slack only lets you remove your OWN reaction, and
    these marks are Lucy's. The mini is Lucy — from a laptop this would try to
    remove a reaction that isn't there and change nothing.

    What it is for (Megan 2026-08-20): the 4am batch loads its code at 04:00 and
    keeps it in memory all morning, so a `git pull` mid-morning does NOT stop the
    running process from behaving the old way. `failure-credico_fetch` got a
    :pending: at 08:30 from code that had been fixed on disk an hour earlier.
    Also covers the ordinary case — somebody picked a ticket up, then put it
    down."""
    key = (args or "").strip().split(None, 1)[0] if (args or "").strip() else ""
    if not key:
        return False, ("incident_unmark needs a key or report id (e.g. "
                       "failure-credico_fetch)")
    try:
        from automations.shared import incident_thread as inc
    except Exception as e:  # noqa: BLE001
        return False, (f"couldn't import incident_thread "
                       f"({type(e).__name__}: {str(e)[:90]})")
    # Same long-lived-poller staleness as the two actions above: this process
    # caches channel history for its whole life, so a post opened after it booted
    # is invisible until the cache is dropped.
    inc._forget_history(inc.CHANNEL)
    try:
        ok = inc.mark_not_working(key)
    except Exception as e:  # noqa: BLE001
        return False, (f"mark_not_working failed ({type(e).__name__}: "
                       f"{str(e)[:100]})")
    if not ok:
        return False, (f"no post found for {key!r} — copy the key off the "
                       f"thread's marker line (_incident · <key> · … _)")
    return True, f"{key}: in-progress mark cleared — nobody is shown on it now"


def _action_run_bg_check_sync(args: str) -> tuple[bool, str]:
    """Run bg_check_sync NOW on THIS machine. Default = LIVE (writes col K + posts
    the weekly thread in BOTH recruiting rooms as Lucy). Pass extra args to override,
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


def _action_probe_knocks(args: str) -> tuple[bool, str]:
    """READ-ONLY: scrape ONE office's knocks for ONE day and print what came
    back. Touches no Sheet, posts nothing to Slack — it runs
    `automations.rashad_metrics.knocks_pull` standalone, whose whole job is the
    preview (`_print_preview`).

      probe_knocks "<ownerville office>" [YYYY-MM-DD] [campaign=<id|none>]
        office  the name to IMPERSONATE — i.e. an office's `knocks_office` in
                office_metrics/offices.py, NOT its owner. Quote it.
                Use the word `master` for Raf's own office: his login IS
                office 11280, so he is not in the Office Access list and
                CANNOT be impersonated — probing him by name just returns
                "couldn't be found in ownerville" (2026-08-24). `master`
                runs total_knocks.pull instead, which is the exact path his
                daily report uses.
        date    default: yesterday (Central), same as the daily run.
        campaign=<id>    pin a different TeleMapper campaign for this probe
        campaign=none    skip the pin entirely (what an NDS office gets in
                         weekly_knock_dispositions). Lets the "is the pin
                         blanking this office?" question be asked from the
                         laptop instead of needing a code change + deploy.

    Why this exists: when a daily metrics run posts "No data available", the log
    only says `0 rep(s)` — which reads identically whether (a) the office really
    logged nothing, (b) its roster moved, or (c) the scrape broke. Re-running the
    report to find out re-POSTS to the office's channel. This asks the same
    question with no side effects, and takes a DATE, so you can compare a
    suspect day against a known-good one:

      probe_knocks "Muhammad Waqar" 2026-07-30   → 7 rep(s), known good
      probe_knocks "Muhammad Waqar" 2026-08-04   → 0 rep(s), the day in question

    Read the full table with `lucy logtail probe-knocks-<office>`."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, ('probe_knocks needs an office name, e.g. '
                       'probe_knocks "Muhammad Waqar" 2026-08-04')
    office = parts[0].strip()
    date_arg = None
    campaign = None                      # None = leave the default pin alone
    for raw in parts[1:]:
        arg = raw.strip()
        if arg.lower().startswith("campaign="):
            val = arg.split("=", 1)[1].strip()
            # 'none' / '' both mean DON'T pin — knocks_pull skips the pin on
            # an empty KNOCKS_CAMPAIGN_ID.
            campaign = "" if val.lower() in ("none", "off", "") else val
            continue
        date_arg = arg
    if date_arg:
        try:
            dt.datetime.strptime(date_arg, "%Y-%m-%d")
        except ValueError:
            return False, f"probe_knocks: date must be YYYY-MM-DD, got {date_arg!r}"
    # Same guard the other browser actions use — a human Chrome left open on the
    # mini single-instances with patchright's and breaks the scrape.
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome()
    except Exception:  # noqa: BLE001 — a guard must never crash the run
        pass
    master = office.lower() in ("master", "raf", "rafael hidalgo")
    module = ("automations.total_knocks.pull" if master
              else "automations.rashad_metrics.knocks_pull")
    cmd = [sys.executable, "-m", module]
    if date_arg:
        cmd.append(date_arg)
    env = {} if master else {"KNOCKS_OFFICE": office}
    if campaign is not None:
        env["KNOCKS_CAMPAIGN_ID"] = campaign
    slug = "".join(c if c.isalnum() else "-" for c in office).strip("-").lower()
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    ok, res = _run_cmd(cmd, timeout_s=15 * 60,
                       log_name=f"probe-knocks-{slug}-{stamp}.log",
                       env=env or None)
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


def _action_sendimage_diag(args: str) -> tuple[bool, str]:
    """Try several AppleScript attachment forms at ONE number, each labelled.

    Args:  <phone> [image path]   (default image = today's hourly AT&T shot)

    Sending an image through Messages is the one step that fails SILENTLY:
    osascript returns success and the attachment never arrives, which is what
    happened on the first live disposition text (2026-08-04) and, in hindsight,
    is why the Texas de Brazil image sends were never actually landing either.
    Since nothing errors, the only way to learn which form works is to fire each
    one at a single willing recipient with a label in front of it and ask which
    labels showed up. Deliberately 1:1 — never point this at a group.

    Each variant sends a text tag first, then the image, so a missing image is
    attributable to a specific form rather than to the whole run."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, "sendimage_diag needs a phone number"
    phone = _normalize_us_phone(parts[0])
    if len(parts) > 1:
        img = Path(parts[1])
    else:
        from automations.b2b_dispositions import run as bd_run
        img = (bd_run.OUTPUT_DIR / dt.date.today().isoformat() / "hourly_at-t.png")
    if not img.exists():
        return False, f"no image at {img}"
    p = str(img).replace("\\", "\\\\").replace('"', '\\"')

    # RESOLVE the 1:1 chat id — never construct it. The first run of this diag
    # guessed "iMessage;-;+1XXX" and Messages answered "Can't get chat id …",
    # which made the two chat-id variants look like failures when the test itself
    # was malformed. Those are the variants that matter, because the group send
    # addresses a chat id too.
    ok_c, found = _osascript(
        'tell application "Messages"\n'
        '  set res to ""\n'
        '  repeat with c in chats\n'
        '    try\n'
        f'      if (id of c) contains "{phone}" then set res to res & (id of c) & linefeed\n'
        '    end try\n'
        '  end repeat\n'
        '  return res\n'
        'end tell', timeout=120)
    ids = [x.strip() for x in (found or "").splitlines() if x.strip()] if ok_c else []
    if not ids:
        return False, (f"no existing 1:1 chat with {phone} on this machine — send "
                       "that number a plain text first so the thread exists, then "
                       "re-run")
    chat_id = ids[0].replace("\\", "\\\\").replace('"', '\\"')

    def _tag(n: int, how: str) -> tuple[bool, str]:
        return _osascript(
            'tell application "Messages"\n'
            '  set svcId to id of 1st service whose service type = iMessage\n'
            f'  send "IMG TEST v{n} — {how}" to buddy "{phone}" of service id svcId\n'
            'end tell', timeout=120)

    variants = [
        # v1: exactly what the disposition send used (POSIX file, inside tell,
        # addressed to a chat id). This is the one that silently did nothing.
        (1, "POSIX file -> chat id",
         'tell application "Messages"\n'
         f'  set theChat to a reference to chat id "{chat_id}"\n'
         f'  send (POSIX file "{p}") to theChat\n'
         'end tell'),
        # v2: coerce to an alias OUTSIDE the tell block — the form most commonly
        # reported as the one that still works on recent macOS.
        (2, "alias outside tell -> chat id",
         f'set f to (POSIX file "{p}") as alias\n'
         'tell application "Messages"\n'
         f'  set theChat to a reference to chat id "{chat_id}"\n'
         '  send f to theChat\n'
         'end tell'),
        # v3: address a buddy instead of a chat. swag believes this can't work;
        # worth one datapoint rather than another inherited assumption.
        (3, "POSIX file -> buddy",
         'tell application "Messages"\n'
         '  set svcId to id of 1st service whose service type = iMessage\n'
         f'  send (POSIX file "{p}") to buddy "{phone}" of service id svcId\n'
         'end tell'),
        # v4: alias + buddy.
        (4, "alias outside tell -> buddy",
         f'set f to (POSIX file "{p}") as alias\n'
         'tell application "Messages"\n'
         '  set svcId to id of 1st service whose service type = iMessage\n'
         f'  send f to buddy "{phone}" of service id svcId\n'
         'end tell'),
    ]

    out = []
    for n, how, script in variants:
        _tag(n, how)
        time.sleep(3)
        ok, res = _osascript(script, timeout=180)
        out.append(f"v{n}({how.split(' -> ')[0]}): "
                   + ("no error" if ok else f"ERROR {res[:60]}"))
        time.sleep(12)   # let Messages finish the upload before the next one
    return True, (f"sent 4 labelled attempts + image {img.name} to {phone} "
                  f"(chat id {chat_id[:34]}…) · " + " · ".join(out)
                  + " · ASK THE RECIPIENT which v#'s IMAGE actually arrived — "
                    "'no error' here does NOT mean it was delivered")


def _action_sendimage_fmt(args: str) -> tuple[bool, str]:
    """Does Messages reject the IMAGE ITSELF rather than the send?

    Args:  <phone> [image path]

    Every AppleScript addressing form failed identically (8 labels delivered, 0
    images), which points away from "how we send" and toward "what we send".
    Texas de Brazil never handed Messages a raw artifact either — it rendered
    fresh RGB PNGs at 100 dpi and trimmed them. Our disposition shots are
    Playwright screenshots stitched by PIL: likely RGBA, and very tall.

    So this sends the SAME picture four ways — as captured, flattened to RGB,
    as JPEG, and downscaled — and reports each file's real mode/dimensions/bytes.
    Whichever labels arrive with a picture tells us the constraint. 1:1 only."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, "sendimage_fmt needs a phone number"
    phone = _normalize_us_phone(parts[0])
    if len(parts) > 1:
        src = Path(parts[1])
    else:
        from automations.b2b_dispositions import run as bd_run
        src = (bd_run.OUTPUT_DIR / dt.date.today().isoformat() / "hourly_at-t.png")
    if not src.exists():
        return False, f"no image at {src}"

    try:
        from PIL import Image
    except ImportError:
        return False, "Pillow not installed on this machine"

    im = Image.open(src)
    facts = "src mode=%s size=%dx%d bytes=%d" % (
        im.mode, im.size[0], im.size[1], src.stat().st_size)

    work = src.parent
    made = []   # (label, path)
    made.append(("c1 as-captured", src))

    rgb = im.convert("RGB")
    p2 = work / "fmt_rgb.png"
    rgb.save(p2)
    made.append(("c2 flattened RGB png", p2))

    p3 = work / "fmt.jpg"
    rgb.save(p3, "JPEG", quality=85)
    made.append(("c3 jpeg", p3))

    # Very tall images are the other suspect: a stitched rep-list + gap card can
    # run thousands of pixels down, and Messages is fussy about extreme ratios.
    small = rgb.copy()
    small.thumbnail((900, 1600))
    p4 = work / "fmt_small.jpg"
    small.save(p4, "JPEG", quality=85)
    made.append(("c4 jpeg <=900x1600", p4))

    out = []
    for label, path in made:
        p = str(path).replace("\\", "\\\\").replace('"', '\\"')
        info = ""
        try:
            with Image.open(path) as x:
                info = "%s %dx%d %dkb" % (x.mode, x.size[0], x.size[1],
                                          path.stat().st_size // 1024)
        except Exception:  # noqa: BLE001
            pass
        _osascript(
            'tell application "Messages"\n'
            '  set svcId to id of 1st service whose service type = iMessage\n'
            f'  send "FMT {label} — {info}" to buddy "{phone}" of service id svcId\n'
            'end tell', timeout=120)
        time.sleep(3)
        ok, res = _osascript(
            f'set f to (POSIX file "{p}") as alias\n'
            'tell application "Messages"\n'
            '  set svcId to id of 1st service whose service type = iMessage\n'
            f'  send f to buddy "{phone}" of service id svcId\n'
            'end tell', timeout=180)
        out.append("%s: %s" % (label.split()[0], "no error" if ok else "ERR"))
        time.sleep(12)
    return True, (facts + " · " + " · ".join(out)
                  + " · ASK which FMT label came WITH a picture")


def _action_sendimage_loc(args: str) -> tuple[bool, str]:
    """Is Messages simply unable to READ the file where we keep it?

    Args:  <phone> [image path]

    Addressing form didn't matter; image format didn't matter. The remaining
    difference between our sends and a human's is WHERE the file lives: ours sit
    under the repo's output/ tree, and Messages is a sandboxed app. A sandboxed
    app that can't read a path drops the attachment and reports nothing — which
    is exactly the symptom (text delivers, picture never appears, no error).

    Copies the same picture into progressively more 'normal' locations and sends
    each labelled. Whichever arrives tells us where captures have to be staged."""
    import shlex
    import shutil
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, "sendimage_loc needs a phone number"
    phone = _normalize_us_phone(parts[0])
    if len(parts) > 1:
        src = Path(parts[1])
    else:
        from automations.b2b_dispositions import run as bd_run
        src = (bd_run.OUTPUT_DIR / dt.date.today().isoformat() / "hourly_at-t.png")
    if not src.exists():
        return False, f"no image at {src}"

    home = Path.home()
    targets = [
        ("L1 repo output (current)", src),
        ("L2 home folder", home / "lucy_img_test.png"),
        ("L3 Pictures", home / "Pictures" / "lucy_img_test.png"),
        ("L4 Downloads", home / "Downloads" / "lucy_img_test.png"),
        ("L5 tmp", Path("/tmp") / "lucy_img_test.png"),
    ]
    out = []
    for label, path in targets:
        try:
            if path != src:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, path)
                try:
                    os.chmod(path, 0o644)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            out.append(f"{label.split()[0]}: copy failed {str(e)[:40]}")
            continue
        p = str(path).replace("\\", "\\\\").replace('"', '\\"')
        _osascript(
            'tell application "Messages"\n'
            '  set svcId to id of 1st service whose service type = iMessage\n'
            f'  send "LOC {label}" to buddy "{phone}" of service id svcId\n'
            'end tell', timeout=120)
        time.sleep(3)
        ok, res = _osascript(
            f'set f to (POSIX file "{p}") as alias\n'
            'tell application "Messages"\n'
            '  set svcId to id of 1st service whose service type = iMessage\n'
            f'  send f to buddy "{phone}" of service id svcId\n'
            'end tell', timeout=180)
        out.append("%s: %s" % (label.split()[0], "no error" if ok else "ERR " + res[:40]))
        time.sleep(12)
    return True, (" · ".join(out) + " · ASK which LOC label came WITH a picture")


def _action_fda_check(args: str) -> tuple[bool, str]:
    """READ-ONLY: does THIS process have Full Disk Access? Sends nothing.

    Text sends work and attachments silently vanish. The two need different
    things: scripting Messages needs Automation (granted 2026-08-03), but an
    attachment makes Messages copy the file into ~/Library/Messages/Attachments,
    which is TCC-protected. If the poller lacks Full Disk Access that copy fails
    and the picture is dropped with no error — matching every result so far
    (addressing form, image format and file location all ruled out).

    ~/Library/Messages/chat.db is the standard FDA probe: readable = granted."""
    import sqlite3
    db = Path.home() / "Library" / "Messages" / "chat.db"
    # The path a human must actually add. `.venv/bin/python` is a SYMLINK, and
    # macOS registers the resolved binary — adding the link can silently grant
    # nothing. It also lives in a dot-directory the file picker hides by default,
    # so hand over the real target instead.
    out = [f"interpreter: {sys.executable}",
           f"resolved: {os.path.realpath(sys.executable)}",
           f"chat.db exists: {db.exists()}"]
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
        con.execute("SELECT COUNT(*) FROM chat").fetchone()
        con.close()
        out.append("FULL DISK ACCESS: GRANTED for this process")
        out.append("=> FDA is NOT the reason attachments are being dropped")
    except Exception as e:  # noqa: BLE001
        out.append(f"FULL DISK ACCESS: DENIED ({type(e).__name__}: {str(e)[:80]})")
        out.append("=> LIKELY CAUSE. A human at Lucy 2: System Settings ▸ Privacy "
                   "& Security ▸ Full Disk Access ▸ + ▸ add the poller's python "
                   "(the same binary the LaunchAgent runs), then restart_poller.")
    return True, " · ".join(out)


def _action_stage_img_test(args: str) -> tuple[bool, str]:
    """Write a one-command image-send test for a HUMAN to run in Terminal.

    Args:  <phone> [image path]

    Terminal is already in Lucy 2's Full Disk Access list (switched off) and
    already holds the Automation grant from 2026-08-03. Flipping that one toggle
    gives a single process BOTH permissions — so running this script from
    Terminal isolates the question we can't answer from here: is Full Disk Access
    what's swallowing the attachment, or is AppleScript unable to send images on
    this macOS at all (which is what swag_welcome concluded)?

    Cheaper and far less error-prone than adding a symlinked binary out of a
    hidden .venv directory through the file picker. Writes the script only;
    sends nothing itself."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, "stage_img_test needs a phone number"
    phone = _normalize_us_phone(parts[0])
    if len(parts) > 1:
        img = Path(parts[1])
    else:
        from automations.b2b_dispositions import run as bd_run
        img = (bd_run.OUTPUT_DIR / dt.date.today().isoformat() / "hourly_at-t.png")
    if not img.exists():
        return False, f"no image at {img}"

    script = Path.home() / "img_test.applescript"
    script.write_text(
        '-- Sends one picture to %s from this machine\'s iMessage account.\n'
        '-- Run from Terminal AFTER switching Terminal on in Full Disk Access.\n'
        'set f to (POSIX file "%s") as alias\n'
        'tell application "Messages"\n'
        '  set svcId to id of 1st service whose service type = iMessage\n'
        '  send "TERMINAL TEST — picture should follow" to buddy "%s" of service id svcId\n'
        '  delay 2\n'
        '  send f to buddy "%s" of service id svcId\n'
        'end tell\n' % (phone, img, phone, phone), encoding="utf-8")
    return True, (f"staged {script} (image {img.name}) · AT LUCY 2: switch Terminal "
                  "ON in Full Disk Access, open Terminal, paste:  osascript "
                  f"~/img_test.applescript  · then check {phone} for the PICTURE")


def _action_shortcuts_probe(args: str) -> tuple[bool, str]:
    """READ-ONLY: what Shortcuts exist on this machine, and is the CLI usable?

    The Shortcuts route is the fallback for sending pictures, since AppleScript
    attachments never arrive here. swag_welcome drives a Shortcut named
    'Alphalete Swag Card' the same way. Before building anything on that, find
    out whether the `shortcuts` CLI works on Lucy 2 and whether that Shortcut
    (or any) is present — it was built on a different Mac, and a Shortcut can
    only be created by a human in the Shortcuts app.

    Sends nothing."""
    try:
        proc = subprocess.run(["shortcuts", "list"], capture_output=True,
                              text=True, timeout=30)
    except FileNotFoundError:
        return False, "no `shortcuts` CLI on this machine (needs macOS 12+)"
    except Exception as e:  # noqa: BLE001
        return False, f"shortcuts list failed: {str(e)[:120]}"
    if proc.returncode != 0:
        return False, ("shortcuts list exited %d: %s"
                       % (proc.returncode, (proc.stderr or "").strip()[:160]))
    names = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    swag = [n for n in names if "swag" in n.lower()]
    return True, ("%d shortcut(s): %s%s · swag card present: %s"
                  % (len(names), ", ".join(names[:12]),
                     " …" if len(names) > 12 else "",
                     swag[0] if swag else "NO — a human must build one in the "
                     "Shortcuts app on Lucy 2"))


def _action_reveal_python(args: str) -> tuple[bool, str]:
    """Open Finder on THIS machine with the poller's own interpreter selected.

    Granting Full Disk Access means dragging that exact binary into the list,
    and it lives in `.venv/bin/` — a dot-directory the file picker hides, which
    is precisely where the person at Lucy 2 got stuck (Cmd+Shift+G appeared to
    do nothing because the picker had not opened yet). `open -R` sidesteps all
    of it: Finder opens with the file highlighted and it can be dragged straight
    into System Settings.

    Reports the path too, so it can be pasted if the reveal is missed. Opens a
    window on the machine; sends nothing and changes nothing."""
    target = os.path.realpath(sys.executable)
    try:
        subprocess.run(["open", "-R", target], capture_output=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't reveal {target}: {str(e)[:120]}"
    return True, (f"Finder is now open on this machine with {Path(target).name} "
                  f"selected · full path: {target} · AT LUCY 2: drag that "
                  "highlighted file into System Settings ▸ Privacy & Security ▸ "
                  "Full Disk Access, switch it ON, and remove the earlier "
                  "python3.9 entry (wrong binary)")


def _action_text_dispositions(args: str) -> tuple[bool, str]:
    """Text one captured disposition posting to its campaign's iMessage group.

    Args:  <manifest filename> [YYYY-MM-DD]   e.g.
           text_dispositions text_manifest_hourly_3-00-pm.json

    THIS ACTION EXISTS FOR ONE REASON: permission. macOS grants "control
    Messages" per executable identity. THIS poller earned that grant on
    2026-08-03 when a human clicked Allow at Lucy 2. The scheduled
    b2b-dispositions job is a different identity (launchd runs it through
    /bin/bash on a wrapper) and has never been authorized — sending from there
    would pop a consent dialog on a machine nobody is sitting at, hang five
    minutes, and fail, every hour. So the capture job writes a manifest and
    queues this; the send happens here, inside the already-permitted process.

    The manifest names the groups by NAME; text_post re-resolves them at send
    time, so a membership change can't leave us texting a dead thread."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, ("text_dispositions needs a manifest filename (e.g. "
                       "text_manifest_hourly_3-00-pm.json)")
    name = parts[0]
    day = parts[1] if len(parts) > 1 else dt.date.today().isoformat()

    from automations.b2b_dispositions import run as bd_run
    from automations.b2b_dispositions import text_post as tp
    path = bd_run.OUTPUT_DIR / day / name
    if not path.exists():
        return False, f"no manifest {name!r} under {path.parent}"

    try:
        res = tp.send_manifest(path, dry_run=False)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:220]}"
    if res.get("skipped"):
        return True, f"already sent ({res['skipped']}) — not re-texting"
    sent = res.get("sent") or []
    lines = ["%s -> %s (%s imgs)" % (s.get("campaign"), s.get("group"),
                                     len(s.get("sent_images") or []))
             for s in sent]
    if res.get("errors"):
        return False, "FAILED: " + " · ".join(res["errors"])[:300]
    return True, ("texted %d group(s): " % len(sent)) + " · ".join(lines)


def _action_text_tracker(args: str) -> tuple[bool, str]:
    """Text one Tableau Country Tracker board to its iMessage group(s).

    Args:  <tracker id> [extra flags]   e.g.
           text_tracker b2b_att_country            -> LIVE send (default)
           text_tracker b2b_box --dry-run          -> capture + resolve, no text

    Same permission story as text_dispositions: macOS grants "control Messages"
    per executable identity, and only THIS poller earned the grant (2026-08-03).
    The mini queues this the moment the board posts to Slack; the poller runs
    tracker_texts.run as a SUBPROCESS, which inherits the grant and does both the
    Tableau capture and the send. Idempotent per (tracker, day) via a .sent marker
    inside tracker_texts, so the control queue's retries never double-text a group.

    Default is LIVE (--send) because the trigger only ever queues a real send; a
    dry-run for verification is opt-in by passing --dry-run in the args."""
    import shlex
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    if not parts:
        return False, ("text_tracker needs a tracker id (e.g. "
                       "text_tracker b2b_att_country)")
    tracker = parts[0]
    extra = parts[1:]
    # Default to a real send; an explicit --dry-run in the args overrides it.
    if not any(f in ("--send", "--dry-run") for f in extra):
        extra = extra + ["--send"]

    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome()
    except Exception:  # noqa: BLE001 — a guard must never crash the run
        pass

    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    ok, out = _run_cmd([sys.executable, "-m", "automations.tracker_texts.run",
                        "--tracker", tracker, *extra], timeout_s=15 * 60,
                       log_name=f"tracker-texts-{tracker}-{stamp}.log")
    lines = [ln for ln in (out or "").splitlines()
             if ("TEXT" in ln or "skipped" in ln or "ERROR" in ln
                 or "FAILED" in ln or ln.strip().startswith("image"))]
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


def _action_install_indeed_source_report(args: str) -> tuple[bool, str]:
    """Install the Source Report - Indeed refresh agent on THIS machine (Lucy 2).

    Rebuilds the CURRENT month of the "Source Report - Indeed" tab in the Alphalete
    Org Applicant Tracker from AppStream's Source Report, for all 28 offices, at
    4:00am / 12:00pm / 5:00pm. Idempotent — reinstalling re-locks the plist.
    `git pull` (update) must have landed the plist first."""
    from automations.day_orchestrator import install_agent
    try:
        ok, msg = install_agent.install("indeed-source-report")
    except Exception as e:  # noqa: BLE001 — report the reason, never a stack trace
        return False, f"{type(e).__name__}: {str(e)[:120]}"
    return ok, msg[:400]


def _action_install_day_orchestrator(args: str) -> tuple[bool, str]:
    """Install the 4am day-orchestrator LaunchAgent on THIS machine.

    Born 2026-08-22 for Lucy 3: reports get assigned to a machine via
    schedule_config's per-report "machine" field, but a machine can't run
    its share of the morning without the orchestrator agent — and until
    now installing it meant hands on the box. Idempotent — reinstalling
    re-locks the plist. `update` must have landed the plist first."""
    from automations.day_orchestrator import install_agent
    try:
        ok, msg = install_agent.install("day-orchestrator")
    except Exception as e:  # noqa: BLE001 — report the reason, never a stack trace
        return False, f"{type(e).__name__}: {str(e)[:120]}"
    return ok, msg[:400]


def _action_appstream_whoami(args: str) -> tuple[bool, str]:
    """Which AppStream account is THIS machine using, and which offices can it see?

      appstream_whoami                 as it runs today (reuses the saved session)
      appstream_whoami --force         ignore the saved session, log in fresh
      appstream_whoami --offices 1,2   probe specific office ids

    Read-only: it switches office and reads the page back, nothing is written.
    Exists because a stale .appstream_storage_state.json keeps a session minted by
    a DIFFERENT login working forever — so the configured username is never used
    and the machine silently sees fewer offices than it should."""
    cmd = [sys.executable, "-m", "automations.shared.appstream_whoami"] + (args or "").split()
    ok, res = _run_cmd(cmd, timeout_s=20 * 60,
                       log_name="appstream-whoami.log")
    return ok, res[:900]


def _action_funnel_board_unlock(args: str) -> tuple[bool, str]:
    """Clear a stale funnel_board run lock left by a killed run.

    run.py takes automations/funnel_board/state/run.lock and releases it via
    atexit — which never fires when the poller's timeout SIGKILLs a long
    backfill. The lock then blocks every later run for STALE_MIN (90) minutes,
    and those runs exit 0, so the report looks healthy while doing nothing.

    Reports the lock's age and removes it. Refuses if a funnel_board process is
    actually alive, so this can't be used to break a lock that is doing its job."""
    import shutil, time
    lock = REPO_ROOT / "automations" / "funnel_board" / "state" / "run.lock"
    if not lock.exists():
        return True, "no lock present — nothing to clear"
    alive = subprocess.run(["pgrep", "-f", "automations.funnel_board.run"],
                           capture_output=True, text=True).stdout.strip()
    age = (time.time() - lock.stat().st_mtime) / 60.0
    if alive:
        return False, ("lock is %.0f min old but funnel_board IS running (pid %s) "
                       "— refusing to break a live lock"
                       % (age, alive.replace("\n", ",")))
    shutil.rmtree(lock, ignore_errors=True)
    return not lock.exists(), "cleared a %.0f min old lock (no funnel_board running)" % age


def _action_set_appstream_alt_creds(args: str) -> tuple[bool, str]:
    """Install a SECOND AppStream login on THIS machine, beside the primary.

      set_appstream_alt_creds <username> <password>

    Why a second one rather than replacing: Lucy 2 runs as CarlosNLR, which
    cannot see six of the 28 offices, while rcaptain can. Other reports on that
    machine already depend on the primary account and its saved session, so the
    alternate is stored separately and jobs choose per run
    (funnel_board --account alt). The alternate also gets its OWN browser profile
    so its cookies never overwrite the primary's session.

    Writes to ~/.config/recruiting-report/appstream-alt.json (chmod 600) and
    verifies by actually logging in and reading the account back. NEVER echoes
    the password. In SECRET_ACTIONS, so the poller blanks the Args cell the
    moment the row ends."""
    import json as _json
    parts = (args or "").split()
    if len(parts) < 2:
        return False, "need: set_appstream_alt_creds <username> <password>"
    user, pw = parts[0], " ".join(parts[1:])
    path = Path.home() / ".config" / "recruiting-report" / "appstream-alt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"appstream_alt_username": user,
                                 "appstream_alt_password": pw}))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    # Prove it before declaring success — a stored credential that cannot log in
    # is worse than none, because it looks configured.
    ok, res = _run_cmd([sys.executable, "-m", "automations.shared.appstream_whoami",
                        "--user", user, "--pass", pw,
                        "--offices", "22583,19717,23607,22177,23411,21328"],
                       timeout_s=20 * 60, log_name="appstream-alt-verify.log")
    tail = res.split("·")[-1].strip()[:200]
    if not ok:
        return False, ("stored %s at %s but the login/office check FAILED: %s"
                       % (user, path.name, tail))
    return True, "stored %s and verified: %s" % (user, tail)


def _action_set_appstream_creds(args: str) -> tuple[bool, str]:
    """Install the PRIMARY AppStream login on THIS machine.

      set_appstream_creds <username> <password>

    WHY (Megan 2026-08-23): there was a set_appstream_alt_creds for the SECOND
    account but nothing for the first, so the only ways onto a new machine were
    hand-editing JSON or the macOS keychain — neither reachable on a never-touch
    runner. Lucy 3 took alphalete_org_focus on 8/22 and its very first step, the
    recruiting pull, died with `Missing AppStream credential 'appstream_username'`
    while the other five steps passed. shared.creds._resolve_as reads the creds
    FILE first, then the env var, then the keychain — so writing the file is the
    portable fix and the one a push_cred_file can later replicate.

    MERGES into the repo-root ownerville-creds.json and backs it up first: that
    file already holds the ownerville pair every Tableau report depends on, and
    replacing it wholesale would log the machine out of ownerville — which is the
    exact machine-wide outage this same day was spent fixing.

    Verifies by really logging in (appstream_whoami) — a stored credential that
    cannot authenticate is worse than none, because it looks configured. NEVER
    echoes the password. In SECRET_ACTIONS, so the poller blanks the Args cell the
    moment the row finishes (`lucy status` prints the whole Args column)."""
    import json as _json
    import shlex
    import shutil
    try:
        parts = shlex.split((args or "").strip())
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't read Args ({str(e)[:80]}) — quote the password"
    if len(parts) != 2:
        return False, ("set_appstream_creds needs exactly `<username> <password>` "
                       "(quote the password if it has spaces) — got "
                       f"{len(parts)} value(s)")
    user, pw = parts[0].strip(), parts[1]
    if not user or not pw:
        return False, "username and password must both be non-empty"
    path = REPO_ROOT / "ownerville-creds.json"
    data: dict = {}
    salvaged = ""
    if path.exists():
        try:
            data = _json.loads(path.read_text())
        except Exception as e:  # noqa: BLE001
            # UNPARSEABLE, not missing. Refusing outright strands the machine:
            # on 2026-08-23 Lucy 3's copy arrived shlex-quoted through the
            # push_cred_file -> Sheet -> set_cred_file round-trip, so every later
            # install bounced off a file that json.loads can't open. Nothing is
            # lost by starting clean — an unreadable creds file already resolves
            # to {} everywhere (shared.creds._file swallows the error) — but SAY
            # SO in the result, because any ownerville pair inside it is going
            # away and only the .bak still has it.
            salvaged = (f" NOTE: the existing {path.name} was UNREADABLE "
                        f"({str(e).splitlines()[0][:60]}); it was backed up and "
                        "replaced. Any ownerville keys it held are only in the "
                        ".bak now — re-push ownerville-creds if they're needed.")
            data = {}
        stamp = _now().replace(":", "").replace("-", "").replace("T", "-")
        try:
            shutil.copy2(path, path.parent / f"{path.name}.bak.{stamp}")
        except Exception:  # noqa: BLE001 — a failed backup shouldn't block the fix
            pass
    kept = sorted(k for k in data if not k.startswith("appstream_"))
    data["appstream_username"] = user
    data["appstream_password"] = pw
    try:
        path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't write {path.name}: {str(e).splitlines()[0][:120]}"
    ok, res = _run_cmd([sys.executable, "-m", "automations.shared.appstream_whoami",
                        "--user", user, "--pass", pw],
                       timeout_s=20 * 60, log_name="appstream-creds-verify.log")
    tail = res.split("·")[-1].strip()[:200]
    if not ok:
        return False, (f"stored {user} in {path.name} (kept: {', '.join(kept) or 'none'}) "
                       f"but the LOGIN CHECK FAILED: {tail}{salvaged}")
    return True, (f"AppStream creds installed for {user} + login verified "
                  f"(kept existing keys: {', '.join(kept) or 'none'}) · {tail}{salvaged}")


def _action_appstream_clear_session(args: str) -> tuple[bool, str]:
    """Delete this machine's saved AppStream session so the next run must log in.

    .appstream_storage_state.json is injected whenever it is still live, which is
    how a machine keeps operating as an account nobody configured: Lucy 2 reads
    configured=rcaptain and lands on account_no=6039 "Carlos Hidalgo" on every
    probe, including forced ones. Removing the file leaves nothing to fall back
    to, so the next login either authenticates with the stored credentials or
    fails loudly — which is the distinction we actually need.

    Safe: it is a cache. The next run rebuilds it. Refuses while an AppStream
    automation is running so it cannot yank the session out from under one."""
    alive = subprocess.run(["pgrep", "-f", "automations.funnel_board.run"],
                           capture_output=True, text=True).stdout.strip()
    if alive:
        return False, ("a funnel_board run is active (pid %s) — not clearing the "
                       "session under it" % alive.replace("\n", ","))
    from automations.shared.tableau_patchright import APPSTREAM_STORAGE_STATE
    if not APPSTREAM_STORAGE_STATE.exists():
        return True, "no saved session present — next run must log in already"
    size = APPSTREAM_STORAGE_STATE.stat().st_size
    APPSTREAM_STORAGE_STATE.unlink()
    return True, ("removed %s (%d bytes). The next run has to log in with the "
                  "stored credentials." % (APPSTREAM_STORAGE_STATE.name, size))


def _action_install_tracker_mirror(args: str) -> tuple[bool, str]:
    """Install the tracker-mirror agent on THIS machine (Lucy 2): ferries each
    manager's ad tracker values from the org tracker's authorized IMPORTRANGE
    staging tabs into Alphalete Recruiting Dashboard, every 2h through the workday.
    Idempotent; `update` must have landed the plist first."""
    from automations.day_orchestrator import install_agent
    try:
        ok, msg = install_agent.install("tracker-mirror")
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:120])
    return ok, msg[:400]


def _action_chrome_unstick(args: str) -> tuple[bool, str]:
    """Kill an AUTOMATION Chrome left holding a shared browser profile.

      chrome_unstick [profile-name] [--dry]
        profile-name  the profile dir's name, default '.browser_profile'
                      (tableau_patchright.PROFILE_DIR — what every Tableau
                      report on this machine launches on)
        --dry         list what would be killed and change nothing

    WHY THIS EXISTS (2026-08-14): when `lucy rerun` kills a browser report at
    its timeout, Playwright's Chrome can outlive the Python parent and keep the
    profile's ProcessSingleton. Every later run on that profile then dies with
    "Failed to create a ProcessSingleton for your profile directory", AFTER
    burning the full 30-minute profile-lock wait (_PROFILE_LOCK_WAIT_S) — which
    is exactly how box_order_log_abel failed twice that afternoon while Roshan's
    identical run had gone through an hour earlier.

    chrome_guard can't clean this up: it protects everything under
    `automations/uploaded` on purpose, so the orphan survives every guard pass
    and would have broken the 7:00 LaunchAgents the next morning too.

    Matched on the `--user-data-dir=` VALUE, by exact dir name, not a substring:
    '.browser_profile' must not also match the session holder's
    '.browser_profile_holder' (killing the holder logs every report out). Only
    the main browser process is signalled; helpers (`--type=`) die with it."""
    import shlex
    import signal as _signal
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    dry = "--dry" in parts
    named = [p for p in parts if not p.startswith("-")]
    target = named[0] if named else ".browser_profile"
    if sys.platform != "darwin":
        return False, f"chrome_unstick is macOS-only (this machine: {sys.platform})"
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,command="], capture_output=True,
                             text=True, timeout=15).stdout
    except Exception as e:  # noqa: BLE001
        return False, f"ps failed: {type(e).__name__}: {str(e)[:100]}"
    victims = []
    for line in out.splitlines():
        line = line.strip()
        if "Google Chrome.app/Contents/MacOS/Google Chrome" not in line:
            continue
        if "--type=" in line:
            continue                       # helper process, not the browser
        udd = ""
        for tok in line.split():
            if tok.startswith("--user-data-dir="):
                udd = tok.split("=", 1)[1]
                break
        if not udd or os.path.basename(udd.rstrip("/")) != target:
            continue
        try:
            victims.append(int(line.split(None, 1)[0]))
        except ValueError:
            continue
    if not victims:
        return True, f"no Chrome is holding {target!r} — nothing to unstick"
    if dry:
        return True, f"DRY: would kill PID(s) {victims} holding {target!r}"
    killed = []
    for pid in victims:
        try:
            os.kill(pid, _signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            pass
        except Exception as e:  # noqa: BLE001
            return False, f"kill {pid} failed: {type(e).__name__}: {str(e)[:80]}"
    time.sleep(5)
    still = []
    for pid in killed:
        try:
            os.kill(pid, 0)
            os.kill(pid, _signal.SIGKILL)
            still.append(pid)
        except OSError:
            pass
    return True, (f"unstuck {target!r}: closed PID(s) {killed}"
                  + (f" (SIGKILL needed for {still})" if still else ""))


def _action_daystate(args: str) -> tuple[bool, str]:
    """Read the orchestrator's OWN per-report record for a day. READ ONLY.

      daystate [YYYY-MM-DD] [filter]
        date    defaults to today
        filter  optional status substring (e.g. failed, incomplete, still) —
                omit for the full roll-up

    WHY THIS EXISTS (Megan 2026-08-19): "what actually ran today?" was
    unanswerable from a laptop all day. The Hub Activity sheet logs runs from
    ANY machine (so a laptop run looks like a mini run), and `logtail` only sees
    the orchestrator's console lines — reports that neither DONE nor failed
    simply do not appear. Both got read as evidence and both gave wrong answers.
    output/day_state/<date>.json is the orchestrator's own status per report,
    and logtail cannot reach it (it is path-locked to output/logs).

    NOTE the mini's day_state only knows what the MINI ran. Reports run by hand
    from Megan's laptop (2026-08-19: owner_showdown, daily_rep_breakdown, the
    d2d metrics) are absent here and are NOT failures.

    The Sheet result cell holds ~470 chars, so this returns COUNTS plus the
    reports that are not terminal-clean; the full dump is teed to
    output/logs/daystate-<date>.log for `lucy logtail daystate`."""
    import json as _json
    parts = (args or "").split()
    date = _now()[:10]
    filt = None
    for tok in parts:
        if len(tok) == 10 and tok[4] == "-" and tok[7] == "-":
            date = tok
        else:
            filt = tok.lower()
    if not all(c.isdigit() or c == "-" for c in date):
        return False, "daystate: date must be YYYY-MM-DD"
    path = (REPO_ROOT / "output" / "day_state" / f"{date}.json").resolve()
    root = (REPO_ROOT / "output" / "day_state").resolve()
    if root not in path.parents:
        return False, "daystate: refused (path escaped output/day_state)"
    if not path.exists():
        return False, f"no day_state for {date} (the orchestrator may not have run)"
    try:
        data = _json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return False, f"daystate: unreadable ({type(e).__name__}: {e})"
    reports = data.get("reports") or {}
    buckets: dict = {}
    detail = []
    for rid, rs in sorted(reports.items()):
        st = str((rs or {}).get("status", "?")).lower()
        buckets[st] = buckets.get(st, 0) + 1
        if filt and filt not in st:
            continue
        if filt or not st.startswith("done"):
            why = str((rs or {}).get("reason") or (rs or {}).get("waiting_on") or "")[:60]
            detail.append(f"{rid}: {st}{(' - ' + why) if why else ''}")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(buckets.items(), key=lambda kv: -kv[1]))
    full = (f"day_state {date} — {len(reports)} report(s)\n{counts}\n\n"
            + "\n".join(detail if detail else ["(all terminal-clean)"]))
    try:
        _log_dir = REPO_ROOT / "output" / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
        _write_log(_log_dir / f"daystate-{date}.log", ["daystate", date], full)
    except Exception:  # noqa: BLE001 — the tee is a convenience, never a failure
        pass
    head = f"{len(reports)} report(s) · {counts}"
    shown = "; ".join(detail[:6])
    more = f" (+{len(detail)-6} more — lucy logtail daystate-{date})" if len(detail) > 6 else ""
    return True, (head + ((" · " + shown + more) if detail else " · all terminal-clean"))


ACTIONS = {
    "ping": _action_ping,
    "messages_diag": _action_messages_diag,
    "find_group": _action_find_group,
    "sendtext": _action_sendtext,
    "run_b2b_dispositions": _action_run_b2b_dispositions,
    "text_dispositions": _action_text_dispositions,
    "text_tracker": _action_text_tracker,
    "sendimage_diag": _action_sendimage_diag,
    "sendimage_fmt": _action_sendimage_fmt,
    "sendimage_loc": _action_sendimage_loc,
    "fda_check": _action_fda_check,
    "stage_img_test": _action_stage_img_test,
    "shortcuts_probe": _action_shortcuts_probe,
    "reveal_python": _action_reveal_python,
    "install_b2b_dispositions": _action_install_b2b_dispositions,
    "focus_owner": _action_focus_owner,
    "screendrive": _action_screendrive,
    "logtail": _action_logtail,
    "daystate": _action_daystate,
    "probe_knocks": _action_probe_knocks,
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
    "git_recover": _action_git_recover,
    "set_meta_token": _action_set_meta_token,
    "set_doubleentry_creds": _action_set_doubleentry_creds,
    "set_appstream_creds": _action_set_appstream_creds,
    "set_appstream_state": _action_set_appstream_state,
    "set_appstream_alt_state": _action_set_appstream_alt_state,
    "appstream_promote_alt": _action_appstream_promote_alt,
    "set_payroll_webapp": _action_set_payroll_webapp,
    "set_slack_token": _action_set_slack_token,
    "set_slack_user_token": _action_set_slack_user_token,
    "push_slack_tokens": _action_push_slack_tokens,
    "push_cred_file": _action_push_cred_file,
    "set_cred_file": _action_set_cred_file,
    "set_office_slack_token": _action_set_office_slack_token,
    "set_dd_bot_token": _action_set_dd_bot_token,
    "set_dd_app_token": _action_set_dd_app_token,
    "set_gbp_token": _action_set_gbp_token,
    "set_gdocs_token": _action_set_gdocs_token,
    "set_gmail_token": _action_set_gmail_token,
    "set_credico_state": _action_set_credico_state,
    "set_contacts_token": _action_set_contacts_token,
    "set_contacts_ro_token": _action_set_contacts_ro_token,
    "restart_holder": _action_restart_holder,
    "restart_orchestrator": _action_restart_orchestrator,
    "restart_poller": _action_restart_poller,
    "restart_hub": _action_restart_hub,
    "install_hub_watch": _action_install_hub_watch,
    "install_lucy2_digest": _action_install_lucy2_digest,
    "install_card_scheduler": _action_install_card_scheduler,
    "install_jiraiya": _action_install_jiraiya,
    "set_raffi_app_password": _action_set_raffi_app_password,
    "set_alphalete_app_password": _action_set_alphalete_app_password,
    "post_note": _action_post_note,
    "incident_resolve": _action_incident_resolve,
    "incident_working": _action_incident_working,
    "incident_unmark": _action_incident_unmark,
    "install_enrollment_pending": _action_install_enrollment_pending,
    "git_push_setup": _action_git_push_setup,
    "git_push_check": _action_git_push_check,
    "install_tracker_auto_commit": _action_install_tracker_auto_commit,
    "appstream_whoami": _action_appstream_whoami,
    "funnel_board_unlock": _action_funnel_board_unlock,
    "appstream_clear_session": _action_appstream_clear_session,
    "set_appstream_alt_creds": _action_set_appstream_alt_creds,
    "install_indeed_source_report": _action_install_indeed_source_report,
    "install_tracker_mirror": _action_install_tracker_mirror,
    "install_day_orchestrator": _action_install_day_orchestrator,
    "install_bg_check_sync": _action_install_bg_check_sync,
    "install_bg_check_watchdog": _action_install_bg_check_watchdog,
    "run_bg_check_sync": _action_run_bg_check_sync,
    "post_nsf_correction": _action_post_nsf_correction,
    "reseed_appstream": _action_reseed_appstream,
    "sheets_login": _action_sheets_login,
    "set_sheets_cookies": _action_set_sheets_cookies,
    "watch_test": _action_watch_test,
    "diag": _action_diag,
    "nsf_screenshot_diag": _action_nsf_screenshot_diag,
    "nsf_fix_rollcall": _action_nsf_fix_rollcall,
    "nsf_status": _action_nsf_status,
    "chrome_sync_diag": _action_chrome_sync_diag,
    "chrome_unstick": _action_chrome_unstick,
    "sheets_whoami": _action_sheets_whoami,
    "slack_whoami": _action_slack_whoami,
    "slack_channel": _action_slack_channel,
    "slack_find": _action_slack_find,
    "clear_untracked": _action_clear_untracked,
    "set_sleep": _action_set_sleep,
    "reboot": _action_reboot,
}


# ---------------------------------------------------------------------------
# Enqueue + poll
# ---------------------------------------------------------------------------

def enqueue(action: str, args: str = "", by: str = "Eve", *, sandbox: bool = False,
            machine: str | None = None, auto: bool = False) -> None:
    """Add a fix request to the queue (called by Eve / Megan / the orchestrator).
    Targets `machine`'s tab (default 'Lucy 1' → the original 'Mini Control').

    `auto=True` stamps the By column `auto:<name>` — CODE queued this, not a
    person. A `rerun` row is the only place that changes behaviour today: a
    human's rerun marks the report's alert thread :pending: ("I'm on this"), and
    a watchdog's must not, because nobody is (see _action_rerun / is_manual).
    Any future automated enqueuer should pass it; forgetting it costs one wrong
    ⏳, which the daily sweep clears."""
    if auto and not str(by).startswith(AUTO_BY_PREFIX):
        by = "{}{}".format(AUTO_BY_PREFIX, by)
    # An EXPLICIT --machine target whose tab doesn't exist is a typo, not a new
    # machine: _open would silently create a tab no poller reads and the row
    # would sit "queued" forever (--machine lucy2 vs 'Lucy 2', 2026-08-20 —
    # looked exactly like a wedged poller). Machine names are matched loosely
    # (case/space/hyphen-insensitive) against the tabs that already exist, so
    # 'lucy2' still routes to 'Mini Control - Lucy 2'. A genuinely NEW machine
    # bootstraps its own tab the first time ITS poller runs — never from here.
    if machine is not None and not sandbox:
        sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
        prefix = "{} - ".format(CONTROL_TAB)
        tabs = {t.title for t in sh.worksheets()
                if t.title == CONTROL_TAB or t.title.startswith(prefix)}
        def _canon_m(s):
            return re.sub(r"[^a-z0-9]", "", s.lower())
        wanted = _control_tab_for(machine)
        cands = [t for t in tabs if _canon_m(t) == _canon_m(wanted)]
        if not cands:
            known = ", ".join(sorted(
                (t[len(prefix):] if t != CONTROL_TAB else DEFAULT_MACHINE)
                for t in tabs))
            print("[mini_control] UNKNOWN machine '{}' — nothing queued. "
                  "Known machines: {}".format(machine, known))
            return
        if len(cands) == 1:
            target = cands[0]
        else:
            # Twin tabs that differ only in case/spacing (an orphan from an old
            # typo next to the real one): route to the tab a poller has
            # DEMONSTRABLY read — it has processed rows; an orphan never does.
            proven = []
            for t in cands:
                try:
                    vals = sh.worksheet(t).get_all_values()
                    if any(len(r) > 4 and r[4] not in ("", "queued")
                           for r in vals[1:]):
                        proven.append(t)
                except Exception:  # noqa: BLE001
                    pass
            target = proven[0] if len(proven) == 1 else (
                wanted if wanted in tabs else cands[0])
        machine = DEFAULT_MACHINE if target == CONTROL_TAB \
            else target[len(prefix):]
    ws = _open(sandbox, machine)
    ws.append_row([_now(), action, args, by, "queued", "", ""],
                  value_input_option="RAW")
    # Don't echo a secret back at the person queueing it — their terminal
    # scrollback is one more place the password would sit.
    shown = "<redacted>" if action in SECRET_ACTIONS else args
    print(f"[mini_control] queued: {action} {shown} (by {by}) "
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
    bound repeated REPORT runs (rerun). READONLY_ACTIONS (logtail, git_status,
    git_diff, …) are excluded for the same reason and one more: they're how a
    failure gets diagnosed, so charging them means a bad morning spends the
    budget it needs (2026-08-13 — 55 of the day's 100 rows were reads)."""
    today = dt.date.today().isoformat()
    free = PLUMBING_ACTIONS | READONLY_ACTIONS
    return sum(
        1 for r in rows
        if str(r.get("Status", "")).strip().lower() in ("done", "failed", "running")
        and str(r.get("Queued At", "")).startswith(today)
        and str(r.get("Action", "")).strip().lower() not in free
    )


_ORPHAN_GRACE_MIN = 10


def _reclaim_orphans(ws, rows) -> int:
    """Close rows still marked 'running' that nothing is actually running.

    WHY (Megan 2026-08-19): three stale pills in one day —
    box_order_log_roshan (orphaned by a poller restart), fiber_activations
    (sat 'running' ~5h after it had finished writing both blocks) and the
    daily_rep_breakdown row. Each one cost real time chasing work that was
    already done, and the fiber pill nearly caused a DUPLICATE re-run.

    THE INVARIANT that makes this safe: poll_once is SYNCHRONOUS and
    single-threaded — it sets a row 'running', executes the action to
    completion, then writes the result. So at the TOP of a pass nothing this
    poller launched can still legitimately be 'running'; anything that is was
    left behind by a crash, a kill, a re-exec or a launchd restart.

    A _ORPHAN_GRACE_MIN cushion on the row's own 'started <ts>' stamp guards the
    one case the invariant does not cover: a second poller process briefly
    overlapping this one. Rows younger than that are left alone, so a live job is
    never stolen. Marked 'orphaned' (not 'failed') so it is obvious in the tab
    that the action's outcome is UNKNOWN — it may well have completed."""
    import re as _re
    now = dt.datetime.now()
    n = 0
    for i, row in enumerate(rows):
        if str(row.get("Status", "")).strip().lower() != "running":
            continue
        started = None
        m = _re.search(r"started\s+(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})",
                       str(row.get("Result", "")))
        if m:
            try:
                started = dt.datetime.fromisoformat(m.group(1).replace(" ", "T"))
            except Exception:  # noqa: BLE001
                started = None
        if started and (now - started).total_seconds() < _ORPHAN_GRACE_MIN * 60:
            continue                      # too fresh — could be a live overlap
        age = f", running {int((now - started).total_seconds() // 60)}m" if started else ""
        try:
            _set(ws, i + 2, "orphaned",
                 f"no poller was running this at {now:%H:%M} — left behind by a "
                 f"restart/kill{age}. The action may have COMPLETED; check its "
                 f"log or output before re-running.", finished=True)
            n += 1
        except Exception:  # noqa: BLE001 — reclaiming must never break the pass
            pass
    return n


def poll_once(*, dry_run: bool = False, sandbox: bool = False,
              machine: str | None = None) -> int:
    """One poll pass: run every 'queued' row's whitelisted action. Returns the
    number of rows acted on."""
    ws = _open(sandbox, machine)
    rows = ws.get_all_records()           # list of dicts keyed by header
    # Close anything left 'running' by a previous pass before doing new work, so
    # a stale pill never reads as live (see _reclaim_orphans).
    if not dry_run:
        _orphans = _reclaim_orphans(ws, rows)
        if _orphans:
            print(f"[mini_control] reclaimed {_orphans} orphaned 'running' row(s)",
                  flush=True)
            rows = ws.get_all_records()   # re-read: statuses just changed
    cap_used = _autoruns_today(rows)
    acted = 0
    for i, row in enumerate(rows):
        if str(row.get("Status", "")).strip().lower() != "queued":
            continue
        rownum = i + 2                    # +1 header row, +1 for 1-based
        action = str(row.get("Action", "")).strip()
        args = str(row.get("Args", "")).strip()
        handler = ACTIONS.get(action)

        # A restart is landing: leave this row for the process that will have
        # the new code, and stop the pass. Nothing is lost — the row keeps its
        # place in the queue (see _restart_hold_active).
        if not dry_run and _restart_hold_active():
            _set(ws, rownum, "queued",
                 f"held @ {_now()} — a poller restart is landing; this runs on "
                 f"the NEW code in a few seconds")
            print(f"[mini_control] holding {action} until the restart lands",
                  flush=True)
            break

        if handler is None:
            _set(ws, rownum, "failed",
                 f"unknown action {action!r}; allowed: {', '.join(ACTIONS)}", finished=True)
            acted += 1
            continue
        # The cap bounds runaway REPORT churn only. PLUMBING actions (update,
        # restart_poller, ping, …) must ALWAYS run — else a cap-hit freezes the
        # deploy/recovery channel itself (incl. the very command that clears it).
        # Never let a secret-carrying Args reach a log line or the Result cell.
        shown = "<redacted>" if action in SECRET_ACTIONS else args
        if (action.strip().lower() not in PLUMBING_ACTIONS
                and action.strip().lower() not in READONLY_ACTIONS
                and cap_used >= DAILY_AUTORUN_CAP):
            # SAY SO OUT LOUD. A capped row stays "queued" while plumbing keeps
            # succeeding, so the queue reads as alive and the skipped rerun looks
            # like it's merely waiting its turn — on 2026-08-13 that cost an hour
            # of watching a row that was never going to run.
            print(f"[mini_control] daily cap ({DAILY_AUTORUN_CAP}) reached — "
                  f"leaving {action} {shown} queued for a human")
            _set(ws, rownum, "queued",
                 f"daily cap {DAILY_AUTORUN_CAP} reached @ {_now()} — NOT run; "
                 f"waiting for a human or for the date to roll")
            continue
        if dry_run:
            print(f"[mini_control] DRY-RUN would run: {action} {shown}")
            _set(ws, rownum, "queued", f"[dry-run] would run {action} {shown} @ {_now()}")
            continue

        print(f"[mini_control] running: {action} {shown}")
        _set(ws, rownum, "running", f"started {_now()}")
        cap_used += 1
        # Park who queued this for the handler to read (see _CURRENT_BY). Always
        # cleared, so a handler can never inherit the previous row's author.
        global _CURRENT_BY
        _CURRENT_BY = str(row.get("By", "")).strip()
        try:
            ok, result = handler(args)
        except Exception as e:
            ok, result = False, f"handler error: {str(e).splitlines()[0][:160]}"
        finally:
            _CURRENT_BY = ""
        _set(ws, rownum, "done" if ok else "failed", result, finished=True)
        if action in SECRET_ACTIONS:
            # Blank the Args cell now that the secret has been consumed — pass or
            # fail, it must not stay in the Sheet. Best-effort: losing the redact
            # must not turn a successful install into a failed row, but say so.
            try:
                ws.update_cells([gspread.Cell(rownum, 3, "<redacted>")],
                                value_input_option="RAW")
            except Exception as e:  # noqa: BLE001
                print(f"[mini_control]   ⚠ could NOT redact row {rownum}'s Args "
                      f"({type(e).__name__}) — clear it by hand")
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
        # A secret-carrying row is redacted by the poller once it runs, but a
        # still-QUEUED one holds the live password — never print it here.
        if action in SECRET_ACTIONS:
            args = "<redacted>"
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
        '  lucy probe_knocks "<office>" [date] [campaign=<id|none>]\n'
        "                            READ-ONLY: what a knocks scrape returns for\n"
        "                            one office on one day (no Sheet, no Slack).\n"
        '                            Use "master" as the office for Raf (he cannot\n'
        "                            be impersonated). campaign=none skips the\n"
        "                            TeleMapper pin, to test whether the pin is\n"
        "                            what is blanking an office.\n"
        "  lucy update               git pull the latest code onto the mini\n"
        "  lucy git_status           branch, HEAD, and what's blocking a pull\n"
        "  lucy git_diff [path]      what this machine's uncommitted edits SAY\n"
        "  lucy git_stash            park uncommitted edits so update can run\n"
        "  lucy restart_holder       restart the session keep-alive\n"
        "  lucy diag                 machine health: sleep, agents, session, disk\n"
        "  lucy set_sleep 1|0        prevent (1) / allow (0) sleep (needs NOPASSWD pmset)\n"
        "  lucy reseed_appstream     open AppStream login (needs a human AT the mini)\n"
        "  lucy watch_test           send a test of the 6pm session-expiry Slack ping\n"
        '  lucy incident_resolve <key> ["note"]\n'
        "                            close an incident thread in #claudecorrections\n"
        "                            (the key is in its '_incident · … · open …_' line)\n"
        "  lucy incident_unmark <key>\n"
        "                            take the :pending: mark back OFF a post —\n"
        "                            nobody is on it (leaves the incident open)\n"
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
