"""Source-sheet config + shared helpers for the disconnect/cancel follow-up
tracker. Responses are logged into the source sheet's own feedback columns —
there is no separate tracking sheet."""
from __future__ import annotations

import datetime as dt
import re
from typing import List, Optional

# The daily-refreshed "AT&T Fiber Metrics Report".
SRC_ID = "1Xddk29xvB3LYp24KndVbijgTngUVSAuQ-r5tjh7uqO8"

# Where detected responses are logged: (tab, feedback-column header). A
# customer's response goes into the feedback cell of their most-recent matching
# row in whichever office tab they appear (Raf's captainship = Local Office +
# Raf's Captainship).
SOURCE_FEEDBACK_TABS = [
    ("Local Office - Daily Cancels", "Cancel Feedback"),
    ("Local Office - New Internet Disconnects", "Disconnects Feedback"),
    ("Raf's Captainship - Cancels Ongoing", "Cancels Feedback"),
    ("Raf's Captainship - New Internet Disconnects", "DISCONNECTS FEEDBACK"),
]

# Phone anchor — the source rows sometimes shift a column, so we locate the
# phone by shape rather than trusting the header position.
_PHONE = re.compile(r"\D*(\d{3})\D*(\d{3})\D*(\d{4})\D*$")


def norm_phone(s: str) -> str:
    """Any phone format -> +1XXXXXXXXXX (last 10 digits). '' if not a phone."""
    d = re.sub(r"\D", "", s or "")
    return f"+1{d[-10:]}" if len(d) >= 10 else ""


def _hidx(header: List[str], *names: str) -> Optional[int]:
    """Index of the first header cell matching any candidate name."""
    low = [h.strip().lower() for h in header]
    for n in names:
        t = n.strip().lower()
        if t in low:
            return low.index(t)
    return None


def parse_date(s: str, today: dt.date) -> Optional[dt.date]:
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:  # source sometimes drops the year (e.g. "7/11") -> assume current year
        return dt.datetime.strptime(f"{s}/{today.year}", "%m/%d/%Y").date()
    except ValueError:
        return None
