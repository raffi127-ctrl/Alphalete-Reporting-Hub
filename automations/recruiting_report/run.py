"""Orchestrate the weekly recruiting-report fill.

Workflow per run:
  1. Attach to your already-running Chrome (debug port 9222) — you must have
     logged into AppStream manually first.
  2. Refresh the AppStream office list, then auto-onboard: any Sheet tab not
     yet in office-mapping.json whose name matches an AppStream office
     (directly OR via the shared 'ICD Aliases' list) is added to the
     confirmed set and remembered permanently.
  3. For each confirmed office: fetch the target week's metrics, write to the
     office tab + master row. If the tab is empty, first drop in a full
     formatted copy of Template Fiber, then backfill the recent weeks.
       - needs_review / ambiguous name: color the tab red to fix the mapping.
       - no AppStream match:            color the tab blue.
  4. OPT phase — pull the ATT ICD Summary crosstab from Tableau and fill each
     tab's OPT + Office-Metrics section (needs Tableau open + logged in).
  5. Log everything to output/logs/recruiting-<date>.log.

Usage:
  .venv/bin/python -m automations.recruiting_report.run                 # current week, live
  .venv/bin/python -m automations.recruiting_report.run --dry-run       # don't write to Sheet
  .venv/bin/python -m automations.recruiting_report.run --only "Cody Cannon"
  .venv/bin/python -m automations.recruiting_report.run --week 2026-05-10
  .venv/bin/python -m automations.recruiting_report.run --retry-missing # 2nd-login pass for offices a prior login couldn't reach
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Make emoji / checkmarks safe on the Windows console (cp1252 default), so the
# Hub can run this on Eve's machine — same guard the other reports use.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from patchright.sync_api import sync_playwright

from . import fetch_office, fill

WORKSPACE = Path(__file__).resolve().parent.parent.parent
LOG_ROOT = WORKSPACE / "output" / "logs"


def _hidden_tab_titles(sh) -> set:
    """Set of tab titles currently HIDDEN in the Sheet. Megan hides a tab when
    the rep is retired / no longer producing; the runner uses that as the
    cue to stop fetching for them (their AppStream office is usually
    deprovisioned too, which is why a fetch attempt fails). One API call —
    gspread's Worksheet object doesn't expose the hidden flag, so we ask
    the Sheets API directly."""
    try:
        # On gspread.Spreadsheet, .client is the HTTPClient directly (not a
        # Client wrapper) — call .request on it. Don't reach for a .http_client
        # attribute; that's only on the higher-level Client.
        resp = sh.client.request(
            "get",
            f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
            params={"fields": "sheets(properties(title,hidden))"},
        )
        data = resp.json()
        return {s["properties"]["title"] for s in data.get("sheets", [])
                if s["properties"].get("hidden")}
    except Exception:
        return set()   # fail open — better to attempt all than skip all


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    """AS picker Sunday for the most-recently-COMPLETED week.

    The downstream per-week writer does a +7 day shift (sheet's WE
    Sunday convention = AS picker Sunday + 7), so this function
    returns the Sunday that maps to the just-ended week's column.

    Eve runs this on Mondays AFTER the prior week ends — she wants
    the just-ended week's column filled, NOT a new in-progress week's
    upcoming-Sunday column.

      Mon 5/25 → 5/17 (→ +7 = WE 5/24, just-ended week ✓)
      Wed 5/27 → 5/17 (same → WE 5/24)
      Sun 5/24 → 5/10 (today's week isn't fully complete until 23:59,
                       so target last fully-completed week's WE 5/17)

    Previously returned the in-progress week's Sunday, which on Monday
    5/25 mapped to WE 5/31 (col K) instead of the desired WE 5/24
    (col J)."""
    today = today or dt.date.today()
    # weekday(): Mon=0 ... Sun=6
    #   days back to last Sunday strictly before today  → (wd+1)%7 or 7
    #   minus another 7 for the +7 WE-shift convention → target just-
    #   completed week, not in-progress
    days_back = ((today.weekday() + 1) % 7 or 7) + 7
    return today - dt.timedelta(days=days_back)


def _setup_logging(week: dt.date) -> logging.Logger:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / f"recruiting-{week.isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    return logging.getLogger("run")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="Sunday YYYY-MM-DD (matches AS picker + Sheet column). Default: most recent Sunday.")
    ap.add_argument("--only", help="Only process this office (by sheet_tab name).")
    ap.add_argument("--retry-missing", action="store_true",
                    help="Re-fetch only the offices still missing from this "
                         "week's results file — for a second pass under a "
                         "different AppStream login. Skips onboarding/pruning "
                         "and the OPT phase.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-opt", action="store_true",
                    help="Skip the OPT phase at the end of the run. Use when "
                         "the captainship's Tableau views aren't wired up yet "
                         "(e.g. early Carlos rollout — AppStream pull only).")
    ap.add_argument("--backfill-weeks", type=int, default=10,
                    help="When a tab is empty (new ICD), how many recent weeks to auto-fill. Default: 10.")
    args = ap.parse_args()

    week = dt.date.fromisoformat(args.week) if args.week else _most_recent_sunday()
    log = _setup_logging(week)
    log.info("target week (AS picker Sunday): %s", week.isoformat())
    log.info("dry_run=%s", args.dry_run)

    mapping = fill.load_mapping()
    log.info(
        "mapping: %d confirmed, %d needs_review, %d skip",
        mapping["confirmed_count"], mapping["needs_review_count"], mapping["skip_count"],
    )

    sh = fill.open_sheet()
    log.info("connected to Google Sheet")

    # Step 1a: needs_review tabs -> red
    for nr in mapping["needs_review"]:
        tab_name = nr["sheet_tab"]
        if args.only and tab_name != args.only:
            continue
        try:
            ws = sh.worksheet(tab_name)
            if not args.dry_run:
                fill.mark_needs_review(ws)
            log.info("[needs_review] %s — colored tab red", tab_name)
        except Exception as e:
            log.warning("[needs_review] %s — failed: %s", tab_name, e)

    # Cumulative results across this week's runs (so rhidalgo + rcaptain sessions
    # both contribute to the "filled this week" set, and `still_missing` reflects
    # offices truly unreachable by anyone).
    results_file = WORKSPACE / "output" / "recruiting_results.json"
    prior_filled: set = set()
    retry_targets: set = set()
    if results_file.exists():
        try:
            prior = json.loads(results_file.read_text())
            if prior.get("week") == week.isoformat():
                prior_filled = set(prior.get("filled", []))
                retry_targets = set(prior.get("still_missing", []))
        except Exception:
            pass
    filled_in_run: set = set()
    inaccessible_in_run: set = set()

    if args.retry_missing:
        if not retry_targets:
            log.info("--retry-missing: no offices still missing for week %s — "
                     "run a full report first (or everything is already filled)",
                     week.isoformat())
            return 0
        log.info("--retry-missing: re-fetching %d office(s) under the current "
                 "login: %s", len(retry_targets), ", ".join(sorted(retry_targets)))

    # Unattended AppStream login via patchright (rcaptain) — no human-launched
    # debug Chrome. Replaces the old connect_over_cdp(9222) path, which broke on
    # Chrome 148 ("Browser context management is not supported"). The session is
    # a full AppStream console with the #searchMC office switcher.
    from automations.shared.tableau_patchright import appstream_direct_session
    log.info("logging into AppStream via patchright (rcaptain) — unattended")

    # Manage the AppStream session manually (not a `with`) so the per-owner loop
    # can RELAUNCH it if the browser/page dies mid-run. Previously one transient
    # #searchMC stall closed the Chrome tab, and every remaining owner then
    # failed instantly with TargetClosedError, leaving the report unfilled (Eve,
    # 2026-06-02). The persistent profile means a relaunch reuses the login.
    _appstream_cm = appstream_direct_session(verbose=True)
    target_page = _appstream_cm.__enter__()
    appstream_dead = False

    def _relaunch_appstream():
        """Close the dead session and open a fresh one (reusing the logged-in
        profile — no re-auth). Returns the new page, or None if relaunch fails."""
        nonlocal _appstream_cm
        try:
            _appstream_cm.__exit__(None, None, None)
        except Exception:
            pass
        try:
            _appstream_cm = appstream_direct_session(verbose=True)
            return _appstream_cm.__enter__()
        except Exception as exc:
            log.error("AppStream relaunch failed: %s", exc)
            return None

    def _appstream_page_dead(page, exc) -> bool:
        """True when the error means the page/context/browser is gone (vs. a
        recoverable per-owner issue like a missing office)."""
        try:
            if page.is_closed():
                return True
        except Exception:
            return True
        msg = str(exc).lower()
        return ("has been closed" in msg or "target page" in msg
                or "browser has been closed" in msg or "target closed" in msg)

    try:

        # Steps 2-4 (office-list refresh, onboard, prune, categorize) are
        # skipped on a --retry-missing pass: a different login sees a narrower
        # office list and would mis-categorize tabs against it.
        if not args.retry_missing:
            # Step 2: refresh the AppStream office list BEFORE matching tabs, so an
            # ICD added to AppStream today can still be onboarded this same run.
            try:
                from automations.recruiting_report.list_all_offices import (
                    refresh_offices_from_page,
                )
                log.info(refresh_offices_from_page(target_page))
            except Exception as e:
                log.warning("office-list refresh skipped: %s", e)

            # Step 3: auto-onboard — any tab not yet mapped whose name matches an
            # AppStream office (directly or via the shared 'ICD Aliases' list) is
            # added to the confirmed set and remembered in office-mapping.json.
            onboard = fill.auto_onboard_tabs(sh, mapping, dry_run=args.dry_run)
            for entry in onboard["onboarded"]:
                log.info("[onboarded] %s → AppStream office %s (%s)",
                         entry["sheet_tab"], entry["office_id"], entry["as_owner"])
            for amb in onboard["ambiguous"]:
                tab = amb["tab"]
                _ids = ", ".join(str(c.get("office_id")) for c in amb["candidates"])
                log.warning("[onboard] %s — name matches %d AppStream offices "
                            "(%s); needs a pick in the Hub — marking red",
                            tab, len(amb["candidates"]), _ids)
                try:
                    if not args.dry_run:
                        fill.mark_needs_review(sh.worksheet(tab))
                except Exception as e:
                    log.warning("  couldn't color %s: %s", tab, e)

            # Step 3.5: prune — any confirmed tab the runner has since deleted
            # from the Sheet is dropped from the mapping, so it stops erroring.
            for tab in fill.prune_deleted_tabs(sh, mapping, dry_run=args.dry_run):
                log.info("[pruned] %s — tab no longer in the Sheet, removed from mapping", tab)

            # Step 4: tabs still unmatched -> blue. Likely the AppStream login
            # lacks access, or an alias row is missing from the 'ICD Aliases' Sheet.
            if not args.only:
                for tab in onboard["unmatched"]:
                    try:
                        if not args.dry_run:
                            fill.mark_uncategorized(sh.worksheet(tab))
                        log.info("[uncategorized] %s — no AppStream match "
                                 "(check AppStream access / alias list)", tab)
                    except Exception as e:
                        log.warning("[uncategorized] %s — failed: %s", tab, e)

        # Step 5: build the fetch scope (includes any freshly-onboarded ICDs).
        confirmed = mapping["confirmed"]
        if args.only:
            confirmed = [c for c in confirmed if c["sheet_tab"] == args.only]
        if args.retry_missing:
            confirmed = [c for c in confirmed if c["sheet_tab"] in retry_targets]
        # Drop tabs the user has HIDDEN in the Sheet — hiding is the visual
        # signal that a tab is inactive/retired (often because the underlying
        # AppStream office has also been deprovisioned, which is why these
        # hits return "not accessible"). Mapping stays intact so unhiding the
        # tab later just re-enables it; no edit needed (Megan, 2026-05-20).
        hidden = _hidden_tab_titles(sh)
        skipped_hidden = [c["sheet_tab"] for c in confirmed if c["sheet_tab"] in hidden]
        if skipped_hidden:
            log.info("skipping %d hidden tab(s): %s",
                     len(skipped_hidden), ", ".join(skipped_hidden))
        confirmed = [c for c in confirmed if c["sheet_tab"] not in hidden]
        if not confirmed:
            log.info("nothing to fetch from AS (no confirmed offices in scope)")
            return 0

        # Pre-compute Template Fiber's weekly columns once — drives backfill on
        # newly-onboarded (empty) office tabs.
        template_sundays = fill.list_template_columns(sh)
        log.info("template has %d weekly columns", len(template_sundays))

        # Step 3: per-office fetch + fill (handles primary + sibling sections)
        for office in confirmed:
            tab_name = office["sheet_tab"]
            primary_id = office["office_id"]
            owner = office["as_owner"]
            siblings = office.get("siblings", [])
            log.info("→ %s (id %s%s)", tab_name, primary_id,
                     f" + siblings {siblings}" if siblings else "")

            try:
                # _retry so a transient Sheets rate-limit (429) waits + retries
                # instead of being mistaken for a missing tab.
                ws = fill._retry(sh.worksheet, tab_name)
            except Exception as e:
                log.warning("  tab %r — couldn't open it (%s) — skipping", tab_name, e)
                continue

            # Determine weeks to fetch (uses PRIMARY section's populated check)
            if fill.is_office_tab_populated(ws):
                weeks_to_fetch = [week]
            else:
                # Empty tab (freshly-added ICD) — drop in a full formatted copy
                # of Template Fiber, then backfill the recent weeks.
                if args.dry_run:
                    log.info("  tab empty → (dry-run) would insert Template Fiber")
                else:
                    try:
                        fill.duplicate_template_for_tab(sh, tab_name)
                        ws = sh.worksheet(tab_name)
                        log.info("  tab empty → inserted Template Fiber")
                    except Exception as e:
                        log.warning("  template insert failed for %s: %s", tab_name, e)
                recent_template_sundays = [s for s in template_sundays if s <= week][-args.backfill_weeks:]
                weeks_to_fetch = sorted(set(recent_template_sundays + [week]))
                log.info("  backfilling last %d weeks", len(weeks_to_fetch))

            values = fill._retry(ws.get_all_values)
            sunday_to_col = fill.find_sunday_columns(values, header_row_idx=0)

            primary_status: Optional[str] = None  # "filled" | "inaccessible"

            for section_id in [primary_id] + list(siblings):
                if section_id == primary_id:
                    section_label = tab_name
                    anchor = 1
                else:
                    section_label = f"{tab_name} (id {section_id})"
                    anchor_found = fill.find_office_section_anchor(ws, section_id)
                    if not anchor_found:
                        log.warning("  [%s] no section header on tab — skip", section_label)
                        continue
                    anchor = anchor_found

                metric_rows = fill.find_office_metric_rows(ws, anchor_row=anchor, max_rows=30)
                if not metric_rows:
                    log.info("  [%s] no metric rows in section — skip", section_label)
                    continue

                week_data: Dict[dt.date, Dict[str, Optional[float]]] = {}
                inaccessible = False
                for w in weeks_to_fetch:
                    try:
                        metrics = fetch_office.fetch_one(target_page, section_id, owner, w)
                        if metrics:
                            week_data[w] = metrics
                            if section_id == primary_id:
                                log.info("  fetched %s: pull=%s, 1st_booked=%s",
                                         w, metrics.get("pull"), metrics.get("first_booked"))
                        elif metrics == {}:
                            log.warning("  [%s] not accessible — skipping (data preserved)", section_label)
                            inaccessible = True
                            break
                    except Exception as e:
                        log.exception("  fetch failed for %s week %s: %s", section_label, w, e)
                        # If the browser/page died, relaunch the session once and
                        # retry this week — otherwise every remaining owner fails
                        # instantly on the dead page (Eve, 2026-06-02).
                        if _appstream_page_dead(target_page, e):
                            log.warning("  AppStream page/browser closed — relaunching session…")
                            target_page = _relaunch_appstream()
                            if target_page is None:
                                appstream_dead = True
                                break
                            try:
                                metrics = fetch_office.fetch_one(target_page, section_id, owner, w)
                                if metrics:
                                    week_data[w] = metrics
                                elif metrics == {}:
                                    inaccessible = True
                                    break
                            except Exception as e2:
                                log.exception("  retry after relaunch failed for %s week %s: %s",
                                              section_label, w, e2)

                if appstream_dead:
                    break

                if section_id == primary_id:
                    if inaccessible:
                        primary_status = "inaccessible"
                    elif week_data:
                        primary_status = "filled"

                if inaccessible or not week_data:
                    continue

                we_sunday_data = {(w + dt.timedelta(days=7)): m for w, m in week_data.items()}
                for line in fill.fill_office_section(
                    ws, metric_rows, sunday_to_col, we_sunday_data, args.dry_run, label=section_label
                ):
                    log.info(line)

            if appstream_dead:
                break

            if primary_status == "filled":
                filled_in_run.add(tab_name)
            elif primary_status == "inaccessible":
                inaccessible_in_run.add(tab_name)

        if appstream_dead:
            log.error("AppStream session was unrecoverable — stopped the fetch "
                      "phase early; remaining tabs will show as missing and can "
                      "be filled with a --retry-missing run.")
    finally:
        # Close the AppStream session (replaces the old `with`'s auto-teardown).
        try:
            _appstream_cm.__exit__(None, None, None)
        except Exception:
            pass

    # Write the cumulative weekly results so the dashboard can alert on tabs
    # that couldn't be filled by any run this week. Hidden tabs (retired
    # reps Megan has hidden in the Sheet) are dropped from the missing list
    # — we never tried to fill them, so they shouldn't be flagged.
    all_filled = prior_filled | filled_in_run
    confirmed_names = {c["sheet_tab"] for c in mapping["confirmed"]}
    still_missing = sorted(confirmed_names - all_filled - hidden)
    results_file.parent.mkdir(parents=True, exist_ok=True)
    results_file.write_text(json.dumps({
        "week": week.isoformat(),
        "filled": sorted(all_filled),
        "still_missing": still_missing,
        "inaccessible_in_last_run": sorted(inaccessible_in_run),
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }, indent=2))

    if still_missing:
        log.warning("MISSING TABS (%d): %s", len(still_missing), ", ".join(still_missing))
    else:
        log.info("MISSING TABS: none ✓ (all %d confirmed offices filled this week)", len(confirmed_names))

    # OPT phase — pull the ATT ICD Summary from Tableau and fill each tab's
    # OPT + Office-Metrics section. Runs after the AppStream phase (its
    # Playwright context is already closed). Wrapped so a Tableau hiccup
    # can't fail the recruiting fill that already succeeded. Skipped on a
    # --retry-missing pass — the OPT data isn't login-dependent and a full
    # run already covered every tab.
    if args.retry_missing:
        log.info("OPT phase skipped (--retry-missing is an AppStream-only pass)")
    elif args.no_opt:
        log.info("OPT phase skipped (--no-opt)")
    else:
        try:
            from automations.recruiting_report import opt_phase
            opt_result = opt_phase.run_opt_phase(dry_run=args.dry_run, logfn=log.info)
            log.info("OPT phase: %d tabs filled, %d skipped",
                     len(opt_result["filled"]), len(opt_result["skipped"]))
        except Exception as e:
            log.warning("OPT phase skipped (is Tableau open + logged in?): %s", e)

    # '=== done ===' is the Hub's success sentinel (dashboard.py checks it
    # BEFORE scanning for tracebacks) — plain 'done' let recovered fetch-retry
    # tracebacks flip a clean run to 'failed' (badge bug, 2026-06-05).
    log.info("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
