"""Post the run's result to #11280: one bare header line, detail in the thread.

Same shape as the Blue Ink summary and the corrections channel -- the room
stays scannable and whoever owns it clicks once for the detail.

What goes in the thread is the count and the tab it came off, plus anything a
human has to act on. Correctly-skipped people (quit, failed background,
declined Friday) are the report WORKING and are not listed: fourteen of those
every Monday would bury the one line that matters.

What IS listed is anyone nobody excluded who still didn't get the email --
today that means no usable address on the sheet. They are starting on Monday
and will arrive having installed nothing, and without this line the channel
would show a clean "52 emailed" and no hint that anyone was missed. Silently
dropping a person is the failure mode this room exists to catch.
"""
from __future__ import annotations

import os
from typing import List, Tuple

from automations.shared import slack_metrics_post as smp

# #11280-alphalete-marketing-inc-rafael-hidalgo -- the new-start family's room
# (automations/shared/new_start_steps.SLACK_CHANNEL). PRIVATE: a bot that
# isn't invited fails with channel_not_found.
CHANNEL = os.environ.get("SLACK_SKOOL_SLACK_CHANNEL", "C0AUAS88FGW")

HEADER = "Slack / Skool Email"

# Who fixes a missing address. Same three as the Blue Ink summary, by user ID
# rather than @handle: "tiff" matches six people in this workspace.
TAG_USER_IDS = [
    "U0B9924FHCL",   # Tiffani Brown
    "U0APVP29QSD",   # Aimee Garibay
    "U0BBG374GE9",   # Alisson Rodriguez
]


def _mentions() -> str:
    return " ".join("<@%s>" % uid for uid in TAG_USER_IDS)


def build_thread(tab: str, recipients: List[str],
                 problems: List[Tuple[str, int, str]] = None,
                 warnings: List[str] = None) -> str:
    n = len(recipients)
    lines = ["*%d* new start%s emailed their Slack + Skool links"
             % (n, "" if n == 1 else "s"),
             "off `%s`" % tab]

    problems = problems or []
    if problems:
        lines += ["", ":warning: *%d* had no usable email and did NOT get it "
                  "- they start today with nothing installed:" % len(problems)]
        for name, row, why in problems:
            lines.append("\u2022 *%s* (row %d) - %s" % (name, row, why))
        tags = _mentions()
        if tags:
            lines += ["", "%s - these need an address on the sheet, then "
                      "`Send Now` for them." % tags]

    if warnings:
        lines += ["", *[":warning: " + w for w in warnings]]
    return "\n".join(lines)


def post(tab: str, recipients: List[str], *,
         problems: List[Tuple[str, int, str]] = None,
         warnings: List[str] = None, dry_run: bool = True) -> None:
    body = build_thread(tab, recipients, problems, warnings)
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
