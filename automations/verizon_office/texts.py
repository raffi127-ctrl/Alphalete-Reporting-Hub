"""Verizon pictures -> the "Verizon" and "Verizon Leaders" iMessage chats.

    python -m automations.verizon_office.texts                 # dry run: find, download, resolve the chats, send nothing
    python -m automations.verizon_office.texts --send          # text
    lucy rerun verizon_texts -- --send

Carlos 2026-11-15: "On the Verizon and the Verizon Leaders chat, let's add in
this Verizon revenue sales board. After you post it on the Verizon metrics
thread, also send it out in those two text chains. The churn rates by rep:
let's also send that screenshot out. The Verizon churn screenshot: let's add
that one every day. Tomorrow, let's send out the Verizon Wireless comp grid
... a one-time thing. And at 9:30 am, you get the tracker ... send that one
out to the Verizon and the Verizon leaders chat as well, with Nico's name
highlighted like you've been doing."

SLACK IS THE HANDOFF. The pictures are made on Lucy 4 (the Verizon Metrics
thread) and Lucy 3 (the tracker thread, already painted with Nico's row by
tableau_screenshots.highlight for #alphalete-gp-sales); Messages lives on
LUCY 1. So this runs on Lucy 1, pulls the exact PNGs the channel got back out
of Slack (owner_chat_texts.slack_fetch does the same for the owners' chats) and
texts them -- same picture the room saw, by construction.

ONE TEXT PER PICTURE PER CHAT PER DAY (markers under output/verizon_texts/),
so the LaunchAgent can fire every half hour and only ever send what is new.
Nothing in the thread yet = exit 0, try again next tick. The "Verizon" chat is
pinned by its people (owner_sales_hourly.config.VERIZON_GROUP); "Verizon
Leaders" is resolved by name on every send (text_post.resolve_group, which
fails loud on 0 or 2+ hits rather than texting the wrong room).

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "verizon_texts"
CHANNEL = "C07J46MQNUX"                       # #alphalete-gp-sales
TRACKER_ID = "vzw_wireless"                   # tableau_screenshots.pages: Verizon Wireless Daily Scorecard (SCI)
OFFICE_KEY = "nicolas"                        # icd_alerts.offices / Office Channels row

# The comp grid is a ONE-TIME send (Carlos 2026-11-15: "Tomorrow ... just a
# one-time thing. Send it out in both chats.")
COMP_GRID_DAYS = (dt.date(2026, 11, 16),)

# (key, needle in the Verizon Metrics thread reply's caption, iMessage caption)
# in send order. The needles are the captions thread_boards / daily.py post.
THREAD_ITEMS = (
    ("revenue_board", "Revenue Board", "Verizon Revenue Sales Board"),
    ("churn_by_rep", "Churn Rates by Rep", "Verizon Churn Rates by Rep"),
    ("churn_tab", "VERIZON CHURN", "Verizon Churn (0-30 day)"),
    ("disc_before_approval", "Disconnected Before Approval", "Verizon Disconnected Before Approval"),
    ("comp_grid", "Verizon Wireless Comp Grid", "Verizon Wireless Comp Grid"),
)


def groups(log=print) -> List:
    """The chats Nico's knock boards already text -- his approved text
    destinations on the 'Office Channels' tab (icd_alerts.post.approved_texts),
    so this lands in exactly the rooms Lucy 1 already sends to (Carlos
    2026-11-15: "how does she currently send stuff on there?"). A dict is a
    participant-pinned destination, a string a name needle -- both are what
    text_post.send_to_group takes. Sheet unreadable or nothing approved: the
    pinned "Verizon" chat plus "Verizon Leaders" by name."""
    from automations.owner_sales_hourly.config import VERIZON_GROUP
    fallback = [VERIZON_GROUP, "Verizon Leaders"]
    try:
        from automations.icd_alerts import post as P
        dests = [{k: d[k] for k in ("group", "chat_guid", "require_handles") if d.get(k)}
                 for d in (P.approved_texts().get(OFFICE_KEY) or [])]
        dests = [d for d in dests if d.get("require_handles") or d.get("group")]
    except Exception as e:  # noqa: BLE001
        log("  Office Channels unreadable (%s: %s) -- using the pinned Verizon chat + 'Verizon Leaders'" % (type(e).__name__, str(e)[:80]))
        return fallback
    if not dests:
        log("  no approved text destination for %s on Office Channels -- using the pinned Verizon chat + 'Verizon Leaders'" % OFFICE_KEY)
        return fallback
    out = [d if d.get("require_handles") else d["group"] for d in dests]
    log("  chats (Office Channels, %s): %s" % (OFFICE_KEY, ", ".join(d.get("group", "?") if isinstance(d, dict) else d for d in out)))
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _marker(key: str, group_name: str, day: dt.date) -> Path:
    return OUT_DIR / day.isoformat() / ("%s__%s.sent" % (key, _slug(group_name)))


def _day_label(day: dt.date) -> str:
    return "%s %d" % (day.strftime("%b"), day.day)


def _unescape(s: str) -> str:
    return (s or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def wanted(day: dt.date) -> List[Tuple[str, str, str]]:
    """The thread items due today (the comp grid only on its days)."""
    return [it for it in THREAD_ITEMS if it[0] != "comp_grid" or day in COMP_GRID_DAYS]


def match_thread_items(replies: List[dict], day: dt.date) -> Dict[str, Optional[dict]]:
    """{key: file object or None} for every item due today, matched on the
    reply's caption text. The newest matching reply wins (a corrected board
    re-posted later in the day is the one to text)."""
    out: Dict[str, Optional[dict]] = {}
    for key, needle, _cap in wanted(day):
        fobj = None
        for m in replies:                                   # oldest -> newest
            text = _unescape(m.get("text") or "")
            if needle.lower() in text.lower():
                f = next((f for f in (m.get("files") or []) if f.get("url_private")), None)
                if f:
                    fobj = f
        out[key] = fobj
    return out


def _metrics_thread_replies(client, day: dt.date) -> List[dict]:
    from automations.sales_boards import run as SB
    ts = SB.find_verizon_metrics_thread_ts(client, CHANNEL, day)
    if not ts:
        return []
    out, cursor = [], None
    while True:
        resp = client.conversations_replies(channel=CHANNEL, ts=ts, limit=200, cursor=cursor)
        out += [m for m in resp.get("messages", []) if m.get("ts") != ts]
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def _tracker_file(client, day: dt.date) -> Optional[dict]:
    """Today's Verizon Wireless scorecard reply in the channel's tracker thread
    (the copy posted there already carries Nico's row highlighted)."""
    from automations.tableau_screenshots import pages as pages_mod
    from automations.tableau_screenshots import slack_post as sp
    spec = pages_mod.by_id(TRACKER_ID)
    if not spec:
        return None
    ts, _legacy = sp.find_thread_ts(client, CHANNEL, day)
    if not ts:
        return None
    for m in sp._image_replies(client, CHANNEL, ts):
        if sp._reply_matches(m, spec, day):
            f = next((f for f in (m.get("files") or []) if f.get("url_private")), None)
            if f:
                return f
    return None


def collect(day: dt.date, log=print) -> List[Tuple[str, str, Path]]:
    """[(key, caption, png)] of everything posted so far today, downloaded."""
    from automations.owner_chat_texts.slack_fetch import _download
    from automations.shared import slack_metrics_post as smp
    client, token = smp._client(), smp._load_token()
    day_dir = OUT_DIR / day.isoformat()
    found: List[Tuple[str, str, Path]] = []
    try:
        f = _tracker_file(client, day)
    except Exception as e:  # noqa: BLE001 -- the tracker leg never costs the thread leg
        log("  tracker thread unreadable (%s: %s)" % (type(e).__name__, str(e)[:80]))
        f = None
    if f:
        found.append(("tracker", "Verizon Wireless Daily Scorecard - %s" % _day_label(day),
                      _download(f["url_private"], token, day_dir / "tracker.png")))
    replies = _metrics_thread_replies(client, day)
    matched = match_thread_items(replies, day)
    for key, _needle, cap in wanted(day):
        f = matched.get(key)
        if f:
            found.append((key, "%s - %s" % (cap, _day_label(day)),
                          _download(f["url_private"], token, day_dir / ("%s.png" % key))))
    missing = [k for k, _n, _c in wanted(day) if not matched.get(k)] + ([] if any(k == "tracker" for k, _, _ in found) else ["tracker"])
    log("[verizon texts] %s: %d picture(s) in Slack, not yet: %s" % (day, len(found), ", ".join(missing) or "none"))
    return found


def send(found, day: dt.date, *, dry_run: bool = True, log=print) -> dict:
    from automations.b2b_dispositions import text_post as tp
    out = {"sent": [], "skipped": [], "errors": []}
    chats = groups(log)
    for key, caption, png in found:
        for group in chats:
            name = group.get("group", "") if isinstance(group, dict) else group
            m = _marker(key, name, day)
            if m.exists() and not dry_run:
                out["skipped"].append("%s -> %s (sent %s)" % (key, name, m.read_text().strip()[:19]))
                continue
            try:
                res = tp.send_to_group(name, caption, [png], dry_run=dry_run,
                                       dest=group if isinstance(group, dict) else None)
                out["sent"].append("%s %s -> %s (chat %s, %s people)" % (
                    "WOULD TEXT" if dry_run else "TEXTED", key, name, res.get("chat_id"), res.get("participants")))
                if not dry_run:
                    m.parent.mkdir(parents=True, exist_ok=True)
                    m.write_text(dt.datetime.now().isoformat(timespec="seconds"))
            except Exception as e:  # noqa: BLE001 -- one chat failing never costs the other
                out["errors"].append("%s -> %s: %s: %s" % (key, name, type(e).__name__, str(e)[:160]))
    for k in ("sent", "skipped", "errors"):
        for line in out[k]:
            log("  %s %s" % ({"sent": "✓", "skipped": "·", "errors": "✗"}[k], line))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="text the chats (default: dry run)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    found = collect(day)
    if not found:
        print("nothing posted yet — nothing to text")
        return 0
    res = send(found, day, dry_run=not a.send)
    return 1 if res["errors"] and not res["sent"] else 0


if __name__ == "__main__":
    sys.exit(main())
