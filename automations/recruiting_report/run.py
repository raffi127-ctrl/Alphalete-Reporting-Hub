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
  4. Log everything to output/logs/recruiting-<date>.log.

Usage:
  .venv/bin/python -m automations.recruiting_report.run                 # current week, live
  .venv/bin/python -m automations.recruiting_report.run --dry-run       # don't write to Sheet
  .venv/bin/python -m automations.recruiting_report.run --only "Cody Cannon"
  .venv/bin/python -m automations.recruiting_report.run --week 2026-05-10
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright

from . import fetch_office, fill

WORKSPACE = Path(__file__).resolve().parent.parent.parent
LOG_ROOT = WORKSPACE / "output" / "logs"


def _most_recent_sunday(today: Optional[dt.date] = None) -> dt.date:
    """The most recent Sunday on or before today."""
    today = today or dt.date.today()
    # weekday(): Mon=0 ... Sun=6
    days_back = (today.weekday() + 1) % 7
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
    ap.add_argument("--dry-run", action="store_true")
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
    if results_file.exists():
        try:
            prior = json.loads(results_file.read_text())
            if prior.get("week") == week.isoformat():
                prior_filled = set(prior.get("filled", []))
        except Exception:
            pass
    filled_in_run: set = set()
    inaccessible_in_run: set = set()

    log.info("attaching to Chrome at %s", fetch_office.CDP_URL)
    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(fetch_office.CDP_URL)
        target_page = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "applicantstream" in page.url:
                    target_page = page
                    break
            if target_page:
                break
        if not target_page:
            log.error("no applicantstream tab open in attached Chrome — log in first")
            return 1

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
        for tab in onboard["ambiguous"]:
            log.warning("[onboard] %s — name matches >1 AppStream office; "
                        "marking needs_review (red)", tab)
            try:
                if not args.dry_run:
                    fill.mark_needs_review(sh.worksheet(tab))
            except Exception as e:
                log.warning("  couldn't color %s: %s", tab, e)

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
                ws = sh.worksheet(tab_name)
            except Exception as e:
                log.warning("  tab %r missing: %s", tab_name, e)
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

            if primary_status == "filled":
                filled_in_run.add(tab_name)
            elif primary_status == "inaccessible":
                inaccessible_in_run.add(tab_name)
    finally:
        p.stop()

    # Write the cumulative weekly results so the dashboard can alert on tabs
    # that couldn't be filled by any run this week.
    all_filled = prior_filled | filled_in_run
    confirmed_names = {c["sheet_tab"] for c in mapping["confirmed"]}
    still_missing = sorted(confirmed_names - all_filled)
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

    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
