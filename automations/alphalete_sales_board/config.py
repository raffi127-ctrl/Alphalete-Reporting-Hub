"""Where the Alphalete Sales Board sweep reads, writes and posts.

ONE PLACE for every id, name and window, because the sweep runs unattended 150+
times a day and nobody is going to read the code to find out which chat it is
texting.

RUNS ON LUCY 1 (Megan 2026-08-26). Not a load decision -- Lucy 1 is the busiest
runner -- but the iMessage one: the two chats below live in Lucy 1's Messages
(signed in as alphaletereporting@gmail.com, same account owner_chat_texts
sends the owner trackers from), and Lucy 3's chat.db probe came back empty on
2026-08-26. The board write and the Slack post could live anywhere; the texts
could not, and splitting the sweep across two machines would buy a quieter box
at the price of a cross-machine handoff for state this report re-reads every
five minutes. See MODULE NOTES in run.py for how the load is fenced instead.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

# --- SaraPlus ---------------------------------------------------------------
LOGIN_URL = "https://ui.saraplus.com"

# Credentials live OUTSIDE the repo, like every other machine credential.
# Push it to a runner with:
#   lucy push_cred_file saraplus-creds "Lucy 1" --machine "<the box that has it>"
# File shape: {"email": "...", "password": "..."}
CREDS_PATH = Path.home() / ".config" / "recruiting-report" / "saraplus-creds.json"

# Its own Chrome profile, under automations/uploaded/ so chrome_guard's
# close_stray_chrome() protects it and the Tableau/ownerville profiles are
# never shared. [[reference_chrome_collision_guard]]
REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO_ROOT / "automations" / "uploaded" / ".saraplus_profile"

# --- the board --------------------------------------------------------------
# 'Alphalete SALES BOARD 2025' -- the same workbook rep_sales_fill writes and
# terminated_reps reads. Tabs are 'Sales Board WE <m>.<d>' (the week's SUNDAY).
SPREADSHEET_ID = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"

# SaraPlus spelling -> the name as col C carries it. Only rows where the LETTERS
# differ belong here; parentheticals like '(Wk3)' are stripped before matching.
NAME_MAP: Dict[str, str] = {
    "NATHANIEL MARTINEZ": "Nathaniel (Nate) Martinez",
    "GLORIA SCOTT": "Annice Middleton",
}

# --- notifications ----------------------------------------------------------
SLACK_CHANNEL = "C068PH3RFSM"          # #alphalete-sales

# iMessage group needles for text_post.resolve_group (case-insensitive
# substring; it raises on 0 or 2+ hits rather than guessing). The TS system
# addressed these by chat.db ROWID (40 and 31) -- a per-machine integer that
# means a different room on a different Mac, which is exactly why this port
# resolves by NAME on every send instead.
# Needles, not ids. The TS system addressed these rooms by chat.db ROWID (40
# and 31) -- a per-machine integer that names a DIFFERENT room on a different
# Mac -- so this port resolves by name on every send instead.
#
# Read off Lucy 1 on 2026-08-26 (`lucy find_group Alphalete --machine "Lucy 1"`):
#     "Alphalete A-Team Chat<flames>"   20 participants
#     "Alphalete lvl 1's<flames>"       29 participants
#     "Alphalete Owners<flame> - Real"  25 participants
# "Alphalete Partners" was NOT among them at 17:23 -- Megan added
# alphaletereporting@ (the account Lucy 1's Messages is signed in as) to it at
# 17:38 the same day, which is what put the room on that machine at all. So a
# resolution failure here reads as "Lucy was removed from the chat", and that
# is the right thing for it to mean.
GROUP_PARTNERS = "Alphalete Partners"   # the 7-person partners chat
GROUP_LVL1 = "Alphalete lvl 1"          # the 29-person reps chat

WEEKLY_GOAL = 80

# The Lvl 1's chat gets ONE leaderboard a day, at the end of selling: Mon-Fri
# 8:00pm, Saturday 4:00pm. The Partners chat gets every sweep that found a sale.
LVL1_WINDOWS = {0: (20, 0), 1: (20, 0), 2: (20, 0), 3: (20, 0), 4: (20, 0),
                5: (16, 0)}
LVL1_WINDOW_MINUTES = 5

# --- the selling day --------------------------------------------------------
# The sweep is fenced to these hours (machine-local, Lucy 1 is Central). The
# 4am batch owns the morning: it runs ~130 reports and several of them drive a
# browser, so the sweep deliberately does not start until the wave is through.
# SaraPlus is cumulative per day, so a late start loses nothing -- the first
# sweep of the day reads the whole day so far.
DAY_START_HHMM = (7, 0)
DAY_END_HHMM = (21, 30)
WEEKDAYS = (0, 1, 2, 3, 4, 5)          # Mon-Sat; Sunday is not a selling day

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "alphalete_sales_board_state.json"
LOCK_PATH = Path.home() / ".config" / "recruiting-report" / "alphalete_sales_board.lock"


def creds() -> Dict[str, str]:
    """{'email', 'password'} for SaraPlus, or a clear error naming the fix."""
    env_user = os.environ.get("SARA_PLUS_EMAIL")
    env_pass = os.environ.get("SARA_PLUS_PASSWORD")
    if env_user and env_pass:
        return {"email": env_user, "password": env_pass}
    if not CREDS_PATH.exists():
        raise RuntimeError(
            "no SaraPlus credentials at %s. Push them to this runner with "
            "`lucy push_cred_file saraplus-creds \"Lucy 1\" --machine \"<box "
            "that has them>\"`, or export SARA_PLUS_EMAIL / SARA_PLUS_PASSWORD."
            % CREDS_PATH)
    data = json.loads(CREDS_PATH.read_text())
    missing = [k for k in ("email", "password") if not data.get(k)]
    if missing:
        raise RuntimeError("%s is missing %s" % (CREDS_PATH, ", ".join(missing)))
    return {"email": data["email"], "password": data["password"]}


def in_selling_window(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if now.weekday() not in WEEKDAYS:
        return False
    start = now.replace(hour=DAY_START_HHMM[0], minute=DAY_START_HHMM[1],
                        second=0, microsecond=0)
    end = now.replace(hour=DAY_END_HHMM[0], minute=DAY_END_HHMM[1],
                      second=0, microsecond=0)
    return start <= now <= end


def lvl1_due(now: Optional[dt.datetime] = None) -> bool:
    """True inside the day's one Lvl 1's slot. A 5-minute width matches the
    5-minute sweep, so exactly one sweep a day lands in it -- and state.py
    still records the send, so a double-fired launchd tick can't text twice."""
    now = now or dt.datetime.now()
    slot = LVL1_WINDOWS.get(now.weekday())
    if not slot:
        return False
    start = now.replace(hour=slot[0], minute=slot[1], second=0, microsecond=0)
    return start <= now < start + dt.timedelta(minutes=LVL1_WINDOW_MINUTES)


def week_ending(day: dt.date) -> dt.date:
    """The Sunday that closes `day`'s Mon-Sun week -- the board's tab name."""
    return day + dt.timedelta(days=6 - day.weekday())
