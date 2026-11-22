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
import re
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


def pending_note(missing) -> str:
    """'Pending update: Frontier' — what the image + caption say when the run
    hit the time cap with a campaign's numbers still missing for yesterday."""
    return "Pending update: " + ", ".join(missing) if missing else ""


def stamp_pending(png: Path, missing) -> Path:
    """Add a yellow band ABOVE the table naming the campaign(s) whose numbers
    for yesterday aren't in yet (Eve 2026-11-21: post at the time cap anyway,
    but say what's missing ON the image, since it gets forwarded without the
    caption). Same file, overwritten; the table itself is untouched."""
    if not missing:
        return png
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(png).convert("RGB")
    w, h = img.size
    size = max(16, w // 45)
    font = None
    for name in ("Arial Bold.ttf", "Arial.ttf", "arialbd.ttf", "arial.ttf",
                 "DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/Library/Fonts/Arial.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            break
        except Exception:  # noqa: BLE001 — try the next font
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:   # old Pillow: fixed-size bitmap font
            font = ImageFont.load_default()
    text = (f"{pending_note(missing)} - yesterday's numbers hadn't come in "
            f"yet when this was sent")
    band = int(size * 2.2)
    out = Image.new("RGB", (w, h + band), "white")
    d = ImageDraw.Draw(out)
    d.rectangle([0, 0, w, band - 1], fill="#FFF2CC")
    d.text((size // 2, (band - size) // 2), text, fill="#7F4F00", font=font)
    out.paste(img, (0, band))
    out.save(png)
    return png


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


def _announce(client, ts: str, posted: bool, logfn=print) -> None:
    """Keep the trackers thread's parent honest about this image: make sure it
    lists ':earth_americas: Country Sales by Campaign' (a thread posted before that
    line existed gets it appended), and once the image is in, react to the
    parent like every other tracker. Best-effort: the image is what matters."""
    from automations.tableau_screenshots import slack_post as sp
    item = sp.EXTRA_LINES[TRACKERS_CHANNEL][0]
    try:
        msgs = client.conversations_history(
            channel=TRACKERS_CHANNEL, latest=ts, inclusive=True,
            limit=1).get("messages", [])
        text = (msgs[0].get("text") or "") if msgs else ""
        if text and item["title"] not in text:
            client.chat_update(channel=TRACKERS_CHANNEL, ts=ts,
                               text=text.rstrip() + "\n" + sp.extra_line(item))
            logfn("  trackers thread: header line added")
    except Exception as e:  # noqa: BLE001
        logfn(f"  trackers thread: header line not added ({type(e).__name__})")
    if not posted:
        return
    try:
        client.reactions_add(channel=TRACKERS_CHANNEL, timestamp=ts,
                             name=item["react"])
    except Exception as e:  # noqa: BLE001 -- already_reacted on a rerun is fine
        if "already_reacted" not in str(e):
            logfn(f"  trackers thread: reaction not added ({type(e).__name__})")


def announce_only(today: dt.date, logfn=print) -> int:
    """Add the ':earth_americas: Country Sales by Campaign' line to today's
    trackers parent without posting anything. For a thread that went out
    before the line existed (Eve 2026-11-21). Has to run on a Lucy: only the
    token that posted the parent can edit it."""
    from automations.shared import slack_metrics_post as smp
    from automations.tableau_screenshots.slack_post import find_thread_ts
    client = smp._client()
    ts, _ = find_thread_ts(client, TRACKERS_CHANNEL, today)
    if not ts:
        logfn("  trackers thread: no thread today")
        return 1
    _announce(client, ts, False, logfn)
    return 0


UPDATED_MARK = "_(UPDATED"


def updated_note(filled) -> str:
    """'UPDATED: Frontier is in now' — caption of the complete re-post."""
    return f"UPDATED: {', '.join(filled)} {'is' if len(filled) == 1 else 'are'} in now"


def pending_in_thread(today: dt.date, client=None) -> list:
    """Campaigns today's image went out WITHOUT (its 'Pending update: X'
    caption in the trackers thread), or [] when there is nothing to catch up:
    no thread, no image yet, the image was complete, or the UPDATED re-post is
    already there. Read from Slack, so it works on whichever Lucy runs it."""
    from automations.tableau_screenshots.slack_post import find_thread_ts
    if client is None:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
    ts, _ = find_thread_ts(client, TRACKERS_CHANNEL, today)
    if not ts:
        return []
    want = caption(today).strip("*")
    msgs = client.conversations_replies(channel=TRACKERS_CHANNEL, ts=ts,
                                        limit=200).get("messages", [])
    mine = [m.get("text") or "" for m in msgs if want in (m.get("text") or "")]
    if any(UPDATED_MARK in t for t in mine):
        return []
    for t in mine:
        m = re.search(r"Pending update: ([^)_]+)", t)
        if m:
            return [c.strip() for c in m.group(1).split(",") if c.strip()]
    return []


def post(today: dt.date, *, dry_run: bool = True, to_eve: bool = False,
         dm_only=(), missing=(), filled=(), logfn=print) -> bool:
    """Render + deliver. Returns True if every target got it (or had it).
    `missing` = campaigns still empty (image + caption say so).
    `filled`  = the catch-up re-post: same image, now complete, captioned
    UPDATED and deduped separately from the morning one."""
    png = stamp_pending(render(today), missing)
    cap = caption(today)            # base caption: what the dedup looks for
    msg = cap + (f"  _({pending_note(missing)})_" if missing else "")
    if filled:
        msg = cap + f"  _({updated_note(filled)})_"
        cap = cap + "  " + UPDATED_MARK       # dedup key for the re-post
    logfn(f"  image: {png}")
    if dry_run:
        logfn(f"  DRY RUN — would post {msg!r} to the trackers thread + Raf DM")
        return True
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    if to_eve:
        ok = _send(client, EVE_DM, png, msg)
        logfn(f"  Eve DM: {'sent' if ok else 'FAILED'}")
        return ok
    if dm_only:                      # one-off: these people only, no thread
        ok = True
        for u in dm_only:
            dm = client.conversations_open(users=u)["channel"]["id"]
            sent = _send(client, dm, png, msg)
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
        if not filled:
            _announce(client, ts, True, logfn)
    else:
        sent = _send(client, TRACKERS_CHANNEL, png, msg, thread_ts=ts)
        logfn(f"  trackers thread: {'posted' if sent else 'FAILED'}")
        ok &= sent
        if not filled:
            _announce(client, ts, sent, logfn)
    # 2. Raf DM
    dm = client.conversations_open(users=RAF)["channel"]["id"]
    marker = OUT / f"raf_dm_sent_{today}{'_updated' if filled else ''}.txt"
    try:
        done = _already(client, dm, cap, today)
    except Exception:  # noqa: BLE001 — token without im:history: this
        done = marker.exists()  # machine's own record is the fallback
    if done:
        logfn("  Raf DM: already sent today")
    else:
        sent = _send(client, dm, png, msg)
        logfn(f"  Raf DM: {'sent' if sent else 'FAILED'}")
        if sent:
            marker.write_text(msg, encoding="utf-8")
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
    ap.add_argument("--announce-only", action="store_true",
                    help="only add the Country Sales line to today's trackers "
                         "thread header (no image, no DM)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    if a.announce_only:
        return announce_only(today)
    return 0 if post(today, dry_run=not a.post, to_eve=a.to_eve,
                     dm_only=[u for u in a.dm_only.split(",") if u]) else 1


if __name__ == "__main__":
    sys.exit(main())
