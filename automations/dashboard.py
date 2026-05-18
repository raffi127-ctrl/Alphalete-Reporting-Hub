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
import re
import subprocess
from pathlib import Path
from urllib.parse import quote as _urlquote

import sys

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

UPLOADED_REPORTS_FILE = WORKSPACE / "uploaded_reports.json"
UPLOADED_SCRIPTS_DIR = WORKSPACE / "automations" / "uploaded"
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
    try:
        import os
        os.kill(int(pid), 0)
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
                tail = Path(log_path).read_text().lower().splitlines()[-10:]
                tail_text = "\n".join(tail)
                if "done" in tail_text or "[ok]" in tail_text:
                    status = "success"
                elif "error" in tail_text or "failed" in tail_text or "traceback" in tail_text:
                    status = "failed"
            except Exception:
                pass
        try:
            _save_run_state_for(report_id, status if status != "unknown" else "success",
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


def _record_active_run(report_id: str, report_name: str, user: str, log_path: Path, pid: int) -> None:
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
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "hub_run_id": hub_run_id,
    })
    ACTIVE_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_RUNS_FILE.write_text(json.dumps(active, indent=2))


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
                os.kill(int(pid), signal.SIGKILL)
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
_FAILURE_SIGNATURES: list[tuple[tuple[str, ...], str, str]] = [
    (("port 9222", "no ownerville tab", "debug chrome isn't running",
      "no ownerville tab found", "chrome is open but no ownerville"),
     "Report Chrome isn't running, or the site got logged out.",
     "Launch Report Chrome from the sidebar, log into the report's "
     "website, then click Run Again."),
    (("invalid_grant", "refresherror", "token has been expired",
      "token has been revoked", "invalid credentials"),
     "The Google sign-in for the Sheet expired.",
     "Re-authorize Google access (the OAuth login), then click Run Again. "
     "Ask Megan if you're not sure how."),
    (("429", "quota exceeded", "resource_exhausted", "rate limit"),
     "Google Sheets hit its per-minute limit.",
     "Wait about 2 minutes, then click Run Again — the run picks up where "
     "it stopped, so nothing already done is lost."),
    (("phase 3 failed", "tableau pull (phase 3) failed",
      "tableau download failed", "tableau (phase 3)"),
     "The Tableau step couldn't load.",
     "The scrape itself already finished — only the Tableau sale-type data "
     "is missing. Open the Tableau tab, sign in, then click Run Again."),
]


def _diagnose_run_failure(log_text: str) -> tuple[str, str] | None:
    """Translate a failed run's log into (headline, what-to-do).
    Returns None when nothing recognizable matched — the caller then
    falls back to the report's generic failure message."""
    low = (log_text or "").lower()
    for needles, headline, fix in _FAILURE_SIGNATURES:
        if any(n in low for n in needles):
            return headline, fix
    return None


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


def _load_uploaded_reports_raw() -> list[dict]:
    """Read uploaded_reports.json and convert to AUTOMATED_REPORTS-compatible dicts.
    Called once at module load so the list of all reports is fresh on each rerun."""
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
        out.append({
            "id": r["id"],
            "name": r["name"],
            "creator": r.get("creator", ""),
            "emoji": r.get("emoji", "⭐"),
            "color": r.get("color", "#667eea"),
            "description": r.get("description", ""),
            "sheet_url": r.get("sheet_url", ""),
            "assignees": r.get("assignees", []),
            "schedule": r.get("schedule"),
            "checklist": r.get("checklist", []),
            "actions": [{
                "label": r.get("action_label", "Run Report"),
                "icon": "▶",
                "primary": True,
                "module": module,
                "args_fn": (lambda a=args_list: list(a)),
            }],
        })
    return out

# Team members. Each is a dict so we can add avatars/colors easily.
# Order: alphabetical by name.
MEMBERS = [
    # `email` powers the "Ask for an update" button on claimed backlog cards.
    # Fill these in (or correct any guesses) — when blank, the button opens
    # an empty mailto and the requester types the address manually.
    {"name": "Carlos",  "emoji": "🎩",        "color": "#E76F51", "email": "carloshidalgo349@gmail.com"},
    {"name": "Eve",     "emoji": "🌷",        "color": "#4ECDC4", "email": "alphaletereporting@gmail.com"},
    {"name": "JD",      "emoji": "⚡",        "color": "#9B59B6", "email": "josh.mascorro17@gmail.com"},
    {"name": "Maud",    "emoji": "🌟",        "color": "#FF6B6B", "email": "maudmiller4@gmail.com"},
    {"name": "Megan",   "emoji": "👩‍💼",     "color": "#667eea", "email": "meganhidalgo1191@gmail.com"},
    {"name": "Raf",     "emoji": "🚀",        "color": "#F4A261", "email": "raffi127@gmail.com"},
    {"name": "Twaddle", "emoji": "🦊",        "color": "#2A9D8F", "email": "dylanjtwaddle@gmail.com"},
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


def _last_completed_as_picker(today: dt.date | None = None) -> dt.date:
    return _last_completed_we_sunday(today) - dt.timedelta(days=7)


AUTOMATED_REPORTS = [
    {
        "id": "recruiting",
        "name": "Weekly Recruiting Report",
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
        "assignees": ["Eve"],   # primary owner; anyone can still run it
        "schedule": {
            "frequency": "weekly",
            "weekdays": [0],  # Monday
            "time": "8:00 AM",
            "estimated_minutes": 15,
        },
        "checklist": [
            {"text": "Launch Chrome with the recruiting profile",
             "action": "launch_chrome"},
            {"text": "Log into AppStream as **rhidalgo** (broader account) in the new Chrome window"},
        ],
        "post_run": {
            "message_success": "⏳ Done with **rhidalgo** (~43 offices filled). Now **log out of rhidalgo and log into rcaptain** in the same Chrome window, then click **Run Again** below to fill the remaining offices.",
            "message_failed": "❌ rhidalgo run failed. Check the log above. To retry, switch logins if needed and click Run Again.",
            "again_label": "🔁 Run Again with rcaptain",
            # This run isn't "complete" — it's a mid-process hand-off — so the
            # callout is amber, not green. Green is reserved for fully done.
            "success_tone": "warning",
        },
        "actions": [
            {
                "label": "Run This Week",
                "icon": "▶",
                "primary": True,
                "help": "Fills the most recent WE Sunday column",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda: ["--week", _last_completed_as_picker().isoformat()],
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
        "id": "daily-focus",
        "name": "Daily Recruiting Focus — Raf",
        "creator": "Megan",
        "emoji": "☀️",
        "color": "#4ECDC4",
        "category": "🎯 Recruiting",
        "description": "Per-ICD daily breakdown (Mon–Fri current week, last week, plus next-week scheduled) for Raf's captainship. Fills the 'Raf' tab.",
        "breakdown": (
            "WHAT IT DOES\n"
            "A day-by-day breakdown (Mon-Fri) of the recruiting numbers "
            "for **every ICD in Raf's captainship** — current week and "
            "last week, side by side.\n\n"
            "TO ADD AN ICD\n"
            "**1.**  Make sure the **rcaptain** AppStream account can see "
            "that ICD.\n"
            "**2.**  Add the ICD's name to the list on the right of the "
            "report (**column V**) — it has to match the AppStream name "
            "**exactly**.\n"
            "✅  The next run reads that list and fills in the new ICD "
            "automatically.\n\n"
            "IF AN ICD IS SKIPPED\n"
            "If an ICD can't be pulled — almost always because the account "
            "has no AppStream access — the card lists it once the run "
            "finishes.\n"
            "🔁  Log into an account that **has access**, then click "
            "**Retry** — only the skipped ICDs re-pull."
        ),
        "sheet_url": DAILY_FOCUS_SHEET_URL,
        "assignees": ["Maud"],
        "schedule": {
            # Weekly with weekdays [1..5] = Tue–Sat. (frequency 'daily' would
            # short-circuit and ignore the weekdays filter, so it'd appear
            # 7 days a week on the calendar.)
            "frequency": "weekly",
            "weekdays": [1, 2, 3, 4, 5],  # Tue–Sat
            "time": "8:00 AM",
            "estimated_minutes": 6,
        },
        "checklist": [
            {"text": "Launch Chrome with the recruiting profile",
             "action": "launch_chrome"},
            {"text": "Log into AppStream as **rcaptain** in the new Chrome window"},
        ],
        "post_run": {
            # The renderer at the call site handles three branches:
            #   • state file has items → gold callout listing each skipped ICD
            #   • state file exists but empty → "All ICDs filled" success
            #   • state file missing → THIS fallback text
            "message_success": "✅ Daily Focus run complete. If any ICDs couldn't be pulled (no AppStream access), they're listed below — log into an account that has access, then click retry. Already-pulled ICDs are skipped.",
            "message_failed": "❌ Run failed. Check the log, fix the issue, then retry below — only the missing ICDs are re-pulled.",
            "again_label": "🔁 Retry the skipped ICDs",
            "again_action": {
                "label": "Retry skipped ICDs",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: ["--captainship", "Raf", "--retry-inaccessible"],
            },
            "again_state_file": "output/daily_focus_state_Raf.json",
            "again_state_key": "inaccessible",
            "again_empty_message": "✅ All ICDs already pulled — nothing to retry.",
        },
        "actions": [
            {
                "label": "Run Daily Focus",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's daily focus report for Raf's captainship ICDs.",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: ["--captainship", "Raf"],
            },
            {
                "label": "Run for One ICD",
                "icon": "🎯",
                "needs_text": True,
                "text_label": "ICD name (as it appears in col V)",
                "help": "Just refill one ICD's section — handy after a typo fix or partial run",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda name: ["--captainship", "Raf", "--only", name],
            },
        ],
    },
    {
        "id": "daily-focus-carlos",
        "screenshot_from": "daily-focus",  # shares the Raf Daily Focus screenshot
        "name": "Daily Recruiting Focus — Carlos",
        "creator": "Megan",
        "emoji": "☀️",
        "color": "#E76F51",
        "category": "🎯 Recruiting",
        "description": "Per-ICD daily breakdown (Mon–Fri current week, last week, plus next-week scheduled) for Carlos's captainship. Fills the 'Carlos' tab.",
        "breakdown": (
            "WHAT IT DOES\n"
            "A day-by-day breakdown (Mon-Fri) of the recruiting numbers "
            "for **every ICD in Carlos's captainship** — current week and "
            "last week, side by side.\n\n"
            "TO ADD AN ICD\n"
            "**1.**  Make sure the **CarlosNLR** AppStream account can see "
            "that ICD.\n"
            "**2.**  Add the ICD's name to the list on the right of the "
            "report (**column V**) — it has to match the AppStream name "
            "**exactly**.\n"
            "✅  The next run reads that list and fills in the new ICD "
            "automatically.\n\n"
            "IF AN ICD IS SKIPPED\n"
            "If an ICD can't be pulled — almost always because the account "
            "has no AppStream access — the card lists it once the run "
            "finishes.\n"
            "🔁  Log into an account that **has access**, then click "
            "**Retry** — only the skipped ICDs re-pull."
        ),
        "sheet_url": DAILY_FOCUS_SHEET_URL,
        "assignees": ["Maud"],
        "schedule": {
            "frequency": "weekly",
            "weekdays": [1, 2, 3, 4, 5],  # Tue–Sat
            "time": "8:00 AM",
            "estimated_minutes": 6,
        },
        "checklist": [
            {"text": "Launch Chrome with the recruiting profile",
             "action": "launch_chrome"},
            {"text": "Log into AppStream as **CarlosNLR** in the new Chrome window"},
        ],
        "post_run": {
            "message_success": "✅ Daily Focus run complete. If any ICDs couldn't be pulled (no AppStream access), they're listed below — log into an account that has access, then click retry. Already-pulled ICDs are skipped.",
            "message_failed": "❌ Run failed. Check the log, fix the issue, then retry below — only the missing ICDs are re-pulled.",
            "again_label": "🔁 Retry the skipped ICDs",
            "again_action": {
                "label": "Retry skipped ICDs",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: ["--captainship", "Carlos", "--retry-inaccessible"],
            },
            "again_state_file": "output/daily_focus_state_Carlos.json",
            "again_state_key": "inaccessible",
            "again_empty_message": "✅ All ICDs already pulled — nothing to retry.",
        },
        "actions": [
            {
                "label": "Run Daily Focus",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's daily focus report for Carlos's captainship ICDs.",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda: ["--captainship", "Carlos"],
            },
            {
                "label": "Run for One ICD",
                "icon": "🎯",
                "needs_text": True,
                "text_label": "ICD name (as it appears in col V)",
                "help": "Just refill one ICD's section — handy after a typo fix or partial run",
                "module": "automations.recruiting_report.daily_focus",
                "args_fn": lambda name: ["--captainship", "Carlos", "--only", name],
            },
        ],
    },
]

# Merge in user-uploaded reports (saved by the Wire-Up dialog)
AUTOMATED_REPORTS.extend(_load_uploaded_reports_raw())


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

def _spawn_background_run(cmd: list[str], report_id: str, report_name: str) -> None:
    """Start a report run as a DETACHED background process. Its output is
    redirected straight to the run's log file, and the run is registered in
    active_runs.json — so the auto-refreshing active-run panel shows it and
    the dashboard never blocks waiting for the run to finish.

    Completion is picked up by _read_active_runs(): once the PID exits, that
    run is treated as a finished orphan — its status is read off the log tail
    and the post-run state is saved."""
    ACTIVE_RUNS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = ACTIVE_RUNS_LOG_DIR / f"{report_id}.log"
    log_handle = log_file.open("w")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(WORKSPACE),
            stdout=log_handle, stderr=subprocess.STDOUT,
        )
    finally:
        # The child keeps its own dup of the fd; the parent's copy isn't needed.
        log_handle.close()
    _record_active_run(report_id, report_name,
                       st.session_state.get("user", "unknown"),
                       log_file, proc.pid)


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
        return today + dt.timedelta(days=1)
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
        return True
    return day.weekday() in sched.get("weekdays", [])


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
    sh = _fill._client().open_by_key(HUB_ACTIVITY_SHEET_ID)
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
    except Exception:
        # Sheet write failed — local active_runs.json still works for this
        # user. Don't block the run on a coordination error.
        pass
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
        # Status is column 8, Ended At is column 9.
        ws.update_cell(cell.row, 8, status)
        ws.update_cell(cell.row, 9, dt.datetime.now().isoformat(timespec="seconds"))
        _hub_activity_rows.clear()
    except Exception:
        pass


def _hub_active_runs() -> list[dict]:
    """Return remote-active rows shaped like local active_runs entries."""
    cutoff = dt.datetime.now() - HUB_STALE_AFTER
    out = []
    for r in _hub_activity_rows():
        if str(r.get("Status", "")).lower() != "started":
            continue
        if r.get("Ended At"):
            continue
        try:
            started = dt.datetime.fromisoformat(str(r.get("Started At", "")))
        except Exception:
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
        ts_raw = r.get("Ended At") or r.get("Started At") or ""
        try:
            ts = dt.datetime.fromisoformat(str(ts_raw))
        except Exception:
            continue
        if ts < cutoff:
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


def _latest_run_summary(report_id: str) -> str | None:
    """Return compact text like 'Today · Megan · 1:06 AM', or None.
    Considers runs by any teammate, not just this machine."""
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
        return f"Last ran {day.lower()} · {user} · {time_str}"
    return None


def _ran_within_24h(report_id: str) -> tuple[bool, str | None, str | None]:
    """Was this report successfully run in the last 24h by anyone?
    Returns (yes/no, user, time_str)."""
    cutoff = dt.datetime.now() - dt.timedelta(hours=24)
    for r in _all_runs_merged(days=2):
        if r.get("report_id") == report_id and r.get("status") == "success" and r["_dt"] >= cutoff:
            return True, r.get("user", "someone"), r["_dt"].strftime("%I:%M %p").lstrip("0")
    return False, None, None


def _execute_action(report: dict, action: dict, picked, chrome_ok: bool) -> None:
    """Kick off one action as a background run, then rerun so the live
    run panel takes over. The dashboard never blocks waiting for the run."""
    if not chrome_ok:
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
    # -u → unbuffered, so the live run panel sees log lines as they happen.
    cmd = [VENV_PY, "-u", "-m", action["module"]] + args
    try:
        _spawn_background_run(cmd, report["id"], report["name"])
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
    if log_path:
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

    tail = _tail_log(log_path) if log_path else ""

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
        sh = _f._client().open_by_key(_df.DAILY_FOCUS_SPREADSHEET_ID)
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

    for name in unmapped:
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
                "✅ Confirm match", key=f"map_confirm_{name}",
                disabled=confirm_disabled, use_container_width=True,
                type="primary",
            ):
                _save_icd_mapping(name, suggestion["office_id"])
                _daily_focus_icds_in_sheet.clear()
                st.rerun()
            picker_state_key = f"map_picker_open_{name}"
            if btn_cols[1].button(
                "🔍 Pick different", key=f"map_pick_{name}",
                use_container_width=True,
            ):
                st.session_state[picker_state_key] = not st.session_state.get(picker_state_key, False)
                st.rerun()
            if btn_cols[2].button(
                "🚫 Not an ICD", key=f"map_skip_{name}",
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
                    key=f"map_picker_{name}",
                    label_visibility="collapsed",
                )
                save_cols = st.columns([1, 4])
                if save_cols[0].button(
                    "💾 Save", key=f"map_save_{name}",
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


def _render_report_screenshot(report: dict) -> None:
    """Right-column content on a report's Library page: the report's
    screenshot in a fixed-height frame so it lines up with the run card.
    A report can borrow another report's screenshot via `screenshot_from`
    — in that case there's no uploader here (update it on that report)."""
    import base64
    from PIL import Image as _Image
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
                _Image.open(_up).convert("RGB").save(shot, "PNG")
                st.rerun()
            except Exception as e:
                st.error(f"Couldn't save that image: {e}")


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


def _render_report_card(report: dict, today: dt.date, chrome_ok: bool) -> None:
    """One unified card per report: header, gated checklist, primary run button,
    secondary actions inside an expander."""
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
        if ran_today:
            pills += "<span class='pill pill-ok'>✅ DONE TODAY</span>"
        elif is_due:
            pills += "<span class='pill pill-due'>DUE TODAY</span>"
        if sched:
            pills += f"<span class='pill pill-info'>{sched.get('time', '')} • ~{sched.get('estimated_minutes', '?')} min</span>"
        if pills:
            st.markdown(pills, unsafe_allow_html=True)
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
        st.link_button("📂 Open Sheet", report["sheet_url"])

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
        if report["id"] in ("daily-focus", "daily-focus-carlos"):
            _render_daily_focus_mapping_prompt(
                "Carlos" if report["id"] == "daily-focus-carlos" else "Raf")

        # Weekly Recruiting only: ask the runner to resolve any tab whose name
        # matches more than one AppStream office, before the run.
        if report["id"] == "recruiting":
            _render_recruiting_office_picker()

        # Checklist (gates the primary run button)
        all_checked = True
        if checklist:
            with st.expander("📋 Pre-flight checklist", expanded=(is_due and not ran_today)):
                for idx, step in enumerate(checklist):
                    if step.get("info"):
                        st.info(step["text"])
                        continue
                    cols = st.columns([5, 3])
                    ck_key = f"check_{report['id']}_{idx}"
                    msg_key = f"msg_{report['id']}_{idx}"
                    with cols[0]:
                        ck = st.checkbox(step["text"], key=ck_key)
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
            recent, recent_user, recent_time = _ran_within_24h(report["id"])
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
            missing_items: list[str] = []
            state_file_exists = False
            if again_state_rel and again_state_key:
                state_path = WORKSPACE / again_state_rel
                try:
                    if state_path.exists():
                        state_file_exists = True
                        data = json.loads(state_path.read_text())
                        missing_items = list(data.get(again_state_key) or [])
                except Exception:
                    pass
            nothing_to_retry = state_file_exists and not missing_items

            with st.container(border=True):
                if last_run["status"] == "success":
                    if missing_items:
                        # High-visibility gold callout listing the exact ICDs
                        # that didn't pull — these need AppStream access from
                        # the logged-in account. The retry button re-pulls
                        # just these once a login with access is in place.
                        _names = ", ".join(missing_items)
                        st.markdown(
                            "<div style='background:linear-gradient(135deg, #FFF3D6 0%, #FFE4A8 100%); "
                            "border:2px solid #C9A85C; border-radius:10px; "
                            "padding:14px 18px; margin:4px 0 10px; color:#5C4220;'>"
                            "<div style='font-weight:800; font-size:1.15rem;'>"
                            f"⚠️ Run complete — {len(missing_items)} "
                            f"ICD{'s' if len(missing_items)!=1 else ''} not pulled "
                            "(no AppStream access)</div>"
                            "<div style='margin-top:6px; font-size:0.95rem;'>"
                            f"<b>{_names}</b></div>"
                            "<div style='margin-top:8px; font-size:0.95rem;'>"
                            "If another AppStream account has access to these, log "
                            "into it in the report's Chrome window, then click the "
                            "button below to re-pull just the missing ICDs."
                            "</div></div>",
                            unsafe_allow_html=True,
                        )
                    elif state_file_exists:
                        # An empty "inaccessible" list isn't real success if
                        # ICDs are still unmapped — the run silently skips
                        # those, so nothing got filled for them.
                        _dfu = []
                        if report["id"] in ("daily-focus", "daily-focus-carlos"):
                            _dfu = _daily_focus_unmapped(
                                "Carlos" if report["id"] == "daily-focus-carlos"
                                else "Raf")
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
                    else:
                        # Reports without a state-file config fall back to the
                        # generic post_run success message.
                        msg = post_run_cfg.get(
                            "message_success",
                            "✅ Run finished. If any ICD showed 'not accessible' "
                            "in the log, switch AppStream logins and run again.",
                        )
                        # Amber for mid-process hand-off messages; green only
                        # when the report is genuinely complete.
                        if post_run_cfg.get("success_tone") == "warning":
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
                    if _diag:
                        st.markdown(
                            "<div style='background:linear-gradient(135deg,#FFE4E0 0%,#FFCEC7 100%);"
                            "border:2px solid #D8261C;border-radius:10px;"
                            "padding:14px 18px;margin:4px 0 10px;color:#5C1A14;'>"
                            "<div style='font-weight:800;font-size:1.1rem;'>"
                            f"❌ {_diag[0]}</div>"
                            "<div style='margin-top:6px;font-size:0.95rem;'>"
                            f"<b>What to do:</b> {_diag[1]}</div></div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        msg = post_run_cfg.get(
                            "message_failed",
                            "❌ Run failed. Check the log below, then click Run Again.",
                        )
                        st.error(msg)

                    # Raw log — expanded when we couldn't diagnose it.
                    if _log_tail_text:
                        with st.expander("📜 Run log (last 40 lines)",
                                         expanded=not bool(_diag)):
                            st.code(_log_tail_text, language="log")

                    # One click sends this failure to Megan as a bug report.
                    _glitch_key = f"glitch_sent_{report['id']}"
                    if st.session_state.get(_glitch_key):
                        st.success("🚩 Sent to Megan — she'll follow up by email.")
                    elif st.button("🚩 Report this glitch to Megan",
                                   key=f"glitch_{report['id']}",
                                   use_container_width=True):
                        try:
                            _file_run_glitch(report, _log_tail_text,
                                             st.session_state.get("user", ""))
                            st.session_state[_glitch_key] = True
                            st.rerun()
                        except Exception as e:
                            st.error(f"Couldn't send the glitch report: {e}")

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
                again_action = post_run_cfg.get("again_action") or primary
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
                            st.caption("Log into an AppStream account with access, then click →")
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
    sh = _fill._client().open_by_key(INTAKE_SPREADSHEET_ID)
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
def _compute_leaderboard() -> list[dict]:
    """Per-teammate Hub-activity stats + badges, ranked by total activity.

    All from data the Hub already records — the intake Sheet (requests /
    reports built / reviews) and the Hub Activity log (report runs). No
    weighting: every action counts as 1. Cached 60s so it never slows a
    page render. Returns one dict per MEMBER, in rank order."""
    members = [m["name"] for m in MEMBERS]
    stats = {n: {"requests": 0, "builds": 0, "runs": 0, "reviews": 0}
             for n in members}
    try:
        intake = _read_intake()
    except Exception:
        intake = []
    for r in intake:
        submitter = str(r.get("Submitted By") or "").strip()
        status = str(r.get("Status") or "").strip()
        if submitter in stats:
            stats[submitter]["requests"] += 1
            if status == "Done":
                stats[submitter]["reviews"] += 1   # reviewed + approved it

    # Reports built — counted from the library itself (each report's
    # `creator`), so built-in reports count too, not only ones that came
    # through the intake/upload flow.
    for rep in AUTOMATED_REPORTS:
        creator = str(rep.get("creator") or "").strip()
        if creator in stats:
            stats[creator]["builds"] += 1

    for run in _hub_activity_rows():
        runner = str(run.get("User") or "").strip()
        if runner in stats:
            stats[runner]["runs"] += 1

    board = []
    for n in members:
        s = stats[n]
        board.append({
            "name": n,
            "requests": s["requests"], "builds": s["builds"],
            "runs": s["runs"], "reviews": s["reviews"],
            "total": s["requests"] + s["builds"] + s["runs"] + s["reviews"],
        })
    board.sort(key=lambda x: (-x["total"], x["name"]))
    # 1-based rank; ties share a rank.
    _rank, _prev = 0, None
    for i, row in enumerate(board):
        if row["total"] != _prev:
            _rank, _prev = i + 1, row["total"]
        row["rank"] = _rank

    # Badges: #1 in each category, awarded only when the top count is > 0
    # (no badge on a score of 0). Ties → everyone tied gets it.
    _BADGES = [
        ("total",    "👑", "Hub MVP"),
        ("builds",   "🏆", "Top Creator"),
        ("requests", "📨", "Top Requester"),
        ("runs",     "🏃", "Top Runner"),
        ("reviews",  "👀", "Top Reviewer"),
    ]
    for row in board:
        row["badges"] = []
    for stat, emoji, label in _BADGES:
        top = max((r[stat] for r in board), default=0)
        if top <= 0:
            continue
        for r in board:
            if r[stat] == top:
                r["badges"].append({"emoji": emoji, "label": label})
    return board


def _badge_chip(b: dict) -> str:
    """Inline HTML chip for a leaderboard badge — emoji + label, so it
    reads at a glance instead of being a bare emoji."""
    return (
        "<span style='display:inline-block;background:#FFF3D6;color:#8B6914;"
        "border-radius:999px;padding:2px 9px;font-size:0.78rem;font-weight:700;"
        f"margin:2px 3px 2px 0;white-space:nowrap'>{b['emoji']} {b['label']}</span>"
    )


def _render_leaderboard() -> None:
    """Ranked board — every teammate by total Hub activity, with badges."""
    board = _compute_leaderboard()
    if not board or all(r["total"] == 0 for r in board):
        st.caption("No Hub activity logged yet — the leaderboard fills in "
                   "as people submit, build, run, and review reports.")
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    NUM = "padding:8px 14px;text-align:right;white-space:nowrap"
    head = (
        "<tr style='font-size:0.8rem;opacity:0.55;text-transform:uppercase;"
        "letter-spacing:0.03em'>"
        "<td style='padding:6px 12px'></td>"
        "<td style='padding:6px 12px'>Teammate</td>"
        f"<td style='{NUM}'>🏆 Built</td><td style='{NUM}'>📨 Requested</td>"
        f"<td style='{NUM}'>🏃 Runs</td><td style='{NUM}'>👀 Reviews</td>"
        f"<td style='{NUM}'>Total</td></tr>"
    )
    rows_html = ""
    for r in board:
        rk = medals.get(r["rank"], f"#{r['rank']}")
        badges = "".join(_badge_chip(b) for b in r["badges"])
        name_cell = r["name"]
        if badges:
            name_cell += f"<br><span style='font-weight:400'>{badges}</span>"
        rows_html += (
            "<tr style='border-top:1px solid rgba(0,0,0,0.08)'>"
            f"<td style='padding:8px 12px;font-size:1.15rem'>{rk}</td>"
            f"<td style='padding:8px 12px;font-weight:700'>{name_cell}</td>"
            f"<td style='{NUM}'>{r['builds']}</td>"
            f"<td style='{NUM}'>{r['requests']}</td>"
            f"<td style='{NUM}'>{r['runs']}</td>"
            f"<td style='{NUM}'>{r['reviews']}</td>"
            f"<td style='{NUM};font-weight:800;font-size:1.15rem'>{r['total']}</td>"
            "</tr>"
        )
    st.markdown(
        "<table style='width:100%;border-collapse:collapse'>"
        + head + rows_html + "</table>",
        unsafe_allow_html=True,
    )


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
    sh = _fill._client().open_by_key(INTAKE_SPREADSHEET_ID)
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


def _file_run_glitch(report: dict, log_tail: str, user: str) -> str:
    """File a failed report run as a bug report — lands on the Bug Reports
    tab, which emails Megan. Auto-fills the report name, a plain-English
    cause (if recognizable), and the run log. Returns the new bug ID."""
    diag = _diagnose_run_failure(log_tail)
    diag_line = f"Likely cause: {diag[0]}\n{diag[1]}\n\n" if diag else ""
    details = (
        f"Automatic glitch report — a run of '{report['name']}' failed.\n\n"
        f"{diag_line}"
        f"--- Run log (last lines) ---\n"
        f"{(log_tail or '').strip() or '(no log was captured)'}"
    )
    return _add_bug(
        title=f"Run glitch — {report['name']}",
        bug_type="Bug / something broke",
        sheet_link=report.get("sheet_url", ""),
        loom_link="",
        details=details,
        submitted_by=user or "unknown",
        submitter_email=_member_email(user) or "",
        priority=PRIORITY_OPTIONS[1],
    )


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
    """Save a wire-up: write the script to automations/uploaded/<id>.py and
    append metadata to uploaded_reports.json. Returns (ok, message)."""
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", metadata["id"]).strip("_").lower()
    if not safe_id:
        return False, "Report id couldn't be derived from name."
    # Validate Python syntax before saving
    try:
        ast.parse(script_text)
    except SyntaxError as e:
        return False, f"Script has a Python syntax error: {e}"

    UPLOADED_SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    init_file = UPLOADED_SCRIPTS_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")
    script_path = UPLOADED_SCRIPTS_DIR / f"{safe_id}.py"
    script_path.write_text(script_text)

    metadata["id"] = safe_id
    metadata["module"] = f"automations.uploaded.{safe_id}"

    existing = []
    if UPLOADED_REPORTS_FILE.exists():
        try:
            existing = json.loads(UPLOADED_REPORTS_FILE.read_text())
        except Exception:
            existing = []
    # If an entry with same id exists, replace it (allows re-wire)
    existing = [e for e in existing if e.get("id") != safe_id]
    existing.append(metadata)
    UPLOADED_REPORTS_FILE.write_text(json.dumps(existing, indent=2))
    return True, f"Saved to automations/uploaded/{safe_id}.py and uploaded_reports.json"


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
    return True, "Report approved and added to the Library."


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
        }

        # Validate the script up front (same check _save_uploaded_report runs)
        # so a syntax error is caught before staging.
        try:
            ast.parse(script_text)
        except SyntaxError as e:
            st.error(f"Script has a Python syntax error: {e}")
            return

        if entry.get("ID"):
            # Intake-linked upload → goes through the requester review loop.
            # Stage it; it only reaches the Library once the requester
            # clicks Approve. review_cc rides along for the approval email.
            _stage_pending_report(str(entry["ID"]), metadata, script_text, review_cc)
            # Stash the follow-up notes on the intake row BEFORE flipping
            # status — the Apps Script emails on the status change and
            # reads this cell for the body.
            try:
                _iws = _intake_ws()
                _icell = _iws.find(str(entry["ID"]))
                if _icell:
                    if "Review Notes" in INTAKE_HEADERS:
                        _iws.update_cell(
                            _icell.row,
                            INTAKE_HEADERS.index("Review Notes") + 1,
                            followup_notes.strip(),
                        )
                    if "Report Breakdown" in INTAKE_HEADERS:
                        _iws.update_cell(
                            _icell.row,
                            INTAKE_HEADERS.index("Report Breakdown") + 1,
                            breakdown.strip(),
                        )
            except Exception:
                pass
            _set_intake_status(str(entry["ID"]), "In Review")
            try:
                _append_intake_note(
                    str(entry["ID"]),
                    f"📤 Uploaded for review — '{name}'. Requester: please "
                    f"review and either request edits or approve.",
                    st.session_state.get("user") or "creator",
                )
            except Exception:
                pass
            requester = entry.get("Submitted By", "the requester")
            st.success(
                f"✅ Sent to **{requester}** for review. It moves to the Report "
                f"Library only after they approve it."
            )
            st.balloons()
        else:
            # Direct upload (no intake card) — no review loop; register now.
            ok, msg = _save_uploaded_report(metadata, script_text)
            if not ok:
                st.error(msg)
                return
            target_text = (
                "in the **🔍 Unassigned** section of the Report Library"
                if assignee == "Not sure yet"
                else f"on **{assignee}**'s dashboard"
            )
            st.success(f"✅ Uploaded! It will appear {target_text}.")
            st.balloons()
            st.markdown(
                "**Heads up:** The new automation is saved on this Mac. "
                "To make it available to the whole team, ask Megan to commit + push to GitHub."
            )


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
            _needs_login = bool(meta.get("needs_login") or meta.get("checklist"))
            _chrome_ok = _check_chrome_running() if _needs_login else True
            if _needs_login:
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
            st.markdown(
                "👀 **Review it:** run the report once to confirm it works. "
                "The Approve button unlocks after a successful run.\n\n"
                "Spot a glitch, a flaw, or anything you'd change? Use "
                "**📝 Request Edits** below to send it back to the creator "
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
                            st.link_button(_lbl, _url, use_container_width=True)

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
            if review_mode:
                _render_review_panel(entry)
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
                st.link_button("📂 Open Sheet", entry["Sheet Link"], use_container_width=True)
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

    # Bug triage is Megan-only right now. Other people on the hub can still
    # see the bugs (for visibility), but the action buttons are hidden so
    # only Megan can move them between states.
    _is_megan = (_detect_hub_user() or "").strip().lower() == "megan"

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
            if _is_megan:
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
                st.caption("⏳ Waiting on Megan to triage.")
        elif status == "In Progress" or status == "Needs Info":
            if _is_megan:
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
                st.caption(f"⏳ Megan is on it — current status: **{status}**.")
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
        if _url_view in {"home", "user", "overview", "library", "backlog", "bugs"}
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


_VALID_VIEWS = {"home", "user", "overview", "library", "backlog", "bugs"}


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


def _go_overview():
    _set_view("overview")


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
    # Launch Report Chrome — scraping reports need the special port-9222
    # Chrome the automations attach to, so the launcher is one click away.
    if st.button("🚀 Launch Report Chrome", use_container_width=True, key="nav_launch_chrome"):
        ok, msg = _launch_chrome()
        if ok:
            st.toast(msg, icon="🚀")  # transient — no persistent green box
        else:
            st.error(msg)
    if st.button("📊 7-Day Overview", use_container_width=True, key="nav_overview"):
        _go_overview()
        st.rerun()

    # Chrome status check — other code reads `chrome_ok`; the pill gives the
    # Launch button above immediate feedback.
    chrome_ok = _check_chrome_running()
    _pill_class = "ok" if chrome_ok else "warn"
    _pill_label = "🟢 Chrome connected" if chrome_ok else "🔴 Chrome offline"
    st.markdown(
        f'<div class="system-status-pill {_pill_class}">{_pill_label}</div>',
        unsafe_allow_html=True,
    )
    if not chrome_ok:
        st.warning("Chrome not running — click 🚀 Launch Report Chrome above.")
        with st.expander("Chrome troubleshooting"):
            st.markdown("**If Chrome won't launch, run this in Terminal:**")
            st.code("rm ~/.config/recruiting-report/chrome-attach/Singleton*", language="bash")

    # Remaining tasks today (user view only)
    if st.session_state.view == "user" and st.session_state.user:
        st.markdown("---")
        st.markdown("### 📋 Today's Tasks")
        if st.session_state.user == "Unassigned":
            my_reports = [r for r in AUTOMATED_REPORTS if not r.get("assignees")]
        else:
            my_reports = [r for r in AUTOMATED_REPORTS if st.session_state.user in r.get("assignees", [])]
        due_today_for_me = [r for r in my_reports if _is_due_today(r, today)]
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
    if st.button("📥 Upload Built Automation", use_container_width=True, key="nav_upload"):
        st.session_state.show_wireup_direct = True
    if st.button("✏️ Request Change to Existing Report", use_container_width=True, key="open_change_request_btn"):
        st.session_state.show_change_request_dialog = True

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
# HOME VIEW — name picker + Alphalete Overview button
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
    _due_today = [r for r in AUTOMATED_REPORTS if _is_due_today(r, today)]
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
    _badges_by_member = {r["name"]: r["badges"] for r in _compute_leaderboard()}
    # Build pack cards: synthetic "Unassigned" card first, then real members.
    # Clicking it opens a filtered user-style page showing only reports with
    # no assignees, so someone can pick them up.
    UNASSIGNED_CARD = {"name": "Unassigned", "emoji": "🔍", "is_unassigned": True}
    pack_cards = [UNASSIGNED_CARD] + list(MEMBERS)
    PACK_COLS = 3
    rows = [pack_cards[i:i + PACK_COLS] for i in range(0, len(pack_cards), PACK_COLS)]
    for row in rows:
        # Always use the same column count so a partial last row keeps cards
        # at the same width as full rows. If the row is short, center it by
        # leaving equal empty slots on either side.
        if len(row) < PACK_COLS:
            cols = st.columns(PACK_COLS)
            pad = (PACK_COLS - len(row)) // 2
            card_cols = cols[pad:pad + len(row)]
        else:
            cols = st.columns(PACK_COLS)
            card_cols = cols
        for col, member in zip(card_cols, row):
            with col:
                is_unassigned = member.get("is_unassigned", False)
                if is_unassigned:
                    unassigned_reports = [r for r in AUTOMATED_REPORTS if not r.get("assignees")]
                    count = len(unassigned_reports)
                else:
                    my_reports = [r for r in AUTOMATED_REPORTS if member["name"] in r.get("assignees", [])]
                    due_count = sum(1 for r in my_reports if _is_due_today(r, today))
                with st.container(border=True):
                    st.markdown(
                        f"<div style='text-align:center; font-size: 3.5rem; line-height: 1.0; margin-bottom: 0.4rem'>{member['emoji']}</div>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='text-align:center; font-size: 1.3rem; font-weight: 700; margin-bottom: 0.3rem'>{member['name']}</div>",
                        unsafe_allow_html=True,
                    )
                    _mbadges = [] if is_unassigned else _badges_by_member.get(member["name"], [])
                    if _mbadges:
                        _bhtml = "".join(_badge_chip(b) for b in _mbadges)
                        st.markdown(
                            f"<div style='text-align:center; margin-bottom:0.3rem'>{_bhtml}</div>",
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
# OVERVIEW VIEW — 7-day run log with miss alerts
# --------------------------------------------------------------------------

elif st.session_state.view == "overview":
    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
        <h1>📊 Alphalete Marketing — 7-Day Overview</h1>
        <p>Every report run by anyone, last 7 days.</p>
    </div>
    """, unsafe_allow_html=True)

    # Hub leaderboard — every teammate ranked by total activity.
    st.markdown("### 🏆 Hub Leaderboard")
    _render_leaderboard()
    st.markdown("")

    # Currently-running activity log (anyone's runs)
    active_now = _read_active_runs()
    if active_now:
        st.markdown("### 🏃 Running Right Now")
        for run in active_now:
            try:
                started = dt.datetime.fromisoformat(run.get("started_at", ""))
                elapsed = dt.datetime.now() - started
                elapsed_str = f"{int(elapsed.total_seconds() // 60)}m {int(elapsed.total_seconds() % 60)}s"
            except Exception:
                elapsed_str = "?"
            with st.container(border=True):
                st.markdown(
                    f"⏳ **{run.get('report_name', '?')}** — started by **{run.get('user', '?')}** • running for **{elapsed_str}**"
                )

    # Missed runs alert section
    missed = _missed_runs(AUTOMATED_REPORTS, days=7, today=today)
    if missed:
        st.markdown("### ⚠️ Missed Runs")
        with st.container(border=True):
            for m in missed:
                r = m["report"]
                d = m["missed_date"]
                assignees = ", ".join(r.get("assignees", [])) or "unassigned"
                st.markdown(
                    f"⚠️ **{r['name']}** was due on **{d.strftime('%a %b %d')}** — assigned to **{assignees}** — no successful run logged"
                )
    else:
        st.success("✅ No missed runs in the last 7 days. Great work, team!")

    # Recent runs activity feed — merged across all teammates' machines.
    st.markdown("### 🗓️ Recent Activity")
    runs = _all_runs_merged(days=7)
    if not runs:
        st.info("No runs logged yet. As people use the dashboard, runs will appear here.")
    else:
        # Group by date
        by_date: dict = {}
        for r in runs:
            day = r["_dt"].date()
            by_date.setdefault(day, []).append(r)
        for day in sorted(by_date.keys(), reverse=True):
            label = day.strftime("%A, %b %d")
            if day == today:
                label += "  •  TODAY"
            elif day == today - dt.timedelta(days=1):
                label += "  •  Yesterday"
            report_lookup = {rep["id"]: rep for rep in AUTOMATED_REPORTS}
            with st.expander(f"📅 {label}  —  {len(by_date[day])} run{'s' if len(by_date[day]) != 1 else ''}", expanded=(day == today)):
                for r in by_date[day]:
                    icon = "✅" if r.get("status") == "success" else "❌"
                    time_str = r["_dt"].strftime("%I:%M %p")
                    rep = report_lookup.get(r.get("report_id"))
                    sheet_url = rep.get("sheet_url") if rep else None
                    sheet_link = f"  •  [📂 Open Sheet]({sheet_url})" if sheet_url else ""
                    st.markdown(
                        f"{icon}  **{time_str}**  •  {r.get('report_name', r.get('report_id', '?'))}  •  ran by **{r.get('user', '?')}**{sheet_link}"
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

        # Group reports into sections. Anything with empty/missing `assignees`
        # lands in a top "Unassigned" section so it's easy to find and claim.
        # Otherwise, group by `category` field (defaults to "All Reports").
        UNASSIGNED_LABEL = "🔍 Unassigned reports"
        sections: dict[str, list] = {}
        for r in AUTOMATED_REPORTS:
            if _lib_query and _lib_query not in (
                f"{r.get('name', '')} {r.get('description', '')}".lower()
            ):
                continue
            if not r.get("assignees"):
                cat = UNASSIGNED_LABEL
            else:
                cat = r.get("category", "All Reports")
            sections.setdefault(cat, []).append(r)

        # Render Unassigned first if any, then the rest in insertion order
        ordered_sections = []
        if UNASSIGNED_LABEL in sections:
            ordered_sections.append((UNASSIGNED_LABEL, sections.pop(UNASSIGNED_LABEL)))
        ordered_sections.extend(sections.items())
        if not ordered_sections:
            st.info(f"No reports match “{_lib_query}”."
                    if _lib_query else "No reports in the library yet.")

        # Mid-flow runs — used to decorate cards with a "pick up" pill so
        # anyone browsing the library sees that this report is partway through.
        lib_persisted = _load_all_run_state()
        for section_name, reports_in_section in ordered_sections:
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
                        if st.button(
                            _label,
                            key=f"lib_btn_{report['id']}",
                            use_container_width=True,
                            help=("Mid-run — pick up where you left off"
                                  if _pickup else report.get("description") or None),
                        ):
                            st.session_state["library_report_id"] = report["id"]
                            st.rerun()


# --------------------------------------------------------------------------
# USER VIEW — that user's today's schedule + their reports
# --------------------------------------------------------------------------

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
        # Personal Hub-activity standing — rank, the four stats, badges.
        _lb = _compute_leaderboard()
        _me = next((r for r in _lb if r["name"] == user_name), None)
        if _me:
            _medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(_me["rank"], f"#{_me['rank']}")
            _bhtml = "".join(_badge_chip(b) for b in _me["badges"])
            with st.container(border=True):
                st.markdown(
                    "<div style='font-size:1.1rem;font-weight:700;margin-bottom:6px'>"
                    f"🏆 Your Hub standing — {_medal}</div>"
                    "<div style='font-size:0.97rem;line-height:1.9'>"
                    f"🏆 <b>{_me['builds']}</b> reports built &nbsp;&nbsp;&nbsp; "
                    f"📨 <b>{_me['requests']}</b> requests submitted &nbsp;&nbsp;&nbsp; "
                    f"🏃 <b>{_me['runs']}</b> report runs &nbsp;&nbsp;&nbsp; "
                    f"👀 <b>{_me['reviews']}</b> reviews completed</div>"
                    + (f"<div style='margin-top:8px'>{_bhtml}</div>" if _bhtml else ""),
                    unsafe_allow_html=True,
                )

        # 7-day schedule strip — visual overview of this user's responsibilities
        # for the week ahead. One row, 7 columns; auto-updates as new reports
        # get assigned to them (or as schedules change).
        st.markdown("### 📅 This week")
        _cal_cols = st.columns(7)
        for _i in range(7):
            _day = today + dt.timedelta(days=_i)
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
                if _due:
                    for _r in _due:
                        # Click jumps straight to the report's Library card
                        # so the user can run it without hunting for it.
                        if st.button(
                            f"{_r.get('emoji', '📄')} {_r['name']}",
                            key=f"cal_{user_name}_{_day.strftime('%Y%m%d')}_{_r['id']}",
                            use_container_width=True,
                            help="Open this report to run it",
                        ):
                            st.session_state["library_report_id"] = _r["id"]
                            st.session_state["library_came_from"] = ("user", user_name)
                            _set_view("library")
                            st.rerun()
                else:
                    st.markdown(
                        "<div style='text-align:center; color:#bbb; "
                        "font-size:0.8em; padding:4px 0'>—</div>",
                        unsafe_allow_html=True,
                    )
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

        # Two-column layout below the hero:
        #   left:  "Completed Today" checklist for this user
        #   right: in-progress banner + this user's reports
        user_layout = st.columns([1, 4])

        with user_layout[0]:
            st.markdown("### ✅ Completed Today")
            completed_today = _get_completed_today(user_name)
            if not completed_today:
                st.caption("Nothing marked completed yet today.")
            else:
                for item in completed_today:
                    report_id = item.get("report_id", "")
                    report_name = item.get("report_name", "?")
                    try:
                        marked_dt = dt.datetime.fromisoformat(item.get("marked_at", ""))
                        marked_str = marked_dt.strftime("%I:%M %p").lstrip("0")
                    except Exception:
                        marked_str = ""
                    with st.container(border=True):
                        st.markdown(
                            f"<div style='font-weight:600'>✓ {report_name}</div>"
                            f"<div style='font-size:0.8rem; color:#777'>marked at {marked_str}</div>",
                            unsafe_allow_html=True,
                        )
                        if st.button(
                            "↩ Undo",
                            key=f"undo_completed_{report_id}_{item.get('run_ts', '')}",
                            use_container_width=True,
                        ):
                            _unmark_run_completed(user_name, report_id, item.get("run_ts", ""))
                            st.rerun()

        with user_layout[1]:
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
                                    # If post_run defines a separate retry action
                                    # (e.g. daily-focus's --retry-inaccessible),
                                    # prefer it over re-running the full primary.
                                    again_action = post_run_cfg.get("again_action") or primary
                                    again_state_rel = post_run_cfg.get("again_state_file")
                                    again_state_key = post_run_cfg.get("again_state_key")
                                    again_empty_msg = post_run_cfg.get(
                                        "again_empty_message",
                                        "✅ Nothing to retry from the previous run.",
                                    )
                                    nothing_to_retry = False
                                    if again_state_rel and again_state_key:
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

            if my_reports:
                st.markdown("## 🚀 Your Reports")
                st.caption("Click a report name to open it and run.")
                in_progress_ids = {r["id"] for r in in_progress}
                for report in my_reports:
                    is_pickup = report["id"] in in_progress_ids
                    if is_pickup:
                        saved_ts = persisted.get(report["id"], {}).get("ts", "")
                        try:
                            saved_str = dt.datetime.fromisoformat(saved_ts).strftime("%I:%M %p").lstrip("0")
                        except Exception:
                            saved_str = ""
                        # Gold banner above the row — visually marks this report
                        # as "still in flight today." Click behavior is unchanged.
                        st.markdown(
                            "<div style='background:linear-gradient(135deg, #FFF8E7 0%, #FFF3D6 100%); "
                            "border-left:4px solid #C9A85C; border-radius:6px; "
                            "padding:6px 12px; margin-top:0.4rem; margin-bottom:-0.2rem; "
                            "font-size:0.9em; color:#5C4220'>"
                            "<span style='display:inline-block; background:#C9A85C; color:#2A1F12; "
                            "padding:1px 8px; border-radius:999px; font-size:0.72em; "
                            "font-weight:800; letter-spacing:0.02em; margin-right:8px'>"
                            "📌 PICK UP WHERE YOU LEFT OFF"
                            "</span>"
                            + (f"<span style='color:#8B6914'>last run {saved_str} today</span>"
                               if saved_str else "")
                            + "</div>",
                            unsafe_allow_html=True,
                        )
                    _row = st.columns([3, 2])
                    with _row[0]:
                        if st.button(
                            f"{report.get('emoji', '📄')} {report['name']}",
                            key=f"profile_run_{report['id']}",
                            use_container_width=True,
                        ):
                            st.session_state["library_report_id"] = report["id"]
                            st.session_state["library_came_from"] = ("user", user_name)
                            _set_view("library")
                            st.rerun()
                    with _row[1]:
                        st.markdown(
                            "<div style='padding:0.5rem 0.6rem; color:#666; "
                            "font-size:0.9em'>"
                            f"📅 {_format_schedule_short(report)}"
                            "</div>",
                            unsafe_allow_html=True,
                        )
            else:
                st.info(f"No reports assigned to {user_name} yet.")


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
