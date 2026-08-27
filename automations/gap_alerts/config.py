"""Static config for Rep Gap Alerts (Raf, 2026-08-26).

This is the BOTTOM HALF of Carlos's hourly B2B Dispositions post — the "Reps
Over 15 Min Gap" card and nothing else (Megan 8/26: "we only want the bottom
section showing only reps with gaps over 15 min"). No Today's Activity panel,
no territory stats, no Slack: it goes to one iMessage group, every 10 minutes of
the selling day (Raf moved it off 5 minutes on 2026-08-27 — see TICK_MINUTES).

Shaped as an OFFICE TABLE from the start even though Raf is the only row. The
b2b_dispositions module is Carlos-shaped throughout and adding a second office
to it meant touching every function; the same request has now arrived twice, so
the second office here is a dict, not a refactor.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

# --- OwnerVille ---------------------------------------------------------------
# Same JSON endpoint b2b_dispositions and total_knocks read: p=510's
# report_timeTracker.cfc?method=getTimeTrackingData. The live card WIDGET does
# not render under patchright (only a hidden template loads), which is why the
# card is redrawn from the data — see b2b_dispositions.capture.render_gap_card.
PAGE_TIME_TRACKER = 510

# Today's Activity (p=88): the rep list with each rep's knock-count badge. Raf
# asked for it 2026-08-27 — "can we actually get that column that Carlos gets
# that shows total knocks" — so his card now carries the same two panels
# Carlos's hourly B2B post has, in the same order.
PAGE_TODAYS_ACTIVITY = 88

# "Over 15 minute gap" is the card's own name for it, and >15 (not >=) is what
# b2b_dispositions has been sending Carlos since July. Kept identical so the two
# offices are looking at the same definition of "inactive".
GAP_THRESHOLD_MIN = 15

# --- offices ------------------------------------------------------------------
# name         ownerville office name (impersonation + alias lookup)
# ov           "master"      — the login IS this office (Raf: rhidalgo = 11280)
#              "impersonate" — enter Office Access as this owner, then exit
# campaign_id  TeleMapper campaign pin (invD2DClientId). The campaign is a
#              STICKY session-global that ANY other job on the box can move, so
#              every pull re-pins it. "3" = RES AT&T, the same value
#              weekly_knock_dispositions pins for Raf's office.
# group        iMessage group NAME. Resolved fresh on every send by
#              text_post.resolve_group — never a stored chat id: a group's GUID
#              is reminted on every membership change and a stale one "sends"
#              into a dead thread without erroring. That is how the Texas de
#              Brazil texts vanished.
RAF = {
    "key": "rafael",
    "name": "Rafael Hidalgo",
    "ov": "master",
    "campaign_id": "3",
    "group": "Alphalete Partners",
    "label": "",           # blank = no office name on the card (Raf's own room)
}

OFFICES: List[Dict] = [RAF]


def enabled() -> List[Dict]:
    return list(OFFICES)


def office(key: str) -> Optional[Dict]:
    for o in OFFICES:
        if o["key"] == key.strip().lower():
            return o
    return None


# --- the card -----------------------------------------------------------------
CARD_TITLE = "KNOCKS & GAPS"
PANEL_TODAYS_ACTIVITY = "TODAY'S ACTIVITY"
PANEL_GAPS = "REPS OVER 15 MIN GAP"

# The screenshot needs a real viewport; the JSON pull did not. Tall on purpose —
# a plain screenshot only sees what is in-frame, and Raf's roster is ~48 reps
# against Carlos's ~22.
VIEWPORT = {"width": 1680, "height": 1600}

# --- delivery format ----------------------------------------------------------
# Raf 2026-08-27, after the first two-panel card landed: "Can we make it a PDF
# so it's easier to see please?" Stacking his ~48-rep roster above the gap card
# made one very tall, very narrow image, which Messages shows inline as an
# unreadable sliver.
#
# Carlos hit the same wall on 8/6 and split his post into TWO pictures — that
# works at his ~22 reps. Raf's roster is more than twice that, so even a split
# leaves a sliver; a PDF opens full-screen and zooms, which is what he asked for.
SEND_AS_PDF = True

# A PDF page taller than this many times its width gets sliced into more pages.
# The whole point is that a page fits the screen at fit-to-width; one enormous
# page would just move the squinting from Messages into Preview.
PDF_MAX_ASPECT = 1.45

# Slices overlap by this many pixels so a rep row cut by a page break still
# appears whole on the next page. Cheap insurance against the one thing a naive
# slice gets wrong.
# Slices no longer overlap — the cut snaps to the gap BETWEEN rows, so nothing
# is severed and nothing needs repeating. Kept at 0 as the record of why.
PDF_SLICE_OVERLAP_PX = 0

# Render at N device pixels per CSS pixel, so the screenshot carries N× the
# detail. The panel is narrower than the PDF page, so a viewer scales it up and
# 1× text arrives soft — the only real fix is capturing more pixels, since
# nothing recovers detail a screenshot never took.
#
# NOT CSS ZOOM, and the difference is the whole lesson of 2026-08-27. Zoom
# scales the LAYOUT: at zoom=2 the rep column went narrow, every name wrapped
# onto two lines, the panel came back twice as tall, and it sliced into 29
# near-empty pages. Raf called it "mushed". device_scale paints the SAME layout
# with more pixels — nothing reflows, aspect ratios are unchanged, so the page
# count and the row cuts come out exactly as they do at 1×.
#
# Same knob tableau_screenshots has used for crisper Tableau posts.
#
# 2 -> 3 on 2026-08-27: at 2x the text was legible but still soft once Raf
# zoomed in, and zooming in is the whole reason this is a PDF. 3 is 50% more
# linear resolution. Safe to turn precisely because it is NOT zoom: the layout
# is identical, so page counts and row cuts do not move. The cost is a bigger
# screenshot and a slightly longer run — worth watching against
# MIN_SEND_GAP_MINUTES, which has to stay under (cadence - runtime).
CAPTURE_DEVICE_SCALE = 3

# The gap card is drawn by us, not screenshotted, so it has to be drawn bigger
# to match. A 1× card beside a 2× screenshot on one page width is visibly the
# softer of the two, and the PDF should read as one document.
CARD_RENDER_SCALE = 3

# --- the selling day (machine-local; Lucy 1 is Central) -----------------------
# Ticks every 10 minutes inside these windows (Megan 2026-08-26):
#     Mon–Fri  1:30pm – 8:30pm
#     Saturday 10:00am – 5:00pm
#     Sunday   off entirely
#
# Saturday has its OWN START, not just its own end — it is the one day the field
# is out in the morning. Every other short-interval job in this repo happens to
# share one start time across the week, so this is the thing to notice when
# editing: there are two windows here, not one window with a short Saturday.
#
# The END is load-bearing. Once the field stops knocking, EVERY rep reads
# "inactive 90 min ago" and the card degenerates into the whole roster — a wall
# of red that says nothing. That is why the day is fenced to the hours reps are
# actually out rather than left to run to midnight.
DAY_START_HHMM = (13, 30)
DAY_END_HHMM = (20, 30)
SATURDAY_START_HHMM = (10, 0)
SATURDAY_END_HHMM = (17, 0)
WEEKDAYS = (0, 1, 2, 3, 4, 5)          # Mon-Sat; Sunday is not a selling day
SATURDAY = 5

# The cadence, in one place. The gate that actually enforces it is MINUTE % 10
# in deploy/gap_alerts_5min.sh (whose filename is historic — see the note at the
# top of that script). Was 5 from launch until 2026-08-27, when Raf asked for
# 10: at 5 minutes the card was arriving faster than the room could act on it.
# CHANGE BOTH, and keep MIN_SEND_GAP_MINUTES just under this.
TICK_MINUTES = 10

# A card is REFUSED if this office got one less than this many minutes ago.
#
# WHY IT EXISTS. The pid lock stops two ticks OVERLAPPING; it does nothing
# about two landing back to back, and the room reads two near-identical cards
# as a broken alert. A launchd job fires the moment it is (re)loaded and again
# after a wake, the Hub button runs on top of the schedule, and so does a
# `lucy rerun`. All three happened the first evening this went live.
#
# MUST BE WELL UNDER (cadence - runtime), and that is the part that bit us.
# It was set to 9 against a 10-minute cadence on the reasoning that "just under
# a full tick" was safest — but the guard measures from when the card SENT,
# while the cadence anchors on when the tick FIRES, and a run takes 1-4 minutes
# in between. So each send landed ~1.5 min after its anchor, the next anchored
# tick was only ~8.5 minutes later, and the guard ate it: every second tick
# skipped, a real cadence of 20 minutes, and Raf watching an empty chat
# (2026-08-27, "it's not posting? it's been over 10 min").
#
# 5 leaves room for the slowest run we have seen (3m52s) and still blocks what
# it is for: the :01 catch-up minute after a :00 send, a reinstall fire, a
# hand-run stacked on the schedule.
MIN_SEND_GAP_MINUTES = 5

STATE_PATH = Path.home() / ".config" / "recruiting-report" / "gap_alerts_state.json"
LOCK_PATH = Path.home() / ".config" / "recruiting-report" / "gap_alerts.lock"

# Its OWN browser profile. The shared .browser_profile is held by the 4am batch
# and by anything else driving ownerville; a job that wakes up 96 times a day
# must never queue behind — or evict — one of those.
# Named .browser_profile_* on purpose: that wildcard is already in .gitignore,
# and this repo is PUBLIC — a profile dir holding a live OwnerVille session is
# one `git add .` away from being published. Same convention the captainship
# and other-office jobs use.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_gap_alerts")


def window_for(weekday: int):
    """((start_h, start_m), (end_h, end_m)) for a weekday, or None on Sunday."""
    if weekday not in WEEKDAYS:
        return None
    if weekday == SATURDAY:
        return SATURDAY_START_HHMM, SATURDAY_END_HHMM
    return DAY_START_HHMM, DAY_END_HHMM


def window_label(weekday: Optional[int] = None) -> str:
    """'1:30 PM-8:30 PM' — for the log line that explains a skipped tick."""
    win = window_for(dt.datetime.now().weekday() if weekday is None else weekday)
    if not win:
        return "off (Sunday)"
    return "%s-%s" % (_fmt12(win[0]), _fmt12(win[1]))


def _fmt12(hm) -> str:
    h, m = hm
    # No %-I: Windows has no such format code and every report here has to
    # import on both platforms.
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def in_selling_window(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    win = window_for(now.weekday())
    if not win:
        return False
    (sh, sm), (eh, em) = win
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end


def slot_label(now: Optional[dt.datetime] = None) -> str:
    """'4:35 PM' — the tick's own clock time, drawn on the card so a reader can
    tell a fresh card from one that scrolled up. No %-I: Windows has no such
    format code and every report here has to import on both."""
    now = now or dt.datetime.now()
    h12 = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    return "%d:%02d %s" % (h12, now.minute, ampm)
