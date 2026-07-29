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


def _pull(dest: Path, verbose: bool = True) -> Path:
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    with tableau_session(verbose=verbose) as page:
        return download_crosstab_patchright(
            BASE_VIEW_URL, CROSSTAB_SHEET, dest, verbose=verbose, page=page)


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
    ap.add_argument("--test-to", metavar="ADDR",
                    help="send for real but ONLY to this address (proving send "
                         "for review — implies --email; the owner is NOT mailed)")
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

    from . import clean, xlsx, payout, png

    # ---- 1. get the ALL-OWNERS crosstab --------------------------------
    if args.from_file:
        src = Path(args.from_file)
        if not src.exists():
            print("✗ no such file: {}".format(src), file=sys.stderr)
            return 2
    else:
        src = OUTPUT_DIR / "box_order_log_all_{}.csv".format(today.isoformat())
        try:
            _pull(src, verbose=verbose)
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

    if verbose:
        reps = sorted({(s.fields.get("Rep Name") or "").strip()
                       for s in sales if (s.fields.get("Rep Name") or "").strip()})
        dated = [s.sale_date for s in sales if s.sale_date]
        print("\nBOX Order Log — {} — {}".format(
            cfg.display, today.strftime("%B %d, %Y")))
        print("  matched {} of {} sales to {} (office #{})".format(
            len(sales), len(all_sales), cfg.display, cfg.office_id))
        print("  {} rep(s): {}".format(len(reps), ", ".join(reps)))
        if dated:
            print("  sale dates {} … {}".format(min(dated), max(dated)))

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
