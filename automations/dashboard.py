"""Operator dashboard for running report automations.

For Eve / Maud (operators): click a button, the report runs.
For Megan: add new automated reports to AUTOMATED_REPORTS once Claude builds them.

Run with:
    .venv/bin/streamlit run automations/dashboard.py
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote as _urlquote

import sys

# macOS 26 (Sequoia) + Python 3.14 regression: fork() in a multi-threaded
# Python process crashes in the child during pthread_atfork handlers
# (NEFlowDirectorDestroy / nw_settings_child_has_forked, then
# os_log_preferences_refresh SIGSEGVs). Pop-ups Megan saw 2026-05-22.
# Forcing subprocess to use posix_spawn() instead of fork()+exec() avoids
# the atfork path entirely. Set BEFORE any Popen so the module-level
# auto-detection doesn't fire first.
if sys.platform == "darwin":
    subprocess._USE_POSIX_SPAWN = True   # type: ignore[attr-defined]

# Windows: Python 3.13 defaults stdout/stderr to cp1252, which crashes
# on common log chars like '<-' (←) or any non-ASCII owner name.
# Eve hit this on the financial pull 2026-05-22 — the launcher .bat now
# sets PYTHONIOENCODING=utf-8 + PYTHONUTF8=1, but reconfigure here too
# so direct streamlit runs (no .bat) get the same protection.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

import streamlit as st

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from automations.recruiting_report import fill as _fill  # noqa: E402

# Python interpreter for spawning report subprocesses. sys.executable is the
# Python that's running this Streamlit process — on macOS it's .venv/bin/python,
# on Windows it's .venv\Scripts\python.exe. Same answer, no platform detection.
VENV_PY = sys.executable
LOG_DIR = WORKSPACE / "output" / "logs"
RUNS_LOG = LOG_DIR / "runs.jsonl"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{_fill.SPREADSHEET_ID}/edit"
# Daily Focus reports (Raf + Carlos captainships) live in their own shared
# sheet — one tab per captainship.
DAILY_FOCUS_SHEET_URL = "https://docs.google.com/spreadsheets/d/11FRYGG1hvuxcbWiYtDv7LzVss6ujZE_SOpqfhrQrVAo/edit"
# Carlos 1on1s - Focus Report (the B2B equivalent of Raf's weekly recruiting
# report). Shared module — set CAPTAINSHIP=Carlos when running.
CARLOS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1KLF8diMJ8pwIQWW9IqN7CL288t1l9VGUKxzBcMl8Of4/edit"
# Alphalete Org 1on1s - Focus Reports — third sheet, reps × campaign tabs
# (NDS / B2B / BOX / Retail / JE / Frontier). Shared module — set
# CAPTAINSHIP=Alphalete-Org when running.
ALPHALETE_ORG_SHEET_URL = "https://docs.google.com/spreadsheets/d/1C6BLttOSZhs_dREySac19XkxnMl-Ab_sYacNSl2l6AQ/edit"

UPLOADED_REPORTS_FILE = WORKSPACE / "uploaded_reports.json"
UPLOADED_SCRIPTS_DIR = WORKSPACE / "automations" / "uploaded"

# --- Shared report library (so ANY upload is instantly visible/runnable on
# EVERY Hub, with no Git push/pull). Uploaded automations are stored in a
# shared Google Sheet (same login every Hub already uses for the backlog).
# Each Hub reads it on load, writes the script to a local, git-ignored cache
# dir, and runs it from there — no collaborator access or `git push` needed.
SHARED_LIBRARY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SHARED_LIBRARY_TAB = "Report Library"
SHARED_LIBRARY_HEADERS = ["ID", "Name", "Module", "Created By", "Created At",
                          "Metadata", "Script"]
# Git-ignored — scripts are materialized here from the shared Sheet, so they
# never collide with tracked files or block the launcher's `git pull`.
SHARED_SCRIPTS_DIR = WORKSPACE / "automations" / "uploaded" / "_shared"
SHARED_SCRIPTS_PKG = "automations.uploaded._shared"
# Manual library assignments live here so anyone can claim an unassigned
# report from the Library view without editing source files. The file is a
# simple {report_id: [assignee_name, ...]} JSON dict; values override
# whatever assignees came from the source (uploaded_reports.json or the
# hardcoded AUTOMATED_REPORTS list).
LIBRARY_ASSIGNMENTS_FILE = WORKSPACE / "library_assignments.json"
# Uploaded report screenshots — one PNG per report id, shown on the
# report's Library page. Kept in resources/ so they sync to teammates.
REPORT_SHOTS_DIR = WORKSPACE / "resources" / "report-screenshots"
RUN_STATE_FILE = WORKSPACE / "output" / "run_state.json"
ACTIVE_RUNS_FILE = WORKSPACE / "output" / "active_runs.json"
ACTIVE_RUNS_LOG_DIR = WORKSPACE / "output" / "logs" / "active"
COMPLETED_MARKS_FILE = WORKSPACE / "output" / "completed_marks.json"
RUN_STATE_TTL_HOURS = 24


def _col_a1(n: int) -> str:
    """1-based column number → A1 column letters (1→A, 26→Z, 27→AA).
    Plain chr(ord('A')+n) breaks past column Z — this handles any width."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _pid_alive(pid: int) -> bool:
    """Cross-platform 'is this PID still running?' check.

    os.kill(pid, 0) is the POSIX liveness idiom and is correct on macOS/Linux,
    but on Windows os.kill routes signal 0 through TerminateProcess — it is NOT
    a safe existence probe there. So a finished run never migrated out of
    active_runs.json and the Hub showed it 'Running' forever; because
    _pid_alive is shared, EVERY report got stuck this way on Windows
    (Eve, 2026-06-11: daily-rep-breakdown, pid 11652, dead but still 'Running').

    Order: psutil if installed (cleanest, never touches the process) → a
    read-only Windows ctypes probe → the POSIX os.kill path. psutil is optional,
    not a hard dependency, so teammates without it still get a correct answer.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    try:
        import psutil  # optional — absent on most teammate machines
        return psutil.pid_exists(pid)
    except Exception:
        pass

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        # OpenProcess only opens; it never signals/terminates the target.
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False  # no such pid (or no rights) → treat as gone
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                # A pid can stay openable after exit; STILL_ACTIVE means live.
                return exit_code.value == STILL_ACTIVE
            return True  # couldn't read exit code — don't falsely orphan it
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _scan_running_subprocesses() -> list[dict]:
    """Scan the OS process list for python subprocesses matching any
    report's action module. This catches runs that bypassed active_runs.json
    — e.g. subprocess started in a terminal, or dashboard tab crashed before
    it could record the entry. Returns entries shaped like active_runs.json."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,user,command"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except Exception:
        return []
    # Build module → (report_id, report_name) from AUTOMATED_REPORTS, which is
    # defined later in this file but evaluated at call time.
    module_index: dict[str, tuple[str, str]] = {}
    try:
        for r in AUTOMATED_REPORTS:
            for action in r.get("actions", []):
                mod = action.get("module")
                if mod:
                    module_index[mod] = (r["id"], r["name"])
    except NameError:
        # Called before AUTOMATED_REPORTS is defined (shouldn't happen
        # in practice; defensive).
        return []
    found: list[dict] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[2]
        for mod, (rid, rname) in module_index.items():
            # Match either '-m mod' or the module path appearing in the cmd.
            if f"-m {mod}" in cmd or f"/{mod.replace('.', '/')}.py" in cmd:
                found.append({
                    "report_id": rid,
                    "report_name": rname,
                    "user": parts[1],
                    "pid": pid,
                    "log_path": str(ACTIVE_RUNS_LOG_DIR / f"{rid}.log"),
                    "started_at": "",
                    "orphan": True,  # Flag so the UI can note "detected via ps"
                })
                break
    return found


def _read_active_runs() -> list[dict]:
    """Return live runs. Orphans (subprocess finished but the streamlit
    handler never logged completion because the user navigated away) get
    migrated into runs.jsonl + run_state.json so the user can see them.

    Also merges in any python subprocesses found via ps that match a known
    report module but aren't in active_runs.json — catches dashboard-lost
    runs (e.g. tab crashed mid-run, started from terminal)."""
    active: list[dict] = []
    if ACTIVE_RUNS_FILE.exists():
        try:
            active = json.loads(ACTIVE_RUNS_FILE.read_text())
        except Exception:
            active = []
    alive = []
    orphans = []
    for a in active:
        pid = a.get("pid")
        if pid and _pid_alive(int(pid)):
            alive.append(a)
        else:
            orphans.append(a)

    for orphan in orphans:
        report_id = orphan.get("report_id")
        if not report_id:
            continue
        # Guess success/failure from the log tail
        log_path = orphan.get("log_path")
        status = "unknown"
        if log_path and Path(log_path).exists():
            try:
                full_low = Path(log_path).read_text(errors="replace").lower()
                tail_text = "\n".join(full_low.splitlines()[-10:])
                # Canonical end-markers FIRST, searched across the WHOLE log:
                # every report's run.py prints '=== done ===' on success, and
                # an uncaught crash prints a Python traceback. Scanning the
                # full text (not just the last 10 lines) fixes the
                # false-failure Eve hit 2026-05-31: churn/cancel reports
                # (Captainship Churn - Owners Metrics, Ongoing Cancel) dump
                # tables AFTER '=== done ===', pushing the sentinel out of the
                # 10-line tail so a benign word ('error', '✗', "couldn't
                # find") in the trailing data flipped the run to 'failed'.
                if "=== done ===" in full_low or "=== done (dry-run) ===" in full_low:
                    status = "success"
                elif ("traceback (most recent call last)" in full_low
                      or "timed out after" in full_low
                      or "— killed" in full_low
                      or "fill incomplete" in full_low
                      or "run incomplete" in full_low):
                    # A phase-watchdog kill (daily.py prints
                    # 'Phase N TIMED OUT after M min' and
                    # '... exceeded M min — killed') is a REAL failure: the run
                    # is incomplete. Catch it here, before the optimistic
                    # 'unknown -> success' default below — which was silently
                    # marking timed-out focus-office runs as 'completed'
                    # (Megan 2026-06-07). Likewise any report that ends
                    # '... INCOMPLETE ...' because a pull was skipped/failed —
                    # a report must NEVER read as completed when missing data
                    # (Megan 2026-06-08).
                    status = "failed"
                # Fuzzy tail heuristic — fallback only when neither explicit
                # sentinel is present (older reports, or a hard kill mid-run).
                #
                # Failure signatures include scraper-style markers ("✗",
                # "couldn't find", "couldn't be found", "auto-skipping") so a
                # run that stalled or auto-skipped reps still gets classified
                # as failed (the orphan path then auto-files a glitch row).
                #
                # Success markers checked FIRST so a summary line like
                # "Filled: 1; Errors: 0" wins before the failure scan sees
                # the substring "error" inside "Errors: 0" — Eve's 2026-05-26
                # Frontier OPT run was wrongly auto-filed as failed because
                # "errors: 0" tripped the "error" substring match.
                elif any(s in tail_text for s in (
                    "done", "[ok]", "errors: 0", "0 errors", "filled:",
                )):
                    status = "success"
                elif any(s in tail_text for s in (
                    "error", "failed", "traceback",
                    "✗", "couldn't find", "couldn't be found",
                    "auto-skipping", "timed out", "— killed",
                )):
                    status = "failed"
            except Exception:
                pass
        try:
            # Unverified runs default to FAILED, not success: an orphan with
            # no '=== done ===' sentinel and no recognizable success marker did
            # NOT verifiably complete, so it must not show as 'completed'
            # (Megan 2026-06-07 — timed-out runs were reading as done).
            _save_run_state_for(report_id, status if status != "unknown" else "failed",
                                user=orphan.get("user"))
            _log_run(
                report_id=report_id,
                report_name=orphan.get("report_name", "?"),
                user=orphan.get("user", "unknown"),
                status=status,
            )
            # Close out the shared Hub Activity row so other teammates'
            # dashboards stop showing this run as still going.
            if orphan.get("hub_run_id"):
                _hub_log_run_end(orphan["hub_run_id"],
                                 status if status != "unknown" else "success")
            # A failed run auto-files a glitch report so Megan gets the full
            # error log without anyone having to click anything.
            if status == "failed":
                _rep = next((r for r in AUTOMATED_REPORTS
                             if r.get("id") == report_id), {})
                _file_run_glitch(
                    report_id,
                    orphan.get("report_name", "?"),
                    _tail_log(log_path, lines=200) if log_path else "",
                    orphan.get("user", ""),
                    command=orphan.get("command", ""),
                    sheet_url=_rep.get("sheet_url", ""),
                )
        except Exception:
            pass

    if len(alive) != len(active):
        ACTIVE_RUNS_FILE.write_text(json.dumps(alive, indent=2))

    # Merge in ps-scanned subprocesses that aren't already tracked. This is
    # the safety net for runs the dashboard lost track of.
    tracked_pids = {int(a["pid"]) for a in alive if a.get("pid")}
    tracked_report_ids = {a.get("report_id") for a in alive}
    for found in _scan_running_subprocesses():
        if int(found["pid"]) in tracked_pids:
            continue
        if found.get("report_id") in tracked_report_ids:
            continue
        alive.append(found)
        tracked_report_ids.add(found.get("report_id"))

    # Merge in remote-active runs from the shared Hub Activity tab. Skip
    # any whose RunID we already have locally (those are our own — same
    # row, just observed from both sides).
    local_hub_ids = {a.get("hub_run_id") for a in alive if a.get("hub_run_id")}
    for remote in _hub_active_runs():
        if remote.get("hub_run_id") and remote["hub_run_id"] in local_hub_ids:
            continue
        if remote.get("report_id") in tracked_report_ids:
            continue
        alive.append(remote)
    return alive


def _record_active_run(report_id: str, report_name: str, user: str, log_path: Path,
                       pid: int, command: str = "") -> None:
    active = []
    if ACTIVE_RUNS_FILE.exists():
        try:
            active = json.loads(ACTIVE_RUNS_FILE.read_text())
        except Exception:
            active = []
    # Replace any existing entry for this report
    active = [a for a in active if a.get("report_id") != report_id]
    # Write a 'started' row to the shared Hub Activity tab so other teammates'
    # dashboards can see this run. The returned RunID is stored locally so
    # _clear_active_run can find the row to mark complete.
    hub_run_id = _hub_log_run_start(report_id, report_name, user, pid)
    active.append({
        "report_id": report_id,
        "report_name": report_name,
        "user": user,
        "log_path": str(log_path),
        "pid": pid,
        "command": command,  # exact command — surfaced in a glitch report
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "hub_run_id": hub_run_id,
    })
    ACTIVE_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_RUNS_FILE.write_text(json.dumps(active, indent=2))


def _manifest_retry(report: dict):
    """STANDARD failure-manifest retry context for a card, or None.

    Any report can opt into the Hub's 'Retry failed only' button just by writing
    a manifest (automations.shared.run_manifest) on each run — no per-card
    again_state_file / again_state_key / again_action config needed. The
    manifest carries the failed parts + the exact CLI args to re-run only those;
    we synthesize an again_action that runs the card's PRIMARY module with those
    args. Returns None when there's nothing to retry (so the button stays
    hidden), so the legacy again_state_file path still applies for cards that
    haven't been migrated. Best-effort — never raises into the UI."""
    try:
        from automations.shared import run_manifest as _rm
        spec = _rm.retry_spec(report.get("id", ""))
    except Exception:
        return None
    if not spec:
        return None
    actions = report.get("actions") or []
    primary = next((a for a in actions if a.get("primary")),
                   actions[0] if actions else None)
    if not primary or not primary.get("module"):
        return None
    retry_args = list(spec["retry_args"])
    return {
        "failed": list(spec["failed"]),
        "kind": spec.get("kind", "part"),
        "action": {
            "label": "Retry failed only",
            "module": primary["module"],
            "args_fn": (lambda ra=retry_args: list(ra)),
        },
    }


def _clear_active_run(report_id: str, status: str = "success") -> None:
    """Remove the local active-run entry AND mark the matching Hub Activity
    row finished. `status` should be 'success', 'failed', or 'stopped' so
    the shared tab reflects the actual outcome."""
    if not ACTIVE_RUNS_FILE.exists():
        return
    try:
        active = json.loads(ACTIVE_RUNS_FILE.read_text())
    except Exception:
        return
    # Look up the Hub RunID before removing the entry locally.
    hub_run_id = None
    for a in active:
        if a.get("report_id") == report_id:
            hub_run_id = a.get("hub_run_id")
            break
    active = [a for a in active if a.get("report_id") != report_id]
    ACTIVE_RUNS_FILE.write_text(json.dumps(active, indent=2))
    if hub_run_id:
        _hub_log_run_end(hub_run_id, status)


def _kill_active_run(report_id: str, user: str | None = None) -> tuple[bool, str]:
    """SIGTERM the running subprocess for `report_id`, then SIGKILL after a
    short grace period if it ignores TERM. Clears the active-runs entry and
    records the run as 'stopped' in run_state + runs.jsonl. Returns
    (True, message) on success, (False, message) if nothing was running."""
    import os, signal, time as _time
    if not ACTIVE_RUNS_FILE.exists():
        return False, "No active run for this report."
    try:
        active = json.loads(ACTIVE_RUNS_FILE.read_text())
    except Exception:
        return False, "Couldn't read active runs file."

    target = next((a for a in active if a.get("report_id") == report_id), None)
    if not target:
        return False, "No active run for this report."

    pid = target.get("pid")
    killed_pid = False
    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
            # Give the subprocess up to 3s to clean up after SIGTERM before
            # we escalate to SIGKILL — most Python scripts exit on SIGTERM
            # within a few hundred ms.
            for _ in range(30):
                if not _pid_alive(int(pid)):
                    break
                _time.sleep(0.1)
            if _pid_alive(int(pid)):
                # Windows signal has no SIGKILL; os.kill(SIGTERM) there already
                # routes through TerminateProcess (a hard kill), so SIGTERM is
                # the strongest escalation available. getattr keeps this from
                # raising AttributeError (uncaught below) on Windows.
                os.kill(int(pid), getattr(signal, "SIGKILL", signal.SIGTERM))
            killed_pid = True
        except (OSError, ValueError):
            pass

    _clear_active_run(report_id, status="stopped")
    _save_run_state_for(report_id, "stopped", user=user or target.get("user"))
    _log_run(
        report_id=report_id,
        report_name=target.get("report_name", "?"),
        user=user or target.get("user", "unknown"),
        status="stopped",
    )
    if killed_pid:
        return True, "Run stopped. Partial Sheet writes from this run stay — re-run for a fresh pass."
    return True, "Active-run entry cleared (subprocess had already exited)."


def _tail_log(log_path: str | Path, lines: int = 40) -> str:
    """Last `lines` lines of a log file. Empty string if missing/unreadable."""
    try:
        p = Path(log_path)
        if not p.exists():
            return ""
        return "\n".join(p.read_text(errors="replace").splitlines()[-lines:])
    except Exception:
        return ""


# Common run-failure signatures → plain-English diagnosis. Each entry is
# (substrings to look for, headline, what-to-do). First match wins; the
# match is case-insensitive against the failed run's log tail. Order
# matters — the specific causes are listed before the catch-alls.
# Each signature: needles (log substrings) → headline (WHY), fix (WHAT to do),
# optional link (Tableau/help URL), and message (a neutral, copy-paste note the
# user can send to whoever can fix it — shown with a Copy button). The link for
# a Tableau-specific failure is usually supplied by the REPORT's manifest
# remediation (it knows its exact source); these generic messages cover the rest.
_FAILURE_SIGNATURES: list[dict] = [
    {"needles": ("port 9222", "no ownerville tab", "debug chrome isn't running",
                 "no ownerville tab found", "chrome is open but no ownerville"),
     "pre_manifest": True,
     "headline": "Report Chrome isn't running, or the site got logged out.",
     "fix": "Launch Report Chrome from the sidebar, log into the report's "
            "website, then click Run Again.",
     "link": "",
     "message": "A report run failed because Report Chrome wasn't running (or "
                "the site had logged out), so it couldn't reach the report's "
                "website. Launching Report Chrome, signing in, and re-running "
                "should fix it."},
    {"needles": ("auto-relogin failed", "ownerville auto-relogin",
                 "ownerville login did not complete", "no rqst after a fresh login",
                 "_ensure_ownerville_logged_in", "still no rqst"),
     "pre_manifest": True,
     "headline": "The ownerville login failed (Cloudflare check or saved "
                 "credentials) — NOT a Tableau worksheet problem.",
     "fix": "Open ownerville once in the report's browser and clear the 'verify "
            "you're human' (Cloudflare) box so the session warms up, then re-run. "
            "Also confirm ownerville-creds.json has the right username/password. "
            "A scheduled/unattended run can't clear Cloudflare on its own — a "
            "person has to warm the login first.",
     "link": "",
     "message": "A report run failed at the ownerville login (every Tableau pull "
                "signs in through ownerville first). It couldn't get a valid "
                "session — usually a Cloudflare 'verify you're human' block on an "
                "unattended run, or wrong/missing saved credentials. Open "
                "ownerville in the report's browser, clear the Cloudflare check to "
                "warm the session, then re-run."},
    {"needles": ("invalid_grant", "refresherror", "token has been expired",
                 "token has been revoked", "invalid credentials"),
     "pre_manifest": True,
     "headline": "The Google sign-in for the Sheet expired.",
     "fix": "Re-authorize Google access (the OAuth login), then click Run "
            "Again. Ask Megan if you're not sure how.",
     "link": "",
     "message": "A report run failed because the Google sign-in for the Sheet "
                "expired. The OAuth token needs re-authorizing before the "
                "report can write to the Sheet again."},
    {"needles": ("429", "quota exceeded", "resource_exhausted", "rate limit"),
     "pre_manifest": True,
     "headline": "Google Sheets hit its per-minute limit.",
     "fix": "Wait about 2 minutes, then click Run Again — the run picks up "
            "where it stopped, so nothing already done is lost.",
     "link": "",
     "message": "A report run hit Google Sheets' per-minute write limit (429). "
                "Waiting ~2 minutes and re-running should clear it; the run "
                "resumes where it stopped."},
    {"needles": ("couldn't find the", "saw 0 thumb", "the view may have changed",
                 "sheet in the crosstab dialog", "custom view", "re-create the "
                 "custom view", "view not found"),
     "headline": "A Tableau worksheet the report needs is missing (the view may "
                 "have changed).",
     "fix": "Open the report's Tableau source and confirm the worksheet it "
            "pulls still exists and has data for this week. A renamed/removed "
            "section or team, a broken saved view, or data not loaded yet are "
            "the usual causes. Then re-run.",
     "link": "",
     "message": "A report run failed because a Tableau worksheet it needs is "
                "missing or empty — it couldn't find the expected sheet in the "
                "Crosstab dialog. This usually means the view changed, a "
                "section/team was renamed or removed, or that week's data isn't "
                "loaded yet. Please check the Tableau source has that worksheet "
                "with data for the current week, then re-run."},
    {"needles": ("phase 3 failed", "tableau pull (phase 3) failed",
                 "tableau download failed", "tableau (phase 3)"),
     "headline": "The Tableau step couldn't load.",
     "fix": "The scrape itself already finished — only the Tableau sale-type "
            "data is missing. Open the Tableau tab, sign in, then click Run "
            "Again.",
     "link": "",
     "message": "A report run failed at its Tableau step (the rest finished). "
                "Only the Tableau sale-type data is missing — opening the "
                "Tableau view, signing in, and re-running should complete it."},
    # Generic transient browser/Tableau timeout — LAST so the specific
    # crosstab ("couldn't find the … sheet") and phase-3 signatures above win
    # first. Without this, a raw patchright TimeoutError / TargetClosedError
    # fell through to None: no help message AND no dedup key, so the same flaky
    # load filed a fresh row every run (Fiber Activations, 2026-06-11/12).
    {"needles": ("timeouterror", "wait_for: timeout", "locator.click: timeout",
                 "wait_for_function: timeout", "wait_for_selector: timeout",
                 "timeout 30000ms", "timeout 120000ms", "targetclosederror",
                 "target page, context or browser has been closed"),
     "headline": "Tableau was slow or flaky and the step timed out.",
     "fix": "This is almost always a transient Tableau load — click Run Again. "
            "The Hub already auto-retries each pull a few times; if the SAME "
            "section keeps timing out across several runs, its saved/custom "
            "view may be corrupted — re-create it in Tableau.",
     "link": "",
     "message": "A report run timed out waiting on Tableau — usually a transient "
                "slow/half-rendered load. Re-running clears it most of the time. "
                "If one specific section keeps failing, its Tableau view may need "
                "to be re-created."},
]


_ERR_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Timeout)):\s*(.+)$")


def _extract_error_line(log_text: str) -> str | None:
    """Pull the most informative real error out of a run log — the LAST
    'SomeError: message' traceback line (the outermost raised exception). Used
    as a fallback so an UNRECOGNIZED failure still names its actual cause from
    the log, instead of falling back to a Tableau guess or no cause at all.
    Per Megan 2026-06-17: the Hub must say the real cause, not just 'Tableau'."""
    if not log_text:
        return None
    last = None
    for raw in log_text.splitlines():
        m = _ERR_LINE_RE.match(raw.strip())
        if m:
            last = f"{m.group(1)}: {m.group(2).strip()}"
    if last:
        return last[:300]
    # No exception line — fall back to the last 'failed'/'error' summary line.
    for raw in reversed(log_text.splitlines()):
        s = raw.strip()
        if s and ("failed" in s.lower() or s.lower().startswith("error")):
            return s[:300]
    return None


def _diagnose_run_failure(log_text: str) -> tuple[str, str] | None:
    """Translate a failed run's log into (headline, what-to-do).
    Returns None only when the log is empty — otherwise it always names a
    cause: a known signature if one matches, else the actual error pulled
    from the log (never a generic Tableau guess)."""
    low = (log_text or "").lower()
    for sig in _FAILURE_SIGNATURES:
        if any(n in low for n in sig["needles"]):
            return sig["headline"], sig["fix"]
    # No known signature — surface the REAL error from the log so the Hub
    # still reports an accurate cause (not a default Tableau flag).
    err = _extract_error_line(log_text)
    if err:
        return (f"The run hit an error: {err}",
                "Read the full traceback in the run log below, fix that specific "
                "error, then re-run. (If it looks like a transient Tableau/network "
                "blip, try Run Again first.)")
    return None


def _failure_remediation(report_id: str, log_text: str) -> dict | None:
    """Richer failure help: {reason, fix, link, message}, or None.

    Prefers the REPORT's own manifest remediation (it knows the exact Tableau
    link + a tailored message); falls back to the generic log-signature match.
    `link` is "" when unknown; `message` is neutral copy-paste text. Powers the
    Hub's failure callout (why → fix → link → message-to-send)."""
    low = (log_text or "").lower()

    def _sig_dict(sig: dict) -> dict:
        return {"reason": sig["headline"], "fix": sig["fix"],
                "link": sig.get("link", ""), "message": sig.get("message", "")}

    # 1) High-confidence infrastructure causes (login / OAuth / quota / Chrome)
    #    win over the report's manifest — they are NOT Tableau-data problems, so
    #    a Tableau-oriented manifest message would mislead.
    for sig in _FAILURE_SIGNATURES:
        if sig.get("pre_manifest") and any(n in low for n in sig["needles"]):
            return _sig_dict(sig)
    # 2) Report-provided manifest remediation (best for Tableau-data issues —
    #    it knows the exact view + link).
    try:
        from automations.shared import run_manifest as _rm
        rem = _rm.failure_remediation(report_id) if report_id else None
    except Exception:
        rem = None
    if rem:
        return {"reason": rem.get("reason", ""), "fix": rem.get("fix", ""),
                "link": rem.get("link", ""), "message": rem.get("message", "")}
    # 3) Remaining generic signatures (Tableau worksheet / timeout / etc.).
    for sig in _FAILURE_SIGNATURES:
        if any(n in low for n in sig["needles"]):
            return _sig_dict(sig)
    # 4) Last resort: surface the ACTUAL error from the log so the Hub still
    #    names a real cause instead of nothing (Megan 2026-06-17).
    err = _extract_error_line(log_text)
    if err:
        return {"reason": f"The run hit an error: {err}",
                "fix": "Read the full traceback in the run log, fix that error, "
                       "then re-run.",
                "link": "",
                "message": f"A report run failed with: {err}. See the full "
                           "log/traceback to fix it, then re-run."}
    return None


def _is_oauth_failure(diag: tuple[str, str] | None) -> bool:
    """True if the diagnosis is an expired/revoked Google OAuth token."""
    return bool(diag) and "google sign-in" in (diag[0] or "").lower()


def _reset_oauth_token() -> tuple[bool, str]:
    """Delete the local OAuth token file so the next run re-prompts Google
    sign-in. Returns (success, message). Safe to call when the file is
    already gone."""
    from pathlib import Path
    token_path = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
    if not token_path.exists():
        return True, ("Already cleared — token file isn't here. "
                      "Just click Run Again and you'll be prompted to sign in.")
    try:
        # Rename instead of delete so the prior token is recoverable from
        # disk if the new sign-in fails (same pattern the prior rotation
        # used on 2026-05-15: .dead-<timestamp>).
        import datetime as _dt
        ts = _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        backup = token_path.with_suffix(f".json.dead-{ts}")
        token_path.rename(backup)
        return True, ("Google sign-in cleared. Click Run Again — a Google "
                      "sign-in tab will open in your browser. Sign in, "
                      "grant access, and you're back.")
    except Exception as e:
        return False, (f"Couldn't clear the token file ({type(e).__name__}: "
                       f"{e}). You can delete it manually: in Finder press "
                       f"Cmd+Shift+G, paste `~/.config/recruiting-report`, "
                       f"then trash `oauth-token.json`.")


def _estimated_minutes_for(report_id: str) -> int | None:
    """A report's declared estimated_minutes, if any — powers the
    time-based progress bar for reports without per-step log markers."""
    try:
        for r in AUTOMATED_REPORTS:
            if r.get("id") == report_id:
                return r.get("schedule", {}).get("estimated_minutes")
    except Exception:
        pass
    return None


# Reports that track owner-access gaps. When a report whose uploaded
# script contains `script_marker` is sent for review, the Hub reads these
# result files and appends the gaps to the review email — so the reviewer
# knows exactly which owners still need access granted. Add an entry here
# as new access-gated reports come online.
_ACCESS_GAP_SOURCES = [
    {
        "script_marker": "focus_office_att",
        "ov_results": "output/focus_office_scrape_results.json",
        "tableau_results": "output/focus_office_tableau_results.json",
        "checkpoint_file": "output/focus_office_run_checkpoint.json",
    },
]


def _access_gaps_for_script(script_text: str) -> str:
    """If the uploaded report tracks access gaps, return a plain-text block
    naming owner tabs we can't fully scrape because we lack access (no
    ownerville access, or the owner isn't in the Tableau export). Returns
    '' when there are no gaps, or the report doesn't track them."""
    for src in _ACCESS_GAP_SOURCES:
        if src["script_marker"] not in (script_text or ""):
            continue
        ov_missing: list[str] = []
        tab_missing: list[str] = []
        try:
            p = WORKSPACE / src["ov_results"]
            if p.exists():
                results = json.loads(p.read_text()).get("results", {})
                ov_missing = sorted(o for o, s in results.items() if s != "ok")
        except Exception:
            pass
        try:
            p = WORKSPACE / src["tableau_results"]
            if p.exists():
                tab_missing = sorted(
                    json.loads(p.read_text()).get("missing_from_tableau", [])
                )
        except Exception:
            pass
        lines = []
        if ov_missing:
            lines.append(f"• ownerville: {', '.join(ov_missing)}")
        if tab_missing:
            lines.append(f"• Tableau: {', '.join(tab_missing)}")
        if not lines:
            return ""
        return ("⚠️ Owner tabs we can't fully scrape yet — no access. Please "
                "re-ping to get access granted:\n" + "\n".join(lines))
    return ""


def _resume_checkpoint_for(report: dict) -> "Path | None":
    """The resume-checkpoint file for a report, if it tracks one. Uses an
    explicit post_run.resume_checkpoint config when present; otherwise
    matches the report's uploaded script against the known access-gap
    sources — so the resume-aware Run Again button works with zero config."""
    rel = (report.get("post_run") or {}).get("resume_checkpoint")
    if rel:
        return WORKSPACE / rel
    try:
        script_path = UPLOADED_SCRIPTS_DIR / f"{report.get('id', '')}.py"
        if script_path.exists():
            txt = script_path.read_text(errors="replace")
            for src in _ACCESS_GAP_SOURCES:
                if src.get("checkpoint_file") and src["script_marker"] in txt:
                    return WORKSPACE / src["checkpoint_file"]
    except Exception:
        pass
    return None


def _load_all_run_state() -> dict:
    """Read persisted run state, dropping entries older than TTL."""
    if not RUN_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(RUN_STATE_FILE.read_text())
    except Exception:
        return {}
    cutoff = dt.datetime.now() - dt.timedelta(hours=RUN_STATE_TTL_HOURS)
    fresh = {}
    for k, v in data.items():
        try:
            ts = dt.datetime.fromisoformat(v.get("ts", ""))
            if ts >= cutoff:
                fresh[k] = v
        except Exception:
            continue
    return fresh


def _save_run_state_for(report_id: str, status: str, user: str | None = None) -> None:
    state = _load_all_run_state()
    entry = {"status": status, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    if user:
        entry["user"] = user
    state[report_id] = entry
    RUN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATE_FILE.write_text(json.dumps(state, indent=2))


def _clear_run_state_for(report_id: str) -> None:
    state = _load_all_run_state()
    state.pop(report_id, None)
    RUN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATE_FILE.write_text(json.dumps(state, indent=2))


# --- Per-report results (currently only recruiting writes this) ---
RECRUITING_RESULTS_FILE = WORKSPACE / "output" / "recruiting_results.json"


def _load_recruiting_results() -> dict:
    """Returns {week, filled[], still_missing[], inaccessible_in_last_run[], updated_at}."""
    if not RECRUITING_RESULTS_FILE.exists():
        return {}
    try:
        return json.loads(RECRUITING_RESULTS_FILE.read_text())
    except Exception:
        return {}


# --- Completion marks (user ticks off a finished run on their profile) ---


def _load_completed_marks() -> dict:
    """Structure: {user: {YYYY-MM-DD: [{report_id, report_name, run_ts, marked_at}, ...]}}."""
    if not COMPLETED_MARKS_FILE.exists():
        return {}
    try:
        return json.loads(COMPLETED_MARKS_FILE.read_text())
    except Exception:
        return {}


def _save_completed_marks(data: dict) -> None:
    COMPLETED_MARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMPLETED_MARKS_FILE.write_text(json.dumps(data, indent=2))


def _mark_run_completed(user: str, report_id: str, report_name: str, run_ts: str) -> None:
    data = _load_completed_marks()
    today = dt.date.today().isoformat()
    user_data = data.setdefault(user, {})
    day_list = user_data.setdefault(today, [])
    for item in day_list:
        if item.get("report_id") == report_id and item.get("run_ts") == run_ts:
            return
    day_list.append({
        "report_id": report_id,
        "report_name": report_name,
        "run_ts": run_ts,
        "marked_at": dt.datetime.now().isoformat(timespec="seconds"),
    })
    _save_completed_marks(data)


def _unmark_run_completed(user: str, report_id: str, run_ts: str) -> None:
    data = _load_completed_marks()
    today = dt.date.today().isoformat()
    user_data = data.get(user, {})
    day_list = user_data.get(today, [])
    user_data[today] = [
        item for item in day_list
        if not (item.get("report_id") == report_id and item.get("run_ts") == run_ts)
    ]
    _save_completed_marks(data)


def _get_completed_today(user: str) -> list[dict]:
    data = _load_completed_marks()
    today = dt.date.today().isoformat()
    items = data.get(user, {}).get(today, [])
    items.sort(key=lambda x: x.get("marked_at", ""), reverse=True)
    return items


def _shared_library_ws():
    """The shared 'Report Library' worksheet, created with headers if missing.
    Lives in the same Sheet the backlog uses, so every Hub can read/write it
    with the shared login — no Git, no per-user access setup."""
    import gspread as _gs
    sh = _fill.open_by_key(SHARED_LIBRARY_SHEET_ID)
    try:
        return sh.worksheet(SHARED_LIBRARY_TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHARED_LIBRARY_TAB, rows=200,
                              cols=len(SHARED_LIBRARY_HEADERS))
        ws.update([SHARED_LIBRARY_HEADERS], "A1:G1")
        return ws


def _materialize_shared_script(safe_id: str, script_text: str) -> str:
    """Write a shared-library script to the local git-ignored cache dir so it
    can be run via `python -m automations.uploaded._shared.<id>`. Only rewrites
    when the content changed. Returns the dotted module path."""
    SHARED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    init_f = SHARED_SCRIPTS_DIR / "__init__.py"
    if not init_f.exists():
        init_f.write_text("")
    p = SHARED_SCRIPTS_DIR / f"{safe_id}.py"
    if (not p.exists()) or p.read_text() != script_text:
        p.write_text(script_text)
    return f"{SHARED_SCRIPTS_PKG}.{safe_id}"


@st.cache_data(ttl=60, show_spinner=False)
def _read_shared_library_rows() -> list[dict]:
    """Read uploaded automations from the shared Sheet + materialize each
    script locally. Returns PLAIN, picklable metadata dicts (no `actions`
    callables) — st.cache_data can't serialize lambdas, so the action/args_fn
    are added later in _read_shared_library (uncached). Cached 60s so reruns
    don't hammer the API. Fails open (returns []) if the Sheet is unreachable."""
    try:
        rows = _shared_library_ws().get_all_records()
    except Exception:
        return []
    out: list[dict] = []
    for r in rows:
        meta_json = str(r.get("Metadata") or "").strip()
        script = str(r.get("Script") or "")
        if not meta_json or not script:
            continue
        try:
            meta = json.loads(meta_json)
        except Exception:
            continue
        safe_id = meta.get("id") or str(r.get("ID") or "").strip()
        if not safe_id:
            continue
        try:
            module = _materialize_shared_script(safe_id, script)
        except Exception:
            continue
        meta["id"] = safe_id
        meta["module"] = module
        meta.setdefault("creator", str(r.get("Created By") or ""))
        out.append(meta)
    return out


def _read_shared_library() -> list[dict]:
    """AUTOMATED_REPORTS-compatible dicts for the shared library. Wraps the
    cached row read and layers on the synthetic `actions` (with args_fn
    lambdas) — kept OUT of the cached function because st.cache_data can't
    pickle lambdas (that error was silently yielding an empty library)."""
    out: list[dict] = []
    try:
        rows = _read_shared_library_rows()
    except Exception:
        return []
    for meta in rows:
        report = dict(meta)
        module = report.get("module")
        if not module:
            continue
        args_list = report.get("args", [])
        report["actions"] = [{
            "label": report.get("action_label", "Run Report"),
            "icon": "▶", "primary": True, "module": module,
            "args_fn": (lambda a=args_list: list(a)),
        }]
        report.setdefault("emoji", "⭐")
        report.setdefault("color", "#667eea")
        report.setdefault("description", "")
        report.setdefault("sheet_url", "")
        report.setdefault("assignees", [])
        report.setdefault("checklist", [])
        out.append(report)
    return out


def _shared_library_upsert(metadata: dict, script_text: str) -> tuple[bool, str]:
    """Write/replace an uploaded automation in the shared Sheet (keyed by ID),
    so it's instantly visible + runnable on every Hub. Returns (ok, message)."""
    safe_id = metadata.get("id", "")
    if not safe_id:
        return False, "missing report id"
    row = [safe_id, metadata.get("name", ""), metadata.get("module", ""),
           metadata.get("creator", "") or (st.session_state.get("user") or ""),
           dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
           json.dumps(metadata), script_text]
    try:
        ws = _shared_library_ws()
        try:
            cell = ws.find(safe_id, in_column=1)
        except Exception:
            cell = None
        if cell:
            ws.update([row], f"A{cell.row}:G{cell.row}")
        else:
            ws.append_row(row, value_input_option="RAW")
        _read_shared_library.clear()
        return True, "published to the shared library (live for everyone)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _load_uploaded_reports_raw() -> list[dict]:
    """Read uploaded_reports.json and convert to AUTOMATED_REPORTS-compatible dicts.
    Called once at module load so the list of all reports is fresh on each rerun.

    Pass-through approach: copy every field from the JSON entry, then
    layer the synthetic Hub-UI fields (`actions`) on top. Previously this
    function hand-listed each field, which silently dropped `breakdown`,
    `category`, `needs_login`, `followup_notes`, and any future field a
    wire-up form added - the breakdown text was in the file but never
    reached the 'How <report> works' panel. Megan 2026-05-22.
    """
    if not UPLOADED_REPORTS_FILE.exists():
        return []
    try:
        raw = json.loads(UPLOADED_REPORTS_FILE.read_text())
    except Exception:
        return []
    out = []
    for r in raw:
        module = r.get("module")
        if not module:
            continue
        args_list = r.get("args", [])
        report = dict(r)
        # Synthesize the actions entry the Hub UI expects (the JSON
        # stores `module` + `args` flat; the UI takes a list of action
        # dicts with `args_fn` callables).
        report["actions"] = [{
            "label": r.get("action_label", "Run Report"),
            "icon": "▶",
            "primary": True,
            "module": module,
            "args_fn": (lambda a=args_list: list(a)),
        }]
        # Defaults for UI-required fields when the JSON didn't set them.
        report.setdefault("creator", "")
        report.setdefault("emoji", "⭐")
        report.setdefault("color", "#667eea")
        report.setdefault("description", "")
        report.setdefault("sheet_url", "")
        report.setdefault("assignees", [])
        report.setdefault("checklist", [])
        out.append(report)
    return out

# Team members. Each is a dict so we can add avatars/colors easily.
# Order: alphabetical by name.
MEMBERS = [
    # `email` powers the "Ask for an update" button on claimed backlog cards.
    # Fill these in (or correct any guesses) — when blank, the button opens
    # an empty mailto and the requester types the address manually.
    {"name": "Eve",     "emoji": "🌷",        "color": "#4ECDC4", "email": "alphaletereporting@gmail.com"},
    # Not people — buckets for reports that run on a schedule with NO human
    # trigger (fully unattended via patchright auto-login). No email.
    # Lucy 1 = the main mini; Lucy 2 = Carlos's machine (his org's reports).
    {"name": "Lucy 1", "emoji": "🤖", "color": "#10B981", "email": ""},
    {"name": "Lucy 2", "emoji": "🦾", "color": "#E76F51", "email": ""},
    {"name": "Maud",    "emoji": "🌟",        "color": "#FF6B6B", "email": "maudmiller4@gmail.com"},
]


def _gmail_compose_url(to: str = "", subject: str = "", body: str = "", cc: str = "") -> str:
    """Build a Gmail compose URL that drafts an email in the browser.

    Opens Gmail (not the OS default mail client) so the user doesn't have
    to swap between Gmail and Mail.app. Any empty parameter is omitted
    cleanly from the URL — Gmail just leaves that field blank in compose.
    """
    parts = ["https://mail.google.com/mail/?view=cm&fs=1&tf=cm"]
    if to:
        parts.append(f"to={_urlquote(to)}")
    if cc:
        parts.append(f"cc={_urlquote(cc)}")
    if subject:
        parts.append(f"su={_urlquote(subject)}")
    if body:
        parts.append(f"body={_urlquote(body)}")
    return parts[0] + ("&" + "&".join(parts[1:]) if len(parts) > 1 else "")


def _member_email(name: str) -> str:
    """Return the email for a member name (case-insensitive). Empty if unknown."""
    if not name:
        return ""
    target = name.strip().lower()
    for m in MEMBERS:
        if m["name"].lower() == target:
            return (m.get("email") or "").strip()
    return ""

# --------------------------------------------------------------------------
# Configuration — Megan edits this section as new automations come online
# --------------------------------------------------------------------------

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _last_completed_we_sunday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


# DEPRECATED (2026-06-29): recruiting_report.run's --week now means the Sheet WE
# Sunday (it reads AppStream from week-7 internally), so callers pass
# _last_completed_we_sunday() directly. This WE-minus-7 helper is the OLD
# AS-picker convention and is no longer wired anywhere — do NOT use it for a
# --week arg or you'll fill the column one week too early.
def _last_completed_as_picker(today: dt.date | None = None) -> dt.date:
    return _last_completed_we_sunday(today) - dt.timedelta(days=7)


AUTOMATED_REPORTS = [
    {
        "id": "recruiting",
        "name": "ATT Program - Focus Report (Raf)",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#FF6B6B",
        "category": "🎯 Recruiting",
        "description": "Pulls funnel metrics from ApplicantStream, fills the mass-report Sheet across ~52 ICD office tabs.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Provides a **week-over-week** overview of the recruiting "
            "numbers for selected ICDs.\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the most recently finished week.\n\n"
            "TO ADD AN ICD\n"
            "**1.**  Add a tab and label it the ICD's name — it must match "
            "the **AppStream name** exactly.\n"
            "**2.**  Make sure the **rcaptain** AppStream login has access "
            "to that ICD.\n"
            "✅  Claude auto-adds the template and fills in that ICD's data "
            "on the next run.\n\n"
            "IF AN ICD IS SKIPPED\n"
            "It most likely isn't in AppStream — check that the **rcaptain** "
            "login can see it."
        ),
        "sheet_url": SHEET_URL,
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "8:00 AM",
            "estimated_minutes": 15,
        },
        # Fully unattended via patchright (rcaptain AppStream + ownerville
        # Tableau) — no pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Recruiting report run complete — the rcaptain login reaches every ICD, so it's all done in one run.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda: ["--week", _last_completed_we_sunday().isoformat()],
            },
            {
                "label": "Backfill Last 10 Weeks (one office)",
                "icon": "🔁",
                "needs_text": True,
                "text_label": "Office tab name (exact match)",
                "help": "Fill any empty cells in the last 10 weeks for ONE office. Won't overwrite existing data.",
                "module": "automations.recruiting_report.backfill_blanks",
                "args_fn": lambda name: ["--weeks", "10", "--only", name],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat()],
            },
            {
                "label": "Run for One Office (pick a week)",
                "icon": "🎯",
                "needs_date": True,
                "needs_text": True,
                "text_label": "Office tab name (exact match)",
                "help": "Just refill ONE office's tab for any week. Pick the WE Sunday + type the office tab name.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d, name: ["--week", (d - dt.timedelta(days=7)).isoformat(), "--only", name],
            },
        ],
    },
    {
        "id": "recruiting-carlos",
        "name": "Carlos 1on1s - Focus Report",
        "creator": "Megan",
        "emoji": "📊",
        "color": "#A78BFA",
        "category": "🎯 Recruiting",
        "description": "Pulls B2B funnel + OPT metrics from ApplicantStream + Tableau, fills Carlos's 32-ICD focus-report Sheet.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Recruiting pull (APPS / Total Applies / Retention / "
            "1st & 2nd Booked / etc.) from AppStream\n"
            "**•** OPT metrics (Active Headcount, Sales by product, "
            "AVG Apps, Scorecard Ranking, etc.) from Tableau\n"
            "**•** Cancel Rate, Activation %, Churn buckets, Penetration "
            "Rate, Direct Deposit, Personal Production from Tableau\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the just-ended week's column "
            "(WE Sunday).\n\n"
            "TO ADD AN ICD\n"
            "**1.**  Add a tab named the ICD's exact AppStream name.\n"
            "**2.**  Make sure the **CarlosNLR** AppStream login (Lucy 2) can "
            "see that ICD.\n"
            "✅  Next run auto-fills the new tab.\n\n"
            "IF DATA IS MISSING\n"
            "Cells marked **'No Data In Tableau'** mean the ICD is too "
            "new for that time window (e.g. 60/90/120-day churn). Cells "
            "marked **'No Access'** mean the Tableau session doesn't have "
            "permission to that ICD's data."
        ),
        "sheet_url": CARLOS_SHEET_URL,
        "assignees": ["Lucy 2"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "8:00 AM",
            "estimated_minutes": 15,
        },
        # Fully unattended via patchright (rcaptain AppStream + ownerville
        # Tableau) — no pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Carlos report run complete — Recruiting pull + 6 Tableau OPT views + Personal Production all filled across 32 ICD tabs.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        # CAPTAINSHIP=Carlos switches the shared recruiting_report module
        # to Carlos's sheet/master tab/template/mapping file at import time.
        "env": {"CAPTAINSHIP": "Carlos"},
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "ONE run: recruiting pull + all 7 Carlos B2B OPT views.",
                # Chains recruiting (--no-opt) + each opt_phase_carlos B2B view
                # as its own subprocess (carlos_opt_all), so one bad view can't
                # abort the rest. The shared ATT opt_phase is NOT used — Carlos's
                # B2B owners aren't in those views (glitch 2026-06-01).
                "module": "automations.recruiting_report.carlos_opt_all",
                "args_fn": lambda: ["--week", _last_completed_we_sunday().isoformat()],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat(), "--no-opt"],
            },
            {
                "label": "Run for One ICD (pick a week)",
                "icon": "🎯",
                "needs_date": True,
                "needs_text": True,
                "text_label": "ICD tab name (exact match)",
                "help": "Just refill ONE ICD's tab for any week.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d, name: ["--week", (d - dt.timedelta(days=7)).isoformat(), "--only", name, "--no-opt"],
            },
        ],
    },
    {
        "id": "recruiting-alphalete-org",
        "name": "Alphalete Org 1on1s - Focus Report",
        "creator": "Megan",
        "emoji": "🌐",
        "color": "#10B981",
        "category": "🎯 Recruiting",
        "description": "Pulls recruiting + (eventually) OPT metrics for the "
                       "rep-per-campaign tabs on the Alphalete Org sheet "
                       "(NDS / B2B / BOX / Retail / JE / Frontier).",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Recruiting pull (APPS / Total Applies / Retention / "
            "1st & 2nd Booked / etc.) from AppStream for every visible "
            "rep tab.\n"
            "**•** OPT / Personal Production — *in progress* (NDS reps "
            "aren't in Raf's existing Tableau view; needs Megan to share "
            "a Tableau scope that includes them).\n"
            "**•** Financial section — handled by the weekly Financial "
            "Pull card, which distributes uploaded workbooks to every "
            "matched ICD on this sheet too.\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the just-ended week's column.\n\n"
            "TAB CONVENTION\n"
            "Each tab is named `<AppStream owner name> - <CAMPAIGN>` "
            "(e.g. `Isaiah Revelle - NDS`). The runner strips the "
            "campaign suffix to find the AppStream owner.\n\n"
            "TO ADD A NEW REP\n"
            "**1.**  Create a tab named with the rep's exact AppStream "
            "name + ` - <CAMPAIGN>` suffix.\n"
            "**2.**  The campaign suffix tells the runner which template "
            "to clone (NDS Template / B2B Template).\n"
            "✅  Next run auto-fills the new tab.\n\n"
            "WHEN A REP RETIRES\n"
            "Just **hide the tab** in the Sheet. Runner auto-skips "
            "hidden tabs — no mapping edit needed."
        ),
        "sheet_url": ALPHALETE_ORG_SHEET_URL,
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "8:00 AM",
            "estimated_minutes": 45,
        },
        # Fully unattended via patchright (rcaptain AppStream + ownerville
        # Tableau) — no pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Alphalete Org run complete — recruiting + all "
                               "OPT (NDS, BOX, JE, B2B, Retail) ran. Check the "
                               "per-step summary at the bottom of the log: any "
                               "step marked ❌ can be re-run from its own button. "
                               "Financial section is handled by the weekly "
                               "Financial Pull card.",
            "message_failed":  "❌ Run failed. Check the log above, fix the "
                               "issue, then run again.",
        },
        # CAPTAINSHIP=Alphalete-Org switches the shared recruiting_report
        # module to the Alphalete Org sheet/mapping at import time.
        "env": {"CAPTAINSHIP": "Alphalete-Org"},
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "ONE run: recruiting pull + all OPT (NDS, BOX, JE, B2B, "
                        "Retail) for the current week. Needs Report Chrome open + "
                        "logged into AppStream + ownerville.",
                # Chains recruiting (--no-opt) + every OPT module in sequence via
                # opt_all (Megan 2026-05-25: "chain them"). Each step is an
                # isolated subprocess so one failure can't abort the rest; the
                # OPT modules auto-target the current week, so only the
                # recruiting step needs --week.
                "module": "automations.alphalete_org_report.opt_all",
                "args_fn": lambda: ["--week", _last_completed_we_sunday().isoformat()],
            },
            {
                # Retail OPT - fills BOTH ICD sections on Boaktear's tab
                # (Akib = Boaktear Chowdhury + MJ = Amjad Malhas) plus the
                # shared Costco section. Pulls fresh from CHURNRATES/RETAILPULL,
                # SARAPLUSSALESSUMMARY, ABPCONVERSIONS, RETAILSALESSUMMARYBYCLUB.
                "label": "Run Retail OPT",
                "icon": "🛒",
                "help": "Fills the Retail OPT block on Boaktear's tab for BOTH "
                        "Akib + MJ sections: churn %, Next Up %, Extra/Premium "
                        "%, ABP %, Costco store wireless lines, Internet, and "
                        "Total New Lines. Needs the Reporting Chrome open.",
                "module": "automations.alphalete_org_report.opt_retail",
                "args_fn": lambda: [],
            },
            {
                # BOX OPT - fully automated (Tableau B2B BOX Energy daily
                # tracker, no email/upload needed), so it runs as part of
                # this report. Fills every ' - BOX' tab on each run.
                "label": "Run BOX OPT",
                "icon": "🔋",
                "help": "Fills the BOX OPT block on every ' - BOX' tab: "
                        "Active Selling Heads, Total Box CX's, AVG Kwh per "
                        "CX, AVG Sales per Leader, the shared National AVGs, "
                        "and Accepted %. Pulls fresh from the B2B BOX Energy "
                        "daily tracker (current week).",
                "module": "automations.alphalete_org_report.opt_box",
                "args_fn": lambda: [],
            },
            {
                # NDS OPT - fully automated (Tableau via patchright, no manual
                # Chrome). Fills every ' - NDS' tab's OPT block + rep chart.
                "label": "Run NDS OPT",
                "icon": "📡",
                "help": "Fills the NDS OPT block on every ' - NDS' tab: Active "
                        "Selling Heads, New Lines, AVG Apps/Headcount, Scorecard "
                        "Ranking, churn, Activation %, Cancel Rate, Total Leads, "
                        "Direct Deposit, Next Up/Extra %, plus the rep chart.",
                "module": "automations.alphalete_org_report.opt_nds",
                "args_fn": lambda: [],
            },
            {
                # JE OPT - fully automated (Tableau via patchright). Fills the
                # ' - JE' tab(s): per-store sales, totals, conversion, DD.
                "label": "Run JE OPT",
                "icon": "⚡",
                "help": "Fills the JE OPT block on every ' - JE' tab: per-store "
                        "sales, Total Sales, Store Count, AVG/Store, Conversion, "
                        "Personal Production, Direct Deposit.",
                "module": "automations.alphalete_org_report.opt_je",
                "args_fn": lambda: [],
            },
            {
                # B2B OPT - fully automated (ATTTRACKER-B2B via patchright).
                # Fills the ' - B2B' tab, mapping every metric by label.
                "label": "Run B2B OPT",
                "icon": "🏢",
                "help": "Fills the B2B OPT block on every ' - B2B' tab: rep "
                        "count, new internets/voice/wireless/new lines, total "
                        "apps + AVGs, scorecard ranking, cancel/activation/churn "
                        "rates, penetration, Direct Deposit.",
                "module": "automations.alphalete_org_report.opt_b2b",
                "args_fn": lambda: [],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat(),
                                      "--no-opt"],
            },
            {
                "label": "Run for One Rep (pick a week)",
                "icon": "🎯",
                "needs_date": True,
                "needs_text": True,
                "text_label": "Rep tab name (exact match, incl. campaign suffix)",
                "help": "Just refill ONE rep's tab for any week.",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d, name: ["--week", (d - dt.timedelta(days=7)).isoformat(),
                                            "--only", name, "--no-opt"],
            },
        ],
    },
    {
        "id": "carlos-captainship-headcount",
        "name": "Carlos Captainship Headcount",
        "creator": "Maud",
        "emoji": "🧮",
        "color": "#FF6B6B",
        "category": "📊 Metrics",
        "description": "Adds this week's column to the 'Captainship Head count' tab of the All In One - CARLOS sheet — each active owner's Rep Count from Tableau, retotaled and sorted high→low — then DMs a 4-week screenshot to Carlos + Maud on Slack.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Inserts a fresh leftmost week column.\n"
            "**•** Fills each **active** owner's **Rep Count**, pulled live "
            "from Tableau.\n"
            "**•** DMs a screenshot of the past 4 weeks to **Carlos + Maud** "
            "on Slack (as Lucy).\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each run fills the just-ended week. Re-running the "
            "same week refreshes the numbers in place (no duplicate column).\n\n"
            "IF THE ROSTER CHANGES\n"
            "The run only fills the owners already listed (rows 2–12). If it "
            "prints a **⚠ NOT FOUND** owner, that person may have left "
            "Carlos' team — move+hide their row. To add a new owner, add a "
            "row with their short name; it fills on the next run."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1xQQLzE8mU-a4lpk1IK3WolTPlFxavuMzdK3jA7NGga8/edit"),
        "assignees": ["Lucy 2"],
        # Runs on Lucy 2 (Carlos' Neo Laptop) — its Tableau session + the Monday
        # 7am launchd job (com.alphalete.carlos-captainship-headcount-mon) live
        # there. A Hub "play" from ANY machine routes the run to Lucy 2 via the
        # mini-control queue (run_rerun_id = the schedule_config id `rerun` resolves).
        "run_machine": "Lucy 2",
        "run_rerun_id": "carlos_captainship_headcount",
        # Self-running weekly launchd job: it doesn't report a per-day completion
        # to the Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "7:00 AM",
            "estimated_minutes": 3,
        },
        # Tableau login is unattended (ownerville SSO via patchright) — no
        # pre-flight clicks needed.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Headcount done — this week's column filled, total recomputed, owners sorted, and the 4-week screenshot DM'd to Carlos + Maud on Slack. Review any ⚠ roster flags in the log.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column from Tableau (idempotent — refreshes if it already exists), then DMs a 4-week screenshot to Carlos + Maud on Slack.",
                "module": "automations.carlos_captainship_headcount.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "raf-captainship-bonus",
        "name": "Raf Captainship Bonus",
        "creator": "Maud",
        "emoji": "💰",
        "color": "#E8612A",
        "category": "📊 Metrics",
        "description": "Adds this week's column to the 'Captainship Bonuses' tab of the Alphalete Org/Captainship Reports sheet — each rep's Total Activations + the team New Internet 60-day churn % and activation % from Tableau, recomputes Money Made, re-points the chart, and DMs the PDF to Raf, Dylan + Maud on Slack as Lucy.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Inserts a fresh leftmost week column (this past Sunday, "
            "e.g. `WE 7.5`), pushing prior weeks right and keeping every "
            "rep's history — the top tier tables stay put.\n"
            "**•** Fills each **active** rep's **Total Activations** for Raf's "
            "team (Tableau ATTTRACKER2_1-D2D / CaptainsBonus), plus the team "
            "**60-day churn %** and **activation %** (Rolling 4 Weeks).\n"
            "**•** Auto-syncs the roster: **adds** a row for a new rep and "
            "**hides** one who left the team.\n"
            "**•** Lets the Total Sales / Money Made / TOTAL MONEY MADE "
            "formulas recompute and re-points the performance chart's series "
            "at the Total Sales row.\n"
            "**•** DMs **Raf Captainship WE <date>.pdf** (4 weeks + chart) "
            "to Raf, Dylan + Maud on Slack as Lucy (nothing saved to "
            "Downloads).\n\n"
            "WHEN IT RUNS\n"
            "**Tuesdays.** Each run fills the just-ended week. Re-running the "
            "same week refreshes in place (no duplicate column)."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit"),
        "assignees": ["Lucy 1"],
        # Self-running weekly launchd job on Lucy 1 (Tue 10am CST), not the 4am
        # batch — show the run time on the tile and keep it out of the
        # "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1],  # Tuesday
            "time": "10:00 AM CST",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Raf Captainship Bonus done — column filled, roster synced, Money Made recomputed, chart re-pointed, PDF DM'd to Raf, Dylan + Maud on Slack.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column from Tableau, syncs the roster, and DMs the PDF to Raf, Dylan + Maud on Slack (idempotent — refreshes if it already exists).",
                "module": "automations.raf_captainship_bonus.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "carlos-captainship-bonus",
        "name": "Carlos B2B Captainship Bonus",
        "creator": "Maud",
        "emoji": "💰",
        "color": "#6AA84F",
        "category": "📊 Metrics",
        "description": "Adds this week's column to the 'Carlos B2B Captainship' tab of the All In One - CARLOS sheet — each rep's activations + the four churn / activation / non-payment metrics from Tableau, recomputes Money Made, re-points the chart, and DMs the PDF to Carlos + Maud on Slack.",
        "breakdown": (
            "WHAT IT DOES\n"
            "**•** Inserts a fresh leftmost week column (this past Sunday, "
            "e.g. `WE 7.5`).\n"
            "**•** Fills each **active** rep's **weekly activations** for "
            "Carlos' B2B team (Tableau ATTTRACKER-B2B / Captain Team), plus "
            "the **team 0-30 churn %**, **Carlos' personal 0-30 churn %**, "
            "**31-60 activation %**, and **non-payment %**.\n"
            "**•** Auto-syncs the roster: **adds** a row for a new rep and "
            "**hides** one who left the team.\n"
            "**•** Lets the Total Activations / Money Made / TOTAL AMOUNT "
            "formulas recompute and re-points the performance chart's series "
            "at the Total - All Units row.\n"
            "**•** DMs **Carlos Captainship WE <date>.pdf** (5 weeks + "
            "chart) to Carlos + Maud on Slack (as Lucy).\n\n"
            "WHEN IT RUNS\n"
            "**Tuesdays.** Each run fills the just-ended week. Re-running the "
            "same week refreshes in place (no duplicate column)."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1xQQLzE8mU-a4lpk1IK3WolTPlFxavuMzdK3jA7NGga8/edit"),
        "assignees": ["Lucy 2"],
        # Self-running weekly launchd job on Lucy 2 (Tue 10am), not the 4am
        # batch — show the run time on the tile and keep it out of the
        # "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1],  # Tuesday
            "time": "10:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Carlos B2B Captainship Bonus done — column filled, roster synced, Money Made recomputed, chart re-pointed, PDF DM'd to Carlos + Maud on Slack.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column from Tableau, syncs the roster, and saves the PDF (idempotent — refreshes if it already exists).",
                "module": "automations.carlos_captainship_bonus.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "daily-focus",
        "name": "Daily Recruiting Focus",
        "creator": "Megan",
        "emoji": "☀️",
        "color": "#4ECDC4",
        "category": "🎯 Recruiting",
        "description": "Per-ICD daily breakdown (Mon–Fri current week, last week, plus next-week scheduled) for every captainship tab — fills them all in one run.",
        "breakdown": (
            "WHAT IT DOES\n"
            "A day-by-day breakdown (Mon-Fri) of the recruiting numbers "
            "for **every ICD across all captainship tabs** — current "
            "week and last week, side by side. One run fills every tab.\n\n"
            "WEEKEND ROLLOVER\n"
            "Per Raf's rule, weekend numbers fold into the adjacent weekday:\n"
            "• **Sunday → Monday** (Sun + Mon counts combined into Mon's cell).\n"
            "• **Saturday → Friday** (Fri + Sat counts combined into Fri's cell).\n"
            "Tue/Wed/Thu pass through unchanged. Percentages get recomputed "
            "from the combined counts.\n\n"
            "COLUMN V IS THE LIST — ADD / REMOVE / REORDER\n"
            "The names in **column V** are the source of truth. Each run:\n"
            "• **Adds** a section for any name newly in col V (needs "
            "**rcaptain** AppStream access + an exact-match name).\n"
            "• **Deletes** the section for any name removed from col V.\n"
            "• **Reorders** the sections to match col V's order.\n\n"
            "IF AN ICD IS SKIPPED\n"
            "If a new ICD has no AppStream office mapped yet, the card "
            "prompts you to map it at the top — confirm the match, then re-run."
        ),
        "sheet_url": DAILY_FOCUS_SHEET_URL,
        "assignees": ["Lucy 1"],
        "schedule": {
            # Weekly with weekdays [0..4] = Mon–Fri. (frequency 'daily' would
            # short-circuit and ignore the weekdays filter, so it'd appear
            # 7 days a week on the calendar.)
            "frequency": "weekly",
            "weekdays": [0, 1, 2, 3, 4],  # Mon–Fri (Megan 2026-06-07)
            "time": "7:00 AM",  # 7am CST (Eve)
            "estimated_minutes": 10,
        },
        # Fully unattended via patchright (rcaptain AppStream) — no pre-flight
        # clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Daily Focus run complete — every captainship tab is filled. Any ICD that couldn't be pulled (rcaptain has no AppStream access to it yet) is listed below.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
            "again_label": "🔁 Retry the skipped ICDs",
            "again_action": {
                "label": "Retry skipped ICDs",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: ["--retry-inaccessible"],
            },
            "again_state_file": "output/daily_focus_state.json",
            "again_state_key": "inaccessible",
            "again_empty_message": "✅ All ICDs pulled — nothing to retry.",
        },
        "actions": [
            {
                "label": "Run Daily Focus",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's daily focus report for every ICD across all captainship tabs.",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: [],
            },
            {
                "label": "Run for One ICD",
                "icon": "🎯",
                "needs_text": True,
                "text_label": "ICD name (as it appears in col V)",
                "help": "Just refill one ICD's section — handy after a typo fix or partial run",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda name: ["--only", name],
            },
        ],
    },
    {
        "id": "financial-pull",
        "name": "Financial Report",
        "creator": "Megan",
        "emoji": "💰",
        "color": "#34D399",
        "category": "🎯 Recruiting",
        "description": "Parses the emailed FINANCIAL SUMMARY workbooks "
                       "(plus the German + Coel files) and fills the "
                       "financial section across every matched ICD tab on "
                       "the ATT Program, Carlos 1on1s, and Alphalete Org "
                       "1on1s focus reports.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the financial workbooks emailed each week and writes "
            "them into the latest 4 week columns on every matched ICD.\n\n"
            "WHEN IT RUNS\n"
            "Auto-runs Thursday mornings on the mac mini scheduler — it "
            "pulls this week's FINANCIAL SUMMARY workbooks straight from the "
            "reporting inbox (all senders) and fills, no upload needed. The "
            "manual upload button below stays as a fallback for a re-run.\n\n"
            "IF AN ICD ISN'T IN THIS UPLOAD\n"
            "Their tab is **left untouched** — whatever was filled by a "
            "previous run stays put. When you later upload a file that "
            "DOES include that ICD, the cells fill in then. (So you can "
            "safely upload partial / incremental sets of files any day.) "
            "Raf Hidalgo is permanently skipped (his financials live in "
            "a separate report)."
        ),
        "sheet_url": SHEET_URL,
        # The financial pull writes to three different focus reports. Listed
        # here so the card surfaces all three destinations, not just the
        # primary 'Open Sheet' link (which is the ATT Program one).
        "target_sheets": [
            {"name": "ATT Program - Focus Report",          "url": SHEET_URL},
            {"name": "Carlos 1on1s - Focus Report",         "url": CARLOS_SHEET_URL},
            {"name": "Alphalete Org 1on1s - Focus Reports", "url": ALPHALETE_ORG_SHEET_URL},
        ],
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [3],   # Thursday — 2026-07-01: cut over to auto
                                # email-ingest. All 3 senders land by Wed
                                # midday, so Thursday's 4am run has the full
                                # week with a day of buffer.
            "time": "4:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [
            {"text": "Upload financial .xlsx files recieved via email",
             "uploader": {
                 "target_dir": "automations/uploaded/financial",
                 "accept": [".xlsx"],
                 "multiple": True,
             }},
        ],
        "post_run": {
            "message_success": "✅ Financial section filled on every "
                               "matched ICD tab. Unmatched tabs were left "
                               "untouched (re-upload with their file later).",
            "message_failed": "❌ Run failed. Check the log above.",
        },
        "actions": [
            {
                "label": "Run Financial Pull",
                "icon": "▶",
                "primary": True,
                "help": "Parses every .xlsx in automations/uploaded/financial/ "
                        "and fills the financial section.",
                "module": "automations.financial_report.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "frontier-opt-data-pull",
        "name": "Frontier OPT Data Pull",
        "creator": "Megan",
        "emoji": "📄",
        "color": "#10B981",
        "category": "🎯 Recruiting",
        "description": "Parses the uploaded Frontier PDF reports (Daily "
                       "Sales by Store, Daily Sales Events, Quality "
                       "Scorecard) and fills the OPT section on every "
                       "' - Frontier' tab of the Alphalete Org 1on1s "
                       "focus report.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Reads the Frontier PDFs and fills each Frontier tab:\n"
            "- **Daily Sales - by Store** → per-store production, Total "
            "Sales, Total Store Count, AVG/Store, Active Headcount\n"
            "- **Daily Sales - Events** → GIG % / VAS % / ABP %\n"
            "- **Quality Scorecard** → Approval / Canceled / Pending "
            "(Four Weeks Rolling)\n\n"
            "WHEN IT RUNS\n"
            "Mondays — upload whichever Frontier PDFs arrived, then Run.\n\n"
            "PARTIAL UPLOADS ARE SAFE\n"
            "Upload one, two, or all three PDFs — only the rows from the "
            "PDFs you uploaded change; every other cell is left untouched. "
            "The PDFs each carry their week-ending; data lands in the "
            "correct week column automatically (re-uploads refresh to the "
            "latest numbers)."
        ),
        "sheet_url": ALPHALETE_ORG_SHEET_URL,
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday
            "time": "9:30 AM",
            "estimated_minutes": 3,
        },
        "checklist": [
            {"text": "Upload the Frontier PDF report(s) received via email "
                     "(Daily Sales by Store, Daily Sales Events, and/or "
                     "Quality Scorecard)",
             "uploader": {
                 "target_dir": "automations/uploaded/frontier",
                 "accept": [".pdf"],
                 "multiple": True,
             }},
        ],
        "post_run": {
            "message_success": "✅ Frontier OPT filled from the uploaded "
                               "PDF(s). Rows without a matching PDF were "
                               "left untouched.",
            "message_failed": "❌ Run failed. Check the log above.",
        },
        "actions": [
            {
                "label": "Run Frontier OPT Data Pull",
                "icon": "▶",
                "primary": True,
                "help": "Parses every Frontier PDF in "
                        "automations/uploaded/frontier/ and fills the "
                        "Frontier tabs.",
                "module": "automations.alphalete_org_report.opt_frontier",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "leaders-call",
        "name": "Leader's Call - Weekly Recognition (2:05 PM CST)",
        "creator": "Claude",
        "emoji": "📣",
        "color": "#F59E0B",
        "category": "🎯 Recruiting",
        "description": "Pulls each campaign's qualifying reps from Tableau "
                       "(Fiber, NDS, B2B, JE, BOX, Costco, Revenue) + the "
                       "Frontier scorecard auto-pulled from Lucy's Monday email, "
                       "fills the Leader's Call tab, and DMs the recognition "
                       "PDF to the leadership group as Lucy.",
        # NOTE (Claude): draft 'How it works' — Megan/Maud to review/edit.
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills the **Leader's Call** tab with the week's recognition "
            "names per campaign, each section sorted high-to-low:\n"
            "- **Fiber / NDS / B2B / JE / BOX** — reps with **12+** apps\n"
            "- **Costco** — reps with **8+** (ATV+DTV+Internet+AIA+New/Port, "
            "no Up)\n"
            "- **Revenue over 2K** — reps at **$2,000+** (local-office owners)\n"
            "- **Frontier** — reps with **8+** from the uploaded scorecard\n\n"
            "WHEN IT RUNS\n"
            "**Mondays.** Each campaign view's 'This Week' = the just-"
            "completed week, so the run recognizes the finished week.\n\n"
            "FRONTIER — AUTO-PULLED FROM EMAIL\n"
            "Frontier isn't in Tableau, so it's read automatically from the "
            "**'Frontier - Sales Verification' email** that lands in Lucy's "
            "inbox Monday ~2pm — **no upload needed**. (Backup: if that email "
            "hasn't arrived yet, it uses the last uploaded file; you can upload "
            "one below.) The other 7 campaigns pull from Tableau (no login "
            "needed).\n\n"
            "DATA SOURCES\n"
            "Each section comes from its own Tableau crosstab (pulled "
            "unattended via the saved ownerville session), filtered to the "
            "local-office owners + that section's threshold.\n\n"
            "DELIVERY\n"
            "After a clean run, the recognition PDF is built and DM'd to the "
            "leadership group (Maud, Carlos, Rafael) on Slack as Lucy — "
            "automatically."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],   # Monday
            "time": "2:05 PM",
            "estimated_minutes": 8,
        },
        "checklist": [
            {"text": "Backup only — Frontier auto-pulls from Lucy's Monday "
                     "email. Upload the 'Sales Verification' file here ONLY if "
                     "that email hasn't arrived yet.",
             "uploader": {
                 "target_dir": "automations/uploaded/leaders_call_frontier",
                 "accept": [".xlsx", ".csv", ".pdf"],
                 "multiple": True,
             }},
        ],
        "post_run": {
            "message_success": "✅ Leader's Call tab filled + recognition PDF "
                               "DM'd to the group (Maud, Carlos, Rafael) as "
                               "Lucy. Spot-check before the call.",
            "message_failed": "❌ Run failed. Check the log above, then re-run.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Pulls all 7 Tableau campaigns + the Frontier upload "
                        "and writes the Leader's Call tab.",
                "module": "automations.leaders_call.run",
                "args_fn": lambda: ["--write"],
            },
            {
                "label": "Preview (no write)",
                "icon": "👁",
                "help": "Pull + print every section without touching the Sheet.",
                "module": "automations.leaders_call.run",
                "args_fn": lambda: ["--dry-run"],
            },
        ],
    },
    {
        "id": "daily-rep-breakdown",
        "name": "Daily Rep Breakdown - ATT Program",
        "creator": "Megan",
        "emoji": "📊",
        "color": "#F472B6",
        "category": "🎯 Recruiting",
        "description": "Per-rep day-by-day production breakdown from "
                       "ownerville + Tableau — one tab per owner. "
                       "Monday wipes + scrapes the full week; Tue-Sun "
                       "incremental.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls each rep's daily production from ownerville and "
            "Tableau into the Daily Rep Breakdown Sheet. Monday does a "
            "full wipe + re-scrape (so terminated reps drop off "
            "cleanly). Tue-Sun do an incremental update (yesterday's "
            "now-complete numbers plus today's partial).\n\n"
            "WHEN IT RUNS\n"
            "**Every day.** Monday is a fresh start; the rest of the "
            "week is additive."
        ),
        "sheet_url": "https://docs.google.com/spreadsheets/d/"
                     "1xgVE_e8bZimACgPdqcdNCr1qo4sedWect_zzEcUgEJY/edit",
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "9:00 AM",
            "estimated_minutes": 15,
        },
        # Fully unattended via patchright (ownerville Tableau session) — no
        # pre-flight clicks. Empty list hides the section.
        "checklist": [],
        "post_run": {
            "message_success": "✅ Daily Rep Breakdown complete — Sheet "
                               "updated and you'll see a desktop "
                               "notification when it finishes.",
            "message_failed": "❌ Run failed. Check the log above, fix "
                              "the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Rep Breakdown",
                "icon": "▶",
                "primary": True,
                "help": "Monday = full wipe + scrape. Tue-Sun = "
                        "incremental update.",
                "module": "automations.focus_office_att.daily",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "daily-metrics",
        "name": "10 Daily Metrics Report",
        "creator": "Megan",
        "emoji": "📊",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "One run that fires all 10 daily #alphalete-sales metrics — Telemapper Knocks, Time Gaps, Order Log, Sales Scheduled 6+ Days, Canceled Orders, Ongoing Cancel, Disconnects, New Internet Churn, Wireless Churn, Rep Activations — each posting into today's Metrics thread.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Runs all 10 metric reports back-to-back & posts into today's "
            "Metrics thread in #alphalete-sales Slack. The day's header "
            "thread is posted first if it isn't already up.\n\n"
            "METRICS POSTED (in thread order)\n"
            "• 🪵 Telemapper Knocks\n"
            "• ⏰ Time Gaps\n"
            "• 📋 Order Log\n"
            "• 📅 Sales Scheduled 6+ Days Out\n"
            "• 🚫 Canceled Orders\n"
            "• 🔁 Ongoing Cancel\n"
            "• ❎ Disconnected New Internets\n"
            "• 🌐 New Internet Churn\n"
            "• 📊 Wireless Churn\n"
            "• 🆕 Rep Activations\n\n"
            "IF ONE FAILS\n"
            "The run keeps going and ends with a ✅/❌ summary. Re-run just "
            "the ones that failed from 'More actions' below.\n\n"
            "WHEN IT RUNS\n"
            "Daily.\n\n"
            "──────────  HOW EACH REPORT WORKS  ──────────\n\n"
            "🪵 TELEMAPPER KNOCKS + ⏰ TIME GAPS\n"
            "Collects Disposition by rep + time gaps from Ownerville (always "
            "the day prior) for Raf's Local Office. Screenshots + posts both "
            "to the Metrics thread; keeps no record. Opens Ownerville "
            "automatically — don't type in or close the window while it runs.\n\n"
            "📋 ORDER LOG + 🆕 REP ACTIVATIONS\n"
            "Fills out the order log and saves it to your Downloads folder as "
            "'Order Log MM-DD-YYYY.xlsx', then posts it to the Metrics thread. "
            "From the same data it also posts a 🆕 Rep Activations summary "
            "(Posted / Pending / Total / Canceled per rep, last week & this "
            "week).\n\n"
            "📅 SALES SCHEDULED 6+ DAYS OUT\n"
            "All scheduled new-internet installs planned 6+ days out for Raf's "
            "Local Office + Raf's Captainship + Starr's Captainship. Fills the "
            "'VAs' Data' sheet tabs (Scheduled 6 days out — Raf / Starr), "
            "overwritten clean + color-shaded by Owner. Saves a colored table "
            "per captainship to Downloads, posts Raf's Local Office to the "
            "Metrics thread, and emails each captainship its table from "
            "alphaletereporting@gmail.com with Eve's signature.\n\n"
            "🚫 CANCELED ORDERS\n"
            "Pulls the Tableau Order Log for the previous 30 completed days. "
            "New rows insert at the TOP of each tab, dedup'd by (Customer "
            "Name, SPM #). Posts an image of the new Local Office cancels. "
            "Tabs filled (AT&T Fiber Metrics Report): Local Office - Daily "
            "Cancels, Raf's Captainship - Cancels Ongoing, Starr Capi + Sahil "
            "- Cancels Ongoing.\n\n"
            "🔁 ONGOING CANCEL\n"
            "Pulls Internet Cancel Rates (Running Sum) from Tableau for Raf's "
            "reps over the last 7 days.\n\n"
            "❎ DISCONNECTED NEW INTERNETS\n"
            "Pulls the Tableau Order Log for the previous 30 completed days. "
            "New rows insert at the TOP of each tab, dedup'd by (Customer "
            "Name, Account BAN). Posts an image of the new Local Office "
            "disconnects. Tabs filled (AT&T Fiber Metrics Report): Local "
            "Office / Raf's Captainship / Starr Capi + Sahil - New Internet "
            "Disconnects.\n\n"
            "🌐 NEW INTERNET CHURN + 📊 WIRELESS CHURN\n"
            "Fills Raf's Local Office churn on the AT&T Fiber Metrics Report "
            "sheet (tabs: Local Office - New Internet Churn, Local Office - "
            "Wireless Churn) and posts both to the Metrics thread."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 15,
        },
        "post_run": {
            "message_success": "✅ Daily Metrics done — all 10 posted to the Metrics thread.",
            "message_failed": "❌ Some metrics failed — check the summary above, then re-run those from More actions.",
        },
        "actions": [
            {
                "label": "Run All 10 Metrics",
                "icon": "▶",
                "primary": True,
                "help": "Runs all 7 reports → 10 metrics posted to today's thread; continues past any that fail.",
                "module": "automations.daily_metrics.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Telemapper Knocks + Time Gaps",
                "icon": "🪵",
                "help": "Re-run just Knocks + Time Gaps.",
                "module": "automations.total_knocks.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Order Log",
                "icon": "📋",
                "help": "Re-run just the Order Log.",
                "module": "automations.uploaded.order_log",
                "args_fn": lambda: [],
            },
            {
                "label": "Sales Scheduled 6+ Days Out",
                "icon": "📅",
                "help": "Re-run just Sales Scheduled 6+ Days Out.",
                "module": "automations.scheduled_6_days_out.run",
                "args_fn": lambda: ["--post-slack", "--send-email"],
            },
            {
                "label": "Canceled Orders",
                "icon": "🚫",
                "help": "Re-run just Canceled Orders.",
                "module": "automations.canceled_orders.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Ongoing Cancel",
                "icon": "🔁",
                "help": "Re-run just Ongoing Cancel.",
                "module": "automations.ongoing_cancel.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Disconnected New Internets",
                "icon": "❎",
                "help": "Re-run just Disconnects.",
                "module": "automations.disconnects.run",
                "args_fn": lambda: [],
            },
            {
                "label": "New Internet + Wireless Churn (Local Office)",
                "icon": "🌐",
                "help": "Re-run just Raf's Local Office churn (New Internet + Wireless).",
                "module": "automations.churn.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "rashad-metrics",
        "name": "Rashad's Daily Metrics (#elevate-sales)",
        "creator": "Megan",
        "emoji": "📈",
        "color": "#8B5CF6",
        "category": "🏢 Other Offices",
        "description": "The same 10 daily metrics as the main report, scoped to Rashad Reed's office and posted into his #elevate-sales Metrics thread — Telemapper Knocks, Time Gaps, Order Log, Sales Scheduled 6+ Days, Canceled Orders, Ongoing Cancel, Disconnects, New Internet Churn, Wireless Churn, Rep Activations.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Runs all 10 daily metrics for Rashad Reed's office and posts each "
            "into today's Metrics thread in #elevate-sales (one header thread "
            "per day, created first if it isn't up yet).\n\n"
            "METRICS POSTED (in thread order)\n"
            "• 🚪 Telemapper Knocks\n"
            "• ⏰ Time Gaps\n"
            "• 📋 Order Log\n"
            "• 📅 Sales Scheduled 6+ Days Out\n"
            "• 🚫 Canceled Orders\n"
            "• 🔁 Ongoing Cancel\n"
            "• ❎ Disconnected New Internets\n"
            "• 🌐 New Internet Churn\n"
            "• 📊 Wireless Churn\n"
            "• 🆕 Rep Activations\n\n"
            "IF ONE FAILS\n"
            "The run keeps going and ends with a ✅/❌ summary. Re-run just the "
            "ones that failed from the per-metric buttons below.\n\n"
            "WHEN IT RUNS\n"
            "Daily, not before 6am — same metric logic as the main report, "
            "filtered to Rashad's office and posted to #elevate-sales instead "
            "of #alphalete-sales."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "11louWIU8IuSPrZLsMkRh8qEnO3wNqmeNwIOSKPpXzm8/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "6:00 AM",
            "estimated_minutes": 12,
        },
        "post_run": {
            "message_success": "✅ Rashad's metrics posted to the #elevate-sales thread.",
            "message_failed": "❌ A metric failed — check the summary above, then re-run that one from the buttons below.",
        },
        "actions": [
            {
                "label": "Run All Metrics",
                "icon": "▶",
                "primary": True,
                "help": "Runs all 10 metrics → posted to today's #elevate-sales thread; continues past any that fail.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--live"],
            },
            {
                "label": "Telemapper Knocks + Time Gaps",
                "icon": "🚪",
                "help": "Re-run just Knocks + Time Gaps for Rashad.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "knocks_gaps", "--live"],
            },
            {
                "label": "Order Log + Rep Activations",
                "icon": "📋",
                "help": "Re-run just the Order Log + Rep Activations for Rashad.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "order_log", "--live"],
            },
            {
                "label": "Sales Scheduled 6+ Days Out",
                "icon": "📅",
                "help": "Re-run just Sales Scheduled 6+ Days for Rashad.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "sales_6plus", "--live"],
            },
            {
                "label": "Canceled Orders",
                "icon": "🚫",
                "help": "Re-run just Canceled Orders for Rashad.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "cancels", "--live"],
            },
            {
                "label": "Ongoing Cancel",
                "icon": "🔁",
                "help": "Re-run just Ongoing Cancel for Rashad.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "ongoing_cancel", "--live"],
            },
            {
                "label": "Disconnected New Internets",
                "icon": "❎",
                "help": "Re-run just Disconnects for Rashad.",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "disconnects", "--live"],
            },
            {
                "label": "New Internet + Wireless Churn",
                "icon": "🌐",
                "help": "Re-run just New Internet + Wireless Churn for Rashad (the recovery used 2026-06-30).",
                "module": "automations.rashad_metrics.run",
                "args_fn": lambda: ["--only", "churn", "--live"],
            },
        ],
    },
    {
        "id": "fiber-activations",
        "name": "Fiber Activations Report",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#A78BFA",
        "category": "🎯 Fiber",
        "description": "Daily Wed→Tue fill on the 'Captainship Activations' tab — Raf's team activations + country activations + EOW sales + 60-day churn + activation rate. Then posts the blue + orange screenshots to Slack.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls 6 Tableau numbers daily into the 'Captainship Activations' "
            "tab, then renders two PNGs (blue Fiber table + secondary tables, "
            "orange Country table) and posts them to #level10-alphalete.\n\n"
            "WHEN IT RUNS\n"
            "**Every day, Wed–Tue.** Each Wednesday inserts a new row for the "
            "new cycle.\n\n"
            "SLACK\n"
            "Replies in the weekly **'Activations Report Tracker WE MM.DD'** "
            "thread (created automatically each Wednesday, under Eve). Post "
            "name = PNG file name; Wednesday's Fiber post tags Rafael, Maud "
            "& Dylan."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "5:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Fiber Activations done — sheet updated (day cell + Activations + EOW Sales + Churn + Activation Rate) and both screenshots posted to the WE tracker thread in #level10-alphalete.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Today's Fill",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's day-of-week cell (Wednesday also inserts the new row), then posts the blue + orange screenshots to the weekly tracker thread in #level10-alphalete.",
                "module": "automations.fiber_activations.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "tableau-screenshots",
        "name": "Alphalete Tableau Trackers",
        "creator": "Megan",
        "emoji": "📸",
        "color": "#1F4E79",
        "category": "📊 Metrics",
        "description": "Captures the 8 Tableau sales trackers as images and posts them daily into an 'Alphalete Tableau Trackers M/D/YYYY' thread in #alphalete-sales + #top-leaders-alphalete-org. Replaces Jolie's manual tracker post.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Grabs each of the 8 Tableau trackers \n\n"
            "TRACKERS\n"
            "1. AT&T Internet Country Sales Tracker\n"
            "2. AT&T Internet Country Sales Tracker (Internet Only)\n"
            "3. NDS Tracker\n"
            "4. B2B AT&T Internet Country Sales Tracker\n"
            "5. B2B AT&T Internet Country Sales Tracker (CRU)\n"
            "6. B2B D2D Consolidated\n"
            "7. B2B Box Tracker\n"
            "8. ATT Quantum Fiber Daily Tracker\n\n"
            "WHEN IT RUNS\n"
            "Daily in Slack channels: #alphalete-sales & #top-leaders-alphalete-org."
        ),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "5:00 AM",
            "estimated_minutes": 12,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Tableau Trackers posted — all 8 tracker screenshots in the dated thread in #alphalete-sales + #top-leaders-alphalete-org.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Post Today's Trackers",
                "icon": "▶",
                "primary": True,
                "help": "Captures the 8 Tableau trackers and posts them to the dated thread in #alphalete-sales + #top-leaders-alphalete-org. Needs a warm Tableau session (best run on the mini).",
                "module": "automations.tableau_screenshots.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "alphalete-production",
        "name": "Alphalete Daily Production Slack Post",
        "creator": "Eve",
        "emoji": "🐺",
        "color": "#6A4C93",
        "category": "📊 Metrics",
        "description": "Combines Jolie's two manual morning screenshot posts into ONE dated '🐺 Alphalete Production' thread in #alphalete-sales: Daily Production, a Team Sales board per team, Highrollers of the day, and 3 rankings (Apps / New Internets / Wireless).",
        "breakdown": (
            "WHAT IT DOES\n"
            "Screenshots the Sales Board tab into clean PNGs — off a hidden, "
            "auto-deleted copy tab, so the live sheet is never touched — and posts "
            "them as Lucy in one threaded post.\n\n"
            "IMAGES\n"
            "1. Daily Production\n"
            "2. Team Sales — one image per team (auto-counts from the sheet)\n"
            "3. Highrollers of the Day\n"
            "4. Total Week Production (Ranking based on Apps)\n"
            "5. Ranking based on New Internets\n"
            "6. Ranking based on Wireless\n\n"
            "WHEN IT RUNS\n"
            "Daily, ~4 AM on the mini (before the manual post), into #alphalete-sales. "
            "Monday shows the fully-completed prior Mon–Sun week."
        ),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "4:00 AM",
            "estimated_minutes": 8,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Alphalete Production posted — Daily Production, team boards, Highrollers, and the 3 rankings in the dated thread in #alphalete-sales.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Post Today's Production",
                "icon": "▶",
                "primary": True,
                "help": "Renders every section off a hidden copy of the Sales Board tab and posts them to the dated thread in #alphalete-sales. Best run on the mini (posts as Lucy).",
                "module": "automations.alphalete_production.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "captainship-activations",
        "name": "Captainship Activations (per-captain)",
        "creator": "Eve",
        "emoji": "🧑‍✈️",
        "color": "#8E7CC3",
        "category": "🎯 Fiber",
        "description": "Daily Wed→Tue fill of the 5 per-captain tabs (Wayne, Starr, Chan, Tony, Sahil): violet captain table + shared country table. Renders 6 PNGs and saves them to your Downloads folder (no Slack).",
        "breakdown": (
            "WHAT IT DOES\nOne Tableau pull → writes each captain's violet cells "
            "(activations, EOW, churn, appr) + the global country cells, then "
            "renders 6 PNGs (5 captain violet w/o the Payout col + 1 country) and "
            "saves them to your Downloads folder.\n\nDRIVE\nUpload to the "
            "'Captainship Activations - PNGs' Drive folder is OPTIONAL (the "
            "'Run + upload to Drive' button) and pending the Drive API being "
            "enabled — a failed/disabled upload never breaks the run.\n\nWHEN\n"
            "**On the scheduler — every day, Wed–Tue** (fully unattended, "
            "gated on the same Fiber Tableau session as Fiber Activations). "
            "You can also trigger it by hand here. Wednesday "
            "structure-only-inserts the new WE row. NO Slack."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "13-9f_aPDlPa6L6_Wash4ws7959mn822J__vB5OYmcB8/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {"frequency": "daily", "time": "9:00 AM", "estimated_minutes": 6},
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Activations done — 5 tabs filled (violet + country) and 6 PNGs uploaded to the Drive folder.",
            "message_failed": "❌ Run failed. Check the log, fix, re-run.",
        },
        "actions": [
            {
                "label": "Run Today's Fill",
                "icon": "▶",
                "primary": True,
                "help": "Pulls Tableau, fills the 5 tabs, renders the 6 PNGs and saves them to your Downloads folder.",
                "module": "automations.fiber_activations.captain_run",
                "args_fn": lambda: [],
            },
            {
                "label": "Dry-run (no writes)",
                "icon": "🧪",
                "primary": False,
                "help": "Pull + show what would be written + render PNGs locally; no Sheet writes, no Downloads/Drive.",
                "module": "automations.fiber_activations.captain_run",
                "args_fn": lambda: ["--dry-run"],
            },
            {
                "label": "Run + upload to Drive",
                "icon": "☁",
                "primary": False,
                "help": "Same as Run Today's Fill, plus upload the PNGs to the Drive folder (needs the Drive API enabled; failures are non-fatal).",
                "module": "automations.fiber_activations.captain_run",
                "args_fn": lambda: ["--drive"],
            },
        ],
    },
    {
        "id": "captainship-new-internet-wireless-churn",
        "name": "Captainship - New Internet & Wireless Churn",
        "creator": "Megan",
        "emoji": "🧭",
        "color": "#F59E0B",
        "category": "📊 Metrics",
        "description": "Daily fill of Raf's Captainship per-ICD churn rates (4 buckets: 0-30 / 30 / 60 / 90 day) for BOTH the Captainship New Internet and Wireless tabs. Pulls overall ICD churn (one row per ICD owner), not per-rep. No Slack post — sheet fill only.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills Raf's Captainship per-ICD churn rates "
            "(\"AT&T Fiber Metrics Report\" Google Sheet) "
            "on both the Captainship New Internet and Captainship "
            "Wireless tabs.\n\n"
            "TABS FILLED (on the AT&T Fiber Metrics Report sheet)\n"
            "• Captainship - New Internet Churn\n"
            "• Captainship - Wireless Churn\n\n"
            "WHEN IT RUNS\n"
            "Daily."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Captainship Churn done — both tabs filled, sections sorted, blank-today rows hidden.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Captainship Churn (Both Tabs)",
                "icon": "▶",
                "primary": True,
                "help": "Pulls both Captainship Churn Crosstabs in one Tableau session + fills both tabs (skips today if already filled — pass --force-insert in CLI to override).",
                "module": "automations.captainship_churn.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "owners-metrics-churn",
        "name": "Captainship Churn - Owners Metrics Report",
        "creator": "Megan",
        "emoji": "📑",
        "color": "#F59E0B",
        "category": "📊 Metrics",
        "description": "Daily per-ICD churn fills across the Owners Metrics Report sheet — one tab per captainship. Covers ATT Fiber (Wayne / Starr Rodenhurst / Chan Park / Tony Chavez / Sahil Multani), B2B (Carlos Hidalgo / Eveliz Wright / Luis Salazar), and NDS (Khalil Mansour / Colten Wright / Jairo Ruiz).",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills per-ICD churn rates on every captainship tab of "
            "the Owners Metrics Report Google Sheet.\n\n"
            "TABS FILLED — ATT Fiber (4 buckets: 0-30 / 30 / 60 / 90)\n"
            "• Churn - Wayne (ATT Fiber)\n"
            "• Churn - Starr Rodenhurst (ATT Fiber)\n"
            "• Churn - Chan Park (ATT Fiber)\n"
            "• Churn - Tony Chavez (ATT Fiber)\n"
            "• Churn - Sahil Multani (ATT Fiber)\n\n"
            "TABS FILLED — B2B (5 buckets: 0-30 / 30 / 60 / 90 / 120)\n"
            "• Churn - Carlos Hidalgo (B2B)\n"
            "• Churn - Eveliz Wright (B2B)\n"
            "• Churn - Luis Salazar (B2B)\n\n"
            "TABS FILLED — NDS (4 buckets: 0-30 / 30 / 60 / 90)\n"
            "• Churn - Khalil Mansour (NDS)\n"
            "• Churn - Colten Wright (NDS)\n"
            "• Churn - Jairo Ruiz (NDS)\n\n"
            "WHEN IT RUNS\n"
            "Daily."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1uFrT0EkkGT0QqlYTxw_uevZD3ObKxaVjWsvZAUDxK6c/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Owners Metrics Churn done — all Fiber tabs filled, sections sorted, blank-today + 5-zero rows hidden.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Owners Metrics Churn",
                "icon": "▶",
                "primary": True,
                "help": "Pulls all captainship Crosstabs in one Tableau session + fills each tab (skips today's INSERT if already filled — pass --force-insert in CLI to override).",
                "module": "automations.owners_metrics_churn.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "ongoing-1st-round-recruiter-retention",
        "name": "Ongoing 1st Round Recruiter Retention",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#2563EB",
        "category": "🎯 Recruiting",
        "description": "Weekly per-recruiter 1st-round retention for Raf's office — Scheduled / Showed Up / Retention % (Showed ÷ Scheduled) per week on the '1st rd Recruiter %' tab. Columns are week-ending Sundays; % color-coded (<45% red, 45–49.9% grey, ≥50% green); active schedulers highlighted.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls AppStream's Retention Report (admin breakdown) for Raf's "
            "office and fills one block per week per recruiter: Scheduled (Sch), "
            "Showed Up (SU), and Retention % (Showed ÷ Scheduled).\n\n"
            "WEEKS\n"
            "Each column is a week ENDING on Sunday. AppStream only reports "
            "Sun–Sat weeks, so a column uses the AppStream week that ends the day "
            "before it — a ~1-week shift (Sundays are near-zero, so the weekly "
            "totals line up).\n\n"
            "COLORS & HIGHLIGHTS\n"
            "• Retention %: under 45% red, 45–49.9% grey, 50%+ green.\n"
            "• A recruiter's NAME turns yellow if they scheduled an interview in "
            "the latest week (active schedulers that week).\n"
            "• AI Messaging and Self Scheduled rows are tinted — interviews not "
            "booked by a person.\n\n"
            "ROWS\n"
            "Recruiters who scheduled an interview in the last 2 weeks sit on top, "
            "sorted by the latest week's retention (high → low). Those with none "
            "in the last 2 weeks drop to the bottom and are hidden.\n\n"
            "WHEN IT RUNS\n"
            "Mondays. Each run fills the latest week and catches up any missed "
            "weeks; existing history stays as-is."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "8:00 AM",
            "estimated_minutes": 10,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Recruiter retention updated — week totals filled, recruiters sorted by retention, inactive rows hidden.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Recruiter Retention",
                "icon": "▶",
                "primary": True,
                "help": "Pull AppStream + fill all weeks on the Ongoing tab (week totals).",
                "module": "automations.recruiter_retention.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "daily-1st-round-recruiter-percent",
        "name": "Daily Recruiter 1st Round Retention",
        "creator": "Megan",
        "emoji": "🎯",
        "color": "#2563EB",
        "category": "🎯 Recruiting",
        "description": "Daily Mon–Fri recruiter scorecards for Raf's office on the 'Daily 1st rd Recruiter %' tab — Booked / Scheduled / Showed / Retention % per day + Total, with current week (Mon→today) and last week side by side. Alphabetized; inactive recruiters recycle to a hidden bottom; % color-coded.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls AppStream's Retention Report (admin breakdown) for Raf's "
            "office and fills a daily Mon–Fri scorecard per recruiter.\n\n"
            "TWO CARDS PER RECRUITER\n"
            "• Left = current week, filled Monday → today (days after today "
            "stay blank).\n"
            "• Right = last week, full Mon–Fri.\n"
            "The day-header dates auto-update to the current week each run.\n\n"
            "COLORS\n"
            "Retention %: under 45% red, 45–49.9% grey, 50%+ green.\n\n"
            "ROWS / RECYCLING\n"
            "Recruiters are alphabetized. Anyone with no Booked/Scheduled/Showed "
            "for two weeks straight drops to the bottom and is hidden (never "
            "deleted) — they resurface at the top automatically when they get "
            "activity again. Manual Weekly/Daily goals in columns A/B travel with "
            "each recruiter, so they're never erased or misaligned.\n\n"
            "WHEN IT RUNS\n"
            "Monday–Friday, 8 AM."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4/edit"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "weekdays": [0, 1, 2, 3, 4],   # Mon–Fri only
            "time": "8:00 AM",
            "estimated_minutes": 4,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Daily recruiter % updated — Mon→today + last week filled, alphabetized, inactive recycled to the hidden bottom.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Recruiter %",
                "icon": "▶",
                "primary": True,
                "help": "Pull AppStream + fill the daily Mon–Fri scorecards (this week + last week).",
                "module": "automations.recruiter_retention.daily",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "country-metrics",
        "name": "Country Metrics",
        "creator": "Eve",
        "emoji": "🌎",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "Weekly New Internet Country Metrics + Sales/breakdown per captainship (Raf / Starr / Aron / Pat / Wayne / Sam / Chan / Tony / Sahil) on the 'Country Metrics' tab.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls New Internet Country Metrics and Sales + Breakdown per "
            "Captainship.\n\n"
            "WHEN IT RUNS\n"
            "Thursdays. Each run fills the most recently finished week.\n\n"
            "WHILE IT RUNS\n"
            "Claude will automatically open/connect with Tableau, do not type "
            "or close the window while it works, otherwise the run will fail. "
            "It will indicate when it's finished."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE/edit#gid=1044031962"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [3],  # Thursday
            "time": "8:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Country Metrics done — all 10 sections (COUNTRY + 9 captainships) filled for the latest weekending.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recently finished week's column (run Thursdays).",
                "module": "automations.country_metrics.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "int-wow-penetration",
        "name": "Int WoW Report - Penetration %",
        "creator": "Eve",
        "emoji": "📶",
        "color": "#0EA5E9",
        "category": "📊 Metrics",
        "description": "Weekly Fiber Lead penetration % per owner on the Int WoW Report sheet. Each Tuesday inserts a new weekending column (newest first) in the 'Penetration %' table from Tableau's Fiber Lead Performance view.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Pulls per-owner Fiber Lead penetration % from Tableau (ATT "
            "Tracker 2.1 - D2D / Fiber Lead Performance) and inserts a new "
            "weekending column at the LEFT (B) of the 'Penetration %' table "
            "— newest week first, older weeks shift right.\n\n"
            "WHEN IT RUNS\n"
            "**Tuesdays.** The weekending is the previous Sunday (Central).\n\n"
            "OWNER MATCHING\n"
            "Owner names are matched to the sheet through the ICD Aliases "
            "sheet, so spelling variants collapse to one person. Owners on "
            "the sheet that Tableau didn't report get '-%'. New owners are "
            "inserted alphabetically; look-alike names are logged (not "
            "inserted) so you can add an alias.\n\n"
            "TOTAL ROW\n"
            "The NATIONAL row = Tableau's 'Total general' Assigned Fiber Lead "
            "Penetration with Owner = (All).\n\n"
            "WATCH FOR\n"
            "Any % above 50% is logged as a WARNING (likely a Tableau glitch) "
            "but still written."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit#gid=1630583673"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1],  # Tuesday
            "time": "8:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Int WoW Penetration % done — new weekending column inserted at B, owners matched, '-%' filled, NATIONAL total set.",
            "message_failed": "❌ Run failed. Check the log above (a stale Tableau/ownerville session usually clears on a retry), then run again.",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Pulls Fiber Lead Performance from Tableau and inserts this week's column (weekending = last Sunday). Re-running the same week overwrites that column.",
                "module": "automations.int_wow_penetration.run",
                "args_fn": lambda: [],
            },
            {
                "label": "Run a Specific Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick any date in the target week; the weekending Sunday is computed automatically.",
                "module": "automations.int_wow_penetration.run",
                "args_fn": lambda d: ["--date", d.isoformat()],
            },
        ],
    },
    {
        "id": "org-sales-board",
        "name": "Alphalete Org Sales Board (Copy Tab)",
        "creator": "Megan",
        "emoji": "🏆",
        "color": "#10B981",
        "category": "📊 Metrics",
        "description": "Fills the Alphalete Org Sales Board COPY TAB — 7 daily product sections (Retail NL/Internet, Fiber, NDS, B2B, BOX, Retail JE) + all 10 captainship leaderboards from Tableau. Writes ONLY to the copy tab (validation), never the live VA tab.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Fills the **copy tab** of the Alphalete Org Sales Board: all 7 "
            "daily product sections (Retail NL, Retail Internet, ATT Fiber, "
            "ATT NDS, B2B, BOX, Retail JE) and all 10 captainship "
            "leaderboards.\n\n"
            "WHERE IT WRITES\n"
            "**COPY TAB ONLY** — \"Copy of Alphalete ORG Sales Board\". It never "
            "touches the live VA tab. This is the validation pass: run it daily, "
            "compare to what the VAs key, confirm it matches before going live.\n\n"
            "WHEN IT RUNS\n"
            "**Daily.** Only completed days fill; today + future stay blank.\n"
            "**Tuesday** — the run rolls the week over **automatically** first "
            "(freezes the finished week + shifts the 4-week history), then fills. "
            "Nothing extra to do; safe to re-run (the rollover skips if already "
            "done).\n\n"
            "MATCH CHECK\n"
            "Every daily fill ends by **auto-comparing** the copy to the live VA "
            "tab (by ICD, completed days) and flags any real mismatch — so a "
            "glitch never slips by.\n\n"
            "STILL MANUAL (not yet automated)\n"
            "Only **Frontier** (Verizon PDF) is keyed by hand now. **Retail JE** "
            "is automated — it pulls from Just Energy (Daily Sales by ICD) and "
            "auto-rolls to the current week (filled for the ICDs already on the "
            "board).\n\n"
            "ZERO-SALES ICDs\n"
            "An ICD with no sales this week shows **NS** — that's correct (it "
            "matches the VAs' 0) and it fills the moment they sell."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit#gid=388012799"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "6:00 AM",
            "estimated_minutes": 20,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Org Sales Board (copy tab) filled — 7 daily sections + 10 captainships, by program. Compare to the VA tab to confirm the match.",
            "message_failed": "❌ Run failed. Check the log above, fix the issue, then run again.",
        },
        "actions": [
            {
                "label": "Run Daily Fill (Copy Tab)",
                "icon": "▶",
                "primary": True,
                "help": "Fills the copy tab's 7 daily sections + 10 captainships for the completed days this week, then auto-compares to the live VA tab and flags any real mismatch. On Tuesdays it rolls the week over first automatically. Copy tab only — never the live VA tab.",
                "module": "automations.org_sales_board.run",
                "args_fn": lambda: ["--step", "daily", "--with-captainships"],
            },
        ],
    },
    {
        "id": "sales-board-screenshot-email",
        "name": "Org. Sales Board Email",
        "creator": "Megan",
        "emoji": "📧",
        "color": "#DC2626",
        "category": "📊 Metrics",
        "description": "Emails exact-sheet screenshots of the Org Sales Board (copy tab) — Product Summary, ALPHALETE ORG leaderboard, the daily sections, every in-org captainship, and the RAF/CARLOS/COLTEN/BEN ORG summaries. Rendered via the Sheets PDF export (no browser).",
        "breakdown": (
            "WHAT IT DOES\n"
            "Sends a daily email of the Org Sales Board as clean, exact-sheet "
            "screenshots (colors/fonts/borders match the sheet). Rendered from the "
            "COPY tab via the Google Sheets PDF-export endpoint — no browser, runs "
            "from any machine.\n\n"
            "RECIPIENTS\n"
            "Proving phase: Maud + Rafael + Megan. Expand to the full distribution "
            "list once it's proven out.\n\n"
            "WHEN IT RUNS\n"
            "Daily, after the morning Sales Board fill (so the numbers are fresh)."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E/edit#gid=25197725"),
        "assignees": ["Lucy 1"],
        "schedule": {
            "frequency": "daily",
            "time": "6:30 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Sales Board screenshot email sent.",
            "message_failed": "❌ Send failed — check the log above, fix, then re-run.",
        },
        "actions": [
            {
                "label": "Send Email (Maud + Rafael + Megan)",
                "icon": "▶",
                "primary": True,
                "help": "Renders every section of the copy tab to exact-sheet images and emails them to the proving list (Maud, Rafael, Megan). Takes a couple of minutes. Manual send — bypasses the fill-complete guard (the copy tab is kept current by the mini; that guard protects the automated scheduled run).",
                "module": "automations.org_sales_board.screenshot_email",
                "args_fn": lambda: ["--force"],
            },
        ],
    },
    {
        "id": "brand-health-audit",
        # Non-breaking spaces keep "(12 CST Daily)" together so the cadence
        # wraps as one clean unit onto line 2 of the strip pill (same trick as
        # rc-autoread's "(Q 10 Min)").
        "name": "Brand Health Audit (12 CST Daily)",
        "creator": "Megan",
        "emoji": "🩺",
        "color": "#6366F1",
        "category": "🩺 Brand Health",
        "description": "Daily reputation + brand scan for Alphalete Marketing — Google reviews, search results, Reddit, website, and public social — posted to the Brand Health Slack channel.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Runs every brand collector for **Alphalete Marketing** (Google "
            "reviews, search results, Reddit mentions, website, reputation "
            "sites, public social) and posts the results in the **Brand "
            "Health Slack Channel**.\n\n"
            "WHEN IT RUNS\n"
            "**Every day at noon (Central)**, via a launchd timer on the Mac "
            "mini (LUCY). The **Run Now** button here triggers an extra pass "
            "any time."
        ),
        "sheet_url": ("https://docs.google.com/spreadsheets/d/"
                      "1zoRQRhvkpu7Vvw4TsC60ufja9XwpUR8hHvV7FyzezMY/edit"),
        "assignees": ["Lucy 1"],
        # Self-running background job (noon launchd) — keep it out of the "due
        # today / not completed" tallies; it doesn't report completion to the Hub.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "12:00 PM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Brand Health scan complete — scorecard written and any new findings alerted to Slack.",
            "message_failed": "❌ Run failed. Check the log above (usually an API key or rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Run the full brand scan for Alphalete Marketing and post any new findings.",
                "module": "automations.brand_audit.run",
                "args_fn": lambda: ["--company", "Alphalete Marketing"],
            },
        ],
    },
    {
        "id": "rc-autoread",
        # The name uses non-breaking spaces ( ) inside "RingCentral Auto-Read"
        # and "(Q 10 Min)" so the cadence wraps as one clean unit onto line 2 of
        # the This Week strip pill instead of breaking mid-phrase.
        "name": "RingCentral Auto-Read (Q 10 Min)",
        "creator": "Dylan",
        "emoji": "📲",
        "color": "#F59E0B",
        "category": "📲 Ops",
        "description": "Marks RingCentral SMS conversations read once they hit a known wrap-up message (installs, DirecTV/cell hand-offs, fiber reminders), leaving customer-reply threads unread.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Scans the RingCentral extension for **unread SMS** and marks a "
            "conversation read once it has reached a known **wrap-up** "
            "message. Threads where the **customer replied after** the "
            "wrap-up are left unread so a human still sees them.\n\n"
            "WHEN IT RUNS\n"
            "**Every ~10 minutes, 7 AM–midnight Central**, via a launchd "
            "timer on the Mac mini (LUCY). The **Run "
            "Now** button here triggers an extra pass any time.\n\n"
            "IF A THREAD ISN'T CLEARING\n"
            "Its wrap-up wording probably isn't in the phrase list — add the "
            "phrase to WRAP_UP_PHRASES in automations/rc_autoread/run.py."
        ),
        # No Google Sheet — RingCentral API only.
        "assignees": ["Lucy 1"],
        # Runs on its own 10-min launchd timer — hide the DUE-TODAY + schedule
        # pills on the report page (cadence is in the breakdown).
        "hide_schedule": True,
        # Self-running background job: never reports a per-day completion to the
        # Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "7:00 AM",
            "estimated_minutes": 1,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Auto-read pass complete — wrapped-up threads marked read, customer-reply threads left unread.",
            "message_failed": "❌ Run failed. Check the log above (usually a RingCentral auth/token or rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Scan the extension and mark wrapped-up threads read.",
                "module": "automations.rc_autoread.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "resume-pushing",
        # Non-breaking spaces keep "Resume Pushing" and "(Q 10 Min)" together
        # so the cadence wraps as one clean unit onto line 2 of the This Week
        # strip pill (same trick as rc-autoread's "(Q 10 Min)").
        "name": "Resume Pushing (Q 10 Min)",
        "creator": "Carlos",
        "emoji": "📄",
        "color": "#F59E0B",
        "category": "📲 Ops",
        "description": "Extracts new applicant resumes in Carlos's ApplicantStream office (11580) and sends the valid ones to the AI call list — the unattended, scheduled version of Carlos's uploaded resume-pusher.",
        "breakdown": (
            "WHAT IT DOES\n"
            "For **Carlos's office (11580)** in ApplicantStream: opens the "
            "**Batch Process of Emails** page, runs **Auto-Extract** (pulls "
            "name / phone / email off each applicant's resume), **selects "
            "everyone**, and clicks **Send to AI**. Only applicants with a "
            "**valid, unique phone** actually go to the AI call list — the "
            "rest are skipped and flagged (no phone / duplicate), not sent.\n\n"
            "WHEN IT RUNS\n"
            "**Every ~10 minutes, 8 AM–10 PM Central, Sun + Mon–Fri** (not "
            "Saturday).\n\n"
            "HOW IT RUNS\n"
            "On Lucy 2 (Carlos' Neo Laptop)."
        ),
        # No Google Sheet — ApplicantStream action bot only.
        "assignees": ["Lucy 2"],
        # Needs Carlos's AppStream session, which only exists on Lucy 2 — so a Hub
        # "play" from ANY machine routes the run to Lucy 2 via the mini-control
        # queue (run_rerun_id = the schedule_config id `rerun` resolves there).
        "run_machine": "Lucy 2",
        "run_rerun_id": "resume_pushing",
        # Runs on its own 8am launchd timer on Lucy 2 — hide the DUE-TODAY +
        # schedule pills on the report page (cadence is in the breakdown).
        "hide_schedule": True,
        # Self-running background job: never reports a per-day completion to the
        # Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "8:00 AM",
            "estimated_minutes": 5,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Resume Pushing complete — resumes extracted and valid applicants sent to the AI call list.",
            "message_failed": "❌ Run failed. Check the log above (usually an expired AppStream session or office 11580 not reachable), then run again.",
        },
        "actions": [
            {
                "label": "Run",
                "icon": "▶",
                "primary": True,
                "help": "Runs a full pass now: Auto-Extract, then send valid applicants to the AI call list. IRREVERSIBLE (only applicants with a valid, unique phone are sent).",
                "module": "automations.resume_pushing.run",
                "args_fn": lambda: [],
            },
        ],
    },
    {
        "id": "social-media-posting",
        # Non-breaking spaces keep "(12 + 4 CST Daily)" together so the cadence
        # wraps as one clean unit onto line 2 of the strip pill (same trick as
        # rc-autoread's "(Q 10 Min)" and the Brand Health card).
        "name": "Alphalete social media posting (12 + 4 CST Daily)",
        "creator": "Megan",
        "emoji": "📸",
        "color": "#EC4899",
        "category": "📸 Social",
        "description": "Turns photos reps drop in #alphaletesocialmedia into brand-safe, captioned social posts — screens the photo, auto-edits it, drafts a caption, collects ✅/❌ approvals, then schedules the approved post.",
        "breakdown": (
            "WHAT IT DOES\n"
            "Watches the **#alphaletesocialmedia** Slack channel. When a rep "
            "drops a photo, Lucy: (1) **brand-safety screens** it (flags "
            "alcohol / profanity / anything unprofessional for approver "
            "sign-off), (2) **auto-edits** the photo (enhance + crop), (3) "
            "drafts a **caption** in our voice, (4) collects the approvers' "
            "**:white_check_mark: / :x:** reactions on the photo and the "
            "caption, and (5) once both are approved, **schedules the post** "
            "(Zoho).\n\n"
            "WHEN IT RUNS\n"
            "**Twice a day — noon and 4 PM (Central)** — via a launchd timer on "
            "the Mac mini (LUCY). The **Run Now** button here triggers an extra "
            "pass any time.\n\n"
            "HOW FAST A PHOTO MOVES\n"
            "The approval flow is human-in-the-loop, so a submission advances "
            "**one approval round-trip per run**: one run **proposes** the "
            "photo + caption, people react ✅/❌, and the **next run collects** "
            "those reactions and schedules. Two runs a day (noon + 4 PM) means "
            "~2 round-trips daily, so a photo reaches *scheduled* roughly "
            "**twice as fast** as a once-a-day cadence. Use **Run Now** to push "
            "it through immediately once people have reacted.\n\n"
            "NO DOUBLE-POSTING\n"
            "Each submission is tracked by its Slack timestamp and handled "
            "once; a lock stops the two daily runs (or a manual **Run Now**) "
            "from colliding on the same photo."
        ),
        # No Google Sheet — Slack + Anthropic + Zoho APIs only.
        "assignees": ["Lucy 1"],
        # Runs on its own launchd timer (noon + 4 PM) — hide the DUE-TODAY +
        # schedule pills on the report page (cadence is in the breakdown).
        "hide_schedule": True,
        # Self-running background job: never reports a per-day completion to the
        # Hub, so keep it out of the "due today / not completed" tallies.
        "self_scheduled": True,
        "schedule": {
            "frequency": "daily",
            "time": "12:00 PM",
            "estimated_minutes": 3,
        },
        "checklist": [],
        "post_run": {
            "message_success": "✅ Scan complete — new photos screened + proposed, ready approvals scheduled. (Approvals advance one round-trip per run; use Run Now to advance faster.)",
            "message_failed": "❌ Run failed. Check the log above (usually a Slack or Anthropic API / rate-limit issue), then run again.",
        },
        "actions": [
            {
                "label": "Run Now",
                "icon": "▶",
                "primary": True,
                "help": "Do an extra pass now — screen + propose new photos and schedule any that are fully approved.",
                "module": "automations.brand_audit.social_inbox",
                "args_fn": lambda: [],
            },
        ],
    },
]

# Merge in user-uploaded reports (saved by the Wire-Up dialog)
# Uploaded automations come from two places: the shared Google Sheet library
# (anyone's upload, visible to everyone instantly — preferred) and the legacy
# local uploaded_reports.json (older Git-based reports, e.g. Order Log). Merge
# them, with the shared store winning on an id collision.
try:
    _shared_uploaded = _read_shared_library()
except Exception:
    _shared_uploaded = []   # fail open — Hub still loads off legacy reports
_shared_ids = {r.get("id") for r in _shared_uploaded}
AUTOMATED_REPORTS.extend(_shared_uploaded)
AUTOMATED_REPORTS.extend(r for r in _load_uploaded_reports_raw()
                         if r.get("id") not in _shared_ids)


def _load_library_overrides() -> dict[str, list[str]]:
    """Manual library assignments saved from the Library UI."""
    if not LIBRARY_ASSIGNMENTS_FILE.exists():
        return {}
    try:
        data = json.loads(LIBRARY_ASSIGNMENTS_FILE.read_text())
        return {str(k): list(v) for k, v in data.items() if isinstance(v, list)}
    except Exception:
        return {}


def _set_library_assignment(report_id: str, assignee: str) -> bool:
    """Persist a library assignment override and return success."""
    overrides = _load_library_overrides()
    if assignee:
        overrides[str(report_id)] = [assignee]
    else:
        overrides.pop(str(report_id), None)
    try:
        LIBRARY_ASSIGNMENTS_FILE.write_text(json.dumps(overrides, indent=2))
    except Exception:
        return False
    # Reflect immediately in the in-memory list so the next rerun shows
    # the move from Unassigned to the assignee's section.
    for r in AUTOMATED_REPORTS:
        if str(r.get("id")) == str(report_id):
            r["assignees"] = list(overrides.get(str(report_id), [])) or []
            break
    return True


# Apply any persisted overrides on top of the merged list.
_library_overrides = _load_library_overrides()
for _r in AUTOMATED_REPORTS:
    if str(_r.get("id")) in _library_overrides:
        _r["assignees"] = list(_library_overrides[str(_r["id"])])

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _spawn_background_run(cmd: list[str], report_id: str, report_name: str,
                          env_overrides: dict | None = None) -> None:
    """Start a report run as a DETACHED background process. Its output is
    redirected straight to the run's log file, and the run is registered in
    active_runs.json — so the auto-refreshing active-run panel shows it and
    the dashboard never blocks waiting for the run to finish.

    Completion is picked up by _read_active_runs(): once the PID exits, that
    run is treated as a finished orphan — its status is read off the log tail
    and the post-run state is saved.

    `env_overrides` (optional): extra env vars to pass to the subprocess on
    top of the inherited environment. Used by captainship-scoped reports
    (e.g. Carlos's Focus Report sets CAPTAINSHIP=Carlos to switch the
    shared recruiting_report module to Carlos's sheet/mapping/template)."""
    ACTIVE_RUNS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = ACTIVE_RUNS_LOG_DIR / f"{report_id}.log"
    log_handle = log_file.open("w")
    # Every manual Hub "play" sets HUB_MANUAL_RUN=1. A report with a machine-local
    # safety gate (e.g. "was the upstream fill fresh on THIS box?") must bypass it
    # when this is set, so the play button ALWAYS runs, from any machine (Megan
    # 2026-07-03 — that's the point of the Hub). The automated day-orchestrator
    # does NOT go through here, so its gates still apply to the unattended run.
    import os as _os
    env = {**_os.environ, "HUB_MANUAL_RUN": "1"}
    if env_overrides:
        env.update(env_overrides)
    # Windows: spawn the report in its OWN process group so a child crash
    # (or any CTRL_C / CTRL_BREAK Windows generates for the console) does
    # NOT propagate back to the Hub's streamlit process. Without this,
    # the subprocess shares the .bat's console group — when a report dies
    # mid-run Windows fires a console event group-wide, Streamlit catches
    # it, prints 'Stopping...', and the whole Hub goes down (Eve, 2026-05-22).
    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(WORKSPACE),
            stdout=log_handle, stderr=subprocess.STDOUT,
            # No stdin — guarantees scripts checking `sys.stdin.isatty()` see
            # non-interactive and fall back to skip/fail instead of prompting
            # (which would hang forever; the Hub has no keyboard to type into).
            stdin=subprocess.DEVNULL,
            env=env,
            **popen_kwargs,
        )
    finally:
        # The child keeps its own dup of the fd; the parent's copy isn't needed.
        log_handle.close()
    _record_active_run(report_id, report_name,
                       st.session_state.get("user", "unknown"),
                       log_file, proc.pid, command=" ".join(cmd))


def _check_chrome_running() -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("localhost", 9222))
        s.close()
        return True
    except OSError:
        return False


@st.cache_data(ttl=300, show_spinner=False)
def _git_health() -> dict:
    """'Are you on the latest code?' status for the sidebar badge. Compares the
    local HEAD to the cached origin/main ref (the launcher fetches it on every
    startup), so this needs NO network call — fast, cached 5 min. Surfacing this
    would have caught Eve running week-old code on the wrong branch for hours
    (2026-05-25). Returns {icon,label,detail,ok}; empty label = not a git repo."""
    import subprocess

    def _git(*args) -> str:
        try:
            return subprocess.run(["git", *args], cwd=str(WORKSPACE),
                                  capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        except Exception:
            return ""

    head = _git("rev-parse", "--short", "HEAD")
    if not head:
        return {"icon": "", "label": "", "detail": "", "ok": True}
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    local = _git("rev-parse", "HEAD")
    remote = _git("rev-parse", "origin/main")
    when = _git("log", "-1", "--format=%cr")
    if remote and local != remote:
        behind = _git("rev-list", "--count", "HEAD..origin/main")
        if behind and behind != "0":
            return {"icon": "⚠️", "label": f"{behind} update(s) behind",
                    "detail": f"on '{branch}' @ {head} — fully quit + relaunch to update",
                    "ok": False}
        return {"icon": "⚠️", "label": "not on latest main",
                "detail": f"on '{branch}' @ {head}", "ok": False}
    return {"icon": "✅", "label": "On latest",
            "detail": f"{head} · updated {when}", "ok": True}


# Sites the debug Chrome opens as login-ready tabs on launch. Scraping
# reports attach to these via CDP after the user logs in once. Add more
# here as new scraped sources come online.
DEBUG_CHROME_STARTUP_TABS = [
    "https://applicantstream.com",
    "https://v2.ownerville.com",
]


def _launch_chrome() -> tuple[bool, str]:
    """Launch Chrome with the remote-debugging-port for scraping, opening
    a login-ready tab for each site in DEBUG_CHROME_STARTUP_TABS.
    Returns (success, message). Platform-aware: `open -na` on macOS,
    chrome.exe on Windows, `google-chrome` on Linux."""
    import os
    import platform
    user_dir = os.path.expanduser("~/.config/recruiting-report/chrome-attach")
    args = [
        f"--remote-debugging-port=9222",
        f"--user-data-dir={user_dir}",
    ]
    # Trailing positional URLs open as tabs.
    tabs = list(DEBUG_CHROME_STARTUP_TABS)
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", "-na", "Google Chrome", "--args", *args, *tabs])
        elif system == "Windows":
            # Try the standard install locations + PATH; first one that exists wins.
            candidates = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            ]
            chrome_exe = next((c for c in candidates if os.path.exists(c)), "chrome.exe")
            subprocess.Popen([chrome_exe, *args, *tabs])
        else:
            # Linux + everything else
            subprocess.Popen(["google-chrome", *args, *tabs])
        return True, "Chrome is launching with login tabs ready."
    except FileNotFoundError as e:
        return False, f"Couldn't find Chrome. Install Google Chrome, then retry. ({e})"
    except Exception as e:
        return False, f"Couldn't launch Chrome: {e}"


def _on_chrome_launch_click(ck_key: str, msg_key: str):
    """Callback: launch Chrome and auto-check the related checklist item."""
    ok, msg = _launch_chrome()
    st.session_state[msg_key] = (ok, msg)
    if ok:
        st.session_state[ck_key] = True


def _on_link_open_click(url: str, ck_key: str):
    """Callback: open URL in browser and auto-check the related checklist item."""
    import webbrowser
    webbrowser.open(url)
    st.session_state[ck_key] = True


def _list_recent_logs(n: int = 6) -> list[Path]:
    if not LOG_DIR.exists():
        return []
    return sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:n]


def _recent_run_logs(n: int = 8) -> list[dict]:
    """The most-recently-run reports' logs. Each run writes (truncating) to
    active/<report_id>.log, so that file persists after the run finishes — it's
    exactly the log the Hub streamed live, just no longer in the active panel.
    Newest first; report name resolved from AUTOMATED_REPORTS. Lets a finished
    run's log be viewed on the Hub instead of digging it out of the terminal
    (Eve 2026-06-01)."""
    if not ACTIVE_RUNS_LOG_DIR.exists():
        return []
    try:
        id_to_name = {r["id"]: r["name"] for r in AUTOMATED_REPORTS}
    except Exception:
        id_to_name = {}
    out = []
    for p in sorted(ACTIVE_RUNS_LOG_DIR.glob("*.log"),
                    key=lambda p: p.stat().st_mtime, reverse=True)[:n]:
        out.append({
            "report_id": p.stem,
            "name": id_to_name.get(p.stem, p.stem),
            "path": p,
            "mtime": dt.datetime.fromtimestamp(p.stat().st_mtime),
        })
    return out


def _is_due_today(report: dict, today: dt.date) -> bool:
    return _was_due_on(report, today)


def _next_due(report: dict, today: dt.date):
    sched = report.get("schedule")
    if not sched:
        return None
    if sched.get("frequency") == "monthly":
        dom = sched.get("day_of_month")
        if not dom:
            return None
        # Next occurrence of dom (this month if in future, else next month)
        try:
            this_month = today.replace(day=dom)
        except ValueError:
            this_month = None
        if this_month and this_month > today:
            return this_month
        # Next month
        if today.month == 12:
            next_year, next_month = today.year + 1, 1
        else:
            next_year, next_month = today.year, today.month + 1
        try:
            return dt.date(next_year, next_month, dom)
        except ValueError:
            return None
    if sched.get("frequency") == "daily":
        wd = sched.get("weekdays")
        if not wd:
            return today + dt.timedelta(days=1)
        # Daily-but-weekday-restricted: next allowed weekday.
        deltas = [((d - today.weekday()) % 7) or 7 for d in wd]
        return today + dt.timedelta(days=min(deltas))
    weekdays = sched.get("weekdays", [])
    if not weekdays:
        return None
    deltas = [((wd - today.weekday()) % 7) or 7 for wd in weekdays]
    return today + dt.timedelta(days=min(deltas))


def _was_due_on(report: dict, day: dt.date) -> bool:
    """Was this report scheduled to run on `day`?"""
    sched = report.get("schedule")
    if not sched:
        return False
    if sched.get("frequency") == "monthly":
        return day.day == sched.get("day_of_month")
    if sched.get("frequency") == "daily":
        # A daily report may restrict to certain weekdays (e.g. Daily
        # Recruiter Retention runs Mon–Fri only). Honor the list if present;
        # no list = every day.
        wd = sched.get("weekdays")
        return day.weekday() in wd if wd else True
    return day.weekday() in sched.get("weekdays", [])


# Cache the orchestrator config once per process (registry is lightweight; the
# app reloads on restart if schedule_config changes).
_SCHED_REGISTRY_CACHE: dict = {}


def _report_time_minutes(report: dict) -> int:
    """Minutes-since-midnight of a report's scheduled run time (schedule.time,
    e.g. '8:00 AM' or '12:00 PM CST'), for ordering the Time Set Reports section
    earliest-first. Missing / unparseable → sorts last."""
    t = ((report.get("schedule") or {}).get("time") or "")
    t = t.replace("CST", "").replace("cst", "").strip()
    for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            parsed = dt.datetime.strptime(t, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return 10_000


def _sched_sorted(reports: list[dict], day: dt.date) -> list[dict]:
    """Order Hub cards to match the day-orchestrator's ACTUAL run sequence for
    `day` (registry.run_order — flow_rank -> priority -> id), so the schedule
    view lists reports top-to-bottom in the order they'll run. Cards map to a
    scheduler report primarily by report ID (the canonical orchestrator
    report_id -> Hub card id map in hub_publish._HUB_CARD), falling back to the
    action module. ID-matching is what makes shared-library / uploaded reports
    (whose module path is 'automations.uploaded._shared.<id>', never the
    scheduler's real module) land in their true run slot instead of getting
    dumped to the bottom. Cards NOT on the scheduler keep their relative order,
    placed after the scheduled ones. Best-effort — any failure falls back to
    the original list order."""
    try:
        cached = _SCHED_REGISTRY_CACHE.get("v")
        if cached is None:
            from automations.day_orchestrator import registry as _reg
            from automations.day_orchestrator.hub_publish import _HUB_CARD
            cached = (_reg, _reg.load_config(), _HUB_CARD)
            _SCHED_REGISTRY_CACHE["v"] = cached
        _reg, cfg, _hub_card = cached
        ordered_ids = [r.report_id for r in
                       _reg.run_order(_reg.scheduled_today(cfg, day), day)]
        card_rank: dict[str, int] = {}   # Hub card id -> run position
        mod_rank: dict[str, int] = {}    # action module -> run position (fallback)
        for pos, rid in enumerate(ordered_ids):
            cid = _hub_card.get(rid)
            if cid is not None:
                card_rank[cid] = pos
            rep = cfg.reports.get(rid)
            if rep and getattr(rep, "command", None):
                mod_rank[rep.command[0]] = pos

        def _rank(card: dict) -> int:
            cid = str(card.get("id"))
            if cid in card_rank:
                return card_rank[cid]
            for a in card.get("actions", []):
                if a.get("module") in mod_rank:
                    return mod_rank[a["module"]]
            return 10_000  # unscheduled cards sort after, keeping their order

        return sorted(reports, key=_rank)
    except Exception:
        return reports


# --------------------------------------------------------------------------
# Cross-user run coordination via the recruiting Sheet's "Hub Activity" tab.
# Each run start appends a row; run-end updates the same row by RunID. Lets
# every teammate's dashboard see who is running what right now (so they don't
# kick off the same report on top of each other), plus a unified "Last ran by"
# timestamp regardless of which machine the run happened on.
# --------------------------------------------------------------------------
HUB_ACTIVITY_TAB = "Hub Activity"
# Lives on the Hub's backend workbook (the "Automation Backlog" intake Sheet),
# not on any individual report's deliverable sheet — see INTAKE_SPREADSHEET_ID.
HUB_ACTIVITY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
HUB_ACTIVITY_HEADERS = [
    "RunID", "Started At", "Report ID", "Report Name",
    "User", "Machine", "PID", "Status", "Ended At",
]
# Rows older than this with no end_ts are treated as stale (the originating
# machine probably crashed mid-run); they're hidden from the active list and
# can be ignored for lock purposes.
HUB_STALE_AFTER = dt.timedelta(hours=2)


def _hub_activity_ws():
    import gspread as _gs
    sh = _fill.open_by_key(HUB_ACTIVITY_SHEET_ID)
    try:
        return sh.worksheet(HUB_ACTIVITY_TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=HUB_ACTIVITY_TAB, rows=2000,
                              cols=len(HUB_ACTIVITY_HEADERS))
        ws.update([HUB_ACTIVITY_HEADERS],
                  f"A1:{_col_a1(len(HUB_ACTIVITY_HEADERS))}1")
        return ws


@st.cache_data(ttl=10)
def _hub_activity_rows() -> list[dict]:
    """Cached read of the Hub Activity tab (10s TTL = how fast we see other
    users' state changes)."""
    try:
        return _hub_activity_ws().get_all_records()
    except Exception:
        return []


HUB_SYNC_ERROR_LOG = LOG_DIR / "hub_activity_sync_errors.log"


def _log_hub_sync_error(op: str, ex: BaseException) -> None:
    """Append a sync failure to a local file so silent Hub-Activity
    breakage (auth, permissions, network) becomes visible. The Hub
    surfaces the most recent error in its status strip when this file
    exists + has recent entries."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with HUB_SYNC_ERROR_LOG.open("a") as f:
            f.write(json.dumps({
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "op": op,
                "error": f"{type(ex).__name__}: {str(ex)[:200]}",
            }) + "\n")
    except Exception:
        pass


def _hub_log_run_start(report_id: str, report_name: str, user: str, pid: int) -> str:
    """Append a 'started' row. Returns the RunID — store it locally so the
    matching run-end can find this row to update."""
    import socket, uuid
    run_id = uuid.uuid4().hex[:12]
    machine = socket.gethostname()
    try:
        _hub_activity_ws().append_row([
            run_id,
            dt.datetime.now().isoformat(timespec="seconds"),
            report_id, report_name, user, machine, str(pid or ""),
            "started", "",
        ])
        _hub_activity_rows.clear()
    except Exception as ex:
        # Sheet write failed — local active_runs.json still works for this
        # user. Don't block the run on a coordination error, but DO log
        # it so we know cross-machine visibility is broken.
        _log_hub_sync_error("hub_log_run_start", ex)
    return run_id


def _hub_log_run_end(run_id: str, status: str) -> None:
    """Update an existing run row with end timestamp + final status."""
    if not run_id:
        return
    try:
        ws = _hub_activity_ws()
        cell = ws.find(str(run_id))
        if not cell:
            return
        # Status is column 8, Ended At is column 9. Write the timestamp RAW
        # so Sheets stores the literal ISO string instead of auto-parsing it
        # into its own date format (which breaks fromisoformat on read; see
        # _parse_hub_ts).
        ws.update_cell(cell.row, 8, status)
        ws.update(
            [[dt.datetime.now().isoformat(timespec="seconds")]],
            f"I{cell.row}", value_input_option="RAW")
        _hub_activity_rows.clear()
    except Exception as ex:
        _log_hub_sync_error("hub_log_run_end", ex)


def _parse_hub_ts(raw) -> dt.datetime | None:
    """Parse a Hub Activity timestamp tolerantly. We write ISO 8601, but
    Google Sheets auto-parses the cell and re-renders it WITHOUT the 'T' and
    without a zero-padded hour (e.g. '2026-05-31 9:55:19'), which
    dt.fromisoformat rejects. That silently dropped finished rows from the
    cross-machine 'ran today' view — a successful run on a teammate's Mac
    never showed done (Eve's 9 Daily Metrics, 2026-05-31). Accept both."""
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _hub_active_runs() -> list[dict]:
    """Return remote-active rows shaped like local active_runs entries."""
    cutoff = dt.datetime.now() - HUB_STALE_AFTER
    out = []
    for r in _hub_activity_rows():
        if str(r.get("Status", "")).lower() != "started":
            continue
        if r.get("Ended At"):
            continue
        started = _parse_hub_ts(r.get("Started At"))
        if started is None:
            continue
        if started < cutoff:
            continue
        out.append({
            "report_id": str(r.get("Report ID", "")),
            "report_name": str(r.get("Report Name", "")),
            "user": str(r.get("User", "")),
            "machine": str(r.get("Machine", "")),
            "pid": str(r.get("PID", "")),
            "started_at": str(r.get("Started At", "")),
            "hub_run_id": str(r.get("RunID", "")),
            "remote": True,
        })
    return out


def _hub_recent_runs(days: int = 14) -> list[dict]:
    """Return finished hub rows (success/failed/stopped) within the window,
    newest first. Used to merge cross-user 'Last ran' timestamps."""
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    out = []
    for r in _hub_activity_rows():
        status = str(r.get("Status", "")).lower()
        if status not in ("success", "failed", "stopped"):
            continue
        ts = _parse_hub_ts(r.get("Ended At") or r.get("Started At"))
        if ts is None or ts < cutoff:
            continue
        out.append({
            "ts": ts.isoformat(timespec="seconds"),
            "_dt": ts,
            "report_id": str(r.get("Report ID", "")),
            "report_name": str(r.get("Report Name", "")),
            "user": str(r.get("User", "")) or "someone",
            "status": status,
            "machine": str(r.get("Machine", "")),
        })
    out.sort(key=lambda x: x["_dt"], reverse=True)
    return out


def _log_run(report_id: str, report_name: str, user: str, status: str) -> None:
    """Append a single run record to runs.jsonl."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "report_id": report_id,
        "report_name": report_name,
        "user": user,
        "status": status,  # "success" | "failed"
    }
    with RUNS_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _read_runs(days: int = 7) -> list[dict]:
    """Read runs from the last `days` days, newest first."""
    if not RUNS_LOG.exists():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    out = []
    for line in RUNS_LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = dt.datetime.fromisoformat(e["ts"])
            if ts >= cutoff:
                e["_dt"] = ts
                out.append(e)
        except Exception:
            continue
    out.sort(key=lambda x: x["_dt"], reverse=True)
    return out


def _all_runs_merged(days: int = 14) -> list[dict]:
    """Local runs.jsonl + Hub Activity finished rows, deduped, newest first.
    Lets every dashboard see runs that other teammates kicked off."""
    local = _read_runs(days)
    remote = _hub_recent_runs(days)
    # Dedup: a run that ran on this machine appears in both lists. Match by
    # (report_id, user, second-precision timestamp).
    seen = {(r.get("report_id"), r.get("user"), r["_dt"].replace(microsecond=0))
            for r in local}
    out = list(local)
    for r in remote:
        key = (r.get("report_id"), r.get("user"), r["_dt"].replace(microsecond=0))
        if key in seen:
            continue
        out.append(r)
        seen.add(key)
    out.sort(key=lambda x: x["_dt"], reverse=True)
    return out


def _was_run_successfully_today(report_id: str, today: dt.date | None = None) -> bool:
    """True if a successful run of this report was logged today by anyone."""
    today = today or dt.date.today()
    for r in _all_runs_merged(2):
        if r.get("report_id") == report_id and r.get("status") == "success" and r["_dt"].date() == today:
            return True
    return False


def _week_run_statuses(week_days: list[dt.date]) -> dict:
    """{(report_id, date): latest_status} for the given days, from the shared
    run feed (local + Hub Activity) — powers the This-week grid's per-card
    outcome badges. Latest run wins for a given report+day."""
    wanted = set(week_days)
    latest: dict = {}   # (report_id, date) -> (dt, status)
    for r in _all_runs_merged(days=8):
        when = r.get("_dt")
        if when is None:
            continue
        d = when.date()
        if d not in wanted:
            continue
        rid = r.get("report_id")
        if not rid:
            continue
        key = (rid, d)
        if key not in latest or when > latest[key][0]:
            latest[key] = (when, (r.get("status") or "").lower())
    return {k: v[1] for k, v in latest.items()}


def _latest_run_summary(report_id: str) -> str | None:
    """Return compact text like 'Today · Megan · 1:06 AM', or None.
    Considers runs by any teammate, not just this machine.

    When the most recent run was on a DIFFERENT machine (e.g. Maud's
    Hub ran it but Megan's Hub is reading this), the machine name is
    appended so it's obvious why the local state files don't have any
    matching details."""
    import socket as _socket
    this_machine = _socket.gethostname()
    for r in _all_runs_merged(days=14):
        if r.get("report_id") != report_id:
            continue
        when = r["_dt"]
        today = dt.date.today()
        time_str = when.strftime("%I:%M %p").lstrip("0")
        if when.date() == today:
            day = "Today"
        elif when.date() == today - dt.timedelta(days=1):
            day = "Yesterday"
        else:
            day = f"{when.strftime('%b')} {when.day}"
        user = r.get("user", "someone")
        machine = (r.get("machine") or "").strip()
        # Remote-run suffix — keep terse; full machine name would be noisy
        # so we just show the user's name as the "on whose Mac" hint.
        # (Local runs from runs.jsonl don't carry a machine field, so the
        # absence-of-machine check is the local-vs-remote signal too.)
        if machine and machine != this_machine:
            return f"Last ran {day.lower()} · {user} · {time_str} · on {user}'s Mac"
        return f"Last ran {day.lower()} · {user} · {time_str}"
    return None


# Unambiguous "the run finished but something real went wrong" markers in a run
# log — kept narrow on purpose so expected per-report gaps (e.g. Daily Focus
# skipping no-access ICDs) DON'T false-flag. Catches the silent-partial trap: a
# run that 'succeeds' while a whole phase quietly skipped (Eve's OPT, 2026-05-25).
_PARTIAL_RUN_MARKERS = [
    ("opt phase skipped", "Tableau OPT was skipped"),
    ("download failed", "a Tableau source failed to download"),
    ("fiber pull failed", "the Fiber pull didn't finish"),
    ("targetclosederror", "the browser closed mid-run (sleep/crash?)"),
    ("couldn't sync to latest", "ran on possibly-stale code"),
]


def _run_outcome(report_id: str) -> dict:
    """Classify the last run's outcome, with a cross-machine staleness guard.

    `_run_outcome_raw` reads THIS machine's local log — but when a report runs on
    a teammate's Mac, the local log never updates and can show a failure forever
    (a frozen 'LAST RUN FAILED' next to a green 'DONE TODAY', 2026-06-04). So if
    the local verdict is failed/partial but a NEWER successful run exists in the
    merged cross-machine history, the local log is stale → report healthy."""
    result = _run_outcome_raw(report_id)
    if result.get("status") in ("failed", "partial"):
        try:
            log_path = ACTIVE_RUNS_LOG_DIR / f"{report_id}.log"
            log_mtime = dt.datetime.fromtimestamp(log_path.stat().st_mtime)
            if any(r.get("report_id") == report_id
                   and r.get("status") == "success" and r["_dt"] > log_mtime
                   for r in _all_runs_merged(14)):
                return {"status": "full", "issues": []}
        except Exception:
            pass
    return result


def _skipped_icds(log_text: str) -> list[str]:
    """ICDs/owners the scrape couldn't match in ownerville and auto-skipped.
    Pulled from the "Couldn't find 'X' in ownerville" lines, deduped, in order.
    A run that completes but skips a couple ICDs should SAY SO (Megan
    2026-06-18: "if it's just missing 2 ICDs it should say that, not failed")."""
    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"[Cc]ouldn'?t find '([^']+)' in ownerville", log_text or ""):
        n = m.group(1).strip()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _run_outcome_raw(report_id: str) -> dict:
    """Classify the LAST run of `report_id` from its persisted log:
    {'status': 'full'|'partial'|'failed'|None, 'issues': [...]}. None = no log.
    Powers the card's last-run badge — so a run that quietly skipped a phase
    reads as 'partial', not a green 'success'.

    Trust the SAVED status (set from the script's exit code at run-end) as the
    source of truth — only re-scan the log if the save says success but the
    log contains an unambiguous partial-run marker. This stops transient
    'TargetClosedError' / 'traceback' lines in a recovered-and-finished run
    from flipping a clean 'success' into a red 'LAST RUN FAILED' (Eve flagged
    this 2026-05-27 on ATT Focus Report + Frontier OPT)."""
    try:
        text = (ACTIVE_RUNS_LOG_DIR / f"{report_id}.log").read_text(errors="replace")
    except Exception:
        return {"status": None, "issues": []}
    low = text.lower()
    saved_status = (_load_all_run_state().get(report_id, {}).get("status") or "").lower()

    # If exit code → success, only down-grade to 'partial' on the narrow,
    # unambiguous markers; ignore generic 'traceback'/'targetclosederror'
    # (those routinely appear in successful runs that retried + recovered).
    if saved_status == "success":
        # Only trust markers that explicitly say a whole phase was SKIPPED
        # — those are silent-partials worth surfacing.
        skip_markers = [(m, msg) for m, msg in _PARTIAL_RUN_MARKERS
                        if "skipped" in m or "failed" in m or "sync to latest" in m]
        issues = [msg for marker, msg in skip_markers if marker in low]
        # Surface ICDs the scrape couldn't match in ownerville: a completed run
        # that quietly skipped a couple reps/owners should read "N ICDs skipped",
        # NOT a silent green (and NOT a red failure) — Megan 2026-06-18.
        skipped = _skipped_icds(text)
        if skipped:
            issues.append(f"{len(skipped)} ICD(s) skipped (not found in ownerville): "
                          + ", ".join(skipped))
        if issues:
            return {"status": "partial", "issues": issues, "skipped": skipped}
        return {"status": "full", "issues": []}

    # Saved status is failed/unknown — old behavior (broad log scan).
    issues = [msg for marker, msg in _PARTIAL_RUN_MARKERS if marker in low]
    if issues:
        return {"status": "partial", "issues": issues}
    if "traceback (most recent call last)" in low:
        return {"status": "failed", "issues": ["the run crashed — see the log"]}
    # A phase-watchdog kill ('... TIMED OUT after N min', 'exceeded N min —
    # killed') is a real, incomplete run — never let it read as 'full'.
    if "timed out after" in low or "— killed" in low:
        return {"status": "failed", "issues": ["the run timed out before finishing — click Run Again to resume"]}
    # Trust a saved 'failed' (non-zero exit code) — don't optimistically
    # upgrade it to 'full' just because the log lacks a traceback. The old
    # fall-through to 'full' was masking failed/timed-out runs (Megan 2026-06-07).
    if saved_status == "failed":
        return {"status": "failed", "issues": ["the run did not finish — see the log"]}
    return {"status": "full", "issues": []}


def _ran_today(report_id: str, today: dt.date | None = None) -> tuple[bool, str | None, str | None]:
    """Was this report successfully run TODAY (calendar day) by anyone?
    Returns (yes/no, user, time_str).

    Calendar-day — NOT a rolling 24h window. The old 24h version flagged a
    run from YESTERDAY (e.g. 10am) as "already ran today" the next morning,
    blocking a legitimate fresh run and showing stale numbers (Megan
    2026-06-08, noticed across multiple reports). 'Already ran today' must
    mean ran on today's date."""
    today = today or dt.date.today()
    for r in _all_runs_merged(days=2):
        if (r.get("report_id") == report_id and r.get("status") == "success"
                and r["_dt"].date() == today):
            return True, r.get("user", "someone"), r["_dt"].strftime("%I:%M %p").lstrip("0")
    return False, None, None


def _execute_action(report: dict, action: dict, picked, chrome_ok: bool) -> None:
    """Kick off one action as a background run, then rerun so the live
    run panel takes over. The dashboard never blocks waiting for the run."""
    # Every report now self-logs-in via patchright (ownerville/AppStream/Tableau),
    # so none need the manual debug Chrome — the preflight no longer blocks runs
    # (Megan 2026-05-25, "remove the debug from all reports + update the
    # preflight"). A card can opt back into the Chrome check with
    # "needs_chrome": True if it ever depends on the debug browser again.
    if not chrome_ok and report.get("needs_chrome"):
        st.error("⚠️ Chrome isn't running — launch it from the sidebar first.")
        return
    # Cross-user lock: refuse to start a run if anyone else is already running
    # this report (per the shared Hub Activity tab). The button disable is the
    # primary guard; this is the backstop in case state changed mid-click.
    # Drop the 10s Hub Activity cache first so this check sees the freshest
    # possible state — shrinks the window where two people could both start.
    me = st.session_state.get("user", "")
    _hub_activity_rows.clear()
    for a in _read_active_runs():
        if a.get("report_id") != report["id"]:
            continue
        other = a.get("user") or "someone"
        if other.strip().lower() == me.strip().lower():
            continue  # our own in-flight run — the card already shows it
        st.error(
            f"⛔ **{other}** is already running this report. Wait for them "
            "to finish before starting a new run — running it twice at the "
            "same time would corrupt the Sheet."
        )
        return
    needs_date = action.get("needs_date")
    needs_text = action.get("needs_text")
    if needs_text and needs_date:
        # picked is a tuple (date, text)
        date_val, text_val = picked if isinstance(picked, tuple) else (None, None)
        if not text_val:
            st.error(f"⚠️ Please enter the {action.get('text_label', 'input')} first.")
            return
        args = action["args_fn"](date_val, text_val)
    elif needs_text:
        if not picked:
            st.error(f"⚠️ Please enter the {action.get('text_label', 'input')} first.")
            return
        args = action["args_fn"](picked)
    elif needs_date:
        args = action["args_fn"](picked)
    else:
        args = action["args_fn"]()
    # Machine-bound reports (e.g. resume_pushing needs Carlos's AppStream session,
    # which only exists on Lucy 2) route their run to that machine via the mini-
    # control queue instead of spawning locally — so "play" always lands on the
    # right machine no matter which machine is serving this Hub.
    run_machine = report.get("run_machine")
    if run_machine:
        from automations.day_orchestrator import mini_control
        try:
            local = mini_control._machine_profile()
        except Exception:
            local = "Lucy 1"
        if local != run_machine:
            rerun_id = report.get("run_rerun_id") or report["id"]
            queued = (f"{rerun_id} " + " ".join(args)).strip()
            try:
                mini_control.enqueue("rerun", queued, by=(me or "Hub"),
                                     machine=run_machine)
                st.success(
                    f"▶ Sent to **{run_machine}** — this report only runs there "
                    f"(Carlos's machine). It will start within ~2 min; track it "
                    "with `lucy status` or check back here shortly."
                )
            except Exception as e:
                st.error(f"Couldn't send the run to {run_machine}: {e}")
            return
    # -u → unbuffered, so the live run panel sees log lines as they happen.
    cmd = [VENV_PY, "-u", "-m", action["module"]] + args
    # Per-report env overrides (e.g. captainship-scoped reports set
    # CAPTAINSHIP=Carlos so the shared module switches to Carlos's sheet).
    env_overrides = action.get("env") or report.get("env")
    try:
        _spawn_background_run(cmd, report["id"], report["name"],
                              env_overrides=env_overrides)
    except Exception as e:
        st.error(f"Couldn't start the run: {e}")
        return
    # The run is now a detached background process. Rerun so the card flips
    # straight to the live, auto-refreshing run panel — nothing blocks, so the
    # page never shows a stale duplicate of itself while the run goes.
    st.rerun()


@st.fragment(run_every=3)
def _active_run_fragment(report_id: str) -> None:
    """Auto-refreshing body of the active-run panel. Re-reads active_runs
    + log file every 3s. When the subprocess finishes, breaks out of the
    fragment by triggering a full app rerun so the post-run callout shows."""
    active_runs = _read_active_runs()
    active = next((a for a in active_runs if a.get("report_id") == report_id), None)
    if not active:
        # Run completed (or was killed) — bounce to a full app rerun so the
        # parent card switches back to its normal state.
        st.rerun(scope="app")
        return

    started_at = active.get("started_at", "")
    runner = active.get("user", "someone")
    log_path = active.get("log_path", "")
    pid = active.get("pid")
    is_remote = bool(active.get("remote"))
    machine = active.get("machine", "")

    elapsed_s = 0
    try:
        start_dt = dt.datetime.fromisoformat(started_at)
        elapsed_s = max(0, int((dt.datetime.now() - start_dt).total_seconds()))
        if elapsed_s < 60:
            elapsed_str = f"{elapsed_s}s"
        elif elapsed_s < 3600:
            elapsed_str = f"{elapsed_s // 60}m {elapsed_s % 60}s"
        else:
            elapsed_str = f"{elapsed_s // 3600}h {(elapsed_s % 3600) // 60}m"
    except Exception:
        elapsed_str = "—"

    is_orphan = bool(active.get("orphan"))
    elapsed_html = (
        f"<span>running for <b>{elapsed_str}</b></span>"
        if elapsed_str != "—"
        else "<span style='opacity:0.85'>just detected — elapsed time unknown</span>"
    )
    if is_remote:
        machine_part = f" on <b>{machine}</b>" if machine else ""
        started_html = (
            f"Started by <b>{runner}</b>{machine_part} · {elapsed_html} "
            "<span style='opacity:0.85'>(running on another teammate's Mac)</span>"
        )
    elif is_orphan:
        started_html = (
            f"PID <b>{pid}</b> · running as <b>{runner}</b> · {elapsed_html} "
            "<span style='opacity:0.85'>(detected by process scan)</span>"
        )
    else:
        started_html = f"Started by <b>{runner}</b> · {elapsed_html}"
    st.markdown(
        "<style>"
        "@keyframes runpulse { 0%,100% { opacity:1 } 50% { opacity:0.55 } }"
        ".runpulse-dot { display:inline-block; width:12px; height:12px; "
        " border-radius:50%; background:#fff; margin-right:10px; "
        " vertical-align:middle; animation: runpulse 1.1s ease-in-out infinite }"
        "</style>"
        "<div style='background:linear-gradient(135deg, #D8261C 0%, #B11B12 100%); "
        "border:0; border-radius:10px; padding:1rem 1.2rem; margin:0.4rem 0 0.8rem; "
        "color:#fff; box-shadow:0 2px 8px rgba(201,32,32,0.25);'>"
        "<div style='font-weight:800; font-size:1.3rem; letter-spacing:0.02em;'>"
        "<span class='runpulse-dot'></span>RUNNING NOW</div>"
        f"<div style='margin-top:0.35rem; font-size:1rem;'>{started_html}</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    if is_remote:
        # Log file lives on the runner's machine — can't read it from here.
        # No Stop button either, since os.kill won't reach a remote PID.
        st.info(
            f"📋 Live log is only visible on **{runner}'s** Mac. "
            "This card auto-updates the moment they finish — you'll see the "
            "post-run summary appear here. If they're stuck, ping them."
        )
        st.caption("Auto-refreshes every 3s.")
        return

    # Show how fresh the log file is so it's obvious whether the subprocess
    # is actively writing or has gone quiet.
    log_freshness = ""
    # A scan-detected run (no Hub-recorded start) reads its log_path from
    # the report's default log file, which may belong to a previous Hub
    # run. If that file's mtime predates this process, it's not this run's
    # log — hide it instead of showing stale content + a misleading
    # "stuck" warning.
    log_belongs_to_this_run = True
    if is_orphan and not started_at and log_path:
        try:
            mtime = Path(log_path).stat().st_mtime
            if dt.datetime.now().timestamp() - mtime > 30:
                log_belongs_to_this_run = False
        except Exception:
            log_belongs_to_this_run = False

    if log_path and log_belongs_to_this_run:
        try:
            mtime = Path(log_path).stat().st_mtime
            age_s = max(0, int(dt.datetime.now().timestamp() - mtime))
            if age_s < 3:
                log_freshness = "🟢 log updating live"
            elif age_s < 10:
                log_freshness = f"🟡 log last updated {age_s}s ago"
            else:
                log_freshness = f"🔴 log hasn't updated in {age_s}s — subprocess may be stuck or finished"
        except Exception:
            pass

    tail = _tail_log(log_path) if (log_path and log_belongs_to_this_run) else ""
    if not log_belongs_to_this_run:
        st.info(
            "📋 This run was launched outside the Hub (from a terminal) — "
            "the live log isn't visible here. The card will refresh with "
            "the post-run summary once it finishes."
        )

    # Progress bar. The scraper prints a "[i/N]" marker per office; with
    # elapsed time we extrapolate how much is left. Reports that print no
    # such marker fall back to a time estimate (if they declare one).
    import re as _re
    _markers = _re.findall(r"\[(\d+)/(\d+)\]", tail or "")
    if _markers:
        _i, _n = int(_markers[-1][0]), max(int(_markers[-1][1]), 1)
        _i = min(_i, _n)
        _eta = ""
        try:
            if 0 < _i < _n and elapsed_s:
                _rem = int(elapsed_s * (_n - _i) / _i)
                _eta = (f" · ~{_rem // 60}m {_rem % 60}s left" if _rem >= 60
                        else f" · ~{_rem}s left")
        except Exception:
            _eta = ""
        st.progress(min(_i / _n, 0.97), text=f"Office {_i} of {_n}{_eta}")
    else:
        _est = _estimated_minutes_for(report_id)
        if _est and elapsed_s:
            _total = _est * 60
            _rem = max(0, _total - elapsed_s)
            st.progress(min(elapsed_s / _total, 0.95),
                        text=f"~{_rem // 60}m left (estimated)")

    if tail:
        st.code(tail, language="log")
    else:
        st.caption("No log output yet — the subprocess may have just started.")
    if log_freshness:
        st.caption(log_freshness + " · auto-refreshes every 3s")
    else:
        st.caption("Auto-refreshes every 3s.")

    cols = st.columns([1, 3])
    stop_clicked = cols[0].button(
        "⛔ Stop",
        key=f"stop_active_{report_id}",
        type="secondary",
        use_container_width=True,
    )
    cols[1].caption(
        f"PID {pid}. Stop kills the report immediately. "
        f"Data already written to the Sheet is not undone."
    )

    if stop_clicked:
        ok, msg = _kill_active_run(
            report_id, user=st.session_state.get("user"),
        )
        (st.warning if ok else st.info)(msg)
        st.rerun(scope="app")


def _render_active_run_panel(report: dict, active: dict) -> None:
    """In-progress banner: who started, elapsed time, live log tail, Stop.

    Renders inside an already-open report card container. Returning from
    here is the caller's responsibility (skip the rest of the card while
    a run is in flight). The Stop button kills the subprocess and reruns
    the page so the normal flow comes back. The body is wrapped in a
    Streamlit fragment so it auto-refreshes every 3s without a manual
    refresh button — and re-reads active_runs to know when to bounce out."""
    _active_run_fragment(report["id"])


# ---- Daily Focus: ICD ↔ AppStream office mapping prompt ----
# When a new name appears in col V of the Daily Focus tab, we ask Megan
# (in the dashboard) to confirm which AppStream office it maps to. The
# answer is persisted to output/icd_office_mappings.json so we never ask
# about that name again. all-offices.json (149 known offices) provides
# the candidate list for fuzzy-matching + a manual picker.

@st.cache_data(ttl=60)
def _daily_focus_icds_in_sheet(captainship: str) -> list[str]:
    try:
        from automations.recruiting_report import fill as _f, daily_focus as _df
        sh = _f.open_by_key(_df.DAILY_FOCUS_SPREADSHEET_ID)
        ws = _df.find_captainship_worksheet(sh, captainship)
        if ws is None:
            return []
        col = ws.col_values(_df.ICD_LIST_COLUMN)
        return [v.strip() for v in col if v and v.strip()]
    except Exception:
        return []


def _daily_focus_unmapped(captainship: str) -> list[str]:
    """ICDs in a captainship's sheet with no AppStream office mapping yet.
    The run silently skips these — so a run that left ICDs unmapped is not
    a clean success, and the post-run callout must say so."""
    try:
        from automations.recruiting_report import daily_focus as _df
        return [n for n in _daily_focus_icds_in_sheet(captainship)
                if not _df._is_skipped(n) and not _df._resolve_office_id(n)]
    except Exception:
        return []


@st.cache_data(ttl=600)
def _all_appstream_offices() -> list[dict]:
    try:
        path = WORKSPACE / "automations" / "recruiting_report" / "all-offices.json"
        return list(json.loads(path.read_text()).get("offices", []))
    except Exception:
        return []


def _suggest_office_for_name(name: str) -> dict | None:
    """Score AppStream owners against an ICD name; return the best match
    if the score is meaningful, else None."""
    name_low = name.lower().strip()
    name_words = set(name_low.replace(",", " ").split())
    best, best_score = None, 0
    for o in _all_appstream_offices():
        owner = (o.get("owner") or "").lower()
        if not owner:
            continue
        owner_words = set(owner.replace(",", " ").split())
        overlap = len(name_words & owner_words)
        score = overlap + (5 if name_low in owner or owner in name_low else 0)
        if score > best_score:
            best_score, best = score, o
    return best if best_score >= 1 else None


def _save_icd_mapping(name: str, office_id: str) -> None:
    """Persist an ICD-name → office-id (or SKIP) decision."""
    from automations.recruiting_report import daily_focus as _df
    overrides = _df._load_overrides()
    overrides[name.lower().strip()] = office_id
    _df._save_overrides(overrides)


def _render_daily_focus_mapping_prompt(captainship: str) -> None:
    """If col V has names not yet mapped (and not skipped), render an inline
    confirm panel with fuzzy-match suggestions + manual picker + skip."""
    from automations.recruiting_report import daily_focus as _df
    icds = _daily_focus_icds_in_sheet(captainship)
    if not icds:
        return
    unmapped = [n for n in icds
                if not _df._is_skipped(n) and not _df._resolve_office_id(n)]
    if not unmapped:
        return

    st.markdown(
        "<div style='background:linear-gradient(135deg, #FFF3D6 0%, #FFE4A8 100%); "
        "border:2px solid #C9A85C; border-radius:10px; "
        "padding:14px 18px; margin:6px 0 10px; color:#5C4220;'>"
        f"<div style='font-weight:800; font-size:1.1rem;'>"
        f"👋 {len(unmapped)} new ICD{'s' if len(unmapped)!=1 else ''} need an "
        "AppStream mapping</div>"
        "<div style='margin-top:6px; font-size:0.95rem;'>"
        "Confirm each suggested match below. Anything unmapped will be "
        "skipped on the next run."
        "</div></div>",
        unsafe_allow_html=True,
    )

    offices = _all_appstream_offices()
    sorted_options = sorted(offices, key=lambda o: (o.get("owner") or "").lower())
    option_labels = [
        f"{o['office_id']}  —  {o.get('owner','?')}  ({o.get('company','?')})"
        for o in sorted_options
    ]

    # Enumerate so every widget key carries the row index. Two unmapped tabs
    # can share the same display name; keying on `name` alone collided and the
    # whole 'library' screen died with StreamlitDuplicateElementKey (Maud,
    # 2026-06-06). The index makes each row's keys unique regardless.
    for _i, name in enumerate(unmapped):
        suggestion = _suggest_office_for_name(name)
        with st.container(border=True):
            top_cols = st.columns([3, 6])
            top_cols[0].markdown(f"**{name}**")
            if suggestion:
                top_cols[1].markdown(
                    f"Suggested: **{suggestion.get('owner','?')}** "
                    f"(office **{suggestion['office_id']}**) "
                    f"— *{suggestion.get('company','')}*"
                )
            else:
                top_cols[1].markdown("_No close match in known offices — pick manually below._")

            btn_cols = st.columns([2, 2, 2, 4])
            confirm_disabled = suggestion is None
            if btn_cols[0].button(
                "✅ Confirm match", key=f"map_confirm_{_i}_{name}",
                disabled=confirm_disabled, use_container_width=True,
                type="primary",
            ):
                _save_icd_mapping(name, suggestion["office_id"])
                _daily_focus_icds_in_sheet.clear()
                st.rerun()
            picker_state_key = f"map_picker_open_{_i}_{name}"
            if btn_cols[1].button(
                "🔍 Pick different", key=f"map_pick_{_i}_{name}",
                use_container_width=True,
            ):
                st.session_state[picker_state_key] = not st.session_state.get(picker_state_key, False)
                st.rerun()
            if btn_cols[2].button(
                "🚫 Not an ICD", key=f"map_skip_{_i}_{name}",
                use_container_width=True,
                help="Mark this name as 'not a real ICD' so we never ask again "
                     "(e.g. for header/title rows).",
            ):
                _save_icd_mapping(name, _df.SKIP_SENTINEL)
                _daily_focus_icds_in_sheet.clear()
                st.rerun()

            if st.session_state.get(picker_state_key):
                default_idx = 0
                if suggestion:
                    try:
                        default_idx = next(
                            i for i, o in enumerate(sorted_options)
                            if o["office_id"] == suggestion["office_id"]
                        )
                    except StopIteration:
                        pass
                pick = st.selectbox(
                    "AppStream office",
                    option_labels, index=default_idx,
                    key=f"map_picker_{_i}_{name}",
                    label_visibility="collapsed",
                )
                save_cols = st.columns([1, 4])
                if save_cols[0].button(
                    "💾 Save", key=f"map_save_{_i}_{name}",
                    type="primary", use_container_width=True,
                ):
                    chosen = sorted_options[option_labels.index(pick)]
                    _save_icd_mapping(name, chosen["office_id"])
                    _daily_focus_icds_in_sheet.clear()
                    st.session_state.pop(picker_state_key, None)
                    st.rerun()


# ---- Weekly Recruiting: multi-office tab picker ----
# When a new Sheet tab's name matches MORE than one AppStream office, the run
# can't guess which to pull. The runner picks here, before the run — the pick
# is saved and the next run onboards that tab automatically.

@st.cache_data(ttl=60)
def _recruiting_ambiguous_tabs() -> list:
    """Recruiting Sheet tabs whose name matches >1 AppStream office and that
    the runner hasn't picked an office for yet. 60s cache."""
    try:
        from automations.recruiting_report import fill as _f
        return _f.unresolved_ambiguous_tabs(_f.open_sheet())
    except Exception:
        return []


def _render_recruiting_office_picker() -> None:
    """Ask the runner which AppStream office a multi-office tab should pull
    from, before the run. The pick is remembered; the next run uses it."""
    from automations.recruiting_report import fill as _f
    amb = _recruiting_ambiguous_tabs()
    if not amb:
        return

    st.markdown(
        "<div style='background:linear-gradient(135deg, #FFF3D6 0%, #FFE4A8 100%); "
        "border:2px solid #C9A85C; border-radius:10px; "
        "padding:14px 18px; margin:6px 0 10px; color:#5C4220;'>"
        f"<div style='font-weight:800; font-size:1.1rem;'>"
        f"⚠️ {len(amb)} tab{'s' if len(amb)!=1 else ''} match more than one "
        "AppStream office</div>"
        "<div style='margin-top:6px; font-size:0.95rem;'>"
        "Pick the right office for each, then run — the run pulls it in. "
        "Run without picking and the tab is flagged red, not filled."
        "</div></div>",
        unsafe_allow_html=True,
    )

    for item in amb:
        tab = item["tab"]
        cands = item["candidates"]
        labels = [
            f"{c.get('office_id')}  —  {c.get('company') or c.get('owner', '?')}"
            for c in cands
        ]
        with st.container(border=True):
            st.markdown(f"**{tab}** matches {len(cands)} AppStream offices:")
            pick = st.selectbox(
                f"Which office is {tab}?",
                labels, key=f"recr_amb_pick_{tab}",
                label_visibility="collapsed",
            )
            if st.button(
                f"💾 Save — pull {tab} from this office",
                key=f"recr_amb_save_{tab}", type="primary",
                use_container_width=True,
            ):
                chosen = cands[labels.index(pick)]
                _f.save_office_choice(tab, chosen["office_id"])
                _recruiting_ambiguous_tabs.clear()
                st.success(
                    f"Saved. The next run pulls **{tab}** from office "
                    f"{chosen['office_id']}."
                )
                st.rerun()


@st.fragment(run_every=10)
def _cross_user_pulse(report_id: str) -> None:
    """Tiny invisible fragment that polls cross-user state every 10s. When
    a teammate's run starts (or finishes), it triggers an app-wide rerun so
    the report card reflects the new state — no manual reload needed."""
    sig_key = f"cross_user_sig_{report_id}"
    me = st.session_state.get("user", "")
    others_active_for_this = [
        a for a in _read_active_runs()
        if a.get("report_id") == report_id
        and (a.get("user") or "").strip().lower() != me.strip().lower()
    ]
    # Build a tiny signature of what's relevant; if it changes, rerun the app.
    sig = tuple(sorted(
        (a.get("hub_run_id") or a.get("pid"), a.get("user"))
        for a in others_active_for_this
    ))
    last_sig = st.session_state.get(sig_key)
    if last_sig is not None and sig != last_sig:
        st.session_state[sig_key] = sig
        st.rerun(scope="app")
    elif last_sig is None:
        st.session_state[sig_key] = sig


@st.fragment(run_every=20)
def _this_week_strip(today: dt.date, my_reports: list[dict], user_name: str) -> None:
    """The '📅 This week' 7-day schedule strip, in its own auto-refreshing
    fragment (re-runs every 20s) so the live 'running now' 🔄 badge + the
    per-day outcome pills update on their own — no manual page refresh (the
    badge used to only update when the whole page was reloaded). The
    pill-coloring CSS is injected once by the caller OUTSIDE this fragment and
    persists across fragment reruns. Card clicks call st.rerun(scope="app") so
    navigation escapes the fragment and switches the whole app to the report —
    a bare st.rerun() would only re-run this fragment and never navigate.
    Remote reads (_week_run_statuses → Hub Activity) are cached ttl=10s, so the
    20s cadence never hits the Sheet more than once per 10s."""
    _week_start = today - dt.timedelta(days=today.weekday())    # Monday
    _week_days = [_week_start + dt.timedelta(days=_k) for _k in range(7)]
    _cal_statuses = _week_run_statuses(_week_days)
    # Live "running now": actual subprocesses (active_runs.json + a ps match),
    # so the card shows a pulsing 🔄 for whatever is executing right now.
    try:
        _running_ids = {a.get("report_id") for a in _read_active_runs()}
    except Exception:
        _running_ids = set()

    def _cal_status(_rid: str, _day: dt.date) -> str:
        """Per-card outcome for a day: ok / fail / miss / up(coming)."""
        if _day > today:
            return "up"                       # future — hasn't run
        _s = _cal_statuses.get((_rid, _day))
        if _s == "success":
            return "ok"
        if _s is None:                        # no run recorded
            return "up" if _day == today else "miss"
        if _s in ("running", "started", "in progress", "in-progress"):
            return "up" if _day == today else "fail"   # stuck if it's a past day
        return "fail"                         # any other terminal status

    _cal_cols = st.columns(7)
    for _i, _day in enumerate(_week_days):
        with _cal_cols[_i]:
            _is_today = (_day == today)
            _today_pill = (
                "<span style='background:#C9A85C; color:#2A1F12; "
                "padding:1px 6px; border-radius:999px; font-size:0.65em; "
                "font-weight:800; margin-left:4px; vertical-align:middle'>"
                "TODAY</span>"
                if _is_today else ""
            )
            _header_color = "#8B6914" if _is_today else "#555"
            st.markdown(
                f"<div style='text-align:center; padding:2px 0 6px'>"
                f"<div style='font-weight:700; color:{_header_color}; font-size:0.95em'>"
                f"{_day.strftime('%a')}{_today_pill}</div>"
                f"<div style='font-size:0.78em; color:#777'>{_day.strftime('%b')} {_day.day}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            _due = [r for r in my_reports if _was_due_on(r, _day)]
            # List reports in the order the day-orchestrator will run them
            # (matches the scheduler sequence), then split out Other Offices.
            _due = _sched_sorted(_due, _day)
            if _due:
                # Single-office reports (category "🏢 Other Offices") render
                # UNDER an "Other Offices" divider, below the main-office
                # reports — not mixed into the day's list (Megan 2026-06-30).
                _main = [r for r in _due if r.get("category") not in ("🏢 Other Offices", "📲 Ops")]
                _other = [r for r in _due if r.get("category") == "🏢 Other Offices"]
                _ops = [r for r in _due if r.get("category") == "📲 Ops"]
                # Split the main block into the 4am orchestrator sweep vs reports on
                # their OWN fixed timer (self_scheduled — the same flag that puts the
                # "· HH:MM CST" time on the tile), each under its own divider so the
                # morning batch reads as its own section (Megan 2026-07-09).
                _batch = [r for r in _main if not r.get("self_scheduled")]
                # Time Set reports run on their own clock → order them by that clock
                # (earliest first: 8am steak before the noon ones), Megan 2026-07-09.
                _timed = sorted(
                    [r for r in _main if r.get("self_scheduled")],
                    key=_report_time_minutes,
                )
                _ordered = (
                    (["__MORNING__"] if _batch else []) + _batch
                    + (["__TIMESET__"] if _timed else []) + _timed
                    + (["__OTHER_OFFICES__"] if _other else []) + _other
                    + (["__OPS__"] if _ops else []) + _ops
                )
                for _r in _ordered:
                    if _r == "__MORNING__":
                        st.markdown(
                            "<div style='border-top:3px solid #10B981; "
                            "margin:10px 0 5px; padding-top:6px; "
                            "font-size:0.95em; font-weight:700; color:#10B981; "
                            "letter-spacing:0.05em; text-align:center'>"
                            "☀️ MORNING BATCH</div>",
                            unsafe_allow_html=True,
                        )
                        continue
                    if _r == "__TIMESET__":
                        st.markdown(
                            "<div style='border-top:3px solid #6366F1; "
                            "margin:10px 0 5px; padding-top:6px; "
                            "font-size:0.95em; font-weight:700; color:#6366F1; "
                            "letter-spacing:0.05em; text-align:center'>"
                            "⏰ TIME SET REPORTS</div>",
                            unsafe_allow_html=True,
                        )
                        continue
                    if _r == "__OTHER_OFFICES__":
                        st.markdown(
                            "<div style='border-top:3px solid #DC2626; "
                            "margin:10px 0 5px; padding-top:6px; "
                            "font-size:0.95em; font-weight:700; color:#DC2626; "
                            "letter-spacing:0.05em; text-align:center'>"
                            "🏢 OTHER OFFICES</div>",
                            unsafe_allow_html=True,
                        )
                        continue
                    if _r == "__OPS__":
                        st.markdown(
                            "<div style='border-top:3px solid #F59E0B; "
                            "margin:10px 0 5px; padding-top:6px; "
                            "font-size:0.95em; font-weight:700; color:#F59E0B; "
                            "letter-spacing:0.05em; text-align:center'>"
                            "📲 OPS</div>",
                            unsafe_allow_html=True,
                        )
                        continue
                    # Per-day run outcome → colored pill (green ✅ ran ok,
                    # coral ⚠️ failed/incomplete, gray – scheduled-didn't-run,
                    # plain = upcoming). Status is encoded in the button key
                    # (__calstat_<status>) which the injected CSS colors.
                    _stat = _cal_status(_r["id"], _day)
                    if _day == today and _r["id"] in _running_ids:
                        _stat = "running"          # live subprocess right now
                    _icon = {"ok": "✅ ", "fail": "⚠️ ", "miss": "– ",
                             "running": "🔄 "}.get(_stat, "")
                    _label = f"{_icon}{_r.get('emoji', '📄')} {_r['name']}"
                    # Self-scheduled reports fire on their OWN fixed timer (not the
                    # 4am batch), so show the run time on the tile — otherwise there
                    # is no way to see WHEN it runs. Batch reports omit it (they run
                    # in the morning sweep, no individual time).
                    if _r.get("self_scheduled"):
                        _sched_t = (_r.get("schedule") or {}).get("time")
                        if _sched_t:
                            _label += f" · {_sched_t} CST"
                    _help = {
                        "ok": "Ran OK — open to view",
                        "fail": "Failed / incomplete — open to see why",
                        "miss": "Was scheduled but didn't run — open to run",
                        "up": "Open this report to run it",
                        "running": "Running now — open to watch",
                    }.get(_stat, "Open this report to run it")
                    if st.button(
                        _label,
                        key=f"cal_{user_name}_{_day.strftime('%Y%m%d')}_{_r['id']}__calstat_{_stat}",
                        use_container_width=True,
                        help=_help,
                    ):
                        st.session_state["library_report_id"] = _r["id"]
                        st.session_state["library_came_from"] = ("user", user_name)
                        _set_view("library")
                        st.rerun(scope="app")
            else:
                st.markdown(
                    "<div style='text-align:center; color:#bbb; "
                    "font-size:0.8em; padding:4px 0'>—</div>",
                    unsafe_allow_html=True,
                )


def _render_report_screenshot(report: dict) -> None:
    """Right-column content on a report's Library page: the report's
    screenshot in a fixed-height frame so it lines up with the run card.
    A report can borrow another report's screenshot via `screenshot_from`
    — in that case there's no uploader here (update it on that report)."""
    import base64
    from PIL import Image as _Image
    # Show the result of a just-completed save+sync (stashed before the rerun,
    # so it survives into the run where the new image renders).
    _saved_msg = st.session_state.pop(f"shot_msg_{report['id']}", None)
    if _saved_msg:
        (st.success if _saved_msg[0] else st.warning)(_saved_msg[1])
    _borrowed = report.get("screenshot_from")
    _shot_id = _borrowed or report["id"]
    shot = REPORT_SHOTS_DIR / f"{_shot_id}.png"
    if shot.exists():
        # Fixed-height frame — keeps the screenshot the same height as the
        # run card beside it (instead of towering over, or under, it). The
        # image is scaled to fit inside, so the whole report stays visible.
        _b64 = base64.b64encode(shot.read_bytes()).decode("ascii")
        st.markdown(
            "<div style='height:460px; border-radius:10px; "
            "background:#FFFFFF; display:flex; "
            "align-items:center; justify-content:center; overflow:hidden'>"
            f"<img src='data:image/png;base64,{_b64}' "
            "style='max-width:100%; max-height:100%; object-fit:contain'/>"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        "<div style='border:2px dashed #C9A85C; border-radius:10px; "
        "padding:36px 18px; text-align:center; color:#8B6914; "
        "background:#FFFDF6; font-size:1.05rem'>"
        "📸<br/>No screenshot yet</div>",
        unsafe_allow_html=True,
    )
    if _borrowed:
        st.caption("This report shares another report's screenshot — "
                   "add it on that report's card.")
        return
    with st.expander("📸 Add a screenshot", expanded=True):
        st.caption("Upload an image of the report's tab so people can see "
                   "what it looks like.")
        _up = st.file_uploader(
            "Screenshot", type=["png", "jpg", "jpeg"],
            key=f"shot_up_{report['id']}", label_visibility="collapsed",
        )
        if _up is not None and st.button(
            "💾 Save screenshot", key=f"shot_save_{report['id']}",
            type="primary", use_container_width=True,
        ):
            try:
                REPORT_SHOTS_DIR.mkdir(parents=True, exist_ok=True)
                _img = _Image.open(_up).convert("RGB")
                # Cap the longest side so screenshots committed to the repo stay
                # lean (these accumulate); still ample for the card frame.
                _img.thumbnail((1600, 1600))
                _img.save(shot, "PNG")
            except Exception as e:
                st.error(f"Couldn't save that image: {e}")
            else:
                # Sync through the repo so it lands on every teammate's Hub on
                # their next relaunch (the launcher hard-pulls origin/main).
                _ok, _msg = _git_push_screenshot(
                    f"resources/report-screenshots/{_shot_id}.png", report["name"])
                st.session_state[f"shot_msg_{report['id']}"] = (_ok, _msg)
                st.rerun()


def _render_report_breakdown(report: dict) -> None:
    """Full-width 'how this report works' panel — Alphalete cream/gold
    styling. The breakdown text uses ALL-CAPS section headers; each
    section renders with a styled, icon'd header. **bold** in the body is
    honored; everything else is escaped."""
    import html as _html
    explainer = (report.get("breakdown") or "").strip()
    if not explainer:
        with st.container(border=True):
            st.markdown(f"### 📖 How {report['name']} works")
            st.caption("No write-up for this report yet.")
        return

    def _fmt(_t: str) -> str:
        # Escape for safety, then honor a light **bold** subset.
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _html.escape(_t))

    # Friendly icon per section, matched on a keyword in its header.
    # Order matters — first keyword found wins.
    _icons = [("HOW TO", "▶️"), ("ADD", "➕"), ("SKIP", "⚠️"),
              ("RUN", "🕒"), ("PRE-FLIGHT", "🚀"), ("DOES", "📊")]
    _blocks = []
    for _block in explainer.split("\n\n"):
        _lines = _block.split("\n")
        _hdr = _lines[0].strip()
        _body = "\n".join(_lines[1:]).strip()
        _icon = next((e for k, e in _icons if k in _hdr.upper()), "•")
        _blocks.append(
            "<div style='margin-bottom:16px'>"
            "<div style='font-weight:800; font-size:0.82rem; "
            "letter-spacing:0.08em; color:#A8852F; margin-bottom:6px'>"
            f"{_icon}&nbsp; {_html.escape(_hdr.upper())}</div>"
            "<div style='white-space:pre-wrap; font-size:0.96rem; "
            "line-height:1.7; color:#2A1F12'>"
            f"{_fmt(_body)}</div></div>"
        )
    st.markdown(
        "<div style='background:#FBF8F0; border:1px solid #E3D4AC; "
        "border-radius:12px; padding:20px 24px 6px; "
        "box-shadow:0 1px 4px rgba(168,133,47,0.10)'>"
        "<div style='font-size:1.2rem; font-weight:800; color:#2A1F12; "
        f"margin-bottom:16px'>📖 How {_html.escape(report['name'])} works</div>"
        + "".join(_blocks) + "</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=30, show_spinner=False)
def _tdb_store_all() -> dict:
    """Cached read of the shared 'TdB Manual Inputs' store (dinner + backfill
    leaders). 30s TTL so the card doesn't hit the Sheet on every rerender."""
    from automations.day_orchestrator import tdb_manual_store as _s
    return _s.all()


def _render_texas_de_brazil_dinner_inputs() -> None:
    """Texas de Brazil card: dinner dates + BACKFILL leaders, in the shared
    'TdB Manual Inputs' Sheet store (live cross-machine — reaches the mini with
    no code editing, no git push). The board auto-detects most leaders on its
    own; the leader boxes here are only for ones it missed. Dinner shows THIS
    competition month + the next 2 so Maud sets ~2 months ahead."""
    import datetime as _dt
    from automations.day_orchestrator import tdb_manual_store as _store
    store = _tdb_store_all()
    # This competition month (anchored to yesterday, matching the report) + next 2.
    anchor = _dt.date.today() - _dt.timedelta(days=1)
    y, mo = anchor.year, anchor.month
    months = []
    for _ in range(3):
        months.append((y, mo))
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    cur_period = f"{months[0][0]}-{months[0][1]:02d}"
    cur = store.get(cur_period, {})
    with st.expander("🍽️ Dinner dates & leaders (auto-syncs to the mini)"):
        st.caption("Dinner: set ~2 months ahead so the flyer never says TBD. "
                   "Leaders auto-track from the board — only add ones below that "
                   "the board missed. Saves to the shared sheet; no code editing.")
        st.markdown("**Dinner dates**")
        dinner_inputs = []
        for i, (yy, mm) in enumerate(months):
            key = f"{yy}-{mm:02d}"                 # storage key = competition month
            ent = store.get(key, {})
            # Label by the DINNER month (competition month + 1).
            dyy, dmm = (yy, mm + 1) if mm < 12 else (yy + 1, 1)
            st.markdown(f"*{_dt.date(dyy, dmm, 1).strftime('%B')} Date"
                        f"{'  ← this run' if i == 0 else ''}*")
            c1, c2 = st.columns(2)
            day = c1.text_input("Dinner date", value=ent.get("dinner_day", ""),
                                placeholder="e.g. SAT · AUG 11", key=f"tdb_dd_{key}",
                                label_visibility="collapsed")
            tm = c2.text_input("Dinner time", value=ent.get("dinner_time", ""),
                               placeholder="e.g. 7:00 PM", key=f"tdb_dt_{key}",
                               label_visibility="collapsed")
            dinner_inputs.append((key, day, tm))

        st.markdown(f"**Backfill leaders — {_dt.date(months[0][0], months[0][1], 1).strftime('%B')} "
                    "(only if the board missed them)**")
        promotions = st.text_area(
            "Promotions", value=cur.get("promotions", ""),
            placeholder="One per line:  Promoter > New Leader\ne.g. Willie Henderson > Jessie Gomez",
            key="tdb_promos", height=90)
        car_ride = st.text_area(
            "Car-ride leaders", value=cur.get("car_ride", ""),
            placeholder="One name per line", key="tdb_cars", height=68)

        if st.button("Save dinner & leaders", key="tdb_dinner_save"):
            try:
                for key, day, tm in dinner_inputs:
                    _store.set(key, dinner_day=day.strip(), dinner_time=tm.strip(),
                               by="hub")
                _store.set(cur_period, promotions=promotions.strip(),
                           car_ride=car_ride.strip(), by="hub")
                _tdb_store_all.clear()
                st.success("Saved — syncs to the mini on the next run.")
            except Exception as e:
                st.error(f"Couldn't save: {e}")


def _render_report_card(report: dict, today: dt.date, chrome_ok: bool) -> None:
    """One unified card per report: header, gated checklist, primary run button,
    secondary actions inside an expander."""
    import html as _html
    # Reports self-log-in via patchright — don't gate the run button on the debug
    # Chrome unless the card explicitly opts in with needs_chrome (Megan 2026-05-25).
    chrome_ok = chrome_ok or not report.get("needs_chrome", False)
    is_due = _is_due_today(report, today)
    sched = report.get("schedule", {})
    checklist = report.get("checklist", [])
    actions = report["actions"]
    primary = next((a for a in actions if a.get("primary")), actions[0])
    secondary = [a for a in actions if a is not primary]
    ran_today = _was_run_successfully_today(report["id"], today)
    # 10s heartbeat: notices when a teammate starts/finishes a run.
    _cross_user_pulse(report["id"])

    with st.container(border=True):
        st.markdown('<div class="report-card-marker"></div>', unsafe_allow_html=True)
        # Header row
        last_run_text = _latest_run_summary(report["id"])
        pills = ""
        # Background always-on jobs (hide_schedule) skip the DUE/DONE-today +
        # schedule-time pills — those read wrong for something that runs on its
        # own timer and doesn't report a per-day status.
        _hide_sched = report.get("hide_schedule")
        if ran_today and not _hide_sched:
            pills += "<span class='pill pill-ok'>✅ DONE TODAY</span>"
        elif is_due and not _hide_sched:
            pills += "<span class='pill pill-due'>DUE TODAY</span>"
        # Last-run outcome (#4) — surfaces a silent partial/failed run at a
        # glance, without opening the card.
        _card_oc = _run_outcome(report["id"])
        _skipped_list = _card_oc.get("skipped") or []
        if _card_oc["status"] == "partial":
            if _skipped_list:
                _n = len(_skipped_list)
                pills += (f"<span class='pill pill-warn'>⚠️ COMPLETED · "
                          f"{_n} ICD{'s' if _n != 1 else ''} SKIPPED</span>")
            else:
                pills += "<span class='pill pill-warn'>⚠️ LAST RUN PARTIAL</span>"
        elif _card_oc["status"] == "failed":
            pills += "<span class='pill pill-warn'>❌ LAST RUN FAILED</span>"
        if sched and not _hide_sched:
            pills += f"<span class='pill pill-info'>{sched.get('time', '')} • ~{sched.get('estimated_minutes', '?')} min</span>"
        if pills:
            st.markdown(pills, unsafe_allow_html=True)
        # Name the skipped ICDs so "2 ICDs skipped" is actionable, not a mystery.
        if _skipped_list:
            st.caption(f"⏭️ Skipped — not found in ownerville: {', '.join(_skipped_list)}")
        # Report name — forced onto a single line (ellipsis if ever too long).
        st.markdown(
            "<div style='font-size:1.35rem; font-weight:800; line-height:1.25; "
            "white-space:nowrap; overflow:hidden; text-overflow:ellipsis; "
            "margin:0.45rem 0 0.1rem'>"
            f"{report['emoji']} {report['name']}</div>",
            unsafe_allow_html=True,
        )
        # Last-run tag — its own line, directly under the name.
        if last_run_text:
            st.markdown(
                "<div style='color:#C92020; font-size:1rem; font-weight:700; "
                "white-space:nowrap; margin:0 0 0.35rem'>"
                f"· {last_run_text}</div>",
                unsafe_allow_html=True,
            )
        _creator = report.get("creator")
        if _creator:
            st.caption(f"👤 Creator: {_creator}")
        # sheet_url is optional — Slack-posting reports (e.g. Ongoing Cancel)
        # don't have a destination Sheet.
        if report.get("sheet_url"):
            st.link_button("📂 Open Sheet", report["sheet_url"])

        # If the report fans out to MULTIPLE destination sheets (e.g. the
        # Financial Pull which fills ATT Program + Carlos + Alphalete Org
        # focus reports), show each one with a small link so teammates know
        # everywhere the run touches.
        _target_sheets = report.get("target_sheets") or []
        if _target_sheets:
            _items = "".join(
                f"<li><a href='{_html.escape(s['url'])}' target='_blank' "
                f"style='color:#2A1F12; text-decoration:underline'>"
                f"{_html.escape(s['name'])}</a></li>"
                for s in _target_sheets
            )
            st.markdown(
                "<div style='background:#FBF8F0; border:1px solid #E3D4AC; "
                "border-radius:8px; padding:8px 14px; margin:8px 0 0; "
                "font-size:0.92rem'>"
                "<div style='font-weight:700; color:#2A1F12; margin-bottom:4px'>"
                "Fills out these Google Sheets:</div>"
                f"<ul style='margin:0 0 0 18px; padding:0'>{_items}</ul>"
                "</div>",
                unsafe_allow_html=True,
            )

        # In-progress check. If THIS report has a live subprocess (maybe
        # started by another tab, or by the same user before they navigated
        # away), surface a Run-in-progress panel with a Stop button and the
        # live log tail. We skip the rest of the card — checklist, Run
        # button, post-run callout — because none of that is relevant while
        # the subprocess is still going.
        _active_runs = _read_active_runs()
        _active_for_this = next(
            (a for a in _active_runs if a.get("report_id") == report["id"]),
            None,
        )
        if _active_for_this:
            _render_active_run_panel(report, _active_for_this)
            return

        # Daily-Focus only: prompt for any new ICDs in col V that don't have
        # an AppStream office mapped yet. Once confirmed (or marked 'not an
        # ICD'), the choice is persisted so it never asks again.
        if report["id"] == "daily-focus":
            _render_daily_focus_mapping_prompt("Raf")
            _render_daily_focus_mapping_prompt("Carlos")

        # Weekly Recruiting only: ask the runner to resolve any tab whose name
        # matches more than one AppStream office, before the run.
        if report["id"] == "recruiting":
            _render_recruiting_office_picker()

        # Texas de Brazil only: let Maud set the dinner date/time each cycle
        # (written to the report's manual-inputs JSON that the run reads).
        if report["id"] == "june_texas_de_brazil_monthly_competition":
            _render_texas_de_brazil_dinner_inputs()

        # Checklist (gates the primary run button)
        all_checked = True
        if checklist:
            with st.expander("📋 Pre-flight checklist", expanded=(is_due and not ran_today)):
                for idx, step in enumerate(checklist):
                    # An uploaded report can register a step dict with no "text"
                    # key; reading step["text"] then KeyError'd and took the whole
                    # library screen down (2026-05-27). Default it so a malformed
                    # step renders as an empty/blank line instead of crashing.
                    step_text = step.get("text", "")
                    if step.get("info"):
                        st.info(step_text)
                        continue
                    # Upload step — file_uploader inline, files saved to
                    # target_dir; step is "done" when at least 1 file is there.
                    if step.get("uploader"):
                        up_cfg = step["uploader"]
                        target_dir = WORKSPACE / up_cfg["target_dir"]
                        target_dir.mkdir(parents=True, exist_ok=True)
                        st.markdown(f"**{step_text}**")
                        _accept = [a.lstrip(".")
                                    for a in up_cfg.get("accept", [".xlsx"])]
                        _multi = bool(up_cfg.get("multiple", False))
                        _up = st.file_uploader(
                            up_cfg.get("button_label", "Drop file(s) here"),
                            type=_accept,
                            accept_multiple_files=_multi,
                            key=f"upload_{report['id']}_{idx}",
                            label_visibility="collapsed",
                        )
                        if _up:
                            items = _up if isinstance(_up, list) else [_up]
                            for f in items:
                                (target_dir / f.name).write_bytes(f.getbuffer())
                            st.success(
                                f"✅ Saved {len(items)} file(s) to "
                                f"`{up_cfg['target_dir']}/`"
                            )
                        existing = sorted(
                            p for p in target_dir.glob("*")
                            if not p.name.startswith("~$")
                            and p.suffix.lower() in {f".{a}" for a in _accept}
                        )
                        if existing:
                            preview = ", ".join(p.name for p in existing[:5])
                            more = f" (+{len(existing)-5} more)" if len(existing) > 5 else ""
                            st.caption(f"📂 {len(existing)} file(s) ready: {preview}{more}")
                            if st.button(
                                "🗑️ Clear uploaded files",
                                key=f"clear_up_{report['id']}_{idx}",
                            ):
                                for p in existing:
                                    p.unlink()
                                st.rerun()
                        else:
                            all_checked = False
                            st.warning("Upload at least one file to continue.")
                        continue
                    cols = st.columns([5, 3])
                    ck_key = f"check_{report['id']}_{idx}"
                    msg_key = f"msg_{report['id']}_{idx}"
                    with cols[0]:
                        ck = st.checkbox(step_text, key=ck_key)
                        if not ck:
                            all_checked = False
                        # Display action result message (set by callback on previous run).
                        # Success → transient toast shown once (no persistent green box);
                        # failure → keep the error visible until the next action.
                        if msg_key in st.session_state:
                            ok, m = st.session_state[msg_key]
                            if ok:
                                st.toast(m, icon="🚀")
                                del st.session_state[msg_key]
                            else:
                                st.error(m)
                    with cols[1]:
                        if step.get("link"):
                            st.button(
                                step.get("link_label", "Open"),
                                key=f"link_{report['id']}_{idx}",
                                use_container_width=True,
                                on_click=_on_link_open_click,
                                args=(step["link"], ck_key),
                            )
                        elif step.get("action") == "launch_chrome":
                            st.button(
                                "🚀 Launch Report Chrome",
                                key=f"chrome_{report['id']}_{idx}",
                                use_container_width=True,
                                on_click=_on_chrome_launch_click,
                                args=(ck_key, msg_key),
                            )

        # Primary run button — gated by checklist + Chrome
        run_disabled = (not all_checked) or (not chrome_ok)
        run_help = None
        if not chrome_ok:
            run_help = "Chrome isn't running — launch it from the sidebar first."
        elif not all_checked:
            run_help = "Complete the checklist first."

        # Picker for date/text input (if primary action needs one)
        picked = None
        if primary.get("needs_date"):
            picked = st.date_input("WE Sunday", key=f"date_{report['id']}_{primary['label']}", value=_last_completed_we_sunday())
        elif primary.get("needs_text"):
            picked = st.text_input(
                primary.get("text_label", "Input"),
                key=f"text_{report['id']}_{primary['label']}",
                placeholder=primary.get("text_label", ""),
            )

        # 24h-rerun confirmation gate. If the report was already run successfully
        # in the last 24h (by anyone), clicking Run shows a confirmation banner
        # instead of executing immediately.
        confirm_key = f"confirm_pending_{report['id']}"
        confirm_meta_key = f"confirm_meta_{report['id']}"

        if st.button(
            f"{primary.get('icon', '▶')} {primary['label']}",
            key=f"prim_{report['id']}",
            type="primary",
            use_container_width=True,
            disabled=run_disabled,
            help=run_help,
        ):
            recent, recent_user, recent_time = _ran_today(report["id"])
            if recent:
                st.session_state[confirm_key] = True
                st.session_state[confirm_meta_key] = (recent_user, recent_time)
                st.rerun()
            else:
                _execute_action(report, primary, picked, chrome_ok)

        if st.session_state.get(confirm_key):
            ru, rt = st.session_state.get(confirm_meta_key, ("someone", "earlier today"))
            with st.container(border=True):
                st.warning(
                    f"⚠️ **{ru}** already ran this at **{rt}** today. "
                    f"Run it again anyway?"
                )
                cc = st.columns([1, 1])
                with cc[0]:
                    if st.button("✅ Yes, run it again", key=f"confirm_yes_{report['id']}",
                                 type="primary", use_container_width=True):
                        st.session_state.pop(confirm_key, None)
                        st.session_state.pop(confirm_meta_key, None)
                        _execute_action(report, primary, picked, chrome_ok)
                        st.rerun()
                with cc[1]:
                    if st.button("🛑 Stop", key=f"confirm_no_{report['id']}",
                                 use_container_width=True):
                        st.session_state.pop(confirm_key, None)
                        st.session_state.pop(confirm_meta_key, None)
                        st.rerun()

        # Post-run callout (appears after a run completes; persists 24h)
        last_run = st.session_state.get(f"last_run_{report['id']}")
        if not last_run:
            persisted = _load_all_run_state().get(report["id"])
            if persisted:
                last_run = persisted
                # Re-hydrate session state so the rest of the page sees it
                st.session_state[f"last_run_{report['id']}"] = persisted
        if last_run:
            post_run_cfg = report.get("post_run", {})
            # Read state file (if configured) to find ICDs the run skipped.
            # When the state file exists with a non-empty list, we promote the
            # prompt to a high-visibility "switch logins and finish" call-to-
            # action with the actual missing names — Megan asked for this so
            # she knows every cell is accounted for.
            again_state_rel = post_run_cfg.get("again_state_file")
            again_state_key = post_run_cfg.get("again_state_key")
            # STANDARD failure manifest (output/manifests/<id>.json) takes
            # precedence over the legacy per-card again_state_file: any report
            # that writes one gets this retry button generically, no per-card
            # config. _mr carries the failed parts + a synthesized again_action.
            _mr = _manifest_retry(report)
            missing_items: list[str] = []
            # New (post 2026-05-20): the state file may also carry a
            # 'denied' list (real access denials) and 'fetch_errors'
            # list (transient timeouts). Reading them lets the callout
            # tell the user the RIGHT fix (request access vs just retry)
            # instead of blaming AppStream access for every failure.
            denied_items: list[str] = []
            fetch_error_items: list[str] = []
            state_file_exists = False
            if _mr:
                state_file_exists = True
                missing_items = list(_mr["failed"])
            elif again_state_rel and again_state_key:
                state_path = WORKSPACE / again_state_rel
                try:
                    if state_path.exists():
                        state_file_exists = True
                        data = json.loads(state_path.read_text())
                        missing_items = list(data.get(again_state_key) or [])
                        denied_items = list(data.get("denied") or [])
                        fetch_error_items = list(data.get("fetch_errors") or [])
                except Exception:
                    pass
            nothing_to_retry = state_file_exists and not missing_items

            with st.container(border=True):
                if last_run["status"] == "success":
                    if missing_items:
                        # When the state file gives us the split (denied vs
                        # fetch_errors), show two separate callouts so the
                        # user knows which fix applies to each ICD.
                        # Legacy state files only have `missing_items` —
                        # those fall back to the single combined callout.
                        if denied_items or fetch_error_items:
                            if denied_items:
                                _names = ", ".join(denied_items)
                                st.markdown(
                                    "<div style='background:linear-gradient(135deg, #FFE4E0 0%, #FFCEC7 100%); "
                                    "border:2px solid #D8261C; border-radius:10px; "
                                    "padding:14px 18px; margin:4px 0 10px; color:#5C1A14;'>"
                                    "<div style='font-weight:800; font-size:1.15rem;'>"
                                    f"🚩 {len(denied_items)} "
                                    f"ICD{'s' if len(denied_items)!=1 else ''} blocked "
                                    "by AppStream — request access</div>"
                                    "<div style='margin-top:6px; font-size:0.95rem;'>"
                                    f"<b>{_names}</b></div>"
                                    "<div style='margin-top:8px; font-size:0.95rem;'>"
                                    "AppStream refused these ICDs for the logged-in "
                                    "account. Request rcaptain access (or switch to "
                                    "an AppStream account that already has it) and "
                                    "click the button below to re-pull."
                                    "</div></div>",
                                    unsafe_allow_html=True,
                                )
                            if fetch_error_items:
                                _names = ", ".join(fetch_error_items)
                                st.markdown(
                                    "<div style='background:linear-gradient(135deg, #FFF4E0 0%, #FFE3B5 100%); "
                                    "border:2px solid #C8841C; border-radius:10px; "
                                    "padding:14px 18px; margin:4px 0 10px; color:#5C3E14;'>"
                                    "<div style='font-weight:800; font-size:1.15rem;'>"
                                    f"⚠️ {len(fetch_error_items)} "
                                    f"ICD{'s' if len(fetch_error_items)!=1 else ''} hit a "
                                    "transient pull error — usually fixed by a retry</div>"
                                    "<div style='margin-top:6px; font-size:0.95rem;'>"
                                    f"<b>{_names}</b></div>"
                                    "<div style='margin-top:8px; font-size:0.95rem;'>"
                                    "These weren't access denials — Playwright timed "
                                    "out or the page didn't return data. Click the "
                                    "button below to re-pull (a fresh attempt almost "
                                    "always succeeds)."
                                    "</div></div>",
                                    unsafe_allow_html=True,
                                )
                        else:
                            # Legacy single-bucket callout (state file pre-dates the split)
                            _names = ", ".join(missing_items)
                            st.markdown(
                                "<div style='background:linear-gradient(135deg, #FFE4E0 0%, #FFCEC7 100%); "
                                "border:2px solid #D8261C; border-radius:10px; "
                                "padding:14px 18px; margin:4px 0 10px; color:#5C1A14;'>"
                                "<div style='font-weight:800; font-size:1.15rem;'>"
                                f"🚩 Run complete — {len(missing_items)} "
                                f"ICD{'s' if len(missing_items)!=1 else ''} not pulled</div>"
                                "<div style='margin-top:6px; font-size:0.95rem;'>"
                                f"<b>{_names}</b></div>"
                                "<div style='margin-top:8px; font-size:0.95rem;'>"
                                "Either rcaptain has no AppStream access yet, or "
                                "the pull hit a transient error. Try the retry "
                                "button below first — if it still fails, request "
                                "rcaptain access for these ICDs."
                                "</div></div>",
                                unsafe_allow_html=True,
                            )

                        # Run log expander — also shown for completed-with-gaps
                        # runs, not just outright failures. Lets the teammate
                        # diagnose WHY each ICD was missed (timeout vs real
                        # access denial vs page-load issue) without having to
                        # crack open Terminal. Added 2026-05-21 after Maud
                        # hit a retry-then-data-loss issue where the only way
                        # to see what went wrong was the on-disk log file.
                        _log_path_gap = ACTIVE_RUNS_LOG_DIR / f"{report['id']}.log"
                        if _log_path_gap.exists():
                            try:
                                _gap_log_tail = "\n".join(
                                    _log_path_gap.read_text(errors="replace").splitlines()[-40:]
                                )
                            except Exception:
                                _gap_log_tail = ""
                            if _gap_log_tail:
                                with st.expander("📜 Run log (last 40 lines)",
                                                 expanded=False):
                                    st.code(_gap_log_tail, language="log")
                    elif state_file_exists:
                        # An empty "inaccessible" list isn't real success if
                        # ICDs are still unmapped — the run silently skips
                        # those, so nothing got filled for them.
                        _dfu = []
                        if report["id"] == "daily-focus":
                            _dfu = (_daily_focus_unmapped("Raf")
                                    + _daily_focus_unmapped("Carlos"))
                        if _dfu:
                            st.warning(
                                f"⚠️ {len(_dfu)} ICD(s) were skipped — not mapped "
                                "to an AppStream office yet: "
                                f"{', '.join(_dfu)}. Map them in the prompt at the "
                                "top of this card, then re-run."
                            )
                        else:
                            st.success(
                                "✅ All ICDs filled on the first run — every cell is "
                                "accounted for. Nothing to retry."
                            )
                        # Also expose the run log here — "All filled" can be
                        # misleading when a retry silently damaged data the
                        # Hub doesn't track (e.g. cleared cells for ICDs not
                        # in the missing list). Lets a teammate look at what
                        # actually happened even on the success path.
                        _log_path_ok = ACTIVE_RUNS_LOG_DIR / f"{report['id']}.log"
                        if _log_path_ok.exists():
                            try:
                                _ok_log_tail = "\n".join(
                                    _log_path_ok.read_text(errors="replace").splitlines()[-40:]
                                )
                            except Exception:
                                _ok_log_tail = ""
                            if _ok_log_tail:
                                with st.expander("📜 Run log (last 40 lines)",
                                                 expanded=False):
                                    st.code(_ok_log_tail, language="log")
                    else:
                        # Reports without a state-file config fall back to the
                        # generic post_run success message — but reflect what
                        # ACTUALLY happened (honest status #1): if the run log
                        # shows a phase quietly skipped or the browser died mid-
                        # run, go amber + name it instead of a misleading green.
                        msg = post_run_cfg.get(
                            "message_success",
                            "✅ Run finished. If any ICD showed 'not accessible' "
                            "in the log, switch AppStream logins and run again.",
                        )
                        _post_oc = _run_outcome(report["id"])
                        if _post_oc["status"] == "partial":
                            st.warning(
                                "⚠️ Run finished, but not everything filled:\n"
                                + "\n".join(f"• {i}" for i in _post_oc["issues"])
                                + "\n\nCheck the run log below, then re-run if needed."
                            )
                        elif post_run_cfg.get("success_tone") == "warning":
                            st.warning(msg)
                        else:
                            st.success(msg)
                else:
                    # Read the run log — used both to diagnose the failure
                    # and to show the raw tail.
                    _log_path = ACTIVE_RUNS_LOG_DIR / f"{report['id']}.log"
                    _log_tail_text = ""
                    if _log_path.exists():
                        try:
                            _log_tail_text = "\n".join(
                                _log_path.read_text(errors="replace").splitlines()[-40:]
                            )
                        except Exception:
                            _log_tail_text = ""

                    # Plain-English diagnosis of common failures. When we
                    # recognize the cause, show it prominently in place of
                    # the report's generic failure message.
                    _diag = _diagnose_run_failure(_log_tail_text)
                    # Richer remediation: prefers the report's own manifest
                    # remediation (exact Tableau link + tailored message), falls
                    # back to the generic signature. why → fix → link → message.
                    _rem = _failure_remediation(report["id"], _log_tail_text)
                    if _diag or _rem:
                        _why = (_rem.get("reason") if _rem and _rem.get("reason")
                                else (_diag[0] if _diag else "The run failed."))
                        _fix = (_rem.get("fix") if _rem and _rem.get("fix")
                                else (_diag[1] if _diag else
                                      "Check the log below, then run again."))
                        st.markdown(
                            "<div style='background:linear-gradient(135deg,#FFE4E0 0%,#FFCEC7 100%);"
                            "border:2px solid #D8261C;border-radius:10px;"
                            "padding:14px 18px;margin:4px 0 10px;color:#5C1A14;'>"
                            "<div style='font-weight:800;font-size:1.1rem;'>"
                            f"❌ {_why}</div>"
                            "<div style='margin-top:6px;font-size:0.95rem;'>"
                            f"<b>What to do:</b> {_fix}</div></div>",
                            unsafe_allow_html=True,
                        )
                        # If it's a Tableau (or other) issue with a known link,
                        # show exactly where the missing info lives.
                        if _rem and _rem.get("link"):
                            st.markdown(
                                f"🔗 **Where to look:** [{_rem['link']}]({_rem['link']})")
                        # Copy-paste message to send to whoever can fix it.
                        # st.code gives a one-click Copy icon (top-right).
                        if _rem and _rem.get("message"):
                            st.caption("💬 Message to send (hover the box → click "
                                       "the Copy icon):")
                            st.code(_rem["message"], language=None)
                        # Self-heal for OAuth lockouts — one-click reset
                        # instead of asking teammates to dig into a hidden
                        # folder. Added 2026-05-21 after Maud got stuck.
                        if _is_oauth_failure(_diag):
                            _oauth_msg_key = f"oauth_reset_msg_{report['id']}"
                            if _oauth_msg_key in st.session_state:
                                _ok, _msg = st.session_state[_oauth_msg_key]
                                (st.success if _ok else st.error)(_msg)
                            if st.button(
                                "🔄 Reset Google Sign-In",
                                key=f"oauth_reset_{report['id']}",
                                help="One-click fix — clears the expired "
                                     "Google token so the next Run prompts "
                                     "a fresh sign-in.",
                            ):
                                st.session_state[_oauth_msg_key] = _reset_oauth_token()
                                st.rerun()
                    else:
                        msg = post_run_cfg.get(
                            "message_failed",
                            "❌ Run failed. Check the log below, then click Run Again.",
                        )
                        st.error(msg)

                    # Raw log — always expanded on a failed run so users
                    # can copy-paste the last 40 lines to Megan without an
                    # extra click. st.code adds a hover Copy button in
                    # Streamlit so paste-into-Slack is one click.
                    if _log_tail_text:
                        with st.expander(
                                "📜 Run log (last 40 lines) — hover the box for a Copy button",
                                expanded=True):
                            st.code(_log_tail_text, language="log")

                    # Every failed run auto-files a glitch row to the Bug
                    # Reports tab in the intake Sheet (see the orphan path in
                    # _read_active_runs). The intake Sheet's Apps Script
                    # (notifyMeganOnNewBug, time-driven every 5 min) emails
                    # Megan when a new row lands.
                    st.caption("🚩 Filed on the Bug Reports tab — Megan gets "
                               "an email with the full log within 5 minutes.")

                again_label = post_run_cfg.get("again_label", "🔁 Run Again")
                _resume_done = 0
                if missing_items:
                    # Make the button count-aware so it matches the callout above.
                    again_label = f"🔁 Retry {len(missing_items)} skipped ICD{'s' if len(missing_items)!=1 else ''}"
                else:
                    # A leftover resume checkpoint means the last run was
                    # interrupted; re-running picks up where it stopped.
                    _cp_path = _resume_checkpoint_for(report)
                    if _cp_path and _cp_path.exists():
                        try:
                            _resume_done = len(
                                json.loads(_cp_path.read_text()).get("completed", [])
                            )
                        except Exception:
                            _resume_done = 0
                    if _resume_done:
                        again_label = (f"▶ Resume run — {_resume_done} "
                                       f"office{'s' if _resume_done != 1 else ''} "
                                       "already done")
                # Optional: a separate action to fire on Run Again (e.g. retry
                # mode that only re-processes the items that failed last time).
                # Standard manifest wins, then a per-card again_action, then the
                # full primary run.
                again_action = (_mr["action"] if _mr
                                else post_run_cfg.get("again_action") or primary)
                again_empty_msg = post_run_cfg.get(
                    "again_empty_message",
                    "✅ Nothing to retry from the previous run.",
                )

                # Only show the retry button when there's something to retry,
                # OR for reports without a state file (legacy fallback).
                show_again = bool(missing_items) or not state_file_exists
                if show_again:
                    cols = st.columns([3, 2])
                    with cols[0]:
                        if missing_items:
                            st.caption("Once an AppStream account with access is logged in, click →")
                        elif _resume_done:
                            st.caption("Picks up where it stopped — already-done "
                                       "offices are skipped.")
                        else:
                            st.caption("When you're ready, click below.")
                    with cols[1]:
                        if st.button(again_label, key=f"again_{report['id']}", use_container_width=True, disabled=not chrome_ok):
                            if nothing_to_retry:
                                st.success(again_empty_msg)
                            else:
                                _execute_action(report, again_action, None, chrome_ok)
                if st.button("✅ Mark as Completed", key=f"dismiss_{report['id']}"):
                    # Record on this user's "Completed Today" list
                    _mark_run_completed(
                        user=st.session_state.get("user", "unknown"),
                        report_id=report["id"],
                        report_name=report["name"],
                        run_ts=last_run.get("ts", ""),
                    )
                    st.session_state.pop(f"last_run_{report['id']}", None)
                    st.session_state.pop(f"glitch_sent_{report['id']}", None)
                    _clear_run_state_for(report["id"])
                    st.rerun()

        # Secondary actions
        if secondary:
            with st.expander("⚙️ More actions"):
                for action in secondary:
                    cols = st.columns([4, 3, 2])
                    with cols[0]:
                        st.markdown(f"**{action.get('icon', '')} {action['label']}**")
                        if action.get("help"):
                            st.caption(action["help"])
                    with cols[1]:
                        sec_date = None
                        sec_text = None
                        if action.get("needs_date"):
                            sec_date = st.date_input(
                                "WE Sunday",
                                key=f"sec_date_{report['id']}_{action['label']}",
                                value=_last_completed_we_sunday(),
                                label_visibility="collapsed",
                            )
                        if action.get("needs_text"):
                            sec_text = st.text_input(
                                action.get("text_label", "Input"),
                                key=f"sec_text_{report['id']}_{action['label']}",
                                label_visibility="collapsed",
                                placeholder=action.get("text_label", ""),
                            )
                        if not (action.get("needs_date") or action.get("needs_text")):
                            st.write("")
                        # Build sec_picked: tuple if both, single value if one, None if neither
                        if action.get("needs_date") and action.get("needs_text"):
                            sec_picked = (sec_date, sec_text)
                        elif action.get("needs_date"):
                            sec_picked = sec_date
                        elif action.get("needs_text"):
                            sec_picked = sec_text
                        else:
                            sec_picked = None
                    with cols[2]:
                        if st.button(
                            f"{action.get('icon', '▶')} Run",
                            key=f"sec_{report['id']}_{action['label']}",
                            use_container_width=True,
                            disabled=not chrome_ok,
                            help=None if chrome_ok else "Chrome isn't running",
                        ):
                            _execute_action(report, action, sec_picked, chrome_ok)


# Intake/backlog lives in its own dedicated Google Sheet (separate from the
# big recruiting reports Sheet). Anyone who submits requests via the dashboard
# needs Edit access to this Sheet — share it with their Google account.
INTAKE_SPREADSHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
INTAKE_TAB = "Automation Backlog"
INTAKE_HEADERS = [
    "ID", "Title", "Sheet Link", "Loom Link", "Description",
    "Submitted By", "Submitted At", "Status", "Assigned To", "Assigned At",
    "Preferred Creator", "Currently runs", "Priority", "Submitter Email",
    "Review CC", "Notes", "Resurrected At", "Completed At", "Claim History",
    "Additional Links", "Review Notes", "Schedule Days",
    "Schedule Frequency", "Schedule Day Of Month", "Schedule Time",
    "Report Breakdown", "Edit Request",
]

PRIORITY_OPTIONS = [
    "1 — 🚨 URGENT (drop everything)",
    "2 — 🔥 High (needed this week)",
    "3 — 📌 Medium (nice to have soon)",
    "4 — 🌱 Low (when there's bandwidth)",
    "5 — 🌮 When pigs fly (or you have a sec)",
]

BUG_TAB = "Bug Reports"
BUG_HEADERS = [
    "ID", "Title", "Type", "Sheet Link", "Loom Link", "Details",
    "Submitted By", "Submitter Email", "Priority",
    "Status", "Submitted At", "Resolution Note", "Resolved At",
    "Resurrected At", "Resurrection Note",
]


def _intake_ws():
    """Return the intake worksheet, creating it if missing.

    Also self-heals the header row: if older deployments wrote a shorter
    INTAKE_HEADERS list, the existing sheet may be missing newer columns
    (e.g. 'Currently runs', 'Priority'). gspread's get_all_records()
    rejects rows with values past the headered columns, which would make
    new submissions silently disappear from the homepage. Detecting the
    drift and extending the header row fixes that without touching any
    user-set columns.
    """
    import gspread as _gs
    sh = _fill.open_by_key(INTAKE_SPREADSHEET_ID)
    try:
        ws = sh.worksheet(INTAKE_TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=INTAKE_TAB, rows=300, cols=len(INTAKE_HEADERS))
        ws.update([INTAKE_HEADERS], f"A1:{_col_a1(len(INTAKE_HEADERS))}1")
        return ws

    # Self-heal: only extend when current row 1 is a strict PREFIX of
    # INTAKE_HEADERS so we never overwrite custom column names.
    try:
        current_headers = ws.row_values(1)
    except Exception:
        current_headers = []
    if (
        len(current_headers) < len(INTAKE_HEADERS)
        and INTAKE_HEADERS[: len(current_headers)] == current_headers
    ):
        ws.update(
            [INTAKE_HEADERS],
            f"A1:{_col_a1(len(INTAKE_HEADERS))}1",
        )
    return ws


@st.cache_data(ttl=30)
def _read_intake() -> list[dict]:
    """All intake records, newest first. Cached 30s to avoid per-rerun API hits.

    Intentionally NOT catching exceptions here — the call sites wrap this in
    try/except and render the real error (e.g. corrupted OAuth JSON). A silent
    return [] makes auth failures look like "nothing to claim" to the user.
    """
    ws = _intake_ws()
    rows = ws.get_all_records()
    return list(reversed(rows))


@st.cache_data(ttl=60)
def _add_intake(title: str, sheet_link: str, loom_link: str, description: str,
                submitted_by: str, preferred_creator: str = "",
                currently_runs: str = "", priority: str = "",
                submitter_email: str = "",
                additional_links: str = "", schedule_days: str = "",
                schedule_frequency: str = "", schedule_day_of_month: str = "",
                schedule_time: str = "") -> str:
    new_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ws = _intake_ws()
    # Fill every column positionally so each value lands in the right cell.
    # Empty strings for columns the form doesn't populate.
    ws.append_row([
        new_id, title, sheet_link, loom_link, description,
        submitted_by, dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Unassigned", "", "",
        preferred_creator or "",
        currently_runs or "",
        priority or "",
        submitter_email or "",
        "",  # Review CC
        "",  # Notes
        "",  # Resurrected At
        "",  # Completed At
        "",  # Claim History
        additional_links or "",  # Additional Links
        "",  # Review Notes
        schedule_days or "",  # Schedule Days (weekday indexes, comma-separated)
        schedule_frequency or "",     # Schedule Frequency (daily/weekly/monthly)
        schedule_day_of_month or "",  # Schedule Day Of Month
        schedule_time or "",          # Schedule Time
    ])
    _read_intake.clear()
    return new_id


def _assign_intake(entry_id: str, user: str) -> bool:
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    ws.update_cell(row, 8, "In Progress")
    ws.update_cell(row, 9, user)
    ws.update_cell(row, 10, now)
    _append_claim_history(row, user, now)
    _read_intake.clear()
    return True


def _unassign_intake(entry_id: str) -> bool:
    """Send a claimed backlog entry back to Unassigned — for when someone
    claimed it by mistake. Clears the assignee + claim timestamp and flips
    Status back to 'Unassigned'. Claim History is left intact as a record."""
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    ws.update_cell(row, 8, "Unassigned")   # Status
    ws.update_cell(row, 9, "")             # Assigned To
    ws.update_cell(row, 10, "")            # Assigned At
    _read_intake.clear()
    return True


def _append_claim_history(row: int, user: str, when: str) -> None:
    """Append a 'name | timestamp' line to the row's Claim History cell.

    Keeps a running log of every assignment so completed-card summaries
    can show the full chain when a project is resurrected and re-claimed.
    """
    if "Claim History" not in INTAKE_HEADERS:
        return
    ws = _intake_ws()
    col = INTAKE_HEADERS.index("Claim History") + 1
    try:
        current = ws.cell(row, col).value or ""
    except Exception:
        current = ""
    new_line = f"{user} | {when}"
    updated = (current.rstrip() + "\n" + new_line) if current.strip() else new_line
    ws.update_cell(row, col, updated)


def _mark_intake_done(entry_id: str, cc_emails: str = "") -> bool:
    """Set status to Done (triggers the Apps Script review email) and stash
    any optional CCs that should be added to that email. Also stamps the
    Completed At column so the summary card can compute elapsed time.
    """
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    if cc_emails and "Review CC" in INTAKE_HEADERS:
        ws.update_cell(row, INTAKE_HEADERS.index("Review CC") + 1, cc_emails.strip())
    if "Completed At" in INTAKE_HEADERS:
        ws.update_cell(
            row,
            INTAKE_HEADERS.index("Completed At") + 1,
            dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    ws.update_cell(row, INTAKE_HEADERS.index("Status") + 1, "Done")
    _read_intake.clear()
    return True


def _resurrect_intake(entry_id: str, reason: str, author: str) -> bool:
    """Re-open a Done backlog entry. Flips status to 'Needs Updates' so it
    surfaces on the assigned person's queue with a red flag — someone then
    has to explicitly claim those updates to move it to In Progress.
    """
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    # Append a note first (uses the existing notes flow so it shows up in
    # the Notes expander like any other update).
    _append_intake_note(
        entry_id,
        f"🔄 Resurrected: {reason.strip() or '(no reason given)'}",
        author or "Someone",
    )
    if "Resurrected At" in INTAKE_HEADERS:
        ws.update_cell(
            row,
            INTAKE_HEADERS.index("Resurrected At") + 1,
            dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    ws.update_cell(row, INTAKE_HEADERS.index("Status") + 1, "Needs Updates")
    _read_intake.clear()
    return True


def _claim_intake_updates(entry_id: str, claimer: str) -> bool:
    """Pick up a 'Needs Updates' card and move it to In Progress.

    Updates the Assigned To column to the claimer (the original assignee
    can claim themselves to confirm they're handling it, or anyone else
    can take it on). Assigned At is refreshed too so the card's claim
    timestamp reflects the new ownership. Appends to Claim History so
    completed-card summaries can show the full chain of claimers.
    """
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if claimer:
        ws.update_cell(row, INTAKE_HEADERS.index("Assigned To") + 1, claimer)
        ws.update_cell(row, INTAKE_HEADERS.index("Assigned At") + 1, now)
        _append_claim_history(row, claimer, now)
    ws.update_cell(row, INTAKE_HEADERS.index("Status") + 1, "In Progress")
    _read_intake.clear()
    return True


def _append_intake_link(entry_id: str, url: str, label: str = "") -> bool:
    """Append a 'label | url' line to the row's Additional Links column.

    Anyone viewing a project card can drop a new link onto it at any time
    (source data, follow-up loom, supporting doc, whatever). Label is
    optional — without one, the card renders the link as a generic 🔗.
    """
    url = (url or "").strip()
    if not url:
        return False
    if "Additional Links" not in INTAKE_HEADERS:
        return False
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    col = INTAKE_HEADERS.index("Additional Links") + 1
    try:
        current = ws.cell(row, col).value or ""
    except Exception:
        current = ""
    new_line = f"{(label or '').strip()} | {url}" if (label or "").strip() else url
    updated = (current.rstrip() + "\n" + new_line) if current.strip() else new_line
    ws.update_cell(row, col, updated)
    _read_intake.clear()
    return True


def _safe_link_button(label: str, url, **kwargs) -> None:
    """st.link_button crashes with 'bad argument type for built-in operation'
    when `url` isn't a non-empty str — gspread hands back ints/floats for
    numeric-looking cells, and a truthiness check passes those through. Coerce
    to str and skip empties so one malformed link can't take down the whole
    screen (TypeError on 'library', 2026-05-27)."""
    u = str(url or "").strip()
    if not u:
        return
    st.link_button(label, u, **kwargs)


def _label_for_url(url: str) -> str:
    """Pick a short, scannable button label from a URL's host.

    Used when the user attaches a link from a card without typing their own
    label — the host alone is enough to tell at a glance what's behind the
    button (Loom vs YouTube vs Drive vs Sheet).
    """
    u = (url or "").strip().lower()
    if "loom.com" in u:
        return "Loom video"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube video"
    if "vimeo.com" in u:
        return "Vimeo video"
    if "docs.google.com/spreadsheets" in u:
        return "Google Sheet"
    if "docs.google.com/document" in u:
        return "Google Doc"
    if "docs.google.com/presentation" in u:
        return "Google Slides"
    if "drive.google.com" in u:
        return "Google Drive"
    if "dropbox.com" in u:
        return "Dropbox"
    if "notion.so" in u or "notion.site" in u:
        return "Notion"
    return "Link"


def _parse_link_lines(raw: str) -> list[tuple[str, str]]:
    """Parse newline-separated link lines into (label, url) tuples.

    A line may be 'label | url', 'label: url', or just a bare url — and may
    also be a plain-text note with no link at all. We pull the first http(s)
    URL out of each line; the text before it (minus a trailing ':' or '|')
    becomes the label. Lines with NO url are dropped, so stray notes never
    render as dead buttons.
    """
    out: list[tuple[str, str]] = []
    for raw_line in (raw or "").splitlines():
        line = raw_line.strip()
        if not line or line.lower() == "n/a":
            continue
        m = re.search(r"https?://\S+", line)
        if not m:
            continue  # a note with no link — not a button
        url = m.group(0).rstrip(".,);")
        label = line[:m.start()].strip().rstrip("|:").strip()
        out.append((label, url))
    return out


def _append_intake_note(entry_id: str, note: str, author: str) -> bool:
    """Append a timestamped note to the row's Notes column.

    Notes accumulate top-down with the newest at the bottom, each prefixed
    with a timestamp + author so the thread reads as a running log.
    """
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    notes_col = INTAKE_HEADERS.index("Notes") + 1
    try:
        current = ws.cell(row, notes_col).value or ""
    except Exception:
        current = ""
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    new_line = f"[{ts} — {author.strip()}] {note.strip()}"
    updated = (current.rstrip() + "\n\n" + new_line) if current.strip() else new_line
    ws.update_cell(row, notes_col, updated)
    _read_intake.clear()
    return True


# --------------------------------------------------------------------------
# Bug Reports — separate tab in the intake Sheet. Lighter-weight than the
# automation backlog: only Megan triages these, so the home-page UI is
# condensed and there's no "claim" step. When Megan marks a bug Fixed or
# Needs Info, the Apps Script picks up the status change and emails the
# submitter (using the Submitter Email captured at intake).
# --------------------------------------------------------------------------

def _bugs_ws():
    """Return the Bug Reports worksheet, creating it if missing."""
    import gspread as _gs
    sh = _fill.open_by_key(INTAKE_SPREADSHEET_ID)
    try:
        ws = sh.worksheet(BUG_TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=BUG_TAB, rows=300, cols=len(BUG_HEADERS))
        ws.update([BUG_HEADERS], f"A1:{_col_a1(len(BUG_HEADERS))}1")
        return ws
    try:
        current_headers = ws.row_values(1)
    except Exception:
        current_headers = []
    if (
        len(current_headers) < len(BUG_HEADERS)
        and BUG_HEADERS[: len(current_headers)] == current_headers
    ):
        ws.update(
            [BUG_HEADERS],
            f"A1:{_col_a1(len(BUG_HEADERS))}1",
        )
    return ws


@st.cache_data(ttl=30)
def _read_bugs() -> list[dict]:
    """All bug records, newest first.

    Intentionally NOT catching exceptions — see _read_intake for rationale.
    """
    ws = _bugs_ws()
    rows = ws.get_all_records()
    return list(reversed(rows))


def _add_bug(title: str, bug_type: str, sheet_link: str, loom_link: str,
             details: str, submitted_by: str, submitter_email: str,
             priority: str) -> str:
    new_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ws = _bugs_ws()
    ws.append_row([
        new_id, title, bug_type, sheet_link, loom_link, details,
        submitted_by, submitter_email, priority,
        "Open", dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "", "",
    ])
    _read_bugs.clear()
    return new_id


def _hub_git_sha() -> str:
    """Short git commit the Hub is running on — lets a glitch report pin the
    exact code version. '?' if git isn't available."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(WORKSPACE), capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() or "?"
    except Exception:
        return "?"


def _file_run_glitch(report_id: str, report_name: str, log_text: str,
                     user: str, command: str = "", sheet_url: str = "") -> str:
    """File a failed report run as a rich bug report on the Bug Reports tab.

    Captures everything needed to actually debug it: the plain-English likely
    cause, the exact command, the Hub code version, and the run log (with any
    traceback). Returns the new bug ID (or the existing one if deduped)."""
    diag = _diagnose_run_failure(log_text)
    diag_line = f"LIKELY CAUSE: {diag[0]}\n{diag[1]}\n\n" if diag else ""

    # Dedup: a flaky report (a Tableau timeout that clears on a re-run) was
    # filing a fresh P2 row EVERY run — Fiber Activations 5x, Captainship
    # Churn 3x in one week — burying the tab in the same transient. If an
    # unresolved 'Run glitch — {report_name}' with the SAME likely-cause was
    # already filed in the last 7 days, return that ID instead of spamming a
    # duplicate. A genuinely NEW error (different cause) still files. Never
    # raises — on any error we fall through and file (a dup beats a lost
    # report). (Megan 2026-06-14)
    _sig = f"Likely cause: {diag[0]}" if diag else ""
    if _sig:
        try:
            _cutoff = (dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
            for _b in _read_bugs():
                if (
                    str(_b.get("Title", "")) == f"Run glitch — {report_name}"
                    and str(_b.get("Status", "")).strip().lower()
                        not in ("resolved", "fixed")
                    and str(_b.get("Submitted At", "")) >= _cutoff
                    and _sig in str(_b.get("Details", ""))
                ):
                    return str(_b.get("ID", ""))
        except Exception:
            pass
    # Self-contained block to paste straight into Claude — everything it needs
    # to act with no back-and-forth. The 20-line error tail REPLACES the old
    # full run-log dump (Megan 2026-06-27: keep the email clean + engaging, not
    # a wall of text); the full log still lives in output/logs on disk.
    _err_tail = "\n".join((log_text or "").strip().splitlines()[-20:]) \
        or "(no log was captured)"
    _cause = diag[0] if diag else "see the error tail below"
    claude_block = (
        "===== PASTE THIS TO CLAUDE TO FIX =====\n"
        f"The Hub report \"{report_name}\" (report_id: {report_id}) failed"
        f"{(' on ' + user) if user else ''}.\n"
        f"What ran: {command or 'n/a'}\n"
        f"Hub version (git SHA): {_hub_git_sha()}\n"
        f"Likely cause: {_cause}\n"
        "Diagnose the root cause from the error below and fix it in the repo. "
        "If it's a transient Tableau/network blip, just re-run it instead. "
        "Error tail:\n"
        f"{_err_tail}\n"
        "===== END ====="
    )
    details = (
        f"⚠️ CAUSE: {_cause}\n\n"
        "🛠️ TO FIX — paste this whole block into Claude:\n\n"
        f"{claude_block}\n\n"
        f"— {report_name} · {dt.datetime.now():%Y-%m-%d %H:%M}"
        f" · {user or 'unknown'} · {_hub_git_sha()}"
    )
    return _add_bug(
        title=f"Run glitch — {report_name}",
        bug_type="Bug / something broke",
        sheet_link=sheet_url,
        loom_link="",
        details=details,
        submitted_by=user or "unknown",
        submitter_email=_member_email(user) or "",
        priority=PRIORITY_OPTIONS[1],
    )


def _file_hub_glitch(ex: BaseException) -> None:
    """Auto-file a Hub-side crash (an uncaught error anywhere in the Hub) as a
    bug report, with the full traceback so it can actually be fixed.

    Deduped per session so a repeating error doesn't spam the tab. Never
    raises — glitch-filing must not itself break the Hub."""
    try:
        if type(ex).__name__ in ("RerunException", "StopException", "RerunData"):
            return  # Streamlit control-flow, not a real error
        import traceback as _tb
        tb = "".join(_tb.format_exception(type(ex), ex, ex.__traceback__))
        sig = f"{type(ex).__name__}:{ex}"[:200]
        seen = st.session_state.setdefault("_hub_glitch_seen", set())
        if sig in seen:
            return
        seen.add(sig)
        view = str(st.session_state.get("view", "?"))
        user = str(st.session_state.get("user", "") or "")
        # Same self-contained "paste to Claude" block as the run-glitch report,
        # so an uncaught Hub crash is one paste to fix too. The 20-line traceback
        # tail replaces the old full-traceback dump (Megan 2026-06-27: keep the
        # email clean, not a wall of text).
        _err_tail = "\n".join(tb.strip().splitlines()[-20:]) or "(no traceback)"
        claude_block = (
            "===== PASTE THIS TO CLAUDE TO FIX =====\n"
            f"The Alphalete Hub (Streamlit, automations/dashboard.py) crashed with "
            f"an uncaught {type(ex).__name__} on the \"{view}\" screen"
            f"{(' for ' + user) if user else ''}.\n"
            f"Error: {sig}\n"
            f"Hub version (git SHA): {_hub_git_sha()}\n"
            "Find the root cause from the traceback below and fix it in the repo "
            "(dashboard.py or a module it calls). Traceback tail:\n"
            f"{_err_tail}\n"
            "===== END ====="
        )
        details = (
            f"⚠️ CAUSE: uncaught {type(ex).__name__} on the '{view}' screen — {sig}\n\n"
            "🛠️ TO FIX — paste this whole block into Claude:\n\n"
            f"{claude_block}\n\n"
            f"— Hub crash · {dt.datetime.now():%Y-%m-%d %H:%M}"
            f" · {user or 'unknown'} · {_hub_git_sha()}"
        )
        _add_bug(
            title=f"Hub glitch — {type(ex).__name__} on '{view}' screen",
            bug_type="Bug / something broke",
            sheet_link="", loom_link="", details=details,
            submitted_by=user or "unknown",
            submitter_email=_member_email(user) or "",
            priority=PRIORITY_OPTIONS[1],
        )
    except Exception:
        pass


# Hook Streamlit's uncaught-exception handler so ANY Hub crash auto-files a
# glitch report (then still shows Streamlit's normal error). Idempotent — the
# marker stops it re-wrapping on each rerun. Wrapped in try/except so a
# Streamlit-internals change can never break the Hub.
try:
    import streamlit.runtime.scriptrunner.exec_code as _st_exec
    import streamlit.runtime.fragment as _st_frag
    if not getattr(_st_exec.handle_uncaught_app_exception, "_hub_patched", False):
        _orig_uncaught = _st_exec.handle_uncaught_app_exception

        def _hub_uncaught(ex: BaseException) -> None:
            _file_hub_glitch(ex)
            _orig_uncaught(ex)

        _hub_uncaught._hub_patched = True
        _st_exec.handle_uncaught_app_exception = _hub_uncaught
        _st_frag.handle_uncaught_app_exception = _hub_uncaught
except Exception:
    pass


def _resurrect_bug(bug_id: str, reason: str) -> bool:
    """Re-open a Fixed bug. Flips status back to In Progress, stamps
    Resurrected At, and stashes the reason in Resurrection Note.
    """
    ws = _bugs_ws()
    try:
        cell = ws.find(str(bug_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    if "Resurrection Note" in BUG_HEADERS:
        ws.update_cell(row, BUG_HEADERS.index("Resurrection Note") + 1, (reason or "").strip())
    if "Resurrected At" in BUG_HEADERS:
        ws.update_cell(
            row,
            BUG_HEADERS.index("Resurrected At") + 1,
            dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    ws.update_cell(row, BUG_HEADERS.index("Status") + 1, "In Progress")
    _read_bugs.clear()
    return True


def _start_bug(bug_id: str) -> bool:
    """Flip an Open bug to 'In Progress' so it moves to the left column.

    No email fires (the Apps Script only emails on Fixed / Needs Info).
    """
    ws = _bugs_ws()
    try:
        cell = ws.find(str(bug_id))
    except Exception:
        return False
    if not cell:
        return False
    ws.update_cell(cell.row, BUG_HEADERS.index("Status") + 1, "In Progress")
    _read_bugs.clear()
    return True


def _resolve_bug(bug_id: str, status: str, note: str) -> bool:
    """Set Status + Resolution Note + Resolved At on a bug row.

    `status` should be 'Fixed' or 'Needs Info'. The Apps Script polls
    this column and emails the submitter when it flips off 'Open'.
    """
    ws = _bugs_ws()
    try:
        cell = ws.find(str(bug_id))
    except Exception:
        return False
    if not cell:
        return False
    row = cell.row
    ws.update_cell(row, BUG_HEADERS.index("Status") + 1, status)
    ws.update_cell(row, BUG_HEADERS.index("Resolution Note") + 1, note)
    ws.update_cell(row, BUG_HEADERS.index("Resolved At") + 1,
                   dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    _read_bugs.clear()
    return True


@st.dialog("➕ Submit a New Automation Request", width="large")
def _show_intake_dialog():
    st.caption("Describe what you need automated. Someone on the team will claim it and build it.")
    with st.form("new_intake_form", clear_on_submit=True):
        title = st.text_input("Report name *", placeholder="e.g. Sales Pipeline Daily")
        sheet_link = st.text_input("Link to the report (Google Sheet) *", placeholder="https://docs.google.com/...")
        loom_link = st.text_input(
            "Link to a video walking through what you need *",
            placeholder="Paste a Loom, YouTube, Google Drive, or screen-recording link",
        )
        additional_links = st.text_area(
            "More links (optional)",
            placeholder="Paste any extra videos or sheets that help.\nOne link per line.",
            height=90,
        )
        description = st.text_area(
            "Goal & details *",
            placeholder="What should this automation do? What problem does it solve? "
                        "What manual work is it replacing? Any tricky bits?",
            height=140,
        )
        cols = st.columns(2)
        with cols[0]:
            # Submitter is picked from the Hub's member list (not free text)
            # so leaderboard stats tie cleanly to a real teammate.
            _member_names = [m["name"] for m in MEMBERS]
            _cur_user = st.session_state.get("user", "") or ""
            _sb_idx = _member_names.index(_cur_user) if _cur_user in _member_names else 0
            submitted_by = st.selectbox("Your name *", _member_names, index=_sb_idx,
                                        key="intake_submitted_by")
        with cols[1]:
            preferred_creator = st.selectbox(
                "Preferred creator (optional)",
                ["No preference"] + [m["name"] for m in MEMBERS],
                key="intake_preferred_creator",
                help="If you have a specific person in mind to build this, pick them. Anyone can still claim it.",
            )
        submitter_email = st.text_input(
            "Your email *",
            placeholder="you@example.com",
            help="We'll use this to message you with any questions we have while working on your request.",
        )
        st.caption(
            "📬 Any questions we have while building your report will be sent to this email."
        )
        currently_runs = st.text_input(
            "Who currently runs this report?",
            placeholder="e.g. Sarah from Sales, or 'me' — anyone, even folks outside the team",
            help="Free text — the person/people doing this manually today. Helps us know who to loop in or onboard.",
        )
        priority = st.selectbox(
            "Priority",
            PRIORITY_OPTIONS,
            index=2,
            key="intake_priority",
            help="How urgent is this? Don't worry, 5 is a real option.",
        )
        # Schedule — how often + what time the finished report should run.
        # Captured here so the Wire-Up form auto-fills the schedule when the
        # builder uploads. A form can't rerun on the radio, so all three
        # detail widgets show at once; submit uses only the relevant ones.
        st.markdown("**📅 When should this report run?**")
        _freq_choice = st.radio(
            "How often?",
            ["Every day", "Certain days each week", "Once a month"],
            key="intake_sched_freq",
            horizontal=True,
        )
        _run_time = st.time_input(
            "What time of day should it run?",
            value=dt.time(8, 0),
            key="intake_sched_time",
        )
        st.caption("If you picked **Certain days each week**, tick those days:")
        _sched_cols = st.columns(7)
        _day_labels = ["M", "T", "W", "Th", "F", "Sa", "Su"]
        _picked_days: list[int] = []
        for _di, _dcol in enumerate(_sched_cols):
            with _dcol:
                st.markdown(
                    f"<div style='text-align:center; font-weight:600'>{_day_labels[_di]}</div>",
                    unsafe_allow_html=True,
                )
                if st.checkbox(" ", key=f"intake_sched_day_{_di}",
                               label_visibility="collapsed"):
                    _picked_days.append(_di)
        _month_day = st.number_input(
            "If you picked Once a month — which day of the month?",
            min_value=1, max_value=31, value=1, step=1,
            key="intake_sched_month_day",
        )
        ok = st.form_submit_button("📨 Submit", type="primary", use_container_width=True)
        if ok:
            _freq_map = {
                "Every day": "daily",
                "Certain days each week": "weekly",
                "Once a month": "monthly",
            }
            _frequency = _freq_map.get(_freq_choice, "daily")
            if not (title and sheet_link and loom_link and description and submitted_by and submitter_email):
                st.error("Please fill in every field marked *.")
            elif _frequency == "weekly" and not _picked_days:
                st.error('You picked "Certain days each week" — tick at least one day below.')
            else:
                pc = "" if preferred_creator == "No preference" else preferred_creator
                # Normalize the additional-links textarea: parse → re-emit canonical
                # 'label | url' lines. Drops blanks and 'n/a' placeholders.
                _extras = "\n".join(
                    f"{lbl} | {url}" if lbl else url
                    for lbl, url in _parse_link_lines(additional_links or "")
                )
                try:
                    _add_intake(
                        title, sheet_link, loom_link, description, submitted_by,
                        pc, currently_runs, priority, submitter_email,
                        additional_links=_extras,
                        schedule_days=(",".join(str(d) for d in _picked_days)
                                       if _frequency == "weekly" else ""),
                        schedule_frequency=_frequency,
                        schedule_time=_fmt_time_str(_run_time),
                        schedule_day_of_month=(str(int(_month_day))
                                               if _frequency == "monthly" else ""),
                    )
                    st.success("✅ Submitted! It will appear on the home page for someone to claim.")
                    st.balloons()
                except Exception as e:
                    import traceback
                    err_text = str(e) or repr(e) or "(no message)"
                    st.error(f"Couldn't save to Sheet: {err_text}")
                    # Most common cause: this user's Google account isn't shared
                    # on the intake Sheet, or they haven't completed OAuth yet.
                    err_low = err_text.lower()
                    if "permission" in err_low or "403" in err_text or "forbidden" in err_low:
                        st.warning(
                            "Looks like a permissions issue. Megan needs to share "
                            "the **Automation Backlog** Sheet with this user's Google "
                            "account (Editor access)."
                        )
                    elif "credential" in err_low or "oauth" in err_low or "token" in err_low:
                        st.warning(
                            "Looks like a Google sign-in issue. This user may need "
                            "to delete their saved OAuth token and sign in again."
                        )
                    with st.expander("🔍 Full error details (for Megan)"):
                        st.code(traceback.format_exc(), language="text")


def _save_uploaded_report(metadata: dict, script_text: str) -> tuple[bool, str]:
    """Publish a wire-up to the SHARED report library (a Google Sheet every Hub
    reads), and cache the script locally so the submitting machine can run it
    immediately. No Git push/pull or collaborator access — the upload is live
    for everyone the moment it's saved. Returns (ok, message)."""
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", metadata["id"]).strip("_").lower()
    if not safe_id:
        return False, "Report id couldn't be derived from name."
    # VALIDATION GATE — every upload (anyone's, including Megan's) passes through
    # here, no exceptions (Megan 2026-05-25). validate_report enforces the
    # block-level auto-checks (syntax, size, Windows compatibility, required
    # metadata) AND the attestations the uploader ticked (carried on
    # metadata['attestations']). On block we return the plain-English reasons so
    # the caller shows the user exactly what to fix.
    from automations.shared.report_validation import validate_report
    _vr = validate_report(script_text, metadata, metadata.get("attestations"))
    if _vr.blocked:
        return False, ("This report can't go live yet — fix these first:\n  • "
                       + "\n  • ".join(_vr.why()))

    metadata["id"] = safe_id
    metadata["module"] = f"{SHARED_SCRIPTS_PKG}.{safe_id}"
    # Cache locally first so this Hub can run it right away.
    try:
        _materialize_shared_script(safe_id, script_text)
    except Exception as e:
        return False, f"Couldn't cache the script locally: {e}"
    # Publish to the shared store → visible + runnable on every Hub.
    ok, msg = _shared_library_upsert(metadata, script_text)
    if not ok:
        return False, f"Saved locally but couldn't publish to the shared library: {msg}"
    return True, msg


# --------------------------------------------------------------------------
# Multi-round report review
# --------------------------------------------------------------------------
# When a creator uploads an automation for an intake request, it does NOT go
# straight to the Report Library. It is STAGED while the requester reviews:
#   In Progress --upload--> In Review --request edits--> Edits Requested
#                              ^                              |
#                              +---------- revise ------------+
#   In Review --approve--> Done  (only now promoted to the Library)
# The staged report (metadata + script) lives in output/pending_reports/
# until the requester approves.
PENDING_REPORTS_DIR = WORKSPACE / "output" / "pending_reports"


def _pending_report_path(intake_id: str) -> Path:
    return PENDING_REPORTS_DIR / f"{intake_id}.json"


def _stage_pending_report(intake_id: str, metadata: dict, script_text: str,
                          review_cc: str = "") -> None:
    """Stash a built-but-not-yet-approved report through the review loop.
    review_cc is carried through and used on the approval email."""
    PENDING_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    _pending_report_path(intake_id).write_text(
        json.dumps({"metadata": metadata, "script": script_text,
                    "review_cc": review_cc}, indent=2)
    )


def _load_pending_report(intake_id: str) -> dict | None:
    """Return {'metadata': ..., 'script': ...} for a staged report, or None."""
    p = _pending_report_path(intake_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _clear_pending_report(intake_id: str) -> None:
    p = _pending_report_path(intake_id)
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass


def _set_intake_status(entry_id: str, status: str) -> bool:
    """Set the Status cell on an intake row. Returns True on success."""
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    ws.update_cell(cell.row, INTAKE_HEADERS.index("Status") + 1, status)
    _read_intake.clear()
    return True


def _git_push_library_addition(report_name: str) -> tuple[bool, str]:
    """Auto-commit + push the new library files (automations/uploaded/<id>.py
    and uploaded_reports.json) so the company repo owns the script, not just
    the local Hub instance. Returns (ok, status_message).

    Megan 2026-05-22: before this, approve-via-Hub stopped at the
    approver's filesystem - the report only existed on their laptop, and
    the company had no way to pull it. JD's Order Log was approved on his
    machine and Megan couldn't see it in her Hub. Auto-push closes the
    gap so 'in the Library' really means 'in the company repo'.
    """
    import subprocess
    try:
        # Stage only the two specific paths - never blanket `git add .`,
        # which would sweep in unrelated working-tree changes (e.g.
        # output/ files, in-flight edits) and create a messy commit.
        subprocess.run(
            ["git", "add", "automations/uploaded/", "uploaded_reports.json"],
            cwd=str(WORKSPACE), check=True, capture_output=True, timeout=20)
        # Check whether there's actually anything staged - a re-approve
        # of an unchanged report wouldn't have any diff.
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(WORKSPACE), capture_output=True, timeout=10)
        if diff.returncode == 0:
            return True, "Already in sync with remote (nothing to commit)"
        subprocess.run(
            ["git", "commit", "-m", f"Library: add {report_name} (approved via Hub)"],
            cwd=str(WORKSPACE), check=True, capture_output=True, timeout=20)
        push = subprocess.run(
            ["git", "push"],
            cwd=str(WORKSPACE), capture_output=True, timeout=60, text=True)
        if push.returncode != 0:
            return False, (
                f"Committed locally but push failed:\n{push.stderr.strip()[:400]}\n"
                "Run `git push` from a terminal to finish syncing."
            )
        return True, "Committed + pushed to remote — anyone who pulls gets it"
    except subprocess.TimeoutExpired as e:
        return False, f"Git command timed out: {e.cmd}. Run git push manually."
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace").strip()[:400]
        return False, f"Git failed at `{' '.join(e.cmd)}`:\n{stderr}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _git_push_screenshot(rel_path: str, report_name: str) -> tuple[bool, str]:
    """Auto-commit + push ONE uploaded screenshot PNG so every teammate's Hub
    shows it on their next relaunch (the launcher hard-pulls origin/main on
    launch). Mirrors _git_push_library_addition but stages only the single PNG,
    and commits with an explicit pathspec so it never sweeps in unrelated
    staged/working-tree edits (Megan's dev machine often has in-flight changes).
    """
    import subprocess
    try:
        # Stage just this PNG (covers both a brand-new file and an overwrite).
        subprocess.run(["git", "add", rel_path], cwd=str(WORKSPACE),
                       check=True, capture_output=True, timeout=20)
        # Nothing changed (re-saving the same image)? Treat as already synced.
        diff = subprocess.run(["git", "diff", "--cached", "--quiet", "--", rel_path],
                              cwd=str(WORKSPACE), capture_output=True, timeout=10)
        if diff.returncode == 0:
            return True, "Already in sync (image unchanged)."
        # Pathspec commit -> only this PNG is committed, even if other paths
        # happen to be staged.
        subprocess.run(["git", "commit", "-m", f"Hub: screenshot for {report_name}",
                        "--", rel_path],
                       cwd=str(WORKSPACE), check=True, capture_output=True, timeout=20)
        push = subprocess.run(["git", "push"], cwd=str(WORKSPACE),
                              capture_output=True, timeout=60, text=True)
        if push.returncode != 0:
            return False, ("Saved + committed locally, but the push failed:\n"
                           f"{(push.stderr or '').strip()[:300]}\n"
                           "Run `git push` from a terminal to finish syncing.")
        return True, "Pushed ✓ — teammates see it on their next Hub relaunch."
    except subprocess.TimeoutExpired as e:
        return False, f"Saved locally; git timed out ({e.cmd}). Run `git push` manually."
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace").strip()[:300]
        return False, f"Saved locally; git failed at `{' '.join(e.cmd)}`:\n{stderr}"
    except Exception as e:
        return False, f"Saved locally; couldn't sync to the repo ({type(e).__name__}: {e})."


def _promote_pending_report(entry_id: str) -> tuple[bool, str]:
    """Requester-approved: promote the staged report into the Report Library
    (uploaded_reports.json + automations/uploaded/<id>.py), mark the intake
    row Done, and clear the staging file. Returns (ok, message)."""
    staged = _load_pending_report(entry_id)
    if not staged:
        return False, "No staged report found — the creator may need to re-upload."
    ok, msg = _save_uploaded_report(staged["metadata"], staged["script"])
    if not ok:
        return False, msg
    try:
        _mark_intake_done(str(entry_id), cc_emails=staged.get("review_cc", ""))
    except Exception:
        pass
    _clear_pending_report(entry_id)
    # Auto-push to the company repo so the new report doesn't live on
    # the approver's laptop alone. Failure here doesn't undo the approve
    # - the files are already saved locally - it just means the user has
    # to run `git push` manually.
    push_ok, push_msg = _git_push_library_addition(
        (staged.get("metadata") or {}).get("name", "report"))
    if push_ok:
        return True, f"Report approved and added to the Library. {push_msg}."
    return True, (
        f"Report approved and added to the Library locally.\n"
        f"⚠️ Auto-push to company repo failed: {push_msg}"
    )


def _parse_time_str(s: str) -> dt.time:
    """Parse a display time string ('8:00 AM') into a datetime.time.
    Falls back to 08:00 if the string is missing or unrecognized."""
    s = (s or "").strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return dt.time(8, 0)


def _fmt_time_str(t: dt.time) -> str:
    """Format a datetime.time as a portable display string ('8:00 AM').
    Hand-built rather than strftime('%-I:%M %p') — the '%-I' no-pad flag
    is invalid on Windows and raises ValueError there."""
    hour = t.hour % 12 or 12
    ampm = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {ampm}"


def _extract_report_breakdown(script_text: str) -> str:
    """Pull a module-level `REPORT_BREAKDOWN = "..."` string constant out
    of an uploaded script, if the creator wrote one. Returns '' if absent
    or the script doesn't parse. Lets the Wire-Up form pre-fill the
    requester cheat-sheet straight from the script (same idea as
    ESTIMATED_MINUTES)."""
    try:
        tree = ast.parse(script_text)
    except SyntaxError:
        return ""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Name) and tgt.id == "REPORT_BREAKDOWN"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                return node.value.value.strip()
    return ""


def _clear_wireup_state() -> None:
    """Drop every wu_* widget key so the dialog re-renders from `value=`
    defaults. Call before opening the dialog so a revise pre-fills from
    the staged report instead of showing stale values from a prior open."""
    for k in list(st.session_state.keys()):
        if k.startswith("wu_"):
            del st.session_state[k]


@st.dialog("🛠️ Wire Up Built Automation", width="large")
def _show_wire_up_dialog(entry: dict | None = None):
    """Form the builder fills out when their automation is built and ready.
    `entry` is the backlog entry; pass None for direct upload of an
    already-built automation that wasn't tracked on the backlog.

    If the entry already has a STAGED report (a prior upload that's in the
    review loop), the form pre-fills from that staged report — so a
    'revise & re-upload' keeps the creator's script, schedule, checklist,
    etc. instead of making them re-enter everything."""
    # A staged report (mid-review revise) takes priority for pre-fill.
    staged = _load_pending_report(str(entry["ID"])) if entry and entry.get("ID") else None
    staged_meta = (staged or {}).get("metadata", {}) if staged else {}
    staged_script = (staged or {}).get("script", "") if staged else ""

    if entry:
        st.markdown(f"**Backlog item:** {entry.get('Title', 'Untitled')}")
        if staged:
            st.caption(
                "Revising after requester feedback — fields are pre-filled "
                "from your last upload. Make the requested edits and re-upload."
            )
        else:
            st.caption(
                "Paste what Claude generated (the Python script + a few details about how/when to run it). "
                "Most fields auto-fill from the backlog entry — change them if needed."
            )
    else:
        st.caption(
            "Paste what Claude generated for an already-built automation. "
            "All fields start blank — fill them in."
        )
    entry = entry or {"ID": "", "Title": "", "Sheet Link": "", "Description": ""}

    # NOTE: this used to be an st.form, but inside a form the radio doesn't
    # trigger a rerun, so the conditional Specific-days vs Monthly UI never
    # updated. Plain widgets fix that — every change reruns immediately.
    _members = [m["name"] for m in MEMBERS]
    # "Who runs" defaults to whoever the requester named in the intake's
    # "Who currently runs this report?" field (if it matches a teammate),
    # or the staged assignee on a revise. The creator can still change it.
    _assignee_opts = ["Not sure yet"] + _members
    _prefill_runner = ""
    _staged_assignees = staged_meta.get("assignees") or []
    if _staged_assignees and _staged_assignees[0] in _members:
        _prefill_runner = _staged_assignees[0]
    else:
        _intake_runner = (entry.get("Currently runs") or "").strip()
        for m in _members:
            if m.lower() == _intake_runner.lower():
                _prefill_runner = m
                break
    _assignee_idx = _assignee_opts.index(_prefill_runner) if _prefill_runner else 0

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Report name *",
                              value=staged_meta.get("name") or entry.get("Title", ""),
                              key="wu_name")
        sheet_url = st.text_input("Sheet URL",
                                  value=staged_meta.get("sheet_url") or entry.get("Sheet Link", ""),
                                  key="wu_sheet_url")
    with col2:
        assignee = st.selectbox(
            "Who runs this report?",
            _assignee_opts,
            index=_assignee_idx,
            key="wu_assignee",
            help="Defaults to who the requester said runs it — change if it should be someone else.",
        )

    # Emoji + one-line description are no longer hand-entered. Emoji
    # defaults (carried over on a revise); description stays blank.
    # Estimated run time is read from the script (ESTIMATED_MINUTES = N)
    # in the submit handler — the builder knows it, the uploader shouldn't
    # have to guess.
    emoji = staged_meta.get("emoji") or "📊"
    description = staged_meta.get("description") or ""

    st.markdown("**📅 Schedule**")
    # Pre-fill from what the requester picked on the intake form.
    _intake_freq = (entry.get("Schedule Frequency") or "").strip().lower()
    _intake_time = (entry.get("Schedule Time") or "").strip()
    _intake_dom = (entry.get("Schedule Day Of Month") or "").strip()
    _staged_sched = staged_meta.get("schedule") or {}
    _monthly_default = (_staged_sched.get("frequency") == "monthly") or (_intake_freq == "monthly")
    sched_mode = st.radio(
        "When does this report run?",
        ["Specific days", "Monthly (on a day of the month)"],
        index=1 if _monthly_default else 0,
        horizontal=True,
        key="wu_sched_mode_radio",
    )

    days_chosen: list[int] = []
    day_of_month: int = 1

    # Default day selection: staged schedule's weekdays if revising, else Tue-Sat.
    # Default day selection priority:
    #   1. staged schedule (revising a prior upload)
    #   2. the days the REQUESTER picked on the intake form
    #   3. Tue-Sat fallback
    _staged_weekdays = set(_staged_sched.get("weekdays", []))
    _intake_days: set[int] = set()
    for _tok in str(entry.get("Schedule Days") or "").split(","):
        _tok = _tok.strip()
        if _tok.isdigit():
            _intake_days.add(int(_tok))
    # 'Every day' on the intake form → all 7 days pre-ticked.
    _freq_fallback = ({0, 1, 2, 3, 4, 5, 6} if _intake_freq == "daily"
                      else {1, 2, 3, 4, 5})
    _default_days = _staged_weekdays or _intake_days or _freq_fallback
    if sched_mode == "Specific days":
        st.caption("Tick every day this report should run.")
        dcols = st.columns(7)
        short_labels = ["M", "T", "W", "Th", "F", "Sa", "Su"]
        for i, col in enumerate(dcols):
            with col:
                st.markdown(f"<div style='text-align:center; font-weight:600; font-size:1.05rem'>{short_labels[i]}</div>", unsafe_allow_html=True)
                if st.checkbox(" ", key=f"wu_sched_day_{i}", label_visibility="collapsed", value=(i in _default_days)):
                    days_chosen.append(i)
    else:
        _dom_default = 1
        if _staged_sched.get("day_of_month"):
            _dom_default = int(_staged_sched["day_of_month"])
        elif _intake_dom.isdigit() and 1 <= int(_intake_dom) <= 31:
            _dom_default = int(_intake_dom)
        day_of_month = st.number_input(
            "Day of the month",
            min_value=1, max_value=31, value=_dom_default, step=1,
            key="wu_day_of_month",
            help="The report will run on this day each month. If the month is shorter, it's skipped (e.g. 31st only runs in long months).",
        )
        st.success(f"📅  This report will appear on the **{_ordinal(int(day_of_month))} of every month** in the assignee's schedule.")

    # Time picker pre-fills from the staged upload, else the requester's
    # intake time, else 8:00 AM. Stored back as a display string.
    _time_default = _parse_time_str(_staged_sched.get("time") or _intake_time or "8:00 AM")
    sched_cols = st.columns(2)
    with sched_cols[0]:
        time_val = st.time_input("Time of day", value=_time_default, key="wu_time_val")
    with sched_cols[1]:
        st.caption("Runs are still triggered manually — this time shows on the report card.")
    time_str = _fmt_time_str(time_val)

    st.markdown("**🐍 Python script** (paste what Claude generated)")
    script_text = st.text_area(
        "Script content *",
        value=staged_script,
        height=260,
        key="wu_script_text",
        placeholder='# Example:\nimport sys\n\ndef main():\n    print("Hello")\n    return 0\n\nif __name__ == "__main__":\n    sys.exit(main())',
        help="Must be valid Python. The dashboard will run it as `python -m automations.uploaded.<name>`.",
    )

    st.markdown("**🌐 Browser login**")
    # Pre-flight steps are no longer hand-typed. If the report scrapes a
    # logged-in website, ticking this box makes the Hub attach the standard
    # pre-flight checklist automatically (launch Report Chrome, then log in).
    _staged_needs_login = bool(staged_meta.get("needs_login")) or bool(staged_meta.get("checklist"))
    needs_login = st.checkbox(
        "This report pulls from a website that needs a login (e.g. ownerville)",
        value=_staged_needs_login,
        key="wu_needs_login",
        help="If ticked, the Hub adds the standard pre-flight steps for you — "
             "launch Report Chrome, then log in. You don't write a checklist.",
    )
    if needs_login:
        st.caption(
            "✅ Pre-flight steps added automatically — **1.** Launch Report "
            "Chrome  **2.** Log into the site in that Chrome window."
        )

    # Follow-up questions / extra info for the requester — goes into the
    # "uploaded for review" email so the requester knows what to check
    # or answer before approving.
    followup_notes = st.text_area(
        "Follow-up questions / additional info for the requester",
        value=staged_meta.get("followup_notes", ""),
        key="wu_followup_notes",
        height=110,
        placeholder=(
            "Anything the requester should know or answer before they review:\n"
            "• 'Confirm the Saturday column should stay hidden until the weekend.'\n"
            "• 'I assumed reps are sorted A-Z — let me know if you want by sales.'"
        ),
        help="Included in the alert email sent to the requester when you upload for review.",
    )

    # Report breakdown — a plain-language cheat-sheet for the requester
    # (tab colors, how to add an ICD, handy functions, pre-flight steps).
    # Pre-fills from a `REPORT_BREAKDOWN = "..."` constant in the script if
    # the creator (Claude) wrote one; the creator can edit before it sends.
    _parsed_breakdown = _extract_report_breakdown(script_text)
    if "wu_breakdown_srcseen" not in st.session_state:
        st.session_state.wu_breakdown_srcseen = script_text
        st.session_state.wu_breakdown = (
            staged_meta.get("breakdown") or _parsed_breakdown or ""
        )
    elif st.session_state.wu_breakdown_srcseen != script_text:
        # Script changed (e.g. the creator just pasted it) → re-derive.
        st.session_state.wu_breakdown_srcseen = script_text
        if _parsed_breakdown:
            st.session_state.wu_breakdown = _parsed_breakdown
    breakdown = st.text_area(
        "📋 Report breakdown — cheat-sheet sent to the requester",
        key="wu_breakdown",
        height=180,
        placeholder=(
            "A plain-language guide for the requester:\n"
            "• What the tab colors mean\n"
            "• How to add an ICD to the report\n"
            "• Handy functions worth knowing\n"
            "• Pre-flight steps before a run"
        ),
        help="Auto-fills from the script's REPORT_BREAKDOWN if present. "
             "Goes into the 'uploaded for review' email to the requester.",
    )

    review_cc = ""
    if entry.get("ID"):
        review_cc = st.text_input(
            "Also CC on the review email (comma-separated, optional)",
            key="wu_review_cc",
            placeholder="alice@example.com, bob@example.com",
            help=(
                "The original requester is always emailed when you upload. "
                "Add anyone else here who should know the report is ready to test."
            ),
        )
        st.caption(
            "Uploading saves the automation to the Report Library, adds it to "
            "the schedule profile card of the person assigned above, marks the "
            "backlog card complete, and emails the requester (plus any CCs above) "
            "to review."
        )
    # ---- Validation gate (Megan 2026-05-25): live script checks + the
    # attestations the uploader must confirm before it can go live. The full
    # check (incl. metadata + these attestations) is re-run as the hard gate in
    # _save_uploaded_report on submit, so nothing can bypass it. ----
    from automations.shared.report_validation import (
        RULES as _VAL_RULES, validate_report as _live_validate)
    _live = _live_validate(
        script_text or "",
        {"name": name, "sheet_url": sheet_url, "schedule": {"_ok": 1},
         "needs_login": needs_login, "breakdown": breakdown})
    _script_fails = [r for r in _live.results
                     if r.rule_id in ("syntax", "size", "windows") and not r.passed]
    if _script_fails:
        st.error("⚠️ This won't pass validation yet:\n"
                 + "\n".join(f"• {r.detail}" for r in _script_fails))
    if _live.warnings:
        st.caption("Heads up (won't block): "
                   + "; ".join(r.detail for r in _live.warnings))
    st.markdown("**Confirm before it goes live:**")
    _attestations = {}
    for _r in _VAL_RULES:
        if _r.kind == "attest":
            _attestations[_r.id] = st.checkbox(_r.label, key=f"wu_att_{_r.id}",
                                               help=_r.help)

    _submit_label = "🔧 Re-upload for Review" if staged else "🚀 Upload & Send for Review"
    submitted = st.button(_submit_label, type="primary", use_container_width=True, key="wu_submit")
    if submitted:
        if not (name and script_text):
            st.error("Please fill every field marked *.")
            return
        # "Not sure yet" → no assignee → report lands in Unassigned section.
        assignees_list: list[str] = [] if assignee == "Not sure yet" else [assignee]

        # Estimated run time is read from the script itself — the builder
        # declares `ESTIMATED_MINUTES = N` (module constant). Falls back to
        # 10 if the script doesn't declare it.
        _est_match = re.search(r"ESTIMATED_MINUTES\s*=\s*(\d+)", script_text)
        est_min = int(_est_match.group(1)) if _est_match else 10

        # Build schedule dict
        if sched_mode.startswith("Monthly"):
            schedule = {
                "frequency": "monthly",
                "day_of_month": int(day_of_month),
                "time": time_str,
                "estimated_minutes": est_min,
            }
        else:
            if not days_chosen:
                st.error("Pick at least one day.")
                return
            freq = "daily" if len(days_chosen) == 7 else "weekly"
            schedule = {
                "frequency": freq,
                "weekdays": sorted(days_chosen),
                "time": time_str,
                "estimated_minutes": est_min,
            }

        # Pre-flight checklist is auto-generated, not hand-typed. A report
        # that needs a browser login gets the standard two steps; otherwise
        # no checklist at all.
        if needs_login:
            checklist = [
                {"text": "Launch Report Chrome", "action": "launch_chrome"},
                {"text": "Log into the website this report pulls from, in "
                         "that Chrome window"},
            ]
        else:
            checklist = []

        # Auto-append owner-access gaps (owners on the Sheet we can't scrape
        # yet, per the report's last run) to the review notes — so the
        # review email tells the reviewer exactly what access to chase down.
        _gap_block = _access_gaps_for_script(script_text)
        if _gap_block and "Owner tabs we can't fully scrape" not in followup_notes:
            followup_notes = (followup_notes.rstrip() + "\n\n" + _gap_block).strip()

        metadata = {
            "id": name,
            "name": name,
            "creator": st.session_state.get("user") or "",
            "emoji": emoji or "📊",
            "description": description,
            "sheet_url": sheet_url,
            "assignees": assignees_list,
            "schedule": schedule,
            "checklist": checklist,
            "needs_login": needs_login,
            "breakdown": breakdown,  # report cheat-sheet for the review email
            "followup_notes": followup_notes,  # carried for revise pre-fill
            "args": [],
            "attestations": _attestations,  # validation-gate human confirmations
        }

        # Validate the script up front (same check _save_uploaded_report runs)
        # so a syntax error is caught before staging.
        try:
            ast.parse(script_text)
        except SyntaxError as e:
            st.error(f"Script has a Python syntax error: {e}")
            return

        # Review process removed 2026-05-24 (Megan: it wasn't working as
        # intended, and uploads got stuck on the submitter's laptop). Uploads
        # now publish straight to the SHARED library (a Google Sheet every Hub
        # reads) — instantly visible + runnable for everyone, no Git, no
        # approval, no collaborator access needed.
        ok, msg = _save_uploaded_report(metadata, script_text)
        if not ok:
            st.error(msg)
            return
        if entry.get("ID"):
            # Record the breakdown / notes on the intake row, then close it out.
            try:
                _iws = _intake_ws()
                _icell = _iws.find(str(entry["ID"]))
                if _icell:
                    if "Review Notes" in INTAKE_HEADERS:
                        _iws.update_cell(_icell.row,
                                         INTAKE_HEADERS.index("Review Notes") + 1,
                                         followup_notes.strip())
                    if "Report Breakdown" in INTAKE_HEADERS:
                        _iws.update_cell(_icell.row,
                                         INTAKE_HEADERS.index("Report Breakdown") + 1,
                                         breakdown.strip())
            except Exception:
                pass
            try:
                _mark_intake_done(str(entry["ID"]), cc_emails=review_cc)
            except Exception:
                pass
        target_text = (
            "in the **🔍 Unassigned** section of the Report Library"
            if assignee == "Not sure yet"
            else f"on **{assignee}**'s dashboard"
        )
        st.success(f"✅ Published live — it's now {target_text} for the whole "
                   f"team, instantly. No commit/push needed.")
        st.balloons()


def _priority_rank(p: str) -> int:
    """Sort key from a priority string. Lower = more urgent.

    Priorities are stored as '1 — 🚨 URGENT…', '2 — 🔥 High…', etc.
    Empty / unrecognized priorities sort to the end so urgent items
    bubble to the top of any list.
    """
    s = (p or "").strip()
    if s and s[0].isdigit():
        try:
            return int(s[0])
        except ValueError:
            pass
    return 99


def _priority_pill_html(p: str) -> str:
    """Inline HTML pill for the priority level, color-coded by urgency.

    Returns empty string when the entry has no recorded priority so the
    card doesn't render a stray gray chip for legacy rows.
    """
    s = (p or "").strip()
    if not s:
        return ""
    rank = _priority_rank(s)
    palette = {
        1: ("#FDE2E1", "#8B1A22"),  # red — URGENT
        2: ("#FFE6CC", "#9C4A00"),  # orange — High
        3: ("#FFF3D6", "#8B6914"),  # gold — Medium
        4: ("#E2F4E6", "#1F7A3D"),  # green — Low
        5: ("#EEEEEE", "#555555"),  # gray — When pigs fly
    }
    bg, fg = palette.get(rank, ("#EEEEEE", "#555555"))
    return (
        f"<span style='display:inline-block; background:{bg}; color:{fg}; "
        f"padding:3px 10px; border-radius:999px; font-size:0.85em; "
        f"font-weight:700; margin:0 0 0.3rem'>{s}</span>"
    )


def _render_review_panel(entry: dict) -> None:
    """cols[1] content for a card mid-review (In Review / Edits Requested).
    Shows the staged report summary + the requester's review actions."""
    eid = str(entry["ID"])
    status = entry.get("Status", "")
    staged = _load_pending_report(eid)
    if not staged:
        st.warning("No staged report found — ask the creator to re-upload it.")
        return
    meta = staged.get("metadata", {})

    st.markdown(f"**{meta.get('emoji', '📊')} {meta.get('name', '(unnamed report)')}**")
    if meta.get("description"):
        st.caption(meta["description"][:160])
    sched = meta.get("schedule", {})
    _daynames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    _days = sched.get("weekdays", [])
    _when = (", ".join(_daynames[d] for d in _days if 0 <= d < 7)
             if _days else sched.get("frequency", "—"))
    _who = (meta.get("assignees") or ["Unassigned"])[0]
    st.caption(f"📅 {_when}  ·  👤 {_who}")

    if status == "In Review":
        _requester = entry.get("Submitted By") or "Requester"
        st.markdown(f"**{_requester}:** review, then approve or request edits.")

        # The staged report isn't in the Library yet — give it a runnable
        # identity (matches the safe_id _save_uploaded_report computes on
        # approve) so the reviewer can actually run it before approving.
        _safe_id = (re.sub(r"[^a-zA-Z0-9_]", "_", str(meta.get("id") or eid))
                    .strip("_").lower()) or f"review_{eid}"
        _review_report = {"id": _safe_id, "name": meta.get("name", "report"),
                          "sheet_url": meta.get("sheet_url", "")}

        # A review run already in flight → show the live progress panel.
        _active = next((a for a in _read_active_runs()
                        if a.get("report_id") == _safe_id), None)
        if _active:
            _render_active_run_panel(_review_report, _active)
            return

        _rs = _load_all_run_state().get(_safe_id) or {}
        _reviewed_ok = _rs.get("status") == "success"

        if _reviewed_ok:
            st.success("✅ Test run finished — you've seen it work. Ready to approve.")
            if st.button("✅ Approve & Upload to HUB", key=f"approve_{eid}",
                         use_container_width=True, type="primary"):
                ok, msg = _promote_pending_report(eid)
                if ok:
                    try:
                        _append_intake_note(
                            eid, "✅ Approved by requester — uploaded to the HUB.",
                            st.session_state.get("user", "") or "requester")
                    except Exception:
                        pass
                    st.session_state.pop(f"reviewing_{eid}", None)
                    st.success(msg)
                    st.balloons()
                    st.rerun()
                else:
                    st.error(msg)
        elif st.session_state.get(f"reviewing_{eid}"):
            # Step 2 — pre-flight, then run the report for real.
            # Reports self-log-in via patchright — only check the debug Chrome
            # for a card that explicitly opts in with needs_chrome.
            _needs_login = bool(meta.get("needs_login") or meta.get("checklist"))
            _needs_chrome = bool(meta.get("needs_chrome"))
            _chrome_ok = _check_chrome_running() if _needs_chrome else True
            if _needs_chrome:
                st.markdown(
                    "**Pre-flight — do this first:**\n\n"
                    "1. Launch Report Chrome\n"
                    "2. Log into the website this report pulls from, in that window."
                )
                if not _chrome_ok:
                    if st.button("🚀 Launch Report Chrome", key=f"rv_chrome_{eid}",
                                 use_container_width=True):
                        _launch_chrome()
                        st.rerun()
                    st.caption("Launch Chrome + log in, then the Run button turns on.")
                else:
                    st.caption("✅ Chrome detected — confirm you're logged in, then run.")
            if _rs.get("status") == "failed":
                _diag = _diagnose_run_failure(
                    _tail_log(ACTIVE_RUNS_LOG_DIR / f"{_safe_id}.log"))
                st.error("❌ The last run failed. "
                         + (_diag[1] if _diag
                            else "Try Run again, or send it back with Request Edits."))
                # Self-heal for OAuth lockouts (same convention as the main
                # report failure callout — one-click reset).
                if _is_oauth_failure(_diag):
                    _rv_msg_key = f"oauth_reset_msg_rv_{eid}"
                    if _rv_msg_key in st.session_state:
                        _ok, _msg = st.session_state[_rv_msg_key]
                        (st.success if _ok else st.error)(_msg)
                    if st.button("🔄 Reset Google Sign-In",
                                 key=f"oauth_reset_rv_{eid}",
                                 help="One-click fix — clears the expired "
                                      "Google token so the next Run prompts "
                                      "a fresh sign-in."):
                        st.session_state[_rv_msg_key] = _reset_oauth_token()
                        st.rerun()
            if st.button("▶ Run the report", key=f"rv_run_{eid}",
                         use_container_width=True, type="primary",
                         disabled=not _chrome_ok):
                try:
                    UPLOADED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
                    _init = UPLOADED_SCRIPTS_DIR / "__init__.py"
                    if not _init.exists():
                        _init.write_text("")
                    (UPLOADED_SCRIPTS_DIR / f"{_safe_id}.py").write_text(
                        staged.get("script", ""))
                except Exception as e:
                    st.error(f"Couldn't stage the script to run: {e}")
                else:
                    _execute_action(
                        _review_report,
                        {"label": "Review run",
                         "module": f"automations.uploaded.{_safe_id}",
                         "args_fn": lambda: []},
                        None, _chrome_ok,
                    )
        else:
            # Step 1 — the Review button.
            _creator = entry.get("Assigned To") or "the creator"
            st.markdown(
                "👀 **Review it:** run the report once to confirm it works. "
                "The Approve button unlocks after a successful run.\n\n"
                "Spot a glitch, a flaw, or anything you'd change? Use "
                f"**📝 Request Edits** below to send it back to **{_creator}** "
                "with your notes."
            )
            if st.button("🔍 Review the report", key=f"startreview_{eid}",
                         use_container_width=True, type="primary"):
                st.session_state[f"reviewing_{eid}"] = True
                st.rerun()

        # Request Edits — sits below the review actions. Available at any
        # point: spotting a flaw before/after running both count.
        with st.popover("📝 Request Edits", use_container_width=True):
            _edit = st.text_area(
                "What needs to change?", key=f"edit_req_{eid}",
                placeholder="Describe the edits you'd like the creator to make…",
            )
            _author = st.text_input(
                "Your name", key=f"edit_author_{eid}",
                value=st.session_state.get("user", "") or "",
            )
            if st.button("Send edits to creator", key=f"edit_send_{eid}",
                         use_container_width=True):
                if not (_edit or "").strip():
                    st.error("Describe the edits first.")
                elif not (_author or "").strip():
                    st.error("Add your name.")
                else:
                    _txt = _edit.strip()
                    _append_intake_note(eid, f"📝 Edits requested: {_txt}", _author)
                    # Stash the edit text where the Apps Script can read it
                    # for the "edits requested" email to the creator.
                    try:
                        _iws = _intake_ws()
                        _ic = _iws.find(eid)
                        if _ic and "Edit Request" in INTAKE_HEADERS:
                            _iws.update_cell(
                                _ic.row,
                                INTAKE_HEADERS.index("Edit Request") + 1, _txt)
                    except Exception:
                        pass
                    _set_intake_status(eid, "Edits Requested")
                    st.rerun()
    elif status == "Edits Requested":
        st.info("⏳ Edits requested — waiting on the creator to revise.")
        if st.button("🔧 Revise & Re-upload", key=f"revise_{eid}",
                     use_container_width=True, type="primary"):
            _clear_wireup_state()
            _show_wire_up_dialog(entry)


def _render_intake_card(entry: dict, allow_claim: bool = True, allow_done: bool = False,
                        review_mode: bool = False) -> None:
    """Render one backlog entry. review_mode=True renders the requester
    review panel (for In Review / Edits Requested cards)."""
    with st.container(border=True):
        # Resurrected banner sits above everything so it's the first thing you
        # see on a re-opened card. Pulled from the row's Resurrected At column.
        if (entry.get("Resurrected At") or "").strip():
            st.markdown(
                "<div style='background:#FFE6CC; color:#8B1A22; padding:8px 14px; "
                "border-radius:8px; border-left:4px solid #B8232C; font-weight:700; "
                "margin-bottom:0.6rem'>"
                f"🔄 RESURRECTED on {entry.get('Resurrected At')} — needs additional work"
                "</div>",
                unsafe_allow_html=True,
            )
        cols = st.columns([5, 2])
        with cols[0]:
            st.markdown(f"### {entry.get('Title', 'Untitled')}")
            _priority_html = _priority_pill_html(entry.get("Priority", ""))
            if _priority_html:
                st.markdown(_priority_html, unsafe_allow_html=True)
            preferred = entry.get("Preferred Creator", "")
            if preferred:
                if allow_done:
                    # In Progress side — show as compact text since the card
                    # is already claimed and this is just reference info.
                    st.markdown(
                        f"<span style='font-size:0.78em; color:#777'>"
                        f"👋 Requested for <b>{preferred}</b></span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(f"<span class='pill pill-info'>👋 Requested for: {preferred}</span>",
                                unsafe_allow_html=True)
            if entry.get("Assigned To"):
                st.markdown(
                    f"<div style='background:#FFF3D6; color:#5C4220; padding:6px 12px; "
                    f"border-radius:8px; font-weight:700; margin:0.4rem 0 0.5rem; "
                    f"display:inline-block'>"
                    f"🛠️ Being worked on by {entry['Assigned To']}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='font-size:0.95rem; margin:0 0 0.3rem'>"
                    f"👤 Requested by <b>{entry.get('Submitted By') or '—'}</b></div>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"Submitted {entry.get('Submitted At', '?')} "
                    f"• Claimed {entry.get('Assigned At', '')}"
                )
            else:
                st.caption(
                    f"Submitted by **{entry.get('Submitted By', '?')}** on {entry.get('Submitted At', '?')}"
                )
            # Build the flat list of link buttons to show on the card. Each
            # is (label, url). The two primary fields (Sheet Link, Loom Link)
            # come first; then anything in Additional Links (labeled or not).
            def _render_link_buttons():
                _btns: list[tuple[str, str]] = []
                if entry.get("Sheet Link"):
                    _btns.append(("📂 Open Sheet", entry["Sheet Link"]))
                if entry.get("Loom Link"):
                    _btns.append(("▶️ Watch video", entry["Loom Link"]))
                for _lbl, _url in _parse_link_lines(entry.get("Additional Links") or ""):
                    _btns.append((f"🔗 {_lbl or _label_for_url(_url)}", _url))
                if not _btns:
                    return
                # Two-column layout — rows of 2 buttons.
                for i in range(0, len(_btns), 2):
                    _row = st.columns(2)
                    for j, (_lbl, _url) in enumerate(_btns[i:i+2]):
                        with _row[j]:
                            _safe_link_button(_lbl, _url, use_container_width=True)

            if entry.get("Description"):
                with st.expander("Project Details"):
                    st.markdown(entry["Description"])
                    _render_link_buttons()
            else:
                _render_link_buttons()

            # Notes — anyone can add a timestamped note to the project card.
            _existing_notes = (entry.get("Notes") or "").strip()
            _note_count = _existing_notes.count("\n\n") + 1 if _existing_notes else 0
            _notes_label = f"📝 Notes ({_note_count})" if _note_count else "📝 Notes"
            with st.expander(_notes_label):
                if _existing_notes:
                    st.markdown(
                        "\n\n".join(
                            f"<div style='background:#FAFAFA; padding:8px 12px; "
                            f"border-left:3px solid #C9A85C; border-radius:4px; "
                            f"margin-bottom:6px; font-size:0.9em; white-space:pre-wrap'>"
                            f"{line}</div>"
                            for line in _existing_notes.split("\n\n")
                            if line.strip()
                        ),
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No notes yet. Add the first one below.")
                _new_note = st.text_area(
                    "New note",
                    key=f"note_input_{entry['ID']}",
                    height=70,
                    label_visibility="collapsed",
                    placeholder="Status update, question, blocker, etc.",
                )
                _note_author = st.text_input(
                    "Your name",
                    key=f"note_author_{entry['ID']}",
                    value=st.session_state.get("user", "") or "",
                    placeholder="Your name",
                    label_visibility="collapsed",
                )
                if st.button("➕ Add note", key=f"note_save_{entry['ID']}", use_container_width=True):
                    if not (_new_note or "").strip():
                        st.error("Add a note first.")
                    elif not (_note_author or "").strip():
                        st.error("Add your name so others know who wrote it.")
                    elif _append_intake_note(str(entry["ID"]), _new_note, _note_author):
                        st.success("Note added.")
                        st.rerun()
                    else:
                        st.error("Couldn't save the note — try again.")

                # Attach an additional link to this card — video, sheet, doc,
                # whatever. Single URL input; the button label is auto-derived
                # from the host so it's still scannable in the button row.
                st.markdown("---")
                _link_url = st.text_input(
                    "🔗 Attach a link to a sheet or video",
                    key=f"link_url_{entry['ID']}",
                    placeholder="Paste any URL — Loom, YouTube, Drive, Sheet, …",
                )
                if st.button("➕ Attach link", key=f"link_save_{entry['ID']}", use_container_width=True):
                    if not (_link_url or "").strip():
                        st.error("Paste a URL first.")
                    elif _append_intake_link(str(entry["ID"]), _link_url, _label_for_url(_link_url)):
                        st.success("Link attached.")
                        st.rerun()
                    else:
                        st.error("Couldn't save the link — try again.")
        with cols[1]:
            if allow_claim:
                claim_to = st.selectbox(
                    "Claim for…",
                    ["— claim project —"] + [m["name"] for m in MEMBERS],
                    key=f"claim_pick_{entry['ID']}",
                    label_visibility="collapsed",
                )
                if claim_to and claim_to != "— claim project —":
                    if st.button("🤝 Claim", key=f"claim_btn_{entry['ID']}", use_container_width=True, type="primary"):
                        if _assign_intake(str(entry["ID"]), claim_to):
                            st.success(f"Claimed by {claim_to}")
                            st.rerun()
                        else:
                            st.error("Couldn't claim — please try again.")
            if allow_done:
                if st.button(
                    "📥 Upload the Automation",
                    key=f"wireup_{entry['ID']}",
                    use_container_width=True,
                    type="primary",
                ):
                    _clear_wireup_state()
                    _show_wire_up_dialog(entry)
                # Gmail compose URL — opens Gmail in the browser (not the
                # native Mail app) so the user doesn't have to swap clients.
                requester_email = (entry.get("Submitter Email") or "").strip()
                if requester_email:
                    _gmail_url = _gmail_compose_url(
                        to=requester_email,
                        subject=f"Re: {entry.get('Title', '')}",
                        body=(
                            f"Hi {entry.get('Submitted By', 'there')},\n\n"
                            f"I'm working on your automation request and had a quick question:\n\n\n\n"
                            f"Thanks!\n"
                        ),
                    )
                    st.link_button(
                        "✉️ Ask requester a question",
                        _gmail_url,
                        use_container_width=True,
                        help=f"Opens Gmail addressed to {requester_email}",
                    )

                # Anyone can ping the claimer for a status update. Captures the
                # asker's email so the claimer knows who to reply to, and
                # auto-CCs the original requester so they see the thread.
                claimer = entry.get("Assigned To") or ""
                claimer_email = _member_email(claimer)
                with st.popover("📨 Ask for an update", use_container_width=True):
                    st.caption(
                        f"Sends a quick check-in to **{claimer or 'the claimer'}**"
                        + (
                            f" and CCs the original requester at **{requester_email}**"
                            if requester_email else ""
                        )
                        + "."
                    )
                    asker_email = st.text_input(
                        "Your email (optional)",
                        key=f"asker_email_{entry['ID']}",
                        placeholder="you@example.com",
                        help=(
                            "If you're not the original requester but would still "
                            "like an update, drop your email here and the claimer's "
                            "reply will include you."
                        ),
                    )
                    if not claimer_email:
                        st.warning(
                            f"No email on file for {claimer or 'this person'}. "
                            "Add one in the MEMBERS list to enable one-click pre-fill."
                        )
                    _title = entry.get("Title", "")
                    _body_lines = [
                        f"Hi {claimer or 'there'},",
                        "",
                        f"Quick check-in on '{_title}' — when do you think it'll be ready?",
                        "",
                        "Thanks!",
                    ]
                    if asker_email:
                        _body_lines.append(f"(Reply directly to: {asker_email})")
                    _gmail_update_url = _gmail_compose_url(
                        to=claimer_email or "",
                        cc=requester_email or "",
                        subject=f"Quick check-in: {_title}",
                        body="\n".join(_body_lines),
                    )
                    st.link_button(
                        "📤 Open in Gmail",
                        _gmail_update_url,
                        use_container_width=True,
                        help="Drafts the email in Gmail. Fill in any blank \"To\" "
                             "if the claimer's email isn't on file yet.",
                    )

                # Unclaim — if someone grabbed this by mistake, send it
                # straight back to the Unassigned section.
                if st.button("↩️ Unclaim — send back to Unassigned",
                             key=f"unclaim_{entry['ID']}",
                             use_container_width=True,
                             help="Clears the assignee and returns this "
                                  "request to the Unassigned section."):
                    if _unassign_intake(str(entry["ID"])):
                        st.success("Unclaimed — moved back to Unassigned.")
                        st.rerun()
                    else:
                        st.error("Couldn't unclaim — please try again.")

        # The review panel's instructions are too long to read crammed in the
        # narrow right column — render it full-width below the card instead.
        if review_mode:
            st.markdown("---")
            _render_review_panel(entry)


def _format_elapsed(start_str: str, end_str: str) -> str:
    """Pretty-print the gap between two 'YYYY-MM-DD HH:MM' timestamps.

    Returns '' if either timestamp can't be parsed. Format adjusts to the
    magnitude: minutes, hours+minutes, or days+hours.
    """
    fmts = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M")
    def _parse(s: str):
        s = (s or "").strip()
        if not s:
            return None
        for f in fmts:
            try:
                return dt.datetime.strptime(s, f)
            except ValueError:
                continue
        return None
    start, end = _parse(start_str), _parse(end_str)
    if not start or not end or end < start:
        return ""
    delta = end - start
    total_min = int(delta.total_seconds() // 60)
    if total_min < 60:
        return f"{total_min}m"
    if total_min < 60 * 24:
        return f"{total_min // 60}h {total_min % 60}m"
    days = total_min // (60 * 24)
    rem_hours = (total_min % (60 * 24)) // 60
    return f"{days}d {rem_hours}h"


def _render_needs_updates_card(entry: dict) -> None:
    """Resurrected backlog entry waiting to be claimed for updates.

    Visually distinct from In Progress (red banner) so the assignee — and
    anyone else passing through — sees that this is a re-opened project
    that hasn't been picked up yet.
    """
    entry_id = str(entry.get("ID", ""))
    with st.container(border=True):
        st.markdown(
            "<div style='background:#FFE6CC; color:#8B1A22; padding:8px 14px; "
            "border-radius:8px; border-left:4px solid #B8232C; font-weight:700; "
            "margin-bottom:0.6rem'>"
            f"🚨 UPDATES NEEDED — resurrected on {entry.get('Resurrected At') or '?'}"
            "</div>",
            unsafe_allow_html=True,
        )
        cols = st.columns([5, 2])
        with cols[0]:
            st.markdown(f"### {entry.get('Title', 'Untitled')}")
            _priority_html = _priority_pill_html(entry.get("Priority", ""))
            if _priority_html:
                st.markdown(_priority_html, unsafe_allow_html=True)
            previous_assignee = entry.get("Assigned To", "")
            if previous_assignee:
                st.markdown(
                    f"<span style='font-size:0.9em; color:#5C4220'>"
                    f"Previously built by <b>{previous_assignee}</b></span>",
                    unsafe_allow_html=True,
                )
            # Surface the latest note (which is the resurrection reason) so the
            # ask is visible without expanding anything.
            _notes = (entry.get("Notes") or "").strip()
            if _notes:
                _latest = _notes.split("\n\n")[-1]
                st.markdown(
                    f"<div style='background:#FAFAFA; padding:8px 12px; "
                    f"border-left:3px solid #C9A85C; border-radius:4px; "
                    f"margin:0.4rem 0; font-size:0.9em; white-space:pre-wrap'>"
                    f"{_latest}</div>",
                    unsafe_allow_html=True,
                )
        with cols[1]:
            claim_to = st.selectbox(
                "Claim updates for…",
                ["— claim updates —"] + [m["name"] for m in MEMBERS],
                key=f"updates_claim_pick_{entry_id}",
                label_visibility="collapsed",
            )
            if claim_to and claim_to != "— claim updates —":
                if st.button(
                    "🤝 Claim Updates",
                    key=f"updates_claim_btn_{entry_id}",
                    use_container_width=True,
                    type="primary",
                ):
                    if _claim_intake_updates(entry_id, claim_to):
                        st.success(f"Claimed by {claim_to} — moving to In Progress.")
                        st.rerun()
                    else:
                        st.error("Couldn't update — please try again.")


def _render_completed_intake_card(entry: dict) -> None:
    """Compact read-only summary of a Done backlog entry."""
    entry_id = str(entry.get("ID", ""))
    with st.container(border=True):
        title = entry.get("Title", "Untitled")
        assignee = entry.get("Assigned To", "?")
        submitted_by = entry.get("Submitted By", "?")
        priority_pill = _priority_pill_html(entry.get("Priority", ""))
        st.markdown(
            f"**✅ {title}**"
            + ("  \n" + priority_pill if priority_pill else "")
            + f"<br/><span style='color:#777; font-size:0.85em'>"
            f"Built by <b>{assignee}</b> • Requested by {submitted_by}"
            f"</span>",
            unsafe_allow_html=True,
        )
        with st.expander("Project summary"):
            submitted_at = (entry.get("Submitted At") or "").strip()
            completed_at = (entry.get("Completed At") or entry.get("Assigned At") or "").strip()
            elapsed = _format_elapsed(submitted_at, completed_at)

            # Claim history. Prefer the explicit column when present; fall
            # back to the single Assigned To entry for older rows.
            claim_history_raw = (entry.get("Claim History") or "").strip()
            if claim_history_raw:
                claim_lines = [ln.strip() for ln in claim_history_raw.splitlines() if ln.strip()]
            elif assignee and assignee != "?":
                claim_lines = [f"{assignee} | {entry.get('Assigned At', '')}"]
            else:
                claim_lines = []

            timeline_rows = [
                f"<b>👤 Requested by:</b> {submitted_by}",
                f"<b>📨 Requested at:</b> {submitted_at or '?'}",
            ]
            if claim_lines:
                if len(claim_lines) == 1:
                    timeline_rows.append(f"<b>🤝 Claimed by:</b> {claim_lines[0]}")
                else:
                    inner = "<br/>&nbsp;&nbsp;• " + "<br/>&nbsp;&nbsp;• ".join(claim_lines)
                    timeline_rows.append(f"<b>🤝 Claimed by ({len(claim_lines)} times):</b>{inner}")
            timeline_rows.append(f"<b>✅ Completed at:</b> {completed_at or '?'}")
            if elapsed:
                timeline_rows.append(f"<b>⏱️ Total time to complete:</b> {elapsed}")

            st.markdown(
                "<div style='font-size:0.9em; line-height:1.7'>"
                + "<br/>".join(timeline_rows)
                + "</div>",
                unsafe_allow_html=True,
            )

            if entry.get("Description"):
                st.markdown("---")
                st.markdown("**📝 Project description**")
                st.markdown(entry["Description"])
            if entry.get("Sheet Link"):
                _safe_link_button("📂 Open Sheet", entry["Sheet Link"], use_container_width=True)
        with st.popover("🔄 Resurrect this project", use_container_width=True):
            st.caption(
                "Move this back to In Progress to flag a needed update, fix, or "
                "edit. The card will reappear in the active list with a banner."
            )
            _r_reason = st.text_area(
                "What needs to change?",
                key=f"resurrect_reason_{entry_id}",
                height=80,
                placeholder="e.g. column heading changed, dates are off, etc.",
            )
            _r_author = st.text_input(
                "Your name",
                key=f"resurrect_author_{entry_id}",
                value=st.session_state.get("user", "") or "",
                placeholder="Your name",
            )
            if st.button(
                "🔄 Resurrect",
                key=f"resurrect_btn_{entry_id}",
                use_container_width=True,
                type="primary",
            ):
                if not (_r_reason or "").strip():
                    st.error("Add a reason so the builder knows what to do.")
                elif not (_r_author or "").strip():
                    st.error("Add your name so the builder knows who to follow up with.")
                elif _resurrect_intake(entry_id, _r_reason, _r_author):
                    st.success("Card moved back to In Progress.")
                    st.rerun()
                else:
                    st.error("Couldn't resurrect — try again.")


def _render_completed_bug_card(entry: dict) -> None:
    """Compact read-only summary of a Fixed bug or site-edit suggestion."""
    bug_id = str(entry.get("ID", ""))
    bug_type = entry.get("Type", "")
    type_emoji = "💡" if "Site" in bug_type else "🐛" if "Bug" in bug_type else "✏️"
    with st.container(border=True):
        st.markdown(
            f"**{type_emoji} {entry.get('Title', 'Untitled')}**  \n"
            f"<span style='color:#777; font-size:0.85em'>"
            f"Reported by <b>{entry.get('Submitted By', '?')}</b>"
            f"</span>",
            unsafe_allow_html=True,
        )
        if entry.get("Resolution Note"):
            with st.expander("Resolution note"):
                st.write(entry["Resolution Note"])
        if entry.get("Details"):
            with st.expander("Original report"):
                st.write(entry["Details"])
        with st.popover("🔄 Resurrect this", use_container_width=True):
            st.caption(
                "Move this back to In Progress to flag that it still needs work."
            )
            _b_reason = st.text_area(
                "What's still wrong?",
                key=f"resurrect_bug_reason_{bug_id}",
                height=80,
                placeholder="e.g. fix didn't stick, another instance just popped up, etc.",
            )
            if st.button(
                "🔄 Resurrect",
                key=f"resurrect_bug_btn_{bug_id}",
                use_container_width=True,
                type="primary",
            ):
                if not (_b_reason or "").strip():
                    st.error("Add a reason so Megan knows what's needed.")
                elif _resurrect_bug(bug_id, _b_reason):
                    st.success("Bug moved back to In Progress.")
                    st.rerun()
                else:
                    st.error("Couldn't resurrect — try again.")


def _render_bug_card(entry: dict) -> None:
    """Condensed card for the right-hand Bug Reports section."""
    bug_id = str(entry.get("ID", ""))
    status = entry.get("Status") or "Open"
    bug_type = entry.get("Type", "")
    priority = entry.get("Priority", "")
    type_emoji = "💡" if "Site" in bug_type else "🐛" if "Bug" in bug_type else "✏️"

    # Bug triage is admin-only (Megan + Eve as of 2026-05-28). Other people
    # on the hub can still see the bugs (for visibility), but the action
    # buttons are hidden so only admins can move them between states.
    _is_admin = (_detect_hub_user() or "").strip().lower() in {"megan", "eve"}

    with st.container(border=True):
        _priority_html = _priority_pill_html(priority)
        st.markdown(
            f"**{type_emoji} {entry.get('Title', 'Untitled')}**  \n"
            + (_priority_html + "<br/>" if _priority_html else "")
            + f"<span style='color:#777; font-size:0.85em'>"
            f"{entry.get('Submitted By', '?')} • {entry.get('Submitted At', '')}"
            f"</span>",
            unsafe_allow_html=True,
        )
        if entry.get("Details"):
            with st.expander("Details"):
                st.write(entry["Details"])
                link_row = st.columns(2)
                with link_row[0]:
                    sl = (entry.get("Sheet Link") or "").strip()
                    if sl and sl.lower() != "n/a":
                        st.link_button("📂 Sheet", sl, use_container_width=True)
                with link_row[1]:
                    ll = (entry.get("Loom Link") or "").strip()
                    if ll and ll.lower() != "n/a":
                        st.link_button("▶️ Loom", ll, use_container_width=True)

        if status == "Open":
            if _is_admin:
                if st.button(
                    "👀 I've Seen This — Working On It",
                    key=f"bug_start_{bug_id}",
                    use_container_width=True,
                    type="primary",
                    help="Moves the bug to In Progress and emails the requester a heads-up that you've seen it.",
                ):
                    if _start_bug(bug_id):
                        st.success("Moved to In Progress — heads-up email going out shortly.")
                        st.rerun()
                    else:
                        st.error("Couldn't update — try again.")
            else:
                st.caption("⏳ Waiting on triage.")
        elif status == "In Progress" or status == "Needs Info":
            if _is_admin:
                note = st.text_input(
                    "Note to requester (sent in the email)",
                    key=f"bug_note_{bug_id}",
                    placeholder="What did you fix? Or what do you need to know?",
                    label_visibility="collapsed",
                )
                btn_cols = st.columns(2)
                with btn_cols[0]:
                    if st.button("✅ Mark Fixed", key=f"bug_fix_{bug_id}", use_container_width=True, type="primary"):
                        if _resolve_bug(bug_id, "Fixed", note or ""):
                            st.success("Marked Fixed — email going out shortly.")
                            st.rerun()
                        else:
                            st.error("Couldn't update — try again.")
                with btn_cols[1]:
                    if st.button("❓ Need More Info?", key=f"bug_info_{bug_id}", use_container_width=True):
                        if not (note or "").strip():
                            st.error("Add a note so the requester knows what you need.")
                        elif _resolve_bug(bug_id, "Needs Info", note):
                            st.success("Email going out shortly.")
                            st.rerun()
            else:
                st.caption(f"⏳ Triage in progress — current status: **{status}**.")
        else:
            badge = "✅ Fixed" if status == "Fixed" else f"⏳ {status}"
            st.caption(badge)
            if entry.get("Resolution Note"):
                st.caption(f"Note: {entry['Resolution Note']}")


def _format_schedule_short(report: dict) -> str:
    """One-line schedule summary for compact lists.

    Examples:
        Mon Wed Fri at 8:00 AM
        Daily at 9:00 AM
        15th of each month at 8:00 AM
    """
    sched = report.get("schedule") or {}
    freq = sched.get("frequency", "")
    time_str = (sched.get("time") or "").strip()
    time_part = f" at {time_str}" if time_str else ""
    if freq == "monthly":
        dom = sched.get("day_of_month")
        if dom:
            return f"{_ordinal(int(dom))} of each month{time_part}"
        return f"Monthly{time_part}"
    if freq == "daily":
        return f"Daily{time_part}"
    weekdays = sched.get("weekdays") or []
    if not weekdays:
        return "(no schedule set)"
    day_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = " ".join(day_short[d] for d in sorted(weekdays))
    return f"{days}{time_part}"


def _render_bug_typed_view(
    *,
    type_keyword: str,
    page_title: str,
    page_caption: str,
    empty_message: str,
    completed_label: str,
    completed_empty_label: str,
) -> None:
    """Shared renderer for the Bugs view and the Change Requests view.

    Both views share data + render logic — bug rows in the same Sheet tab,
    same card renderer, same statuses. They differ only in the Type filter
    (e.g. 'Bug' vs 'Change'), labels, and captions.
    """
    st.markdown(f"## {page_title}")
    st.caption(page_caption)
    if st.button("⚠️ Report a Bug / Suggest a Site Edit", type="primary",
                 use_container_width=True, key="bugpage_report_btn"):
        st.session_state.show_bug_dialog = True

    # type_keyword can be a single string or list of accepted substrings.
    _keywords = [type_keyword] if isinstance(type_keyword, str) else list(type_keyword)
    bugs = [
        b for b in _read_bugs()
        if any(k in (b.get("Type") or "") for k in _keywords)
    ]

    # Focused card from email deep link (?bug=<id>). If the row is on the
    # other typed view, drop the focus silently so we don't render a card
    # that doesn't belong here.
    _dl_bug_id = st.query_params.get("bug", "").strip()
    if _dl_bug_id:
        _hit = next((b for b in bugs if str(b.get("ID")) == _dl_bug_id), None)
        if _hit:
            st.markdown("#### 📌 You came here from an email")
            _render_bug_card(_hit)
            if st.button("← Back to full list", key=f"clear_{type_keyword}_focus"):
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()
            st.markdown("---")
        else:
            _dl_bug_id = ""

    _focus_bid = _dl_bug_id or None
    in_progress = sorted(
        [b for b in bugs
         if (b.get("Status") or "") in ("In Progress", "Needs Info")
         and str(b.get("ID")) != _focus_bid],
        key=lambda b: _priority_rank(b.get("Priority", "")),
    )
    open_entries = sorted(
        [b for b in bugs
         if (b.get("Status") or "Open") == "Open"
         and str(b.get("ID")) != _focus_bid],
        key=lambda b: _priority_rank(b.get("Priority", "")),
    )
    fixed = [b for b in bugs
             if (b.get("Status") or "") == "Fixed"
             and str(b.get("ID")) != _focus_bid]

    if not in_progress and not open_entries and not _focus_bid and not fixed:
        st.info(empty_message)
        return

    cols = st.columns(2)
    # LEFT = In Progress + completed history below
    with cols[0]:
        st.markdown(f"#### 🛠️ In Progress ({len(in_progress)})")
        if in_progress:
            for entry in in_progress:
                _render_bug_card(entry)
        else:
            st.caption("Nothing in progress.")

        st.markdown("---")
        with st.expander(f"{completed_label} ({len(fixed)})", expanded=False):
            if fixed:
                for entry in fixed[:25]:
                    _render_completed_bug_card(entry)
            else:
                st.caption(completed_empty_label)
    # RIGHT = Open (untouched / just arrived)
    with cols[1]:
        st.markdown(f"#### 📥 Open ({len(open_entries)})")
        if open_entries:
            for entry in open_entries:
                _render_bug_card(entry)
        else:
            st.caption("Nothing new in the queue.")


def _missed_runs(reports: list[dict], days: int = 7, today: dt.date | None = None) -> list[dict]:
    """For each report, find days in the past `days` where it was scheduled
    but no successful run was logged by anyone. Returns list of {report, missed_date}."""
    today = today or dt.date.today()
    runs = _all_runs_merged(days=days + 1)
    success_by_report: dict[str, set] = {}
    for r in runs:
        if r.get("status") == "success":
            success_by_report.setdefault(r["report_id"], set()).add(r["_dt"].date())
    missed = []
    for report in reports:
        sched = report.get("schedule")
        if not sched:
            continue
        for offset in range(1, days + 1):  # exclude today (still has time left)
            day = today - dt.timedelta(days=offset)
            if _was_due_on(report, day) and day not in success_by_report.get(report["id"], set()):
                missed.append({"report": report, "missed_date": day})
    return sorted(missed, key=lambda m: m["missed_date"], reverse=True)


# --------------------------------------------------------------------------
# Page setup + custom theme
# --------------------------------------------------------------------------

_FAVICON_PATH = WORKSPACE / "resources" / "alphalete-shield.png"
st.set_page_config(
    page_title="Alphalete Marketing Report Hub",
    # Pass the Path object directly (not str()). On Windows, str(Path) yields
    # backslashes which some Streamlit code paths mis-parse as URL escapes;
    # the Path object lets Streamlit normalize internally. Falls back to the
    # emoji if the file isn't there.
    page_icon=_FAVICON_PATH if _FAVICON_PATH.exists() else "🐺",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* App-wide */
    .main > div { padding-top: 1rem; }
    h1, h2, h3 { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }

    /* Alphalete brand palette
       --gold-dark: #8B6914   (deep gold, header gradient end)
       --gold:      #C9A85C   (Alphalete wolf gold)
       --gold-soft: #E8D08C   (soft gold accent)
       --red:       #B8232C   (Alphalete red)
       --red-dark:  #8B1A22   (deep red, button hover) */

    /* Hero card — gold gradient */
    .hero {
        background: linear-gradient(135deg, #2A1F12 0%, #5C4220 50%, #8B6914 100%);
        color: white;
        padding: 1.8rem 2rem;
        border-radius: 16px;
        margin-bottom: 1.2rem;
        box-shadow: 0 8px 24px rgba(139, 105, 20, 0.28);
        border: 1px solid rgba(201, 168, 92, 0.4);
    }
    .hero h1 { color: #E8D08C !important; margin: 0 0 0.4rem 0; font-size: 1.9rem; }
    .hero p { margin: 0; opacity: 0.92; font-size: 1.05rem; color: #F5EAD0; }
    .hero .big-date {
        font-size: 2.4rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        margin-bottom: 0.3rem;
        color: #E8D08C;
        line-height: 1.1;
        text-shadow: 0 2px 8px rgba(0,0,0,0.35);
    }

    /* Report cards */
    [data-testid="stContainer"]:has(.report-card-marker) {
        background: white;
        border-radius: 14px;
        padding: 1.2rem 1.4rem !important;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }

    /* Status pills */
    .pill {
        display: inline-block;
        padding: 0.45rem 1.1rem;
        border-radius: 999px;
        font-size: 1.05rem;
        font-weight: 700;
        margin-right: 0.5rem;
        letter-spacing: 0.3px;
    }
    .pill-due { background: #FFE9E9; color: #C92020; border: 2px solid #C92020; }
    .pill-ok  { background: #E6F7EC; color: #1F7A3D; border: 2px solid #1F7A3D; }
    .pill-info{ background: #E8F0FE; color: #1A4FB0; }
    .pill-warn{ background: #FFF3D6; color: #8B6914; border: 2px solid #C9A227; }

    /* Red STOP REPORT button (uses :has() to target the stButton right after our anchor div) */
    div[data-testid="stVerticalBlock"]:has(> div > div > .stop-btn-anchor) .stButton > button,
    div:has(> div > div > .stop-btn-anchor) + div .stButton > button {
        background: #C92020 !important;
        background-image: none !important;
        color: #FFFFFF !important;
        border: 2px solid #8B1414 !important;
        font-weight: 800 !important;
        letter-spacing: 0.5px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div > div > .stop-btn-anchor) .stButton > button:hover,
    div:has(> div > div > .stop-btn-anchor) + div .stButton > button:hover {
        background: #A11515 !important;
        box-shadow: 0 4px 14px rgba(201, 32, 32, 0.45) !important;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
        transition: transform 0.1s ease, box-shadow 0.15s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(184, 35, 44, 0.18);
    }
    /* Primary buttons = Alphalete gold gradient with deep-brown text */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #E8C268 0%, #C9A85C 100%);
        border: 1px solid #A88840;
        color: #2A1F12 !important;
        font-weight: 800;
        text-shadow: 0 1px 0 rgba(255,255,255,0.3);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #F2D080 0%, #D6B468 100%);
        box-shadow: 0 6px 18px rgba(201, 168, 92, 0.45);
        color: #2A1F12 !important;
    }
    /* Secondary buttons get a subtle gold accent on hover */
    .stButton > button[kind="secondary"]:hover {
        border-color: #C9A85C;
    }
    /* Make link buttons match the secondary look */
    .stLinkButton > a {
        border-radius: 10px !important;
    }
    /* Section headings get a gold underline accent */
    .main h2 {
        border-bottom: 3px solid #C9A85C;
        padding-bottom: 0.4rem;
        display: inline-block;
    }
    /* Status pill: Done Today switches to brand gold */
    .pill-ok { background: #FFF3D6 !important; color: #8B6914 !important; }

    /* Hide Streamlit's default top-right toolbar (Deploy button, hamburger
       menu, share icon). Reusing the slot below for our own status pill. */
    [data-testid="stToolbar"], .stDeployButton { display: none !important; }
    header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }

    /* Sidebar is always visible — hide the collapse / expand controls so it
       can't be dismissed accidentally. The nav is the spine of the hub. */
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebar"] button[kind="header"] {
        display: none !important;
    }
    [data-testid="stSidebar"] {
        min-width: 17rem !important;
        max-width: 17rem !important;
        transform: none !important;
        visibility: visible !important;
    }

    /* Our custom top-right system-status pill */
    .system-status-pill {
        position: fixed;
        top: 10px;
        right: 18px;
        z-index: 9999;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.01em;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        border: 1px solid rgba(0,0,0,0.06);
    }
    .system-status-pill.ok   { background: #E8F6EC; color: #1F7A3D; }
    .system-status-pill.warn { background: #FFEBE8; color: #B8232C; }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Session state init + view router
# --------------------------------------------------------------------------

if "view" not in st.session_state:
    # Restore from URL on first load so refresh stays on the same page.
    # Inline set (instead of _VALID_VIEWS) so this block doesn't depend on
    # helpers defined further down in the file — Streamlit runs top-to-bottom.
    _url_view = st.query_params.get("view", "").strip()
    st.session_state.view = (
        _url_view
        if _url_view in {"home", "user", "library", "backlog", "bugs"}
        else "home"
    )
    # A library report-detail page encodes ?report=<id> in the URL; restore
    # it so a browser refresh reloads that report's page, not the list.
    _url_report = st.query_params.get("report", "").strip()
    if _url_report:
        st.session_state["library_report_id"] = _url_report
if "user" not in st.session_state:
    _url_user = st.query_params.get("user", "").strip()
    st.session_state.user = _url_user or None

# Email deep-link auto-navigation. The intake/bug notification emails put
# ?request=<id> or ?bug=<id> in the URL; on first arrival we jump straight
# to the relevant view so the focused card lands front-and-center.
if not st.session_state.get("_deep_link_handled"):
    _dl_req = st.query_params.get("request", "").strip()
    _dl_bug = st.query_params.get("bug", "").strip()
    if _dl_req:
        st.session_state.view = "backlog"
    elif _dl_bug:
        # Bugs and change requests share the same Sheet tab + ?bug=<id>
        # deep link; look up the row's Type to land on the right view.
        _b_lookup = next((b for b in _read_bugs() if str(b.get("ID")) == _dl_bug), None)
        if _b_lookup and "Change" in (_b_lookup.get("Type") or ""):
            st.session_state.view = "changes"
        else:
            st.session_state.view = "bugs"
    if _dl_req or _dl_bug:
        st.session_state._deep_link_handled = True

LOGO_PATH = WORKSPACE / "resources" / "alphalete-shield.png"
LOGO_EXISTS = LOGO_PATH.exists()

# --------------------------------------------------------------------------
# Soft auth gate + session persistence
#
# This is a UX gate, not real security. Anyone who knows HUB_PASSWORD can sign
# in. The real access control is GitHub repo invites + the local install
# required to even reach localhost:8501. Rotate by changing HUB_PASSWORD below
# (or set the HUB_PASSWORD env var to override without editing this file).
#
# Sessions persist via a small file under ~/.config/recruiting-report/. After
# successful login the file is touched; every authed render refreshes the
# timestamp. After 1 hour with no activity, the next visit prompts for the
# password again. Browser refreshes don't bounce the user back to the login.
# --------------------------------------------------------------------------
import os as _os
import time as _time

HUB_PASSWORD = _os.environ.get("HUB_PASSWORD", "LolaOG2026")
_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
_SESSION_FILE = _CONFIG_DIR / ".pack-access-session"
_SESSION_TTL_SECONDS = 60 * 60  # 1 hour of inactivity


def _has_valid_session() -> bool:
    if not _SESSION_FILE.exists():
        return False
    try:
        last = float(_SESSION_FILE.read_text().strip())
    except Exception:
        return False
    return (_time.time() - last) < _SESSION_TTL_SECONDS


def _refresh_session() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _SESSION_FILE.write_text(str(_time.time()))


def _clear_session() -> None:
    try:
        _SESSION_FILE.unlink()
    except FileNotFoundError:
        pass


if "authed" not in st.session_state:
    # Rehydrate from disk on first load (or after browser refresh) so users
    # don't get bounced back to the login screen every time they reload.
    st.session_state.authed = _has_valid_session()


def _render_login_screen() -> None:
    # Hide the sidebar entirely on the login screen
    st.markdown(
        "<style>[data-testid='stSidebar'] { display: none !important; }</style>",
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 2, 1])
    with cols[1]:
        st.markdown("<div style='height: 4rem'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            if LOGO_EXISTS:
                import base64
                _logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
                st.markdown(
                    "<div style='text-align:center; margin: 1rem 0 0.2rem'>"
                    f"<img src='data:image/png;base64,{_logo_b64}' style='height: 90px'/>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                "<div style='text-align:center; font-size: 1.8rem; font-weight: 800; line-height: 1.2; margin-top: 0.6rem'>"
                "Alphalete Marketing<br/>Report Hub"
                "</div>"
                "<div style='text-align:center; opacity: 0.7; margin: 0.4rem 0 1.2rem'>"
                "Enter the team password to continue."
                "</div>",
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=False):
                pw = st.text_input(
                    "Password",
                    type="password",
                    label_visibility="collapsed",
                    placeholder="Team password",
                )
                submit = st.form_submit_button("Sign in", use_container_width=True, type="primary")
                if submit:
                    if pw == HUB_PASSWORD:
                        st.session_state.authed = True
                        _refresh_session()
                        st.rerun()
                    else:
                        st.error("Wrong password. Try again or text Megan.")


# Auth gate
if not st.session_state.authed:
    _render_login_screen()
    st.stop()

# Refresh session timestamp on every authed render. After SESSION_TTL_SECONDS
# of inactivity (no script reruns), the next page load will fail
# _has_valid_session() and bounce back to the login screen.
_refresh_session()


today = dt.date.today()
weekday_name = WEEKDAY_NAMES[today.weekday()]
hour = dt.datetime.now().hour
greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 11 → '11th', 22 → '22nd', etc."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


BIG_DATE = f"{weekday_name.upper()}, {today.strftime('%B').upper()} {_ordinal(today.day).upper()}"


_VALID_VIEWS = {"home", "user", "library", "backlog", "bugs"}


def _set_view(view: str) -> None:
    """Set the active view and mirror it into the URL.

    Persisting `?view=…` in the URL keeps the user on the same page after
    a hard refresh; without this, refreshing would always drop them back
    to home. Clearing the query params first also drops any one-shot
    deep-link params (?request=, ?bug=) when the user navigates away.
    """
    st.session_state.view = view
    try:
        st.query_params.clear()
        st.query_params["view"] = view
    except Exception:
        pass


def _go_home():
    st.session_state.user = None
    _set_view("home")


def _go_user(name: str):
    st.session_state.user = name
    _set_view("user")
    try:
        st.query_params["user"] = name
    except Exception:
        pass


def _go_library():
    # Always return to the top-level library list (not a previously-opened detail).
    # Clearing library_came_from too so the "Back" button on a detail card
    # routes back here instead of bouncing the user to a profile they may
    # not even be looking at anymore.
    st.session_state.pop("library_report_id", None)
    st.session_state.pop("library_came_from", None)
    _set_view("library")


def _go_backlog():
    _set_view("backlog")


def _go_bugs():
    _set_view("bugs")


def _go_audit():
    _set_view("audit")


def _render_validation_audit() -> None:
    """Re-run every automated validation rule across every report. When a rule is
    added to report_validation.RULES, this instantly flags which existing reports
    now fail it (Megan 2026-05-25: 'check all existing reports against any new
    validation requirements'). Attestations (human confirmations) can't be
    re-derived after upload, so only the automated rules are re-checked here."""
    import automations.shared.report_validation as _rv
    st.markdown("## 🛡️ Validation Audit")
    st.caption("Re-runs the automated validation rules across every report. Add "
               "a rule and this shows which existing reports now fail it. "
               "Attestations (clean run / preview / names) were confirmed by the "
               "uploader at upload time and can't be re-checked here.")

    # --- Uploaded library reports: full auto-rule audit (what the gate governs) ---
    try:
        rows = _shared_library_ws().get_all_records()
    except Exception as e:
        rows = []
        st.error(f"Couldn't read the shared library: {e}")
    uploaded, uploaded_ids = [], set()
    for r in rows:
        meta_json = str(r.get("Metadata") or "").strip()
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except Exception:
            meta = {}
        name = meta.get("name") or str(r.get("Name") or r.get("ID") or "?")
        if meta.get("id"):
            uploaded_ids.add(meta["id"])
        uploaded.append((name, str(r.get("Script") or ""), meta))

    st.markdown(f"### Uploaded reports ({len(uploaded)})")
    if not uploaded:
        st.caption("No uploaded reports in the shared library yet.")
    else:
        audited = _rv.audit_reports(uploaded)
        n_fail = sum(1 for rep in audited.values() if rep.auto_failures)
        if n_fail:
            st.warning(f"⚠️ {n_fail} of {len(audited)} uploaded report(s) fail an automated rule.")
        else:
            st.success(f"✅ All {len(audited)} uploaded report(s) pass the automated rules.")
        for nm, rep in audited.items():
            fails, warns = rep.auto_failures, rep.warnings
            icon = "❌" if fails else ("⚠️" if warns else "✅")
            head = f"{icon} {nm}" + (f" — {len(fails)} issue(s)" if fails else "")
            with st.expander(head, expanded=bool(fails)):
                for cr in rep.results:
                    if cr.kind != "auto":
                        continue
                    mark = "✅" if cr.passed else ("⚠️" if cr.severity == "warn" else "❌")
                    md = f"{mark} **{cr.label}**"
                    if not cr.passed and cr.detail:
                        md += f" — {cr.detail}"
                    st.markdown(md)

    # --- Built-in reports: maintained in code (kept cross-platform there), listed
    # for completeness, NOT script-audited (avoids false positives on the vetted,
    # platform-guarded codebase). ---
    builtin = [r for r in AUTOMATED_REPORTS if r.get("id") not in uploaded_ids]
    st.markdown(f"### Built-in reports ({len(builtin)})")
    st.caption("Maintained in the codebase and kept cross-platform there — listed "
               "for completeness, not script-audited.")
    for r in builtin:
        st.markdown(f"- {r.get('emoji', '📊')} {r.get('name', '?')}")


def _detect_hub_user() -> str:
    """Best guess at who's using this hub, based on the OS user (or HUB_USER env).

    Match strategy (in order):
      1. HUB_USER env var (explicit override — set in shell or .env if needed)
      2. Exact match: member name == OS user (case-insensitive)
      3. Substring match: member name appears anywhere in OS user
         (handles 'maudmiller' → Maud, 'evelynsobrino' → Eve, etc.)
      4. Substring match on the machine hostname (fallback for shared-os-user setups)
      5. Final fallback: title-cased OS user, NOT MEMBERS[0]. Logging as
         the OS user is preferable to silently mis-attributing every
         unmatched run to the first person in the list.
    """
    import os
    import getpass
    import socket
    env = os.environ.get("HUB_USER", "").strip()
    if env:
        return env
    try:
        os_user = getpass.getuser().lower()
    except Exception:
        os_user = ""
    try:
        host = socket.gethostname().lower()
    except Exception:
        host = ""

    # Exact match on OS user.
    for m in MEMBERS:
        if m["name"].lower() == os_user:
            return m["name"]
    # Substring match on OS user (e.g. 'maud' inside 'maudmiller').
    for m in MEMBERS:
        if m["name"].lower() in os_user:
            return m["name"]
    # Substring match on hostname (e.g. 'maud' inside 'maud-macbook').
    for m in MEMBERS:
        if m["name"].lower() in host:
            return m["name"]
    # No match — return the OS user title-cased rather than guessing.
    return os_user.title() if os_user else "Unknown"


def _render_currently_running_banner(filter_user: str | None = None):
    """Show a banner if any reports are running in the background.
    If `filter_user` is given, only show runs started by that user."""
    active = _read_active_runs()
    if filter_user:
        active = [a for a in active if a.get("user") == filter_user]
    if not active:
        return
    for run in active:
        report_name = run.get("report_name", "?")
        user = run.get("user", "?")
        try:
            started = dt.datetime.fromisoformat(run.get("started_at", ""))
            elapsed = dt.datetime.now() - started
            elapsed_str = f"{int(elapsed.total_seconds() // 60)}m {int(elapsed.total_seconds() % 60)}s"
        except Exception:
            elapsed_str = "?"

        with st.container(border=True):
            cols = st.columns([5, 2])
            with cols[0]:
                st.markdown(
                    f"### 🏃  **{report_name}** is running…"
                )
                st.caption(f"Started by **{user}** • running for **{elapsed_str}** • PID {run.get('pid', '?')}")
            with cols[1]:
                st.markdown(
                    "<div style='padding-top: 0.6rem; color: #8B6914; font-weight: 600'>⏳ In progress</div>",
                    unsafe_allow_html=True,
                )

            # Tail the log file so the user can see live progress
            log_path = run.get("log_path")
            if log_path and Path(log_path).exists():
                try:
                    tail = Path(log_path).read_text().splitlines()[-15:]
                    with st.expander("📜 Live log (last 15 lines)", expanded=False):
                        st.code("\n".join(tail), language="log")
                except Exception:
                    pass

            stop_cols = st.columns([5, 2])
            with stop_cols[1]:
                st.markdown('<div class="stop-btn-anchor"></div>', unsafe_allow_html=True)
                if st.button("🛑 STOP REPORT", key=f"stop_{run['report_id']}", use_container_width=True,
                             help="Force-stop this background run", type="primary"):
                    try:
                        import os, signal
                        os.kill(int(run["pid"]), signal.SIGTERM)
                    except Exception as e:
                        st.error(f"Couldn't stop: {e}")
                    _clear_active_run(run["report_id"], status="stopped")
                    st.rerun()


# --------------------------------------------------------------------------
# Sidebar: system status + recent logs (always visible)
# --------------------------------------------------------------------------

with st.sidebar:
    # --- Navigation ---
    if st.session_state.view != "home":
        if st.button("🏠 Home Hub", use_container_width=True):
            _go_home()
            st.rerun()
    if st.button("📚 Report Library", use_container_width=True):
        _go_library()
        st.rerun()

    # --- Recent run logs: view a FINISHED run's log on the Hub (so you don't
    # have to open the terminal once it leaves the live panel — Eve 2026-06-01).
    _recent_logs = _recent_run_logs()
    if _recent_logs:
        with st.expander("📄 Recent run logs"):
            _opts = {f"{r['name']} · {r['mtime'].strftime('%b %d  %H:%M')}": r
                     for r in _recent_logs}
            _pick = st.selectbox("Pick a finished run", list(_opts.keys()),
                                 key="recent_log_pick",
                                 label_visibility="collapsed")
            _r = _opts.get(_pick)
            if _r:
                try:
                    _txt = _r["path"].read_text(errors="replace")
                except Exception as e:
                    _txt = f"(couldn't read log: {e})"
                st.download_button(
                    "⬇ Download full log", _txt,
                    file_name=f"{_r['report_id']}.log",
                    use_container_width=True, key="recent_log_dl")
                _tail = "\n".join(_txt.splitlines()[-300:]) or "(empty)"
                st.code(_tail)

    # Version/health badge — "are you on the latest code?" Would have caught
    # Eve running week-old code on the wrong branch for hours (2026-05-25).
    _gh = _git_health()
    if _gh.get("label"):
        _gh_cls = "ok" if _gh["ok"] else "warn"
        st.markdown(
            f'<div class="system-status-pill {_gh_cls}" title="{_gh["detail"]}">'
            f'{_gh["icon"]} {_gh["label"]}</div>',
            unsafe_allow_html=True,
        )
        if not _gh["ok"]:
            st.caption(f"⚠️ {_gh['detail']}")

    # Chrome status check removed 2026-05-26: every report now runs through
    # patchright's unattended login (rcaptain on AppStream, ownerville on
    # Tableau), so there's no debug-port Chrome for the user to keep open.
    # `chrome_ok` (referenced elsewhere) is force-true so any leftover gates
    # don't block runs; clean those out in a follow-up if anything reads it.
    chrome_ok = True

    # Remaining tasks today (user view only)
    if st.session_state.view == "user" and st.session_state.user:
        st.markdown("---")
        st.markdown("### 📋 Today's Tasks")
        if st.session_state.user == "Unassigned":
            my_reports = [r for r in AUTOMATED_REPORTS if not r.get("assignees")]
        else:
            my_reports = [r for r in AUTOMATED_REPORTS if st.session_state.user in r.get("assignees", [])]
        due_today_for_me = [r for r in my_reports
                            if _is_due_today(r, today) and not r.get("self_scheduled")]
        if not due_today_for_me:
            st.caption("☕ Nothing due today.")
        else:
            for r in due_today_for_me:
                done = _was_run_successfully_today(r["id"], today)
                if done:
                    st.markdown(f"<div style='padding: 0.4rem 0; color: #1F7A3D'>✅ <s>{r['emoji']} {r['name']}</s></div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='padding: 0.4rem 0'>☐ {r['emoji']} <b>{r['name']}</b></div>", unsafe_allow_html=True)

    st.markdown("---")

    # --- Requests & uploads ---
    # Backlog count so the sidebar shows what's waiting without clicking
    # through. Wrapped in try/except: _read_intake's internal try/except is
    # below @st.cache_data, so decorator-layer errors bypass it.
    try:
        _intake_rows = _read_intake()
    except Exception as e:
        st.error(f"❌ _read_intake threw: {type(e).__name__}: {e}")
        _intake_rows = []
    _backlog_count = sum(
        1 for r in _intake_rows
        if (r.get("Status") or "Unassigned") in ("Unassigned", "In Progress", "Needs Updates")
    )
    if st.button(f"📨 New Automation Request ({_backlog_count})", use_container_width=True, key="nav_backlog"):
        _go_backlog()
        st.rerun()
    # Admin/build tools tucked under one expander (#7 declutter) so the daily
    # path — run my reports — stays front and center.
    with st.expander("🛠️ Build & manage"):
        if st.button("📥 Upload Built Automation", use_container_width=True, key="nav_upload"):
            st.session_state.show_wireup_direct = True
        if st.button("✏️ Request Change to Existing Report", use_container_width=True, key="open_change_request_btn"):
            st.session_state.show_change_request_dialog = True
        if st.button("🛡️ Validation Audit", use_container_width=True, key="nav_audit"):
            _go_audit()
            st.rerun()

    st.markdown("---")

    # --- Bug report + account ---
    st.markdown(
        """
        <style>
        div[data-testid="stSidebar"] button[kind="secondary"]:has(div:contains("Report a Bug")) {
            background: #C92020 !important;
            color: white !important;
            border: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button("⚠️ Report a Bug / Suggest a Site Edit", use_container_width=True, key="open_bug_dialog_btn"):
        _go_bugs()
        st.rerun()
    # Tiny sign-out link — ends the 1-hour session so the next page load
    # prompts for the Pack Access password again.
    if st.button("Sign out", use_container_width=True, key="sidebar_signout_btn"):
        st.session_state.authed = False
        _clear_session()
        st.rerun()


# --------------------------------------------------------------------------
# HOME VIEW — logo + date header + The Pack
# --------------------------------------------------------------------------

if st.session_state.view == "home":
    if LOGO_EXISTS:
        import base64
        _logo_b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
        _logo_html = (
            f"<img src='data:image/png;base64,{_logo_b64}' "
            "style='height:90px; width:auto; display:block'/>"
        )
    else:
        _logo_html = "<div style='font-size: 4rem; line-height: 1.0'>🐺</div>"
    st.markdown(
        "<div style='display:flex; align-items:center; gap:1rem; margin:0.4rem 0 1rem'>"
        f"{_logo_html}"
        "<div style='font-size:2.6rem; font-weight:800; letter-spacing:-0.5px; line-height:1.1'>"
        "Alphalete Marketing Report Hub</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    # Run-count for the date header: of the reports due to run today,
    # how many have a successful run logged.
    _due_today = [r for r in AUTOMATED_REPORTS
                  if _is_due_today(r, today) and not r.get("self_scheduled")]
    _ran_today = sum(1 for r in _due_today if _was_run_successfully_today(r["id"], today))
    _due_n = len(_due_today)
    st.markdown(f"""
    <div class="hero" style="display:flex; align-items:center; justify-content:space-between">
        <div class="big-date">{BIG_DATE}</div>
        <div style="text-align:right; line-height:1.15">
            <div style="font-size:2rem; font-weight:800">{_ran_today}<span style="opacity:0.45">/{_due_n}</span></div>
            <div style="font-size:0.78rem; opacity:0.75; text-transform:uppercase; letter-spacing:0.05em">Reports run today</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### 🐺 The Pack")
    # Layout (Megan 2026-07-07): the two Lucy automations on the TOP row —
    # Lucy 1 above the left column, Lucy 2 above the right — then Eve, Maud and
    # the Unassigned bucket across the BOTTOM row.
    UNASSIGNED_CARD = {"name": "Unassigned", "emoji": "🔍", "is_unassigned": True}
    PACK_COLS = 3
    _by_name = {m["name"]: m for m in MEMBERS}
    _bots = [_by_name[n] for n in ("Lucy 1", "Lucy 2") if n in _by_name]
    _bottom = [m for m in MEMBERS if m["name"] not in ("Lucy 1", "Lucy 2")]
    _bottom.append(UNASSIGNED_CARD)
    # (row_cards, column_slots): slots pick which of the 3 columns each card
    # fills, so the two top-row bots sit over the outer bottom-row cards. The
    # bottom row wraps into further rows of 3 if more members are ever added.
    pack_rows = [(_bots, [0, 2][:len(_bots)])]
    for i in range(0, len(_bottom), PACK_COLS):
        chunk = _bottom[i:i + PACK_COLS]
        pack_rows.append((chunk, list(range(len(chunk)))))
    for row, slots in pack_rows:
        cols = st.columns(PACK_COLS)
        card_cols = [cols[s] for s in slots]
        for col, member in zip(card_cols, row):
            with col:
                is_unassigned = member.get("is_unassigned", False)
                if is_unassigned:
                    unassigned_reports = [r for r in AUTOMATED_REPORTS if not r.get("assignees")]
                    count = len(unassigned_reports)
                else:
                    my_reports = [r for r in AUTOMATED_REPORTS if member["name"] in r.get("assignees", [])]
                    # Only count reports still UNCOMPLETED today —
                    # successfully-run reports shouldn't show as "due"
                    # (the strip already marks them with ✅).
                    due_count = sum(
                        1 for r in my_reports
                        if _is_due_today(r, today)
                        and not r.get("self_scheduled")
                        and not _was_run_successfully_today(r["id"], today)
                    )
                with st.container(border=True):
                    st.markdown(
                        f"<div style='text-align:center; font-size: 3.5rem; line-height: 1.0; margin-bottom: 0.4rem'>{member['emoji']}</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='text-align:center; font-size: 1.3rem; font-weight: 700; margin-bottom: 0.3rem'>{member['name']}</div>",
                        unsafe_allow_html=True,
                    )
                    if is_unassigned:
                        if count > 0:
                            st.markdown(
                                f"<div style='text-align:center'><span class='pill pill-due'>{count} need{'s' if count == 1 else ''} a home</span></div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                "<div style='text-align:center'><span class='pill pill-ok'>All claimed</span></div>",
                                unsafe_allow_html=True,
                            )
                    elif due_count > 0:
                        st.markdown(
                            f"<div style='text-align:center'><span class='pill pill-due'>{due_count} report{'s' if due_count != 1 else ''} due today</span></div>",
                            unsafe_allow_html=True,
                        )
                    elif my_reports:
                        st.markdown(
                            f"<div style='text-align:center'><span class='pill pill-ok'>All clear today</span></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"<div style='text-align:center'><span class='pill pill-info'>No reports yet</span></div>",
                            unsafe_allow_html=True,
                        )
                    btn_label = "Open unassigned reports" if is_unassigned else f"Open {member['name']}'s reports"
                    if st.button(
                        btn_label,
                        key=f"pick_{member['name']}",
                        use_container_width=True,
                    ):
                        _go_user(member["name"])
                        st.rerun()


# --------------------------------------------------------------------------
# BACKLOG VIEW — automation request intake + claim flow
# --------------------------------------------------------------------------

elif st.session_state.view == "backlog":
    st.markdown("## 🚧 Automation Request Log")
    st.caption("New report ideas from the team. Anyone can claim a request to take it on.")

    if st.button("➕ Submit a New Request", type="primary", key="backlog_open_intake_btn"):
        _show_intake_dialog()

    intake = _read_intake()

    # Focused card from email deep link
    _dl_request_id = st.query_params.get("request", "").strip()
    if _dl_request_id:
        _hit = next((r for r in intake if str(r.get("ID")) == _dl_request_id), None)
        if _hit:
            st.markdown("#### 📌 You came here from an email")
            _hit_status = _hit.get("Status") or "Unassigned"
            _render_intake_card(
                _hit,
                allow_claim=(_hit_status == "Unassigned"),
                allow_done=(_hit_status == "In Progress"),
            )
            if st.button("← Back to full backlog", key="clear_request_focus"):
                try:
                    st.query_params.clear()
                except Exception:
                    pass
                st.rerun()
            st.markdown("---")
        else:
            st.warning(f"Couldn't find a request with ID `{_dl_request_id}` — showing the full backlog below.")

    _focus_id = _dl_request_id or None
    unassigned = sorted(
        [r for r in intake
         if (r.get("Status") or "Unassigned") == "Unassigned"
         and str(r.get("ID")) != _focus_id],
        key=lambda r: _priority_rank(r.get("Priority", "")),
    )
    in_progress = sorted(
        [r for r in intake
         if r.get("Status") == "In Progress"
         and str(r.get("ID")) != _focus_id],
        key=lambda r: _priority_rank(r.get("Priority", "")),
    )

    # In Review = creator uploaded, requester reviewing. "Edits Requested"
    # = requester sent it back; both share the In Review section since
    # they're the same review loop, just different turns.
    in_review = sorted(
        [r for r in intake
         if r.get("Status") in ("In Review", "Edits Requested")
         and str(r.get("ID")) != _focus_id],
        key=lambda r: _priority_rank(r.get("Priority", "")),
    )

    needs_updates = sorted(
        [r for r in intake
         if r.get("Status") == "Needs Updates"
         and str(r.get("ID")) != _focus_id],
        key=lambda r: _priority_rank(r.get("Priority", "")),
    )
    completed_intake = sorted(
        [r for r in intake
         if r.get("Status") == "Done"
         and str(r.get("ID")) != _focus_id],
        key=lambda r: r.get("Assigned At", "") or r.get("Submitted At", ""),
        reverse=True,
    )

    if not intake:
        st.info("No requests in the backlog yet. Click **Submit a New Request** above to add the first one.")
    else:
        backlog_cols = st.columns(2)
        # LEFT = Needs Updates (resurrected, waiting to be re-claimed)
        # + In Progress (actively being worked on)
        # + Completed history below.
        with backlog_cols[0]:
            if needs_updates:
                st.markdown(f"#### 🚨 Needs Updates ({len(needs_updates)})")
                for entry in needs_updates:
                    _render_needs_updates_card(entry)
                st.markdown("")

            st.markdown(f"#### 🛠️ In Progress ({len(in_progress)})")
            if in_progress:
                for entry in in_progress:
                    _render_intake_card(entry, allow_claim=False, allow_done=True)
            else:
                st.caption("No projects in progress yet.")

            if in_review:
                st.markdown("")
                st.markdown(f"#### 🔍 In Review ({len(in_review)})")
                st.caption("Creator uploaded — requester reviews, then approves or requests edits.")
                for entry in in_review:
                    _render_intake_card(entry, allow_claim=False, allow_done=False,
                                        review_mode=True)

            st.markdown("---")
            with st.expander(f"✅ Completed Automations ({len(completed_intake)})", expanded=False):
                if completed_intake:
                    for entry in completed_intake[:25]:
                        _render_completed_intake_card(entry)
                else:
                    st.caption("Nothing finished yet.")
        # RIGHT = Unassigned (waiting to be claimed)
        with backlog_cols[1]:
            st.markdown(f"#### 🔓 Unassigned ({len(unassigned)})")
            if unassigned:
                for entry in unassigned:
                    _render_intake_card(entry, allow_claim=True, allow_done=False)
            else:
                st.caption("Nothing waiting to be claimed.")


# --------------------------------------------------------------------------
# BUGS VIEW — bug reports only (Megan-triaged). Change requests now flow
# into the Automation Request Log instead since they follow the same
# claim → build → review path as new automation requests.
# --------------------------------------------------------------------------

elif st.session_state.view == "bugs":
    _render_bug_typed_view(
        type_keyword=["Bug", "Site"],
        page_title="🐛 Bugs & Site Edits Being Fixed",
        page_caption="Things that are broken or polish/UX tweaks to the hub. Submitted via the sidebar. Megan triages and replies to the submitter by email.",
        empty_message="No bug reports or site-edit suggestions right now.",
        completed_label="✅ Completed",
        completed_empty_label="Nothing fixed yet.",
    )


# --------------------------------------------------------------------------
# REPORT LIBRARY VIEW — every automation in one place; anyone can launch
# --------------------------------------------------------------------------

elif st.session_state.view == "library":
    selected_id = st.session_state.get("library_report_id")

    # Keep the URL in sync so a browser refresh reloads the SAME page — the
    # open report's detail page if one is selected, else the library list.
    if selected_id:
        st.query_params["view"] = "library"
        st.query_params["report"] = str(selected_id)
    elif "report" in st.query_params:
        del st.query_params["report"]

    # If we got here from a user profile, the Back button should return there
    # instead of bouncing to the library list. Tracked via library_came_from
    # which the entry-point buttons set.
    _came_from = st.session_state.get("library_came_from")
    if _came_from and _came_from[0] == "user":
        _back_label = f"← Back to {_came_from[1]}'s profile"
    else:
        _back_label = "← Back to Library"

    def _back_from_library_detail() -> None:
        st.session_state.pop("library_report_id", None)
        if _came_from and _came_from[0] == "user":
            st.session_state.user = _came_from[1]
            st.session_state.pop("library_came_from", None)
            _set_view("user")
        st.rerun()

    if selected_id:
        report = next((r for r in AUTOMATED_REPORTS if r["id"] == selected_id), None)
        if not report:
            st.error("That report isn't in the library anymore.")
            if st.button(_back_label, key="lib_detail_back_missing"):
                _back_from_library_detail()
        else:
            if st.button(_back_label, key="lib_detail_back"):
                _back_from_library_detail()

            # Auto-detect the runner from the OS user. The run gets attributed
            # to this person automatically — no dropdown needed.
            detected_user = _detect_hub_user()
            st.session_state.user = detected_user

            # Unassigned reports get an inline assign picker (full width,
            # above the run/screenshot columns).
            if not report.get("assignees"):
                with st.container(border=True):
                    st.markdown("**🔍 This report isn't assigned yet.**")
                    _ac = st.columns([3, 2])
                    with _ac[0]:
                        _pick = st.selectbox(
                            "Assign to…",
                            ["— assign to —"] + [m["name"] for m in MEMBERS],
                            key=f"lib_detail_assign_pick_{report['id']}",
                            label_visibility="collapsed",
                        )
                    with _ac[1]:
                        if _pick and _pick != "— assign to —" and st.button(
                            "🤝 Assign", key=f"lib_detail_assign_btn_{report['id']}",
                            use_container_width=True,
                        ):
                            if _set_library_assignment(str(report["id"]), _pick):
                                st.success(f"Assigned to {_pick}.")
                                st.rerun()
                            else:
                                st.error("Couldn't save — try again.")

            # Run controls on the left, the report's screenshot on the
            # right; the how-it-works breakdown spans full width below.
            _run_col, _shot_col = st.columns([1, 1])
            with _run_col:
                _render_report_card(report, today, chrome_ok)
            with _shot_col:
                _render_report_screenshot(report)
            # Breathing room between the run/screenshot row and the
            # full-width how-it-works breakdown below it.
            st.markdown("<div style='height:1.6rem'></div>",
                        unsafe_allow_html=True)
            _render_report_breakdown(report)
    else:
        st.markdown(
            "<div style='font-size:2.4rem; font-weight:800; letter-spacing:-0.5px; "
            "margin:0.4rem 0 0.4rem'>📚 Report Library</div>",
            unsafe_allow_html=True,
        )
        st.caption("Every automation. Click a report to open its checklist + run it.")

        # Search box — type to filter the list by report name / description.
        _lib_query = st.text_input(
            "Search reports", key="lib_search",
            placeholder="🔍  Search reports by name…",
            label_visibility="collapsed",
        ).strip().lower()

        # Flat alphabetical list — no sections (Megan, 2026-05-19 — chose
        # this for 7-year-old-simple over by-day or by-assignee groupings).
        # One report per row; search box at top still filters.
        _filtered = [
            r for r in AUTOMATED_REPORTS
            if not _lib_query or _lib_query in (
                f"{r.get('name', '')} {r.get('description', '')}".lower())
        ]
        _filtered.sort(key=lambda r: (r.get("name") or "").lower())
        ordered_sections = [("", _filtered)] if _filtered else []
        if not ordered_sections:
            st.info(f"No reports match “{_lib_query}”."
                    if _lib_query else "No reports in the library yet.")

        # Mid-flow runs — used to decorate cards with a "pick up" pill so
        # anyone browsing the library sees that this report is partway through.
        lib_persisted = _load_all_run_state()
        for section_name, reports_in_section in ordered_sections:
            if section_name:
                st.markdown(f"### {section_name}")
            # 3-per-row grid of report buttons. Click one to open its page
            # (explainer + live preview + run controls). A 📌 prefix flags a
            # report whose last run is mid-flow — pick up where you left off.
            for _i in range(0, len(reports_in_section), 3):
                _row = st.columns(3)
                for _j, report in enumerate(reports_in_section[_i:_i + 3]):
                    with _row[_j]:
                        _pickup = lib_persisted.get(report["id"])
                        _label = f"{report.get('emoji', '📄')} {report['name']}"
                        if _pickup:
                            _label = "📌 " + _label
                        # Key includes the section so a report that
                        # appears under multiple days (e.g. Daily Focus on
                        # Tue-Sat) doesn't trigger StreamlitDuplicateElementKey.
                        _btn_key = f"lib_btn_{section_name}_{report['id']}"
                        if st.button(
                            _label,
                            key=_btn_key,
                            use_container_width=True,
                            help=("Mid-run — pick up where you left off"
                                  if _pickup else report.get("description") or None),
                        ):
                            st.session_state["library_report_id"] = report["id"]
                            st.rerun()


# --------------------------------------------------------------------------
# USER VIEW — that user's today's schedule + their reports
# --------------------------------------------------------------------------

elif st.session_state.view == "audit":
    if st.button("← Back to Library", key="audit_back"):
        _go_library()
        st.rerun()
    _render_validation_audit()

else:  # st.session_state.view == "user"
    user_name = st.session_state.user or "friend"
    is_unassigned_view = (user_name == "Unassigned")
    member = next((m for m in MEMBERS if m["name"] == user_name), None)
    member_emoji = "🔍" if is_unassigned_view else (member["emoji"] if member else "📊")

    # Only show "currently running" for runs THIS user kicked off
    _render_currently_running_banner(filter_user=user_name)
    if is_unassigned_view:
        st.markdown(f"""
        <div class="hero">
            <div class="big-date">{BIG_DATE}</div>
            <h1>{member_emoji} Unassigned Reports</h1>
            <p>These reports need someone to pick them up. Open one to claim it.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="hero">
            <div class="big-date">{BIG_DATE}</div>
            <h1>{member_emoji} {greeting}, {user_name}!</h1>
            <p>Here's what's on your plate.</p>
        </div>
        """, unsafe_allow_html=True)

    if is_unassigned_view:
        my_reports = [r for r in AUTOMATED_REPORTS if not r.get("assignees")]
    else:
        my_reports = [r for r in AUTOMATED_REPORTS if user_name in r.get("assignees", [])]

    # ----- "Pick up where you left off" banner -----
    # Show banner for: reports persisted with state where THIS user is the one
    # who ran it (regardless of assignee). Falls back to assignee for older
    # entries that don't have user info.
    persisted = _load_all_run_state()
    in_progress = [
        r for r in AUTOMATED_REPORTS
        if r["id"] in persisted
        and (
            persisted[r["id"]].get("user") == user_name
            or (not persisted[r["id"]].get("user") and user_name in r.get("assignees", []))
        )
    ]

    # Unassigned view is a queue, not a person — skip the personal
    # "Completed Today" + "Pick up where you left off" sections and just
    # list the reports needing someone to claim them.
    if is_unassigned_view:
        if my_reports:
            st.markdown("## 🚀 Reports needing a home")
            for report in my_reports:
                _render_report_card(report, today, chrome_ok)
        else:
            st.success("🎉 Every report has someone assigned. Nothing to pick up.")
    else:
        # 7-day schedule strip — visual overview of this user's responsibilities
        # for the week ahead. One row, 7 columns; auto-updates as new reports
        # get assigned to them (or as schedules change).
        st.markdown("### 📅 This week")
        # Colored status pills: Streamlit tags each keyed button's wrapper with a
        # `st-key-<key>` class. We suffix the key with `__calstat_<status>` and
        # color the button by that suffix (space-safe: the suffix has no spaces
        # even when the profile name does). Only calendar buttons match.
        st.markdown(
            "<style>"
            "@keyframes calpulse{0%{opacity:1}50%{opacity:.5}100%{opacity:1}}"
            "[class*='__calstat_ok'] button{background:#E1F5EE!important;color:#04342C!important;border-color:#5DCAA5!important}"
            "[class*='__calstat_fail'] button{background:#FAECE7!important;color:#712B13!important;border-color:#F0997B!important}"
            "[class*='__calstat_miss'] button{background:transparent!important;color:#888780!important;border-color:var(--border)!important;opacity:.75}"
            "[class*='__calstat_running'] button{background:#FBF3DE!important;color:#6B5210!important;border-color:#C9A85C!important;animation:calpulse 1.4s ease-in-out infinite}"
            # RingCentral Auto-Read is a background OPS automation — always show its
            # pill in the orange OPS color, regardless of run-status (its launchd
            # job doesn't report status back, so the default pill would read gray).
            "[class*='rc-autoread__calstat'] button{background:#FDECC8!important;color:#7A4E06!important;border-color:#F59E0B!important;opacity:1!important;animation:none!important}"
            # Resume Pushing is the same kind of background OPS automation (Lucy 2
            # launchd, no status reported back) — orange OPS pill regardless of
            # run-status, so it doesn't read gray.
            "[class*='resume-pushing__calstat'] button{background:#FDECC8!important;color:#7A4E06!important;border-color:#F59E0B!important;opacity:1!important;animation:none!important}"
            "</style>",
            unsafe_allow_html=True,
        )
        # Rendered in an auto-refreshing fragment (every 20s) so the 🔄 running
        # badge + outcome pills update live without a manual page reload. The
        # pill-coloring CSS above is injected once here (outside the fragment)
        # and persists across the fragment's reruns.
        _this_week_strip(today, my_reports, user_name)
        st.markdown("---")

        # ---- Personal portfolio: projects this user has claimed / shipped ----
        # Pulled from the Automation Request Log. "In progress" = anything
        # this user has currently claimed (Assigned To matches). "Shipped" =
        # rows marked Done with this user as the most recent claimer.
        _all_intake = _read_intake()
        # "In flight" for the creator = anything they've claimed that isn't
        # shipped yet — including items mid-review (In Review / Edits
        # Requested) so the creator can jump back in to revise.
        _my_in_flight = [
            r for r in _all_intake
            if (r.get("Assigned To") or "").strip() == user_name
            and r.get("Status") in ("In Progress", "Needs Updates",
                                     "In Review", "Edits Requested")
        ]
        _my_shipped = sorted(
            [r for r in _all_intake
             if (r.get("Assigned To") or "").strip() == user_name
             and r.get("Status") == "Done"],
            key=lambda r: r.get("Completed At", "") or r.get("Assigned At", ""),
            reverse=True,
        )

        if _my_in_flight or _my_shipped:
            _shipped_n = len(_my_shipped)
            _in_flight_n = len(_my_in_flight)
            _stat_line = (
                f"🚀 <b>{_shipped_n} shipped</b> &nbsp;•&nbsp; "
                f"🛠️ <b>{_in_flight_n} in flight</b>"
            )
            if _shipped_n >= 10:
                _stat_line += " &nbsp;•&nbsp; 🌟 <b>look at you go!</b>"
            elif _shipped_n >= 3:
                _stat_line += " &nbsp;•&nbsp; 🔥 <b>on a roll!</b>"
            elif _shipped_n >= 1:
                _stat_line += " &nbsp;•&nbsp; 🎉 <b>nice work!</b>"
            st.markdown(
                "<div style='background:linear-gradient(135deg, #FFF8E7 0%, #FFF3D6 100%); "
                "border-left:4px solid #C9A85C; border-radius:8px; padding:14px 18px; "
                "margin-bottom:0.6rem; font-size:1.1em; color:#5C4220'>"
                f"{_stat_line}"
                "</div>",
                unsafe_allow_html=True,
            )

            _proj_cols = st.columns(2)
            with _proj_cols[0]:
                st.markdown(f"#### 🛠️ In Progress ({_in_flight_n})")
                if _my_in_flight:
                    for entry in _my_in_flight:
                        _status = entry.get("Status", "")
                        with st.container(border=True):
                            _ph = _priority_pill_html(entry.get("Priority", ""))
                            _status_line = {
                                "In Review": "🔍 Awaiting requester review",
                                "Edits Requested": "📝 Requester asked for edits",
                            }.get(_status, "")
                            st.markdown(
                                f"**{entry.get('Title', 'Untitled')}**"
                                + ("  \n" + _ph if _ph else "")
                                + f"<br/><span style='color:#777; font-size:0.85em'>"
                                f"Claimed on {entry.get('Assigned At', '?')}"
                                + (f" · {_status_line}" if _status_line else "")
                                + f"</span>",
                                unsafe_allow_html=True,
                            )
                            if _status == "In Review":
                                st.caption("Waiting on the requester — nothing to do right now.")
                            else:
                                _btn_label = ("🔧 Revise & Re-upload"
                                              if _status == "Edits Requested"
                                              else "📥 Upload the Automation")
                                if st.button(
                                    _btn_label,
                                    key=f"profile_upload_{entry['ID']}",
                                    use_container_width=True,
                                ):
                                    _clear_wireup_state()
                                    _show_wire_up_dialog(entry)
                else:
                    st.caption("Nothing claimed right now. Head to the **Automation Request Log** to grab one.")
            with _proj_cols[1]:
                st.markdown(f"#### ✅ Shipped ({_shipped_n})")
                if _my_shipped:
                    for entry in _my_shipped[:10]:
                        _render_completed_intake_card(entry)
                    if _shipped_n > 10:
                        st.caption(f"… plus {_shipped_n - 10} more in the Automation Request Log.")
                else:
                    st.caption("First ship pending. You've got this. 💪")
            st.markdown("---")

        # "Completed Today" section intentionally removed (Megan, 2026-05-19)
        # — completed reports now show a green ✅ on their card in the
        # 7-day schedule strip above. Below: in-progress pick-up banner.
        if True:
            if in_progress:
                st.markdown("### 📌 Pick up where you left off")
                for report in in_progress:
                    saved = persisted[report["id"]]
                    saved_ts = saved.get("ts", "")
                    try:
                        saved_dt = dt.datetime.fromisoformat(saved_ts)
                        saved_str = saved_dt.strftime("%I:%M %p")
                    except Exception:
                        saved_str = saved_ts
                    post_run_cfg = report.get("post_run", {})
                    again_label = post_run_cfg.get("again_label", "🔁 Continue / Run Again")

                    # Recruiting report has structured per-week results: if all 52 tabs
                    # are filled, this banner shows a green "all done" state. Otherwise
                    # it lists the tabs that still need data.
                    results = _load_recruiting_results() if report["id"] == "recruiting" else {}
                    all_filled = bool(results) and not results.get("still_missing")
                    still_missing = results.get("still_missing", []) if results else []

                    with st.container(border=True):
                        if all_filled:
                            st.success(
                                f"🎉 **{report['emoji']} {report['name']} — Complete!** "
                                f"All **{len(results.get('filled', []))}** offices filled this week. "
                                f"Last run **{saved_str}** today."
                            )
                        elif still_missing:
                            st.warning(
                                f"⚠️ **{report['emoji']} {report['name']}** — last run **{saved_str}** today. "
                                f"**{len(still_missing)}** tab{'s' if len(still_missing) != 1 else ''} still need data."
                            )
                            with st.expander(f"📋 Show the {len(still_missing)} missing tabs", expanded=False):
                                for name in still_missing:
                                    st.markdown(f"- {name}")

                        cols = st.columns([5, 2, 2])
                        with cols[0]:
                            if not (all_filled or still_missing):
                                st.markdown(f"**{report['emoji']} {report['name']}** — last run **{saved_str}** today")
                                if post_run_cfg.get("message_success") and saved.get("status") == "success":
                                    st.caption(post_run_cfg["message_success"])
                                else:
                                    st.caption("You started this earlier today but haven't marked it done yet.")
                        with cols[1]:
                            if not all_filled:
                                if st.button(again_label, key=f"continue_{report['id']}", use_container_width=True, type="primary", disabled=not chrome_ok):
                                    primary = next((a for a in report["actions"] if a.get("primary")), report["actions"][0])
                                    # Standard failure manifest wins; else a
                                    # per-card again_action (e.g. daily-focus's
                                    # --retry-inaccessible); else the full primary.
                                    _mr = _manifest_retry(report)
                                    again_action = (_mr["action"] if _mr
                                                    else post_run_cfg.get("again_action") or primary)
                                    again_state_rel = post_run_cfg.get("again_state_file")
                                    again_state_key = post_run_cfg.get("again_state_key")
                                    again_empty_msg = post_run_cfg.get(
                                        "again_empty_message",
                                        "✅ Nothing to retry from the previous run.",
                                    )
                                    nothing_to_retry = False
                                    if _mr:
                                        nothing_to_retry = False   # manifest exists = there IS something to retry
                                    elif again_state_rel and again_state_key:
                                        state_path = WORKSPACE / again_state_rel
                                        try:
                                            if state_path.exists():
                                                data = json.loads(state_path.read_text())
                                                nothing_to_retry = not data.get(again_state_key)
                                            else:
                                                nothing_to_retry = True
                                        except Exception:
                                            nothing_to_retry = False
                                    if nothing_to_retry:
                                        st.success(again_empty_msg)
                                    elif again_action is primary:
                                        picked = None
                                        if primary.get("needs_date") or primary.get("needs_text"):
                                            d = st.session_state.get(f"date_{report['id']}_{primary['label']}")
                                            t = st.session_state.get(f"text_{report['id']}_{primary['label']}")
                                            if primary.get("needs_date") and primary.get("needs_text"):
                                                picked = (d, t)
                                            elif primary.get("needs_date"):
                                                picked = d
                                            elif primary.get("needs_text"):
                                                picked = t
                                        _execute_action(report, primary, picked, chrome_ok)
                                    else:
                                        _execute_action(report, again_action, None, chrome_ok)
                        with cols[2]:
                            if st.button("✅ Mark as Completed", key=f"banner_done_{report['id']}", use_container_width=True):
                                _mark_run_completed(
                                    user=user_name,
                                    report_id=report["id"],
                                    report_name=report["name"],
                                    run_ts=saved_ts,
                                )
                                _clear_run_state_for(report["id"])
                                st.session_state.pop(f"last_run_{report['id']}", None)
                                st.rerun()

            # "Your Reports" list intentionally removed (Megan, 2026-05-19) —
            # the 7-day schedule strip above already shows which reports
            # the user runs and when. Library is the place to actually
            # open + run them.


# --------------------------------------------------------------------------
# Bug-report and change-request dialogs (two dedicated forms, one per
# sidebar button — no shared dropdown).
# --------------------------------------------------------------------------

@st.dialog("🐛 Report a Bug or Suggest a Site Edit", width="large")
def _show_bug_dialog():
    st.caption(
        "Something broken on an existing report, or want to tweak how the hub "
        "itself looks/works? Drop it here — Megan handles both and follows up "
        "by email.\n\n"
        "**Tweak to an existing report?** Use **\"Request Change to Existing "
        "Report\"** instead.\n\n"
        "**Brand-new automation?** Use **\"New Automation Request\"** instead."
    )
    with st.form("bug_form", clear_on_submit=True):
        cols = st.columns(2)
        with cols[0]:
            kind = st.selectbox(
                "What kind?",
                ["Bug / something broke", "Site edit suggestion"],
                help="'Bug' = a report or feature is broken. "
                     "'Site edit suggestion' = polish/UX tweak to the hub itself.",
            )
            subject = st.text_input(
                "Subject",
                placeholder="e.g. 'OPT Focus Report' or 'Sidebar layout'",
                help="What this is about — the report name, the page, etc.",
            )
            requester = st.text_input("Your name", value=st.session_state.get("user", "") or "")
            requester_email = st.text_input(
                "Your email",
                placeholder="you@example.com",
                help="Megan will reply here when it's fixed or if she needs more info.",
            )
        with cols[1]:
            link = st.text_input("Sheet link", placeholder="https://…  (paste 'n/a' if not applicable)")
            loom = st.text_input("Loom", placeholder="https://loom.com/…  (paste 'n/a' if not applicable)")
            priority = st.selectbox(
                "Priority",
                PRIORITY_OPTIONS,
                index=2,
                help="How urgent is this? Don't worry, 5 is a real option.",
            )
        details = st.text_area(
            "Details — what's broken / what should change?",
            height=140,
            placeholder="Describe what's wrong (or what the edit should look like), "
                        "when it started, etc.",
        )
        submitted = st.form_submit_button("📨 Submit", type="primary", use_container_width=True)

        if submitted:
            missing = [
                label for label, val in [
                    ("Subject", subject),
                    ("Your name", requester),
                    ("Your email", requester_email),
                    ("Sheet link", link),
                    ("Loom", loom),
                    ("Details", details),
                ] if not str(val).strip()
            ]
            if missing:
                st.error("Please fill in every field — missing: " + ", ".join(missing))
            else:
                try:
                    _add_bug(
                        title=subject,
                        bug_type=kind,
                        sheet_link=link,
                        loom_link=loom,
                        details=details,
                        submitted_by=requester,
                        submitter_email=requester_email,
                        priority=priority,
                    )
                    success_msg = (
                        "✅ Submitted! Megan will reply to your email when it's fixed."
                        if "Bug" in kind
                        else "✅ Suggestion sent! Megan will reply when it's been applied or if she has questions."
                    )
                    st.success(success_msg)
                    st.balloons()
                except Exception as e:
                    st.error(f"Couldn't save: {e}")


@st.dialog("✏️ Request a Change to an Existing Report", width="large")
def _show_change_request_dialog():
    st.caption(
        "Got a tweak in mind for a report that already exists? Fill this out "
        "and it lands in the **Automation Request Log** — someone will claim "
        "it and follow the same build → review flow as a new automation.\n\n"
        "**Something broken instead?** Use **\"Report a Bug\"**.\n\n"
        "**Brand-new report?** Use **\"New Automation Request\"**."
    )
    with st.form("change_request_form", clear_on_submit=True):
        cols = st.columns(2)
        with cols[0]:
            report_name = st.text_input("Existing report name", placeholder="e.g. 'OPT Focus Report'")
            requester = st.text_input("Your name", value=st.session_state.get("user", "") or "")
            requester_email = st.text_input(
                "Your email",
                placeholder="you@example.com",
                help="You'll get an email when someone claims it and another when it's ready for your review.",
            )
        with cols[1]:
            link = st.text_input("Sheet link", placeholder="https://…  (paste 'n/a' if none)")
            loom = st.text_input("Loom", placeholder="https://loom.com/…  (paste 'n/a' if none)")
            priority = st.selectbox(
                "Priority",
                PRIORITY_OPTIONS,
                index=2,
                help="How urgent is this? Don't worry, 5 is a real option.",
            )
        details = st.text_area(
            "Details — what should change?",
            height=140,
            placeholder="Describe the tweak: a new column, a different filter, updated formula, etc.",
        )
        submitted = st.form_submit_button("✏️ Submit Change Request", type="primary", use_container_width=True)

        if submitted:
            missing = [
                label for label, val in [
                    ("Existing report name", report_name),
                    ("Your name", requester),
                    ("Your email", requester_email),
                    ("Sheet link", link),
                    ("Loom", loom),
                    ("Details", details),
                ] if not str(val).strip()
            ]
            if missing:
                st.error("Please fill in every field — missing: " + ", ".join(missing))
            else:
                try:
                    # Title is prefixed so change requests are visually
                    # distinct on backlog cards even though they live in the
                    # same Sheet tab as new automation requests.
                    _add_intake(
                        title=f"✏️ Change Request: {report_name}",
                        sheet_link=link,
                        loom_link=loom,
                        description=details,
                        submitted_by=requester,
                        preferred_creator="",
                        currently_runs="",
                        priority=priority,
                        submitter_email=requester_email,
                    )
                    st.success(
                        "✅ Submitted to the Automation Request Log — someone will claim it "
                        "and you'll get an email when it's ready for your review."
                    )
                    st.balloons()
                except Exception as e:
                    st.error(f"Couldn't save the change request: {e}")


if st.session_state.get("show_bug_dialog"):
    st.session_state.show_bug_dialog = False
    _show_bug_dialog()

if st.session_state.get("show_change_request_dialog"):
    st.session_state.show_change_request_dialog = False
    _show_change_request_dialog()

if st.session_state.get("show_wireup_direct"):
    st.session_state.show_wireup_direct = False
    _clear_wireup_state()
    _show_wire_up_dialog(None)


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------

st.divider()
st.caption(
    "🐺 **Live more. Dream more. Do more.** — Alphalete Marketing"
)
