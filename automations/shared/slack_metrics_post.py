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
import time
from pathlib import Path

CHANNEL_ID = os.environ.get("METRICS_CHANNEL_ID", "C068PH3RFSM")  # default #alphalete-sales; override via METRICS_CHANNEL_ID (e.g. Rashad's private #elevate-sales) — read at import so subprocesses pick it up
# Optional per-office label appended to the Metrics header, e.g. "Salik Mallick".
# REQUIRED when two offices post to the SAME channel (Salik + Hammad both in
# #elite-prime-sales) so each gets its OWN thread and you can tell them apart —
# ensure_metrics_thread adds it to the header, find_metrics_thread_ts requires it
# so an office finds ITS thread, not the other's. Unset = original single-office
# behaviour, unchanged. Read at import so metric subprocesses inherit it.
HEADER_LABEL = os.environ.get("METRICS_HEADER_LABEL", "").strip()
# Raf 8/23 (Loom): everything that lands in #alphalete-sales ALSO lands in
# #alphalete-lvl1-chat — same parents, same replies, its own copy of each thread
# (Slack can't share a thread across channels). Keyed by the PRIMARY channel so
# other offices' channels (Rashad's via METRICS_CHANNEL_ID, per-office
# channel_id args, offices that swap smp.CHANNEL_ID) never mirror. Lucy must be
# a member of every mirror channel (lvl1 is private). Kill switch:
# ALPHALETE_MIRROR_OFF=1 turns all mirroring off without a code change.
MIRROR_CHANNELS = {
    "C068PH3RFSM": ["C09JG28CD27"],   # #alphalete-sales -> #alphalete-lvl1-chat
}


def mirror_channels(channel_id: str) -> list:
    """The channels `channel_id`'s posts must be copied into ([] for most)."""
    if os.environ.get("ALPHALETE_MIRROR_OFF", "") == "1":
        return []
    return MIRROR_CHANNELS.get(channel_id or "", [])
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
    """The 'Lucy' (Lucy 1) token — env SLACK_BOT_TOKEN
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


def _norm_first_line(text: str) -> str:
    """A parent message's dated first line, markdown-stripped + whitespace-
    collapsed — the identity we match a thread's cross-channel twin on."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return re.sub(r"\s+", " ", first.replace("*", "")).strip()


def _mirror_thread_ts(client, src_channel: str, src_ts: str,
                      dst_channel: str, today: dt.date) -> str:
    """The dst-channel twin of a thread parent: today's dst message whose first
    line matches the src parent's (we post identical parents into every mirror),
    posting a copy of the src parent if it isn't there yet. First-line match, not
    whole-text, so Slack's own text normalization can never make the copy
    unrecognizable (which would spawn a duplicate parent per reply)."""
    src = client.conversations_replies(channel=src_channel, ts=src_ts, limit=1)
    text = (src.get("messages") or [{}])[0].get("text") or ""
    key = _norm_first_line(text)
    if not key:
        raise SlackPostError("mirror: source thread parent has no text")
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    cursor = None
    for _ in range(10):
        resp = client.conversations_history(
            channel=dst_channel, oldest=str(oldest), limit=200,
            **({"cursor": cursor} if cursor else {}))
        for msg in resp.get("messages", []):
            if _norm_first_line(msg.get("text", "")) == key:
                return msg.get("thread_ts") or msg.get("ts")
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return client.chat_postMessage(channel=dst_channel, text=text)["ts"]


def _mirror_reply(client, channel_id: str, thread_ts: str, today: dt.date,
                  out: dict, *, text: str | None = None,
                  file_path=None, file_name: str | None = None,
                  comment: str | None = None,
                  react_emoji: str | None = None,
                  wait_visible: bool = False,
                  top_level: bool = False) -> None:
    """Copy one thread reply (text OR file) into every mirror of `channel_id`,
    into the mirror's own twin of the thread. Appends per-channel results onto
    out['mirrors']. Best-effort by design: a broken mirror prints loudly but
    never fails the primary post."""
    for dst in mirror_channels(channel_id):
        try:
            # A top-level primary mirrors as a top-level message too — looking up
            # (or creating) a twin THREAD for a post that isn't in one would file
            # the mirror somewhere the original isn't.
            m_ts = (None if top_level else
                    _mirror_thread_ts(client, channel_id, thread_ts, dst, today))
            if file_path is not None:
                resp = client.files_upload_v2(
                    channel=dst, thread_ts=m_ts, file=str(file_path),
                    filename=file_name, initial_comment=comment)
                if wait_visible and resp.get("ok"):
                    # same ordering guarantee as the primary thread (Eve 8/19:
                    # small images overtake big ones without this)
                    wait_for_share(client, dst, m_ts, _uploaded_file_id(resp),
                                   text=comment or "")
            else:
                resp = client.chat_postMessage(channel=dst, thread_ts=m_ts,
                                               text=text)
            if react_emoji:
                try:
                    client.reactions_add(channel=dst, timestamp=m_ts,
                                         name=react_emoji)
                except Exception:      # noqa: BLE001 — already-reacted is fine
                    pass
            out.setdefault("mirrors", []).append(
                {"channel": dst, "ok": resp.get("ok"), "thread_ts": m_ts})
        except Exception as e:      # noqa: BLE001
            print(f"  reply mirror to {dst} failed: "
                  f"{type(e).__name__}: {str(e)[:120]}")
            out.setdefault("mirrors", []).append(
                {"channel": dst, "ok": False, "error": str(e)[:200]})


def find_metrics_thread_ts(client, today: dt.date,
                           channel_id: str | None = None) -> str:
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
        channel=channel_id or CHANNEL_ID, oldest=str(oldest), limit=100
    )
    for msg in resp.get("messages", []):
        text = msg.get("text", "")
        # LABELLED (two offices share a channel): the office's thread must carry
        # BOTH today's date line AND this office's label — otherwise office A
        # would grab office B's thread. The 'Metrics' workflow-bot shortcut is
        # skipped here (labelled threads are posted by our code, not that bot).
        if HEADER_LABEL:
            if HEADER_LABEL in text and any(c in text for c in text_candidates):
                return msg.get("thread_ts") or msg.get("ts")
            continue
        # Identity match — Workflow Builder bot named 'Metrics'.
        bot_name = (msg.get("bot_profile") or {}).get("name") or msg.get("username") or ""
        if bot_name.strip().lower() == "metrics":
            return msg.get("thread_ts") or msg.get("ts")
        # Body-text fallback for manual posts.
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
                          *, dry_run: bool = False,
                          sections: list | None = None) -> dict:
    """Make sure today's Metrics header thread exists in #alphalete-sales.

    OUR CODE posts this header (Megan 2026-07-10: the old Slack Workflow
    that used to post it is retired). If today's header is somehow already
    there (a manual post) we reuse its ts; otherwise we post one ourselves,
    in the exact 'Metrics for: <Month> <ordinal> <year>' format that
    find_metrics_thread_ts recognises (so the replies still match it).
    Because this is now the primary poster, the checklist below is the
    source of truth — keep it in sync with the metrics actually posted.

    `sections`: when given (a list of "emoji Label" lines), the header lists
    EXACTLY those instead of the default 12-metric D2D checklist — so an office
    that posts a different set (e.g. a wireless/NDS office) gets a header that
    matches ITS boards, not the internet template. Omitted => the default 12
    (every existing D2D office, byte-identical)."""
    today = today or dt.date.today()
    # The dated first line (which find_metrics_thread_ts recognises) + the
    # metric checklist. This code is the poster now (no more Slack Workflow),
    # so this list IS the header — keep it in sync with the metrics posted
    # (Rep Activations 2026-06-26; New Internet ABP % 2026-07-10).
    # When two offices share a channel, the label (owner name) goes in the header
    # so each thread is distinct + human-distinguishable (Megan 2026-07-15).
    _label_suffix = f" — {HEADER_LABEL}" if HEADER_LABEL else ""
    # Bold first line (Megan 2026-07-10). find_metrics_thread_ts matches on a
    # substring, so the '*...*' wrapper doesn't break thread detection.
    _first = (f"*Metrics for: {today.strftime('%B')} {_ordinal(today.day)} "
              f"{today.year}{_label_suffix}*")
    _default = [
        # ONE combined board since Raf's Loom 2026-08-22 (knocks + time gaps
        # in a single image — the separate Time Gaps post retired), so ONE
        # header line (Megan 2026-08-22).
        ":door: Total Knocks (with Time Gaps)",
        ":clipboard: Order Log",
        ":date: Sales scheduled 6+ days out",
        ":no_entry_sign: Canceled Orders",
        ":arrows_counterclockwise: Ongoing Cancel",
        ":negative_squared_cross_mark: Disconnected New Internets",
        ":globe_with_meridians: New Internet Churn",
        ":bar_chart: Wireless Churn",
        ":new: Rep Activations",
        ":credit_card: New Internet ABP %",
        # Screenshot of the office's Tableau Metrics board (Raf 2026-07-16).
        ":camera_with_flash: Tableau Metrics",
    ]
    header_text = "\n".join([_first, "", *(sections if sections else _default)])
    if dry_run:
        return {"dry_run": True, "header_text": header_text,
                "to_channel": CHANNEL_ID,
                "mirrors_to": mirror_channels(CHANNEL_ID)}
    client = _client()
    try:
        ts = find_metrics_thread_ts(client, today)
        out = {"ok": True, "existed": True, "thread_ts": ts}
    except SlackPostError:
        resp = client.chat_postMessage(channel=CHANNEL_ID, text=header_text)
        out = {"ok": resp.get("ok"), "existed": False,
               "thread_ts": resp.get("ts"), "header_text": header_text}
    # copy the parent into each mirror channel (best-effort — a broken mirror
    # must never take down the primary thread)
    if out.get("thread_ts"):
        for dst in mirror_channels(CHANNEL_ID):
            try:
                _mirror_thread_ts(client, CHANNEL_ID, out["thread_ts"], dst, today)
            except Exception as e:      # noqa: BLE001
                print(f"  metrics-thread mirror to {dst} failed: "
                      f"{type(e).__name__}: {str(e)[:120]}")
    return out


def find_named_thread_ts(client, title: str, today: dt.date,
                         *, channel_id: str | None = None) -> str:
    """Find TODAY's parent post for a NAMED thread (one that is NOT the daily
    'Metrics for:' thread) — e.g. 'Knocks for other offices'.

    Match is on the dated header line this module posts itself:
        '<title> — <Month> <ordinal> <year>'
    read as a plain substring, so the bold '*…*' wrapper doesn't break it.
    Raises SlackPostError when today's header isn't in the channel yet, so the
    caller can post it (ensure_named_thread does exactly that).
    """
    channel_id = channel_id or CHANNEL_ID
    marker = f"{title} — {today.strftime('%B')} {_ordinal(today.day)} {today.year}"
    oldest = dt.datetime.combine(today, dt.time.min).timestamp()
    resp = client.conversations_history(channel=channel_id, oldest=str(oldest),
                                        limit=200)
    for msg in resp.get("messages", []):
        if marker in (msg.get("text", "") or ""):
            return msg.get("thread_ts") or msg.get("ts")
    raise SlackPostError(f"No '{marker}' header posted today.")


def ensure_named_thread(title: str, today: dt.date | None = None,
                        *, lines: list | None = None, dry_run: bool = False,
                        channel_id: str | None = None) -> dict:
    """Make sure today's parent post for a NAMED thread exists, and return its
    ts — the same 'post it if it isn't there' contract as
    ensure_metrics_thread, but for a thread that runs ALONGSIDE the Metrics
    one instead of inside it (Eve 2026-08-18: 'Knocks for other offices').

    `lines`: optional checklist body under the dated first line (e.g. one
    ':door: Owner Name' per office), so the thread says up front what should
    land in it.
    """
    today = today or dt.date.today()
    first = (f"*{title} — {today.strftime('%B')} {_ordinal(today.day)} "
             f"{today.year}*")
    header_text = "\n".join([first, "", *lines]) if lines else first
    channel_id = channel_id or CHANNEL_ID
    if dry_run:
        return {"dry_run": True, "header_text": header_text,
                "to_channel": channel_id,
                "mirrors_to": mirror_channels(channel_id)}
    client = _client()
    try:
        ts = find_named_thread_ts(client, title, today, channel_id=channel_id)
        out = {"ok": True, "existed": True, "thread_ts": ts}
    except SlackPostError:
        resp = client.chat_postMessage(channel=channel_id, text=header_text)
        out = {"ok": resp.get("ok"), "existed": False,
               "thread_ts": resp.get("ts"), "header_text": header_text}
    if out.get("thread_ts"):
        for dst in mirror_channels(channel_id):
            try:
                _mirror_thread_ts(client, channel_id, out["thread_ts"], dst, today)
            except Exception as e:      # noqa: BLE001
                print(f"  named-thread mirror to {dst} failed: "
                      f"{type(e).__name__}: {str(e)[:120]}")
    return out


def post_reply_text_only(
    text: str,
    *,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    thread_ts: str | None = None,
    channel_id: str | None = None,
) -> dict:
    """Reply in today's Metrics thread with just a text message (no file
    attachment). Used by reports where 'nothing new' = a one-liner instead
    of an empty-state image. Still adds the parent-thread reaction so the
    metric is marked done on the header."""
    today = today or dt.date.today()
    channel_id = channel_id or CHANNEL_ID
    if dry_run:
        return {"dry_run": True, "would_post_text": text,
                "to_channel": channel_id, "react_emoji": react_emoji,
                "mirrors_to": mirror_channels(channel_id)}
    client = _client()
    # thread_ts given => post into THAT thread (e.g. a named thread from
    # ensure_named_thread); omitted => today's 'Metrics for:' thread, unchanged.
    thread_ts = thread_ts or find_metrics_thread_ts(client, today)
    resp = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts,
                                    text=text)
    out = {"ok": resp.get("ok"), "thread_ts": thread_ts, "ts": resp.get("ts")}
    if react_emoji:
        try:
            r = client.reactions_add(channel=channel_id, timestamp=thread_ts,
                                     name=react_emoji)
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            out["reaction_warning"] = str(e)
    _mirror_reply(client, channel_id, thread_ts, today, out,
                  text=text, react_emoji=react_emoji)
    return out


# How long wait_visible waits for ONE image's share message to appear, and how
# often it looks. Generous enough for a slow render, short enough that a thread
# never stalls on it — past the cap we post the next image anyway.
_SHARE_WAIT_S = 20.0
_SHARE_POLL_S = 1.0


def _uploaded_file_id(resp) -> str:
    """The new file's id out of a files_upload_v2 response. The SDK returns
    {'files': [{...}]} for v2 and {'file': {...}} for the older shape — read both
    rather than trusting one, because getting it wrong here doesn't raise, it
    just silently turns wait_visible into a no-op."""
    try:
        files = resp.get("files") or []
        if files:
            first = files[0]
            # v2 nests one more level in some SDK versions: {'files':[{'files':[…]}]}
            inner = (first.get("files") or [None])[0] if isinstance(first, dict) else None
            return (inner or first).get("id") or ""
        return (resp.get("file") or {}).get("id") or ""
    except Exception:          # noqa: BLE001
        return ""


def wait_for_share(client, channel_id: str, thread_ts: str, file_id: str,
                   *, text: str = "", timeout_s: float = _SHARE_WAIT_S) -> bool:
    """Block until `file_id`'s message is actually IN the thread. True if it
    showed up, False on timeout (the caller posts the next one regardless — a
    tidier order is never worth a missing image).

    WHY (Eve 2026-08-19): files_upload_v2 returns when the UPLOAD finishes, but
    Slack posts the share message once it has finished PROCESSING the file — so
    several uploads fired back to back land in size order, not call order. In the
    'Knocks for other offices' thread that turned "Time Gaps + Knocks Sahil, then
    Time Gaps + Knocks Chan" (what Eve asked for on 8/18) into all the Time Gaps
    followed by all the Knocks: the small images overtook the big ones. It only
    showed up the first day both offices ran in ONE pass — before that they ran
    half an hour apart, which hid it.

    Matches on the file id, falling back to the initial comment `text` when the
    upload response didn't carry an id — without a fallback an unexpected
    response shape would quietly restore the old, wrong order.

    Never raises: a thread read that fails is treated as 'not visible yet'."""
    if not thread_ts or not (file_id or text):
        return False
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            resp = client.conversations_replies(channel=channel_id,
                                                ts=thread_ts, limit=200)
            for msg in resp.get("messages") or []:
                if file_id and any(f.get("id") == file_id
                                   for f in msg.get("files") or []):
                    return True
                if text and (msg.get("text") or "").strip() == text.strip():
                    return True
        except Exception:      # noqa: BLE001 — ordering is best-effort
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(_SHARE_POLL_S)


def post_reply_with_image(
    image_path: Path,
    *,
    comment: str,
    react_emoji: str | None = None,
    today: dt.date | None = None,
    dry_run: bool = False,
    file_name: str | None = None,
    thread_ts: str | None = None,
    channel_id: str | None = None,
    wait_visible: bool = False,
    top_level: bool = False,
) -> dict:
    """Reply in today's Metrics thread with an image attachment + optional
    reaction emoji on the parent.

    react_emoji: short name WITHOUT colons, e.g. 'arrows_counterclockwise',
    'negative_squared_cross_mark'.

    wait_visible (default False = unchanged for every existing caller): don't
    return until this image is visible in the thread, so a caller posting a
    SEQUENCE gets its own order instead of Slack's upload-processing order. See
    wait_for_share. Adds ~1-2s per image; use it only where the order carries
    meaning, i.e. images grouped by whose they are.
    """
    today = today or dt.date.today()
    channel_id = channel_id or CHANNEL_ID
    if dry_run:
        return {
            "dry_run": True,
            "would_post_image": str(image_path),
            "to_channel": channel_id,
            "comment": comment,
            "react_emoji": react_emoji,
            "mirrors_to": mirror_channels(channel_id),
            "top_level": top_level,
        }
    client = _client()
    # thread_ts given => post into THAT thread (e.g. a named thread from
    # ensure_named_thread); omitted => today's 'Metrics for:' thread, unchanged.
    # top_level => no thread at all: a plain channel post. Megan 2026-08-25 on
    # the knocks boards: "should NOT go in a thread but just be posted to the
    # channel so everyone can see it" — said of the 9 PM board and then of
    # Cody's 2 PM / 5:15 PM. Default False, so every other caller is unchanged.
    thread_ts = None if top_level else (thread_ts
                                        or find_metrics_thread_ts(client, today))
    upload_resp = client.files_upload_v2(
        channel=channel_id,
        thread_ts=thread_ts,
        file=str(image_path),
        filename=file_name or f"{comment} {today.month}.{today.day}.png",
        initial_comment=comment,
    )
    out = {
        "ok": upload_resp.get("ok"),
        "thread_ts": thread_ts,
        "file": _uploaded_file_id(upload_resp),
    }
    if wait_visible and out["ok"]:
        out["visible"] = wait_for_share(client, channel_id, thread_ts,
                                        out.get("file") or "", text=comment)
    if react_emoji and thread_ts:   # a top-level post has no ts to react to
        try:
            r = client.reactions_add(
                channel=channel_id, timestamp=thread_ts, name=react_emoji
            )
            out["reaction_ok"] = r.get("ok")
        except Exception as e:
            # Already-reacted is fine; surface other errors only.
            out["reaction_warning"] = str(e)
    _mirror_reply(client, channel_id, thread_ts, today, out,
                  file_path=image_path,
                  file_name=file_name or f"{comment} {today.month}.{today.day}.png",
                  comment=comment, react_emoji=react_emoji,
                  wait_visible=wait_visible, top_level=top_level)
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
            "mirrors_to": mirror_channels(CHANNEL_ID),
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
    _mirror_reply(client, CHANNEL_ID, thread_ts, today, out,
                  file_path=file_path, file_name=file_name or default_name,
                  comment=comment, react_emoji=react_emoji)
    return out
