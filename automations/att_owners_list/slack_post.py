"""The weekly note to #revision-emails: who joined the ATT program, who didn't
sell, and what that did to the Country Sales Board.

ONE THREAD PER YEAR (Eve, 2026-08-14). The channel used to get a loose post
every Friday; now the year has a single parent message ('ATT Owners List —
2026') and each week's detail is a reply inside it. Fifty-two weeks of roster
churn read as one story instead of fifty-two orphans scattered between the
gates, and the channel only ever shows one ATT Owners List item.

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
import json
from pathlib import Path
from typing import List, Optional

from automations.shared import slack_metrics_post as smp

# #revision-emails. Hardcoded like the other gates: the reporting token can
# neither create nor list channels by name, and a rename keeps the id.
CHANNEL = "C0BLLU9M0A2"
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE/edit"
             "?gid=601599943#gid=601599943")

# Where the year's parent ts is remembered. A CACHE, never the source of
# truth: the Friday run happens on Lucy 1 and a catch-up run happens on Eve's
# Windows box, and neither can see the other's file — a machine that has never
# posted this year finds the parent by reading the channel instead (below).
STATE_PATH = (Path.home() / ".config" / "recruiting-report" /
              "att_owners_list_threads.json")


def root_text(year: int) -> str:
    """The parent message of the year's thread. Deliberately thin: it is a
    heading people scroll past, and every number lives in the replies."""
    return "\n".join([
        f"*ATT Owners List — {year}*",
        "",
        "Weekly roster changes for the ATT program land in this thread — one "
        "reply per week ending.",
        f"<{SHEET_URL}|Open the 'ATT owners list' tab>",
    ])


def _root_marker(year: int) -> str:
    """What identifies the parent in the channel. The weekly replies start
    '*ATT Owners List — WE 8.9*', so matching the full '— <year>*' is what
    keeps a reply from ever being mistaken for the parent."""
    return f"*ATT Owners List — {year}*"


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


def _remembered(year: int) -> Optional[str]:
    try:
        return (json.loads(STATE_PATH.read_text(encoding="utf-8"))
                .get(str(year)) or None)
    except Exception:                      # missing, empty, or hand-mangled
        return None


def _remember(year: int, ts: str) -> None:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data[str(year)] = ts
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def find_root_ts(client, year: int, *, channel: str = CHANNEL,
                 logfn=print) -> Optional[str]:
    """The ts of this year's parent message, or None if it isn't there yet.

    The cached ts is checked against Slack before it is trusted — a parent that
    was deleted would otherwise send every remaining week of the year into a
    thread nobody can open. When the cache misses (another machine posted it,
    or the file is gone) the channel is read back from Jan 1: conversations_
    history returns only top-level messages, so a weekly reply can't be picked
    up by mistake."""
    marker = _root_marker(year)
    cached = _remembered(year)
    if cached:
        try:
            msgs = client.conversations_replies(
                channel=channel, ts=cached, limit=1).get("messages", [])
            if msgs and msgs[0].get("text", "").startswith(marker):
                return cached
            logfn(f"  cached thread ts={cached} is not this year's parent "
                  f"any more — looking it up in the channel")
        except Exception as e:
            logfn(f"  cached thread ts={cached} unreadable "
                  f"({type(e).__name__}) — looking it up in the channel")

    oldest = dt.datetime(year, 1, 1).timestamp()
    cursor, pages = None, 0
    while pages < 25:                      # ~5k messages; a year of this channel
        resp = client.conversations_history(
            channel=channel, oldest=str(oldest), limit=200, cursor=cursor)
        for msg in resp.get("messages", []):
            if msg.get("text", "").startswith(marker):
                ts = msg.get("thread_ts") or msg.get("ts")
                _remember(year, ts)
                return ts
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        pages += 1
        if not cursor:
            break
    return None


def ensure_root_ts(client, year: int, *, channel: str = CHANNEL,
                   logfn=print) -> str:
    """This year's parent ts, posting the parent if the year is new."""
    ts = find_root_ts(client, year, channel=channel, logfn=logfn)
    if ts:
        logfn(f"  thread for {year}: ts={ts}")
        return ts
    r = client.chat_postMessage(channel=channel, text=root_text(year),
                                unfurl_links=False)
    _remember(year, r["ts"])
    logfn(f"  started the {year} thread — ts={r['ts']}")
    return r["ts"]


def post(text: str, *, year: int, dry_run: bool = True,
         channel: str = CHANNEL, logfn=print) -> Optional[str]:
    """Send the week's detail as a reply in the year's thread.

    No reply_broadcast: the point of the thread is that the channel shows ONE
    ATT Owners List item, and a broadcast copy would put the week back in the
    channel exactly as before. Anyone following the thread still gets it."""
    if dry_run:
        logfn(f"── DRY-RUN, would reply in the {year} thread in "
              f"#revision-emails ──")
        logfn(text)
        logfn("──────────────────────────────────────────────")
        return None
    client = smp._client()
    thread_ts = ensure_root_ts(client, year, channel=channel, logfn=logfn)
    r = client.chat_postMessage(channel=channel, text=text,
                                thread_ts=thread_ts, unfurl_links=False)
    logfn(f"✓ posted to {channel} thread={thread_ts} ts={r['ts']}")
    return r["ts"]
