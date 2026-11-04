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

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from automations.owner_rep_audit import config as C

SCIM_URL = "https://api.slack.com/scim/v1/Users/{uid}"


def fold(name: str) -> str:
    return " ".join(re.sub(r"[^a-z ]+", " ", (name or "").lower()).split())


# Aptel runs recruiting for the offices. Its people are never the owner's reps
# to remove, whichever Slack they sit in (Eve 2026-11-04): accounts of Aptel's
# own org are already `external`, and this catches the ones on AO's team.
APTEL_DOMAIN = "@aptel.com"


def _live(users: List[Dict]) -> List[Dict]:
    return [u for u in users
            if not (u.get("deleted") or u.get("bot") or u.get("external")
                    or (u.get("email") or "").lower().endswith(APTEL_DOMAIN))]


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


def in_slack(reps: List[Dict], users: List[Dict],
             owner_id: str = "") -> List[Dict]:
    """The OwnerVille reps who still have a live AO Slack account -- the only
    ones this audit asks about (Eve 10/12: the job is cleaning SLACK). The
    owner's own account is never on their list."""
    out = []
    for r in reps:
        acct = find_rep(r, users)
        if acct and acct["id"] != owner_id:
            out.append(dict(r, slack_id=acct["id"]))
    return out


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


# ------------------------------------------------------- protected staff

# Recruiting and admin people sit in OwnerVille as reps, never sell, and their
# owner doesn't know their names, so they land on the owner's list and get a
# REMOVE (Kash 22177, 2026-11-03). Being in an office's recruiting channel, or
# on protected_staff.json, means the owner's OK is not enough.
STAFF_CHANNEL = re.compile(r"recruit|interview", re.I)
PROTECTED_FILE = Path(__file__).with_name("protected_staff.json")


def visible_channels(cli) -> List[Dict]:
    """Every channel this machine's token can see. Private ones it isn't in
    don't show up, so what it protects depends on the token."""
    from automations.ao_cleanup.slack_read import _paged
    return _paged(cli.conversations_list, "channels",
                  types="public_channel,private_channel",
                  exclude_archived=True)


def file_ids() -> Set[str]:
    return set(json.loads(PROTECTED_FILE.read_text(encoding="utf-8"))["slack_ids"])


def protected_ids(cli=None) -> Set[str]:
    """Every Slack id Lucy must not deactivate. Raises if the channels can't
    be read: no answer here has to mean nobody gets deactivated."""
    from automations.ao_cleanup.slack_read import _paged, client
    cli = cli or client()
    ids = file_ids()
    for c in visible_channels(cli):
        if STAFF_CHANNEL.search(c.get("name") or ""):
            ids.update(_paged(cli.conversations_members, "members",
                              channel=c["id"]))
    return ids


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
