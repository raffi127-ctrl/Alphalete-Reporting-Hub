"""Slack safety net for AT&T Fiber Owners removals — reaction-driven.

Flow (Raf 2026-07-27, mirroring the social-media approval automation):
  Phase 1 (post): a parent "ICDs being removed from Email Contacts" message, then ONE
                  threaded reply per ICD. Lucy seeds ✅ / ❌ so approvers just tap.
  Phase 2 (finalize, +24h): an ICD is KEPT if an approver (Eve / Raf / Megan / Maud)
                  reacted ✅ on its line; otherwise it's removed.

Semantics (as Raf phrased it — "removed tomorrow if not ✅"):
  ✅  = keep on the list (still an active ICD)
  ❌  = confirm the removal
  no approver reaction = removed tomorrow (default)

Reactions are READ via conversations_replies (history scope) — reactions.get needs a
scope the token lacks (same as brand_audit.social_inbox). Posts + reacts AS the token
identity: Lucy on the mini, Megan on the laptop.
"""
from __future__ import annotations

import os
import re
import ssl
from typing import Dict, List, Optional, Tuple

_ACRONYM = re.compile(r"^[A-Z]{2,4}$")


def clean_name(name: str) -> str:
    """Display name for Slack: drop org/location tags a contact tacked on, e.g.
    'Tony Chavez SCI Cali' → 'Tony Chavez'. Truncates at the first all-caps acronym
    token (SCI) or a parenthetical; keeps real multi-word names ('Jose Antonio
    Chavez', 'John Richard Young') untouched."""
    n = re.sub(r"\s*[\(\[].*$", "", name or "").strip()
    toks = n.split()
    out: List[str] = []
    for i, t in enumerate(toks):
        if i >= 1 and _ACRONYM.match(t):
            break
        out.append(t)
    return " ".join(out) or (name or "").strip()

CHANNEL_ID = os.environ.get("FIBER_DISTRO_SLACK_CHANNEL", "C075PCEL92M")  # #l10-alphalete

KEEP_EMOJI = "white_check_mark"     # ✅  keep
REMOVE_EMOJI = "x"                   # ❌  confirm removal

# Only these people's reactions count (Raf 2026-07-27). Eve pending — add her ID.
APPROVERS: Dict[str, str] = {
    "Eve": "U088E2KJEV8",     # Evelyn Sobrino
    "Raf": "U045Z8N0ZQC",     # Rafael Hidalgo
    "Megan": "U04G5HJBGFN",   # Megan Hines
    "Maud": "U045USN7NCD",    # Maud Miller
}


def _client():
    """Channel posts/reactions use the xoxp USER token (Lucy on the mini, Megan on
    the laptop) — same pattern as every other channel-posting report."""
    import certifi
    from slack_sdk import WebClient
    from automations.shared import slack_metrics_post as smp
    ctx = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=smp._load_token(), ssl=ctx)


def _strip(text: str) -> str:
    return (text or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def post_departures(departures: List[dict], roster_date: str,
                    channel: str = CHANNEL_ID, dry_run: bool = True) -> Optional[dict]:
    """Post the parent + one reply per ICD with seeded ✅/❌. Returns
    {parent_ts, candidates:[{name,emails,resourceName,reply_ts}]} (None if none)."""
    if not departures:
        return None
    parent_text = "🐺 *ICDs being removed from Email Contacts* — ✅ keep · ❌ remove"

    if dry_run:
        from pathlib import Path
        outdir = Path(__file__).resolve().parents[2] / "output" / "fiber_owners_distro"
        outdir.mkdir(parents=True, exist_ok=True)
        preview = [parent_text] + [f"    ↳ *{clean_name(d['name'])}* — removed tomorrow if not ✅   [✅ ❌]"
                                   for d in departures]
        txt = "\n".join(preview)
        (outdir / f"slack-departures-{roster_date}.txt").write_text(txt, encoding="utf-8")
        print(f"[dry-run] would post to {channel}:\n"
              f"------------------------------------------------------------\n{txt}\n"
              f"------------------------------------------------------------")
        return None

    cli = _client()
    parent = cli.chat_postMessage(channel=channel, text=parent_text)
    parent_ts = parent["ts"]
    cands = []
    for d in departures:
        reply = cli.chat_postMessage(
            channel=channel, thread_ts=parent_ts,
            text=f"*{clean_name(d['name'])}* — removed tomorrow if not ✅")
        ts = reply["ts"]
        for emoji in (KEEP_EMOJI, REMOVE_EMOJI):
            try:
                cli.reactions_add(channel=channel, timestamp=ts, name=emoji)
            except Exception:
                pass
        cands.append({"name": d["name"], "emails": d.get("emails") or [],
                      "resourceName": d["resourceName"], "reply_ts": ts})
    return {"parent_ts": parent_ts, "candidates": cands}


def _reactions_by_ts(cli, parent_ts: str, channel: str) -> Dict[str, list]:
    """{message_ts: [reactions]} for the thread, via conversations_replies."""
    out: Dict[str, list] = {}
    try:
        for m in cli.conversations_replies(channel=channel, ts=parent_ts).get("messages", []):
            out[m["ts"]] = m.get("reactions") or []
    except Exception:
        pass
    return out


def read_decisions(parent_ts: str, candidates: List[dict],
                   channel: str = CHANNEL_ID) -> Tuple[List[dict], List[dict]]:
    """Return (to_remove, to_keep). An ICD is KEPT only if an APPROVER reacted ✅ on
    its line; everything else is removed."""
    cli = _client()
    rx = _reactions_by_ts(cli, parent_ts, channel)
    approver_ids = set(APPROVERS.values())
    keep, remove = [], []
    for c in candidates:
        reacts = rx.get(c["reply_ts"], [])
        kept = any(r.get("name") == KEEP_EMOJI
                   and approver_ids.intersection(r.get("users") or [])
                   for r in reacts)
        (keep if kept else remove).append(c)
    return remove, keep


def post_summary(parent_ts: str, removed: List[dict], kept: List[dict],
                 channel: str = CHANNEL_ID, dry_run: bool = True) -> None:
    parts = [f"✅ Done — removed {len(removed)} ICD(s) from Email Contacts."]
    if kept:
        parts.append("Kept (✅): " + ", ".join(clean_name(m.get("name", "?")) for m in kept))
    text = "\n".join(parts)
    if dry_run:
        print(f"[dry-run] would post summary to thread {parent_ts}:\n{text}")
        return
    _client().chat_postMessage(channel=channel, thread_ts=parent_ts, text=text)
