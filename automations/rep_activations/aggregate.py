"""Aggregate the Order Log crosstab into a per-rep, per-pay-period summary.

Consumes the cleaned DataFrame produced by
``order_log._load_and_clean`` (FRIENDLY_HEADERS columns, dates already
parsed to datetime / NaT) and rolls it up into two Sun-Sat tables:

  * "last"  — the just-closed pay period (previous Sun-Sat). Posted = how
              many of a rep's orders ACTIVATED in that window.
  * "this"  — the running pay period (current Sun-Sat).

Per the report's definitions (confirmed with Megan):
  * Posted   = Status "Active", counted in the week its Activation Date
               falls in.
  * Pending  = the rep's live outstanding pipeline — every order NOT yet
               Active and NOT Cancelled/Disconnected. This is one pool,
               shown identically in BOTH tables (a pending sale rolls into
               whichever week it eventually activates).
  * Total    = Posted + Pending.
  * Canceled/Disconnected = Status Cancelled/Disconnected, bucketed by
               Activation Date if present else Install Date.

No hard-coded column positions — everything is looked up by the friendly
header label and status strings are normalized (strip + lowercase), so a
template/status tweak survives.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

# Status buckets (normalized: stripped + lowercased). "canceled" and
# "cancelled" are both accepted so a source-spelling change can't silently
# drop cancels.
POSTED_STATUSES = {"active"}
CANCEL_STATUSES = {"cancelled", "canceled", "disconnected"}
# Pending is defined as "a real order that is neither posted nor canceled",
# i.e. everything else with a non-blank status (Scheduled, Open, Shipped,
# Pending Shipment, Delivered, and any future status). Defining it by
# exclusion keeps the live-pipeline count robust to new status values.


def _norm_status(value) -> str:
    return str(value or "").strip().lower()


def _as_date(value) -> Optional[dt.date]:
    """Coerce a cell (Timestamp / datetime / NaT / str) to a date or None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def week_bounds(today: dt.date):
    """Return (last_start, last_end, this_start, this_end) as Sun-Sat weeks.

    ``this_start`` is the most recent Sunday on or before ``today``.
    """
    days_since_sunday = (today.weekday() + 1) % 7  # Mon=0..Sun=6 -> Sun=0
    this_start = today - dt.timedelta(days=days_since_sunday)
    this_end = this_start + dt.timedelta(days=6)
    last_start = this_start - dt.timedelta(days=7)
    last_end = this_start - dt.timedelta(days=1)
    return last_start, last_end, this_start, this_end


def _label(start: dt.date, end: dt.date) -> str:
    # Built manually (no %-m / %-d) so it renders the same on Windows + macOS.
    return f"{start.month}.{start.day} - {end.month}.{end.day}"


def _in_week(d: Optional[dt.date], start: dt.date, end: dt.date) -> bool:
    return d is not None and start <= d <= end


def build_week_tables(df: pd.DataFrame, today: dt.date) -> dict:
    """Roll the cleaned order DataFrame up into the two weekly tables.

    Returns ``{"last": {"label": str, "rows": [...]},
               "this": {"label": str, "rows": [...]}}`` where each row is
    ``{"rep", "posted", "pending", "total", "canceled"}``, sorted by total
    descending (rep name as the tiebreak).
    """
    last_start, last_end, this_start, this_end = week_bounds(today)

    reps: dict[str, dict] = {}
    for _, row in df.iterrows():
        rep = str(row.get("Rep", "")).strip()
        if not rep:
            continue
        status = _norm_status(row.get("Status"))
        act = _as_date(row.get("Activation Date"))
        inst = _as_date(row.get("Install Date"))
        cancel_bucket = act if act is not None else inst

        agg = reps.setdefault(rep, {
            "pending": 0, "posted_last": 0, "posted_this": 0,
            "canceled_last": 0, "canceled_this": 0,
        })

        if status in POSTED_STATUSES:
            if _in_week(act, last_start, last_end):
                agg["posted_last"] += 1
            if _in_week(act, this_start, this_end):
                agg["posted_this"] += 1
        elif status in CANCEL_STATUSES:
            if _in_week(cancel_bucket, last_start, last_end):
                agg["canceled_last"] += 1
            if _in_week(cancel_bucket, this_start, this_end):
                agg["canceled_this"] += 1
        elif status:
            agg["pending"] += 1

    def make_rows(posted_key: str, canceled_key: str) -> list[dict]:
        rows = []
        for rep, a in reps.items():
            posted = a[posted_key]
            pending = a["pending"]
            rows.append({
                "rep": rep,
                "posted": posted,
                "pending": pending,
                "total": posted + pending,
                "canceled": a[canceled_key],
            })
        rows.sort(key=lambda r: (-r["total"], r["rep"].lower()))
        return rows

    return {
        "last": {
            "label": _label(last_start, last_end),
            "rows": make_rows("posted_last", "canceled_last"),
        },
        "this": {
            "label": _label(this_start, this_end),
            "rows": make_rows("posted_this", "canceled_this"),
        },
    }
