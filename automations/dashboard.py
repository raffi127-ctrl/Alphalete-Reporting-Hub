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
            _save_run_state_for(report_id, status if status != "unknown" else "success")
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


def _save_run_state_for(report_id: str, status: str) -> None:
    state = _load_all_run_state()
    state[report_id] = {"status": status, "ts": dt.datetime.now().isoformat(timespec="seconds")}
    RUN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATE_FILE.write_text(json.dumps(state, indent=2))


def _clear_run_state_for(report_id: str) -> None:
    state = _load_all_run_state()
    state.pop(report_id, None)
    RUN_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATE_FILE.write_text(json.dumps(state, indent=2))


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
    {"name": "Eve",     "emoji": "🌷",        "color": "#4ECDC4"},
    {"name": "JD",      "emoji": "⚡",        "color": "#9B59B6"},
    {"name": "Maud",    "emoji": "🌟",        "color": "#FF6B6B"},
    {"name": "Megan",   "emoji": "👩‍💼",     "color": "#667eea"},
    {"name": "Raf",     "emoji": "🚀",        "color": "#F4A261"},
    {"name": "Twaddle", "emoji": "🦊",        "color": "#2A9D8F"},
]

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

# Future: read pending automation requests from this Sheet. Update the ID
# once Megan shares the URL.
REPORT_INTAKE_SHEET_ID = ""
REPORT_INTAKE_TAB = "Sheet1"


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
        _save_run_state_for(report["id"], "success" if rc == 0 else "failed")
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
            st.markdown(f"### {report['emoji']} {report['name']}")
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

        if st.button(
            f"{primary.get('icon', '▶')} {primary['label']}",
            key=f"prim_{report['id']}",
            type="primary",
            use_container_width=True,
            disabled=run_disabled,
            help=run_help,
        ):
            _execute_action(report, primary, picked, chrome_ok)

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
                if st.button("✖ Dismiss / Mark Done", key=f"dismiss_{report['id']}"):
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


INTAKE_TAB = "Automation Backlog"
INTAKE_HEADERS = [
    "ID", "Title", "Sheet Link", "Loom Link", "Description",
    "Submitted By", "Submitted At", "Status", "Assigned To", "Assigned At",
    "Preferred Creator",
]


def _intake_ws():
    """Return the intake worksheet, creating it if missing."""
    import gspread as _gs
    sh = _fill.open_sheet()
    try:
        return sh.worksheet(INTAKE_TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=INTAKE_TAB, rows=300, cols=len(INTAKE_HEADERS))
        ws.update([INTAKE_HEADERS], f"A1:{chr(ord('A') + len(INTAKE_HEADERS) - 1)}1")
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
                submitted_by: str, preferred_creator: str = "") -> str:
    new_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ws = _intake_ws()
    ws.append_row([
        new_id, title, sheet_link, loom_link, description,
        submitted_by, dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Unassigned", "", "",
        preferred_creator or "",
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
    ws.update_cell(row, 8, "In Progress")
    ws.update_cell(row, 9, user)
    ws.update_cell(row, 10, dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    _read_intake.clear()
    return True


def _mark_intake_done(entry_id: str) -> bool:
    ws = _intake_ws()
    try:
        cell = ws.find(str(entry_id))
    except Exception:
        return False
    if not cell:
        return False
    ws.update_cell(cell.row, 8, "Done")
    _read_intake.clear()
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
                ["— No preference —"] + [m["name"] for m in MEMBERS],
                help="If you have a specific person in mind to build this, pick them. Anyone can still claim it.",
            )
        ok = st.form_submit_button("📨 Submit", type="primary", use_container_width=True)
        if ok:
            if not (title and sheet_link and loom_link and description and submitted_by):
                st.error("Please fill in every field marked *.")
            else:
                pc = "" if preferred_creator == "— No preference —" else preferred_creator
                try:
                    _add_intake(title, sheet_link, loom_link, description, submitted_by, pc)
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
            "Who runs this report? *",
            [m["name"] for m in MEMBERS],
            index=0,
            key="wu_assignee",
            help="The person whose dashboard this will appear on",
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

    submitted = st.button("🚀 Wire It Up & Mark Done", type="primary", use_container_width=True, key="wu_submit")
    if submitted:
        if not (name and assignee and script_text):
            st.error("Please fill every field marked *.")
            return

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
            "assignees": [assignee],
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
                _mark_intake_done(str(entry["ID"]))
            except Exception:
                pass

        st.success(f"✅ Wired up! It will appear on **{assignee}**'s dashboard.")
        st.balloons()
        st.markdown(
            "**Heads up:** The new automation is saved on this Mac. "
            "To make it available to the whole team, ask Megan to commit + push to GitHub."
        )


def _render_intake_card(entry: dict, allow_claim: bool = True, allow_done: bool = False) -> None:
    """Render one backlog entry."""
    with st.container(border=True):
        cols = st.columns([5, 2])
        with cols[0]:
            st.markdown(f"### {entry.get('Title', 'Untitled')}")
            preferred = entry.get("Preferred Creator", "")
            if preferred:
                st.markdown(f"<span class='pill pill-info'>👋 Requested for: {preferred}</span>",
                            unsafe_allow_html=True)
            st.caption(
                f"Submitted by **{entry.get('Submitted By', '?')}** on {entry.get('Submitted At', '?')}"
                + (f" • Claimed by **{entry.get('Assigned To')}** on {entry.get('Assigned At', '')}" if entry.get('Assigned To') else "")
            )
            if entry.get("Description"):
                st.markdown(entry["Description"])
            link_cols = st.columns(2)
            with link_cols[0]:
                if entry.get("Sheet Link"):
                    st.link_button("📂 Open Sheet", entry["Sheet Link"], use_container_width=True)
            with link_cols[1]:
                if entry.get("Loom Link"):
                    st.link_button("▶️ Watch Loom", entry["Loom Link"], use_container_width=True)
        with cols[1]:
            if allow_claim:
                claim_to = st.selectbox(
                    "Claim for…",
                    ["— pick name —"] + [m["name"] for m in MEMBERS],
                    key=f"claim_pick_{entry['ID']}",
                    label_visibility="collapsed",
                )
                if claim_to and claim_to != "— pick name —":
                    if st.button("🤝 Claim", key=f"claim_btn_{entry['ID']}", use_container_width=True, type="primary"):
                        if _assign_intake(str(entry["ID"]), claim_to):
                            st.success(f"Claimed by {claim_to}")
                            st.rerun()
                        else:
                            st.error("Couldn't claim — please try again.")
            if allow_done:
                if st.button("🛠️ Wire It Up", key=f"wireup_{entry['ID']}", use_container_width=True, type="primary"):
                    _show_wire_up_dialog(entry)
                if st.button("✅ Just mark done", key=f"justdone_{entry['ID']}", use_container_width=True):
                    if _mark_intake_done(str(entry["ID"])):
                        st.success("Marked done (no automation wired)")
                        st.rerun()


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

st.set_page_config(
    page_title="Megan's Reports",
    page_icon="📊",
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
        padding: 0.25rem 0.75rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-right: 0.4rem;
    }
    .pill-due { background: #FFE9E9; color: #C92020; }
    .pill-ok  { background: #E6F7EC; color: #1F7A3D; }
    .pill-info{ background: #E8F0FE; color: #1A4FB0; }

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
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Session state init + view router
# --------------------------------------------------------------------------

if "view" not in st.session_state:
    st.session_state.view = "home"   # "home" | "user" | "overview"
if "user" not in st.session_state:
    st.session_state.user = None     # name from MEMBERS once selected

LOGO_PATH = WORKSPACE / "resources" / "alphalete-shield.png"
LOGO_EXISTS = LOGO_PATH.exists()

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


def _go_home():
    st.session_state.view = "home"
    st.session_state.user = None


def _go_user(name: str):
    st.session_state.user = name
    st.session_state.view = "user"


def _go_overview():
    st.session_state.view = "overview"


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
                if st.button("⏹ Stop run", key=f"stop_{run['report_id']}", use_container_width=True,
                             help="Force-stop this background run"):
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
        st.markdown("---")
    st.markdown("### 🛠️ System Status")
    chrome_ok = _check_chrome_running()
    if chrome_ok:
        st.success("Chrome is connected ✨")
    else:
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
    if st.button("⚠️ Suggest a Change / Bug", use_container_width=True, key="open_suggest_btn"):
        st.session_state.show_suggest = True


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

    # Member cards in a 3-column grid (2 rows x 3 cols for 6 members)
    rows = [MEMBERS[i:i + 3] for i in range(0, len(MEMBERS), 3)]
    for row in rows:
        cols = st.columns(len(row))
        for col, member in zip(cols, row):
            with col:
                # Count today's reports for this member
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
                    if due_count > 0:
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
                    if st.button(
                        f"Open {member['name']}'s reports",
                        key=f"pick_{member['name']}",
                        use_container_width=True,
                    ):
                        _go_user(member["name"])
                        st.rerun()

    # --------------------------------------------------------------------
    # Automation Backlog — unassigned + in-progress requests
    # --------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 🚧 Automation Backlog")
    st.caption("New report ideas and bugs from the team. Anyone can claim a request to take it on.")
    st.markdown(
        """
        <style>
        /* Big square backlog action buttons */
        div[data-testid="column"]:has(button[key="open_intake_btn"]) button,
        div[data-testid="column"]:has(button[key="open_wireup_direct_btn"]) button {
            min-height: 140px !important;
            font-size: 1.7rem !important;
            font-weight: 800 !important;
            border-radius: 18px !important;
            letter-spacing: 0.01em !important;
            padding: 0.6rem 1rem !important;
        }
        /* Secondary backlog button — gold border on hover for cohesion */
        div[data-testid="column"]:has(button[key="open_wireup_direct_btn"]) button {
            border: 2px solid #C9A85C !important;
            color: #5C4220 !important;
            background: #FFF8E7 !important;
        }
        div[data-testid="column"]:has(button[key="open_wireup_direct_btn"]) button:hover {
            background: #FFF2D0 !important;
            border-color: #8B6914 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    bl_cols = st.columns(2)
    with bl_cols[0]:
        if st.button("➕  Submit a New Request", use_container_width=True, type="primary", key="open_intake_btn"):
            _show_intake_dialog()
    with bl_cols[1]:
        if st.button("📥  Upload a Built Automation", use_container_width=True, key="open_wireup_direct_btn",
                     help="Upload an automation that's already built (skips the backlog claim flow)"):
            _show_wire_up_dialog(None)

    intake = _read_intake()
    unassigned = [r for r in intake if (r.get("Status") or "Unassigned") == "Unassigned"]
    in_progress = [r for r in intake if r.get("Status") == "In Progress"]

    if not intake:
        st.info("No requests in the backlog yet. Click **Submit Request** above to add the first one.")
    else:
        if unassigned:
            st.markdown(f"#### 🔓 Unassigned ({len(unassigned)})")
            for entry in unassigned:
                _render_intake_card(entry, allow_claim=True, allow_done=False)
        if in_progress:
            st.markdown(f"#### 🛠️ In Progress ({len(in_progress)})")
            for entry in in_progress:
                _render_intake_card(entry, allow_claim=False, allow_done=True)


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
            with st.expander(f"📅 {label}  —  {len(by_date[day])} run{'s' if len(by_date[day]) != 1 else ''}", expanded=(day == today)):
                for r in by_date[day]:
                    icon = "✅" if r.get("status") == "success" else "❌"
                    time_str = r["_dt"].strftime("%I:%M %p")
                    st.markdown(
                        f"{icon}  **{time_str}**  •  {r.get('report_name', r.get('report_id', '?'))}  •  ran by **{r.get('user', '?')}**"
                    )


# --------------------------------------------------------------------------
# USER VIEW — that user's today's schedule + their reports
# --------------------------------------------------------------------------

else:  # st.session_state.view == "user"
    user_name = st.session_state.user or "friend"
    member = next((m for m in MEMBERS if m["name"] == user_name), None)
    member_emoji = member["emoji"] if member else "📊"

    # Only show "currently running" for runs THIS user kicked off
    _render_currently_running_banner(filter_user=user_name)
    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
        <h1>{member_emoji} {greeting}, {user_name}!</h1>
        <p>Here's what's on your plate.</p>
    </div>
    """, unsafe_allow_html=True)

    my_reports = [r for r in AUTOMATED_REPORTS if user_name in r.get("assignees", [])]

    # ----- "Pick up where you left off" banner -----
    # Any of this user's reports with persisted run state (within last 24h)
    persisted = _load_all_run_state()
    in_progress = [r for r in my_reports if r["id"] in persisted]
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

            with st.container(border=True):
                cols = st.columns([5, 2, 2])
                with cols[0]:
                    st.markdown(f"**{report['emoji']} {report['name']}** — last run **{saved_str}** today")
                    if post_run_cfg.get("message_success") and saved.get("status") == "success":
                        st.caption(post_run_cfg["message_success"])
                    else:
                        st.caption("You started this earlier today but haven't marked it done yet.")
                with cols[1]:
                    if st.button(again_label, key=f"continue_{report['id']}", use_container_width=True, type="primary", disabled=not chrome_ok):
                        # Find the primary action and re-execute
                        primary = next((a for a in report["actions"] if a.get("primary")), report["actions"][0])
                        # Build picked from any saved widget state (date/text)
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
                    if st.button("✅ Mark fully done", key=f"banner_done_{report['id']}", use_container_width=True):
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

@st.dialog("💡 Suggest an Automation or Report a Bug", width="large")
def _show_suggest_dialog():
    st.caption(
        "See a report we should automate, or hit a bug? "
        "Drop the details here — Megan reviews and works with Claude to build/fix."
    )
    with st.form("suggestion_form", clear_on_submit=True):
        cols = st.columns(2)
        with cols[0]:
            sugg_type = st.selectbox(
                "What kind?",
                ["Bug / something broke", "Change to an existing report", "New automation request"],
            )
            report_name = st.text_input("Report name", placeholder="e.g. 'OPT Focus Report'")
            requester = st.text_input("Your name", value=st.session_state.get("user", "") or "")
        with cols[1]:
            link = st.text_input("Sheet link (optional)", placeholder="https://…")
            loom = st.text_input("Loom (optional)", placeholder="https://loom.com/…")
            priority = st.select_slider("Priority", options=["Low", "Medium", "High", "Blocking"], value="Medium")
        details = st.text_area(
            "Details — what should it do? what's broken?",
            height=140,
            placeholder="Describe the goal, the source data, what's wrong, etc.",
        )
        submitted = st.form_submit_button("📨 Submit", type="primary", use_container_width=True)

        if submitted:
            if not (report_name and requester and details):
                st.error("Please fill in Report Name, Your Name, and Details.")
            elif not REPORT_INTAKE_SHEET_ID:
                st.warning("Intake Sheet not wired up yet — sending to log only.")
                st.code(f"""Type: {sugg_type}
Report: {report_name}
Requester: {requester}
Priority: {priority}
Link: {link}
Loom: {loom}
Details: {details}""")
            else:
                try:
                    from automations.recruiting_report.fill import _client
                    sh = _client().open_by_key(REPORT_INTAKE_SHEET_ID)
                    ws = sh.worksheet(REPORT_INTAKE_TAB)
                    ws.append_row([
                        report_name, link, loom, "", "",
                        sugg_type, requester, priority, details,
                        dt.datetime.now().isoformat(timespec="minutes"),
                    ])
                    st.success("✅ Submitted!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Couldn't write to intake Sheet: {e}")


if st.session_state.get("show_suggest"):
    st.session_state.show_suggest = False
    _show_suggest_dialog()


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------

st.divider()
st.caption(
    "🐺 **Live more. Dream more. Do more.** — Alphalete Marketing"
)
