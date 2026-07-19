"""What each rep gets paid for, by week.

The BOX counterpart of `automations/rep_activations/aggregate.py`, which is
what the Fiber order log posts to Slack each morning. Same three buckets and
the same two tables (the just-closed pay week, and the running one), so a rep
who reads both reports reads them the same way.

The mapping from Fiber to BOX:

    Fiber                       BOX
    -----                       ---
    Active                  ->  Accepted by Supplier      (POSTED — pays)
    bucketed by             ->  bucketed by
      Activation Date             Accepted Date
    Cancelled/Disconnected  ->  Cancelled by Broker, Rejected, Dropped
    everything else         ->  Ready For Booking, Submitted to Supplier,
                                Verification, Incomplete  (PENDING)

Accepted Date is the bucketing date because Carlos said so directly (Slack,
2026-07-18): a sale pays in the week "it was accepted by the supplier". A deal
sold on the 17th and accepted on the 22nd pays the following week.

NOTE ON DOLLARS: this counts SALES, not money — same as the Fiber report. The
workbook's Rates / Commission Calculator tabs are Base Energy residential and
carry no BOX rate card, so there is nothing here to price a B2B energy deal
with. If a payout formula turns up (BF Tier x kWh x term, presumably), it
slots in on top of these counts.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence

# Statuses that mean "this one pays".
POSTED_STATUSES = ("Accepted by Supplier",)
# Statuses that mean "this one died".
CANCEL_STATUSES = ("Cancelled by Broker", "Rejected", "Dropped")


def week_bounds(today: dt.date):
    """(last_start, last_end, this_start, this_end) as Sun-Sat weeks.

    Same arithmetic as rep_activations.aggregate.week_bounds, so the two
    reports never disagree about which week is which.
    """
    days_since_sunday = (today.weekday() + 1) % 7      # Mon=0..Sun=6 -> Sun=0
    this_start = today - dt.timedelta(days=days_since_sunday)
    this_end = this_start + dt.timedelta(days=6)
    last_start = this_start - dt.timedelta(days=7)
    last_end = this_start - dt.timedelta(days=1)
    return last_start, last_end, this_start, this_end


def label(start: dt.date, end: dt.date) -> str:
    """'7.12 - 7.18' — built by hand, no %-m/%-d (they die on Windows)."""
    return "{}.{} - {}.{}".format(start.month, start.day, end.month, end.day)


def _in_week(d: Optional[dt.date], start: dt.date, end: dt.date) -> bool:
    return d is not None and start <= d <= end


def build_week_tables(sales: Sequence, today: Optional[dt.date] = None) -> Dict:
    """Roll the collapsed sales into the two weekly payout tables.

    Returns {"last": {"label", "rows"}, "this": {"label", "rows"}} where each
    row is {"rep", "posted", "pending", "total", "canceled"}, sorted by total
    descending with the rep name as tiebreak.

    Pending is a single pool shown identically in both tables — a deal that
    hasn't been accepted has no payout week yet, so pinning it to one would be
    inventing information. Fiber does the same.
    """
    today = today or dt.date.today()
    last_start, last_end, this_start, this_end = week_bounds(today)

    reps: Dict[str, Dict[str, int]] = {}
    for s in sales:
        rep = (s.fields.get("Rep Name") or "").strip()
        if not rep:
            continue
        agg = reps.setdefault(rep, {
            "pending": 0, "posted_last": 0, "posted_this": 0,
            "canceled_last": 0, "canceled_this": 0,
        })
        # Accepted Date for a paid sale; for a dead one fall back to the sale
        # date so a cancel still lands in a week rather than vanishing.
        paid_on = s.accepted_date
        dead_on = s.accepted_date or s.sale_date

        if s.status in POSTED_STATUSES:
            if _in_week(paid_on, last_start, last_end):
                agg["posted_last"] += 1
            if _in_week(paid_on, this_start, this_end):
                agg["posted_this"] += 1
        elif s.status in CANCEL_STATUSES:
            if _in_week(dead_on, last_start, last_end):
                agg["canceled_last"] += 1
            if _in_week(dead_on, this_start, this_end):
                agg["canceled_this"] += 1
        elif s.status:
            agg["pending"] += 1

    def make_rows(posted_key: str, canceled_key: str) -> List[Dict]:
        rows = []
        for rep, a in reps.items():
            posted = a[posted_key]
            pending = a["pending"]
            rows.append({"rep": rep, "posted": posted, "pending": pending,
                         "total": posted + pending,
                         "canceled": a[canceled_key]})
        rows.sort(key=lambda r: (-r["total"], r["rep"].lower()))
        return rows

    return {
        "last": {"label": label(last_start, last_end),
                 "rows": make_rows("posted_last", "canceled_last")},
        "this": {"label": label(this_start, this_end),
                 "rows": make_rows("posted_this", "canceled_this")},
    }


def by_week_matrix(sales: Sequence):
    """Reps x weeks grid of PAID sales, for the workbook's payout tab.

    Buckets on the week the supplier ACCEPTED the sale — deliberately NOT
    `Sale.week_ending`, which is the week it was sold and is what the log is
    grouped by. The two answer different questions and conflating them is
    exactly what produced a bogus 41-sale week (see clean.py).

    Returns (reps, weeks, {(rep, week): paid}, {rep: pending}), reps ordered
    busiest-first and weeks newest-first.
    """
    posted: Dict[tuple, int] = {}
    pending: Dict[str, int] = {}
    totals: Dict[str, int] = {}
    weeks = set()
    for s in sales:
        rep = (s.fields.get("Rep Name") or "").strip()
        if not rep:
            continue
        totals.setdefault(rep, 0)
        pending.setdefault(rep, 0)
        if s.status in POSTED_STATUSES and s.accepted_date:
            import automations.box_order_log.clean as _clean
            wk = _clean.week_ending(s.accepted_date)
            weeks.add(wk)
            key = (rep, wk)
            posted[key] = posted.get(key, 0) + 1
            totals[rep] += 1
        elif s.status not in CANCEL_STATUSES and s.status:
            pending[rep] += 1
    reps = sorted(totals, key=lambda r: (-totals[r], r.lower()))
    return reps, sorted(weeks, reverse=True), posted, pending
