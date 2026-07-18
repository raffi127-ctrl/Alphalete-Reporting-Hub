"""Weekly BG-status post to #rafs-office-recruiting, as Lucy.

Model (Raf's design): ONE parent thread per start-week; a single reply under it
lists every scheduled new start + current status; each daily run REBUILDS the
roster from the sheet (so same-day adds appear) and EDITS that reply in place so
it never grows long. A new start-week -> a new parent thread.

State (which message to edit) is kept in output/bg_slack_state.json, keyed by the
week date. dry_run prints the exact message and never touches Slack -- the default,
per the standing "ask before any Slack post" rule.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from automations.shared import slack_metrics_post as smp
from automations.bg_check_sync import parse

CHANNEL_ID = os.environ.get("BGSYNC_SLACK_CHANNEL", "C06881A7WLV")  # #rafs-office-recruiting
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
             f"_updated {updated_str} · auto by Lucy_", ""]
    awaiting_vals = {"", "Sent", "Not Taken"}
    by_status = {}
    awaiting = []
    other = []
    for name, status in people:
        if status in dict(BUCKETS):
            by_status.setdefault(status, []).append(name)
        elif status in awaiting_vals:
            awaiting.append(name)
        else:
            other.append((name, status))
    for status, label in BUCKETS:
        names = sorted(by_status.get(status, []))
        if names:
            lines.append(f"{label} ({len(names)})")
            lines += [f"   • {n}" for n in names]
    if awaiting:
        lines.append(f"🔲 Invited — not taken yet ({len(awaiting)})")
        lines += [f"   • {n}" for n in sorted(awaiting)]
    if other:
        lines.append(f"• Other ({len(other)})")
        lines += [f"   • {n} — {s}" for n, s in sorted(other)]
    if needs_confirm:
        lines.append("")
        lines.append(f"📝 *Report back — needs PASS/FAIL confirmation* ({len(needs_confirm)})")
        lines += [f"   • {n}" for n in sorted(needs_confirm)]
    return "\n".join(lines)


def post_or_update(week_date: str, body: str, *, dry_run: bool = True) -> dict:
    """Post the weekly parent+reply if new; otherwise edit the existing reply.
    Returns the state entry for this week."""
    state = _load_state()
    entry = state.get(week_date)

    if dry_run:
        action = "EDIT existing reply" if entry else "POST new parent + reply"
        print(f"[slack dry-run] channel {CHANNEL_ID} · week {week_date} · {action}\n")
        print(body)
        return entry or {"dry_run": True}

    client = smp._bot_client()
    if not entry:
        parent = client.chat_postMessage(
            channel=CHANNEL_ID,
            text=f"📋 BG Status — New Starts (week of {week_date})")
        reply = client.chat_postMessage(
            channel=CHANNEL_ID, thread_ts=parent["ts"], text=body)
        entry = {"channel": CHANNEL_ID, "parent_ts": parent["ts"],
                 "reply_ts": reply["ts"]}
        state[week_date] = entry
        _save_state(state)
    else:
        client.chat_update(channel=entry["channel"], ts=entry["reply_ts"], text=body)
    return entry
