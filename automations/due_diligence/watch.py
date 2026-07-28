"""Answer Due Diligence requests that leaders DM to the bot.

Raf (and anyone on the DD_DM_USERS allowlist) DMs the bot an ICD + rep; this
polls each allowed user's DM (conversations_history — the same pattern every
other 'read Slack' report uses, since there's no inbound listener infra),
assembles the rep's DD numbers, replies in the DM, and logs the block to that
ICD's tab (creating the tab if it's new).

Idempotent: the newest handled ts is persisted PER DM, and each handled message
gets a ✅, so a re-run never double-answers. Designed to run on a short launchd
interval (poll_once) rather than as a long-lived process; --loop is for local
testing.

SAFE BY DEFAULT: without --live it prints replies instead of DMing, and without
--write it never touches the Sheet.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional

from . import config as C
from . import format_slack
from .pull import gather_rep_dd
from . import fill as dd_fill

_MENTION = re.compile(r"<@[^>]+>")
_LINK = re.compile(r"<[^>|]+(?:\|[^>]*)?>")
_KEYWORD = re.compile(r"^\s*(dd|due[\s-]?diligence)\b[:,\s]*", re.I)
_LABEL_ICD = re.compile(r"\bicd\b\s*[:\-]?\s*(.+?)(?=\brep\b|\n|$)", re.I | re.S)
_LABEL_REP = re.compile(r"\brep\b\s*[:\-]?\s*(.+?)(?=\bicd\b|\n|$)", re.I | re.S)
_SPLIT = re.compile(r"\s*[/|]\s*|\s+[-–—]\s+|\n+|\s*,\s*")


# --------------------------------------------------------------------------
def _load_state() -> dict:
    try:
        return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def extract_request(text: str) -> tuple:
    """Parse an (ICD, rep) request. Accepts labelled ('ICD: … Rep: …') or a
    separated pair ('Alex Touati / Adalberto Celaya', '… - …', '… , …', or two
    lines). A lone token is treated as the rep with the ICD unknown."""
    t = _MENTION.sub("", text or "")
    t = _LINK.sub("", t)
    t = _KEYWORD.sub("", t).strip()
    mi, mr = _LABEL_ICD.search(t), _LABEL_REP.search(t)
    if mi or mr:
        return (mi.group(1).strip() if mi else "",
                mr.group(1).strip() if mr else "")
    parts = [p.strip() for p in _SPLIT.split(t, maxsplit=1) if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return ("", parts[0] if parts else "")


FORM_TEMPLATE = (
    ":scroll: *Team Due Diligence* — copy this, fill it in, and send it back:\n"
    "```\nICD: \nLeader: \nTeam:\n(one rep per line)\n```\n"
    "_Or for a single rep: `Alex Touati / Adalberto Celaya`._"
)


def extract_team_request(text: str) -> tuple:
    """Parse a filled team form -> (icd, leader, [reps]). Reps come from the
    lines under a 'Team:' heading. Blank/hint lines are skipped."""
    t = _MENTION.sub("", text or "")
    t = _LINK.sub("", t)
    icd = leader = ""
    reps, in_team = [], False
    for raw in t.splitlines():
        l = raw.strip()
        low = l.lower()
        if low.startswith("icd"):
            icd = l.split(":", 1)[1].strip() if ":" in l else l[3:].strip()
            in_team = False
        elif low.startswith("leader"):
            leader = l.split(":", 1)[1].strip() if ":" in l else l[6:].strip()
            in_team = False
        elif low.startswith("team"):
            in_team = True
            after = l.split(":", 1)[1].strip() if ":" in l else ""
            if after:
                reps.append(after)
        elif in_team and l and not l.startswith("("):
            reps.append(l)
    return icd, leader, reps


def _client():
    # DMs (read + reply) run on the 'Jiraiya' bot token so the conversation is
    # with the bot Raf DMs. Set DD_BOT_TOKEN to Jiraiya's own app token; unset
    # falls back to the Lucy bot token. Scopes: im:history, chat:write, im:write,
    # users:read (name resolve), reactions:write (optional ✅).
    import ssl
    from pathlib import Path
    tok = os.environ.get("DD_BOT_TOKEN", "").strip()
    if not tok:
        # File fallback (same convention as the other bots) so the token never
        # has to be pasted into chat / the plist.
        tf = Path.home() / ".config" / "recruiting-report" / "dd-bot-token"
        if tf.exists():
            tok = tf.read_text(encoding="utf-8-sig").strip()
    if tok:
        import certifi
        from slack_sdk import WebClient
        ctx = ssl.create_default_context(cafile=certifi.where())
        return WebClient(token=tok.lstrip("﻿"), ssl=ctx)
    from automations.shared.slack_metrics_post import _bot_client
    return _bot_client()


def _dm_channels(client) -> List[dict]:
    """Resolve each allowlisted user to their DM (im) channel with the bot.
    Returns [{'user': id, 'im': channel_id}]. conversations_open both creates
    (first time) and fetches the existing DM, so no im:read/list scope needed."""
    from automations.shared.slack_metrics_post import _resolve_user_id
    out = []
    for who in C.DD_DM_USERS:
        try:
            uid = _resolve_user_id(client, who)
            im = client.conversations_open(users=uid)["channel"]["id"]
            out.append({"user": uid, "im": im, "who": who})
        except Exception as e:      # noqa: BLE001
            print(f"  can't open DM for {who!r}: {type(e).__name__}: {e}")
    return out


# --------------------------------------------------------------------------
def _pending_messages(client, channel: str, last_ts: str) -> List[dict]:
    """Top-level human messages newer than last_ts, oldest-first."""
    kwargs = {"channel": channel, "limit": 50}
    if last_ts:
        kwargs["oldest"] = last_ts
    resp = client.conversations_history(**kwargs)
    msgs = []
    for m in resp.get("messages", []):
        if m.get("subtype") or m.get("bot_id"):
            continue                      # joins, our own bot posts, etc.
        if m.get("thread_ts") and m.get("thread_ts") != m.get("ts"):
            continue                      # a reply inside a thread, not a request
        if m.get("ts") == last_ts:
            continue                      # oldest is inclusive — skip the boundary
        msgs.append(m)
    msgs.sort(key=lambda m: float(m["ts"]))
    return msgs


def _react(client, channel: str, ts: str, name: str, add: bool = True) -> None:
    try:
        if add:
            client.reactions_add(channel=channel, timestamp=ts, name=name)
        else:
            client.reactions_remove(channel=channel, timestamp=ts, name=name)
    except Exception:
        pass                              # already-reacted / already-gone is fine


def _parse_dd_request(text: str) -> tuple:
    """(icd, leader, [names]) from either the team form or a single 'ICD / rep'."""
    icd, leader, reps = extract_team_request(text)
    names = []
    for n in ([leader] + reps if leader else reps):
        if n and n not in names:
            names.append(n)
    if not (icd and names):
        i2, r2 = extract_request(text)     # single 'ICD / rep' fallback
        if i2 and r2:
            icd, leader, names = i2, "", [r2]
    return icd, leader, names


def handle_message(msg: dict, *, client, channel: str, post: bool,
                   write_sheet: bool, page=None, verbose: bool = False) -> dict:
    """Assemble + answer one request (a team, or a single rep). Returns a dict."""
    from .pull import gather_team
    ts = msg["ts"]
    icd, leader, names = _parse_dd_request(msg.get("text", ""))
    if not (icd and names):
        _post(client, channel, ts, FORM_TEMPLATE, post)
        return {"ts": ts, "skipped": "need ICD + team"}

    if post:
        _react(client, channel, ts, C.WORKING_REACTION, add=True)

    people, misses = gather_team(names, icd=icd, page=page, verbose=verbose)
    link = f"https://docs.google.com/spreadsheets/d/{C.DD_SHEET_ID}/edit"
    if not people:
        reply = (f":warning: Couldn't find any of those reps under *{icd}*: "
                 f"{', '.join(names)}. Check the spelling and resend.")
    else:
        res = dd_fill.write_team_block(people, icd=icd, leader=leader,
                                       dry_run=not write_sheet)
        head = f":scroll: *Due Diligence — {icd}*  ({len(people)} rep{'s' if len(people)!=1 else ''})"
        lines = [head]
        for p in people:
            lines.append(f"• {p.matched_rep} — fiber 8wk *{p.new_int.avg_8wk}* · "
                         f"wireless 8wk *{p.wireless.avg_8wk}*")
        if res.get("wrote"):
            newtab = " (new tab)" if res.get("created_tab") else ""
            lines.append(f":pencil2: Logged to the *{res.get('tab')}* tab{newtab} — <{link}|open sheet>.")
        elif res.get("error"):
            lines.append(f":warning: Not logged: {res['error']}.")
        else:
            lines.append(f":eyes: Preview only — would log to *{icd}* (<{link}|sheet> not modified).")
        if misses:
            lines.append(f":warning: Couldn't match (check spelling): {', '.join(misses)}")
        reply = "\n".join(lines)

    _post(client, channel, ts, reply, post)
    if post:
        _react(client, channel, ts, C.WORKING_REACTION, add=False)
        _react(client, channel, ts, C.DONE_REACTION, add=True)
    return {"ts": ts, "icd": icd, "found": len(people), "misses": misses,
            "posted": post, "wrote_sheet": bool(write_sheet and people)}


def _post(client, channel: str, thread_ts: str, text: str, post: bool) -> None:
    if not post:
        print(f"\n----- reply for thread {thread_ts} (NOT posted) -----\n{text}\n")
        return
    client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)


# --------------------------------------------------------------------------
def poll_once(*, post: bool = False, write_sheet: bool = False,
              verbose: bool = False) -> dict:
    """One poll: for each allowed DM, handle every request newer than that DM's
    saved cursor. Opens the Tableau session only if something is pending."""
    if not C.DD_DM_USERS:
        raise SystemExit("DD_DM_USERS is not set — list who the bot answers "
                         "(env DD_DM_USERS, e.g. Raf's id) before running.")
    client = _client()
    state = _load_state()
    cursors = state.setdefault("ims", {})       # {im_id: last_ts}

    # Collect pending requests across every allowed DM first (cheap), so we open
    # at most ONE Tableau session for the whole batch.
    pending = []                                 # [(im_id, msg)]
    for dm in _dm_channels(client):
        im = dm["im"]
        for m in _pending_messages(client, im, cursors.get(im, "")):
            pending.append((im, m))
    if not pending:
        return {"handled": 0}

    results = []
    page_cm = None
    page = None
    try:
        # A human's Chrome (on the mini) collides with the browser reports; guard
        # only when there's actually a request to serve. Opt-in via
        # DD_CHROME_GUARD (the deploy wrapper sets it; local runs leave it off).
        if os.environ.get("DD_CHROME_GUARD", "").strip() in ("1", "on", "true"):
            try:
                from automations.day_orchestrator import chrome_guard
                chrome_guard.close_stray_chrome(verbose=False)
            except Exception as e:      # noqa: BLE001 — best-effort
                print(f"  chrome guard skipped: {type(e).__name__}: {e}")
        from automations.shared.tableau_patchright import tableau_session
        page_cm = tableau_session(headless=True, verbose=verbose)
        page = page_cm.__enter__()
        for im, m in pending:
            try:
                results.append(handle_message(
                    m, client=client, channel=im, post=post,
                    write_sheet=write_sheet, page=page, verbose=verbose))
                cursors[im] = m["ts"]
                _save_state(state)        # checkpoint after each so a crash
                                          # mid-batch never re-answers a request
            except Exception as e:        # noqa: BLE001
                print(f"  request {m.get('ts')} failed: {type(e).__name__}: {e}")
    finally:
        if page_cm is not None:
            try:
                page_cm.__exit__(None, None, None)
            except Exception:
                pass
    return {"handled": len(results), "results": results}


def watch_loop(interval_s: int = 60, **kw) -> None:
    """Local-testing loop. On the mini this runs via a launchd StartInterval
    calling poll_once instead."""
    print(f"Watching DMs from {C.DD_DM_USERS} every {interval_s}s "
          f"(post={kw.get('post')}, write={kw.get('write_sheet')}). Ctrl-C to stop.")
    while True:
        try:
            out = poll_once(**kw)
            if out.get("handled"):
                print(f"handled {out['handled']} request(s)")
        except Exception as e:            # noqa: BLE001
            print(f"poll error: {type(e).__name__}: {e}")
        time.sleep(interval_s)
