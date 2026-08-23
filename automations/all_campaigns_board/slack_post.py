"""All Campaigns Org Sales Board — Slack screenshot DM.

Screenshots the whole 'All Campaigns Org Sales Board' tab (exact-sheet render via
the Sheets PDF export — no browser, same path the ORG board email/Slack use) and
sends it as ONE shared Slack GROUP DM (from Lucy) with the whole recipient list
in a single thread, under the title 'All Campaigns Org Sales Board'.

Dry-run by default (builds the PNG, resolves recipients, sends nothing);
`--post` actually delivers the DMs.

Usage:
  python -m automations.all_campaigns_board.slack_post            # dry-run
  python -m automations.all_campaigns_board.slack_post --post     # send the DMs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key
from automations.org_sales_board.run import SHEET_ID
from automations.org_sales_board.screenshot_email import (
    _export_png, _access_token, stitch_vertical, column_pixels, _range_width_px,
)
from automations.org_sales_board.rollover import a1col
from automations.shared import slack_metrics_post as smp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TARGET_TAB = "All Campaigns Org Sales Board"     # live title has a trailing space
TITLE = "All Campaigns Org Sales Board"
# Slack user IDs (not names) so delivery never depends on the bot having the
# users:read scope — resolved 2026-07-25. Name in the comment for readability.
RECIPIENTS = [
    "U045Z8N0ZQC",   # Rafael Hidalgo (raffi127@gmail.com)
    "U046G04P5LG",   # Carlos Hidalgo (carloshidalgo349@gmail.com)
    "U045USN7NCD",   # Maud Miller (maudmiller4@gmail.com)
    "U04G5HJBGFN",   # Megan Hidalgo (ltdhidalgos@gmail.com)
    "U088E2KJEV8",   # Evelyn Sobrino
]
MAX_COL = 26                                      # A..Z (covers the delta box)
HISTORY_WEEKS = 4     # frozen leaderboard weeks shown beside the live one
DAILY_HISTORY_ROWS = 4   # 'WE m.d' rows kept under the daily block's Totals row
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "all_campaigns_board"


def _find_ws(sh, title=TARGET_TAB):
    want = title.strip().lower()
    return next(w for w in sh.worksheets() if w.title.strip().lower() == want)


def _cell(g, r, c):        # 1-based, like the rest of the render helpers
    return (g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1])
            else "").strip()


def _last_col(g, r0: int, r1: int, cap: int = MAX_COL) -> int:
    """Right-most 1-based column with content across rows r0..r1."""
    last = 1
    for r in range(r0, min(r1, len(g)) + 1):
        row = g[r - 1] if r - 1 < len(g) else []
        for c in range(min(len(row), cap), 0, -1):
            if str(row[c - 1]).strip():
                last = max(last, c)
                break
    return last


def used_range(ws) -> str:
    """A1 through the bottom-right of the report's content (cols A..Z).

    Kept for the `--range` escape hatch and for anything that still wants the
    whole tab in one shot. The DM and the email no longer use it: see
    capture_ranges."""
    g = ws.get_all_values()
    last_row = 0
    last_col = 1
    for r in range(len(g)):
        row = g[r]
        row_has = False
        for c in range(min(MAX_COL, len(row))):
            if str(row[c]).strip():
                row_has = True
                last_col = max(last_col, c + 1)
        if row_has:
            last_row = r + 1
    return f"A1:{a1col(last_col)}{max(last_row, 1)}"


def capture_ranges(grid) -> list[tuple[str, str]]:
    """The tab as [(name, A1 range)], in tab order, each found by LABEL.

    WHY NOT ONE RANGE ANY MORE (Eve 2026-07-31). Rendering A1:Z<end> in a single
    shot makes every block as wide as the WIDEST one — the delta chart, 25
    columns across. The summary and the leaderboard only occupy the left ~40% of
    that, so in an email column they were painted at 40% of the available width
    and the numbers came out unreadable. Rendered separately, each block gets the
    whole 900px column to itself. Nothing is cropped and nothing is stretched;
    they are just no longer forced to share a width.

      1. TOP SUMMARY  — title + Product Summary + Current vs Prior, A1 down to
         the row above the leaderboard header.
      2. LEADERBOARD  — 'AT&T FIBER TEAM' header through TOTALS. Capped at the
         live week + HISTORY_WEEKS frozen ones: this leaderboard GROWS RIGHT one
         column every Tuesday and keeps full history, so an uncapped render gets
         wider (and every block in it smaller) every single week.
      3. DAILY BLOCK  — the 'All Units' day table through its WE-history stack.
      4. DELTA CHART  — the per-rep This week / Last week / Delta triplets for
         all seven days.

    Each block is optional except the summary: a finder that can't locate its
    block logs and is skipped, so one template change can't cost the whole email.
    """
    from automations.all_campaigns_board.rollover import (
        find_leaderboard_block, DAILY_LABEL,
    )
    from automations.org_sales_board import fill_section as fs
    from automations.org_sales_board import rollover as org_ro

    out: list[tuple[str, str]] = []
    lb = find_leaderboard_block(grid)          # raises if the tab is unrecognisable
    lb_hdr = lb["header_row"]

    # 1) everything above the leaderboard header
    if lb_hdr > 1:
        top_end = lb_hdr - 1
        out.append(("summary", f"A1:{a1col(_last_col(grid, 1, top_end))}{top_end}"))

    # 2) the leaderboard, capped so a year of frozen weeks doesn't shrink it
    lb_last = min(lb["last_col"], lb["first_col"] + HISTORY_WEEKS)
    lb_end = lb["totals_row"] or (max(lb["data_rows"]) if lb["data_rows"] else lb_hdr)
    out.append(("leaderboard", f"A{lb_hdr}:{a1col(lb_last)}{lb_end}"))

    # 3) the daily block, through the WE-history rows under its Totals — those
    #    rows are the week-over-week trend and are visible on this tab (unlike the
    #    ORG board's captainship stacks, which are hidden and need unhiding).
    #
    #    CAPPED AT DAILY_HISTORY_ROWS (Eve 2026-08-05). The stack keeps every week
    #    the board has ever closed and grows one row every Tuesday, so an uncapped
    #    render gets taller forever — and the rows nobody reads squeeze the ones
    #    they do. Four back is what she wants to see, matching HISTORY_WEEKS on the
    #    leaderboard above it. Counted in WE ROWS, not rows: a blank spacer row
    #    inside the stack must not eat one of the four.
    #
    #    RIGHT EDGE = running total + 2, i.e. through PREVIOUS WEEK'S TOTALS. The
    #    two columns past it on the tab are 'Campaign' and 'Org Head', which Eve
    #    cut from the email 2026-07-31 — they are routing metadata for the fill,
    #    not numbers anyone reads, and they cost width every other column needs.
    #    Anchored to the running-total column, never a letter, so an inserted day
    #    moves the edge with it. [[feedback_no_hardcoded_columns]]
    try:
        a = fs.find_daily_section(grid, DAILY_LABEL)
        end = a.totals_row
        kept = 0
        for r in range(a.totals_row + 1, min(a.totals_row + 30, len(grid) + 1)):
            lab = (_cell(grid, r, 1) + " " + _cell(grid, r, 2)).strip().lower()
            if lab.startswith("we "):
                end = r
                kept += 1
                if kept >= DAILY_HISTORY_ROWS:
                    break
            elif lab:
                break                      # a non-WE label means the stack ended
        out.append(("daily",
                    f"A{a.header_row}:{a1col(a.running_total_col + 2)}{end}"))
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠ daily block not located ({type(e).__name__}: {e}) — "
              f"sending the board without it")

    # 4) the delta chart — same derivation the Country board uses, from the one
    #    definition next to find_delta_tables. It already trims the days that
    #    haven't happened; the email paints it full-bleed and attaches a
    #    full-size copy (screenshot_email.build_email) since inline it is
    #    unavoidably shrunk — splitting it in two was vetoed (Raf 2026-08-23).
    tables = org_ro.find_delta_tables(grid)
    if tables:
        rng = org_ro.delta_block_range(grid, tables[0])
        # Col A beside the delta chart is its RANK CHAIN — 1..n position
        # formulas added 2026-08-23 (Raf: number the owners so the board says
        # how many it lists). The shared range derivation starts at col B
        # (delta_block_range's contract, which the Country board also uses);
        # widen to col A only when the numbers are actually there, so an
        # unnumbered tab renders exactly as before.
        first_data = tables[0]["data_rows"][0]
        if _cell(grid, first_data, 1).strip():
            rng = "A" + rng.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        out.append(("delta", rng))
    else:
        print("  ⚠ delta units chart not located — sending the board without it")
    return out


def render_parts(rngs: list[str] | None = None
                 ) -> tuple[list[tuple[str, Path, int]], str]:
    """Render each block to its OWN PNG. [(name, path, sheet_px)], plus the
    ranges joined for logging. This is what the email uses — one image per block.

    `sheet_px` is how wide the block is ON THE SHEET. The email scales every
    image against the widest block so one sheet pixel is the same size in all of
    them; without it a narrow block would be blown up to the same width as the
    delta chart and its text would come out nearly twice the size."""
    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh)
    blocks = (capture_ranges(ws.get_all_values()) if rngs is None
              else [(f"block{i}", r) for i, r in enumerate(rngs)])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    token = _access_token()
    colpx = column_pixels(sh, ws.id)
    parts = []
    for name, rng in blocks:
        p = OUT_DIR / f"all_units_{name}.png"
        _export_png(ws.id, rng, p, token)
        parts.append((f"allunits_{name}", p, _range_width_px(colpx, rng)))
    return parts, " + ".join(r for _n, r in blocks)


def build_pngs(rngs: list[str] | None = None
               ) -> tuple[list[tuple[str, Path, int]], str]:
    """Per-block images, for the EMAIL."""
    return render_parts(rngs)


def _pick_client():
    """Send as LUCY via the provisioned 'Lucy Reporting' USER token
    (slack-user-token) — the same xoxp token every metrics post, leaders_call
    and raf_captainship_bonus already use. Returns (client, as_bot).

    THIS IS NOT A FALLBACK. The separate bot-app token (SLACK_BOT_TOKEN) was
    never created on the mini, so the old 'try the bot, warn, drop to the user
    token' path logged a SlackPostError on every run since this DM went live on
    2026-07-25 — making a perfectly good send read like a broken one. The user
    token IS Lucy (confirmed by Eve 2026-07-27 off a delivered DM), so say so
    instead of apologising for it."""
    return smp._client(), False


def build_png(rngs: list[str] | None = None) -> tuple[Path, str]:
    """ONE stitched image, for the SLACK DM — which takes a single file.

    Same blocks, same renderer as the email; only the delivery differs, so the DM
    and the mail can never disagree about the numbers."""
    parts, rng = render_parts(rngs)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "all_campaigns_org_sales_board.png"
    stitch_vertical([p for _n, p, _w in parts], out)
    return out, rng


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="actually send the DMs (default: dry-run, no send)")
    ap.add_argument("--only", default="",
                    help="comma-separated Slack user id(s)/name(s) to send to "
                         "INSTEAD of the full recipient list (for a targeted test)")
    args = ap.parse_args(argv)
    dry = not args.post

    recipients = ([r.strip() for r in args.only.split(",") if r.strip()]
                  if args.only else RECIPIENTS)
    if args.only:
        print(f"  --only override: sending to {recipients} (test)")

    png, rng = build_png()
    print(f"screenshot {rng} → {png} ({png.stat().st_size // 1024} KB)")

    # ONE shared group DM (mpim) with ALL recipients in a single thread — NOT
    # separate individual DMs (Megan 2026-07-25: "todo en un mismo dm"). Needs the
    # Lucy bot's mpim:write scope; dm_users_with_file falls back to individual DMs
    # only if that scope is missing (surfaced via mode='individual_dms').
    _, as_bot = _pick_client()
    print(f"{'DRY-RUN (no send)' if dry else 'SENDING group DM'} to {recipients} "
          f"— title {TITLE!r}")
    resp = smp.dm_users_with_file(
        png, users=recipients, comment=TITLE,
        file_name=f"{TITLE}.png", dry_run=dry, as_bot=as_bot)
    print(f"  result: {resp}")
    if not dry and resp.get("mode") == "individual_dms":
        print("  ⚠ fell back to INDIVIDUAL DMs — the Lucy bot is missing the "
              "mpim:write scope; add it + reinstall for ONE shared group DM.")
    # A FAILED SEND MUST FAIL THE RUN. dm_users_with_file swallows Slack errors
    # into the payload, so returning 0 unconditionally let a DM that delivered
    # nothing get recorded as DONE — the orchestrator's failure alert would
    # never fire and this DM could stop going out unnoticed. Partial delivery
    # counts too: the individual-DM fallback reports ok=True if ANY recipient
    # got it, so four of five silently missing out would otherwise look clean.
    failed = [r.get("user_id") for r in resp.get("results", [])
              if not r.get("ok")]
    if not dry and (not resp.get("ok", False) or failed):
        print(f"  ❌ send FAILED{f' for {failed}' if failed else ''} — "
              f"not everyone got it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
