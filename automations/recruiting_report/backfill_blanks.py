"""Fill in blank week-cells across the last N weeks for each confirmed office.

For each office:
  1. Read its tab once.
  2. Find which of the last N Sundays have at least one blank metric cell.
  3. Fetch + write only those weeks.

Avoids re-fetching weeks that are already filled. Skips offices not visible
in the current AS account (data preserved).
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Dict, List, Optional

import gspread
from patchright.sync_api import sync_playwright

from . import fetch_office, fill


def _last_n_sundays(n: int, today: Optional[dt.date] = None) -> List[dt.date]:
    """Return the last N Sundays (Sheet column dates) on or before today."""
    today = today or dt.date.today()
    last_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return [last_sun - dt.timedelta(days=7 * i) for i in range(n)]


def _find_blank_weeks_in_section(
    values: List[List[str]],
    sunday_to_col: Dict[dt.date, int],
    metric_rows: Dict[str, int],
    sheet_sundays: List[dt.date],
) -> List[dt.date]:
    """Given pre-read sheet values, sunday->col mapping, and metric->row
    mapping for ONE section, return which Sundays have at least one blank
    metric cell."""
    blanks = []
    for sun in sheet_sundays:
        col = sunday_to_col.get(sun)
        if col is None:
            continue
        for metric, row in metric_rows.items():
            if row - 1 < len(values) and col - 1 < len(values[row - 1]):
                cell = values[row - 1][col - 1]
                if cell == "" or cell is None:
                    blanks.append(sun)
                    break
            else:
                blanks.append(sun)
                break
    return blanks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=10, help="How many recent weeks to check.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Restrict to one office (sheet_tab name).")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("backfill")

    sheet_sundays = _last_n_sundays(args.weeks)
    log.info("Checking last %d Sundays: %s … %s", args.weeks,
             sheet_sundays[-1].isoformat(), sheet_sundays[0].isoformat())

    mapping = fill.load_mapping()
    confirmed = mapping["confirmed"]
    if args.only:
        confirmed = [c for c in confirmed if c["sheet_tab"] == args.only]
    if not confirmed:
        log.error("no offices in scope")
        return 1

    sh = fill.open_sheet()
    log.info("connected to Google Sheet")

    # Unattended AppStream login via patchright (rcaptain) — replaces the
    # debug-Chrome CDP attach (broken on Chrome 148). Megan 2026-05-25.
    from automations.shared.tableau_patchright import appstream_direct_session
    with appstream_direct_session(verbose=True) as target_page:

        for office in confirmed:
            tab_name = office["sheet_tab"]
            primary_id = office["office_id"]
            owner = office["as_owner"]
            siblings = office.get("siblings", [])
            all_section_ids = [primary_id] + list(siblings)

            try:
                ws = sh.worksheet(tab_name)
            except Exception as e:
                log.warning("[%s] tab missing: %s", tab_name, e)
                continue

            # Read tab once, compute date columns once
            values = fill._retry(ws.get_all_values)
            sunday_to_col = fill.find_sunday_columns(values, header_row_idx=0)

            # Process each section (primary first, then siblings)
            for section_id in all_section_ids:
                if section_id == primary_id:
                    section_label = f"{tab_name}"
                    anchor = 1
                else:
                    section_label = f"{tab_name} (id {section_id})"
                    anchor_found = fill.find_office_section_anchor(ws, section_id)
                    if not anchor_found:
                        log.warning("[%s] no section header found on tab — skip", section_label)
                        continue
                    anchor = anchor_found

                metric_rows = fill.find_office_metric_rows(ws, anchor_row=anchor, max_rows=30)
                if not metric_rows:
                    log.info("[%s] no metric rows in section starting at row %d — skip",
                             section_label, anchor)
                    continue

                blanks = _find_blank_weeks_in_section(values, sunday_to_col, metric_rows, sheet_sundays)
                if not blanks:
                    log.info("[%s] no blanks in last %d weeks — skip", section_label, args.weeks)
                    continue

                log.info("[%s] %d blank weeks: %s", section_label, len(blanks),
                         ", ".join(b.isoformat() for b in blanks))

                # Fetch each blank week from AS for this office_id
                week_data: Dict[dt.date, Dict[str, Optional[float]]] = {}
                inaccessible = False
                for sheet_sun in blanks:
                    as_picker = sheet_sun - dt.timedelta(days=7)
                    try:
                        metrics = fetch_office.fetch_one(target_page, section_id, owner, as_picker)
                        if metrics:
                            week_data[sheet_sun] = metrics
                        elif metrics == {}:
                            log.warning("[%s] not accessible — skipping (data preserved)", section_label)
                            inaccessible = True
                            break
                    except Exception as e:
                        log.exception("[%s] fetch failed for %s: %s", section_label, as_picker, e)

                if inaccessible or not week_data:
                    continue

                for line in fill.fill_office_section(
                    ws, metric_rows, sunday_to_col, week_data, args.dry_run, label=section_label
                ):
                    log.info(line)
    # (appstream_direct_session closes the browser on exit — no manual teardown)

    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
