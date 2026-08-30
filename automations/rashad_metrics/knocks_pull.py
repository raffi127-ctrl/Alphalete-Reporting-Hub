"""Pull a SPECIFIC office's daily 'knocks' data (Disposition by Rep + Time
Tracker gaps) from ownerville — the EXACT same scrape Raf's Total Knocks
report uses, but for an arbitrary office reached via IMPERSONATION first.

Raf's pull (automations.total_knocks.pull) scrapes whatever office the
ownerville session is currently on — Raf is the master/default office, so
it never switches. This module does the same scrape, but inside the single
ownerville_session it first IMPERSONATES the target office (default:
Rashad Reed), scrapes, then EXITS impersonation before the session closes.

EVERYTHING that does the actual scraping is IMPORTED from
total_knocks.pull (no copy-paste): _navigate / _header_index /
_scrape_rows / _scrape_time_tracker, the SHEET_COLUMNS/COL_* constants,
and the same badge-ID gap merge that pull_disposition_day does. The ONLY
thing added here is the impersonate-by-name wrapper, which is itself
imported from focus_office_att.run_all_owners so the office-switching
logic stays in one place.

Office is env-targetable (same pattern as the churn module's
CHURN_NI_VIEW_URL etc.):
    RASHAD_KNOCKS_OFFICE   default "Rashad Reed"
Name-spelling drift is resolved through the canonical ICD alias list.

Run standalone to preview a day's scrape WITHOUT touching any Sheet:
    python -m automations.rashad_metrics.knocks_pull            # yesterday
    python -m automations.rashad_metrics.knocks_pull 2026-06-27 # a date
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from typing import Optional

from automations.shared.tableau_patchright import ownerville_session

# Impersonate-by-name machinery — imported, NOT duplicated. These are the
# same helpers run_all_owners uses to switch ownerville to one owner's
# office and back to master.
from automations.focus_office_att.aliases import (
    alias_to_canonical,
    load_aliases,
)
from automations.focus_office_att.run_all_owners import (
    _navigate_to_office_access,
    _find_owner_and_impersonate,
    _exit_impersonation,
)
from automations.focus_office_att.step5_fill_one_owner import page_rqst

# Scrape primitives + canonical columns — imported from Raf's pull so this
# report and Raf's stay byte-for-byte identical on the scrape itself.
from automations.total_knocks import pull as knocks
from automations.total_knocks.pull import (
    COL_ID,
    COL_GAPS,
    COL_TOTAL_GAPS,
    KnocksPullFailed,  # re-exported: callers catch it without importing both
    SHEET_COLUMNS,  # re-exported for callers (Sheet column order)
)

# The WIRELESS (NDS) Disposition by Rep table has a different shape from the
# house one: one "Not Interested" bucket (no Talk-To/Presentation split), no
# Sale column, plus wireless-only columns we don't board (battery, coverage,
# device, territory name, tm version, vl, total hours, total scheduled).
# Discovered live 2026-08-22 (Isaiah Revelle): the house scrape raised
# "missing expected column(s)" and the live-headers diagnostic showed this set.
_WIRELESS_COLUMNS = [
    knocks.COL_ID, knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED,
    knocks.COL_TOTAL_KNOCKS, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_COME_BACK,
    knocks.COL_INACCESSIBLE, knocks.COL_DO_NOT_KNOCK,
]
_WIRELESS_COUNTS = {
    knocks.COL_TOTAL_LEADS_KNOCKED, knocks.COL_TOTAL_KNOCKS,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_COME_BACK,
    knocks.COL_INACCESSIBLE, knocks.COL_DO_NOT_KNOCK,
}


# Energy Wells: the wireless columns plus Presentation and VL. Ordered so the
# board reads knocks -> outcomes, the same left-to-right as the others.
_ENERGYWELL_COLUMNS = [
    knocks.COL_ID, knocks.COL_REP, knocks.COL_TOTAL_LEADS_KNOCKED,
    knocks.COL_TOTAL_KNOCKS, knocks.COL_FIRST_KNOCK, knocks.COL_LAST_KNOCK,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_PRESENTATION,
    knocks.COL_COME_BACK, knocks.COL_VL, knocks.COL_INACCESSIBLE,
    knocks.COL_DO_NOT_KNOCK,
]
_ENERGYWELL_COUNTS = {
    knocks.COL_TOTAL_LEADS_KNOCKED, knocks.COL_TOTAL_KNOCKS,
    knocks.COL_NO_ANSWER, knocks.COL_NOT_INTERESTED, knocks.COL_PRESENTATION,
    knocks.COL_COME_BACK, knocks.COL_VL, knocks.COL_INACCESSIBLE,
    knocks.COL_DO_NOT_KNOCK,
}
# Talk-to = everything except No answer and Inaccessible — nobody was spoken to
# in those. The SAME rule fiber uses (Do Not Knock counts), with VL added per
# Raf. Fiber's TALK_TO_PARTS is shared by every fiber board and must not gain
# VL, so Energy Wells carries its own list.
_ENERGYWELL_TALK_TO_PARTS = [
    knocks.COL_NOT_INTERESTED, knocks.COL_PRESENTATION, knocks.COL_COME_BACK,
    knocks.COL_VL, knocks.COL_DO_NOT_KNOCK,
]


def _is_energywell_dispo(idx: dict) -> bool:
    """Energy-Wells-shaped Disposition: the VL column is the signature — no
    other campaign's grid carries it. Checked BEFORE the wireless test, which
    this shape would otherwise satisfy (it has no Talk-To split either)."""
    return (knocks._norm(knocks.COL_TOTAL_KNOCKS) in idx
            and knocks._norm(knocks.COL_VL) in idx)


def _scrape_energywell_rows(page, idx: dict) -> list[dict]:
    """Energy Wells rows, keyed by _ENERGYWELL_COLUMNS, with Total Talk to
    computed over _ENERGYWELL_TALK_TO_PARTS. Same pagination walk as the
    wireless scrape."""
    rows = _scrape_shaped_rows(page, idx, _ENERGYWELL_COLUMNS,
                               _ENERGYWELL_COUNTS, "Energy Wells")
    for rec in rows:
        rec[knocks.COL_TOTAL_TALK_TO] = sum(
            int(rec.get(c) or 0) for c in _ENERGYWELL_TALK_TO_PARTS)
    return rows


def _is_wireless_dispo(idx: dict) -> bool:
    """Wireless-shaped Disposition: has Total Knocks but not the house
    Talk-To split — the signature that separates the two table shapes."""
    return (knocks._norm(knocks.COL_TOTAL_KNOCKS) in idx
            and knocks._norm(knocks.COL_TALK_TO_NI) not in idx)


def _scrape_wireless_rows(page, idx: dict) -> list[dict]:
    """Walk the DataTables pages of a WIRELESS-shaped Disposition table and
    return one dict per rep keyed by _WIRELESS_COLUMNS. Same pagination walk
    as the house _scrape_rows, minus the Talk-To calculation."""
    return _scrape_shaped_rows(page, idx, _WIRELESS_COLUMNS, _WIRELESS_COUNTS,
                               "Wireless")


def _scrape_shaped_rows(page, idx: dict, columns: list, counts: set,
                        label: str) -> list[dict]:
    """The DataTables walk, for any campaign's column set.

    Was the wireless-only scrape; Energy Wells needed the identical walk over a
    different column list, and a second copy of a pagination loop is how the
    two drift. `label` only names the shape in errors.
    """
    want = {c: idx.get(knocks._norm(c)) for c in columns}
    missing = [c for c, i in want.items() if i is None]
    if missing:
        raise RuntimeError(
            f"{label} disposition table is missing expected column(s): "
            + ", ".join(missing)
            + ". Live headers were: " + ", ".join(sorted(idx)) + ".")

    table = page.locator("#table-dispositions")
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#table-dispositions tbody tr')"
            ".length >= 1", timeout=10000)
    except Exception as e:  # noqa: BLE001 — turned into a typed failure below
        # An empty day still renders DataTables' 'No data available' row, so
        # zero rows means the grid never built — a failed scrape, not a quiet
        # day. Same rule as the house walk in total_knocks.pull._scrape_rows.
        raise KnocksPullFailed(
            f"{label} disposition grid rendered no rows at all — not even "
            "DataTables' 'No data available' placeholder — so the scrape "
            "failed rather than the day being empty.") from e

    out: list = []
    seen_ids: set = set()
    for _ in range(20):  # safety cap on pagination
        for tr in table.locator("tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if not cells or cells[0].lower().startswith("no data"):
                continue
            if max(want.values()) >= len(cells):
                continue
            rec = {}
            for col, i in want.items():
                raw = cells[i]
                rec[col] = knocks._to_int(raw) if col in counts else raw
            rid = str(rec.get(knocks.COL_ID, "")).strip()
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            out.append(rec)
        nxt = page.locator("#table-dispositions_next").first
        if nxt.count() == 0 or "disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001 — same tolerance as the house walk
            pass
    return out

# Default office to impersonate. Env-targetable so the same module can be
# pointed at another office without a code change (mirrors the churn
# module's CHURN_*_VIEW_URL env overrides).
# KNOCKS_OFFICE is the office-agnostic override (Aya + future offices);
# RASHAD_KNOCKS_OFFICE stays as Rashad's back-compat name.
DEFAULT_OFFICE = (os.environ.get("KNOCKS_OFFICE")
                  or os.environ.get("RASHAD_KNOCKS_OFFICE", "Rashad Reed"))

# TeleMapper pages AND its JSON endpoints (Time Tracker included) are scoped
# to the session's STICKY current campaign — whatever was last selected, by
# anyone, survives into the next visit. Proven 2026-08-22: with Isaiah's
# session stuck on RES-ENERGYWELL the Time Tracker returned 0 rows for a day
# with 7 knocking reps; one navigation pinned to RES AT&T brought them back.
# So every scrape PINS the campaign first. 3 = "RES AT&T", the campaign all
# current knocks offices (fiber D2D and NDS wireless) knock under.
KNOCKS_CAMPAIGN_ID = os.environ.get("KNOCKS_CAMPAIGN_ID", "3")


# An office that knocks a campaign OTHER than the default goes here, keyed by
# ownerville name (already _norm_name'd — lowercase, trimmed). An entry has to
# be OBSERVED and written down, never inferred: a guess here silently blanks a
# whole office's board.
#
# calvin ribera -> 40 (RES-ENERGYWELL). Observed 2026-08-29: Megan read
# invD2DClientId=40 straight off the live URL with his grid on screen. He is
# Energy Wells ONLY (Raf: "Calvin is ENERGY WELL only"), and without this entry
# he was being pinned to 3 (RES AT&T) like everyone else and coming back with
# ZERO rows for days that plainly had four reps on them — the exact
# silently-blank-board failure this dict exists to prevent.
CAMPAIGN_OVERRIDES: "dict[str, str]" = {
    "calvin ribera": "40",
    # BOTH spellings. Ownerville has "Ribera", everyone says "Rivera", and the
    # alias sheet resolves one to the other — but this lookup happens on
    # whatever name the caller passed. Missing here, the wrong spelling would
    # fall through to the RES AT&T default and blank his board, which is the
    # failure that cost days.
    "calvin rivera": "40",
}


def campaign_for_office(name: str) -> str:
    """The TeleMapper campaign to pin for `name`. "" would mean DON'T pin.

    Everyone gets the default unless CAMPAIGN_OVERRIDES says otherwise.

    This USED to return "" for any office flagged NDS, on the reasoning that a
    wireless office has no fiber campaign. That was wrong, and Isaiah is why
    (Megan checked his ownerville on 2026-08-25): his campaign picker offers
    BASE Energy / RES AT&T / RES-ENERGYWELL, and his reps knock RES AT&T like
    everyone else. His Disposition page is empty because his reps don't
    disposition at all — they clock in and knock, and Time Tracker is the only
    record. NDS describes the BUSINESS, not the campaign; conflating the two
    left his session free to drift onto BASE Energy or RES-ENERGYWELL and
    quietly return nothing.

    So the pin is not derived from anything about the office any more — an
    exception has to be observed and written down, not inferred.
    """
    from automations.focus_office_att.aliases import _norm_name
    return CAMPAIGN_OVERRIDES.get(_norm_name(name or ""), KNOCKS_CAMPAIGN_ID)


def _pin_campaign(page, rqst: str, campaign_id: Optional[str] = None,
                  verbose: bool = True) -> None:
    """Force the impersonated session's TeleMapper campaign so a stale sticky
    selection can't silently blank the whole pull. Best-effort: a failure here
    leaves us exactly where we were before this guard existed.

    `campaign_id` None means "use the module default" (what every caller did
    before per-office campaigns existed). An EMPTY campaign skips the pin —
    the session keeps whatever campaign it already had. That's what
    weekly_knock_dispositions does for an NDS office, and it's how
    `lucy probe_knocks … campaign=none` asks whether the pin is what's
    blanking an office."""
    campaign_id = (KNOCKS_CAMPAIGN_ID if campaign_id is None else campaign_id)
    if not campaign_id:
        if verbose:
            print("  · TeleMapper campaign pin SKIPPED "
                  "(no campaign for this office)", flush=True)
        return
    try:
        page.goto(f"https://v2.ownerville.com/index.cfm?p=88&rqst={rqst}"
                  f"&invD2DClientId={campaign_id}",
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1000)
        if verbose:
            print(f"  ✓ Pinned TeleMapper campaign (invD2DClientId="
                  f"{campaign_id})", flush=True)
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  ⚠ Campaign pin failed ({type(e).__name__}) — "
                  "continuing with the session's current campaign", flush=True)


def pull_office_knocks(office_name: Optional[str] = None,
                       target: Optional[dt.date] = None,
                       verbose: bool = True) -> tuple[dt.date, list[dict]]:
    """Scrape Disposition by Rep + Time Tracker gaps for `office_name`'s
    office for `target` (default: yesterday, Central Time), merged by badge
    ID — exactly like total_knocks.pull.pull_disposition_day, but inside the
    session it impersonates `office_name` first and exits impersonation
    after.

    Returns (date, [rep_record, ...]) with each record keyed by
    SHEET_COLUMNS. Reps with no Time Tracker row keep Gaps / Total Gaps
    blank (per Eve), identical to Raf's pull.

    `office_name` defaults to RASHAD_KNOCKS_OFFICE ("Rashad Reed"). The name
    is resolved through the canonical ICD alias list, and the per-row search
    in _find_owner_and_impersonate also tries every known alias.
    """
    office_name = office_name or DEFAULT_OFFICE
    target = target or knocks._yesterday()

    # Resolve any spelling drift to the canonical name up front, so logs +
    # the office-row search start from the canonical spelling. The search
    # itself (get_search_candidates inside the helper) still tries aliases.
    aliases_raw = load_aliases()
    canonical = alias_to_canonical(office_name, aliases_raw)
    if verbose and canonical != office_name:
        print(f"-> Office '{office_name}' resolves to canonical '{canonical}'",
              flush=True)

    with ownerville_session(verbose=verbose) as page:
        return pull_office_on_page(page, canonical, aliases_raw, target,
                                   verbose=verbose)


def pull_office_days_on_page(page, canonical: str, aliases_raw,
                             targets: "list[dt.date]", *,
                             verbose: bool = True) -> "dict":
    """SEVERAL days for one office on an ALREADY-OPEN page: impersonate
    `canonical` ONCE, scrape each day in `targets`, exit impersonation once.
    Returns {date: rows}.

    Why days loop INSIDE the impersonation: switching offices is the expensive
    step (Office Access page, row search, token handoff) and the sticky-campaign
    pin goes with it. A day is just a re-navigation of p=89 plus one JSON fetch,
    so a week costs one impersonation, not seven.

    NOT a date-range request to ownerville, deliberately: p=510 (Time Tracker)
    has no range parameter, and 'Avg. Hrs Knocking' is single-day clock
    arithmetic that a server-side aggregate would silently break. The days are
    folded afterwards by total_knocks.aggregate, where the arithmetic is right
    and each day stays individually cacheable.
    """
    out: dict = {}
    # Bound every op so a stuck page can't hang the run (same guard
    # run_all_owners uses).
    page.set_default_timeout(60_000)
    page.set_default_navigation_timeout(60_000)

    # Clear any lingering impersonation from a prior interrupted run so
    # the ?p=901 navigation below isn't bounced back to ?p=2. Always
    # safe — returns False if not currently impersonating.
    if _exit_impersonation(page) and verbose:
        print("  ✓ Cleared lingering impersonation from prior session",
              flush=True)

    # --- IMPERSONATE the target office --------------------------------
    if not _navigate_to_office_access(page):
        raise RuntimeError(
            "Couldn't reach the ownerville Office Access page (?p=901) to "
            f"impersonate {canonical!r}.")
    # _find_owner_and_impersonate returns the FRESH rqst for the
    # impersonated session (the server hands back a new token), so we
    # don't need to re-capture it separately.
    rqst, reason = _find_owner_and_impersonate(page, canonical, aliases_raw)
    if not rqst:
        raise RuntimeError(
            f"Couldn't impersonate {canonical!r} in ownerville: {reason}")
    if verbose:
        print(f"  ✓ Impersonated {canonical!r}; rqst={rqst[:8]}…",
              flush=True)

    try:
        # Defensive: prefer the live page's rqst if the post-impersonate
        # navigation landed on a URL with a newer token. page_rqst falls
        # back to the value we already have.
        rqst = page_rqst(page) or rqst

        # Sticky-campaign guard — see KNOCKS_CAMPAIGN_ID above. Pinned once
        # for the impersonated session, not once per day: the campaign is a
        # property of the session, and re-pinning would cost a navigation a day.
        _pin_campaign(page, rqst, campaign_for_office(canonical),
                      verbose=verbose)

        for target in targets:
            out[target] = _scrape_day_on_page(page, rqst, target,
                                              verbose=verbose)
    finally:
        # ALWAYS exit impersonation before the session closes so the
        # next run / other reports start from master, not a stuck
        # impersonated state.
        if _exit_impersonation(page):
            if verbose:
                print("  ✓ Exited impersonation", flush=True)
        elif verbose:
            print("  ⚠ Exit-impersonation call didn't succeed", flush=True)

    return out


def _scrape_day_on_page(page, rqst: str, target: dt.date, *,
                        verbose: bool = True) -> list:
    """ONE day's rows on a page that is already impersonating the right office
    with its campaign pinned — Disposition by Rep merged with Time Tracker
    gaps, exactly as pull_office_on_page always did inline. Extracted so the
    multi-day loop and the single-day wrapper can't drift apart."""
    mdy = target.strftime("%m/%d/%Y")

    # --- SCRAPE (identical to pull_disposition_day) ---------------
    if verbose:
        print(f"-> Disposition by Rep for {mdy} (rqst {rqst[:12]}…)",
              flush=True)
    knocks._navigate(page, rqst, mdy)
    idx = knocks._header_index(page)
    # A WIRELESS (NDS) office's Disposition table has its own shape —
    # scrape it with the wireless column set instead of letting the house
    # scrape raise "missing expected column(s)". The wireless rows keep
    # COL_TOTAL_KNOCKS, so knocks_run renders a real Total Knocks board.
    if _is_energywell_dispo(idx):
        # BEFORE the wireless test: Energy Wells has no Talk-To split either,
        # so the wireless check would claim it and drop VL and Presentation.
        rows = _scrape_energywell_rows(page, idx)
        if verbose:
            print(f"-> Energy-Wells-shaped disposition: {len(rows)} rep(s)",
                  flush=True)
    elif _is_wireless_dispo(idx):
        rows = _scrape_wireless_rows(page, idx)
        if verbose:
            print(f"-> Wireless-shaped disposition: {len(rows)} rep(s)",
                  flush=True)
    else:
        rows = knocks._scrape_rows(page, idx)
    # Supplementary while we have disposition rows, the last source
    # standing when we don't — only then is a failed fetch fatal.
    tt = knocks._scrape_time_tracker(page, rqst, mdy, verbose=verbose,
                                     required=not rows)
    if verbose:
        print(f"-> Time Tracker: gap data for {len(tt)} rep(s)", flush=True)

    # A wireless/NDS owner has NO Disposition campaign, so p=89 returns 0
    # rows and there's nothing to hang the gaps on. Build Time-Gaps rows
    # straight from the Time Tracker (name + knock times live in its JSON)
    # while the session is still open. Only the Time Gaps board renders;
    # knocks_run skips Total Knocks when there's no knock data.
    if not rows:
        gap_rows = knocks._scrape_time_tracker_rows(page, rqst, mdy,
                                                    verbose=verbose)
        if gap_rows:
            if verbose:
                print(f"-> Disposition empty; {len(gap_rows)} Time-Tracker gap "
                      f"row(s) (gaps-only office).", flush=True)
            return gap_rows
        return []

    # --- Merge gaps onto disposition rows by badge ID (same as Raf's) -----
    matched = 0
    for rec in rows:
        rid = str(rec.get(COL_ID, "")).strip()
        if rid in tt:
            rec.update(tt[rid])
            matched += 1
    if verbose:
        print(f"-> Merged gaps onto {matched}/{len(rows)} disposition rep(s)",
              flush=True)
    return rows


def pull_office_on_page(page, canonical: str, aliases_raw, target: dt.date,
                        *, verbose: bool = True) -> tuple[dt.date, list[dict]]:
    """ONE day for one office on an already-open page — the original
    single-date entry point, now a thin wrapper over the multi-day loop so both
    paths impersonate, pin and scrape through identical code."""
    days = pull_office_days_on_page(page, canonical, aliases_raw, [target],
                                    verbose=verbose)
    return target, days.get(target, [])


def is_master_office(name: str) -> bool:
    """Is `name` the MASTER ownerville office — the login itself?

    The rhidalgo login IS office 11280, so Raf is not in his own Office Access
    list and `_find_owner_and_impersonate` can never find him. Asking for him
    by impersonation fails with "name not found in ownerville", which reads
    exactly like a permissions gap and is not one (Megan 2026-08-24: `/knocks
    Rafael Hidalgo` answered "16 offices are in this position").
    """
    from automations.focus_office_att.aliases import _norm_name
    from automations.weekly_knock_dispositions.offices import RAF
    return _norm_name(name or "") == _norm_name(RAF["name"])


def pull_master_days_on_page(page, targets: "list[dt.date]", *,
                             verbose: bool = True) -> "dict":
    """The master office's rows for SEVERAL days on an ALREADY-OPEN page — no
    impersonation, because the session is already on that office. Returns
    {date: rows}.

    Same steps as the impersonated path minus the office switch: capture rqst,
    pin the campaign (the sticky-campaign guard applies to the master session
    too), then Disposition + Time Tracker merged by badge id per day. Lived
    inline in captainship_drafts.knock_dispo_images._daily_rows_for_owner until
    on-demand `/knocks` needed the same routing; extracted here so the two
    callers share ONE master scrape instead of keeping two copies in step.
    """
    rqst = knocks._capture_rqst(page)
    if not rqst:
        raise RuntimeError("Couldn't capture ownerville rqst token from "
                           f"{page.url!r} for the master office.")
    from automations.weekly_knock_dispositions.offices import RAF as _RAF
    _pin_campaign(page, rqst, campaign_for_office(_RAF["name"]),
                  verbose=verbose)
    out: dict = {}
    for target in targets:
        rows = _scrape_day_on_page(page, rqst, target, verbose=verbose)
        if verbose:
            print(f"-> master office {target}: {len(rows)} rep(s)", flush=True)
        out[target] = rows
    return out


def pull_master_on_page(page, target: dt.date, *, verbose: bool = True) -> list:
    """ONE day for the master office — the original entry point, wrapping the
    multi-day loop so both paths run identical code."""
    return pull_master_days_on_page(page, [target], verbose=verbose).get(
        target, [])


def pull_offices_days(jobs, verbose: bool = True, profile_dir=None):
    """Scrape SEVERAL offices, each for its OWN list of days, in ONE session.

    `jobs`: [(office_name, [date, ...]), ...]. Per-office date lists rather
    than one shared list because the caller's two offices rarely need the same
    days — the board's office may be missing Thursday while the comparison
    office is missing all week, and pulling days we already have on disk is
    pure waste.

    Returns [(office_name, {date: rows}, error_or_None), ...] in the order
    given. One office raising does NOT abort the rest — its error rides in the
    tuple so the caller can report it per office. A partial failure mid-office
    loses that office's whole dict: the days share one impersonation, so there
    is no half-office state worth handing back.
    """
    aliases_raw = load_aliases()
    out: list = []
    with ownerville_session(verbose=verbose, profile_dir=profile_dir) as page:
        for name, targets in jobs:
            targets = sorted(set(targets))
            canonical = alias_to_canonical(name, aliases_raw)
            if verbose and canonical != name:
                print(f"-> Office '{name}' resolves to canonical '{canonical}'",
                      flush=True)
            if verbose and len(targets) > 1:
                print(f"-> {canonical}: {len(targets)} day(s), "
                      f"{targets[0]} → {targets[-1]}", flush=True)
            try:
                if is_master_office(canonical):
                    # The login IS this office — impersonating it would fail.
                    days = pull_master_days_on_page(page, targets,
                                                    verbose=verbose)
                else:
                    days = pull_office_days_on_page(page, canonical,
                                                    aliases_raw, targets,
                                                    verbose=verbose)
                out.append((name, days, None))
            except Exception as e:  # noqa: BLE001 — one office must not kill the rest
                if verbose:
                    print(f"  ✗ {name}: {type(e).__name__}: {str(e)[:120]}",
                          flush=True)
                out.append((name, {}, e))
    return out


def pull_offices_knocks(office_names, target: Optional[dt.date] = None,
                        verbose: bool = True, profile_dir=None):
    """Scrape SEVERAL offices inside ONE ownerville session, one day each.

    Why one session: each `ownerville_session` launches real Chrome on a shared
    user-data-dir, and the next launch can be adopted by the one before it if
    that Chrome hasn't fully exited ("Opening in existing browser session" —
    the profile race that cost other_office_knocks its second office on
    2026-08-18, even with the built-in 4x8s retry). One login, one browser,
    offices in turn — and it's faster, because the login is paid once.
    Impersonation is exited between offices exactly as the single-office path
    does, so each office starts from master.

    `profile_dir`: run on a Chrome profile of your own instead of the shared
    one, so a run that overlaps another browser report doesn't lose the launch
    race (the shared profile is first-come, first-served).

    Returns (target, [(office_name, rows, error_or_None), ...]) in the order
    given. One office raising does NOT abort the rest — its error rides in the
    tuple so the caller can report it per office.

    A thin wrapper over `pull_offices_days` since on-demand ranges arrived;
    every existing caller keeps this exact signature and return shape.
    """
    target = target or knocks._yesterday()
    out = [(name, days.get(target, []), err)
           for name, days, err in pull_offices_days(
               [(n, [target]) for n in office_names],
               verbose=verbose, profile_dir=profile_dir)]
    return target, out


def _print_preview(office_name: str, target: dt.date, rows: list[dict]) -> None:
    print(f"\n=== {office_name} — Disposition by Rep — {target.isoformat()} "
          f"({len(rows)} rep(s)) ===")
    show = [COL_ID, "Rep", "Total Knocks", "Total Talk to",
            "First Knock", "Last Knock", "Sale", COL_GAPS, COL_TOTAL_GAPS]
    print("  " + " | ".join(f"{c}" for c in show))
    for r in rows[:25]:
        print("  " + " | ".join(str(r.get(c, "")) for c in show))
    if len(rows) > 25:
        print(f"  … +{len(rows) - 25} more")


def main() -> int:
    target = None
    if len(sys.argv) > 1:
        target = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    office_name = DEFAULT_OFFICE
    target, rows = pull_office_knocks(office_name, target)
    _print_preview(office_name, target, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
