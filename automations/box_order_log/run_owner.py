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


def _pull(dest: Path, verbose: bool = True, today: Optional[dt.date] = None) -> Path:
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from . import window
    # Same SCI date-filter drift hits the base view (all owners) — force the
    # window so per-owner pulls (Roshan et al.) never truncate. See window.py.
    start, end = window.default_window(today)
    hook = window.date_window_hook(start, end, verbose=verbose)
    with tableau_session(verbose=verbose) as page:
        return download_crosstab_patchright(
            BASE_VIEW_URL, CROSSTAB_SHEET, dest, verbose=verbose, page=page,
            pre_export=hook)


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
    ap.add_argument("--require-fresh", action="store_true",
                    help="EARLY pass only: if this owner's newest sale hasn't "
                         "reached yesterday, exit 3 (no email) so the later "
                         "pass sends once the extract lands. Data-timed, not "
                         "clock-timed — mirrors box_order_log's 7:00 gate.")
    ap.add_argument("--from-file", metavar="CSV",
                    help="skip the Tableau pull; use an existing ALL-OWNERS "
                         "BoxOrderLog crosstab")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    verbose = not args.quiet
    today = dt.date.today()

    cfg = owners_mod.OWNERS.get(args.owner)
    if not cfg:
        print("✗ unknown owner {!r}. Known: {}".format(
            args.owner, ", ".join(sorted(owners_mod.OWNERS))), file=sys.stderr)
        return 2

    from . import clean, xlsx, payout, png, window

    # ---- 1. get the ALL-OWNERS crosstab --------------------------------
    if args.from_file:
        src = Path(args.from_file)
        if not src.exists():
            print("✗ no such file: {}".format(src), file=sys.stderr)
            return 2
    else:
        src = OUTPUT_DIR / "box_order_log_all_{}.csv".format(today.isoformat())
        try:
            _pull(src, verbose=verbose, today=today)
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

    # Freshness gate for the EARLY (7:00) pass — same idea as box_order_log's:
    # if the owner's newest sale hasn't reached yesterday, the extract likely
    # hasn't refreshed yet, so DON'T email; exit 3 and let the 8:30 pass (which
    # omits --require-fresh) send once the data's in.
    if args.require_fresh and (args.email or args.test_to):
        dated_all = [s.sale_date for s in sales if s.sale_date]
        expected = today - dt.timedelta(days=1)
        newest = max(dated_all) if dated_all else None
        if newest is None or newest < expected:
            print("extract not fresh yet (newest sale {}, need >= {}) — "
                  "deferring to the later pass".format(newest, expected),
                  flush=True)
            return 3

    dated = [s.sale_date for s in sales if s.sale_date]
    newest = max(dated) if dated else None
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
        warn = window.capped_pull_warning(newest, today)
        if warn:
            print("  " + warn)

    # HARD GATE (2026-08-12): if the pull is clearly capped, do NOT email the
    # owner numbers that understate reality — skip the send and fail loudly.
    # The filter-release hook is best-effort and occasionally misses on a bad
    # viz load; this is the net that stops the wrong email from going out. Dry
    # runs are exempt (they're for inspection). See window.should_block_send.
    send_now = args.email or bool(args.test_to)
    block = window.should_block_send(newest, today)
    if block and send_now:
        print("✗ {} — {}: {}".format(
            cfg.display, today.isoformat(), block), file=sys.stderr, flush=True)
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

    if not send_for_real and verbose:
        print("\n  Dry-run: nothing emailed. Re-run with --email to send to {}."
              .format(", ".join(cfg.email_to)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
