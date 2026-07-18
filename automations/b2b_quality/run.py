"""B2B Quality & Bonus — daily Slack thread (VA-replacement Item 5).

The three ATTTRACKER-B2B Tableau views the VA posts each morning, moved into
their own dated thread in #alphalete-gp-sales (Megan 2026-07-17 — she picked the
title over "B2B Performance" / "Alphalete B2B Metrics" / "B2B Scorecard"):

    *B2B Quality & Bonus 07/18/2026*
    • Tiered Bonus
    • Activation Rate
    • Churn Rate

…then each view's image as a threaded reply, titled with YESTERDAY's date to
match her convention ("Tiered Bonus 7.17.png").

The Sales Boards moved OUT of her old combined "Alphalete B2B" post into the
separate "Vantura Production" thread (automations/sales_boards), leaving these
three as the quality/payout half.

CAPTURE: rides the same machinery as the tracker screenshots — Tableau's own
Download → Image on a logged-in session (NOT a page screenshot, which drags in
browser chrome). So it MUST run on Lucy 1: ownerville is single-session and a
laptop scrape evicts the session holder.

DRY-RUN by default — posting needs --post.

Usage:
  lucy rerun b2b_quality                     # capture only, no post
  lucy rerun b2b_quality --post              # capture + post the thread
  lucy rerun b2b_quality --post --dm U…      # post to a DM (test)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

_BASE = "https://us-east-1.online.tableau.com/#/site/sci/views/"

# Saved views carry the filters the VA uses (Carlos's office). The GUID + saved
# view name in each URL is what pins those filters — don't trim them.
SPECS = [
    {
        "id": "tiered_bonus",
        "title": "Tiered Bonus",
        "emoji": "\U0001F3AF",                 # dart
        "url": _BASE + ("ATTTRACKER-B2B/OrderTieredBonus-RepRanking/"
                        "d8e25f41-e23b-4d82-bb9d-4c52dde38b9e/CarlosLocalOffice?:iid=1"),
        "crop": "canvas",
    },
    {
        "id": "activation_rate",
        "title": "Activation Rate",
        "emoji": "\U000026A1",                 # zap
        # Sorted 0-7 Day high→low; reps blank in that column are excluded (Megan).
        "url": _BASE + ("ATTTRACKER-B2B/ACTIVATIONRATES/"
                        "4c53fb7e-5a1b-4e8f-990e-0b2c8cf42309/"
                        "CarlosLocalOfficeEXPANDED?:iid=2"),
        "crop": "canvas",
    },
    {
        "id": "churn_rate",
        "title": "Churn Rate",
        "emoji": "\U0001F4C9",                 # chart_with_downwards_trend
        # Sorted 0-30 Day high→low (Megan).
        "url": _BASE + ("ATTTRACKER-B2B/CHURNRATES/"
                        "7419b960-0fb1-41d5-a11e-76f0e81c0547/"
                        "CarlosLocalOfficeEXPANDEDCHURN?:iid=1"),
        "crop": "canvas",
    },
]

THREAD_TITLE = "B2B Quality & Bonus"
CHANNEL = ("#alphalete-gp-sales", "C07J46MQNUX")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_quality"


def header_title(day) -> str:
    """Parent's first line — also the needle used to find today's thread."""
    return f"{THREAD_TITLE} {day.month:02d}/{day.day:02d}/{day.year}"


def header_text(day) -> str:
    return "\n".join([f"*{header_title(day)}*"] + [f"• {s['title']}" for s in SPECS])


def _channel():
    scratch = os.environ.get("B2B_QUALITY_CHANNEL_ID")
    return (f"scratch ({scratch})", scratch) if scratch else CHANNEL


def capture_all(out_dir: Path, only=None, headless: bool = True) -> dict:
    """{spec_id: png_path} via Tableau's Download → Image. A view that fails is
    SKIPPED and flagged rather than posted wrong — same rule as the trackers."""
    from automations.shared.tableau_patchright import tableau_session
    from automations.tableau_screenshots import capture as cap
    specs = [s for s in SPECS if not only or s["id"] in only]
    out, failed = {}, []
    out_dir.mkdir(parents=True, exist_ok=True)
    with tableau_session(headless=headless, allow_form_login=False, verbose=True) as page:
        for spec in specs:
            try:
                png = cap.capture_page(page, spec, out_dir, verbose=True)
                out[spec["id"]] = png
                print(f"   ✓ {spec['title']} -> {png.name}", flush=True)
            except Exception as e:  # noqa: BLE001 — one bad view must not kill the rest
                failed.append(spec["id"])
                print(f"   ⚠ {spec['id']} FAILED: {type(e).__name__}: "
                      f"{str(e).splitlines()[0][:120]}", flush=True)
    if failed:
        print(f"captured {len(out)}/{len(specs)} — failed: {', '.join(failed)}", flush=True)
    return out


def find_thread_ts(client, channel: str, day):
    """ts of today's parent so a re-run never starts a second thread. Degrades to
    None (start fresh) if the history read fails — Lucy's token lacks im:history,
    which would otherwise crash a --dm test after the captures."""
    oldest = dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()
    try:
        resp = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
    except Exception as e:  # noqa: BLE001
        print(f"    (thread lookup unavailable — {type(e).__name__}; new thread)")
        return None
    needle = header_title(day)
    for m in resp.get("messages", []):
        if needle in (m.get("text") or ""):
            return m.get("thread_ts") or m.get("ts")
    return None


def _already_replied(client, channel: str, thread_ts: str, plain: str) -> bool:
    """Two signals — caption text OR attached filename. files_upload_v2 doesn't
    guarantee initial_comment survives as the message text, and a false negative
    re-posts the image on the next pass."""
    try:
        rs = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    except Exception:  # noqa: BLE001
        return False
    for m in rs.get("messages", []):
        text = (m.get("text") or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        if plain in text:
            return True
        if any((f.get("name") or "").startswith(plain) for f in (m.get("files") or [])):
            return True
    return False


def post_thread(imgs: dict, day, yday, dry_run: bool, dm_user: str = "") -> list:
    name, cid = _channel()
    tag = f"{yday.month}.{yday.day}"
    if dry_run:
        return [{"dry_run": True, "channel": name, "id": cid, "header": header_text(day),
                 "replies": [f"{s['emoji']} *{s['title']} {tag}*"
                             for s in SPECS if s["id"] in imgs]}]
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if dm_user:
        cid = client.conversations_open(users=dm_user)["channel"]["id"]
        name = f"DM to {dm_user}"
    ts = find_thread_ts(client, cid, day)
    created = False
    if not ts:
        ts = client.chat_postMessage(channel=cid, text=header_text(day)).get("ts")
        created = True
    out = [{"channel": name, "thread_ts": ts, "created_parent": created}]
    for spec in SPECS:
        png = imgs.get(spec["id"])
        if not png:
            continue
        plain = f"{spec['title']} {tag}"
        caption = f"{spec['emoji']} *{plain}*"
        if _already_replied(client, cid, ts, plain):
            out.append({"view": spec["id"], "skipped": "already in thread"})
            continue
        r = client.files_upload_v2(channel=cid, thread_ts=ts, file=str(png),
                                   filename=f"{plain}.png", initial_comment=caption)
        out.append({"view": spec["id"], "ok": r.get("ok")})
        time.sleep(1)
    return out


def _publish_hub(status: str) -> None:
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("b2b_quality",
                                 "B2B Quality & Bonus → #alphalete-gp-sales", status)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated view ids")
    ap.add_argument("--post", action="store_true", help="ACTUALLY post (default dry-run)")
    ap.add_argument("--dm", metavar="USER_ID", help="post the thread to a DM (test)")
    ap.add_argument("--show", action="store_true", help="run the browser headed")
    args = ap.parse_args(argv)

    today = dt.date.today()
    yday = today - dt.timedelta(days=1)
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    imgs = capture_all(OUT_DIR, only=only, headless=not args.show)
    if not imgs:
        print("no views captured — nothing to post.")
        _publish_hub("failed")
        return 75           # EX_TEMPFAIL: let the scheduler retry

    if not args.post:
        r = post_thread(imgs, today, yday, dry_run=True)[0]
        print(f"dry-run: {len(imgs)} image(s) in {OUT_DIR}. Not posting.")
        print(f"WOULD post to {r['channel']} ({r['id']}) as a thread:")
        for line in r["header"].split("\n"):
            print(f"    {line}")
        for rep in r["replies"]:
            print(f"    ↳ {rep}  (+ image)")
        return 0

    print("POSTING thread to Slack as Lucy:")
    try:
        results = post_thread(imgs, today, yday, dry_run=False, dm_user=args.dm or "")
    except Exception:
        _publish_hub("failed")
        raise
    for r in results:
        print(f"    {r}")
    if not args.dm:
        _publish_hub("success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
