"""Jiraiya — Socket Mode app: `/dd` opens a fill-in popup, hit Summon Jiraiya.

An always-on listener (Socket Mode, no inbound HTTP needed). On `/dd` it opens a
modal with ICD / Leader / Team fields; on submit it pulls the whole team from
Tableau and logs the 3-table block to that ICD's tab, then DMs the requester the
result. Uses the stdlib socket-mode backend — no extra dependency.

Tokens:
  * bot   (xoxb) — DD_BOT_TOKEN or ~/.config/recruiting-report/dd-bot-token
  * app   (xapp) — DD_APP_TOKEN or ~/.config/recruiting-report/dd-app-token
"""
from __future__ import annotations

import json
import os
import ssl
import threading
from pathlib import Path

from . import config as C
from . import fill as dd_fill

CALLBACK = "dd_form"
_CTX_PATH = C.OUTPUT_DIR / "bot_context.json"
# Trivial replies that should NOT trigger a re-pull.
_ACKS = {"thanks", "thank you", "ty", "thx", "ok", "okay", "cool", "nice",
         "great", "perfect", "👍", "🙏", "got it"}


def _load_ctx() -> dict:
    try:
        return json.loads(_CTX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ctx(user_id: str, icd: str, leader: str, names: list) -> None:
    d = _load_ctx()
    d[user_id] = {"icd": icd, "leader": leader, "names": names}
    C.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _CTX_PATH.write_text(json.dumps(d), encoding="utf-8")


def _app_token() -> str:
    tok = os.environ.get("DD_APP_TOKEN", "").strip()
    if not tok:
        f = Path.home() / ".config" / "recruiting-report" / "dd-app-token"
        if f.exists():
            tok = f.read_text(encoding="utf-8-sig").strip()
    if not tok:
        raise SystemExit("No app-level token — set DD_APP_TOKEN or save it to "
                         "~/.config/recruiting-report/dd-app-token (xapp-…).")
    return tok.lstrip("﻿")


def _web():
    from .watch import _client
    return _client()               # the Jiraiya bot (xoxb) web client


def _modal() -> dict:
    def _inp(bid, label, ph, multiline=False, optional=False):
        return {"type": "input", "block_id": bid, "optional": optional,
                "label": {"type": "plain_text", "text": label},
                "element": {"type": "plain_text_input", "action_id": "v",
                            "multiline": multiline,
                            "placeholder": {"type": "plain_text", "text": ph}}}
    return {
        "type": "modal", "callback_id": CALLBACK,
        "title": {"type": "plain_text", "text": "Jiraiya"},
        "submit": {"type": "plain_text", "text": "Summon Jiraiya"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": ":scroll: I'll pull the team's last 8 weeks of fiber, "
                     "wireless, cancel & churn and log it to the ICD's tab."}},
            _inp("icd", "ICD", "Kakashi Hatake"),
            _inp("leader", "Leader", "Might Guy", optional=True),
            _inp("team", "Team (one rep per line)",
                 "Naruto Uzumaki\nSasuke Uchiha\nSakura Haruno", multiline=True),
        ],
    }


def _process(web, user_id: str, icd: str, leader: str, names: list,
             thread_ts: str = None) -> None:
    """Runs in a background thread (the pull takes minutes; the modal was already
    ack'd). DMs the requester progress + the result. `thread_ts` threads the reply
    under an existing message (used when re-pulling from a corrected-name reply)."""
    from .pull import gather_team
    link = f"https://docs.google.com/spreadsheets/d/{C.DD_SHEET_ID}/edit"
    # files_upload_v2 needs the DM *channel* id (not the user id), so open it once.
    try:
        chan = web.conversations_open(users=user_id)["channel"]["id"]
    except Exception:
        chan = user_id
    _kw = {"thread_ts": thread_ts} if thread_ts else {}
    try:
        # Fast when today's 3am harvest cache is warm; a live 8-week pull otherwise.
        from .pull import _cache_dir, _cache_complete, recent_sundays
        warm = _cache_complete(_cache_dir(), recent_sundays(C.WEEKS))
        est = "about *30 seconds*" if warm else "*a few minutes* (pulling 8 weeks live)"
        web.chat_postMessage(channel=chan, **_kw, text=(
            f":frog: On it — pulling *{icd}*. This takes {est}; I'll send back an "
            f"image of the 3 charts and log them to the sheet."))
        people, misses = gather_team(names, icd=icd)
        if not people:
            web.chat_postMessage(channel=chan, **_kw, text=(
                f":warning: Couldn't find any of those reps under *{icd}*: "
                f"{', '.join(names)}. Check the spelling and try `/dd` again."))
            return
        from . import team_render
        res = team_render.write_and_render(people, icd=icd, leader=leader)
        tab_link = f"{link}#gid={res['gid']}"
        cap = (f":scroll: *Due Diligence — {res['tab']}*  ({len(people)} rep"
               f"{'s' if len(people) != 1 else ''}) — logged to the "
               f"<{tab_link}|{res['tab']} tab>.")
        if misses:
            cap += (f"\n:warning: Couldn't match: *{', '.join(misses)}* — reply in "
                    f"this thread with the correct spelling and I'll re-pull the "
                    f"whole team's numbers for you.")
        # A source that came back without its per-rep breakout empties a whole
        # column for EVERYONE. That used to be silent, so say it once, up front.
        broken = sorted({g for p in people for g in p.gaps
                         if "WITHOUT a 'Rep Name' column" in g})
        if broken:
            cap += ("\n:rotating_light: A source view is collapsed, so those "
                    "columns are blank for every rep:\n" +
                    "\n".join(f"• {g}" for g in broken))
        web.files_upload_v2(channel=chan, **_kw, file=str(res["png"]),
                            filename=f"{icd} Due Diligence.png", initial_comment=cap)
        # Remember this request so a thread reply (a corrected name) can re-pull
        # without re-entering the team. Store only the MATCHED reps so misses
        # don't pile up on the running list.
        _save_ctx(user_id, icd, leader, [p.matched_rep for p in people])
    except Exception as e:                       # noqa: BLE001 — never crash the listener
        try:
            web.chat_postMessage(channel=chan, **_kw,
                                 text=f":x: Jiraiya hit an error: {type(e).__name__}: {str(e)[:200]}")
        except Exception:
            pass


def _handler(client, req):
    from slack_sdk.socket_mode.response import SocketModeResponse
    print(f"[req] type={req.type} cmd={req.payload.get('command')} "
          f"ptype={req.payload.get('type')}", flush=True)
    if req.type == "slash_commands" and req.payload.get("command") == "/dd":
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        try:
            r = client.web_client.views_open(trigger_id=req.payload["trigger_id"], view=_modal())
            print(f"[modal] opened ok={r.get('ok')}", flush=True)
        except Exception as e:                # noqa: BLE001
            print(f"[modal] FAILED {type(e).__name__}: {e}", flush=True)
        return
    if req.type == "events_api":
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        ev = req.payload.get("event", {})
        print(f"[event] etype={ev.get('type')} ch={ev.get('channel_type')} "
              f"sub={ev.get('subtype')} bot={bool(ev.get('bot_id'))} "
              f"user={ev.get('user')} text={(ev.get('text') or '')[:40]!r}", flush=True)
        if (ev.get("type") == "message" and ev.get("channel_type") == "im"
                and not ev.get("bot_id") and not ev.get("subtype")):
            user = ev.get("user")
            text = (ev.get("text") or "").strip()
            ctx = _load_ctx().get(user or "")
            print(f"[event] ctx_found={bool(ctx)} is_ack={text.lower() in _ACKS}", flush=True)
            # Only re-pull when the user has a recent request AND the reply looks
            # like a name (not a "thanks"). Adds the corrected name(s) and re-runs.
            if ctx and text and text.lower() not in _ACKS:
                new_names = list(dict.fromkeys(
                    ctx["names"] + [l.strip() for l in text.splitlines() if l.strip()]))
                tts = ev.get("thread_ts") or ev.get("ts")   # reply in the thread
                threading.Thread(
                    target=_process,
                    args=(client.web_client, user, ctx["icd"], ctx["leader"], new_names, tts),
                    daemon=True).start()
        return
    # Promotion Check-In "Remove a mistake" modal submit.
    if req.type == "interactive" and req.payload.get("type") == "view_submission" \
            and req.payload.get("view", {}).get("callback_id") == "promo_remove_modal":
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        try:
            from automations.promotion_checkin import handler as promo
            threading.Thread(target=promo.handle_remove_submission,
                             args=(client.web_client, req.payload), daemon=True).start()
        except Exception as e:                # noqa: BLE001 — never crash the listener
            print(f"[promo] remove dispatch failed {type(e).__name__}: {e}", flush=True)
        return
    if req.type == "interactive" and req.payload.get("type") == "view_submission" \
            and req.payload.get("view", {}).get("callback_id") == CALLBACK:
        vals = req.payload["view"]["state"]["values"]
        def g(bid):
            return (vals.get(bid, {}).get("v", {}).get("value") or "").strip()
        icd, leader, team_raw = g("icd"), g("leader"), g("team")
        names = ([leader] if leader else []) + [l.strip() for l in team_raw.splitlines() if l.strip()]
        names = list(dict.fromkeys(names))       # dedup, keep order
        user_id = req.payload["user"]["id"]
        # Close the modal immediately (must ack < 3s); process in the background.
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        threading.Thread(target=_process, args=(client.web_client, user_id, icd, leader, names),
                         daemon=True).start()
        return
    # Promotion Check-In buttons (a separate feature riding the same Jiraiya app).
    if req.type == "interactive" and req.payload.get("type") == "block_actions":
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        try:
            from automations.promotion_checkin import handler as promo
            if promo.is_promo_action(req.payload):
                threading.Thread(target=promo.handle_action,
                                 args=(client.web_client, req.payload),
                                 daemon=True).start()
        except Exception as e:                # noqa: BLE001 — never crash the listener
            print(f"[promo] dispatch failed {type(e).__name__}: {e}", flush=True)
        return
    # ack anything else so Slack doesn't retry
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))


def run() -> None:
    from slack_sdk.socket_mode.builtin import SocketModeClient
    web = _web()
    client = SocketModeClient(app_token=_app_token(), web_client=web)
    client.socket_mode_request_listeners.append(_handler)
    print("Jiraiya Socket Mode listener connecting…")
    client.connect()
    print("connected — /dd is live. Ctrl-C to stop.")
    threading.Event().wait()


if __name__ == "__main__":
    run()
