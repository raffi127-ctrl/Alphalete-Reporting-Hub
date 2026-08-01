"""Force the BOX Order Log's date window at pull time.

Why this exists (2026-08-01): the Smart Circle source view
`B2BBOXEnergyTracker → BoxOrderLog` carries **Start Date / End Date** filter
controls, and their saved value drifts — on 2026-08-01 it was pinned to a
two-day window (7/20–7/21) for EVERY office (Carlos, Roshan, Ryan, Abel), so
the raw crosstab came back with almost nothing and the Slack workbook/PNG
showed just two reps. The Google Sheet survived only because it MERGES each
pull with its existing rows; the daily workbook + payout image are built off
the raw pull, so they mirrored the truncated feed.

We don't own that Tableau workbook and can't stop the filter from drifting, so
we adapt: every pull DRIVES the Start/End Date textareas to a wide window,
overriding whatever SCI has saved. Same mechanism as
`automations/uploaded/order_log._set_order_log_dates_sync` — the AT&T order
log already does this for the same reason.

The hook runs after the viz hydrates and on every retry (a re-navigation
resets the view to its saved range), so the dates are re-applied each attempt.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

# Pull comfortably wider than the report's rolling 6-week (42-day) window so the
# merge and the payout "last week & this week" always have full data, with room
# to spare. ~10 weeks matches the old "full pull" scope.
WINDOW_DAYS = 70


def default_window(today: Optional[dt.date] = None,
                   days: int = WINDOW_DAYS) -> Tuple[dt.date, dt.date]:
    """(start, end) window ending today, `days` back. End=today keeps today's
    sales (Carlos counts by sale date)."""
    today = today or dt.date.today()
    return today - dt.timedelta(days=days), today


def _fmt(d: dt.date) -> str:
    """Tableau's date textareas accept M/D/YYYY with no leading zeros."""
    return "{}/{}/{}".format(d.month, d.day, d.year)


def date_window_hook(start: dt.date, end: dt.date, verbose: bool = True):
    """Build a sync `pre_export(page, viz)` that pins the export to start→end.

    Passing this to download_crosstab_patchright also disables its same-day
    cache (cacheable = pre_export is None), which is what we want: never serve
    a cached truncated pull."""
    def _hook(page, viz) -> None:
        if verbose:
            print("-> Forcing BOX date range: {} → {}".format(
                _fmt(start), _fmt(end)), flush=True)
        for label, d in (("Start Date", start), ("End Date", end)):
            box = viz.locator('textarea[aria-label="{}"]'.format(label)).first
            box.wait_for(state="visible", timeout=15_000)
            # force=True bypasses Tableau's transparent click-capture overlay.
            box.click(force=True)
            box.fill(_fmt(d))
            box.press("Enter")
            page.wait_for_timeout(1200)
        # Let the viz recompute against the new window before the export reads it.
        page.wait_for_timeout(6000)
    return _hook
