"""Text bundles: several morning texts sent as ONE PDF (Carlos 2026-11-27).

    "can all of these be posted in one pdf file? in the morning. NDS Tracker,
     today's 1st/2nd-round schedule, Customer Churn and Revenue Board, 2nd
     rounds and new starts by leader"            -> "morning", both chains, 7:30
    "Lets post these all at once in one PDF file as well: AT&T and Verizon
     Week 1s, AT&T teams week so far, AT&T and Verizon Weeks 1-4"
                                                 -> "weeks", A Players only, 11:30

HOW: each report still builds on its own clock, but its text route points at a
bundle token ("BUNDLE:<bundle>:<part>") instead of a chat. text_post sees the
token and DROPS the picture/text into today's bundle folder on Lucy 2
(store.py) instead of texting. The bundle's own agent (run.py, launchd
com.alphalete.text-bundles) stitches what arrived into one PDF at its tick and
queues ONE text per chat through the normal text outbox. A part that is still
missing makes the early ticks wait; the FINAL tick sends whatever is there. A
part that lands after the bundle went out is texted on its own (never lost).

To take a report back out of a bundle: put its chat(s) back in its route.
Python 3.9-safe (Lucy 2).
"""
from __future__ import annotations

from pathlib import Path

from automations.b2b_dispositions.config import TEXT_GROUP_ALL, TEXT_GROUP_ATT

ROOT = Path(__file__).resolve().parents[2] / "output" / "text_bundles"
PREFIX = "BUNDLE:"
TEXT_CAMPAIGN = "TEXT BUNDLES"          # b2b_dispositions.config.TEXT_ROUTES key

ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
MON_SAT = [0, 1, 2, 3, 4, 5]
MON_FRI = [0, 1, 2, 3, 4]


def token(bundle: str, part: str) -> str:
    return "%s%s:%s" % (PREFIX, bundle, part)


# parts: (part id, label, weekdays it is EXPECTED -- a missing expected part
# holds the early ticks; it is still included on any day it shows up).
# Order here = page order in the PDF.
BUNDLES = {
    "morning": {
        "label": "Morning Reports",
        "groups": [TEXT_GROUP_ALL, TEXT_GROUP_ATT],
        "weekdays": ALL_DAYS,
        "ticks": [(7, 30), (7, 45), (8, 0), (8, 30)],     # last = final
        "parts": [
            ("tracker", "NDS Tracker", ALL_DAYS),
            ("schedule", "Today's 1st/2nd-round schedule", MON_SAT),
            ("customer_churn", "NDS Customer Churn", ALL_DAYS),
            ("revenue_board", "NDS Revenue Board", ALL_DAYS),
            ("second_rounds", "2nd rounds & new starts by leader", MON_SAT),
        ],
    },
    "weeks": {
        "label": "Week Tables",
        "groups": [TEXT_GROUP_ALL],
        "weekdays": MON_FRI,
        "ticks": [(11, 35), (11, 45), (12, 0)],
        "parts": [
            ("nds_week1", "AT&T Week 1s", MON_FRI),
            ("vz_week1", "Verizon Week 1s", MON_FRI),
            # Built by run.py at send time (the NDS Sales Board's Teams box).
            ("teams", "AT&T teams, week so far", []),
            ("nds_weeks", "AT&T Weeks 1-4", MON_FRI),
            ("vz_weeks", "Verizon Weeks 1-4", MON_FRI),
        ],
    },
}


def kind(bundle: str) -> str:
    return "bundle_" + bundle


def late_kind(bundle: str) -> str:
    return "bundle_late_" + bundle
