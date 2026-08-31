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

# #rafs-office-recruiting-11280 -- confirmed by Megan
# 2026-08-24. Same room bg_check_sync posts to, so Lucy is already a member;
# it is PRIVATE, and a bot that isn't invited fails with channel_not_found.
CHANNEL = os.environ.get("BLUEINK_SLACK_CHANNEL", "C0AUAS88FGW")

HEADER = "Blueink Status Update"

# Who sends these by hand when the report can't. All three confirmed by
# workspace lookup + Megan (2026-08-24); "tiff" matched six people, and she
# named Tiffani Brown.
TAG_USER_IDS = [
    "U0B9924FHCL",   # Tiffani Brown
    "U0APVP29QSD",   # Aimee Garibay
    "U0BBG374GE9",   # Alisson Rodriguez
]


def _mentions() -> str:
    return " ".join("<@%s>" % uid for uid in TAG_USER_IDS)


def _held_phrase(why: str) -> str:
    """Turn a screen verdict into something a person reads without decoding.

    recent_ui.verdict hands back the row prefix and date it saw, e.g.
    "Sent 8/24/26" or "Completed 8/24/26". Megan's wording (2026-08-31) is
    "already sent on <date>" -- the date is the point, because it is what tells
    the reader whether to chase a signature or leave it alone.
    """
    parts = (why or "").split()
    if len(parts) == 2 and "/" in parts[1]:
        return "already %s on %s" % (parts[0].lower(), parts[1])
    return why or "already has a packet"


def build_thread(sent: int, problems: List[Tuple[str, str]],
                 warnings: List[str] = None,
                 held: List[Tuple[str, str]] = None) -> str:
    """The reply body. `problems` is [(person name, why)]; `held` is
    [(person name, verdict)] for people we deliberately did NOT send because
    Blue Ink already shows them a packet."""
    lines = ["*%d* new start%s sent" % (sent, "" if sent == 1 else "s")]
    lines.append("*%d* failed to send" % len(problems))
    if problems:
        lines.append("")
        for name, why in problems:
            lines.append("• *%s* — %s" % (name, why))
        # Name the action, not the vibe: the people tagged here are the ones
        # who will actually send these, so the line tells them to, rather than
        # leaving them to work out that "needs a look" means "do it yourself".
        tags = _mentions()
        if tags:
            lines += ["", "%s — these need to be sent manually." % tags]

    # Held-back people are NOT failures and must not be tagged to anyone: they
    # already have their paperwork, so there is no action to hand out. They get
    # named anyway because the sheet can't show it -- the green tint only marks
    # what THIS report sent, so a packet the team sent by hand leaves the row
    # looking untouched, and "why was Jose skipped?" costs somebody a morning
    # (Megan asked for this line 2026-08-31, having asked exactly that).
    if held:
        lines += ["", "*%d* not sent — already had a packet:" % len(held)]
        for name, why in held:
            lines.append("• *%s* — %s" % (name, _held_phrase(why)))

    return "\n".join(lines + _warn_lines(warnings))


def _warn_lines(warnings) -> list:
    """Things that didn't stop the send but somebody should know about."""
    if not warnings:
        return []
    return ["", *[":warning: " + w for w in warnings]]


def post(sent: int, problems: List[Tuple[str, str]], *,
         warnings: List[str] = None, held: List[Tuple[str, str]] = None,
         dry_run: bool = True) -> None:
    """Header to the channel, detail in its thread."""
    body = build_thread(sent, problems, warnings, held)
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
