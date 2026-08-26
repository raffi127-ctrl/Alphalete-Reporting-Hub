"""The new-start onboarding family — one row per step a NEW HIRE goes through.

A REGISTRY, not a card. Every step here has its OWN Hub card, on its own
machine and its own cadence:

    BG Check Sync    Lucy 1   11:30am + 4pm          -> bg-check-sync
    Blue Ink Packet  Lucy 2   Mon 7:30am + 2h sweep  -> blueink-docs
    Headshot Photo   Lucy 3   Mon 8:30am + 5min tick -> headshot-bot
    Digi Docs        Lucy 3   Mon 7:45am             -> digi-docs

These were briefly merged onto one card on 2026-08-25 and split back the same
day (Megan). The merge cited the D2D Office Daily Metrics card as precedent,
which was a misread: that card merges twelve runs of the SAME module on the
SAME machine in the SAME batch. A Hub card is the unit of "did THIS run on THIS
box at THIS time" — its pill, its schedule, its due-today count and the profile
it appears on are all keyed to exactly that. Across three machines and three
cadences none of those can be right: one pill cannot show Blue Ink failing while
Headshots succeeds, and one schedule string cannot be three cadences.

So the rule this file encodes: **merge WITHIN a machine and cadence, never
across.** Two jobs that share a box AND a clock can share a card; anything else
gets its own.

What the family still shares is real, and is what this registry is for: the
same weekly cohort on the same `D2D OBCL <m.d>` tab of the same workbook (every
chart on it — Monday's has two), the same eligibility block-list, the same
Slack room, one column each, and all of it on Raf's logins. Report code reads
these constants instead of each module carrying its own copy.
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

# NOTE: there is deliberately NO family-wide card id. Each Step carries its own
# `card`, and runners pass THAT to hub_activity.log_completed — which keys on
# the card id, so a runner logging its scheduler handle instead self-registers a
# duplicate library card and splits its history in two. That is exactly what the
# Monday headshot thread did until 2026-08-25.


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
    card: str = ""              # this step's Hub card id
    # report_ids this step publishes under; hub_publish._HUB_CARD routes each
    # to `card`. Several ids per card is normal — the Monday thread and the
    # 5-minute tick are both the Headshot Bot.
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
        card="bg-check-sync",
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
        card="blueink-docs",
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
        card="headshot-bot",
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
    Step(
        key="digi_docs",
        label="Digi Docs",
        emoji="🗂️",
        column="Digi Docs",
        machine="Lucy 3",
        when="Mon 7:45 AM",
        does=("adds each new start to OwnerVille, then generates their "
              "document bundle — which is what mails it — ticks the BG and "
              "drug-test attestations, and tints the Digi Docs cell"),
        card="digi-docs",
        report_ids=("digi_docs",),
        actions=(
            Action("Preview Bundles", "👁",
                   "Show who WOULD be sent to this week, and who wouldn't and "
                   "why. Sends nothing.",
                   "automations.digi_docs.run", primary=True),
            Action("Send Bundles Now", "▶",
                   "Add anyone missing to OwnerVille, then generate and mail "
                   "this week's document bundles. Cannot be undone.",
                   "automations.digi_docs.run", ("--both", "--live")),
            Action("Add To OwnerVille Only", "➕",
                   "Mails nobody. Adds this week's new starts to OwnerVille "
                   "so they exist before the bundles go out.",
                   "automations.digi_docs.run", ("--add-only", "--live")),
        ),
        notes=("Generating the bundle IS the send — OwnerVille mails the "
               "nine documents itself. There is no separate send step and no "
               "unsend.",
               "Tints the Digi Docs cell, never the name and never the "
               "checkbox: the tint says WE SENT IT, the tick is a person "
               "saying it's complete.",
               "Skips anyone whose Onboarding Documents row isn't REQUIRED "
               "ACTION, so a re-run after a mid-batch stall is quiet and "
               "safe.",
               "Onboarding Quizzes is NOT automated — those six courses are "
               "the rep's own coursework and stay a human column."),
    ),
    # ---- NEXT STEP GOES HERE ----------------------------------------------
    # Add it as one Step(...) row and it picks up its section on the Hub card
    # and its buttons automatically — nothing else to edit.
]


def live_steps() -> list:
    return [s for s in STEPS if s.live]


def by_key(key: str) -> Step:
    for s in STEPS:
        if s.key == key:
            return s
    raise KeyError(key)


def report_id_map() -> dict:
    """{report_id: card id} — what hub_publish._HUB_CARD needs so every run
    lands on ITS OWN step's card."""
    return {rid: s.card for s in live_steps() for rid in s.report_ids if s.card}


def machines() -> list:
    """Every machine the family touches, in step order, de-duped."""
    out: list = []
    for s in live_steps():
        if s.machine not in out:
            out.append(s.machine)
    return out
