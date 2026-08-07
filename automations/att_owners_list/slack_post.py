"""The weekly note to #revision-emails: who joined the ATT program, who didn't
sell, and what that did to the Country Sales Board.

NOT a review gate. The other four posts in this channel wait for a ✅ before
something is sent; this one reports work that has ALREADY happened, so it tags
nobody and asks for nothing [[project_captainship-review-gate]]. The channel is
right anyway: it is where the people who watch these reports already look.

Posted through the provisioned slack-user-token, the same path every metrics
post uses — so WHO it comes from is whoever that machine's token belongs to.
On Lucy 1 (where the Friday run is scheduled) that is Lucy; run by hand from
Eve's Windows box the token is Evelyn's and the post carries her name.
[[reference_lucy-slack-identity]] [[project_slack-token-on-windows-is-evelyn]]
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from automations.shared import slack_metrics_post as smp

# #revision-emails. Hardcoded like the other gates: the reporting token can
# neither create nor list channels by name, and a rename keeps the id.
CHANNEL = "C0BLLU9M0A2"
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE/edit"
             "?gid=601599943#gid=601599943")


def we_label(sunday: dt.date) -> str:
    """'WE 8.2' — month.day unpadded, the way the boards label their weeks."""
    return f"WE {sunday.month}.{sunday.day}"


def _owner_line(pull, name: str) -> str:
    o = next((x for x in pull.owners if x.name == name), None)
    return f"• {name}" if o is None else f"• {o.name} — {o.total} units"


def build(plan, pull, *, board: Optional[dict] = None,
          tab: str = "ATT Owners List") -> str:
    """The message: THREE lists, what the board picked up, and the link.

    Eve 2026-08-07 — nothing else. The first version carried the week's unit
    count, the week it compared against, a sentence explaining what red means
    and a running "N owners still out from earlier weeks" tally. All of that is
    on the tab, in colour, for anyone who opens the link; in the channel it
    buried the three names that actually changed this week."""
    L: List[str] = [f"*ATT Owners List — {we_label(plan.sunday)}*"]

    if plan.new:
        L.append(f"\n:new: *Joined the program ({len(plan.new)})*")
        L += [_owner_line(pull, n) for n in sorted(plan.new)]
    if plan.back:
        L.append(f"\n:arrows_counterclockwise: *Back at selling "
                 f"({len(plan.back)})*")
        L += [_owner_line(pull, n) for n in sorted(plan.back)]
    if plan.dropped:
        L.append(f"\n:warning: *No sales for the week ({len(plan.dropped)})*")
        L += [f"• {n}" for n in sorted(plan.dropped)]
    if not plan.new and not plan.back and not plan.dropped:
        L.append("\nNo changes this week — same owners as last week.")

    if board:
        if board.get("added"):
            L.append(f"\n:white_check_mark: Added to the *Country Sales Board* "
                     f"(all three boxes): {', '.join(board['added'])}")
        elif board.get("would_add"):
            L.append(f"\n:construction: Country Sales Board — would add: "
                     f"{', '.join(board['would_add'])} (dry-run)")
    L.append(f"\n<{SHEET_URL}|Open the '{tab}' tab>")
    return "\n".join(L)


def post(text: str, *, dry_run: bool = True, channel: str = CHANNEL,
         logfn=print) -> Optional[str]:
    if dry_run:
        logfn("── DRY-RUN, would post to #revision-emails ──")
        logfn(text)
        logfn("──────────────────────────────────────────────")
        return None
    r = smp._client().chat_postMessage(channel=channel, text=text,
                                       unfurl_links=False)
    logfn(f"✓ posted to {channel} ts={r['ts']}")
    return r["ts"]
