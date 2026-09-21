"""Call List to 2nd Round -- post the board's picture into a Slack thread, as Lucy.

Renders the board tab to a PNG (Sheets PDF export, the exact sheet look, no
browser) and replies with it in the thread you point it at.

MUST RUN ON THE MINI: on Eve's Windows box the Slack token is Evelyn's own, so
a post from there would be signed by Evelyn, not Lucy.

Dry-run by default (builds the PNG, prints the message, sends nothing):
    python -m automations.call_list_to_2nd.slack_post --thread <slack link>
    python -m automations.call_list_to_2nd.slack_post --thread <slack link> --post
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fill
from automations.call_list_to_2nd import run as rep

TITLE = "Call List to 2nd Round"
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "call_list_to_2nd"
_LINK_RE = re.compile(r"/archives/([A-Z0-9]+)/p(\d{10})(\d{6})")


def parse_thread(link: str) -> Tuple[str, str]:
    """Slack message link -> (channel id, thread ts).
    'https://x.slack.com/archives/C0ABC/p1758480000123456' -> ('C0ABC', '1758480000.123456')."""
    m = _LINK_RE.search(link or "")
    if not m:
        raise SystemExit(f"not a Slack message link: {link!r}")
    return m.group(1), f"{m.group(2)}.{m.group(3)}"


def _last_row(values) -> int:
    """Last row with anything on either side of the board."""
    last = rep.HEADER_ROW
    for i, row in enumerate(values, start=1):
        if any(str(c).strip() for c in row):
            last = i
    return last


def build_png(tab: str = rep.SANDBOX_TAB, out: Optional[Path] = None) -> Tuple[Path, str]:
    """(png, the board's status line)."""
    from automations.org_sales_board.screenshot_email import _export_png, _access_token

    ws = fill.worksheet_ci(fill.open_by_key(rep.SHEET_ID), tab)
    values = ws.get_all_values()
    header = values[rep.HEADER_ROW - 1] if len(values) >= rep.HEADER_ROW else []
    width = len(rep.resolve_columns(header))
    last_col = rep._a1col(2 * width + rep.GAP_COLS)
    rng = f"A1:{last_col}{_last_row(values)}"
    status = values[rep.STATUS_ROW - 1][0] if len(values) >= rep.STATUS_ROW else ""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = out or OUT_DIR / "call_list_to_2nd.png"
    _export_png(ws.id, rng, out, _access_token(), spreadsheet_id=rep.SHEET_ID)
    return out, status


def message(status: str, sample: bool) -> str:
    lines = [f"*{TITLE}*" + ("  (sample)" if sample else ""),
             "This week on the left, last week on the right. Every day is re-checked on "
             "each run, so days that owners update late move -- what changed is named on "
             "each day's bar.",
             "• 1st round (sent to call list, 1st rds booked/showed): ApplicantStream",
             "• 2nd round (booked/showed): each owner's ARS REPORT",
             "• Retention Call List and 1st rd %: 50%+ green, 45–49.99% grey, under 45% red",
             "• 2nd interview %: 50%+ green, under 50% red",
             "• Today's 2nd interview % stays blank until tomorrow (most of today's 2nd "
             "rounds have not happened yet at 1 PM)"]
    if status:
        lines.append(f"_{status}_")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="call_list_to_2nd.slack_post")
    ap.add_argument("--thread", required=True, help="Slack link to the thread's parent message")
    ap.add_argument("--tab", default=rep.SANDBOX_TAB)
    ap.add_argument("--sample", action="store_true", help="mark the post as a sample")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    args = ap.parse_args(argv)

    from automations.shared import slack_metrics_post as smp
    channel, ts = parse_thread(args.thread)
    png, status = build_png(args.tab)
    text = message(status, args.sample)
    print(f"picture -> {png} ({png.stat().st_size // 1024} KB)")
    print(f"{'POSTING' if args.post else 'DRY-RUN (no post)'} to {channel} thread {ts}:\n{text}")
    resp = smp.post_reply_with_image(png, comment=text, channel_id=channel, thread_ts=ts,
                                     file_name=f"{TITLE}.png", dry_run=not args.post,
                                     mirror=False)
    print(f"  result: {resp}")
    if args.post and not (resp or {}).get("ok", False):
        print("  FAILED - nothing landed in the thread")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
