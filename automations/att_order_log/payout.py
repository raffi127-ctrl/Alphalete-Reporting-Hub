"""AT&T Activation-report overview — the two-week per-rep rollup (item #8).

The AT&T counterpart of box_order_log.payout (Megan 2026-07-20: "built off of
the box order log we made, he wants something similar for at&t"). Two tables —
the just-closed pay week and the running one — with one row per rep:

    Rep Name  |  Activated  |  Cancelled  |  Still Open

Mapping from BOX to AT&T (Carlos: an AT&T sale pays on its POSTED date):

    BOX                                   AT&T
    ---                                   ----
    Accepted by Supplier (accepted date)  Activated   (POSTED date)
    Cancelled by Broker/Rejected/Dropped  Cancelled   (Canceled/Disconnected)
    Still Open (not accepted, any week)   Still Open  (not POSTED, any week)

WEEK SCOPE, same caveat BOX carries: Activated and Cancelled are WEEK figures
(the posted-date week). Still Open is NOT a week figure — it's every one of that
rep's sales that hasn't posted yet, whatever week it was ordered, so it's
identical in both tables. A sale with no posted date has no pay week yet, so
pinning it to one would invent information.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Sequence

from .sheet import _parse_date

POSTED_DATE_COL = "spe.dtr Posted Date (copy)"      # activation date, preserved
CANCEL_STATUSES = ("canceled", "cancelled", "disconnected")


def week_bounds(today: dt.date):
    """(last_start, last_end, this_start, this_end) as Sun-Sat weeks — same
    arithmetic as box_order_log.payout so the two reports agree on the weeks."""
    days_since_sunday = (today.weekday() + 1) % 7
    this_start = today - dt.timedelta(days=days_since_sunday)
    this_end = this_start + dt.timedelta(days=6)
    last_start = this_start - dt.timedelta(days=7)
    last_end = this_start - dt.timedelta(days=1)
    return last_start, last_end, this_start, this_end


def label(start: dt.date, end: dt.date) -> str:
    return "{}.{} - {}.{}".format(start.month, start.day, end.month, end.day)


def _in_week(d: Optional[dt.date], start: dt.date, end: dt.date) -> bool:
    return d is not None and start <= d <= end


def build_week_tables(lines: Sequence[dict],
                      today: Optional[dt.date] = None) -> Dict:
    """Roll the AT&T sales into the two weekly tables.

    Returns {"last": {...}, "this": {...}}, each {"label", "rows", "totals"},
    rows = [{"rep", "activated", "canceled", "open"}] sorted by activated desc,
    rep as tiebreak.
    """
    today = today or dt.date.today()
    ls, le, ts, te = week_bounds(today)

    reps: Dict[str, Dict[str, int]] = {}
    for ln in lines:
        rep = str(ln.get("Rep", "") or "").strip()
        if not rep:
            continue
        agg = reps.setdefault(rep, {
            "open": 0, "act_last": 0, "act_this": 0,
            "can_last": 0, "can_this": 0})
        posted = _parse_date(ln.get(POSTED_DATE_COL))
        status = str(ln.get("DTR Status (enriched)", "")).strip().lower()
        cancelled = status in CANCEL_STATUSES

        if cancelled:
            # Cancelled counts in the week it posted (if it ever did); a sale
            # that never posted then cancelled has no pay week, so it drops out
            # of the week figures (it's also not "open" — it's dead).
            if _in_week(posted, ls, le):
                agg["can_last"] += 1
            elif _in_week(posted, ts, te):
                agg["can_this"] += 1
        elif posted is None:
            agg["open"] += 1                     # not posted, not dead = pending
        else:
            if _in_week(posted, ls, le):
                agg["act_last"] += 1
            elif _in_week(posted, ts, te):
                agg["act_this"] += 1

    def _table(start, end, act_key, can_key):
        rows = []
        for rep, a in reps.items():
            rows.append({"rep": rep, "activated": a[act_key],
                         "canceled": a[can_key], "open": a["open"]})
        rows.sort(key=lambda r: (-r["activated"], -r["open"], r["rep"].lower()))
        totals = {
            "activated": sum(r["activated"] for r in rows),
            "canceled": sum(r["canceled"] for r in rows),
            "open": sum(r["open"] for r in rows)}
        return {"label": label(start, end), "rows": rows, "totals": totals}

    return {"last": _table(ls, le, "act_last", "can_last"),
            "this": _table(ts, te, "act_this", "can_this")}
