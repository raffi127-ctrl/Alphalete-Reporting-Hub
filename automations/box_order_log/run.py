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

# Where the thread posts. Each entry gets its own parent + replies (a Slack
# thread can't span channels). Same two rooms as the Sales Boards thread
# (sales_boards/run.py TARGETS), and Lucy is a member of both.
#
# #a-players-b2b is NEW as of 2026-08-15, not a restoration. Carlos said the
# order log "is currently posted on Alphalete GP sales and A Players B2B" — it
# never had been: Evelyn couldn't find it, nothing in this repo had ever pointed
# the order log at that channel, and the only Lucy posts in that room were the
# Vantura Production boards, the tracker screenshots, dispositions and
# b2b_metrics (he was remembering the Box TRACKER images). Megan took the
# question back to him and he asked for the whole thread there too, so this is
# what he wants, not what he assumed he already had.
TARGETS = [
    ("#alphalete-gp-sales", "C07J46MQNUX"),
    ("#a-players-b2b", "C0AJQA8P716"),
]

# The parent message lists what's in the thread, one emoji-led line per
# attachment, matching the other Lucy threads in this channel (Megan
# 2026-07-19). Defined once and reused as the reply captions so the header and
# the attachments can never drift apart.
WORKBOOK_LINE = "\U0001F4E6 Overall log + a tab per rep"
# Megan 2026-08-15: the trailing "— last week & this week" came off to clean the
# header up. Each line is just the name of the thing now; the images say the
# rest. (The OWNER EMAIL keeps its own longer wording — that copy is separately
# Megan-approved and doesn't read from here.)
PAYOUT_LINE = "\U0001F4B5 Accepted by supplier"
# Third attachment (Carlos 2026-08-15): the Box Tier Bonus - Rep Level board.
# The line itself lives in tier_bonus.py, next to the capture it describes.

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _pull(dest: Path, verbose: bool = True, view_url: str = "",
          crosstab_sheet: str = "", today: Optional[dt.date] = None,
          tier_owner: str = "", tier_dest: Optional[Path] = None):
    """Download the order-log crosstab. Returns (csv_path, tier_png, tier_note).

    tier_png is None when the board couldn't be captured, and tier_note then
    carries the reason; when tier_png IS set, a non-empty tier_note is a
    clipping warning about the image (both are surfaced, never swallowed).

    When `tier_owner` is set the Box Tier Bonus board is captured in the SAME
    browser session, right after the crosstab — a second session would mean a
    second Chrome launch and a second SSO round-trip for one screenshot. The
    tier capture never breaks the pull: a flake there comes back as a message
    and the log still posts (see tier_bonus.capture_quietly).
    """
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright, tableau_session)
    from . import window
    # Force the Start/End Date filters to a wide window every run. The SCI
    # source view's saved date range drifts (found pinned to a 2-day window
    # 2026-08-01, which truncated the feed to 2 reps) and we can't stop it, so
    # we override it at pull time. See window.py.
    start, end = window.default_window(today)
    hook = window.date_window_hook(start, end, verbose=verbose)
    with tableau_session(verbose=verbose) as page:
        out = download_crosstab_patchright(
            view_url or VIEW_URL, crosstab_sheet or CROSSTAB_SHEET, dest,
            verbose=verbose, page=page, pre_export=hook)
        tier_png, tier_note = None, ""
        if tier_owner and tier_dest is not None:
            from . import tier_bonus
            if verbose:
                print("\n-> Box Tier Bonus board for {}".format(tier_owner),
                      flush=True)
            tier_png, tier_note = tier_bonus.capture_quietly(
                tier_dest, tier_owner, page=page, day=today, verbose=verbose)
        return out, tier_png, tier_note


def _post_thread(client, channel: str, text: str, xlsx_path: Path,
                 payout_path: Path, tier_path: Optional[Path],
                 tier_line: str) -> str:
    """Post one dated thread — parent, then its attachments — and return its ts.

    One call per destination: Slack threads don't span channels, so Carlos's two
    rooms each get their own parent and their own replies.
    """
    ts = client.chat_postMessage(channel=channel, text=text)["ts"]
    # Workbook first — the overall log plus a tab per rep plus the payout grid.
    # Then the payout image, which Slack renders inline so the numbers are
    # readable without opening anything. Same pairing as the Fiber post. Last
    # the tier board, so the thread reads log -> pay -> where each rep sits on
    # the ladder; it goes in only when we have it, matching the header.
    client.files_upload_v2(
        channel=channel, thread_ts=ts, file=str(xlsx_path),
        filename=xlsx_path.name, title=xlsx_path.stem,
        initial_comment=WORKBOOK_LINE,
    )
    client.files_upload_v2(
        channel=channel, thread_ts=ts, file=str(payout_path),
        filename=payout_path.name, title=payout_path.stem,
        initial_comment=PAYOUT_LINE,
    )
    if tier_path:
        client.files_upload_v2(
            channel=channel, thread_ts=ts, file=str(tier_path),
            filename=tier_path.name, title=tier_path.stem,
            initial_comment=tier_line,
        )
    return ts


def _describe(sales, stats) -> str:
    from . import clean
    weeks, statuses, counts = clean.week_counts(sales)
    lines = [
        "  {:>5} raw rows from Tableau".format(stats.get("raw_rows", 0)),
        "  {:>5} dropped (Draft — tablet quotes, never a sale)".format(
            stats.get("dropped_never_a_sale", 0)),
        "  {:>5} pipeline duplicates collapsed".format(
            stats.get("collapsed_rows", 0)),
    ]
    if stats.get("dropped_dead"):
        # Names the sub-statuses from the constant so the two can't drift.
        lines.append("  {:>5} dropped (final state {} — not a sale)".format(
            stats["dropped_dead"],
            " or ".join(clean.DEAD_VERIFICATION_SUBS)))
    if stats.get("dropped_never_reached_tpv"):
        lines.append("  {:>5} dropped (cancelled/rejected before ever reaching "
                     "TPV — not sales)".format(stats["dropped_never_reached_tpv"]))
    lines.append("  {:>5} real sales".format(stats.get("sales", 0)))
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
    from . import tier_bonus          # names the default owner in --help
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
    ap.add_argument("--require-fresh", action="store_true",
                    help="EARLY pass only: if the pulled extract hasn't reached "
                         "the latest completed day, skip the post (exit 3, no "
                         "marker) so the 8:30 fallback posts once the data's in. "
                         "Makes the post data-timed instead of clock-timed; 8:30 "
                         "runs WITHOUT this flag, so it stays the fail-open floor.")
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
    # --- per-office overrides (onboarded B2B offices) ---------------------
    # Default (no overrides) = Carlos's existing standalone post, byte-identical.
    ap.add_argument("--view-url", metavar="URL",
                    help="override the Tableau view to pull — per-office runs point "
                         "at the TEAM ALLEXP order-log view (all offices)")
    ap.add_argument("--crosstab-sheet", metavar="NAME",
                    help="override the crosstab worksheet name (default 'Order Log')")
    ap.add_argument("--owner-office", metavar="VALUE",
                    help="slice the export to ONE office by its exact 'Owner & "
                         "Office' value — the per-office isolation filter")
    ap.add_argument("--channel", metavar="CID",
                    help="override the Slack channel id to post the thread to")
    ap.add_argument("--channel-name", metavar="#name",
                    help="display name for --channel (logs + preview text)")
    # --- Box Tier Bonus board (Carlos 2026-08-15) ------------------------
    ap.add_argument("--tier-owner", metavar="NAME",
                    help="Owner Name to slice the Box Tier Bonus - Rep Level "
                         "board to. Defaults to {} on Carlos's standalone run; "
                         "a per-office run (--owner-office) has NO default and "
                         "skips the board unless this names that office's owner "
                         "— posting Carlos's tier board to another office's "
                         "channel would be worse than posting none.".format(
                             tier_bonus.DEFAULT_OWNER))
    ap.add_argument("--no-tier", action="store_true",
                    help="leave the Box Tier Bonus board out of the thread")
    args = ap.parse_args(argv)

    # Carlos's run (no --owner-office) gets the board by default; every other
    # office must name its own owner. See --tier-owner above.
    tier_owner = "" if args.no_tier else (
        args.tier_owner or ("" if args.owner_office else tier_bonus.DEFAULT_OWNER))

    # Resolve the post destinations once. A --channel override (per-office runs)
    # means EXACTLY that one channel; Carlos's own run posts to both of his.
    if args.channel:
        targets = [(args.channel_name or args.channel, args.channel)]
    else:
        targets = list(TARGETS)
    chan_id = targets[0][1]
    chan_name = " + ".join(name for name, _ in targets)

    verbose = not args.quiet
    today = dt.date.today()
    started_at = dt.datetime.now()

    def _report_to_hub(started, loud):
        """Tell the Hub this pass finished.

        Only for runs the Hub didn't start itself — a Hub-launched run is
        already logged by dashboard.py, and double-logging would let the
        card's daily_runs counter hit its target early and go green before
        the second pass. HUB_RUN=1 is set by the dashboard's launcher.
        """
        if os.environ.get("HUB_RUN"):
            return
        from automations.shared import hub_activity
        ok = hub_activity.log_completed("box-order-log", "BOX Order Log")
        if loud and not ok:
            print("  (couldn't record this run on the Hub — tile may not "
                  "turn green; the report itself is fine)")

    from . import clean, render

    # ---- 1. get the crosstab (+ the tier board, same session) -----------
    tier_png, tier_note = None, ""
    if args.from_file:
        src = Path(args.from_file)
        if not src.exists():
            print("✗ no such file: {}".format(src), file=sys.stderr)
            return 2
        if tier_owner:
            # --from-file skips the pull, so there's no open session to ride;
            # the board still gets captured (it's live data either way), just
            # in a session of its own.
            tier_png, tier_note = tier_bonus.capture_quietly(
                OUTPUT_DIR, tier_owner, day=today, verbose=verbose)
    else:
        src = OUTPUT_DIR / "box_order_log_{}.csv".format(today.isoformat())
        try:
            _, tier_png, tier_note = _pull(
                src, verbose=verbose, view_url=(args.view_url or ""),
                crosstab_sheet=(args.crosstab_sheet or ""), today=today,
                tier_owner=tier_owner, tier_dest=OUTPUT_DIR)
        except Exception as exc:
            print("✗ Tableau pull failed: {}".format(exc), file=sys.stderr)
            traceback.print_exc()
            return 1

    # ---- 2. collapse ----------------------------------------------------
    sales, stats = clean.load(src, owner_office=(args.owner_office or ""))
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

    # NB: `window` above is the human date-range string, so the module has to
    # come in under another name here.
    from . import window as window_mod
    _capped = window_mod.capped_pull_warning(
        max(dated) if dated else None, today)
    if _capped:
        print("\n  " + _capped, flush=True)

    # Freshness gate for the EARLY (7:00) pass. Box's extract lands ~7-8am, so
    # the 7:00 clock is a guess — if it fires before the refresh, it posts a
    # stale log and the 8:30 fallback won't re-post (marker set). Instead: if
    # --require-fresh and the newest sale hasn't reached the latest COMPLETED
    # day, DON'T post — exit 3 so the wrapper leaves the marker unset and the
    # 8:30 pass (which omits --require-fresh) posts once the data is in. 8:30
    # stays the fail-open floor: a genuinely late day or a no-prior-day-sales
    # day (e.g. a Monday with no Sunday sales) still posts there. Data-timed,
    # not clock-timed — and never a missed day.
    if args.require_fresh and args.post:
        expected = today - dt.timedelta(days=1)      # prior day's finalised sales
        newest = max(dated) if dated else None
        if newest is None or newest < expected:
            print("box extract not fresh yet (newest sale {}, need >= {}) — "
                  "deferring the post to the 8:30 fallback".format(
                      newest, expected), flush=True)
            # Still tell the Hub this pass RAN. A deferral is a completed pass
            # that deliberately did nothing — "ran and had nothing to post" is
            # success, same rule post_watch.py applies to its done-markers. Skip
            # it and the card counts 1 of its 2 daily_runs and sits amber all
            # day on every not-fresh-at-7 morning (8/3, 8/10, 8/16…), even
            # though the 8:30 pass posted normally. Reported BEFORE the sheet
            # merge on purpose: this pass writes nothing either way.
            _report_to_hub(started_at, verbose)
            return 3

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
                   subtitle="Accepted & Cancelled are for that week — pay "
                            "follows the week after. Still Open = deals not "
                            "yet accepted, any week.")
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
    # The header lists exactly what's in the thread — so the tier line goes in
    # only when the board is actually in hand. A capture that failed is called
    # out below instead of being quietly left off.
    attach_lines = [WORKBOOK_LINE, PAYOUT_LINE]
    if tier_png:
        attach_lines.append(tier_bonus.TIER_LINE)
    header = "*BOX Order Log — {}*\n{}".format(
        today.strftime("%B %d, %Y"), "\n".join(attach_lines))
    if not args.post:
        _report_to_hub(started_at, verbose)
        if verbose:
            print("\n  Not posted to Slack. To post the PDF to {}:".format(
                chan_name))
            print("    header : {}".format(header))
            if tier_png:
                print("    tier   : {}{}".format(
                    tier_png, "  ⚠ " + tier_note if tier_note else ""))
            elif tier_owner:
                print("    tier   : NOT captured — {}".format(tier_note))
            print("    re-run with --post")
        return 0

    # HARD GATE (2026-08-12): don't POST a clearly-capped pull. The filter
    # release is best-effort and can miss on a bad viz load, capping the export
    # to a stale ID snapshot; posting it puts numbers that understate reality in
    # front of the whole channel. Skip the post and fail loudly instead — the
    # Sheet merge already ran above and keeps its newer rows, so nothing good is
    # lost. Same net as run_owner's send gate. See window.should_block_send.
    _block = window_mod.should_block_send(max(dated) if dated else None, today)
    if _block:
        print("\n✗ NOT posting to {} — {}".format(chan_name, _block),
              file=sys.stderr, flush=True)
        # Suppressed post = nothing in the channel, so ping #claudecorrections
        # so it's heard, not silently missed. Never let it break the exit.
        try:
            from automations.shared import section_drop_alert as sda
            _newest = max(dated) if dated else None
            _behind = (today - _newest).days if _newest else None
            _detail = ("newest sale {}, {} days behind".format(_newest, _behind)
                       if _newest else "no dated sales at all")
            # ONE alert for the whole BOX family (Eve 2026-08-14). Carlos's run
            # here and the per-owner runs on the mini share this report_id on
            # purpose: section_drop_alert keys its incident thread off it, so
            # three offices failing the same morning land as three lines in ONE
            # thread instead of three near-identical 🚨 posts — which is what
            # happened on 8/14 and made one stuck export read as three broken
            # reports. Whoever fails first opens it; the rest reply. So the
            # OFFICE has to be inside the line: the headline can no longer say
            # whose numbers are missing.
            sda.alert(report_id="box-order-log",
                      failed=["Carlos Hidalgo — {}".format(_detail)],
                      kind="capped", day=today)
        except Exception:
            pass
        return 3

    try:
        from automations.shared import slack_metrics_post as smp
    except Exception as exc:
        print("✗ Slack helper unavailable: {}".format(exc), file=sys.stderr)
        return 1

    os.environ["METRICS_CHANNEL_ID"] = chan_id
    # Each channel is a thread of its own: parent, then workbook, payout and the
    # tier board as replies. A DM preview collapses to a single destination.
    posts = list(targets)
    try:
        client = smp._client()
        text = header
        if args.dm:
            users = ",".join(u.strip() for u in args.dm.split(",") if u.strip())
            posts = [("DM to {}".format(users),
                      client.conversations_open(users=users)["channel"]["id"])]
            # Say plainly that this is a preview — a DM that looks exactly
            # like the real post is otherwise easy to mistake for the feed
            # having already gone live.
            text = (header + "\n_Preview — this is what would post to "
                    "{} every morning. Nothing has been posted to the "
                    "channel._".format(chan_name))
        if args.note:
            text = text + "\n" + args.note
        posted, failed_channels = [], []
        for name, target in posts:
            # Per-channel try/except on purpose: aborting the loop after channel
            # one posted would leave a live thread AND a non-zero exit, and the
            # 8:30 fallback would then post that channel a SECOND time. So a
            # channel that fails is recorded and the rest still go out.
            try:
                _post_thread(client, target, text, out_xlsx, out_png, tier_png,
                             tier_bonus.TIER_LINE)
            except Exception as exc:                      # noqa: BLE001
                failed_channels.append("{} — {}: {}".format(
                    name, type(exc).__name__,
                    str(exc).splitlines()[0][:160]))
                print("  ✗ post to {} failed: {}".format(name, exc),
                      file=sys.stderr, flush=True)
                continue
            posted.append(name)
            if verbose:
                print("  posted to {}".format(name), flush=True)
        where = " + ".join(posted) if posted else "nowhere"
    except Exception as exc:
        print("✗ Slack post failed: {}".format(exc), file=sys.stderr)
        traceback.print_exc()
        return 1

    if not posted:
        # Nothing landed anywhere — the loudest case there is, and the one the
        # channel can't notice for itself (no thread = nothing to look at).
        if not args.dm:
            try:
                from automations.shared import section_drop_alert as sda
                sda.alert(report_id="box-order-log", failed=failed_channels,
                          kind="section", day=today)
            except Exception:
                pass
        print("✗ the thread posted to NO channel — {}".format(
            "; ".join(failed_channels)), file=sys.stderr)
        return 1
    if failed_channels:
        # Live in one room, missing from another: looks completely fine to
        # anyone reading the channel that DID get it. Say so where dropped
        # sections get read, and don't let the alert break the run.
        print("  ⚠ did NOT post to: {}".format("; ".join(failed_channels)),
              file=sys.stderr, flush=True)
        try:
            from automations.shared import section_drop_alert as sda
            sda.alert(report_id="box-order-log", failed=failed_channels,
                      kind="section", day=today)
        except Exception:
            pass
    print("\n✅ Posted to {}".format(where))
    # Two ways the tier board can leave the thread short of the truth: it wasn't
    # captured at all, or it was captured clipped (reps cut off the bottom).
    # Both look FINE in the channel — the log and payout are right there — so
    # neither can be left to a log line nobody reads. Never breaks the run.
    if tier_owner and tier_note:
        if tier_png:
            trouble = "the Box Tier Bonus board may be CUT OFF — {}".format(tier_note)
        else:
            trouble = "posted WITHOUT the Box Tier Bonus board — {}".format(tier_note)
        print("  ⚠ {}".format(trouble), file=sys.stderr, flush=True)
        if not args.dm:
            try:
                from automations.shared import section_drop_alert as sda
                sda.alert(report_id="box-order-log",
                          failed=["{} ({}) — {}".format(
                              tier_bonus.BOARD_NAME, tier_owner, tier_note)],
                          kind="section", day=today)
            except Exception:
                pass
    _report_to_hub(started_at, verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
