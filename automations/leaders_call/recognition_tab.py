"""Weekly tab creator for Maud's "Alphalete Recognition" sheet.

Maud's recognition sheet has ONE tab per week, named by the week-ending Sunday in
`M.D` form (e.g. `7.19`, `7.12`, `7.5` — no leading zeros), each a copy of the
canonical `Template ` tab (note the trailing space). ICDs fill in their office
PROMOTIONS (cols A-F: # | Rep | Trainer | Owner | Category | Notes) and highrolling
reps (cols H-J) for that week's Leader's Call.

This module makes sure the CURRENT week's tab exists BEFORE Maud's Monday reminder
goes out — otherwise the reminder points ICDs at a sheet with no fresh tab to fill.
It ONLY duplicates the Template into a new dated tab (front position). It never
edits, clears, or deletes an existing tab — if the week's tab already exists it is
left exactly as-is (idempotent; safe to run repeatedly).

    # dry-run (default) — read-only, prints what it WOULD do, writes nothing:
    python -m automations.leaders_call.recognition_tab
    # create for real (only after Megan says use the real sheet):
    python -m automations.leaders_call.recognition_tab --write
    # test against a sandbox copy for any week:
    python -m automations.leaders_call.recognition_tab --write \
        --sheet-id <SANDBOX_ID> --for 2026-07-27

The week is the just-completed week (the Sunday on/just before the run day), the
same week the Leader's Call recognizes — so on a Monday run it names last Sunday's
date, matching automations.leaders_call.run._target_week(). RUN IT MONDAY (before
the 11am reminder). See [[project_leaders_call]].
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

# Maud's live "Alphalete Recognition" sheet. Sandbox rule: while building, point at
# a DUPLICATED copy via --sheet-id and only flip to this once Megan says so.
RECOGNITION_SHEET_ID = "1lgYjfpCwYbeeGAdx7FEyI9PIqFk-W57X7HaZ4nsuoFM"
# Canonical blank Megan curated 2026-07-21 ("LUCY TEMPLATE"): current single-section
# format (Rep | Trainer | Owner | Recognition | Notes for Extra Recognition). We
# duplicate it VERBATIM each week — the old `Template ` tab is stale, don't use it.
TEMPLATE_TAB = "LUCY TEMPLATE"


def week_ending_sunday(when: dt.date | None = None) -> dt.date:
    """The Sunday on/just before `when` (default today) — the just-completed
    week's end. Mon..Sat map back to the prior Sunday; Sunday maps to itself."""
    when = when or dt.date.today()
    offset = (when.weekday() + 1) % 7      # Mon=0..Sun=6 -> days back to Sunday
    return when - dt.timedelta(days=offset)


def week_tab_name(when: dt.date | None = None) -> str:
    """`M.D.YY` with no leading zeros, matching the sheet's CURRENT tabs
    (7.19.26, 7.12.26, 7.5.26). NOTE: the older `M.D` tabs (7.5, 6.28) are a
    2020-era convention — using the 2-digit year both matches today's format and
    avoids colliding with those ancient same-month/day tabs."""
    sun = week_ending_sunday(when)
    return f"{sun.month}.{sun.day}.{sun.strftime('%y')}"


def ensure_week_tab(sheet_id: str = RECOGNITION_SHEET_ID,
                    when: dt.date | None = None,
                    dry_run: bool = True) -> dict:
    """Ensure the current week's tab exists. Returns a small result dict:
    {action: exists|would_create|created, tab, ...}. Never deletes/edits."""
    from automations.recruiting_report import fill
    c = fill._client()
    sh = c.open_by_key(sheet_id)
    name = week_tab_name(when)
    titles = [w.title for w in sh.worksheets()]

    if name in titles:
        return {"action": "exists", "tab": name, "sheet": sh.title}

    if TEMPLATE_TAB not in titles:
        # Don't guess a fallback — the template name is exact; surface loudly.
        return {"action": "error", "tab": name, "sheet": sh.title,
                "error": f"template tab {TEMPLATE_TAB!r} not found; tabs={titles[:6]}…"}

    if dry_run:
        return {"action": "would_create", "tab": name, "from": TEMPLATE_TAB,
                "sheet": sh.title}

    tmpl = sh.worksheet(TEMPLATE_TAB)
    sh.duplicate_sheet(source_sheet_id=tmpl.id, insert_sheet_index=0,
                       new_sheet_name=name)      # front position = current week
    return {"action": "created", "tab": name, "from": TEMPLATE_TAB, "sheet": sh.title}


def main() -> int:
    ap = argparse.ArgumentParser(description="Create the current week's tab in the "
                                             "Alphalete Recognition sheet.")
    ap.add_argument("--write", action="store_true",
                    help="Actually create the tab (default is a read-only dry-run).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Force read-only even if --write is passed (wrapper passthrough).")
    ap.add_argument("--sheet-id", default=RECOGNITION_SHEET_ID,
                    help="Override the target sheet (use a SANDBOX copy while testing).")
    ap.add_argument("--for", dest="for_date", default=None,
                    help="Compute the week for this YYYY-MM-DD instead of today (testing).")
    args = ap.parse_args()

    when = None
    if args.for_date:
        when = dt.datetime.strptime(args.for_date, "%Y-%m-%d").date()

    res = ensure_week_tab(args.sheet_id, when=when,
                          dry_run=args.dry_run or not args.write)
    action = res.get("action")
    # Mark the Hub card green on a successful live run (created OR already there).
    if args.write and not args.dry_run and action in ("created", "exists"):
        try:
            from automations.day_orchestrator import hub_publish
            hub_publish.publish_done("recognition_tab", "Recognition Weekly Tab",
                                     status="success")
        except Exception:
            pass
    if action == "exists":
        print(f"✓ Week tab {res['tab']!r} already exists in {res['sheet']!r} — "
              "nothing to do.")
        return 0
    if action == "would_create":
        print(f"[dry-run] would duplicate {res['from']!r} → new tab {res['tab']!r} "
              f"(front) in {res['sheet']!r}. Re-run with --write to create it.")
        return 0
    if action == "created":
        print(f"✅ Created week tab {res['tab']!r} (from {res['from']!r}) in "
              f"{res['sheet']!r}.")
        return 0
    print(f"❌ {res.get('error', res)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
