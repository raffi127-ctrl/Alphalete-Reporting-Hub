"""Slack safety net for AT&T Fiber Owners removals.

Flow (Megan 2026-07-27):
  Phase 1 (post): announce the owners about to be removed to #l10-alphalete, opening
                  a thread with a 24h objection window.
  Phase 2 (finalize, +24h): anyone a human vouched for with a `Name - not terminated`
                  reply is skipped this cycle (re-add once, NOT pinned); the rest are
                  removed.

Posts AS Lucy (the automated-reports identity), reusing the shared Slack token
helpers. Lucy must be a member of the channel.
"""
from __future__ import annotations

import os
import re
import ssl
from typing import Dict, List, Optional, Tuple

CHANNEL_ID = os.environ.get("FIBER_DISTRO_SLACK_CHANNEL", "C075PCEL92M")  # #l10-alphalete

VOUCH_RE = re.compile(r"^\s*(.+?)\s*[-–—]\s*not\s+terminated\b", re.I)


def _client():
    """Channel posts use the xoxp USER token (Lucy on the mini, Megan on the
    laptop) — same pattern as every other channel-posting report."""
    import certifi
    from slack_sdk import WebClient
    from automations.shared import slack_metrics_post as smp
    ctx = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=smp._load_token(), ssl=ctx)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


def build_message(departures: List[dict], roster_date: str) -> str:
    lines = [
        f"🧹 *AT&T Fiber Owners — weekly list cleanup* (roster {roster_date})",
        "",
        f"These {len(departures)} owner(s) are no longer on Kelly's roster and will be "
        "*removed from the distribution list in 24 hours*:",
    ]
    for m in departures:
        emails = ", ".join(m.get("emails") or [])
        lines.append(f"   •  {m.get('name') or '(no name)'}  <{emails}>")
    lines += [
        "",
        "If any of them did *not* actually terminate, reply in this thread:",
        "`Name - not terminated`   (e.g. `Jane Smith - not terminated`)",
        "Anyone vouched for stays this week.",
    ]
    return "\n".join(lines)


def post_departures(departures: List[dict], roster_date: str,
                    channel: str = CHANNEL_ID, dry_run: bool = True) -> Optional[str]:
    """Post the departure announcement. Returns the thread ts (parent message)."""
    text = build_message(departures, roster_date)
    if dry_run:
        from pathlib import Path
        import datetime as dt
        outdir = Path(__file__).resolve().parents[2] / "output" / "fiber_owners_distro"
        outdir.mkdir(parents=True, exist_ok=True)
        p = outdir / f"slack-departures-{roster_date}.txt"
        p.write_text(text, encoding="utf-8")
        print(f"[dry-run] would post to {channel}:\n"
              f"------------------------------------------------------------\n"
              f"{text}\n"
              f"------------------------------------------------------------\n"
              f"(preview → {p})")
        return None
    resp = _client().chat_postMessage(channel=channel, text=text)
    return resp["ts"]


def _strip(text: str) -> str:
    return (text or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def read_vouched(thread_ts: str, departures: List[dict],
                 channel: str = CHANNEL_ID) -> List[dict]:
    """Departures a human vouched for via `Name - not terminated`. Matches the
    replied name to a candidate leniently (shared last name + first initial, or
    substring)."""
    client = _client()
    resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    vouched_names: List[str] = []
    for msg in resp.get("messages", []):
        if msg.get("ts") == thread_ts:
            continue
        m = VOUCH_RE.match(_strip(msg.get("text", "")))
        if m:
            vouched_names.append(_norm(m.group(1)))

    def matches(cand_name: str, vouch: str) -> bool:
        c, v = _norm(cand_name), vouch
        if not c or not v:
            return False
        if v in c or c in v:
            return True
        ct, vt = c.split(), v.split()
        if ct and vt and ct[-1] == vt[-1] and ct[0][:1] == vt[0][:1]:
            return True          # same surname + first initial
        return len(set(ct) & set(vt)) >= 2

    out = []
    for m in departures:
        if any(matches(m.get("name", ""), v) for v in vouched_names):
            out.append(m)
    return out


def post_summary(thread_ts: str, removed: List[dict], kept: List[dict],
                 channel: str = CHANNEL_ID, dry_run: bool = True) -> None:
    parts = [f"✅ Cleanup done. Removed {len(removed)} owner(s) no longer on the roster."]
    if kept:
        parts.append("Kept this week (vouched as not terminated): "
                     + ", ".join(m.get("name", "?") for m in kept))
    text = "\n".join(parts)
    if dry_run:
        print(f"[dry-run] would post summary to thread {thread_ts}:\n{text}")
        return
    _client().chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
