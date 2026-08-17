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

THE CONTROL IS A DROPDOWN NOW (2026-08-17)
------------------------------------------
"SCI removed the filters" (below, 2026-08-13) was wrong, and it cost days. On
8/17 Eve opened the view by hand and saw `Contract ID` reading **"Multiple
values"** — the filter is still there, it just renders as a COLLAPSED dropdown
instead of an expanded checkbox list, and a collapsed dropdown has no items in
the DOM at all until you open it. That is why the probe counted zero nodes
carrying the field name: it was looking for the items, and the items don't exist
yet. Hidden ≠ removed.

So the release now has two paths, tried in order:

  1. EXPANDED list — `_all_item`, the original path, one locator and done.
  2. COLLAPSED dropdown — find the field's combo box, open it, tick `(All)`
     inside the menu it renders, close it. Same keyboard trick as path 1: the
     menu item ignores mouse clicks and only flips on Space.

Finding the combo is the fiddly half, because the collapsed control carries the
VALUE ("Multiple values"), not the field name — the name lives in a separate
title element. We try, in order: an `id`/`aria-label` that names the field, then
the title text walked up to the nearest ancestor holding a combo box. When none
of them match, the log prints every combo it DID see with its title and value,
so the next run tells us what the DOM looks like instead of just "not found" —
the same lesson as `describe_filters`.
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


# --- collapsed dropdown ("Multiple values") -----------------------------------
# A quick filter shown as a dropdown renders NOTHING of its item list until it is
# opened, so every selector that looks for the items comes back empty and reads
# exactly like "the filter was removed". These are the pieces of the open/tick
# dance; see the module docstring for how 2026-08-13 got this wrong.

# Which part of a .tabComboBox opens the menu differs by Tableau build (label /
# name container / arrow button), so we try each — same finding as the b2b_metrics
# week dropdown, 2026-08-17.
_COMBO = ".tabComboBox"
_COMBO_OPENERS = (".tabComboBox", ".tabComboBoxButton", ".tabComboBoxName")
# The item list, spelled a few ways depending on whether the filter is a plain
# list or a searchable one.
_MENU_ITEMS = (".QFCheckbox", '[role="checkbox"]', ".tabMenuItemName",
               ".tabComboBoxMenuItem", '[role="option"]', '[role="menuitem"]',
               ".tabMenuItem")
# NOT a title source: `.tabComboBoxNameContainer` holds the VALUE ('(All)',
# '(Multiple values)'), which is why describe_filters' "quick-filter titles" line
# printed six values and no field name. The name comes from _combo_label.


def _text(loc, timeout_ms: int = 4_000) -> str:
    """Squashed inner_text, or '' — never raises. Tableau prefixes a checked item
    with a ✓ glyph, which is state, not name."""
    try:
        return " ".join((loc.inner_text(timeout=timeout_ms) or "").split()
                        ).lstrip("✓").strip()
    except Exception:                                       # noqa: BLE001
        return ""


def _is_all(text: str) -> bool:
    """Does this menu item name the '(All)' entry? Tableau writes '(All)'; some
    builds and locales drop the parens."""
    return text.strip().strip("()").casefold() == "all"


def _combo_label(viz, combo) -> str:
    """The FIELD name behind a collapsed dropdown, e.g. 'Filter Contract ID
    Inclusive (All)'.

    Probed against the live view 2026-08-17: the combo's own text is the VALUE
    ('(All)', '(Multiple values)') and nothing about it names the field, but
    Tableau points `aria-labelledby` at a label node that does. The grandparent's
    text carries the same sentence and is the fallback for a build that drops the
    attribute — those two are the only places the name appears at all.
    """
    try:
        lab = combo.get_attribute("aria-labelledby")
    except Exception:                                       # noqa: BLE001
        lab = None
    if lab:
        # An id, not a class: match it exactly rather than through CSS escaping
        # (Tableau's ids carry dots and colons).
        got = _text(viz.locator('[id="{}"]'.format(lab)).first, timeout_ms=2_000)
        if got:
            return got
    return _text(combo.locator("xpath=../.."), timeout_ms=2_000)


def _field_combo(viz, field: str):
    """(locator, how) for `field`'s collapsed dropdown, or (None, reason).

    Two ways in, cheapest first. An ATTRIBUTE naming the field is unambiguous
    when it's there (older builds put it in the id). Otherwise we read each
    dropdown's label — see _combo_label — which is what the live view actually
    offers.
    """
    for sel in ('{}[id*="{}"]'.format(_COMBO, field),
                '[aria-label*="{}"]{}'.format(field, _COMBO),
                '{}[aria-label*="{}"]'.format(_COMBO, field)):
        try:
            loc = viz.locator(sel).first
            if loc.count():
                return loc, "attribute"
        except Exception:                                   # noqa: BLE001
            continue
    try:
        combos = viz.locator(_COMBO)
        for i in range(min(combos.count(), 25)):
            combo = combos.nth(i)
            if field.casefold() in _combo_label(viz, combo).casefold():
                return combo, "label"
    except Exception:                                       # noqa: BLE001
        pass
    return None, "no combo box carries or is labelled {!r}".format(field)


def _describe_combos(viz, limit: int = 12) -> str:
    """Every dropdown on the view as 'title=value', for the log. A release that
    can't find its field must say what it DID see, or the next run is another
    round of guessing."""
    out = []
    try:
        combos = viz.locator(_COMBO)
        for i in range(min(combos.count(), limit)):
            combo = combos.nth(i)
            out.append("{}={!r}".format(
                _combo_label(viz, combo) or "?", _text(combo)))
    except Exception as exc:                                # noqa: BLE001
        return "<combo probe failed: {!r}>".format(exc)
    return " | ".join(out) or "(no dropdowns)"


def _release_dropdown(page, viz, field: str, verbose: bool,
                      settle_ms: int = 15_000) -> str:
    """Open `field`'s dropdown and tick '(All)'.

    Returns one of:
      'released' — it now reads (All), the export is uncapped for this field
      'stuck'    — the dropdown IS on the view but wouldn't go to (All): a real
                   problem, worth the retry pass
      'absent'   — no dropdown for this field, so this isn't the control shape
                   in play and the caller should keep looking

    Fail-soft like everything else here: any step that doesn't work logs what it
    saw, and the caller's send gate still refuses to ship a capped pull."""
    combo, how = _field_combo(viz, field)
    if combo is None:
        if verbose:
            print("  -> BOX filter {!r}: no dropdown either ({}). Saw: {}".format(
                field, how, _describe_combos(viz)), flush=True)
        return "absent"
    before = _text(combo)
    if _is_all(before):
        if verbose:
            print("  -> BOX filter {!r} dropdown already reads '(All)'".format(
                field), flush=True)
        return "released"
    if verbose:
        print("  -> BOX filter {!r} is a collapsed dropdown reading {!r} "
              "(found by {}) — opening it".format(field, before, how),
              flush=True)
    for opener in _COMBO_OPENERS:
        try:
            target = (combo if opener == _COMBO
                      else combo.locator(opener).first)
            if not target.count():
                continue
            try:
                target.click(timeout=15_000)
            except Exception:                               # noqa: BLE001
                target.focus()
                page.keyboard.press("Enter")
        except Exception:                                   # noqa: BLE001
            continue
        page.wait_for_timeout(2_500)
        for sel in _MENU_ITEMS:
            try:
                items = viz.locator(sel)
                n = min(items.count(), 300)
            except Exception:                               # noqa: BLE001
                continue
            for j in range(n):
                item = items.nth(j)
                if not _is_all(_text(item, timeout_ms=2_000)):
                    continue
                # Mouse clicks are swallowed by Tableau's click-capture overlay
                # on these items — verified 2026-08-07 against all four click
                # paths. Focus + Space is the only thing that flips them.
                try:
                    item.focus()
                    page.keyboard.press(" ")
                except Exception as exc:                    # noqa: BLE001
                    if verbose:
                        print("  ⚠ BOX filter {!r}: (All) found via {} but "
                              "wouldn't take the keypress ({!r})".format(
                                  field, sel, exc), flush=True)
                    continue
                # Un-pinning re-queries against every contract; give it room.
                page.wait_for_timeout(settle_ms)
                try:
                    page.keyboard.press("Escape")           # close the menu
                except Exception:                           # noqa: BLE001
                    pass
                now = _text(combo)
                ok = _is_all(now) or item.get_attribute("aria-checked") == "true"
                if verbose:
                    print("  -> BOX filter {!r} {} — dropdown now reads "
                          "{!r}".format(field,
                                        "released to (All)" if ok
                                        else "did NOT flip", now), flush=True)
                return "released" if ok else "stuck"
        if verbose:
            print("  -> BOX filter {!r}: {} opened no (All) item".format(
                field, opener), flush=True)
    try:
        page.keyboard.press("Escape")
    except Exception:                                       # noqa: BLE001
        pass
    if verbose:
        print("  ⚠ BOX filter {!r}: dropdown found but no '(All)' item in it — "
              "export stays capped to the saved ID list".format(field),
              flush=True)
    return "stuck"


def release_pinned_filters(page, viz, fields: Sequence = PINNED_ID_FILTERS,
                           verbose: bool = True,
                           hydrate_timeout_ms: int = 20_000) -> None:
    """Check '(All)' on each pinned categorical filter that isn't already on.

    Fail-SOFT on purpose: a filter we can't reach must not kill the whole
    report (Carlos's daily Slack post rides this same hook). The runners
    compare the export's newest sale date against today and REFUSE to
    email/post a clearly-capped pull (see should_block_send), so a regression
    here can't silently ship a third of the numbers.

    WAIT FOR HYDRATION (2026-08-12): the viz loads the filter panel async, and
    `_all_item(...).count()` reads 0 the instant it's called if the checkbox
    hasn't rendered yet. That made the release SILENTLY skip on a slow load —
    the 4:29pm re-pull that day capped at 8/4 with "no (All) item found" for
    both filters, exactly this race. So each field now waits for its (All)
    item to attach before concluding it's absent, and the whole pass retries
    once if any field couldn't be released.

    THE CONTROLS ARE GONE (2026-08-13): SCI removed both quick filters from the
    workbook. A probe found ZERO nodes carrying "Contract ID" or "Account Id" in
    their id — not an unchecked (All), not a collapsed panel, nothing — while the
    Start/End Date textareas in the same panel still drive fine. And the pull is
    healthy without them: that morning's team export reached Carlos's 2026-08-12
    sales, so whatever pinned the include list left with the controls.

    So "field not on this view" is now the EXPECTED case and says so plainly. It
    used to shout "the pull may be capped" and burn 80s retrying (2 fields x 2
    attempts x 20s) on every single pull — a warning that fired every run, on
    every view, for a control that no longer exists. A field that IS present but
    won't flip is still a real problem and still warns. The release stays wired
    up: if SCI ever re-adds the filters, it starts working again on its own.
    """
    unresolved = list(fields)
    for attempt in range(2):
        if not unresolved:
            break
        if attempt and verbose:
            print("  -> BOX filter release retry for {}".format(unresolved),
                  flush=True)
        still_pending = []
        for field in unresolved:
          try:
            box = _all_item(viz, field)
            # Give the async panel time to render before deciding it's missing.
            try:
                box.wait_for(state="attached", timeout=hydrate_timeout_ms)
            except Exception:
                pass
            if box.count() == 0:
                # No expanded (All). Before concluding anything, try the
                # COLLAPSED dropdown: it renders no items at all until opened,
                # which is what made 2026-08-13 read this as "SCI deleted the
                # control" when the filter was alive and capping the export.
                shape = _release_dropdown(page, viz, field, verbose)
                if shape == "released":
                    continue
                if shape == "stuck":
                    # The control IS there and we couldn't get it to (All) —
                    # a real cap, and worth the second pass.
                    still_pending.append(field)
                    continue
                # Still nothing. If NOTHING on the view carries the field name,
                # the filter really isn't here — nothing to release, don't retry.
                # If the field IS there but its (All) isn't, that's the 8/12
                # hydration race and worth another pass.
                present = viz.locator('[id*="{}"]'.format(field)).count()
                if not present:
                    if verbose:
                        print("  -> BOX filter {!r} not on this view — nothing "
                              "to release".format(field), flush=True)
                    continue
                if verbose:
                    print("  ⚠ BOX filter {!r}: {} node(s) but no (All) item "
                          "after {}s — the pull may be capped".format(
                              field, present, hydrate_timeout_ms // 1000),
                          flush=True)
                still_pending.append(field)
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
            if state != "true":
                still_pending.append(field)
                if verbose:
                    print("  ⚠ {!r} did NOT flip — export will be capped to "
                          "the view's saved ID list".format(field), flush=True)
          except Exception as exc:                          # noqa: BLE001
            still_pending.append(field)
            if verbose:
                print("  ⚠ BOX filter {!r} release failed ({!r}) — "
                      "continuing".format(field, exc), flush=True)
        unresolved = still_pending


def describe_filters(page, viz, limit: int = 25) -> str:
    """Dump what filter controls the loaded viz actually exposes.

    WHY (2026-08-13): both owner pulls capped again and the log said
    "no (All) item found after 20s" for BOTH fields on BOTH attempts. The
    2026-08-12 hardening added exactly that hydration wait, so 80s of waiting
    ruling the item absent is not a race — the node the selector describes is
    not in the DOM at all. Rather than guess at a new selector, this prints the
    ground truth: how many checkboxes the viz has, every id that ends in
    `_(All)` (whatever its field), and the quick-filter titles on the view.

    Read-only and defensive: every probe is wrapped, because the point is to
    come back with a description even when half the page is unexpected.
    """
    lines = ["--- filter probe ---"]

    def _try(label, fn):
        try:
            lines.append("{}: {}".format(label, fn()))
        except Exception as exc:                            # noqa: BLE001
            lines.append("{}: <probe failed: {!r}>".format(label, exc))

    _try("checkbox nodes", lambda: viz.locator('[role="checkbox"]').count())
    _try("nodes with id ending _(All)",
         lambda: viz.locator('[id$="_(All)"]').count())
    _try("date textareas",
         lambda: viz.locator('textarea[aria-label$="Date"]').count())

    def _all_ids():
        loc = viz.locator('[id$="_(All)"]')
        n = min(loc.count(), limit)
        return "\n" + "\n".join(
            "    {!r}".format(loc.nth(i).get_attribute("id")) for i in range(n)
        ) if n else "(none)"
    _try("ids ending _(All)", _all_ids)

    def _titles():
        # Tableau labels each quick filter's header with the field name; the
        # class has been stable across the SCI views we drive.
        loc = viz.locator(".tabComboBoxNameContainer, .fltrTitle, "
                          '[data-tb-test-id="filter-title"]')
        n = min(loc.count(), limit)
        return "\n" + "\n".join(
            "    {!r}".format((loc.nth(i).inner_text() or "").strip())
            for i in range(n)) if n else "(none)"
    _try("quick-filter titles", _titles)

    # Each pinned field, matched loosely: does ANY node carry the field name in
    # its id? If the field is present but has no _(All) child, the control is a
    # dropdown/search filter, not a checkbox list — a different release path.
    for field in PINNED_ID_FILTERS:
        _try("nodes with {!r} in id".format(field),
             (lambda f=field: viz.locator('[id*="{}"]'.format(f)).count()))

    # The 8/13 blind spot: a COLLAPSED dropdown has no items and no field name in
    # any id, so every probe above reads zero and the filter looks deleted. Its
    # value ("Multiple values") is right here and says otherwise.
    _try("dropdowns (title=value)", lambda: _describe_combos(viz))
    for field in PINNED_ID_FILTERS:
        _try("dropdown for {!r}".format(field),
             (lambda f=field: "{} ({})".format(
                 _text(_field_combo(viz, f)[0]) if _field_combo(viz, f)[0]
                 else "(not found)", _field_combo(viz, f)[1])))

    lines.append("--- end filter probe ---")
    return "\n".join(lines)


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
    return ("⚠ CAPPED PULL: newest sale is {} — {} days behind {}; the counts "
            "below UNDERSTATE reality. First thing to check is Contract ID / "
            "Account Id on the view — they must read '(All)', not 'Multiple "
            "values'.".format(newest, behind, today))


# The send/post gate is deliberately LOOSER than the warning above: a warning is
# cheap and should fire on any short pull (>2 days), but REFUSING to deliver is
# not — a false block means an owner gets no email that day. A real cap sits the
# frozen ID snapshot 5–8+ days behind; the widest legitimate gap is a weekend
# (Fri sale, Mon pull = 3 days). So block only at >= 4 days behind, which no
# normal week can reach but every genuine cap blows past.
BLOCK_SEND_MIN_DAYS_BEHIND = 4


def should_block_send(newest: Optional[dt.date],
                      today: Optional[dt.date] = None,
                      min_days_behind: int = BLOCK_SEND_MIN_DAYS_BEHIND) -> str:
    """Return a loud reason string when a pull is too capped to DELIVER, else ''.

    This is the safety net the 2026-08-07 fix lacked: `release_pinned_filters`
    is best-effort and can still miss on a bad viz load (Roshan, 2026-08-12 —
    the release found no '(All)' item and the pull capped to 8/4). When that
    happens the counts understate reality by a third or more, and the only prior
    guard (`--require-fresh`) fails OPEN on the later pass. Rather than email
    an owner numbers that are quietly wrong, the runners call this and skip the
    send, failing loudly instead. The Sheet still merges safely (it keeps its
    newer existing rows), so nothing good is lost — only the wrong email/post is
    suppressed until a clean pull lands.
    """
    today = today or dt.date.today()
    if newest is None:
        return ("CAPPED PULL: export has no dated sales at all — refusing to "
                "send. Check the Start/End Date and Contract ID / Account Id "
                "filters (must read '(All)').")
    behind = (today - newest).days
    if behind < min_days_behind:
        return ""
    # The dates can't name the cause (Eve 2026-08-17): a Contract ID include list
    # frozen on day X starves every owner from day X on, which reads exactly like
    # the feed dying. So send the reader to the filter, not to an inference.
    return ("CAPPED PULL: newest sale is {} — {} days behind {} — refusing to "
            "send numbers that would understate reality. Check Contract ID / "
            "Account Id on the view: they must read '(All)'. 'Multiple values' "
            "= re-pinned to a stale ID snapshot, and no newer sale can enter "
            "whatever dates we type (probe: run_owner --probe-filters). Re-run "
            "once a clean pull lands (newest within {} days).".format(
                newest, behind, today, min_days_behind - 1))


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
