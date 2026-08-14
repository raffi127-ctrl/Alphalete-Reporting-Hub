"""Rafael's Captainship metrics — daily fill of three tabs in one run.

WHAT IT FILLS
  Workbook: "AT&T Fiber Metrics Report" (Raf's)
  Tabs:     Captainship - Cancel Rate       (0-30 / 30-60 boxes)
            Captainship - Activation Rate   (0-30 / 30-60 boxes)
            Captainship - 6 days out
  Rows:     Captainship Avg + one row per ICD owner on Raf's Team
  Columns:  today's B:C pair (% + count); history shifts right

WHERE THE NUMBERS COME FROM (full path)
  Tableau -> ATT TRACKER 2_1 - D2D -> view "Metrics"
          -> worksheet "Metrics Call Last week data (Internet)"
          -> rows where "Captain's Bonus Teams" == "Raf's Team",
             read at each owner's subtotal row ("Rep Name" == 'Total')
  cancel 0-30      column '0-30 day New Internet cancel rate'
  cancel 30-60     100% - '30-60 day New Internet activation rate' (no 30-60
                   cancel column exists); blank stays blank
  activation 0-30  column 'Rolling 4 Weeks'
  activation 30-60 column '30-60 day New Internet activation rate'
  6+ days out      column '% of sales scheduled 6+ days out (4 wks)'
  counts           see boxes.py — neither 30-60 box has one, so those
                   'units' cells are left blank on purpose

  python -m automations.captainship_raf_metrics.run
  python -m automations.captainship_raf_metrics.run --dry-run
  python -m automations.captainship_raf_metrics.run --only cancel
  python -m automations.captainship_raf_metrics.run --skip-download
  python -m automations.captainship_raf_metrics.run --force-insert
  python -m automations.captainship_raf_metrics.run --reformat   # heal history
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from automations.shared.tableau_patchright import tableau_session
from automations.captainship_raf_metrics import boxes as B, fill, pull
from automations.focus_office_att.aliases import load_aliases, alias_to_canonical

REPORT_ID = "captainship-raf-metrics"
# Texas company — the report date is always Central, never the box's clock.
TZ = ZoneInfo("America/Chicago")

TAB_SLUGS = {
    "cancel": B.TAB_CANCEL,
    "activation": B.TAB_ACTIVATION,
    "sixdays": B.TAB_SIXDAYS,
}

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — older Pythons / redirected stdout
    pass


def _today(arg: str | None) -> dt.date:
    return dt.date.fromisoformat(arg) if arg else dt.datetime.now(TZ).date()


def _apply_aliases(parsed: dict, aliases: dict) -> dict:
    """Canonicalize owner names through the shared ICD Aliases sheet BEFORE the
    fill, so a Tableau spelling the tab doesn't use matches the existing row
    instead of appending a duplicate one."""
    if not aliases:
        return parsed
    merged: dict = {}
    for name, per_box in parsed.get("reps", {}).items():
        canonical = alias_to_canonical(name, aliases)
        if canonical in merged:
            for box, slot in per_box.items():
                merged[canonical].setdefault(box, {}).update(slot)
        else:
            merged[canonical] = per_box
    parsed["reps"] = merged
    return parsed


def _fill_tab(tab: str, all_parsed: dict, today: dt.date, args) -> dict:
    print(f"\n--- {tab} ---")
    parsed = pull.for_tab(all_parsed, tab)
    ws = fill.open_ws(tab, sheet_id=args.sheet_id)
    boxes = fill.find_boxes(ws)
    required = {b.box for b in B.for_tab(tab) if not b.optional}
    missing = sorted(required - set(boxes))
    if missing:
        # A required box that isn't there means the col-A labels changed and
        # half the tab would fill silently. Never that — fail this tab loudly.
        raise RuntimeError(
            f"box(es) {missing} not found on {tab!r} (found {sorted(boxes)}). "
            f"The col-A section labels changed — see boxes.py markers.")
    skipped = sorted({b.box for b in B.for_tab(tab) if b.optional} - set(boxes))
    if skipped:
        print(f"  ℹ optional box(es) not on this tab yet, skipped: {skipped}")
    step = fill.col_step(boxes)
    print(f"  Layout read off the tab: {step} column(s) per day"
          + (" (% + units)" if step == 2 else " (% only — no units column)"))
    for box, sect in boxes.items():
        print(f"    {box:>5}: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} ICD row(s)")

    if args.reformat:
        cols = fill.day_columns(ws, boxes)
        print(f"  --reformat: re-stamping {len(cols)} day pair(s)")
        for c0 in cols:
            fill.format_pair(ws, boxes, first_col_0=c0,
                             dry_run=args.dry_run, logfn=print)
            fill.merge_headers(ws, boxes, first_col_0=c0, dry_run=args.dry_run)
        return {"summary": {}, "added": {}}

    fill.ensure_columns(ws, dry_run=args.dry_run, logfn=print)

    already = fill.today_already_filled(ws, boxes, today)
    if already and not args.force_insert:
        print(f"  '{fill._date_label(today)}' already in B — refreshing today's "
              f"values in place (no second pair).")
    else:
        fill.insert_day_at_b(ws, step, dry_run=args.dry_run, logfn=print)

    # Who this tab already carried, BEFORE place_reps updates `boxes` in place.
    # A rep gaining their FIRST row in one box while another box has carried
    # them for weeks is a maturing cohort, not a new rep — see
    # captain_watch.observe_added.
    roster_before = {n for s in boxes.values() for n in s["rep_rows"]}

    added = fill.place_reps(ws, boxes, parsed, dry_run=args.dry_run, logfn=print)
    for box, names in added.items():
        print(f"  + {box}: added {len(names)} ICD row(s): {names}")
    if not added:
        print("  (no new ICD rows to add)")

    # A rep new to Raf's captainship: ask for a ✅ in #revision-emails. Only the
    # checkmark puts them on the Org Sales Board; this tab already has them.
    # Advisory — the fill's own work is done. [[project_new_owners]]
    try:
        from automations.new_owners import captain_watch as _cw
        _cw.observe_added(added, captain="Raf",
                          source="Captainship Metrics - Rafael",
                          known=roster_before,
                          dry_run=args.dry_run)
    except Exception as _e:  # noqa: BLE001 — never break the fill on a notice
        print(f"  (new-rep gate skipped: {type(_e).__name__}: {str(_e)[:60]})")

    print(f"  Write {fill._date_label(today)}...")
    summary = fill.write_today(ws, boxes, today, parsed,
                               dry_run=args.dry_run, logfn=print)
    fill.merge_headers(ws, boxes, dry_run=args.dry_run)
    fill.format_pair(ws, boxes, dry_run=args.dry_run, logfn=print)

    for box, s in summary.items():
        extra = ""
        if s["blank"]:
            extra += f", {len(s['blank'])} blank"
        if s["unmatched"]:
            extra += f", {len(s['unmatched'])} not on the tab: {s['unmatched']}"
        print(f"    {box:>5}: avg {s['avg'] or '-'}, {s['filled']} filled{extra}")
    return {"summary": summary, "added": added}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_raf_metrics")
    ap.add_argument("--date", default=None, help="Override today (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen; write nothing.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the cached Metrics crosstab in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Open a new B:C pair even if today's date is in B.")
    ap.add_argument("--only", choices=sorted(TAB_SLUGS), default=None,
                    help="Run one tab only.")
    ap.add_argument("--reformat", action="store_true",
                    help="Re-stamp the house style onto EVERY day pair "
                         "(heals a tab someone formatted by hand). No pull, "
                         "no new column.")
    ap.add_argument("--sheet-id", default=None,
                    help="Write to a different workbook (a sandbox copy).")
    args = ap.parse_args(argv)

    today = _today(args.date)
    tabs = ([TAB_SLUGS[args.only]] if args.only else B.TABS)
    target = args.sheet_id or B.SHEET_ID

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== Rafael Captainship Metrics — {today.isoformat()} ({mode}) ===")
    print(f"Workbook: https://docs.google.com/spreadsheets/d/{target}/edit")
    print(f"Tabs: {tabs}")

    # --- Phase 1: one Tableau session, one crosstab, every box ---
    parsed = {"office_total": {}, "reps": {}}
    if not args.reformat:
        csv_path = Path(tempfile.gettempdir()) / pull.CSV_NAME
        if args.skip_download:
            if not csv_path.exists():
                print(f"  ⚠ --skip-download set but no cached CSV at {csv_path}")
                return 1
            print(f"\nPhase 1: cached crosstab {csv_path}")
        else:
            print("\nPhase 1: Tableau — Metrics crosstab "
                  f"('{pull.WORKSHEET}')...")
            try:
                with tableau_session(verbose=False) as page:
                    csv_path = pull.fetch(csv_path, page=page, verbose=False)
                print(f"  ✓ {csv_path}")
            except Exception as e:  # noqa: BLE001
                # The pull feeds all three tabs — there is no partial success
                # worth keeping. Fail loudly rather than half-fill.
                msg = str(e).splitlines()[0][:200]
                print(f"  ⚠ Metrics crosstab pull FAILED: {msg}")
                _manifest(failed=["Metrics crosstab"], args=args,
                          note=f"the Metrics crosstab pull failed: {msg}")
                print("\n=== run INCOMPLETE — no tab was filled. ===")
                return 1

        parsed = pull.parse(csv_path)
        parsed = _apply_aliases(parsed, load_aliases())
        print(f"  Raf's Team: {len(parsed['reps'])} ICD owner(s); "
              + ", ".join(
                  f"{b.key} avg "
                  f"{(parsed['office_total'].get(b.key) or {}).get('pct', '-')}"
                  for b in B.BOXES))

    # --- Phase 2: fill each tab ---
    print("\nPhase 2: fill the tabs")
    failed: list = []
    unmatched_all: dict = {}
    for tab in tabs:
        try:
            res = _fill_tab(tab, parsed, today, args)
        except Exception as e:  # noqa: BLE001 — one bad tab mustn't kill the rest
            print(f"  ⚠ {tab}: FAILED — {type(e).__name__}: "
                  f"{str(e).splitlines()[0][:200]}")
            failed.append(tab)
            continue
        um = sorted({n for s in res["summary"].values() for n in s["unmatched"]})
        if um:
            unmatched_all[tab] = um

    for tab, names in unmatched_all.items():
        print(f"\n  ℹ {tab}: ICD(s) in Tableau with no row on the tab: "
              f"{', '.join(names)}")

    _manifest(failed=failed, args=args,
              note=("ICD(s) in Tableau with no row on the tab: "
                    + "; ".join(f"{k} — {', '.join(v)}"
                                for k, v in unmatched_all.items())
                    ) if unmatched_all else None)

    if failed:
        print(f"\n=== run INCOMPLETE — {len(tabs) - len(failed)}/{len(tabs)} "
              f"tabs filled; MISSING: {failed} ===")
        return 1
    print("\n=== done ===")
    return 0


def _manifest(*, failed, args, note=None) -> None:
    """Standard failure manifest -> Hub 'Retry failed only' + failure callout."""
    if args.dry_run or args.only or args.reformat:
        return
    try:
        from automations.shared import run_manifest as _rm
        if failed:
            _rm.write_manifest(
                REPORT_ID, failed=list(failed), retry_args=[], kind="report",
                note=(note or f"{len(failed)} tab(s) failed: {failed}."),
                remediation=_rm.make_remediation(
                    reason=f"Rafael's captainship metrics failed for: "
                           f"{', '.join(failed)}.",
                    fix="Usually a flaky/slow Tableau load (a re-run often "
                        "clears it). If the log says a column is missing, the "
                        "Metrics view was renamed — that breaks "
                        "captainship_activation_rate and country_metrics too. "
                        "If it says no rows for the team, Raf's Team was "
                        "renamed in SFDC; update boxes.TEAM.",
                    link=pull.VIEW_URL,
                    message="Rafael's Captainship metrics couldn't fill: "
                            f"{', '.join(failed)}. Can someone check the "
                            "Metrics view is loading?"))
        elif note:
            _rm.write_manifest(REPORT_ID, failed=[], kind="report",
                               note="⚠ " + note)
        else:
            _rm.mark_clean(REPORT_ID, kind="report")
    except Exception:  # noqa: BLE001 — a manifest must never fail the run
        pass


if __name__ == "__main__":
    sys.exit(main())
