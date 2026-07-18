"""Program Sales Boards — daily Slack thread (VA-replacement Items 5-8).

Replaces the VA's per-program Sales Board posts in #alphalete-gp-sales with ONE
dated thread (Megan 2026-07-17):

    Vantura Production 07/18/2026
    B2B Sales Board
    Base Sales Board
    JE Sales Board
    BOX Sales Board

…then each board's TWO images as a threaded reply — (a) the weekly ranking and
(b) the Highrollers cut for yesterday. Titled with YESTERDAY's date, matching the
VA (posted Sat 7/18 -> "BOX Sales Board 7.17").

Rendering lives in render.py — see its header for why we duplicate the tab and
hide rows per campaign instead of cropping ranges (campaigns are NOT contiguous).

SANDBOX-FIRST: defaults to the sandbox sheet; set SALES_BOARD_SHEET_ID to the
real sheet only after sign-off. DRY-RUN by default — real posting needs --post.

Usage:
  python -m automations.sales_boards.run                  # dry-run, all 4
  python -m automations.sales_boards.run --program JE     # one program
  python -m automations.sales_boards.run --post           # actually post
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

from automations.recruiting_report.fill import open_by_key, _retry
from automations.pnl_office.run import _token
from automations.sales_boards import render as R

SANDBOX_SHEET_ID = "15QzcyFqTzX9RYNJ2SvT_HOiyQsMU1v90wHjSUHA_cNc"   # re-copied 7/18
PROD_SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
SHEET_ID = os.environ.get("SALES_BOARD_SHEET_ID", SANDBOX_SHEET_ID)
TAB = "Sales Board"
TEMP_TAB = "_sb_render_tmp"          # ephemeral copy we create + delete

PROGRAMS = R.PROGRAMS
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "sales_boards"
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")

# The second daily thread in the same channel — the three ATTTRACKER-B2B Tableau
# views. Those captures aren't built yet; the header lives here so both threads
# stay consistent when they land.
QUALITY_THREAD_TITLE = "B2B Quality & Bonus"
QUALITY_THREAD_ITEMS = ["Tiered Bonus", "Activation Rate", "Churn Rate"]


def header_title(day) -> str:
    """Parent's first line — also the needle used to find today's thread."""
    return f"Vantura Production {day.month:02d}/{day.day:02d}/{day.year}"


def header_text(day) -> str:
    return "\n".join([f"*{header_title(day)}*"] + [f"{p} Sales Board" for p in PROGRAMS])


def quality_header_text(day) -> str:
    title = f"{QUALITY_THREAD_TITLE} {day.month:02d}/{day.day:02d}/{day.year}"
    return "\n".join([f"*{title}*"] + [f"• {i}" for i in QUALITY_THREAD_ITEMS])


def _channel():
    scratch = os.environ.get("SALES_BOARD_CHANNEL_ID")
    return (f"scratch ({scratch})", scratch) if scratch else CHANNEL


def find_thread_ts(client, channel: str, day):
    """ts of today's parent, so a re-run never starts a second thread."""
    oldest = dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()
    resp = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
    needle = header_title(day)
    for msg in resp.get("messages", []):
        if needle in (msg.get("text") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    return None


def _already_replied(client, channel: str, thread_ts: str, caption: str) -> bool:
    try:
        rs = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    except Exception:  # noqa: BLE001
        return False
    for m in rs.get("messages", []):
        if caption in (m.get("text") or ""):
            return True
    return False


def post_thread(imgs: dict, day, yday, dry_run: bool) -> list:
    """Find-or-create today's parent, then post each board's images as a reply."""
    name, cid = _channel()
    tag = f"{yday.month}.{yday.day}"
    if dry_run:
        return [{"dry_run": True, "channel": name, "id": cid,
                 "header": header_text(day),
                 "replies": [(f"{p} Sales Board {tag}",
                              sorted(v)) for p, v in imgs.items() if v]}]
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    ts = find_thread_ts(client, cid, day)
    created = False
    if not ts:
        ts = client.chat_postMessage(channel=cid, text=header_text(day)).get("ts")
        created = True
    out = [{"channel": name, "thread_ts": ts, "created_parent": created}]
    for p in PROGRAMS:
        parts = imgs.get(p) or {}
        if not parts:
            continue
        caption = f"{p} Sales Board {tag}"
        if _already_replied(client, cid, ts, caption):
            out.append({"board": p, "skipped": "already in thread"})
            continue
        uploads = [{"file": str(parts[k]), "filename": f"{caption} ({k}).png"}
                   for k in ("a", "b") if k in parts]
        r = client.files_upload_v2(channel=cid, thread_ts=ts,
                                   file_uploads=uploads, initial_comment=caption)
        out.append({"board": p, "images": len(uploads), "ok": r.get("ok")})
        time.sleep(1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", choices=PROGRAMS, help="just one program")
    ap.add_argument("--post", action="store_true",
                    help="ACTUALLY post to Slack (default dry-run)")
    args = ap.parse_args(argv)

    today = dt.date.today()
    yday = today - dt.timedelta(days=1)
    programs = [args.program] if args.program else PROGRAMS

    sh = open_by_key(SHEET_ID)
    src = _retry(lambda: sh.worksheet(TAB))
    print(f"sheet: {SHEET_ID[:12]}… "
          f"({'SANDBOX' if SHEET_ID == SANDBOX_SHEET_ID else 'PROD'})  tab={TAB}")

    for w in sh.worksheets():                 # clear any orphan from a crashed run
        if w.title == TEMP_TAB:
            sh.del_worksheet(w)
    tmp = sh.duplicate_sheet(src.id, new_sheet_name=TEMP_TAB)
    try:
        sh.batch_update({"requests": [{"clearBasicFilter": {"sheetId": tmp.id}}]})
        imgs = R.render_all(sh, tmp, SHEET_ID, _token(), yday, OUT_DIR, programs)
    finally:
        sh.del_worksheet(tmp)
        print("temp tab removed")

    made = sum(len(v) for v in imgs.values())
    if not args.post:
        print(f"dry-run: {made} image(s) in {OUT_DIR}. Not posting.")
        r = post_thread(imgs, today, yday, dry_run=True)[0]
        print(f"WOULD post to {r['channel']} ({r['id']}) as a thread:")
        for line in r["header"].split("\n"):
            print(f"    {line}")
        for cap, keys in r["replies"]:
            print(f"    ↳ {cap}  ({len(keys)} image(s): {', '.join(keys)})")
        return 0
    print("POSTING thread to Slack as Lucy:")
    for r in post_thread(imgs, today, yday, dry_run=False):
        print(f"    {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
