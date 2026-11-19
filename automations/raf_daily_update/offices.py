"""Which offices get the Daily Update, and where each one's goes.

Raf's Daily Update started as his alone (office 11280). Raf, 2026-10-26: roll
it out to other ICDs. Same ApplicantStream pages, same sheet layout, same
Slack thread — only these four things differ per office.

NOT LucyEco. ApplicantStream is read with Lucy's own 'Lucy Reports' login,
which already sees every org office (Daily EOD AppStream and Second Rounds
Tomorrow read them all daily). Going through each ICD's machine would mean an
AppStream login per office and their computer awake at 5pm, for nothing more.

Adding an office: one entry below. `sheet` stays "" until their live Daily
Update link is in — a run with no sheet still previews and can post to Slack,
but --write refuses. Their sheet must carry Raf's headers (layout.REQUIRED);
the first run against it fails loudly if it doesn't.

Raf's own scheduled run (5pm CT on Lucy 2, deploy/raf_daily_update.sh) reads
the "raf" entry through automations.raf_daily_update.run and does not move.
Every other office runs through automations.raf_daily_update.offices_run
(schedule id daily_update_offices), which names no machine, so a build/fix
rerun goes to the least-loaded Lucy (day_orchestrator/routing.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

#: #org-indeed-accounts — where every office's test posts go until its go.
TEST_CHANNEL = "C0BH637AM8F"


@dataclass(frozen=True)
class Office:
    key: str
    office_id: str             # ApplicantStream office id
    owner: str
    channel: str = ""          # the office's own recruiting channel
    sheet: str = ""            # their live Daily Update sheet ("" = no link yet)
    test_sheet: str = ""       # a copy to write while testing
    test_channel: str = TEST_CHANNEL
    # One fixed tab name ('Daily Update'), or "" for a tab per month the way
    # Raf's sheet has them ('October -2026').
    tab: str = ""
    # Who Lucy asks to tag a leader she can't: {name: Slack id}
    tag_helpers: Dict[str, str] = field(default_factory=dict)
    # Where the 5pm run posts (deploy/raf_daily_update.sh), shown on the Hub
    # card: True = the office's own `channel`, False = `test_channel`.
    posts_in_own_channel: bool = False


OFFICES: Dict[str, Office] = {
    "raf": Office(
        key="raf", office_id="11280", owner="Rafael Hidalgo",
        channel="C0AUAS88FGW",                   # #rafs-office-recruiting-11280
        sheet="1hMdhHAFjFX9QJnXkFzH216Ti6aPbrmiO8DjUU1gaTnw",
        test_sheet="1qFChT5PX2AU8Yu-0QmpZswV6zfhhi4u_72BWyiMPcZY",
        tag_helpers={"Aisha Ceron": "U083X5ZJWSH",
                     "Rafael Hidalgo": "U045Z8N0ZQC"}),
    # SLACK POST ONLY (Megan 2026-10-26). His sheet is filled by
    # automations/omar_daily_update (Eve) — one writer per sheet — so no
    # `sheet` here: this entry only posts the Daily Update thread (picture +
    # leader tags) in his recruiting channel.
    "omar": Office(
        # AppStream 24153 was Raf's funnel, closed by eStream 2026-11-04 ("Cancel
        # Rafs funnel - 24153"); Omar's own office is 24232 (call list moved
        # 10/30). OwnerVille is still 24153 — that is a different system.
        key="omar", office_id="24232", owner="Omar Mohamad",
        # C0C6HKZ63EK (the 24153 room) was renamed #old-omar-dont-use on
        # 2026-11-06; his live room came with the 24232 move.
        channel="C0CEZ64FYM6",   # #24232-kalkan-marketing-inc-omar-mohamad
        posts_in_own_channel=True,   # Megan 2026-10-26: post in his channel
        tag_helpers={"Omar Mohamad": "U0C144X8SBD"}),   # not look-alike U0A0J2T9XKL
    # THE OTHER THREE 2R OWNERS (2026-11-19). The 6pm BOB nudge already runs
    # for all five offices on the `2R Contacts` roster; these three were the
    # ones with no Daily Update of their own, so the day they are nudged about
    # was never written up anywhere. Same report, same layout.
    #
    # NO `channel` AND NO `sheet` YET, on purpose. Every office before them
    # started by posting into #org-indeed-accounts and writing nothing
    # (posts_in_own_channel=False, sheet=""), so the first runs can be read
    # before they reach an owner's room -- Raf's own entry still carries its
    # test sheet for the same reason. Their live link and room go in when
    # Megan gives each office its go; --write refuses until `sheet` is set.
    "algemar": Office(
        # Office 23965 "Algemar Kennel El Paso" -- Raf's funnel renamed
        # (Maud, 2026-11-10). El Paso is MOUNTAIN, but the roster records
        # America/Chicago and that is what the nudge uses; the Daily Update
        # does not read a timezone, so the two cannot disagree here.
        key="algemar", office_id="23965", owner="Algemar Kennel",
        tag_helpers={"Algemar Kennel": "U09MXMU76MB"}),
    "cyrus": Office(
        # Reception from Maud (#l10-alphalete 2026-11-13); token authorized by
        # Eve the same day. Cyrus is the one of the three who already has an
        # ECO office (`cyrus`), so his Slack id comes from the owner list
        # rather than the roster, where his cell is blank.
        key="cyrus", office_id="22815", owner="Cyrus Wade",
        tag_helpers={"Cyrus Wade": "U06A1QA642X"}),
    "vincent": Office(
        # 24290, NOT 24332 (Megan, 2026-11-18: "24290 is Vincent's AppStream").
        # 24332 came from Maud 11/13 and read back zero second-interview rows,
        # which is how the wrong id was caught. Access was granted on 24332, so
        # a first run here is also the check that Lucy can see 24290 at all.
        key="vincent", office_id="24290", owner="Vincent Dodson",
        tag_helpers={"Vincent Dodson": "U09K1SXDZK2"}),
}


def get(key_or_id: str) -> Office:
    """An office by key ('raf') or ApplicantStream id ('11280'). An id that is
    not listed yet gives a bare office — enough for a dry-run preview of any
    org office, nothing to write to or post in."""
    k = str(key_or_id or "").strip()
    if k.lower() in OFFICES:
        return OFFICES[k.lower()]
    for o in OFFICES.values():
        if o.office_id == k:
            return o
    if k.isdigit():
        return Office(key=k, office_id=k, owner="")
    raise KeyError(f"unknown office {k!r} — known: {', '.join(OFFICES)} "
                   "(or pass an ApplicantStream office id to preview it)")
