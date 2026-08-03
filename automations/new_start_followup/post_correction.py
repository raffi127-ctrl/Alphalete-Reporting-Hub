"""One-off: post the corrected New-Start counts into Aisha's weekly thread, as Lucy.

week of 8/3 tidy-up (Raf 2026-08-04). Posts ONLY into the
'New Starts Scheduled for Monday' thread — never the main channel. Dry-run by
default; --post actually sends. Runs on the mini so _client() == Lucy Reporting.
"""
from __future__ import annotations

import argparse
import sys

from automations.shared import slack_metrics_post as smp

CHANNEL = "C06881A7WLV"                 # #rafs-office-recruiting
THREAD_TS = "1785532928.456599"         # Aisha's "New Starts Scheduled for Monday" post

MESSAGE = (
    ":clipboard: *New-Start Texts — week of 8/3 · corrected*\n\n"
    ":pray: *Apologies for the earlier mix-up!* Here's the corrected count of "
    "new starts each leader has:\n\n"
    "*:white_check_mark: Done (16)*\n"
    "• Anthony Marchetti — 1\n"
    "• Bill Hirwa — 1\n"
    "• De'Avion Allen — 2\n"
    "• Eli Rodriguez — 2\n"
    "• Isabella Pike — 1\n"
    "• Jessie Gomez — 4\n"
    "• Kaleb Muvunyi — 3\n"
    "• Lakeaih Gregory — 1\n"
    "• Logan Roodenburg — 2\n"
    "• Mustafa Alzaidy — 2\n"
    "• Pranish Shrestha — 3\n"
    "• Raphael Luzes — 3\n"
    "• Rhea McKee — 1\n"
    "• Sydney Agnew — 3\n"
    "• Tadana Manyangadze — 3\n"
    "• Zoria Johnson — 1\n\n"
    "*:white_large_square: Still to send (5)* — please text yours + reply *Sent*:\n"
    "• <@U07EMBLBN5A> — 1\n"
    "• <@U0AQZ7Y2B3M> — 1\n"
    "• <@U0B98MRD29J> — 1\n"
    "• <@U0B4KGN441L> — 1\n"
    "• <@U0AGKBS4TKJ> — 2\n\n"
    ":warning: Manual reach-out (not in Slack): *Abel Mireles* — 1"
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true", help="actually post (default: dry-run)")
    args = ap.parse_args(argv)

    client = smp._client()
    who = client.auth_test().get("user", "?")
    print(f"[identity] posting as: {who}")
    print(f"[target] channel {CHANNEL} · thread {THREAD_TS} (NOT main channel)\n")
    print(MESSAGE)
    if not args.post:
        print("\n[dry-run] not sent. Re-run with --post.")
        return 0
    resp = client.chat_postMessage(channel=CHANNEL, thread_ts=THREAD_TS, text=MESSAGE)
    print(f"\n[posted] ts={resp['ts']} as {who}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
