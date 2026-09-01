"""Who gets which board, and why anyone is left out.

THE ROSTER IS PER SLOT, because two different people asked for two different
things and both are right:

  2:00 PM  first knocks  ─┐  CODY ONLY. He asked for these two (Slack DM
  5:15 PM  money lap     ─┘  2026-08-24) and Megan scoped them to his channel
                             alone (2026-08-25: "we only want to run this for
                             Cody's channel").

  9:00 PM  end of day        EVERY enrolled office, in its own local 9 PM.
                             Raf, 2026-08-25: "Can we have this Daily knocks
                             Post for every office at 9:00PM CEN please? I want
                             people to look at it at night for break downs, a
                             full view."

Raf wrote "CEN", which reads as one org-wide clock; Megan settled it as each
office's own 9 PM (2026-08-25), so a Michigan office gets its board at 9 PM
Michigan time rather than 10 PM. The org-wide "full view" is therefore not one
simultaneous moment — it rolls across the timezones over an hour.

Enrolment resolves against `office_metrics.OFFICES`, the one registry that
already knows an office's channel, its ownerville name and its cross-workspace
token — so a key here needs no second config.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from automations.office_metrics.offices import OFFICES, Office

# The two afternoon slots are Cody's alone (Megan 2026-08-25). Widening this is
# a one-line change: the schedule, the pull and the posting are all already
# multi-office, because the 9 PM slot exercises that path every night.
INTRADAY_KEYS = ("cody",)

# HAMMAD AND SALIK STAY TWO BOARDS — do not merge them (Megan 2026-08-25,
# asked directly). They sit in the same office and share #elite-prime-sales, so
# the channel gets two images seconds apart and it looks like a mistake. It
# isn't: each owner's board is judged on its own reps, which is why the header
# carries the first name. Read the summary rows accordingly — TOTAL, Talk To's
# per Rep and Chan's comparison line are all PER OWNER, not per that channel's
# combined roster.
#
# key -> why this office is held back from EVERY slot, including the 9 PM one.
# A real blocker, not a preference. Printed in the run log so a stale entry
# can't quietly outlive the thing that caused it.
# isaiah was here until 2026-08-25, held back as "gaps-only rows still render as
# no-rows (785ad46)". That stopped being true: render_knocks_boards dispatches on
# knocks_shape(), and a gaps-only office routes to render_telemapper_knocks —
# which carries Gaps + Total Gaps itself, so needs_time_gaps() is False and he
# gets ONE merged image like everyone else (Megan 2026-08-25: "Isaiah should post
# just like the others just with more limited data"). Verified against his real
# 2026-08-21 rows (probe_knocks): shape gaps_only, one 20KB board, not "no rows".
# His knock counts / Talk-To / Sale columns stay blank — ownerville has no
# Disposition page for a wireless office — but First/Last Knock, Gaps and Total
# Gaps are all real. [[project_isaiah_legacy_wireless]]
BLOCKED: dict = {}

# RAF IS NOT IN office_metrics.OFFICES, and that is not an oversight to fix
# there. His local office was folded onto the shared office-metrics CARD in July
# 2026 but never into the office TABLE — he still runs the older
# `automations.daily_metrics.run --owner "Rafael Hidalgo"` module. Adding him to
# OFFICES would enrol him in every report built on that table (office_metrics'
# own runner among them) and double-post metrics he already gets. So he lives
# here, local to the knocks roster, and nowhere else.
#
# Megan 2026-08-25, on the count looking short: "Raf gets metrics every morning
# so I feel like we're missing something."
#
# ov 'master': the rhidalgo login IS office 11280, so he cannot be impersonated —
# `pull_offices_days` sees is_master_office() and routes to pull_master_days_on_page
# instead. knocks_office must therefore match weekly_knock_dispositions.offices.RAF
# ["name"] exactly, which is what is_master_office compares against.
#
# Channel: #alphalete-sales. His Total Knocks board has always gone there; it
# went into that channel's Metrics THREAD, and the intraday boards post
# top-level instead (Megan, same day: "just be posted to the channel so everyone
# can see it"). Irving/Frisco TX -> Central.
RAF_OFFICE = Office(
    key="raf",
    report_id="knocks_intraday_raf",   # knocks-only; his metrics card is elsewhere
    label="Rafael Hidalgo",
    owner="Rafael Hidalgo",
    channel_id="C068PH3RFSM",          # #alphalete-sales
    channel_name="#alphalete-sales",
    sheet_id="",                       # this module writes no Sheet
    knocks_office="Rafael Hidalgo",    # == RAF["name"] -> is_master_office True
    timezone="America/Chicago",
)


# --- offices that moved to the dispositions sign-up ---------------------------
# An office that enrolls through the Daily Dispositions link picks its own
# channels AND its own times, so this module must stop posting to it — otherwise
# the room gets two identical boards seconds apart (Megan 2026-09-01: "they
# should just get removed from knocks_intraday since we want them enrolling in
# the dispositions").
#
# DERIVED, not a hand-kept list: read straight from the same
# gap_alerts/onboarded_offices.json that apply writes, so enrolling an office is
# the ONE action that both wires it there and removes it here. A hand-kept
# BLOCKED entry would be a second place to remember.
#
# Matched on CHANNEL ID, not office key: the two registries key offices
# differently (this one by office_metrics key, that one by the owner's first
# name), and the thing that must not receive two boards is the channel.
_ONBOARDED_JSON = (Path(__file__).resolve().parents[1] / "gap_alerts"
                   / "onboarded_offices.json")


def disposition_channels() -> set:
    """Slack channel ids owned by a LIVE dispositions enrollment. Best-effort:
    an unreadable file means this module keeps posting exactly as it did, which
    is the safe direction — a duplicate board is noise, a board that silently
    stops is a report nobody notices died."""
    out = set()
    try:
        rows = json.loads(_ONBOARDED_JSON.read_text())
    except Exception:                                # noqa: BLE001
        return out
    for r in rows:
        if not isinstance(r, dict) or not r.get("enabled", False):
            continue          # wired-but-off offices are not posting yet
        for d in r.get("destinations") or []:
            if d.get("kind") == "slack" and (d.get("channel_id") or "").strip():
                out.add(d["channel_id"].strip())
    return out


def _drop_enrolled(offices: List[Office]) -> List[Office]:
    taken = disposition_channels()
    if not taken:
        return offices
    return [o for o in offices if o.channel_id not in taken]


def enrolled(slot_key: str) -> List[Office]:
    """Offices owed `slot_key`'s board, in registry order.

    An unknown slot key returns [] rather than raising — a typo in a caller
    should cost one quiet slot, not crash a nightly run for every office."""
    if slot_key == "eod":
        # Raf rides the 9 PM slot only, and is appended rather than merged into
        # OFFICES so nothing else in the codebase inherits him. See RAF_OFFICE.
        return _drop_enrolled([OFFICES[k] for k in OFFICES if k not in BLOCKED]
                              + [RAF_OFFICE])
    elif slot_key in ("first", "money"):
        keys = list(INTRADAY_KEYS)
    else:
        return []
    return _drop_enrolled([OFFICES[k] for k in keys
                           if k in OFFICES and k not in BLOCKED])


def everyone() -> List[Office]:
    """Every office this module posts to in any slot — for the idle-tick log."""
    seen, out = set(), []
    for slot_key in ("first", "money", "eod"):
        for o in enrolled(slot_key):
            if o.key not in seen:
                seen.add(o.key)
                out.append(o)
    return out


def unknown_keys() -> List[str]:
    """Enrolled keys that are not real offices — a typo here would otherwise be
    an office that silently never posts."""
    return sorted(k for k in INTRADAY_KEYS if k not in OFFICES)


def blocked_lines() -> List[str]:
    """One 'key — reason' line per blocked office, for the run log."""
    return [f"{k} — {why}" for k, why in BLOCKED.items() if k in OFFICES]
