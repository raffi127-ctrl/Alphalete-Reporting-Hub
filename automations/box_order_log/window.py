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

SECOND DRIFTING CONTROL — the pinned ID filters (2026-08-07)
------------------------------------------------------------
Roshan reported her "accepted by supplier" count looked far too low (34 for the
week when her office had sold ~88). It was: the true count was 120. The cause
was NOT the dates — a probe confirmed the End Date textarea reads back
`8/7/2026` and the export still stopped at 7/30.

The view also carries **Contract ID** and **Account Id** categorical quick
filters whose saved state has `(All)` UNCHECKED, with tens of thousands of IDs
individually checked (44,356 checkbox nodes in the DOM on 2026-08-07). That
include-list is a frozen snapshot: every contract created after it was saved is
excluded, whatever date window we type. So the export's max Sale Date sat at
7/30 for eight straight days while Accepted Date kept advancing to 8/6 — the
same pinned contracts kept getting accepted, but no new sale ever entered.

So the hook now releases those two filters before setting the dates. Two
things make that fiddly and are load-bearing here:

  * The `(All)` item ignores mouse clicks — `.click()`, `.click(force=True)`,
    a click on the inner `<a>`, and `dispatch_event('click')` all leave
    aria-checked='false'. Only **focus + Space** flips it. (The date textareas
    need force=True for the same overlay; the checkboxes need the keyboard.)
  * We locate the item by its `id`, which embeds the field name, rather than
    walking the filter panels — enumerating a 44k-checkbox panel's inner_text
    is slow enough to matter on every pull.

Releasing the filters FIRST and setting the dates second is deliberate: the
saved range is narrow (7/20–7/21), so the expensive all-contracts requery runs
against a small window before we widen it.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional, Sequence, Tuple

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


# Categorical quick filters on the view whose saved include-lists pin the
# result set to a stale snapshot of IDs. Releasing them to (All) is what lets
# sales newer than that snapshot into the export at all. See the module
# docstring for how this was found.
PINNED_ID_FILTERS = ("Contract ID", "Account Id")


def _all_item(viz, field: str):
    """The '(All)' checkbox for one categorical filter.

    Matched on the DOM id, which embeds the field name, e.g.
        FI_federated.0brn…,none:<BOM>Contract ID:nk98096…_(All)
    Walking the filter panels instead means reading the inner_text of a panel
    holding tens of thousands of checkboxes on every single pull.
    """
    return viz.locator(
        '[role="checkbox"][id*="{}"][id$="_(All)"]'.format(field)).first


def release_pinned_filters(page, viz, fields: Sequence = PINNED_ID_FILTERS,
                           verbose: bool = True) -> None:
    """Check '(All)' on each pinned categorical filter that isn't already on.

    Fail-SOFT on purpose: a filter we can't reach must not kill the whole
    report (Carlos's daily Slack post rides this same hook). The runners
    compare the export's newest sale date against today and flag a short pull,
    so a silent regression here surfaces there instead of vanishing.
    """
    for field in fields:
        try:
            box = _all_item(viz, field)
            if box.count() == 0:
                if verbose:
                    print("  ⚠ BOX filter {!r}: no (All) item found — "
                          "the pull may be capped".format(field), flush=True)
                continue
            if box.get_attribute("aria-checked") == "true":
                if verbose:
                    print("  -> BOX filter {!r} already (All)".format(field),
                          flush=True)
                continue
            # Mouse clicks are swallowed by Tableau's click-capture overlay
            # here — even force=True. The keyboard is the only thing that
            # toggles it. Verified 2026-08-07 against all four click paths.
            box.focus()
            page.keyboard.press(" ")
            # Un-pinning re-queries against every contract; give it room.
            page.wait_for_timeout(15_000)
            state = box.get_attribute("aria-checked")
            if verbose:
                print("  -> BOX filter {!r} released to (All) "
                      "(aria-checked={!r})".format(field, state), flush=True)
            if state != "true" and verbose:
                print("  ⚠ {!r} did NOT flip — export will be capped to the "
                      "view's saved ID list".format(field), flush=True)
        except Exception as exc:                          # noqa: BLE001
            if verbose:
                print("  ⚠ BOX filter {!r} release failed ({!r}) — "
                      "continuing".format(field, exc), flush=True)


def capped_pull_warning(newest: Optional[dt.date],
                        today: Optional[dt.date] = None,
                        tolerance_days: int = 2) -> str:
    """A loud line when the export's newest sale date looks capped, else ''.

    This is the check that was missing on 2026-08-07: the pinned ID filters
    held max(Sale Date) at 7/30 for eight days and every run still looked
    healthy, because the only guard (`--require-fresh`) is designed to fail
    OPEN — the later pass ships regardless. A short pull now says so in the
    run output instead of quietly shipping a third of the real numbers.
    """
    today = today or dt.date.today()
    if newest is None:
        return ("⚠ CAPPED PULL: the export has no dated sales at all. "
                "Check the view's Start/End Date and the Contract ID / "
                "Account Id filters (they must read '(All)').")
    behind = (today - newest).days
    if behind <= tolerance_days:
        return ""
    return ("⚠ CAPPED PULL: newest sale is {} — {} days behind {}. The view's "
            "Contract ID / Account Id filters have probably re-pinned to a "
            "stale ID list (see window.py); the counts below UNDERSTATE "
            "reality.".format(newest, behind, today))


def date_window_hook(start: dt.date, end: dt.date, verbose: bool = True):
    """Build a sync `pre_export(page, viz)` that pins the export to start→end.

    Passing this to download_crosstab_patchright also disables its same-day
    cache (cacheable = pre_export is None), which is what we want: never serve
    a cached truncated pull."""
    def _hook(page, viz) -> None:
        # Release the pinned Contract ID / Account Id lists FIRST: the saved
        # date range is narrow, so the expensive all-contracts requery runs
        # against a small window before we widen it below.
        release_pinned_filters(page, viz, verbose=verbose)
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
