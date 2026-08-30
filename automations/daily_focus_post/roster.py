"""WHO gets a nightly Daily Focus Report post, and where.

One row per office. Everything that differs between offices lives here and
nowhere else — the tab its section sits on, the section label, the Slack
channel, and the timezone its 7 PM is measured in. Adding an office is a data
change, never a code change.

THE ASK (Raf, Loom 2026-08-30):
  "Can we make it where every day at 7 PM local time for that market, this Lucy
  Reporting sends a report that says Daily Focus Report, and then it just sends
  a screenshot of current week and the one last week... and post it in the
  thread. I would like it for my office. And then eventually I want to take
  this to other offices."

So: Lucy STARTS the thread each day (the dated parent post) and replies into it
with the office's section — Current Week and Last Week side by side, which is
one full-width row window on the tab. Raf's office first; the rest follow by
adding rows here once he signs off.

WHY 'owner' AND 'tab' ARE SEPARATE: the Daily Focus workbook has one tab per
CAPTAINSHIP, and each tab carries several owner SECTIONS. Raf's own office is
the first section on the 'Rafael Hidalgo' tab, which also holds John Richard
Young and the rest of his captainship. An office's post is its OWN section, not
its captain's whole tab — so a rollout row names both.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

# The Daily Focus workbook — same id the fill writes to
# (recruiting_report.daily_focus.DAILY_FOCUS_SPREADSHEET_ID).
SPREADSHEET_ID = "11FRYGG1hvuxcbWiYtDv7LzVss6ujZE_SOpqfhrQrVAo"

# The thread's title. Lucy posts '<TITLE> — August 30th 2026' as the parent and
# hangs the screenshot under it. Keep this stable: ensure_named_thread finds
# today's existing parent by this title, so changing it mid-day starts a second
# thread instead of reusing the first.
THREAD_TITLE = "Daily Focus Report"

# Office-local hour the post fires at, 24h. Raf asked for 7 PM.
POST_HOUR = 19

# Mon-Fri only (Megan 2026-08-30). The underlying report is itself a Mon-Fri
# breakdown — weekend numbers are folded into the adjacent weekday by the fill
# (Sat -> Fri, Sun -> Mon), so a Saturday or Sunday post would just repeat
# Friday's board. Monday=0 .. Sunday=6, measured in the OFFICE's timezone.
POST_WEEKDAYS = (0, 1, 2, 3, 4)


@dataclass(frozen=True)
class FocusOffice:
    key: str            # CLI handle, unique
    label: str          # human name for logs
    owner: str          # the col-C section label on the tab, e.g. "Rafael Hidalgo"
    tab: str            # the captainship tab the section lives on
    channel_id: str     # Slack channel the thread is started in
    channel_name: str   # display only — the ID is what posts
    timezone: str = "America/Chicago"


# Raf's office. The channel is PRIVATE and was renamed from
# #11280-alphalete-marketing-inc-rafael-hidalgo to #rafs-office-recruiting-11280
# — the ID is unchanged and is what matters. lucy_reporting (U0BCG8F9B5Z) is
# already a member (she posts BG Status there daily), so no new invite is needed.
# Irving/Frisco TX -> Central.
RAF = FocusOffice(
    key="raf",
    label="Rafael Hidalgo",
    owner="Rafael Hidalgo",
    tab="Rafael Hidalgo",
    channel_id="C0AUAS88FGW",
    channel_name="#rafs-office-recruiting-11280",
    timezone="America/Chicago",
)

# ENROLLED — start with Raf alone (his explicit ask: "I would like it for my
# office. And then eventually I want to take this to other offices"). Add a row
# above and list it here to roll out; nothing else needs to change.
ROSTER: List[FocusOffice] = [RAF]

BY_KEY = {o.key: o for o in ROSTER}


def get(key: str) -> FocusOffice:
    try:
        return BY_KEY[key]
    except KeyError:
        raise SystemExit(
            f"unknown office {key!r}. enrolled: {', '.join(BY_KEY)}")


def validate() -> List[str]:
    """Structural check. Two offices sharing a channel is the copy-paste
    mistake that posts one office's numbers into another's room, so it is a
    hard error rather than a warning."""
    problems: List[str] = []
    seen_channel = {}
    seen_key = set()
    for o in ROSTER:
        if o.key in seen_key:
            problems.append(f"{o.key}: duplicate key")
        seen_key.add(o.key)
        for f in ("label", "owner", "tab", "channel_id", "channel_name", "timezone"):
            if not (getattr(o, f) or "").strip():
                problems.append(f"{o.key}: empty {f}")
        if o.channel_id in seen_channel:
            problems.append(
                f"{o.key}: channel {o.channel_id} already used by "
                f"{seen_channel[o.channel_id]!r} — two offices must never share "
                f"a Daily Focus channel")
        else:
            seen_channel[o.channel_id] = o.key
    return problems
