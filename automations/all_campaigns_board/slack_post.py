"""All Campaigns Org Sales Board — Slack screenshot DM.

Screenshots the whole 'All Campaigns Org Sales Board' tab (exact-sheet render via
the Sheets PDF export — no browser, same path the ORG board email/Slack use) and
sends it as an INDIVIDUAL Slack DM (from Lucy) to a fixed recipient list, under
the title 'All Campaigns Org Sales Board'.

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
RECIPIENTS = [
    "Rafael Hidalgo",
    "Carlos Hidalgo",
    "Maud Miller",
    "Megan Hidalgo",
    "Evelyn Sobrino",
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
    args = ap.parse_args(argv)
    dry = not args.post

    png, rng = build_png()
    print(f"screenshot {rng} → {png} ({png.stat().st_size // 1024} KB)")

    # Resolve recipients up front (read-only) so a bad name is caught before any
    # send, and logged either way.
    client, as_bot = _pick_client()
    resolved = []
    for name in RECIPIENTS:
        try:
            uid = smp._resolve_user_id(client, name)
            resolved.append((name, uid))
            print(f"  resolved {name!r} → {uid}")
        except Exception as e:
            print(f"  ⚠ could NOT resolve {name!r}: {type(e).__name__}: {e}")
            resolved.append((name, None))

    print(f"{'DRY-RUN (no send)' if dry else 'SENDING'} — title {TITLE!r}")
    results = []
    for name, uid in resolved:
        if uid is None:
            results.append({"name": name, "ok": False, "reason": "unresolved"})
            continue
        r = smp.dm_user_with_file(
            png, user=uid, comment=TITLE,
            file_name=f"{TITLE}.png", dry_run=dry, as_bot=as_bot)
        print(f"  DM {name}: {r}")
        results.append({"name": name, **r})
    ok = sum(1 for r in results if r.get("ok") or r.get("dry_run"))
    print(f"=== {ok}/{len(RECIPIENTS)} DM(s) {'previewed' if dry else 'sent'} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
