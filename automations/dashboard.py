"""Operator dashboard for running report automations.

For Eve / Maud (operators): click a button, the report runs.
For Megan: add new automated reports to AUTOMATED_REPORTS once Claude builds them.

Run with:
    .venv/bin/streamlit run automations/dashboard.py
"""
from __future__ import annotations

import datetime as dt
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
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{_fill.SPREADSHEET_ID}/edit"

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
# Hero header
# --------------------------------------------------------------------------

today = dt.date.today()
weekday_name = WEEKDAY_NAMES[today.weekday()]
hour = dt.datetime.now().hour
greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")

st.markdown(f"""
<div class="hero">
    <h1>📊 {greeting}, friend!</h1>
    <p>Today is <b>{weekday_name}, {today.strftime("%B %d")}</b>. Your report dashboard is ready.</p>
</div>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Sidebar: system status + recent logs
# --------------------------------------------------------------------------

with st.sidebar:
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
# Today's Schedule
# --------------------------------------------------------------------------

due_today = [r for r in AUTOMATED_REPORTS if _is_due_today(r, today)]

st.markdown("## 📅 Today's Schedule")

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
else:
    nexts = []
    for r in AUTOMATED_REPORTS:
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
        st.info("No scheduled reports yet.")


# --------------------------------------------------------------------------
# Automated Reports (run buttons)
# --------------------------------------------------------------------------

st.markdown("## 🚀 Run a Report")

for report in AUTOMATED_REPORTS:
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
                    else:
                        args = action["args_fn"](picked) if action.get("needs_date") else action["args_fn"]()
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
