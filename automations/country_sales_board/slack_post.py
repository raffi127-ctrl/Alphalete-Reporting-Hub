"""Country Sales Board — Slack screenshot DM.

Screenshots the Country Sales Board and sends it as ONE shared Slack GROUP DM
(from Lucy) with all recipients in a single thread — the same path and the same
shape as all_campaigns_board.slack_post, which this is modelled on. Exact-sheet
render via the Sheets PDF export; no browser.

WHAT IT CAPTURES — and why it is NOT one range. The All Campaigns tab is small
enough to screenshot end to end; this one is not. It runs to row 310 and column
BC (54 cols), because the leaderboard carries 52 weeks of frozen history. A
full-tab render is one unreadable postage stamp, and a single contiguous range
covering everything would drag in the WE history stack nobody reads in an
email. So we render THREE blocks and stitch them into one image, in tab order:

  1. THE BOARD — row 1 through the leaderboard's TOTALS row, cols A..J:
     title + Product Summary + Current vs Prior (Mon..Sun and Grand Total,
     which is why it reaches column J — stopping at H would cut Sunday and the
     Grand Total off the summary), then the full rep ranking with the live week
     in col C and the 7 most recent frozen weeks beside it for trend.

  2. THE DAILY SALES BREAKDOWN — the day block ('Fiber - All Units'), every rep
     by day with the running week total and their last two weeks, cols A..L
     (Eve 2026-07-31: the draft had the summary and the deltas but not the raw
     per-day numbers they are computed from). See `daily_range`.

  3. THE DELTA UNITS CHART — the per-rep 'Total for week' triplet plus ALL
     SEVEN DAYS, each as This week / Last week / Delta (Eve 2026-07-27: the
     first version omitted this block entirely and she asked for every day).
     Columns B..Z; anything narrower drops days off the right.

All three blocks are located by LABEL every run — the leaderboard by its header,
the day block by the finder the fill itself writes through, the delta box by
org_sales_board's own find_delta_tables — so an inserted row or a new rep never
silently crops the image. [[feedback_no_hardcoded_columns]]

HISTORY_WEEKS is the one display choice left as a constant: how many frozen
leaderboard weeks to show beside the live one.

Dry-run by default (builds the PNG, resolves recipients, sends nothing);
`--post` actually delivers the DM.

Usage:
  python -m automations.country_sales_board.slack_post            # dry-run
  python -m automations.country_sales_board.slack_post --post     # send the DM
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board.screenshot_email import (
    _export_png, _access_token, stitch_vertical, column_pixels, _range_width_px,
)
from automations.shared import slack_metrics_post as smp
from automations.country_sales_board.run import SHEET_ID, PROD_TAB, CENTRAL

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TARGET_TAB = PROD_TAB                 # 'Country Sales Board' — the real tab
TITLE_PREFIX = "Country Sales Board"
HISTORY_WEEKS = 7                     # frozen leaderboard weeks shown beside the live one
STITCH_GAP_PX = 28                    # white gutter between the two stitched blocks

# Slack user IDs (not names) so delivery never depends on the bot having the
# users:read scope. Name in the comment for readability. This list is
# DELIBERATELY SHORTER than all_campaigns_board's five (Eve 2026-07-27): this
# board goes to Rafael, Maud and Evelyn only — no Carlos, no Megan.
RECIPIENTS = [
    "U045Z8N0ZQC",   # Rafael Hidalgo (raffi127@gmail.com)
    "U045USN7NCD",   # Maud Miller (maudmiller4@gmail.com)
    "U088E2KJEV8",   # Evelyn Sobrino
]
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "country_sales_board"


def report_date(today: dt.date | None = None) -> dt.date:
    """The day the DM is REPORTING ON — yesterday.

    The fill only writes COMPLETED days (strictly before today), so the last day
    carrying numbers is always yesterday. Titling the message with the run date
    would date it a day ahead of the sales it shows (Eve 2026-07-27). Anchored to
    America/Chicago, not the machine clock — the mini and Eve's box are in
    different zones and a UTC-evening run would otherwise title itself with the
    wrong day. [[project_central-time-for-texas-reports]]"""
    today = today or dt.datetime.now(CENTRAL).date()
    return today - dt.timedelta(days=1)


def title_for(day: dt.date) -> str:
    """'Country Sales Board 7.26' — month.day, unpadded, matching the WE labels
    the board itself uses in column A ('WE 7.19')."""
    return f"{TITLE_PREFIX} {day.month}.{day.day}"


def _find_ws(sh, title: str = TARGET_TAB):
    want = title.strip().lower()
    try:
        return next(w for w in sh.worksheets() if w.title.strip().lower() == want)
    except StopIteration:
        raise ValueError(f"Tab {title!r} not found in the workbook.") from None


def _pick_client(prefer_bot: bool = False):
    """Send as LUCY via the provisioned 'Lucy Reporting' USER token
    (slack-user-token) — the same xoxp token every metrics post, leaders_call
    and raf_captainship_bonus already use. Returns (client, as_bot).

    THIS IS NOT A FALLBACK. The separate bot-app token (SLACK_BOT_TOKEN) was
    never created on the mini, so the old 'try the bot, warn, drop to the user
    token' path printed a SlackPostError on every single run and made a working
    send read like a broken one — which is exactly how we spent 2026-07-27
    believing these DMs came from a personal account. They come from Lucy: the
    user token IS Lucy (confirmed by Eve off the delivered DM). Naming that
    outright, the way leaders_call and raf_captainship_bonus do, is the whole
    point. [[project_country-sales-board]]

    `prefer_bot` is for a machine where the bot app HAS been seeded (Lucy 2) and
    someone deliberately wants the DM to come from the app instead."""
    if prefer_bot:
        try:
            return smp._bot_client(), True
        except Exception as e:
            print(f"  --as-bot asked for the bot app but no bot token is on "
                  f"this machine ({type(e).__name__}) — sending as Lucy "
                  f"(user token) instead")
    return smp._client(), False


def daily_range(grid) -> str:
    """The DAILY SALES BREAKDOWN box — the per-rep day block.

    Eve 2026-07-31: the draft went out with the board and the delta chart but
    without this, which is the one place the raw per-day numbers live. The
    block is col-A label 'Fiber - All Units', a weekday header row, the
    day-of-month row under it, ~75 rep rows and a Totals row.

    Columns A..L, and L is not optional: A is the rank, B the name, C..I the
    seven days, J the running week total, and K/L each rep's last-week and
    previous-week totals — stopping at J would show the week with nothing to
    compare it against, which is the same complaint that put the delta chart
    in this image in the first place.

    Located by LABEL via the same finder the fill writes through, so the render
    and the write can never disagree about where the block is."""
    from automations.org_sales_board.fill_section import find_daily_section
    from automations.org_sales_board.rollover import a1col
    from automations.country_sales_board.fill import BLOCK_LABEL

    a = find_daily_section(grid, BLOCK_LABEL)
    last_col = a.running_total_col + 2          # J -> L (last / previous week)
    return f"A{a.header_row}:{a1col(last_col)}{a.totals_row}"


def capture_ranges(grid) -> list[tuple[str, str]]:
    """The [(name, A1 range)] to render, found by LABEL so an inserted row can't
    crop them: the board, the daily sales breakdown, the delta units chart — in
    the order they appear on the tab."""
    from automations.org_sales_board import rollover as org_ro
    from automations.org_sales_board.rollover import a1col
    from automations.country_sales_board import rollover as cr

    lb = cr.find_leaderboard(grid)
    out = [("board", f"A1:{a1col(2 + 1 + HISTORY_WEEKS)}{lb['totals_row']}")]

    # The daily breakdown must never take the whole image down with it: the
    # board and the delta chart are still worth sending if this one block
    # can't be located.
    try:
        out.append(("daily", daily_range(grid)))
    except Exception as e:                                  # noqa: BLE001
        print(f"  ⚠ daily sales breakdown not located ({type(e).__name__}: {e})"
              f" — sending the board without it")

    tables = org_ro.find_delta_tables(grid)
    if not tables:
        return out
    # The delta block's own range derivation lives beside find_delta_tables, so
    # this board and the All Units board can't drift apart on it. It already
    # trims the days that haven't happened; the email paints it at WIDE_PX.
    out.append(("delta", org_ro.delta_block_range(grid, tables[0])))
    return out


def render_parts(tab: str = TARGET_TAB, rngs: list[str] | None = None
                 ) -> tuple[list[tuple[str, Path, int]], str]:
    """Render each block to its OWN PNG. [(name, path, sheet_px)], plus the
    ranges joined for logging.

    `sheet_px` is how wide the block is ON THE SHEET. The email scales every
    image against the widest block so one sheet pixel is the same size in all of
    them; without it the narrow board block would be blown up to the width of the
    delta chart and its text would come out nearly twice the size.

    This is what the EMAIL uses. Stitching the blocks pads the narrow ones out to
    the width of the 25-column delta chart, so in a 900px mail column the board
    and the daily table were painted at ~75% of the space available to them and
    the numbers came out unreadable (Eve 2026-07-31). One image per block, one
    table row per image, and each gets the full column."""
    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh, tab)
    blocks = (capture_ranges(ws.get_all_values()) if rngs is None
              else [(f"block{i}", r) for i, r in enumerate(rngs)])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    colpx = column_pixels(sh, ws.id)
    parts = []
    for name, rng in blocks:
        p = OUT_DIR / f"country_{name}.png"
        # spreadsheet_id is REQUIRED here: _export_png defaults to the ORG
        # board's workbook, and this tab lives in ATT Program - Focus Report.
        _export_png(ws.id, rng, p, token, spreadsheet_id=SHEET_ID)
        parts.append((f"country_{name}", p, _range_width_px(colpx, rng)))
    return parts, " + ".join(r for _n, r in blocks)


def build_pngs(tab: str = TARGET_TAB, rngs: list[str] | None = None
               ) -> tuple[list[tuple[str, Path, int]], str]:
    """Per-block images, for the EMAIL."""
    return render_parts(tab, rngs)


def build_png(tab: str = TARGET_TAB,
              rngs: list[str] | None = None) -> tuple[Path, str]:
    """ONE stitched image, for the SLACK DM — which takes a single file."""
    parts, rng = render_parts(tab, rngs)
    out = OUT_DIR / "country_sales_board.png"
    stitch_vertical([p for _n, p, _w in parts], out, gap=STITCH_GAP_PX)
    return out, rng


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="actually send the DM (default: dry-run, no send)")
    ap.add_argument("--only", default="",
                    help="comma-separated Slack user id(s) to send to INSTEAD "
                         "of the full recipient list (for a targeted test)")
    ap.add_argument("--as-bot", action="store_true",
                    help="send from the Slack BOT APP instead of Lucy's user "
                         "token (only on a machine where the bot is seeded)")
    ap.add_argument("--tab", default=TARGET_TAB,
                    help="tab to screenshot (default: the real board)")
    ap.add_argument("--range", dest="rng", default=None,
                    help="comma-separated A1 range(s) to capture, overriding "
                         "the label-driven board + delta-chart pair")
    ap.add_argument("--date", metavar="YYYY-MM-DD",
                    help="override the RUN date; the title still reports the "
                         "day before it (testing/backfill)")
    args = ap.parse_args(argv)
    dry = not args.post

    # The DM is titled with the day it REPORTS ON — yesterday — because the fill
    # only writes completed days.
    today = dt.date.fromisoformat(args.date) if args.date else None
    title = title_for(report_date(today))

    recipients = ([r.strip() for r in args.only.split(",") if r.strip()]
                  if args.only else RECIPIENTS)
    if args.only:
        print(f"  --only override: sending to {recipients} (test)")

    rngs = ([r.strip() for r in args.rng.split(",") if r.strip()]
            if args.rng else None)
    png, rng = build_png(args.tab, rngs)
    print(f"screenshot {args.tab!r} {rng} → {png} "
          f"({png.stat().st_size // 1024} KB)")

    # ONE shared group DM (mpim) with ALL recipients in a single thread — NOT
    # separate individual DMs. Needs the Lucy bot's mpim:write scope;
    # dm_users_with_file falls back to individual DMs only if that scope is
    # missing (surfaced via mode='individual_dms').
    _, as_bot = _pick_client(prefer_bot=args.as_bot)
    print(f"  sending as {'the Slack bot app' if as_bot else 'Lucy (user token)'}")
    print(f"{'DRY-RUN (no send)' if dry else 'SENDING group DM'} to {recipients} "
          f"— title {title!r}")
    resp = smp.dm_users_with_file(
        png, users=recipients, comment=title,
        file_name=f"{title}.png", dry_run=dry, as_bot=as_bot)
    print(f"  result: {resp}")
    if not dry and resp.get("mode") == "individual_dms":
        print("  ⚠ fell back to INDIVIDUAL DMs — the group-DM open failed. A "
              "SINGLE recipient is the usual cause: one user opens an IM, not "
              "an mpim, so it needs im:write rather than mpim:write.")
    # A FAILED SEND MUST FAIL THE RUN. dm_users_with_file swallows Slack errors
    # and reports them in the payload, so returning 0 unconditionally made a
    # send that delivered nothing get recorded as DONE — the orchestrator's
    # failure alert would never fire and nobody would know the DM stopped going
    # out. Caught 2026-07-27 by a proving send that failed on missing_scope and
    # still exited 0.
    # Partial delivery counts as failure too: the individual-DM fallback reports
    # ok=True if ANY recipient got it, so two of three silently missing out
    # would otherwise look clean.
    failed = [r.get("user_id") for r in resp.get("results", [])
              if not r.get("ok")]
    if not dry and (not resp.get("ok", False) or failed):
        print(f"  ❌ send FAILED{f' for {failed}' if failed else ''} — "
              f"not everyone got it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
