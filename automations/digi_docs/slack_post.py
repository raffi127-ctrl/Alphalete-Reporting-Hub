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
    # One line, not three. Everything the run did to a person happens together
    # -- the bundle goes out and the boxes get ticked in the same pass -- so
    # splitting it across a headline and a trailing note just made the reader
    # assemble it themselves (Megan 2026-08-25).
    lines = [f"*{sent}* new start{'' if sent == 1 else 's'}: digi docs sent · "
             f"BG checked · drug test checked"]
    if refused:
        lines.append("")
        lines.append(f"*Needs doing by hand ({len(refused)}):*")
        lines += [f"• {r}" for r in refused]
    # No separate attestation line: the headline above already says the boxes
    # were ticked. The NAMES still matter -- the drug-test box asserts a
    # completed review to AT&T, not a status -- so they stay in the run log,
    # per rep and per box, where they are recoverable without putting thirty
    # names between the reader and the lines they have to act on.

    body = "\n".join(lines)
    if dry_run:
        print(f"\n--- Slack (dry run, NOT posted) -> {CHANNEL} ---")
        print(body)
        return False
    from automations.shared import slack_metrics_post as smp
    parent = smp.ensure_named_thread(HEADER, channel_id=CHANNEL)
    smp.post_reply_text_only(body, thread_ts=parent, channel_id=CHANNEL)
    return True
