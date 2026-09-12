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
# Broken out of PENDING as its own column (Carlos, 2026-08-25): "any of them
# that are labeled Submitted to Supplier go on there, and then, as long as it's
# not cancelled by broker, it would go under pending". So this is a SUBSET of
# `pending`, not a fourth bucket — a submitted deal is counted in both columns,
# on purpose. Read literally off the current status, which is what "labeled"
# means; the workbook's yellow SECTION is deliberately wider (it also holds
# Ready For Booking and an already-submitted Verification).
SUBMITTED_STATUSES = ("Submitted to Supplier",)


def week_bounds(today: dt.date):
    """(last_start, last_end, this_start, this_end) as MON-SUN weeks.

    Carlos 2026-09-13, BOX only. Was Sun-Sat (rep_activations' arithmetic);
    Mon-Sun makes LAST WEEK the exact window the week's DD pays on, so the
    revenue board reconciles against the paycheck feed line-for-line — the
    comparison that surfaced the TX-Grid-vs-New-Comp scale gap in the first
    place.
    """
    this_start = today - dt.timedelta(days=today.weekday())
    this_end = this_start + dt.timedelta(days=6)
    last_start = this_start - dt.timedelta(days=7)
    last_end = this_start - dt.timedelta(days=1)
    return last_start, last_end, this_start, this_end


def label(start: dt.date, end: dt.date) -> str:
    """'7.12 - 7.18' — built by hand, no %-m/%-d (they die on Windows)."""
    return "{}.{} - {}.{}".format(start.month, start.day, end.month, end.day)


def _in_week(d: Optional[dt.date], start: dt.date, end: dt.date) -> bool:
    return d is not None and start <= d <= end


def build_week_tables(sales: Sequence, today: Optional[dt.date] = None,
                      money_fn=None, bonus_fn=None) -> Dict:
    """Roll the collapsed sales into the two weekly payout tables.

    Returns {"last": {"label", "rows"}, "this": {"label", "rows"}} where each
    row is {"rep", "posted", "submitted", "pending", "total", "canceled"},
    sorted by total descending with the rep name as tiebreak.

    NOTE ON SCOPE — this bit confused Carlos on 2026-07-18 and the labels now
    say it outright. `posted` and `canceled` are WEEK figures. `pending` is
    NOT: it's every deal of that rep's still waiting on acceptance, whatever
    week it was sold, and it is identical in both tables. `submitted` is the
    same shape — an all-time slice of `pending`, identical in both tables. A deal that hasn't
    been accepted has no payout week yet, so pinning it to one would invent
    information. That's why there is no longer a "Total" column — summing a
    week figure with an all-time one produced a number that meant nothing.
    """
    today = today or dt.date.today()
    last_start, last_end, this_start, this_end = week_bounds(today)

    reps: Dict[str, Dict[str, int]] = {}
    for s in sales:
        rep = (s.fields.get("Rep Name") or "").strip()
        if not rep:
            continue
        # money_fn (Carlos 2026-09-13: "show me the revenue count") prices the
        # deal and each bucket sums DOLLARS instead of counting 1s. Same
        # buckets, same dates, same sort — only the unit changes, so the two
        # screenshots read as the same board in two currencies.
        unit = 1 if money_fn is None else money_fn(s)[0]
        agg = reps.setdefault(rep, {
            "pending": 0, "submitted": 0, "posted_last": 0, "posted_this": 0,
            "canceled_last": 0, "canceled_this": 0,
            "n_posted_last": 0, "n_posted_this": 0,
        })
        # Accepted Date for a paid sale; for a dead one fall back to the sale
        # date so a cancel still lands in a week rather than vanishing.
        paid_on = s.accepted_date
        dead_on = s.accepted_date or s.sale_date

        if s.status in POSTED_STATUSES:
            if _in_week(paid_on, last_start, last_end):
                agg["posted_last"] += unit
                agg["n_posted_last"] += 1
            if _in_week(paid_on, this_start, this_end):
                agg["posted_this"] += unit
                agg["n_posted_this"] += 1
        elif s.status in CANCEL_STATUSES:
            if _in_week(dead_on, last_start, last_end):
                agg["canceled_last"] += unit
            if _in_week(dead_on, this_start, this_end):
                agg["canceled_this"] += unit
        elif s.status:
            agg["pending"] += unit
            if s.status in SUBMITTED_STATUSES:
                agg["submitted"] += unit

    def make_rows(posted_key: str, canceled_key: str) -> List[Dict]:
        rows = []
        for rep, a in reps.items():
            posted = a[posted_key]
            if money_fn is not None:
                # THE WEEKLY VOLUME BONUS RIDES IN ACCEPTED $ (Carlos
                # 2026-09-13: "You know what the rep is qualifying for, so
                # can't you add it in there?"). Tier from that week's accepted
                # COUNT, bonus = rate x count, straight onto the week figure.
                # Still Open / Submitted get none — an unaccepted deal has no
                # tier yet. bonus_fn(week_end, n) picks the SCALE — the new
                # Texas payout starts with sales as of 9/7 (Carlos), so the
                # week that straddles the cutover pays on the right card.
                n = a["n_" + posted_key]
                week_end = (last_end if posted_key == "posted_last"
                            else this_end)
                if bonus_fn is not None:
                    posted += bonus_fn(week_end, n)
                else:
                    from automations.vantura_revenue_board.run import box_tier_for
                    _t, rate = box_tier_for(n)
                    posted += rate * n
            pending = a["pending"]
            rows.append({"rep": rep, "posted": posted, "pending": pending,
                         "submitted": a["submitted"],
                         "total": posted + pending,
                         "canceled": a[canceled_key]})
        # Rank by what actually pays that week. The old key was posted+pending,
        # which mixed a week figure with an all-time one.
        rows.sort(key=lambda r: (-r["posted"], -r["pending"], r["rep"].lower()))
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


def filter_active(tables: Dict, active, terminated, names_match) -> Dict:
    """Drop Terminated reps' ROWS; keep them in the TOTAL strip.

    Carlos 2026-09-13: "cross-reference only the active reps to be shown. I do
    still want the totals to include any reps that may no longer be around."
    Same terminated-driven rule as the activation board: hidden only on an
    explicit Terminated match with no Active row, because the roster has gaps
    and hiding an unmatched seller silently is worse than showing one who
    left. The all-rep sums land in table["totals"]; the renderer prefers them
    over summing the visible rows, which is exactly the asked-for behaviour.
    """
    hidden = set()
    for which in ("last", "this"):
        t = tables[which]
        t["totals"] = {k: sum(r[k] for r in t["rows"])
                       for k in ("posted", "submitted", "canceled", "pending")}
        kept = []
        for r in t["rows"]:
            if any(names_match(r["rep"], x) for x in terminated) and not any(
                    names_match(r["rep"], x) for x in active):
                hidden.add(r["rep"])
            else:
                kept.append(r)
        t["rows"] = kept
    tables["hidden"] = sorted(hidden)
    return tables
