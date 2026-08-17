"""BOX Order Log for a SINGLE owner (not Carlos) -> emailed to that owner.

Carlos's `run.py` is scoped to his office by the `CarlosOrderLog` Tableau custom
view and posts to Slack. This runner is for other BOX owners who want their OWN
office's log by EMAIL: it pulls the org-wide `BoxOrderLog` view (all owners),
filters the rows down to one owner (see owners.py), builds the same per-rep
workbook + payout image, and emails it.

DRY-RUN BY DEFAULT — pulls, filters, builds, and writes a preview .eml, but
sends NOTHING. Add --email to actually send. Sandbox/dry-run first, per house
rules, until the pull + owner match are verified against real data.

    # dry: pull, filter to Roshan, build, write preview .eml (no send)
    python -m automations.box_order_log.run_owner --owner roshan

    # reuse an already-downloaded all-owners crosstab (no Tableau pull)
    python -m automations.box_order_log.run_owner --owner roshan --from-file all.csv

    # actually send the email
    python -m automations.box_order_log.run_owner --owner roshan --email

Python 3.9 on Lucy 2 — annotations deferred, no runtime `X | Y`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from . import day_marker

# The org-wide BoxOrderLog view — same workbook/worksheet as Carlos's, but
# WITHOUT his `CarlosOrderLog` custom-view segment, so the pull carries every
# owner's rows and we filter in code (the reliable technique — see
# vantura_churn/pull.py, which likewise filters the order log by owner in code
# rather than fighting the URL/quick-filter).
BASE_VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "B2BBOXEnergyTracker/BoxOrderLog?:iid=1"
)
CROSSTAB_SHEET = "Order Log"      # same worksheet Carlos's pull uses

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _view_url(team: bool) -> str:
    """Which all-owners view to pull.

    BASE (`BoxOrderLog`, no custom-view segment) carries every owner, but its
    SAVED state is what keeps re-pinning the Contract ID / Account Id include
    lists, and on 2026-08-13 the '(All)' checkboxes weren't even reachable in
    the DOM any more, so `release_pinned_filters` had nothing to un-pin and both
    owner pulls capped (Roshan 8/4, Abel 7/30) and self-suppressed.

    TEAM is Megan's `ALLEXPORDERLOG` custom view (per_office.TEAM_VIEW_URL) —
    same workbook + worksheet, same "Owner & Office" column, every office in one
    export, but its OWN saved filter state. `per_office` has pulled it since
    2026-07-29. Imported (not re-declared) so the two can never drift.
    """
    if not team:
        return BASE_VIEW_URL
    from .per_office import TEAM_VIEW_URL
    return TEAM_VIEW_URL


def _pull(dest: Path, verbose: bool = True, today: Optional[dt.date] = None,
          team: bool = False) -> Path:
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from . import window
    # Same SCI date-filter drift hits the base view (all owners) — force the
    # window so per-owner pulls (Roshan et al.) never truncate. See window.py.
    start, end = window.default_window(today)
    hook = window.date_window_hook(start, end, verbose=verbose)
    with tableau_session(verbose=verbose) as page:
        return download_crosstab_patchright(
            _view_url(team), CROSSTAB_SHEET, dest, verbose=verbose, page=page,
            pre_export=hook)


def _probe_filters(verbose: bool = True, team: bool = False) -> int:
    """Open the view and DUMP its filter controls — no export, no send.

    Diagnostic for the failure mode the 2026-08-12 hardening could not fix: the
    release logs '(All) item not found' for both fields on both attempts, i.e.
    the selector no longer matches anything rather than losing a hydration race.
    This prints what IS in the DOM so the selector can be corrected against
    fact instead of guesswork. See window.describe_filters.
    """
    from automations.shared.tableau_patchright import tableau_session
    from . import window
    url = _view_url(team)
    print("-> probing filters on {}".format(url), flush=True)
    with tableau_session(verbose=verbose) as page:
        page.goto(url, wait_until="domcontentloaded")
        viz = page.frame_locator('iframe[title="Data Visualization"]')
        viz.locator(
            '[data-tb-test-id="viz-viewer-toolbar-button-download"]'
        ).wait_for(state="visible", timeout=120_000)
        page.wait_for_timeout(25_000)
        print(window.describe_filters(page, viz), flush=True)
    return 0


def _owners_present(sales) -> List[str]:
    return sorted({(s.fields.get("Owner & Office") or "").strip()
                   for s in sales
                   if (s.fields.get("Owner & Office") or "").strip()})


def _filter_owner(sales, match: str):
    m = match.strip().lower()
    return [s for s in sales
            if m in (s.fields.get("Owner & Office") or "").strip().lower()]


def main(argv: Optional[list] = None) -> int:
    from . import owners as owners_mod

    ap = argparse.ArgumentParser(
        description="BOX Order Log for one owner -> emailed")
    ap.add_argument("--owner", required=True,
                    help="owner key from owners.py (e.g. roshan)")
    ap.add_argument("--email", action="store_true",
                    help="actually send the email (default: dry-run, writes a "
                         "preview .eml and sends nothing)")
    ap.add_argument("--sheet", action="store_true",
                    help="also fill this owner's metrics workbook 'Lucy Box "
                         "Order Log' tab (owners.py sheet_id). Merges the "
                         "rolling 6-week log; touches only that tab + its hidden "
                         "data tab. No-op if the owner has no sheet_id.")
    ap.add_argument("--test-to", metavar="ADDR",
                    help="send for real but ONLY to this address (proving send "
                         "for review — implies --email; the owner is NOT mailed)")
    ap.add_argument("--resend", action="store_true",
                    help="email even if this owner already got today's log. The "
                         "day's per-owner marker normally makes a second --email "
                         "a no-op, whatever launched it (wrapper, `lucy rerun`, "
                         "Hub card) — use this only when the first email was "
                         "wrong and they really do need a second one.")
    ap.add_argument("--require-fresh", action="store_true",
                    help="EARLY pass only: if this owner's newest sale hasn't "
                         "reached yesterday, exit 3 (no email) so the later "
                         "pass sends once the extract lands. Data-timed, not "
                         "clock-timed — mirrors box_order_log's 7:00 gate.")
    ap.add_argument("--from-file", metavar="CSV",
                    help="skip the Tableau pull; use an existing ALL-OWNERS "
                         "BoxOrderLog crosstab")
    ap.add_argument("--team-view", action="store_true",
                    help="pull Megan's ALLEXPORDERLOG custom view instead of the "
                         "bare BoxOrderLog base view. Same rows, but its own "
                         "saved filter state — the base view's Contract ID / "
                         "Account Id include lists keep re-pinning and cap the "
                         "export (see window.py).")
    ap.add_argument("--probe-filters", action="store_true",
                    help="diagnostic: open the view, print its filter controls, "
                         "and exit. No export, no email, no sheet write.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    verbose = not args.quiet
    today = dt.date.today()

    # Diagnostic short-circuit: --probe-filters needs no owner data, so it runs
    # before the registry lookup and never touches a deliverable.
    if args.probe_filters:
        return _probe_filters(verbose=verbose, team=args.team_view)

    cfg = owners_mod.OWNERS.get(args.owner)
    if not cfg:
        print("✗ unknown owner {!r}. Known: {}".format(
            args.owner, ", ".join(sorted(owners_mod.OWNERS))), file=sys.stderr)
        return 2

    # ONE EMAIL PER OWNER PER DAY (2026-08-17). deploy/box_order_log_owners.sh
    # has always checked this marker before adding --email, but nothing else
    # did: `lucy rerun box_order_log_roshan --email` and a Hub-card click went
    # straight to her inbox. On 8/17 the noon pass emailed Abel and Roshan
    # cleanly and a 16:35 re-run sent both an identical second copy, because it
    # never looked. Checked BEFORE the pull — an owner who's already had today's
    # log doesn't need a 6,000-row Tableau export to find that out. --test-to is
    # exempt: a proving send to one reviewer isn't the owner's delivery.
    if args.email and not args.test_to and not args.resend and \
            day_marker.already_done(day_marker.owner_stem(cfg.key), today):
        print("  " + day_marker.skip_message(
            "{}'s BOX Order Log".format(cfg.display),
            day_marker.owner_stem(cfg.key), today), flush=True)
        return 0

    from . import clean, xlsx, payout, png, window

    # ---- 1. get the ALL-OWNERS crosstab --------------------------------
    if args.from_file:
        src = Path(args.from_file)
        if not src.exists():
            print("✗ no such file: {}".format(src), file=sys.stderr)
            return 2
    else:
        # One file name per VIEW. `box_order_log_all_<date>.csv` is what
        # per_office._shared_team_file() treats as "today's TEAM ALLEXP export"
        # and reuses without re-pulling — so a BASE-view pull must not land
        # there wearing the team export's name (it did until 2026-08-13).
        src = OUTPUT_DIR / ("box_order_log_all_{}.csv" if args.team_view
                            else "box_order_log_base_{}.csv").format(
                                today.isoformat())
        try:
            _pull(src, verbose=verbose, today=today, team=args.team_view)
        except Exception as exc:
            print("✗ Tableau pull failed: {}".format(exc), file=sys.stderr)
            traceback.print_exc()
            return 1

    # ---- 2. collapse to one row per sale (all owners) ------------------
    all_sales, stats = clean.load(src)
    if not all_sales:
        print("✗ no sales in the crosstab — check the view / date filter.",
              file=sys.stderr)
        return 1

    # ---- 3. filter to THIS owner --------------------------------------
    sales = _filter_owner(all_sales, cfg.match)
    if not sales:
        # Self-documenting failure: the pull didn't contain this owner. Either
        # the base view is still scoped to Carlos, or the match string is off.
        # Print the owners we DID find so the fix is obvious.
        print("✗ no rows matched owner {!r} (match={!r}).".format(
            cfg.display, cfg.match), file=sys.stderr)
        print("  Owners present in this pull ({}):".format(len(_owners_present(all_sales))),
              file=sys.stderr)
        for o in _owners_present(all_sales):
            print("    - {}".format(o), file=sys.stderr)
        print("  If this owner isn't listed, the base view is scoped and the "
              "pull needs a session/view that can see them. If they're listed "
              "under a different spelling, update owners.py `match`.",
              file=sys.stderr)
        return 1

    dated = [s.sale_date for s in sales if s.sale_date]
    newest = max(dated) if dated else None
    # The EXPORT's newest sale, across every owner in it — the honest measure of
    # whether the PULL is capped. See the gate below for why this matters.
    export_dated = [s.sale_date for s in all_sales if s.sale_date]
    export_newest = max(export_dated) if export_dated else None

    # Freshness gate for the EARLY (7:00) pass — same idea as box_order_log's:
    # if the extract hasn't reached yesterday, it likely hasn't refreshed yet,
    # so DON'T email; exit 3 and let the 8:30 pass (which omits --require-fresh)
    # send once the data's in. Measured on the EXPORT, not this owner: "has the
    # extract landed" is a property of the feed, and asking it of one small
    # office defers every quiet morning for no reason (same confusion that
    # suppressed both owners on 2026-08-13 — see the send gate below).
    if args.require_fresh and (args.email or args.test_to):
        expected = today - dt.timedelta(days=1)
        if export_newest is None or export_newest < expected:
            print("extract not fresh yet (newest sale in the export {}, need "
                  ">= {}) — deferring to the later pass".format(
                      export_newest, expected), flush=True)
            return 3
    if verbose:
        reps = sorted({(s.fields.get("Rep Name") or "").strip()
                       for s in sales if (s.fields.get("Rep Name") or "").strip()})
        print("\nBOX Order Log — {} — {}".format(
            cfg.display, today.strftime("%B %d, %Y")))
        print("  matched {} of {} sales to {} (office #{})".format(
            len(sales), len(all_sales), cfg.display, cfg.office_id))
        print("  {} rep(s): {}".format(len(reps), ", ".join(reps)))
        if dated:
            print("  sale dates {} … {}".format(min(dated), max(dated)))
        print("  export newest sale (all owners): {}".format(export_newest))
        # Newest sale PER OWNER: the one readout that separates "the pull is
        # capped" (everybody frozen on the same day) from "this office is quiet"
        # (others current, this one behind). Reading it cost a whole morning on
        # 2026-08-13, so it's printed every run now.
        per_owner = {}
        for s in all_sales:
            o = (s.fields.get("Owner & Office") or "").strip()
            if not o or not s.sale_date:
                continue
            if o not in per_owner or s.sale_date > per_owner[o]:
                per_owner[o] = s.sale_date
        for o in sorted(per_owner, key=lambda k: per_owner[k], reverse=True):
            print("    newest {}  {}".format(per_owner[o], o))
        warn = window.capped_pull_warning(export_newest, today)
        if warn:
            print("  " + warn)

    # HARD GATE (2026-08-12): if the pull is clearly capped, do NOT email the
    # owner numbers that understate reality — skip the send and fail loudly.
    # The filter-release hook is best-effort and occasionally misses on a bad
    # viz load; this is the net that stops the wrong email from going out. Dry
    # runs are exempt (they're for inspection). See window.should_block_send.
    #
    # JUDGED AGAINST WHAT WE ALREADY HAVE (2026-08-13, after two wrong gates).
    #
    # Measuring this owner against TODAY (the 8/12 gate) silences an office that
    # simply hasn't sold — Abel's is 14 sales deep, so it would have blocked him
    # permanently, with no path back. Measuring the whole EXPORT against today
    # (my first fix, same day) passes a pull that's healthy for one office and
    # gutted for another: Carlos came back current at 8/12 while Roshan's and
    # Abel's rows lost the week the 8/11 pull had delivered, and on that reading
    # both owners were emailed undercounted numbers.
    #
    # The stored high-water mark settles both. The Sheet's data tab only merges
    # forward, so it's the newest sale we've ever successfully pulled for this
    # office. A quiet office matches it; a short pull falls behind it. Today
    # Roshan's sheet holds sales through 8/10 and the pull returned 8/04 —
    # caught, in the one comparison that doesn't depend on how busy the office is
    # or on how the other offices happen to look.
    #
    # The export-wide check stays as the backstop for an owner with no sheet on
    # file (nothing to compare against) and for a wholesale frozen feed.
    send_now = args.email or bool(args.test_to)
    known_newest = None
    try:
        from . import sheet as box_sheet
        known_newest = box_sheet.newest_sale_date(cfg.sheet_id)
    except Exception as exc:                              # noqa: BLE001
        print("  ⚠ could not read {}'s stored high-water mark ({!r}) — falling "
              "back to the export-wide check".format(cfg.display, exc),
              file=sys.stderr, flush=True)
    block = window.should_block_send(export_newest, today)
    if known_newest and newest and newest < known_newest:
        block = ("SHORT PULL: this office's newest sale came back {} but the "
                 "Sheet already holds {} — the pull LOST {} day(s) of sales it "
                 "delivered before. Refusing to send numbers that undercount. "
                 "The Sheet keeps its newer rows; re-run once a full pull "
                 "lands.".format(newest, known_newest,
                                 (known_newest - newest).days))
    elif verbose and known_newest:
        print("  stored high-water mark for {}: {} (pull: {})".format(
            cfg.display, known_newest, newest))
    if block and send_now:
        print("✗ {} — {}: {}".format(
            cfg.display, today.isoformat(), block), file=sys.stderr, flush=True)
        # Make the suppression AUDIBLE — a blocked run delivers nothing, so
        # without a ping it's silent. Only for the real owner send (--email),
        # not a --test-to proving send. Never let the alert break the exit.
        if args.email:
            try:
                from automations.shared import section_drop_alert as sda
                # Say which comparison actually fired. The 8/13 alert quoted the
                # owner's newest sale against today and read as "Abel's numbers
                # are 14 days behind", which sent me looking for a frozen feed
                # when the real question was whether the pull came back short.
                if known_newest and newest and newest < known_newest:
                    detail = ("pull returned {} but the Sheet already holds {} "
                              "— lost {} day(s) of sales".format(
                                  newest, known_newest,
                                  (known_newest - newest).days))
                elif export_newest:
                    detail = "newest sale in the export {}, {} days behind".format(
                        export_newest, (today - export_newest).days)
                else:
                    detail = "no dated sales at all"
                # Shared report_id = shared incident thread: this office joins
                # Carlos's/the other owner's alert instead of opening its own
                # (Eve 2026-08-14 — "un solo mensaje, y adentro qué oficinas
                # fallaron"). The office name and its own re-run command move
                # INTO the line, because the headline is now family-level and
                # can't name either. See run.py's twin comment.
                sda.alert(report_id="box-order-log",
                          failed=["{} — {} · re-run `box_order_log_{}`".format(
                              cfg.display, detail, cfg.key)],
                          kind="capped", day=today)
            except Exception:
                pass
        return 3

    # ---- 4. build the owner's workbook + payout image ------------------
    out_xlsx = OUTPUT_DIR / "BOX Order Log {} {}.xlsx".format(
        cfg.display, today.strftime("%m-%d-%Y"))
    out_png = OUTPUT_DIR / "BOX Payout {} {}.png".format(
        cfg.display, today.strftime("%m-%d-%Y"))
    try:
        xlsx.build(sales, out_xlsx, today=today)
        tables = payout.build_week_tables(sales, today)
        png.render(tables, out_png,
                   subtitle="Accepted & Cancelled are for that week — pay "
                            "follows the week after. Still Open = deals not "
                            "yet accepted, any week.")
    except Exception as exc:
        print("✗ build failed: {}".format(exc), file=sys.stderr)
        traceback.print_exc()
        return 1
    if verbose:
        print("  Workbook: {}".format(out_xlsx))
        print("  Payout image: {}".format(out_png))

    # ---- 4b. fill the owner's metrics-sheet BOX Order Log tab -----------
    # Same formula template as Carlos's board, so box_order_log.sheet.push
    # writes the hidden data tab + rebuilds the view, sized to this owner's rep
    # count. Only that tab + its hidden data tab are touched. Rolling 6 weeks,
    # merged (never blanked). Best-effort: a sheet hiccup must not stop the email.
    if args.sheet:
        if not cfg.sheet_id:
            print("  (--sheet: {} has no sheet_id in owners.py — skipping)"
                  .format(cfg.display))
        else:
            from . import sheet as box_sheet
            try:
                res = box_sheet.push(sales, today=today, sheet_id=cfg.sheet_id)
                print("  \U0001F4CA Sheet updated ({} rows, {} reps, {} weeks)"
                      .format(res.get("rows"), res.get("reps"),
                              res.get("weeks")))
            except Exception as exc:
                print("  ⚠ sheet write failed (email still proceeds): {}"
                      .format(exc), file=sys.stderr)
                traceback.print_exc()

    # ---- 5. email it (dry by default) ---------------------------------
    from . import email as box_email
    subject = "BOX Order Log — {}".format(today.strftime("%B %d, %Y"))
    if args.test_to:
        subject = "[TEST] " + subject + " — {} (office #{})".format(
            cfg.display, cfg.office_id)
    first_name = cfg.display.split()[0]
    # --test-to sends for real but only to that one address (proving send);
    # it implies --email and the owner is NOT mailed.
    send_for_real = args.email or bool(args.test_to)
    recipients = [args.test_to] if args.test_to else list(cfg.email_to)
    try:
        box_email.send(subject, out_xlsx, out_png, recipients,
                       greeting_name=first_name, dry_run=not send_for_real)
    except Exception as exc:
        print("✗ email failed: {}".format(exc), file=sys.stderr)
        traceback.print_exc()
        return 1

    # Claim the day as soon as the owner's copy is actually away, so the NEXT
    # --email from any entry point no-ops. The wrapper touches this same file on
    # exit 0; whichever gets there first satisfies both. --test-to doesn't claim
    # it — the owner still hasn't been mailed.
    if args.email and not args.test_to:
        day_marker.mark_done(day_marker.owner_stem(cfg.key), today)

    if not send_for_real and verbose:
        print("\n  Dry-run: nothing emailed. Re-run with --email to send to {}."
              .format(", ".join(cfg.email_to)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
