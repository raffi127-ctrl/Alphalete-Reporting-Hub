"""Call List to 2nd Round -- post the picture in today's thread, as Lucy.

WHERE (Eve, 2026-09-21): #ars-recruiting-numbers, ONE thread per day. The
day's first pass posts the dated parent ('Call List to 2nd Round — September
22nd 2026'); every pass -- each time zone's 1 PM -- replies under it with the
picture of ITS offices, so the day's updates stay together.

WHAT: ONE picture of ONE day (Eve): the last full day -- yesterday, or last
Friday on a Monday -- from the '(picture)' tab run.py writes next to the board.
Anything that moved since the last check (owners updating late) goes as a
SECOND picture in the same message, off the '(updates)' tab -- no second image
on a pass where nothing moved.

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
import time
import sys
from pathlib import Path
from typing import List, Optional, Tuple

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


def _set_hidden(sh, sheet_id: int, hidden: bool) -> None:
    sh.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "hidden": hidden}, "fields": "hidden"}}]})


def _export_tab(sh, name: str, out: Path) -> Tuple[Optional[Path], str, str]:
    """Shoot one picture tab -> (png or None when it has no rows, title, status)."""
    from automations.org_sales_board.screenshot_email import _export_png, _access_token

    pic = fill.worksheet_ci(sh, name)
    values = pic.get_all_values()
    header = values[rep.HEADER_ROW - 1] if len(values) >= rep.HEADER_ROW else []
    width = len(rep.resolve_columns(header))
    # the '(updates)' tab carries one column Eve's template doesn't have (the
    # before→after), which resolve_columns drops -- shoot it too
    if rep.MOVED_HEADER in header:
        width = max(width + 1, header.index(rep.MOVED_HEADER) + 1)
    last = max((i for i, r in enumerate(values, start=1) if any(str(c).strip() for c in r[:width])),
               default=rep.HEADER_ROW)
    title = values[rep.TITLE_ROW - 1][0] if values else ""
    status = values[rep.STATUS_ROW - 1][0] if len(values) >= rep.STATUS_ROW else ""
    if last <= rep.HEADER_ROW:            # title + header only: nothing to show
        return None, title, status
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # The picture tab is kept HIDDEN so the workbook stays clean (Eve,
    # 2026-09-21) -- but a hidden tab exports as a blank page. So: show it for
    # the export, and hide it again whatever happens.
    # Read the flag FRESH: the opened workbook can be a cached copy from before
    # the tab was hidden, and trusting it exported a blank page (2026-09-21).
    meta = sh.fetch_sheet_metadata({"fields": "sheets(properties(sheetId,hidden))"})
    hidden = any(s["properties"]["sheetId"] == pic.id and s["properties"].get("hidden")
                 for s in meta["sheets"])
    if hidden:
        _set_hidden(sh, pic.id, False)
    try:
        _export_png(pic.id, f"A1:{rep._a1col(width)}{last}", out, _access_token(),
                    spreadsheet_id=rep.SHEET_ID)
    finally:
        if hidden:
            _set_hidden(sh, pic.id, True)
    return out, title, status


def build_pngs(tab: str = rep.SANDBOX_TAB) -> Tuple[Path, Optional[Path], str, str]:
    """(the day's picture, the updates picture or None, title, status).

    TWO images in one Slack message (Eve, 2026-09-22): the day's board, and
    what moved on earlier days -- as a picture rather than a list of names in
    the message text. run.py blanks the '(updates)' tab when nothing moved, and
    then there is no second image."""
    sh = fill.open_by_key(rep.SHEET_ID)
    png, title, status = _export_tab(sh, tab + rep.PICTURE_SUFFIX,
                                     OUT_DIR / "call_list_to_2nd.png")
    if png is None:
        raise SystemExit(f"{tab + rep.PICTURE_SUFFIX!r} is empty - run.py first")
    upd = None
    for attempt in (1, 2):                  # the export drops a connection now and then
        try:
            upd, _, _ = _export_tab(sh, tab + rep.UPDATES_SUFFIX,
                                    OUT_DIR / "call_list_to_2nd_updates.png")
            break
        except Exception as exc:            # noqa: BLE001 -- run.py may not have made it yet
            # say so: a swallowed error here silently drops the second image
            print(f"  updates picture attempt {attempt} failed "
                  f"({type(exc).__name__}: {exc})")
            if attempt == 2:
                break
            time.sleep(3)
    return png, upd, title, status


def message(title: str, has_updates: bool = False) -> str:
    """The reply's text: one line. No colour legend and no list of changes --
    Eve, 2026-09-22: both made the post look overloaded. The changes are the
    second image; the text only says it is there."""
    line = f"*{title.replace('  ·  ', ' · ') or TITLE}*"
    if has_updates:
        line += "  ·  2nd picture: what moved on earlier days"
    return line


def post(png: Path, updates: Optional[Path], text: str, *, thread_ts: str) -> dict:
    """Both pictures in ONE message: Slack groups several files under a single
    initial_comment, so the day and its updates arrive together instead of as
    two posts people have to tie back to each other."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    uploads = [{"file": str(png), "filename": f"{TITLE}.png"}]
    if updates:
        uploads.append({"file": str(updates), "filename": f"{TITLE} - updates.png"})
    resp = client.files_upload_v2(file_uploads=uploads, channel=CHANNEL_ID,
                                  thread_ts=thread_ts, initial_comment=text)
    return {"ok": bool(resp.get("ok")), "files": len(uploads)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="call_list_to_2nd.slack_post")
    ap.add_argument("--production", action="store_true",
                    help=f"the picture of {rep.PRODUCTION_TAB!r} (default: the SANDBOX's)")
    ap.add_argument("--png-only", action="store_true", help="just build the picture, no Slack")
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    args = ap.parse_args(argv)
    tab = rep.PRODUCTION_TAB if args.production else rep.SANDBOX_TAB

    png, updates, title, status = build_pngs(tab)
    text = message(title, updates is not None)
    print(f"picture -> {png} ({png.stat().st_size // 1024} KB)")
    print(f"updates -> {updates} ({updates.stat().st_size // 1024} KB)" if updates
          else "updates -> none (nothing moved on an earlier day)")
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
    resp = post(png, updates, text, thread_ts=ts)
    print(f"  result: {resp}")
    if not (resp or {}).get("ok", False):
        print("  FAILED - nothing landed in the thread")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
