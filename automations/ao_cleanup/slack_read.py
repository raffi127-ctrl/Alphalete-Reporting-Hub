"""The read-only Slack token for the AO cleanup, and the calls it unlocks.

Separate from the reporting token on purpose. `slack_metrics_post`'s token is
the one every report posts with (chat:write/files:write, no read scopes); this
one is the mirror image — `identify,channels:read,groups:read,users:read` and
nothing that can write. Created 2026-09-10 as the "AO Cleanup" Slack app so the
cleanup could ask `conversations.members` directly instead of reconstructing
membership from join/leave messages, which is provably incomplete in
#alphalete-sales (Slack stopped recording channel_join there on 2025-08-21).

Keep them apart: rotating or revoking this one must never take the reports down.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import os
import ssl
import time
from pathlib import Path
from typing import List, Optional

TOKEN_PATH = Path.home() / ".config" / "recruiting-report" / "slack-read-token"
NEEDED_SCOPES = ("channels:read", "groups:read", "users:read")
# Adding `users:read.email` to the app fills column F. Without it every email
# comes back blank — users.list still works, it just omits the field.
AO_TEAM_ID = "T045BN1CWB1"   # anyone on another team_id is a Slack Connect guest


class NoReadToken(RuntimeError):
    pass


def load_token():
    # type: () -> str
    tok = os.environ.get("SLACK_READ_TOKEN", "").strip()
    if tok:
        return tok
    if not TOKEN_PATH.exists():
        raise NoReadToken(
            "No hay token de lectura en %s.\n"
            "Crealo en api.slack.com/apps (app 'AO Cleanup') con los scopes de "
            "usuario %s, instalalo en AO y guarda el xoxp- ahi."
            % (TOKEN_PATH, ", ".join(NEEDED_SCOPES)))
    # utf-8-sig: Notepad / PowerShell 5.x write a BOM and Slack rejects it.
    return TOKEN_PATH.read_text(encoding="utf-8-sig").strip()


def client():
    from slack_sdk import WebClient
    return WebClient(token=load_token(), ssl=ssl._create_unverified_context())


def _paged(fn, key, **kwargs):
    """Walk a cursor-paginated Slack endpoint, backing off on ratelimited."""
    out, cursor = [], None
    while True:
        for attempt in range(5):
            try:
                resp = fn(cursor=cursor, limit=200, **kwargs)
                break
            except Exception as exc:                     # noqa: BLE001
                wait = getattr(getattr(exc, "response", None), "headers", {}) \
                    .get("Retry-After")
                if wait is None or attempt == 4:
                    raise
                time.sleep(int(wait) + 1)
        out.extend(resp.get(key, []))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def members(channel_id, cli=None):
    # type: (str, Optional[object]) -> List[str]
    """Every current member of the channel. The real list, not a replay."""
    cli = cli or client()
    return _paged(cli.conversations_members, "members", channel=channel_id)


def channel_info(channel_id, cli=None):
    cli = cli or client()
    return (cli.conversations_info(channel=channel_id).get("channel") or {})


def all_users(cli=None):
    """Every account in the workspace, deactivated ones included."""
    cli = cli or client()
    out = []
    for m in _paged(cli.users_list, "members"):
        prof = m.get("profile") or {}
        out.append({
            "id": m.get("id"),
            "name": (prof.get("real_name") or m.get("real_name")
                     or prof.get("display_name") or ""),
            "email": prof.get("email") or "",
            "username": m.get("name") or "",
            "deleted": bool(m.get("deleted")),
            "bot": bool(m.get("is_bot")) or m.get("id") == "USLACKBOT",
            "restricted": bool(m.get("is_restricted")
                               or m.get("is_ultra_restricted")),
            "admin": bool(m.get("is_admin")),
            "team": m.get("team_id") or "",
            "external": bool(m.get("team_id")) and m.get("team_id") != AO_TEAM_ID,
        })
    return out


def one_user(user_id, cli=None):
    """users.info for somebody users.list never returned — in practice a
    Slack Connect member of ANOTHER workspace sitting in one of our channels."""
    cli = cli or client()
    u = cli.users_info(user=user_id).get("user") or {}
    prof = u.get("profile") or {}
    team = u.get("team_id") or prof.get("team") or ""
    return {
        "id": user_id,
        "name": (prof.get("real_name") or u.get("real_name")
                 or prof.get("display_name") or ""),
        "email": prof.get("email") or "",
        "username": u.get("name") or "",
        "deleted": bool(u.get("deleted")),
        "bot": bool(u.get("is_bot")),
        "restricted": bool(u.get("is_restricted") or u.get("is_ultra_restricted")),
        "team": team,
        "external": bool(team) and team != AO_TEAM_ID,
    }
