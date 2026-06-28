"""Residential Rep Count — weekly run (Fridays AM, after Archey's Thu-night email).

Reads Archey's latest "Residential Rep Counts" email from
alphaletereporting@gmail.com, parses the `ICD Headcount (by Campaign)` tab, then:
  1. structural phase — add new rostered ICDs; move 0-for-3-weeks ICDs to "No
     longer active"; move returning ICDs back up; dedup alias/maiden-name rows;
     sort both sections by first name; collapse the inactive group;
  2. fill phase — write each active ICD's Unique Headcount into a new Saturday
     week column and recompute TOTAL + Org Ongoing Data.

PRODUCTION DEFAULT: real tab, live write (the scheduler just calls this module).
Testing opt-outs:
  python -m automations.residential_rep_count.run --sandbox          # sandbox tab
  python -m automations.residential_rep_count.run --sandbox --dry-run
  python -m automations.residential_rep_count.run --week-ending 2026-06-20
"""
from __future__ import annotations

import argparse
import datetime as dt
import tempfile
import traceback

from automations.residential_rep_count import (
    email_source, fill, org_headcount, parse, structure)
from automations.recruiting_report import fill as rfill

REPORT_ID = "residential_rep_count"


class EmailNotLanded(Exception):
    """This week's Archey email hasn't arrived yet — wait + retry."""


def _parse_we(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m-%d").date()


def _expected_week_ending(today: dt.date) -> dt.date:
    """The Saturday this Friday-run should fill = the most recent Saturday
    strictly before today (Archey labels weeks by their ending Saturday)."""
    offset = (today.weekday() - 5) % 7 or 7
    return today - dt.timedelta(days=offset)


def _run(args) -> dict:
    sandbox = bool(args.sandbox)
    dry = bool(args.dry_run)
    print(f"Residential Rep Count → {'SANDBOX' if sandbox else 'REAL'} tab"
          f" · {'DRY-RUN' if dry else 'LIVE WRITE'}")

    with tempfile.TemporaryDirectory() as td:
        if args.week_ending:
            want = _parse_we(args.week_ending)
            xlsx, week, subject = email_source.fetch_latest(td, week_ending=want)
        else:
            # Default: require THIS week's email to have landed.
            expected = _expected_week_ending(dt.date.today())
            latest = email_source.latest_week_ending()
            if latest is None or latest < expected:
                raise EmailNotLanded(
                    f"Archey's WE {expected.month}/{expected.day} email not in "
                    f"alphaletereporting yet (latest = "
                    f"{latest if latest else 'none'}).")
            xlsx, week, subject = email_source.fetch_latest(td)
        print(f"  email: {subject!r}  (week ending {week})")
        email_data = parse.parse_headcounts(xlsx)
        print(f"  parsed {len(email_data)} ICD rows from '{parse.HEADCOUNT_TAB}'")

        ws, _ = fill.open_tab(sandbox=sandbox)
        lookup = fill.build_matcher(email_data)
        struct = structure.apply_structure(
            ws, ws.id, lookup, email_data, week, dry_run=dry)
        grid = rfill._retry(ws.get_all_values)
        rep = fill.fill_week(ws, grid, email_data, week, dry_run=dry)

        # also keep the SCI RC/NC Headcount tab current (append this week's
        # org-level column); non-fatal — the ICD fill is the primary output.
        org_rep = None
        try:
            org_data = org_headcount.parse_org_snapshot(xlsx)
            ws_org, _ = org_headcount.open_tab(sandbox=sandbox)
            org_rep = org_headcount.update_week(ws_org, week, org_data, dry_run=dry)
        except Exception as e:
            print(f"  ⚠ SCI RC/NC Headcount update skipped: {e}")

    print(f"\n=== structural {'plan' if dry else 'changes'} ===")
    for line in struct:
        print("  " + line)
    print(f"\n=== {rep['label']} fill ===")
    for line in rep["log"]:
        print("  " + line)
    print(f"  cells {'to write' if dry else 'written'}: {len(rep['updates'])}")
    if org_rep:
        print(f"\n=== SCI RC/NC Headcount: {org_rep['label']} === "
              f"{org_rep['cells']} cells"
              + (f", +{org_rep['appended']} new org leader(s)"
                 if org_rep["appended"] else ""))
    if rep["unmatched"]:
        print(f"\n⚠ {len(rep['unmatched'])} active ICD(s) NOT in the email "
              "(filled 0 — check ICD Aliases): " + ", ".join(rep["unmatched"]))
    try:
        from automations.shared import terminated_icds as ti
        _, flag = ti.alert_terminated(rep["active_names"],
                                      report_label="Residential Rep Count")
        if flag:
            print("\n" + flag)
    except Exception as e:
        print(f"  (terminated-ICD check skipped: {e})")
    return rep


def _org_backfill(args) -> int:
    """Backfill the 'SCI RC/NC Headcount' tab — Org Leader rows × weekly columns
    of Unique Headcount, from the last N weeks' 'Org Snapshot (by Campaign)'."""
    sandbox = bool(args.sandbox)
    dry = bool(args.dry_run)
    n = args.org_backfill
    print(f"SCI RC/NC Headcount BACKFILL ({n} weeks) → "
          f"{'SANDBOX' if sandbox else 'REAL'} tab · "
          f"{'DRY-RUN' if dry else 'LIVE WRITE'}")
    with tempfile.TemporaryDirectory() as td:
        items = email_source.fetch_recent(td, n)
        if not items:
            print("  no Archey emails found"); return 1
        print(f"  {len(items)} weekly emails: {items[0][1]} → {items[-1][1]}")
        weeks = [(week, org_headcount.parse_org_snapshot(path))
                 for path, week, _ in items]
        ws, _ = org_headcount.open_tab(sandbox=sandbox)
        rep = org_headcount.write_backfill(ws, weeks, dry_run=dry)
    print(f"  {rep['leaders']} org leaders × {rep['weeks']} weeks "
          f"({rep['first_week']} → {rep['last_week']})"
          f"{'  [dry-run, not written]' if dry else ''}")
    return 0


def _backfill(args) -> int:
    """Fill the last N weeks' columns from their emails — FILL ONLY (no section
    moves; structural changes belong to the live current-week run)."""
    sandbox = bool(args.sandbox)
    dry = bool(args.dry_run)
    print(f"Residential Rep Count BACKFILL ({args.backfill} weeks) → "
          f"{'SANDBOX' if sandbox else 'REAL'} tab · "
          f"{'DRY-RUN' if dry else 'LIVE WRITE'}")
    with tempfile.TemporaryDirectory() as td:
        items = email_source.fetch_recent(td, args.backfill)
        print(f"  found {len(items)} weekly emails: "
              + ", ".join(str(w) for _, w, _ in items))
        ws, _ = fill.open_tab(sandbox=sandbox)
        for path, week, _subj in items:
            email_data = parse.parse_headcounts(path)
            grid = rfill._retry(ws.get_all_values)
            rep = fill.fill_week(ws, grid, email_data, week, dry_run=dry)
            new = next((l for l in rep["log"] if "NEW week" in l), "")
            print(f"  {rep['label']}: {rep['total_hc']}/{rep['total_icd']} "
                  f"({len(rep['updates'])} cells){'  '+new if new else ''}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", action="store_true",
                    help="target the 'Rep Count 24-26 SANDBOX' tab (testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="don't write anything (testing)")
    ap.add_argument("--week-ending", help="Saturday YYYY-MM-DD to fill "
                    "(default: this week's, must have landed)")
    ap.add_argument("--backfill", type=int, metavar="N",
                    help="fill the last N weeks' columns from their emails "
                         "(fill-only, no section moves)")
    ap.add_argument("--org-backfill", type=int, metavar="N",
                    help="backfill the 'SCI RC/NC Headcount' tab from the last "
                         "N weeks (Org Leader × weekly Unique Headcount)")
    args = ap.parse_args(argv)

    if args.org_backfill:
        return _org_backfill(args)
    if args.backfill:
        return _backfill(args)

    from automations.shared import run_manifest as rm
    try:
        _run(args)
        if not args.sandbox and not args.dry_run:
            rm.mark_clean(REPORT_ID, kind="week")
        return 0
    except EmailNotLanded as e:
        print(f"\n⏳ {e}\n   Not done yet — will retry when the email arrives.")
        if not args.sandbox and not args.dry_run:
            rm.write_manifest(
                REPORT_ID, failed=["email"], retry_args=[], kind="week",
                note=str(e),
                remediation=rm.make_remediation(
                    reason=str(e),
                    fix="Wait for Archey's Thursday-night 'Residential Rep "
                        "Counts' email to land in alphaletereporting@gmail.com, "
                        "then rerun.",
                    message=f"lucy rerun {REPORT_ID}"))
        return 2
    except Exception as e:
        traceback.print_exc()
        if not args.sandbox and not args.dry_run:
            rm.write_manifest(
                REPORT_ID, failed=["run"], retry_args=[], kind="week",
                note=str(e),
                remediation=rm.make_remediation(
                    reason=f"Residential Rep Count failed: {e}",
                    fix="Check the traceback above; rerun once resolved.",
                    message=f"lucy rerun {REPORT_ID}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
