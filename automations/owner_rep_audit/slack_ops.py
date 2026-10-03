"""Slack side: who is who in the AO workspace, the owner DMs, and the removal.

Two tokens, on purpose:
  * Lucy's user token (shared.slack_metrics_post._client) SENDS and READS the
    owner DMs, so every message comes from Lucy, never from a person.
  * the AO Cleanup token (ao_cleanup.slack_read) LOOKS UP members and
    DEACTIVATES them through SCIM (needs the `admin` scope; an AO admin account
    answers 403 -- only Megan, the Owner, can deactivate those).
Both live on Lucy 1, which is why this job runs there.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from automations.owner_rep_audit import config as C

SCIM_URL = "https://api.slack.com/scim/v1/Users/{uid}"


def fold(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]+", " ", (name or "").lower()).split())


def _live(users: List[Dict]) -> List[Dict]:
    return [u for u in users
            if not (u.get("deleted") or u.get("bot") or u.get("external"))]


def find_owner(owner: str, users: List[Dict]) -> Optional[str]:
    """The owner's member id: the override table first, then a UNIQUE exact
    name match. Two people with the owner's name -> None (a DM to the wrong
    person asking who to fire is the one mistake this can't make)."""
    if owner in C.OWNER_SLACK:
        return C.OWNER_SLACK[owner]
    hits = [u["id"] for u in _live(users) if fold(u["name"]) == fold(owner)]
    return hits[0] if len(hits) == 1 else None


def find_rep(rep: Dict, users: List[Dict]) -> Optional[Dict]:
    """The rep's live Slack account: email first, then a unique exact name."""
    live = _live(users)
    email = (rep.get("email") or "").lower()
    if email:
        for u in live:
            if (u.get("email") or "").lower() == email:
                return u
    hits = [u for u in live if fold(u["name"]) == fold(rep["name"])]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------ DMs (Lucy)

def lucy():
    from automations.shared.slack_metrics_post import _client
    return _client()


def open_dm(cli, uid: str) -> str:
    return cli.conversations_open(users=uid)["channel"]["id"]


def send(cli, channel: str, text: str, thread_ts: str = None) -> str:
    kw = {"thread_ts": thread_ts} if thread_ts else {}
    return cli.chat_postMessage(channel=channel, text=text, **kw)["ts"]


def owner_messages(cli, channel: str, uid: str, after_ts: str) -> List[Dict]:
    """The owner's own messages in the DM newer than `after_ts`, oldest first.
    Threaded replies to Lucy's DM count too: owners answer both ways."""
    msgs = cli.conversations_history(channel=channel, oldest=after_ts,
                                     limit=200).get("messages", [])
    out = [m for m in msgs if m.get("user") == uid]
    for m in msgs:
        if m.get("reply_count"):
            rep = cli.conversations_replies(channel=channel, ts=m["ts"],
                                            oldest=after_ts, limit=200)
            out += [r for r in rep.get("messages", [])
                    if r.get("user") == uid and r["ts"] != m["ts"]
                    and float(r["ts"]) > float(after_ts)]
    uniq = {m["ts"]: m for m in out}
    return [uniq[k] for k in sorted(uniq, key=float)]


# ------------------------------------------------------------- removal (SCIM)

def deactivate(uid: str) -> str:
    """'ok' | 'admin' (403: an AO admin, Megan only) | 'error: …'."""
    import requests
    from automations.ao_cleanup.slack_read import load_token
    r = requests.delete(SCIM_URL.format(uid=uid), timeout=30,
                        headers={"Authorization": f"Bearer {load_token()}"})
    if r.status_code in (200, 204):
        return "ok"
    if r.status_code == 403:
        return "admin"
    return f"error: HTTP {r.status_code} {r.text[:120]}"
