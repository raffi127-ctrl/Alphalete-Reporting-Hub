"""The new-start onboarding steps, in one place — one row per thing a NEW HIRE
in Raf's office gets put through.

Employee onboarding grew one automation at a time (BG Check Sync, then Blue Ink
New Start Docs, then the Headshot Bot) and each arrived with its own Hub card.
They were already the same job wearing three hats: the SAME weekly cohort on the
SAME `D2D OBCL <m.d>` tab of the SAME workbook, each ticking its own column and
reporting into the SAME Slack room. Megan 2026-08-25: separate runs, one thing —
so they share ONE card, the way the twelve per-office metric runs share the D2D
Office Daily Metrics card.

This module is that card's registry. The Hub card is GENERATED from it, so the
next onboarding automation (Digi Docs + Onboarding Quizzes — see
workflows/digi-docs-onboarding-quizzes.md) is one Step(...) row, not a card to
hand-write.

Import-light on purpose (dataclasses + stdlib only).
"""
from __future__ import annotations

from dataclasses import dataclass

# "All in One Local Office - Raf" — the workbook every step reads and writes.
SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
SHEET_URL = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
             "?gid=1430069873#gid=1430069873")

# A new tab per week. Monday's has TWO charts on it, so anything reading this
# tab reads every chart (blueink_docs.roster / shared.obcl_charts).
DATED_TAB_PREFIX = "D2D OBCL"

# Where every step reports what still needs doing by hand.
SLACK_CHANNEL = "#11280-alphalete-marketing-inc-rafael-hidalgo"

# The one Hub card all of these report onto.
CARD_ID = "new-start-onboarding"


@dataclass(frozen=True)
class Action:
    label: str
    icon: str
    help: str
    module: str
    args: tuple = ()
    primary: bool = False


@dataclass(frozen=True)
class Step:
    """One new-start automation: the OBCL column it owns, the machine it runs
    on, and the buttons that drive it."""
    key: str
    label: str                  # how the card names it
    emoji: str
    column: str                 # the OBCL column it fills
    machine: str
    when: str                   # human-readable schedule
    does: str                   # one line: what it actually does
    actions: tuple = ()
    # report_ids this step publishes under. They all route to CARD_ID via
    # hub_publish._HUB_CARD, and each keeps its OWN Report Name on the row so
    # the card's run feed still says which step ran.
    report_ids: tuple = ()
    notes: tuple = ()           # anything the card should say out loud
    live: bool = True


STEPS: list = [
    Step(
        key="bg_check",
        label="BG Check Sync",
        emoji="🪪",
        column="BG Status : Last Checked",
        machine="Lucy 1",
        when="11:30 AM + 4 PM daily",
        does=("reads the Sterling / First Advantage emails and updates each "
              "new start's BG Status on both OBCL tabs"),
        report_ids=("bg_check_sync",),
        actions=(
            Action("Sync BG Statuses", "🔁",
                   "Read today's BG-check emails and update the BG Status "
                   "column on both OBCL tabs.",
                   "automations.bg_check_sync.run"),
            Action("Preview BG Statuses", "👁",
                   "Show what WOULD be written. Changes nothing.",
                   "automations.bg_check_sync.preview"),
        ),
        notes=("Two passes a day, not three: the nightly schedule guard only "
               "self-heals jobs with ≤2 launchd entries.",),
    ),
    Step(
        key="blueink",
        label="Blue Ink Packet",
        emoji="🖊️",
        column="Blue Ink",
        machine="Lucy 2",
        when="Mon 7:30 AM, then a signed-sweep every 2h (8:15 AM–8:15 PM)",
        does=("sends each eligible new start their I-9 / W-4 / Direct Deposit "
              "packet through the Blue Ink web app, tints the name green, and "
              "ticks the box once they've SIGNED"),
        report_ids=("blueink_docs",),
        actions=(
            Action("Preview Packets", "👁",
                   "Show who WOULD be sent to this week, and who wouldn't and "
                   "why. Sends nothing.",
                   "automations.blueink_docs.run", primary=True),
            Action("Send Packets Now", "▶",
                   "Send this week's packets for real, then post the summary "
                   "to Slack. Cannot be undone.",
                   "automations.blueink_docs.run", ("--send", "--slack")),
            Action("Refresh Signed", "✅",
                   "Sends nothing. Ticks the Blue Ink checkbox for anyone "
                   "whose packet has been signed since the last run.",
                   "automations.blueink_docs.run", ("--sync-completed",)),
        ),
        notes=("Sends through the WEB APP on purpose — API sends bill as Bulk "
               "Envelopes, capped at 50/YEAR on this plan and long spent.",
               "Needs a live browser session on Lucy 2. When it expires the "
               "run refuses to send and says so; a human re-seeds with "
               "`session.py --login` at that machine.",
               "The cell carries two facts: light green = we sent it, "
               "checkbox ticked = they signed it. It only ever ticks ON."),
    ),
    Step(
        key="headshot",
        label="Headshot Photo",
        emoji="📸",
        column="Headshot Photo",
        machine="Lucy 3",
        when="Mon 8:30 AM thread, then every 5 min all week",
        does=("collects headshots in a Monday Slack thread, cuts each onto a "
              "white background, uploads it to the rep's OwnerVille profile, "
              "and ticks the column"),
        report_ids=("headshots", "headshots_monday"),
        actions=(
            Action("Check for New Photos", "👁",
                   "Run one pass now instead of waiting for the 5-minute "
                   "tick: process new replies, upload them, tick the sheet.",
                   "automations.headshots.run"),
            Action("Post This Week's Photo Thread", "📢",
                   "Post the Monday Headshot Submissions thread now — for a "
                   "missed or deleted Monday. Will not post twice in a week.",
                   "automations.headshots.weekly_thread", ("--force",)),
            Action("Why Was A Photo Skipped?", "🔍",
                   "Read-only: show what the bot decided about every reply in "
                   "the current thread, and why. Changes nothing.",
                   "automations.headshots.run", ("--diag",)),
        ),
        notes=("Name typos are forgiven, but two people too close to tell "
               "apart is refused rather than guessed.",
               "Never overwrites a photo already on someone's OwnerVille "
               "profile.",
               "Also watches LAST week's thread, so weekend stragglers still "
               "get handled."),
    ),
    # ---- NEXT STEP GOES HERE ----------------------------------------------
    # Digi Docs + Onboarding Quizzes (Megan 2026-08-25). The click-path is
    # captured in workflows/digi-docs-onboarding-quizzes.md, read off her Loom;
    # three questions there need answering before it can be wired. Add it as
    # one Step(...) row and it picks up its section on the Hub card and its
    # buttons automatically — nothing else to edit.
]


def live_steps() -> list:
    return [s for s in STEPS if s.live]


def by_key(key: str) -> Step:
    for s in STEPS:
        if s.key == key:
            return s
    raise KeyError(key)


def report_id_map() -> dict:
    """{report_id: CARD_ID} — what hub_publish._HUB_CARD needs to route every
    step's runs onto the one card."""
    return {rid: CARD_ID for s in live_steps() for rid in s.report_ids}


def machines() -> list:
    """Assignees for the card, in step order, de-duped."""
    out: list = []
    for s in live_steps():
        if s.machine not in out:
            out.append(s.machine)
    return out
