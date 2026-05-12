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
import shlex
import subprocess
from pathlib import Path
from urllib.parse import quote as _urlquote

import sys

import streamlit as st

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from automations.recruiting_report import fill as _fill  # noqa: E402

VENV_PY = str(WORKSPACE / ".venv" / "bin" / "python")
LOG_DIR = WORKSPACE / "output" / "logs"
RUNS_LOG = LOG_DIR / "runs.jsonl"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{_fill.SPREADSHEET_ID}/edit"

UPLOADED_REPORTS_FILE = WORKSPACE / "uploaded_reports.json"
UPLOADED_SCRIPTS_DIR = WORKSPACE / "automations" / "uploaded"
# Manual library assignments live here so anyone can claim an unassigned
# report from the Library view without editing source files. The file is a
# simple {report_id: [assignee_name, ...]} JSON dict; values override
# whatever assignees came from the source (uploaded_reports.json or the
# hardcoded AUTOMATED_REPORTS list).
LIBRARY_ASSIGNMENTS_FILE = WORKSPACE / "library_assignments.json"
RUN_STATE_FILE = WORKSPACE / "output" / "run_state.json"
ACTIVE_RUNS_FILE = WORKSPACE / "output" / "active_runs.json"
ACTIVE_RUNS_LOG_DIR = WORKSPACE / "output" / "logs" / "active"
COMPLETED_MARKS_FILE = WORKSPACE / "output" / "completed_marks.json"
RUN_STATE_TTL_HOURS = 24


def _pid_alive(pid: int) -> bool:
    try:
        import os
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _read_active_runs() -> list[dict]:
    """Return live runs. Orphans (subprocess finished but the streamlit
    handler never logged completion because the user navigated away) get
    migrated into runs.jsonl + run_state.json so the user can see them."""
    if not ACTIVE_RUNS_FILE.exists():
        return []
    try:
        active = json.loads(ACTIVE_RUNS_FILE.read_text())
    except Exception:
        return []
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
        except Exception:
            pass

    if len(alive) != len(active):
        ACTIVE_RUNS_FILE.write_text(json.dumps(alive, indent=2))
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
    active.append({
        "report_id": report_id,
        "report_name": report_name,
        "user": user,
        "log_path": str(log_path),
        "pid": pid,
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
    })
    ACTIVE_RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_RUNS_FILE.write_text(json.dumps(active, indent=2))


def _clear_active_run(report_id: str) -> None:
    if not ACTIVE_RUNS_FILE.exists():
        return
    try:
        active = json.loads(ACTIVE_RUNS_FILE.read_text())
    except Exception:
        return
    active = [a for a in active if a.get("report_id") != report_id]
    ACTIVE_RUNS_FILE.write_text(json.dumps(active, indent=2))


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
        "emoji": "🎯",
        "color": "#FF6B6B",
        "category": "🎯 Recruiting",
        "description": "Pulls funnel metrics from ApplicantStream, fills the mass-report Sheet across ~52 ICD office tabs.",
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
            "message_success": "✅ Done with **rhidalgo** (~43 offices filled). Now **log out of rhidalgo and log into rcaptain** in the same Chrome window, then click **Run Again** below to fill the remaining offices.",
            "message_failed": "❌ rhidalgo run failed. Check the log above. To retry, switch logins if needed and click Run Again.",
            "again_label": "🔁 Run Again with rcaptain",
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
        "name": "Daily Recruiting Focus",
        "emoji": "☀️",
        "color": "#4ECDC4",
        "category": "🎯 Recruiting",
        "description": "Per-ICD daily breakdown (Mon–Fri current week, last week, plus next-week scheduled). Auto-fills the 'Daily Focus Report' tab.",
        "sheet_url": SHEET_URL,
        "assignees": ["Maud"],
        "schedule": {
            "frequency": "daily",
            "weekdays": [1, 2, 3, 4, 5],  # Tue–Sat
            "time": "8:00 AM",
            "estimated_minutes": 6,
        },
        "checklist": [
            {"text": "Launch Chrome with the recruiting profile",
             "action": "launch_chrome"},
            {"text": "Log into AppStream as **rhidalgo** (broader account) in the new Chrome window"},
        ],
        "actions": [
            {
                "label": "Run Daily Focus",
                "icon": "▶",
                "primary": True,
                "help": "Fills today's daily focus report for all 17 ICDs (current + last week + next-week scheduled)",
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

def _stream_subprocess(cmd: list[str], output_box, report_id: str | None = None,
                        report_name: str | None = None) -> int:
    """Run a subprocess, stream stdout to UI, and (if report_id given) also
    record an active-run entry + duplicate output to a log file so the run
    can be tracked across page navigations."""
    log_file = None
    log_handle = None
    if report_id:
        ACTIVE_RUNS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = ACTIVE_RUNS_LOG_DIR / f"{report_id}.log"
        log_handle = log_file.open("w")

    proc = subprocess.Popen(cmd, cwd=str(WORKSPACE), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)

    if report_id:
        _record_active_run(report_id, report_name or report_id,
                           st.session_state.get("user", "unknown"),
                           log_file, proc.pid)

    lines: list[str] = []
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            ln = line.rstrip()
            lines.append(ln)
            if log_handle:
                log_handle.write(line)
                log_handle.flush()
            output_box.code("\n".join(lines[-30:]), language="log")
        proc.wait()
    finally:
        if log_handle:
            log_handle.close()
        if report_id:
            _clear_active_run(report_id)
    return proc.returncode


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


def _launch_chrome() -> tuple[bool, str]:
    """Launch Chrome with the remote-debugging-port for AS scraping.
    Returns (success, message)."""
    import os
    user_dir = os.path.expanduser("~/.config/recruiting-report/chrome-attach")
    try:
        subprocess.Popen([
            "open", "-na", "Google Chrome", "--args",
            "--remote-debugging-port=9222",
            f"--user-data-dir={user_dir}",
        ])
        return True, "Chrome is launching — check for a new window, then log into AppStream."
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


def _was_run_successfully_today(report_id: str, today: dt.date | None = None) -> bool:
    """True if a successful run of this report was logged today."""
    today = today or dt.date.today()
    for r in _read_runs(2):
        if r.get("report_id") == report_id and r.get("status") == "success" and r["_dt"].date() == today:
            return True
    return False


def _latest_run_summary(report_id: str) -> str | None:
    """Return compact text like 'Today · Megan · 1:06 AM', or None."""
    for r in _read_runs(days=14):
        if r.get("report_id") != report_id:
            continue
        when = r["_dt"]
        today = dt.date.today()
        time_str = when.strftime("%-I:%M %p")
        if when.date() == today:
            day = "Today"
        elif when.date() == today - dt.timedelta(days=1):
            day = "Yesterday"
        else:
            day = when.strftime("%b %-d")
        user = r.get("user", "someone")
        return f"Last ran {day.lower()} · {user} · {time_str}"
    return None


def _ran_within_24h(report_id: str) -> tuple[bool, str | None, str | None]:
    """Was this report successfully run in the last 24h? Returns (yes/no, user, time_str)."""
    cutoff = dt.datetime.now() - dt.timedelta(hours=24)
    for r in _read_runs(days=2):
        if r.get("report_id") == report_id and r.get("status") == "success" and r["_dt"] >= cutoff:
            return True, r.get("user", "someone"), r["_dt"].strftime("%-I:%M %p")
    return False, None, None


def _execute_action(report: dict, action: dict, picked, chrome_ok: bool) -> None:
    """Run one action: stream output, log the run, balloons on success."""
    if not chrome_ok:
        st.error("⚠️ Chrome isn't running — launch it from the sidebar first.")
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
    cmd = [VENV_PY, "-m", action["module"]] + args
    st.info(f"`{' '.join(shlex.quote(c) for c in cmd)}`")
    with st.status("Running…", expanded=True) as s:
        box = st.empty()
        rc = _stream_subprocess(cmd, box, report_id=report["id"], report_name=report["name"])
        if rc == 0:
            s.update(label="✅ Done!", state="complete")
            st.balloons()
        else:
            s.update(label=f"❌ Failed (exit {rc})", state="error")
        _log_run(
            report_id=report["id"],
            report_name=report["name"],
            user=st.session_state.get("user", "unknown"),
            status="success" if rc == 0 else "failed",
        )
        st.session_state[f"last_run_{report['id']}"] = {
            "status": "success" if rc == 0 else "failed",
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
        }
        # Also persist to disk so the callout survives navigations / refreshes
        _save_run_state_for(
            report["id"],
            "success" if rc == 0 else "failed",
            user=st.session_state.get("user"),
        )
    # Refresh so the "Pick up where you left off" banner appears immediately
    # (otherwise the user has to manually reload to see the post-run prompt).
    st.rerun()


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

    with st.container(border=True):
        st.markdown('<div class="report-card-marker"></div>', unsafe_allow_html=True)
        # Header row
        header_cols = st.columns([5, 2])
        last_run_text = _latest_run_summary(report["id"])
        with header_cols[0]:
            pills = ""
            if ran_today:
                pills += "<span class='pill pill-ok'>✅ DONE TODAY</span>"
            elif is_due:
                pills += "<span class='pill pill-due'>DUE TODAY</span>"
            if sched:
                pills += f"<span class='pill pill-info'>{sched.get('time', '')} • ~{sched.get('estimated_minutes', '?')} min</span>"
            if pills:
                st.markdown(pills, unsafe_allow_html=True)
            last_run_inline = (
                f"<span style='color:#C92020; font-size:1.4rem; font-weight:700; "
                f"margin-left:1rem; white-space:nowrap'>· {last_run_text}</span>"
                if last_run_text else ""
            )
            st.markdown(
                "<div style='display:flex; align-items:baseline; flex-wrap:nowrap; "
                "gap:0.5rem; margin:0.4rem 0 0.2rem'>"
                f"<span style='font-size:1.5rem; font-weight:700; line-height:1.2'>"
                f"{report['emoji']} {report['name']}</span>"
                f"{last_run_inline}"
                "</div>",
                unsafe_allow_html=True,
            )
            st.caption(report["description"])
        with header_cols[1]:
            st.link_button("📂 Open Sheet", report["sheet_url"], use_container_width=True)

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
                        # Display action result message (set by callback on previous run)
                        if msg_key in st.session_state:
                            ok, m = st.session_state[msg_key]
                            (st.success if ok else st.error)(m)
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
                                "🚀 Launch Chrome",
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
                    if st.button("✖ Cancel", key=f"confirm_no_{report['id']}",
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
            with st.container(border=True):
                if last_run["status"] == "success":
                    msg = post_run_cfg.get(
                        "message_success",
                        "✅ Run finished. If any ICD showed 'not accessible' in the log, switch AppStream logins and run again.",
                    )
                    st.success(msg)
                else:
                    msg = post_run_cfg.get(
                        "message_failed",
                        "❌ Run failed. Check the log above. You can retry with the same or other AppStream login below.",
                    )
                    st.error(msg)
                again_label = post_run_cfg.get("again_label", "🔁 Run Again")
                cols = st.columns([3, 2])
                with cols[0]:
                    st.caption("When you're ready, click Run Again below.")
                with cols[1]:
                    if st.button(again_label, key=f"again_{report['id']}", use_container_width=True, disabled=not chrome_ok):
                        _execute_action(report, primary, picked, chrome_ok)
                if st.button("✅ Mark as Completed", key=f"dismiss_{report['id']}"):
                    # Record on this user's "Completed Today" list
                    _mark_run_completed(
                        user=st.session_state.get("user", "unknown"),
                        report_id=report["id"],
                        report_name=report["name"],
                        run_ts=last_run.get("ts", ""),
                    )
                    st.session_state.pop(f"last_run_{report['id']}", None)
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
        ws.update([INTAKE_HEADERS], f"A1:{chr(ord('A') + len(INTAKE_HEADERS) - 1)}1")
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
            f"A1:{chr(ord('A') + len(INTAKE_HEADERS) - 1)}1",
        )
    return ws


@st.cache_data(ttl=30)
def _read_intake() -> list[dict]:
    """All intake records, newest first. Cached 30s to avoid per-rerun API hits."""
    try:
        ws = _intake_ws()
        rows = ws.get_all_records()
        return list(reversed(rows))
    except Exception:
        return []


def _add_intake(title: str, sheet_link: str, loom_link: str, description: str,
                submitted_by: str, preferred_creator: str = "",
                currently_runs: str = "", priority: str = "",
                submitter_email: str = "") -> str:
    new_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ws = _intake_ws()
    ws.append_row([
        new_id, title, sheet_link, loom_link, description,
        submitted_by, dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Unassigned", "", "",
        preferred_creator or "",
        currently_runs or "",
        priority or "",
        submitter_email or "",
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
        ws.update([BUG_HEADERS], f"A1:{chr(ord('A') + len(BUG_HEADERS) - 1)}1")
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
            f"A1:{chr(ord('A') + len(BUG_HEADERS) - 1)}1",
        )
    return ws


@st.cache_data(ttl=30)
def _read_bugs() -> list[dict]:
    """All bug records, newest first."""
    try:
        ws = _bugs_ws()
        rows = ws.get_all_records()
        return list(reversed(rows))
    except Exception:
        return []


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
        loom_link = st.text_input("Loom video walking through what's needed *", placeholder="https://www.loom.com/share/...")
        description = st.text_area(
            "Goal & details *",
            placeholder="What should this automation do? What problem does it solve? "
                        "What manual work is it replacing? Any tricky bits?",
            height=140,
        )
        cols = st.columns(2)
        with cols[0]:
            submitted_by = st.text_input("Your name *", value=st.session_state.get("user", "") or "")
        with cols[1]:
            preferred_creator = st.selectbox(
                "Preferred creator (optional)",
                ["No preference"] + [m["name"] for m in MEMBERS],
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
            help="How urgent is this? Don't worry, 5 is a real option.",
        )
        ok = st.form_submit_button("📨 Submit", type="primary", use_container_width=True)
        if ok:
            if not (title and sheet_link and loom_link and description and submitted_by and submitter_email):
                st.error("Please fill in every field marked *.")
            else:
                pc = "" if preferred_creator == "No preference" else preferred_creator
                try:
                    _add_intake(title, sheet_link, loom_link, description, submitted_by, pc, currently_runs, priority, submitter_email)
                    st.success("✅ Submitted! It will appear on the home page for someone to claim.")
                    st.balloons()
                except Exception as e:
                    st.error(f"Couldn't save to Sheet: {e}")


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


@st.dialog("🛠️ Wire Up Built Automation", width="large")
def _show_wire_up_dialog(entry: dict | None = None):
    """Form the builder fills out when their automation is built and ready.
    `entry` is the backlog entry to mark Done; pass None for direct upload of
    an already-built automation that wasn't tracked on the backlog."""
    if entry:
        st.markdown(f"**Backlog item:** {entry.get('Title', 'Untitled')}")
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
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Report name *", value=entry.get("Title", ""), key="wu_name")
        emoji = st.text_input("Emoji (single char)", value="⭐", key="wu_emoji",
                              help="An emoji to represent the report on the dashboard")
        sheet_url = st.text_input("Sheet URL", value=entry.get("Sheet Link", ""), key="wu_sheet_url")
    with col2:
        assignee = st.selectbox(
            "Who runs this report?",
            ["Not sure yet"] + [m["name"] for m in MEMBERS],
            index=0,
            key="wu_assignee",
            help="If unsure, leave 'Not sure yet' — it'll land in the Unassigned section of the library.",
        )
        est_min = st.number_input("Estimated minutes per run", min_value=1, max_value=120, value=5, key="wu_est_min")

    description = st.text_area(
        "Short description (one line)",
        value=entry.get("Description", "")[:140],
        key="wu_description",
        help="What this automation does — shown under the report name on the card",
    )

    st.markdown("**📅 Schedule**")
    sched_mode = st.radio(
        "When does this report run?",
        ["Specific days", "Monthly (on a day of the month)"],
        horizontal=True,
        key="wu_sched_mode_radio",
    )

    days_chosen: list[int] = []
    day_of_month: int = 1

    if sched_mode == "Specific days":
        st.caption("Tick every day this report should run.")
        dcols = st.columns(7)
        short_labels = ["M", "T", "W", "Th", "F", "Sa", "Su"]
        for i, col in enumerate(dcols):
            with col:
                st.markdown(f"<div style='text-align:center; font-weight:600; font-size:1.05rem'>{short_labels[i]}</div>", unsafe_allow_html=True)
                if st.checkbox(" ", key=f"wu_sched_day_{i}", label_visibility="collapsed", value=(i in [1, 2, 3, 4, 5])):
                    days_chosen.append(i)
    else:
        day_of_month = st.number_input(
            "Day of the month",
            min_value=1, max_value=31, value=1, step=1,
            key="wu_day_of_month",
            help="The report will run on this day each month. If the month is shorter, it's skipped (e.g. 31st only runs in long months).",
        )
        st.success(f"📅  This report will appear on the **{_ordinal(int(day_of_month))} of every month** in the assignee's schedule.")

    sched_cols = st.columns(2)
    with sched_cols[0]:
        time_str = st.text_input("Time of day", value="8:00 AM", key="wu_time_str")
    with sched_cols[1]:
        st.caption("(Time of day is informational — runs are triggered manually unless you set a cron.)")

    st.markdown("**🐍 Python script** (paste what Claude generated)")
    script_text = st.text_area(
        "Script content *",
        height=260,
        key="wu_script_text",
        placeholder='# Example:\nimport sys\n\ndef main():\n    print("Hello")\n    return 0\n\nif __name__ == "__main__":\n    sys.exit(main())',
        help="Must be valid Python. The dashboard will run it as `python -m automations.uploaded.<name>`.",
    )

    st.markdown("**📋 Pre-flight checklist (optional)**")
    st.caption(
        "One step per line. To add a link to a step, use the format: "
        "`Step text | URL | Button label`. The button label is optional; "
        "if omitted, defaults to 'Open'."
    )
    checklist_text = st.text_area(
        "Each line becomes a checkbox the user ticks before the Run button enables",
        key="wu_checklist_text",
        height=140,
        placeholder=(
            "Launch Chrome\n"
            "Log into AppStream as rhidalgo\n"
            "Open the source data | https://docs.google.com/spreadsheets/d/abc | 📂 Open Source\n"
            "Watch the runbook | https://loom.com/xyz | ▶️ Watch Loom"
        ),
        help=(
            "Examples:\n"
            "• 'Launch Chrome' — checkbox only\n"
            "• 'Open the data | https://...' — checkbox + link button (default label 'Open')\n"
            "• 'Watch loom | https://... | ▶️ Loom' — checkbox + custom-labeled link button"
        ),
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
    submitted = st.button("🚀 Upload & Send for Review", type="primary", use_container_width=True, key="wu_submit")
    if submitted:
        if not (name and script_text):
            st.error("Please fill every field marked *.")
            return
        # "Not sure yet" → no assignee → report lands in Unassigned section.
        assignees_list: list[str] = [] if assignee == "Not sure yet" else [assignee]

        # Build schedule dict
        if sched_mode.startswith("Monthly"):
            schedule = {
                "frequency": "monthly",
                "day_of_month": int(day_of_month),
                "time": time_str,
                "estimated_minutes": int(est_min),
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
                "estimated_minutes": int(est_min),
            }

        # Parse checklist: each line is "text" OR "text | url" OR "text | url | label"
        checklist = []
        for line in checklist_text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            step = {"text": parts[0]}
            if len(parts) >= 2 and parts[1]:
                step["link"] = parts[1]
                step["link_label"] = parts[2] if len(parts) >= 3 and parts[2] else "Open"
            checklist.append(step)

        metadata = {
            "id": name,
            "name": name,
            "emoji": emoji or "⭐",
            "description": description,
            "sheet_url": sheet_url,
            "assignees": assignees_list,
            "schedule": schedule,
            "checklist": checklist,
            "args": [],
        }

        ok, msg = _save_uploaded_report(metadata, script_text)
        if not ok:
            st.error(msg)
            return

        if entry.get("ID"):
            try:
                _mark_intake_done(str(entry["ID"]), cc_emails=review_cc)
            except Exception:
                pass

        target_text = (
            "in the **🔍 Unassigned** section of the Report Library"
            if assignee == "Not sure yet"
            else f"on **{assignee}**'s dashboard"
        )
        st.success(
            f"✅ Uploaded! It will appear {target_text}. "
            "The requester has been emailed to review."
        )
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


def _render_intake_card(entry: dict, allow_claim: bool = True, allow_done: bool = False) -> None:
    """Render one backlog entry."""
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
                st.caption(
                    f"Submitted by **{entry.get('Submitted By', '?')}** on {entry.get('Submitted At', '?')} "
                    f"• Claimed on {entry.get('Assigned At', '')}"
                )
            else:
                st.caption(
                    f"Submitted by **{entry.get('Submitted By', '?')}** on {entry.get('Submitted At', '?')}"
                )
            if entry.get("Description"):
                with st.expander("Project Details"):
                    st.markdown(entry["Description"])
                    link_cols = st.columns(2)
                    with link_cols[0]:
                        if entry.get("Sheet Link"):
                            st.link_button("📂 Open Sheet", entry["Sheet Link"], use_container_width=True)
                    with link_cols[1]:
                        if entry.get("Loom Link"):
                            st.link_button("▶️ Watch Loom", entry["Loom Link"], use_container_width=True)
            elif entry.get("Sheet Link") or entry.get("Loom Link"):
                link_cols = st.columns(2)
                with link_cols[0]:
                    if entry.get("Sheet Link"):
                        st.link_button("📂 Open Sheet", entry["Sheet Link"], use_container_width=True)
                with link_cols[1]:
                    if entry.get("Loom Link"):
                        st.link_button("▶️ Watch Loom", entry["Loom Link"], use_container_width=True)

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
    """Compact read-only summary of a Fixed bug or change request."""
    bug_id = str(entry.get("ID", ""))
    bug_type = entry.get("Type", "")
    type_emoji = "🐛" if "Bug" in bug_type else "✏️"
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
    type_emoji = "🐛" if "Bug" in bug_type else "✏️"

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

    bugs = [b for b in _read_bugs() if type_keyword in (b.get("Type") or "")]

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
    but no successful run was logged. Returns list of {report, missed_date}."""
    today = today or dt.date.today()
    runs = _read_runs(days + 1)
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
    page_icon=str(_FAVICON_PATH) if _FAVICON_PATH.exists() else "🐺",
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
        if _url_view in {"home", "user", "overview", "library", "backlog", "bugs", "changes"}
        else "home"
    )
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


_VALID_VIEWS = {"home", "user", "overview", "library", "backlog", "bugs", "changes"}


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
    # Always return to the top-level library list (not a previously-opened detail)
    st.session_state.pop("library_report_id", None)
    _set_view("library")


def _go_backlog():
    _set_view("backlog")


def _go_bugs():
    _set_view("bugs")


def _go_changes():
    _set_view("changes")


def _detect_hub_user() -> str:
    """Best guess at who's using this hub, based on the OS user (or HUB_USER env).

    Each member can override by exporting HUB_USER=<name> before running
    streamlit. Falls back to a name-similarity match against MEMBERS, then to
    the first MEMBERS entry.
    """
    import os
    import getpass
    env = os.environ.get("HUB_USER", "").strip()
    if env:
        return env
    try:
        os_user = getpass.getuser().lower()
    except Exception:
        os_user = ""
    for m in MEMBERS:
        if m["name"].lower() == os_user or m["name"].lower().startswith(os_user):
            return m["name"]
    return MEMBERS[0]["name"] if MEMBERS else "Megan"


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
                    _clear_active_run(run["report_id"])
                    st.rerun()


# --------------------------------------------------------------------------
# Sidebar: system status + recent logs (always visible)
# --------------------------------------------------------------------------

with st.sidebar:
    if st.session_state.view != "home":
        if st.button("🏠 Back to Home", use_container_width=True):
            _go_home()
            st.rerun()
    if st.button("📚 Report Library", use_container_width=True):
        _go_library()
        st.rerun()

    # Counts so the sidebar shows what's waiting without clicking through.
    _backlog_count = sum(
        1 for r in _read_intake()
        if (r.get("Status") or "Unassigned") in ("Unassigned", "In Progress", "Needs Updates")
    )
    _bugs_count = sum(
        1 for b in _read_bugs()
        if (b.get("Status") or "Open") in ("Open", "In Progress", "Needs Info")
        and "Bug" in (b.get("Type") or "")
    )
    _changes_count = sum(
        1 for b in _read_bugs()
        if (b.get("Status") or "Open") in ("Open", "In Progress", "Needs Info")
        and "Change" in (b.get("Type") or "")
    )
    if st.button(f"📨 New Automation Request ({_backlog_count})", use_container_width=True, key="nav_backlog"):
        _go_backlog()
        st.rerun()
    if st.button("📥 Upload Built Automation", use_container_width=True, key="nav_upload"):
        st.session_state.show_wireup_direct = True

    # Chrome status check still happens here (other code reads `chrome_ok`),
    # but the visible pill is rendered top-right of the page instead of in
    # the sidebar. The "Chrome not running" sidebar warning + Launch button
    # stays as the recovery path when it's actually broken.
    chrome_ok = _check_chrome_running()
    _pill_class = "ok" if chrome_ok else "warn"
    _pill_label = "🟢 Chrome connected" if chrome_ok else "🔴 Chrome offline"
    st.markdown(
        f'<div class="system-status-pill {_pill_class}">{_pill_label}</div>',
        unsafe_allow_html=True,
    )
    if not chrome_ok:
        st.markdown("---")
        st.warning("Chrome not running")
        if st.button("🚀 Launch Chrome", use_container_width=True, key="sidebar_launch_chrome"):
            ok, msg = _launch_chrome()
            (st.success if ok else st.error)(msg)
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

    # Bottom-of-sidebar: suggest button (small, red)
    st.markdown("---")
    st.markdown(
        """
        <style>
        div[data-testid="stSidebar"] button[kind="secondary"]:has(div:contains("Suggest")) {
            background: #C92020 !important;
            color: white !important;
            border: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button("⚠️ Suggest a Change / Report A Bug", use_container_width=True, key="open_suggest_btn"):
        st.session_state.show_suggest = True
    if st.button(f"🐛 Bugs Being Fixed ({_bugs_count})", use_container_width=True, key="nav_bugs"):
        _go_bugs()
        st.rerun()
    if st.button(f"✏️ Report Change Requests ({_changes_count})", use_container_width=True, key="nav_changes"):
        _go_changes()
        st.rerun()

    # Tiny sign-out link at the very bottom — ends the 1-hour session so the
    # next page load prompts for the Pack Access password again.
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
    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
    </div>
    """, unsafe_allow_html=True)

    # Overview card (logo now lives next to the page header above)
    with st.container(border=True):
        cols = st.columns([5, 2])
        with cols[0]:
            st.markdown(
                "<div style='font-size: 1.8rem; font-weight: 800; line-height: 1.1; margin-top: 0.5rem'>Alphalete Marketing</div>"
                "<div style='font-size: 1.3rem; font-weight: 600; opacity: 0.7; margin-bottom: 0.4rem'>7-Day Overview</div>"
                "<div style='opacity: 0.85'>Every report run by anyone, last 7 days.</div>",
                unsafe_allow_html=True,
            )
        with cols[1]:
            st.markdown("<div style='padding-top: 1.2rem'></div>", unsafe_allow_html=True)
            if st.button("📊 Open Overview", use_container_width=True, type="primary", key="home_overview_btn"):
                _go_overview()
                st.rerun()

    st.markdown("### 🐺 The Pack")
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
# BUGS / CHANGE REQUESTS VIEWS — both views are identical in shape, just
# filtered by row Type. Bugs = 'Bug / something broke'. Change requests =
# 'Change to an existing report'. Same Sheet tab, same Apps Script — just
# two filtered surfaces so admins can triage them with separate mindsets.
# The shared renderer _render_bug_typed_view is defined further up with
# the other card helpers; here we just dispatch by view.
# --------------------------------------------------------------------------

elif st.session_state.view == "bugs":
    _render_bug_typed_view(
        type_keyword="Bug",
        page_title="🐛 Bug Reports",
        page_caption="Things that are broken. Submitted via the sidebar. Megan triages and replies to the submitter by email.",
        empty_message="No bug reports right now.",
        completed_label="🐛 Bug Fixes Completed",
        completed_empty_label="No bugs fixed yet.",
    )


elif st.session_state.view == "changes":
    _render_bug_typed_view(
        type_keyword="Change",
        page_title="✏️ Report Change Requests",
        page_caption="Tweaks and edits to existing reports. Submitted via the sidebar. Megan triages and replies to the submitter by email.",
        empty_message="No change requests right now.",
        completed_label="✏️ Completed Change Requests",
        completed_empty_label="No change requests completed yet.",
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

    # Recent runs activity feed
    st.markdown("### 🗓️ Recent Activity")
    runs = _read_runs(7)
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

    if selected_id:
        report = next((r for r in AUTOMATED_REPORTS if r["id"] == selected_id), None)
        if not report:
            st.error("That report isn't in the library anymore.")
            if st.button("← Back to Library"):
                st.session_state.pop("library_report_id", None)
                st.rerun()
        else:
            if st.button("← Back to Library", key="lib_detail_back"):
                st.session_state.pop("library_report_id", None)
                st.rerun()

            st.markdown(
                f"<div style='font-size:2.2rem; font-weight:800; margin:0.4rem 0 0.4rem'>"
                f"{report.get('emoji', '📄')} {report['name']}</div>",
                unsafe_allow_html=True,
            )
            if report.get("description"):
                st.caption(report["description"])

            # Auto-detect the runner from the OS user. The run gets attributed
            # to this person automatically — no dropdown needed.
            detected_user = _detect_hub_user()
            st.session_state.user = detected_user
            member = next((m for m in MEMBERS if m["name"] == detected_user), None)
            member_emoji = member["emoji"] if member else "👤"
            st.caption(f"{member_emoji} Running as **{detected_user}**")

            st.markdown("---")
            _render_report_card(report, today, chrome_ok)
    else:
        st.markdown(
            "<div style='font-size:2.4rem; font-weight:800; letter-spacing:-0.5px; "
            "margin:0.4rem 0 0.4rem'>📚 Report Library</div>",
            unsafe_allow_html=True,
        )
        st.caption("Every automation. Click a report to open its checklist + run it.")

        # Group reports into sections. Anything with empty/missing `assignees`
        # lands in a top "Unassigned" section so it's easy to find and claim.
        # Otherwise, group by `category` field (defaults to "All Reports").
        UNASSIGNED_LABEL = "🔍 Unassigned reports"
        sections: dict[str, list] = {}
        for r in AUTOMATED_REPORTS:
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

        for section_name, reports_in_section in ordered_sections:
            st.markdown(f"### {section_name}")
            for report in reports_in_section:
                with st.container(border=True):
                    cols = st.columns([5, 2])
                    with cols[0]:
                        st.markdown(
                            f"**{report.get('emoji', '📄')} {report['name']}**"
                        )
                        if report.get("description"):
                            st.caption(report["description"])
                        meta_lines = []
                        assignees = report.get("assignees", [])
                        if assignees:
                            meta_lines.append(f"**Assigned to:** {', '.join(assignees)}")
                        else:
                            meta_lines.append("**Assigned to:** _Not yet assigned_")
                        last_run = _latest_run_summary(report["id"])
                        if last_run:
                            meta_lines.append(
                                f"<span style='color:#C92020; font-weight:600'>{last_run}</span>"
                            )
                        else:
                            meta_lines.append("<span style='color:#777'>Not yet run</span>")
                        st.markdown(
                            "  •  ".join(meta_lines),
                            unsafe_allow_html=True,
                        )
                        # Inline assign picker for unassigned reports.
                        if not assignees:
                            assign_cols = st.columns([3, 2])
                            with assign_cols[0]:
                                _pick = st.selectbox(
                                    "Assign to…",
                                    ["— assign to —"] + [m["name"] for m in MEMBERS],
                                    key=f"lib_assign_pick_{report['id']}",
                                    label_visibility="collapsed",
                                )
                            with assign_cols[1]:
                                if _pick and _pick != "— assign to —":
                                    if st.button(
                                        "🤝 Assign",
                                        key=f"lib_assign_btn_{report['id']}",
                                        use_container_width=True,
                                    ):
                                        if _set_library_assignment(str(report["id"]), _pick):
                                            st.success(f"Assigned to {_pick}.")
                                            st.rerun()
                                        else:
                                            st.error("Couldn't save — try again.")
                    with cols[1]:
                        if st.button(
                            "Open →",
                            key=f"lib_open_{report['id']}",
                            type="primary",
                            use_container_width=True,
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
                    f"<div style='font-size:0.78em; color:#777'>{_day.strftime('%b %-d')}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                _due = [r for r in my_reports if _was_due_on(r, _day)]
                if _due:
                    for _r in _due:
                        st.markdown(
                            "<div style='background:#FAFAFA; border-left:3px solid #C9A85C; "
                            "padding:4px 8px; border-radius:4px; margin-bottom:4px; "
                            "font-size:0.82em; line-height:1.25; word-break:break-word'>"
                            f"{_r.get('emoji', '📄')} {_r['name']}"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown(
                        "<div style='text-align:center; color:#bbb; "
                        "font-size:0.8em; padding:4px 0'>—</div>",
                        unsafe_allow_html=True,
                    )
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
                        marked_str = marked_dt.strftime("%-I:%M %p")
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
                for report in my_reports:
                    _render_report_card(report, today, chrome_ok)
            else:
                st.info(f"No reports assigned to {user_name} yet.")


# --------------------------------------------------------------------------
# Suggest dialog (triggered from sidebar red button)
# --------------------------------------------------------------------------

@st.dialog("⚠️ Report a Bug or Suggest a Change", width="large")
def _show_suggest_dialog():
    st.caption(
        "Found a bug or want a tweak to something that already exists? "
        "Drop the details here — Megan reviews and follows up by email.\n\n"
        "**Need a brand-new report automated?** Use **\"Submit a New Automation Request\"** on the home page instead."
    )
    with st.form("suggestion_form", clear_on_submit=True):
        cols = st.columns(2)
        with cols[0]:
            sugg_type = st.selectbox(
                "What kind?",
                ["Bug / something broke", "Change to an existing report"],
            )
            report_name = st.text_input("Report name", placeholder="e.g. 'OPT Focus Report'")
            requester = st.text_input("Your name", value=st.session_state.get("user", "") or "")
            requester_email = st.text_input(
                "Your email",
                placeholder="you@example.com",
                help="Megan will reply here when the bug is fixed or if she needs more info.",
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
            "Details — what should it do? what's broken?",
            height=140,
            placeholder="Describe the goal, the source data, what's wrong, etc.",
        )
        submitted = st.form_submit_button("📨 Submit", type="primary", use_container_width=True)

        if submitted:
            missing = [
                label for label, val in [
                    ("Report name", report_name),
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
                        title=report_name,
                        bug_type=sugg_type,
                        sheet_link=link,
                        loom_link=loom,
                        details=details,
                        submitted_by=requester,
                        submitter_email=requester_email,
                        priority=priority,
                    )
                    st.success("✅ Submitted! Megan will reply to your email when it's fixed.")
                    st.balloons()
                except Exception as e:
                    st.error(f"Couldn't save the bug report: {e}")


if st.session_state.get("show_suggest"):
    st.session_state.show_suggest = False
    _show_suggest_dialog()

if st.session_state.get("show_wireup_direct"):
    st.session_state.show_wireup_direct = False
    _show_wire_up_dialog(None)


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------

st.divider()
st.caption(
    "🐺 **Live more. Dream more. Do more.** — Alphalete Marketing"
)
