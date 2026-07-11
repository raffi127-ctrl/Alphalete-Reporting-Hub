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
    SHEET_COLUMNS,  # re-exported for callers (Sheet column order)
)

# Default office to impersonate. Env-targetable so the same module can be
# pointed at another office without a code change (mirrors the churn
# module's CHURN_*_VIEW_URL env overrides).
# KNOCKS_OFFICE is the office-agnostic override (Aya + future offices);
# RASHAD_KNOCKS_OFFICE stays as Rashad's back-compat name.
DEFAULT_OFFICE = (os.environ.get("KNOCKS_OFFICE")
                  or os.environ.get("RASHAD_KNOCKS_OFFICE", "Rashad Reed"))


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
    mdy = target.strftime("%m/%d/%Y")

    # Resolve any spelling drift to the canonical name up front, so logs +
    # the office-row search start from the canonical spelling. The search
    # itself (get_search_candidates inside the helper) still tries aliases.
    aliases_raw = load_aliases()
    canonical = alias_to_canonical(office_name, aliases_raw)
    if verbose and canonical != office_name:
        print(f"-> Office '{office_name}' resolves to canonical '{canonical}'",
              flush=True)

    with ownerville_session(verbose=verbose) as page:
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

            # --- SCRAPE (identical to pull_disposition_day) ---------------
            if verbose:
                print(f"-> Disposition by Rep for {mdy} (rqst {rqst[:12]}…)",
                      flush=True)
            knocks._navigate(page, rqst, mdy)
            idx = knocks._header_index(page)
            rows = knocks._scrape_rows(page, idx)
            tt = knocks._scrape_time_tracker(page, rqst, mdy, verbose=verbose)
            if verbose:
                print(f"-> Time Tracker: gap data for {len(tt)} rep(s)",
                      flush=True)
        finally:
            # ALWAYS exit impersonation before the session closes so the
            # next run / other reports start from master, not a stuck
            # impersonated state.
            if _exit_impersonation(page):
                if verbose:
                    print("  ✓ Exited impersonation", flush=True)
            elif verbose:
                print("  ⚠ Exit-impersonation call didn't succeed", flush=True)

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
    return target, rows


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
