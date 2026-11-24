"""Daily 5 PM (office-local) owner tag in the weekly BG Status thread.

Raf, 2026-11-24 (via Eve): tag the office owner every day at 5 PM their time
in the "BG Status — New Starts" thread so they can see what changed in the
background checks. Same for EVERY office that gets that thread once the
onboarding project rolls it out — tagging THAT office's owner.

WHY A NEW REPLY AND NOT THE EDITED ONE: the thread's status reply is edited in
place every hour, and Slack does not notify anyone mentioned in an edit. So the
tag is its own reply under the same parent, once a day.

HOW IT DECIDES WHAT CHANGED: each time it tags, it keeps a snapshot of every
person's status for that week (in output/bg_slack_state.json, next to the
thread's ts). The next day's tag lists the difference against that snapshot:
status moves, people added to the week, people taken off it. The first tag of
a week has nothing to compare to, so it gives the current totals instead.
A day with no change still tags, saying so — Raf asked for every day.

TIMING: runs inside the hourly bg_check_sync pass (mini, 8am–9pm Central). The
first pass at or after 17:00 in the OFFICE's time zone tags, once per day
(`tagged_on`). Up to 21:00 local, so a missed 5 PM pass catches up at 6.

── TO ADD AN OFFICE (onboarding rollout) ──────────────────────────────────────
1. Its thread must be posted by the same machinery (a (name, channel_id) in
   slack_post.CHANNELS, or the onboarding equivalent writing the same state
   shape: state[week]["channels"][channel_id] = {parent_ts, reply_ts, ...}).
2. Add ONE line to OWNERS below: channel id → owner's Slack id + time zone.
   Slack ids come from resources/owner-slack-ids.md (watch the look-alikes).
That's all. A channel with no OWNERS line is simply never tagged.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — every runner is 3.9+
    ZoneInfo = None  # type: ignore

from automations.bg_check_sync import parse
from automations.shared.new_start_steps import SLACK_CHANNEL_ID

# channel id -> who to tag there and in what time zone "5 PM" is.
OWNERS: Dict[str, Dict[str, str]] = {
    # #rafs-office-recruiting-11280 — Rafael (Raf) Hidalgo, Texas.
    SLACK_CHANNEL_ID: {"office": "raf", "owner": "Rafael Hidalgo",
                       "slack_id": "U045Z8N0ZQC", "tz": "America/Chicago"},
}

TAG_HOUR = 17          # 5 PM office-local
LAST_HOUR = 21         # don't tag later than this (a pass that missed 5 PM)

# Same display buckets as the thread itself, so the tag reads like it.
_AWAITING = {"", parse.SENT, "Not Taken"}
_LABELS = {
    parse.PASSED: "✅ Passed",
    parse.TAKEN_PENDING: "⏳ Taken / Pending",
    parse.REVIEW: "🔎 Review (Sterling deciding)",
    parse.FAILED: "❌ Failed",
    parse.UNPERFORMABLE: "⚠️ Unperformable",
    "awaiting": "🔲 Invited — not taken yet",
}
_ORDER = [parse.PASSED, parse.FAILED, parse.UNPERFORMABLE, parse.REVIEW,
          parse.TAKEN_PENDING, "awaiting"]


def bucket(status: str) -> str:
    s = (status or "").strip()
    return "awaiting" if s in _AWAITING else s


def label(b: str) -> str:
    return _LABELS.get(b, b or "—")


def snapshot(people: List[Tuple[str, str]]) -> Dict[str, str]:
    """{name: bucket} for the week's roster."""
    return {name: bucket(st) for name, st in people if name}


def diff(prev: Dict[str, str], cur: Dict[str, str]) -> Tuple[
        List[Tuple[str, str, str]], List[Tuple[str, str]], List[str]]:
    """(moved [(name, before, after)], added [(name, now)], removed [names])."""
    moved = [(n, prev[n], cur[n]) for n in sorted(cur)
             if n in prev and prev[n] != cur[n]]
    added = [(n, cur[n]) for n in sorted(cur) if n not in prev]
    removed = sorted(n for n in prev if n not in cur)
    return moved, added, removed


def _totals(cur: Dict[str, str]) -> str:
    counts: Dict[str, int] = {}
    for b in cur.values():
        counts[b] = counts.get(b, 0) + 1
    order = _ORDER + sorted(b for b in counts if b not in _ORDER)
    parts = [f"{label(b)} {counts[b]}" for b in order if counts.get(b)]
    return f"*Now — {len(cur)} scheduled:* " + " · ".join(parts)


def render(slack_id: str, week_date: str, prev: Optional[Dict[str, str]],
           cur: Dict[str, str]) -> str:
    who = f"<@{slack_id}>"
    if prev is None:
        return "\n".join([
            f"{who} Daily BG check update — new starts week of {week_date}",
            _totals(cur),
            "_From tomorrow, this 5 PM note lists every change since the "
            "day before._"])

    moved, added, removed = diff(prev, cur)
    lines = [f"{who} Daily BG check update — new starts week of {week_date}"]
    if not (moved or added or removed):
        lines.append("No background check changes since yesterday.")
    else:
        lines.append("*Changes since yesterday:*")
        by_after: Dict[str, List[str]] = {}
        for n, before, after in moved:
            by_after.setdefault(after, []).append(f"{n} _(was {label(before)})_")
        order = _ORDER + sorted(b for b in by_after if b not in _ORDER)
        for b in order:
            for item in by_after.get(b, []):
                lines.append(f"   •  {label(b)}: {item}")
        for n, now in added:
            lines.append(f"   •  🆕 Added to the week: {n} — {label(now)}")
        for n in removed:
            lines.append(f"   •  ➖ No longer on the week: {n}")
    lines.append("")
    lines.append(_totals(cur))
    return "\n".join(lines)


def _local_now(tz: str, now_utc: Optional[dt.datetime]) -> dt.datetime:
    base = now_utc or dt.datetime.now(dt.timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=dt.timezone.utc)
    return base.astimezone(ZoneInfo(tz)) if ZoneInfo else base


def due(entry: dict, tz: str, now_utc: Optional[dt.datetime] = None) -> bool:
    """True on the first pass between 5 PM and 9 PM office-local each day."""
    local = _local_now(tz, now_utc)
    if not (TAG_HOUR <= local.hour < LAST_HOUR):
        return False
    return entry.get("tagged_on") != local.date().isoformat()


def maybe_tag(week_date: str, people: List[Tuple[str, str]], chans: dict, *,
              client=None, dry_run: bool = True,
              now_utc: Optional[dt.datetime] = None, log=print) -> List[str]:
    """Tag each channel's owner in this week's thread if it's their 5 PM.

    Mutates `chans` (the per-channel state entries) with `tagged_on` and
    `tag_snapshot`; the caller saves state. Returns the channel ids tagged.
    Never raises — the tag is an extra, the thread update is the job.
    """
    done: List[str] = []
    cur = snapshot(people)
    for cid, entry in (chans or {}).items():
        owner = OWNERS.get(cid)
        if not owner or not isinstance(entry, dict) or not entry.get("parent_ts"):
            continue
        try:
            if not due(entry, owner["tz"], now_utc):
                continue
            prev = entry.get("tag_snapshot")
            text = render(owner["slack_id"], week_date, prev, cur)
            if dry_run:
                log(f"[owner-tag dry-run] {owner['owner']} in {cid} · "
                    f"week {week_date}\n{text}")
                continue
            client.chat_postMessage(channel=cid, thread_ts=entry["parent_ts"],
                                    text=text)
            entry["tagged_on"] = _local_now(owner["tz"], now_utc).date().isoformat()
            entry["tag_snapshot"] = cur
            done.append(cid)
            log(f"[owner-tag] tagged {owner['owner']} in {cid} week {week_date}")
        except Exception as e:  # noqa: BLE001
            log(f"[owner-tag] ⚠ {cid} week {week_date} skipped: "
                f"{type(e).__name__}: {str(e)[:160]}")
    return done
