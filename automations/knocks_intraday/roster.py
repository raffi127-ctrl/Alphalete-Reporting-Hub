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


def enrolled(slot_key: str) -> List[Office]:
    """Offices owed `slot_key`'s board, in registry order.

    An unknown slot key returns [] rather than raising — a typo in a caller
    should cost one quiet slot, not crash a nightly run for every office."""
    if slot_key == "eod":
        keys = [k for k in OFFICES]
    elif slot_key in ("first", "money"):
        keys = list(INTRADAY_KEYS)
    else:
        return []
    return [OFFICES[k] for k in keys if k in OFFICES and k not in BLOCKED]


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
