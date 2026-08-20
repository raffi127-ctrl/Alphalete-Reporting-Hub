"""Is Lucy in the office's Slack channel? (best-effort, never raises)

The tracker posts go out as Lucy (the xoxp user token), so Lucy must be a
member of the channel before anything can post there. The self-serve form runs
this at submit + confirm time so Megan's ping can already say "Lucy is in" /
"Lucy still needs an invite" instead of finding out on the first morning run.

Uses the same SLACK_USER_TOKEN the corrections ping uses (on Streamlit Cloud
that's the `slack_user_token` secret). A private channel Lucy hasn't been
invited to is INVISIBLE to her token — that comes back "not_found", which for
our channels almost always means "private + no invite yet".
"""
from __future__ import annotations

from typing import Optional


def check_channel(channel_id: str = "", channel_name: str = "") -> dict:
    """-> {status, channel_id, channel_name, note}
    status: member | not_member | not_found | no_token | error
    Tries the id first (exact), then scans by name."""
    out = {"status": "error", "channel_id": (channel_id or "").strip(),
           "channel_name": (channel_name or "").strip(), "note": ""}
    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
    except Exception as e:                            # noqa: BLE001
        out["status"] = "no_token"
        out["note"] = f"no Slack token available ({type(e).__name__})"
        return out

    cid = out["channel_id"]
    if cid:
        try:
            info = client.conversations_info(channel=cid)
            ch = info.get("channel") or {}
            out["channel_id"] = ch.get("id", cid)
            out["channel_name"] = "#" + ch.get("name", out["channel_name"].lstrip("#"))
            out["status"] = "member" if ch.get("is_member") else "not_member"
            return out
        except Exception as e:                        # noqa: BLE001
            # channel_not_found on a user token = Lucy can't see it (bad id, OR
            # a private channel she isn't in). Fall through to the name scan.
            out["note"] = f"id lookup: {e}"[:200]

    name = out["channel_name"].lstrip("#").lower()
    if not name:
        out["status"] = "not_found"
        return out
    try:
        cursor: Optional[str] = None
        while True:
            resp = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True, limit=1000, cursor=cursor)
            for ch in resp.get("channels", []):
                if (ch.get("name") or "").lower() == name:
                    out["channel_id"] = ch.get("id", "")
                    out["channel_name"] = "#" + ch.get("name", name)
                    out["status"] = ("member" if ch.get("is_member")
                                     else "not_member")
                    return out
            cursor = (resp.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        out["status"] = "not_found"
    except Exception as e:                            # noqa: BLE001
        out["status"] = "error"
        out["note"] = f"{type(e).__name__}: {e}"[:200]
    return out


def human_line(res: dict) -> str:
    """One plain-English line about the check, for the ping / the form."""
    ch = res.get("channel_name") or res.get("channel_id") or "the channel"
    s = res.get("status")
    if s == "member":
        return f"Lucy is already in {ch} — good to go."
    if s == "not_member":
        return f"Lucy is NOT in {ch} yet — she needs an invite before this can post."
    if s == "not_found":
        return (f"Couldn't find {ch} — it's probably a private channel Lucy "
                "hasn't been invited to yet (or the name is misspelled).")
    if s == "no_token":
        return "Couldn't check whether Lucy is in the channel (no Slack access here)."
    return f"Channel check failed ({res.get('note') or 'unknown error'})."
