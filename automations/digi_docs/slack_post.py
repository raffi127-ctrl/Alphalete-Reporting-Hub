"""Post who still needs doing by hand to #11280.

Correct skips are NOT listed — no-shows, terminations, people already marked.
They would bury the names that need acting on, which is the same call
blueink_docs makes and the reason its summary is readable at 8am.
"""
from __future__ import annotations

import os
from typing import List, Tuple

# #11280-alphalete-marketing-inc-rafael-hidalgo — confirmed by Megan
# 2026-08-25, not just inherited from blueink_docs because it sits next
# to it. Same room as the other two new-start steps.
CHANNEL = os.environ.get("DIGI_DOCS_SLACK_CHANNEL", "C0AUAS88FGW")
HEADER = "🗂️ Digi Docs"


def post(sent: int, refused: List[str], attested: List[Tuple],
         *, dry_run: bool = True) -> bool:
    lines = [f"*{sent}* new start{'' if sent == 1 else 's'} sent their document "
             f"bundle."]
    if refused:
        lines.append("")
        lines.append(f"*Needs doing by hand ({len(refused)}):*")
        lines += [f"• {r}" for r in refused]
    if attested:
        # A COUNT here, the names in the run log. These ticks assert a completed
        # drug-screen review to AT&T, so the names have to be recoverable -- but
        # thirty of them on a full Monday is a wall of text between the reader
        # and the two lines they actually have to act on, which is the one thing
        # this post exists to prevent.
        lines.append("")
        lines.append(f"_Background + drug-test boxes ticked for "
                     f"{len(attested)}. Names are in the run log._")

    body = "\n".join(lines)
    if dry_run:
        print(f"\n--- Slack (dry run, NOT posted) -> {CHANNEL} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    smp.post_reply_text_only(body, thread_ts=parent, channel_id=CHANNEL)
    return True
