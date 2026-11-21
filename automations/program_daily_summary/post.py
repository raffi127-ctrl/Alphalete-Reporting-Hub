"""Country Campaign Board -> one image a day for Raf (Eve 2026-11-20).

The TOP table only (title + Product Summary: campaign x Mon..Sun + Grand
Total), rendered exactly as the Sheet looks (Sheets PDF export, no browser) and
sent to:
  1. today's Tableau trackers thread in #alphalete-sales ('Tableau Country
     Trackers M/D/YYYY', found by tableau_screenshots.slack_post), as a reply;
  2. Raf by DM.
The comparison boxes stay out until Raf asks for them.

Never twice: before each send it looks for today's caption in that thread /
that DM (Slack-side, so a rerun on ANOTHER Lucy is still caught). No trackers
thread today -> the DM still goes, the thread is skipped and said so.

  python -m automations.program_daily_summary.post              # dry run
  python -m automations.program_daily_summary.post --post
  python -m automations.program_daily_summary.post --post --to-eve   # test
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console
    pass

from automations.program_daily_summary import board
from automations.program_daily_summary import layout as L

TRACKERS_CHANNEL = "C068PH3RFSM"     # #alphalete-sales (trackers thread)
RAF = "U045Z8N0ZQC"                  # Rafael Hidalgo
EVE_DM = "D087ZGE2B0F"               # Eve's self-DM — tests only
OUT = Path(__file__).resolve().parents[2] / "output" / "program_daily_summary"


def caption(today: dt.date) -> str:
    """'*Country Sales by Campaign - Nov 19*' — dated by the last day shown
    (yesterday), like the Country Sales Board DM."""
    day = today - dt.timedelta(days=1)
    return f"*Country Sales by Campaign - {day.strftime('%b')} {day.day}*"


def render(today: dt.date, ws=None) -> Path:
    """PNG of B<title>:J<Grand Total>, rows found by label."""
    from automations.org_sales_board.screenshot_email import (
        _export_png, _access_token)
    ws = board._tab(ws)
    rows = board.locate(ws.col_values(2))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"Country Sales by Campaign {today - dt.timedelta(days=1)}.png"
    return _export_png(ws.id, f"B{L.R_TITLE}:J{rows['total']}", out,
                       _access_token(), spreadsheet_id=L.SHEET_ID)


def _already(client, channel: str, cap: str, today: dt.date,
             thread_ts: str | None = None) -> bool:
    oldest = str(dt.datetime.combine(today, dt.time.min).timestamp())
    if thread_ts:
        msgs = client.conversations_replies(channel=channel, ts=thread_ts,
                                            limit=200).get("messages", [])
    else:
        msgs = client.conversations_history(channel=channel, oldest=oldest,
                                            limit=200).get("messages", [])
    want = cap.strip("*")
    return any(want in (m.get("text") or "") for m in msgs)


def _send(client, channel, png: Path, cap: str, thread_ts=None):
    kw = {"thread_ts": thread_ts} if thread_ts else {}
    r = client.files_upload_v2(channel=channel, file=str(png),
                               filename=png.name, initial_comment=cap, **kw)
    return bool(r.get("ok"))


def post(today: dt.date, *, dry_run: bool = True, to_eve: bool = False,
         dm_only=(), logfn=print) -> bool:
    """Render + deliver. Returns True if every target got it (or had it)."""
    png = render(today)
    cap = caption(today)
    logfn(f"  image: {png}")
    if dry_run:
        logfn(f"  DRY RUN — would post {cap!r} to the trackers thread + Raf DM")
        return True
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if to_eve:
        ok = _send(client, EVE_DM, png, cap)
        logfn(f"  Eve DM: {'sent' if ok else 'FAILED'}")
        return ok
    if dm_only:                      # one-off: these people only, no thread
        ok = True
        for u in dm_only:
            dm = client.conversations_open(users=u)["channel"]["id"]
            sent = _send(client, dm, png, cap)
            logfn(f"  DM {u}: {'sent' if sent else 'FAILED'}")
            ok &= sent
        return ok

    ok = True
    # 1. trackers thread
    from automations.tableau_screenshots.slack_post import find_thread_ts
    try:
        ts, _ = find_thread_ts(client, TRACKERS_CHANNEL, today)
    except Exception as e:  # noqa: BLE001 — the DM still goes
        ts = None
        logfn(f"  trackers thread: could not read the channel ({e})")
    if not ts:
        logfn("  trackers thread: no thread today yet — skipped (DM still goes)")
        ok = False
    elif _already(client, TRACKERS_CHANNEL, cap, today, thread_ts=ts):
        logfn("  trackers thread: already posted today")
    else:
        sent = _send(client, TRACKERS_CHANNEL, png, cap, thread_ts=ts)
        logfn(f"  trackers thread: {'posted' if sent else 'FAILED'}")
        ok &= sent
    # 2. Raf DM
    dm = client.conversations_open(users=RAF)["channel"]["id"]
    marker = OUT / f"raf_dm_sent_{today}.txt"
    try:
        done = _already(client, dm, cap, today)
    except Exception:  # noqa: BLE001 — token without im:history: this
        done = marker.exists()  # machine's own record is the fallback
    if done:
        logfn("  Raf DM: already sent today")
    else:
        sent = _send(client, dm, png, cap)
        logfn(f"  Raf DM: {'sent' if sent else 'FAILED'}")
        if sent:
            marker.write_text(cap, encoding="utf-8")
        ok &= sent
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true", help="actually send")
    ap.add_argument("--to-eve", action="store_true",
                    help="send ONLY to Eve's DM (test)")
    ap.add_argument("--dm-only", default="",
                    help="comma Slack user IDs: DM just them, skip the thread")
    ap.add_argument("--today", help="YYYY-MM-DD")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    return 0 if post(today, dry_run=not a.post, to_eve=a.to_eve,
                     dm_only=[u for u in a.dm_only.split(",") if u]) else 1


if __name__ == "__main__":
    sys.exit(main())
