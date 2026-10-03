"""The 7:30 thread set-up for Carlos's room, and the pins (Carlos 2026-10-03).

"Let's make sure we start the thread right after the threads that are
already posted in the morning, by the metrics threads for Box and for B2B ...
pin all of these threads, and then the next morning ... unpin the day
prior's pins. That way, the only pins pinned for the day are the current
day's threads."

So, once a day in #alphalete-gp-sales, after B2B Metrics (~5:10) and Box
Metrics (~7:05) have posted:

  1. open today's parent for each of his day-threads, in this order:
       Box Knocks Board      -- then post YESTERDAY's final board into it
       Box Territory Stats   -- then post YESTERDAY's territory pictures into it
       Hourly Activity, Box 15 Min Gaps, Fiber 15 Min Gaps
     Two title styles, on purpose: the b2b_dispositions threads are
     "<prefix> M/D/YY" (slack_post.day_title), the two the Lucy 1 jobs reply
     into are "<prefix> — Month Dth YYYY" (shared ensure_named_thread), each
     spelled the way the job that posts into it looks it up.
  2. pin every one of them;
  3. unpin yesterday's (any pinned post of ours whose dated title is not
     today's).

Everything after the parents is best effort and says so in the log: a missing
yesterday board, a pin scope the token lacks, a Slack hiccup -- none of them
may cost the parents, which are what the day's posts need to find.

    python -m automations.b2b_dispositions.run --morning            # dry run
    python -m automations.b2b_dispositions.run --morning --send
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional

from automations.b2b_dispositions import config as cfg
from automations.b2b_dispositions import slack_post as sp
from automations.shared import slack_metrics_post as smp

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_dispositions"


def _long(day: dt.date) -> str:
    """'October 3rd 2026' -- the shared named-thread date."""
    return "%s %s %d" % (day.strftime("%B"), smp._ordinal(day.day), day.year)

CHANNEL = "C07J46MQNUX"                      # #alphalete-gp-sales

# b2b_dispositions-style threads: "<prefix> M/D/YY"
DAY_THREADS = [cfg.THREAD_HOURLY, cfg.THREAD_GAPS, cfg.THREAD_DISPOSITIONS]
# shared-style threads: "<prefix> — Month Dth YYYY" (what Lucy 1 looks up)
NAMED_THREADS = ["Box Knocks Board", "Fiber Knocks Board", "Fiber 15 Min Gaps"]
# Old thread names still in the room today -> retitled in place rather than
# left as an empty twin (Carlos 2026-10-03: "you just posted something called
# hourly activity with nothing in it").
RENAMED = {"Hourly Activity": cfg.THREAD_HOURLY}
# Spelling of the thread BOX-1's Lucy 1 board replies into. Must match
# icd_alerts.knocks_post.THREAD_TITLES["C07J46MQNUX"].
BOX_BOARD_THREAD = "Box Knocks Board"
# Order of the parents in the room, top to bottom.
ORDER = [("named", BOX_BOARD_THREAD), ("day", cfg.THREAD_DISPOSITIONS),
         ("day", cfg.THREAD_HOURLY), ("day", cfg.THREAD_GAPS),
         ("named", "Fiber Knocks Board"), ("named", "Fiber 15 Min Gaps")]
ALL_PREFIXES = DAY_THREADS + NAMED_THREADS + list(RENAMED)


# Parents this run OPENED (vs found). Yesterday's board and pictures go in
# only on the open, so a re-run (or a hand run after the 7:30 one) never
# posts them twice.
_OPENED: set = set()


def _ensure_day_parent(client, prefix: str, today: dt.date, log) -> Optional[str]:
    title = sp.day_title(prefix, today)
    ts = sp._find_parent_ts(client, CHANNEL, title, today)
    if ts:
        log("  %s: already up" % title)
        return ts
    _OPENED.add(prefix)
    for old, new in RENAMED.items():
        if new != prefix:
            continue
        old_ts = sp._find_parent_ts(client, CHANNEL, sp.day_title(old, today), today)
        if old_ts:
            client.chat_update(channel=CHANNEL, ts=old_ts, text="*%s*" % title)
            log("  %s: retitled from %s" % (title, sp.day_title(old, today)))
            return old_ts
    ts = client.chat_postMessage(channel=CHANNEL, text="*%s*" % title).get("ts")
    log("  %s: opened" % title)
    return ts


def _ensure_named_parent(prefix: str, today: dt.date, log) -> Optional[str]:
    out = smp.ensure_named_thread(prefix, today, channel_id=CHANNEL)
    if not out.get("existed"):
        _OPENED.add(prefix)
    log("  %s — %s: %s" % (prefix, _long(today),
                           "already up" if out.get("existed") else "opened"))
    return out.get("thread_ts")


def _yesterday_box_board(client, yday: dt.date, log) -> Optional[Path]:
    """Yesterday's LAST 'Box Knocks Board' picture, as Lucy 1 posted it here
    (knocks_post posts it loose or into that day's thread). Downloaded with
    the bot token; None when there isn't one."""
    import requests
    oldest = dt.datetime.combine(yday, dt.time.min).timestamp()
    latest = dt.datetime.combine(yday, dt.time.max).timestamp()
    try:
        hist = client.conversations_history(channel=CHANNEL, oldest=str(oldest),
                                            latest=str(latest), limit=500)
    except Exception as e:  # noqa: BLE001
        log("  yesterday's board: history read failed (%s)" % type(e).__name__)
        return None
    msgs = list(hist.get("messages", []))
    # The boards may be replies inside yesterday's thread.
    for m in list(msgs):
        if BOX_BOARD_THREAD in (m.get("text") or "") and m.get("reply_count"):
            try:
                rep = client.conversations_replies(channel=CHANNEL, ts=m["ts"],
                                                   limit=200)
                msgs.extend(rep.get("messages", []))
            except Exception:  # noqa: BLE001
                pass
    cands = [m for m in msgs
             if "Box Knocks" in (m.get("text") or "") and m.get("files")]
    if not cands:
        log("  yesterday's board: none found in the room")
        return None
    last = max(cands, key=lambda m: float(m.get("ts") or 0))
    f = last["files"][0]
    url = f.get("url_private_download") or f.get("url_private")
    r = requests.get(url, headers={"Authorization": "Bearer %s" % smp._load_token()},
                     timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"\x89PNG"):
        log("  yesterday's board: download was not a PNG (token lacks files:read?)")
        return None
    out = OUTPUT_DIR / yday.strftime("%Y-%m-%d") / "box_knocks_board_final.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    return out


def _yesterday_territories(yday: dt.date) -> List[Path]:
    """Yesterday's territory pictures from this machine's own run."""
    d = OUTPUT_DIR / yday.strftime("%Y-%m-%d")
    return sorted(d.glob("territory_box_*.png")) if d.exists() else []


def _pin(client, ts: str, log) -> None:
    try:
        client.pins_add(channel=CHANNEL, timestamp=ts)
        log("  pinned %s" % ts)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "already_pinned" in msg:
            log("  already pinned %s" % ts)
        else:
            log("  PIN FAILED %s: %s" % (ts, msg[:140]))


def _unpin_old(client, today: dt.date, log) -> None:
    """Unpin every pinned post of ours in the room that is not today's."""
    try:
        items = client.pins_list(channel=CHANNEL).get("items", [])
    except Exception as e:  # noqa: BLE001
        log("  pins list failed: %s" % str(e)[:140])
        return
    today_mdy = sp._short_mdy(today)
    today_long = _long(today)
    for it in items:
        m = it.get("message") or {}
        text = m.get("text") or ""
        if not any(p in text for p in ALL_PREFIXES):
            continue
        if today_mdy in text or today_long in text:
            continue
        try:
            client.pins_remove(channel=CHANNEL, timestamp=m.get("ts"))
            log("  unpinned: %s" % text[:60].replace("\n", " "))
        except Exception as e:  # noqa: BLE001
            log("  UNPIN FAILED %s: %s" % (m.get("ts"), str(e)[:120]))


def run(today: Optional[dt.date] = None, *, send: bool, log=print) -> int:
    today = today or dt.date.today()
    yday = today - dt.timedelta(days=1)
    if today.weekday() == 6:
        log("Sunday — no threads to open")
        return 0
    if not send:
        log("DRY RUN — would open, fill and pin these threads in #alphalete-gp-sales:")
        for kind, prefix in ORDER:
            log("  %s" % (sp.day_title(prefix, today) if kind == "day"
                          else "%s — %s" % (prefix, _long(today))))
        log("  + yesterday's final Box board, yesterday's %d territory picture(s)"
            % len(_yesterday_territories(yday)))
        return 0
    client = smp._client()
    parents: Dict[str, str] = {}
    for kind, prefix in ORDER:
        try:
            ts = (_ensure_day_parent(client, prefix, today, log) if kind == "day"
                  else _ensure_named_parent(prefix, today, log))
            if ts:
                parents[prefix] = ts
        except Exception as e:  # noqa: BLE001
            log("  %s: FAILED to open (%s: %s)" % (prefix, type(e).__name__, str(e)[:120]))
    # Yesterday's final Box board into today's Box Knocks Board thread.
    try:
        board = (_yesterday_box_board(client, yday, log)
                 if BOX_BOARD_THREAD in _OPENED else None)
        if board and parents.get(BOX_BOARD_THREAD):
            client.files_upload_v2(channel=CHANNEL, file=str(board),
                                   filename=board.name,
                                   initial_comment="*Final board — %s*" % sp._short_mdy(yday),
                                   thread_ts=parents[BOX_BOARD_THREAD])
            log("  posted yesterday's final Box board")
    except Exception as e:  # noqa: BLE001
        log("  yesterday's board skipped: %s: %s" % (type(e).__name__, str(e)[:120]))
    # Yesterday's territory pictures into today's Territory Stats thread.
    try:
        terrs = (_yesterday_territories(yday)
                 if cfg.THREAD_DISPOSITIONS in _OPENED else [])
        ts = parents.get(cfg.THREAD_DISPOSITIONS)
        if terrs and ts:
            for k in range(0, len(terrs), 10):
                client.files_upload_v2(
                    file_uploads=[{"file": str(p), "filename": p.name} for p in terrs[k:k + 10]],
                    channel=CHANNEL, thread_ts=ts,
                    initial_comment=("*Territory stats — %s (final)*" % sp._short_mdy(yday)) if k == 0 else None)
            log("  posted %d of yesterday's territory picture(s)" % len(terrs))
        elif ts and cfg.THREAD_DISPOSITIONS in _OPENED:
            log("  no territory pictures from yesterday on this machine")
    except Exception as e:  # noqa: BLE001
        log("  yesterday's territories skipped: %s: %s" % (type(e).__name__, str(e)[:120]))
    for prefix, ts in parents.items():
        _pin(client, ts, log)
    _unpin_old(client, today, log)
    return 0
