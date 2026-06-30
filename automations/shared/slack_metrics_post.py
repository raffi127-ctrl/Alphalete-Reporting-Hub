"""Shared Slack-post utilities for reports that reply in the daily
'Metrics M/DD' thread in #alphalete-sales.

Each report:
  1. Finds today's parent thread (or fails with a friendly 'no header
     posted yet' error so the user knows what to do).
  2. Replies in that thread with an image + 'Report Name' comment.
  3. Adds a reaction emoji on the parent thread, matching Eve's
     manual flow (each metric has its own emoji on the parent post —
     e.g. 🔄 Ongoing Cancel, ❎ Disconnected New Internets).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import ssl
from pathlib import Path

CHANNEL_ID = os.environ.get("METRICS_CHANNEL_ID", "C068PH3RFSM")  # default #alphalete-sales; override via METRICS_CHANNEL_ID (e.g. Rashad's private #elevate-sales) — read at import so subprocesses pick it up
TOKEN_PATH = Path.home() / ".config" / "recruiting-report" / "slack-user-token"
# Token for the automated-reports identity 'Lucy' (alphaletereporting@gmail.com)
# used to DM finished reports so they come FROM Lucy, not the person running it.
BOT_TOKEN_PATH = Path.home() / ".config" / "recruiting-report" / "slack-bot-token"


class SlackPostError(RuntimeError):
    pass


def _load_token() -> str:
    """Read the xoxp- token from env var or file.

    Reads the file as utf-8-sig (auto-strips a leading BOM) because
    Windows Notepad + PowerShell 5.x's Set-Content default to writing
    UTF-8 *with* BOM. A BOM in the token corrupts the
    'Authorization: Bearer <token>' header — slack_sdk then crashes with
    'UnicodeEncodeError: latin-1 codec can't encode character \\ufeff'
    when urllib tries to send the request (Eve, 2026-05-28).
    """
    tok = os.environ.get("SLACK_USER_TOKEN")
    if tok:
        return tok.lstrip("﻿").strip()
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text(encoding="utf-8-sig").strip()
    raise SlackPostError(
        f"No Slack user token found. Save it to {TOKEN_PATH} or set "
        f"SLACK_USER_TOKEN env var. See "
        f"automations/ongoing_cancel/SETUP.md for one-time install steps."
    )


def _client():
    import certifi
    from slack_sdk import WebClient
    ctx = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=_load_token(), ssl=ctx)


def _load_bot_token() -> str:
    """The 'Lucy' (Fully Automated Alphalete Reports) token — env SLACK_BOT_TOKEN
    or the slack-bot-token file. Separate from the per-user metrics token so DMs
    are sent AS Lucy."""
    tok = os.environ.get("SLACK_BOT_TOKEN")
    if tok:
        return tok.lstrip("﻿").strip()
    if BOT_TOKEN_PATH.exists():
        return BOT_TOKEN_PATH.read_text(encoding="utf-8-sig").strip()
    raise SlackPostError(
        f"No 'Lucy' Slack token found. Save it to {BOT_TOKEN_PATH} or set "
        "SLACK_BOT_TOKEN. (Create a Slack app on the alphaletereporting account "
        "with chat:write + files:write + im:write, install it, save the token.)")


def _bot_client():
    import certifi
    from slack_sdk import WebClient
    ctx = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=_load_bot_token(), ssl=ctx)


def _resolve_user_id(client, query: str) -> str:
    """Resolve a Slack user id from an email or a (real/display) name. Tries an
    email lookup first, then exact then substring name match over the workspace
    member list. Skips deactivated accounts and bots."""
    q = (query or "").strip()
    if re.fullmatch(r"[UW][A-Z0-9]{6,}", q):    # already a Slack user id
        return q
    if "@" in q:
        try:
            return client.users_lookupByEmail(email=q)["user"]["id"]
        except Exception:
            pass  # fall through to name match
    ql = q.lower()
    members, cursor = [], None
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        members.extend(resp.get("members", []))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break

    def names(u):
        p = u.get("profile", {})
        return [n.lower() for n in (u.get("real_name", ""), p.get("real_name", ""),
                p.get("display_name", ""), u.get("name", "")) if n]

    active = [u for u in members if not u.get("deleted") and not u.get("is_bot")]
    for u in active:                       # exact match
        if ql in names(u):
            return u["id"]
    for u in active:                       # substring fallback
        if any(ql in n for n in names(u)):
            return u["id"]
    raise SlackPostError(
        f"Couldn't find a Slack user matching {query!r} in the workspace.")


def dm_user_with_file(file_path: "Path", *, user: str, comment: str,
                      file_name: str | None = None, dry_run: bool = False,
                      as_bot: bool = True) -> dict:
    """DM a Slack user a file attachment with a comment, FROM Lucy by default.

    `user` may be a Slack user id (U…/W…), an email, or a name. Opens a DM and
    uploads the file. as_bot=True uses the 'Lucy' token (_bot_client) so the DM
    is sent as Lucy; pass as_bot=False to send from the per-user metrics token.
    Token scopes: files:write + im:write (+ users:read only if `user` is a name)."""
    if dry_run:
        return {"dry_run": True, "to_user": user, "file": str(file_path),
                "comment": comment, "as_bot": as_bot}
    client = _bot_client() if as_bot else _client()
    user_id = _resolve_user_id(client, user)
    channel = client.conversations_open(users=user_id)["channel"]["id"]
    resp = client.files_upload_v2(
        channel=channel, file=str(file_path),
        filename=file_name or Path(file_path).name, initial_comment=comment)
    return {"ok": resp.get("ok"), "user_id": user_id, "channel": channel,
            "file": (resp.get("file") or {}).get("id")}


def dm_users_with_file(file_path: "Path", *, users: "list[str]", comment: str,
                       file_name: str | None = None, dry_run: bool = False,
                       as_bot: bool = True) -> dict:
    """DM a file to a GROUP of Slack users from Lucy. Tries ONE multi-party DM
    (a single shared thread — needs the mpim:write scope); if Lucy lacks that
    scope (or the group open fails for any reason), falls back to an individual
    DM to each user (im:write, which Lucy has) so the PDF still reaches everyone.
    `users` are ids (U…/W…), emails, or names. Returns mode='group_dm' or
    'individual_dms' so the caller can log which path ran."""
    if dry_run:
        return {"dry_run": True, "to_users": users, "file": str(file_path),
                "comment": comment, "as_bot": as_bot}
    client = _bot_client() if as_bot else _client()
    user_ids = [_resolve_user_id(client, u) for u in users]
    try:
        channel = client.conversations_open(users=",".join(user_ids))["channel"]["id"]
        resp = client.files_upload_v2(
            channel=channel, file=str(file_path),
            filename=file_name or Path(file_path).name, initial_comment=comment)
        return {"ok": resp.get("ok"), "mode": "group_dm", "channel": channel,
                "user_ids": user_ids, "file": (resp.get("file") or {}).get("id")}
    except Exception as e:
        # Most likely missing_scope (mpim:write) — deliver individually so the
        # PDF still lands for everyone. Each DM needs only im:write.
        print(f"  group DM unavailable ({type(e).__name__}: {str(e)[:100]}) — "
              f"sending individual DMs instead.")
        results = []
        for uid in user_ids:
            try:
                results.append(dm_user_with_file(
                    file_path, user=uid, comment=comment,
                    file_name=file_name, as_bot=as_bot))
            except Exception as e2:
                print(f"  DM to {uid} failed: {type(e2).__name__}: {str(e2)[:80]}")
                results.append({"ok": False, "user_id": uid})
        return {"ok": any(r.get("ok") for r in results), "mode": "individual_dms",
                "user_ids": user_ids, "results": results}


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4 → '4th', 11 → '11th', 21 → '21st'…"""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{'st' if n % 10 == 1 else 'nd' if n % 10 == 2 else 'rd' if n % 10 == 3 else 'th'}"


_SPANISH_MONTHS = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}


def find_metrics_thread_ts(client, today: dt.date) -> str:
    """Find today's Metrics parent thread in #alphalete-sales.

    Primary match: the daily Slack Workflow that posts at 7:00 AM with
    display name 'Metrics' (bot_profile.name / username == 'Metrics').
    Its body text starts with 'for <date>:' rendered in the viewer's
    locale — no 'Metrics' word in the body, so identity match is the
    only reliable signal.

    Fallback: body-text match for manually-posted headers in either
    English ('Metrics for: May 28th 2026') or legacy short form
    ('Metrics 5/28'). Spanish month names included for completeness.
    """
    text_candidates = [
        f"Metrics for: {today.strftime('%B')} {_ordinal(today.day)} {today.year}",
        f"Metrics for: {today.strftime('%B')} {_ordinal(today.day)}",
        f"Metrics {today.month}/{today.day}",
        f"Metrics {today.month:02d}/{today.day:02d}",
        f"for {today.day} de {_SPANISH_MONTHS[today.month]} de {today.year}",
        f"for {today.day} de {_SPANISH_MONTHS[today.month]}",
    ]
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    resp = client.conversations_history(
        channel=CHANNEL_ID, oldest=str(oldest), limit=100
    )
    for msg in resp.get("messages", []):
        # Identity match — Workflow Builder bot named 'Metrics'.
        bot_name = (msg.get("bot_profile") or {}).get("name") or msg.get("username") or ""
        if bot_name.strip().lower() == "metrics":
            return msg.get("thread_ts") or msg.get("ts")
        # Body-text fallback for manual posts.
        text = msg.get("text", "")
        if any(c in text for c in text_candidates):
            return msg.get("thread_ts") or msg.get("ts")
    expected = (f"'Metrics for: {today.strftime('%B')} "
                f"{_ordinal(today.day)} {today.year}'")
    raise SlackPostError(
        f"Couldn't find today's {expected} header thread (or the Slack "
        f"workflow post) in #alphalete-sales. Post the header thread "
        f"there first, then click Run Again."
    )


def ensure_metrics_thread(today: dt.date | None = None,
                          *, dry_run: bool = False) -> dict:
    """Make sure today's Metrics header thread exists in #alphalete-sales.

    The daily Slack Workflow normally posts the 'Metrics for: <date>'
    header early morning, and each per-metric report just replies to it.
    This is a FALLBACK so a fully-automated run never depends on that
    workflow firing: if today's header is already there (bot OR manual) we
    do nothing and return its ts; if it's missing we post one ourselves,
    in the exact 'Metrics for: <Month> <ordinal> <year>' format that
    find_metrics_thread_ts recognises (so the replies still match it)."""
    today = today or dt.date.today()
    # Match the Slack Workflow bot's header: the dated first line (which
    # find_metrics_thread_ts recognises) + the metric checklist with the same
    # emoji shortcodes the bot uses, so a fallback-posted header reads
    # identically to the normal one. NOTE: this list must stay in sync with the
    # Slack "Metrics" Workflow Builder header (that's the PRIMARY poster; this is
    # only the fallback). Rep Activations added 2026-06-26 — add the matching
    # ":new: Rep Activations" line to the Workflow Builder header too.
    header_text = "\n".join([
        f"Metrics for: {today.strftime('%B')} {_ordinal(today.day)} {today.year}",
        "",
        ":door: Telemapper Knocks",
        ":clock1: Time Gaps",
        ":clipboard: Order Log",
        ":date: Sales scheduled 6+ days out",
        ":no_entry_sign: Canceled Orders",
        ":arrows_counterclockwise: Ongoing Cancel",
        ":negative_squared_cross_mark: Disconnected New Internets",
        ":globe_with_meridians: New Internet Churn",
        ":bar_chart: Wireless Churn",
        ":new: Rep Activations",
    ])
    if dry_run:
        return {"dry_run": True, "header_text": header_text,
                "to_channel": CHANNEL_ID}
    client = _client()
    try:
        ts = find_metrics_thread_ts(client, today)
        return {"ok": True, "existed": True, "thread_ts": ts}
    except SlackPostError:
        pass  # not posted yet — fall through and post it ourselves
    resp = client.chat_postMessage(channel=CHANNEL_ID, text=header_text)
    return {"ok": resp.get("ok"), "existed": False,
            "thread_ts": resp.get("ts"), "header_text": header_text}


def post_reply_text_only(
    text: str,
    *,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
) -> dict:
    """Reply in today's Metrics thread with just a text message (no file
    attachment). Used by reports where 'nothing new' = a one-liner instead
    of an empty-state image. Still adds the parent-thread reaction so the
    metric is marked done on the header."""
    today = today or dt.date.today()
    if dry_run:
        return {"dry_run": True, "would_post_text": text,
                "to_channel": CHANNEL_ID, "react_emoji": react_emoji}
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    resp = client.chat_postMessage(channel=CHANNEL_ID, thread_ts=thread_ts,
                                    text=text)
    out = {"ok": resp.get("ok"), "thread_ts": thread_ts, "ts": resp.get("ts")}
    if react_emoji:
        try:
            r = client.reactions_add(channel=CHANNEL_ID, timestamp=thread_ts,
                                     name=react_emoji)
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            out["reaction_warning"] = str(e)
    return out


def post_reply_with_image(
    image_path: Path,
    *,
    comment: str,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    file_name: str | None = None,
) -> dict:
    """Reply in today's Metrics thread with an image attachment + optional
    reaction emoji on the parent.

    react_emoji: short name WITHOUT colons, e.g. 'arrows_counterclockwise',
    'negative_squared_cross_mark'.
    """
    today = today or dt.date.today()
    if dry_run:
        return {
            "dry_run": True,
            "would_post_image": str(image_path),
            "to_channel": CHANNEL_ID,
            "comment": comment,
            "react_emoji": react_emoji,
        }
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    upload_resp = client.files_upload_v2(
        channel=CHANNEL_ID,
        thread_ts=thread_ts,
        file=str(image_path),
        filename=file_name or f"{comment} {today.month}.{today.day}.png",
        initial_comment=comment,
    )
    out = {
        "ok": upload_resp.get("ok"),
        "thread_ts": thread_ts,
        "file": upload_resp.get("file", {}).get("id"),
    }
    if react_emoji:
        try:
            r = client.reactions_add(
                channel=CHANNEL_ID, timestamp=thread_ts, name=react_emoji
            )
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            # Already-reacted is fine; surface other errors only.
            out["reaction_warning"] = str(e)
    return out


def post_reply_with_file(
    file_path: Path,
    *,
    comment: str,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    file_name: str | None = None,
) -> dict:
    """Reply in today's Metrics thread with an arbitrary file attachment
    (.xlsx, .csv, .pdf, etc.) + optional reaction emoji on the parent.

    Same shape as post_reply_with_image but the default upload filename
    preserves the source file's extension (instead of forcing .png), so
    Slack renders the right preview for spreadsheets / docs / etc.
    """
    today = today or dt.date.today()
    if dry_run:
        return {
            "dry_run": True,
            "would_post_file": str(file_path),
            "to_channel": CHANNEL_ID,
            "comment": comment,
            "react_emoji": react_emoji,
        }
    client = _client()
    thread_ts = find_metrics_thread_ts(client, today)
    default_name = f"{comment} {today.month}.{today.day}{file_path.suffix}"
    upload_resp = client.files_upload_v2(
        channel=CHANNEL_ID,
        thread_ts=thread_ts,
        file=str(file_path),
        filename=file_name or default_name,
        initial_comment=comment,
    )
    out = {
        "ok": upload_resp.get("ok"),
        "thread_ts": thread_ts,
        "file": upload_resp.get("file", {}).get("id"),
    }
    if react_emoji:
        try:
            r = client.reactions_add(
                channel=CHANNEL_ID, timestamp=thread_ts, name=react_emoji
            )
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            out["reaction_warning"] = str(e)
    return out
