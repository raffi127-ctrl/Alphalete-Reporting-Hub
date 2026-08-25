"""The onboarding surfaces, in one place — one row per thing a NEW OFFICE gets
wired into.

Onboarding grew one automation at a time (metrics 2026-08-20, trackers
2026-08-20) and each arrived with its own Hub presence: its own link block on
the Office Operations page, its own scheduler handles, its own Hub card. Megan
2026-08-25: they are separate runs but they are all ONE thing — onboarding — so
they belong on ONE card, the way the twelve per-office metric runs share the
D2D Office Daily Metrics card.

This module is that card's registry. Everything that describes a surface —
its form, the sheet tab the form writes, the module that materializes it into
the repo, the auto-commit leg, the safety-net check — is a row here, and the
Hub card + the Office Operations link block are GENERATED from it. Adding the
next onboarding automation is one `Surface(...)` row, not a card to hand-write
and a link block to remember.

Import-light on purpose (dataclasses + stdlib only): the Hub, the forms and
the runners all import it, and none of them should pay for the others.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# The AUTOMATION MASTER workbook every onboarding form writes into. Same sheet
# the Hub's intake / Hub Activity tabs live on.
MASTER_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
MASTER_SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{MASTER_SHEET_ID}/edit")

# The one Hub card every onboarding surface reports onto. Runners pass THIS to
# hub_activity.log_completed — that function keys on the card id, so a runner
# logging its own scheduler handle instead would self-register a duplicate
# library card and split the card's history in two.
CARD_ID = "office-onboarding"


@dataclass(frozen=True)
class Link:
    label: str
    url: str
    caption: str = ""


@dataclass(frozen=True)
class Surface:
    """One onboarding automation: a form, a sheet tab, and the legs that turn a
    submitted row into working config."""
    key: str
    label: str                      # how the card names it
    emoji: str
    # One line: what enrolling an office here actually turns on.
    gives: str
    sheet_tab: str                  # tab on the AUTOMATION MASTER workbook
    # Module that reads the tab and materializes it into the repo. Dry-run by
    # default; `apply_args` is what --write looks like.
    apply_module: str
    apply_args: tuple = ("--write",)
    apply_label: str = ""           # button text on the card
    # Optional legs.
    auto_commit_module: str = ""    # commits + pushes confirmed rows
    auto_commit_label: str = ""
    auto_commit_when: str = ""      # human-readable schedule
    pending_module: str = ""        # safety net: flags un-applied rows
    pending_when: str = ""
    links: tuple = ()               # Link rows for the Office Ops block
    live: bool = True
    note: str = ""                  # anything the card should say out loud


# ---------------------------------------------------------------------------
# The surfaces, in the order an office gets set up.
# ---------------------------------------------------------------------------
SURFACES: list = [
    Surface(
        key="metrics",
        label="Metrics Onboarding",
        emoji="🏢",
        gives=("its own daily Metrics thread — all 12 metrics posted "
               "into its Slack channel, on the machine its Tableau view owner "
               "implies (Raf → Lucy 1, Carlos → Lucy 2)"),
        sheet_tab="Office Onboarding",
        apply_module="automations.office_onboarding.apply",
        apply_label="Apply enrollments (write registry + schedule)",
        auto_commit_module="automations.tracker_onboarding.auto_commit",
        auto_commit_label="Auto-commit confirmed offices",
        auto_commit_when="3:15 AM + 5:30 PM on Lucy 1",
        pending_module="automations.office_onboarding.pending_alert",
        pending_when="hourly, 9 AM–10 PM on Lucy 1",
        links=(
            Link("🏢 Open onboarding form",
                 "https://alphaletemetricsintake.streamlit.app",
                 "Add a new office"),
            Link("🧵 Thread Builder (admin)",
                 "https://alphaletemetricsintake.streamlit.app/?admin=1",
                 "Edit sections + order · password A****123"),
            Link("📤 Owner request form (send to an office)",
                 "https://alphaletemetricsrequest.streamlit.app",
                 "Owner picks program + metrics → you get pinged to finalize"),
        ),
        note=("A BRAND-NEW office is never auto-applied at 4am: apply rewrites "
              "the committed registry AND schedule_config, so it is reviewed "
              "first. The hourly pending check is what stops a submitted "
              "office sitting unnoticed in the meantime."),
    ),
    Surface(
        key="trackers",
        label="Tracker Onboarding",
        emoji="📊",
        gives=("the daily Tableau tracker screenshots in its own Slack "
               "channel — same universal boards everyone gets, in the order "
               "the form picks"),
        sheet_tab="Tracker Onboarding",
        apply_module="automations.tracker_onboarding.apply",
        apply_label="Apply tracker enrollments",
        auto_commit_module="automations.tracker_onboarding.auto_commit",
        auto_commit_label="Auto-commit confirmed offices",
        auto_commit_when="3:15 AM + 5:30 PM on Lucy 1",
        links=(
            Link("📊 Open tracker form",
                 "https://alphaletetrackerintake.streamlit.app",
                 "Pick the channel + which trackers, in what order"),
        ),
        note=("No schedule entry and no machine choice: the existing daily "
              "tracker_screenshots run loops every org in the registry, so an "
              "applied office posts on the next run with no other wiring."),
    ),
    # ---- NEXT SURFACE GOES HERE -------------------------------------------
    # Add the third onboarding automation as one Surface(...) row and it picks
    # up its section on the Hub card, its buttons, and its link block on the
    # Office Operations page automatically. Nothing else to edit.
]

# The auto-commit leg is SHARED: tracker_onboarding.auto_commit runs the
# tracker apply AND the metrics registry apply in one pass (never
# schedule_config.json — that file is hot on the runners). So the card must not
# render one button per surface for it.
_AUTO_COMMIT_SHARED = "automations.tracker_onboarding.auto_commit"


def by_key(key: str) -> Surface:
    for s in SURFACES:
        if s.key == key:
            return s
    raise KeyError(key)


def live_surfaces() -> list:
    return [s for s in SURFACES if s.live]


def all_links() -> list:
    """Every form link, surface order — what the Office Ops block renders."""
    return [(s, ln) for s in live_surfaces() for ln in s.links]


def auto_commit_surfaces() -> list:
    return [s for s in live_surfaces() if s.auto_commit_module]


def pending_surfaces() -> list:
    return [s for s in live_surfaces() if s.pending_module]
