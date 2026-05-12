"""Operator dashboard for running report automations.

For Eve / Maud (operators): click a button, the report runs.
For Megan: add new automated reports to AUTOMATED_REPORTS once Claude builds them.

Run with:
    .venv/bin/streamlit run automations/dashboard.py
"""
from __future__ import annotations

import datetime as dt
import json
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
                "label": "Backfill Last 10 Weeks",
                "icon": "🔁",
                "help": "For each office, fills any empty cells in the last 10 weeks (won't overwrite existing data).",
                "module": "automations.recruiting_report.backfill_blanks",
                "args_fn": lambda: ["--weeks", "10"],
            },
            {
                "label": "Run a Specific Past Week",
                "icon": "📆",
                "needs_date": True,
                "help": "Pick a WE Sunday to fill",
                "module": "automations.recruiting_report.run",
                "args_fn": lambda d: ["--week", (d - dt.timedelta(days=7)).isoformat()],
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

# Future: read pending automation requests from this Sheet. Update the ID
# once Megan shares the URL.
REPORT_INTAKE_SHEET_ID = ""
REPORT_INTAKE_TAB = "Sheet1"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _stream_subprocess(cmd: list[str], output_box) -> int:
    proc = subprocess.Popen(cmd, cwd=str(WORKSPACE), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    lines: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        lines.append(line.rstrip())
        output_box.code("\n".join(lines[-30:]), language="log")
    proc.wait()
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
    sched = report.get("schedule")
    if not sched:
        return False
    if sched.get("frequency") == "daily":
        return True
    return today.weekday() in sched.get("weekdays", [])


def _next_due(report: dict, today: dt.date):
    sched = report.get("schedule")
    if not sched:
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
    if action.get("needs_text") and not picked:
        st.error(f"⚠️ Please enter the {action.get('text_label', 'input')} first.")
        return
    if action.get("needs_date") or action.get("needs_text"):
        args = action["args_fn"](picked)
    else:
        args = action["args_fn"]()
    cmd = [VENV_PY, "-m", action["module"]] + args
    st.info(f"`{' '.join(shlex.quote(c) for c in cmd)}`")
    with st.status("Running…", expanded=True) as s:
        box = st.empty()
        rc = _stream_subprocess(cmd, box)
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

        # Post-run callout (appears after a run completes)
        last_run = st.session_state.get(f"last_run_{report['id']}")
        if last_run:
            with st.container(border=True):
                if last_run["status"] == "success":
                    st.success("✅ Run finished. If any ICD showed 'not accessible' in the log, switch AppStream logins and run again.")
                else:
                    st.error("❌ Run failed. Check the log above. You can retry with the same or other AppStream login below.")
                cols = st.columns([3, 2])
                with cols[0]:
                    st.markdown(
                        "**Need to switch AppStream accounts?** "
                        "Log out in the Chrome window, log into the other account, then click Run Again."
                    )
                with cols[1]:
                    if st.button("🔁 Run Again", key=f"again_{report['id']}", use_container_width=True, disabled=not chrome_ok):
                        _execute_action(report, primary, picked, chrome_ok)
                if st.button("✖ Dismiss", key=f"dismiss_{report['id']}"):
                    del st.session_state[f"last_run_{report['id']}"]
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
                        if action.get("needs_date"):
                            sec_picked = st.date_input(
                                "WE Sunday",
                                key=f"sec_date_{report['id']}_{action['label']}",
                                value=_last_completed_we_sunday(),
                                label_visibility="collapsed",
                            )
                        elif action.get("needs_text"):
                            sec_picked = st.text_input(
                                action.get("text_label", "Input"),
                                key=f"sec_text_{report['id']}_{action['label']}",
                                label_visibility="collapsed",
                                placeholder=action.get("text_label", ""),
                            )
                        else:
                            sec_picked = None
                            st.write("")
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


def _add_intake(title: str, sheet_link: str, loom_link: str, description: str, submitted_by: str) -> str:
    new_id = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ws = _intake_ws()
    ws.append_row([
        new_id, title, sheet_link, loom_link, description,
        submitted_by, dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Unassigned", "", "",
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

    /* Hero card */
    .hero {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1.8rem 2rem;
        border-radius: 16px;
        margin-bottom: 1.2rem;
        box-shadow: 0 8px 24px rgba(102, 126, 234, 0.18);
    }
    .hero h1 { color: white !important; margin: 0 0 0.4rem 0; font-size: 1.9rem; }
    .hero p { margin: 0; opacity: 0.92; font-size: 1.05rem; }
    .hero .big-date {
        font-size: 2.4rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        margin-bottom: 0.3rem;
        opacity: 0.95;
        line-height: 1.1;
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
        transition: transform 0.1s ease;
    }
    .stButton > button:hover { transform: translateY(-1px); }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border: none;
    }
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Session state init + view router
# --------------------------------------------------------------------------

if "view" not in st.session_state:
    st.session_state.view = "home"   # "home" | "user" | "overview"
if "user" not in st.session_state:
    st.session_state.user = None     # name from MEMBERS once selected

LOGO_PATH = WORKSPACE / "resources" / "alphalete-logo.png"
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
    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
        <h1>{'🐺' if not LOGO_EXISTS else ''} Alphalete Reports</h1>
        <p>Pick your name to see today's reports — or view the team overview.</p>
    </div>
    """, unsafe_allow_html=True)

    # BIG Alphalete Overview card with wolf logo
    with st.container(border=True):
        cols = st.columns([1, 4, 2])
        with cols[0]:
            if LOGO_EXISTS:
                st.image(str(LOGO_PATH), width=130)
            else:
                st.markdown(
                    "<div style='font-size: 5rem; text-align: center; line-height: 1.0'>🐺</div>",
                    unsafe_allow_html=True,
                )
        with cols[1]:
            st.markdown(
                "<div style='font-size: 1.8rem; font-weight: 800; line-height: 1.1; margin-top: 0.5rem'>Alphalete Marketing</div>"
                "<div style='font-size: 1.3rem; font-weight: 600; opacity: 0.7; margin-bottom: 0.4rem'>7-Day Overview</div>"
                "<div style='opacity: 0.85'>Every report run by anyone, last 7 days.</div>",
                unsafe_allow_html=True,
            )
        with cols[2]:
            st.markdown("<div style='padding-top: 1.2rem'></div>", unsafe_allow_html=True)
            if st.button("📊 Open Overview", use_container_width=True, type="primary", key="home_overview_btn"):
                _go_overview()
                st.rerun()

    st.markdown("### 👥 Who are you?")

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


# --------------------------------------------------------------------------
# OVERVIEW VIEW — 7-day run log with miss alerts
# --------------------------------------------------------------------------

elif st.session_state.view == "overview":
    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
        <h1>📊 Alphalete Marketing — 7-Day Overview</h1>
        <p>Every report run by anyone, last 7 days. Reports flagged ⚠️ were scheduled but never ran.</p>
    </div>
    """, unsafe_allow_html=True)

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

    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
        <h1>{member_emoji} {greeting}, {user_name}!</h1>
        <p>Here's what's on your plate.</p>
    </div>
    """, unsafe_allow_html=True)

    my_reports = [r for r in AUTOMATED_REPORTS if user_name in r.get("assignees", [])]

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
    "💜 Built with Claude. To add a new automated report: Megan + Claude work together "
    "to build the script, then Megan adds a card to `AUTOMATED_REPORTS` in `automations/dashboard.py`."
)
