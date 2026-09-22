"""Call List to 2nd Round -- post the picture in today's thread, as Lucy.

WHERE (Eve, 2026-09-21): #ars-recruiting-numbers, ONE thread per day. The
day's first pass posts the dated parent ('Call List to 2nd Round — September
22nd 2026'); every pass -- each time zone's 1 PM -- replies under it with the
picture of ITS offices, so the day's updates stay together.

WHAT: ONE picture of ONE day (Eve): the last full day -- yesterday, or last
Friday on a Monday -- from the '(picture)' tab run.py writes next to the board.
Anything that moved on an earlier day (owners updating late) is listed in the
message text, read off the board's day bars.

MUST RUN ON THE MINI: on Eve's Windows box the Slack token is Evelyn's own, so
a post from there would be signed by Evelyn, not Lucy.

Dry-run by default (builds the PNG, prints what it would post, sends nothing):
    python -m automations.call_list_to_2nd.slack_post
    python -m automations.call_list_to_2nd.slack_post --production --post
    python -m automations.call_list_to_2nd.slack_post --png-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import List, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.call_list_to_2nd import run as rep

TITLE = "Call List to 2nd Round"
CHANNEL_ID = "C0C42793AKS"       # #ars-recruiting-numbers (same channel as Below the Mark)
THREAD_LINES = [
    "Call list → 1st round → 2nd round, every office · the last full day",
    "Each time zone at its own 1 PM — every update lands in this thread.",
]
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "call_list_to_2nd"
MAX_CHANGE_LINES = 10


def changed_lines(board_values) -> List[str]:
    """'Wednesday 9/16: Kash Rai 2nd % 64%→73%, ...' for every day bar on the
    board that names a change, both weeks."""
    out = []
    for row in board_values[rep.FIRST_BODY_ROW - 1:]:
        for cell in row:
            text = str(cell)
            m = rep._BAND_RE.match(text)
            if m and "CHANGED: " in text:
                out.append(f"{text.split('  ·  ')[0].title()}: {text.split('CHANGED: ', 1)[1]}")
    return out


def build_png(tab: str = rep.SANDBOX_TAB) -> Tuple[Path, str, str, List[str]]:
    """(png, the picture's title, its status line, what changed on earlier days)."""
    from automations.org_sales_board.screenshot_email import _export_png, _access_token

    sh = fill.open_by_key(rep.SHEET_ID)
    pic = fill.worksheet_ci(sh, tab + rep.PICTURE_SUFFIX)
    values = pic.get_all_values()
    header = values[rep.HEADER_ROW - 1] if len(values) >= rep.HEADER_ROW else []
    width = len(rep.resolve_columns(header))
    last = max((i for i, r in enumerate(values, start=1) if any(str(c).strip() for c in r[:width])),
               default=rep.HEADER_ROW)
    title = values[rep.TITLE_ROW - 1][0] if values else ""
    status = values[rep.STATUS_ROW - 1][0] if len(values) >= rep.STATUS_ROW else ""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "call_list_to_2nd.png"
    _export_png(pic.id, f"A1:{rep._a1col(width)}{last}", out, _access_token(),
                spreadsheet_id=rep.SHEET_ID)
    board = fill.worksheet_ci(sh, tab).get_all_values()
    return out, title, status, changed_lines(board)


def message(title: str, changes: List[str]) -> str:
    """The reply's text. Short on purpose: the thread's parent already says what
    the report is; the colour rules are the ones Rafael set."""
    lines = [f"*{title.replace('  ·  ', ' · ') or TITLE}*",
             "Retention Call List & 1st rd %: 50%+ green · 45–49.99% grey · under 45% red  |  "
             "2nd interview %: 50%+ green · under 50% red"]
    if changes:
        lines.append("*Updated late* (moved on earlier days since the last check):")
        lines += [f"• {c}" for c in changes[:MAX_CHANGE_LINES]]
        if len(changes) > MAX_CHANGE_LINES:
            lines.append(f"• …and {len(changes) - MAX_CHANGE_LINES} more days")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="call_list_to_2nd.slack_post")
    ap.add_argument("--production", action="store_true",
                    help=f"the picture of {rep.PRODUCTION_TAB!r} (default: the SANDBOX's)")
    ap.add_argument("--png-only", action="store_true", help="just build the picture, no Slack")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    args = ap.parse_args(argv)
    tab = rep.PRODUCTION_TAB if args.production else rep.SANDBOX_TAB

    png, title, status, changes = build_png(tab)
    text = message(title, changes)
    print(f"picture -> {png} ({png.stat().st_size // 1024} KB)")
    print(text)
    if args.png_only:
        return 0

    from automations.shared import slack_metrics_post as smp
    today = dt.datetime.now(dt.timezone.utc).astimezone(rep.CT).date()
    dry = not args.post
    print(f"{'DRY-RUN (no post)' if dry else 'POSTING'} to {CHANNEL_ID}, today's '{TITLE}' thread")
    head = smp.ensure_named_thread(TITLE, today, lines=THREAD_LINES, dry_run=dry,
                                   channel_id=CHANNEL_ID)
    print(f"  thread: {head}")
    if dry:
        return 0
    ts = head.get("thread_ts")
    if not ts:
        print("  FAILED - could not find or post today's thread")
        return 1
    resp = smp.post_reply_with_image(png, comment=text, channel_id=CHANNEL_ID, thread_ts=ts,
                                     file_name=f"{TITLE}.png", mirror=False)
    print(f"  result: { {k: v for k, v in resp.items() if k != 'raw'} }")
    if not (resp or {}).get("ok", False):
        print("  FAILED - nothing landed in the thread")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
