"""Where Lucy Broadcast sends — read LIVE from the replies in the channel's
how-it-works thread (config.DESTINATIONS_THREAD_TS).

Megan 2026-10-18: "they may continuously add or remove channels / group
imessages" — so nobody edits code to change the list. People reply in that
thread:

    "send to #alphalete-sales and #a-players-b2b"
    "add the A Players text"
    "remove #alphalete-sales"

Every tick the WHOLE thread is replayed oldest -> newest, starting from an empty
list (plus anything hard-set in config). Stateless on purpose: an edited reply
counts as edited, a deleted reply stops counting, and there's no saved list
that can drift away from what the thread says.

Matching is strict so a casual sentence can't add a destination:
  * Slack  — only a real channel link (type # and pick it) or a "#name" that is
             a channel Lucy is IN. A channel she's not in is reported back
             ("invite @Lucy Reporting first"), never silently dropped.
  * Texts  — only a name that IS one of the group chats in Messages on this
             Mac (Lucy 1). Longest name wins, so "A Players" inside
             "A Players Leaders" isn't double-matched.
  * Remove — the reply contains remove / stop / take off / don't send / no
             longer / unsubscribe; then everything it names comes OFF.

Python 3.9-safe.
"""
from __future__ import annotations

import platform
import re
from typing import Dict, List, Optional, Tuple

_REMOVE = re.compile(
    r"\b(remove|stop|take\s+(?:\w+\s+)?off|don'?t\s+send|do\s+not\s+send|"
    r"no\s+longer|unsubscribe|delete)\b", re.I)
_CHAN_LINK = re.compile(r"<#([CG][A-Z0-9]+)(?:\|([^>]*))?>")
_CHAN_TEXT = re.compile(r"(?<![\w<])#([a-z0-9][a-z0-9_\-]*)", re.I)


# Words people put around a bare name that aren't part of it.
# Includes the label words from Megan's examples ("Slack Channel: x",
# "Imessage Group - x").
_FILLER = ("please", "pls", "add", "send", "to", "the", "channel", "slack",
           "also", "and", "from", "it", "this", "too", "imessage", "group",
           "text", "chat")
# Slack sends emoji as :fire: text; Messages names hold the real 🔥 (which
# _norm drops). Strip the code so "Owners:fire:" == "Owners🔥".
_EMOJI_CODE = re.compile(r":[a-z0-9_+\-]+:", re.I)
# A reply SHOWING the format ("EXAMPLES: ...") is not a request.
_EXAMPLE = re.compile(r"\bexamples?\b", re.I)


def _norm(s: str) -> str:
    """Lowercase words only — 'A-Players 🔥 ' -> 'a players'."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def is_removal(text: str) -> bool:
    return bool(_REMOVE.search(text or ""))


def parse_reply(text: str, channels: Dict[str, str],
                groups: List[str]) -> Dict:
    """What ONE reply asks for.

    channels: {channel_id: name} for channels Lucy is in.
    groups:   iMessage group names on this Mac.
    Returns {"remove", "slack": [ids], "groups": [names],
             "not_member": [ids or #names Lucy isn't in]}."""
    text = text or ""
    if _EXAMPLE.search(text):
        return {"remove": False, "slack": [], "groups": [], "not_member": [],
                "example": True}
    text = _EMOJI_CODE.sub(" ", text)
    by_name = {n.lower(): cid for cid, n in channels.items()}
    slack: List[str] = []
    not_member: List[str] = []

    def add(cid):
        if cid not in slack:
            slack.append(cid)

    for cid, label in _CHAN_LINK.findall(text):
        if cid in channels:
            add(cid)
        else:
            not_member.append("#" + label if label else cid)
    stripped = _CHAN_LINK.sub(" ", text)
    for name in _CHAN_TEXT.findall(stripped):
        cid = by_name.get(name.lower())
        if cid:
            add(cid)
        else:
            not_member.append("#" + name)

    # Groups: whole-word match of the normalised group name, longest first,
    # blanking each hit so a shorter name inside it can't match again.
    # Blanking keeps every other character's position, so the hits can be
    # returned in the order the person wrote them.
    hay = " %s " % _norm(stripped)
    hits: List[Tuple[int, str]] = []
    for g in sorted({g for g in groups if len(_norm(g)) >= 3},
                    key=lambda g: -len(_norm(g))):
        needle = " %s " % _norm(g)
        at = hay.find(needle)
        if at >= 0:
            hits.append((at, g))
            hay = hay.replace(needle, " " + "|" * (len(needle) - 2) + " ")
    found = [g for _, g in sorted(hits)]

    # One-per-reply (Megan's thread rule): a reply that is JUST a channel name,
    # typed without the #, e.g. "alphalete-sales" or "remove alphalete sales".
    if not slack and not found and not not_member:
        bare = " %s " % _norm(_REMOVE.sub(" ", stripped))
        for w in _FILLER:
            bare = bare.replace(" %s " % w, " ")
        bare = bare.strip()
        for cid, n in channels.items():
            if bare and bare == _norm(n):
                slack.append(cid)
                break
    return {"remove": is_removal(text), "slack": slack, "groups": found,
            "not_member": not_member}


def replay(replies: List[dict], channels: Dict[str, str], groups: List[str],
           base_slack=(), base_groups=()) -> Tuple[List[str], List[str], Dict[str, Dict]]:
    """Apply every reply in order. Returns (slack ids, group names,
    {reply_ts: parse result})."""
    slack = [c for c in base_slack if c]
    texts = [g for g in base_groups if g]
    per: Dict[str, Dict] = {}
    for r in sorted(replies, key=lambda r: r.get("ts", "")):
        p = parse_reply(r.get("text") or "", channels, groups)
        per[r["ts"]] = p
        for cid in p["slack"]:
            if p["remove"]:
                if cid in slack:
                    slack.remove(cid)
            elif cid not in slack:
                slack.append(cid)
        for g in p["groups"]:
            if p["remove"]:
                if g in texts:
                    texts.remove(g)
            elif g not in texts:
                texts.append(g)
    return slack, texts, per


# ---- live lookups -------------------------------------------------------------
def _read(fn, **kw):
    """One Slack read with the shared retry for a mid-body cut-off."""
    try:
        from automations.shared import slack_retry
        return slack_retry.read(fn, **kw)
    except ImportError:
        return fn(**kw)


def thread_replies(cl, channel: str, thread_ts: str, own_user: str) -> List[dict]:
    """Every human reply under the how-it-works post (not the post itself, not
    Lucy's own confirmations)."""
    out: List[dict] = []
    cursor = None
    while True:
        # Small pages: a big Slack response gets cut off mid-body on Lucy 1
        # (IncompleteRead, ~74 KB ceiling) and no retry saves it.
        kw = {"channel": channel, "ts": thread_ts, "limit": 50}
        if cursor:
            kw["cursor"] = cursor
        resp = _read(cl.conversations_replies, **kw)
        for m in resp.get("messages", []):
            if m.get("ts") == thread_ts or m.get("bot_id"):
                continue
            if own_user and m.get("user") == own_user:
                continue
            if m.get("subtype") not in (None, "", "thread_broadcast"):
                continue
            out.append(m)
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def member_channels(cl) -> Dict[str, str]:
    """{id: name} of every channel this token is a member of."""
    out: Dict[str, str] = {}
    cursor = None
    while True:
        # limit=1000 came back truncated on Lucy 1 (2026-10-18 first dry run:
        # IncompleteRead 74352 of ~128k bytes) — Lucy is in a LOT of channels.
        kw = {"types": "public_channel,private_channel",
              "exclude_archived": True, "limit": 100}
        if cursor:
            kw["cursor"] = cursor
        resp = _read(cl.users_conversations, **kw)
        for c in resp.get("channels", []):
            out[c["id"]] = c.get("name") or c["id"]
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def imessage_groups() -> Optional[List[str]]:
    """Group-chat names in Messages on this Mac, or None when they can't be
    read (not a Mac / Messages blocked) — None means "unknown", so callers
    must not tell anyone a group doesn't exist."""
    if platform.system() != "Darwin":
        return None
    try:
        from automations.b2b_dispositions import text_post
        return [c["name"] for c in text_post.list_chats()
                if (c.get("name") or "").strip()]
    except Exception:  # noqa: BLE001
        return None
