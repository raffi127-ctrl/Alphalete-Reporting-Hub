"""BOX (B2B) Order Log -> #alphalete-gp-sales, as its own dated header.

Carlos's B2B counterpart to Raf's Fiber Order Log. Pulls his Box Order Log
view, collapses the status-transition rows into one row per real sale
(see clean.py), and renders a color-coded PDF split by week ending with a
count-by-week summary on the cover page.

DRY-RUN BY DEFAULT — builds the PDF and describes the post without sending.
Add --post to actually post. Runs on Lucy 2 (Carlos's machine); the channel
is his private #alphalete-gp-sales, same as the Sales Boards report.

    python -m automations.box_order_log.run              # build only
    python -m automations.box_order_log.run --post       # build + post
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

# Python 3.9 on the mini / Lucy 2 — keep annotations deferred and avoid
# runtime-evaluated `X | Y`. (order_log.py:31 records the outage this caused.)

VIEW_URL = (
    "https://us-east-1.online.tableau.com/#/site/sci/views/"
    "B2BBOXEnergyTracker/BoxOrderLog/8286c5bb-09f8-4bd8-a3cf-4842dd4d7f87/"
    "CarlosOrderLog?:iid=1"
)
# Worksheet as it appears in Download -> Crosstab. The dialog offers two:
# "Latest Update" (a timestamp caption) and "Order Log" (the data).
CROSSTAB_SHEET = "Order Log"

CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _pull(dest: Path, verbose: bool = True) -> Path:
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    with tableau_session(verbose=verbose) as page:
        return download_crosstab_patchright(
            VIEW_URL, CROSSTAB_SHEET, dest, verbose=verbose, page=page)


def _describe(sales, stats) -> str:
    from . import clean
    weeks, statuses, counts = clean.week_counts(sales)
    lines = [
        "  {:>5} raw rows from Tableau".format(stats.get("raw_rows", 0)),
        "  {:>5} dropped (Draft — tablet quotes, never a sale)".format(
            stats.get("dropped_never_a_sale", 0)),
        "  {:>5} pipeline duplicates collapsed".format(
            stats.get("collapsed_rows", 0)),
        "  {:>5} real sales".format(stats.get("sales", 0)),
    ]
    if stats.get("kept_incomplete"):
        lines.append("  {:>5} of those are not completed sales — TPV failed, "
                     "incomplete, cancelled (kept on purpose)".format(
                         stats["kept_incomplete"]))
    if stats.get("missing_sale_date"):
        lines.append("  ⚠ {} sale(s) have no sale date".format(
            stats["missing_sale_date"]))
    lines.append("")
    lines.append("  Week Ending    " + "".join(
        "{:>13}".format(s[:12]) for s in statuses) + "{:>8}".format("TOTAL"))
    for w in weeks:
        total = sum(counts.get((w, s), 0) for s in statuses)
        lines.append("  {:<15}".format(w.strftime("%m/%d/%Y") if w else "no date")
                     + "".join("{:>13}".format(counts.get((w, s), 0) or "")
                               for s in statuses)
                     + "{:>8}".format(total))
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="BOX Order Log -> #alphalete-gp-sales")
    ap.add_argument("--sheet", action="store_true",
                    help="write the Lucy Box Order Log tab on the Vantura "
                         "Master Sales Board (Carlos's actual ask)")
    ap.add_argument("--weeks", type=int, default=6,
                    help="how many weeks back the rolling window keeps "
                         "(default 6; older weeks drop off)")
    ap.add_argument("--xlsx", action="store_true",
                    help="build the daily workbook: one tab per rep, "
                         "Fiber-style (full pull, not just the 6-week window)")
    ap.add_argument("--pdf", action="store_true",
                    help="also build the PDF")
    ap.add_argument("--post", action="store_true",
                    help="actually post to Slack (default: build only)")
    ap.add_argument("--note", metavar="TEXT",
                    help="extra line under the header — e.g. what changed "
                         "since the last preview")
    ap.add_argument("--dm", metavar="USER_IDS",
                    help="route the post to a DM instead of the channel, for "
                         "review. Comma-separate for a group DM. Same code "
                         "path as the real post, so what you see is what "
                         "would ship.")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op flag; dry-run is already the default")
    ap.add_argument("--from-file", metavar="CSV",
                    help="skip the Tableau pull and use an existing crosstab")
    ap.add_argument("--out", metavar="PDF", help="output PDF path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    verbose = not args.quiet
    today = dt.date.today()

    from . import clean, render

    # ---- 1. get the crosstab -------------------------------------------
    if args.from_file:
        src = Path(args.from_file)
        if not src.exists():
            print("✗ no such file: {}".format(src), file=sys.stderr)
            return 2
    else:
        src = OUTPUT_DIR / "box_order_log_{}.csv".format(today.isoformat())
        try:
            _pull(src, verbose=verbose)
        except Exception as exc:
            print("✗ Tableau pull failed: {}".format(exc), file=sys.stderr)
            traceback.print_exc()
            return 1

    # ---- 2. collapse ----------------------------------------------------
    sales, stats = clean.load(src)
    if not sales:
        print("✗ no sales found in the crosstab — refusing to post an empty "
              "log. Check the view's date filter.", file=sys.stderr)
        return 1

    # Cross-platform date window: %-d is glibc/BSD only and blows up on
    # Windows, so build the day number off the date itself.
    def _pretty(d, with_year=False):
        return "{} {}{}".format(d.strftime("%b"), d.day,
                                d.strftime(", %Y") if with_year else "")

    dated = [s.sale_date for s in sales if s.sale_date]
    window = ("{} – {}".format(_pretty(min(dated)), _pretty(max(dated), True))
              if dated else "")

    # ---- 3. roll to the last N weeks ------------------------------------
    window_sales = clean.last_n_weeks(sales, args.weeks, today=today)
    if not window_sales:
        print("✗ no sales inside the last {} weeks — refusing to blank the "
              "tab. Check the view's date filter.".format(args.weeks),
              file=sys.stderr)
        return 1

    if verbose:
        print("\nBOX Order Log — {}".format(today.strftime("%B %d, %Y")))
        print(_describe(window_sales, stats))
        print("\n  {} of {} sales fall in the last {} weeks".format(
            len(window_sales), len(sales), args.weeks))

    # ---- 4. write the Sheet ---------------------------------------------
    if args.sheet:
        from . import sheet
        try:
            sheet.push(window_sales, today=today, weeks_back=args.weeks)
        except Exception as exc:
            print("✗ Sheet write failed: {}".format(exc), file=sys.stderr)
            traceback.print_exc()
            return 1
        print("\n✅ Wrote '{}' on the Vantura Master Sales Board.".format(
            sheet.TAB_VIEW))
    elif verbose:
        print("\n  (no --sheet — nothing written to the Sales Board)")

    # ---- 5. daily per-rep workbook --------------------------------------
    # Deliberately built off the FULL pull, not window_sales: this is the
    # daily "here's everything, broken down by rep" artifact, while the sheet
    # is the rolling six-week view.
    out_xlsx = OUTPUT_DIR / "BOX Order Log {}.xlsx".format(
        today.strftime("%m-%d-%Y"))
    out_png = OUTPUT_DIR / "BOX Payout {}.png".format(today.strftime("%m-%d-%Y"))
    if args.xlsx or args.post:
        from . import xlsx
        try:
            xlsx.build(sales, out_xlsx, today=today)
        except Exception as exc:
            print("✗ workbook build failed: {}".format(exc), file=sys.stderr)
            traceback.print_exc()
            return 1
        if verbose:
            n_reps = len({(s.fields.get("Rep Name") or "").strip()
                          for s in sales if (s.fields.get("Rep Name") or "").strip()})
            print("\n  Workbook: {}".format(out_xlsx))
            print("    All Reps summary + Payout by Week + {} rep tabs, "
                  "{} sales".format(n_reps, len(sales)))

        # The payout image that goes inline in Slack.
        from . import payout, png
        tables = payout.build_week_tables(sales, today)
        png.render(tables, out_png,
                   subtitle="Paid & Cancelled are for that week. "
                            "Still Open = deals not yet accepted, any week.")
        if verbose:
            print("  Payout image: {}".format(out_png))
            for key in ("last", "this"):
                t = tables[key]
                paid = sum(r["posted"] for r in t["rows"])
                pend = sum(r["pending"] for r in t["rows"])
                print("    {:<5} {}  paid={} pending={}".format(
                    key.upper(), t["label"], paid, pend))

    # ---- 6. optional PDF -------------------------------------------------
    out_pdf = Path(args.out) if args.out else (
        OUTPUT_DIR / "BOX Order Log {}.pdf".format(today.strftime("%m-%d-%Y")))
    if args.pdf or args.post:
        subtitle = "Carlos Hidalgo · B2B BOX Energy · sales dated {}".format(window)
        render.render_pdf(window_sales, stats, out_pdf,
                          title="BOX Order Log", subtitle=subtitle)
        if verbose:
            print("  PDF: {}".format(out_pdf))

    # ---- 7. optional Slack post -----------------------------------------
    header = "*BOX Order Log — {}*".format(today.strftime("%B %d, %Y"))
    if not args.post:
        if verbose:
            print("\n  Not posted to Slack. To post the PDF to {}:".format(
                CHANNEL[0]))
            print("    header : {}".format(header))
            print("    re-run with --post")
        return 0

    try:
        from automations.shared import slack_metrics_post as smp
    except Exception as exc:
        print("✗ Slack helper unavailable: {}".format(exc), file=sys.stderr)
        return 1

    os.environ["METRICS_CHANNEL_ID"] = CHANNEL[1]
    try:
        client = smp._client()
        target, where = CHANNEL[1], CHANNEL[0]
        text = header
        if args.dm:
            users = ",".join(u.strip() for u in args.dm.split(",") if u.strip())
            target = client.conversations_open(users=users)["channel"]["id"]
            where = "DM to {}".format(users)
            # Say plainly that this is a preview — a DM that looks exactly
            # like the real post is otherwise easy to mistake for the feed
            # having already gone live.
            text = (header + "\n_Preview — this is what would post to "
                    "{} every morning. Nothing has been posted to the "
                    "channel._".format(CHANNEL[0]))
        if args.note:
            text = text + "\n" + args.note
        resp = client.chat_postMessage(channel=target, text=text)
        ts = resp["ts"]
        # Workbook first — the overall log plus a tab per rep plus the payout
        # grid. Then the image, which Slack renders inline so the numbers are
        # readable without opening anything. Same pairing as the Fiber post.
        client.files_upload_v2(
            channel=target, thread_ts=ts, file=str(out_xlsx),
            filename=out_xlsx.name, title=out_xlsx.stem,
            initial_comment="📦 BOX Order Log — overall log + a tab per rep",
        )
        client.files_upload_v2(
            channel=target, thread_ts=ts, file=str(out_png),
            filename=out_png.name, title=out_png.stem,
            initial_comment="💵 Payout — last week & this week",
        )
    except Exception as exc:
        print("✗ Slack post failed: {}".format(exc), file=sys.stderr)
        traceback.print_exc()
        return 1

    print("\n✅ Posted to {}".format(where))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
