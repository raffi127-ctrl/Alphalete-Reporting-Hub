"""Post who still needs doing by hand to #11280.

Correct skips are NOT listed — no-shows, terminations, people already marked.
They would bury the names that need acting on, which is the same call
blueink_docs makes and the reason its summary is readable at 8am.
"""
from __future__ import annotations

import os
from typing import List, Tuple

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
        # Named, not just counted: these ticks assert a completed drug-screen
        # review to AT&T, and an assertion nobody can audit later is worse than
        # one nobody made.
        lines.append("")
        lines.append(f"_Attestations ticked for {len(attested)}: "
                     + ", ".join(n for n, _m, _t in attested) + "_")

    body = "\n".join(lines)
    if dry_run:
        print(f"\n--- Slack (dry run, NOT posted) -> {CHANNEL} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    smp.post_reply_text_only(body, thread_ts=parent, channel_id=CHANNEL)
    return True
