"""The heads-up in #revision-emails — one running thread per year, per kind.

NOT a review gate. The other posts in this channel wait for a ✅ before something
is sent; these report work that has ALREADY happened, so they tag nobody and ask
for nothing ([[project_captainship-review-gate]], same shape as the ATT Owners
List note). The channel is right anyway: it is where the people who watch these
boards already look.

TWO THREADS, one parent each per calendar year:

    New Owners - Active and Added 2026
    Captainship New Owner - Active and Added 2026

Every add is a REPLY under its parent, so a year of them is one collapsed thread
in the channel instead of a daily drip. The parent's ts lives in the 'New Owners
Log' tab, not in a file on this machine: the Windows box and the mini both run
these reports, and a per-machine anchor would open a second thread for the year
the first time the other one posted.

Posted through the provisioned slack-user-token, like every other channel post —
so WHO it comes from is whoever that machine's token belongs to (Lucy on the
mini, Evelyn on Eve's Windows box). [[reference_lucy-slack-identity]]
"""
from __future__ import annotations

import datetime as dt
import os
from typing import List, Optional

from automations.new_owners import bank

# #revision-emails. Hardcoded like the other posts in this channel: the
# reporting token can neither create nor list channels by name, and a rename
# keeps the id. NEW_OWNERS_CHANNEL_ID retargets it to a scratch channel for a
# live test without touching the code (same escape hatch the Org Board Slack
# post uses).
CHANNEL = os.environ.get("NEW_OWNERS_CHANNEL_ID") or "C0BLLU9M0A2"

TITLES = {
    bank.KIND_ORG: "New Owners - Active and Added",
    bank.KIND_CAPTAINSHIP: "Captainship New Owner - Active and Added",
}
BLURB = {
    bank.KIND_ORG:
        "Running log for the year: every reply is someone from the *New Owners* "
        "list who started selling and now has a row on the Org Sales Board — "
        "daily breakdown and weekly total apps. Nothing to approve, this is a "
        "heads-up.",
    bank.KIND_CAPTAINSHIP:
        "Running log for the year: every reply is a rep who showed up under a "
        "captainship in Tableau and was added to that captainship's boxes and "
        "reports. Nothing to approve, this is a heads-up.",
}


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def thread_key(kind: str, year: int) -> str:
    return f"{year}-{kind.strip().lower()}"


def ensure_thread(log_ws, kind: str, year: int, *, dry_run: bool = False,
                  channel: str = CHANNEL, logfn=print) -> Optional[str]:
    """The year's parent ts for this kind — created + recorded the first time.

    The anchor is saved to the log tab IMMEDIATELY after the post, before any
    reply goes out, so a crash between the two can't strand a parent nobody can
    find (which would show up as a second thread next run)."""
    key = thread_key(kind, year)
    anchor = bank.thread_anchor(log_ws, key)
    if anchor and anchor.get("ts"):
        return anchor["ts"]
    title = f"{TITLES[kind]} {year}"
    text = f"*{title}*\n_{BLURB[kind]}_"
    if dry_run:
        logfn(f"    (dry-run) would open the {year} thread: {title}")
        return None
    r = _client().chat_postMessage(channel=channel, text=text,
                                   unfurl_links=False)
    ts = r["ts"]
    bank.save_thread_anchor(log_ws, key, channel, ts, title)
    logfn(f"    opened the {year} '{TITLES[kind]}' thread (ts={ts})")
    return ts


def _day(today: dt.date) -> str:
    return f"{today.month}/{today.day}"


def campaign_message(adds: List[dict], today: dt.date) -> str:
    """One reply, one bullet per owner: who, and what campaign."""
    lines = [f":new: *{_day(today)}* — added to the Org Sales Board "
             f"({len(adds)} new owner{'s' if len(adds) != 1 else ''})"]
    for a in adds:
        detail = []
        if a.get("units"):
            first = a.get("first_day")
            if first:
                detail.append(f"first sale {first.month}/{first.day}")
            detail.append(f"{a['units']} unit"
                          f"{'s' if a['units'] != 1 else ''} this week")
        if not a.get("org_head"):
            detail.append("no Org Head on the bank row — set it")
        lines.append(f"• *{a['name']}* — {a['campaign']}"
                     + (f" ({' · '.join(detail)})" if detail else ""))
    lines.append("_Daily breakdown + weekly total apps. They roll into the All "
                 "Campaigns board on its next run._")
    return "\n".join(lines)


def captainship_message(adds: List[dict], today: dt.date,
                        siblings: Optional[List[str]] = None) -> str:
    """One reply, one bullet per rep: who, and under which captainship.

    The bullet stays short on purpose — name, captainship, where we saw them.
    The one thing that can need a human (no row on the Org Sales Board, because
    the VA hasn't added them there) is marked ⚠ so it stands out in a list that
    is otherwise pure good news."""
    lines = [f":busts_in_silhouette: *{_day(today)}* — new rep"
             f"{'s' if len(adds) != 1 else ''} under a captainship "
             f"({len(adds)})"]
    for a in adds:
        bits = [f"{a['captain']} captainship"]
        if a.get("where"):
            bits.append(a["where"])
        if a.get("board") is False:
            bits.append("⚠ no row on the Org Sales Board yet — the VA's board "
                        "doesn't list them")
        lines.append(f"• *{a['name']}* — " + " · ".join(bits))
    if siblings:
        lines.append(f"_The captainship's other reports pick them up on their "
                     f"next run: {', '.join(siblings)}._")
    return "\n".join(lines)


def post(log_ws, kind: str, text: str, today: dt.date, *,
         dry_run: bool = False, channel: str = CHANNEL, logfn=print
         ) -> Optional[str]:
    """Reply under the year's parent. Returns the reply ts."""
    ts = ensure_thread(log_ws, kind, today.year, dry_run=dry_run,
                       channel=channel, logfn=logfn)
    if dry_run:
        logfn(f"── DRY-RUN, would reply in #revision-emails "
              f"({TITLES[kind]} {today.year}) ──")
        logfn(text)
        logfn("────────────────────────────────────────────────")
        return None
    r = _client().chat_postMessage(channel=channel, thread_ts=ts, text=text,
                                   unfurl_links=False)
    logfn(f"    ✓ posted to #revision-emails under the {today.year} "
          f"'{TITLES[kind]}' thread (ts={r['ts']})")
    return r["ts"]
