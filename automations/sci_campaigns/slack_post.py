"""SCI Campaigns — the weekly 'done' note.

Posted to the **#l10-alphalete** channel (Raf asked to move it here off the old
group DM, 2026-08-04). Each week is a fresh **top-level** message, followed by a
one-line **reply that @-tags Rafael & Maud** so they get pinged without cluttering
the channel with mentions (Megan, 2026-08-04):

    SCI Campaigns - WE 7/18 Complete       <- top-level, one per week
      └ @Rafael @Maud                      <- reply, pings them

Text only, by design — Megan asked for a notice, not the numbers.

Posts as Lucy via the xoxp USER token (`_client`) — the same token every other
channel post uses. The bot token is DM-only and is NOT on the mini, so it must
NOT be used here ([[reference-lucy-slack-tokens]]). #l10-alphalete is private, so
Lucy Reporting (alphaletereporting@gmail.com) must be a member — she already is,
as int_wow_penetration / fiber_activations post there.

  python -m automations.sci_campaigns.slack_post --week 2026-07-18          # dry-run
  python -m automations.sci_campaigns.slack_post --week 2026-07-18 --post
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from automations.shared import slack_metrics_post as smp

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CHANNEL_ID = "C075PCEL92M"          # #l10-alphalete (private)
# Slack user IDs (not names) so the mention never depends on users:read scope.
RAF = "U045Z8N0ZQC"                 # Rafael Hidalgo (raffi127@gmail.com)
MAUD = "U045USN7NCD"                # Maud Miller (maudmiller4@gmail.com)


def _we_short(week_ending: dt.date) -> str:
    """'7/18' — M/D, no leading zeros, no year. Built from the date parts (not
    strftime %-m, which is Mac-only) so it runs on Windows too."""
    return f"{week_ending.month}/{week_ending.day}"


def notify(week_ending: dt.date, *, dry_run: bool = True) -> dict:
    """Post 'SCI Campaigns - WE <M/D> Complete' to #l10-alphalete, then reply in
    its thread tagging Rafael & Maud."""
    text = f"SCI Campaigns - WE {_we_short(week_ending)} Complete"
    reply = f"<@{RAF}> <@{MAUD}>"
    if dry_run:
        return {"dry_run": True, "channel": CHANNEL_ID, "text": text,
                "reply": reply}
    # Channel post ⇒ the xoxp USER token (Lucy on the mini), never the bot token.
    client = smp._client()
    parent = client.chat_postMessage(channel=CHANNEL_ID, text=text)
    ts = parent.get("ts")
    resp = client.chat_postMessage(channel=CHANNEL_ID, thread_ts=ts, text=reply)
    return {"ok": parent.get("ok") and resp.get("ok"), "channel": CHANNEL_ID,
            "ts": ts, "reply_ts": resp.get("ts"), "text": text, "reply": reply}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", required=True, metavar="YYYY-MM-DD",
                    help="the week ending the note announces")
    ap.add_argument("--post", action="store_true",
                    help="actually send (default: dry-run, no send)")
    args = ap.parse_args(argv)
    out = notify(dt.date.fromisoformat(args.week), dry_run=not args.post)
    print(f"  {'DRY-RUN' if not args.post else 'SENT'}: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
