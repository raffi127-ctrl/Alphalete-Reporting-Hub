"""Hand-recovered figures for weeks no PDF can supply.

LAST-RESORT fallback, consulted only after the week's own email AND the
following week's 'Previous Week Ending' column have both failed. Every entry
below must carry its provenance and must reconcile against
parse.check_consistency — a number typed in here with no source is worse than a
loud failure, because it looks automated.

Adding a week here is a repair, not a routine step. If entries start piling up,
the real fix is upstream: ask Adriana to keep attaching both PDFs.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, NamedTuple


class ByDay(NamedTuple):
    """The by-day half, in the shape parse.parse_byday returns."""
    values: Dict[str, int]        # tab row label -> units
    grand: int                    # that week's Grand Total, for the identity check
    extra: Dict[str, int]         # the ignored 'AT&T Wireless' / 'VZ Wireless' lump


# --- the 'Campaign Totals By Day' half -------------------------------------
BYDAYS: Dict[dt.date, ByDay] = {
    # WE 5.23.2026 sits inside the Apr-May outage: Adriana's last email from her
    # personal Gmail was WE 3.28 (2026-04-03) and nothing reached this inbox
    # again until 2026-06-12. Swept every IMAP folder (All Mail, Important,
    # Sent, Spam/Trash and the 'SCI Campaigns' folder) on five different
    # queries — no tracker mail exists for it.
    #
    # But WE 5.30's attachments DO restate it, and those survived as the two
    # inline JPGs on Rafael's 2026-06-12 forward ('Outlook-q4fzq0ey.jpg', the
    # by-day table). Read 2026-07-27 from its 'Previous Week Ending 5.23.26'
    # column. Reconciles exactly with the FOOTERS entry below: the 13 rows sum
    # to 33,746, which is what this Grand Total of 35,159 implies once the
    # VZ/AT&T Wireless lump is swapped for the footer's four-way split.
    dt.date(2026, 5, 23): ByDay(
        values={
            "AT&T Fiber": 5459,
            "Frontier Fiber": 3739,
            "DTV": 832,
            "Lumen Fiber": 1343,          # printed as 'Quantum Fiber'
            "Verizon FiOS Fiber": 3055,
            "B2B": 6904,                  # printed as 'AT&T B2B'
        },
        grand=35159,
        extra={"AT&T Wireless": 2807, "VZ Wireless": 3101},
    ),
}

# --- the RANKED PDF footer half: AT&T NDS + the four 'Selling … Wireless' rows
FOOTERS: Dict[dt.date, Dict[str, int]] = {
    # WE 5.30.2026 never reached alphaletereporting@gmail.com as an original —
    # Adriana sent it elsewhere and it arrived only as Rafael's 'Fwd:' of
    # 2026-06-12, where Gmail had rewritten both attachments to inline
    # 'Outlook-*.jpg' images with no PDFs. The FOLLOWING week (6.6) is no help
    # either: its email is missing the RANKED PDF entirely, so nothing in any
    # PDF states 5.30's wireless split.
    #
    # Read 2026-07-27 from the 6.6 RANKED JPG's 'Previous Week Ending 5.30.26'
    # column (attachment 'RANKED Residential Telecom Tracker W.E. 6.6.jpg',
    # footer block). Reconciles exactly: with the by-day half taken from the 6.6
    # by-day PDF's prior column, the 13 rows sum to 33,273, which is what that
    # PDF's Grand Total of 34,754 implies once the VZ/AT&T Wireless lump is
    # swapped for this split.
    dt.date(2026, 5, 30): {
        "AT&T NDS": 7723,
        "AT&T selling Wireless": 2341,
        "Frontier Selling Wireless": 892,
        "Verizion FiOS Selling Wireless": 1176,
        "Verizon 5G selling VZ Wireless": 9,
    },
    # WE 5.23.2026 — the other half of the BYDAYS entry above. Read from the
    # RANKED JPG on the same forward ('Outlook-0nbe3nzp.jpg'), footer block,
    # 'Previous Week Ending 5.23.26' column. See that entry for the reconcile.
    dt.date(2026, 5, 23): {
        "AT&T NDS": 7919,
        "AT&T selling Wireless": 2483,
        "Frontier Selling Wireless": 851,
        "Verizion FiOS Selling Wireless": 1155,
        "Verizon 5G selling VZ Wireless": 6,
    },
}
