"""Country Sales Board — Slack screenshot DM.

Screenshots the Country Sales Board and sends it as ONE shared Slack GROUP DM
(from Lucy) with all recipients in a single thread — the same path and the same
shape as all_campaigns_board.slack_post, which this is modelled on. Exact-sheet
render via the Sheets PDF export; no browser.

WHAT IT CAPTURES — and why it is NOT the whole tab. The All Campaigns tab is
small enough to screenshot end to end; this one is not. It runs to row 310 and
column BC (54 cols), because the leaderboard carries 52 weeks of frozen history
and rows 231+ hold a per-rep this-week/last-week/delta box seven days wide. A
full-tab render is one unreadable postage stamp. So CAPTURE_RANGE is the part
that answers "how is the country doing today":

    rows 1-13   title + Product Summary + Current vs Prior (Mon..Sun + Grand
                Total, which is why it reaches column J — stopping at H would
                cut Sunday and the Grand Total off the summary)
    rows 16-94  the full 76-rep ranking + TOTALS, with the live week in col C
                and the 7 most recent frozen weeks beside it for trend

To send the per-rep DAY BLOCK instead (rows 97-175, cols A..L), change
CAPTURE_RANGE to "A1:L175" — nothing else needs to move.

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
CAPTURE_RANGE = "A1:J94"              # see the module docstring

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


def _pick_client():
    """Prefer the 'Lucy' bot token (DMs come from Lucy, matching the other Slack
    reports). Fall back to the per-user token if the bot token isn't on this
    machine. Returns (client, as_bot)."""
    try:
        return smp._bot_client(), True
    except Exception as e:
        print(f"  (no Lucy bot token here — {type(e).__name__}; using the user "
              f"token, the DM sends from that account)")
        return smp._client(), False


def build_png(tab: str = TARGET_TAB, rng: str = CAPTURE_RANGE) -> tuple[Path, str]:
    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh, tab)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "country_sales_board.png"
    # spreadsheet_id is REQUIRED here: _export_png defaults to the ORG board's
    # workbook, and this tab lives in the ATT Program - Focus Report one.
    _export_png(ws.id, rng, out, _access_token(), spreadsheet_id=SHEET_ID)
    return out, rng


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="actually send the DM (default: dry-run, no send)")
    ap.add_argument("--only", default="",
                    help="comma-separated Slack user id(s) to send to INSTEAD "
                         "of the full recipient list (for a targeted test)")
    ap.add_argument("--tab", default=TARGET_TAB,
                    help="tab to screenshot (default: the real board)")
    ap.add_argument("--range", dest="rng", default=CAPTURE_RANGE,
                    help=f"A1 range to capture (default {CAPTURE_RANGE})")
    args = ap.parse_args(argv)
    dry = not args.post

    recipients = ([r.strip() for r in args.only.split(",") if r.strip()]
                  if args.only else RECIPIENTS)
    if args.only:
        print(f"  --only override: sending to {recipients} (test)")

    png, rng = build_png(args.tab, args.rng)
    print(f"screenshot {args.tab!r} {rng} → {png} "
          f"({png.stat().st_size // 1024} KB)")

    # ONE shared group DM (mpim) with ALL recipients in a single thread — NOT
    # separate individual DMs. Needs the Lucy bot's mpim:write scope;
    # dm_users_with_file falls back to individual DMs only if that scope is
    # missing (surfaced via mode='individual_dms').
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
