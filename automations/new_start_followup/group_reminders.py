"""Group reminders for the lvl-1 leaders — iMessage group + Slack channel.

Raf's Loom + follow-up (2026-08-23): the individual texts (texts.py) reach the
leaders one by one, and these two group posts catch everyone else — "not all
the leaders can fit in this chat... if we could ping them in two different
ways, that would be great."

Two slots:
  saturday  (Sat 8:30am, with the individual texts)
      "Hey guys, if you have new starts scheduled can you make sure you send
       out the text and respond to the slack!" + the week's thread link
  daily     (Mon–Fri 9:00am)
      "Hey guys, reminder to text any new starts you closed yesterday!"

Both destinations, both slots:
  * iMessage group  "Alphalete lvl 1's🔥🔥"  — resolved by NAME on every send
    (needle stops before the apostrophe + emoji), from Lucy 1's Messages
    (alphaletereporting@). Lucy is already a member (Megan's screenshot 8/23).
  * Slack           #alphalete-lvl1-chat (private) — Lucy Reporting already
    posts there (Texas de Brazil standings), so membership is proven.

The two halves are independent: the iMessage half failing must not stop the
Slack half, and vice versa. One .sent marker per (slot, day) — a double post
is a duplicate to ~80 people, not a harmless retry.

RUNS ON LUCY 1. Python 3.9-safe.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

# Substring needle for AppleScript's case-insensitive `contains` — stops
# before the "'s🔥🔥" so quoting/emoji never enter the script literal.
IMESSAGE_GROUP = "Alphalete lvl 1"

# #alphalete-lvl1-chat (private; Raf's channel, ~79 members).
SLACK_CHANNEL = "C09JG28CD27"

MARKER_DIR = (Path(__file__).resolve().parents[2] / "output"
              / "new_start_followup" / "group_reminders")


def saturday_message(link: Optional[str]) -> str:
    text = ("Hey guys, if you have new starts scheduled can you make sure "
            "you send out the text and respond to the slack!")
    if link:
        text += "\n" + link
    return text


def daily_message() -> str:
    return "Hey guys, reminder to text any new starts you closed yesterday!"


def _marker(slot: str, day: dt.date) -> Path:
    return MARKER_DIR / day.isoformat() / ("%s.sent" % slot)


def send_all(slot: str, text: str, *, day: Optional[dt.date] = None,
             dry_run: bool = True) -> dict:
    """Send `text` to the iMessage group AND the Slack channel.

    Returns {"imessage": ..., "slack": ..., "errors": [...], "skipped": str|None}.
    """
    day = day or dt.date.today()
    out = {"slot": slot, "dry_run": dry_run, "imessage": None, "slack": None,
           "errors": [], "skipped": None}

    m = _marker(slot, day)
    if m.exists() and not dry_run:
        out["skipped"] = "already sent %s" % m.read_text().strip()[:19]
        return out

    # iMessage half — resolve even on dry-run (proves the group needle).
    try:
        from automations.b2b_dispositions import text_post as tp
        res = tp.send_text_to_group(IMESSAGE_GROUP, text, dry_run=dry_run)
        out["imessage"] = "%s %r (chat %s, %s participants)" % (
            "WOULD TEXT" if dry_run else "TEXTED", res.get("resolved_name"),
            res.get("chat_id"), res.get("participants"))
    except Exception as e:  # noqa: BLE001 — never blocks the Slack half
        out["errors"].append("imessage: %s: %s" % (type(e).__name__, str(e)[:200]))

    # Slack half.
    try:
        if dry_run:
            out["slack"] = "WOULD POST to %s" % SLACK_CHANNEL
        else:
            from automations.shared import slack_metrics_post as smp
            resp = smp._client().chat_postMessage(channel=SLACK_CHANNEL,
                                                  text=text)
            out["slack"] = "POSTED to %s (ts %s)" % (SLACK_CHANNEL, resp["ts"])
    except Exception as e:  # noqa: BLE001
        out["errors"].append("slack: %s: %s" % (type(e).__name__, str(e)[:200]))

    # Marker only when at least one half went out — a fully failed send should
    # retry, a half-failed one shouldn't double the half that worked... but a
    # per-half marker is overkill: the realistic failure is one side's auth,
    # which stays broken within a day. Half-sent is recorded as sent + error.
    if not dry_run and (out["imessage"] or out["slack"]):
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(dt.datetime.now().isoformat(timespec="seconds"))
    return out


def describe(out: dict) -> str:
    lines = []
    if out.get("skipped"):
        lines.append("SKIPPED — %s" % out["skipped"])
    if out.get("imessage"):
        lines.append("iMessage: %s" % out["imessage"])
    if out.get("slack"):
        lines.append("Slack:    %s" % out["slack"])
    for e in out.get("errors") or []:
        lines.append("ERROR:    %s" % e)
    return "\n".join(lines)
