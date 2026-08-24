"""Post the run's result to Slack: a bare header, detail in the thread.

Megan's shape (2026-08-24): the channel gets ONE quiet line, "Blueink Status
Update", and everything worth reading sits in the reply -- how many went out,
how many didn't, and a bullet per person who didn't with the reason. Same
pattern as the corrections channel: the room stays scannable, the detail is one
click away for whoever owns it.

WHAT COUNTS AS A FAILURE HERE is deliberately narrower than "wasn't sent". The
people who were correctly skipped -- quit, failed background, declined Friday --
are the report working, not a problem, and listing 14 of them every Monday would
bury the two names that actually need a human. So the thread lists only people
who SHOULD have docs and don't:

  - the send itself errored
  - no usable email on the sheet
  - someone with the same name already has a packet, sent to a different
    address than the sheet's, so we held off rather than mail a stranger

dry_run is the default and prints the exact message instead of posting, per the
standing "ask before any Slack send" rule.
"""
from __future__ import annotations

import os
from typing import List, Tuple

from automations.shared import slack_metrics_post as smp

# The 11280 room. UNCONFIRMED -- this is the channel bg_check_sync posts to, but
# Megan's own Blueink note went somewhere else, so verify before this goes live.
CHANNEL = os.environ.get("BLUEINK_SLACK_CHANNEL", "C0AUAS88FGW")

HEADER = "Blueink Status Update"

# Who gets pulled in when something needs a human. Aimee and Alisson are
# confirmed by workspace lookup; "tiff" matched SIX people, so it stays out
# until Megan names the right one rather than tagging a stranger in a team room.
TAG_USER_IDS = [
    "U0APVP29QSD",   # Aimee Garibay
    "U0BBG374GE9",   # Alisson Rodriguez
    # "U0B9924FHCL", # Tiffani Brown? -- UNCONFIRMED, see above
]


def _mentions() -> str:
    return " ".join("<@%s>" % uid for uid in TAG_USER_IDS)


def build_thread(sent: int, problems: List[Tuple[str, str]]) -> str:
    """The reply body. `problems` is [(person name, why)]."""
    lines = ["*%d* new start%s sent" % (sent, "" if sent == 1 else "s")]
    if not problems:
        lines.append("*0* failed to send")
        return "\n".join(lines)

    lines.append("*%d* failed to send" % len(problems))
    lines.append("")
    for name, why in problems:
        lines.append("• *%s* — %s" % (name, why))
    tags = _mentions()
    if tags:
        lines += ["", "%s — these need a look." % tags]
    return "\n".join(lines)


def post(sent: int, problems: List[Tuple[str, str]], *,
         dry_run: bool = True) -> None:
    """Header to the channel, detail in its thread."""
    body = build_thread(sent, problems)
    if dry_run:
        print("\n--- Slack (dry run, NOT posted) -> %s ---" % CHANNEL)
        print(HEADER)
        print("  └─ (thread reply)")
        for line in body.split("\n"):
            print("     " + line)
        print("--- end ---")
        return
    # ensure_named_thread is idempotent per (title, day): a second run the same
    # Monday replies under the SAME header instead of starting a second one.
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    ts = parent.get("thread_ts")
    if not ts:
        raise RuntimeError(
            "Blue Ink summary: no thread to reply in (%r). Nothing was said in "
            "the channel." % (parent,))
    smp.post_reply_text_only(body, thread_ts=ts, channel_id=CHANNEL)
