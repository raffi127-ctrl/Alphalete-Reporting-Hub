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
            "human_prep": [
                "Launch Chrome with the recruiting profile (see sidebar command)",
                "Log into AppStream as **rhidalgo** (broader account)",
                "Click **▶ Run This Week** below — fills ~43 offices",
                "When done: log out of rhidalgo, log into **rcaptain**",
                "Click **▶ Backfill Last 10 Weeks** — fills the remaining 8 offices",
                "Spot-check the Sheet — verify 1-2 random office tabs look right",
            ],
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
            "human_prep": [
                "Launch Chrome with the recruiting profile (see sidebar command)",
                "Log into AppStream as **rhidalgo** (broader account)",
                "Click **▶ Run Daily Focus** below — fills all 17 ICDs",
                "If any ICD shows 'not accessible': switch to the other AppStream login and click again",
                "Spot-check the Sheet — verify a couple ICD sections look right",
            ],
        },
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
        st.error("Chrome is NOT running")
        with st.expander("How to launch Chrome", expanded=True):
            st.markdown("Run this in **Terminal**:")
            st.code(
                'open -na "Google Chrome" --args '
                '--remote-debugging-port=9222 '
                '--user-data-dir="$HOME/.config/recruiting-report/chrome-attach"',
                language="bash",
            )
            st.markdown("Then **log into AppStream** in the new Chrome window.")
            st.markdown("**If Chrome won't launch:**")
            st.code("rm ~/.config/recruiting-report/chrome-attach/Singleton*", language="bash")

    st.markdown("---")
    st.markdown("### 📜 Recent Runs")
    logs = _list_recent_logs(6)
    if not logs:
        st.caption("No runs yet.")
    for p in logs:
        mtime = dt.datetime.fromtimestamp(p.stat().st_mtime)
        with st.expander(f"{p.name}", expanded=False):
            st.caption(mtime.strftime("%a %b %d, %I:%M %p"))
            try:
                tail = p.read_text().splitlines()[-25:]
                st.code("\n".join(tail), language="log")
            except Exception:
                st.warning("(couldn't read log)")


# --------------------------------------------------------------------------
# HOME VIEW — name picker + Alphalete Overview button
# --------------------------------------------------------------------------

if st.session_state.view == "home":
    st.markdown(f"""
    <div class="hero">
        <div class="big-date">{BIG_DATE}</div>
        <h1>📊 Welcome to Alphalete Reports</h1>
        <p>Pick your name to see today's reports — or view the team overview.</p>
    </div>
    """, unsafe_allow_html=True)

    # Big Alphalete Overview button at top
    if st.button(
        "📊  Alphalete Marketing — 7-Day Overview",
        use_container_width=True,
        type="primary",
        key="home_overview_btn",
    ):
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

    user_reports = [r for r in AUTOMATED_REPORTS if user_name in r.get("assignees", [])]
    due_today = [r for r in user_reports if _is_due_today(r, today)]

    # ----- Today's Schedule -----
    st.markdown("## 📋 Today's Schedule")

    if due_today:
        for r in due_today:
            sched = r["schedule"]
            with st.container(border=True):
                cols = st.columns([1, 8])
                with cols[0]:
                    st.markdown(f"<div style='font-size: 3rem; text-align:center'>{r['emoji']}</div>",
                               unsafe_allow_html=True)
                with cols[1]:
                    st.markdown(
                        f"<span class='pill pill-due'>DUE TODAY</span>"
                        f"<span class='pill pill-info'>{sched['time']} • ~{sched['estimated_minutes']} min</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"### {r['name']}")
                    st.caption(r["description"])

                with st.expander("📝 Your steps for today", expanded=True):
                    for i, step in enumerate(sched["human_prep"], start=1):
                        st.markdown(f"**{i}.** {step}")
    elif user_reports:
        nexts = []
        for r in user_reports:
            nd = _next_due(r, today)
            if nd:
                nexts.append((nd, r))
        nexts.sort(key=lambda x: x[0])
        if nexts:
            nd, r = nexts[0]
            delta = (nd - today).days
            plural = "s" if delta != 1 else ""
            st.info(
                f"☕ Nothing on your plate today. "
                f"Next up: **{r['name']}** in **{delta} day{plural}** ({WEEKDAY_NAMES[nd.weekday()]} {nd.strftime('%b %d')})."
            )
    else:
        st.info(f"No reports assigned to {user_name} yet. (Anyone can still run anything from the team page.)")

    # ----- All this user's reports (run buttons) -----
    if user_reports:
        st.markdown("## 🚀 Your Reports")

        for report in user_reports:
            with st.container(border=True):
                st.markdown('<div class="report-card-marker"></div>', unsafe_allow_html=True)
                cols = st.columns([5, 2])
                with cols[0]:
                    st.markdown(f"### {report['emoji']} {report['name']}")
                    st.caption(report["description"])
                with cols[1]:
                    st.link_button("📂 Open Sheet", report["sheet_url"], use_container_width=True)

                # Action buttons
                for action in report["actions"]:
                    cols = st.columns([4, 2, 2])
                    with cols[0]:
                        st.markdown(f"**{action.get('icon', '')} {action['label']}**")
                        if action.get("help"):
                            st.caption(action["help"])
                    with cols[1]:
                        if action.get("needs_date"):
                            picked = st.date_input(
                                "WE Sunday",
                                key=f"date_{report['id']}_{action['label']}",
                                value=_last_completed_we_sunday(),
                                label_visibility="collapsed",
                            )
                        elif action.get("needs_text"):
                            picked = st.text_input(
                                action.get("text_label", "Input"),
                                key=f"text_{report['id']}_{action['label']}",
                                label_visibility="collapsed",
                                placeholder=action.get("text_label", ""),
                            )
                        else:
                            picked = None
                            st.write("")
                    with cols[2]:
                        btn_kind = "primary" if action.get("primary") else "secondary"
                        if st.button(
                            f"{action.get('icon', '▶')} Run",
                            key=f"btn_{report['id']}_{action['label']}",
                            type=btn_kind,
                            use_container_width=True,
                        ):
                            if not chrome_ok:
                                st.error("⚠️ Chrome isn't running. Check the sidebar for the launch command.")
                            elif action.get("needs_text") and not picked:
                                st.error(f"⚠️ Please enter the {action.get('text_label', 'input')} first.")
                            else:
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


# --------------------------------------------------------------------------
# Request a new automation OR a change to an existing one
# --------------------------------------------------------------------------

st.markdown("## 💡 Suggest an Automation or Change")
st.caption(
    "See a report we should automate, or want to tweak an existing one? "
    "Drop the details here — Megan reviews and works with Claude to build/update."
)

with st.form("suggestion_form", clear_on_submit=True):
    cols = st.columns(2)
    with cols[0]:
        sugg_type = st.selectbox(
            "What kind of suggestion?",
            ["New automation request", "Change to an existing report", "Bug / something broke"],
        )
        report_name = st.text_input("Report name", placeholder="e.g. 'OPT Focus Report'")
        requester = st.text_input("Your name", placeholder="Eve / Maud / …")
    with cols[1]:
        link = st.text_input("Link to the report (Sheet URL)", placeholder="https://…")
        loom = st.text_input("Loom video showing how it's done manually (optional)", placeholder="https://loom.com/…")
        priority = st.select_slider("Priority", options=["Low", "Medium", "High", "Blocking"], value="Medium")
    details = st.text_area(
        "Details — what should it do? what should change?",
        height=120,
        placeholder="Describe the goal, the source data, and what needs to happen weekly/daily.",
    )
    submitted = st.form_submit_button("📨 Submit Request", type="primary", use_container_width=True)

    if submitted:
        if not (report_name and requester and details):
            st.error("Please fill in at least Report Name, Your Name, and Details.")
        elif not REPORT_INTAKE_SHEET_ID:
            st.warning(
                "Intake Sheet not yet wired up. Megan: paste your "
                "REPORT AUTOMATIONS - TO DO Sheet ID into `REPORT_INTAKE_SHEET_ID` "
                "in `automations/dashboard.py` and re-launch."
            )
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
                    report_name,
                    link,
                    loom,
                    "",  # Who Is Working On — admin to fill
                    "",  # Runbook link — admin to fill
                    sugg_type,
                    requester,
                    priority,
                    details,
                    dt.datetime.now().isoformat(timespec="minutes"),
                ])
                st.success("✅ Submitted! Megan will see this on the next review.")
                st.balloons()
            except Exception as e:
                st.error(f"Couldn't write to intake Sheet: {e}")


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------

st.divider()
st.caption(
    "💜 Built with Claude. To add a new automated report: Megan + Claude work together "
    "to build the script, then Megan adds a card to `AUTOMATED_REPORTS` in `automations/dashboard.py`."
)
