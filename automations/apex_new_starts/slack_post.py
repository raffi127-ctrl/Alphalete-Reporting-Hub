"""Post the leftovers to #rafs-office-recruiting-11280, for Alisson and Tiff.

Megan (2026-09-09): anything the run couldn't do goes in a Slack thread in that
channel, tagging the two people who will do it by hand.

SAME SHAPE AS THE BLUE INK SUMMARY. One quiet header line in the room, and
every name in the thread reply. That keeps the channel scannable and puts the
detail one click from whoever owns it.

WHAT THE THREAD LISTS is narrower than "everything about this run", on purpose.
The Social and the gender are typed by whoever runs the report, in the pop-up,
for every single person -- listing 28 lines saying "needs an SSN" would bury the
three names that actually need chasing. So the thread names only people the run
COULD NOT FINISH, and says which part:

  * no signed Blue Ink packet    -- nothing to fill from; the whole record
  * W-4 Step 1(c) left blank     -- no filing status to read
  * I-9 fields missing           -- named, so nobody has to go hunting
  * skipped mid-run              -- a field on the Apex screen didn't match

Terminated and O-NA people are NOT here. They are the report working.

dry_run is the default and prints the message instead of posting it, per the
standing "ask before any Slack send" rule.
"""
from __future__ import annotations

import os
from typing import List, Tuple

from automations.shared import slack_metrics_post as smp

# #rafs-office-recruiting-11280 -- the same private room blueink_docs and
# bg_check_sync post to, so Lucy is already a member. A bot that isn't invited
# fails with channel_not_found.
CHANNEL = os.environ.get("APEX_NEW_STARTS_SLACK_CHANNEL", "C0AUAS88FGW")

HEADER = "New Starts → Apex"

# Megan named these two specifically (2026-09-09) -- NOT the same list as the
# Blue Ink summary, which also tags Aimee. Ids from the workspace lookup that
# module already did.
TAG_USER_IDS = [
    "U0BBG374GE9",   # Alisson Rodriguez
    "U0B9924FHCL",   # Tiffani Brown
]


def _mentions() -> str:
    return " ".join("<@%s>" % uid for uid in TAG_USER_IDS)


def build_thread(tab: str, added: int, items: List[Tuple[str, List[str]]],
                 *, done: bool = False) -> str:
    """The reply body. `items` is [(person, [what's missing])].

    `done` is the whole difference between a plan and a result, and it is not
    cosmetic. The first version of this message said "27 new starts filled in
    Apex" after a run that never opened Apex -- it had only read the board and
    Blue Ink. Two people were told 27 records existed when none did. A report
    claims what it DID, never what it is ready to do. [[green means delivered]]
    """
    lines = ["*%s*" % tab,
             ("*%d* new start%s added to Apex" if done else
              "*%d* new start%s ready to add to Apex — not added yet")
             % (added, "" if added == 1 else "s")]
    if not items:
        lines += ["", "Nothing needs doing by hand. :tada:"
                      if done else
                      "Nothing is missing — everyone's paperwork is in."]
        return "\n".join(lines)

    lines += ["", "*%d* need%s a hand:" % (len(items),
                                           "" if len(items) == 1 else "")]
    for name, reasons in items:
        lines.append("• *%s* — %s" % (name, "; ".join(reasons)))
    # Name the action, not the vibe: the people tagged are the ones who will
    # actually finish these.
    lines += ["", "%s — these bits need doing by hand in Apex." % _mentions()]
    if not done:
        lines += ["", "_(Nobody has been added to Apex yet — this is the list "
                      "as it stands.)_"]
    return "\n".join(lines)


def post(tab: str, added: int, items: List[Tuple[str, List[str]]], *,
         dry_run: bool = True, done: bool = False) -> None:
    """Header to the channel, detail in its thread.

    `done=False` (the default) means nothing has been typed into Apex yet, and
    the message says so. Only the run that actually fills records passes True.
    """
    body = build_thread(tab, added, items, done=done)
    if dry_run:
        print("\n--- Slack (dry run, NOT posted) -> %s ---" % CHANNEL)
        print(HEADER)
        print("  └─ (thread reply)")
        for line in body.split("\n"):
            print("     " + line)
        print("--- end ---")
        return
    # Idempotent per (title, day): a second run the same day replies under the
    # SAME header instead of starting a second thread.
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    ts = parent.get("thread_ts")
    if not ts:
        raise RuntimeError(
            "Apex new starts summary: no thread to reply in (%r). Nothing was "
            "said in the channel." % (parent,))
    smp.post_reply_text_only(body, thread_ts=ts, channel_id=CHANNEL)
