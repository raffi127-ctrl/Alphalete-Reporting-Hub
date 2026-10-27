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
        key="omar", office_id="24153", owner="Omar Mohamad",
        channel="C0C6HKZ63EK",   # #omars-mohammad-office-recruiting-24153-rafael-hidalgo
        posts_in_own_channel=True,   # Megan 2026-10-26: post in his channel
        tag_helpers={"Omar Mohamad": "U0C144X8SBD"}),   # not look-alike U0A0J2T9XKL
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
