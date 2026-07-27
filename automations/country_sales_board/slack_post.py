"""Country Sales Board — Slack screenshot DM.

Screenshots the Country Sales Board and sends it as ONE shared Slack GROUP DM
(from Lucy) with all recipients in a single thread — the same path and the same
shape as all_campaigns_board.slack_post, which this is modelled on. Exact-sheet
render via the Sheets PDF export; no browser.

WHAT IT CAPTURES — and why it is NOT one range. The All Campaigns tab is small
enough to screenshot end to end; this one is not. It runs to row 310 and column
BC (54 cols), because the leaderboard carries 52 weeks of frozen history. A
full-tab render is one unreadable postage stamp, and a single contiguous range
covering both blocks would drag in the ~135 rows of day block and WE history
sitting between them. So we render TWO blocks and stitch them into one image:

  1. THE BOARD — row 1 through the leaderboard's TOTALS row, cols A..J:
     title + Product Summary + Current vs Prior (Mon..Sun and Grand Total,
     which is why it reaches column J — stopping at H would cut Sunday and the
     Grand Total off the summary), then the full rep ranking with the live week
     in col C and the 7 most recent frozen weeks beside it for trend.

  2. THE DELTA UNITS CHART — the per-rep 'Total for week' triplet plus ALL
     SEVEN DAYS, each as This week / Last week / Delta (Eve 2026-07-27: the
     first version omitted this block entirely and she asked for every day).
     Columns B..Z; anything narrower drops days off the right.

Both blocks are located by LABEL every run — the leaderboard by its header, the
delta box by org_sales_board's own find_delta_tables — so an inserted row or a
new rep never silently crops the image. [[feedback_no_hardcoded_columns]]

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
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board.screenshot_email import _export_png, _access_token
from automations.shared import slack_metrics_post as smp
from automations.country_sales_board.run import SHEET_ID, PROD_TAB

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TARGET_TAB = PROD_TAB                 # 'Country Sales Board' — the real tab
TITLE = "Country Sales Board"
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


def capture_ranges(grid) -> list[str]:
    """The A1 ranges to render, found by LABEL so an inserted row can't crop
    them: [the board, the delta units chart]."""
    from automations.org_sales_board import rollover as org_ro
    from automations.org_sales_board.rollover import a1col
    from automations.country_sales_board import rollover as cr

    lb = cr.find_leaderboard(grid)
    board = f"A1:{a1col(2 + 1 + HISTORY_WEEKS)}{lb['totals_row']}"

    tables = org_ro.find_delta_tables(grid)
    if not tables:
        return [board]
    t = tables[0]
    hdr = t["header_row"]                      # the This week/Last week/Delta row
    # Each day is a 3-col triplet starting at its 'This week' column, so the
    # block's last column is the final day's Delta.
    last_col = max(t["this_cols"]) + 2
    last_row = max(t["data_rows"]) if t.get("data_rows") else hdr

    # find_delta_tables stops at the first row with no NAME in col B — which is
    # exactly what the chart's country-wide TOTALS row looks like (blank col B,
    # then 7409 / 7286 / 1.69% and the per-day totals). Dropping it would cut the
    # single most useful line of the block, so pull it back in: one row past the
    # last rep, blank name, but numbers in the triplet columns.
    if last_row + 1 <= len(grid):
        nxt = grid[last_row]
        name = str(nxt[1]).strip() if len(nxt) > 1 else ""
        vals = [str(nxt[c - 1]).strip() for c in range(3, last_col + 1)
                if c - 1 < len(nxt)]
        if not name and any(vals):
            last_row += 1

    # hdr - 1 is the day-name row above it ('Monday'…'Sunday') — include it or
    # the triplets have no labels.
    delta = f"B{hdr - 1}:{a1col(last_col)}{last_row}"
    return [board, delta]


def _stitch(paths: list[Path], out: Path) -> Path:
    """Stack the rendered blocks into ONE image, left-aligned on a white canvas
    sized to the widest. Deliberately PADS rather than SCALES — the two blocks
    render at different widths (10 cols vs 25), and resampling either one to
    match would soften text that is already small in the delta chart."""
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    if len(ims) == 1:
        ims[0].save(out)
        return out
    w = max(i.width for i in ims)
    h = sum(i.height for i in ims) + STITCH_GAP_PX * (len(ims) - 1)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    y = 0
    for im in ims:
        canvas.paste(im, (0, y))
        y += im.height + STITCH_GAP_PX
    canvas.save(out)
    return out


def build_png(tab: str = TARGET_TAB,
              rngs: list[str] | None = None) -> tuple[Path, str]:
    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh, tab)
    if rngs is None:
        rngs = capture_ranges(ws.get_all_values())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "country_sales_board.png"
    token = _access_token()
    parts = []
    for i, rng in enumerate(rngs):
        # spreadsheet_id is REQUIRED here: _export_png defaults to the ORG
        # board's workbook, and this tab lives in ATT Program - Focus Report.
        p = OUT_DIR / f"_part{i}.png"
        _export_png(ws.id, rng, p, token, spreadsheet_id=SHEET_ID)
        parts.append(p)
    _stitch(parts, out)
    return out, " + ".join(rngs)


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
    args = ap.parse_args(argv)
    dry = not args.post

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
          f"— title {TITLE!r}")
    resp = smp.dm_users_with_file(
        png, users=recipients, comment=TITLE,
        file_name=f"{TITLE}.png", dry_run=dry, as_bot=as_bot)
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
