"""Weekly BG-status post to BOTH recruiting rooms, as Lucy.

#rafs-office-recruiting AND #11280-alphalete-marketing-inc-rafael-hidalgo:
each room gets its OWN parent thread + reply, tracked separately, so the
edit-in-place model works per room.

Model (Raf's design): ONE parent thread per start-week; a single reply under it
lists every scheduled new start + current status; each daily run REBUILDS the
roster from the sheet (so same-day adds appear) and EDITS that reply in place so
it never grows long. A new start-week -> a new parent thread.

State (which message to edit) is kept in output/bg_slack_state.json, keyed by the
week date and then by channel id. dry_run prints the exact message and never
touches Slack -- the default, per the standing "ask before any Slack post" rule.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from automations.shared import slack_metrics_post as smp
from automations.bg_check_sync import parse

# Eve 2026-08-20: the post goes to BOTH rooms -- the original recruiting channel
# AND Raf's office channel. Same workspace org (AO), so nothing leaves the org.
# The new room is PRIVATE: lucy_reporting (U0BCG8F9B5Z) must be invited or its
# post dies with channel_not_found -- which is tolerated per-room (see
# post_or_update) so a missing invite can't take the other room's update down.
# BGSYNC_SLACK_CHANNEL overrides, comma-separated, for a scratch-channel test.
CHANNELS = [
    ("#rafs-office-recruiting", "C06881A7WLV"),
    ("#11280-alphalete-marketing-inc-rafael-hidalgo", "C0AUAS88FGW"),
]
_env = os.environ.get("BGSYNC_SLACK_CHANNEL", "").strip()
if _env:
    CHANNELS = [(cid, cid) for cid in
                (c.strip() for c in _env.split(",")) if cid]
CHANNEL_IDS = [cid for _, cid in CHANNELS]
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "output" / "bg_slack_state.json"

# Display order + emoji for each bucket.
BUCKETS = [
    (parse.PASSED, "✅ Passed"),
    (parse.TAKEN_PENDING, "⏳ Taken / Pending"),
    (parse.REVIEW, "🔎 Review (Sterling deciding)"),
    (parse.FAILED, "❌ Failed"),
    (parse.UNPERFORMABLE, "⚠️ Unperformable"),
]


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def render(week_date: str, people: list, needs_confirm: list, updated_str: str) -> str:
    """people: list of (name, status). needs_confirm: list of names (report back,
    no PASS email). Returns the reply body."""
    lines = [f"*BG Status — New Starts (week of {week_date})*",
             f"*{len(people)} scheduled to start*",
             f"_updated {updated_str} · auto by Lucy_"]

    def section(label: str, names: list, suffixes: dict | None = None) -> None:
        """Blank line + bold header + bullets, so sections read as distinct blocks."""
        if not names:
            return
        lines.append("")            # breathing room between sections
        lines.append(f"*{label} ({len(names)})*")
        for n in sorted(names):
            tail = f" — {suffixes[n]}" if suffixes and n in suffixes else ""
            lines.append(f"   •  {n}{tail}")

    awaiting_vals = {"", "Sent", "Not Taken"}
    by_status: dict = {}
    awaiting: list = []
    other: dict = {}
    for name, status in people:
        if status in dict(BUCKETS):
            by_status.setdefault(status, []).append(name)
        elif status in awaiting_vals:
            awaiting.append(name)
        else:
            other[name] = status
    for status, label in BUCKETS:
        section(label, by_status.get(status, []))
    section("🔲 Invited — not taken yet", awaiting)
    section("• Other", list(other), suffixes=other)
    section("📝 Report back — needs PASS/FAIL confirmation", needs_confirm)
    return "\n".join(lines)


def _week_channels(state: dict, week_date: str) -> dict:
    """Per-channel entries for a week: {channel_id: {parent_ts, reply_ts, ...}}.

    Migrates the pre-2026-08-20 single-channel shape ({channel, parent_ts,
    reply_ts} straight on the week) into the by-channel map, so the room that
    already has a thread keeps getting EDITED instead of re-posted."""
    entry = state.get(week_date) or {}
    if "parent_ts" in entry:                       # legacy flat shape
        return {entry.get("channel", CHANNEL_IDS[0]): entry}
    return dict(entry.get("channels") or {})


def post_or_update(week_date: str, body: str, *, dry_run: bool = True,
                   repost: bool = False, today: str | None = None) -> dict:
    """Post the weekly parent+reply if new; otherwise edit the existing reply.

    Runs once PER CHANNEL in CHANNELS — each room keeps its own parent/reply ts,
    so "edit in place" stays true per room and a room added later just starts its
    own thread instead of back-filling.

    `repost` (Friday afternoon): instead of editing the buried thread, post a
    FRESH parent+reply at the bottom of the channel with the same current content
    so it's visible going into the start week — but only once per day (guarded by
    `reposted_on` so the 3x/day runs don't stack copies). `today` is an ISO date
    string used for that once-a-day guard. Returns {channel_id: entry}."""
    state = _load_state()
    chans = _week_channels(state, week_date)

    if dry_run:
        for name, cid in CHANNELS:
            entry = chans.get(cid)
            if not entry:
                action = "POST new parent + reply"
            elif repost and entry.get("reposted_on") != today:
                action = "REPOST fresh (Friday bump)"
            else:
                action = "EDIT existing reply"
            print(f"[slack dry-run] {name} ({cid}) · week {week_date} · {action}")
        print()
        print(body)
        return chans or {"dry_run": True}

    # The USER token (_client) is 'Lucy' on the mini and is what every live
    # channel post uses (tableau_screenshots, daily_metrics). The bot token is
    # DM-only and isn't on the mini. Lucy must be a member of EVERY channel in
    # CHANNELS — a private room she was never invited to answers channel_not_found.
    client = smp._client()

    def _post_fresh(cid: str) -> dict:
        parent = client.chat_postMessage(
            channel=cid,
            text=f"📋 BG Status — New Starts (week of {week_date})")
        reply = client.chat_postMessage(
            channel=cid, thread_ts=parent["ts"], text=body)
        e = {"channel": cid, "parent_ts": parent["ts"], "reply_ts": reply["ts"]}
        if repost:
            e["reposted_on"] = today
        return e

    failures = []
    for name, cid in CHANNELS:
        entry = chans.get(cid)
        do_repost = bool(entry) and repost and entry.get("reposted_on") != today
        try:
            if not entry or do_repost:
                entry = _post_fresh(cid)
                chans[cid] = entry
                print(f"[slack] {'REPOSTED' if do_repost else 'POSTED new'} "
                      f"{name} week {week_date} parent={entry['parent_ts']} "
                      f"reply={entry['reply_ts']}")
            else:
                client.chat_update(channel=cid, ts=entry["reply_ts"], text=body)
                print(f"[slack] EDITED {name} week {week_date} "
                      f"reply={entry['reply_ts']}")
        except Exception as e:  # noqa: BLE001
            # One room failing (a missing invite, an archived channel) must not
            # cost the other room its update — the sheet write already happened.
            failures.append((name, cid, e))
            print(f"[slack] !! {name} ({cid}) FAILED: {e}")

    # Save whatever landed, so a later run edits instead of double-posting.
    state[week_date] = {"channels": chans}
    _save_state(state)

    if failures and len(failures) == len(CHANNELS):
        name, cid, e = failures[0]
        raise RuntimeError(f"BG Slack post failed in every channel; {name} "
                           f"({cid}): {e}")
    if failures:
        rooms = ", ".join(n for n, _, _ in failures)
        print(f"[slack] WARNING — posted everywhere except: {rooms}. "
              f"Usually lucy_reporting (U0BCG8F9B5Z) is not in that channel.")
    return chans
