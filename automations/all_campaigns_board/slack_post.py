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
from automations.org_sales_board.screenshot_email import _export_png, _access_token
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
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "all_campaigns_board"


def _find_ws(sh, title=TARGET_TAB):
    want = title.strip().lower()
    return next(w for w in sh.worksheets() if w.title.strip().lower() == want)


def used_range(ws) -> str:
    """A1 through the bottom-right of the report's content (cols A..Z)."""
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


def _pick_client():
    """Prefer the 'Lucy' bot token (DMs come from Lucy, matching the other
    Slack reports). Fall back to the per-user token if the bot token isn't on
    this machine (e.g. running off the runner). Returns (client, as_bot)."""
    try:
        return smp._bot_client(), True
    except Exception as e:
        print(f"  (no Lucy bot token here — {type(e).__name__}; using the user "
              f"token, DMs send from that account)")
        return smp._client(), False


def build_png() -> tuple[Path, str]:
    sh = open_by_key(SHEET_ID)
    ws = _find_ws(sh)
    rng = used_range(ws)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "all_campaigns_org_sales_board.png"
    _export_png(ws.id, rng, out, _access_token())
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
