"""The pending-orders worklist — every BOX deal still in flight.

One model, two surfaces. The workbook's "Pending Orders" tab (xlsx.py) and the
Pending Orders image posted to Slack (pending_png.py) both read this module, so
the two can never disagree about what counts as pending, which section a deal
sits in, or what its next step is. The logic lived inside xlsx.build until
2026-08-25, when Carlos asked for the same tab as a standalone screenshot
("can this be a separate screenshot that gets sent, we can call it pending
orders") — copying it would have been two rules to keep in sync.

"Pending" is exactly the payout image's "Still Open": the status is neither
Accepted by Supplier nor a terminal cancel/reject/drop.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence, Tuple

from . import clean, payout

# Column order for both surfaces. Widths differ (Excel points vs pixels) but
# the columns themselves are defined once, here.
COLUMNS: Tuple[str, ...] = ("Rep Name", "Sale Date", "Days Waiting",
                            "Business Name", "Contract ID", "Status",
                            "Next step")

TITLE = "Pending orders — not yet accepted"


def is_pending(sale) -> bool:
    return (sale.status
            and sale.status not in payout.POSTED_STATUSES
            and sale.status not in payout.CANCEL_STATUSES)


def next_step(s) -> str:
    """Plain, action-focused — what has to happen next, no color-speak."""
    submitted = any(h.startswith(clean.SUBMITTED) for h in s.history)
    if s.status == "Ready For Booking":
        return "Send the bill copy / ETF document"
    if s.status == "Incomplete":
        return "Fix the missing contract data"
    if s.status == clean.SUBMITTED:
        return "Waiting on the supplier — nothing for us to do"
    if s.status == "Verification":
        return ("Waiting on the supplier" if submitted
                else "Submit a bill or ETF document")
    return clean.STATUS_MEANING.get(s.status, "")


def is_yellow(s) -> bool:
    """Whether this deal sits in the YELLOW half of the worklist.

    "Yellow" is whatever color_for() actually PAINTS yellow, not a status name:
    Submitted to Supplier, Ready For Booking (yellow since 2026-08-20), and a
    Verification sale whose HISTORY shows it was already submitted (an
    un-submitted Verification is orange, so it stays in the first section).
    Reading the paint is the point — recolor a status in clean.py and it moves
    sections on its own, with no second rule to keep in sync.
    """
    return clean.color_for(s.status, s.history) == clean.YELLOW


def _rep_of(s) -> str:
    return (s.fields.get("Rep Name") or "").strip() or "(no rep)"


def by_rep(rows: Sequence) -> List[Tuple[str, List]]:
    """[(rep, sales)] — reps A-Z, oldest deal first inside each rep.

    Oldest first because this is a chase list: within a rep's block the stalest
    deal is the one that most needs a call.
    """
    groups: Dict[str, List] = {}
    for s in rows:
        groups.setdefault(_rep_of(s), []).append(s)
    for rep in groups:
        groups[rep].sort(key=lambda s: (s.sale_date or dt.date.max,
                                        (s.fields.get("Business Name") or "").strip()))
    return [(rep, groups[rep]) for rep in sorted(groups)]


def plural(n: int) -> str:
    return "" if n == 1 else "s"


def days_waiting(s, today: dt.date):
    return (today - s.sale_date).days if s.sale_date else ""


def row_values(s, today: dt.date) -> List:
    """The seven cells for one pending deal, in COLUMNS order.

    Sale Date comes back as a `date` — Excel wants the real value so its own
    number format applies; the PNG formats it on the way out.
    """
    return [(s.fields.get("Rep Name") or "").strip(),
            s.sale_date or "",
            days_waiting(s, today),
            (s.fields.get("Business Name") or "").strip(),
            (s.fields.get("Contract ID") or "").strip(),
            s.status,
            next_step(s)]


def subtitle(count: int, today: dt.date) -> str:
    return ("Every deal still in flight (cancelled and rejected are excluded). "
            "{} as of {}. Two sections, each by sales rep: what we still have "
            "to work first, then the yellow ones sitting with the "
            "supplier.".format(
                "{} pending".format(count) if count else "none pending",
                today.strftime("%m/%d/%Y")))


def subtitle_no_yellow(count: int, today: dt.date) -> str:
    """Subtitle for the yellow-less view. Says the yellow ones were LEFT OUT
    rather than just omitting them — otherwise a shorter list reads as deals
    having gone missing."""
    return ("Deals still in flight that need something from us, by sales rep. "
            "{} as of {}. The ones waiting on the supplier (yellow) are not "
            "shown — they are on the Pending Orders tab of the workbook.".format(
                "{} order{}".format(count, plural(count)) if count
                else "none right now",
                today.strftime("%m/%d/%Y")))


def build(sales: Sequence, today: Optional[dt.date] = None, *,
          skip_yellow: bool = False) -> Dict:
    """The whole worklist, ready to lay out.

    Returns {"today", "count", "subtitle", "sections": [section, ...]} where a
    section is {"title", "rows", "reps", "empty_note"}. Both sections are
    always present, even when empty — an empty half is information ("no yellow
    deal is open"), and dropping it would make the image look truncated.

    `skip_yellow` drops the yellow half entirely: one section, no banner (with
    nothing to separate it from, a bar reading "NOT YELLOW" over a board with
    no yellow on it is just confusing), and `count` counts only what is shown.
    That's the SLACK IMAGE (Carlos, 2026-08-26: "can we have it so the
    screenshot doesn't show the orders in yellow"). The workbook tab keeps both
    halves — it's the full record, and he asked about the screenshot.
    """
    today = today or dt.date.today()
    pend = [s for s in sales if is_pending(s)]

    not_yellow, yellow = [], []
    for s in pend:
        (yellow if is_yellow(s) else not_yellow).append(s)

    if skip_yellow:
        return {"today": today, "count": len(not_yellow),
                "subtitle": subtitle_no_yellow(len(not_yellow), today),
                "sections": [
                    {"key": "not_yellow",
                     "title": None,
                     "rows": not_yellow,
                     "reps": by_rep(not_yellow),
                     "empty_note": "Nothing needs work right now — every open "
                                   "deal is with the supplier."}]}

    # Banners name the COLOR, not who has the ball. They used to say "ours to
    # work" / "waiting on the supplier", which stopped being true on 2026-08-20
    # when Ready For Booking turned yellow: that one still needs a document
    # from us but now sits in the yellow half. The per-row "Next step" column
    # carries the meaning instead.
    sections = [
        {"key": "not_yellow",
         "title": "NOT YELLOW  •  {} order{}".format(len(not_yellow),
                                                     plural(len(not_yellow))),
         "rows": not_yellow,
         "reps": by_rep(not_yellow),
         "empty_note": "Nothing here — every open deal is yellow."},
        {"key": "yellow",
         "title": "YELLOW  •  {} order{}".format(len(yellow),
                                                 plural(len(yellow))),
         "rows": yellow,
         "reps": by_rep(yellow),
         "empty_note": "Nothing here — no yellow deal is open."},
    ]
    return {"today": today, "count": len(pend),
            "subtitle": subtitle(len(pend), today), "sections": sections}
