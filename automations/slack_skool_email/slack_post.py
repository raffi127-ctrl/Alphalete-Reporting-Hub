"""Post the run's result to #11280: one bare header line, detail in the thread.

Same shape as the Blue Ink summary and the corrections channel -- the room
stays scannable and whoever owns it clicks once for the detail.

What goes in the thread is the count and the tab it came off, plus anything a
human has to act on. Correctly-skipped people (quit, failed background,
declined Friday) are the report WORKING and are not listed: fourteen of those
every Monday would bury the one line that matters.
"""
from __future__ import annotations

import os
from typing import List

from automations.shared import slack_metrics_post as smp

# #11280-alphalete-marketing-inc-rafael-hidalgo -- the new-start family's room
# (automations/shared/new_start_steps.SLACK_CHANNEL). PRIVATE: a bot that
# isn't invited fails with channel_not_found.
CHANNEL = os.environ.get("SLACK_SKOOL_SLACK_CHANNEL", "C0AUAS88FGW")

HEADER = "Slack / Skool Email"


def build_thread(tab: str, recipients: List[str],
                 warnings: List[str] = None) -> str:
    n = len(recipients)
    lines = ["*%d* new start%s emailed their Slack + Skool links"
             % (n, "" if n == 1 else "s"),
             "off `%s`" % tab]
    if warnings:
        lines += ["", *[":warning: " + w for w in warnings]]
    return "\n".join(lines)


def post(tab: str, recipients: List[str], *, warnings: List[str] = None,
         dry_run: bool = True) -> None:
    body = build_thread(tab, recipients, warnings)
    if dry_run:
        print("\n--- Slack (dry run, NOT posted) -> %s ---" % CHANNEL)
        print(HEADER)
        print("  |- (thread reply)")
        for line in body.split("\n"):
            print("     " + line)
        print("--- end ---")
        return
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    ts = parent.get("thread_ts")
    if not ts:
        raise RuntimeError(
            "Slack/Skool summary: no thread to reply in (%r). Nothing was "
            "said in the channel." % (parent,))
    smp.post_reply_text_only(body, thread_ts=ts, channel_id=CHANNEL)
