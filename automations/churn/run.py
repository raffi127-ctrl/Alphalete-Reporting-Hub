"""Combined Churn run — fills BOTH Local Office Churn tabs (New Internet
+ Wireless) from a single Tableau patchright session.

Both reports pull from the same CHURN view (ATT TRACKER 2.1 - D2D), so
running them under one shared session saves ~30s of Ownerville → Tableau
SSO each daily run.

  python -m automations.churn.run                 # both, today
  python -m automations.churn.run --force-insert  # insert dup col even if today's already there
  python -m automations.churn.run --dry-run
  python -m automations.churn.run --skip-download # reuse cached CSVs
  python -m automations.churn.run --only new-internet   # one or the other
  python -m automations.churn.run --only wireless
  # repair ONE image that a flaky Slack upload dropped (no duplicates):
  python -m automations.churn.run --only wireless --only-period 90 --skip-download

After both fills complete, each report renders 4 multi-week PNG
images (one per period bucket) and posts them as replies in today's
7am Metrics workflow thread in #alphalete-sales — 🌐 globe reaction on
the parent for New Internet Churn, 📊 bar_chart for Wireless Churn.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
import time
from pathlib import Path

from automations.shared.tableau_patchright import tableau_session
from automations.shared.slack_metrics_post import (
    post_reply_with_file, SlackPostError,
)
from automations.shared import repair_hint
from automations.new_internet_churn import (
    pull as ni_pull, fill as ni_fill, render as ni_render,
)
from automations.wireless_churn import (
    pull as wl_pull, fill as wl_fill, render as wl_render,
)


# The slug daily_metrics knows this metric by (METRICS in
# automations/daily_metrics/run.py). It is how a dropped image finds its way back
# to a scoped repair command instead of a whole-metric re-run.
HINT_SLUG = "churn"


SLACK_CONFIG = {
    # (slug from REPORTS) → (title prefix, render module, reaction emoji)
    "new-internet": ("New Internet Churn", ni_render, "globe_with_meridians"),
    "wireless":     ("Wireless Churn",     wl_render, "bar_chart"),
}


REPORTS = [
    ("new-internet", "New Internet Churn", ni_pull, ni_fill),
    ("wireless",     "Wireless Churn",     wl_pull, wl_fill),
]


def _run_fill_phase(label: str, pull_mod, fill_mod, parsed: dict,
                    today: dt.date, args) -> int:
    """Fill the destination tab for one of the two Churn reports.
    Returns 0 on success, 1 on early-exit (today's column already
    present without --force-insert)."""
    print(f"\n--- {label}: parse + fill ---")
    office = parsed["office_total"]
    reps = parsed["reps"]
    print(f"  Reps with data: {len(reps)}")
    for p in pull_mod.PERIODS:
        odata = office.get(p, {})
        units = pull_mod.fmt_units(odata)
        print(f"    Office {p:>4}-day: {odata.get('pct', '-'):>8}  ({units or '-'})")

    print(f"  Open '{fill_mod.TAB_LOCAL_OFFICE}'...")
    ws = fill_mod.open_ws()
    sections = fill_mod.find_sections(ws)
    for p, sect in sections.items():
        print(f"    {p:>4}-day: header row {sect['header_row']}, "
              f"{len(sect['rep_rows'])} existing reps")
    # A rep on TWO rows in one section: only the last row gets today's value,
    # the other keeps a frozen one the daily B+C insert copies forward. Report
    # it (deleting a row is Megan's call), don't fail the Local Office post.
    _warn_dups = getattr(fill_mod, "warn_duplicate_rep_rows", None)
    if _warn_dups:
        _warn_dups(sections, fill_mod.TAB_LOCAL_OFFICE)
    # Same class of invisible row: values with NO name in col A. write_today
    # clears today's pair on them; deleting the row itself stays a human call.
    _warn_ghosts = getattr(fill_mod, "warn_nameless_data_rows", None)
    if _warn_ghosts:
        _warn_ghosts(sections, fill_mod.TAB_LOCAL_OFFICE)

    already_filled = fill_mod.today_already_filled(ws, sections, today)
    skip_insert = already_filled and not args.force_insert

    if skip_insert:
        print(f"  ⚠ '{fill_mod._date_label(today)}' already in B+C — skipping "
              f"COLUMN insert (idempotent). insert_missing_reps + "
              f"write_today + cleanup pass still run so today's values "
              f"get refreshed from the latest pull (matters when the "
              f"source URL changed mid-day, e.g. Eve's wireless-URL fix "
              f"2026-05-29).")
    # insert_missing_reps runs EVERY run, including same-day refreshes
    # (Megan 2026-06-04, mirrors captainship/owners): rows that go
    # missing after the day's first fill get re-created on refresh.
    added = fill_mod.insert_missing_reps(ws, sections, parsed,
                                          dry_run=args.dry_run, logfn=print)
    if added:
        for p, names in added.items():
            print(f"  + {p}-day: added {len(names)} new rep(s): {names[:5]}"
                  + (" …" if len(names) > 5 else ""))
    else:
        print("  (no new reps to add)")
    if not skip_insert:
        if args.dry_run:
            print("  (dry-run, skipping column insert + merge)")
        else:
            fill_mod.insert_two_cols_at_b(ws, sections)
            fill_mod._merge_section_headers(ws, sections)

    # RE-RESOLVE section bounds from the LIVE grid after the row inserts.
    # insert_missing_reps inserts bottom-section-first, which shifts the lower
    # sections DOWN but leaves their in-memory header_rows stale. On an
    # established office (Raf/Rashad: tiny/no inserts) that's harmless, but on a
    # FRESH office's big first-run insert (Aya's whole roster at once) the stale
    # header_rows made unhide_all_rep_rows compute an inverted range
    # (startIndex > endIndex) and crash BEFORE the tier-coloring step — leaving
    # the tab all-orange with no red/yellow/green (Megan 2026-07-11). Re-finding
    # is idempotent for established offices. (Skip on dry-run — no inserts ran.)
    if not args.dry_run:
        sections = fill_mod.find_sections(ws)

    print(f"  Write today ({fill_mod._date_label(today)})...")
    summary = fill_mod.write_today(ws, sections, today, parsed,
                                    dry_run=args.dry_run, logfn=print)
    for p, s in summary.items():
        unmatched_str = (f", {len(s['unmatched'])} unmatched"
                         if s['unmatched'] else "")
        print(f"    {p:>4}-day: {s['filled']} filled{unmatched_str}")

    # Unhide every rep row BEFORE sort so sortRange (which skips
    # hidden rows) can actually move them. Without this, a rep who
    # was hidden yesterday but has data today stays stuck at their
    # old row position even after the write (Megan 2026-05-29: Bill
    # Hirwa stuck at row 24 with 6.67% instead of being sorted into
    # the visible block).
    fill_mod.unhide_all_rep_rows(ws, sections,
                                 dry_run=args.dry_run, logfn=print)

    # Sort by today's % descending — Sheets-native sortRange, atomic.
    # Blanks land at the top (DESCENDING quirk), then hide_blanks_today
    # below hides them — visual end state is non-blank reps in % desc
    # order, blanks invisible.
    # Give every rep row (incl. newly-inserted + sort-moved ones) the canonical
    # borders/centering/font so a new rep matches the existing rows — Megan
    # 2026-07-15: "if a new rep is added, they should get borders and that
    # formatting." Borders span col A..last-DATA-col only (NOT the full grid
    # width), so a wide template's empty history columns stay clean — the fix
    # for the earlier "way too many borders". Background is left untouched; the
    # pct-color pass below owns the fills.
    fill_mod.apply_rep_row_format(ws, sections,
                                  dry_run=args.dry_run, logfn=print)

    # Paint direct background on each pct cell (col B) per period
    # threshold — required because Eve's existing conditional rules
    # don't cover every rep row; direct backgrounds make the colors
    # uniform across all rep rows regardless of rule coverage.
    fill_mod.apply_pct_direct_colors(ws, sections, parsed,
                                     dry_run=args.dry_run, logfn=print)

    # Col C (units) white-override conditional rule — required because
    # Eve's existing % color rules have 3-col ranges that paint C red
    # when the % triggers.
    fill_mod.apply_units_white_override(ws, sections,
                                         dry_run=args.dry_run, logfn=print)

    # Whiten blank cells so the PASTE_NORMAL insert's carried-over
    # red/yellow/green doesn't stick on cells that have NO data today.
    # captainship_churn + owners_metrics_churn already call this; the
    # local-office New Internet + Wireless runner never did, so blank
    # cells showed incorrect colors on Raf/Rashad/Aya (Megan 2026-07-10).
    fill_mod.clear_empty_cell_backgrounds(ws, sections,
                                          dry_run=args.dry_run, logfn=print)

    # Per-section filters: Megan 2026-05-28 — sortRange above already
    # gives reps highest-to-lowest within each section, so we let Eve
    # apply per-section filters from the Sheets UI as needed. The
    # apply_filters helper is kept in fill.py for future use.

    hide_actions = fill_mod.hide_blanks_today(ws, sections,
                                              dry_run=args.dry_run, logfn=print)
    if isinstance(hide_actions, dict) and "hidden" in hide_actions:
        print(f"  Hidden: {len(hide_actions['hidden'])}   "
              f"Unhidden: {len(hide_actions['unhidden'])}")

    # Megan 2026-05-29: hide reps whose 5 leftmost pct cols
    # (B/D/F/H/J) are all explicit 0% (blanks don't count). Same rule
    # already applied on Captainship tabs.
    fill_mod.hide_after_5_zero_pulls(ws, sections,
                                     dry_run=args.dry_run, logfn=print)
    return 0


def main(argv=None) -> int:
    # HARVEST CUTOVER (Megan 2026-08-25, cutting Tableau access after they
    # flagged the account). This one entry point is where BOTH churn pulls
    # happen for every caller — daily_metrics, office_metrics (all 11 offices),
    # rashad_metrics, aya_metrics and any hand run — so the switch belongs here
    # rather than in new_internet_churn / wireless_churn, which have no process
    # of their own on the scheduled path.
    #
    # What it actually saves: offices.CHURN_USE_ALL_OFFICE is True, so all 11
    # offices pull the SAME two org-wide views (INTAllTeams / WirelessAllTeams)
    # and slice to their owner in Python — 22 live pulls a day of 2 distinct
    # views. Those two are now declared in the harvest registry, so the batch
    # pulls them once at order 8 and every office reads the file. Rashad's and
    # Raf's own churn views were already harvested and were being re-scraped too.
    #
    # It cannot change a number. Each report still slices the same bytes it
    # would have downloaded: the adapter serves a byte-identical cached file or
    # returns None and the live scrape runs exactly as today — on a miss, a
    # checksum mismatch, a wrong-date entry, or ANY error. The loader hard-fails
    # rather than serve stale data, and the cached file is COPIED to each
    # caller's out_path, so no two offices share a file handle.
    #
    # An office whose view isn't declared (and jamis_metrics, which runs at 7.9,
    # BEFORE the harvest) simply misses and scrapes live, as it does today.
    #
    # setdefault, not assignment: HARVEST_MODE=off in the environment still
    # wins, so a rollback needs no code change or deploy.
    os.environ.setdefault("HARVEST_MODE", "on")
    os.environ.setdefault("HARVEST_VERBOSE", "1")

    ap = argparse.ArgumentParser(prog="churn")
    ap.add_argument("--date", default=None,
                    help="Override today's date (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would happen, but don't write to the Sheet.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse cached Tableau CSVs in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Insert a NEW B+C column even if today's date label "
                         "is already present (for side-by-side verification).")
    ap.add_argument("--only", choices=("new-internet", "wireless"), default=None,
                    help="Run only one of the two reports.")
    ap.add_argument("--only-period", choices=("0-30", "30", "60", "90"),
                    default=None,
                    help="Post ONLY this period's image. For repairing a run "
                         "where one image didn't land (a flaky Slack upload) "
                         "without re-posting the 3 that did. Sheet fill is "
                         "unaffected — it stays idempotent.")
    ap.add_argument("--skip-slack", action="store_true",
                    help="Sheet-only run, no Slack post. Use for mid-day "
                         "re-runs (e.g. URL fix) when you don't want to "
                         "double-post screenshots in the metrics thread.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    selected = [r for r in REPORTS if args.only is None or r[0] == args.only]

    print(f"=== Churn (Local Office) — {today.isoformat()} "
          f"({'DRY-RUN' if args.dry_run else 'LIVE'}) ===")
    print(f"Reports: {[r[1] for r in selected]}")

    # --- Phase 1: pull both CSVs (single Tableau session) ---
    csvs: dict = {}
    if args.skip_download:
        for slug, label, pull_mod, _ in selected:
            # Default temp path for each module
            default = Path(tempfile.gettempdir()) / (
                "new_internet_churn_local_office.csv" if slug == "new-internet"
                else "wireless_churn_local_office.csv"
            )
            if not default.exists():
                print(f"  ⚠ --skip-download set but no cached CSV at {default}")
                return 1
            csvs[slug] = default
            print(f"  ✓ {label}: cached {default}")
    else:
        print("\nPhase 1: one Tableau patchright session, two Crosstab pulls...")
        with tableau_session(verbose=False) as page:
            for slug, label, pull_mod, _ in selected:
                print(f"  → pulling {label}...")
                csvs[slug] = pull_mod.fetch_crosstab(verbose=False, page=page)
                print(f"    ✓ {csvs[slug]}")

    # --- Phase 2: parse + fill each ---
    print("\nPhase 2: fill destination tabs")
    for slug, label, pull_mod, fill_mod in selected:
        parsed = pull_mod.parse(csvs[slug])
        _run_fill_phase(label, pull_mod, fill_mod, parsed, today, args)

    # --- Phase 3: render 4 multi-week PNGs per report + post to Slack ---
    if args.dry_run:
        print("\nPhase 3: (dry-run, skipping Slack post)")
    elif args.skip_slack:
        print("\nPhase 3: (--skip-slack, sheet fill only)")
    else:
        # The hint describes the run that just happened and nothing else — a
        # leftover from this morning would have the runner above us suggest
        # re-posting one image when today's problem is a dead Tableau pull.
        repair_hint.clear(HINT_SLUG)
        post_failures = _post_to_slack(selected, today,
                                       only_period=args.only_period)
        if post_failures:
            print(f"\n✗ {post_failures} Slack post(s) FAILED — the sheets were "
                  f"filled but those metric(s) did NOT reach the thread. Exiting "
                  f"non-zero so the daily orchestrator flags it instead of "
                  f"counting a silent success.")
            return 1

    print("\n=== done ===")
    return 0


def _post_to_slack(selected, today: dt.date,
                   only_period: str | None = None) -> int:
    """For each selected report: render 4 multi-week PNGs from the
    freshly-filled sheet + post each as a reply in today's 7am Metrics
    workflow thread. Adds the matching workflow-header reaction on the
    parent thread (only the first post per report triggers it; the
    other 3 posts re-attempt but Slack's already-reacted is silent)."""
    print("\nPhase 3: render + post to today's Metrics thread")
    PERIODS = ("0-30", "30", "60", "90")
    if only_period:
        PERIODS = (only_period,)
        print(f"  (--only-period {only_period}: posting just that image — the others are already in the thread)")
    out_dir = Path(tempfile.gettempdir()) / "churn_slack_post"
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0  # Slack posts that raised or came back ok=False
    missed: list[str] = []  # "<label> <period>-day" for each one that didn't land
    # The same misses as (report slug, period) so we can hand the runner above us
    # the EXACT re-post command instead of "re-run the whole metric".
    missed_parts: list[tuple[str, str]] = []

    for slug, label, _pull_mod, fill_mod in selected:
        title_prefix, render_mod, react_emoji = SLACK_CONFIG[slug]
        print(f"  → {label} (​{title_prefix})")
        ws = fill_mod.open_ws()
        sections = fill_mod.find_sections(ws)
        paths = render_mod.render_all_sections(ws, sections, today, out_dir)
        # Track the first section we actually POST so the parent-thread
        # reaction attaches there. For a fully-populated office (Raf) the
        # first present period is "0-30", identical to before. For a young
        # office whose 0-30 is the only filled section, the reaction still
        # fires (on that first present section) rather than being lost on a
        # skipped period.
        posted_any = False
        for period in PERIODS:
            if period not in paths:
                print(f"      {period}-day: ⚠ skipped — section empty / not "
                      f"detected on the sheet (no PNG rendered).")
                continue
            # Small wait between posts so Slack's file-upload events
            # commit in the SAME ORDER we send them. Without this, rapid
            # back-to-back files_upload_v2 calls can get assigned
            # overlapping millisecond timestamps and the Slack thread
            # may display them out of [0-30, 30, 60, 90] order (Megan
            # 2026-05-28).
            if posted_any:
                time.sleep(1.0)
            comment = f"{'🌐' if slug == 'new-internet' else '📊'} {title_prefix} — {period} Day"
            file_name = f"{title_prefix} {period} Day {today:%m-%d-%Y}.png"
            try:
                result = post_reply_with_file(
                    paths[period],
                    comment=comment,
                    react_emoji=react_emoji if not posted_any else None,
                    file_name=file_name,
                )
                posted_any = True
                print(f"      {period}-day: posted (file={result.get('file')})")
                if not result.get("ok", True):
                    failures += 1
                    missed.append(f"{title_prefix} {period}-day")
                    missed_parts.append((slug, period))
            # Catch EVERY post failure, not just SlackPostError. On 2026-08-25 a
            # bare urllib URLError (SSL handshake timeout inside the slack_sdk
            # upload) escaped this handler on the LAST of the 8 posts: 7 images
            # were already in the thread, but the exception unwound main() so the
            # run exited 1 and the alert reported BOTH churn metrics as "did NOT
            # post" — with a fix command (--only churn) that would have
            # re-posted those 7. A flaky post is a per-post failure like any
            # other: count it, say which one, and keep going so the rest of the
            # thread still lands.
            except Exception as e:  # noqa: BLE001
                failures += 1
                kind = "" if isinstance(e, SlackPostError) else f"{type(e).__name__}: "
                print(f"      {period}-day: ⚠ Slack post failed: {kind}{e}")
                missed.append(f"{title_prefix} {period}-day")
                missed_parts.append((slug, period))

    if missed:
        print(f"\n  Images that did NOT reach the thread: {', '.join(missed)}")
        print(f"  Everything else posted — re-post ONLY these, e.g. "
              f"--only <report> --only-period <period> --skip-download, "
              f"never the whole metric.")
        # Say it in a file too, so the runner above us can put that scoped
        # command in the alert instead of `--only churn` (which re-posts all 8
        # and duplicates the ones that landed — 16 dupes on 2026-08-25).
        # --only/--only-period each take ONE value, so a single command can only
        # express a SINGLE dropped image; more than one falls back to the plain
        # re-run, where re-posting the set really is the practical fix.
        module_args = None
        if len(missed_parts) == 1:
            m_slug, m_period = missed_parts[0]
            # No --skip-download: hours later the cached CSV may be gone and the
            # module would just exit 1. A fresh pull costs ~1 minute and the
            # sheet fill is idempotent, so the repair always works.
            module_args = f"--only {m_slug} --only-period {m_period}"
        repair_hint.write(HINT_SLUG, missed=missed, module_args=module_args)
    return failures


if __name__ == "__main__":
    sys.exit(main())
